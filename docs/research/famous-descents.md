# Famous US Descents — research for Hillbomb Collections

**34 roads across 12 metro areas.** All OSM names, `highway` tags and bboxes verified against live
Overpass. Last updated 2026-07-16. Dirt descents are in the companion
[dirt-descents.md](dirt-descents.md).

> This file and its dirt companion cover the **original 94 spots**. The August 2026 pass
> that took the collection to 272 is written up separately in
> [expansion-2026-08.md](expansion-2026-08.md) — read that one for the OSM-name traps,
> the region-bbox limits, and the current state of the `ref`-only backlog item described
> below, which it confirms is still the biggest structural gap.

---

## Promotion status (2026-08-06)

Every entry below is now either in `backend/spots.py` or listed here with a reason. Two were
promoted out of the **Rejected** table after the constraint that blocked them changed or the
research question was answered:

| Entry | Outcome |
|---|---|
| **Mount Hamilton Road** | **Promoted.** Rejected only for spanning 0.19° of longitude against a per-axis 0.1° bbox cap. That guard is now area-based (`test_spots.test_bbox_is_tight`), and this road is a long thin corridor covering 0.0103°² — half the budget. It builds the longest route in the collection: 28.5 km, 1,652 m of descent. |
| **Council Crest** | **Promoted, re-scoped.** The name/reality mismatch called out below is real, and the fix was the one this table proposed: drop `Southwest Council Crest Drive` (the near-flat summit loop) and use `Southwest Greenway Avenue` / `Southwest Talbot Road` / `Southwest Fairmount Boulevard`. Builds a 1.67 km descent with 99 m of drop, against 36 m for the loop road. `confidence="low"` until someone who rides it confirms the line. |

Two are excluded for the same reason, which is worth stating as a rule: **a famous climb is not
automatically a hill bomb.** Hillbomb only traverses edges in their legal direction, so a road that
is one-way uphill, or closed to bicycles downhill, correctly yields nothing.

| Entry | Why it is not a spot |
|---|---|
| **Mount Washington Auto Road** | Descending by bicycle is **strictly prohibited** — racers are driven down. OSM agrees: `bicycle=no` on 8 of 17 ways. Verified and documented below, deliberately not shipped. |
| **Canton Avenue** | Its three steep ways are all **`oneway=yes` uphill** (`incline=34%`), so there is no legal descent. Attempting it shipped a 0 m / 0 km/h card built from the flat block at the top — the pipeline refusing correctly, not failing. |

### Two pipeline gaps this research keeps running into

**1. Hillbomb matches on `name`, but many state-route roads carry only `ref`.**
This is now the single most common reason a verified-famous descent cannot ship. All of
these exist in OSM, are rideable, and are unreachable because `osm_way_names` has nothing
to match:

| Descent | Tagged | Missing |
|---|---|---|
| Mount Mitchell, NC — highest peak east of the Mississippi | `ref=NC 128` | no `name` at all |
| Brasstown Bald, GA — Georgia's high point | `ref=GA 180 Spur` | no `name` at all |
| Mount Magazine, AR — Arkansas's high point | `ref=AR 309` | no `name` at all |
| Hyde Park Road upper half, NM — the ski-basin climb | `ref=NM 475` | no `name` on the top 9.8 km |

Three US state high points, lost to a tag we do not read. Letting a spot match on `ref`
as well as `name` — a small change in `build_collections._matches_spot` and
`pathfinding.build_route_from_data`, which would need to carry `ref` onto the edge the
way `way_name` already is — would unlock all four. This is the highest-value unblock in
the backlog.

**2. The pipeline reads no `bicycle=*` tag anywhere.** `grep -rn bicycle backend/*.py`
returns nothing outside `spots.py`. Mount Washington (`bicycle=no` on 8 of 17 ways) and
Pilot Rock Trail (`bicycle=no` on a 644 m segment *between* two `bicycle=yes` segments)
were both caught by research judgement, not by the code — nothing stops the pathfinder
routing down a way bikes are barred from. For an app whose whole output is "go ride down
this", that gap is worth closing: `access`/`bicycle` belong in `mark_traversable`
alongside surface and rank.

### A tag worth reading later

Canton Avenue carries **`incline=34%`** in OSM, against the 3.5% our 10 m DEM measures. Several
shipped spots have the same problem (Filbert, Baxter, Eldred, Bradford, Fargo, Rialto), and the
"What is estimated" section below treats it as an unavoidable limitation. It may not be: where OSM
carries an explicit `incline`, it is a better source for short steep streets than any DEM we can
sample. Not implemented — recorded because the fix is cheaper than the workaround.

---

## Method & confidence

### What was actually verified (hard data)

Every entry below had its **OSM way name, `highway` tag, `surface`/`oneway` tags, bbox, and length**
verified by querying the live **Overpass API** (`overpass-api.de`, data timestamp 2026-07-16), not by
guessing from the common name. The query pattern was:

```
[out:json];way["name"="<candidate name>"]["highway"](<region bbox>);out tags geom;
```

This means:

- **`osm_way_names` are exact.** If a name is listed, ways with that exact `name` tag exist in OSM at
  that location. Where the popular name is not the OSM name (Hawk Hill → `Conzelman Road`,
  the Counterbalance → `Queen Anne Avenue North`), the OSM name is what is recorded.
- **`bbox` is derived from real OSM node geometry** — it is the union bbox of the matched ways
  (optionally clipped to the famous segment, noted per-entry). No coordinate below is invented.
- **`highway_tag` is the real tag distribution**, including cases that will bite the default
  rideable-road set (see "Tag gotchas" below).
- **`length_km` is computed** by haversine over OSM geometry.

### What is estimated (softer data)

- **`descent_m` / `avg_grade_pct`** are computed from **USGS NED 10m** elevation
  (`opentopodata.org/v1/ned10m`) sampled every ~50 m along the OSM geometry. These are good to
  roughly ±5% on long climbs.
