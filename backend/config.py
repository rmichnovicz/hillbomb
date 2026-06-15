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
    animate_candidates: bool = False


@dataclass
class SearchConfig:
    # Graph construction
    # Default 10m matches 3DEP 1/3 arc-sec (continental US baseline).
    # ElevationService sets this to 1.0 for 1m lidar areas or 30.0 for SRTM fallback.
    elevation_sample_interval_m: float = 10.0
    peak_search_radius_m: float = 75.0
    peak_min_elevation_delta_m: float = 4.0
    grade_inflection_threshold: float = 0.04

    # Pathfinding
    max_paths_per_node: int = 3
    max_routes: int = 9999
    priority_weight_speed: float = 1.0
    # Seed speed for paths starting at peak nodes (m/s).  A rider at a hilltop
    # has some momentum; starting from rest causes shallow summit sections
    # (grade < crr_pathfinding) to bleed speed before the real descent begins.
    # ~15 km/h lets paths traverse gentle openers without creating false routes
    # on truly flat ground (speed floor still fires before min_route_length_m).
    peak_seed_speed_ms: float = 5.6  # ≈ 20 km/h

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
        weight_kg=85,
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

# Road types included by default in search
DEFAULT_ROAD_TYPES: set[str] = {
    "tertiary", "tertiary_link",
    "unclassified",
    "residential",
    "service",
    "cycleway", "path",
    "living_street",
}
