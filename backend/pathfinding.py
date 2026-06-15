"""
Greedy descent pathfinding on the route graph.

Priority queue entry: (priority_tuple, path_id, sequence_number, node_id)
Priority tuple: (-is_extending, -arrival_speed, -elevation)
  - min-heap with negated values → extending beats new, faster beats slower, higher beats lower

Lazy deletion: each path has a sequence_number; stale queue entries are discarded on pop.
"""

import heapq
import math
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from .types import OSMNode, OSMWay, Route
from .config import SearchConfig, RiderParams, Toggles, HIGHWAY_RANK
from .graph import _haversine_m
import networkx as nx


# How often find_routes polls should_cancel(), in main-loop iterations. The check
# is cheap but the loop can run millions of times, so we sample rather than poll
# every pop. At ~microseconds per iteration this bounds cancellation latency in the
# search stage to well under a millisecond.
_CANCEL_CHECK_INTERVAL = 256


def build_route_from_data(
    node_ids: list[int],
    coordinates: list[list[float]],
    elevations: list[float],
    distances: list[float],
    G: nx.DiGraph,
    start_node_id: int | None = None,
) -> Route:
    """
    Construct a Route from pre-computed geometry slices.
    Does not apply a minimum-length filter — caller is responsible.
    Used by the pipeline when re-assembling sub-routes after physics splitting.
    """
    length_m = sum(distances)
    total_descent = sum(
        max(elevations[i] - elevations[i + 1], 0.0)
        for i in range(len(elevations) - 1)
    )
    avg_grade = ((elevations[-1] - elevations[0]) / length_m * 100.0) if length_m > 0 else 0.0

    primary_hw = "residential"
    best_grade_abs = 0.0
    route_name = ""
    surface_distances: dict[str, float] = {}
    for i in range(len(node_ids) - 1):
        u, v = node_ids[i], node_ids[i + 1]
        if G.has_edge(u, v):
            ed = G[u][v]
            if abs(ed.get("grade", 0)) > best_grade_abs:
                best_grade_abs = abs(ed.get("grade", 0))
                primary_hw = ed.get("highway", "residential")
                route_name = ed.get("way_name", "")
            surf = ed.get("surface", "") or ""
            seg_dist = distances[i] if i < len(distances) else 0.0
            surface_distances[surf] = surface_distances.get(surf, 0.0) + seg_dist

    if not route_name:
        for i in range(len(node_ids) - 1):
            u, v = node_ids[i], node_ids[i + 1]
            if G.has_edge(u, v):
                route_name = G[u][v].get("way_name", "")
                if route_name:
                    break

    return Route(
        route_id=str(uuid.uuid4()),
        node_ids=node_ids,
        coordinates=coordinates,
        elevations=elevations,
        segment_distances=distances,
        primary_highway=primary_hw,
        start_node_id=start_node_id if start_node_id is not None else (node_ids[0] if node_ids else 0),
        name=route_name or "Unnamed route",
        length_m=length_m,
        total_descent_m=total_descent,
        avg_grade_pct=avg_grade,
        surface_distances=surface_distances,
    )


# ── Physics helper (grade-proxy speed, no air resistance) ────────────────────

def _speed_at_node(
    prev_speed_ms: float,
    grade: float,
    dist_m: float,
    params: RiderParams,
) -> float:
    """Estimate arrival speed using a simple kinematic model (no air drag)."""
    g = 9.81
    # grade is rise/run: negative = downhill (propulsive).
    # Net force = gravity component - rolling resistance (always opposes motion;
    # speed is non-negative so the resistance term is simply +crr).
    # Negate grade so downhill gives positive acceleration.
    net_accel = g * (-grade - params.crr_pathfinding)
    # v² = u² + 2as
    v2 = prev_speed_ms ** 2 + 2 * net_accel * dist_m
    return math.sqrt(max(v2, 0.0))


# ── Path state ────────────────────────────────────────────────────────────────

@dataclass
class _Path:
    path_id: str
    node_ids: list[int]
    sequence_number: int = 0
    arrival_speed_ms: float = 0.0
    total_dist_m: float = 0.0
    total_descent_m: float = 0.0
    active: bool = True
    stop_events: list[str] = field(default_factory=list)
    # Number of times the path has changed highway type or surface type.
    # Used as a primary sort key so type-consistent continuations are explored
    # (and emitted) before type-changing detours; dedup then discards the latter.
    type_changes: int = 0


# ── Main algorithm ────────────────────────────────────────────────────────────