- **`max_grade_pct`** — ⚠️ **read this**. A 10 m DEM sampled over ~40 m windows *systematically
  smooths away short pitches*. Filbert Street measured **13.7%** from the DEM against a published
  **31.5%**. So:
  - For the **short steep streets**, `max_grade_pct` is the **published/surveyed** figure, cited in
    the blurb. The DEM value is not used.
  - For the **long mountain climbs**, `max_grade_pct` is the DEM-derived value and is a
    *lower bound* — real pitches are steeper.
  - This is a genuine limitation of the same 10 m data tier Hillbomb itself defaults to
    (`elevation_sample_interval_m = 10.0`), and it is worth knowing that Hillbomb will under-read
    grade on exactly these famous short streets unless 1 m lidar is available.
- **`descent_m` for a whole-road bbox is the road's full min→max relief**, which may exceed the
  descent of any single rideable line if the road has intermediate rises.

### Tag gotchas that matter for Hillbomb

Several marquee descents are **not `residential`/`tertiary`** and will be excluded or mis-ranked by a
default rideable set:

- `Dolores Street`, `Marin Avenue`, `Queen Anne Avenue North` → **`secondary`**
- `South Gate Road` / `Summit Road` (Mt Diablo), `Ridgecrest Boulevard`, `Maryhill Loops Road` → **`unclassified`**
- `Twin Peaks Boulevard` is a **mix** of `secondary`/`unclassified`/`tertiary`/`residential`, plus
  `construction`, `pedestrian` and `cycleway` ways (the north loop is closed to cars).
- `Baxter Street` and `Canton Avenue` carry `surface=concrete` / `surface=sett` respectively — both
  are penalized or excluded by surface filters.

### Rejected entries

| Candidate | Why rejected |
|---|---|
| **Lombard Street (crooked block), SF** | The famous block is one-way downhill at ~27% but is 8 hairpins over 180 m with a 5 mph limit, speed bumps, and constant tourist foot traffic. It is a landmark, not a rideable descent. OSM `Lombard Street` also spans `trunk` (US‑101) for most of its length, so a name match pulls in a highway. |
| ~~**Mount Hamilton Road, San Jose**~~ | ✅ **PROMOTED** — see Promotion status above. Verified in OSM (`highway=secondary`, 32.9 km), rejected here only for spanning 0.20° of longitude against the old per-axis 0.1° budget. The budget is now area-based and this fits inside it. |
| **Council Crest, Portland** | ⚠️ **Name/reality mismatch.** `Southwest Council Crest Drive` exists in OSM (`residential`+`tertiary`, 38 ways) but measures only **36 m of relief over 2.2 km (1.7% avg)** — it is just the *summit loop road*. The actual famous climb to Council Crest is ridden on `SW Greenway Avenue` / `SW Talbot Road` / `SW Fairmount Boulevard`, which are different OSM ways. Including "Council Crest Drive" would give users a flat loop. Needs re-scoping to the correct way names before it can ship. ✅ **PROMOTED** with exactly that re-scoping — see Promotion status above. |
| **Mount Tabor, Portland** | Not probed. The famous skate runs are on interior Mt Tabor Park roads whose OSM names I did not verify, and much of the park is closed to cars/has seasonal restrictions. Rather than guess a name, deferred. |
| **Signal Hill, Long Beach** | Not probed — I could not confidently identify which OSM-named street the historic speed runs used. Deferred rather than guessed. |
| **22nd Street, SF** | Tied with Filbert at a surveyed 31.5%, but `22nd Street` is an extremely common OSM name and the steep block is short; the Filbert entry already covers this exact "steepest in SF" claim. Skipped as redundant. |

---

## San Francisco Bay Area

### hawk-hill-conzelman
```yaml
slug: hawk-hill-conzelman
name: Hawk Hill (Conzelman Road)
city: San Francisco Bay Area
state: CA
osm_way_names: ["Conzelman Road"]
bbox: [37.82315, -122.52901, 37.83378, -122.48336]   # ~4.7 km2 (0.011 x 0.046 deg)
highway_tag: residential          # all 20 ways; surface=asphalt; oneway=yes on 17
descent_m: 196
length_km: 6.5
max_grade_pct: 18        # DEM-smoothed est 20.3 over the upper wall; ~18% published
avg_grade_pct: 3.0       # whole road incl. flat approach; the climb proper averages ~6-7%
discipline: cycling
blurb: >
  The single most photographed climb in the Bay Area — the Marin Headlands road up from the
  Golden Gate Bridge's north end to the Hawk Hill summit, with the bridge and city framed behind.
  A fixture of San Francisco Grand Prix-era racing and the standard Saturday effort for every SF club.
notes: >
  West of the summit Conzelman becomes ONE-WAY DOWNHILL (oneway=yes on 17 of 20 ways) — the
  descent toward Point Bonita is legally one-way, which is unusually favorable for this app.
  Tagged residential despite being a park road. One way is motor_vehicle=no + bicycle=designated.
confidence: high         # name, tags, bbox all from live Overpass
```

### old-la-honda
```yaml
slug: old-la-honda
name: Old La Honda Road
city: San Francisco Bay Area
state: CA
osm_way_names: ["Old La Honda Road"]
bbox: [37.35716, -122.26613, 37.39599, -122.24435]   # ~8.3 km2 (0.039 x 0.022 deg)
highway_tag: tertiary             # 4 tertiary + 1 residential; surface=asphalt; one bridge=yes
descent_m: 398
length_km: 9.3           # full road both sides of Skyline; the classic east side is ~5.6 km
max_grade_pct: 26        # DEM est 26.4 (lower bound)
avg_grade_pct: 4.3       # whole road; the timed east climb averages ~7.3%
discipline: cycling
blurb: >
  The Bay Area's benchmark climb and de facto fitness test: the 5.6 km east side from Portola Road
  to Skyline is the most-ridden timed segment on the Peninsula, with a sub-15-minute time the
  long-standing marker of a serious amateur.
notes: >
  bbox covers BOTH sides of Skyline (east side from Portola Rd, west side dropping to La Honda).
  Narrow, no centerline, damp and leaf-covered under redwoods much of the year — descent is
  technical rather than fast.
confidence: high
```

