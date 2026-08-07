# Adding a spot to Collections

The working runbook for putting a new famous descent in the Collections tab. For *why*
the feature is built the way it is, read [collections.md](collections.md) first — this
doc assumes it.

The whole job is: get two fields right (`osm_way_names` and `bbox`), run the builder, read
what it says, commit the JSON.

---

## 1. Pick a road

`docs/research/famous-descents.md` is the backlog — roads already researched with a
proposed bbox, OSM name and confidence rating, but not yet promoted into `spots.py`.
Start there before researching something new.

A road earns a slot if someone outside its own city would recognize it. The bar is
"famous descent", not "good hill" — good hills are what the search is for.

## 2. Find the exact OSM name

**This is the field that fails most often.** `osm_way_names` matches the OSM `name` tag,
not the name people use. Hawk Hill is not an OSM way; the way is called *Conzelman Road*.

Ask the map:

```bash
backend/.venv/bin/python -m backend.scripts.scout_ways --bbox 37.82,-122.53,37.84,-122.48 --name Conzelman
```

`scout_ways` reads the same local GOL the pipeline reads, so it answers offline in
milliseconds. Per matching `name` it prints the way count, `highway` classes and the
`max_road_rank` they imply, surface, how many ways are one-way, length, net relief — and
a tight, already-padded bbox for step 3.

When you know the hill but not its name, invert it: `--list` ranks every named way in a
box by elevation relief, which is also the fastest way to find out that the famous road
is signed one thing and tagged another.

```bash
backend/.venv/bin/python -m backend.scripts.scout_ways --bbox 47.60,-122.40,47.66,-122.34 --list
```

Two things to know about `--list`. It groups by `name` across the whole box, so a row
can be several disconnected roads that share a common name — re-run with `--name` in a
tight box before believing its numbers. And its box must sit **wholly inside** a
coverage region or the query falls through to public Overpass; it prints which source it
used on the first line.

