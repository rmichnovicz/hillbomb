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

# ...but symmetric similarity structurally cannot see a route that lies *inside* another
# one. Mount Diablo's South Gate Road shipped a 5.1 km route whose nodes were 98% a
# subset of the 9.2 km route above it — Jaccard 0.53, well under the cut, because the
# union is dominated by the longer route's extra half. A short line that adds nothing to
# a long one it sits inside is a duplicate however little of that long one it covers,
# so containment gets its own, lower threshold.
CONTAINMENT_THRESHOLD = 0.7


def _jaccard(a: frozenset[int], b: frozenset[int]) -> float:
    if not a and not b:
        return 1.0
    return len(a & b) / len(a | b)


def _containment(a: frozenset[int], b: frozenset[int]) -> float:
    """Fraction of the *smaller* set that the two share — 1.0 when one is a subset."""
    smaller = min(len(a), len(b))
    if smaller == 0:
        return 1.0 if not a and not b else 0.0
    return len(a & b) / smaller


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
    max_trail_difficulty: int | None = None,
) -> None:
    """Set `way.traversable` in place for every way.

    The full classified road network is fetched on every search; this decides which
    of it may actually be *ridden*. Bigger roads (and surface/rank/difficulty-excluded
    ways) stay in the graph as non-traversable detection edges so the
    avoid-bigger/equal-roads toggles can stop a descent at a crossing without ever
    routing onto it.

    `allowed_surface_categories=None` means all surfaces are allowed.

    `max_trail_difficulty=None` means any difficulty is allowed. When set, a way graded
    ABOVE it is excluded — but an *untagged* way (trail_difficulty is None) is kept,
    because most trails carry no `mtb:scale` and excluding unknowns would throw away
    the terrain along with the black diamonds. That asymmetry is the whole caveat on
    this filter: it can tighten a search already on trails, and cannot be leaned on to
    guarantee singletrack never reaches a road result. See config.MAX_TRAIL_DIFFICULTY.
    """
    for w in ways:
        w.traversable = (
            w.highway in road_types
            and HIGHWAY_RANK.get(w.highway, 3) <= max_road_rank
            and (
                allowed_surface_categories is None
                or surface_category(w.surface) in allowed_surface_categories
            )
            and (
                max_trail_difficulty is None
                or w.trail_difficulty is None
                or w.trail_difficulty <= max_trail_difficulty
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
        # 0-6 mtb:scale of the hardest segment, or null when nothing on the route
        # was tagged. Null means unknown, NOT easy — the frontend must not render it
        # as a grade of 0. See config.SAC_SCALE_TO_DIFFICULTY.
        "trail_difficulty": route.trail_difficulty,
        "stops": route.stops,
        "speed_profile": [round(v, 1) for v in route.speed_profile],
        "top_speed_kmh": round(route.top_speed_kmh, 1),
        "avg_speed_kmh": round(route.avg_speed_kmh, 1),
    }


def spot_summary(entry: dict) -> dict:
    """Index-card view of a spot: metadata plus headline stats, minus all geometry.

    Same reason `route_payload` lives here. Collections are served two ways in
    production — by `main.py` from the built doc, and as flat files on the CDN written
    by `scripts/export_static_collections.py` — and the frontend must not be able to
    tell which one it got. One definition, both callers.
    """
    routes = entry.get("routes", [])
    best = routes[0] if routes else None
    return {
        "slug": entry["slug"],
        "name": entry["name"],
        "state": entry["state"],
        "blurb": entry["blurb"],
        "disciplines": entry["disciplines"],
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


def collections_index(doc: dict) -> dict:
    """The whole index: every city, every spot summary, no geometry.

    Deliberately light — a few tens of KB against ~8 MB for the full corpus — so the
    Collections tab can load it on open and fetch spots lazily.
    """
    return {
        "version": doc.get("version", 1),
        "cities": [
            {"city": c["city"], "spots": [spot_summary(s) for s in c.get("spots", [])]}
            for c in doc.get("cities", [])
        ],
    }


# ── Finalization ──────────────────────────────────────────────────────────────

class RouteFinalizer:
    """Turns raw pathfinding output into emittable routes.

    Per raw route: simulate speed, split at any point the rider stalls to 0, drop
    sub-minimum-length fragments, drop near-duplicates of anything already emitted,
    then attach physics and a flow score.

    Stateful — it remembers what it has emitted in order to dedup — so use one
    instance per search and feed it routes in the order pathfinding produced them.

    `split_on_stall=False` keeps a stalling route whole, dipping to 0 km/h mid-profile
    and picking back up when the road tips down again (the sim carries speed across
    segments, so it recovers on its own). The collections builder wants this: a curated
    spot is one named descent, and splitting it at a 6 m riser turned Piuma Road into
    two routes that read as duplicates. A live search keeps the default — there, a
    stall is genuinely the end of that descent and the far side is a separate find.
    """

    def __init__(
        self,
        G,
        nodes: dict[int, OSMNode],
        config: SearchConfig,
        params: RiderParams,
        split_on_stall: bool = True,
    ) -> None:
        self._G = G
        self._nodes = nodes
        self._config = config
        self._params = params
        self._split_on_stall = split_on_stall
        self._emitted_node_sets: list[frozenset[int]] = []

    def finalize(self, raw_route: Route) -> list[Route]:
        """Return 0+ ready-to-emit routes derived from one raw route."""
        speed_profile, _top_speed, _avg_speed = simulate_speed_profile(
            raw_route.elevations, raw_route.segment_distances, self._params, self._config
        )

        if self._split_on_stall:
            segments = split_route_on_zero_speed(
                raw_route.node_ids,
                raw_route.elevations,
                raw_route.segment_distances,
                speed_profile,
            )
        else:
            segments = [(
                raw_route.node_ids,
                raw_route.elevations,
                raw_route.segment_distances,
                speed_profile,
            )]
        was_split = len(segments) > 1

        out: list[Route] = []
        for seg_idx, (seg_node_ids, seg_elevs, seg_dists, seg_speed) in enumerate(segments):
            if sum(seg_dists) < self._params.min_route_length_m:
                continue

            candidate_set = frozenset(seg_node_ids)
            if any(
                _jaccard(candidate_set, s) > DEDUP_THRESHOLD
                or _containment(candidate_set, s) > CONTAINMENT_THRESHOLD
                for s in self._emitted_node_sets
            ):
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

            compute_flow_score(route, self._G, self._nodes, self._config, self._params)
            out.append(route)

        return out