### mt-diablo-south-gate
```yaml
slug: mt-diablo-south-gate
name: Mount Diablo — South Gate Road
city: San Francisco Bay Area
state: CA
osm_way_names: ["South Gate Road"]
bbox: [37.84063, -121.94985, 37.86693, -121.92033]   # ~7.6 km2 (0.026 x 0.030 deg)
highway_tag: unclassified         # all 13 ways -- NOT in a default rideable set
descent_m: 437
length_km: 9.4
max_grade_pct: 26        # DEM est 25.7 (lower bound)
avg_grade_pct: 4.7
discipline: cycling
blurb: >
  The lower half of the Bay Area's premier mountain climb and the route of the Mt. Diablo Challenge,
  run every October since 1982 — the 17.7 km race from Athenian School to the summit where breaking
  one hour is the coveted benchmark (finishers earn the "under an hour" shirt).
notes: >
  State park road: entrance fee for cars, gates close at sunset. Tagged unclassified -- will be
  dropped by a rideable set that stops at residential/tertiary. Pairs with summit-road above it.
confidence: high
```

### mt-diablo-summit-road
```yaml
slug: mt-diablo-summit-road
name: Mount Diablo — Summit Road
city: San Francisco Bay Area
state: CA
osm_way_names: ["Summit Road"]
bbox: [37.86252, -121.93222, 37.88174, -121.91410]   # ~3.4 km2 (0.019 x 0.018 deg)
highway_tag: unclassified         # all 7 ways
descent_m: 505
length_km: 7.4
max_grade_pct: 21        # DEM est 21.1 (lower bound); final 100 m pitch is a published ~16-18%
avg_grade_pct: 6.8
discipline: cycling
blurb: >
  The upper mountain — from Junction Ranger Station to the 1,173 m summit, including the notorious
  final pitch to the observation tower that decides the Mt. Diablo Challenge every year.
notes: >
  "Summit Road" is a very common name nationally — this bbox is what disambiguates it. Verify any
  name-substring match stays inside the box. Unclassified tag; seasonal ice/closure near the top.
confidence: high
```

### marin-avenue-berkeley
```yaml
slug: marin-avenue-berkeley
name: Marin Avenue (Berkeley)
city: San Francisco Bay Area
state: CA
osm_way_names: ["Marin Avenue"]
bbox: [37.88774, -122.29267, 37.89841, -122.25982]   # ~3.4 km2 (0.011 x 0.033 deg)
highway_tag: secondary            # 21 of 25 ways secondary -- NOT residential
descent_m: 306
length_km: 3.45
max_grade_pct: 25        # published ~25% on the steepest blocks above Arlington; DEM est 23.7
avg_grade_pct: 8.9
discipline: both
blurb: >
  The steepest sustained paved street climb in the Bay Area — the arrow-straight wall from
  Arlington Avenue to Grizzly Peak Boulevard, pitching to ~25%, long used as the finale of the
  Berkeley Hills Road Race area rides and a rite of passage for East Bay cyclists.
notes: >
  Tagged secondary -- a default rideable set that excludes secondary will drop this entirely.
  Real traffic and cross streets with stop signs on the descent; steep enough that the downhill is
  genuinely brake-limited. Lower Marin Ave (west of Arlington) is flat and excluded by this bbox.
confidence: high
```

### twin-peaks-blvd
```yaml
slug: twin-peaks-blvd
name: Twin Peaks Boulevard
city: San Francisco Bay Area
state: CA
osm_way_names: ["Twin Peaks Boulevard"]
bbox: [37.74577, -122.45089, 37.76110, -122.44567]   # ~0.8 km2 (0.015 x 0.005 deg)
highway_tag: mixed                # secondary(3) + unclassified(6) + tertiary(3) + residential(4)
                                  # plus construction(3), pedestrian(2), cycleway(1)
descent_m: 111
length_km: 2.65
max_grade_pct: 12        # DEM est 6.0 -- badly smoothed; real pitches are steeper
avg_grade_pct: 4.2
discipline: both
blurb: >
  San Francisco's signature summit road and one of the city's classic skate bombs — the switchbacked
  drop from the 280 m Twin Peaks overlook into the Castro, with the whole city laid out ahead.
notes: >
  ⚠️ The north/upper loop was closed to private cars (Twin Peaks Promenade) and OSM reflects this
  with construction/pedestrian/cycleway ways — car-free but legality for skating is unclear.
  Highly mixed tagging: any rideable filter will fragment this road. Fog and wind are constant.
confidence: high         # tags/bbox verified; note the mixed tagging is real, not an error
```

### dolores-street
```yaml
slug: dolores-street
name: Dolores Street
city: San Francisco Bay Area
state: CA
osm_way_names: ["Dolores Street"]
bbox: [37.74040, -122.42602, 37.75992, -122.42396]   # ~0.4 km2 (0.020 x 0.002 deg)
highway_tag: secondary            # all matched ways secondary; oneway=yes (divided boulevard)
descent_m: 47
length_km: 4.3           # both carriageways summed; each direction ~2.1 km
max_grade_pct: 12.5      # DEM est; the 21st-22nd St block is the steep one
avg_grade_pct: 1.1       # whole street -- misleading, the bomb is the top few blocks
discipline: skate
blurb: >
  The most famous street skate bomb in San Francisco — the palm-lined drop from Dolores Heights
  through the Mission, immortalized by the annual (unsanctioned) Dolores Park hill bombs that draw
  hundreds of skaters and have become a recurring flashpoint with SFPD.
notes: >
  ⚠️ Legally fraught: SFPD has repeatedly cracked down on the Dolores bombs (mass citations and
  arrests in 2023). Tagged secondary and oneway=yes per carriageway — it's a divided boulevard, so
  the two directions are separate ways. Real traffic, stop signs, and Muni.
  avg_grade over the full street is misleading; the rideable bomb is the north end.
confidence: high         # OSM data verified; grade figures are DEM-smoothed
```

