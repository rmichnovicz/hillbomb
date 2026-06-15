from dataclasses import dataclass, field


@dataclass
class OSMNode:
    id: int
    lat: float
    lon: float
    elevation: float = 0.0
    # OSM tags relevant to pathfinding
    is_traffic_signal: bool = False
    is_stop_sign: bool = False


@dataclass
class OSMWay:
    id: int
    node_ids: list[int]
    highway: str
    oneway: bool       # True = forward only
    oneway_reverse: bool  # True = reverse only (oneway=-1)
    is_bridge: bool = False
    is_tunnel: bool = False
    surface: str = ""  # e.g. "asphalt", "cobblestone", "gravel"
    name: str = ""


@dataclass
class Route:
    route_id: str
    node_ids: list[int]
    # Geometry as list of [lon, lat] pairs
    coordinates: list[list[float]]
    # Elevation at each coordinate point (m)
    elevations: list[float]
    # Distance between consecutive points (m)
    segment_distances: list[float]
    # Highway type of the steepest segment (for naming)
    primary_highway: str
    # OSM node ID of the route's starting peak
    start_node_id: int = 0
    name: str = ""
    length_m: float = 0.0
    total_descent_m: float = 0.0
    avg_grade_pct: float = 0.0
    flow_score: float = 100.0
    flow_grade: str = "A"
    # Surface tag → total distance (m) along that surface
    surface_distances: dict[str, float] = field(default_factory=dict)
    # Filled in by physics.py
    top_speed_kmh: float = 0.0
    avg_speed_kmh: float = 0.0
    speed_profile: list[float] = field(default_factory=list)
