"""
Tests for physics.py — speed profile simulation.

Physics model:
  F_net = m*g*(-grade) - 0.5*rho*Cd*A*v² - Crr*m*g
  a = F_net / m
  v_new = sqrt(max(v² + 2*a*ds, 0))  (sub-stepped per segment)

grade convention: positive = uphill (rises/run); negative = downhill.
"""

import math
import pytest
from ..config import RiderParams, SearchConfig, RIDER_PROFILES
from ..physics import simulate_speed_profile, split_route_on_zero_speed


# ── Shared fixtures ───────────────────────────────────────────────────────────

@pytest.fixture
def longboarder():
    return RIDER_PROFILES["longboarder"]

@pytest.fixture
def cyclist():
    return RIDER_PROFILES["cyclist_upright"]

@pytest.fixture
def config():
    return SearchConfig()


# ── Output shape ──────────────────────────────────────────────────────────────

def test_output_length_matches_elevations(longboarder, config):
    elevs = [100.0, 90.0, 80.0, 75.0]
    dists = [100.0, 100.0, 50.0]
    profile, top, avg = simulate_speed_profile(elevs, dists, longboarder, config)
    assert len(profile) == len(elevs)

def test_single_segment(longboarder, config):
    elevs = [50.0, 40.0]
    dists = [100.0]
    profile, top, avg = simulate_speed_profile(elevs, dists, longboarder, config)
    assert len(profile) == 2

def test_top_speed_is_max_of_profile(longboarder, config):
    elevs = [100.0, 90.0, 80.0, 70.0]
    dists = [100.0, 100.0, 100.0]
    profile, top, avg = simulate_speed_profile(elevs, dists, longboarder, config)
    assert math.isclose(top, max(profile), rel_tol=1e-6)

def test_avg_speed_between_zero_and_top(longboarder, config):
    elevs = [100.0, 85.0, 70.0, 55.0]
    dists = [100.0, 100.0, 100.0]
    profile, top, avg = simulate_speed_profile(elevs, dists, longboarder, config)
    assert 0.0 <= avg <= top + 1e-6

def test_first_speed_is_zero(longboarder, config):
    """Starting from rest — first node always has speed 0."""
    elevs = [100.0, 90.0, 80.0]
    dists = [100.0, 100.0]
    profile, _, _ = simulate_speed_profile(elevs, dists, longboarder, config)
    assert profile[0] == 0.0


# ── Directional physics ───────────────────────────────────────────────────────

def test_steep_downhill_accelerates(longboarder, config):
    """20% grade over 300m from rest should reach > 30 km/h."""
    drop = 60.0  # 60m drop over 300m = 20% grade
    elevs = [200.0, 200.0 - drop / 3, 200.0 - 2 * drop / 3, 200.0 - drop]
    dists = [100.0, 100.0, 100.0]
    profile, top, _ = simulate_speed_profile(elevs, dists, longboarder, config)
    assert top > 30.0, f"Expected > 30 km/h on steep downhill, got {top:.1f}"

def test_flat_from_rest_gives_zero_speed(longboarder, config):
    """No grade, starting at rest → rolling resistance keeps speed at 0."""
    elevs = [100.0, 100.0, 100.0, 100.0]
    dists = [100.0, 100.0, 100.0]
    profile, top, avg = simulate_speed_profile(elevs, dists, longboarder, config)
    assert top == pytest.approx(0.0, abs=0.1)

def test_uphill_from_rest_gives_zero_speed(longboarder, config):
    """Uphill from rest → can't go backwards; stays at 0."""
    elevs = [100.0, 110.0, 120.0]
    dists = [100.0, 100.0]
    profile, top, _ = simulate_speed_profile(elevs, dists, longboarder, config)
    assert top == pytest.approx(0.0, abs=0.1)

def test_speed_increases_on_steeper_grade(longboarder, config):
    """20% grade over 200m should produce higher top speed than 5% over 200m."""
    steep_elevs = [100.0, 80.0]   # 20% grade
    gentle_elevs = [100.0, 90.0]  # 10% grade
    dists = [100.0]

    _, top_steep, _ = simulate_speed_profile(steep_elevs, dists, longboarder, config)
    _, top_gentle, _ = simulate_speed_profile(gentle_elevs, dists, longboarder, config)
    assert top_steep > top_gentle


# ── Air drag caps terminal velocity ───────────────────────────────────────────

def test_terminal_velocity_bounded(cyclist, config):
    """Very long steep descent: speed must plateau (air drag) and stay below 200 km/h."""
    n = 50
    drop_per_segment = 15.0  # 15% grade
    dist_per_segment = 100.0
    elevs = [500.0 - i * drop_per_segment for i in range(n + 1)]
    dists = [dist_per_segment] * n
    profile, top, _ = simulate_speed_profile(elevs, dists, cyclist, config)
    assert top < 200.0, f"Top speed {top:.1f} km/h exceeds physical bound"
    # Speed profile should plateau: last 10 entries should all be within 5 km/h of each other
    tail = profile[-10:]
    assert max(tail) - min(tail) < 5.0, "Speed should plateau at terminal velocity"


# ── Profile units ─────────────────────────────────────────────────────────────

def test_profile_in_kmh(longboarder, config):
    """Profile values are in km/h, not m/s — should be > 1 for meaningful descent."""
    elevs = [100.0, 80.0]
    dists = [200.0]
    profile, top, _ = simulate_speed_profile(elevs, dists, longboarder, config)
    assert top > 1.0, "Speed profile should be in km/h"

