export interface RouteMetadata {
  name: string
  length_m: number
  total_descent_m: number
  avg_grade_pct: number
  primary_highway: string
}

export interface RouteGeometry {
  type: 'LineString'
  coordinates: [number, number][]  // [lon, lat] pairs
}

/** A fully populated route — physics fields are always present (included in the route SSE event). */
export interface Route {
  route_id: string
  start_node_id: number
  geometry: RouteGeometry
  metadata: RouteMetadata
  /** Per-node elevations (metres) — included so the client can run live physics. */
  elevations: number[]
  /** Distance between consecutive nodes (metres), length = elevations.length - 1. */
  segment_distances: number[]
  flow_score: number
  flow_grade: string
  /** Surface category → percentage of route distance (paved/gravel/unpaved/cobblestone/unknown). */
  surface_pcts: Record<string, number>
  speed_profile: number[]
  top_speed_kmh: number
  avg_speed_kmh: number
}

/** All routes sharing the same starting peak node. */
export interface StartGroup {
  startNodeId: string
  /** Routes sorted by top_speed_kmh descending; best route is [0]. */
  routes: Route[]
  startCoord: [number, number]
}

export interface RiderParams {
  weight_kg: number
  drag_coefficient: number
  frontal_area_m2: number
  crr_physics: number
  /** Rolling resistance used during pathfinding (affects which routes are found; requires re-search). */
  crr_pathfinding: number
}

export type RiderProfile = 'longboarder' | 'cyclist_upright' | 'cyclist_drops'

export const RIDER_PROFILES: Record<RiderProfile, RiderParams> = {
  longboarder: {
    weight_kg: 80,
    drag_coefficient: 0.75,
    frontal_area_m2: 0.35,
    crr_physics: 0.012,
    crr_pathfinding: 0.012,
  },
  cyclist_upright: {
    weight_kg: 85,
    drag_coefficient: 0.88,
    frontal_area_m2: 0.42,
    crr_physics: 0.004,
    crr_pathfinding: 0.004,
  },
  cyclist_drops: {
    weight_kg: 80,
    drag_coefficient: 0.70,
    frontal_area_m2: 0.32,
    crr_physics: 0.003,
    crr_pathfinding: 0.003,
  },
}

export interface Toggles {
  avoid_stoplights: boolean
  avoid_stop_signs: boolean
  avoid_bigger_roads: boolean
  avoid_equal_roads: boolean
  exclude_tunnels: boolean
  exclude_bridges: boolean
  animate_candidates: boolean
}

export interface SearchOptions {
  bbox: [number, number, number, number]  // south, west, north, east
  road_types?: string[]
  rider_profile?: RiderProfile
  toggles?: Partial<Toggles>
  max_road_rank?: number
  allowed_surface_categories?: string[]
  crr_pathfinding?: number
}

// SSE event shapes emitted by the backend
export type SSEEvent =
  | { type: 'status'; message: string }
  | { type: 'route'; route_id: string; start_node_id: number; geometry: RouteGeometry; metadata: RouteMetadata; elevations: number[]; segment_distances: number[]; flow_score: number; flow_grade: string; surface_pcts: Record<string, number>; speed_profile: number[]; top_speed_kmh: number; avg_speed_kmh: number }
  | { type: 'candidate'; geometry: RouteGeometry }
  | { type: 'error'; message: string }
  | { type: 'done' }
