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
#
# Every bbox and OSM name below was verified against live Overpass (2026-07); the raw
# research, including grades, history and rejected candidates, is in
# docs/research/famous-descents.md. Where a spot is `confidence="medium"`, the doubt is
# recorded in `notes` — usually a claimed-but-unsurveyed grade, or a road whose famous
# section is a subjective slice of a longer way.
#
# Note on max_road_rank: every road here is rank <= 6 (secondary), so all of them work
# at the default. Several are tagged far below their stature — Conzelman and Baxter are
# `residential`, Mt. Diablo and Maryhill are `unclassified` — which is exactly why the
# rank cap is a per-spot field rather than an assumption.

SPOTS: list[Spot] = [
    # ── San Francisco Bay Area ────────────────────────────────────────────────
    Spot(
        slug="hawk-hill-conzelman",
        name="Hawk Hill (Conzelman Road)",
        city="San Francisco Bay Area",
        state="CA",
        # Union bbox of the 20 real Conzelman ways, so it holds both the descent back
        # toward the bridge and the one-way drop west to Point Bonita.
        bbox=(37.82315, -122.52901, 37.83378, -122.48336),
        osm_way_names=("Conzelman",),
        blurb=(
            "The single most photographed climb in the Bay Area — the Marin Headlands "
            "road up from the Golden Gate Bridge's north end to the Hawk Hill summit, "
            "with the bridge and city framed behind. A fixture of San Francisco Grand "
            "Prix-era racing and the standard Saturday effort for every SF club."
        ),
        discipline="cycling",
        notes=(
            "West of the summit Conzelman is one-way downhill — 17 of its 20 ways carry "
            "oneway=yes — so the descent toward Point Bonita has no oncoming traffic. "
            "Popular with tourists and often busy."
        ),
        confidence="high",
    ),
    Spot(
        slug="old-la-honda",
        name="Old La Honda Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.35716, -122.26613, 37.39599, -122.24435),
        osm_way_names=("Old La Honda Road",),
        blurb=(
            "The Bay Area's benchmark climb and de facto fitness test: the 5.6 km east "
            "side from Portola Road to Skyline is the most-ridden timed segment on the "
            "Peninsula, with a sub-15-minute time the long-standing marker of a serious "
            "amateur."
        ),
        discipline="cycling",
        notes=(
            "Narrow, no centerline, and damp under redwoods much of the year — the "
            "descent is technical rather than fast. The bbox covers both sides of Skyline."
        ),
        confidence="high",
    ),
    Spot(
        slug="mt-diablo-south-gate",
        name="Mount Diablo — South Gate Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.84063, -121.94985, 37.86693, -121.92033),
        osm_way_names=("South Gate Road",),
        blurb=(
            "The lower half of the Bay Area's premier mountain climb and the route of "
            "the Mt. Diablo Challenge, run every October since 1982 — the 17.7 km race "
            "from Athenian School to the summit where breaking one hour earns you the "
            "'under an hour' shirt."
        ),
        discipline="cycling",
        notes="State park road: entrance fee for cars, and the gates close at sunset.",
        confidence="high",
    ),
    Spot(
        slug="mt-diablo-summit-road",
        name="Mount Diablo — Summit Road",
        city="San Francisco Bay Area",
        state="CA",
        # "Summit Road" is a very common name nationally; this tight bbox is the only
        # thing disambiguating it, since we match the name as a substring.
        bbox=(37.86252, -121.93222, 37.88174, -121.91410),
        osm_way_names=("Summit Road",),
        blurb=(
            "The upper mountain — from Junction Ranger Station to the 1,173 m summit, "
            "including the notorious final pitch to the observation tower that decides "
            "the Mt. Diablo Challenge every year."
        ),
        discipline="cycling",
        notes="Ice and seasonal closures near the top.",
        confidence="high",
    ),
    Spot(
        slug="marin-avenue-berkeley",
        name="Marin Avenue (Berkeley)",
        city="San Francisco Bay Area",
        state="CA",
        # Clipped to the wall above Arlington; lower Marin Ave is flat.
        bbox=(37.88774, -122.29267, 37.89841, -122.25982),
        osm_way_names=("Marin Avenue",),
        blurb=(
            "The steepest sustained paved street climb in the Bay Area — the "
            "arrow-straight wall from Arlington Avenue to Grizzly Peak Boulevard, "
            "pitching to roughly 25%, and a rite of passage for East Bay cyclists."
        ),
        discipline="both",
        notes=(
            "Real traffic, and cross streets with stop signs the whole way down. Steep "
            "enough that the descent is genuinely brake-limited rather than fast."
        ),
        confidence="high",
    ),
    Spot(
        slug="twin-peaks-blvd",
        name="Twin Peaks Boulevard",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.74577, -122.45089, 37.76110, -122.44567),
        osm_way_names=("Twin Peaks Boulevard",),
        blurb=(
            "San Francisco's signature summit road and one of the city's classic skate "
            "bombs — the switchbacked drop from the 280 m overlook into the Castro, with "
            "the whole city laid out ahead."
        ),
        discipline="both",
        notes=(
            "The north loop is now the car-free Twin Peaks Promenade; OSM tags it as "
            "construction/pedestrian, so the pathfinder won't route onto it and the road "
            "may come back fragmented. Fog and wind are constant."
        ),
        confidence="high",
    ),
    Spot(
        slug="dolores-street",
        name="Dolores Street",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.74040, -122.42602, 37.75992, -122.42396),
        osm_way_names=("Dolores Street",),
        blurb=(
            "The most famous street skate bomb in San Francisco — the palm-lined drop "
            "from Dolores Heights through the Mission, immortalized by the annual "
            "unsanctioned hill bombs that draw hundreds of skaters."
        ),
        discipline="skate",
        rider_profile="longboarder",
        notes=(
            "Legally fraught: SFPD has repeatedly cracked down on the Dolores bombs, with "
            "mass citations and arrests in 2023. A divided boulevard with real traffic, "
            "stop signs and Muni — each carriageway is a separate one-way OSM way."
        ),
        confidence="high",
    ),
    Spot(
        slug="filbert-street-sf",
        name="Filbert Street (Russian Hill)",
        city="San Francisco Bay Area",
        state="CA",
        # Clipped to the single steep Hyde–Leavenworth block. Filbert Street runs flat
        # for kilometres either side, so the name alone would match the wrong road.
        bbox=(37.80010, -122.41938, 37.80057, -122.41583),
        osm_way_names=("Filbert Street",),
        blurb=(
            "Tied with 22nd Street as the steepest street in San Francisco at a surveyed "
            "31.5% — the Hyde-to-Leavenworth block on Russian Hill, steep enough that the "
            "city paved it in concrete with traction ridges and the sidewalks are stairs."
        ),
        discipline="skate",
        rider_profile="longboarder",
        notes=(
            "One extreme block, not a sustained run. Concrete with transverse traction "
            "ridges — rough and grabby on urethane. Expect Hillbomb to under-read the "
            "grade here: 10 m elevation data smooths a 31.5% pitch to about 14%."
        ),
        confidence="high",
    ),
    Spot(
        slug="bradford-street-sf",
        name="Bradford Street (Bernal Heights)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.73688, -122.40977, 37.74323, -122.40937),
        osm_way_names=("Bradford Street",),
        blurb=(
            "Widely cited as the steepest street in San Francisco — and arguably in the "
            "US — at a claimed 41% on the short dead-end pitch above Tompkins Avenue, on "
            "the north face of Bernal Heights."
        ),
        discipline="skate",
        rider_profile="longboarder",
        notes=(
            "The 41% is a claim, not a survey, and applies only to a short dead-end stub "
            "rather than the street as a whole. It doesn't connect through: a stunt pitch, "
            "not a descent with a run-out."
        ),
        confidence="medium",
    ),
    Spot(
        slug="page-mill-road",
        name="Page Mill Road (upper)",
        city="San Francisco Bay Area",
        state="CA",
        # Clipped to the tertiary upper section. Lower Page Mill is a trunk/primary
        # expressway by I-280 — out of this box, and above the rank cap regardless.
        bbox=(37.31489, -122.18931, 37.38948, -122.16197),
        osm_way_names=("Page Mill Road",),
        blurb=(
            "One of the Peninsula's great sustained climbs, rising from Palo Alto to "
            "Skyline Boulevard past Foothills Park — a Silicon Valley classic and the "
            "standard long effort paired with Old La Honda."
        ),
        discipline="cycling",
        notes="The lower half of Page Mill is an expressway; this is the upper road only.",
        confidence="medium",
    ),
    Spot(
        slug="sierra-road-san-jose",
        name="Sierra Road",
        city="San Francisco Bay Area",
        state="CA",
        # Clipped to the famous climb from near Piedmont Rd east.
        bbox=(37.39519, -121.85702, 37.41461, -121.80009),
        osm_way_names=("Sierra Road",),
        blurb=(
            "The decisive climb of the Amgen Tour of California — the brutally exposed "
            "wall above East San Jose that shattered the peloton on multiple editions and "
            "remains the Bay Area's hardest big climb."
        ),
        discipline="cycling",
        notes="No shade and no water, but a fast, open descent.",
        confidence="medium",
    ),
    Spot(
        slug="mt-tam-ridgecrest",
        name="Mount Tamalpais — Ridgecrest Boulevard",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.90905, -122.65837, 37.93937, -122.61258),
        osm_way_names=("Ridgecrest Boulevard",),
        blurb=(
            "The ridge road along Mt. Tamalpais to the East Peak — the mountain where "
            "mountain biking was invented, the Repack downhill running nearby — and the "
            "most scenic paved descent in Marin."
        ),
        discipline="cycling",
        notes=(
            "Ridgecrest is the ridge road: rolling, with a low average grade. The real "
            "elevation is gained below it on Panoramic Highway. Gated in fire weather."
        ),
        confidence="high",
    ),

    # ── Los Angeles ───────────────────────────────────────────────────────────
    Spot(
        slug="baxter-street",
        name="Baxter Street (Echo Park)",
        city="Los Angeles",
        state="CA",
        bbox=(34.08821, -118.26230, 34.09464, -118.24720),
        osm_way_names=("Baxter Street",),
        blurb=(
            "One of the steepest streets in the United States at about 32%, famous well "
            "beyond cycling: the blind crest became a viral Waze-routing disaster, with "
            "cars bottoming out and crashing often enough that LA restricted it in 2019."
        ),
        discipline="skate",
        rider_profile="longboarder",
        notes=(
            "The crest is genuinely blind — drivers cannot see over it, which is exactly "
            "what makes bombing it dangerous. Concrete on the steep blocks."
        ),
        confidence="high",
    ),
    Spot(
        slug="eldred-street",
        name="Eldred Street (Highland Park)",
        city="Los Angeles",
        state="CA",
        bbox=(34.10773, -118.20991, 34.10977, -118.20563),
        osm_way_names=("Eldred Street",),
        blurb=(
            "Frequently ranked the steepest street in Los Angeles at about 33% — so steep "
            "it dead-ends in a staircase, garbage trucks refuse to drive it, and the city "
            "serves it with a special small vehicle."
        ),
        discipline="skate",
        rider_profile="longboarder",
        notes="A dead end that finishes in stairs. Very short, narrow, and no run-out.",
        confidence="high",
    ),
    Spot(
        slug="fargo-street",
        name="Fargo Street (Echo Park)",
        city="Los Angeles",
        state="CA",
        bbox=(34.08889, -118.26285, 34.09373, -118.25002),
        osm_way_names=("Fargo Street",),
        blurb=(
            "Home of the Fargo Street Hill Climb, run by the Los Angeles Wheelmen every "
            "year since 1974 — the oldest 'can you even ride up it' event in American "
            "cycling, on a roughly 32% pitch where most entrants fail."
        ),
        discipline="cycling",
        notes="Concrete, and on the same Echo Park hill as Baxter Street.",
        confidence="high",
    ),
    Spot(
        slug="glendora-mountain-road",
        name="Glendora Mountain Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.14162, -117.84977, 34.22984, -117.77195),
        osm_way_names=("Glendora Mountain Road",),
        blurb=(
            "'GMR' — the most-ridden mountain road in Southern California and the "
            "training ground for generations of LA racers: 24 km of near-constant "
            "gradient above Glendora, immaculate surface, legendary descent."
        ),
        discipline="cycling",
        notes=(
            "Subject to fire and storm closures that have lasted years at a time. Heavy "
            "motorcycle traffic on weekends. The largest bbox in the collection — expect "
            "a slow first build."
        ),
        confidence="medium",
    ),
    Spot(
        slug="latigo-canyon",
        name="Latigo Canyon Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.02997, -118.81544, 34.09214, -118.75350),
        osm_way_names=("Latigo Canyon Road",),
        blurb=(
            "The best-known climb in the Santa Monica Mountains — 16 km of switchbacks "
            "from Pacific Coast Highway to the ridge, a staple of Malibu gran fondos and "
            "the descent that defines Malibu road riding."
        ),
        discipline="cycling",
        notes="The drop back to PCH is fast and open, with long sightlines.",
        confidence="medium",
    ),
    Spot(
        slug="tuna-canyon",
        name="Tuna Canyon Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.03946, -118.61767, 34.07738, -118.58832),
        osm_way_names=("Tuna Canyon Road",),
        blurb=(
            "Roughly 70 turns in four miles dropping to the Pacific — and most of it is "
            "legally one-way downhill, a legacy of an old mudslide, so you get the whole "
            "road with no oncoming traffic. One of the most sought-after descents in "
            "California for cyclists and longboarders alike."
        ),
        discipline="both",
        notes=(
            "The one-way-downhill status is the entire appeal, but OSM's tagging doesn't "
            "reflect it: only 1 of 7 ways carries oneway=yes and one is explicitly "
            "oneway=no, so the pathfinder may route it in both directions. Narrow, blind "
            "turns, no guardrail."
        ),
        confidence="medium",
    ),
    Spot(
        slug="piuma-road",
        name="Piuma Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.06501, -118.70455, 34.08219, -118.65343),
        osm_way_names=("Piuma Road",),
        blurb=(
            "A Santa Monica Mountains classic climbed from Malibu Canyon, and one of the "
            "most consistently used race-simulation climbs for LA-area cyclists."
        ),
        discipline="cycling",
        notes="Pairs with Stunt Road on the standard Malibu loop.",
        confidence="medium",
    ),
    Spot(
        slug="stunt-road",
        name="Stunt Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.08041, -118.66502, 34.10193, -118.64574),
        osm_way_names=("Stunt Road",),
        blurb=(
            "One of the definitive Santa Monica Mountains climbs, running from Mulholland "
            "Highway to Saddle Peak — a fixture of Malibu loops and a well-known "
            "motorcycle and cycling road."
        ),
        discipline="cycling",
        notes="Good surface, technical descent.",
        confidence="medium",
    ),

    # ── Seattle ───────────────────────────────────────────────────────────────
    Spot(
        slug="queen-anne-counterbalance",
        name="Queen Anne Avenue North (the Counterbalance)",
        city="Seattle",
        state="WA",
        bbox=(47.61859, -122.35770, 47.65041, -122.35661),
        osm_way_names=("Queen Anne Avenue North",),
        blurb=(
            "'The Counterbalance' — named for the underground 16-ton counterweights that "
            "hauled streetcars up this ~18% grade from 1900 to 1940. The tunnels are "
            "still under the street. Seattle's most storied hill."
        ),
        discipline="skate",
        rider_profile="longboarder",
        notes="A busy arterial with real traffic and signals at Mercer and Roy.",
        confidence="high",
    ),

    # ── Denver / Boulder ──────────────────────────────────────────────────────
    Spot(
        slug="lookout-mountain-road",
        name="Lookout Mountain Road",
        city="Denver / Boulder",
        state="CO",
        bbox=(39.71607, -105.25377, 39.74941, -105.22751),
        osm_way_names=("Lookout Mountain Road",),
        blurb=(
            "Colorado's most-ridden climb — the switchbacks out of Golden past Buffalo "
            "Bill's grave, used by the Coors Classic and the USA Pro Challenge, and the "
            "daily proving ground for the Front Range."
        ),
        discipline="cycling",
        notes=(
            "Tagged bicycle=designated on several ways, with wide shoulders. The descent "
            "into Golden is fast, open and well-sighted."
        ),
        confidence="high",
    ),
    Spot(
        slug="flagstaff-road",
        name="Flagstaff Road (Flagstaff Mountain)",
        city="Denver / Boulder",
        state="CO",
        bbox=(39.98003, -105.33248, 40.00695, -105.28072),
        osm_way_names=("Flagstaff Road",),
        blurb=(
            "Boulder's iconic climb, rising straight out of Chautauqua Park — a regular "
            "USA Pro Challenge summit finish and probably the most famous training climb "
            "in American cycling, ridden by decades of Boulder-based pros."
        ),
        discipline="cycling",
        notes="Steep, tight switchbacks low down make for a technical descent.",
        confidence="high",
    ),

    # ── Columbia Gorge ────────────────────────────────────────────────────────
    Spot(
        slug="maryhill-loops",
        name="Maryhill Loops Road",
        city="Columbia Gorge",
        state="WA",
        bbox=(45.70455, -120.80931, 45.72557, -120.79283),
        osm_way_names=("Maryhill Loops Road",),
        blurb=(
            "The most famous downhill skateboarding road in America. Built in 1911 as "
            "Washington's first asphalt road, it's now owned by the Maryhill Museum, "
            "closed to cars most of the year, and rented to longboard clubs — 2.1 miles "
            "and 21 bends of pristine, traffic-free pavement."
        ),
        discipline="skate",
        rider_profile="longboarder",
        notes=(
            "A private road owned by the Maryhill Museum. Skating it requires a paid, "
            "waivered event — you cannot just show up and bomb it."
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
