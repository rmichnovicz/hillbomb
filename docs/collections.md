# Collections — curated famous descents

**Status: in progress.** Read this before touching the Collections feature.

Collections are a curated set of famous descents (Hawk Hill, Lookout Mountain,
Canton Ave …) grouped by city, precomputed offline by a build script and served as
static JSON. They are the answer to "the app is useless until I pan to a good hill" —
a new user opens the Collections tab and immediately has world-class routes to look at.

---

## Why precomputed, not live

Running a live search for a famous spot would take ~15 s (Overpass 7 s + elevation 3 s +
graph 4 s) and hammer Overpass for a result that never changes. Roads don't move. So we
run the real pipeline once, offline, and commit the output.

The build script uses **the same pipeline code as `POST /search`** — not a
reimplementation. That is the whole point of `backend/pipeline.py` (see below). A curated
route and a searched route are byte-identical in shape, so every frontend component
(map layer, profile chart, sparkline, GPX export) works on both with zero special-casing.

---

## Architecture

```
backend/spots.py                     # curated Spot definitions (the proposals, in code)
backend/pipeline.py                  # shared pipeline core — used by BOTH main.py and the build script
backend/scripts/build_collections.py # offline builder: Spot -> routes -> JSON
backend/data/collections.json        # build output; COMMITTED to the repo
backend/scripts/export_static_collections.py  # collections.json -> flat files for the CDN
backend/scripts/scout_ways.py        # research: verify a spot's osm_way_names + bbox, offline
GET /collections/index.json          # index (computed); dev + docker + fallback
GET /collections/{slug}.json         # one spot, verbatim from collections.json
frontend/src/components/Collections/ # the Collections tab
```

**In production those two URLs are files, not endpoints.** The deploy exports
`collections.json` into `frontend/dist/collections/` and Cloudflare Pages serves it, so
browsing Collections never touches a container — see `docs/deploy.md`. FastAPI serves
the same URLs everywhere else, and `test_static_export_matches_the_api` asserts the two
answer identically. The exported files are build artifacts and are not committed;
`collections.json` remains the single source of truth.

### `backend/spots.py`

A `Spot` dataclass + the `SPOTS` list. Each spot is a *proposal*: a bbox, the OSM way
name(s) to filter routes to, and the metadata we want to show. Spots are data, not code —
adding one is a list entry, not a new module.

Key fields (see the dataclass docstring for the full set):

- `bbox` — TIGHT. We fetch the whole road network in it, so a loose bbox is a slow build
  and a heavy Overpass query. Aim for the road + ~200 m.
- `osm_way_names` — the **exact OSM `name` tag**, not the popular name. "Hawk Hill" is not
  an OSM way; the way is named "Conzelman Road". Getting this wrong = zero routes.
- `road_types` / `max_road_rank` — many famous climbs are `secondary` or `tertiary`, above
  the app's default rideable cut. Spots override per-spot.
- `confidence` — `high`/`medium`/`low`. Low-confidence spots are researched but unverified;
  the build will tell you if the bbox/name is wrong (it finds no routes).

### `backend/pipeline.py`

Extracted from `main.py` so the build script cannot drift from the live search. Contains:

- `mark_traversable()` — the whole-network-fetch/filter-for-riding rule
- `surface_category()` / `surface_pcts()`
- `RouteFinalizer` — physics sim, optional zero-speed splitting, dedup, flow scoring.
  Dedup runs two tests: **Jaccard** over node sets for near-identical lines, and
  **containment** (`|A∩B| / min`) for a route that lies *inside* one already emitted.
  The second exists because symmetric similarity structurally can't see a subset —
  Mount Diablo's South Gate Road shipped a 5.1 km route that was 98% a subset of the
  9.2 km one above it at a Jaccard of only 0.53.
- `route_payload()` — the canonical route → dict serialization

`main.py` wraps `route_payload()` in an SSE frame; the build script writes it to JSON.
**If you change a route's wire shape, change it here and it lands in both.**

### The tab

