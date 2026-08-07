"""
Speed profile simulation using a drag-aware kinematic model.

Model (per segment, sub-stepped for accuracy):
  F_gravity  = -m * g * grade        (grade < 0 → downhill → propulsive)
  F_drag     =  0.5 * rho * Cd * A * v²
  F_rolling  =  Crr * m * g
  F_net      =  F_gravity - F_drag - F_rolling
  a          =  F_net / m
  v_new      =  min(sqrt(max(v² + 2*a*ds, 0)), v_max)  [energy method; sub-stepped]

grade: (elev_end - elev_start) / distance  (positive = uphill, negative = downhill)
Outputs are in km/h.

v_max comes from params.max_speed_kmh and is None (uncapped) for the road profiles.
It stands in for a brake, which this model otherwise does not have — see
config.RiderParams.max_speed_kmh for why dirt profiles need one and tarmac doesn't.

NOTE: usePhysics.ts in the frontend must implement the same model.
      When changing this file, update usePhysics.ts to match.
"""

import math
import numpy as np
from .config import RiderParams, SearchConfig

# Sub-steps per segment; keeps error small for typical 10–100m segments
_SUB_STEPS = 10


def simulate_speed_profile(
    elevations: list[float],
    distances: list[float],
    params: RiderParams,
    config: SearchConfig,
) -> tuple[list[float], float, float]:
    """
    Simulate speed along a route.

    Args:
        elevations: elevation at each node (m), length N
        distances:  distance between consecutive nodes (m), length N-1
        params:     rider physics parameters (uses crr_physics, not crr_pathfinding)
        config:     search config (air_density_kg_m3)

    Returns:
        (speed_profile_kmh, top_speed_kmh, avg_speed_kmh)
        speed_profile_kmh has length N (first entry is always 0 — starting from rest).
    """
    if len(elevations) == 0:
        return [], 0.0, 0.0

    n = len(elevations)
    speed_ms = np.zeros(n)

    g = 9.81
    m = params.weight_kg
    crr = params.crr_physics
    drag_k = 0.5 * config.air_density_kg_m3 * params.drag_coefficient * params.frontal_area_m2

    # inf rather than a branch in the hot sub-step loop; min() against it is a no-op.
    v_max = params.max_speed_kmh / 3.6 if params.max_speed_kmh is not None else math.inf

    v = 0.0  # starting from rest

    for i in range(n - 1):
        dist = distances[i]
        grade = (elevations[i + 1] - elevations[i]) / dist if dist > 0 else 0.0

        # Compute constant forces for this segment
        f_gravity = -m * g * grade       # positive when going downhill
        f_rolling = crr * m * g          # always opposing motion

        sub_ds = dist / _SUB_STEPS
        for _ in range(_SUB_STEPS):
            f_drag = drag_k * v * v      # always opposing motion
            f_net = f_gravity - f_drag - f_rolling
            a = f_net / m
            v_sq = v * v + 2.0 * a * sub_ds
            v = min(math.sqrt(max(v_sq, 0.0)), v_max)

        speed_ms[i + 1] = v

    speed_kmh = (speed_ms * 3.6).tolist()
    top = max(speed_kmh)
    avg = float(np.mean(speed_kmh))  # n >= 1 here (len==0 returned early above)

    return speed_kmh, top, avg


_Segment = tuple[list[int], list[float], list[float], list[float]]


def _trim_leading_stall(segment: _Segment) -> _Segment | None:
    """
    Drop leading nodes the rider never moves through.

    After a split, a segment begins at the stall node (speed 0) and may be
    followed by a flat/uphill run the rider can't climb from rest — the sim keeps
    speed at 0 across all of it until the road tips downhill again. Those leading
    0 km/h nodes are not part of the rideable descent, so we trim them, keeping
    the single crest node right before motion resumes as the route's start (which
    naturally begins at rest, like any descent).

    Returns the trimmed segment, or None if the rider never moves at all (the
    whole segment is stalled — nothing rideable to emit).
    """
    node_ids, elevations, distances, speed = segment
    first_moving = next((i for i, s in enumerate(speed) if s > 0.0), None)
    if first_moving is None:
        return None  # rider never gets going; drop the segment
    start = max(first_moving - 1, 0)  # keep the crest node just before motion
    if start == 0:
        return segment
    return (
        node_ids[start:],
        elevations[start:],
        distances[start:],
        speed[start:],
    )


def split_route_on_zero_speed(
    node_ids: list[int],
    elevations: list[float],
    distances: list[float],
    speed_profile_kmh: list[float],
) -> list[_Segment]:
    """
    Split a route wherever the physics sim transitions from moving (>0 km/h) to
    exactly 0 km/h. The sliced speed profile is already correct for each sub-segment
    because the sim restarts from rest at the stop point.

    Each split segment is then trimmed of the leading stall (see
    _trim_leading_stall) so it begins where the rider actually starts rolling
    rather than at the stall point and the flat/uphill that follows it.

    Returns a list of (node_ids, elevations, distances, speed_profile_kmh) tuples.
    Returns the original as a single-element list when no stop events occur.

    distances[i] is the distance from node_ids[i] to node_ids[i+1],
    so len(distances) == len(node_ids) - 1.
    """
    n = len(speed_profile_kmh)
    if n <= 1:
        return [(node_ids, elevations, distances, speed_profile_kmh)]

    # Indices where the rider transitions from moving to fully stopped
    split_points = [
        i for i in range(1, n)
        if speed_profile_kmh[i] == 0.0 and speed_profile_kmh[i - 1] > 0.0
    ]

    if not split_points:
        return [(node_ids, elevations, distances, speed_profile_kmh)]

    raw_segments: list[_Segment] = []
    prev = 0
    for sp in split_points:
        # Segment covers nodes [prev..sp] inclusive → sp-prev distances
        raw_segments.append((
            node_ids[prev:sp + 1],
            elevations[prev:sp + 1],
            distances[prev:sp],
            speed_profile_kmh[prev:sp + 1],
        ))
        prev = sp

    # Tail segment [prev..end]
    if prev < n:
        raw_segments.append((
            node_ids[prev:],
            elevations[prev:],
            distances[prev:],
            speed_profile_kmh[prev:],
        ))

    # The first segment starts at the original descent peak (already rolling), so
    # only the post-stall segments need trimming; running the trim over all of
    # them is harmless and keeps the logic uniform.
    trimmed = (_trim_leading_stall(seg) for seg in raw_segments)
    return [seg for seg in trimmed if seg is not None]
