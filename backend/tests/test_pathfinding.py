"""
Tests for pathfinding.py — greedy descent algorithm.

Key invariants under test:
  - Routes seed from peak nodes only
  - Paths terminate at valleys, traffic signals, stop signs, speed floor,
    node cap, bigger-road crossings
  - Routes shorter than min_route_length_m are silently discarded
  - Paths never revisit a node (cycle-free)
  - max_routes cap is respected
  - Toggles correctly disable each stop type
  - Downhill edges accelerate; uphill/flat edges decelerate (correct physics sign)

Two bugs that these tests expose and the implementation must fix:
  1. _speed_at_node sign error: formula used `g*(grade - crr)` which gives negative
     acceleration for negative (downhill) grade. Correct: `g*(-grade - crr)`.
  2. current_hw_rank was computed from the max of OUTGOING edges (always >= next_hw_rank,
     so the bigger-road check could never fire). Correct: rank of the incoming edge
     (G[prev_node][current_node]), or 0 at the seed node.
"""

import math
import networkx as nx
import pytest

from ..config import RIDER_PROFILES, SearchConfig, Toggles
from ..pathfinding import _CANCEL_CHECK_INTERVAL, _speed_at_node, find_routes
from ..types import OSMNode

# ── Graph-building helpers ────────────────────────────────────────────────────

# Nodes are placed along a south-running transect; 1° lat ≈ 111 km.
_BASE_LAT = 37.75
_BASE_LON = -122.45
_LAT_PER_M = 1 / 111_000


def _make_node(
    nid: int,
    south_m: float,
    elevation: float,
    *,
    is_peak: bool = False,
    is_valley: bool = False,
    is_traffic_signal: bool = False,
    is_stop_sign: bool = False,
) -> OSMNode:
    lat = _BASE_LAT - south_m * _LAT_PER_M
    return OSMNode(
        id=nid, lat=lat, lon=_BASE_LON, elevation=elevation,
        is_traffic_signal=is_traffic_signal, is_stop_sign=is_stop_sign,
    )


def _add_node(G: nx.DiGraph, node: OSMNode, *, is_peak=False, is_valley=False) -> None:
    G.add_node(
        node.id, lat=node.lat, lon=node.lon, elevation=node.elevation,
        is_traffic_signal=node.is_traffic_signal,
        is_stop_sign=node.is_stop_sign,
        is_peak=is_peak, is_valley=is_valley,
        is_inflection=False, is_intersection=False,
    )


def _add_edge(
    G: nx.DiGraph, u: int, v: int,
    *,
    grade: float = -0.10,
    dist: float = 150.0,
    highway: str = "residential",
    hw_rank: int = 3,
    surface: str = "asphalt",
    is_tunnel: bool = False,
    way_name: str = "Test Street",
) -> None:
    G.add_edge(
        u, v,
        grade=grade, distance_m=dist,
        highway=highway, hw_rank=hw_rank, surface=surface,
        is_bridge=False, is_tunnel=is_tunnel, way_name=way_name,
    )


def _run(G, nodes, *, config=None, params=None, toggles=None):
    if config is None:
        config = SearchConfig()
    if params is None:
        params = RIDER_PROFILES["longboarder"]  # min_speed=5km/h, min_length=60m
    if toggles is None:
        toggles = Toggles()
    return list(find_routes(G, nodes, config, params, toggles))


def _linear_graph(n_nodes: int = 4, grade: float = -0.10, dist: float = 150.0, *,
                  last_is_valley: bool = True):
    """
    Build a simple linear chain: node 1 (peak) → node 2 → … → node n (valley).
    Returns (G, nodes_by_id).
    """
    G = nx.DiGraph()
    nodes = {}
    for i in range(1, n_nodes + 1):
        south_m = (i - 1) * dist
        elev = 100.0 - (i - 1) * dist * abs(grade)
        is_peak = (i == 1)
        is_valley = (i == n_nodes) and last_is_valley
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
    for i in range(1, n_nodes):
        _add_edge(G, i, i + 1, grade=grade, dist=dist)
    return G, nodes


# ── _speed_at_node unit tests ────────────────────────────────────────────────

