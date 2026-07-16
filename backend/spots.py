"""
Curated famous descents — the "Collections" source data.

Each `Spot` is a proposal: a bounding box, the OSM way name(s) that identify the road,
and the metadata we show in the UI. `scripts/build_collections.py` runs the real search
pipeline over each spot and keeps the routes whose name matches `osm_way_names`.

Adding a spot is a list entry, not a new module. See `docs/collections.md`.

The two fields that actually decide whether a spot works:

  `osm_way_names` — the EXACT OSM `name` tag, not the popular name. "Hawk Hill" is not
      an OSM way; the way is named "Conzelman Road". Matched as a case-insensitive
      substring against the route name, so "Conzelman" catches "Conzelman Road".
  `bbox` — tight. We fetch the entire classified road network inside it, so a loose box
      means a slow build and a rude Overpass query. Road + ~200 m is the target.

`confidence` records how sure we are of those two. Anything below "high" is researched
but unproven — a build finding routes on it is the proof.
"""

from dataclasses import dataclass, field

from .config import Toggles


@dataclass(frozen=True)
class Spot:
    slug: str                                    # stable id; used as the JSON key and URL fragment
    name: str                                    # display name
    city: str                                    # metro grouping in the UI
    state: str                                   # 2-letter
    bbox: tuple[float, float, float, float]      # south, west, north, east
    osm_way_names: tuple[str, ...]               # exact OSM `name` tag substrings
    blurb: str                                   # 1-2 sentences: why it's famous
    discipline: str = "cycling"                  # "cycling" | "skate" | "both"

    # Pipeline overrides. Famous climbs are often `secondary`/`tertiary`, above the
    # app's default rideable cut, so spots frequently need to raise max_road_rank.
    rider_profile: str = "cyclist_upright"
    max_road_rank: int = 6                       # see config.HIGHWAY_RANK; 6 = secondary
    allowed_surface_categories: tuple[str, ...] | None = None  # None = all surfaces
    # Curated descents are a *named road*, so by default a route may not wander off it.
    # Spots whose descent legitimately changes name must set stay_on_initial_road=False
    # and list every name in osm_way_names.
    toggles: Toggles = field(default_factory=lambda: Toggles(
        avoid_stoplights=True,
        avoid_stop_signs=True,
        avoid_bigger_roads=True,
        avoid_equal_roads=False,
        stay_on_initial_road=True,
    ))
    max_routes: int = 4                          # kept per spot, best-first
    notes: str = ""                              # gotchas: closures, legality, surface
    confidence: str = "high"                     # high | medium | low


# ── The collection ────────────────────────────────────────────────────────────
#
# Ordering within a city is roughly "most famous first" — the UI preserves it.

SPOTS: list[Spot] = [
    # ── San Francisco Bay Area ────────────────────────────────────────────────
    Spot(
        slug="hawk-hill-conzelman",
        name="Hawk Hill (Conzelman Road)",
        city="San Francisco Bay Area",
        state="CA",
        # Captures the full Conzelman ridge and both descents. Verified by
        # tests/test_hawk_hill_e2e.py, which finds real routes in this box.
        bbox=(37.820, -122.515, 37.845, -122.470),
        osm_way_names=("Conzelman",),
        blurb=(
            "The classic Marin Headlands descent, straight off the north end of the "
            "Golden Gate Bridge. Conzelman climbs the ridge to Hawk Hill and drops back "
            "toward the bridge with the whole city in view — the single most-ridden "
            "postcard climb in the Bay Area."
        ),
        discipline="cycling",
        # Every Conzelman way is tagged `residential` (rank 3) as of 2026-07 — despite
        # being a major named climb — so the default cap of 6 covers it with room to
        # spare, and the connecting roads at the ridge stay rideable too.
        max_road_rank=6,
        notes=(
            "The westbound section past Hawk Hill is one-way downhill — the pathfinder "
            "respects that automatically. Popular with tourists and often busy."
        ),
        confidence="high",
    ),
]


def by_slug(slug: str) -> Spot | None:
    return next((s for s in SPOTS if s.slug == slug), None)


def by_city(city: str) -> list[Spot]:
    """Spots in a metro, matched case-insensitively."""
    return [s for s in SPOTS if s.city.lower() == city.lower()]


def cities() -> list[str]:
    """Distinct metros, in SPOTS order (not alphabetical — curation order is intentional)."""
    seen: list[str] = []
    for s in SPOTS:
        if s.city not in seen:
            seen.append(s.city)
    return seen
