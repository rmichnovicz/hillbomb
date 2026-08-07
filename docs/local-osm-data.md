# Local OSM data (GeoDesk)

Hillbomb reads its road network from a local GeoDesk **GOL** file where we have one
and from public Overpass everywhere else. This documents why, how to build the
GOL, and the two things that will silently break if you get them wrong.

---

## Why

Overpass is not a problem we're fixing — the FOSSGIS instance publishes a
fair-use threshold of roughly 10,000 queries and 1 GB per day, and Hillbomb is
nowhere near it. What a local GOL buys is **latency and independence**:

| | cold Overpass | local GOL |
|---|---|---|
| Twin Peaks (136 ways) | ~1,300 ms | **14 ms** |
| SF viewport (17,008 ways) | ~3,400 ms | **667 ms** |
| Angeles Crest (1,525 ways) | ~21,000 ms | **84 ms** |

(Measured 2026-08-06 on the committed region set. Overpass timings include one
504-and-retry, which is ordinary for it.)

It also means a search in a covered region works when Overpass is down.

Coverage is deliberately partial. Anything outside it falls through to Overpass,
so panning to Lisbon still returns routes.

---

## Two tiers

The right amount of coverage differs by environment, so there are two:

| tier | regions | Geofabrik downloads | GOL | for |
|---|---|---|---|---|
| `deploy` | 3 (Bay Area, Tahoe, LA) | 1.4 GB, 2 extracts | ~200 MB | ships inside the Cloud Run image |
| `all` | 34 — every city in `spots.py` | 9.0 GB, 35 extracts | ~820 MB | local dev and Collections builds |

Locally you want everything: a `--clean` Collections rebuild is ~94 spots, which
against Overpass is ~94 cold queries and half an hour. On Cloud Run every megabyte
is cold-start image-pull time, so only regions marked `deploy=True` go in.

```bash
python -m backend.scripts.build_gol --tier all    --work-dir /tmp/golbuild --out data/hillbomb.gol
python -m backend.scripts.build_gol --tier deploy --work-dir /tmp/golbuild --out data/hillbomb-deploy.gol
python -m backend.scripts.build_gol --tier all --list --work-dir . --out /dev/null   # just look
```

`--work-dir` holds the raw Geofabrik extracts and per-region intermediates. It is
disposable — delete it once the GOL exists, or keep it to make the next rebuild
download-free. The build script warns when the output exceeds 500 MB, which is the
line between "fine on a workstation" and "do not put this in a container image".

### The manifest is what defines coverage

`build_gol.py` writes `<out>.regions.json` next to the GOL, listing the regions
that actually went in, and `osmsource` reads coverage from **that file**, never
from `COVERAGE_REGIONS`.

This is load-bearing. With a deploy-tier GOL on Cloud Run and a 34-region catalog
in the code, routing by the catalog would send a Denver search to a file with no
Colorado in it — returning an empty road network that looks exactly like "no
rideable roads here". A missing or corrupt manifest means *no* coverage, not full
coverage: failing toward Overpass is always the safe direction.

---

## Building it

Needs `osmium-tool` (`brew install osmium-tool`) and the GOL utility.