### filbert-street-sf
```yaml
slug: filbert-street-sf
name: Filbert Street (Russian Hill)
city: San Francisco Bay Area
state: CA
osm_way_names: ["Filbert Street"]
bbox: [37.80010, -122.41938, 37.80057, -122.41583]   # ~0.02 km2 (0.0005 x 0.004 deg) -- one block
highway_tag: residential          # 4 ways in the clipped block
descent_m: 46
length_km: 0.32          # the Hyde-to-Leavenworth steep block
max_grade_pct: 31.5      # PUBLISHED/surveyed. DEM read only 13.7% -- do not trust DEM here.
avg_grade_pct: 14.6
discipline: skate
blurb: >
  Tied with 22nd Street as the steepest street in San Francisco at a surveyed 31.5% — the
  Hyde-to-Leavenworth block on Russian Hill, steep enough that the city paved it in concrete
  with traction ridges and the sidewalks become staircases.
notes: >
  bbox is CLIPPED to the single steep block; "Filbert Street" continues flat for kilometres either
  side, so a name-only match without this bbox is wrong. Concrete with transverse ridges — rough
  and grabby on urethane. This is a short, extreme block, not a sustained run.
confidence: high         # bbox clipped and verified; max_grade is published not measured
```

### bradford-street-sf
```yaml
slug: bradford-street-sf
name: Bradford Street (Bernal Heights)
city: San Francisco Bay Area
state: CA
osm_way_names: ["Bradford Street"]
bbox: [37.73688, -122.40977, 37.74323, -122.40937]   # ~0.03 km2 (0.006 x 0.0004 deg)
highway_tag: residential          # 4 residential + 2 tertiary; surface=concrete on the steep way
descent_m: 64
length_km: 0.58
max_grade_pct: 41        # PUBLISHED claim for the dead-end pitch above Tompkins. DEM est 18.6.
avg_grade_pct: 11.0
discipline: skate
blurb: >
  Widely cited as the steepest street in San Francisco — and arguably the US — at a claimed 41% on
  the short dead-end pitch above Tompkins Avenue on the north face of Bernal Heights.
notes: >
  ⚠️ The 41% figure applies only to a very short dead-end stub, not the whole street, and is a claim
  rather than an official survey (unlike Filbert/22nd's surveyed 31.5%). Concrete surface.
  Dead-end: it does not connect through, so it is a stunt pitch, not a run-out descent.
confidence: medium       # OSM name/bbox high confidence; the 41% grade claim is disputed
```

### page-mill-road
```yaml
slug: page-mill-road
name: Page Mill Road (upper)
city: San Francisco Bay Area
state: CA
osm_way_names: ["Page Mill Road"]
bbox: [37.31489, -122.18931, 37.38948, -122.16197]   # ~19.9 km2 (0.075 x 0.027 deg) -- large
highway_tag: tertiary             # clipped to the tertiary section only
descent_m: 616
length_km: 14.1
max_grade_pct: 20        # DEM est 20.3 (lower bound)
avg_grade_pct: 4.4
discipline: cycling
blurb: >
  One of the Peninsula's great sustained climbs, rising from Palo Alto to Skyline Boulevard past
  Foothills Park — a Silicon Valley classic and the standard long effort paired with Old La Honda.
notes: >
  ⚠️ bbox CLIPPED to the tertiary upper section. The full OSM "Page Mill Road" also spans
  highway=trunk and highway=primary (the Page Mill Expressway down by I-280) — a name-only match
  will pull in an expressway. Must use both the name AND highway=tertiary AND this bbox.
  Still a large box (~20 km2) — expect a heavy Overpass fetch.
confidence: medium       # name/tag verified; bbox is large and clipped by hand
```

### sierra-road-san-jose
```yaml
slug: sierra-road-san-jose
name: Sierra Road
city: San Francisco Bay Area
state: CA
osm_way_names: ["Sierra Road"]
bbox: [37.39519, -121.85702, 37.41461, -121.80009]   # ~10.8 km2 (0.019 x 0.057 deg)
highway_tag: tertiary             # clipped section is all tertiary (full road also has secondary)
descent_m: 570
length_km: 7.1
max_grade_pct: 15        # DEM est 15.4 (lower bound)
avg_grade_pct: 8.0
discipline: cycling
blurb: >
  The decisive climb of the Amgen Tour of California — the brutally exposed wall above East San Jose
  that shattered the peloton on multiple editions and remains the Bay Area's hardest big climb.
notes: >
  bbox CLIPPED to the famous climb (from near Piedmont Rd east); the full OSM "Sierra Road"
  continues east to Felter Road and includes highway=secondary ways at its west end.
  No shade, no water, and a fast open descent.
confidence: medium       # name/tags verified; bbox clipped by hand to the climb
```

### mt-tam-ridgecrest
```yaml
slug: mt-tam-ridgecrest
name: Mount Tamalpais — Ridgecrest Boulevard
city: San Francisco Bay Area
state: CA
osm_way_names: ["Ridgecrest Boulevard"]
bbox: [37.90905, -122.65837, 37.93937, -122.61258]   # ~13.6 km2 (0.030 x 0.046 deg)
highway_tag: unclassified         # all 3 ways
descent_m: 172
length_km: 6.2
max_grade_pct: 13        # DEM est 13.2
avg_grade_pct: 2.8
discipline: cycling
blurb: >
  The ridge road along Mt. Tamalpais to the East Peak — the mountain where mountain biking was
  invented (the Repack downhill runs nearby) and the most scenic paved descent in Marin.
notes: >
  Tagged unclassified. Ridgecrest is the RIDGE road (rolling, low avg grade) — it is not the
  climb itself; the big elevation is gained on Panoramic Highway / Fairfax-Bolinas Rd below it.
  Gated seasonally and in fire weather. Fog.
confidence: high         # name/tags/bbox verified; note this is a ridge, not a big descent
```

---

## Los Angeles

### baxter-street
```yaml
slug: baxter-street
name: Baxter Street (Echo Park)
city: Los Angeles
state: CA
osm_way_names: ["Baxter Street"]
bbox: [34.08821, -118.26230, 34.09464, -118.24720]   # ~0.9 km2 (0.006 x 0.015 deg)
highway_tag: residential          # 11 residential (+1 footway); surface=concrete on 6 ways
descent_m: 58
length_km: 1.6
max_grade_pct: 32        # PUBLISHED/surveyed ~32%
avg_grade_pct: 3.6
discipline: skate
blurb: >
  One of the steepest streets in the United States at ~32%, and famous well beyond cycling: the
  blind crest became a viral Waze-routing disaster, with cars bottoming out and crashing so often
  that LA closed it to through traffic and installed restrictions in 2019.
notes: >
  ⚠️ surface=concrete on the steep blocks. Through traffic restricted since 2019. The crest is
  genuinely blind — cars cannot see over it, which is exactly why it is dangerous to bomb.
confidence: high         # OSM name/tag/bbox verified
```

