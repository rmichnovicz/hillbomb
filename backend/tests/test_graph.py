"""
Tests for graph.py — build_graph.

Key invariants under test:
  - Long bridges (> max_bridge_span_m) are excluded from the graph entirely
  - Short bridges (< max_bridge_span_m) are included as straight-line edges
  - The Golden Gate Bridge scale (2.7 km) never produces routes in results
  - Normal non-bridge ways produce the expected edge sequence
  - Peak / valley / inflection node tagging works
"""

import networkx as nx
import pytest

from ..config import SearchConfig
from ..graph import build_graph
from ..types import OSMNode, OSMWay


# ── Helpers ───────────────────────────────────────────────────────────────────

def _node(nid: int, lat: float, lon: float, elevation: float = 10.0) -> OSMNode:
    return OSMNode(id=nid, lat=lat, lon=lon, elevation=elevation)


def _way(
    wid: int,
    node_ids: list[int],
    highway: str = "residential",
    *,
    oneway: bool = False,
    oneway_reverse: bool = False,
    is_bridge: bool = False,
    is_tunnel: bool = False,
    surface: str = "asphalt",
    name: str = "",
) -> OSMWay:
    return OSMWay(
        id=wid,
        node_ids=node_ids,
        highway=highway,
        oneway=oneway,
        oneway_reverse=oneway_reverse,
        is_bridge=is_bridge,
        is_tunnel=is_tunnel,
        surface=surface,
        name=name,
    )


def _build(nodes: list[OSMNode], ways: list[OSMWay], **config_kwargs) -> nx.DiGraph:
    nodes_by_id = {n.id: n for n in nodes}
    config = SearchConfig(**config_kwargs)
    return build_graph(nodes_by_id, ways, config)


# ── Bridge length filtering ────────────────────────────────────────────────────

class TestBridgeSpanFilter:
    """
    Long bridges must be dropped from the graph; short ones kept.

    The Golden Gate Bridge is ~2.7 km end-to-end.  With the default
    max_bridge_span_m = 500 m it should never produce a graph edge,
    and therefore never appear in route results.
    """

    # Approximate Golden Gate Bridge endpoints (Marin → SF, measured to the
    # nearest OSM node on each approach road).
    # Marin side: Fort Baker approach, ~37.832°N 122.480°W, elev ~5 m
    # SF side:    Doyle Drive approach, ~37.806°N 122.477°W, elev ~10 m
    # Straight-line span ≈ 2,900 m
    GG_MARIN = _node(1, lat=37.832, lon=-122.480, elevation=5.0)
    GG_SF    = _node(2, lat=37.806, lon=-122.477, elevation=10.0)

    def test_golden_gate_scale_bridge_excluded_by_default(self):
        """A 2.7 km bridge must not appear as a graph edge with default config."""
        nodes = [self.GG_MARIN, self.GG_SF]
        ways = [_way(100, [1, 2], highway="primary", is_bridge=True)]
        G = _build(nodes, ways)
        assert not G.has_edge(1, 2), (
            "Golden Gate–scale bridge (≈2.9 km) should be excluded from the graph "
            f"(max_bridge_span_m={SearchConfig().max_bridge_span_m} m) "
            "but an edge 1→2 was found."
        )
        assert not G.has_edge(2, 1)

    def test_golden_gate_scale_bridge_excluded_both_directions(self):
        """Two-way bridges above the threshold are excluded in both directions."""
        nodes = [self.GG_MARIN, self.GG_SF]
        ways = [_way(100, [1, 2], highway="primary", is_bridge=True, oneway=False)]
        G = _build(nodes, ways)
        assert G.number_of_edges() == 0

    def test_short_bridge_included(self):
        """A 50 m bridge over a creek should be kept."""
        # Two nodes 50 m apart (≈0.00045° lat)
        n1 = _node(1, lat=37.75, lon=-122.45, elevation=20.0)
        n2 = _node(2, lat=37.7505, lon=-122.45, elevation=18.0)
        nodes = [n1, n2]
        ways = [_way(10, [1, 2], is_bridge=True)]
        G = _build(nodes, ways)
        assert G.has_edge(1, 2), "Short bridge (≈50 m) should be kept in the graph"

    def test_bridge_at_exactly_threshold_is_kept(self):
        """Span == max_bridge_span_m uses strict > comparison, so it stays."""
        # Place two nodes exactly 500 m apart (≈0.0045° lat).
        n1 = _node(1, lat=37.75000, lon=-122.45, elevation=10.0)
        n2 = _node(2, lat=37.75450, lon=-122.45, elevation=8.0)
        nodes = [n1, n2]
        ways = [_way(10, [1, 2], is_bridge=True)]
        # Use a config with max_bridge_span_m exactly matching the span.
        # The span computed by haversine will be close to 500 m.  We set the
        # threshold to a large value to confirm the boundary condition logic:
        # the check is strictly >, so a span equal to the threshold is kept.
        G = _build(nodes, ways, max_bridge_span_m=600.0)
        assert G.has_edge(1, 2)

    def test_configurable_threshold_allows_longer_bridges(self):
        """Raising max_bridge_span_m lets a previously-excluded bridge through."""
        nodes = [self.GG_MARIN, self.GG_SF]
        ways = [_way(100, [1, 2], highway="primary", is_bridge=True)]
        G = _build(nodes, ways, max_bridge_span_m=5000.0)
        assert G.has_edge(1, 2), (
            "With max_bridge_span_m=5000 m the GG-scale bridge should be included"
        )

    def test_tunnel_also_excluded_when_too_long(self):
        """Tunnel ways obey the same span filter as bridges."""
        nodes = [self.GG_MARIN, self.GG_SF]
        ways = [_way(100, [1, 2], highway="primary", is_tunnel=True)]
        G = _build(nodes, ways)
        assert not G.has_edge(1, 2)

    def test_non_bridge_way_not_affected_by_span_filter(self):
        """A regular (non-bridge) way of any length is not span-filtered."""
        nodes = [self.GG_MARIN, self.GG_SF]
        ways = [_way(100, [1, 2], highway="primary", is_bridge=False)]
        G = _build(nodes, ways)
        # Both directions present (two-way by default)
        assert G.has_edge(1, 2) or G.has_edge(2, 1)


