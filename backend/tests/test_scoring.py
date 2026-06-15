"""
Tests for scoring.py — flow score computation.

Flow score starts at 100 and deducts penalties per occurrence:
  - stoplight:      -30
  - stop sign:      -10
  - bigger road:    -25
  - equal road:     -15 (only on way transitions, not enforced yet — tracked for later)
  - cobblestone:    -30
  - gravel:         -20
  - unpaved:        -15

Score clamped to [0, 100]. Letter grade: A≥80, B≥60, C≥40, D≥20, E≥1, F=0.

compute_flow_score(route, G, nodes_by_id, config) mutates and returns the route.
"""

import networkx as nx
import pytest
from ..config import SearchConfig, HIGHWAY_RANK
from ..types import OSMNode, Route
from ..scoring import compute_flow_score, score_to_grade


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_route(node_ids: list[int], edges: list[dict] | None = None) -> Route:
    """Minimal Route for testing. edges not used by Route itself — only for graph."""
    return Route(
        route_id="test",
        node_ids=node_ids,
        coordinates=[[0.0, 0.0]] * len(node_ids),
        elevations=[100.0] * len(node_ids),
        segment_distances=[50.0] * (len(node_ids) - 1),
        primary_highway="residential",
        name="Test Street",
        length_m=50.0 * (len(node_ids) - 1),
        total_descent_m=10.0,
    )


def _make_graph(
    node_ids: list[int],
    *,
    traffic_signals: set[int] | None = None,
    stop_signs: set[int] | None = None,
    highway: str = "residential",
    surface: str = "asphalt",
) -> tuple[nx.DiGraph, dict[int, OSMNode]]:
    """Build a simple linear graph for testing."""
    G = nx.DiGraph()
    nodes_by_id: dict[int, OSMNode] = {}
    hw_rank = HIGHWAY_RANK.get(highway, 3)

    for nid in node_ids:
        is_signal = nid in (traffic_signals or set())
        is_stop = nid in (stop_signs or set())
        node = OSMNode(id=nid, lat=37.7, lon=-122.4, elevation=100.0,
                       is_traffic_signal=is_signal, is_stop_sign=is_stop)
        nodes_by_id[nid] = node
        G.add_node(nid, elevation=100.0,
                   is_traffic_signal=is_signal, is_stop_sign=is_stop)

    for i in range(len(node_ids) - 1):
        u, v = node_ids[i], node_ids[i + 1]
        G.add_edge(u, v, highway=highway, hw_rank=hw_rank,
                   surface=surface, grade=-0.05, distance_m=50.0)

    return G, nodes_by_id


# ── score_to_grade helper ─────────────────────────────────────────────────────

def test_grade_A_at_80():
    assert score_to_grade(100.0) == "A"
    assert score_to_grade(80.0) == "A"

def test_grade_B_at_60():
    assert score_to_grade(79.9) == "B"
    assert score_to_grade(60.0) == "B"

def test_grade_C_at_40():
    assert score_to_grade(59.9) == "C"
    assert score_to_grade(40.0) == "C"

def test_grade_D_at_20():
    assert score_to_grade(39.9) == "D"
    assert score_to_grade(20.0) == "D"

def test_grade_E_at_1():
    assert score_to_grade(19.9) == "E"
    assert score_to_grade(1.0) == "E"

def test_grade_F_at_zero():
    assert score_to_grade(0.0) == "F"


# ── Clean route ───────────────────────────────────────────────────────────────

def test_clean_route_scores_100():
    nids = [1, 2, 3, 4]
    route = _make_route(nids)
    G, nodes = _make_graph(nids)
    config = SearchConfig()
    result = compute_flow_score(route, G, nodes, config)
    assert result.flow_score == pytest.approx(100.0)
    assert result.flow_grade == "A"

def test_clean_route_returns_same_route_object():
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids)
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result is route


# ── Traffic signal penalty ────────────────────────────────────────────────────

def test_one_stoplight_deducts_30():
    nids = [1, 2, 3, 4]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, traffic_signals={2})
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(70.0)
    assert result.flow_grade == "B"

def test_two_stoplights_deducts_60():
    nids = [1, 2, 3, 4]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, traffic_signals={2, 3})
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(40.0)
    assert result.flow_grade == "C"

def test_stoplight_at_start_node_not_penalized():
    """The first node is the start; don't penalize traffic signal at the top of the hill."""
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, traffic_signals={1})
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(100.0)


# ── Stop sign penalty ─────────────────────────────────────────────────────────

def test_one_stop_sign_deducts_10():
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, stop_signs={2})
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(90.0)
    assert result.flow_grade == "A"

def test_stoplight_and_stop_sign_stack():
    nids = [1, 2, 3, 4]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, traffic_signals={2}, stop_signs={3})
    result = compute_flow_score(route, G, nodes, SearchConfig())
    # 100 - 30 (light) - 10 (stop sign) = 60
    assert result.flow_score == pytest.approx(60.0)


# ── Surface penalties ─────────────────────────────────────────────────────────

def test_cobblestone_surface_deducts_30():
    nids = [1, 2]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, surface="cobblestone")
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(70.0)

def test_cobblestone_two_segments_deducts_60():
    """Two cobblestone segments each deduct independently."""
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, surface="cobblestone")
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(40.0)

def test_gravel_surface_deducts_20():
    nids = [1, 2]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, surface="gravel")
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(80.0)

def test_unpaved_surface_deducts_15():
    nids = [1, 2]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, surface="unpaved")
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(85.0)

def test_mixed_surface_deducts_once_per_segment():
    """Cobble on one segment, asphalt on the other — only one cobble penalty."""
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, surface="asphalt")
    # Override edge (1→2) to cobblestone
    G[1][2]["surface"] = "cobblestone"
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(70.0)

def test_asphalt_no_penalty():
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, surface="asphalt")
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(100.0)

def test_empty_surface_no_penalty():
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, surface="")
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(100.0)


# ── Bigger road crossing ──────────────────────────────────────────────────────

def test_bigger_road_crossing_deducts_25():
    """Route transitions from residential (rank 3) to primary (rank 7)."""
    nids = [1, 2, 3, 4]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, highway="residential")
    # Edge 2→3 crosses onto a primary road
    G[2][3]["hw_rank"] = HIGHWAY_RANK["primary"]
    G[2][3]["highway"] = "primary"
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(75.0)


# ── Score clamping ────────────────────────────────────────────────────────────

def test_score_clamped_at_zero():
    """Enough penalties should clamp to 0, not go negative."""
    nids = [1, 2, 3, 4, 5]
    route = _make_route(nids)
    G, nodes = _make_graph(nids,
                           traffic_signals={2, 3, 4},  # 3 × 30 = 90
                           surface="cobblestone")      # + 30 = 120 total penalties → clamp
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score == pytest.approx(0.0)
    assert result.flow_grade == "F"

def test_score_not_above_100():
    nids = [1, 2]
    route = _make_route(nids)
    G, nodes = _make_graph(nids)
    result = compute_flow_score(route, G, nodes, SearchConfig())
    assert result.flow_score <= 100.0


# ── Custom config penalties ───────────────────────────────────────────────────

def test_custom_stoplight_penalty():
    config = SearchConfig(flow_penalty_stoplight=50.0)
    nids = [1, 2, 3]
    route = _make_route(nids)
    G, nodes = _make_graph(nids, traffic_signals={2})
    result = compute_flow_score(route, G, nodes, config)
    assert result.flow_score == pytest.approx(50.0)
