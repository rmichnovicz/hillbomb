"""
Tests for pipeline.py — the core shared by the live search and the collections builder.

The contract that matters here: `route_payload` is the single definition of a route's
wire shape. Both `/search` (SSE) and `collections.json` go through it, so the frontend
can render either without special-casing. A test pins that shape.
"""

import networkx as nx
import pytest

from ..config import RiderParams, SearchConfig
from ..pipeline import (
    DEDUP_THRESHOLD,
    RouteFinalizer,
    _jaccard,
    mark_traversable,
    route_payload,
    surface_category,
    surface_pcts,
    traversable_node_ids,
)
from ..types import OSMWay, Route


def _way(way_id: int, highway: str, surface: str = "asphalt", node_ids=None,
         trail_difficulty=None) -> OSMWay:
    return OSMWay(
        id=way_id,
        node_ids=node_ids if node_ids is not None else [way_id * 10, way_id * 10 + 1],
        highway=highway,
        oneway=False,
        oneway_reverse=False,
        surface=surface,
        trail_difficulty=trail_difficulty,
    )


def _route(**overrides) -> Route:
    base = dict(
        route_id="r1",
        node_ids=[1, 2, 3],
        coordinates=[[-122.45, 37.75], [-122.449, 37.751], [-122.448, 37.752]],
        elevations=[120.0, 110.0, 100.0],
        segment_distances=[100.0, 100.0],
        primary_highway="residential",
        start_node_id=1,
        name="Test Street",
        length_m=200.0,
        total_descent_m=20.0,
        avg_grade_pct=-10.0,
    )
    base.update(overrides)
    return Route(**base)


# ── surface_category ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tag,expected", [
    ("asphalt", "paved"),
    ("concrete", "paved"),
    ("gravel", "gravel"),
    ("dirt", "unpaved"),
    ("cobblestone", "cobblestone"),
    ("sett", "cobblestone"),
])
def test_surface_category_maps_known_tags(tag, expected):
    assert surface_category(tag) == expected


@pytest.mark.parametrize("tag", ["", "some_new_osm_tag", "wood"])
def test_surface_category_falls_back_to_unknown(tag):
    """Untagged and unrecognized both land in "unknown" so one filter covers both."""
    assert surface_category(tag) == "unknown"


# ── mark_traversable ──────────────────────────────────────────────────────────

def test_mark_traversable_respects_road_types():
    ways = [_way(1, "residential"), _way(2, "motorway")]
    mark_traversable(ways, road_types={"residential"}, max_road_rank=9)
    assert [w.traversable for w in ways] == [True, False]


def test_mark_traversable_respects_max_road_rank():
    ways = [_way(1, "residential"), _way(2, "secondary")]  # ranks 3 and 6
    mark_traversable(ways, road_types={"residential", "secondary"}, max_road_rank=5)
    assert [w.traversable for w in ways] == [True, False]


def test_mark_traversable_respects_surface_filter():
    ways = [_way(1, "residential", "asphalt"), _way(2, "residential", "gravel")]
    mark_traversable(
        ways, road_types={"residential"}, max_road_rank=9,
        allowed_surface_categories={"paved"},
    )
    assert [w.traversable for w in ways] == [True, False]


def test_mark_traversable_none_surface_allows_everything():
    ways = [_way(1, "residential", "gravel"), _way(2, "residential", "")]
    mark_traversable(ways, road_types={"residential"}, max_road_rank=9,
                     allowed_surface_categories=None)
    assert all(w.traversable for w in ways)


def test_mark_traversable_excluding_unknown_drops_untagged_ways():
    """Excluding "unknown" must drop surface-untagged roads, not just odd tags."""
    ways = [_way(1, "residential", "")]
    mark_traversable(ways, road_types={"residential"}, max_road_rank=9,
                     allowed_surface_categories={"paved"})
    assert ways[0].traversable is False


def test_mark_traversable_respects_trail_difficulty_cap():
    ways = [_way(1, "path", trail_difficulty=2), _way(2, "path", trail_difficulty=4)]
    mark_traversable(ways, road_types={"path"}, max_road_rank=9, max_trail_difficulty=3)
    assert [w.traversable for w in ways] == [True, False]


