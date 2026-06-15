"""
Build a sparse directed graph from OSM ways and elevation-enriched nodes.

Node categories added as graph attributes:
  - intersection: degree >= 3 in the undirected sense
  - peak: local elevation maximum within peak_search_radius_m
  - valley: local elevation minimum within peak_search_radius_m
  - inflection: grade change >= grade_inflection_threshold between adjacent segments

Edges carry: distance_m, grade (rise/run, signed), highway, surface, is_bridge, is_tunnel.
"""

import math
import networkx as nx
from .types import OSMNode, OSMWay
from .config import SearchConfig, HIGHWAY_RANK


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    R = 6_371_000.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return R * 2 * math.asin(math.sqrt(a))


def _segment_grade(n1: OSMNode, n2: OSMNode) -> float:
    dist = _haversine_m(n1.lat, n1.lon, n2.lat, n2.lon)
    if dist < 0.1:
        return 0.0
    return (n2.elevation - n1.elevation) / dist


def build_graph(
    nodes_by_id: dict[int, OSMNode],
    ways: list[OSMWay],
    config: SearchConfig,
) -> nx.DiGraph:
    G = nx.DiGraph()

    # ── 1. Add all way-referenced nodes ──────────────────────────────────────
    way_node_ids: set[int] = set()
    for way in ways:
        way_node_ids.update(way.node_ids)

    for nid in way_node_ids:
        if nid not in nodes_by_id:
            continue
        n = nodes_by_id[nid]
        G.add_node(nid,
            lat=n.lat, lon=n.lon, elevation=n.elevation,
            is_traffic_signal=n.is_traffic_signal,
            is_stop_sign=n.is_stop_sign,
            is_peak=False, is_valley=False, is_inflection=False,
        )

    # ── 2. Add directed edges from ways ──────────────────────────────────────
    for way in ways:
        nids = [nid for nid in way.node_ids if nid in G]
        if len(nids) < 2:
            continue

        hw_rank = HIGHWAY_RANK.get(way.highway, 3)

        if way.is_bridge or way.is_tunnel:
            # Straight-line segment: only start→end (and reverse if two-way)
            pairs = [(nids[0], nids[-1])]
            if not way.oneway and not way.oneway_reverse:
                pairs.append((nids[-1], nids[0]))
        else:
            # Full sequence of node pairs
            pairs = []
            for i in range(len(nids) - 1):
                a, b = nids[i], nids[i + 1]
                if way.oneway_reverse:
                    pairs.append((b, a))
                elif way.oneway:
                    pairs.append((a, b))
                else:
                    pairs.append((a, b))
                    pairs.append((b, a))

        for src, dst in pairs:
            n_src = nodes_by_id[src]
            n_dst = nodes_by_id[dst]
            dist = _haversine_m(n_src.lat, n_src.lon, n_dst.lat, n_dst.lon)
            grade = _segment_grade(n_src, n_dst)
            # Very short segments (< 15m) between dense shape points can produce
            # extreme apparent grades from ~1m elevation raster noise.  Cap at a
            # realistic road maximum so noise spikes don't kill pathfinding.
            grade = max(-0.25, min(0.25, grade))
            G.add_edge(src, dst,
                distance_m=dist,
                grade=grade,
                highway=way.highway,
                hw_rank=hw_rank,
                surface=way.surface,
                is_bridge=way.is_bridge,
                is_tunnel=way.is_tunnel,
                way_name=way.name,
            )

    # ── 3. Tag intersection nodes (undirected degree >= 3) ───────────────────
    undirected_degree: dict[int, set[int]] = {}
    for u, v in G.edges():
        undirected_degree.setdefault(u, set()).add(v)
        undirected_degree.setdefault(v, set()).add(u)

    for nid, neighbors in undirected_degree.items():
        if nid in G and len(neighbors) >= 3:
            G.nodes[nid]["is_intersection"] = True

    # ── 4. Tag peak and valley nodes ─────────────────────────────────────────
    r = config.peak_search_radius_m
    min_delta = config.peak_min_elevation_delta_m

    # Primary: strict local maxima — node must be at least min_delta above ALL
    # nearby nodes within r.  Works well for isolated hilltops but fails for
    # ridge tops where many nodes share essentially the same elevation.
    for nid in list(G.nodes):
        n = nodes_by_id.get(nid)
        if n is None:
            continue
        elev = n.elevation

        nearby_elevs = []
        for other_id in G.nodes:
            if other_id == nid:
                continue
            o = nodes_by_id.get(other_id)
            if o is None:
                continue
            d = _haversine_m(n.lat, n.lon, o.lat, o.lon)
            if d <= r:
                nearby_elevs.append(o.elevation)

        if not nearby_elevs:
            continue

        max_nearby = max(nearby_elevs)
        min_nearby = min(nearby_elevs)

        if elev - max_nearby >= min_delta:
            G.nodes[nid]["is_peak"] = True
        elif min_nearby - elev >= min_delta:
            G.nodes[nid]["is_valley"] = True

    # Secondary: ridge-top / plateau peaks — catches roads that run along a
    # ridgeline where all nodes within the primary radius share the same
    # elevation.  A node is a ridge peak if it is within 0.5 m of the local
    # maximum in a wider 200 m neighbourhood AND that neighbourhood has at
    # least min_delta*3 of elevation variation (a real hill, not flat terrain).
    _WIDE_R = 200.0
    _WIDE_DELTA = min_delta * 3

    for nid in list(G.nodes):
        if G.nodes[nid].get("is_peak"):
            continue
        n = nodes_by_id.get(nid)
        if n is None:
            continue
        elev = n.elevation

        wide_elevs = []
        for other_id in G.nodes:
            if other_id == nid:
                continue
            o = nodes_by_id.get(other_id)
            if o is None:
                continue
            if _haversine_m(n.lat, n.lon, o.lat, o.lon) <= _WIDE_R:
                wide_elevs.append(o.elevation)

        if not wide_elevs:
            continue

        wide_max = max(wide_elevs)
        wide_min = min(wide_elevs)

        if elev >= wide_max - 0.5 and elev - wide_min >= _WIDE_DELTA:
            G.nodes[nid]["is_peak"] = True

    # ── 5. Tag grade inflection nodes ────────────────────────────────────────
    threshold = config.grade_inflection_threshold
    for nid in G.nodes:
        in_grades = [G[u][nid]["grade"] for u in G.predecessors(nid) if "grade" in G[u][nid]]
        out_grades = [G[nid][v]["grade"] for v in G.successors(nid) if "grade" in G[nid][v]]
        if in_grades and out_grades:
            avg_in = sum(in_grades) / len(in_grades)
            avg_out = sum(out_grades) / len(out_grades)
            if abs(avg_out - avg_in) >= threshold:
                G.nodes[nid]["is_inflection"] = True

    return G
