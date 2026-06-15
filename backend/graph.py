"""
Build a sparse directed graph from OSM ways and elevation-enriched nodes.

Node categories added as graph attributes:
  - intersection: degree >= 3 in the undirected sense
  - peak: local elevation maximum within peak_search_radius_m
  - valley: local elevation minimum within peak_search_radius_m

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


# Projected node tuple: (node_id, x_m, y_m, lat, lon, elevation)
_ProjNode = tuple[int, float, float, float, float, float]


def _project_nodes(pts: list[tuple[int, float, float, float]]) -> list[_ProjNode]:
    """Project (id, lat, lon, elev) to local equirectangular metres for bucketing.

    Planar distance matches haversine to <0.1% at city scale; it is only used to
    choose grid cells, so the radius test itself still uses haversine.
    """
    if not pts:
        return []
    mean_lat = sum(lat for _, lat, _, _ in pts) / len(pts)
    m_per_lat = 111_320.0
    m_per_lon = 111_320.0 * math.cos(math.radians(mean_lat)) or 1.0
    return [(nid, lon * m_per_lon, lat * m_per_lat, lat, lon, elev)
            for nid, lat, lon, elev in pts]


def _nearby_elevations(proj: list[_ProjNode], radius_m: float) -> dict[int, list[float]]:
    """Map each node id → elevations of all other nodes within radius_m (haversine).

    A uniform grid of cell size radius_m means only the 3×3 surrounding cells are
    scanned per node — O(N·k) instead of the previous O(N²) all-pairs scan.
    """
    grid: dict[tuple[int, int], list[_ProjNode]] = {}
    for item in proj:
        _, x, y, _, _, _ = item
        grid.setdefault((int(x // radius_m), int(y // radius_m)), []).append(item)

    result: dict[int, list[float]] = {}
    for nid, x, y, lat, lon, _ in proj:
        cx, cy = int(x // radius_m), int(y // radius_m)
        nearby: list[float] = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for onid, _ox, _oy, olat, olon, oelev in grid.get((cx + dx, cy + dy), ()):
                    if onid != nid and _haversine_m(lat, lon, olat, olon) <= radius_m:
                        nearby.append(oelev)
        result[nid] = nearby
    return result


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
            is_peak=False, is_valley=False, is_intersection=False,
        )

    # ── 2. Add directed edges from ways ──────────────────────────────────────
    for way in ways:
        nids = [nid for nid in way.node_ids if nid in G]
        if len(nids) < 2:
            continue

        hw_rank = HIGHWAY_RANK.get(way.highway, 3)

        if way.is_bridge or way.is_tunnel:
            n0, n1 = nodes_by_id[nids[0]], nodes_by_id[nids[-1]]
            span = _haversine_m(n0.lat, n0.lon, n1.lat, n1.lon)
            if span > config.max_bridge_span_m:
                continue  # too long (e.g. Golden Gate = 2.7 km); not hill bomb terrain
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

    # Project once; reuse for both the primary and the wider ridge-top pass.
    proj = _project_nodes(
        [(nid, n.lat, n.lon, n.elevation)
         for nid in G.nodes if (n := nodes_by_id.get(nid)) is not None]
    )
    elev_by_id = {nid: elev for nid, _x, _y, _lat, _lon, elev in proj}

    # Primary: strict local maxima — node must be at least min_delta above ALL
    # nearby nodes within r.  Works well for isolated hilltops but fails for
    # ridge tops where many nodes share essentially the same elevation.
    primary_nearby = _nearby_elevations(proj, r)
    for nid, elev in elev_by_id.items():
        nearby = primary_nearby[nid]
        if not nearby:
            continue
        if elev - max(nearby) >= min_delta:
            G.nodes[nid]["is_peak"] = True
        elif min(nearby) - elev >= min_delta:
            G.nodes[nid]["is_valley"] = True

    # Secondary: ridge-top / plateau peaks — catches roads that run along a
    # ridgeline where all nodes within the primary radius share the same
    # elevation.  A node is a ridge peak if it is within 0.5 m of the local
    # maximum in a wider 200 m neighbourhood AND that neighbourhood has at
    # least min_delta*3 of elevation variation (a real hill, not flat terrain).
    _WIDE_R = 200.0
    _WIDE_DELTA = min_delta * 3

    wide_nearby = _nearby_elevations(proj, _WIDE_R)
    for nid, elev in elev_by_id.items():
        if G.nodes[nid].get("is_peak"):
            continue
        nearby = wide_nearby[nid]
        if not nearby:
            continue
        if elev >= max(nearby) - 0.5 and elev - min(nearby) >= _WIDE_DELTA:
            G.nodes[nid]["is_peak"] = True

    return G
