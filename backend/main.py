"""
FastAPI app with SSE streaming search endpoint.

POST /search  →  text/event-stream

SSE events (each is a JSON object on a `data:` line, double-newline terminated):
  { "type": "queued",  "position": N }     ← 1-based place in the elevation-fetch
                                             line; repeats as the line advances.
                                             Only cold (uncached) searches see it.
  { "type": "busy",    "message": "..." }  ← the queue is full; request shed
                                             before any work. Stream ends here.
  { "type": "status",  "message": "..." }
  { "type": "route",   "route_id": ..., "geometry": {...}, "metadata": {...},
                       "flow_score": ..., "flow_grade": ..., "surface_pcts": {...},
                       "speed_profile": [...], "top_speed_kmh": ..., "avg_speed_kmh": ... }
                       ← physics is emitted inline with the route, not as a
                         separate event
  { "type": "error",   "message": "..." }   ← fatal; stream ends here, no done
  { "type": "done" }                        ← always last on success
"""

import asyncio
import json
import logging
import os
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any, AsyncGenerator

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hillbomb.pipeline")

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from .config import DEFAULT_ROAD_TYPES, RIDER_PROFILES, SearchConfig, Toggles
from .elevation import ElevationService, SearchCancelled
from .gate import RequestGate
from .graph import build_graph
from .overpass import fetch_osm_data
from .pathfinding import find_routes
from .pipeline import RouteFinalizer, mark_traversable, route_payload, traversable_node_ids


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.elevation = ElevationService()
    # Caps concurrent cold elevation fetches; the rest queue (see gate.py).
    # 2 keeps us within Overpass/S3 etiquette and bounds bandwidth + memory.
    # Beyond max_waiting queued, new cold searches are shed with a "busy" event
    # instead of growing the backlog unbounded.
    app.state.gate = RequestGate(
        max_concurrent=int(os.environ.get("HILLBOMB_MAX_CONCURRENT_ELEVATION", "2")),
        max_waiting=int(os.environ.get("HILLBOMB_MAX_QUEUE", "20")),
    )
    yield


app = FastAPI(title="Hillbomb API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["POST", "GET", "OPTIONS"],
    allow_headers=["*"],
)


# ── Request model ─────────────────────────────────────────────────────────────

class TogglesRequest(BaseModel):
    avoid_stoplights: bool = True
    avoid_stop_signs: bool = True
    avoid_bigger_roads: bool = True
    avoid_equal_roads: bool = False
    exclude_tunnels: bool = False
    exclude_bridges: bool = False
    stay_on_initial_road: bool = False
    animate_candidates: bool = False


class SearchRequest(BaseModel):
    bbox: tuple[float, float, float, float]  # south, west, north, east
    road_types: list[str] | None = None      # defaults to DEFAULT_ROAD_TYPES
    rider_profile: str = "cyclist_upright"
    toggles: TogglesRequest = TogglesRequest()
    max_routes: int = 500
    max_road_rank: int = 6                   # cap by HIGHWAY_RANK; 6 = secondary (UI slider default), 9 = all roads
    allowed_surface_categories: list[str] | None = None  # None = all surfaces allowed
    crr_pathfinding: float | None = None     # overrides profile default when set

    @field_validator("bbox")
    @classmethod
    def bbox_must_be_valid(cls, v: tuple) -> tuple:
        south, west, north, east = v
        if not (-90 <= south < north <= 90):
            raise ValueError("bbox: south must be < north and within [-90, 90]")
        if not (-180 <= west < east <= 180):
            raise ValueError("bbox: west must be < east and within [-180, 180]")
        return v


# ── SSE helpers ───────────────────────────────────────────────────────────────

def _sse(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload)}\n\n"


