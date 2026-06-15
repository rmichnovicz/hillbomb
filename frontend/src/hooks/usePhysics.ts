/**
 * Live physics re-simulation hook.
 * Re-runs simulateSpeedProfile whenever rider params change,
 * so the profile panel updates without a network round-trip.
 *
 * Returns null while there's no active route or the route has
 * no elevation data yet.
 *
 * See backend/physics.py — must implement the same model.
 */
import { useMemo } from 'react'
import { simulateSpeedProfile } from '../utils/physics'
import type { Route, RiderParams } from '../types'

export interface PhysicsResult {
  speed_profile: number[]
  top_speed_kmh: number
  avg_speed_kmh: number
}

export function usePhysics(route: Route | null, params: RiderParams): PhysicsResult | null {
  return useMemo(() => {
    if (!route || route.elevations.length < 2) return null
    const { profile, topSpeed, avgSpeed } = simulateSpeedProfile(
      route.elevations,
      route.segment_distances,
      params,
    )
    return { speed_profile: profile, top_speed_kmh: topSpeed, avg_speed_kmh: avgSpeed }
  }, [route, params])
}