> **Get the GOL tool from [`clarisma/geodesk-gol`](https://github.com/clarisma/geodesk-gol/releases), v2 or newer.**
> Not `clarisma/gol-tool` — that repo stops at 1.2.0, writes GOL format 1.0 which
> `geodesk` 2.x refuses to open (`Unsupported Store Format`), and has no
> `--waynode-ids` option at all. v2 is a native binary and needs no JVM; v1 was a
> Java app.

```bash
export HILLBOMB_GOL_TOOL=/path/to/gol
python -m backend.scripts.build_gol --tier all --work-dir /tmp/golbuild --out data/hillbomb.gol
```

Nothing to configure to use it: `HILLBOMB_GOL` defaults to `data/hillbomb.gol` in
the repo, so `uvicorn backend.main:app` and `build_collections` both pick it up.
Set `HILLBOMB_GOL=""` to force Overpass, or point it elsewhere to use another file.

The test suite pins `HILLBOMB_GOL=""` in `backend/tests/conftest.py` so results
never depend on whether the developer happens to have built one.

The build downloads the Geofabrik extracts named by each region, slices each
region's bbox out of them, strips everything that isn't one of the 17 highway
classes in `config.HIGHWAY_RANK` (plus `highway=traffic_signals` and
`highway=stop` nodes), merges, and compiles. Current numbers:

| region | roads PBF |
|---|---|
| sf-bay-area | 51.1 MB |
| tahoe | 9.0 MB |
| los-angeles | 60.8 MB |
| **merged → GOL** | 121.7 MB → **200.1 MB** |

That is the `deploy` tier: about 90 seconds once the source extracts are
downloaded. The `all` tier is 34 regions, 563.8 MB of merged roads and an
**822.8 MB** GOL, roughly 15 minutes with the extracts already on disk.
`--work-dir` wants ~3× the source PBF free — budget ~25 GB for the `all` tier.

### Interrupting a build is safe, and re-running resumes

Both the downloads and the GOL are written to scratch paths and renamed into
place, so a killed build leaves the previous GOL and every complete extract
intact, and a re-run picks up where it left off.

This was learned the hard way: an earlier version wrote downloads straight to
their final name, so a build killed mid-transfer left a truncated `.pbf` that the
next run's "already have it" check happily reused. It surfaced eleven regions
later as `PBF error: unexpected EOF` naming a *region*, not the file. Note that
`osmium fileinfo` calls a truncated file healthy — it only reads the header. Use
`osmium fileinfo -e`, which reads the whole thing:

```bash
osmium fileinfo -e /tmp/golbuild/maryland-latest.osm.pbf
```

---

## The two things that silently break

### 1. `--waynode-ids` is not optional

GeoDesk omits the OSM IDs of untagged way vertices by default and reports them as
`id` 0. Hillbomb keys its graph on node IDs and detects an intersection as *two
ways referencing the same node ID* — and a plain street intersection carries no
tags. Measured on the Tahoe region: **15,773 of 15,817 way nodes** came back as
id 0 without the flag. Every one of them would collapse onto a single node.

`build_gol.py` always passes it. `geodesk_source` raises `MissingWaynodeIds` on
the first id-0 node rather than building a nonsense graph. Cost is about +32% file
size (Tahoe: 10.0 MB → 13.2 MB).

### 2. Partial coverage must fall back, not partially serve

`osmsource.covering_region` requires the request bbox to be **wholly inside** a
region. A half-overlapping request served locally comes back with the network
truncated at the file's edge, and `overpass._contiguous_inbbox_runs` then trims
every way at that edge and returns it looking entirely legitimate. Descents would
dead-end along an invisible line with nothing logged.

This is also why region bboxes are padded well beyond the interesting terrain: a
tight box means an edge-of-metro viewport falls back exactly when someone is
looking at the good riding.

---

## What the user sees

`osmsource.describe_source` returns the status text before any fetch starts, and
distinguishes three cases that differ by three orders of magnitude:

| source | message | typical |
|---|---|---|
| `geodesk` | "Reading local map data (San Francisco Bay Area)..." | 10–700 ms |
| `overpass-cache` | "Loading cached map data..." | ~2 ms |
| `overpass` | "Querying Overpass API..." | 1–20 s, may enter retry backoff |

One message for all three made the fast paths look broken and the slow path look
hung. The cache check is a single `stat()` (`overpass.is_cached`) and is racy only
in the harmless direction — an entry expiring between the check and the fetch just
means the text said "cached" for a query that went to the network.

---

## Adding a region

Add a `CoverageRegion` to `COVERAGE_REGIONS` in `backend/osmsource.py` and rebuild.
The catalog is used by both the router and the builder on purpose — a separate list
in the build script could drift, and the failure mode of that drift is the silent
truncation above. (What the *router* trusts at request time is the manifest; the
catalog is what the builder works from and what the tests check.)

Region boxes are the per-city union of spot bboxes padded by 0.2° (~22 km), except
the three `deploy` regions, whose boxes are hand-tuned wider because they are sized
for riding terrain rather than for the descents curated so far. Geofabrik sources
were resolved by intersecting each box against Geofabrik's `index-v1.json`; a
region straddling a state line lists more than one.

`geofabrik` is the extract path minus `-latest.osm.pbf`, e.g.
`north-america/us/california`. Give a region two when it straddles a boundary
(Tahoe pulls California and Nevada, since the lake is the state line).

`test_every_spot_city_has_a_region` fails when a spot is added in a city with no
region, and `test_every_spot_fits_inside_its_region` fails when a region's padding
is too tight to hold its own descents.

---

## Freshness

A GOL is a snapshot; Overpass is live. Measured against a same-day Geofabrik
extract, a 17,008-way SF viewport disagreed on **3 ways** — all of them edited on
OSM that morning (Van Ness Avenue way 397116935 went from 7 nodes to 5 at
20:26 UTC). Agreement was 99.98% for SF, 99.67% for Angeles Crest, 100% for
Tahoe, Marin and Twin Peaks, with **zero** tag differences anywhere.

That is the expected divergence and it's why
`test_geodesk_and_overpass_agree` checks geometry as a ratio (≥99%) but tags
exactly — a tag difference on a way both sources agree on the shape of can't be
vintage, it's a parsing bug.

Roads don't move, so a quarterly rebuild is honest maintenance. `gol` has an
`update` command for incremental diffs if that ever stops being true.

---

## Licensing

- `geodesk` (the Python package the service imports) — **LGPL-3.0**, used
  unmodified as a library.
- `gol` (the build tool) — **AGPL-3.0**, but a standalone CLI run offline to
  produce a data file. Not linked into, shipped with, or invoked by the service.