def _route_event(route) -> str:
    # Shape lives in pipeline.route_payload so the collections builder emits the
    # identical thing; this only adds the SSE discriminator.
    return _sse({"type": "route", **route_payload(route)})


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _pipeline(req: SearchRequest, elevation_svc: ElevationService, gate: RequestGate, request: Request) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()

    road_types = set(req.road_types) if req.road_types else DEFAULT_ROAD_TYPES
    params = RIDER_PROFILES[req.rider_profile]
    if req.crr_pathfinding is not None:
        params = replace(params, crr_pathfinding=req.crr_pathfinding)
    config = SearchConfig(max_routes=req.max_routes)
    # TogglesRequest mirrors the Toggles dataclass field-for-field.
    toggles = Toggles(**req.toggles.model_dump())

    # Cancellation is shared across stages via a threading.Event so it can be read
    # from executor threads (elevation, pathfinding) as well as the event loop.
    # A background watcher polls is_disconnected() and trips the event; because it
    # runs as its own task, it keeps firing even while an executor stage blocks.
    cancel_event = threading.Event()

    async def _watch_disconnect() -> None:
        try:
            while not cancel_event.is_set():
                if await request.is_disconnected():
                    cancel_event.set()
                    return
                await asyncio.sleep(0.15)
        except asyncio.CancelledError:
            pass

    watcher = asyncio.ensure_future(_watch_disconnect())

    # Only the watcher polls request.is_disconnected(); is_done() just reads the
    # event it trips. Polling from two coroutines would race on the ASGI receive
    # channel. Worst-case detection latency is the watcher's 0.15s poll interval.
    async def is_done() -> bool:
        return cancel_event.is_set()

    # Per-stage wall-clock timing. Logged at INFO so slow stages are visible in
    # server logs; the final summary line makes it obvious where time actually goes.
    timings: dict[str, float] = {}

    producer: asyncio.Future | None = None
    try:
        yield _sse({"type": "status", "message": "Querying Overpass API..."})
        t0 = time.perf_counter()
        nodes, ways = await loop.run_in_executor(
            None, fetch_osm_data, req.bbox
        )
        timings["overpass"] = time.perf_counter() - t0
        log.info("stage overpass: %.0f ms (%d nodes, %d ways)",
                 timings["overpass"] * 1000, len(nodes), len(ways))
        if await is_done():
            return

        # Decide traversability per way. Bigger roads (and surface/rank-excluded
        # ways) stay in the graph so the avoid-bigger/equal-roads toggles can stop
        # a descent at them, but are tagged non-traversable so they're never ridden.
        mark_traversable(
            ways,
            road_types=road_types,
            max_road_rank=req.max_road_rank,
            allowed_surface_categories=(
                set(req.allowed_surface_categories)
                if req.allowed_surface_categories is not None
                else None
            ),
        )

        used_ids = {nid for w in ways for nid in w.node_ids}
        active_nodes = {nid: n for nid, n in nodes.items() if nid in used_ids}

        # Elevation is only needed for nodes we might actually ride — i.e. nodes
        # on at least one traversable way. Non-traversable ways (bigger roads,
        # surface/rank-excluded) are kept in the graph for crossing detection,
        # which uses only road rank + way name, never elevation. So we query
        # elevation for the traversable subset and leave the rest at 0.0.
        # The cache file is still keyed on the FULL network geometry (used_ids,
        # which is toggle-independent), so re-searching the same area with
        # different surface/road filters reuses every coordinate already fetched.
        traversable_ids = traversable_node_ids(ways)
        needed_nodes = {nid: n for nid, n in active_nodes.items() if nid in traversable_ids}

        coords = [(n.lon, n.lat) for n in needed_nodes.values()]
        cache_coords = [(n.lon, n.lat) for n in active_nodes.values()]

        # Elevation is the pipeline's slowest stage and the one that overwhelms
        # the box under concurrent load, so cold fetches pass through an admission
        # gate. A warm search (nothing missing from cache) skips the gate entirely
        # and stays instant even while cold fetches are queued behind it.
        ticket = None
        if elevation_svc.missing_coords(coords, cache_coords):
            ticket = gate.enqueue()
            if ticket is None:
                # Line is full — shed rather than pile on. Client can retry.
                yield _sse({"type": "busy",
                            "message": "Server is at capacity right now. "
                                       "Please try your search again in a moment."})
                return
        try:
            if ticket is not None:
                async for position in gate.wait(ticket, is_done):
                    yield _sse({"type": "queued", "position": position})
                if await is_done():
                    return

            yield _sse({"type": "status",
                        "message": f"Fetching elevation for {len(needed_nodes)} nodes..."})
            t0 = time.perf_counter()
            elevs = await loop.run_in_executor(
                None,
                lambda: elevation_svc.get_elevations(
                    coords, cancel_event.is_set, cache_coords
                ),
            )
            timings["elevation"] = time.perf_counter() - t0
        finally:
            # Release the slot (or drop from the line if we never got one) so the
            # next queued search starts its fetch while we move on to the CPU stages.
            if ticket is not None:
                gate.release(ticket)
        log.info("stage elevation: %.0f ms (%d of %d nodes, res=%sm)",
                 timings["elevation"] * 1000, len(coords), len(active_nodes),
                 elevation_svc.resolution_m)
        if await is_done():
            return
        for node, elev in zip(needed_nodes.values(), elevs):
            node.elevation = elev
        config.elevation_sample_interval_m = elevation_svc.resolution_m

        yield _sse({"type": "status", "message": "Building route graph..."})
        t0 = time.perf_counter()
        G = build_graph(nodes, ways, config)
        timings["graph"] = time.perf_counter() - t0
        log.info("stage graph: %.0f ms (%d graph nodes)", timings["graph"] * 1000, G.number_of_nodes())
        if await is_done():
            return

        yield _sse({"type": "status", "message": "Searching for hill bombs..."})
        t0 = time.perf_counter()
        finalizer = RouteFinalizer(G, nodes, config, params)

        # find_routes is a CPU-bound generator. Run it on an executor thread and
        # feed finalized routes through a queue so the event loop stays free to run
        # the disconnect watcher — otherwise a long stretch between yields would
        # block cancellation. cancel_event stops find_routes from inside its loop.
        route_q: asyncio.Queue = asyncio.Queue()
        _SENTINEL = object()

        def _produce_routes() -> None:
            try:
                for r in find_routes(G, nodes, config, params, toggles,
                                     should_cancel=cancel_event.is_set):
                    loop.call_soon_threadsafe(route_q.put_nowait, r)
            except Exception as exc:  # surface to the consumer to handle/emit
                loop.call_soon_threadsafe(route_q.put_nowait, exc)
            finally:
                loop.call_soon_threadsafe(route_q.put_nowait, _SENTINEL)

        producer = loop.run_in_executor(None, _produce_routes)

        while True:
            raw_route = await route_q.get()
            if raw_route is _SENTINEL:
                break
            if isinstance(raw_route, BaseException):
                raise raw_route
            if await is_done():
                return

            for route in finalizer.finalize(raw_route):
                yield _route_event(route)

        timings["pathfinding"] = time.perf_counter() - t0
        log.info("stage pathfinding+emit: %.0f ms", timings["pathfinding"] * 1000)
        log.info(
            "pipeline summary: %s | total %.0f ms",
            " ".join(f"{k}={v * 1000:.0f}ms" for k, v in timings.items()),
            sum(timings.values()) * 1000,
        )

        yield _sse({"type": "done"})

    except (BrokenPipeError, ConnectionResetError, SearchCancelled):
        return  # client closed the connection; normal early exit
    except Exception as exc:
        yield _sse({"type": "error", "message": str(exc)})
    finally:
        # Stop any still-running search and the watcher, and let the producer
        # thread unwind (cancel_event makes find_routes return promptly).
        cancel_event.set()
        watcher.cancel()
        if producer is not None:
            try:
                await producer
            except Exception:
                pass