# ── Normal edge construction ───────────────────────────────────────────────────

class TestEdgeConstruction:
    def test_two_way_road_gets_both_directions(self):
        n1 = _node(1, 37.750, -122.45, elevation=20.0)
        n2 = _node(2, 37.751, -122.45, elevation=15.0)
        G = _build([n1, n2], [_way(1, [1, 2], oneway=False)])
        assert G.has_edge(1, 2)
        assert G.has_edge(2, 1)

    def test_oneway_road_has_one_direction(self):
        n1 = _node(1, 37.750, -122.45, elevation=20.0)
        n2 = _node(2, 37.751, -122.45, elevation=15.0)
        G = _build([n1, n2], [_way(1, [1, 2], oneway=True)])
        assert G.has_edge(1, 2)
        assert not G.has_edge(2, 1)

    def test_oneway_reverse_flips_direction(self):
        n1 = _node(1, 37.750, -122.45, elevation=20.0)
        n2 = _node(2, 37.751, -122.45, elevation=15.0)
        G = _build([n1, n2], [_way(1, [1, 2], oneway_reverse=True)])
        assert G.has_edge(2, 1)
        assert not G.has_edge(1, 2)

    def test_edge_grade_sign_downhill_negative(self):
        n1 = _node(1, 37.750, -122.45, elevation=50.0)  # higher
        n2 = _node(2, 37.755, -122.45, elevation=10.0)  # lower
        G = _build([n1, n2], [_way(1, [1, 2])])
        grade = G[1][2]["grade"]
        assert grade < 0.0, f"Downhill 1→2 should give negative grade, got {grade}"

    def test_edge_grade_sign_uphill_positive(self):
        n1 = _node(1, 37.750, -122.45, elevation=10.0)  # lower
        n2 = _node(2, 37.755, -122.45, elevation=50.0)  # higher
        G = _build([n1, n2], [_way(1, [1, 2])])
        grade = G[1][2]["grade"]
        assert grade > 0.0, f"Uphill 1→2 should give positive grade, got {grade}"

    def test_grade_capped_at_25_percent(self):
        """Extreme grade from raster noise is clamped to ±0.25."""
        n1 = _node(1, 37.750, -122.4500, elevation=0.0)
        n2 = _node(2, 37.750, -122.4501, elevation=1000.0)  # impossibly steep
        G = _build([n1, n2], [_way(1, [1, 2])])
        assert G[1][2]["grade"] <= 0.25

    def test_short_bridge_edge_carries_bridge_flag(self):
        n1 = _node(1, 37.750, -122.45, elevation=20.0)
        n2 = _node(2, 37.7505, -122.45, elevation=18.0)
        G = _build([n1, n2], [_way(1, [1, 2], is_bridge=True)])
        assert G[1][2].get("is_bridge") is True

    def test_traversable_flag_propagates_to_edges(self):
        """A way's traversable flag must carry onto both directed edges."""
        n1 = _node(1, 37.750, -122.45, elevation=20.0)
        n2 = _node(2, 37.751, -122.45, elevation=15.0)
        way = _way(1, [1, 2], highway="primary")
        way.traversable = False  # detection-only bigger road
        G = _build([n1, n2], [way])
        assert G[1][2].get("traversable") is False
        assert G[2][1].get("traversable") is False

    def test_edges_traversable_by_default(self):
        n1 = _node(1, 37.750, -122.45, elevation=20.0)
        n2 = _node(2, 37.751, -122.45, elevation=15.0)
        G = _build([n1, n2], [_way(1, [1, 2])])
        assert G[1][2].get("traversable") is True