### eldred-street
```yaml
slug: eldred-street
name: Eldred Street (Highland Park)
city: Los Angeles
state: CA
osm_way_names: ["Eldred Street"]
bbox: [34.10773, -118.20991, 34.10977, -118.20563]   # ~0.08 km2 (0.002 x 0.004 deg)
highway_tag: residential          # 1 residential way (+1 steps way, excluded)
descent_m: 36
length_km: 0.46
max_grade_pct: 33        # PUBLISHED ~33%
avg_grade_pct: 9.4
discipline: skate
blurb: >
  Frequently ranked the steepest street in Los Angeles at ~33% — so steep that it dead-ends in a
  staircase, garbage trucks refuse to drive it, and the city uses a special small vehicle to serve it.
notes: >
  ⚠️ Dead-end street ending in stairs (OSM has a highway=steps way with the same name — filter it
  out). Very short. Residential and narrow; no run-out.
confidence: high
```

### fargo-street
```yaml
slug: fargo-street
name: Fargo Street (Echo Park)
city: Los Angeles
state: CA
osm_way_names: ["Fargo Street"]
bbox: [34.08889, -118.26285, 34.09373, -118.25002]   # ~0.6 km2 (0.005 x 0.013 deg)
highway_tag: residential          # 5 residential (+1 steps); surface=concrete
descent_m: 50
length_km: 0.88
max_grade_pct: 32        # PUBLISHED ~32-33%
avg_grade_pct: 6.1
discipline: cycling
blurb: >
  Home of the Fargo Street Hill Climb, run by the Los Angeles Wheelmen every year since 1974 — the
  oldest and best-known "can you even ride up it" event in American cycling, on a ~32% pitch where
  most entrants fail.
notes: >
  Adjacent to Baxter Street (same Echo Park hill). Concrete. One OSM way is access=no.
  Includes a highway=steps way with the same name — filter it out.
confidence: high
```

### glendora-mountain-road
```yaml
slug: glendora-mountain-road
name: Glendora Mountain Road
city: Los Angeles
state: CA
osm_way_names: ["Glendora Mountain Road"]
bbox: [34.14162, -117.84977, 34.22984, -117.77195]   # ~60 km2 (0.088 x 0.078 deg) -- LARGE
highway_tag: tertiary             # 2 tertiary + 1 residential; bicycle=yes
descent_m: 763
length_km: 24.1
max_grade_pct: 19.9      # DEM-derived, LOWER BOUND (10m DEM smooths pitches)
avg_grade_pct: 3.2
discipline: cycling
blurb: >
  "GMR" — the most ridden mountain road in Southern California and the training ground for
  generations of LA racers, a 24 km ribbon of near-constant gradient above Glendora with an
  immaculate surface and a legendary descent.
notes: >
  ⚠️ bbox is ~60 km2 — at the edge of usable. The road is inherently 24 km long; consider splitting
  into lower (Glendora to GRR junction) and upper sections. Subject to fire and storm closures;
  has been closed for years at a time. Motorcycle traffic is heavy on weekends.
confidence: medium       # name/tag/bbox verified; bbox is large by necessity
```

### latigo-canyon
```yaml
slug: latigo-canyon
name: Latigo Canyon Road
city: Los Angeles
state: CA
osm_way_names: ["Latigo Canyon Road"]
bbox: [34.02997, -118.81544, 34.09214, -118.75350]   # ~38 km2 (0.062 x 0.062 deg)
highway_tag: tertiary             # all 3 ways
descent_m: 612
length_km: 16.5
max_grade_pct: 14.2      # DEM-derived, LOWER BOUND (10m DEM smooths pitches)
avg_grade_pct: 3.7
discipline: cycling
blurb: >
  The best-known climb in the Santa Monica Mountains — 16 km of switchbacks from Pacific Coast
  Highway to the ridge, a staple of Malibu gran fondos and the descent that defines Malibu road riding.
notes: >
  bbox ~38 km2. Tertiary, well-surfaced. Descent to PCH is fast and open with long sightlines.
confidence: medium       # name/tag/bbox verified; elevation pending
```

### tuna-canyon
```yaml
slug: tuna-canyon
name: Tuna Canyon Road
city: Los Angeles
state: CA
osm_way_names: ["Tuna Canyon Road"]
bbox: [34.03946, -118.61767, 34.07738, -118.58832]   # ~14 km2 (0.038 x 0.029 deg)
highway_tag: tertiary             # all 7 ways
descent_m: 553
length_km: 9.0
max_grade_pct: 18        # published "up to 18%"
avg_grade_pct: 6.2
discipline: both
blurb: >
  ~70 turns in 4 miles dropping to the Pacific — and, crucially, most of it is legally ONE-WAY
  DOWNHILL (a legacy of an old mudslide), so a rider has the whole road with no oncoming traffic.
  One of the most sought-after descents in California for both cyclists and longboarders.
notes: >
  ⚠️ The one-way-downhill status is the whole point of this road, but OSM tagging is inconsistent:
  only 1 of 7 ways carries oneway=yes and another is explicitly oneway=no. VERIFY the oneway
  tagging before relying on it — OSM may not reflect the signed restriction.
  Narrow, no guardrail, blind turns.
confidence: medium       # name/tag/bbox high; the oneway tagging is a real discrepancy
```

### piuma-road
```yaml
slug: piuma-road
name: Piuma Road
city: Los Angeles
state: CA
osm_way_names: ["Piuma Road"]
bbox: [34.06501, -118.70455, 34.08219, -118.65343]   # ~8.6 km2 (0.017 x 0.051 deg)
highway_tag: tertiary             # all 5 ways; one bridge=yes
descent_m: 530
length_km: 10.4
max_grade_pct: 10.3      # DEM-derived, LOWER BOUND (10m DEM smooths pitches)
avg_grade_pct: 5.1
discipline: cycling
blurb: >
  A Santa Monica Mountains classic climbed from Malibu Canyon, and one of the most consistently
  used race-simulation climbs for LA-area cyclists.
notes: >
  Tertiary. Pairs with Stunt Road on the standard Malibu loop.
confidence: medium       # name/tag/bbox verified; elevation pending
```