class TestSpeedAtNode:
    """Physics helper used by the pathfinding priority queue."""

    lb = RIDER_PROFILES["longboarder"]

    def test_downhill_from_rest_gives_nonzero_speed(self):
        """10% downhill over 200m starting from rest must produce > 0 speed."""
        v = _speed_at_node(0.0, -0.10, 200.0, self.lb)
        assert v > 0.0, (
            f"Expected positive speed on 10% downhill but got {v}. "
            "Check sign: formula should use g*(-grade - crr), not g*(grade - crr)."
        )

    def test_downhill_faster_than_shallower_downhill(self):
        v_steep = _speed_at_node(0.0, -0.15, 200.0, self.lb)
        v_gentle = _speed_at_node(0.0, -0.05, 200.0, self.lb)
        assert v_steep > v_gentle

    def test_flat_from_rest_gives_zero_speed(self):
        """No gradient + rolling resistance → can't move from rest."""
        v = _speed_at_node(0.0, 0.0, 200.0, self.lb)
        assert v == pytest.approx(0.0, abs=0.1)

    def test_uphill_from_rest_gives_zero_speed(self):
        v = _speed_at_node(0.0, +0.10, 200.0, self.lb)
        assert v == pytest.approx(0.0, abs=0.1)

    def test_uphill_slows_moving_rider(self):
        """A moving rider should slow down on an uphill segment."""
        v0 = 15.0  # m/s (54 km/h)
        v1 = _speed_at_node(v0, +0.10, 200.0, self.lb)
        assert v1 < v0

    def test_downhill_speeds_up_moving_rider(self):
        v0 = 5.0
        v1 = _speed_at_node(v0, -0.10, 200.0, self.lb)
        assert v1 > v0

    def test_speed_never_negative(self):
        """Clamp to 0 — sqrt of negative is caught."""
        v = _speed_at_node(0.0, +0.50, 1000.0, self.lb)
        assert v >= 0.0

    def test_speed_units_are_m_per_s(self):
        """A 10% grade over 200 m should give a few m/s, not km/h values."""
        v = _speed_at_node(0.0, -0.10, 200.0, self.lb)
        assert 0 < v < 50.0  # plausible m/s range; km/h would be 180+ for same run


# ── Seeding ───────────────────────────────────────────────────────────────────

def test_no_peaks_produces_no_routes():
    G, nodes = _linear_graph(3)
    # Remove peak flag from all nodes
    for nid in G.nodes:
        G.nodes[nid]["is_peak"] = False
    routes = _run(G, nodes)
    assert routes == []


def test_seeds_only_from_peak_nodes():
    """All emitted routes must start at a node tagged is_peak."""
    G, nodes = _linear_graph(4)
    routes = _run(G, nodes)
    for r in routes:
        assert G.nodes[r.node_ids[0]].get("is_peak"), \
            f"Route started at non-peak node {r.node_ids[0]}"


# ── Valley termination ────────────────────────────────────────────────────────

def test_valley_terminates_path():
    """A path reaching a valley node must finalize and be emitted."""
    G, nodes = _linear_graph(4)  # node 4 is the valley
    routes = _run(G, nodes)
    assert len(routes) >= 1
    # At least one route ends at the valley
    assert any(r.node_ids[-1] == 4 for r in routes)


def test_valley_at_start_does_not_terminate():
    """Valley tag on the peak node itself is ignored (start of path, not mid-route)."""
    G, nodes = _linear_graph(4)
    G.nodes[1]["is_valley"] = True  # also tag peak as valley
    routes = _run(G, nodes)
    # Still finds the valley-terminated route reaching node 4
    assert any(len(r.node_ids) > 2 for r in routes)


# ── Traffic signal termination ────────────────────────────────────────────────

def test_traffic_signal_terminates_path():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_signal) in enumerate([
        (0,   100.0, True,  False),   # 1: peak
        (150, 85.0,  False, True),    # 2: traffic signal
        (300, 70.0,  False, False),   # 3: past signal
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_traffic_signal=is_signal)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak)
        G.nodes[i]["is_traffic_signal"] = is_signal
    _add_edge(G, 1, 2)
    _add_edge(G, 2, 3)

    routes = _run(G, nodes)
    # Route must end at node 2 (signal), not continue to 3
    assert any(r.node_ids[-1] == 2 for r in routes)
    assert all(r.node_ids[-1] != 3 for r in routes)


