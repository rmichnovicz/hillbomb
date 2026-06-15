"""
FastAPI app with SSE streaming search endpoint.

POST /search  →  text/event-stream

SSE events (each is a JSON object on a `data:` line, double-newline terminated):
  { "type": "status",  "message": "..." }
  { "type": "route",   "route_id": ..., "geometry": {...}, "metadata": {...},
                       "flow_score": ..., "flow_grade": ... }
  { "type": "physics", "route_id": ..., "speed_profile": [...],
                       "top_speed_kmh": ..., "avg_speed_kmh": ... }
  { "type": "error",   "message": "..." }   ← fatal; stream ends here, no done
  { "type": "done" }                        ← always last on success
"""

import asyncio
import json
import logging
import threading
import time
from contextlib import asynccontextmanager
from dataclasses import replace
from typing import Any, AsyncGenerator

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("hillbomb.pipeline")

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, field_validator

from .config import DEFAULT_ROAD_TYPES, HIGHWAY_RANK, RIDER_PROFILES, SURFACE_CATEGORIES, SearchConfig, Toggles
from .elevation import ElevationService, SearchCancelled
from .graph import build_graph
from .overpass import fetch_osm_data
from .pathfinding import build_route_from_data, find_routes
from .physics import simulate_speed_profile, split_route_on_zero_speed
from .scoring import compute_flow_score

_DEDUP_THRESHOLD = 0.85


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


@asynccontextmanager
async def lifespan(app: FastAPI):
    app.state.elevation = ElevationService()
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
    animate_candidates: bool = False


class SearchRequest(BaseModel):
    bbox: tuple[float, float, float, float]  # south, west, north, east
    road_types: list[str] | None = None      # defaults to DEFAULT_ROAD_TYPES
    rider_profile: str = "cyclist_upright"
    toggles: TogglesRequest = TogglesRequest()
    max_routes: int = 500
    max_road_rank: int = 9                   # cap by HIGHWAY_RANK; 9 = all roads
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


def _surface_pcts(route) -> dict[str, float]:
    """Categorize raw OSM surface tags into display categories and return percentages."""
    total = route.length_m or 1.0
    cat_dist: dict[str, float] = {}
    for tag, dist in route.surface_distances.items():
        matched = "unknown"
        for cat_name, tags in SURFACE_CATEGORIES.items():
            if tag in tags:
                matched = cat_name
                break
        cat_dist[matched] = cat_dist.get(matched, 0.0) + dist
    return {cat: round(d / total * 100, 1) for cat, d in sorted(cat_dist.items(), key=lambda x: -x[1])}


def _route_event(route) -> str:
    return _sse({
        "type": "route",
        "route_id": route.route_id,
        "start_node_id": route.start_node_id,
        "geometry": {
            "type": "LineString",
            "coordinates": route.coordinates,
        },
        "metadata": {
            "name": route.name,
            "length_m": round(route.length_m, 1),
            "total_descent_m": round(route.total_descent_m, 1),
            "avg_grade_pct": round(route.avg_grade_pct, 2),
            "primary_highway": route.primary_highway,
        },
        "elevations": [round(e, 1) for e in route.elevations],
        "segment_distances": [round(d, 1) for d in route.segment_distances],
        "flow_score": round(route.flow_score, 1),
        "flow_grade": route.flow_grade,
        "surface_pcts": _surface_pcts(route),
        "speed_profile": [round(v, 1) for v in route.speed_profile],
        "top_speed_kmh": round(route.top_speed_kmh, 1),
        "avg_speed_kmh": round(route.avg_speed_kmh, 1),
    })


# ── Pipeline ──────────────────────────────────────────────────────────────────