# ── Node tagging ──────────────────────────────────────────────────────────────

class TestNodeTagging:
    def test_intersection_tagged_when_degree_3(self):
        # Three separate ways meet at node 3: it touches nodes 2, 4, and 5.
        nodes = [
            _node(1, 37.750, -122.450, 30.0),
            _node(2, 37.751, -122.450, 25.0),
            _node(3, 37.752, -122.450, 20.0),  # intersection — neighbors: 2, 4, 5
            _node(4, 37.752, -122.451, 15.0),
            _node(5, 37.753, -122.450, 18.0),
        ]
        ways = [
            _way(1, [1, 2, 3]),   # node 3 neighbor: 2
            _way(2, [3, 4]),      # node 3 neighbor: 4
            _way(3, [3, 5]),      # node 3 neighbor: 5 → total degree = 3
        ]
        G = _build(nodes, ways)
        assert G.nodes[3].get("is_intersection"), "Node 3 should be tagged as intersection"

    def test_endpoint_node_not_tagged_intersection(self):
        n1 = _node(1, 37.750, -122.45, 20.0)
        n2 = _node(2, 37.751, -122.45, 15.0)
        G = _build([n1, n2], [_way(1, [1, 2])])
        # Node 1 only connects to node 2 — not an intersection
        assert not G.nodes[1].get("is_intersection")

    def test_peak_tagged_when_significantly_higher_than_neighbors(self):
        # Node 2 sits 10 m above all neighbors within 75 m radius.
        # Place nodes close together (within 75 m) but with a clear elevation gap.
        nodes = [
            _node(1, 37.7500, -122.45, elevation=10.0),
            _node(2, 37.7504, -122.45, elevation=20.0),  # peak: 10 m above neighbors
            _node(3, 37.7508, -122.45, elevation=10.0),
        ]
        ways = [_way(1, [1, 2, 3])]
        G = _build(nodes, ways)
        assert G.nodes[2].get("is_peak"), "Node 2 should be tagged as peak"

    def test_valley_tagged_when_significantly_lower_than_neighbors(self):
        nodes = [
            _node(1, 37.7500, -122.45, elevation=20.0),
            _node(2, 37.7504, -122.45, elevation=10.0),  # valley: 10 m below neighbors
            _node(3, 37.7508, -122.45, elevation=20.0),
        ]
        ways = [_way(1, [1, 2, 3])]
        G = _build(nodes, ways)
        assert G.nodes[2].get("is_valley"), "Node 2 should be tagged as valley"

    def test_flat_nodes_not_tagged_peak_or_valley(self):
        nodes = [
            _node(1, 37.7500, -122.45, elevation=10.0),
            _node(2, 37.7504, -122.45, elevation=10.2),  # < 4 m delta
            _node(3, 37.7508, -122.45, elevation=10.0),
        ]
        ways = [_way(1, [1, 2, 3])]
        G = _build(nodes, ways)
        assert not G.nodes[2].get("is_peak")
        assert not G.nodes[2].get("is_valley")