# ── Endpoint ──────────────────────────────────────────────────────────────────

# ── Collections ───────────────────────────────────────────────────────────────
#
# Curated famous descents, precomputed offline by scripts/build_collections.py. No
# pipeline work happens at request time — roads don't move, so we build once and
# commit the result. Routes here are the same shape as /search routes (both come from
# pipeline.route_payload), so the frontend renders them with the same components.
#
# The payload is split across two endpoints because a single spot's routes are ~65 KB
# of geometry/elevation/speed samples: the index (no geometry) stays small enough to
# load on tab open, and the heavy part is fetched only for the spot the user picks.

COLLECTIONS_PATH = Path(__file__).resolve().parent / "data" / "collections.json"

# Parsed collections.json, invalidated on mtime change so a rebuild is picked up
# without restarting the dev server.
_collections_cache: tuple[float, dict] | None = None


def _load_collections() -> dict:
    """Parse collections.json, caching on mtime.

    An un-built checkout is a normal state, not a server fault — it reads as an empty
    collection so the tab shows its empty state rather than an error.
    """
    global _collections_cache
    if not COLLECTIONS_PATH.exists():
        return {"version": 1, "cities": []}

    mtime = COLLECTIONS_PATH.stat().st_mtime
    if _collections_cache is not None and _collections_cache[0] == mtime:
        return _collections_cache[1]

    try:
        doc = json.loads(COLLECTIONS_PATH.read_text())
    except json.JSONDecodeError as exc:
        raise HTTPException(
            status_code=500,
            detail=f"collections.json is corrupt: {exc}. Rebuild with "
                   f"`python -m backend.scripts.build_collections --clean`.",
        )
    _collections_cache = (mtime, doc)
    return doc


