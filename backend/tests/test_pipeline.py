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
    RouteFinalizer,
    mark_traversable,
    route_payload,
    surface_category,
    surface_pcts,
    traversable_node_ids,
)
from ..types import OSMWay, Route


def _way(way_id: int, highway: str, surface: str = "asphalt", node_ids=None) -> OSMWay:
    return OSMWay(
        id=way_id,
        node_ids=node_ids if node_ids is not None else [way_id * 10, way_id * 10 + 1],
        highway=highway,
        oneway=False,
        oneway_reverse=False,
        surface=surface,
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
        "segment_distances", "flow_score", "flow_grade", "surface_pcts", "stops",
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

def _finalizer() -> RouteFinalizer:
    G = nx.DiGraph()
    params = RiderParams(
        weight_kg=80, drag_coefficient=0.88, frontal_area_m2=0.42,
        crr_physics=0.004, crr_pathfinding=0.004,
        min_continue_speed_kmh=8, min_route_length_m=150,
    )
    return RouteFinalizer(G, {}, SearchConfig(), params)


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


def test_finalizer_dedup_state_is_per_instance():
    """Two searches must not contaminate each other's dedup history."""
    assert len(_finalizer().finalize(_route())) == 1
    assert len(_finalizer().finalize(_route())) == 1
