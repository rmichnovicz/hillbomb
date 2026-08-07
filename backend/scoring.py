"""
Flow score computation for a finalized route.

Score starts at 100 and deducts per occurrence:
  - traffic signal node (not at start): -flow_penalty_stoplight
  - stop sign node (not at start):      -flow_penalty_stop_sign
  - edge with cobblestone surface:      -flow_penalty_surface_cobble
  - edge with gravel surface:           -flow_penalty_surface_gravel
  - edge with unpaved surface:          -flow_penalty_surface_unpaved
  - edge hw_rank > previous edge hw_rank: -flow_penalty_bigger_road

Which surfaces count as rough is a property of the RIDER, not of the road — see
RiderParams.rough_surface_categories. The penalty values are global; the set they
apply to narrows for gravel and empties for MTB.

Score is clamped to [0, 100].
Letter grade: A≥80, B≥60, C≥40, D≥20, E≥1, F=0.
"""

import networkx as nx
from .config import RiderParams, SearchConfig, SURFACE_CATEGORIES
from .types import OSMNode, Route

# Derive the penalised surface sets from the single SURFACE_CATEGORIES taxonomy
# so scoring and the display percentages can't categorise the same tag (e.g.
# "compacted") differently. "paved" carries no penalty.
_PENALTY_BY_CATEGORY = {
    "cobblestone": "flow_penalty_surface_cobble",
    "gravel": "flow_penalty_surface_gravel",
    "unpaved": "flow_penalty_surface_unpaved",
}


def score_to_grade(score: float) -> str:
    if score >= 80:
        return "A"
    if score >= 60:
        return "B"
    if score >= 40:
        return "C"
    if score >= 20:
        return "D"
    if score > 0:
        return "E"
    return "F"


def compute_flow_score(
    route: Route,
    G: nx.DiGraph,
    nodes_by_id: dict[int, OSMNode],
    config: SearchConfig,
    params: RiderParams | None = None,
) -> Route:
    """
    Compute and attach flow_score / flow_grade to the route. Mutates and returns route.

    `params` supplies which surfaces are rough for this rider. Omitting it penalizes
    all of cobblestone/gravel/unpaved, which is the road-cyclist reading and the
    behaviour this function had before profiles could differ.
    """
    score = 100.0
    node_ids = route.node_ids

    # tag → penalty, built once per route from the categories this rider minds.
    rough = params.rough_surface_categories if params is not None else tuple(_PENALTY_BY_CATEGORY)
    penalty_by_tag: dict[str, float] = {
        tag: getattr(config, _PENALTY_BY_CATEGORY[cat])
        for cat in rough
        for tag in SURFACE_CATEGORIES[cat]
    }

    # Track previous edge hw_rank for bigger-road-crossing detection
    prev_hw_rank: int | None = None

    for i, nid in enumerate(node_ids):
        # ── Node penalties (skip start node) ──────────────────────────────────
        if i > 0:
            node_data = G.nodes.get(nid, {})
            if node_data.get("is_traffic_signal"):
                score -= config.flow_penalty_stoplight
            if node_data.get("is_stop_sign"):
                score -= config.flow_penalty_stop_sign

        # ── Edge penalties ────────────────────────────────────────────────────
        if i < len(node_ids) - 1:
            next_id = node_ids[i + 1]
            if not G.has_edge(nid, next_id):
                continue
            edge = G[nid][next_id]

            # Surface penalty (at most one category per edge; categories are disjoint)
            score -= penalty_by_tag.get(edge.get("surface", ""), 0.0)

            # Bigger-road crossing
            hw_rank = edge.get("hw_rank", 0)
            if prev_hw_rank is not None and hw_rank > prev_hw_rank:
                score -= config.flow_penalty_bigger_road
            prev_hw_rank = hw_rank

    score = max(0.0, min(100.0, score))
    route.flow_score = score
    route.flow_grade = score_to_grade(score)
    return route