async def _pipeline(req: SearchRequest, elevation_svc: ElevationService, request: Request) -> AsyncGenerator[str, None]:
    loop = asyncio.get_event_loop()

    road_types = set(req.road_types) if req.road_types else DEFAULT_ROAD_TYPES
    params = RIDER_PROFILES[req.rider_profile]
    if req.crr_pathfinding is not None:
        params = replace(params, crr_pathfinding=req.crr_pathfinding)
    config = SearchConfig(max_routes=req.max_routes)
    toggles = Toggles(
        avoid_stoplights=req.toggles.avoid_stoplights,
        avoid_stop_signs=req.toggles.avoid_stop_signs,
        avoid_bigger_roads=req.toggles.avoid_bigger_roads,
        avoid_equal_roads=req.toggles.avoid_equal_roads,
        exclude_tunnels=req.toggles.exclude_tunnels,
        exclude_bridges=req.toggles.exclude_bridges,
        animate_candidates=req.toggles.animate_candidates,
    )

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
            None, fetch_osm_data, req.bbox, road_types
        )
        timings["overpass"] = time.perf_counter() - t0
        log.info("stage overpass: %.0f ms (%d nodes, %d ways)",
                 timings["overpass"] * 1000, len(nodes), len(ways))
        if await is_done():
            return

        # Filter ways by max road rank
        ways = [w for w in ways if HIGHWAY_RANK.get(w.highway, 3) <= req.max_road_rank]

        # Filter ways by allowed surface categories (ways with no surface tag are always kept)
        if req.allowed_surface_categories is not None:
            allowed_tags: set[str] = set()
            for cat in req.allowed_surface_categories:
                allowed_tags |= SURFACE_CATEGORIES.get(cat, set())
            ways = [w for w in ways if not w.surface or w.surface in allowed_tags]

        used_ids = {nid for w in ways for nid in w.node_ids}
        active_nodes = {nid: n for nid, n in nodes.items() if nid in used_ids}

        yield _sse({"type": "status",
                    "message": f"Fetching elevation for {len(active_nodes)} nodes..."})
        coords = [(n.lon, n.lat) for n in active_nodes.values()]
        t0 = time.perf_counter()
        elevs = await loop.run_in_executor(
            None, elevation_svc.get_elevations, coords, cancel_event.is_set
        )
        timings["elevation"] = time.perf_counter() - t0
        log.info("stage elevation: %.0f ms (%d nodes, res=%sm)",
                 timings["elevation"] * 1000, len(coords), elevation_svc.resolution_m)
        if await is_done():
            return
        for node, elev in zip(active_nodes.values(), elevs):
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
        emitted_node_sets: list[frozenset[int]] = []

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

            speed_profile, top_speed, avg_speed = simulate_speed_profile(
                raw_route.elevations, raw_route.segment_distances, params, config
            )

            segments = split_route_on_zero_speed(
                raw_route.node_ids,
                raw_route.elevations,
                raw_route.segment_distances,
                speed_profile,
            )

            was_split = len(segments) > 1

            for seg_idx, (seg_node_ids, seg_elevs, seg_dists, seg_speed) in enumerate(segments):
                if sum(seg_dists) < params.min_route_length_m:
                    continue

                candidate_set = frozenset(seg_node_ids)
                if any(_jaccard(candidate_set, s) > _DEDUP_THRESHOLD for s in emitted_node_sets):
                    continue
                emitted_node_sets.append(candidate_set)

                if was_split:
                    seg_coords = [[nodes[n].lon, nodes[n].lat] for n in seg_node_ids if n in nodes]
                    # First segment inherits the original peak's group; later segments
                    # start at a new location and belong in their own group.
                    start_node_id = raw_route.start_node_id if seg_idx == 0 else seg_node_ids[0]
                    route = build_route_from_data(
                        seg_node_ids, seg_coords, seg_elevs, seg_dists, G,
                        start_node_id=start_node_id,
                    )
                else:
                    route = raw_route

                route.speed_profile = list(seg_speed)
                route.top_speed_kmh = max(seg_speed) if seg_speed else 0.0
                route.avg_speed_kmh = sum(seg_speed) / len(seg_speed) if seg_speed else 0.0

                compute_flow_score(route, G, nodes, config)
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

@app.post("/search")
async def search(req: SearchRequest, request: Request):
    if req.rider_profile not in RIDER_PROFILES:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown rider_profile '{req.rider_profile}'. "
                   f"Valid options: {list(RIDER_PROFILES)}",
        )
    return StreamingResponse(
        _pipeline(req, request.app.state.elevation, request),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",     # disable nginx buffering
            "Connection": "keep-alive",
        },
    )