def _spot_summary(entry: dict) -> dict:
    """Index-card view of a spot: metadata plus headline stats, minus all geometry."""
    routes = entry.get("routes", [])
    best = routes[0] if routes else None
    return {
        "slug": entry["slug"],
        "name": entry["name"],
        "state": entry["state"],
        "blurb": entry["blurb"],
        "discipline": entry["discipline"],
        "notes": entry["notes"],
        "center": entry["center"],
        "bbox": entry["bbox"],
        "route_count": len(routes),
        # Headline stats come from the best route (the builder sorts best-first).
        "length_m": best["metadata"]["length_m"] if best else 0,
        "total_descent_m": best["metadata"]["total_descent_m"] if best else 0,
        "avg_grade_pct": best["metadata"]["avg_grade_pct"] if best else 0,
        "top_speed_kmh": best["top_speed_kmh"] if best else 0,
        "flow_grade": best["flow_grade"] if best else "",
    }


@app.get("/collections")
async def collections():
    """Index of curated spots by city — metadata and headline stats, no route geometry.

    Deliberately light. Fetch /collections/{slug} for a spot's actual routes.
    """
    doc = _load_collections()
    return {
        "version": doc.get("version", 1),
        "cities": [
            {"city": c["city"], "spots": [_spot_summary(s) for s in c.get("spots", [])]}
            for c in doc.get("cities", [])
        ],
    }


@app.get("/collections/{slug}")
async def collection_spot(slug: str):
    """One curated spot, with its full routes."""
    doc = _load_collections()
    for city in doc.get("cities", []):
        for entry in city.get("spots", []):
            if entry["slug"] == slug:
                return entry
    raise HTTPException(status_code=404, detail=f"Unknown collection spot '{slug}'")


@app.post("/search")
async def search(req: SearchRequest, request: Request):
    if req.rider_profile not in RIDER_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown rider_profile '{req.rider_profile}'. "
                   f"Valid options: {list(RIDER_PROFILES)}",
        )
    return StreamingResponse(
        _pipeline(req, request.app.state.elevation, request.app.state.gate, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",     # disable nginx buffering
            "Connection": "keep-alive",
        },
    )