### stunt-road
```yaml
slug: stunt-road
name: Stunt Road
city: Los Angeles
state: CA
osm_way_names: ["Stunt Road"]
bbox: [34.08041, -118.66502, 34.10193, -118.64574]   # ~4.1 km2 (0.022 x 0.019 deg)
highway_tag: tertiary             # all 4 ways
descent_m: 408
length_km: 6.4
max_grade_pct: 10.1      # DEM-derived, LOWER BOUND (10m DEM smooths pitches)
avg_grade_pct: 6.4
discipline: cycling
blurb: >
  One of the definitive Santa Monica Mountains climbs/descents, running from Mulholland Highway to
  Saddle Peak — a standard fixture of Malibu loops and a well-known motorcycle and cycling road.
notes: >
  Tertiary, good surface, technical descent.
confidence: medium       # name/tag/bbox verified; elevation pending
```

---

## Seattle

### queen-anne-counterbalance
```yaml
slug: queen-anne-counterbalance
name: Queen Anne Avenue North (the Counterbalance)
city: Seattle
state: WA
osm_way_names: ["Queen Anne Avenue North"]
bbox: [47.61859, -122.35770, 47.65041, -122.35661]   # ~1.0 km2 (0.032 x 0.001 deg)
highway_tag: secondary            # 24 secondary + 11 residential -- NOT residential-only
descent_m: 116
length_km: 3.5
max_grade_pct: 18        # published ~18-20% on the Counterbalance blocks
avg_grade_pct: 3.3
discipline: skate
blurb: >
  "The Counterbalance" — named for the underground 16-ton counterweights that hauled streetcars up
  this ~18% grade from 1900 to 1940; the tunnels are still under the street. Seattle's most storied
  hill and a long-standing urban bomb.
notes: >
  Tagged secondary for most of its length — a residential-only rideable set will miss it entirely.
  Busy arterial with signals at Mercer and Roy; real traffic. bbox is a narrow N-S strip.
confidence: high         # name/tags/bbox verified via Overpass
```

---

## Denver / Boulder

### lookout-mountain-road
```yaml
slug: lookout-mountain-road
name: Lookout Mountain Road
city: Denver / Golden
state: CO
osm_way_names: ["Lookout Mountain Road"]
bbox: [39.71607, -105.25377, 39.74941, -105.22751]   # ~8.6 km2 (0.033 x 0.026 deg)
highway_tag: tertiary             # all 21 ways; surface=asphalt; oneway=no; bicycle=designated on 5
descent_m: 459
length_km: 9.9
max_grade_pct: 9.0      # DEM-derived, LOWER BOUND (10m DEM smooths pitches)
avg_grade_pct: 4.6
discipline: cycling
blurb: >
  Colorado's most-ridden climb — the switchbacks out of Golden past Buffalo Bill's grave, used by
  the Coors Classic and the USA Pro Challenge, and the daily proving ground for the Front Range.
notes: >
  Tertiary with bicycle=designated on several ways — genuinely bike-friendly. Wide shoulders.
  The descent back into Golden is fast, open and well-sighted.
confidence: high         # name/tags/bbox verified
```

### flagstaff-road
```yaml
slug: flagstaff-road
name: Flagstaff Road (Flagstaff Mountain)
city: Boulder
state: CO
osm_way_names: ["Flagstaff Road"]
bbox: [39.98003, -105.33248, 40.00695, -105.28072]   # ~14 km2 (0.027 x 0.052 deg)
highway_tag: tertiary             # 4 tertiary + 2 service; surface=asphalt; oneway=no
descent_m: 625
length_km: 8.6
max_grade_pct: 13.9      # DEM-derived, LOWER BOUND (10m DEM smooths pitches)
avg_grade_pct: 7.3
discipline: cycling
blurb: >
  Boulder's iconic climb, rising straight out of Chautauqua Park — a regular USA Pro Challenge
  summit finish and the single most famous training climb in American cycling, ridden by decades
  of pros based in Boulder.
notes: >
  Tertiary + 2 service ways. Steep, tight switchbacks low down; the descent is technical.
  bbox ~14 km2.
confidence: high         # name/tags/bbox verified
```

---

## Washington (Columbia Gorge)

### maryhill-loops
```yaml
slug: maryhill-loops
name: Maryhill Loops Road
city: Goldendale (Columbia Gorge)
state: WA
osm_way_names: ["Maryhill Loops Road"]
bbox: [45.70455, -120.80931, 45.72557, -120.79283]   # ~3.4 km2 (0.021 x 0.016 deg)
highway_tag: unclassified         # 1 unclassified + 1 service; motor_vehicle=permissive; bicycle=permissive
descent_m: 199
length_km: 4.5
max_grade_pct: 16.0      # DEM-derived, LOWER BOUND (10m DEM smooths pitches)
avg_grade_pct: 4.5
discipline: skate
blurb: >
  The most famous downhill skateboarding road in America. Built in 1911 as Washington's first
  asphalt road by Sam Hill, it is now owned by the Maryhill Museum of Art, closed to cars ~90% of
  the year, and rented to longboard clubs — 2.1 miles and 21 bends of pristine, traffic-free
  pavement that hosts the Maryhill Ratz freerides and has hosted world-championship-level racing.
notes: >
  ⚠️ PRIVATE ROAD owned by the Maryhill Museum. Closed to motor vehicles; open to pedestrians and
  bikes when not rented. Skating requires a paid, waivered event — you cannot just show up and bomb it.
  Tagged motor_vehicle=permissive / bicycle=permissive, which correctly reflects the access regime.
confidence: high         # name/tags/bbox verified; access facts from Wikipedia + Maryhill Museum
```

---

## Portland

