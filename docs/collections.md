# Collections — curated famous descents

**Status: in progress.** Read this before touching the Collections feature.

Collections are a hand-curated set of famous descents (Hawk Hill, Lookout Mountain,
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
GET /collections                     # serves collections.json verbatim
frontend/src/components/Collections/ # the Collections tab
```

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
- `finalize_routes()` — physics sim, zero-speed splitting, Jaccard dedup, flow scoring
- `route_payload()` — the canonical route → dict serialization

`main.py` wraps `route_payload()` in an SSE frame; the build script writes it to JSON.
**If you change a route's wire shape, change it here and it lands in both.**

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
- **Slow and network-bound on a cold run.** ~15-30 s per spot. This is expected; it is an
  offline script, not a request path.
- Per-spot failures are reported and the script continues, exiting non-zero at the end if
  anything failed.

---

## Adding a spot

1. Add a `Spot(...)` to `SPOTS` in `backend/spots.py`.
2. `python -m backend.scripts.build_collections --spot <slug>`
3. If it finds 0 routes, the usual causes, in order of likelihood:
   - `osm_way_names` doesn't match the OSM `name` tag — check on openstreetmap.org.
   - `max_road_rank` too low for the road's `highway=*` class.
   - bbox doesn't actually contain the road.
   - the descent is shorter than the profile's `min_route_length_m`.
4. Commit the regenerated `collections.json`.

## Research

`.research/famous-descents.md` holds the raw research (bbox, OSM names, grades, history)
for roads not yet promoted into `spots.py`. It is the backlog. Entries carry a confidence
rating; treat anything below `high` as unverified until a build finds routes on it.
