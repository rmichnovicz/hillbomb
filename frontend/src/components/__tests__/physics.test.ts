/**
 * Tests for utils/physics.ts — must produce the same results as backend physics.py.
 * If the two diverge, this test suite is the first to catch it.
 *
 * Model (matches physics.py):
 *   F_gravity  = -m * g * grade        (grade < 0 → downhill → propulsive)
 *   F_drag     =  0.5 * rho * Cd * A * v²
 *   F_rolling  =  Crr * m * g
 *   F_net      =  F_gravity - F_drag - F_rolling
 *   a          =  F_net / m
 *   v_new      =  sqrt(max(v² + 2*a*sub_ds, 0))
 */
import { describe, it, expect } from 'vitest'
import { simulateSpeedProfile } from '../../utils/physics'
import type { RiderParams } from '../../types'

const LONGBOARDER: RiderParams = {
  weight_kg: 80,
  drag_coefficient: 0.75,
  frontal_area_m2: 0.35,
  crr_physics: 0.012,
  crr_pathfinding: 0.020,
}

const CYCLIST_DROPS: RiderParams = {
  weight_kg: 80,
  drag_coefficient: 0.70,
  frontal_area_m2: 0.32,
  crr_physics: 0.003,
  crr_pathfinding: 0.006,
}

describe('simulateSpeedProfile — output shape', () => {
  it('profile length equals number of elevation points', () => {
    const elevs = [100, 90, 80, 70]
    const dists = [100, 100, 100]
    const { profile } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    expect(profile).toHaveLength(elevs.length)
  })

  it('first speed is always zero (starting from rest)', () => {
    const { profile } = simulateSpeedProfile([100, 80], [200], LONGBOARDER)
    expect(profile[0]).toBe(0)
  })

  it('topSpeed equals max of profile', () => {
    const elevs = [100, 90, 80, 70]
    const dists = [100, 100, 100]
    const { profile, topSpeed } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    expect(topSpeed).toBeCloseTo(Math.max(...profile), 4)
  })

  it('avgSpeed is between 0 and topSpeed', () => {
    const elevs = [100, 85, 70, 55]
    const dists = [100, 100, 100]
    const { topSpeed, avgSpeed } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    expect(avgSpeed).toBeGreaterThanOrEqual(0)
    expect(avgSpeed).toBeLessThanOrEqual(topSpeed + 1e-6)
  })

  it('handles a single-segment route', () => {
    const { profile } = simulateSpeedProfile([100, 80], [200], LONGBOARDER)
    expect(profile).toHaveLength(2)
  })

  it('returns zeros for empty elevations', () => {
    const { profile, topSpeed, avgSpeed } = simulateSpeedProfile([], [], LONGBOARDER)
    expect(profile).toHaveLength(0)
    expect(topSpeed).toBe(0)
    expect(avgSpeed).toBe(0)
  })
})

describe('simulateSpeedProfile — physics correctness', () => {
  it('steep downhill from rest gives speed > 30 km/h', () => {
    // 20% grade over 300m — should reach > 30 km/h (backend test uses same threshold)
    const elevs = [200, 180, 160, 140]
    const dists = [100, 100, 100]
    const { topSpeed } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    expect(topSpeed).toBeGreaterThan(30)
  })

  it('flat from rest gives near-zero speed (rolling resistance blocks motion)', () => {
    const elevs = [100, 100, 100, 100]
    const dists = [100, 100, 100]
    const { topSpeed } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    expect(topSpeed).toBeCloseTo(0, 1)
  })

  it('uphill from rest gives zero speed', () => {
    const elevs = [100, 110, 120]
    const dists = [100, 100]
    const { topSpeed } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    expect(topSpeed).toBeCloseTo(0, 1)
  })

  it('steeper grade produces higher top speed', () => {
    // 20% grade vs 10% grade, same distance
    const { topSpeed: steep  } = simulateSpeedProfile([100, 80], [100], LONGBOARDER)
    const { topSpeed: gentle } = simulateSpeedProfile([100, 90], [100], LONGBOARDER)
    expect(steep).toBeGreaterThan(gentle)
  })

  it('all profile values are non-negative', () => {
    // Mix of ups and downs
    const elevs = [100, 80, 90, 75, 85]
    const dists = [100, 100, 200, 150]
    const { profile } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    expect(profile.every(v => v >= 0)).toBe(true)
  })

  it('terminal velocity is bounded below 200 km/h on a very long steep descent', () => {
    const n = 50
    const drop = 15  // 15m per 100m segment = 15% grade
    const elevs = Array.from({ length: n + 1 }, (_, i) => 500 - i * drop)
    const dists = Array(n).fill(100)
    const { topSpeed, profile } = simulateSpeedProfile(elevs, dists, CYCLIST_DROPS)
    expect(topSpeed).toBeLessThan(200)
    // Speed should plateau: last 10 values within 5 km/h of each other
    const tail = profile.slice(-10)
    expect(Math.max(...tail) - Math.min(...tail)).toBeLessThan(5)
  })

  it('profile values are in km/h not m/s (should be > 1 for meaningful descent)', () => {
    const { topSpeed } = simulateSpeedProfile([100, 80], [200], LONGBOARDER)
    expect(topSpeed).toBeGreaterThan(1)
  })

  it('cyclist_drops faster than longboarder on same descent (lower Crr)', () => {
    const elevs = [100, 85, 70]
    const dists = [150, 150]
    const { topSpeed: lb } = simulateSpeedProfile(elevs, dists, LONGBOARDER)
    const { topSpeed: cy } = simulateSpeedProfile(elevs, dists, CYCLIST_DROPS)
    expect(cy).toBeGreaterThan(lb)
  })
})