def test_mark_traversable_trail_difficulty_cap_keeps_untagged_ways():
    """The inverse of the surface filter, and deliberately so.

    Excluding "unknown" surface drops untagged roads; a difficulty cap must NOT drop
    untagged trails, because almost no US trail carries mtb:scale and doing so would
    empty the graph. Documented in mark_traversable — the cost is that this filter
    cannot promise a road search never sees singletrack.
    """
    ways = [_way(1, "path", trail_difficulty=None)]
    mark_traversable(ways, road_types={"path"}, max_road_rank=9, max_trail_difficulty=0)
    assert ways[0].traversable is True


def test_mark_traversable_none_difficulty_cap_allows_everything():
    ways = [_way(1, "path", trail_difficulty=6)]
    mark_traversable(ways, road_types={"path"}, max_road_rank=9, max_trail_difficulty=None)
    assert ways[0].traversable is True


def test_mark_traversable_overwrites_previous_value():
    """Ways may arrive pre-tagged from a cache; the call must be authoritative."""
    ways = [_way(1, "motorway")]
    ways[0].traversable = True
    mark_traversable(ways, road_types={"residential"}, max_road_rank=9)
    assert ways[0].traversable is False


def test_traversable_node_ids_only_covers_rideable_ways():
    ways = [_way(1, "residential", node_ids=[1, 2]), _way(2, "motorway", node_ids=[3, 4])]
    mark_traversable(ways, road_types={"residential"}, max_road_rank=9)
    assert traversable_node_ids(ways) == {1, 2}


# ── Serialization ─────────────────────────────────────────────────────────────

def test_surface_pcts_aggregates_tags_into_categories():
    route = _route(length_m=200.0, surface_distances={"asphalt": 100.0, "concrete": 50.0, "gravel": 50.0})
    assert surface_pcts(route) == {"paved": 75.0, "gravel": 25.0}


def test_surface_pcts_handles_zero_length_route():
    """Guard against div-by-zero on a degenerate route rather than raising."""
    assert surface_pcts(_route(length_m=0.0, surface_distances={})) == {}


def test_route_payload_has_the_full_wire_shape():
    """Pins the contract shared by /search SSE and collections.json.

    If this test needs updating, the frontend `Route` type does too.
    """
    payload = route_payload(_route())
    assert set(payload) == {
        "route_id", "start_node_id", "geometry", "metadata", "elevations",
        "segment_distances", "flow_score", "flow_grade", "surface_pcts",
        "trail_difficulty", "stops",
        "speed_profile", "top_speed_kmh", "avg_speed_kmh",
    }
    assert payload["geometry"]["type"] == "LineString"
    assert set(payload["metadata"]) == {
        "name", "length_m", "total_descent_m", "avg_grade_pct", "primary_highway",
    }


def test_route_payload_rounds_floats():
    route = _route(length_m=200.123456, elevations=[120.15555, 110.0, 100.0], top_speed_kmh=42.987)
    payload = route_payload(route)
    assert payload["metadata"]["length_m"] == 200.1
    assert payload["elevations"][0] == 120.2
    assert payload["top_speed_kmh"] == 43.0


# ── RouteFinalizer ────────────────────────────────────────────────────────────

def _finalizer(**kwargs) -> RouteFinalizer:
    G = nx.DiGraph()
    params = RiderParams(
        weight_kg=80, drag_coefficient=0.88, frontal_area_m2=0.42,
        crr_physics=0.004, crr_pathfinding=0.004,
        min_continue_speed_kmh=8, min_route_length_m=150,
    )
    return RouteFinalizer(G, {}, SearchConfig(), params, **kwargs)


def _stalling_route(**overrides) -> Route:
    """400 m that drops, climbs a riser hard enough to stop the rider, then drops again.

    The sim reaches 62 km/h, stalls to exactly 0 at node 3, and recovers to 75.
    """
    return _route(
        node_ids=[1, 2, 3, 4, 5],
        coordinates=[[-122.45 + i * 0.001, 37.75 + i * 0.001] for i in range(5)],
        elevations=[120.0, 100.0, 130.0, 128.0, 100.0],
        segment_distances=[100.0] * 4,
        length_m=400.0,
        **overrides,
    )