Browse is a **region accordion**, not a flat list: each city is a collapsed folder
showing how many descents it holds, how long the longest is, and how fast. Expanding one
loads every spot in it (parallel `/collections/{slug}` fetches — a region is ~200 KB, so
there's no bulk endpoint) and draws **one line per spot** on the map, its headline route,
fitted to the whole metro. Hovering a card highlights its line; clicking opens the spot
and its remaining lines.

One region open at a time, deliberately: the open one *is* what the map is showing, and
two would leave "which lines are these?" ambiguous and fight over the viewport.

`useCollections` caches every spot it fetches, so opening a spot after browsing its
region costs no request, and re-expanding a visited region is instant.

### The build script

```bash
python -m backend.scripts.build_collections --spot hawk-hill-conzelman   # one spot
python -m backend.scripts.build_collections --city "San Francisco Bay Area"
python -m backend.scripts.build_collections                              # all spots
python -m backend.scripts.build_collections --dry-run                    # list what would build
```

Behavior that matters:

- **Incremental by default.** Results merge into the existing `collections.json`; a spot
  that fails leaves the previously-built spots intact. `--clean` discards first.
- **Cached.** Overpass + elevation go through the normal disk cache
  (`~/.cache/hillbomb/`), so a rebuild after tweaking a filter is fast and offline.
- **Slow and network-bound on a cold run** *unless you build the local road-network
  cache first* — see below. ~15-30 s per spot against Overpass, well under a second
  against a local GOL.
- Per-spot failures are reported and the script continues, exiting non-zero at the end if
  anything failed.

### Build the local road-network cache first

A full `--clean` rebuild is ~94 spots. Against public Overpass that is roughly 94
cold queries, half an hour of waiting, and a meaningful amount of load on a
volunteer-run service that asks you to keep it under 10k queries a day. Build the
local GeoDesk cache once instead:

```bash
python -m backend.scripts.build_gol --tier all \
    --work-dir /tmp/golbuild --out data/hillbomb.gol
```

`backend/osmsource.py` picks up `data/hillbomb.gol` with no configuration, so the
builder just gets faster — nothing else changes. Verified: a spot built from the
GOL and the same spot built from Overpass produce **byte-identical** route
payloads, so this is a speed change, not a data change.

**Watch the size.** The `all` tier is every region in `COVERAGE_REGIONS` — 34 of
them today, across 35 Geofabrik state extracts. Budget for it:

| | Geofabrik downloads | GOL |
|---|---|---|
| `--tier deploy` (3 regions, what ships to Cloud Run) | 1.4 GB, 2 extracts | ~200 MB |
| `--tier all` (every region, local only) | 9.0 GB, 35 extracts | ~820 MB |

Two things keep it from running away:

- **The source extracts are the big part, and they're disposable.** `--work-dir`
  holds the raw Geofabrik `.osm.pbf` files and the per-region intermediates.
  Delete the whole directory once the GOL is built; keep it only if you plan to
  rebuild soon, since it makes a rebuild download-free.
- **Never ship the `all` tier.** `data/hillbomb.gol` is gitignored, and the build
  script warns above 500 MB. Cloud Run gets `--tier deploy`. See
  `docs/local-osm-data.md` for why the split exists and how the manifest makes it
  impossible for a deploy-tier file to be mistaken for a full one.

Check what a tier covers before committing to the download:

```bash
python -m backend.scripts.build_gol --tier all --list --work-dir . --out /dev/null
```

Regions outside the built set still work — they fall back to Overpass, exactly as
before.

### Why spots ride through stop signs

Spots do **not** build with a normal search's toggles: `avoid_stop_signs` and
`avoid_stoplights` are off in the `Spot.toggles` default. A spot is one named famous
descent, and a rider bombing it rolls the stops.

With them on — which is how this shipped first — the pathfinder cut every descent at its
first cross street, and then seeded a fresh path just below it, so both halves came back
as separate routes on the same road. Mt. Diablo Summit Road shipped as two 3.5 km routes
meeting at a stop sign; Marin Avenue, a 1 km wall, shipped as four ~200 m blocks. Those
read as redundant duplicates in the UI, and the node-set dedup in `pipeline.py` can't
catch them: consecutive fragments barely share any nodes (Jaccard 0.02–0.17), so it
correctly leaves them alone.

Stops on the line are still recorded in `route.stops` and penalized by the flow score.
That's the designed way to say "there's a signal in this run" — and it means curated flow
grades are lower now than in the first build, where cutting at every stop hid them.

`avoid_bigger_roads` stays on: a descent really does end where it meets a highway.

### Why a curated route may dip to 0 km/h

Spots build with `RouteFinalizer(..., split_on_stall=False)`, so a route that stalls
stays whole instead of being cut in two.

A live search splits at any point the sim decelerates the rider to 0
(`split_route_on_zero_speed`), which is right there: the far side of a stall is a
separate descent worth surfacing on its own. On a curated spot it isn't — the road has a
name and the run is the whole road. The sim models a *coasting* rider while most spots
use a `cyclist_upright` profile, so a 6 m riser mid-canyon stalls it where a real rider
would pedal over without noticing, and Piuma Road shipped as two routes because of one.

The speed profile dips to 0 and recovers on its own: `simulate_speed_profile` carries
speed across segments and re-accelerates once the road tips down again. Expect an honest
0 in the middle of a few profiles, and a slightly lower `avg_speed_kmh` on those routes.

### Disciplines

A spot carries `disciplines: tuple[str, ...]` — a list, because plenty of descents are
ridden by more than one crowd. Marin Avenue is a road-bike wall *and* a skate bomb; the
old single-valued `discipline="both"` was that idea encoded as a special case.

The vocabulary is `config.DISCIPLINES`: **road**, **skate**, **gravel**, **mtb**. The
Collections filter builds its chips from the tags **actually in use**, so a discipline no
spot claims shows no chip.

Discipline is **curated, not derived**. It cannot be computed from `surface_pcts`, because
eight of the paved spots report `unknown 100%` — Baxter, Eldred, Fargo, Latigo, Piuma and
Stunt are all tarmac that OSM simply hasn't tagged.

### Dirt: what it took to reach unpaved terrain

Gravel and MTB were reserved words for a while, because the pipeline physically could not
route onto dirt. Four things changed, in dependency order.

**1. `highway=track` was missing from `HIGHWAY_RANK`.** This was the whole blocker.
`overpass.ROAD_NETWORK_TYPES` derives from that dict, so the query never asked for the
standard tag for fire roads and gravel doubletrack, and nothing downstream can route onto
a way that was never downloaded. It now sits at rank 0 with `path`/`cycleway`. Six of the
eleven dirt spots are `track`, including Repack — the road mountain biking was invented
on. (`path` and `cycleway` were already there, which is why singletrack was reachable in
principle all along while fire roads were not.)

**2. Trail difficulty is read, with a caveat that limits what it can promise.**
`mtb:scale` and `sac_scale` fold into one 0–6 integer on `OSMWay` → graph edge → the
route's `trail_difficulty` (the hardest segment, since difficulty is a gate, not an
average). `mark_traversable` takes a `max_trail_difficulty` cap.