### rocky-butte
```yaml
slug: rocky-butte
name: Northeast Rocky Butte Road
city: Portland
state: OR
osm_way_names: ["Northeast Rocky Butte Road"]
bbox: [45.54058, -122.56900, 45.55212, -122.56301]   # ~0.7 km2 (0.012 x 0.006 deg)
highway_tag: tertiary             # 7 tertiary + 3 residential; bicycle=designated on ALL 10 ways
descent_m: 107
length_km: 4.0
max_grade_pct: 11.3      # DEM-derived, lower bound
avg_grade_pct: 2.7
discipline: both
blurb: >
  Portland's in-city climb — a spiral road up an extinct cinder cone to a WPA-era stone castle
  lookout, with a hand-cut stone tunnel partway up. The closest thing Portland has to a real
  hill inside the city, and a long-standing local hillclimb and skate spot.
notes: >
  ⚠️ Contains tunnel=yes — will be dropped entirely if the exclude_tunnels toggle is on, which
  would sever the route. bicycle=designated on every way. One way is motor_vehicle=permissive.
  Portland OSM uses FULL directional names ("Northeast ..."), not "NE ..." — match accordingly.
confidence: high         # name/tags/bbox verified via Overpass
```

---

## Pittsburgh

### canton-avenue
```yaml
slug: canton-avenue
name: Canton Avenue
city: Pittsburgh
state: PA
osm_way_names: ["Canton Avenue"]
bbox: [40.40909, -80.03013, 40.41050, -80.03001]   # ~0.02 km2 (0.0014 x 0.0001 deg) -- tiny
highway_tag: residential          # 5 ways; surface=paving_stones on the steep block
descent_m: 20
length_km: 0.16
max_grade_pct: 37        # PUBLISHED. ⚠️ DEM read only 3.5% -- completely useless at this scale.
avg_grade_pct: 12.8      # DEM over the matched 160 m; published avg for the pitch is ~30%
discipline: skate
blurb: >
  The steepest officially recorded public street in the United States — a claimed 37% over a 21 ft
  section of cobblestone in Beechview, disputed with Dunedin's Baldwin Street for the world record.
  The centerpiece of Pittsburgh's Dirty Dozen race, which since 1983 has sent riders up the city's
  thirteen steepest hills; most cannot clean Canton.
notes: >
  ⚠️ COBBLED (surface=paving_stones) — the flow-score cobble penalty should fire hard here, and it
  is genuinely dangerous to skate. 160 m long: this is a stunt pitch, not a descent.
  ⚠️ Our DEM measured 3.5% max grade vs 37% published — a 10x error. Do not trust computed grade on
  this entry; it is the clearest demonstration of the 10 m DEM limitation in this report.
confidence: high         # OSM name/tags/bbox verified; grade is published, NOT measured
```

### rialto-street
```yaml
slug: rialto-street
name: Rialto Street ("Pig Hill")
city: Pittsburgh
state: PA
osm_way_names: ["Rialto Street"]
bbox: [40.46483, -79.98298, 40.46730, -79.97978]   # ~0.08 km2 (0.003 x 0.003 deg)
highway_tag: tertiary             # 5 tertiary + 1 secondary; surface asphalt/concrete
descent_m: 45
length_km: 0.4
max_grade_pct: 24        # PUBLISHED ~24%. DEM read 3.2% -- again useless at this scale.
avg_grade_pct: 11.2
discipline: cycling
blurb: >
  "Pig Hill" — the ~24% wall up from Rialto Street to Troy Hill, so named because it was the route
  pigs were driven to the slaughterhouse at the top. A fixture of Pittsburgh's Dirty Dozen race.
notes: >
  Short. Tagged tertiary (one way secondary) despite being a wall. Drops straight toward
  Route 28 at the bottom — the run-out is onto a busy road, so the bottom is the hazard.
  ⚠️ DEM grade is unusable (3.2% measured vs ~24% real); max_grade is published.
confidence: high         # name/tags/bbox verified; grade published not measured
```

---

## Salt Lake City

### emigration-canyon
```yaml
slug: emigration-canyon
name: Emigration Canyon Road
city: Salt Lake City
state: UT
osm_way_names: ["Emigration Canyon Road"]
bbox: [40.75759, -111.78976, 40.78654, -111.70001]   # ~25 km2 (0.029 x 0.090 deg) -- clipped
highway_tag: secondary            # all ways secondary; bicycle=designated on 11; one bridge=yes
descent_m: 338
length_km: 12.7
max_grade_pct: 18.4      # DEM-derived, lower bound
avg_grade_pct: 2.7
discipline: cycling
blurb: >
  Salt Lake City's most-ridden road, climbing the canyon the Mormon pioneers descended into the
  valley in 1847 — a steady, low-gradient canyon road to Little Mountain Summit that serves as the
  daily after-work ride for the entire Wasatch Front cycling scene.
notes: >
  ⚠️ Tagged secondary — excluded by a residential/tertiary-only rideable set, despite
  bicycle=designated on most ways. bbox CLIPPED at the west end (the full road runs 0.111 deg of
  longitude, over the 0.1 budget). Low average gradient — a fast, open descent, not a steep one.
confidence: medium       # name/tags verified; bbox clipped by hand to fit the 0.1 deg budget
```

---

## Honolulu

### tantalus-drive
```yaml
slug: tantalus-drive
name: Tantalus Drive
city: Honolulu
state: HI
osm_way_names: ["Tantalus Drive"]
bbox: [21.31530, -157.84075, 21.33175, -157.81390]   # ~4.3 km2 (0.016 x 0.027 deg)
highway_tag: tertiary             # both ways tertiary
descent_m: 401
length_km: 7.0
max_grade_pct: 30.8      # DEM-derived -- unusually high for a DEM read, so real pitches are steeper
avg_grade_pct: 5.7
discipline: cycling
blurb: >
  The western half of the Tantalus–Round Top loop, the definitive Oahu climb: a hairpinned road up
  an extinct cinder cone through rainforest and banyan tunnels above Honolulu, and the venue for the
  Tantalus Time Trial hosted by the Tradewind Cycling Team.
notes: >
  Pairs with Round Top Drive as a one-way loop (up one, down the other) — they are separate OSM
  names for the two sides of the same circuit. Wet, mossy pavement under rainforest canopy is the
  main hazard; the descent is slick more often than not. No surface tag in OSM.
confidence: high         # name/tags/bbox verified via Overpass
```

