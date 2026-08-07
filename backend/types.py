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
    # Technical difficulty on the 0-6 mtb:scale, or None when the way carries neither
    # `mtb:scale` nor `sac_scale` — which is most of them. See config.SAC_SCALE_TO_DIFFICULTY
    # for the derivation and for why "unknown" is a distinct state from "easy".
    trail_difficulty: int | None = None
    # The full road network is fetched on every search; this flag marks whether a
    # way may actually be ridden. Bigger roads are kept non-traversable so the
    # avoid-bigger/equal-roads toggles can detect (and stop at) a crossing without
    # ever routing onto them. Set in main.py; see overpass.ROAD_NETWORK_TYPES.
    traversable: bool = True


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
    # Hardest 0-6 mtb:scale grade on any segment of the route, or None if no segment
    # was tagged. The maximum rather than an average because difficulty is a gate:
    # one S4 rock roll in an otherwise smooth descent is what decides who can ride it.
    trail_difficulty: int | None = None
    # Surface tag → total distance (m) along that surface
    surface_distances: dict[str, float] = field(default_factory=dict)
    # Stop signs / traffic signals on this route, for map display. Includes the
    # start and end nodes. Each: {"type": "stop_sign"|"traffic_signal", "coord": [lon, lat]}.
    stops: list[dict] = field(default_factory=list)
    # Filled in by physics.py
    top_speed_kmh: float = 0.0
    avg_speed_kmh: float = 0.0
    speed_profile: list[float] = field(default_factory=list)
