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

/** A stop sign or traffic signal located on a route (including its start/end). */
export interface RouteStop {
  type: 'stop_sign' | 'traffic_signal'
  coord: [number, number]  // [lon, lat]
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
  /**
   * Hardest segment's 0-6 OSM `mtb:scale` grade, or null when no segment on the route
   * carried a difficulty tag — which is most routes, since coverage is thin.
   * null means UNKNOWN, not easy: render it as "—", never as a grade of 0.
   */
  trail_difficulty: number | null
  /** Stop signs / traffic signals on the route, in path order (start and end included). */
  stops: RouteStop[]
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

// ── Collections ───────────────────────────────────────────────────────────────
// Curated famous descents, precomputed by backend/scripts/build_collections.py.
// The payload is split in two: GET /collections returns the index (no geometry,
// small enough to load on tab open), GET /collections/{slug} returns one spot's
// full routes. A collection route is an ordinary `Route` — same producer on the
// backend (pipeline.route_payload) — so every route component renders it as-is.

/** Index-card view of a curated spot: metadata + the best route's headline stats. */
export interface CollectionSpotSummary {
  slug: string
  name: string
  state: string
  blurb: string
  /**
   * Sports this spot is for — a list, since plenty of descents suit more than one.
   * Deliberately `string[]` and not a union: the Collections filter builds its chips
   * from whatever tags the data actually carries, so adding "gravel" or "mtb" to a spot
   * is a backend data edit with no frontend change. See backend/config.py DISCIPLINES.
   */
  disciplines: string[]
  /** Gotchas worth showing: closures, legality, surface. May be empty. */
  notes: string
  center: [number, number]  // [lon, lat]
  bbox: [number, number, number, number]  // south, west, north, east
  route_count: number
  // Headline stats, from the spot's best route.
  length_m: number
  total_descent_m: number
  avg_grade_pct: number
  top_speed_kmh: number
  flow_grade: string
}

export interface CollectionCity {
  city: string
  spots: CollectionSpotSummary[]
}

export interface CollectionsIndex {
  version: number
  cities: CollectionCity[]
}

/** One curated spot with its full routes (GET /collections/{slug}). */
export interface CollectionSpot extends CollectionSpotSummary {
  city: string
  rider_profile: RiderProfile
  built_at: string
  routes: Route[]
}

export interface RiderParams {
  weight_kg: number
  drag_coefficient: number
  frontal_area_m2: number
  crr_physics: number
  /** Rolling resistance used during pathfinding (affects which routes are found; requires re-search). */
  crr_pathfinding: number
  /**
   * Speed the rider will not exceed, km/h. Omitted/null = uncapped.
   *
   * Stands in for a brake, which this model does not have. Only the dirt profiles set
   * it: on tarmac, drag and Crr alone land near reported speeds, but on a loose fire
   * road the force balance computes 70 km/h where a real rider is braking at 30,
   * because traction and sightlines aren't forces. See backend/config.py RiderParams.
   */
  max_speed_kmh?: number | null
}

export type RiderProfile =
  | 'longboarder'
  | 'cyclist_upright'
  | 'cyclist_drops'
  | 'gravel'
  | 'mtb'

/** Mirrors backend/config.py RIDER_PROFILES — keep the two in sync. */
export const RIDER_PROFILES: Record<RiderProfile, RiderParams> = {
  longboarder: {
    weight_kg: 80,
    drag_coefficient: 0.75,
    frontal_area_m2: 0.35,
    crr_physics: 0.012,
    crr_pathfinding: 0.012,
  },
  cyclist_upright: {
    weight_kg: 80,
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
  gravel: {
    weight_kg: 82,
    drag_coefficient: 0.80,
    frontal_area_m2: 0.40,
    crr_physics: 0.010,
    crr_pathfinding: 0.010,
    max_speed_kmh: 55,
  },
  mtb: {
    weight_kg: 85,
    drag_coefficient: 1.00,
    frontal_area_m2: 0.45,
    crr_physics: 0.030,
    crr_pathfinding: 0.030,
    max_speed_kmh: 40,
  },
}

export interface Toggles {
  avoid_stoplights: boolean
  avoid_stop_signs: boolean
  avoid_bigger_roads: boolean
  avoid_equal_roads: boolean
  exclude_tunnels: boolean
  exclude_bridges: boolean
  stay_on_initial_road: boolean
  animate_candidates: boolean
}

export interface SearchOptions {
  bbox: [number, number, number, number]  // south, west, north, east
  road_types?: string[]
  rider_profile?: RiderProfile
  toggles?: Partial<Toggles>
  max_road_rank?: number
  allowed_surface_categories?: string[]
  /** Cap on 0-6 mtb:scale. Untagged ways are always allowed through — see backend/pipeline.py. */
  max_trail_difficulty?: number | null
  crr_pathfinding?: number
}

// SSE event shapes emitted by the backend
export type SSEEvent =
  | { type: 'queued'; position: number }
  | { type: 'busy'; message: string }
  | { type: 'status'; message: string }
  | { type: 'route'; route_id: string; start_node_id: number; geometry: RouteGeometry; metadata: RouteMetadata; elevations: number[]; segment_distances: number[]; flow_score: number; flow_grade: string; surface_pcts: Record<string, number>; trail_difficulty: number | null; stops: RouteStop[]; speed_profile: number[]; top_speed_kmh: number; avg_speed_kmh: number }
  | { type: 'candidate'; geometry: RouteGeometry }
  | { type: 'error'; message: string }
  | { type: 'done' }