The caveat: **coverage is thin — most trails carry neither tag** — so the cap lets
*untagged* ways through, the opposite of what the surface filter does with `unknown`.
Excluding unknowns would empty the graph on most trail spots. So the filter can narrow a
search already on trails; it **cannot** guarantee a road search never sees singletrack.
Pinning `osm_way_names` is what does that. On the wire, `trail_difficulty: null` means
*unknown*, never *easy*.

**3. Two rider profiles, and the model grew a brake.** `gravel` and `mtb` carry higher
`crr` and a lower `min_continue_speed_kmh` (a tech descent at 6 km/h is a normal MTB
descent; on tarmac that means the descent is over). They also carry a new
`max_speed_kmh`, and that field is an admission: `physics.py` models a *coasting* rider
and has no brake. On tarmac that survives — drag and Crr land near reported speeds. On a
loose 15% fire road it computes 70 km/h where a real rider is braking at 30, because what
limits them is traction, sightline and rock, none of which are forces. Rather than
pretend to model that, the dirt profiles state a ceiling and both the sim and
`_speed_at_node` clamp to it. **A capped route's `top_speed_kmh` reads "at the limit",
not "this is how fast the hill is"** — it came from a constant, not from physics.

**4. Flow scoring had to become rider-relative.** The surface penalty deducts *per edge*,
so a 6 km gravel descent accrued −20 a couple of hundred times and floored at zero: the
first dirt build graded **all eleven spots F**, which made the letter meaningless across
the whole discipline. The premise was wrong, not the arithmetic — gravel is a defect for
a road cyclist and the entire point for a gravel rider. The penalty *values* stay in
`SearchConfig`; the *set they apply to* now rides on
`RiderParams.rough_surface_categories`. Gravel riders are still penalized by cobbles, MTB
riders by nothing underfoot, and road profiles keep the full set unchanged.

Dirt spots deliberately leave `allowed_surface_categories=None`: Old Railroad Grade and
Mount Wilson Toll Road are both partly paved, and filtering to unpaved would fragment
them. `osm_way_names` does the work instead.

See [research/dirt-descents.md](research/dirt-descents.md) for the verified OSM names and
the tag gotchas — Shafer Trail being `highway=secondary` is the one most likely to bite.

---

## Adding a spot

**[adding-a-spot.md](adding-a-spot.md) is the runbook** — finding the OSM name, drawing the
bbox, writing the blurb, reading a failed build. The short version:

1. `python -m backend.scripts.scout_ways --bbox <loose box> --name <road>` to confirm the
   OSM `name` and get a tight bbox back. Offline, off the local GOL, near-instant —
   cheaper than learning the same thing from a failed build.
2. Add a `Spot(...)` to `SPOTS` in `backend/spots.py`.
3. `python -m backend.scripts.build_collections --spot <slug>`
4. If it finds 0 routes, the usual causes, in order of likelihood:
   - `osm_way_names` doesn't match the OSM `name` tag — this is what step 1 rules out.
   - `max_road_rank` too low for the road's `highway=*` class.
   - bbox doesn't actually contain the road.
   - the descent is shorter than the profile's `min_route_length_m`.
5. Commit the regenerated `collections.json`.

Text-only changes (blurb, notes, name) don't need a pipeline run — the builder's
`--metadata-only` mode re-stamps them onto the existing output, leaving routes alone.

## Research

`docs/research/famous-descents.md` holds the raw research (bbox, OSM names, grades, history)
for roads not yet promoted into `spots.py`. It is the backlog. Entries carry a confidence
rating; treat anything below `high` as unverified until a build finds routes on it.
`dirt-descents.md` is its unpaved companion.

`docs/research/expansion-2026-08.md` covers the pass that took the collection from 94
spots to 272. Read it before a big addition: it is where the recurring failure modes are
written down — OSM `name` tags that don't match the popular name (including two roads
renamed inside two years), the `ref`-only roads the pipeline still cannot reach, and the
region bboxes that are now the real limit on coverage rather than research.
