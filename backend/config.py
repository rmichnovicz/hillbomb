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
    # Speed the rider will not exceed, km/h. None = no cap (the pure coasting model).
    #
    # This is a stand-in for braking, and it exists because the model has none. On
    # pavement that omission is survivable: drag and Crr alone land a road descent
    # somewhere near the speed people actually report. Off pavement it isn't. A loose
    # 15% fire road produces a computed 70 km/h where a real rider is hard on the
    # brakes at 30, because what limits them is traction, sightline and rock, none of
    # which the force balance knows about. Rather than pretend to model that, dirt
    # profiles state the ceiling directly and the sim clamps to it.
    #
    # A capped profile's top_speed_kmh reads "at the limit", not "this is how fast the
    # hill is" — the honest reading of a number that came from a constant, not physics.
    max_speed_kmh: float | None = None
    # Surface categories the flow score treats as rough FOR THIS RIDER (see scoring.py).
    #
    # Roughness is relative to what you came for. The flow score deducts per edge, so a
    # 6 km descent on gravel accrues the gravel penalty a couple of hundred times and
    # floors at zero — correct for a road cyclist who wanted tarmac, and nonsense for a
    # gravel rider, who is on gravel on purpose. Left global, it graded every dirt spot
    # in Collections F and made the letter meaningless across the whole discipline.
    #
    # So the penalty values stay in SearchConfig and the *set they apply to* rides on
    # the profile: gravel riders are still penalized by cobbles, MTB riders by nothing
    # underfoot. The default is the full set, so road profiles are unchanged.
    rough_surface_categories: tuple[str, ...] = ("cobblestone", "gravel", "unpaved")


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
    # How many path lineages may pass through one node; the 4th is finalized where
    # it stands. Note this is cumulative over the whole search, not a count of
    # paths alive right now — node_path_count is incremented per fork and only
    # ever released for a seed that gets skipped. That is what makes it an
    # effective brake on branching, and also what makes it truncate a descent
    # mid-road once a few earlier lineages have used up a node.
    # At 3 it did: Harris Creek Road came out as 15.5 km + two fragments, split on
    # a 0.4% straight, and Pacheco Canyon lost nearly half its length. 4 restores
    # both to one continuous route for about 5% more search time; past 4 nothing
    # further is recovered on any spot in the collection.
    max_paths_per_node: int = 4
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
    # ── Dirt ──────────────────────────────────────────────────────────────────
    # The two dirt profiles differ from the road ones in three ways, all of which
    # matter to what the pathfinder finds, not just to what the chart draws:
    #
    #   crr — loose surface. Measured Crr on gravel runs ~0.008-0.012 and on soft or
    #       chunky trail ~0.025-0.035, against 0.004 on tarmac. Since crr_pathfinding
    #       is also the seed threshold (`find_routes` seeds where grade steepens past
    #       it), a higher value is what stops a dirt search from seeding on every
    #       barely-tilted fire road.
    #   min_continue_speed_kmh — low. A tech descent at 6 km/h is a normal MTB
    #       descent, whereas on tarmac that speed means the descent is over. Holding
    #       the road profiles' 8 km/h floor would truncate real trails mid-run.
    #   max_speed_kmh — see RiderParams.max_speed_kmh. Dirt is where the model's
    #       missing brake actually breaks the answer.
    "gravel": RiderParams(
        weight_kg=82,
        drag_coefficient=0.80,   # hoods on a gravel bike; less tucked than drops
        frontal_area_m2=0.40,    # CdA ≈ 0.32
        crr_physics=0.010,
        crr_pathfinding=0.010,
        min_continue_speed_kmh=6,
        min_route_length_m=150,
        max_speed_kmh=55,
        # Cobbles still break a gravel rider's flow; loose surface is the point.
        rough_surface_categories=("cobblestone",),
    ),
    "mtb": RiderParams(
        weight_kg=85,            # heavier bike: full-suspension, dropper, tyres
        drag_coefficient=1.00,   # upright, attack position, no tuck
        frontal_area_m2=0.45,    # CdA ≈ 0.45
        crr_physics=0.030,
        crr_pathfinding=0.030,
        min_continue_speed_kmh=4,
        min_route_length_m=150,
        max_speed_kmh=40,
        # Nothing underfoot counts against an MTB descent. What breaks its flow is
        # traffic and junctions, which the node and road-rank penalties still catch.
        rough_surface_categories=(),
    ),
}

# Sports a curated spot can be tagged with. A spot carries a list of these, so a descent
# ridden by more than one crowd says so directly. The Collections filter derives its
# chips from the tags actually in use, so a discipline no spot claims shows no chip.
DISCIPLINES: dict[str, str] = {
    "road": "Road bike",
    "skate": "Skate",
    "gravel": "Gravel",
    "mtb": "MTB",
}

# OSM highway classification hierarchy (higher index = more major).
#
# The ordering tracks traffic danger ON PAVEMENT, which is what the
# avoid-bigger/equal-roads toggles are for. Off pavement it misfires: a trail meeting a
# dirt forest road (`unclassified`, rank 4) reads as meeting a bigger road and ends the
# descent there. See the Downieville spot, which turns that toggle off for this reason.
HIGHWAY_RANK: dict[str, int] = {
    "path": 0,
    "cycleway": 0,
    # Fire roads and gravel doubletrack. Rank 0 with the other unpaved-by-default
    # classes, and below `service`, because a track is never the *bigger* road at a
    # junction. ROAD_NETWORK_TYPES is derived from these keys, so adding it here is
    # what makes fire-road descents reachable at all — nothing downstream can route
    # onto a way Overpass was never asked for.
    "track": 0,
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

# ── Trail difficulty ──────────────────────────────────────────────────────────
#
# One 0-6 integer, on the OSM `mtb:scale` (Singletrail-Skala) scale:
#
#   0  smooth doubletrack / fire road          3  large obstacles, tight switchbacks
#   1  small obstacles, loose surface          4  loose scree, drops, steps
#   2  bigger roots and rocks, some steps      5-6  expert / borderline unrideable
#
# `mtb:scale` is the value we want and it is the one riders tag. Where it is absent we
# fall back to `sac_scale`, the *hiking* difficulty scale. The two do not measure the
# same thing — sac_scale grades exposure and footing for a walker, not the ride — so
# this mapping is a conservative upper bound rather than a translation: a path graded
# demanding_mountain_hiking is certainly not smooth doubletrack, which is all we claim.
# When both are present the higher of the two wins.
#
# COVERAGE IS THIN, and that shapes how the filter treats it. Most US trails carry
# neither tag, so an untagged way maps to None (unknown), and `max_trail_difficulty`
# lets unknowns through rather than excluding them — the same choice `surface` already
# makes, for the same reason. This means the filter can tighten a search that is
# already on trails; it cannot be relied on to keep singletrack out of a road search.
# Pinning `osm_way_names` and the surface filter are what do that job.
MAX_TRAIL_DIFFICULTY = 6

SAC_SCALE_TO_DIFFICULTY: dict[str, int] = {
    "hiking": 1,                        # T1
    "mountain_hiking": 2,               # T2
    "demanding_mountain_hiking": 3,     # T3
    "alpine_hiking": 4,                 # T4
    "demanding_alpine_hiking": 5,       # T5
    "difficult_alpine_hiking": 6,       # T6
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
