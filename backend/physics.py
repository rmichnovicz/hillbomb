"""
Speed profile simulation using a drag-aware kinematic model.

Model (per segment, sub-stepped for accuracy):
  F_gravity  = -m * g * grade        (grade < 0 → downhill → propulsive)
  F_drag     =  0.5 * rho * Cd * A * v²
  F_rolling  =  Crr * m * g
  F_net      =  F_gravity - F_drag - F_rolling
  a          =  F_net / m
  v_new      =  sqrt(max(v² + 2*a*ds, 0))  [energy method; sub-stepped]

grade: (elev_end - elev_start) / distance  (positive = uphill, negative = downhill)
Outputs are in km/h.

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
            v = math.sqrt(max(v_sq, 0.0))

        speed_ms[i + 1] = v

    speed_kmh = (speed_ms * 3.6).tolist()
    top = max(speed_kmh)
    avg = float(np.mean(speed_kmh))  # n >= 1 here (len==0 returned early above)

    return speed_kmh, top, avg


def split_route_on_zero_speed(
    node_ids: list[int],
    elevations: list[float],
    distances: list[float],
    speed_profile_kmh: list[float],
) -> list[tuple[list[int], list[float], list[float], list[float]]]:
    """
    Split a route wherever the physics sim transitions from moving (>0 km/h) to
    exactly 0 km/h. The sliced speed profile is already correct for each sub-segment
    because the sim restarts from rest at the stop point.

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

    segments: list[tuple[list[int], list[float], list[float], list[float]]] = []
    prev = 0
    for sp in split_points:
        # Segment covers nodes [prev..sp] inclusive → sp-prev distances
        segments.append((
            node_ids[prev:sp + 1],
            elevations[prev:sp + 1],
            distances[prev:sp],
            speed_profile_kmh[prev:sp + 1],
        ))
        prev = sp

    # Tail segment [prev..end]
    if prev < n:
        segments.append((
            node_ids[prev:],
            elevations[prev:],
            distances[prev:],
            speed_profile_kmh[prev:],
        ))

    return segments