def find_routes(
    G: nx.DiGraph,
    nodes_by_id: dict[int, OSMNode],
    config: SearchConfig,
    params: RiderParams,
    toggles: Toggles,
    should_cancel: Callable[[], bool] | None = None,
) -> Iterator[Route]:
    """
    Greedy descent from all peak nodes. Yields Route objects as paths finalize.

    should_cancel, if given, is polled inside the main expansion loop; when it
    becomes true the search stops generating immediately (the generator returns).
    Used so a disconnected client's request stops searching almost at once rather
    than running until max_routes or heap exhaustion.
    """
    min_speed_ms = params.min_continue_speed_kmh / 3.6

    # paths_by_id: path_id → _Path
    paths_by_id: dict[str, _Path] = {}
    # node_path_count: node_id → count of active paths currently at/through that node
    node_path_count: dict[int, int] = {}

    heap: list[tuple] = []
    routes_emitted = 0

    # Nodes already reached by any active path. A peak seed whose node is already
    # in this set would produce a sub-route of an existing path, so it is skipped.
    visited_nodes: set[int] = set()

    def _push(path: _Path, node_id: int, is_extending: bool) -> None:
        elev = G.nodes[node_id].get("elevation", 0)
        priority = (
            0 if is_extending else 1,          # extending first (min-heap: 0 < 1)
            path.type_changes,                 # fewer road/surface-type changes first
            -path.arrival_speed_ms,            # faster first
            -elev,                             # higher first
        )
        heapq.heappush(heap, (priority, path.path_id, path.sequence_number, node_id))

    def _finalize(path: _Path) -> Route | None:
        if path.total_dist_m < params.min_route_length_m:
            return None
        node_ids = path.node_ids
        coords = [[nodes_by_id[n].lon, nodes_by_id[n].lat] for n in node_ids if n in nodes_by_id]
        elevs  = [nodes_by_id[n].elevation for n in node_ids if n in nodes_by_id]
        # Reuse the distance the graph already stored (and that pathfinding scored
        # on); fall back to haversine only if the edge is somehow missing.
        dists: list[float] = []
        for i in range(len(node_ids) - 1):
            u, v = node_ids[i], node_ids[i + 1]
            if G.has_edge(u, v):
                dists.append(G[u][v]["distance_m"])
            else:
                n1, n2 = nodes_by_id[u], nodes_by_id[v]
                dists.append(_haversine_m(n1.lat, n1.lon, n2.lat, n2.lon))
        route = build_route_from_data(node_ids, coords, elevs, dists, G)
        route.route_id = path.path_id  # preserve the path's ID for traceability
        return route

    def _emit(path: _Path) -> Route | None:
        """Mark a path finished and finalize it, bumping the emitted counter.

        Returns the Route to yield, or None if the path is below the minimum
        length. The caller yields — a generator can't yield from a helper.
        """
        nonlocal routes_emitted
        path.active = False
        route = _finalize(path)
        if route is not None:
            routes_emitted += 1
        return route

    # ── Seed from peak nodes ──────────────────────────────────────────────────
    for nid, data in G.nodes(data=True):
        if not data.get("is_peak"):
            continue
        path = _Path(
            path_id=str(uuid.uuid4()),
            node_ids=[nid],
            arrival_speed_ms=config.peak_seed_speed_ms,
        )
        paths_by_id[path.path_id] = path
        node_path_count[nid] = node_path_count.get(nid, 0) + 1
        _push(path, nid, is_extending=False)

    # ── Main loop ─────────────────────────────────────────────────────────────
    # Cancellation is polled every _CANCEL_CHECK_INTERVAL pops (see module const).
    iters = 0
    while heap and routes_emitted < config.max_routes:
        iters += 1
        if should_cancel is not None and iters % _CANCEL_CHECK_INTERVAL == 0 and should_cancel():
            return
        priority, path_id, seq, node_id = heapq.heappop(heap)

        path = paths_by_id.get(path_id)
        if path is None or not path.active or path.sequence_number != seq:
            continue  # stale entry

        # If this is a peak seed and the node was already reached by another path,
        # the descent from here is already covered — skip to avoid sub-routes.
        if len(path.node_ids) == 1 and node_id in visited_nodes:
            path.active = False
            continue

        visited_nodes.add(node_id)
        node_data = G.nodes.get(node_id, {})

        # ── Check hard stops ─────────────────────────────────────────────────
        if len(path.node_ids) > 1:  # don't stop at start node
            if toggles.avoid_stoplights and node_data.get("is_traffic_signal"):
                if route := _emit(path):
                    yield route
                continue

            if toggles.avoid_stop_signs and node_data.get("is_stop_sign"):
                if route := _emit(path):
                    yield route
                continue

        # ── Check valley termination ─────────────────────────────────────────
        if len(path.node_ids) > 1 and node_data.get("is_valley"):
            if route := _emit(path):
                yield route
            continue

        # ── Check speed floor ────────────────────────────────────────────────
        if len(path.node_ids) > 1 and path.arrival_speed_ms < min_speed_ms:
            if route := _emit(path):
                yield route
            continue

        # ── Expand to neighbors ───────────────────────────────────────────────
        current_elev = node_data.get("elevation", 0)
        # Properties of the edge we arrived on (empty strings at the seed peak).
        if len(path.node_ids) >= 2:
            prev_id = path.node_ids[-2]
            arriving_edge = G[prev_id][node_id] if G.has_edge(prev_id, node_id) else {}
            current_hw_rank = arriving_edge.get("hw_rank", 0)
            current_hw = arriving_edge.get("highway", "")
            current_surface = arriving_edge.get("surface", "")
            current_way_name = arriving_edge.get("way_name", "")
        else:
            current_hw_rank = 0
            current_hw = ""
            current_surface = ""
            current_way_name = ""

        # ── Road type hard stops (pre-expansion) ────────────────────────────
        # Check before iterating neighbors so iteration order can't cause a
        # clone to escape onto a continuation edge before the stop fires.
        # Skip at the seed node (len=1): no current road type established yet.
        if len(path.node_ids) >= 2:
            neighbor_ranks = [G[node_id][nid].get("hw_rank", 0) for nid in G.successors(node_id)]
            terminate_for_road_type = False
            if toggles.avoid_bigger_roads and any(r > current_hw_rank for r in neighbor_ranks):
                terminate_for_road_type = True
            # Equal-road stop fires only when an equal-rank successor belongs to a
            # DIFFERENT way — i.e. you'd be turning onto/across another road of the
            # same class. The current road's own continuation (same way_name) has
            # equal rank by definition and must not trigger a stop, or every
            # intersection on a road would truncate the descent.
            if (toggles.avoid_equal_roads
                    and node_data.get("is_intersection")
                    and any(G[node_id][nid].get("hw_rank", 0) == current_hw_rank
                            and G[node_id][nid].get("way_name", "") != current_way_name
                            for nid in G.successors(node_id))):
                terminate_for_road_type = True
            if terminate_for_road_type:
                if route := _emit(path):
                    yield route
                continue

        extended = False
        for next_id in G.successors(node_id):
            if next_id in path.node_ids:
                continue  # no cycles

            edge = G[node_id][next_id]

            # Non-traversable edges (bigger roads fetched only for crossing
            # detection) are never ridden. They still count in the road-type
            # hard-stop check above via successor ranks; here we just never
            # expand onto them.
            if not edge.get("traversable", True):
                continue

            next_data = G.nodes[next_id]

            # ── Tunnel toggle ────────────────────────────────────────────────
            if toggles.exclude_tunnels and edge.get("is_tunnel"):
                continue

            # ── Node cap ─────────────────────────────────────────────────────
            active_at_next = node_path_count.get(next_id, 0)
            if active_at_next >= config.max_paths_per_node:
                # Finalize this path; can't enter the node
                if route := _emit(path):
                    yield route
                break

            # ── Compute arrival speed ─────────────────────────────────────────
            grade = edge.get("grade", 0.0)
            dist = edge.get("distance_m", 1.0)
            arrival_speed = _speed_at_node(path.arrival_speed_ms, grade, dist, params)

            # ── Fork: clone path for each downhill neighbor ───────────────────
            next_elev = next_data.get("elevation", 0)
            descent = current_elev - next_elev

            next_hw = edge.get("highway", "")
            next_surface = edge.get("surface", "")
            type_changed = 1 if (
                (current_hw != "" and next_hw != current_hw)
                or (current_surface != "" and next_surface != current_surface)
            ) else 0
            new_path = _Path(
                path_id=str(uuid.uuid4()),
                node_ids=path.node_ids + [next_id],
                arrival_speed_ms=arrival_speed,
                total_dist_m=path.total_dist_m + dist,
                total_descent_m=path.total_descent_m + max(descent, 0),
                type_changes=path.type_changes + type_changed,
            )
            paths_by_id[new_path.path_id] = new_path
            node_path_count[next_id] = node_path_count.get(next_id, 0) + 1

            _push(new_path, next_id, is_extending=True)
            extended = True

        # If the path is still active here it either forked (extended=True) or
        # ran out of valid successors without any explicit termination event
        # (extended=False: dead end, all neighbors visited, all tunnels excluded).
        # Dead-end paths should be emitted — they represent the furthest the
        # algorithm could travel from the starting peak.
        if path.active:
            if not extended and len(path.node_ids) > 1:
                if route := _emit(path):
                    yield route
            path.sequence_number += 1
            path.active = False