def test_finalizer_attaches_physics():
    routes = _finalizer().finalize(_route(segment_distances=[100.0, 100.0]))
    assert len(routes) == 1
    assert routes[0].speed_profile, "speed profile was not attached"
    assert routes[0].top_speed_kmh > 0


def test_finalizer_drops_routes_below_min_length():
    """min_route_length_m is 150 here; a 20 m route must not survive."""
    short = _route(segment_distances=[10.0, 10.0])
    assert _finalizer().finalize(short) == []


def test_finalizer_dedups_near_identical_routes():
    fin = _finalizer()
    assert len(fin.finalize(_route(route_id="a"))) == 1
    # Same node set → Jaccard 1.0 → dropped as the same line.
    assert fin.finalize(_route(route_id="b")) == []


def test_finalizer_keeps_distinct_routes():
    fin = _finalizer()
    assert len(fin.finalize(_route(route_id="a", node_ids=[1, 2, 3]))) == 1
    assert len(fin.finalize(_route(route_id="b", node_ids=[7, 8, 9]))) == 1


def test_finalizer_drops_a_route_contained_in_one_already_emitted():
    """The Mount Diablo case: a short line living inside a long one Jaccard can't flag."""
    long_route = _route(route_id="long", node_ids=list(range(20)), segment_distances=[100.0] * 19,
                        elevations=[200.0 - i * 5 for i in range(20)])
    inside = _route(route_id="inside", node_ids=list(range(10)), segment_distances=[100.0] * 9,
                    elevations=[200.0 - i * 5 for i in range(10)])
    # Jaccard sees only 10/20 = 0.50, under DEDUP_THRESHOLD — containment sees 10/10.
    assert _jaccard(frozenset(range(10)), frozenset(range(20))) < DEDUP_THRESHOLD

    fin = _finalizer()
    assert len(fin.finalize(long_route)) == 1
    assert fin.finalize(inside) == []


def test_finalizer_keeps_routes_that_merely_cross():
    """Sharing a junction is not containment; two descents through one node both stand."""
    fin = _finalizer()
    a = _route(route_id="a", node_ids=[1, 2, 3, 4, 5], segment_distances=[100.0] * 4,
               elevations=[200.0, 180.0, 160.0, 140.0, 120.0])
    b = _route(route_id="b", node_ids=[9, 8, 3, 7, 6], segment_distances=[100.0] * 4,
               elevations=[200.0, 180.0, 160.0, 140.0, 120.0])
    assert len(fin.finalize(a)) == 1
    assert len(fin.finalize(b)) == 1


def test_finalizer_dedup_state_is_per_instance():
    """Two searches must not contaminate each other's dedup history."""
    assert len(_finalizer().finalize(_route())) == 1
    assert len(_finalizer().finalize(_route())) == 1


# ── split_on_stall ────────────────────────────────────────────────────────────

def test_finalizer_splits_at_a_stall_by_default():
    """A live search treats the far side of a stall as its own descent."""
    routes = _finalizer().finalize(_stalling_route())
    assert len(routes) == 2
    assert [r.node_ids for r in routes] == [[1, 2, 3], [3, 4, 5]]


def test_finalizer_keeps_a_stalling_route_whole_when_splitting_is_off():
    """Collections want the whole named descent, stall included."""
    routes = _finalizer(split_on_stall=False).finalize(_stalling_route())
    assert len(routes) == 1
    assert routes[0].node_ids == [1, 2, 3, 4, 5]


def test_unsplit_route_dips_to_zero_and_recovers():
    """The 0 stays in the profile — that's the point — and speed picks back up."""
    route = _finalizer(split_on_stall=False).finalize(_stalling_route())[0]
    assert route.speed_profile[2] == 0.0, "the stall must survive in the profile"
    assert route.speed_profile[-1] > 0.0, "sim must re-accelerate past the riser"
    assert route.top_speed_kmh == max(route.speed_profile)


def test_split_on_stall_does_not_change_a_route_that_never_stalls():
    """The flag is only about stalls; everything else must be byte-identical."""
    split = _finalizer().finalize(_route(segment_distances=[100.0, 100.0]))[0]
    whole = _finalizer(split_on_stall=False).finalize(_route(segment_distances=[100.0, 100.0]))[0]
    assert split.node_ids == whole.node_ids
    assert split.speed_profile == whole.speed_profile