def test_all_speeds_nonnegative(longboarder, config):
    """Speed can never go negative."""
    # Mix of up and down
    elevs = [100.0, 80.0, 90.0, 75.0, 85.0]
    dists = [100.0, 100.0, 200.0, 150.0]
    profile, _, _ = simulate_speed_profile(elevs, dists, longboarder, config)
    assert all(v >= 0.0 for v in profile)


# ── Rider profiles produce different results ──────────────────────────────────

def test_cyclist_faster_than_longboarder_on_same_run(config):
    """Cyclist has less Crr (better wheels) → higher speed for same descent."""
    elevs = [100.0, 85.0, 70.0]
    dists = [150.0, 150.0]
    lb = RIDER_PROFILES["longboarder"]
    cy = RIDER_PROFILES["cyclist_drops"]
    _, top_lb, _ = simulate_speed_profile(elevs, dists, lb, config)
    _, top_cy, _ = simulate_speed_profile(elevs, dists, cy, config)
    # cyclist_drops has crr_physics=0.003 vs longboarder's 0.012 → cyclist is faster
    assert top_cy > top_lb


# ── split_route_on_zero_speed ─────────────────────────────────────────────────

def test_no_split_when_no_stops():
    node_ids = [1, 2, 3, 4]
    elevs = [100.0, 90.0, 80.0, 70.0]
    dists = [100.0, 100.0, 100.0]
    speed = [0.0, 10.0, 20.0, 25.0]
    result = split_route_on_zero_speed(node_ids, elevs, dists, speed)
    assert len(result) == 1
    assert result[0][0] is node_ids  # same object, no copy


def test_split_at_single_stop():
    node_ids = [1, 2, 3, 4, 5]
    elevs = [100.0, 90.0, 85.0, 75.0, 65.0]
    dists = [100.0, 50.0, 100.0, 100.0]
    #         0     10    5     0    8     — speed[3] is 0 after speed[2]=5 > 0
    speed = [0.0, 10.0, 5.0, 0.0, 8.0]
    result = split_route_on_zero_speed(node_ids, elevs, dists, speed)
    assert len(result) == 2
    seg_a_nodes, seg_a_elevs, seg_a_dists, seg_a_speed = result[0]
    seg_b_nodes, seg_b_elevs, seg_b_dists, seg_b_speed = result[1]
    # First segment: nodes 0..3 (indices 0,1,2,3)
    assert seg_a_nodes == [1, 2, 3, 4]
    assert seg_a_dists == [100.0, 50.0, 100.0]
    assert seg_a_speed == [0.0, 10.0, 5.0, 0.0]
    # Second segment: nodes 3..4 (indices 3,4)
    assert seg_b_nodes == [4, 5]
    assert seg_b_dists == [100.0]
    assert seg_b_speed == [0.0, 8.0]


def test_no_split_when_speed_never_rises():
    """All-zero speed profile (flat/uphill from rest) → no split, single segment."""
    node_ids = [1, 2, 3]
    speed = [0.0, 0.0, 0.0]
    result = split_route_on_zero_speed(node_ids, [100.0]*3, [100.0, 100.0], speed)
    assert len(result) == 1


def test_split_preserves_distance_length():
    """Each segment's distances should have length = len(nodes) - 1."""
    node_ids = [1, 2, 3, 4, 5, 6]
    elevs = [float(e) for e in [100, 90, 80, 75, 65, 55]]
    dists = [100.0] * 5
    speed = [0.0, 10.0, 20.0, 0.0, 5.0, 15.0]
    result = split_route_on_zero_speed(node_ids, elevs, dists, speed)
    assert len(result) == 2
    for seg_nodes, _, seg_dists, _ in result:
        assert len(seg_dists) == len(seg_nodes) - 1


def test_single_node_returns_as_is():
    result = split_route_on_zero_speed([42], [100.0], [], [0.0])
    assert len(result) == 1
    assert result[0][0] == [42]


def test_split_trims_leading_stall():
    """A post-stall segment with a flat/uphill run the rider can't climb from
    rest should be trimmed to start at the crest where motion resumes, keeping
    the single 0 km/h crest node."""
    node_ids = [1, 2, 3, 4, 5, 6, 7, 8]
    elevs = [float(e) for e in [100, 90, 80, 82, 84, 86, 80, 70]]
    dists = [100.0] * 7
    #        rolls down, stalls at idx 3, climbs (stays 0), descends again at idx 6
    speed = [0.0, 10.0, 20.0, 0.0, 0.0, 0.0, 5.0, 12.0]
    result = split_route_on_zero_speed(node_ids, elevs, dists, speed)
    assert len(result) == 2
    # First segment unchanged (starts rolling immediately)
    assert result[0][0] == [1, 2, 3, 4]
    assert result[0][3] == [0.0, 10.0, 20.0, 0.0]
    # Second segment trimmed: drop the stall + uphill, keep node 6 (the crest)
    seg_b_nodes, seg_b_elevs, seg_b_dists, seg_b_speed = result[1]
    assert seg_b_nodes == [6, 7, 8]
    assert seg_b_elevs == [86.0, 80.0, 70.0]
    assert seg_b_dists == [100.0, 100.0]
    assert seg_b_speed == [0.0, 5.0, 12.0]
    assert len(seg_b_dists) == len(seg_b_nodes) - 1


def test_split_drops_fully_stalled_tail():
    """A trailing segment where the rider never moves again is dropped entirely."""
    node_ids = [1, 2, 3, 4, 5]
    elevs = [float(e) for e in [100, 90, 80, 85, 90]]
    dists = [100.0] * 4
    speed = [0.0, 10.0, 0.0, 0.0, 0.0]  # stall at idx 2, never recovers
    result = split_route_on_zero_speed(node_ids, elevs, dists, speed)
    assert len(result) == 1  # only the first, rideable segment survives
    assert result[0][0] == [1, 2, 3]
