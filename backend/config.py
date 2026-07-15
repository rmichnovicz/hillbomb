from dataclasses import dataclass, field


@dataclass
class RiderParams:
    weight_kg: float
    drag_coefficient: float
    frontal_area_m2: float
    crr_physics: float
    crr_pathfinding: float
    min_continue_speed_kmh: float
    min_route_length_m: float


@dataclass
class Toggles:
    avoid_stoplights: bool = True
    avoid_stop_signs: bool = True
    avoid_bigger_roads: bool = True
    avoid_equal_roads: bool = False
    exclude_tunnels: bool = False
    exclude_bridges: bool = False
    # When set, a descent may only continue onto ways sharing the same name as the
    # road it started on. Multiple OSM ways combine freely as long as the name
    # matches; the first edge off the seed establishes the name. Unnamed start
    # roads constrain to other unnamed ways (OSM has no name to match on).
    stay_on_initial_road: bool = False
    animate_candidates: bool = False


@dataclass
class SearchConfig:
    # Graph construction
    # Default 10m matches 3DEP 1/3 arc-sec (continental US baseline).
    # ElevationService sets this to 1.0 for 1m lidar areas or 30.0 for SRTM fallback.
    elevation_sample_interval_m: float = 10.0
    peak_search_radius_m: float = 75.0
    peak_min_elevation_delta_m: float = 4.0
    grade_inflection_threshold: float = 0.04  # 4% grade change triggers an inflection node
    # Bridges/tunnels longer than this span are excluded entirely.  A 500 m cutoff
    # keeps neighborhood bridges while dropping major spans (Golden Gate = 2.7 km,
    # Bay Bridge = 7 km) that produce flat, near-0-km/h routes.
    max_bridge_span_m: float = 500.0

    # Pathfinding
    max_paths_per_node: int = 3
    max_routes: int = 9999
    # Initial speed for a freshly seeded path (m/s).  Seeds start wherever the
    # road first tips downhill (see find_routes), not only at detected peaks, and
    # a rider rolling into a descent already carries some momentum.  Starting
    # from rest would let a shallow opener (grade just past crr_pathfinding) bleed
    # to the speed floor and terminate the route before the real drop begins;
    # ~20 km/h carries paths through gentle openers without manufacturing routes
    # on flat ground (the speed floor still fires before min_route_length_m).
    seed_speed_ms: float = 5.6  # ≈ 20 km/h

    # Physics
    air_density_kg_m3: float = 1.225

    # Flow score penalties (deducted from 100)
    flow_penalty_stoplight: float = 30.0
    flow_penalty_bigger_road: float = 25.0
    flow_penalty_equal_road: float = 15.0
    flow_penalty_stop_sign: float = 10.0
    flow_penalty_surface_cobble: float = 30.0
    flow_penalty_surface_gravel: float = 20.0
    flow_penalty_surface_unpaved: float = 15.0


RIDER_PROFILES: dict[str, RiderParams] = {
    "longboarder": RiderParams(
        weight_kg=80,
        drag_coefficient=0.75,
        frontal_area_m2=0.35,
        crr_physics=0.012,
        crr_pathfinding=0.012,  # physics split handles stall termination; no longer needs inflation
        min_continue_speed_kmh=5,
        min_route_length_m=60,
    ),
    "cyclist_upright": RiderParams(
        weight_kg=80,
        drag_coefficient=0.88,
        frontal_area_m2=0.42,
        crr_physics=0.004,
        crr_pathfinding=0.004,
        min_continue_speed_kmh=8,
        min_route_length_m=150,
    ),
    "cyclist_drops": RiderParams(
        weight_kg=80,
        drag_coefficient=0.70,
        frontal_area_m2=0.32,
        crr_physics=0.003,
        crr_pathfinding=0.003,
        min_continue_speed_kmh=8,
        min_route_length_m=150,
    ),
}

# OSM highway classification hierarchy (higher index = more major)
HIGHWAY_RANK: dict[str, int] = {
    "path": 0,
    "cycleway": 0,
    "living_street": 1,
    "service": 2,
    "residential": 3,
    "unclassified": 4,
    "tertiary": 5,
    "tertiary_link": 5,
    "secondary": 6,
    "secondary_link": 6,
    "primary": 7,
    "primary_link": 7,
    "trunk": 8,
    "trunk_link": 8,
    "motorway": 9,
    "motorway_link": 9,
}

# Surface category → OSM surface tag values
SURFACE_CATEGORIES: dict[str, set[str]] = {
    "paved": {"asphalt", "concrete", "paved", "tarmac", "chipseal", "concrete:plates"},
    "gravel": {"gravel", "fine_gravel", "compacted", "crushed_limestone", "pebblestone"},
    "unpaved": {"unpaved", "dirt", "ground", "grass", "sand", "mud", "earth", "woodchips"},
    "cobblestone": {"cobblestone", "sett", "paving_stones", "unhewn_cobblestone", "cobblestone:flattened"},
}

# Road types eligible to be ridden when a request doesn't pin an explicit set.
# This is the FULL classified network (every highway class we fetch); the actual
# size cut is made by max_road_rank, surfaced in the UI as the "Max road size"
# slider. Keeping the default universe complete is what lets that slider reach all
# the way up to primary/trunk/motorway — a narrower set here would silently shadow
# its upper steps (the slider could raise the rank cap but the road would still be
# filtered out by membership). max_road_rank defaults to secondary (see
# SearchRequest), and the avoid-bigger/equal-road toggles still stop a descent at
# busier crossings, so the out-of-the-box ride is unchanged; the user can now
# opt all the way up when they want it.
DEFAULT_ROAD_TYPES: set[str] = set(HIGHWAY_RANK)
