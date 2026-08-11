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
    blurb: str                                   # one line: where it is + what the descent is like
    # Which sports a spot is for. A list, not one value, because plenty of descents are
    # ridden by more than one — Marin Avenue is both a road-bike wall and a skate bomb,
    # and the old "both" value was that idea encoded as a special case. See
    # config.DISCIPLINES for the vocabulary.
    disciplines: tuple[str, ...] = ("road",)

    # Pipeline overrides. Famous climbs are often `secondary`/`tertiary`, above the
    # app's default rideable cut, so spots frequently need to raise max_road_rank.
    rider_profile: str = "cyclist_upright"
    max_road_rank: int = 6                       # see config.HIGHWAY_RANK; 6 = secondary
    allowed_surface_categories: tuple[str, ...] | None = None  # None = all surfaces
    # Cap on 0-6 mtb:scale; None = any. Rarely worth setting, because OSM difficulty
    # coverage is thin enough that untagged ways have to be allowed through
    # (pipeline.mark_traversable) — a trail spot is far better pinned by osm_way_names.
    max_trail_difficulty: int | None = None
    # Curated descents are a *named road*, so by default a route may not wander off it.
    # Spots whose descent legitimately changes name must set stay_on_initial_road=False
    # and list every name in osm_way_names.
    #
    # The stop toggles are OFF here, unlike a normal search, and that difference is the
    # whole point: a spot is one named famous descent, and a rider bombing it rolls the
    # stop signs. With them on, the pathfinder cut every descent at its first cross
    # street and both halves came back as separate routes on the same road — Mt. Diablo
    # Summit Road shipped as two 3.5 km routes meeting at a stop sign, Marin Avenue as
    # four ~200 m blocks of a 1 km wall. Stops encountered mid-descent are recorded in
    # `route.stops` and penalized by the flow score, which is how the route model was
    # always meant to express "there's a signal in this run".
    #
    # avoid_bigger_roads stays on: a descent really does end where it meets a highway.
    toggles: Toggles = field(default_factory=lambda: Toggles(
        avoid_stoplights=False,
        avoid_stop_signs=False,
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
# Note on max_road_rank: most roads here are rank <= 6 (secondary) and work at the
# default. Several are tagged far below their stature — Conzelman and Baxter are
# `residential`, Mt. Diablo and Maryhill are `unclassified` — which is exactly why the
# rank cap is a per-spot field rather than an assumption.
#
# Ten need it raised, and they are the roads whose fame *is* that they are the state
# highway over a pass: Angeles Crest, Mount Rose, Washington Pass, Crawford Notch and
# Oak Creek Canyon are `primary`, and Newfound Gap Road through the Smokies is `trunk`,
# the only rank-8 spot in the collection. Raising the cap on those is not a loophole —
# there is no smaller road over the pass. Their `notes` carry the traffic warning that
# the rank was standing in for.

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
            "Switchbacks off the Marin Headlands down to the Golden Gate Bridge, with "
            "the city framed behind you the whole way."
        ),
        disciplines=("road",),
        notes=(
            "Two descents leave the summit. Past the top the road turns one-way downhill "
            "toward Point Bonita — no oncoming traffic, and much the longer of the two. "
            "The other drops east back toward the bridge. Busy with tourists most of the day."
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
            "The Peninsula's benchmark climb, winding up through second-growth redwoods "
            "from Portola Road to Skyline."
        ),
        disciplines=("road",),
        notes=(
            "Narrow, no centerline, and damp under redwoods much of the year — the "
            "descent is technical rather than fast."
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
            "The lower half of Mount Diablo — long, steady switchbacks, and the first "
            "half of the Diablo Challenge."
        ),
        disciplines=("road",),
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
            "The upper mountain — Junction Ranger Station to the 1,173 m summit, "
            "finishing on a notoriously steep ramp to the observation tower."
        ),
        disciplines=("road",),
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
            "The steepest sustained street in the Bay Area — an arrow-straight 25% wall "
            "from Arlington Avenue up to Grizzly Peak."
        ),
        disciplines=("road", "skate"),
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
            "Switchbacks from the 280 m overlook down into the Castro, with the whole "
            "city ahead of you."
        ),
        disciplines=("road", "skate"),
        notes=(
            "The north loop is now the car-free Twin Peaks Promenade, closed to through "
            "traffic, so the road may come back in pieces here. Fog and wind are "
            "constant."
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
            "A straight, palm-lined drop from Dolores Heights through the Mission — "
            "San Francisco's best-known street bomb."
        ),
        disciplines=("skate",),
        rider_profile="longboarder",
        notes=(
            "Legally fraught: SFPD has repeatedly cracked down on the Dolores bombs, "
            "with mass citations and arrests in 2023. A divided boulevard with real "
            "traffic, stop signs and Muni."
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
            "Tied for the steepest street in San Francisco at a surveyed 31.5% — one "
            "Russian Hill block, with stairs for sidewalks."
        ),
        disciplines=("skate",),
        rider_profile="longboarder",
        notes=(
            "One extreme block, not a sustained run. Concrete with transverse traction "
            "ridges — rough and grabby on urethane. The grade shown reads low: our "
            "elevation data smooths a surveyed 31.5% pitch to about 14%."
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
            "A claimed 41% on a short dead-end stub off the north face of Bernal "
            "Heights, often called the steepest street in the US."
        ),
        disciplines=("skate",),
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
            "Upper Page Mill, twisting between Skyline and the Palo Alto foothills "
            "past Foothills Park."
        ),
        disciplines=("road",),
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
            "A treeless wall above East San Jose, and the hardest big climb in the "
            "Bay Area."
        ),
        disciplines=("road",),
        notes="No shade and no water, but a fast, open descent.",
        confidence="medium",
    ),
    Spot(
        slug="mt-hamilton-road",
        name="Mount Hamilton Road",
        city="San Francisco Bay Area",
        state="CA",
        # Previously rejected outright: at 0.188° of longitude it broke the old per-axis
        # 0.1° bbox cap, and the research deferred it rather than ship a loose box. The
        # cap is now area-based, and this is the shape that motivated the change — 21 km
        # of road in a corridor covering 0.0103°², half the budget.
        bbox=(37.32243, -121.80344, 37.37949, -121.61385),
        osm_way_names=("Mount Hamilton Road",),
        blurb=(
            "The long road to Lick Observatory — the Bay Area's biggest climb, and its "
            "longest sustained descent."
        ),
        disciplines=("road",),
        notes=(
            "Famous for being relentlessly technical rather than steep: the average "
            "gradient is gentle, but it holds a corner almost the entire way down. Some "
            "one-way sections, and the mountain is remote with no services."
        ),
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
            "The ridge road to Mt. Tamalpais's East Peak — rolling rather than steep, "
            "with the best views in Marin."
        ),
        disciplines=("road",),
        notes=(
            "Ridgecrest is the ridge road: rolling, with a low average grade. The real "
            "elevation is gained below it on Panoramic Highway. Gated in fire weather."
        ),
        confidence="high",
    ),

    Spot(
        slug="repack-road",
        name="Repack (Cascade Fire Road)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.97612, -122.64917, 37.98805, -122.61193),
        # Two OSM ways, 'Cascade Fire Road' and 'Cascade Fire Road / Repack'; the
        # shorter substring catches both.
        osm_way_names=("Cascade Fire Road",),
        blurb=(
            "The fire road where mountain biking was invented — 1,300 ft of loose "
            "Marin dirt, raced on coaster-brake klunkers from 1976."
        ),
        disciplines=("mtb", "gravel"),
        rider_profile="mtb",
        notes=(
            "Named for what the descent did to a coaster brake: riders repacked the "
            "grease after every run. On Marin Municipal Water District land, where "
            "bikes are restricted to fire roads and the posted limit is 15 mph."
        ),
        confidence="high",
    ),
    Spot(
        slug="old-railroad-grade",
        name="Old Railroad Grade (Mount Tamalpais)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.91444, -122.59616, 37.93142, -122.55344),
        osm_way_names=("Old Railroad Grade",),
        blurb=(
            "The graded bed of the 'crookedest railroad in the world', falling off "
            "Mount Tam at a steady, railway-legal gradient."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "A rail grade, so it is evenly graded and never steep — the appeal is "
            "length and the view, not pitch. Mixed dirt, gravel and one paved stretch. "
            "Pairs with Eldridge Grade Fire Road on the far side of the mountain."
        ),
        confidence="high",
    ),
    Spot(
        slug="tunitas-creek-road",
        name="Tunitas Creek Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.35675, -122.40274, 37.42180, -122.31866),
        osm_way_names=("Tunitas Creek",),
        blurb=(
            "Skyline to the coast through a redwood tunnel, on a lane that narrows to "
            "one damp track before it opens onto the Half Moon Bay farmland."
        ),
        disciplines=("road",),
        notes=(
            "Narrow with no centerline and wet under the trees most of the year. The "
            "upper half is broken pavement, and it is busy enough with climbers coming "
            "up that the blind corners matter."
        ),
        confidence="high",
    ),
    Spot(
        slug="kings-mountain-road",
        name="Kings Mountain Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.42315, -122.31610, 37.43965, -122.26401),
        osm_way_names=("Kings Mountain Road",),
        blurb=(
            "Skyline down to Woodside on wide, evenly graded switchbacks under the "
            "redwoods — the Peninsula's fastest way off the ridge."
        ),
        disciplines=("road",),
        notes=(
            "Busy by Peninsula standards: cars, deer, and grit washed into the corners "
            "after rain. The lower corners tighten where the road drops into Woodside."
        ),
        confidence="high",
    ),
    Spot(
        slug="bohlman-on-orbit",
        name="Bohlman Road / On Orbit Drive",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.21820, -122.05100, 37.25557, -122.03271),
        # The famous climb is ridden as one road but is two OSM names — On Orbit Drive
        # is the steep loop hung off Bohlman, and its ways sit inside Bohlman's bbox.
        osm_way_names=("Bohlman Road", "On Orbit Drive"),
        blurb=(
            "Above Saratoga, on pitches over 20% — a descent that is a braking problem "
            "top to bottom, on a lane and a half of patched asphalt."
        ),
        disciplines=("road",),
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # Bohlman and On Orbit are ridden as one road
        ),
        notes=(
            "Blind switchbacks, driveways straight onto the road, and no run-out at the "
            "bottom. The asphalt is patched and broken in places. Going down is harder "
            "than going up."
        ),
        confidence="high",
    ),
    Spot(
        slug="quimby-road",
        name="Quimby Road",
        city="San Francisco Bay Area",
        state="CA",
        # Clipped to the climb east of Murillo Avenue; below that Quimby is a four-lane
        # San Jose arterial running out across the valley floor.
        bbox=(37.32302, -121.79185, 37.34403, -121.71980),
        osm_way_names=("Quimby Road",),
        blurb=(
            "Off the Mount Hamilton foothills into East San Jose, with a wall of a "
            "final kilometre and the whole valley laid out in front of it."
        ),
        disciplines=("road",),
        notes=(
            "The steep upper section is narrow, blind and shoulderless, with cattle "
            "grids. It runs into signals and heavy traffic as soon as it reaches the "
            "valley floor."
        ),
        confidence="high",
    ),
    Spot(
        slug="mount-umunhum-road",
        name="Mount Umunhum Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.14441, -121.90738, 37.17719, -121.86140),
        osm_way_names=("Mount Umunhum Road",),
        blurb=(
            "Off the radar-tower summit in the Sierra Azul on new pavement, with no "
            "driveways and no cross traffic the whole way down to Hicks Road."
        ),
        disciplines=("road",),
        notes=(
            "Rebuilt and reopened to the public in 2017, which is why the surface is "
            "better than anything around it. Open-space land: gated at night, and the "
            "summit lot fills on weekends."
        ),
        confidence="high",
    ),
    Spot(
        slug="claremont-avenue-berkeley",
        name="Claremont Avenue",
        city="San Francisco Bay Area",
        state="CA",
        # Clipped to the wall above the Claremont Hotel. Lower Claremont Avenue runs
        # flat through Rockridge, and the name is common enough that the box is the
        # only thing disambiguating it.
        bbox=(37.85050, -122.25217, 37.89178, -122.20134),
        osm_way_names=("Claremont Avenue",),
        blurb=(
            "Grizzly Peak down into Berkeley past the Claremont Hotel, steepening as it "
            "falls and running straight into city traffic at the bottom."
        ),
        disciplines=("road",),
        notes=(
            "A signed truck route with real traffic and a blind steep section mid-hill. "
            "The upper pitch is around 17%, and the bottom arrives at a busy junction "
            "with no room to scrub speed."
        ),
        confidence="high",
    ),
    Spot(
        slug="panoramic-highway",
        name="Panoramic Highway (Mount Tamalpais)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.88146, -122.63891, 37.91777, -122.55153),
        osm_way_names=("Panoramic Highway",),
        blurb=(
            "The Mount Tam road down toward Mill Valley — long open bends above the "
            "fog line, with the Pacific out to one side most of the way."
        ),
        disciplines=("road",),
        notes=(
            "A two-lane state road carrying all the weekend traffic to Muir Woods and "
            "Stinson Beach, with gravel in the corners after rain. This is where the "
            "elevation is gained below Ridgecrest Boulevard."
        ),
        confidence="high",
    ),
    Spot(
        slug="eldridge-grade",
        name="Eldridge Grade (Mount Tamalpais)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.92623, -122.58704, 37.95746, -122.56748),
        osm_way_names=("Eldridge Grade Fire Road",),
        blurb=(
            "The 1880s wagon road off Mount Tam's north side, dropping in loose "
            "fire-road switchbacks toward Phoenix Lake."
        ),
        disciplines=("mtb", "gravel"),
        rider_profile="mtb",
        notes=(
            "Marin Municipal Water District land: bikes on fire roads only, a posted "
            "15 mph limit and 5 mph at blind turns. Loose over hardpack with embedded "
            "rock, and hikers throughout. Pairs with Old Railroad Grade on the south side."
        ),
        confidence="high",
    ),

    # The dirt half of the Bay Area, mined from recorded GPX tracks and then snapped
    # to OSM way names. `avoid_bigger_roads` is off on every trail spot below: a
    # singletrack crossing a fire road (`unclassified`, rank 4) reads as meeting a
    # bigger road and ends the descent. Same reason as the Downieville spot.
    Spot(
        slug="limekiln-priest-rock",
        name="Limekiln and Priest Rock (Sierra Azul)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.19024, -121.97454, 37.2052, -121.9454),
        osm_way_names=("Limekiln Trail", "Priest Rock Trail"),
        blurb=(
            "Fire road above Los Gatos that runs Limekiln straight into Priest Rock "
            "for 500 m of loose, exposed descent to Lexington Reservoir."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "Midpen land: a posted 15 mph limit, 5 mph passing or at blind turns, "
            "helmets required, e-bikes prohibited on most trails. Limekiln has had "
            "weekday maintenance closures — check before riding. Loose decomposed "
            "granite over hardpack, and no shade on the upper half."
        ),
        toggles=Toggles(
            avoid_stoplights=False, avoid_stop_signs=False,
            avoid_bigger_roads=False, avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        confidence="medium",
    ),
    Spot(
        slug="meridian-ridge-diablo",
        name="Meridian Ridge Road (Mount Diablo)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.89407, -121.92915, 37.90852, -121.91726),
        osm_way_names=("Meridian Ridge Road", "Donner Canyon Road"),
        blurb=(
            "Diablo's dirt side, dropping off the Mitchell Canyon approach in steep "
            "fire-road pitches well past 20%."
        ),
        disciplines=("mtb", "gravel"),
        rider_profile="mtb",
        notes=(
            "Mount Diablo State Park. Fire road, open to bikes and Class 1 e-bikes; "
            "Class 2 and 3 are prohibited on all trails. Rutted and loose after rain."
        ),
        toggles=Toggles(
            avoid_stoplights=False, avoid_stop_signs=False,
            avoid_bigger_roads=False, avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        confidence="medium",
    ),
    Spot(
        slug="grizzly-gulch-coe",
        name="Grizzly Gulch (Henry Coe)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.10172, -121.46698, 37.1144, -121.44326),
        osm_way_names=("Grizzly Gulch Trail",),
        blurb=(
            "Rustic Coe singletrack ridden east to west, giving up 235 m on the way "
            "back down to the Coyote Creek gate."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Henry W. Coe State Park: singletrack closes to bikes for 48 hours after "
            "a half inch or more of rain in 24 hours; roads stay open. No "
            "cross-country riding. Remote — carry water and expect no phone signal."
        ),
        toggles=Toggles(
            avoid_stoplights=False, avoid_stop_signs=False,
            avoid_bigger_roads=False, avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        confidence="medium",
    ),
    Spot(
        slug="middle-ridge-coe",
        name="Middle Ridge (Henry Coe)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.18735, -121.52515, 37.1943, -121.51109),
        osm_way_names=("Middle Ridge Trail",),
        blurb=(
            "The descent off Coe's most-ridden loop — narrow, rooty singletrack "
            "falling toward China Hole at better than 12%."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Henry W. Coe State Park: singletrack closes to bikes for 48 hours after "
            "a half inch or more of rain in 24 hours; roads stay open. No "
            "cross-country riding."
        ),
        toggles=Toggles(
            avoid_stoplights=False, avoid_stop_signs=False,
            avoid_bigger_roads=False, avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        confidence="medium",
    ),
    Spot(
        slug="south-park-drive-tilden",
        name="South Park Drive (Tilden)",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.8779, -122.24462, 37.8946, -122.22081),
        osm_way_names=("South Park Drive",),
        blurb=(
            "Tilden's drop toward Wildcat Canyon, closed to cars five months a year "
            "so the whole descent runs traffic-free."
        ),
        disciplines=("road",),
        rider_profile="cyclist_upright",
        notes=(
            "East Bay Regional Park District closes it to motor vehicles from "
            "November 1 to March 31 for newt migration, and cycling is explicitly "
            "allowed during the closure. Watch for newts on the pavement — they are "
            "slow, hard to see, and the reason the road closes."
        ),
        confidence="medium",
    ),
    Spot(
        slug="morgan-territory-road",
        name="Morgan Territory Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.77637, -121.78032, 37.79585, -121.76763),
        osm_way_names=("Morgan Territory Road",),
        blurb=(
            "A one-lane ribbon off the back of Diablo, dropping through oak shade "
            "toward the Livermore side."
        ),
        disciplines=("road",),
        rider_profile="cyclist_upright",
        notes=(
            "Effectively single-lane in places with blind turns and no shoulder. "
            "Expect oncoming cars mid-lane and gravel washed into the corners."
        ),
        confidence="medium",
    ),
    Spot(
        slug="jamison-creek-road",
        name="Jamison Creek Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(37.14499, -122.18039, 37.1528, -122.17198),
        osm_way_names=("Jamison Creek Road",),
        blurb=(
            "The steepest paved descent in the Santa Cruz Mountains set, falling off "
            "Empire Grade into Boulder Creek at nearly 13%."
        ),
        disciplines=("road",),
        rider_profile="cyclist_upright",
        notes=(
            "Steep, narrow and rough in patches — braking-intensive the whole way "
            "down, with driveways hidden in the trees."
        ),
        confidence="medium",
    ),
    Spot(
        slug="crane-canyon-road",
        name="Crane Canyon Road",
        city="San Francisco Bay Area",
        state="CA",
        bbox=(38.36344, -122.65958, 38.37506, -122.63632),
        osm_way_names=("Crane Canyon Road",),
        blurb=(
            "Sonoma Mountain's west side unwinding toward Rohnert Park — open, fast "
            "and steady rather than steep."
        ),
        disciplines=("road",),
        rider_profile="cyclist_upright",
        notes="No shoulder, and moderate local traffic on weekends.",
        confidence="medium",
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
            "About 32% out of Echo Park, and steep enough that Waze routing traffic "
            "over it became a citywide problem."
        ),
        disciplines=("skate",),
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
            "About 33%, dead-ends in a staircase, and too steep for a garbage truck — "
            "LA sends a special small one."
        ),
        disciplines=("skate",),
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
            "A 32% pitch in Echo Park where the LA Wheelmen have run a can-you-even-"
            "ride-up-it climb every year since 1974."
        ),
        disciplines=("road",),
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
            "'GMR' — 24 km of near-constant gradient above Glendora, and the benchmark "
            "descent in Southern California."
        ),
        disciplines=("road",),
        notes=(
            "Subject to fire and storm closures that have lasted years at a time. Heavy "
            "motorcycle traffic on weekends."
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
            "Sixteen kilometres of switchbacks between Pacific Coast Highway and the "
            "Malibu ridge."
        ),
        disciplines=("road",),
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
            "Roughly 70 turns in four miles down to the Pacific, most of it signed "
            "one-way downhill."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Signed one-way downhill, which is the whole appeal — but that isn't in the "
            "map data, so a route here may be drawn running back up it. Narrow, blind "
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
            "Malibu Canyon up to the Santa Monica ridge, on steady, evenly-graded "
            "switchbacks."
        ),
        disciplines=("road",),
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
            "Mulholland Highway to Saddle Peak, one of the definitive Santa Monica "
            "Mountains roads."
        ),
        disciplines=("road",),
        notes="Good surface, technical descent.",
        confidence="medium",
    ),
    Spot(
        slug="mount-wilson-toll-road",
        name="Mount Wilson Toll Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.18679, -118.10612, 34.22784, -118.05672),
        osm_way_names=("Mount Wilson Toll Road",),
        blurb=(
            "The 1891 carriage road to the Mount Wilson Observatory — LA's original "
            "mountain road, and now its best gravel descent."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "Part paved, part dirt. Gated to cars, so the descent is car-free, but it "
            "is shared with hikers the whole way. Closed after fires, which in the "
            "Angeles means often."
        ),
        confidence="medium",
    ),
    Spot(
        slug="angeles-crest-highway",
        name="Angeles Crest Highway (lower)",
        city="Los Angeles",
        state="CA",
        # Clipped to the bottom 30 km, Clear Creek down to La Cañada. The full highway
        # runs 100 km to Wrightwood and covers 0.11°², five times the bbox budget.
        bbox=(34.20260, -118.20246, 34.27349, -118.04786),
        osm_way_names=("Angeles Crest Highway",),
        max_road_rank=7,   # SR-2 is highway=primary its whole length
        blurb=(
            "The long fall off the San Gabriels into La Cañada, on wide sweeping bends "
            "with nothing between the ridge and the city to slow you down."
        ),
        disciplines=("road",),
        notes=(
            "A state highway with fast traffic, heavy weekend motorcycle use and a "
            "divided section low down. Rockfall, and closures after storms and fires "
            "that have run for years at a time."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mount-baldy-road",
        name="Mount Baldy Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.14835, -117.69543, 34.27676, -117.60685),
        osm_way_names=("Mount Baldy Road",),
        blurb=(
            "Manker Flats down past Mt. Baldy Village to Claremont, tightening through "
            "the canyon narrows below the village before the run-out."
        ),
        disciplines=("road",),
        notes=(
            "Snow, ice and chain controls above the village in winter. Narrow through "
            "the canyon with rockfall and no shoulder. The top of the box reaches the "
            "gravel spur above Manker Flats, which is not the paved road."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mulholland-the-snake",
        name="Mulholland Highway (The Snake)",
        city="Los Angeles",
        state="CA",
        bbox=(34.09543, -118.80729, 34.10796, -118.78927),
        # OSM names this section distinctly from the rest of Mulholland Highway, which
        # is what makes the famous three kilometres separable at all.
        osm_way_names=("Mulholland Highway (The Snake)",),
        blurb=(
            "The corkscrew above Rock Store in the Santa Monica Mountains — three "
            "kilometres of continuous, banked switchbacks and no straight."
        ),
        disciplines=("road",),
        notes=(
            "Heavy weekend motorcycle traffic, riders using the whole road, and a well "
            "known crash record; sheriffs patrol it. Photographers stand in the corners."
        ),
        confidence="high",
    ),
    Spot(
        slug="decker-canyon-road",
        name="Decker Canyon Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.03967, -118.90154, 34.09037, -118.87121),
        # Signed as Decker Canyon Road; the OSM `name` tag is just "Decker Road".
        osm_way_names=("Decker Road",),
        blurb=(
            "Off Mulholland down to the Pacific at Zuma — walled hairpins at the top "
            "that unwind into a fast, open run at the coast."
        ),
        disciplines=("road",),
        notes=(
            "Narrow with blind corners and no guardrail on the upper hairpins. Nearby "
            "Decker School Road and Decker-Edison Road are separate roads; the name "
            "filter is 'Decker Road' precisely so they stay out."
        ),
        confidence="medium",
    ),
    Spot(
        slug="yerba-buena-road",
        name="Yerba Buena Road",
        city="Los Angeles",
        state="CA",
        bbox=(34.05132, -118.96744, 34.11624, -118.89012),
        osm_way_names=("Yerba Buena Road",),
        blurb=(
            "Mulholland down to Pacific Coast Highway through the Circle X ridges, on "
            "the emptiest road in the Santa Monicas."
        ),
        disciplines=("road",),
        notes=(
            "Rough, patched pavement in places, with gravel washed across the road "
            "after rain. Remote — no water, no services, and phone coverage is poor."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mount-lowe-motorway",
        name="Mount Lowe Motorway",
        city="Los Angeles",
        state="CA",
        bbox=(34.21261, -118.14975, 34.24284, -118.09104),
        osm_way_names=("Mount Lowe Motorway",),
        blurb=(
            "A wide dirt truck trail off the Mount Lowe ridge into Altadena, above the "
            "ruins of the mountain railway that used to run the same hill."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "Gated to cars, so the descent is car-free, but shared with hikers all the "
            "way. Loose decomposed granite with washouts, and closed after fires — "
            "which in the Angeles means often. Pairs with the Mount Wilson Toll Road."
        ),
        confidence="medium",
    ),
    Spot(
        slug="big-tujunga-canyon-road",
        name="Big Tujunga Canyon Road",
        city="Los Angeles",
        state="CA",
        # Clipped short of Upper Big Tujunga Canyon Road, a different road whose name
        # contains this one as a substring.
        bbox=(34.27035, -118.31795, 34.30683, -118.15906),
        osm_way_names=("Big Tujunga Canyon Road",),
        blurb=(
            "The canyon road down to Sunland, following the creek out of the gorge on "
            "long open curves with the reservoir below."
        ),
        disciplines=("road",),
        notes=(
            "Sand and rockfall on the road after storms, and closures that have lasted "
            "seasons. Weekend motorcycle traffic, and long unlit stretches."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mount-hollywood-drive",
        name="Mount Hollywood Drive (Griffith Park)",
        city="Los Angeles",
        state="CA",
        bbox=(34.12182, -118.31115, 34.15130, -118.29860),
        osm_way_names=("Mount Hollywood Drive",),
        blurb=(
            "The car-free road through the middle of Griffith Park, curling down from "
            "under the Hollywood Sign toward the Observatory."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Closed to motor traffic, so the descent has no cars — but it is shared with "
            "walkers and runners all day, and it is gentle rather than steep."
        ),
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
            "An 18% arterial named for the underground counterweights that hauled "
            "streetcars up it until 1940."
        ),
        disciplines=("skate",),
        rider_profile="longboarder",
        notes="A busy arterial with real traffic and signals at Mercer and Roy.",
        confidence="high",
    ),
    Spot(
        slug="golden-gardens-drive",
        name="Golden Gardens Drive Northwest",
        city="Seattle",
        state="WA",
        bbox=(47.68728, -122.40424, 47.69589, -122.39654),
        osm_way_names=("Golden Gardens Drive Northwest",),
        blurb=(
            "Sunset Hill down to the beach at Golden Gardens, two long curves through a "
            "wooded ravine to the edge of Puget Sound."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Narrow, no shoulder, and full of beach traffic on summer evenings. The "
            "bottom ends in a parking lot rather than a run-out."
        ),
        confidence="high",
    ),
    Spot(
        slug="james-street-seattle",
        name="James Street (Profanity Hill)",
        city="Seattle",
        state="WA",
        bbox=(47.59993, -122.33580, 47.60903, -122.31857),
        osm_way_names=("James Street",),
        blurb=(
            "First Hill straight down to Pioneer Square on the grade 1890s litigants "
            "named Profanity Hill — the steepest way off the ridge."
        ),
        disciplines=("road", "skate"),
        notes=(
            "A downtown arterial: signals at every block, buses, and old concrete panels "
            "on the lower blocks. East James Street continues east from the top and "
            "shares the name, so a route may run onto it."
        ),
        confidence="medium",
    ),
    Spot(
        slug="yesler-way",
        name="Yesler Way (Skid Road)",
        city="Seattle",
        state="WA",
        bbox=(47.59990, -122.33835, 47.60354, -122.31856),
        osm_way_names=("Yesler Way",),
        blurb=(
            "The original skid road — First Hill to the waterfront on the grade logs "
            "were run down to Yesler's mill."
        ),
        disciplines=("road", "skate"),
        notes=(
            "A downtown arterial with signals, a protected bike lane on part of it, and "
            "streetcar-era brick and concrete panels underfoot. East Yesler Way "
            "continues east from the top and shares the name."
        ),
        confidence="medium",
    ),
    Spot(
        slug="interlaken-boulevard",
        name="Interlaken Boulevard",
        city="Seattle",
        state="WA",
        bbox=(47.62907, -122.31925, 47.64384, -122.29503),
        # One descent, three OSM names — the Olmsted boulevard, the drive that climbs
        # to it, and the cobbled place that links them.
        osm_way_names=(
            "East Interlaken Boulevard",
            "Interlaken Drive East",
            "Interlaken Place East",
        ),
        blurb=(
            "Seattle's oldest park drive: a mossy, shaded descent off Capitol Hill "
            "through Interlaken Park, half of it closed to cars."
        ),
        disciplines=("road",),
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # three names make up the one boulevard
        ),
        notes=(
            "The middle section is closed to motor traffic. Damp, leaf-covered and "
            "shaded almost year-round, with cobbles on Interlaken Place. It contours "
            "as much as it drops, so it is gentle."
        ),
        confidence="medium",
    ),
    Spot(
        slug="toe-jam-hill-road",
        name="Toe Jam Hill Road",
        city="Seattle",
        state="WA",
        bbox=(47.57854, -122.50974, 47.59416, -122.50422),
        osm_way_names=("Toe Jam Hill Road",),
        blurb=(
            "The wall on Bainbridge Island's Chilly Hilly loop, dropping off the bluff "
            "to the Rich Passage shoreline."
        ),
        disciplines=("road",),
        notes=(
            "Ferry access from downtown Seattle. A narrow rural lane with no shoulder, "
            "gravel at the edges and blind driveways. Short: the steep part is a few "
            "hundred metres."
        ),
        confidence="medium",
    ),
    Spot(
        slug="sw-admiral-way",
        name="Southwest Admiral Way",
        city="Seattle",
        state="WA",
        bbox=(47.56969, -122.42036, 47.58305, -122.36876),
        osm_way_names=("Southwest Admiral Way",),
        max_road_rank=7,   # highway=primary over most of its length
        blurb=(
            "West Seattle's front door — a steady arterial drop off the Admiral ridge "
            "toward the Duwamish, with the downtown skyline ahead of you."
        ),
        disciplines=("road",),
        notes=(
            "A busy multi-lane arterial with signals and bus traffic, and the shoulder "
            "runs out near the bottom. Steady rather than steep."
        ),
        confidence="medium",
    ),
    Spot(
        slug="burma-road-vashon",
        name="Burma Road (Vashon Island)",
        city="Seattle",
        state="WA",
        bbox=(47.48021, -122.48152, 47.49739, -122.46588),
        osm_way_names=("Burma Road Southwest",),
        blurb=(
            "Vashon Island's steepest pitch, falling off the central plateau on a "
            "narrow, gravel-edged lane with nothing on it."
        ),
        disciplines=("road", "gravel"),
        notes=(
            "Ferry-only access. Chip seal with loose gravel at the margins. The steep "
            "section is short and the rest rolls, so the numbers will read gentler than "
            "the road feels."
        ),
        confidence="low",
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
            "Switchbacks above Golden, past Buffalo Bill's grave — the most-ridden "
            "road in Colorado."
        ),
        disciplines=("road",),
        notes=(
            "Signed for bikes, with wide shoulders. The descent into Golden is fast, "
            "open and well-sighted."
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
            "Boulder's home climb, rising straight out of Chautauqua Park at the "
            "western edge of town."
        ),
        disciplines=("road",),
        notes="Steep, tight switchbacks low down make for a technical descent.",
        confidence="high",
    ),
    Spot(
        slug="switzerland-trail",
        name="Switzerland Trail",
        city="Denver / Boulder",
        state="CO",
        bbox=(40.00176, -105.52951, 40.07482, -105.42289),
        osm_way_names=("Switzerland Trail",),
        blurb=(
            "An abandoned narrow-gauge rail grade above Boulder, now the definitive "
            "Front Range gravel descent."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "A rail grade, so it is steady rather than steep. Rough and washboarded "
            "after storms."
        ),
        confidence="medium",
    ),
    Spot(
        slug="lickskillet-road",
        name="Lickskillet Road (Gold Hill)",
        city="Denver / Boulder",
        state="CO",
        bbox=(40.06140, -105.41656, 40.07731, -105.40618),
        osm_way_names=("Lickskillet Road",),
        blurb=(
            "Widely called the steepest gravel road in the United States — a sustained "
            "18% of loose dirt out of Left Hand Canyon up to Gold Hill."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Short: about 1 km, all of it steep. Loose over hardpack, so the descent is "
            "a braking problem rather than a fast one, and the county closes it in "
            "winter."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mount-blue-sky-road",
        name="Mount Blue Sky Road (Mount Evans)",
        city="Denver / Boulder",
        state="CO",
        # Echo Lake to the summit. The 17-node way at the top is the one-way summit
        # parking loop; the 23 km road itself is two-way, so the descent is legal.
        bbox=(39.57748, -105.64647, 39.65856, -105.58221),
        osm_way_names=("Mount Blue Sky Road",),
        blurb=(
            "The highest paved road in North America, unwinding off a 14,130 ft "
            "summit past Summit Lake and down to Echo Lake."
        ),
        disciplines=("road",),
        notes=(
            "Renamed from Mount Evans Road in 2023. Gated above Echo Lake from roughly "
            "October to Memorial Day, and the open season runs on timed-entry "
            "reservations. No guardrail above treeline, and "
            "afternoon thunderstorms arrive fast at 14,000 ft."
        ),
        confidence="medium",
    ),
    Spot(
        slug="lefthand-canyon-drive",
        name="Lefthand Canyon Drive",
        city="Denver / Boulder",
        state="CO",
        bbox=(40.05375, -105.50317, 40.1355, -105.27999),
        osm_way_names=("Lefthand Canyon Drive",),
        blurb=(
            "The long way down off the Peak to Peak into Boulder County, following "
            "the creek out of Ward with the canyon opening as you go."
        ),
        disciplines=("road",),
        notes=(
            "The only access to Ward, Jamestown and Gold Hill, so expect real traffic; "
            "the lower narrows have no shoulder, and the canyon collects sand and "
            "rockfall after storms."
        ),
        confidence="medium",
    ),
    Spot(
        slug="sunshine-canyon-drive",
        name="Sunshine Canyon Drive",
        city="Denver / Boulder",
        state="CO",
        bbox=(40.01853, -105.40835, 40.07419, -105.29047),
        osm_way_names=("Sunshine Canyon Drive",),
        blurb=(
            "Gold Hill back down to Mapleton Hill: dirt at the top, pavement at the "
            "bottom, finishing on a residential street in Boulder."
        ),
        disciplines=("road", "gravel"),
        notes=(
            "The upper canyon above Poorman Road is graded dirt and washboards badly. "
            "The paved lower half is steep and narrow with blind corners, and it is a "
            "residential street at the bottom."
        ),
        confidence="medium",
    ),
    Spot(
        slug="magnolia-road",
        name="Magnolia Road",
        city="Denver / Boulder",
        state="CO",
        # Clipped to the paved wall between Boulder Canyon and the top of the climb.
        # Above that, Magnolia flattens out and turns to gravel across the plateau,
        # which is not the section anybody means.
        bbox=(39.98201, -105.40162, 40.00737, -105.34657),
        osm_way_names=("Magnolia Drive",),
        blurb=(
            "The wall straight out of Boulder Canyon — switchbacks with no guardrail "
            "and long pitches where you are on the brakes the whole way."
        ),
        disciplines=("road",),
        notes=(
            "Steep and sustained enough to cook rim brakes, with a sheer drop off the "
            "outside of several corners and no runoff."
        ),
        confidence="medium",
    ),
    Spot(
        slug="deer-creek-canyon",
        name="Deer Creek Canyon",
        city="Denver / Boulder",
        state="CO",
        bbox=(39.53459, -105.21949, 39.57456, -105.08482),
        osm_way_names=("South Deer Creek Canyon Road", "West Deer Creek Canyon Road"),
        blurb=(
            "The standard Denver hill day, running back east out of the pines and "
            "down the canyon to the plains at Chatfield."
        ),
        disciplines=("road",),
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # South Deer Creek Canyon Rd → West Deer Creek Canyon Rd
        ),
        notes=(
            "The road changes name at the Phillips 66 junction. "
            "Popular enough that uphill riders are constant, and the lower canyon "
            "carries commuter traffic to the Ken Caryl subdivisions."
        ),
        confidence="medium",
    ),
    Spot(
        slug="chimney-gulch",
        name="Chimney Gulch Trail",
        city="Denver / Boulder",
        state="CO",
        bbox=(39.73359, -105.24779, 39.7544, -105.23002),
        osm_way_names=("Chimney Gulch Trail",),
        blurb=(
            "The dirt line off Lookout Mountain that Lariat Loop riders never see — "
            "rocky switchbacks finishing at the edge of downtown Golden."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Two-way and busy with hikers, and it crosses Lookout Mountain Road "
            "several times on the way down. Loose decomposed granite over rock steps; "
            "it bakes in summer with no shade."
        ),
        confidence="medium",
    ),

    # ── Sierra Nevada ─────────────────────────────────────────────────────────
    Spot(
        slug="downieville-downhill",
        name="The Downieville Downhill",
        city="Sierra Nevada",
        state="CA",
        # Union of the five named trails in the chain, west to east.
        bbox=(39.56828, -120.82324, 39.62717, -120.66458),
        # The one spot in the collection that is genuinely five roads. Listed in
        # descending order, and paired with stay_on_initial_road=False below —
        # constraining to the seed trail's name would cut the run at Butcher Ranch
        # and ship four fragments of the thing people come here for.
        osm_way_names=(
            "Sunrise Trail",
            "Butcher Ranch Trail",
            "Pauley Creek Trail",
            "Third Divide Trail",
            "First Divide Trail",
        ),
        blurb=(
            "The descent American mountain biking measures itself against — 4,000 ft "
            "down from Packer Saddle into Downieville."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        # The one spot that turns avoid_bigger_roads OFF, and the only one that needs
        # to. The five trails are contiguous in OSM but linked by Lavezzola Road and
        # Gold Valley Road — forest roads tagged `unclassified` (rank 4) against the
        # trails' `path` (rank 0). The bigger-road stop therefore fires at every
        # crossing, and the descent came back cut at Third Divide: 1076 m of a run
        # that is 3006 m with the toggle off. A dirt forest road is not a "bigger
        # road" in the sense the toggle means — that hierarchy tracks traffic danger
        # on pavement, and off it a road crossing is just where the trail continues.
        #
        # Left on for every other dirt spot, where it changes nothing (checked): only
        # a chain that crosses roads mid-descent is affected.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=False,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Five trails end-to-end, not one: Sunrise into Butcher Ranch, then Pauley "
            "Creek, Third Divide and First Divide. Shuttle-served, and the upper half "
            "holds snow into June. The full 15-mile run climbs between drops, so it "
            "shows up here as several descents rather than one. The rocky top section "
            "is rougher than its easy rating suggests."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mills-peak-trail",
        name="Mills Peak Trail",
        city="Sierra Nevada",
        state="CA",
        bbox=(39.68044, -120.63635, 39.74395, -120.60975),
        osm_way_names=("Mills Peak Trail",),
        blurb=(
            "Purpose-built flow from the Mills Peak lookout down to Graeagle, "
            "switchbacking the whole way through Lost Sierra forest."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        # Same case as Downieville: the trail crosses the Mills Peak forest road
        # (`unclassified`, rank 4) several times on the way down, and against the
        # trail's rank 0 each crossing reads as meeting a bigger road and ends the
        # descent. A gravel forest road is not a "bigger road" in the sense the
        # toggle means.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=False,
            avoid_equal_roads=False,
            stay_on_initial_road=True,
        ),
        notes=(
            "Machine-built and shuttle-served from the lookout road above Graeagle. "
            "The upper half holds snow into June, and the descent crosses the forest "
            "road repeatedly — watch for trucks at the crossings."
        ),
        confidence="medium",
    ),
    Spot(
        slug="big-boulder-trail",
        name="Big Boulder Trail",
        city="Sierra Nevada",
        state="CA",
        bbox=(39.61018, -120.75683, 39.6396, -120.73023),
        osm_way_names=("Big Boulder Trail",),
        blurb=(
            "The steep way off the Sierra Buttes country — loose, rocky singletrack "
            "falling toward Lavezzola Creek."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Ridden as the alternative to the Downieville Downhill off the same "
            "shuttle, and rockier for its length than anything on that run. Snowbound "
            "at the top into June."
        ),
        confidence="medium",
    ),
    Spot(
        slug="halls-ranch-trail",
        name="Halls Ranch Trail",
        city="Sierra Nevada",
        state="CA",
        bbox=(39.5339, -120.96397, 39.54707, -120.91283),
        osm_way_names=("Halls Ranch Trail",),
        blurb=(
            "Exposed bench trail off the ridge above Goodyears Bar, dropping through "
            "oak and manzanita to the North Yuba."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "The low-elevation Downieville-area ride, so it comes into condition in "
            "spring when the Buttes are still under snow — and it bakes in summer. "
            "Narrow, off-camber and exposed above the river in places."
        ),
        confidence="medium",
    ),
    Spot(
        slug="gold-lake-highway",
        name="Gold Lake Highway (Lakes Basin)",
        city="Sierra Nevada",
        state="CA",
        # Union of both halves. The road changes OSM name at the county line:
        # "Gold Lake Highway" from Bassetts up to the basin, "Gold Lake Road" from
        # there down to Graeagle. Hence both names and stay_on_initial_road=False.
        bbox=(39.61221, -120.66601, 39.75619, -120.58919),
        osm_way_names=("Gold Lake Highway", "Gold Lake Road"),
        blurb=(
            "Off the summit of the Lakes Basin and down the open glacial valley into "
            "Graeagle, granite and lakes the whole way."
        ),
        disciplines=("road",),
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Closed by snow from roughly November to May. Narrow, no shoulder, and "
            "busy with trailer traffic to the Lakes Basin campgrounds in July and "
            "August. A short 'Old Gold Lake Road' spur shares the name and may show "
            "up as a stray short route."
        ),
        confidence="medium",
    ),

    # ── Lake Tahoe ────────────────────────────────────────────────────────────
    Spot(
        slug="mr-toads-saxon-creek",
        name="Mr. Toad's Wild Ride (Saxon Creek Trail)",
        city="Lake Tahoe",
        state="CA",
        bbox=(38.81292, -119.99667, 38.86315, -119.95878),
        osm_way_names=("Saxon Creek Trail",),
        blurb=(
            "Tahoe's benchmark descent — steep, rocky and relentless, from the Tahoe "
            "Rim Trail down to Oneidas Street."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Loose granite, big steps, and no easy line. Shares its top end with the "
            "Tahoe Rim Trail, which is closed to bikes on even days."
        ),
        confidence="high",
    ),
    Spot(
        slug="mount-rose-highway",
        name="Mount Rose Highway",
        city="Lake Tahoe",
        state="NV",
        # bbox CLIPPED to the Reno side of the summit. The full OSM "Mount Rose
        # Highway" runs 41 km from Incline Village over the pass and out into the
        # Reno suburbs, where it becomes a divided road (28 of 61 ways oneway) and
        # the union box is 0.036 deg^2. This is the descent people mean: summit to
        # the edge of town, 26 km and 1132 m, no oneway ways in it.
        bbox=(39.2888, -119.92812, 39.39373, -119.78848),
        osm_way_names=("Mount Rose Highway",),
        blurb=(
            "From the 8,900 ft Mount Rose summit the road falls away toward Reno in "
            "long open sweepers, the Truckee Meadows spread out below."
        ),
        disciplines=("road",),
        max_road_rank=7,                         # primary
        notes=(
            "NV 431, the highest year-round pass in the Sierra. Plowed all winter but "
            "regularly icy and chained above 7,000 ft, and it is a commuter route "
            "between Reno and the lake, so expect steady traffic at speed."
        ),
        confidence="medium",
    ),
    Spot(
        slug="kingsbury-grade",
        name="Kingsbury Grade (Daggett Pass)",
        city="Lake Tahoe",
        state="NV",
        bbox=(38.92935, -119.93859, 38.98365, -119.84225),
        osm_way_names=("Kingsbury Grade",),
        blurb=(
            "NV 207 off the Tahoe rim at Daggett Pass, then down the east face in "
            "switchbacks to the floor of the Carson Valley."
        ),
        disciplines=("road",),
        max_road_rank=7,                         # primary
        notes=(
            "Two descents share the pass: the short one west into Stateline and the "
            "long, steep one east to Genoa. The east side is narrow, has no shoulder "
            "through the switchbacks, and carries truck traffic."
        ),
        confidence="medium",
    ),
    Spot(
        slug="donner-pass-road",
        name="Donner Pass Road",
        city="Lake Tahoe",
        state="CA",
        # bbox CLIPPED to the summit-to-lake section. The OSM way runs on through
        # Truckee, where it is one-way downtown and dead flat; the descent is the
        # 9 km from Donner Summit down past Rainbow Bridge to the lake.
        bbox=(39.312, -120.34209, 39.3299, -120.25811),
        osm_way_names=("Donner Pass Road",),
        blurb=(
            "Old US 40 off Donner Summit, curling under the granite of Donner Peak "
            "and past Rainbow Bridge down to the lake."
        ),
        disciplines=("road",),
        notes=(
            "The 1926 alignment of the Lincoln Highway, kept as a scenic alternative "
            "to I-80 alongside it. Gated by snow from about November to May, and the "
            "shoulderless section under the cliffs is busy with climbers' cars."
        ),
        confidence="medium",
    ),
    Spot(
        slug="tunnel-creek-road",
        name="Tunnel Creek Road",
        city="Lake Tahoe",
        state="NV",
        bbox=(39.21668, -119.93362, 39.23676, -119.90211),
        osm_way_names=("Tunnel Creek Road",),
        blurb=(
            "The dirt road out of the Marlette flume country, dropping the east "
            "shore rim straight down into Incline Village."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "The standard way down off Marlette Lake and the Flume Trail, and the "
            "reason both are rideable as a point-to-point. Loose decomposed granite "
            "over hardpack, steep enough that it is a braking problem, and the lower "
            "end turns to pavement in the neighbourhood."
        ),
        confidence="medium",
    ),
    Spot(
        slug="tyrolean-downhill",
        name="Tyrolean Downhill",
        city="Lake Tahoe",
        state="NV",
        bbox=(39.25515, -119.9279, 39.2871, -119.91374),
        osm_way_names=("Tyrolean Downhill",),
        blurb=(
            "Black-diamond singletrack from Tahoe Meadows down through rock gardens "
            "and switchbacks to the Diamond Peak parking lot."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Shuttled or reached off the Mount Rose Highway; the bottom drops you at "
            "the ski area. Rebuilt and rerouted by TAMBA in recent years, so the "
            "mapped line may lag the trail on the ground. Snowbound until roughly June."
        ),
        confidence="medium",
    ),
    Spot(
        slug="corral-trail",
        name="Corral Trail",
        city="Lake Tahoe",
        state="CA",
        bbox=(38.86447, -119.97983, 38.8831, -119.9542),
        osm_way_names=("Corral Trail",),
        blurb=(
            "The everyday South Lake Tahoe descent: bermed, rolling singletrack "
            "through jeffrey pine down to the Corral trailhead."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Directional and downhill-only, and the finish for most Toads and Powerline "
            "shuttles. Sandy and heavily ridden — dusty by August. Snow-free earlier "
            "than the high Tahoe trails."
        ),
        confidence="medium",
    ),

    # ── Crested Butte ─────────────────────────────────────────────────────────
    Spot(
        slug="trail-401",
        name="Trail 401",
        city="Crested Butte",
        state="CO",
        bbox=(38.96220, -107.04912, 39.02057, -106.98637),
        osm_way_names=("Trail 401", "Trailriders 401"),
        blurb=(
            "Above the treeline from Schofield Pass down through the wildflowers into "
            "Crested Butte — the most photographed singletrack in Colorado."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # 'Trail 401' → 'Trailriders 401 Trail'
        ),
        notes=(
            "Starts above 11,000 ft, so it is a summer trail and holds snow into July. "
            "Narrow, off-camber bench cut with a steep hillside below it."
        ),
        confidence="medium",
    ),
    Spot(
        slug="trail-403",
        name="Trail 403 (Washington Gulch)",
        city="Crested Butte",
        state="CO",
        bbox=(38.96666, -107.04842, 38.98461, -107.00464),
        osm_way_names=("Washington Gulch Trail",),
        blurb=(
            "The 401's quieter neighbour — off the ridge above Gothic through the "
            "flowers, then bench-cut switchbacks into Washington Gulch."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "This is the singletrack, not Washington Gulch Road in the same valley. "
            "Starts above 11,000 ft and holds snow into July. Narrow "
            "off-camber bench with a steep hillside below it, ridden both directions."
        ),
        confidence="medium",
    ),
    Spot(
        slug="teocalli-ridge",
        name="Teocalli Ridge",
        city="Crested Butte",
        state="CO",
        bbox=(38.89849, -106.88004, 38.94774, -106.86181),
        osm_way_names=("Teocalli Ridge Trail 557",),
        blurb=(
            "Loose, steep switchbacks off the ridge above Brush Creek — the descent "
            "riders spend two hours climbing to get to."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Fall-line and eroded in the upper third, with several exposed corners. "
            "Summer only. The trail crosses cattle range, so expect gates and stock "
            "on it."
        ),
        confidence="medium",
    ),
    Spot(
        slug="slate-river-road",
        name="Slate River Road (Paradise Divide)",
        city="Crested Butte",
        state="CO",
        bbox=(38.87812, -107.0674, 38.99079, -106.97394),
        osm_way_names=("Slate River Road",),
        blurb=(
            "Off Paradise Divide down the Slate River valley on dirt, past the "
            "Pittsburg townsite and out onto pavement at Crested Butte."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "The upper half is rough shelf road above the river and is 4x4 country "
            "in summer; it is closed by snow into June. Washboard and loose rock "
            "through the shaded sections."
        ),
        confidence="medium",
    ),
    Spot(
        slug="pearl-pass",
        name="Pearl Pass",
        city="Crested Butte",
        state="CO",
        bbox=(38.95993, -106.84816, 39.03109, -106.80551),
        osm_way_names=("Pearl Pass Road",),
        blurb=(
            "The 12,700 ft rock crawl the first Klunker Tour crossed in 1976, "
            "dropping off the divide toward Ashcroft on old mining road."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="mtb",
        notes=(
            "Not really a road near the top: loose talus and creek crossings, "
            "unrideable in places, and snow-free only from about mid-July. No "
            "services and no phone signal on either side of the pass."
        ),
        confidence="medium",
    ),

    # ── Moab / Southeast Utah ─────────────────────────────────────────────────
    Spot(
        slug="porcupine-rim",
        name="Porcupine Rim",
        city="Moab / Southeast Utah",
        state="UT",
        # Covers both halves: the 4x4 doubletrack and the singletrack it feeds into.
        bbox=(38.57993, -109.53464, 38.62908, -109.37436),
        osm_way_names=("Porcupine Rim",),
        blurb=(
            "The last and best third of the Whole Enchilada — rim-edge doubletrack "
            "into singletrack, 900 m above the Colorado River."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # 4x4 Trail → Single Track is a name change
        ),
        notes=(
            "Two trails ridden as one: the 4x4 track into the singletrack. Exposed "
            "ledge riding with a long fall on the left, and no shade or water anywhere "
            "on it."
        ),
        confidence="high",
    ),
    Spot(
        slug="shafer-trail",
        name="Shafer Trail",
        city="Moab / Southeast Utah",
        state="UT",
        bbox=(38.44520, -109.82308, 38.49975, -109.67095),
        osm_way_names=("Shafer Trail",),
        blurb=(
            "Switchbacks cut into the cliff below Island in the Sky, dropping 450 m "
            "off the mesa onto the White Rim."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "Dirt, shared with 4x4 traffic, and impassable when wet. Part of it is "
            "surfaced asphalt near the top."
        ),
        confidence="high",
    ),
    Spot(
        slug="moki-dugway",
        name="Moki Dugway",
        city="Moab / Southeast Utah",
        state="UT",
        bbox=(37.26941, -109.94626, 37.27945, -109.93393),
        osm_way_names=("Moki Dugway",),
        blurb=(
            "Three miles of unpaved switchbacks blasted into the Cedar Mesa cliff for "
            "uranium trucks, with no guardrail and an 1,100 ft drop."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Graded dirt, a steady 10%, and signed for 5 mph. Only the switchbacks are "
            "the dugway proper — the highway either side is ordinary pavement."
        ),
        confidence="medium",
    ),
    Spot(
        slug="la-sal-loop-castle-valley",
        name="La Sal Loop Road (Castle Valley)",
        city="Moab / Southeast Utah",
        state="UT",
        # The north half only. The full loop is 39 km and its union bbox is roughly
        # twice the area budget; this is the famous side, the drop into Castle Valley.
        bbox=(38.59119, -109.42491, 38.68544, -109.28824),
        osm_way_names=("La Sal Loop Road",),
        blurb=(
            "Paved switchbacks off the flank of the La Sals, unwinding into Castle "
            "Valley with Castleton Tower standing in front of you."
        ),
        disciplines=("road",),
        notes=(
            "Chip-sealed two-lane with no shoulder and cattle guards. Closed by snow "
            "at the top in winter. Nothing between Castle Valley and the mountain, so "
            "carry water."
        ),
        confidence="medium",
    ),
    Spot(
        slug="long-canyon-road",
        name="Long Canyon Road (Pucker Pass)",
        city="Moab / Southeast Utah",
        state="UT",
        bbox=(38.53787, -109.7661, 38.55045, -109.64576),
        osm_way_names=("Long Canyon Road",),
        blurb=(
            "Off the mesa above Moab through a slot blasted into the cliff, under a "
            "wedged boulder, and out onto Potash Road by the river."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "Dirt and ledge rock shared with 4x4 traffic, one lane in the slot with "
            "nowhere to pass. Impassable when wet. Not to be confused with Long Canyon "
            "Well Road nearby."
        ),
        confidence="medium",
    ),
    Spot(
        slug="captain-ahab",
        name="Captain Ahab",
        city="Moab / Southeast Utah",
        state="UT",
        bbox=(38.50728, -109.62332, 38.52719, -109.60066),
        osm_way_names=("Upper Captain Ahab Trail", "Lower Captain Ahab Trail"),
        blurb=(
            "Amasa Back's purpose-built descent — ledge drops and slickrock benches "
            "cut into the rim above the Colorado."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # Upper Captain Ahab Trail → Lower Captain Ahab Trail
        ),
        notes=(
            "The lower half is one-way downhill. "
            "Mandatory ledge moves with exposure on the outside, and no shade or "
            "water anywhere on it."
        ),
        confidence="medium",
    ),
    Spot(
        slug="geyser-pass-road",
        name="Geyser Pass Road",
        city="Moab / Southeast Utah",
        state="UT",
        bbox=(38.45032, -109.31845, 38.49187, -109.19782),
        osm_way_names=("Geyser Pass Road",),
        blurb=(
            "The Whole Enchilada shuttle road ridden for its own sake — graded dirt "
            "off the La Sal crest, out of the aspens toward the desert."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Graded but washboarded, with shuttle vans on it all summer. Above "
            "10,000 ft at the top and closed by snow from roughly November to June."
        ),
        confidence="medium",
    ),
    Spot(
        slug="sand-flats-road",
        name="Sand Flats Road",
        city="Moab / Southeast Utah",
        state="UT",
        bbox=(38.52072, -109.53678, 38.58727, -109.33627),
        osm_way_names=("Sand Flats Road",),
        blurb=(
            "The long drop off the La Sal shoulder past Slickrock and Hells Revenge "
            "— dirt at the top, pavement by the time you hit Moab."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Half of it is the Sand Flats Recreation Area access road, so there is a "
            "fee station and constant 4x4 and shuttle traffic. Loose sand over "
            "slickrock in the middle section; the short one-way section is a divided "
            "stretch, not a restriction on the descent."
        ),
        confidence="medium",
    ),

    # ── Portland ──────────────────────────────────────────────────────────────
    Spot(
        slug="rocky-butte",
        name="Northeast Rocky Butte Road",
        city="Portland",
        state="OR",
        bbox=(45.54058, -122.56900, 45.55212, -122.56301),
        # Portland OSM spells directions out in full — "Northeast", never "NE".
        osm_way_names=("Northeast Rocky Butte Road",),
        blurb=(
            "A spiral road up an extinct cinder cone to a WPA-era stone lookout, and "
            "the only real hill inside Portland."
        ),
        disciplines=("road", "skate"),
        notes=(
            "A hand-cut stone tunnel partway up, so turning on 'avoid tunnels' cuts "
            "this route in two rather than shortening it. Signed for bikes, and gentle "
            "overall."
        ),
        confidence="high",
    ),

    Spot(
        slug="council-crest",
        name="Council Crest",
        city="Portland",
        state="OR",
        bbox=(45.48625, -122.71423, 45.50628, -122.69253),
        # NOT "Southwest Council Crest Drive", which is the near-flat summit loop —
        # 36 m of relief over 2.2 km. The climb people actually ride comes up Greenway
        # and Talbot, with Fairmount contouring the hill below the top.
        osm_way_names=(
            "Southwest Greenway Avenue",
            "Southwest Talbot Road",
            "Southwest Fairmount Boulevard",
        ),
        blurb=(
            "The climb to Portland's highest point, up through the West Hills to a "
            "park with Mount Hood and Mount St. Helens on the skyline."
        ),
        disciplines=("road",),
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # three named roads make up the climb
        ),
        notes=(
            "Signed for bikes. Fairmount Boulevard contours around the hill rather than "
            "climbing it, so the steep work is on Greenway and Talbot. Dense "
            "residential streets with cross traffic."
        ),
        confidence="low",
    ),

    # ── Pittsburgh ────────────────────────────────────────────────────────────
    # Canton Avenue is deliberately absent. See docs/research/famous-descents.md — its
    # three steep ways are all `oneway=yes` UPHILL in OSM (with `incline=34%`), so there
    # is no legal descent to find. The pipeline is right to refuse it: the only route it
    # can build on the name is the flat block at the top, which shipped as a 0 m / 0 km/h
    # card. A famous climb is not automatically a hill bomb.
    Spot(
        slug="rialto-street",
        name="Rialto Street (Pig Hill)",
        city="Pittsburgh",
        state="PA",
        bbox=(40.46383, -79.98398, 40.46830, -79.97878),
        osm_way_names=("Rialto Street",),
        blurb=(
            "\"Pig Hill\" — the 24% wall up to Troy Hill, named for the pigs once "
            "driven up it to the slaughterhouse at the top."
        ),
        disciplines=("road",),
        notes=(
            "Short, and far steeper than the grade shown here — our elevation data "
            "badly under-reads a 24% wall. The hazard is the bottom, not the top: the "
            "run-out drops straight onto busy Route 28."
        ),
        confidence="high",
    ),
    Spot(
        slug="sycamore-street",
        name="Sycamore Street (Mount Washington)",
        city="Pittsburgh",
        state="PA",
        bbox=(40.4269, -80.00867, 40.43246, -79.99836),
        osm_way_names=("East Sycamore Street",),
        blurb=(
            "Straight off Grandview Avenue down the face of Mount Washington to the "
            "Monongahela — no bends, no relief."
        ),
        disciplines=("road",),
        notes=(
            "The Dirty Dozen hill is the East Sycamore half. It carries real traffic, "
            "and the run-out is into the P.J. McArdle / Liberty Bridge junctions."
        ),
        confidence="high",
    ),
    Spot(
        slug="eleanor-street",
        name="Eleanor Street (South Side Slopes)",
        city="Pittsburgh",
        state="PA",
        # "Eleanor Street" recurs across the metro; this box is what pins it to the
        # South Side Slopes wall.
        bbox=(40.41394, -79.97569, 40.42648, -79.97016),
        osm_way_names=("Eleanor Street",),
        blurb=(
            "One of the South Side Slopes walls, falling off Arlington Avenue to the "
            "flats by the river in a few hundred metres."
        ),
        disciplines=("road",),
        notes=(
            "A Dirty Dozen hill, and far steeper than 10 m elevation data can show. The "
            "map has a gap part way down, so it may appear as two runs rather than one. "
            "Residential the whole way, with cross streets and parked cars."
        ),
        confidence="medium",
    ),
    Spot(
        slug="logan-street-millvale",
        name="Logan Street (Millvale)",
        city="Pittsburgh",
        state="PA",
        bbox=(40.47445, -79.97893, 40.47924, -79.96779),
        osm_way_names=("Logan Street",),
        blurb=(
            "Millvale's Dirty Dozen wall, dropped instead of climbed — off the hill and "
            "straight down to the Allegheny flats."
        ),
        disciplines=("road",),
        notes=(
            "Narrow residential street, and the bottom lands in Millvale's grid a block "
            "from Route 28."
        ),
        confidence="medium",
    ),
    Spot(
        slug="suffolk-street",
        name="Suffolk Street (Fineview)",
        city="Pittsburgh",
        state="PA",
        bbox=(40.4655, -80.00812, 40.47072, -79.99922),
        osm_way_names=("Suffolk Street",),
        blurb=(
            "Off Fineview toward the North Side, with the downtown skyline dead ahead "
            "the whole way down."
        ),
        disciplines=("road",),
        notes=(
            "The first pitch of the Dirty Dozen's Suffolk–Hazelton–Burgess sequence. "
            "Short, residential, and steep enough that the measured gradient here will "
            "read low against what it feels like."
        ),
        confidence="medium",
    ),
    Spot(
        slug="boustead-street",
        name="Boustead Street (Beechview)",
        city="Pittsburgh",
        state="PA",
        bbox=(40.40318, -80.03569, 40.4075, -80.02748),
        osm_way_names=("Boustead Street",),
        blurb=(
            "A single Beechview block aimed downhill at the Saw Mill Run valley, at a "
            "measured 13% and a real deal steeper."
        ),
        disciplines=("road",),
        notes=(
            "Only 350 m end to end, so this is a one-block bomb rather than a descent. "
            "Around the corner from Canton Avenue, which is deliberately not "
            "in this collection — its steep block is one-way uphill."
        ),
        confidence="medium",
    ),

    # ── Salt Lake City ────────────────────────────────────────────────────────
    Spot(
        slug="emigration-canyon",
        name="Emigration Canyon Road",
        city="Salt Lake City",
        state="UT",
        # The research clipped this at the west end to fit a per-axis 0.1° bbox cap.
        # That cap is now area-based (see test_spots.test_bbox_is_tight), and the full
        # road is a long thin corridor: 0.111° of longitude but only 0.0032°², well
        # inside the budget. Un-clipped, so the descent runs the whole canyon.
        bbox=(40.75759, -111.81101, 40.78654, -111.70001),
        osm_way_names=("Emigration Canyon Road",),
        blurb=(
            "Salt Lake's most-ridden road, up the canyon the Mormon pioneers came down "
            "in 1847 — steady, open, and never steep."
        ),
        disciplines=("road",),
        notes=(
            "Real traffic, but it is the after-work ride for the whole Wasatch Front, "
            "and signed for bikes. A low average gradient, so the descent is fast and "
            "open rather than steep."
        ),
        confidence="medium",
    ),
    Spot(
        slug="big-cottonwood-canyon-road",
        name="Big Cottonwood Canyon Road",
        city="Salt Lake City",
        state="UT",
        bbox=(40.60184, -111.80857, 40.65346, -111.57743),
        osm_way_names=("Big Cottonwood Canyon Road",),
        blurb=(
            "Brighton to the valley floor in one line, through the S-curves and out "
            "of the narrows at the mouth onto Wasatch Boulevard."
        ),
        disciplines=("road",),
        notes=(
            "Watershed canyon: no dogs, and the road carries ski traffic all winter "
            "and canyon traffic all summer. Cyclists are legally required to ride "
            "single file, and the lower narrows have no shoulder. Avalanche closures "
            "in winter."
        ),
        confidence="medium",
    ),
    Spot(
        slug="little-cottonwood-canyon-road",
        name="Little Cottonwood Canyon Road",
        city="Salt Lake City",
        state="UT",
        bbox=(40.5688, -111.82526, 40.59414, -111.62605),
        osm_way_names=("Little Cottonwood Road",),
        blurb=(
            "Alta to the mouth down the steepest of the Wasatch canyons, walled in "
            "granite and pointed straight at the valley."
        ),
        disciplines=("road",),
        notes=(
            "Heavy resort traffic, frequent avalanche closures in winter, and a "
            "watershed canyon so no dogs. The gradient near the mouth is the steep part."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mill-creek-canyon-road",
        name="Mill Creek Canyon Road",
        city="Salt Lake City",
        state="UT",
        bbox=(40.6825, -111.7786, 40.70866, -111.64493),
        osm_way_names=("Mill Creek Canyon Road",),
        blurb=(
            "Out of the aspens at Big Water down a narrow shaded canyon, ending "
            "abruptly in a Salt Lake neighbourhood."
        ),
        disciplines=("road",),
        notes=(
            "The upper road above Maple Grove is gated closed by snow from "
            "roughly November to July. Dogs run off-leash on odd-numbered days, and "
            "there is a fee station at the mouth."
        ),
        confidence="medium",
    ),
    Spot(
        slug="bountiful-skyline-drive",
        name="Skyline Drive (Bountiful)",
        city="Salt Lake City",
        state="UT",
        bbox=(40.89277, -111.85493, 40.98178, -111.79095),
        osm_way_names=("Skyline Drive",),
        blurb=(
            "Off the Bountiful Peak ridge straight down the front of the Wasatch, "
            "switchbacks stacked above the valley the whole way into town."
        ),
        disciplines=("road", "gravel"),
        notes=(
            "Steep enough for the whole run that brakes will fade; the top turns to "
            "gravel, and the Forest Service gate is closed by "
            "snow from about November to June."
        ),
        confidence="medium",
    ),
    Spot(
        slug="wasatch-crest-trail",
        name="Wasatch Crest Trail",
        city="Salt Lake City",
        state="UT",
        bbox=(40.61464, -111.60807, 40.68865, -111.55619),
        osm_way_names=("Wasatch Crest Trail",),
        blurb=(
            "The spine ride above Salt Lake: ridge dirt from Guardsman Pass with the "
            "valley on one side and Park City on the other."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "The named segment is the ridge traverse, so the net drop is modest — the "
            "big descent everyone rides afterwards is on the Mill Creek trails past "
            "the end of it. Bikes are allowed in Mill Creek on even-numbered days "
            "only. Above 9,000 ft and snowbound into July."
        ),
        confidence="low",
    ),
    Spot(
        slug="bobsled-trail",
        name="The Bobsled",
        city="Salt Lake City",
        state="UT",
        bbox=(40.77878, -111.85827, 40.79946, -111.84832),
        osm_way_names=("Bobsled Trail",),
        blurb=(
            "A rutted downhill-only chute through the foothills above the Avenues, "
            "spat out at the top of the city streets."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "One-way downhill. Steep, loose and badly eroded, with blind rollers and a "
            "few built jumps; "
            "the line has been rebuilt and re-routed repeatedly, so what is on the "
            "ground may not match the map."
        ),
        confidence="medium",
    ),

    # ── Honolulu ──────────────────────────────────────────────────────────────
    Spot(
        slug="tantalus-drive",
        name="Tantalus Drive",
        city="Honolulu",
        state="HI",
        bbox=(21.31530, -157.84175, 21.33175, -157.81290),
        osm_way_names=("Tantalus Drive",),
        blurb=(
            "Hairpins up an extinct cinder cone through rainforest above Honolulu — "
            "the west half of the Tantalus–Round Top loop."
        ),
        disciplines=("road",),
        notes=(
            "Half of a one-way circuit: most riders climb Tantalus and descend Round "
            "Top, which is a separate spot here. Wet, mossy pavement under the canopy "
            "is the real hazard — the descent is slick more often than not."
        ),
        confidence="high",
    ),
    Spot(
        slug="round-top-drive",
        name="Round Top Drive",
        city="Honolulu",
        state="HI",
        bbox=(21.30743, -157.83138, 21.33208, -157.81137),
        osm_way_names=("Round Top Drive",),
        blurb=(
            "The descending half of the Tantalus loop — off the Puu Ualakaa lookout "
            "down to Makiki, over Diamond Head and Waikiki."
        ),
        disciplines=("road",),
        notes=(
            "The side riders actually descend, and the most scenic drop on Oahu. Same "
            "wet-pavement hazard as Tantalus Drive."
        ),
        confidence="high",
    ),
    Spot(
        slug="wilhelmina-rise",
        name="Wilhelmina Rise",
        city="Honolulu",
        state="HI",
        bbox=(21.28035, -157.79998, 21.29815, -157.78725),
        osm_way_names=("Wilhelmina Rise",),
        blurb=(
            "Straight off the Maunalani ridge in Kaimuki down to Waialae Avenue, with "
            "Diamond Head filling the view the whole way."
        ),
        disciplines=("road",),
        notes=(
            "The steepest paved climb on Oahu, ridden the other way — around 26% at "
            "its worst. Residential, with driveways, cross streets and a signal at the "
            "bottom, and it is arrow-straight, so it comes up fast."
        ),
        confidence="high",
    ),
    Spot(
        slug="saint-louis-drive",
        name="Saint Louis Drive (St. Louis Heights)",
        city="Honolulu",
        state="HI",
        bbox=(21.28722, -157.81353, 21.30388, -157.79865),
        osm_way_names=("Saint Louis Drive",),
        blurb=(
            "Switchbacks down the St. Louis Heights ridge into Kaimuki, looking over "
            "downtown Honolulu and the harbour."
        ),
        disciplines=("road",),
        notes=(
            "Dense residential the whole way, with cross streets and city buses on it. "
            "Patched pavement, and damp under the trees near the top."
        ),
        confidence="medium",
    ),
    Spot(
        slug="pacific-heights-road",
        name="Pacific Heights Road",
        city="Honolulu",
        state="HI",
        bbox=(21.31637, -157.85341, 21.33087, -157.83467),
        osm_way_names=("Pacific Heights Road",),
        blurb=(
            "A narrow ridge road twisting down into downtown Honolulu, one lane wide "
            "in places with the harbour straight ahead."
        ),
        disciplines=("road",),
        notes=(
            "Blind hairpins and no centreline for much of it. The bottom two blocks "
            "are a one-way couplet running uphill, so a run finishes above them."
        ),
        confidence="medium",
    ),
    Spot(
        slug="aiea-heights-drive",
        name="Aiea Heights Drive",
        city="Honolulu",
        state="HI",
        bbox=(21.37723, -157.93311, 21.4005, -157.89806),
        osm_way_names=("Aiea Heights Drive",),
        blurb=(
            "Out of the rainforest at Keaiwa Heiau State Park and down the Aiea ridge "
            "toward Pearl Harbor."
        ),
        disciplines=("road",),
        notes=(
            "State park at the top with a one-way loop inside it, residential below. "
            "Wet, mossy pavement under the canopy; cross streets on the lower half."
        ),
        confidence="high",
    ),
    Spot(
        slug="laukahi-street",
        name="Laukahi Street (Waialae Iki)",
        city="Honolulu",
        state="HI",
        bbox=(21.27506, -157.77441, 21.29678, -157.75948),
        osm_way_names=("Laukahi Street",),
        blurb=(
            "Down the Waialae Iki ridge from the dead end at the top to Kalanianaole "
            "Highway, ocean in front of you the entire way."
        ),
        disciplines=("road",),
        notes=(
            "A dead-end ridge road, so the only traffic is residents. No shade "
            "anywhere on it, and it ends at a highway junction."
        ),
        confidence="medium",
    ),
    Spot(
        slug="nuuanu-pali-drive",
        name="Nuuanu Pali Drive",
        city="Honolulu",
        state="HI",
        bbox=(21.34054, -157.83486, 21.36828, -157.79177),
        osm_way_names=("Nuuanu Pali Drive",),
        blurb=(
            "The old road down Nuuanu Valley under a banyan tunnel, damp and green and "
            "bypassed by the highway beside it."
        ),
        disciplines=("road",),
        notes=(
            "One narrow lane in places, with a short divided section mid-way and tour "
            "vans that stop in the road. Rough, mossy pavement, and a gentle gradient "
            "— about 4% — so it is a scenic run rather than a fast one."
        ),
        confidence="medium",
    ),

    # ── Austin ────────────────────────────────────────────────────────────────
    Spot(
        slug="mount-bonnell-road",
        name="Mount Bonnell Road",
        city="Austin",
        state="TX",
        bbox=(30.31315, -97.77994, 30.34125, -97.77060),
        osm_way_names=("Mount Bonnell Road",),
        blurb=(
            "The ridge road to Austin's highest point and oldest tourist attraction — "
            "the standard pitch on every westside ride."
        ),
        disciplines=("road",),
        notes=(
            "Modest by national standards at 65 m of relief, and included because "
            "Austin genuinely has no bigger paved hill. Low average gradient over the "
            "full road; the pitches are short."
        ),
        confidence="high",
    ),
    Spot(
        slug="ladera-norte",
        name="Ladera Norte",
        city="Austin",
        state="TX",
        bbox=(30.35706, -97.78478, 30.36899, -97.77816),
        osm_way_names=("Ladera Norte",),
        blurb=(
            "A straight residential wall in the Northwest Hills, dropping toward Far "
            "West Boulevard at close to 10% the whole way."
        ),
        disciplines=("road",),
        notes=(
            "One of the handful of Austin streets that hold a real gradient. "
            "Residential, with driveways, parked cars and a stop at the bottom, and "
            "barely a kilometre long."
        ),
        confidence="high",
    ),
    Spot(
        slug="west-courtyard-drive",
        name="Courtyard Drive",
        city="Austin",
        state="TX",
        bbox=(30.35059, -97.80782, 30.36526, -97.79299),
        osm_way_names=("West Courtyard Drive",),
        blurb=(
            "Down through the Courtyard neighbourhood toward the Loop 360 bridge, with "
            "two pitches steep enough to need the brakes."
        ),
        disciplines=("road",),
        notes=(
            "Divided at the bottom, so the run uses one side of a couplet. "
            "Residential, with cross streets; the 20% pitches are short."
        ),
        confidence="high",
    ),
    Spot(
        slug="jester-boulevard",
        name="Jester Boulevard",
        city="Austin",
        state="TX",
        bbox=(30.3677, -97.80492, 30.39832, -97.79521),
        osm_way_names=("Jester Boulevard",),
        blurb=(
            "Off the Jester Estates ridge above Loop 360 — flat along the top, then a "
            "quarter mile at 11% to the bottom."
        ),
        disciplines=("road",),
        notes=(
            "The only way in or out of the subdivision, so traffic is constant at "
            "commute hours. The steep part is the lower quarter mile; the rest of the "
            "named road is ridge-top and flat."
        ),
        confidence="high",
    ),
    Spot(
        slug="smokey-valley",
        name="Smokey Valley",
        city="Austin",
        state="TX",
        bbox=(30.35955, -97.78439, 30.36581, -97.77744),
        osm_way_names=("Smokey Valley",),
        blurb=(
            "A 15% ramp off the ridge above Mount Bonnell — four hundred metres and it "
            "is over."
        ),
        disciplines=("road",),
        notes=(
            "The steepest pitch in Austin and a fixture of the Tour das Hügel. Very "
            "short, residential, with driveways on both sides. Ladera Norte is one "
            "block away."
        ),
        confidence="medium",
    ),
    Spot(
        slug="big-view-drive",
        name="Big View Drive",
        city="Austin",
        state="TX",
        bbox=(30.34739, -97.8757, 30.37959, -97.84278),
        osm_way_names=("Big View Drive",),
        blurb=(
            "Off the ridge west of Loop 360 toward Lake Austin — a rare Austin descent "
            "long enough to get up to speed on."
        ),
        disciplines=("road",),
        notes=(
            "Less talked about than the Loop 360 walls; it earns a slot on being the "
            "largest continuous drop on any named Austin street. Residential, with "
            "driveways and a low limit."
        ),
        confidence="low",
    ),
    Spot(
        slug="city-park-road",
        name="City Park Road",
        city="Austin",
        state="TX",
        bbox=(30.32417, -97.84571, 30.36764, -97.7953),
        osm_way_names=("City Park Road",),
        blurb=(
            "The road out to Emma Long Park, rolling along the ridge and then dropping "
            "hard to the Lake Austin shoreline at the end."
        ),
        disciplines=("road",),
        notes=(
            "A staple of every westside Austin route. Narrow, no shoulder, blind "
            "rollers and weekend park traffic. Only the last section down to the lake "
            "is a sustained descent."
        ),
        confidence="medium",
    ),

    # ── Asheville ─────────────────────────────────────────────────────────────
    Spot(
        slug="town-mountain-road",
        name="Town Mountain Road",
        city="Asheville",
        state="NC",
        bbox=(35.59951, -82.54387, 35.64903, -82.48997),
        osm_way_names=("Town Mountain Road",),
        blurb="Asheville's signature climb, rising from downtown to the Blue Ridge Parkway.",
        disciplines=("road",),
        notes=(
            "Real traffic — it is the gateway ride for a city that has become one of "
            "the biggest pro training bases in the East."
        ),
        confidence="high",
    ),

    # ── Boston ────────────────────────────────────────────────────────────────
    Spot(
        slug="summit-avenue-corey-hill",
        name="Summit Avenue (Corey Hill)",
        city="Boston",
        state="MA",
        # "Summit Avenue" is a very common OSM name — as with Mt. Diablo's Summit Road,
        # this tight bbox is the only thing disambiguating it.
        bbox=(42.34011, -71.14226, 42.34687, -71.12462),
        osm_way_names=("Summit Avenue",),
        blurb=(
            "Corey Hill — at about 17%, the steepest paved wall in Boston's inner "
            "suburbs, and the local benchmark in a flat region."
        ),
        disciplines=("road",),
        notes=(
            "Short, and dense residential the whole way: cross streets and stop signs "
            "on the descent. Parts of it are one-way, so a full-length run may not be "
            "legal in both directions."
        ),
        confidence="medium",
    ),
    Spot(
        slug="great-blue-hill-summit-road",
        name="Great Blue Hill (Summit Road)",
        city="Boston",
        state="MA",
        # "Summit Road" is a generic name and the region already has a "Summit Avenue";
        # this tight box around the Blue Hills access road is what disambiguates it.
        bbox=(42.2101, -71.12086, 42.22306, -71.11121),
        osm_way_names=("Summit Road",),
        blurb=(
            "Off the Blue Hill Observatory on a park road closed to cars — steady 9%, "
            "and steepest in the first few hundred metres."
        ),
        disciplines=("road",),
        notes=(
            "The DCR access road up Great Blue Hill is closed to public motor traffic "
            "but open to bikes and busy with walkers, so treat it as a "
            "shared path rather than a clear road."
        ),
        confidence="medium",
    ),
    Spot(
        slug="coon-hollow-path",
        name="Coon Hollow Path (Blue Hills)",
        city="Boston",
        state="MA",
        bbox=(42.20752, -71.1148, 42.21717, -71.09776),
        osm_way_names=("Coon Hollow Path",),
        blurb=(
            "Black-diamond singletrack off Great Blue Hill, dropping through boulder "
            "gardens to the reservation's south side."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "A designated mountain-bike trail west of Route 28, where riding is legal; "
            "the Skyline Trail and everything east of Route 28 is not. Closed to bikes "
            "for the month of March. The map has a gap mid-trail, so it may appear as "
            "two runs."
        ),
        confidence="medium",
    ),
    Spot(
        slug="chickatawbut-road",
        name="Chickatawbut Road",
        city="Boston",
        state="MA",
        bbox=(42.21444, -71.09353, 42.23108, -71.02962),
        osm_way_names=("Chickatawbut Road",),
        blurb=(
            "The Blue Hills' road ride — a long, open drop east off Chickatawbut Hill "
            "through the reservation woods."
        ),
        disciplines=("road",),
        notes=(
            "Low average gradient: this is a fast rolling road, not a wall. It carries "
            "real traffic, has no shoulder, and crosses Route 28 part way along."
        ),
        confidence="medium",
    ),
    Spot(
        slug="bussey-hill-arboretum",
        name="Bussey Hill (Arnold Arboretum)",
        city="Boston",
        state="MA",
        bbox=(42.29799, -71.12687, 42.30431, -71.1169),
        osm_way_names=("Bussey Hill Road",),
        blurb=(
            "A paved arboretum lane off Bussey Hill, curling down through the "
            "collections toward the Arborway."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Inside the Arnold Arboretum, where bikes are allowed on the paved roads "
            "only. Pedestrians everywhere, and the arboretum gates close at dusk. "
            "Modest drop — this is a smooth cruise, not a bomb."
        ),
        confidence="medium",
    ),
    Spot(
        slug="parker-hill-avenue",
        name="Parker Hill Avenue (Mission Hill)",
        city="Boston",
        state="MA",
        bbox=(42.32619, -71.1118, 42.33499, -71.09717),
        osm_way_names=("Parker Hill Avenue",),
        blurb=(
            "Mission Hill's run: off the crest by the old reservoir and down through "
            "triple-deckers toward the Fenway."
        ),
        disciplines=("skate", "road"),
        rider_profile="longboarder",
        notes=(
            "The hill Boston's longboard scene actually rides, but a small one — the "
            "crest falls away in both directions and neither side gives much more than "
            "30 m. Dense residential: parked cars, cross streets, and hospital traffic."
        ),
        confidence="low",
    ),


    # ══ Batch 2 — scatter-gather sweep, 2026-08-06 ═══════════════════════════
    #
    # Found by fanning region agents across the US, then verifying every candidate
    # against live Overpass. The verification is what earns these their place: it
    # corrected the OSM name on a third of them, and several would have silently
    # found nothing on the obvious guess — Kitt Peak is 'Arizona 386' (no way named
    # 'Kitt Peak Road' exists), App Gap is 'Mill Brook Road', the Rowena Loops are
    # 'Highway 30', and Sandia Crest needs the misspelt 'Sandia Crest Scenic Hyway'
    # variant listed verbatim or the descent breaks in the middle.
    #
    # Many carry a hand-clipped bbox: the full named corridor would blow the area cap
    # (see test_spots.test_bbox_is_tight), so the box covers the section people mean.
    # Where that happened it is called out in the spot's notes.

    # ── Tucson ──────────────────────────────────────────────────────────────
    Spot(
        slug="mount-lemmon",
        name="Mount Lemmon (Catalina Highway)",
        city="Tucson",
        state="AZ",
        bbox=(32.302, -110.763, 32.4502, -110.6831),
        osm_way_names=("North General Hitchcock Highway", "General Hitchcock Highway", "East General Hitchcock Road"),
        blurb=(
            "Forty kilometres of two-lane switchbacks off Mount Lemmon, dropping "
            "through five life zones into the Sonoran desert."
        ),
        disciplines=("road", "skate"),
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "A real state highway: rideable, but the shoulder is narrow and weekend "
            "traffic is heavy. The lower Tucson section is the Catalina Highway; the "
            "mountain road above it is the General Hitchcock Highway."
        ),
        confidence="high",
    ),
    Spot(
        slug="kitt-peak",
        name="Kitt Peak",
        city="Tucson",
        state="AZ",
        bbox=(31.9444, -111.6301, 32.0289, -111.5685),
        osm_way_names=("Arizona 386",),
        blurb=(
            "An empty observatory road falling 1,100 m off Kitt Peak, with almost no "
            "traffic on it."
        ),
        disciplines=("road",),
        notes=(
            "The gate is open roughly 9am–4pm, and that is the real constraint. Almost "
            "no traffic otherwise. Signposted as AZ 386 rather than by the peak's name."
        ),
        confidence="high",
    ),

    # ── Safford ─────────────────────────────────────────────────────────────
    Spot(
        slug="mount-graham-swift-trail",
        name="Mount Graham (Swift Trail)",
        city="Tucson",
        state="AZ",
        bbox=(32.6184, -109.8679, 32.732, -109.6939),
        osm_way_names=("West Swift Trail",),
        blurb=(
            "One of the longest paved climbs in the lower 48, ridden the other way — 37 "
            "km of unbroken pavement off Mount Graham."
        ),
        disciplines=("road",),
        notes=(
            "This is the paved lower 37 km. Above it the road turns to gravel and is "
            "gated seasonally — a separate ride. No services on the mountain."
        ),
        confidence="high",
    ),
    Spot(
        slug="gates-pass",
        name="Gates Pass",
        city="Tucson",
        state="AZ",
        bbox=(32.21589, -111.13437, 32.23785, -111.05931),
        osm_way_names=("Gates Pass Road",),
        blurb=(
            "The saguaro-forest pass west of Tucson, falling off the crest in open "
            "bends toward Old Tucson and the desert museum."
        ),
        disciplines=("road",),
        notes=(
            "Two lanes, no shoulder, and a tight limit through the pass itself; the "
            "sunset pullouts fill with cars that turn without looking."
        ),
        confidence="high",
    ),
    Spot(
        slug="sabino-canyon-road",
        name="Sabino Canyon Road",
        city="Tucson",
        state="AZ",
        bbox=(32.30833, -110.82502, 32.34548, -110.77823),
        osm_way_names=("Upper Sabino Canyon Road",),
        blurb=(
            "A car-free paved road down the Santa Catalinas' front canyon, crossing "
            "Sabino Creek nine times on stone bridges."
        ),
        disciplines=("road",),
        notes=(
            "Bikes are allowed only before 9am and after 5pm, and not at all on "
            "Wednesdays or Saturdays. Pavement only, no e-bikes, and it is a fee area. "
            "Shuttle buses use the same single lane."
        ),
        confidence="high",
    ),
    Spot(
        slug="sentinel-peak-a-mountain",
        name="Sentinel Peak (\"A\" Mountain)",
        city="Tucson",
        state="AZ",
        bbox=(32.20633, -111.0017, 32.21971, -110.98913),
        osm_way_names=("Sentinel Peak Road",),
        blurb=(
            "Off the volcanic hill with the whitewashed letter on it, dropping back "
            "into downtown Tucson with the valley laid out ahead."
        ),
        disciplines=("road",),
        notes=(
            "City park road with a one-way loop at the summit and a gate that closes "
            "after dark. Short, patched pavement, and busy at sunset."
        ),
        confidence="medium",
    ),
    Spot(
        slug="madera-canyon-road",
        name="Madera Canyon Road",
        city="Tucson",
        state="AZ",
        # Clipped at 31.7445 so the box stays inside the Tucson coverage region; the
        # top 200 m of the canyon road falls just outside it.
        bbox=(31.7445, -110.89011, 31.7946, -110.87926),
        osm_way_names=("Madera Canyon Road",),
        blurb=(
            "Out of the Santa Ritas' oak-and-sycamore canyon onto open grassland, on "
            "the road every birder in the country knows."
        ),
        disciplines=("road",),
        notes=(
            "Narrow with no shoulder and heavy weekend trailhead traffic. Forest "
            "Service fee area. This route starts just below the top of the canyon."
        ),
        confidence="medium",
    ),
    Spot(
        slug="redington-pass",
        name="Redington Pass",
        city="Tucson",
        state="AZ",
        # Clipped to the western grade off the pass; the named road runs another 30 km
        # east across the San Pedro valley at about 1%, which is not a descent.
        bbox=(32.25148, -110.67107, 32.30944, -110.5778),
        osm_way_names=("Redington Road",),
        blurb=(
            "Unpaved off Redington Pass into Tucson's east side, washboarded and loose "
            "through the saguaro."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "Graded dirt, but rutted and heavily washboarded, with high-clearance "
            "traffic and informal shooting areas on both sides of the pass. No shade, "
            "no water, and no phone service."
        ),
        confidence="medium",
    ),

    # ── Sedona ──────────────────────────────────────────────────────────────
    Spot(
        slug="schnebly-hill-road",
        name="Schnebly Hill Road",
        city="Sedona",
        state="AZ",
        bbox=(34.86, -111.7641, 34.9141, -111.6406),
        osm_way_names=("Schnebly Hill Road", "Schnebly Hill Road (High Profile/4x4 Vehicles Only)", "Schnebly Hill Road (High Profile Vehicles Only)"),
        blurb=(
            "Off the Mogollon Rim into Sedona: 19 km of rock and gravel with red-rock "
            "canyon walls the whole way down."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="mtb",
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Gravel and rock from the rim down to pavement at the Sedona end, with a "
            "middle section rough enough to be signed for high-profile vehicles only. "
            "Not a road bike descent."
        ),
        confidence="medium",
    ),
    Spot(
        slug="oak-creek-canyon-switchbacks",
        name="Oak Creek Canyon (AZ 89A)",
        city="Sedona",
        state="AZ",
        bbox=(34.9565, -111.75596, 35.06335, -111.73016),
        osm_way_names=("Prescott–Flagstaff Highway",),
        blurb=(
            "The switchbacks off the Mogollon Rim, then fifteen kilometres down Oak "
            "Creek Canyon between red walls into Sedona."
        ),
        disciplines=("road",),
        max_road_rank=7,
        notes=(
            "A two-lane state highway with no shoulder through the canyon, tight "
            "switchbacks and constant tourist traffic."
        ),
        confidence="medium",
    ),
    Spot(
        slug="upper-red-rock-loop-road",
        name="Upper Red Rock Loop Road",
        city="Sedona",
        state="AZ",
        bbox=(34.81534, -111.84155, 34.8521, -111.82159),
        osm_way_names=("Upper Red Rock Loop Road",),
        blurb=(
            "Down off the mesa west of Sedona toward Oak Creek and Red Rock State "
            "Park, with Cathedral Rock across the valley."
        ),
        disciplines=("road",),
        notes=(
            "Narrow and shoulderless, and a well-known photo stop, so cars brake and "
            "pull off without warning. Lower Red Rock Loop Road below it is a "
            "separate, much flatter road."
        ),
        confidence="medium",
    ),
    Spot(
        slug="sedona-airport-road",
        name="Airport Mesa (Airport Road)",
        city="Sedona",
        state="AZ",
        bbox=(34.84922, -111.7922, 34.86439, -111.77696),
        osm_way_names=("Airport Road",),
        blurb=(
            "The short pitch off Airport Mesa, dropping straight back into west Sedona "
            "from the overlook on the saddle."
        ),
        disciplines=("road",),
        notes=(
            "Short. The overlook pull-off and the airport parking generate constant "
            "turning traffic on a road with one lane each way and no shoulder."
        ),
        confidence="medium",
    ),
    Spot(
        slug="hiline-trail",
        name="Hiline Trail",
        city="Sedona",
        state="AZ",
        bbox=(34.80274, -111.80338, 34.81797, -111.76908),
        osm_way_names=("Hiline Trail",),
        blurb=(
            "A ledge line traversing high above Oak Creek before dropping to Baldwin "
            "Trailhead, Cathedral Rock in view most of the way."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Exposed slickrock benches with real consequence, rated black, and loose "
            "over-the-bars pitches near the bottom. Popular with hikers — yield."
        ),
        confidence="medium",
    ),
    Spot(
        slug="hangover-trail",
        name="Hangover Trail",
        city="Sedona",
        state="AZ",
        bbox=(34.86867, -111.74247, 34.87951, -111.71317),
        osm_way_names=("Hangover Trail",),
        blurb=(
            "The shelf around Mitten Ridge above Midgley Bridge — slickrock ledges and "
            "short chutes back down to Schnebly Hill Road."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "The exposure is the difficulty: several sections are a metre-wide ledge "
            "over a long fall, and walking them is the normal choice. Rated double "
            "black. Mostly a traverse, so the sustained drop is short."
        ),
        confidence="medium",
    ),

    # ── Las Vegas ───────────────────────────────────────────────────────────
    Spot(
        slug="deer-creek-road",
        name="Deer Creek Road (Mount Charleston)",
        city="Las Vegas",
        state="NV",
        bbox=(36.2622, -115.6549, 36.345, -115.5878),
        osm_way_names=("Deer Creek Road",),
        blurb=(
            "An alpine two-laner over an 8,000 ft summit, 45 minutes from the Strip and "
            "almost always empty."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Paved, quiet, and 45 minutes from the Strip. The road crests mid-way, so "
            "it comes back as two shorter descents rather than one long one."
        ),
        confidence="medium",
    ),
    Spot(
        slug="red-rock-scenic-drive",
        name="Red Rock Canyon Scenic Drive",
        city="Las Vegas",
        state="NV",
        bbox=(36.10934, -115.49244, 36.17422, -115.4219),
        osm_way_names=("Scenic Drive",),
        blurb=(
            "The back half of the one-way loop through Red Rock Canyon — nothing "
            "coming the other way from the high point down to the wash."
        ),
        disciplines=("road",),
        notes=(
            "One-way, fee entry, timed-entry reservations most of the year, and a gate "
            "that closes at dusk. Slow tourist traffic in a narrow lane."
        ),
        confidence="medium",
    ),
    Spot(
        slug="kyle-canyon-road",
        name="Kyle Canyon Road (Mount Charleston)",
        city="Las Vegas",
        state="NV",
        bbox=(36.2552, -115.65534, 36.31204, -115.38811),
        osm_way_names=("Kyle Canyon Road",),
        blurb=(
            "Off the Spring Mountains at Mount Charleston, out of the pines and down "
            "the alluvial fan into the Mojave."
        ),
        disciplines=("road",),
        notes=(
            "State route 157 and the main road to Mount Charleston, so weekend traffic "
            "is heavy. Snow and ice at the top from November. The bottom can be 20 °C "
            "warmer than the summit."
        ),
        confidence="high",
    ),
    Spot(
        slug="lee-canyon-road",
        name="Lee Canyon Road",
        city="Las Vegas",
        state="NV",
        # Clipped to the sustained grade below the ski area; the flat run-out east to
        # US 95 would push the bbox over the area cap and adds nothing.
        bbox=(36.35966, -115.63635, 36.43083, -115.52784),
        osm_way_names=("Lee Canyon Road",),
        blurb=(
            "The ski-area road on the Spring Mountains' north side, steady and open "
            "from the pinyon down to the valley floor."
        ),
        disciplines=("road",),
        notes=(
            "State route 156. Narrow shoulder, and chains-required conditions through "
            "the winter. This route covers the twelve kilometres that actually descend."
        ),
        confidence="medium",
    ),
    Spot(
        slug="cold-creek-road",
        name="Cold Creek Road",
        city="Las Vegas",
        state="NV",
        # The paved half only; above Cold Creek village the road turns to dirt and the
        # full corridor exceeds the bbox area cap.
        bbox=(36.43847, -115.7256, 36.49477, -115.60427),
        osm_way_names=("Cold Creek Road",),
        blurb=(
            "A dead-end road off the north Spring Mountains that sees almost no cars, "
            "with wild horses standing in the pavement."
        ),
        disciplines=("road",),
        notes=(
            "Paved lower half only. No services, no shade, and the wild-horse band "
            "genuinely blocks the road — they do not move for a bike."
        ),
        confidence="medium",
    ),
    Spot(
        slug="harris-springs-road",
        name="Harris Springs Road",
        city="Las Vegas",
        state="NV",
        bbox=(36.21726, -115.60034, 36.27617, -115.5118),
        osm_way_names=("Harris Springs Road",),
        blurb=(
            "Rough forest road off Angel Peak's shoulder, loose rock and washboard all "
            "the way down into Kyle Canyon."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "High-clearance dirt, rutted and loose, gated in winter, and empty enough "
            "that nobody will find you. Actual safe speed will be much lower than the "
            "number shown."
        ),
        confidence="low",
    ),

    # ── Albuquerque ─────────────────────────────────────────────────────────
    Spot(
        slug="sandia-crest-road",
        name="Sandia Crest Road",
        city="New Mexico",
        state="NM",
        bbox=(35.1611, -106.4529, 35.2199, -106.3467),
        osm_way_names=("Sandia Crest Road", "Sandia Crest Scenic Byway", "Sandia Crest Scenic Hyway"),
        blurb=(
            "Twenty kilometres of tight switchbacks off the 10,678 ft Sandia Crest, "
            "dropping 1,190 m to the East Mountains."
        ),
        disciplines=("road",),
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "A closure near the 10K trailhead was reported in 2026 — check with the "
            "Cibola National Forest before you go. Twenty kilometres of tight "
            "switchbacks with real tourist traffic."
        ),
        confidence="high",
    ),

    # ── Santa Fe ────────────────────────────────────────────────────────────
    Spot(
        slug="hyde-park-road",
        name="Hyde Park Road (Santa Fe)",
        city="New Mexico",
        state="NM",
        bbox=(35.69, -105.928, 35.7477, -105.8317),
        osm_way_names=("Hyde Park Road",),
        blurb=(
            "The lower half of Santa Fe's ski-basin descent — bike-legal asphalt from "
            "Hyde Memorial State Park down into town."
        ),
        disciplines=("road",),
        notes=(
            "The lower half only, from Hyde Memorial State Park down into town: about "
            "400 m of drop at a steady 3%. The upper road to the ski basin isn't "
            "included."
        ),
        confidence="medium",
    ),
    Spot(
        slug="winsor-trail",
        name="Winsor Trail",
        city="New Mexico",
        state="NM",
        # Clipped to the ski-basin-to-Tesuque line; Trail 254 continues east into the
        # Pecos and the full corridor blows the bbox area cap.
        bbox=(35.7432, -105.89098, 35.80673, -105.79881),
        osm_way_names=("Winsor Trail",),
        blurb=(
            "Santa Fe's standard descent: off the ski basin through aspen and fir all "
            "the way down to the village of Tesuque."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Trail 254. Bicycles are prohibited inside the Pecos Wilderness, which the "
            "trail borders — stay on the legal line. Rocky, rooty, heavily walked, and "
            "usually shuttled rather than climbed."
        ),
        confidence="medium",
    ),
    Spot(
        slug="aspen-vista-road",
        name="Aspen Vista Road (FS 150)",
        city="New Mexico",
        state="NM",
        bbox=(35.75881, -105.81305, 35.79008, -105.77921),
        osm_way_names=("FS 150",),
        blurb=(
            "The graded road off Tesuque Peak, running down through the biggest aspen "
            "stand near Santa Fe on packed dirt."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Signed as Forest Road 150. Closed to cars, so it is riders and walkers "
            "only — and it is mobbed in late September. Starts "
            "above 3,600 m; snow closes it in winter."
        ),
        confidence="medium",
    ),
    Spot(
        slug="pacheco-canyon-road",
        name="Pacheco Canyon Road",
        city="New Mexico",
        state="NM",
        bbox=(35.76905, -105.83424, 35.79013, -105.80864),
        osm_way_names=("Pacheco Canyon Road",),
        blurb=(
            "Unpaved down a shaded canyon on the Santa Fe side of the Sangre de "
            "Cristos, cool enough that locals ride it in July."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "Forest Road 102. Washboarded gravel with a rocky upper section. Snowed in "
            "through winter and a mud pit in spring."
        ),
        confidence="medium",
    ),
    Spot(
        slug="camp-may-road",
        name="Camp May Road (Pajarito Mountain)",
        city="New Mexico",
        state="NM",
        bbox=(35.88294, -106.40119, 35.90027, -106.36522),
        osm_way_names=("Camp May Road",),
        blurb=(
            "Off Pajarito Mountain above Los Alamos, out of the ski area and down the "
            "mesa edge toward the townsite."
        ),
        disciplines=("road", "gravel"),
        rider_profile="gravel",
        notes=(
            "Half asphalt and half gravel. County road with light traffic, closed by "
            "snow at the top in winter. A short divided stretch at the ski area is "
            "one-way each way."
        ),
        confidence="medium",
    ),
    Spot(
        slug="la-bajada",
        name="La Bajada",
        city="New Mexico",
        state="NM",
        bbox=(35.54798, -106.23868, 35.56077, -106.22347),
        osm_way_names=("La Bajada Trail",),
        blurb=(
            "The old switchbacks down the La Bajada escarpment — the grade the Camino "
            "Real and then Route 66 both used to get off the mesa."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="mtb",
        notes=(
            "Loose rock on an unmaintained historic alignment; several switchbacks are "
            "washed out. Access crosses pueblo land in places — check before riding. "
            "No shade and no water."
        ),
        confidence="low",
    ),

    # ── Red Lodge ───────────────────────────────────────────────────────────
    Spot(
        slug="beartooth-switchbacks",
        name="Beartooth Pass (East Switchbacks)",
        city="Montana",
        state="MT",
        bbox=(44.9466, -109.4898, 45.0066, -109.4084),
        osm_way_names=("Beartooth Highway",),
        blurb=(
            "Hairpins stacked down off the Beartooth East Summit past Rock Creek Vista "
            "— the highest paved road in the northern Rockies."
        ),
        disciplines=("road",),
        notes=(
            "The switchback staircase from the East Summit down past Rock Creek Vista, "
            "not the whole highway. Closed by snow roughly mid-October to late May. No "
            "shoulder on the hairpins and heavy RV traffic in July and August."
        ),
        confidence="high",
    ),

    # ── West Glacier ────────────────────────────────────────────────────────
    Spot(
        slug="going-to-the-sun-road",
        name="Going-to-the-Sun Road (Logan Pass)",
        city="Montana",
        state="MT",
        bbox=(48.6942, -113.7922, 48.7533, -113.7105),
        osm_way_names=("Going-to-the-Sun Road",),
        blurb=(
            "Glacier's cliff-cut drop from Logan Pass past the Weeping Wall — ledge "
            "pavement with a wall one side and nothing the other."
        ),
        disciplines=("road",),
        notes=(
            "Logan Pass down to The Loop — the section people mean. Seasonal: the pass "
            "typically opens late June and closes mid-October. The park's summer bike "
            "ban covers a lower stretch, not this one."
        ),
        confidence="high",
    ),

    # ── Jackson ─────────────────────────────────────────────────────────────
    Spot(
        slug="old-pass-road-teton",
        name="Old Pass Road (Teton Pass)",
        city="Jackson / Northwest Wyoming",
        state="WY",
        bbox=(43.4877, -110.957, 43.5021, -110.8926),
        osm_way_names=("Old Pass Road",),
        blurb=(
            "The decommissioned original Teton Pass highway: gated to cars, still "
            "paved, and all yours from the summit down."
        ),
        disciplines=("road", "skate"),
        notes=(
            "The Wilson (east) side. Gated at both ends and free of motor traffic, but "
            "expect walkers, dogs and uphill riders; sightlines on the hairpins are "
            "short."
        ),
        confidence="high",
    ),
    Spot(
        slug="lithium-teton-pass",
        name="Lithium (Teton Pass)",
        city="Jackson / Northwest Wyoming",
        state="WY",
        bbox=(43.4751, -110.9542, 43.4909, -110.9063),
        osm_way_names=("Lithium (Bicycle Only Downhill Only)",),
        blurb=(
            "Teton Pass's marquee downhill-only flow trail — 5 km of bermed, machine- "
            "built dirt off the summit toward Wilson."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Downhill and bike-only by design, so nobody is coming up it. Shuttle, or "
            "climb WY-22 or Old Pass Road to the top. Snow-free roughly June to "
            "October."
        ),
        confidence="high",
    ),

    # ── Cody ────────────────────────────────────────────────────────────────
    Spot(
        slug="dead-indian-pass",
        name="Dead Indian Pass (Chief Joseph Highway)",
        city="Jackson / Northwest Wyoming",
        state="WY",
        bbox=(44.734, -109.4215, 44.7674, -109.377),
        osm_way_names=("Chief Joseph Highway",),
        blurb=(
            "Hairpins off the 8,071 ft Dead Indian Summit, unwinding into the Clarks "
            "Fork canyon on the smoothest pavement in Wyoming."
        ),
        disciplines=("road",),
        notes=(
            "This route covers the switchbacks east of the summit and stops before the "
            "road naturally bottoms out. Remote, no services, cattle guards, and strong "
            "crosswinds on the upper hairpins."
        ),
        confidence="high",
    ),
    Spot(
        slug="black-canyon-teton-pass",
        name="Black Canyon (Teton Pass)",
        city="Jackson / Northwest Wyoming",
        state="WY",
        bbox=(43.46724, -110.95969, 43.49897, -110.90571),
        osm_way_names=("Black Canyon Trail",),
        blurb=(
            "Off the top of Teton Pass into the timber — rooty, steep and rough, and "
            "the run Jackson riders lap all summer."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Two-way, so climbers are coming up it, and sightlines in the trees are "
            "short. Snow-free roughly late June to October. Grizzly country — carry "
            "spray."
        ),
        confidence="medium",
    ),
    Spot(
        slug="signal-mountain-road",
        name="Signal Mountain Road",
        city="Jackson / Northwest Wyoming",
        state="WY",
        bbox=(43.82491, -110.61687, 43.85519, -110.56245),
        osm_way_names=("Signal Mountain Road",),
        blurb=(
            "The only summit road inside Grand Teton, and the way down faces the "
            "Cathedral Group across Jackson Lake."
        ),
        disciplines=("road",),
        notes=(
            "Narrow park road with no shoulder, no trailers allowed, and tourist "
            "traffic pulling over for the overlooks. Closed by snow from about "
            "November to May."
        ),
        confidence="medium",
    ),
    Spot(
        slug="curtis-canyon-road",
        name="Curtis Canyon Road",
        city="Jackson / Northwest Wyoming",
        state="WY",
        bbox=(43.50744, -110.69535, 43.52529, -110.6399),
        osm_way_names=("Curtis Canyon Road",),
        blurb=(
            "Gravel off the rim above the National Elk Refuge, dropping toward "
            "Jackson with the Tetons across the valley in front of you."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Unpaved and washboarded, with campground and overlook traffic in summer. "
            "Gated closed in winter for elk. Loose gravel on the switchbacks near the "
            "bottom."
        ),
        confidence="medium",
    ),
    Spot(
        slug="phillips-canyon",
        name="Phillips Canyon",
        city="Jackson / Northwest Wyoming",
        state="WY",
        bbox=(43.527, -110.91406, 43.54389, -110.86132),
        osm_way_names=("Phillips Canyon",),
        blurb=(
            "Down a wooded creek canyon off Phillips Bench toward Wilson — tighter "
            "and rougher than anything else that comes off the pass."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Two-way and rarely groomed: roots, creek crossings and deadfall early in "
            "the season. Not to be confused with Phillips Pass Trail or Phillips Bench "
            "Road above it. Grizzly country."
        ),
        confidence="medium",
    ),

    # ── Boise ───────────────────────────────────────────────────────────────
    Spot(
        slug="bogus-basin-road",
        name="Bogus Basin Road",
        city="Boise",
        state="ID",
        bbox=(43.6383, -116.2108, 43.7756, -116.1),
        osm_way_names=("North Bogus Basin Road",),
        blurb=(
            "Boise's home descent: 30 km of steady paved canyon from the ski area "
            "straight back into town, with no flat spots."
        ),
        disciplines=("road",),
        notes=(
            "A popular climb, so expect uphill riders, and winter ski traffic on the "
            "upper half."
        ),
        confidence="high",
    ),
    Spot(
        slug="eighth-street-trail-4",
        name="8th Street (Trail 4)",
        city="Boise",
        state="ID",
        bbox=(43.64221, -116.15245, 43.67973, -116.09673),
        osm_way_names=("#4 8th Street Motorcycle", "#4 8th Street Motorcycle Trail"),
        blurb=(
            "The spine of the Boise foothills, dropping off the ridge on hardpack "
            "dirt and finishing where 8th Street turns back into a street."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # one way carries the '… Trail' suffix variant
        ),
        notes=(
            "Two-way, open to motorcycles, and the busiest trail in the Ridge to "
            "Rivers network. Closed when wet — the foothills clay ruts permanently. "
            "Expect fast traffic in both directions."
        ),
        confidence="medium",
    ),
    Spot(
        slug="hard-guy",
        name="Hard Guy (Trail 33)",
        city="Boise",
        state="ID",
        bbox=(43.67433, -116.16562, 43.70664, -116.1031),
        osm_way_names=("#33 Hard Guy",),
        blurb=(
            "Off Boise Ridge down the back side into Dry Creek — narrow, fast, and "
            "far friendlier downhill than the name suggests."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "A continuous descent with two-way traffic, exposed and with no water. "
            "Seasonal closures apply in the foothills for winter range; check Ridge to "
            "Rivers before riding it."
        ),
        confidence="medium",
    ),
    Spot(
        slug="boise-ridge-road",
        name="Boise Ridge Road",
        city="Boise",
        state="ID",
        bbox=(43.63914, -116.12122, 43.75411, -116.05746),
        osm_way_names=("Boise Ridge Road",),
        blurb=(
            "The dirt road along the top of the Boise Front, running the ridge from "
            "the Bogus Basin side back down toward Rocky Canyon."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Unpaved the whole way, rutted and rocky in places, and shared with motos "
            "and 4x4s. Snow-closed in winter."
        ),
        confidence="low",
    ),
    Spot(
        slug="harris-creek-road",
        name="Harris Creek Road",
        city="Boise",
        state="ID",
        bbox=(43.86373, -116.20698, 43.90096, -115.99492),
        osm_way_names=("Harris Creek Road",),
        blurb=(
            "The quiet paved back way off the Idaho City side, curving down Harris "
            "Creek toward the Boise valley with almost nothing on it."
        ),
        disciplines=("road",),
        notes=(
            "Paved for most of its length; the gravel continuation is Harris Creek "
            "Summit Road. Narrow, no shoulder, and gravel washes across the corners "
            "after rain."
        ),
        confidence="medium",
    ),

    # ── Butte ───────────────────────────────────────────────────────────────
    Spot(
        slug="fleecer-ridge",
        name="Fleecer Ridge",
        city="Montana",
        state="MT",
        bbox=(45.8314, -112.822, 45.8687, -112.7276),
        osm_way_names=("Fleecer Ridge Road",),
        blurb=(
            "The Tour Divide's most feared drop — loose doubletrack off Fleecer Ridge, "
            "steep enough that most racers walk it."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="mtb",
        notes=(
            "The plunge itself is loose gravel over hardpack at a reported 38% — most "
            "Tour Divide racers walk it, and the speeds shown here should be taken with "
            "salt. No services, and cattle grazing on the ridge."
        ),
        confidence="medium",
    ),

    # ── Bozeman ─────────────────────────────────────────────────────────────
    Spot(
        slug="bangtail-divide",
        name="Bangtail Divide",
        city="Montana",
        state="MT",
        bbox=(45.8138, -110.8837, 45.8606, -110.8254),
        osm_way_names=("Bangtail Divide Trail",),
        blurb=(
            "The closing drop of Montana's best-known IMBA Epic: ridge dirt off Grassy "
            "Mountain, fast up top, switchbacked at the end."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "The northern Grassy Mountain to Brackett Creek segment, not the full "
            "22-mile ridge. Two-way trail, ridden both directions."
        ),
        confidence="medium",
    ),
    Spot(
        slug="skalkaho-pass",
        name="Skalkaho Pass (Skalkaho Highway)",
        city="Montana",
        state="MT",
        # The unpaved west side only — the summit down to where MT-38 is sealed
        # again near Hamilton. East of the pass the road is ordinary pavement.
        bbox=(46.17799, -113.90162, 46.25985, -113.69882),
        osm_way_names=("Skalkaho Highway",),
        blurb=(
            "The dirt shelf road down the west side of the Sapphires into the "
            "Bitterroot, one lane wide past the falls with nothing on the outside."
        ),
        disciplines=("gravel", "road"),
        rider_profile="gravel",
        notes=(
            "MT-38, unpaved over the pass and sealed at both ends. No guardrail on "
            "the shelf section and blind corners with logging trucks on them. Closed "
            "by snow from roughly late October to June."
        ),
        confidence="medium",
    ),
    Spot(
        slug="hyalite-canyon-road",
        name="Hyalite Canyon Road",
        city="Montana",
        state="MT",
        # Bozeman up to the reservoir. Above the dam the road turns to rough track
        # and the grade goes flat, so the box stops there.
        bbox=(45.45898, -111.08152, 45.58723, -110.94795),
        osm_way_names=("Hyalite Canyon Road",),
        blurb=(
            "Bozeman's canyon road, running back down from the reservoir at a grade "
            "you hold without pedalling and without touching the brakes."
        ),
        disciplines=("road", "gravel"),
        notes=(
            "Paved for most of the descent, gravel in places near the top. The "
            "busiest recreation corridor in the state, so traffic is heavy on summer "
            "weekends, and the upper road is snow-closed until late spring."
        ),
        confidence="medium",
    ),
    Spot(
        slug="chestnut-mountain",
        name="Chestnut Mountain",
        city="Montana",
        state="MT",
        bbox=(45.59061, -110.897, 45.64239, -110.85932),
        osm_way_names=("Chestnut Mountain - FS 458",),
        blurb=(
            "Bozeman's shuttle standby — off the summit on fast forested dirt down "
            "to the frontage road at Bozeman Pass."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Two-way and open to motorcycles, which have cut ruts into the fall-line "
            "sections. This is the long FS 458 descent, not the shorter Chestnut "
            "Mountain trails nearby."
        ),
        confidence="medium",
    ),
    Spot(
        slug="sheep-mountain-rattlesnake",
        name="Sheep Mountain (Rattlesnake)",
        city="Montana",
        state="MT",
        bbox=(46.91924, -113.92315, 46.99149, -113.74901),
        osm_way_names=("Sheep Mountain Trail",),
        blurb=(
            "The long way off the Rattlesnake's west ridge back toward Missoula — "
            "open ridgeline up top, then switchbacks in the trees."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Inside the Rattlesnake National Recreation Area, where bikes are allowed "
            "but the wilderness above is closed to them — check the boundary. The map "
            "does not record a difficulty. Not to be confused with Sheep Mountain Loop "
            "or Sheep Mountain Cutoff in the same drainage."
        ),
        confidence="low",
    ),

    # ── Robbinsville ────────────────────────────────────────────────────────
    Spot(
        slug="cherohala-skyway",
        name="Cherohala Skyway",
        city="Southern Appalachians",
        state="NC",
        bbox=(35.3003, -84.0717, 35.3535, -83.8917),
        osm_way_names=("Cherohala Skyway",),
        blurb=(
            "Miles of sweeping, near-empty high-country asphalt falling off the crest "
            "toward Santeetlah Gap."
        ),
        disciplines=("road",),
        notes=(
            "The upper western section, from around Beech Gap east toward Santeetlah "
            "Gap — not the full 60 km skyway, and it doesn't reach Robbinsville. Smooth "
            "asphalt with very little traffic."
        ),
        confidence="high",
    ),

    # ── Waitsfield ──────────────────────────────────────────────────────────
    Spot(
        slug="appalachian-gap",
        name="Appalachian Gap",
        city="Vermont",
        state="VT",
        bbox=(44.1791, -72.9316, 44.2107, -72.841),
        osm_way_names=("Mill Brook Road",),
        blurb=(
            "Nine kilometres of hairpins dropping 450 m off App Gap into the Mad River "
            "Valley."
        ),
        disciplines=("road",),
        notes=(
            "The east side of the gap, signed VT 17. A real road with traffic, and the "
            "upper hairpins are steep and blind."
        ),
        confidence="high",
    ),

    # ── Warren ──────────────────────────────────────────────────────────────
    Spot(
        slug="lincoln-gap",
        name="Lincoln Gap",
        city="Vermont",
        state="VT",
        bbox=(44.0862, -72.9849, 44.1101, -72.8566),
        osm_way_names=("Lincoln Gap Road",),
        blurb=(
            "The steepest paved mile in America, taken downhill — with a gravel west "
            "side off the top."
        ),
        disciplines=("road", "gravel"),
        notes=(
            "Covers both sides of the gap: asphalt east toward Warren, gravel west "
            "toward Lincoln. Closed in winter, and the pitches hit the mid-20s — "
            "genuinely dangerous at speed."
        ),
        confidence="high",
    ),

    # ── Windsor ─────────────────────────────────────────────────────────────
    Spot(
        slug="mount-ascutney",
        name="Mount Ascutney Auto Road",
        city="Vermont",
        state="VT",
        bbox=(43.4309, -72.4547, 43.4415, -72.4032),
        osm_way_names=("Mount Ascutney State Park Road",),
        blurb=(
            "The Ascutney hillclimb run backwards: 6 km at 12% average, on tight "
            "switchbacks off a Vermont monadnock."
        ),
        disciplines=("road",),
        notes=(
            "State park road: entry fee, and gated in winter."
        ),
        confidence="high",
    ),

    # ── East Burke ──────────────────────────────────────────────────────────
    Spot(
        slug="burke-j-bar",
        name="J-Bar (Burke Mountain)",
        city="Vermont",
        state="VT",
        bbox=(44.5687, -71.9192, 44.5897, -71.8927),
        osm_way_names=("Upper J-Bar", "J-Bar Trail"),
        blurb=(
            "Burke's flagship lift-served run — 535 m of machine-built descent through "
            "the Northeast Kingdom woods."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "The full line is Upper J-Bar into J-Bar Trail. Lift-served bike park, so "
            "it needs a paid ticket, it is seasonal, and riding back up is not an "
            "option."
        ),
        confidence="high",
    ),
    Spot(
        slug="smugglers-notch",
        name="Smugglers' Notch (VT 108)",
        city="Vermont",
        state="VT",
        bbox=(44.54102, -72.82572, 44.62178, -72.77397),
        osm_way_names=("Vermont Route 108 South",),
        blurb=(
            "Off the notch toward Jeffersonville: a hairpin threaded between "
            "house-sized boulders, then a long open drop into the valley."
        ),
        disciplines=("road",),
        notes=(
            "The north side of the notch, which is the one people mean. The road "
            "through the boulders is one lane wide with blind corners and no guardrail, "
            "and it is gated and unplowed from roughly October to May."
        ),
        confidence="high",
    ),
    Spot(
        slug="burke-mountain-toll-road",
        name="Burke Mountain Toll Road",
        city="Vermont",
        state="VT",
        bbox=(44.56892, -71.905, 44.59269, -71.88944),
        osm_way_names=("Toll Road",),
        blurb=(
            "Repaved switchbacks off Burke's summit into the Northeast Kingdom, on "
            "grades that touch 18% near the top."
        ),
        disciplines=("road",),
        notes=(
            "No charge for cyclists, but the road is narrow, two-way, and open to cars "
            "in summer — expect oncoming traffic in the switchbacks. Seasonal: gated "
            "outside the summer months. Same mountain as the J-Bar spot, different road."
        ),
        confidence="high",
    ),
    Spot(
        slug="middlebury-gap",
        name="Middlebury Gap (VT 125)",
        city="Vermont",
        state="VT",
        # Clipped to the gap and its east descent to Hancock. The full named corridor
        # runs 20 km out to Middlebury and East Middlebury, most of it flat valley road.
        bbox=(43.92367, -73.00205, 43.95811, -72.86786),
        osm_way_names=("Vermont Route 125",),
        blurb=(
            "The east side of the gap, dropping through Green Mountain National Forest "
            "to Hancock on wide, fast sweepers."
        ),
        disciplines=("road",),
        notes=(
            "A state highway with real traffic, including trucks. The upper section past "
            "the Snow Bowl is the steep part; the lower half is fast and open."
        ),
        confidence="high",
    ),
    Spot(
        slug="brandon-gap",
        name="Brandon Gap",
        city="Vermont",
        state="VT",
        bbox=(43.83797, -73.03207, 43.86106, -72.84807),
        osm_way_names=("Gap Road", "Brandon Mountain Road"),
        blurb=(
            "Both sides of the gap under the Great Cliff — steep and tight west to "
            "Brandon, long and open east toward Rochester."
        ),
        disciplines=("road",),
        # The road changes OSM name at the height of land, so a route may not be pinned
        # to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "VT 73 is Gap Road on the west side and Brandon Mountain Road on the east. "
            "The west descent is the steeper of the two. Peregrine "
            "closures affect the cliff, not the road."
        ),
        confidence="high",
    ),
    Spot(
        slug="roxbury-gap",
        name="Roxbury Gap",
        city="Vermont",
        state="VT",
        bbox=(44.10169, -72.82198, 44.11547, -72.77723),
        osm_way_names=("Roxburry Mountain Road",),
        blurb=(
            "Off the gap above the Mad River Valley: paved and fast west to Warren, "
            "loose gravel east toward Roxbury."
        ),
        disciplines=("road", "gravel"),
        notes=(
            "The map misspells the road as \"Roxburry Mountain Road.\" The Warren side "
            "is asphalt; the Roxbury side is dirt and washes out badly in mud season."
        ),
        confidence="medium",
    ),

    # ── Wilmington ──────────────────────────────────────────────────────────
    Spot(
        slug="whiteface-memorial-highway",
        name="Whiteface Memorial Highway",
        city="New York",
        state="NY",
        bbox=(44.3651, -73.9155, 44.4044, -73.8743),
        osm_way_names=("Whiteface Mountain Veterans Memorial Highway",),
        blurb=(
            "The highest paved road in the Northeast, dropping 700 m off Whiteface with "
            "the Adirondacks open around you."
        ),
        disciplines=("road",),
        notes=(
            "Bikes pay a toll, and the road is seasonal — roughly May to October."
        ),
        confidence="high",
    ),

    # ── Bar Harbor ──────────────────────────────────────────────────────────
    Spot(
        slug="cadillac-summit-road",
        name="Cadillac Mountain Summit Road",
        city="Acadia",
        state="ME",
        bbox=(44.3466, -68.2411, 44.3729, -68.222),
        osm_way_names=("Cadillac Summit Road",),
        blurb=(
            "Acadia's signature descent — smooth asphalt off the first place the sun "
            "hits the US, open above Frenchman Bay."
        ),
        disciplines=("road",),
        notes=(
            "Smooth asphalt at a steady 5%, with a 25 mph limit. Bikes need no vehicle "
            "reservation, but the road is busy with tourist traffic and closed in "
            "winter. The hiking trails off the summit are closed to bikes."
        ),
        confidence="high",
    ),
    Spot(
        slug="park-loop-ocean-drive",
        name="Park Loop Road (Ocean Drive)",
        city="Acadia",
        state="ME",
        # Clipped to the one-way eastern half. The full loop is 30 km and its western
        # side is two-way and largely flat.
        bbox=(44.335, -68.25505, 44.3804, -68.18099),
        osm_way_names=("Park Loop Road",),
        blurb=(
            "One-way and downhill past Sand Beach and Thunder Hole, with the Atlantic "
            "on your left the whole run."
        ),
        disciplines=("road",),
        notes=(
            "The one-way sections run clockwise and the legal direction is the "
            "descending one. Bikes need no vehicle reservation, but this is the busiest "
            "road in the park, with cars parked in the right lane most of the day. "
            "Closed in winter."
        ),
        confidence="high",
    ),
    Spot(
        slug="paradise-hill-road",
        name="Paradise Hill Road",
        city="Acadia",
        state="ME",
        bbox=(44.37323, -68.23618, 44.40175, -68.22452),
        osm_way_names=("Paradise Hill Road",),
        blurb=(
            "The park's back door — off Paradise Hill down to the Hulls Cove visitor "
            "centre through spruce, and empty early."
        ),
        disciplines=("road",),
        notes=(
            "The northern approach to the Park Loop, one-way southbound for cars over "
            "part of its length. Modest drop, and it ends in the visitor-centre car park."
        ),
        confidence="medium",
    ),
    Spot(
        slug="schoodic-head-road",
        name="Schoodic Head (Mountain Road)",
        city="Acadia",
        state="ME",
        # "Mountain Road" is generic; this box is the only thing pinning it to the
        # Schoodic Head summit road.
        bbox=(44.3442, -68.06896, 44.35294, -68.05177),
        osm_way_names=("Mountain Road",),
        blurb=(
            "A narrow gravel road off Schoodic Head on the quiet side of Acadia, "
            "dropping through spruce to the shore road."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Single-lane gravel, rough, and used by hikers walking to the summit. Short "
            "— about 1.8 km — and seasonal."
        ),
        confidence="medium",
    ),
    Spot(
        slug="beech-hill-road",
        name="Beech Hill Road",
        city="Acadia",
        state="ME",
        bbox=(44.31364, -68.35579, 44.35757, -68.33957),
        osm_way_names=("Beech Hill Road",),
        blurb=(
            "Off the Beech Mountain trailhead down to Somesville — a dead-end park road, "
            "so the only traffic is other people leaving."
        ),
        disciplines=("road",),
        notes=(
            "Quiet side of Mount Desert Island and a gentle gradient. Dead-ends at the "
            "Beech Mountain car park, which fills in summer."
        ),
        confidence="medium",
    ),

    # ── Bear Mountain ───────────────────────────────────────────────────────
    Spot(
        slug="perkins-memorial-drive",
        name="Perkins Memorial Drive (Bear Mountain)",
        city="New York",
        state="NY",
        bbox=(41.3011, -74.0157, 41.3195, -73.9953),
        osm_way_names=("Perkins Memorial Drive",),
        blurb=(
            "The New York road scene's home climb, taken downhill — off Perkins Tower "
            "to Seven Lakes Drive, an hour from the city."
        ),
        disciplines=("road",),
        notes=(
            "About 5.7 km, shorter than the 8 km often quoted. Seasonal gate closure "
            "and posted hours at the Perkins Tower entrance, plus park traffic and "
            "pedestrians near the top."
        ),
        confidence="high",
    ),
    Spot(
        slug="cascade-pass-keene",
        name="Cascade Pass (NY 73)",
        city="New York",
        state="NY",
        # Clipped to the pass and the Keene descent; the named way carries on south
        # through Keene Valley for another 8 km of valley road.
        bbox=(44.21, -73.90062, 44.26914, -73.78049),
        osm_way_names=("State Highway 73",),
        blurb=(
            "The Ironman descent — off the pass past the Cascade Lakes and down the "
            "High Peaks corridor into Keene."
        ),
        disciplines=("road",),
        max_road_rank=7,
        notes=(
            "A busy state highway in summer and foliage season, with rock fall and "
            "frost heaves near the lakes."
        ),
        confidence="high",
    ),
    Spot(
        slug="platte-clove-road",
        name="Platte Clove Road",
        city="New York",
        state="NY",
        bbox=(42.1139, -74.12631, 42.16174, -74.05297),
        osm_way_names=("Platte Clove Road",),
        blurb=(
            "A one-lane shelf road off the Catskill escarpment, hairpins hung over "
            "Plattekill Clove with pitches into the mid-teens."
        ),
        disciplines=("road",),
        notes=(
            "Closed to all traffic from November to April, and posted against trucks "
            "and buses year-round. No guardrail over much of the drop, blind hairpins, "
            "and gravel washed across the road after rain."
        ),
        confidence="high",
    ),
    Spot(
        slug="prospect-mountain-highway",
        name="Prospect Mountain Veterans Memorial Highway",
        city="New York",
        state="NY",
        bbox=(43.40491, -73.7508, 43.43839, -73.70911),
        osm_way_names=("Prospect Mountain Veterans Memorial Highway",),
        blurb=(
            "A wide-shouldered spiral off the summit above Lake George, dropping to the "
            "village in long, sighted curves."
        ),
        disciplines=("road",),
        notes=(
            "Bikes pay a small toll and are signed for. Seasonal — roughly late May to "
            "Veterans Day — and the gate shuts in the late afternoon, so a late descent "
            "can leave you locked in. The summit loops are one-way."
        ),
        confidence="high",
    ),
    Spot(
        slug="mountain-rest-road",
        name="Mountain Rest Road (Mohonk)",
        city="New York",
        state="NY",
        bbox=(41.75055, -74.13317, 41.78084, -74.09574),
        osm_way_names=("Mountain Rest Road",),
        blurb=(
            "Down the Shawangunk ridge past the Mohonk gatehouse to New Paltz — steady, "
            "open, and the Gunks' standard descent."
        ),
        disciplines=("road",),
        notes=(
            "Heavy climber and hiker traffic on weekends, with cars pulling in and out "
            "of the Mohonk gatehouse near the top. Two-way the whole way."
        ),
        confidence="high",
    ),
    Spot(
        slug="meads-mountain-road",
        name="Meads Mountain Road (Overlook)",
        city="New York",
        state="NY",
        bbox=(42.04762, -74.12602, 42.07279, -74.11564),
        osm_way_names=("Meads Mountain Road",),
        blurb=(
            "Straight off the Overlook Mountain trailhead into Woodstock — barely three "
            "kilometres, and steep the whole way."
        ),
        disciplines=("road",),
        notes=(
            "Cars park along the shoulder at the trailhead at the top, and the bottom "
            "drops straight into Woodstock village traffic."
        ),
        confidence="high",
    ),
    Spot(
        slug="storm-king-highway",
        name="Storm King Highway (NY 218)",
        city="New York",
        state="NY",
        bbox=(41.38667, -73.99875, 41.43947, -73.96887),
        osm_way_names=("Storm King Highway",),
        blurb=(
            "The cliff road blasted into Storm King above the Hudson — low-angle but "
            "exposed, with stone parapets and no shoulder."
        ),
        disciplines=("road",),
        notes=(
            "A famous road with a modest gradient: the descent is about 130 m over "
            "5 km, so expect a scenic run rather than a fast one. Subject to rock-fall "
            "closures, and there is nowhere to get out of the way of a car."
        ),
        confidence="medium",
    ),

    # ── Lincoln ─────────────────────────────────────────────────────────────
    Spot(
        slug="kancamagus-pass",
        name="Kancamagus Pass",
        city="White Mountains",
        state="NH",
        bbox=(44.003, -71.689, 44.068, -71.4197),
        osm_way_names=("Kancamagus Highway",),
        blurb=(
            "The best-known road descent in the White Mountains, off the 870 m "
            "Kancamagus Pass toward Lincoln."
        ),
        disciplines=("road",),
        notes=(
            "The western half, from the pass down toward Lincoln. No services and no "
            "cell coverage over the pass, and the road is heavily trafficked in foliage "
            "season."
        ),
        confidence="medium",
    ),
    Spot(
        slug="bear-notch-road",
        name="Bear Notch Road",
        city="White Mountains",
        state="NH",
        bbox=(43.99176, -71.33205, 44.08602, -71.27077),
        osm_way_names=("Bear Notch Road",),
        blurb=(
            "The connector between Bartlett and the Kancamagus, dropping north out of "
            "the notch on smooth, sighted curves."
        ),
        disciplines=("road",),
        notes=(
            "Gated and unplowed in winter, which is exactly why it is the pleasant one — "
            "little traffic even in season. Two-way, paved, no shoulder."
        ),
        confidence="high",
    ),
    Spot(
        slug="crawford-notch",
        name="Crawford Notch (US 302)",
        city="White Mountains",
        state="NH",
        # Clipped at the north end to the notch itself; the named way runs on past
        # Bretton Woods and would blow the bbox area cap.
        bbox=(44.08898, -71.41635, 44.2249, -71.3498),
        osm_way_names=("Crawford Notch Road",),
        blurb=(
            "Through the notch below Webster Cliff and down the Saco valley to Bartlett "
            "— wide, fast, and rarely out of sight."
        ),
        disciplines=("road",),
        max_road_rank=7,
        notes=(
            "A truck route with heavy tourist traffic and a long sustained grade past "
            "the Willey House; the shoulder narrows to nothing through the gate of the "
            "notch."
        ),
        confidence="high",
    ),
    Spot(
        slug="tripoli-road",
        name="Tripoli Road",
        city="White Mountains",
        state="NH",
        bbox=(43.94124, -71.67705, 44.00054, -71.5052),
        osm_way_names=("Tripoli Road",),
        blurb=(
            "Over the height of land and down toward Woodstock — dirt through the "
            "middle, pavement at the ends, no houses anywhere."
        ),
        disciplines=("gravel", "road"),
        rider_profile="gravel",
        notes=(
            "Unpaved over the top and closed from roughly November to May. Dispersed "
            "camping along it means parked cars and pedestrians on blind corners in "
            "summer. Surface changes may split the descent into separate runs."
        ),
        confidence="high",
    ),
    Spot(
        slug="sandwich-notch-road",
        name="Sandwich Notch Road",
        city="White Mountains",
        state="NH",
        bbox=(43.82077, -71.59016, 43.88739, -71.47867),
        osm_way_names=("Sandwich Notch Road",),
        blurb=(
            "The oldest and roughest of the notch roads, dropping south to Center "
            "Sandwich on loose dirt and washboard."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Dirt for almost its whole length, badly rutted, and unmaintained in "
            "winter. Genuinely rough rather than groomed gravel — the surface, not the "
            "gradient, is what sets the speed here."
        ),
        confidence="high",
    ),

    # ── Port Angeles ────────────────────────────────────────────────────────
    Spot(
        slug="hurricane-ridge",
        name="Hurricane Ridge",
        city="Washington",
        state="WA",
        bbox=(47.9672, -123.5204, 48.0608, -123.3689),
        osm_way_names=("Hurricane Ridge Road",),
        blurb=(
            "Olympic National Park's marquee descent: 25 km from the 5,242 ft visitor "
            "center down to Heart o' the Hills, three tunnels en route."
        ),
        disciplines=("road",),
        notes=(
            "Summit down to the Heart o' the Hills entrance, stopping short of Port "
            "Angeles. Gated by snow in winter, and chip-sealed and shoulderless in "
            "places. Ride the Hurricane closes it to cars once a year."
        ),
        confidence="high",
    ),

    # ── Bellingham ──────────────────────────────────────────────────────────
    Spot(
        slug="artist-point",
        name="Artist Point (Mount Baker Highway)",
        city="Washington",
        state="WA",
        bbox=(48.8426, -121.9145, 48.9145, -121.6522),
        osm_way_names=("Mount Baker Highway",),
        blurb=(
            "Washington's highest paved road, from Artist Point at 5,140 ft down past "
            "Picture Lake and Heather Meadows."
        ),
        disciplines=("road",),
        notes=(
            "Artist Point down to roughly Douglas Fir, dropping the flat run into "
            "Glacier. The top is gated by snow until about July, and it is a real state "
            "highway with summer tourist traffic."
        ),
        confidence="high",
    ),
    Spot(
        slug="sst-galbraith",
        name="SST (Galbraith Mountain)",
        city="Washington",
        state="WA",
        bbox=(48.723, -122.4254, 48.741, -122.4063),
        osm_way_names=("SST - Upper", "SST - Lower"),
        blurb=(
            "The signature line on Galbraith, the hill that made Bellingham a bike town "
            "— downhill-only dirt singletrack."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Downhill-only dirt, in an upper and a lower half joined through the "
            "surrounding trail network. Galbraith is private timberland open under a "
            "public recreation easement."
        ),
        confidence="high",
    ),

    # ── Wenatchee ───────────────────────────────────────────────────────────
    Spot(
        slug="devils-gulch",
        name="Devil's Gulch",
        city="Washington",
        state="WA",
        bbox=(47.3099, -120.5189, 47.4, -120.4169),
        osm_way_names=("Devils Gulch Trail",),
        blurb=(
            "Buffed Cascade-east singletrack dropping 1,000 m from the Mission Ridge "
            "country to the trailhead near Cashmere."
        ),
        disciplines=("mtb", "gravel"),
        rider_profile="mtb",
        notes=(
            "Eighteen kilometres of buffed, remote singletrack — carry water. Fire "
            "closures are common in late summer."
        ),
        confidence="high",
    ),
    Spot(
        slug="deer-park-road",
        name="Deer Park Road",
        city="Washington",
        state="WA",
        bbox=(47.94692, -123.35311, 48.10595, -123.25498),
        osm_way_names=("Deer Park Road",),
        blurb=(
            "Olympic National Park's back road: gravel switchbacks off Blue Mountain, "
            "then nine miles of pavement down to Highway 101."
        ),
        disciplines=("gravel", "road"),
        rider_profile="gravel",
        max_road_rank=5,                         # tertiary
        notes=(
            "Upper half is narrow one-lane gravel with sheer drops and no guardrail; "
            "the lower half is paved. The park gates it from about October to April, "
            "and there is nowhere to pull off if a car comes the other way."
        ),
        confidence="medium",
    ),
    Spot(
        slug="washington-pass",
        name="Washington Pass (Highway 20)",
        city="Washington",
        state="WA",
        # SR 20 changes OSM name at the pass: "North Cascades Highway" west of it,
        # plain "Highway 20" east. This is the east descent, which is the one with
        # the hairpin under Liberty Bell. bbox clipped short of Mazama to stay
        # inside the size cap.
        bbox=(48.51246, -120.65644, 48.60298, -120.44897),
        osm_way_names=("Highway 20",),
        blurb=(
            "Off Washington Pass under the Liberty Bell spires, then down the Early "
            "Winters valley toward the Methow."
        ),
        disciplines=("road",),
        max_road_rank=7,                         # primary
        notes=(
            "Closed at the pass by avalanche danger from roughly November to April — "
            "the reopening ride before cars return is a local tradition. Wide shoulder, "
            "but summer weekend traffic is heavy with RVs."
        ),
        confidence="medium",
    ),
    Spot(
        slug="harts-pass",
        name="Harts Pass / Slate Peak",
        city="Washington",
        state="WA",
        # Two names for one descent: "Slate Peak Road" from the lookout down to
        # Harts Pass, "Harts Pass Road" from the pass down to the Methow. Hence
        # stay_on_initial_road=False.
        bbox=(48.65282, -120.68083, 48.73982, -120.54783),
        osm_way_names=("Slate Peak Road", "Harts Pass Road"),
        blurb=(
            "The highest road in Washington, dropping off Slate Peak on loose gravel "
            "with the Methow canyon falling away below the edge."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        max_road_rank=4,                         # unclassified
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Single-lane gravel, no guardrail, and long exposed drop-offs — the state "
            "bans trailers on it. Open roughly July to October; snowbound otherwise. "
            "No water and no cell coverage."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mount-constitution",
        name="Mount Constitution",
        city="Washington",
        state="WA",
        bbox=(48.64677, -122.84339, 48.67955, -122.8181),
        osm_way_names=("Mount Constitution Road",),
        blurb=(
            "Orcas Island's summit road, off the stone tower and down through Moran "
            "State Park to sea level at Cascade Lake."
        ),
        disciplines=("road",),
        max_road_rank=4,                         # unclassified
        notes=(
            "The highest point in the San Juans, reached by ferry. Narrow park road "
            "with tight corners, gravel in the turnouts, and slow tourist traffic "
            "most of the summer."
        ),
        confidence="medium",
    ),
    Spot(
        slug="freund-canyon",
        name="Freund Canyon",
        city="Washington",
        state="WA",
        bbox=(47.61991, -120.69641, 47.63405, -120.65357),
        osm_way_names=("Freund Canyon Loop",),
        blurb=(
            "Leavenworth's flow descent — bermed dirt spiralling off the canyon rim "
            "back down to the Wenatchee valley floor."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Ridden as a loop, climbing one side and descending the other. "
            "Low enough to ride from March, and hot and dusty by August."
        ),
        confidence="medium",
    ),
    Spot(
        slug="preston-railroad-tiger",
        name="Preston Railroad Trail (Tiger Mountain)",
        city="Washington",
        state="WA",
        bbox=(47.48776, -121.95424, 47.50101, -121.92399),
        # OSM has it as "Preston Railroad Grade", not the "Trail" everyone says.
        osm_way_names=("Preston Railroad Grade",),
        blurb=(
            "The old logging grade off East Tiger — the descent Seattle mountain "
            "biking grew up on, in the trees the whole way."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Tiger Mountain State Forest, day-use only, and rideable year round "
            "though it runs wet and greasy from October to May. Note the neighbouring "
            "Tiger Mountain Trail is hiker-only — different trail, similar name."
        ),
        confidence="medium",
    ),

    # ── Portland ────────────────────────────────────────────────────────────
    Spot(
        slug="larch-mountain",
        name="Larch Mountain",
        city="Portland",
        state="OR",
        bbox=(45.5088, -122.2561, 45.5518, -122.0789),
        osm_way_names=("East Larch Mountain Road",),
        blurb=(
            "Shaded, evenly graded pavement falling 23 km from near the Larch Mountain "
            "summit to the Historic Columbia River Highway."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Paved and evenly graded the whole way, and gated by snow in winter. The "
            "Larch Mountain hiking trail alongside it is closed to bikes."
        ),
        confidence="high",
    ),
    Spot(
        slug="nw-germantown-road",
        name="Northwest Germantown Road",
        city="Portland",
        state="OR",
        # Portland OSM spells directions out in full — "Northwest", never "NW".
        bbox=(45.57879, -122.85187, 45.59227, -122.77042),
        osm_way_names=("Northwest Germantown Road",),
        blurb=(
            "Skyline down through Forest Park to the Willamette at Highway 30 — steady, "
            "shaded, and the one West Hills drop that never lets up."
        ),
        disciplines=("road",),
        notes=(
            "No shoulder, a 45 mph limit and real commuter traffic, signed as a bike "
            "route regardless. Wet leaves and moss on the shaded lower half for most of "
            "the year. Northwest Old Germantown Road is a separate, quieter road."
        ),
        confidence="high",
    ),
    Spot(
        slug="nw-logie-trail-road",
        name="Northwest Logie Trail Road",
        city="Portland",
        state="OR",
        bbox=(45.64787, -122.89772, 45.66504, -122.86208),
        osm_way_names=("Northwest Logie Trail Road",),
        blurb=(
            "Skyline down to the Tualatin plain northwest of the city — the steepest of "
            "the West Hills drops, on a lane and a half of farm road."
        ),
        disciplines=("road",),
        notes=(
            "Rural and rough, with gravel washed onto the corners, blind farm entrances "
            "and no centerline for much of it. The pavement is in poor repair in places."
        ),
        confidence="medium",
    ),
    Spot(
        slug="nw-newberry-road",
        name="Northwest Newberry Road",
        city="Portland",
        state="OR",
        bbox=(45.60213, -122.83561, 45.62083, -122.80472),
        osm_way_names=("Northwest Newberry Road",),
        blurb=(
            "A narrow ravine road off Skyline down to Highway 30 and the Willamette, "
            "tight and shaded the whole way."
        ),
        disciplines=("road",),
        notes=(
            "Chronically slide-prone and closed for long stretches in the past — check "
            "it is open before riding out to it. Damp, mossy pavement under the trees."
        ),
        confidence="medium",
    ),
    Spot(
        slug="nw-cornell-road",
        name="Northwest Cornell Road",
        city="Portland",
        state="OR",
        bbox=(45.52403, -122.80207, 45.53663, -122.70222),
        osm_way_names=("Northwest Cornell Road",),
        blurb=(
            "Skyline down through two hand-cut rock tunnels into Northwest Portland — "
            "the city's best-known way home off the hill."
        ),
        disciplines=("road",),
        notes=(
            "The two tunnels are unlit, narrow and shoulderless, so lights matter; "
            "turning on 'avoid tunnels' cuts this route in pieces rather than shortening "
            "it. Heavy commuter traffic at both peaks."
        ),
        confidence="high",
    ),
    Spot(
        slug="nw-saltzman-road",
        name="Northwest Saltzman Road",
        city="Portland",
        state="OR",
        bbox=(45.55722, -122.79744, 45.57116, -122.74445),
        osm_way_names=("Northwest Saltzman Road",),
        blurb=(
            "Gravel through the middle of Forest Park, dropping from Skyline to Highway "
            "30 with a gate at the top that keeps the cars off it."
        ),
        disciplines=("gravel", "mtb"),
        rider_profile="gravel",
        notes=(
            "The middle is a gated gravel road inside Forest Park; both ends are paved "
            "residential street, which is why the surface reads mixed. Loose over "
            "hardpack, potholed after rain, and shared with walkers and runners."
        ),
        confidence="high",
    ),
    Spot(
        slug="sandy-ridge-hide-and-seek",
        name="Sandy Ridge — Hide and Seek",
        city="Portland",
        state="OR",
        bbox=(45.37825, -122.03206, 45.40089, -122.01781),
        osm_way_names=("Hide and Seek",),
        blurb=(
            "Sandy Ridge's signature drop — bermed, rock-armoured turns falling off the "
            "ridge through wet Cascade second growth."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Signed downhill-only. "
            "BLM land, ridden year-round in the rain, so expect slick roots and standing "
            "water. The climb back up is on paved Forest Road 14."
        ),
        confidence="medium",
    ),
    Spot(
        slug="sw-broadway-drive",
        name="Southwest Broadway Drive",
        city="Portland",
        state="OR",
        bbox=(45.50181, -122.70600, 45.50987, -122.68291),
        osm_way_names=("Southwest Broadway Drive",),
        blurb=(
            "The West Hills into downtown Portland — a tight, tree-lined drop off the "
            "Council Crest shoulder that spills onto Broadway at the bottom."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Narrow, with parked cars, blind corners and no shoulder, and it arrives "
            "straight into downtown traffic. Asphalt throughout."
        ),
        confidence="medium",
    ),

    # ── Columbia Gorge ──────────────────────────────────────────────────────
    Spot(
        slug="rowena-loops",
        name="Rowena Loops",
        city="Columbia Gorge",
        state="OR",
        bbox=(45.6661, -121.3895, 45.6958, -121.2386),
        osm_way_names=("Highway 30",),
        blurb=(
            "The horseshoe stack below Rowena Crest — the old highway folding through "
            "six curves down to the Columbia."
        ),
        disciplines=("road", "skate"),
        notes=(
            "The old highway through the horseshoe curves; the paved state trail west "
            "of Mosier is a separate facility. The hairpins proper are the eastern 4 "
            "km, below Rowena Crest."
        ),
        confidence="high",
    ),

    # ── Sisters ─────────────────────────────────────────────────────────────
    Spot(
        slug="mckenzie-pass",
        name="McKenzie Pass (Dead Horse Grade)",
        city="Oregon Cascades",
        state="OR",
        bbox=(44.1638, -121.9825, 44.2626, -121.798),
        osm_way_names=("McKenzie Highway",),
        blurb=(
            "Lava fields at the 5,325 ft summit, then the Dead Horse Grade switchbacks, "
            "on new pavement with almost no traffic."
        ),
        disciplines=("road",),
        notes=(
            "The summit through the lava beds and the Dead Horse switchbacks, 26 km. "
            "OR-242 is closed to all traffic mid-November to mid-June, and closed to "
            "cars but open to bikes for a few weeks each spring."
        ),
        confidence="high",
    ),

    # ── Oakridge ────────────────────────────────────────────────────────────
    Spot(
        slug="alpine-trail-oakridge",
        name="Alpine Trail (Oakridge)",
        city="Oregon Cascades",
        state="OR",
        bbox=(43.7579, -122.5254, 43.9034, -122.434),
        osm_way_names=("Alpine Trail #3450", "Alpine Trail"),
        blurb=(
            "Twenty-six kilometres of loamy old-growth singletrack — the trail that "
            "made Oakridge a destination."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Twenty-five kilometres along the ridge plus a short connector at the "
            "Westfir end. Shuttle or climb the forest road to the top; there is no "
            "bail-out once you drop in."
        ),
        confidence="high",
    ),
    Spot(
        slug="larison-rock",
        name="Larison Rock Trail",
        city="Oregon Cascades",
        state="OR",
        bbox=(43.70816, -122.47176, 43.73911, -122.45796),
        osm_way_names=("Larison Rock Trail",),
        blurb=(
            "Oakridge's steep one — tight switchbacks off Larison Rock, then a "
            "straight-line drop down the ridge to the Middle Fork."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Shuttled up the Larison Rock road above Oakridge. Steep and continuous "
            "enough that it is ridden on brakes, and the loose duff over hardpack "
            "goes greasy in the wet."
        ),
        confidence="medium",
    ),
    Spot(
        slug="hardesty-mountain",
        name="Hardesty Mountain",
        city="Oregon Cascades",
        state="OR",
        bbox=(43.7909, -122.67564, 43.8531, -122.65477),
        osm_way_names=("Hardesty Trail",),
        blurb=(
            "A brake-burning drop off Hardesty Mountain on pine-needle singletrack — "
            "switchbacks up top, rougher and faster below."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Willamette National Forest, shuttled from the Hardesty trailhead on "
            "Highway 58. Some of the upper switchbacks are tight enough to walk. "
            "Blowdown is common after winter."
        ),
        confidence="medium",
    ),
    Spot(
        slug="tire-mountain",
        name="Tire Mountain Trail",
        city="Oregon Cascades",
        state="OR",
        bbox=(43.82591, -122.56392, 43.84389, -122.4953),
        osm_way_names=("Tire Mountain Trail",),
        blurb=(
            "Ridge-running singletrack above Westfir, threading camas meadows and "
            "open side-hill on the way down."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Ridden west to east off the Windy Pass road, usually linked to Alpine "
            "on a long day. Narrow and off-camber through the meadows, best in "
            "late spring when the camas is out; poison oak lower down."
        ),
        confidence="medium",
    ),
    Spot(
        slug="larison-creek",
        name="Larison Creek Trail",
        city="Oregon Cascades",
        state="OR",
        bbox=(43.68154, -122.53167, 43.69299, -122.43887),
        osm_way_names=("Larison Creek Trail #3646",),
        blurb=(
            "Benched singletrack down the Larison Creek arm of Hills Creek Reservoir, "
            "mossy and green the whole way."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "The mild Oakridge ride and the one that stays rideable in winter. Low "
            "gradient with short punchy sections, narrow bench above the water, and "
            "hikers coming the other way near the reservoir end."
        ),
        confidence="medium",
    ),
    Spot(
        slug="mckenzie-river-trail",
        name="McKenzie River Trail (upper)",
        city="Oregon Cascades",
        state="OR",
        # bbox CLIPPED to the upper half, Clear Lake down to about Trail Bridge.
        # The full 40 km trail's union box is 0.033 deg^2, over the cap, and the
        # upper half is the section people come for.
        bbox=(44.25829, -122.05501, 44.39548, -121.98708),
        osm_way_names=("McKenzie River Trail #3507",),
        blurb=(
            "Down the lava beds from Clear Lake past Sahalie and Koosah falls and the "
            "Blue Pool, the river never out of earshot."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Nationally known, but the gradient is gentle — it descends at river "
            "grade, so it shows up here as several short pitches rather than one "
            "long run. The lava section near Carmen is a hike-a-bike, and the top "
            "holds snow into June."
        ),
        confidence="low",
    ),

    # ── Copper Harbor ───────────────────────────────────────────────────────
    Spot(
        slug="brockway-mountain-drive",
        name="Brockway Mountain Drive",
        city="Great Lakes",
        state="MI",
        bbox=(47.4604, -88.0741, 47.4719, -87.896),
        osm_way_names=("Brockway Mountain Drive",),
        blurb=(
            "The highest paved road between the Rockies and the Alleghenies, falling "
            "off a Keweenaw ridge to Lake Superior."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Paved on both sides of the ridge, so there are descents off the summit in "
            "either direction. Unplowed and gated in winter."
        ),
        confidence="high",
    ),
    Spot(
        slug="the-flow-copper-harbor",
        name="The Flow (Copper Harbor)",
        city="Great Lakes",
        state="MI",
        bbox=(47.4634, -87.9254, 47.4731, -87.8993),
        osm_way_names=("The Flow",),
        blurb=(
            "Copper Harbor's marquee flow descent off Brockway Mountain — berms, and a "
            "cliffside cantilever bridge."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Dirt singletrack, shuttle-served and ridden downhill in practice, though "
            "nothing stops you climbing it. Berms and a cliffside cantilever bridge."
        ),
        confidence="high",
    ),

    # ── Duluth ──────────────────────────────────────────────────────────────
    Spot(
        slug="seven-bridges-road",
        name="Seven Bridges Road",
        city="Great Lakes",
        state="MN",
        bbox=(46.8369, -92.0185, 46.8633, -92.0051),
        osm_way_names=("Seven Bridges Road", "Occidental Boulevard"),
        blurb=(
            "Duluth's stone-arch-bridge run down Amity Creek, from the Skyline ridge at "
            "Hawk Ridge to lake level."
        ),
        disciplines=("road", "gravel"),
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "About 2.9 km from the Skyline ridge to lake level, carrying on as "
            "Occidental Boulevard for the bottom 600 m. Paved residential street with "
            "the stone arch bridges the whole way."
        ),
        confidence="high",
    ),
    Spot(
        slug="skyline-parkway-west",
        name="Skyline Parkway (west end)",
        city="Great Lakes",
        state="MN",
        bbox=(46.6892, -92.2745, 46.7278, -92.2146),
        osm_way_names=("West Skyline Parkway", "Skyline Parkway"),
        blurb=(
            "The west end of Duluth's ridge-top parkway, off the Thompson Hill overlook "
            "toward the St. Louis River — half asphalt, half gravel."
        ),
        disciplines=("road", "gravel"),
        rider_profile="gravel",
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "The Thompson Hill and Spirit Mountain section, about 5 km — not the full "
            "ridge parkway. Roughly half asphalt, half gravel."
        ),
        confidence="medium",
    ),

    # ── Dardanelle ──────────────────────────────────────────────────────────
    Spot(
        slug="mount-nebo",
        name="Mount Nebo",
        city="Ozarks",
        state="AR",
        bbox=(35.2169, -93.2623, 35.232, -93.1646),
        osm_way_names=("State Highway 155",),
        blurb=(
            "Arkansas's hardest climb ridden the fun way — tight hairpins and 18% "
            "pitches falling 395 m off the Mount Nebo rim."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Signposted as State Highway 155. Paved throughout: tight hairpins off the "
            "rim, then a longer, flatter run east above Dardanelle."
        ),
        confidence="high",
    ),

    # ── Bentonville ─────────────────────────────────────────────────────────
    Spot(
        slug="back-40-the-ledges",
        name="The Ledges (Back 40)",
        city="Ozarks",
        state="AR",
        bbox=(36.4612, -94.1963, 36.4783, -94.178),
        osm_way_names=("The Ledges",),
        blurb=(
            "The bluff-line signature of Bella Vista's Back 40 — karst ledges, a "
            "hanging bridge, and fast swoops into the creek valleys."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Bella Vista has only about 100 m of relief, and The Ledges traverses along "
            "the bluff line rather than dropping continuously — expect several 60-90 m "
            "drops rather than one headline run."
        ),
        confidence="medium",
    ),
    Spot(
        slug="west-devils-den-road",
        name="Devil's Den Road",
        city="Ozarks",
        state="AR",
        bbox=(35.7725, -94.25306, 35.79078, -94.23094),
        osm_way_names=("West Devil's Den Road",),
        blurb=(
            "The drop into Devil's Den, falling off the Boston Mountains plateau to Lee "
            "Creek on tight paved switchbacks."
        ),
        disciplines=("road",),
        notes=(
            "AR 74, a state highway into the park: narrow, no shoulder, and slow with "
            "camper traffic on weekends. Short at under 5 km."
        ),
        confidence="medium",
    ),
    Spot(
        slug="erbie-road",
        name="Erbie Road",
        city="Ozarks",
        state="AR",
        bbox=(36.06924, -93.30454, 36.09386, -93.21819),
        osm_way_names=("Erbie Road",),
        blurb=(
            "Steep, rocky gravel off the Compton plateau down to the Buffalo River "
            "bottom — brake-dragging most of the way."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "Unpaved and rough, with loose rock and no guardrail. Fords near the bottom "
            "can be impassable after rain, and there are no services at Erbie."
        ),
        confidence="low",
    ),
    Spot(
        slug="kessler-mountain",
        name="Kessler Mountain",
        city="Ozarks",
        state="AR",
        bbox=(36.01649, -94.22181, 36.02265, -94.1981),
        osm_way_names=("West Kessler Mountain Road",),
        blurb=(
            "Fayetteville's home hill — a short, steep pitch off the Kessler ridge down "
            "toward the Cato Springs bottom."
        ),
        disciplines=("road", "gravel"),
        rider_profile="gravel",
        notes=(
            "Part asphalt, part gravel, on a residential road with driveways on it. "
            "Two kilometres long, and here because northwest Arkansas has little else "
            "this steep on pavement."
        ),
        confidence="low",
    ),

    # ── Milwaukee ───────────────────────────────────────────────────────────
    Spot(
        slug="holy-hill",
        name="Holy Hill",
        city="Great Lakes",
        state="WI",
        bbox=(43.2478, -88.279, 43.2543, -88.195),
        osm_way_names=("Holy Hill Road",),
        blurb=(
            "Southeastern Wisconsin's benchmark hill, rolling off the ridge below the "
            "basilica spires."
        ),
        disciplines=("road",),
        notes=(
            "A fast rural state highway with real traffic, so pick your moment. Paved, "
            "6.9 km, and the basilica knoll itself sits north of the road."
        ),
        confidence="medium",
    ),
    Spot(
        slug="overflow-copper-harbor",
        name="Overflow (Copper Harbor)",
        city="Great Lakes",
        state="MI",
        bbox=(47.46389, -87.91762, 47.47295, -87.90334),
        osm_way_names=("Overflow",),
        blurb=(
            "Copper Harbor's black-diamond line off Brockway Mountain — one-way, "
            "downhill-only, and twice as steep as The Flow beside it."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "Signed downhill-only. Rock rolls, drops and berms in dirt. "
            "Snow-covered from November."
        ),
        confidence="medium",
    ),
    Spot(
        slug="bliss-road-grandad-bluff",
        name="Bliss Road (Grandad Bluff)",
        city="Great Lakes",
        state="WI",
        bbox=(43.80998, -91.21737, 43.81711, -91.19028),
        osm_way_names=("Bliss Road",),
        blurb=(
            "La Crosse's bluff road, dropping off Grandad Bluff into the Mississippi "
            "valley on a run of tight switchbacks."
        ),
        disciplines=("road",),
        notes=(
            "Paved two-lane carrying overlook traffic, with a couple of blind hairpins "
            "and no shoulder. It is the largest paved drop in the Driftless for a long "
            "way in any direction."
        ),
        confidence="medium",
    ),
    Spot(
        slug="keene-duluth-traverse",
        name="Keene (Duluth Traverse)",
        city="Great Lakes",
        state="MN",
        bbox=(46.73701, -92.19078, 46.7573, -92.17755),
        # The OSM name carries the system in parentheses; this is the exact tag.
        osm_way_names=("Keene (Duluth Traverse)",),
        blurb=(
            "Dirt singletrack peeling off the Skyline ridge down to Keene Creek, in the "
            "middle of the city rather than out of it."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "A segment of the city-long Duluth Traverse, ridden in both directions — "
            "expect riders climbing toward you. Closed when wet in spring thaw."
        ),
        confidence="low",
    ),

    # ── Roanoke ─────────────────────────────────────────────────────────────
    Spot(
        slug="blue-ridge-apple-orchard",
        name="Blue Ridge Parkway — Apple Orchard Mountain",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(37.4926, -79.5425, 37.5703, -79.3513),
        osm_way_names=("Blue Ridge Parkway",),
        blurb=(
            "The Parkway's longest sustained drop, from its Virginia high point all the "
            "way down to the James River."
        ),
        disciplines=("road",),
        notes=(
            "Parkway sections close seasonally for ice, and the tunnels on this stretch "
            "need lights."
        ),
        confidence="high",
    ),

    # ── Lexington ───────────────────────────────────────────────────────────
    Spot(
        slug="vesuvius-va56",
        name="Vesuvius (VA 56)",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(37.8456, -79.2052, 37.9274, -79.0436),
        osm_way_names=("Crabtree Falls Highway", "Tye River Turnpike"),
        blurb=(
            "The Mountains of Misery wall ridden the fast way — off the Blue Ridge "
            "Parkway into the Shenandoah Valley."
        ),
        disciplines=("road",),
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Signed VA 56 the whole way, though the road changes name mid-descent. A "
            "real road with traffic, and the switchbacks below the Parkway are steep."
        ),
        confidence="high",
    ),

    # ── Harrisonburg ────────────────────────────────────────────────────────
    Spot(
        slug="reddish-knob",
        name="Reddish Knob",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(38.4246, -79.2235, 38.484, -79.0369),
        osm_way_names=("Briery Branch Road",),
        blurb=(
            "Harrisonburg's signature ride: nearly 20 km of uninterrupted paved descent "
            "off Briery Branch Gap into the valley."
        ),
        disciplines=("road",),
        notes=(
            "This is the paved road descent from Briery Branch Gap. The gravel spur up "
            "to the 4,397 ft bald is not included."
        ),
        confidence="medium",
    ),

    # ── Elkins ──────────────────────────────────────────────────────────────
    Spot(
        slug="spruce-knob",
        name="Spruce Knob",
        city="Shenandoah & Blue Ridge",
        state="WV",
        bbox=(38.6774, -79.5766, 38.7356, -79.457),
        osm_way_names=("Spruce Mountain Road", "Briery Gap Road"),
        blurb=(
            "West Virginia's high point — 25 km of near-continuous drop off Spruce Knob "
            "down to Riverton."
        ),
        disciplines=("road", "gravel"),
        rider_profile="gravel",
        # The descent legitimately changes OSM name partway down, so it cannot be
        # constrained to the name it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Mixed asphalt and gravel from the summit road down to Riverton, so bring "
            "tires for it. The summit road is gated in winter."
        ),
        confidence="high",
    ),
    Spot(
        slug="wintergreen-drive",
        name="Wintergreen Drive",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(37.90222, -78.97246, 37.92423, -78.94219),
        osm_way_names=("Wintergreen Drive",),
        blurb=(
            "The resort road off Wintergreen's ridge, holding a steady 8% down the "
            "mountain face into the Rockfish Valley."
        ),
        disciplines=("road",),
        notes=(
            "A resort access road, so shuttle vans and guest traffic all day and a "
            "gatehouse at the bottom. Steep enough that the bends arrive quickly."
        ),
        confidence="medium",
    ),
    Spot(
        slug="elliot-knob-forest-road",
        name="Elliott Knob (FS 82)",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(38.15503, -79.31758, 38.1693, -79.27079),
        # OSM spells it "Elliot Knob Forest Road" — one t, unlike the mountain.
        osm_way_names=("Elliot Knob Forest Road",),
        blurb=(
            "Straight down the flank of Elliott Knob on loose forest gravel — no "
            "switchbacks, just a fall-line road that never eases off."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "A gated service road to the summit towers, averaging around 15% on loose "
            "rock. This is a brake-dragging descent, not a fast one, and the speeds a "
            "coasting model predicts on it are not the speeds anyone rides."
        ),
        confidence="medium",
    ),
    Spot(
        slug="wild-oak-trail",
        name="Wild Oak Trail",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(38.3214, -79.30219, 38.39765, -79.16348),
        osm_way_names=("Wild Oak Trail",),
        blurb=(
            "The backbone of Stokesville riding — a ridge circuit in the George "
            "Washington forest with long rocky drops off either end of the crest."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "TR 716, a National Recreation Trail and the spine of the Shenandoah "
            "Mountain 100. It is a loop, so expect separate descents rather than one "
            "continuous run. Remote, rocky and unsigned in places."
        ),
        confidence="medium",
    ),
    Spot(
        slug="wolf-ridge-trail",
        name="Wolf Ridge Trail",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(38.4269, -79.20092, 38.45054, -79.12546),
        osm_way_names=("Wolf Ridge Trail",),
        blurb=(
            "The way down from the Reddish Knob ridge — nine kilometres of Harrisonburg "
            "singletrack falling to the North River."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "TR 378 is open to bikes. Fast and rocky along the ridge, tighter and "
            "more technical in the last third. A long way from a road once committed."
        ),
        confidence="medium",
    ),
    Spot(
        slug="dowells-draft",
        name="Dowells Draft",
        city="Shenandoah & Blue Ridge",
        state="VA",
        bbox=(38.27901, -79.29572, 38.31638, -79.25638),
        osm_way_names=("Dowells Draft",),
        blurb=(
            "Off the Shenandoah Mountain crest down a drainage to US 250 — creek "
            "crossings, loose rock and no flat spots to speak of."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "FR 449 and 650 are open to bikes and form a Shenandoah Mountain 100 "
            "descent. Wet in the bottom of the draft year-round, with several crossings."
        ),
        confidence="medium",
    ),

    # ── Washington DC ───────────────────────────────────────────────────────
    Spot(
        slug="sugarloaf-mount-ephraim",
        name="Mount Ephraim Road (Sugarloaf Mountain)",
        city="Mid-Atlantic",
        state="MD",
        bbox=(39.2183, -77.4267, 39.3016, -77.396),
        osm_way_names=("Mount Ephraim Road",),
        blurb=(
            "The DC area's signature dirt crossing, on the flank of Sugarloaf Mountain "
            "— gravel in the middle, pavement at both ends."
        ),
        disciplines=("gravel", "road"),
        rider_profile="gravel",
        notes=(
            "Gravel over the saddle with pavement at both ends, so expect the road to "
            "break into several runs, with the middle dirt pitch the one people mean. "
            "Modest at about 150 m of drop."
        ),
        confidence="high",
    ),

    # ── Reading ─────────────────────────────────────────────────────────────
    Spot(
        slug="duryea-drive",
        name="Duryea Drive (the Pagoda)",
        city="Mid-Atlantic",
        state="PA",
        bbox=(40.3324, -75.914, 40.3394, -75.8985),
        osm_way_names=("Duryea Drive",),
        blurb=(
            "Twelve switchbacks down Mount Penn past the Pagoda — the road Charles "
            "Duryea built to test his cars."
        ),
        disciplines=("road", "skate"),
        notes=(
            "Twelve switchbacks in 2.5 km, about 8% average, on a paved residential "
            "street. Watch for cars at the bends."
        ),
        confidence="high",
    ),
    Spot(
        slug="gambrill-park-road",
        name="Gambrill Park Road",
        city="Mid-Atlantic",
        state="MD",
        bbox=(39.44392, -77.50334, 39.52137, -77.48713),
        osm_way_names=("Gambrill Park Road",),
        blurb=(
            "Along the Catoctin ridge above Frederick and then off it — long, quiet, "
            "and shaded the whole way."
        ),
        disciplines=("road",),
        notes=(
            "Runs the spine of Gambrill State Park, so the rolling terrain may split the "
            "descent into several runs. Narrow, no centre line, and popular with hikers "
            "crossing to the Catoctin Trail."
        ),
        confidence="high",
    ),
    Spot(
        slug="pen-mar-high-rock",
        name="High Rock (Pen Mar)",
        city="Mid-Atlantic",
        state="MD",
        bbox=(39.693, -77.52544, 39.71978, -77.50404),
        osm_way_names=("Pen Mar High Rock Road",),
        blurb=(
            "Off the hang-glider launch at High Rock and down South Mountain to Pen "
            "Mar — five kilometres of narrow asphalt under hardwoods."
        ),
        disciplines=("road",),
        notes=(
            "Single lane in places, no centre line, and cars park along the top for the "
            "overlook. The Appalachian Trail crosses near the bottom."
        ),
        confidence="high",
    ),
    Spot(
        slug="frostown-road",
        name="Frostown Road (Fox's Gap)",
        city="Mid-Atlantic",
        state="MD",
        bbox=(39.47998, -77.61411, 39.50231, -77.58669),
        osm_way_names=("Frostown Road",),
        blurb=(
            "The quiet back side of Fox's Gap on South Mountain, narrow and wooded and "
            "steep from the ridge down to the Middletown valley."
        ),
        disciplines=("road",),
        notes=(
            "A Civil War Century fixture on the way up. One lane wide in places with no "
            "centre line, loose gravel washed onto the corners, and farm traffic at the "
            "bottom."
        ),
        confidence="high",
    ),
    Spot(
        slug="dahlgren-road",
        name="Dahlgren Road (Turner's Gap)",
        city="Mid-Atlantic",
        state="MD",
        bbox=(39.48217, -77.62044, 39.48999, -77.59392),
        osm_way_names=("Dahlgren Road",),
        blurb=(
            "Off Turner's Gap past the Dahlgren chapel — the steepest way down South "
            "Mountain's eastern face."
        ),
        disciplines=("road", "gravel"),
        notes=(
            "Part of the road is dirt, so expect a mixed-surface run. Very "
            "narrow, and it meets the old National Pike at the top where the through "
            "traffic is."
        ),
        confidence="medium",
    ),
    Spot(
        slug="peters-mountain-road",
        name="Peters Mountain Road (PA 225)",
        city="Mid-Atlantic",
        state="PA",
        bbox=(40.3788, -76.95093, 40.46167, -76.92413),
        osm_way_names=("Peters Mountain Road",),
        blurb=(
            "Over Peters Mountain and down the north side toward Halifax — long "
            "straights and one big sweeping bend."
        ),
        disciplines=("road",),
        max_road_rank=7,
        notes=(
            "A truck route over the ridge with a wide shoulder but fast traffic; the "
            "Appalachian Trail crosses at the top. Modest average gradient over its "
            "full length."
        ),
        confidence="medium",
    ),
    Spot(
        slug="woodrow-road-michaux",
        name="Woodrow Road (Michaux)",
        city="Mid-Atlantic",
        state="PA",
        bbox=(40.00858, -77.37258, 40.03247, -77.34161),
        osm_way_names=("Woodrow Road",),
        blurb=(
            "Michaux gravel, dropping off the plateau on forest-road surface — loose, "
            "fast, and empty outside race weekends."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "State forest road, gravel throughout, shared with hunters' trucks in season "
            "and with the endurance races Michaux is known for. No services and "
            "patchy phone coverage."
        ),
        confidence="medium",
    ),

    # ── Southern Appalachians ─────────────────────────────────────────────────
    #
    # Verified on a second pass: the first attempt lost this whole region to Overpass
    # rate-limiting (seven agents on one public endpoint), and every candidate came
    # back "NOT VERIFIED" rather than refuted. Re-run serially, five of seven stood up.
    #
    # Pilot Rock Trail is deliberately absent. It is a real Pisgah descent, but OSM
    # puts `bicycle=no` on a 644 m segment *between* two `bicycle=yes` segments — so a
    # route down it crosses ground bikes are barred from. The pipeline reads no
    # `bicycle=*` tag at all (see docs/research/famous-descents.md), so it cannot be
    # relied on to avoid that; the only safe filter today is not listing the spot.
    Spot(
        slug="roan-mountain",
        name="Roan Mountain (Carvers Gap)",
        city="Southern Appalachians",
        state="TN",
        bbox=(36.1047, -82.1132, 36.1765, -82.0773),
        # "Carvers Gap" is not an OSM way name — the through road is "Roan Road" for
        # its whole length.
        osm_way_names=("Roan Road",),
        blurb=(
            "Off the shoulder of Roan Mountain at 5,500 ft, dropping 16 km down a "
            "classic Appalachian high gap into the valley."
        ),
        disciplines=("road",),
        notes=(
            "Paved the whole way. Exposed and cold up top — the balds hold weather the "
            "valley doesn't."
        ),
        confidence="high",
    ),
    Spot(
        slug="hogpen-gap",
        name="Hogpen Gap (Richard B. Russell Scenic Highway)",
        city="Southern Appalachians",
        state="GA",
        # Clipped: the full named way runs 22.5 km in one 665-node piece (0.029°²).
        # This is the ~9 km window either side of the gap summit.
        bbox=(34.7229, -83.8614, 34.7589, -83.8083),
        osm_way_names=("Richard B. Russell Scenic Highway",),
        blurb=(
            "GA 348 over the highest paved pass in Georgia — switchbacks off Hogpen "
            "Gap, tagged very steep and signed against trucks."
        ),
        disciplines=("road",),
        notes=(
            "Signed very steep and posted against trucks: a narrow two-lane with a 30 "
            "mph limit."
        ),
        confidence="high",
    ),
    Spot(
        slug="newfound-gap-road",
        name="Newfound Gap (US 441)",
        city="Southern Appalachians",
        state="TN",
        # Clipped to the Tennessee side: Newfound Gap down to the park boundary above
        # Gatlinburg, which is the run people ride. The southern half of the road
        # carries a different OSM name ("Newfound Gap Road South") and is not included.
        bbox=(35.60901, -83.53375, 35.68151, -83.41468),
        # Tagged `highway=trunk`, well above the default rideable cut — hence the cap.
        osm_way_names=("Newfound Gap Road North",),
        blurb=(
            "Twenty kilometres of national-park switchbacks off Newfound Gap toward "
            "Gatlinburg, banked and smooth the whole way down."
        ),
        disciplines=("road",),
        max_road_rank=8,
        notes=(
            "A busy park highway — tour buses, overlook traffic and slow vehicles in "
            "season, and it closes for snow through the winter. Ride it at first light."
        ),
        confidence="medium",
    ),
    Spot(
        slug="kuwohi-road",
        name="Kuwohi (Clingmans Dome Road)",
        city="Southern Appalachians",
        state="TN",
        bbox=(35.55581, -83.49647, 35.61287, -83.42566),
        osm_way_names=("Kuwohi Access Road",),
        blurb=(
            "The dead-end road off the Smokies' high point, eleven kilometres of smooth "
            "two-lane running back down the crest to Newfound Gap."
        ),
        disciplines=("road",),
        notes=(
            "Signed as Clingmans Dome Road until the 2024 renaming. Closed to cars from "
            "December into spring, which is when the descent is best. Fog and ice are "
            "common on the ridge."
        ),
        confidence="medium",
    ),
    Spot(
        slug="sassafras-mountain",
        name="Sassafras Mountain (F. Van Clayton Highway)",
        city="Southern Appalachians",
        state="SC",
        bbox=(35.04405, -82.80466, 35.07852, -82.77334),
        osm_way_names=("F Van Clayton Memorial Highway",),
        blurb=(
            "South Carolina's high point by its only road — a narrow ridge lane holding "
            "7% almost the whole way down to Rocky Bottom."
        ),
        disciplines=("road",),
        notes=(
            "Paved and lightly trafficked, but patched, shoulderless and often covered "
            "in leaf litter. The road dead-ends at the summit, so everything you meet "
            "is going the other way."
        ),
        confidence="medium",
    ),
    Spot(
        slug="black-mountain-trail",
        name="Black Mountain Trail (Pisgah)",
        city="Southern Appalachians",
        state="NC",
        bbox=(35.28434, -82.77731, 35.34792, -82.72013),
        osm_way_names=("Black Mountain Trail",),
        blurb=(
            "The Pisgah descent people mean when they say Pisgah: rock slabs, roots and "
            "off-camber switchbacks dropping to the Davidson River."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "TR 127 is open to bikes along its whole length here. Steep slab and "
            "root sections that hold water; ride it dry. Hikers on the lower half near "
            "the ranger station."
        ),
        confidence="medium",
    ),
    Spot(
        slug="wayah-bald-road",
        name="Wayah Bald Road",
        city="Southern Appalachians",
        state="NC",
        bbox=(35.15212, -83.59129, 35.1806, -83.56011),
        osm_way_names=("Wayah Bald Road",),
        blurb=(
            "Forest Service gravel off the stone tower on Wayah Bald, falling seven "
            "kilometres to Wayah Gap above Franklin."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "FS 69. Loose gravel, no guardrail and blind bends, with a gate near the "
            "top that closes seasonally. Washouts are common after summer storms."
        ),
        confidence="medium",
    ),
    Spot(
        slug="green-river-cove-road",
        name="Green River Cove Road",
        city="Southern Appalachians",
        state="NC",
        # Clipped to the switchbacks. The full named road runs 17 km, but the eastern
        # 10 km is flat cove floor along the river; the famous part is the gorge wall
        # below Saluda.
        bbox=(35.24842, -82.33243, 35.28171, -82.29946),
        osm_way_names=("Green River Cove Road",),
        blurb=(
            "The hairpins below Saluda, corkscrewing down the Green River gorge wall to "
            "the cove floor."
        ),
        disciplines=("road",),
        notes=(
            "Effectively single-lane through the switchbacks, with no guardrail and "
            "blind corners. Heavy tuber and paddler traffic in summer; the cove road "
            "at the bottom is flat."
        ),
        confidence="medium",
    ),
    Spot(
        slug="kitsuma",
        name="Kitsuma",
        city="Asheville",
        state="NC",
        bbox=(35.6173, -82.2708, 35.6367, -82.2178),
        # Deliberately only the two `bicycle=designated` ways. The third name in the
        # system, "Kitsuma Peak Trail" (TR205A), is a 112 m `bicycle=no` spur up to the
        # overlook — left out so no route is built along it.
        osm_way_names=("Kitsuma Trail", "Kitsuma/Youngs Ridge Trail"),
        blurb=(
            "A Pisgah classic outside Old Fort — designated singletrack dropping off "
            "Kitsuma Ridge on a network built for mountain biking."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,   # TR205 into TR206 is a name change
        ),
        notes=(
            "Kitsuma Trail into Youngs Ridge Trail, both open to bikes; the short spur "
            "to the peak itself is not, so walk it if you want the view. Steep, rooty "
            "and switchbacked."
        ),
        confidence="high",
    ),
    Spot(
        slug="curtis-creek-road",
        name="Curtis Creek Road",
        city="Asheville",
        state="NC",
        bbox=(35.6441, -82.2054, 35.7385, -82.1552),
        osm_way_names=("Curtis Creek Road",),
        blurb=(
            "A classic Pisgah gravel descent — Forest Service washboard giving way to "
            "pavement as it drops 17 km back toward Old Fort."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "The upper 11 km is unpaved forest road and the lower 4 km is paved. That "
            "transition is the descent's character."
        ),
        confidence="high",
    ),
    Spot(
        slug="elk-mountain-scenic-highway",
        name="Elk Mountain Scenic Highway",
        city="Asheville",
        state="NC",
        bbox=(35.63472, -82.55208, 35.66178, -82.51073),
        osm_way_names=("Elk Mountain Scenic Highway",),
        blurb=(
            "Off the ridge below the Blue Ridge Parkway into north Asheville, curling "
            "down through hardwoods on a narrow two-lane."
        ),
        disciplines=("road",),
        notes=(
            "Paved, with no shoulder and no centerline in places. It is one of the "
            "standard local climbs, so expect riders coming up while you are coming "
            "down."
        ),
        confidence="medium",
    ),
    Spot(
        slug="ox-creek-road",
        name="Ox Creek Road",
        city="Asheville",
        state="NC",
        bbox=(35.66222, -82.50635, 35.69647, -82.46273),
        osm_way_names=("Ox Creek Road",),
        blurb=(
            "The back side of Craven Gap — seven kilometres of quiet two-lane falling "
            "to Reems Creek and Weaverville."
        ),
        disciplines=("road",),
        notes=(
            "Shares its top with Elk Mountain Scenic Highway, so the two descents leave "
            "the same ridge in opposite directions. Rural and lightly trafficked, with "
            "gravel washed onto the bends after rain."
        ),
        confidence="medium",
    ),
    Spot(
        slug="blue-ridge-craggy-gardens",
        name="Blue Ridge Parkway — Craggy Gardens",
        city="Asheville",
        state="NC",
        # The Parkway is one continuous named road for hundreds of kilometres, so a
        # spot on it has to be clipped to a single famous descent. This is the Craggy
        # Dome-to-Asheville run: from the high ground above Craggy Gardens down past
        # Craven Gap to the Folk Art Center at US 70, about 29 km and 980 m. It is the
        # descent every Asheville rider means by "coming down from Craggy", and it is
        # 400 km south of the Virginia section held by `blue-ridge-apple-orchard`.
        bbox=(35.5984, -82.49889, 35.71177, -82.36285),
        osm_way_names=("Blue Ridge Parkway",),
        blurb=(
            "Off Craggy Dome down the Parkway into east Asheville — long sightlines, "
            "sweeping bends and almost no cross traffic."
        ),
        disciplines=("road",),
        notes=(
            "Closed for ice through much of the winter and after storms. There are "
            "tunnels on this stretch that need lights, and leaf-season traffic is "
            "heavy and slow."
        ),
        confidence="medium",
    ),
    Spot(
        slug="bent-creek-gap-road",
        name="Bent Creek Gap Road",
        city="Asheville",
        state="NC",
        bbox=(35.45044, -82.66476, 35.49214, -82.62475),
        osm_way_names=("Bent Creek Gap Road",),
        blurb=(
            "Forest Service gravel off the Parkway at Bent Creek Gap, dropping into the "
            "Bent Creek watershed above Lake Powhatan."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        notes=(
            "FS 479. Washboard and loose rock, with trailhead and hunting traffic on "
            "weekends. It ends where the pavement starts near Lake Powhatan."
        ),
        confidence="medium",
    ),
    Spot(
        slug="heartbreak-ridge",
        name="Heartbreak Ridge",
        city="Asheville",
        state="NC",
        bbox=(35.6621, -82.2618, 35.70168, -82.23573),
        osm_way_names=("Heartbreak Ridge",),
        blurb=(
            "Switchbacked Pisgah singletrack off the Blue Ridge Parkway toward Old "
            "Fort — steep, rooty and relentless from the first turn."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        notes=(
            "TR 208 is open to bikes and ridden downhill in practice. Exposed "
            "switchbacks, roots and loose rock; no water and no bail-out once you drop "
            "in. The separately named Lower Heartbreak Ridge is a different trail and "
            "is outside this box."
        ),
        confidence="medium",
    ),
    Spot(
        slug="bearwallow-mountain-road",
        name="Bearwallow Mountain Road",
        city="Asheville",
        state="NC",
        bbox=(35.42293, -82.38695, 35.48132, -82.34604),
        osm_way_names=("Bearwallow Mountain Road",),
        blurb=(
            "Off the Bearwallow bald above Gerton, gravel at the top giving way to "
            "pavement as it winds down toward Hickory Nut Gorge."
        ),
        disciplines=("gravel", "road"),
        rider_profile="gravel",
        notes=(
            "Mixed asphalt, gravel and unpaved over 11 km, so surface changes may split "
            "the descent into separate runs. Residential at the bottom end "
            "with driveways and blind entries."
        ),
        confidence="medium",
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
            "2.1 miles and 21 bends of car-free 1911 pavement — the most famous "
            "downhill skateboarding road in America."
        ),
        disciplines=("skate",),
        rider_profile="longboarder",
        notes=(
            "A private road owned by the Maryhill Museum. Skating it requires a paid, "
            "waivered event — you cannot just show up and bomb it."
        ),
        confidence="high",
    ),
    Spot(
        slug="dalles-mountain-road",
        name="Dalles Mountain Road",
        city="Columbia Gorge",
        state="WA",
        bbox=(45.64837, -121.1395, 45.71087, -120.95663),
        osm_way_names=("Dalles Mountain Road",),
        blurb=(
            "Gravel through the Dalles Mountain Ranch, dropping open Columbia Hills "
            "grassland to the river at Highway 14."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        max_road_rank=4,                         # unclassified
        notes=(
            "Mostly gravel with a paved lower section, through Columbia Hills State "
            "Park — a Discover Pass is required at the trailheads. No shade, and the "
            "Gorge wind here is strong enough to change which direction is the easy one."
        ),
        confidence="medium",
    ),
    Spot(
        slug="coyote-wall-syncline",
        name="Coyote Wall (The Syncline)",
        city="Columbia Gorge",
        state="WA",
        # Union of the four descent lines. Atwood Road, the climb, is deliberately
        # not listed — it would surface the way up as a route.
        bbox=(45.6988, -121.43699, 45.71915, -121.38661),
        osm_way_names=(
            "Coyote Wall Trail",
            "Coyote Cliffs Trail",
            "Labyrinth Trail",
            "Little Maui Trail",
        ),
        blurb=(
            "Off the top of the basalt syncline on Little Maui and through the "
            "Labyrinth, in the open oak and balsamroot above the river."
        ),
        disciplines=("mtb",),
        rider_profile="mtb",
        # Four named trails, ridden end to end, so the run cannot be pinned to the
        # one it starts on.
        toggles=Toggles(
            avoid_stoplights=False,
            avoid_stop_signs=False,
            avoid_bigger_roads=True,
            avoid_equal_roads=False,
            stay_on_initial_road=False,
        ),
        notes=(
            "Low elevation, so it rides in late winter and is the Gorge's spring "
            "destination — and it turns to unrideable mud when wet, which the land "
            "managers ask you to stay off. Poison oak and ticks in the oak sections."
        ),
        confidence="medium",
    ),
    Spot(
        slug="seven-mile-hill",
        name="Seven Mile Hill Road",
        city="Columbia Gorge",
        state="OR",
        bbox=(45.62791, -121.32406, 45.64603, -121.23415),
        osm_way_names=("Seven Mile Hill Road",),
        blurb=(
            "Off the wheat plateau west of The Dalles, a steady paved drop through "
            "the orchards to the Columbia."
        ),
        disciplines=("road",),
        notes=(
            "The standard road-bike climb out of The Dalles, so the descent is the "
            "way home. Exposed to the Gorge wind the entire way, and it carries "
            "farm traffic during cherry harvest."
        ),
        confidence="low",
    ),
    Spot(
        slug="courtney-road",
        name="Courtney Road",
        city="Columbia Gorge",
        state="WA",
        bbox=(45.69758, -121.44133, 45.73359, -121.40122),
        osm_way_names=("Courtney Road",),
        blurb=(
            "Above Lyle, mixed gravel and pavement off the cherry orchards, falling "
            "the full wall of the Gorge to the river."
        ),
        disciplines=("gravel",),
        rider_profile="gravel",
        max_road_rank=5,                         # tertiary
        notes=(
            "The access road for the Cherry Orchard trail, part paved and part loose "
            "gravel, with a couple of pitches steep enough to be a braking problem "
            "loaded. Private land either side — stay on the road."
        ),
        confidence="low",
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