### round-top-drive
```yaml
slug: round-top-drive
name: Round Top Drive
city: Honolulu
state: HI
osm_way_names: ["Round Top Drive"]
bbox: [21.30843, -157.83038, 21.33108, -157.81237]   # ~4.0 km2 (0.023 x 0.018 deg)
highway_tag: tertiary             # all 5 ways tertiary
descent_m: 436
length_km: 7.9
max_grade_pct: 27.4      # DEM-derived, lower bound
avg_grade_pct: 5.5
discipline: cycling
blurb: >
  The eastern half of the Tantalus–Round Top loop, dropping ~436 m from the Puu Ualakaa lookout to
  Makiki with panoramic views over Diamond Head and Waikiki — the most scenic descent on Oahu.
notes: >
  The natural descent side of the loop (most riders climb Tantalus and descend Round Top).
  Same wet-pavement hazard. No surface tag in OSM.
confidence: high
```

---

## Austin

### mount-bonnell-road
```yaml
slug: mount-bonnell-road
name: Mount Bonnell Road
city: Austin
state: TX
osm_way_names: ["Mount Bonnell Road"]
bbox: [30.31315, -97.77894, 30.34125, -97.77160]   # ~2.0 km2 (0.028 x 0.007 deg)
highway_tag: tertiary             # all 5 ways; surface=asphalt; 2 bridge=yes
descent_m: 65
length_km: 3.7
max_grade_pct: 18.9      # DEM-derived, lower bound
avg_grade_pct: 1.8
discipline: cycling
blurb: >
  Austin's best-known hill — the road along the ridge to Mount Bonnell, the highest point in the
  city and its oldest tourist attraction, and the standard pitch on every westside Austin ride.
notes: >
  ⚠️ Modest by any national standard — 65 m of relief. Included because Austin genuinely has no
  bigger paved hill, and it is the local benchmark. Low avg grade (1.8%) over the full road.
  Contains 2 bridge=yes ways (treated as straight-line segments by the graph builder).
confidence: high         # name/tags/bbox verified; the hill is real but small
```

---

## Asheville

### town-mountain-road
```yaml
slug: town-mountain-road
name: Town Mountain Road
city: Asheville
state: NC
osm_way_names: ["Town Mountain Road"]
bbox: [35.60051, -82.54287, 35.64803, -82.49097]   # ~24 km2 (0.048 x 0.052 deg)
highway_tag: secondary            # all 5 ways; surface=asphalt
descent_m: 355
length_km: 9.8
max_grade_pct: 11.6      # DEM-derived, lower bound
avg_grade_pct: 3.6
discipline: cycling
blurb: >
  Asheville's signature climb, rising from downtown to the Blue Ridge Parkway — the standard
  gateway ride for a city that has become one of the biggest pro cycling training bases in the
  eastern US.
notes: >
  ⚠️ Tagged secondary — will be excluded by a residential/tertiary-only rideable set. Real traffic.
  bbox ~24 km2.
confidence: high         # name/tags/bbox verified via Overpass
```

---

## New England

### mount-washington-auto-road
```yaml
slug: mount-washington-auto-road
name: Mount Washington Auto Road
city: Mount Washington (North Conway)
state: NH
osm_way_names: ["Mount Washington Auto Road"]
bbox: [44.26963, -71.30311, 44.29621, -71.22489]   # ~20 km2 (0.027 x 0.078 deg)
highway_tag: unclassified         # 16 unclassified + 1 service; bicycle=no on 8 ways(!);
                                  # motor_vehicle=private on 1; 2 bridge=yes; surface=asphalt(16)+metal(1)
descent_m: 1427          # DEM-measured; matches the published 4,725 ft almost exactly
length_km: 12.5
max_grade_pct: 20.0      # DEM-derived, lower bound; published max is ~22% near the top
avg_grade_pct: 11.4      # DEM-measured; matches the published ~12% -- strong validation
discipline: cycling
blurb: >
  The hardest hillclimb in North America and the most famous: 12.5 km at ~12% average gaining
  1,427 m, venue of the Mount Washington Auto Road Bicycle Hillclimb and Newton's Revenge, finishing
  with the infamous 22% ramp at the summit, on a mountain that holds one of the highest surface wind
  speeds ever recorded.
notes: >
  ⚠️⚠️ **DESCENDING BY BICYCLE IS STRICTLY PROHIBITED.** Racers must arrange a car ride down; the
  road closes to uphill traffic at 8am on race day and support drivers descend around noon. OSM
  reflects the restriction: bicycle=no on 8 of 17 ways, motor_vehicle=private on one.
  ⚠️ This is a **climb-only** entry. For a *downhill* app it is famous-but-unrideable, and should
  either be excluded or shown with a hard "no descending" warning. It is a PRIVATE toll road.
  One way is surface=metal (a bridge deck).
  This entry validated the whole elevation pipeline: computed 1427 m / 11.4% vs published
  4,725 ft / ~12%.
confidence: high         # name/tags/bbox verified; descent prohibition confirmed via MWARBH race info
```

### summit-avenue-corey-hill
```yaml
slug: summit-avenue-corey-hill
name: Summit Avenue (Corey Hill)
city: Boston / Brookline
state: MA
osm_way_names: ["Summit Avenue"]
bbox: [42.34111, -71.14126, 42.34587, -71.12562]   # ~0.7 km2 (0.005 x 0.016 deg)
highway_tag: tertiary             # all 5 ways; surface=asphalt; 2 oneway=yes
descent_m: 58
length_km: 1.45
max_grade_pct: 13.1      # DEM-derived, lower bound; published pitches ~17%
avg_grade_pct: 4.0
discipline: cycling
blurb: >
  Corey Hill — the steepest paved climb inside Boston's inner suburbs at ~17%, a long-time fixture
  of Boston-area racing and the local benchmark wall in a famously flat region.
notes: >
  ⚠️ "Summit Avenue" is a very common OSM name — this bbox is doing all the disambiguation work.
  Dense residential with cross streets and stop signs on the descent; short.
  2 of 5 ways are oneway=yes — check direction before assuming a full-length descent is legal.
confidence: medium       # name/tags/bbox verified, but the generic name makes matching risky
```
