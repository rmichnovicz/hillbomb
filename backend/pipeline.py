"""
Shared pipeline core.

Everything here is used by BOTH the live search (`main.py`, streaming over SSE) and
the offline collections builder (`scripts/build_collections.py`, writing JSON). It
exists so those two cannot drift apart: a curated route and a searched route are
produced by the same code and serialized to the same shape, which is what lets every
frontend component render both without special-casing.

If you change a route's wire shape, change `route_payload()` and it lands in both.

What lives here vs. what doesn't:
  - here: pure, synchronous, reusable pipeline logic
  - main.py: HTTP/SSE framing, the admission gate, cancellation, disconnect watching
  - build_collections.py: spot iteration, filtering to named ways, JSON output
"""

from .config import HIGHWAY_RANK, SURFACE_CATEGORIES, RiderParams, SearchConfig
from .pathfinding import build_route_from_data
from .physics import simulate_speed_profile, split_route_on_zero_speed
from .scoring import compute_flow_score
from .types import OSMNode, OSMWay, Route

# Two routes sharing more than this fraction of their nodes are considered the same
# line; the later one is dropped. Jaccard over node sets, so it's symmetric and
# insensitive to length.
DEDUP_THRESHOLD = 0.85


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


# ── Traversability ────────────────────────────────────────────────────────────

def surface_category(tag: str) -> str:
    """Map a raw OSM surface tag to a display/filter category.

    An empty tag (untagged way) or any value matching no known category maps to
    "unknown" — so the "unknown" surface category covers both cases uniformly.
    """
    for cat_name, tags in SURFACE_CATEGORIES.items():
        if tag in tags:
            return cat_name
    return "unknown"


def mark_traversable(
    ways: list[OSMWay],
    road_types: set[str],
    max_road_rank: int,
    allowed_surface_categories: set[str] | None = None,
) -> None:
    """Set `way.traversable` in place for every way.

    The full classified road network is fetched on every search; this decides which
    of it may actually be *ridden*. Bigger roads (and surface/rank-excluded ways) stay
    in the graph as non-traversable detection edges so the avoid-bigger/equal-roads
    toggles can stop a descent at a crossing without ever routing onto it.

    `allowed_surface_categories=None` means all surfaces are allowed.
    """
    for w in ways:
        w.traversable = (
            w.highway in road_types
            and HIGHWAY_RANK.get(w.highway, 3) <= max_road_rank
            and (
                allowed_surface_categories is None
                or surface_category(w.surface) in allowed_surface_categories
            )
        )


def traversable_node_ids(ways: list[OSMWay]) -> set[int]:
    """Node IDs touched by at least one traversable way.

    Elevation is only needed for nodes we might actually ride. Non-traversable ways
    are kept for crossing detection, which uses road rank + way name only, never
    elevation, so their nodes can stay at 0.0.
    """
    return {nid for w in ways if w.traversable for nid in w.node_ids}


# ── Serialization ─────────────────────────────────────────────────────────────

def surface_pcts(route: Route) -> dict[str, float]:
    """Categorize raw OSM surface tags into display categories and return percentages."""
    total = route.length_m or 1.0
    cat_dist: dict[str, float] = {}
    for tag, dist in route.surface_distances.items():
        matched = surface_category(tag)
        cat_dist[matched] = cat_dist.get(matched, 0.0) + dist
    return {cat: round(d / total * 100, 1) for cat, d in sorted(cat_dist.items(), key=lambda x: -x[1])}


def route_payload(route: Route) -> dict:
    """The canonical route → dict form.

    `main.py` wraps this in an SSE frame (adding `type: "route"`); the collections
    builder writes it straight to JSON. The frontend `Route` type matches this exactly.
    """
    return {
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
        "surface_pcts": surface_pcts(route),
        "stops": route.stops,
        "speed_profile": [round(v, 1) for v in route.speed_profile],
        "top_speed_kmh": round(route.top_speed_kmh, 1),
        "avg_speed_kmh": round(route.avg_speed_kmh, 1),
    }


# ── Finalization ──────────────────────────────────────────────────────────────

class RouteFinalizer:
    """Turns raw pathfinding output into emittable routes.

    Per raw route: simulate speed, split at any point the rider stalls to 0, drop
    sub-minimum-length fragments, drop near-duplicates of anything already emitted,
    then attach physics and a flow score.

    Stateful — it remembers what it has emitted in order to dedup — so use one
    instance per search and feed it routes in the order pathfinding produced them.
    """

    def __init__(self, G, nodes: dict[int, OSMNode], config: SearchConfig, params: RiderParams) -> None:
        self._G = G
        self._nodes = nodes
        self._config = config
        self._params = params
        self._emitted_node_sets: list[frozenset[int]] = []

    def finalize(self, raw_route: Route) -> list[Route]:
        """Return 0+ ready-to-emit routes derived from one raw route."""
        speed_profile, _top_speed, _avg_speed = simulate_speed_profile(
            raw_route.elevations, raw_route.segment_distances, self._params, self._config
        )

        segments = split_route_on_zero_speed(
            raw_route.node_ids,
            raw_route.elevations,
            raw_route.segment_distances,
            speed_profile,
        )
        was_split = len(segments) > 1

        out: list[Route] = []
        for seg_idx, (seg_node_ids, seg_elevs, seg_dists, seg_speed) in enumerate(segments):
            if sum(seg_dists) < self._params.min_route_length_m:
                continue

            candidate_set = frozenset(seg_node_ids)
            if any(_jaccard(candidate_set, s) > DEDUP_THRESHOLD for s in self._emitted_node_sets):
                continue
            self._emitted_node_sets.append(candidate_set)

            if was_split:
                seg_coords = [
                    [self._nodes[n].lon, self._nodes[n].lat]
                    for n in seg_node_ids
                    if n in self._nodes
                ]
                # First segment inherits the original peak's group; later segments
                # start at a new location and belong in their own group.
                start_node_id = raw_route.start_node_id if seg_idx == 0 else seg_node_ids[0]
                route = build_route_from_data(
                    seg_node_ids, seg_coords, seg_elevs, seg_dists, self._G,
                    start_node_id=start_node_id,
                )
            else:
                route = raw_route

            route.speed_profile = list(seg_speed)
            route.top_speed_kmh = max(seg_speed) if seg_speed else 0.0
            route.avg_speed_kmh = sum(seg_speed) / len(seg_speed) if seg_speed else 0.0

            compute_flow_score(route, self._G, self._nodes, self._config)
            out.append(route)

        return out