For anything the tool can't answer — which way the one-way runs, whether `bicycle=no` is
on the segment you care about — [openstreetmap.org](https://www.openstreetmap.org) and
the way's tag list is still the place to look.

Matching is a **case-insensitive substring** against the route name, so:

- `"Conzelman"` catches "Conzelman Road" — prefer the short distinctive form.
- `"Summit Road"` also catches every other Summit Road in the bbox. When the name is
  generic, the bbox is the only thing disambiguating it. Tighten accordingly.

If the descent legitimately changes name partway, list every name **and** set
`toggles=Toggles(..., stay_on_initial_road=False)`. A test enforces that pairing —
listing several names while pinned to the first one cuts the route at the boundary.

## 3. Draw a tight bbox

Format is `(south, west, north, east)`. We fetch the **entire classified road network**
inside it, so a loose bbox is a slow build and a rude Overpass query. Target the road
plus ~200 m.

Easiest method: paste the `bbox=(...)` line `scout_ways --name` printed in step 2. It is
the union of every matching way padded by ~200 m, which is the target. Failing that, on
openstreetmap.org use Export → *Manually select a different area*, drag the box around
the road, and read the four numbers off the panel, reordered to south/west/north/east.

If the printed box is too big, the usual cause is that the name also matched a road
somewhere else in your query box. Shrink the query box until only the road you want
comes back, and the union shrinks with it.

`test_spots.py` rejects anything over 0.1° on a side (~11 km) and anything outside the
US, which catches dropped minus signs and swapped lat/lon. It cannot tell you whether the
box actually contains the road — only a build does that.

Clip the box to the *famous* section. Lower Marin Avenue is flat; lower Page Mill is an
expressway; Filbert Street runs flat for kilometres either side of its one steep block.
Where you clipped and why goes in a comment above the `bbox` — several spots have one.

## 4. Write the entry

Add a `Spot(...)` to `SPOTS` in [backend/spots.py](../backend/spots.py), in the right
city block. Order within a city is roughly most-famous-first and the UI preserves it.

Fields you will actually think about:

| Field | Guidance |
|---|---|
| `slug` | kebab-case, stable — it keys the JSON and the URL |
| `city` | the UI grouping key; match an existing string exactly or you create a new region |
| `discipline` | `cycling` \| `skate` \| `both` — display only |
| `rider_profile` | `cyclist_upright` (default), `cyclist_drops`, `longboarder`. Set `longboarder` for skate spots: it changes physics *and* lowers `min_route_length_m` to 60 m, which is what lets a one-block bomb survive at all |
| `max_road_rank` | default 6 = `secondary`. Ranks: path/cycleway 0, living_street 1, service 2, residential 3, unclassified 4, tertiary 5, secondary 6, primary 7, trunk 8, motorway 9 |
| `max_routes` | cap, not a quota — supporting routes must also clear the descent floors in `build_collections.py` |
| `confidence` | `high` only once a build has found routes on it. Record the doubt in `notes` |
| `toggles` | leave the default unless the descent changes road name (see step 2) |

Note that famous roads are routinely tagged far below their stature — Conzelman and Baxter
are `residential`, Mt. Diablo and Maryhill are `unclassified`. That's why the rank cap is
per-spot rather than an assumption.

### Writing the blurb

`blurb` is the one-line hook on the spot card. It is the *only* place it appears, and it
renders as 11px gray text directly under distance, descent, top speed and flow grade.

**Answer: where is it, and what is the descent like.** 140 characters, enforced by
`test_blurb_is_short`.

- Write about the way **down**. This is a descent app; a paragraph about a climbing PR is
  the wrong half of the road.
- Don't restate the stat row — length, drop and speed are already on the card.
- Skip race provenance unless the history *is* the road (Maryhill's museum ownership, the
  Counterbalance's streetcar tunnels, Fargo's 1974 climb).
- Skip the superlative stack. Every spot here is famous — that's the selection criterion,
  so "iconic / legendary / definitive" carries no information and 24 of them in a row read
  as filler.

Hazards, legality, closures and surface go in `notes`, which renders as its own amber
callout on the spot page. Don't say the same thing in both.

## 5. Build it

```bash
python -m backend.scripts.build_collections --spot <slug>
```

Cold runs are network-bound (~15–30 s/spot: Overpass + elevation). Both go through the
disk cache at `~/.cache/hillbomb/`, so re-runs are fast and offline. Builds are
incremental — a failure leaves every previously-built spot intact.

If you have the local road-network cache built (`data/hillbomb.gol`, see
`docs/collections.md`), a spot in a covered region skips Overpass entirely and builds in
well under a second. **A spot in a city that has no `CoverageRegion` cannot use it** —
`test_osmsource.py::test_every_spot_city_has_a_region` fails until you add one to
`backend/osmsource.py`, which is the reminder to do it. Copy the bbox pattern from a
neighbouring region and pad it by ~0.2°; leave `deploy=False` unless this is going into
the Cloud Run image.

A good result prints the headline route:

```
    3 route(s) on Conzelman, keeping 2 — best: 1408 m, 166 m drop, 84 km/h, flow B
```

Sanity-check that line against what you know about the road. A 200 m "descent" on a
2 km climb means something upstream is cutting it short.

## 6. When it finds nothing

The builder fails with a specific message rather than a generic "no routes", so read it.
In rough order of likelihood:

| Message | Cause | Fix |
|---|---|---|
| `No OSM way matching [...] in bbox` | wrong name, or bbox misses the road | re-check the `name` tag on openstreetmap.org (step 2) |
| `none are rideable at max_road_rank=N` | road classed above the cap; the message prints its actual `highway` class | raise `max_road_rank` |
| `Pipeline found no descent on [...]` | road is in the graph but no route survived | descent shorter than the profile's `min_route_length_m` (150 m cyclist, 60 m longboard) — try `rider_profile="longboarder"`; or `stay_on_initial_road` is cutting it at a name change |
| `Overpass returned no ways in bbox` | bbox is empty or malformed | check the coordinate order is (south, west, north, east) |

Two behaviors that look like bugs and aren't, both explained in
[collections.md](collections.md): curated routes ride **through** stop signs, and a
profile may honestly dip to 0 km/h mid-route.

## 7. Commit

```bash
python -m pytest backend/tests/test_spots.py backend/tests/test_collections.py
```

Commit `backend/spots.py` and the regenerated `backend/data/collections.json` together —
the JSON is the build output and is checked in on purpose.

A commit does not publish the spot. Collections are served as flat files from the CDN,
so a new spot goes live on the next static deploy — steps 7–8 of `docs/deploy.md`, which
re-export `collections.json` and push `frontend/dist`. No API deploy is involved.

---

## Copy edits after the fact

Blurbs and notes are baked into `collections.json` at build time, so editing the text in
`spots.py` alone changes nothing a user sees. To publish a copy edit without re-running
the pipeline:

```bash
python -m backend.scripts.build_collections --metadata-only
```

This re-stamps `name`, `city`, `state`, `blurb`, `discipline`, `notes` and `confidence`
from `SPOTS` onto the existing entries, prints what it changed, and leaves `routes` and
`built_at` untouched — so the diff is exactly the text you edited.

It deliberately does **not** re-stamp `bbox` or `rider_profile`: those change what the
pipeline would produce, so writing them next to routes built from the old values would
make the entry describe a build that never happened. Change either one and it warns you
to run a real build instead.

## Rebuilding everything

```bash
python -m backend.scripts.build_collections            # incremental, all spots
python -m backend.scripts.build_collections --clean    # discard old output first
python -m backend.scripts.build_collections --dry-run  # list what would build
```

Use `--clean` after a change to the pipeline or to `Spot.toggles` defaults, where stale
entries built under the old rules would otherwise survive. Note it rewrites every
`built_at`, so expect a large diff.

One caution: the builder writes `collections.json` after **every** spot. Don't run two
builds at once, and don't edit `spots.py` while one is running — it imported `SPOTS` at
startup, so your edit won't be in the output.
