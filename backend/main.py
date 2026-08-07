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

from .config import (
    DEFAULT_ROAD_TYPES,
    MAX_TRAIL_DIFFICULTY,
    RIDER_PROFILES,
    SearchConfig,
    Toggles,
)
from .elevation import ElevationService, SearchCancelled
from .gate import RequestGate
from .graph import build_graph
from .osmsource import describe_source, fetch_osm_data
from .pathfinding import find_routes
from .pipeline import (
    RouteFinalizer,
    collections_index,
    mark_traversable,
    route_payload,
    traversable_node_ids,
)


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

# In production the SPA and the collections JSON are served from a CDN, on a different
# origin than this API, so POST /search is the one cross-origin request the app makes
# and it needs CORS to work at all (a JSON body makes it non-simple, so it costs a
# preflight OPTIONS — hence OPTIONS below). Set HILLBOMB_ALLOWED_ORIGINS to the site's
# real origin there; see docs/deploy.md.
#
# The "*" default is for every other environment — dev, tests, `docker run` — where the
# app and the API share an origin and CORS never comes into play. Note we send no
# credentials, so "*" is a legal value; adding cookies or auth later would make it
# illegal and force an explicit list.
_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.environ.get("HILLBOMB_ALLOWED_ORIGINS", "*").split(",")
    if o.strip()
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
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
    # Cap on 0-6 mtb:scale; None = any. Untagged ways are always allowed, so this
    # narrows a trail search rather than guaranteeing a road one stays off singletrack.
    # See pipeline.mark_traversable.
    max_trail_difficulty: int | None = None
    crr_pathfinding: float | None = None     # overrides profile default when set

    @field_validator("max_trail_difficulty")
    @classmethod
    def difficulty_in_range(cls, v: int | None) -> int | None:
        # Out-of-range values fail silently rather than loudly: 7 would allow
        # everything and -1 would exclude every graded way while still returning
        # untagged ones, which looks like the filter doing nothing.
        if v is not None and not (0 <= v <= MAX_TRAIL_DIFFICULTY):
            raise ValueError(f"max_trail_difficulty must be 0..{MAX_TRAIL_DIFFICULTY}")
        return v

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


async def _messages_until_done(q: "asyncio.Queue[str]", fut: asyncio.Future):
    """Yield messages pushed onto `q` while `fut` is still running.

    Used to surface progress from a blocking executor stage. Without this the
    generator sits on a single `await run_in_executor(...)` and can emit nothing
    until the stage finishes — which for an Overpass outage means up to ~35 s of
    silent spinner while the retries back off.
    """
    while True:
        getter = asyncio.ensure_future(q.get())
        done, _ = await asyncio.wait({getter, fut}, return_when=asyncio.FIRST_COMPLETED)
        if getter in done:
            yield getter.result()
            continue
        # The stage finished. Cancel the pending get and flush anything that
        # landed between the last wait and now, so no message is dropped.
        getter.cancel()
        # A producer thread reaches this queue via call_soon_threadsafe, so a
        # message scheduled just before the stage returned may not have run yet.
        # Yield once to let those callbacks land before deciding the queue is dry.
        await asyncio.sleep(0)
        while not q.empty():
            yield q.get_nowait()
        return


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
        # Name the source the request will actually use. Local GOL, warm Overpass
        # cache and cold Overpass query differ by three orders of magnitude in
        # latency; showing one message for all three makes the fast paths look
        # broken and the slow path look hung.
        osm_source, osm_message = describe_source(req.bbox)
        yield _sse({"type": "status", "message": osm_message})
        t0 = time.perf_counter()

        # Overpass sheds load with 429/504 and can be flat-out down. The retry
        # backoff is up to ~35 s, so tell the user why they're waiting rather
        # than showing an unexplained stall. Emitted as `status` events, which
        # the frontend already renders — no new SSE type.
        retry_msgs: asyncio.Queue[str] = asyncio.Queue()

        def _on_overpass_retry(reason: str, attempt: int, attempts: int, delay: float) -> None:
            # Runs on the executor thread; asyncio.Queue is not thread-safe, so
            # hop to the loop thread before touching it.
            loop.call_soon_threadsafe(
                retry_msgs.put_nowait,
                f"OpenStreetMap data server failed ({reason}) — retrying in "
                f"{delay:.0f}s (attempt {attempt} of {attempts})...",
            )

        osm_fut = loop.run_in_executor(
            None, lambda: fetch_osm_data(req.bbox, on_retry=_on_overpass_retry)
        )
        async for msg in _messages_until_done(retry_msgs, osm_fut):
            yield _sse({"type": "status", "message": msg})
        nodes, ways = await osm_fut

        timings["osm"] = time.perf_counter() - t0
        log.info("stage osm (%s): %.0f ms (%d nodes, %d ways)",
                 osm_source, timings["osm"] * 1000, len(nodes), len(ways))
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
            max_trail_difficulty=req.max_trail_difficulty,
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


