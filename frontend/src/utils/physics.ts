/**
 * Client-side speed profile simulation — mirrors backend/physics.py exactly.
 * If the model changes in physics.py, update this file to match.
 *
 * Model:
 *   grade      = rise / run  (negative = downhill = propulsive)
 *   F_gravity  = -m * g * grade
 *   F_drag     =  0.5 * rho * Cd * A * v²
 *   F_rolling  =  Crr * m * g
 *   F_net      =  F_gravity - F_drag - F_rolling
 *   a          =  F_net / m
 *   v_new      =  min(sqrt(max(v² + 2*a*sub_ds, 0)), v_max)   (energy equation)
 *
 * v_max comes from params.max_speed_kmh and is undefined (uncapped) for the road
 * profiles. It stands in for a brake, which this model otherwise does not have —
 * see backend/config.py RiderParams.max_speed_kmh.
 */
import type { RiderParams } from '../types'

const G = 9.81
const RHO = 1.225   // kg/m³ — air density at sea level
const SUB_STEPS = 10

export interface SpeedProfile {
  profile: number[]   // speed at each elevation point, km/h
  topSpeed: number    // km/h
  avgSpeed: number    // km/h
}

export function simulateSpeedProfile(
  elevations: number[],
  distances: number[],
  params: RiderParams,
): SpeedProfile {
  if (elevations.length === 0) {
    return { profile: [], topSpeed: 0, avgSpeed: 0 }
  }

  const { weight_kg: m, drag_coefficient: Cd, frontal_area_m2: A, crr_physics: Crr } = params
  // Infinity rather than a branch in the hot sub-step loop; Math.min against it is a no-op.
  const vMax = params.max_speed_kmh != null ? params.max_speed_kmh / 3.6 : Infinity

  const profile: number[] = new Array(elevations.length).fill(0)
  let v = 0  // m/s

  for (let i = 0; i < distances.length; i++) {
    const dz = elevations[i + 1] - elevations[i]
    const ds = distances[i]
    const grade = ds > 0 ? dz / ds : 0

    const sub_ds = ds / SUB_STEPS
    for (let s = 0; s < SUB_STEPS; s++) {
      const F_gravity  = -m * G * grade
      const F_drag     =  0.5 * RHO * Cd * A * v * v
      const F_rolling  =  Crr * m * G
      const F_net      = F_gravity - F_drag - F_rolling
      const a          = F_net / m
      const v2_new     = v * v + 2 * a * sub_ds
      v = Math.min(v2_new > 0 ? Math.sqrt(v2_new) : 0, vMax)
    }

    profile[i + 1] = v * 3.6  // m/s → km/h
  }

  const topSpeed = profile.length > 0 ? Math.max(...profile) : 0
  const avgSpeed = profile.length > 0 ? profile.reduce((a, b) => a + b, 0) / profile.length : 0

  return { profile, topSpeed, avgSpeed }
}