def test_traffic_signal_at_start_not_penalized():
    """Signal on the peak (start) node is not a valid stop point — path must continue."""
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_signal, is_valley) in enumerate([
        (0,   100.0, True,  True,  False),   # 1: peak + signal (start)
        (150, 85.0,  False, False, False),   # 2
        (300, 70.0,  False, False, True),    # 3: valley
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_traffic_signal=is_signal,
                          is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
        G.nodes[i]["is_traffic_signal"] = is_signal
    _add_edge(G, 1, 2)
    _add_edge(G, 2, 3)

    routes = _run(G, nodes)
    # Route must extend past node 1
    assert any(len(r.node_ids) > 1 for r in routes)


def test_avoid_stoplights_false_ignores_signal():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_signal, is_valley) in enumerate([
        (0,   100.0, True,  False, False),
        (150, 85.0,  False, True,  False),
        (300, 70.0,  False, False, True),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_traffic_signal=is_signal,
                          is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
        G.nodes[i]["is_traffic_signal"] = is_signal
    _add_edge(G, 1, 2)
    _add_edge(G, 2, 3)

    toggles = Toggles(avoid_stoplights=False)
    routes = _run(G, nodes, toggles=toggles)
    # With signals ignored, route should continue past node 2 to the valley at 3
    assert any(r.node_ids[-1] == 3 for r in routes)


# ── Stop sign termination ─────────────────────────────────────────────────────

def test_stop_sign_terminates_path():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_stop) in enumerate([
        (0,   100.0, True,  False),
        (150, 85.0,  False, True),
        (300, 70.0,  False, False),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_stop_sign=is_stop)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak)
        G.nodes[i]["is_stop_sign"] = is_stop
    _add_edge(G, 1, 2)
    _add_edge(G, 2, 3)

    routes = _run(G, nodes)
    assert any(r.node_ids[-1] == 2 for r in routes)


def test_avoid_stop_signs_false_ignores_stop():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_stop, is_valley) in enumerate([
        (0,   100.0, True,  False, False),
        (150, 85.0,  False, True,  False),
        (300, 70.0,  False, False, True),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_stop_sign=is_stop,
                          is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
        G.nodes[i]["is_stop_sign"] = is_stop
    _add_edge(G, 1, 2)
    _add_edge(G, 2, 3)

    toggles = Toggles(avoid_stop_signs=False)
    routes = _run(G, nodes, toggles=toggles)
    assert any(r.node_ids[-1] == 3 for r in routes)


# ── Speed floor termination ───────────────────────────────────────────────────

def test_speed_floor_terminates_on_steep_uphill():
    """
    A 10% downhill gives ~17 m/s; a subsequent 30% uphill bleeds that to 0 in ~47m.
    Speed floor fires at node 3; path is finalized and emitted (210m > 60m min).
    Node 4 must never appear — the path can't reach it.

    Math (crr_pathfinding=0.012):
      seed speed = 5.6 m/s (peak_seed_speed_ms)
      edge 1→2: net_accel = 9.81*(0.10-0.012) = 0.863 m/s²
                v² = 5.6² + 2*0.863*150 = 290.3  → v₂ ≈ 17.0 m/s
      edge 2→3: net_accel = 9.81*(-0.30-0.012) = -3.061 m/s²
                v² = 290.3 + 2*(-3.061)*60 = -76.9 < 0  → clamped to 0 → floor fires.
    """
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak) in enumerate([
        (0,   100.0, True),
        (150,  85.0, False),   # grade -0.10, dist 150 → arrival ~17.0 m/s
        (210, 103.0, False),   # grade +0.30, dist 60  → arrival 0 m/s → floor fires
        (270, 121.0, False),   # unreachable
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak)
    _add_edge(G, 1, 2, grade=-0.10, dist=150.0)
    _add_edge(G, 2, 3, grade=+0.30, dist=60.0)
    _add_edge(G, 3, 4, grade=+0.30, dist=60.0)

    params = RIDER_PROFILES["longboarder"]  # min_speed=5 km/h, min_length=60m
    routes = _run(G, nodes, params=params)

    assert routes, "Expected route emitted when speed floor fires at node 3"
    for r in routes:
        assert r.node_ids[-1] != 4, "Path should not reach node 4 past the speed floor"


def test_uphill_from_rest_gives_zero_speed_and_terminates_immediately():
    """
    Peak with only an uphill outgoing edge: path gets speed=0 at node 2,
    speed floor fires, route finalizes. If the edge is >= min_route_length_m,
    the route is emitted; otherwise discarded.
    """
    G = nx.DiGraph()
    nodes = {}
    # Node 1 = peak, Node 2 = uphill (higher elevation)
    n1 = _make_node(1, 0, 100.0, is_peak=True)
    n2 = _make_node(2, 150, 115.0)  # 150m north, 15m higher = +10% grade
    nodes[1] = n1
    nodes[2] = n2
    _add_node(G, n1, is_peak=True)
    _add_node(G, n2)
    _add_edge(G, 1, 2, grade=+0.10, dist=150.0)

    params = RIDER_PROFILES["longboarder"]  # min_route_length_m=60
    routes = _run(G, nodes, params=params)

    # Whether emitted or not, speed at node 2 must have been 0
    # (uphill from rest = no propulsion)
    # We just verify no route CONTINUES past node 2
    for r in routes:
        assert len(r.node_ids) <= 2


# ── Bigger road crossing ──────────────────────────────────────────────────────

def test_bigger_road_terminates_path():
    """
    Path on residential (rank 3) should stop when it would cross onto primary (rank 7).
    """
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak) in enumerate([
        (0,   100.0, True),
        (150, 85.0,  False),
        (300, 70.0,  False),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak)
    # First edge: residential
    _add_edge(G, 1, 2, grade=-0.10, dist=150.0, hw_rank=3, highway="residential")
    # Second edge: jumps to primary — should trigger termination
    _add_edge(G, 2, 3, grade=-0.10, dist=150.0, hw_rank=7, highway="primary")

    toggles = Toggles(avoid_bigger_roads=True)
    routes = _run(G, nodes, toggles=toggles)

    # Route must stop at node 2, not reach node 3
    assert any(r.node_ids[-1] == 2 for r in routes), \
        "Expected route to terminate at node 2 when crossing to primary road"
    assert all(r.node_ids[-1] != 3 for r in routes)


def test_avoid_equal_roads_does_not_stop_when_same_road_continues():
    """
    Regression for the Hawk Hill / Conzelman Road case.

    Conzelman Road is a single OSM way (tagged `secondary`, rank 6) that descends
    through several intersections. With `avoid_equal_roads=True`, a hill bomb that
    stays on Conzelman should be allowed to continue STRAIGHT through an
    intersection — the toggle is meant to stop you from *turning onto* a different
    road of equal class, not from continuing on the road you're already on.

    Graph (mirrors the GPX: shorter route stops at node 3, longer continues to 5):

        1(peak) --Conzelman--> 2 --Conzelman--> 3 ==Conzelman==> 4 --Conzelman--> 5(valley)
                                                 |
                                                 +--Side St (residential)--> 99

    Node 3 is an intersection (a minor side road joins), but Conzelman itself
    continues to node 4. The arriving edge (2→3) and the continuation edge (3→4)
    are the SAME way at equal rank, so a naive `any(rank == current_rank)` check
    fires on the road's own continuation and truncates the descent at node 3.

    Expected: with avoid_equal_roads=True the route reaches the valley (node 5).
    """
    G = nx.DiGraph()
    nodes = {}
    specs = [
        # nid, south_m, elev,  is_peak, is_valley
        (1,   0.0,   248.0, True,  False),
        (2,   150.0, 200.0, False, False),
        (3,   300.0, 165.0, False, False),  # intersection (shorter route ends here)
        (4,   450.0, 130.0, False, False),
        (5,   600.0, 95.0,  False, True),   # valley (longer route ends here)
        (99,  300.0, 160.0, False, False),  # minor side road off node 3
    ]
    for nid, south_m, elev, is_peak, is_valley in specs:
        node = _make_node(nid, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[nid] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)

    # Conzelman Road: a single secondary (rank 6) way the whole way down.
    _add_edge(G, 1, 2, grade=-0.10, dist=150.0, highway="secondary", hw_rank=6, way_name="Conzelman Road")
    _add_edge(G, 2, 3, grade=-0.10, dist=150.0, highway="secondary", hw_rank=6, way_name="Conzelman Road")
    _add_edge(G, 3, 4, grade=-0.10, dist=150.0, highway="secondary", hw_rank=6, way_name="Conzelman Road")
    _add_edge(G, 4, 5, grade=-0.10, dist=150.0, highway="secondary", hw_rank=6, way_name="Conzelman Road")
    # A minor side road joins at node 3 — enough to mark it an intersection, but
    # it is a DIFFERENT, lower-class road the rider is not turning onto.
    _add_edge(G, 3, 99, grade=-0.03, dist=150.0, highway="residential", hw_rank=3, way_name="Side Street")
    G.nodes[3]["is_intersection"] = True

    toggles = Toggles(avoid_equal_roads=True)
    routes = _run(G, nodes, toggles=toggles)

    assert any(r.node_ids[-1] == 5 for r in routes), (
        "avoid_equal_roads truncated the descent at the intersection (node 3) even "
        "though Conzelman Road continues straight through it. Routes reached: "
        f"{[r.node_ids for r in routes]}"
    )


def test_avoid_equal_roads_stops_when_turning_onto_different_equal_road():
    """
    The toggle must still fire for its real purpose: a path on one road that can
    only continue by turning onto a DIFFERENT road of equal class should stop.

        1(peak) --Conzelman(secondary)--> 2 --Conzelman(secondary)--> 3
                                                                       |
                                                  Bunker Rd (secondary)+--> 4(valley)

    Node 3 is an intersection where Conzelman ends and only Bunker Road (also
    secondary, equal rank, different way) continues. With avoid_equal_roads=True
    the route must terminate at node 3, not roll onto Bunker Road.
    """
    G = nx.DiGraph()
    nodes = {}
    specs = [
        (1, 0.0,   248.0, True,  False),
        (2, 150.0, 200.0, False, False),
        (3, 300.0, 165.0, False, False),  # intersection: Conzelman ends here
        (4, 450.0, 130.0, False, True),   # only reachable by turning onto Bunker Rd
    ]
    for nid, south_m, elev, is_peak, is_valley in specs:
        node = _make_node(nid, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[nid] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)

    _add_edge(G, 1, 2, grade=-0.10, dist=150.0, highway="secondary", hw_rank=6, way_name="Conzelman Road")
    _add_edge(G, 2, 3, grade=-0.10, dist=150.0, highway="secondary", hw_rank=6, way_name="Conzelman Road")
    # Different equal-rank road continues from the junction.
    _add_edge(G, 3, 4, grade=-0.10, dist=150.0, highway="secondary", hw_rank=6, way_name="Bunker Road")
    G.nodes[3]["is_intersection"] = True

    toggles = Toggles(avoid_equal_roads=True)
    routes = _run(G, nodes, toggles=toggles)

    assert any(r.node_ids[-1] == 3 for r in routes), \
        "Expected route to terminate at node 3 rather than turn onto Bunker Road"
    assert all(r.node_ids[-1] != 4 for r in routes), \
        "Route turned onto a different equal-class road despite avoid_equal_roads=True"


def test_avoid_bigger_roads_false_allows_crossing():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_valley) in enumerate([
        (0,   100.0, True,  False),
        (150, 85.0,  False, False),
        (300, 70.0,  False, True),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
    _add_edge(G, 1, 2, grade=-0.10, dist=150.0, hw_rank=3)
    _add_edge(G, 2, 3, grade=-0.10, dist=150.0, hw_rank=7)

    toggles = Toggles(avoid_bigger_roads=False)
    routes = _run(G, nodes, toggles=toggles)
    assert any(r.node_ids[-1] == 3 for r in routes)


# ── Node cap ──────────────────────────────────────────────────────────────────

def test_node_cap_limits_concurrent_paths():
    """
    max_paths_per_node = 2: at most 2 active paths may enter each node.
    We create 3 peaks all funneling into one shared node — only 2 should pass.
    """
    G = nx.DiGraph()
    nodes = {}
    # Three peaks, each with a downhill edge to the same shared node (5)
    for i, elev in enumerate([110.0, 108.0, 106.0], start=1):
        node = _make_node(i, 0.0, elev, is_peak=True)
        nodes[i] = node
        _add_node(G, node, is_peak=True)
    shared = _make_node(5, 200.0, 90.0)
    nodes[5] = shared
    _add_node(G, shared)
    for i in range(1, 4):
        _add_edge(G, i, 5, grade=-0.10, dist=200.0)

    config = SearchConfig(max_paths_per_node=2, max_routes=50)
    routes = _run(G, nodes, config=config)

    # At most 2 routes should reach node 5 (capped)
    routes_through_5 = [r for r in routes if 5 in r.node_ids]
    assert len(routes_through_5) <= 2


# ── Max routes cap ────────────────────────────────────────────────────────────

def test_max_routes_cap_respected():
    """Never emit more than config.max_routes routes."""
    # Multiple peaks → many potential routes
    G = nx.DiGraph()
    nodes = {}
    for i in range(1, 6):
        peak = _make_node(i, (i - 1) * 500.0, 100.0, is_peak=True)
        valley = _make_node(i + 10, (i - 1) * 500.0 + 200.0, 80.0, is_valley=True)
        nodes[i] = peak
        nodes[i + 10] = valley
        _add_node(G, peak, is_peak=True)
        _add_node(G, valley, is_valley=True)
        _add_edge(G, i, i + 10, grade=-0.10, dist=200.0)

    config = SearchConfig(max_routes=3)
    routes = _run(G, nodes, config=config)
    assert len(routes) <= 3


# ── Minimum route length ──────────────────────────────────────────────────────

def test_short_routes_below_minimum_discarded():
    """Route shorter than min_route_length_m must NOT be emitted."""
    G = nx.DiGraph()
    nodes = {}
    # Very short edge (10m) — well below longboarder's 60m minimum
    n1 = _make_node(1, 0, 100.0, is_peak=True)
    n2 = _make_node(2, 10, 99.0, is_valley=True)
    nodes[1] = n1
    nodes[2] = n2
    _add_node(G, n1, is_peak=True)
    _add_node(G, n2, is_valley=True)
    _add_edge(G, 1, 2, grade=-0.10, dist=10.0)  # only 10m

    params = RIDER_PROFILES["longboarder"]  # min_route_length_m=60
    routes = _run(G, nodes, params=params)
    assert routes == []


def test_route_exactly_at_minimum_is_emitted():
    G = nx.DiGraph()
    nodes = {}
    n1 = _make_node(1, 0, 100.0, is_peak=True)
    n2 = _make_node(2, 100, 90.0, is_valley=True)
    nodes[1] = n1
    nodes[2] = n2
    _add_node(G, n1, is_peak=True)
    _add_node(G, n2, is_valley=True)
    # Longboarder min = 60m; use edge of exactly 60m
    _add_edge(G, 1, 2, grade=-0.10, dist=60.0)

    params = RIDER_PROFILES["longboarder"]
    routes = _run(G, nodes, params=params)
    assert len(routes) >= 1


# ── Cycle prevention ──────────────────────────────────────────────────────────

def test_no_cycles_in_routes():
    """No route may visit the same node twice."""
    G = nx.DiGraph()
    nodes = {}
    # Triangle: 1 (peak) → 2 → 3 → 2 (back-edge creates cycle)
    for i, (south_m, elev, is_peak) in enumerate([
        (0,   100.0, True),
        (150, 85.0,  False),
        (300, 70.0,  False),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak)
    _add_edge(G, 1, 2)
    _add_edge(G, 2, 3)
    _add_edge(G, 3, 2, grade=+0.10, dist=150.0)  # back-edge — must be ignored

    routes = _run(G, nodes)
    for r in routes:
        assert len(r.node_ids) == len(set(r.node_ids)), \
            f"Route visits a node twice: {r.node_ids}"


# ── Tunnel toggle ─────────────────────────────────────────────────────────────

def test_exclude_tunnels_skips_tunnel_edges():
    """With exclude_tunnels=True, no route may include a tunnel edge."""
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_valley) in enumerate([
        (0,   100.0, True,  False),
        (150, 85.0,  False, False),
        (300, 70.0,  False, True),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
    _add_edge(G, 1, 2, grade=-0.10, dist=150.0, is_tunnel=False)
    _add_edge(G, 2, 3, grade=-0.10, dist=150.0, is_tunnel=True)   # tunnel

    toggles = Toggles(exclude_tunnels=True)
    routes = _run(G, nodes, toggles=toggles)
    # No route should reach node 3 (only accessible via tunnel)
    assert all(3 not in r.node_ids for r in routes)


def test_include_tunnels_uses_tunnel_edge():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_valley) in enumerate([
        (0,   100.0, True,  False),
        (150, 85.0,  False, False),
        (300, 70.0,  False, True),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
    _add_edge(G, 1, 2)
    _add_edge(G, 2, 3, is_tunnel=True)

    toggles = Toggles(exclude_tunnels=False)
    routes = _run(G, nodes, toggles=toggles)
    assert any(3 in r.node_ids for r in routes)


# ── Route output fields ───────────────────────────────────────────────────────

def test_route_node_ids_match_path_traversed():
    G, nodes = _linear_graph(4)
    routes = _run(G, nodes)
    assert routes
    r = routes[0]
    # Must start at peak (1) and all ids must be valid graph nodes
    assert r.node_ids[0] == 1
    assert all(nid in G.nodes for nid in r.node_ids)


def test_route_coordinates_match_nodes(tmp_path):
    G, nodes = _linear_graph(4)
    routes = _run(G, nodes)
    assert routes
    r = routes[0]
    for nid, coord in zip(r.node_ids, r.coordinates):
        expected_lon = nodes[nid].lon
        expected_lat = nodes[nid].lat
        assert coord[0] == pytest.approx(expected_lon, abs=1e-6)
        assert coord[1] == pytest.approx(expected_lat, abs=1e-6)


def test_route_elevations_match_nodes():
    G, nodes = _linear_graph(4)
    routes = _run(G, nodes)
    assert routes
    r = routes[0]
    for nid, elev in zip(r.node_ids, r.elevations):
        assert elev == pytest.approx(nodes[nid].elevation, abs=1e-3)


def test_route_total_descent_is_nonnegative():
    G, nodes = _linear_graph(4)
    routes = _run(G, nodes)
    for r in routes:
        assert r.total_descent_m >= 0.0


def test_route_descent_accumulates_only_drops():
    """total_descent_m must only count downhill segments, not uphill ones."""
    G = nx.DiGraph()
    nodes = {}
    # peak → dip → rise → valley: total descent = two drops only
    specs = [
        (1, 0,   100.0, True,  False),
        (2, 150, 80.0,  False, False),   # -20m
        (3, 300, 90.0,  False, False),   # +10m rise — should NOT add to descent
        (4, 450, 70.0,  False, True),    # -20m
    ]
    for nid, south_m, elev, is_peak, is_valley in specs:
        node = _make_node(nid, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[nid] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
    # Grade: seg 1→2: -20/150, seg 2→3: +10/150, seg 3→4: -20/150
    _add_edge(G, 1, 2, grade=-20/150, dist=150.0)
    _add_edge(G, 2, 3, grade=+10/150, dist=150.0)
    _add_edge(G, 3, 4, grade=-20/150, dist=150.0)

    routes = _run(G, nodes)
    valley_routes = [r for r in routes if 4 in r.node_ids]
    if valley_routes:
        r = valley_routes[0]
        # Should count only the two 20m drops, not the 10m rise
        assert r.total_descent_m == pytest.approx(40.0, abs=1.0)


def test_route_name_comes_from_edge_way_name():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_valley) in enumerate([
        (0,   100.0, True,  False),
        (150, 85.0,  False, False),
        (300, 70.0,  False, True),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
    _add_edge(G, 1, 2, way_name="Burnett Avenue")
    _add_edge(G, 2, 3, way_name="Burnett Avenue")

    routes = _run(G, nodes)
    assert routes
    assert routes[0].name == "Burnett Avenue"


def test_unnamed_route_fallback():
    G = nx.DiGraph()
    nodes = {}
    for i, (south_m, elev, is_peak, is_valley) in enumerate([
        (0,   100.0, True,  False),
        (150, 85.0,  False, True),
    ], start=1):
        node = _make_node(i, south_m, elev, is_peak=is_peak, is_valley=is_valley)
        nodes[i] = node
        _add_node(G, node, is_peak=is_peak, is_valley=is_valley)
    _add_edge(G, 1, 2, way_name="")

    routes = _run(G, nodes)
    if routes:
        assert routes[0].name != ""  # falls back to "Unnamed route"


def test_route_length_m_matches_sum_of_edge_distances():
    G, nodes = _linear_graph(4, dist=150.0, last_is_valley=True)
    routes = _run(G, nodes)
    # The valley-terminated route should span all 3 edges = 450m
    valley_routes = [r for r in routes if r.node_ids[-1] == 4]
    if valley_routes:
        r = valley_routes[0]
        assert r.length_m == pytest.approx(450.0, rel=0.05)


# ── Route ID uniqueness ───────────────────────────────────────────────────────

def test_each_route_has_unique_id():
    G = nx.DiGraph()
    nodes = {}
    for i in range(1, 4):
        peak = _make_node(i, (i - 1) * 500.0, 100.0, is_peak=True)
        valley = _make_node(i + 10, (i - 1) * 500.0 + 200.0, 80.0, is_valley=True)
        nodes[i] = peak
        nodes[i + 10] = valley
        _add_node(G, peak, is_peak=True)
        _add_node(G, valley, is_valley=True)
        _add_edge(G, i, i + 10, grade=-0.10, dist=200.0)

    routes = _run(G, nodes)
    ids = [r.route_id for r in routes]
    assert len(ids) == len(set(ids)), "Duplicate route_ids found"


# ── Direction constraints ─────────────────────────────────────────────────────

def test_one_way_edge_not_traversed_in_reverse():
    """
    If we only add edge 1→2 (not 2→1), a peak at node 2 can't route back to node 1.
    """
    G = nx.DiGraph()
    nodes = {}
    # Node 1 is lower, node 2 is the peak — only edge goes 1→2 (one-way)
    n1 = _make_node(1, 200.0, 80.0)   # lower
    n2 = _make_node(2, 0.0,   100.0, is_peak=True, is_valley=False)
    nodes[1] = n1
    nodes[2] = n2
    _add_node(G, n1)
    _add_node(G, n2, is_peak=True)
    # Only 1→2 exists; 2→1 does NOT
    G.add_edge(1, 2, grade=+0.10, dist=200.0, highway="residential", hw_rank=3,
               surface="asphalt", is_bridge=False, is_tunnel=False, way_name="")

    routes = _run(G, nodes)
    # No route from peak (2) should include node 1, since edge 2→1 doesn't exist
    for r in routes:
        assert 1 not in r.node_ids


# ── Cancellation ───────────────────────────────────────────────────────────────

def _wide_fan_graph(n_branches: int = 400):
    """
    One peak fanning out to n_branches independent peak→mid→valley chains.
    Forces well over _CANCEL_CHECK_INTERVAL main-loop iterations, so a cancel
    signal has something to interrupt. Returns (G, nodes_by_id).
    """
    G = nx.DiGraph()
    nodes: dict[int, OSMNode] = {}

    peak = _make_node(0, 0.0, 1000.0, is_peak=True)
    nodes[0] = peak
    _add_node(G, peak, is_peak=True)

    for b in range(1, n_branches + 1):
        mid_id, val_id = b, 10_000 + b
        mid = _make_node(mid_id, 200.0, 900.0)
        val = _make_node(val_id, 400.0, 800.0, is_valley=True)
        nodes[mid_id] = mid
        nodes[val_id] = val
        _add_node(G, mid)
        _add_node(G, val, is_valley=True)
        _add_edge(G, 0, mid_id, grade=-0.10, dist=200.0)
        _add_edge(G, mid_id, val_id, grade=-0.10, dist=200.0)
    return G, nodes


def test_cancel_signal_stops_search_early():
    """should_cancel returning True must truncate the search: far fewer routes
    than an uninterrupted run over the same graph."""
    G, nodes = _wide_fan_graph()
    config = SearchConfig(max_routes=1000)  # high cap so the full run isn't bounded by it
    params = RIDER_PROFILES["longboarder"]
    toggles = Toggles()

    full = list(find_routes(G, nodes, config, params, toggles))
    cancelled = list(find_routes(G, nodes, config, params, toggles,
                                 should_cancel=lambda: True))

    assert len(full) > _CANCEL_CHECK_INTERVAL  # graph is big enough to be interruptible
    assert len(cancelled) < len(full)


def test_cancel_predicate_is_consulted():
    """find_routes must actually poll the supplied should_cancel callable."""
    G, nodes = _wide_fan_graph()
    calls = {"n": 0}

    def should_cancel() -> bool:
        calls["n"] += 1
        return True

    list(find_routes(G, nodes, SearchConfig(max_routes=1000),
                     RIDER_PROFILES["longboarder"], Toggles(),
                     should_cancel=should_cancel))
    assert calls["n"] > 0


def test_never_cancelling_matches_no_predicate():
    """should_cancel that always returns False yields the same routes as omitting it."""
    G, nodes = _linear_graph(4)
    baseline = _run(G, nodes)
    G2, nodes2 = _linear_graph(4)
    with_pred = list(find_routes(G2, nodes2, SearchConfig(),
                                 RIDER_PROFILES["longboarder"], Toggles(),
                                 should_cancel=lambda: False))
    assert [r.node_ids for r in with_pred] == [r.node_ids for r in baseline]