# These two URLs are ".json" because in production they are not served from here at
# all — they are flat files on the CDN, written by scripts/export_static_collections.py
# (see docs/deploy.md). Serving the identical URLs from FastAPI means dev, `docker run`,
# and the CDN are URL-for-URL the same, so the frontend needs no notion of which one it
# is talking to and nothing about collections is only exercised in production.
#
# Declaration order matters: "/collections/index.json" must come first, or it matches
# the slug route below and 404s as an unknown spot named "index".

@app.get("/collections/index.json")
async def collections():
    """Index of curated spots by city — metadata and headline stats, no route geometry.

    Deliberately light. Fetch /collections/{slug}.json for a spot's actual routes.
    """
    return collections_index(_load_collections())


@app.get("/collections/{slug}.json")
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


# ── Health check ──────────────────────────────────────────────────────────────

@app.get("/healthz")
@app.get("/api/healthz")
async def healthz():
    """Liveness probe. Deliberately does no I/O — it must not depend on Overpass,
    S3 or the collections file, or a healthy container looks unhealthy whenever an
    upstream is having a bad day.

    Registered at BOTH paths on purpose. `/healthz` is the conventional name and is
    what the container's own HEALTHCHECK hits over localhost. But on Cloud Run that
    exact path never reaches the container: Google's frontend answers `/healthz`
    itself with its own branded 404 page. (Verified against the deployed service —
    `/healthz` returns a Google error page while `/healthz/`, `/health` and every
    other spelling reach the app.) So anything probing from OUTSIDE — uptime checks,
    load balancers, curl — has to use `/api/healthz`.
    """
    return {"status": "ok"}


# ── Static frontend ───────────────────────────────────────────────────────────
#
# In production the built SPA is served by this same app, from this same origin.
# That is deliberate: the frontend fetches "/search" and "/collections" as RELATIVE
# paths (see hooks/useSearch.ts, hooks/useCollections.ts), so one origin means no
# CORS preflight on the SSE POST and no build-time API base URL to configure per
# environment. Split them and both of those problems arrive at once.
#
# Registered LAST so every API route above wins the match. In development this
# directory does not exist and the whole block is skipped — Vite serves the
# frontend and proxies the API (see frontend/vite.config.ts).

_STATIC_DIR = Path(
    os.environ.get("HILLBOMB_STATIC_DIR", str(Path(__file__).resolve().parents[1] / "static"))
)

if _STATIC_DIR.is_dir():
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    # Vite emits content-hashed filenames under /assets, so they are safe to cache
    # hard and forever. index.html must NOT be (see below).
    _assets = _STATIC_DIR / "assets"
    if _assets.is_dir():
        app.mount("/assets", StaticFiles(directory=str(_assets)), name="assets")

    _INDEX = _STATIC_DIR / "index.html"

    @app.get("/{full_path:path}")
    async def spa(full_path: str):
        """Serve real files, and fall back to index.html for client-side routes.

        The fallback is what makes a deep link work: the SPA owns its routing, so
        any path that isn't a file on disk has to return the app shell rather than
        a 404 and let the client resolve it.

        index.html is served no-store. It names the hashed asset bundles, so a
        cached copy pointing at bundles that no longer exist is exactly how a
        deploy turns into a blank page for anyone with a warm cache.
        """
        candidate = (_STATIC_DIR / full_path).resolve()
        # Containment check: full_path is attacker-controlled, and without this a
        # request for "../../etc/passwd" would escape the static root.
        if candidate.is_file() and candidate.is_relative_to(_STATIC_DIR.resolve()):
            return FileResponse(candidate)
        return FileResponse(_INDEX, headers={"Cache-Control": "no-store"})

    log.info("serving built frontend from %s", _STATIC_DIR)
else:
    log.info("no static dir at %s — API only (dev mode: Vite serves the frontend)", _STATIC_DIR)
