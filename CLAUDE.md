# Hillbomb — architecture and conventions

This file describes the project architecture, conventions, and key decisions for AI-assisted development. Read this before making changes.

`AGENTS.md` is a symlink to this file, so both names resolve to one source of truth. Edit `CLAUDE.md`.

---

## Project overview

Hillbomb finds great downhill routes ("hill bombs") for cyclists and skateboarders. Users search their current map viewport; the backend queries OSM and elevation data, builds a sparse graph, runs a greedy descent pathfinding algorithm, and streams results back to the frontend via SSE.

---

## Repo structure

```
hillbomb/
├── frontend/          # React app
│   ├── src/
│   │   ├── components/
│   │   │   ├── Map/           # MapLibre GL map, route overlays, map pin scrubbing
│   │   │   ├── RouteList/     # Sidebar route cards, sparklines, flow score badges
│   │   │   ├── Collections/   # Curated famous descents tab (region folder → all its lines → spot routes)
│   │   │   ├── ProfilePanel/  # Elevation + speed profile chart, scrub interaction
│   │   │   ├── RiderSettings/ # Physics parameter sliders
│   │   │   └── SearchControls/ # "Search this area" button, toggle controls, physics params, advanced settings
│   │   ├── hooks/
│   │   │   ├── useSearch.ts       # SSE connection, streaming route ingestion
│   │   │   ├── useCollections.ts  # Curated collections index + per-spot fetch
│   │   │   ├── usePhysics.ts      # Client-side physics sim (NumPy equiv in JS)
│   │   │   └── useLocalStorage.ts # Saved routes persistence
│   │   ├── types/             # Shared TypeScript types (Route, Node, Edge, RiderParams)
│   │   ├── api.ts             # Every backend URL. Static vs. dynamic origin split
│   │   └── utils/
│   │       └── gradeColor.ts  # Grade → color mapping (shared by chart and sparklines)
│   └── e2e/               # Playwright — runs against the BUILT bundle, not the dev server
├── backend/
│   ├── main.py            # FastAPI app, SSE endpoint, /collections/*.json endpoints
│   ├── pipeline.py        # Shared pipeline core — used by BOTH main.py and the collections builder
│   ├── osmsource.py       # Chooses the OSM source per bbox: local GOL or Overpass
│   ├── geodesk_source.py  # Reads the road network from a local GeoDesk .gol
│   ├── overpass.py        # Overpass API queries, way parsing
│   ├── elevation.py       # Open-Topo-Data queries, per-node elevation enrichment
│   ├── graph.py           # Sparse graph construction, peak/valley detection
│   ├── pathfinding.py     # Greedy descent algorithm, priority queue, route scoring
│   ├── physics.py         # NumPy speed profile simulation
│   ├── scoring.py         # Flow score computation
│   ├── spots.py           # Curated famous descents (the Collections source data)
│   ├── config.py          # All tunable parameters (see Parameters section)
│   ├── scripts/
│   │   ├── build_collections.py  # Offline builder: Spot → routes → collections.json
│   │   ├── export_static_collections.py  # collections.json → flat files for the CDN
│   │   ├── scout_ways.py         # Research tool: verify a spot's osm_way_names + bbox
│   │   └── build_gol.py          # Offline builder: Geofabrik → filtered → hillbomb.gol
│   └── data/
│       └── collections.json      # Build output; COMMITTED
├── functions/             # Cloudflare Pages Functions — the ONLY dynamic thing on the static half
│   └── api/where.js       # GET /api/where → visitor's approximate location, from request.cf
├── scripts/
│   └── build-static.sh    # SPA + collections → frontend/dist, ready for Pages
├── cpp/                   # C++ pathfinding extension (post-MVP)
│   ├── pathfinding.cpp
│   ├── CMakeLists.txt
│   └── bindings.cpp       # pybind11 bindings, must expose same interface as pathfinding.py
├── Dockerfile             # one image, single-origin: SPA + API. Not the prod path
├── docs/
│   ├── deploy.md          # Cloud Run + Cloudflare Pages runbook — read before deploying
│   ├── local-osm-data.md  # GeoDesk GOL: why, how to build, what breaks silently
│   ├── collections.md     # Collections feature doc — read before touching Collections
│   ├── adding-a-spot.md   # Runbook: add a curated descent, build it, edit its copy
│   └── research/          # Raw research backlog (paved + dirt; verified OSM names and tag gotchas)
├── CLAUDE.md
└── AGENTS.md              # symlink → CLAUDE.md
```

---

## Backend architecture

### Request / response flow

```
POST /search
  { bbox, road_types, toggles, rider_params, animate_candidates }
  → returns SSE stream

SSE events:
  { type: "status",    message: "querying Overpass API..." }
  { type: "status",    message: "fetching elevation data for N nodes..." }
  { type: "status",    message: "building route graph..." }
  { type: "route",     route_id, geometry, metadata, flow_score }   ← emitted immediately when path finalizes
  { type: "physics",   route_id, speed_profile, top_speed, avg_speed }  ← emitted when sim completes
  { type: "candidate", geometry }  ← only when animate_candidates=true
  { type: "error",     message }   ← fatal pipeline error; frontend shows inline error, keeps received routes
  { type: "done" }
```

`route` and `physics` are intentionally decoupled. The frontend renders a route card and map overlay immediately on `route`, then fills in the speed profile and stat bar when the matching `physics` event arrives. Cards show a loading shimmer on speed stats in the interim. If physics moves client-side in the future, the backend simply stops emitting `physics` events.

A **stop button** is shown while a search is in progress. It closes the SSE connection client-side (`eventSource.close()`); routes already received remain displayed. The backend requires no notification — it will hit a `BrokenPipeError` or `ConnectionResetError` on the next SSE write, which should be caught and treated as a normal early exit, not logged as an error.

### Pipeline stages

1. **OSM fetch** (`osmsource.py`): fetch the full classified road network in the bbox. Served from a local GeoDesk GOL when the bbox is *wholly* inside a `COVERAGE_REGION`, otherwise from Overpass (`overpass.py`). Both paths return identical `(nodes_by_id, ways)`. See **Local OSM data** below and `docs/local-osm-data.md`.
2. **Elevation enrichment** (`elevation.py`): query the `ElevationService` for elevation at each node. Sample at `elevation_sample_interval_m` intervals along ways. Cache results within a request. See **Elevation data** section for source details. Elevation is fetched **only for nodes on a traversable way** — non-traversable ways (bigger roads, surface/rank-excluded) are kept in the graph for crossing detection, which uses road rank + way name only, never elevation; their nodes stay at `elevation=0.0`. The disk cache file is keyed on the **full network geometry** (toggle-independent, passed as `cache_coords`), not the queried subset, and stores a per-coordinate map, so re-searches with different surface/road filters reuse every coordinate already fetched and only query newly-needed ones. Peak/valley detection in `graph.py` is correspondingly restricted to nodes touched by a traversable edge so the unfetched zeros can't create spurious peaks or pollute a real node's neighbourhood.
3. **Graph construction** (`graph.py`): build sparse graph with intersection nodes, peak nodes, valley nodes, and grade inflection nodes. Bridge/tunnel ways keep their full node sequence like any other way; only their *elevations* get the deck treatment (see **Bridge/tunnel handling**).
4. **Pathfinding** (`pathfinding.py`): greedy descent from priority queue. Emit routes via an async generator so FastAPI can stream them as SSE events.
5. **Physics simulation** (`physics.py`): for each finalized route, run the NumPy speed profile simulation and attach results before emitting.
6. **Flow scoring** (`scoring.py`): compute flow score for each finalized route before emitting.

### Shared pipeline core (`pipeline.py`)

`main.py` handles HTTP: SSE framing, the admission gate, cancellation, disconnect
watching. Everything *reusable* about the pipeline lives in `pipeline.py`:

- `mark_traversable()` — the fetch-whole-network / filter-for-riding rule
- `surface_category()` / `surface_pcts()`
- `RouteFinalizer` — physics sim, zero-speed splitting, Jaccard dedup, flow scoring
- `route_payload()` — **the single definition of a route's wire shape**

This exists so the offline collections builder cannot drift from the live search: both
call the same code, so a curated route and a searched route are byte-identical in shape.
**If you change a route's wire shape, change `route_payload()`** — it lands in `/search`
SSE and `collections.json` together, and `frontend/src/types/index.ts` `Route` must match.

### Collections (curated famous descents)

A curated set of famous descents (Hawk Hill, etc.) grouped by city, precomputed
offline and served as static JSON — so a new user has world-class routes to look at
without panning around hunting for a hill. Roads don't move, so we run the real pipeline
once, offline, and commit the output rather than paying ~15 s of Overpass + elevation per
view.

```
GET /collections/index.json    → index: spots by city, metadata + headline stats, NO geometry
GET /collections/{slug}.json  → one spot with its full routes
```

Split in two because one spot's routes are ~65 KB of geometry/elevation/speed samples;
the index stays small enough to load on tab open, and the heavy part loads per spot.

**Those URLs end in `.json` because in production they are not endpoints at all.**
`scripts/export_static_collections.py` explodes the committed doc into flat files
(`index.json` plus one per slug) that Cloudflare Pages serves; the container is never in
the path. FastAPI serves the identical URLs for dev, `docker run`, and as a fallback, so
nothing about collections is exercised only in production. The index is *computed* from
the doc rather than stored in it, which gives it a real chance to drift between the two
paths — both go through `pipeline.collections_index()` so it can't, and
`test_static_export_matches_the_api` asserts that.

**Read `docs/collections.md` before touching this**, and `docs/adding-a-spot.md` to add
one. Short version: spots are data in `backend/spots.py`;
`python -m backend.scripts.build_collections` builds them; the output is committed. The
field that decides whether a spot works is `osm_way_names` — it must be the exact OSM
`name` tag ("Conzelman Road"), not the popular name ("Hawk Hill").

**Opening the tab expands the nearest region.** `useIpLocation` + `utils/geo.nearestCity`
pick it from the visitor's IP-derived location, once per mount, and only if no region is
already open. Scoring is on the **nearest spot**, not a regional centroid: several regions
are geographically enormous ("Great Lakes" spans Michigan to Wisconsin, centroid in open
water), and centroids put Chicago 523 km from everything when Holy Hill is 160 km away.
Past a 300 km cap it declines to guess and leaves the list collapsed — nearest-of-34
always returns something, and Wichita does not belong to the Ozarks.

The index is fetched **on mount**, not on tab open, because the guess has to be made
before the visitor picks a tab. That costs 18 KB brotli'd; per-spot geometry stays lazy,
which is where the weight actually is (a large region is ~100 KB on the wire, ~350 KB
decoded — quote the wire figure).

**Desktop and mobile diverge deliberately.** Desktop waits for the tab to be opened
before expanding anything, because until then nothing would render the region it just
paid ~100 KB for. Mobile expands immediately *and* switches to the Collections tab,
because that is what draws the region's lines on the map behind the collapsed bottom
sheet — on a phone the map is the app. The sheet is left **closed**: its label names the
region ("15 descents in San Francisco Bay Area — tap to view"), which does the inviting
without spending two-thirds of the screen. The accepted cost is that the floating
"Search this area" button is hidden on the Collections tab, so a region hit trades
one-tap search for one-tap curated content on first load.

Fits reserve space for the sheet via `HillbombMap`'s `fitBottomInset` (a *fraction* of
map height, read from the live container at fit time so rotation needs no bookkeeping);
only the open sheet counts, since collapsed it is 52px and already fits inside the 60px
base padding.

`e2e/nearest-region.spec.ts` covers this, stubbing `/api/where` by route interception —
that endpoint exists only on the CDN, so it must be faked everywhere else. Read the
comment there before adding a map-viewport assertion: the obvious ones all depend on the
live openfreemap CDN and flake two runs in three alongside the rest of the suite.

A spot's `blurb` is a one-line card hook, capped at 140 chars by `test_blurb_is_short`:
where it is and what the descent is like, with hazards and legality in `notes` instead.
Text-only edits publish via `--metadata-only` — no pipeline run, no route churn.

### Pathfinding algorithm details

The pathfinding algorithm lives in `pathfinding.py`. The C++ replacement (`cpp/`) must expose an identical interface.

The graph is a `nx.DiGraph` (directed). One-way streets have a single directed edge; two-way streets have edges in both directions. `oneway=-1` ways are reversed before edge insertion. The algorithm must only traverse edges in their stored direction.

**Priority queue entry**: `(priority_tuple, path_id, sequence_number, node_id)`

**Priority tuple**: `(-is_extending, -arrival_speed, -elevation)` — min-heap with negated values, so extending paths beat new paths, faster beats slower, higher beats lower.

**Lazy deletion**: each path has a `sequence_number` incremented on any state change. Queue entries with stale sequence numbers are discarded on pop.

**Node cap**: `max_paths_per_node` (from `config.py`) limits active paths through a node. Counts active paths only; completed routes terminating at a node are not counted.

**Descent rule**: Prefer downhill edges. No hard uphill cap — the priority queue naturally deprioritizes paths that slow down on uphills via the arrival speed term. A path that crests a small rise with enough momentum will rank lower until it regains speed.

**Termination conditions** (any one triggers finalization):
- Node cap hit
- Hard stop from active toggle (stoplight, stop sign, bigger road, equal road)
- Estimated speed below `min_continue_speed_kmh` (profile-dependent: 5 longboard, 8 cyclist)
- Valley node reached

Flat sections do not terminate a path — a route may include a flat connector between two steep drops.

**Minimum route filter**: discard routes below `min_route_length_m` (profile-dependent: 60m longboard, 150m cyclist). No minimum grade or top speed filter — let ranking surface quality, don't discard results preemptively.

### Physics simulation (`physics.py`)

Used for the speed profile visualization only — not for pathfinding ranking.

Inputs: array of elevation values, array of distances between nodes, `RiderParams` (weight, Cd, frontal area, Crr).

Model: at each step, compute net force from gravity (grade), air drag (½ρCdAv²), and rolling resistance (Crr × m × g × cos θ). Integrate to get speed over distance. Clamp to physically reasonable maximum.

The same model is implemented in TypeScript (`frontend/src/hooks/usePhysics.ts`) for live slider updates on the client without a round-trip. The two implementations must stay in sync — if you change the model in `physics.py`, update `usePhysics.ts` to match.

---

## Frontend architecture

### Map

MapLibre GL JS via `react-map-gl`. Base tiles from OpenFreeMap or Protomaps (free, OSM-based).

Route overlays are MapLibre `LineLayer`s. The active route uses a solid colored line; other candidates use dashed lines with reduced opacity.

Grade color mapping is defined once in `utils/gradeColor.ts` and shared by the map layer paint expressions, the profile chart bars, and the sparkline thumbnails. If you change the color thresholds, change them in one place only.

### Profile panel

Chart.js dual-axis chart: elevation bars (left Y axis, color-coded by grade) + speed line (right Y axis, blue). Scrubbing the chart moves a cursor and fires a `onScrubPosition` callback that moves a pin on the map. The map pin position is interpolated along the active route geometry.

### Streaming

`useSearch.ts` manages the SSE connection. It parses incoming events and appends routes to local state as they arrive. Routes are inserted into the displayed list in rank order (by top speed) on each new arrival, not appended in arrival order.

### Rider settings

Sliders in `RiderSettings/` update a `RiderParams` object in React state. The profile panel re-runs `usePhysics.ts` whenever `RiderParams` changes, updating the speed line without any network request.

### localStorage

`useLocalStorage.ts` wraps read/write to `localStorage` with a versioned key (e.g. `hillbomb_routes_v1`). Saved routes store the full route geometry and metadata. If the schema changes, increment the version key and discard stale data gracefully.

---

## Elevation data

Elevation is handled by an `ElevationService` class in `elevation.py` that implements a resolution cascade: try the best available source for the queried bbox, fall back as needed.

### Resolution cascade

| Priority | Dataset | Resolution | Coverage | Source | Status |
|---|---|---|---|---|---|
| 1 | USGS 3DEP 1m | ~1m (lidar) | Partial US — urban areas, patchy | S3 COG via TNM lookup | **Off by default** |
| 2 | USGS 3DEP 1/3 arc-sec | ~10m | Continental US | S3 COG, windowed reads | **The working default** |
| 3 | SRTM 1 arc-sec | ~30m | Global | Local `.hgt` tiles, auto-downloaded | Fallback |

**In practice stage 2 serves nearly every query.** Stage 1 is implemented but gated behind `HILLBOMB_USE_1M=true` (default `false`), because 1m coverage is patchy enough that the win is unreliable and the coverage check costs a TNM API fetch at startup on every process whether or not a tile exists. Do not describe 1m as part of the live cascade without checking that env var. SRTM is the global fallback: outside CONUS, or where 3DEP reads fail. When 3DEP covers more than half the points and SRTM fills the rest, `resolution_m` stays at the 3DEP value.

### Access strategy

**3DEP 1/3 arc-sec** is served by `_Dep13TileCache`, which has two modes selected by `HILLBOMB_DEP13_MODE`:

- **`cog` (default)** — the tile is opened over HTTP by URL and only the blocks overlapping the queried window are fetched. Nothing is written to disk. A continental-US search needs no persistent storage at all. Measured on `n38w123` (223 MB tile, 512×512 float32 LZW blocks, 5 overview levels): opening costs 9 HTTP ops and ~28 KB, most of it GDAL probing for sidecar files that 404; a 2.5 km SF viewport then reads **1.7 MB in 2 range requests, 0.77% of the tile**. Note the granularity is a block, not a point — ~850 KB per block — so the win comes from points being *clustered*, which road-network samples always are.
- **`download`** — stream the whole tile to disk on first touch, then read locally. Faster on warm repeats, but pays a ~200 MB download the first time any 1° tile is touched.

Either way the last `HILLBOMB_DEP13_CACHE_SIZE` (default 8) tiles stay open as rasterio datasets in an LRU. The important property is that a dense batch of points in one tile costs **one windowed read per tile, not one read per point** — this is the whole reason `_Dep13TileCache` exists instead of a call to `rasterio.sample()`, which does an internal read per point.

Tile paths are deterministic, so no index lookup is needed: `n{lat+1:02d}w{abs(lon):03d}` under `prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current`. Reads are unsigned (`aws_unsigned=True`) against public buckets, so there is no AWS account or credential anywhere in the system.

**3DEP 1m** is the only source that needs a lookup: its URLs are not deterministic, so `_sample_1m_cog` queries the TNM products API per tile and caches the resulting URL for the process lifetime.

**SRTM** is the one source that genuinely stores tiles locally, pulled as `.hgt.gz` from the public Mapzen/Tilezen skadi bucket into `SRTM_DIR` (defaults to `<cache root>/srtm`) with per-tile download locks so concurrent requests don't duplicate a fetch.

### Cache roots: local vs Cloud Run

Everything cacheable hangs off one root, `HILLBOMB_CACHE_DIR`, defaulting to `~/.cache/hillbomb`. Three things live under it, and they are not the same kind of thing:

| What | Path | Written when |
|---|---|---|
| Overpass responses (24 h TTL) | `overpass/` | Any bbox not served by the GOL |
| Per-coordinate elevation samples | `elevation/` | Every search, regardless of DEM source |
| SRTM `.hgt` tiles | `srtm/` | Only outside 3DEP coverage |
| 3DEP tiles | *(none)* | Only in `HILLBOMB_DEP13_MODE=download` |

On Cloud Run that root is pointed at a GCS bucket mounted with gcsfuse at `/var/cache/hillbomb` (`--add-volume type=cloud-storage` plus gen2 execution environment). **The reason is the sample caches, not the tiles.** Since `cog` mode downloads no tiles, the container needs no persistent disk to work correctly; what the bucket buys is that the Overpass and elevation-sample caches survive scale-to-zero and are shared across instances, which turns a repeated search of the same area from ~15 s into near-instant and keeps load off Overpass. Drop the volume flags and the service is still correct, just cold per instance. Bucket contents are all re-fetchable, so a 30-day lifecycle rule deletes them rather than paying to keep them.

Note the asymmetry this creates with the GOL: the road network ships **inside the image** (immutable, versioned with the deploy), while caches live **outside** it (disposable, shared, expiring). Don't move either one across that line.

### `ElevationService` interface

```python
class ElevationService:
    def get_elevations(self, coords: list[tuple[float, float]]) -> list[float]:
        """
        Returns elevations (meters) for a list of (lon, lat) pairs.
        Internally selects the best available source for the bbox of the query,
        falling back through the cascade as needed.
        """
```

- Coverage check for 1m is done once per bbox (not per point) using a pre-loaded coverage index, and only when `HILLBOMB_USE_1M=true`.
- `elevation_sample_interval_m` in `SearchConfig` should match the resolution of the source actually used. The service sets this on the returned result so the graph builder uses the right interval.
- Bridge/tunnel nodes are queried like any others; their interiors are discarded and replaced with a deck ramp in `graph.py` (see **Bridge/tunnel handling**). Only the two endpoint samples end up being used.

### Tile index for 1m coverage

1m lidar coverage is not uniform. Before querying 1m COGs, the service checks a lightweight coverage index (tile extents fetched from the TNM API at construction) to determine whether 1m data exists for the bbox. If not, skip directly to 1/3 arc-sec. If the index fetch fails, it logs a warning and disables the 1m source rather than erroring.

This index fetch is why the stage is off by default: it runs in `ElevationService.__init__`, so with `HILLBOMB_USE_1M=true` every cold container pays it before the first search, in exchange for a resolution upgrade that most bboxes don't get.

---

## OSM data notes

- **One-way streets**: the pathfinding graph is a directed graph (`nx.DiGraph`). Ways tagged `oneway=yes` get a single directed edge; all other ways get edges in both directions. The pathfinding algorithm must only traverse edges in their legal direction. `oneway=-1` means the way is one-way in the reverse of the geometry direction — handle this by reversing the edge. `cycleway:oneway` and similar tags may override the main oneway tag for bicycle travel; treat these as out-of-scope for MVP and document the limitation.
- **Stop sign coverage is incomplete in OSM**. The "avoid stop signs" toggle uses `highway=stop` nodes, but many stop signs are not mapped. This is expected behavior — document it in the UI tooltip for the toggle.
- **Traffic signal coverage is much better**. The "avoid stoplights" toggle is reliable.
- **Bridge/tunnel handling**: ways tagged `bridge=yes` or `tunnel=yes` are edged over their **real node sequence**, exactly like any other way — their shape points are part of the road and dropping them draws a chord across whatever the road curves around. What gets corrected is elevation: a DEM samples the ground, so interior deck nodes come back with the creek bed below a bridge or the hillside above a tunnel, a fake V that reads as a steep drop and recovery. `graph._deck_elevations` replaces every *interior* node's elevation with a linear ramp between the two end elevations, distributed by distance along the way; the endpoints keep their measured value because they sit on real ground. The graph is therefore the source of truth for elevation — `pathfinding._finalize` reads `G.nodes[...]["elevation"]`, not `OSMNode.elevation`, so the emitted profile matches what pathfinding scored. Caveat: TIGER-era imports routinely tag hundreds of metres of ordinary road as `bridge=yes` (Muir Woods Road, way 12183699 — 51 nodes over 624 m), and on those the ramp flattens real undulation; net drop, length and geometry stay correct. Tunnels and bridges may each be excluded entirely via the `exclude_tunnels` / `exclude_bridges` toggles (pathfinding skips those edges). Bridges/tunnels whose straight-line span exceeds `max_bridge_span_m` are dropped from the graph during construction, and their nodes keep their measured elevation (they may belong to other ways).
- **Highway classification hierarchy** (for "avoid bigger/equal roads" toggles): `motorway > trunk > primary > secondary > tertiary > unclassified > residential > service > path/cycleway/track`. Link variants (e.g. `motorway_link`) are treated as equivalent to their parent class. `track` — fire roads and gravel doubletrack — sits at the bottom with `path`; it is never the bigger road at a junction. Note the rank hierarchy tracks *traffic danger on pavement*, so off it the bigger-road stop misfires: a trail crossing a dirt forest road (`unclassified`, rank 4) reads as meeting a bigger road and terminates the descent. See the Downieville spot in `spots.py`, which turns the toggle off for exactly this reason.
- **Trail difficulty**: `mtb:scale` and `sac_scale` are parsed into one 0-6 integer on `OSMWay.trail_difficulty`, carried onto graph edges, and surfaced as `Route.trail_difficulty` (the route's *hardest* segment). Coverage is thin — most trails carry neither tag — so `None` means **unknown, not easy**, and the `max_trail_difficulty` filter lets untagged ways through. That filter can narrow a trail search; it cannot keep singletrack out of a road search. See `config.SAC_SCALE_TO_DIFFICULTY`.
- **Fetch the whole network, filter for riding**: the "avoid bigger roads" toggle can only stop a descent at a road that exists in the graph. Rather than guess which bigger roads to fetch, the Overpass query always fetches the **entire classified road network** in the bbox (`overpass.ROAD_NETWORK_TYPES`, derived from `HIGHWAY_RANK`), independent of the rider's `road_types`. Keying the fetch on geometry alone also lets re-searches with different toggles/road settings reuse the cached OSM data. Each way is then tagged **traversable** in `main.py` — `highway ∈ road_types`, within `max_road_rank`, surface allowed — and `graph.py` carries that flag onto its edges. Pathfinding never expands onto a non-traversable edge (so bigger roads are never *ridden*), but their presence at a junction still triggers the bigger/equal-road hard stop via successor ranks. This adapts to any custom rideable set: narrow `road_types` to just `residential` and a crossing with a `tertiary` road is still detected.

---

## Local OSM data (GeoDesk)

Where the road network comes from is decided per-request in `osmsource.py`: a local
GeoDesk GOL file where we have coverage, public Overpass everywhere else.
`HILLBOMB_GOL` defaults to `data/hillbomb.gol`, so dev servers and the collections
builder use it with no configuration; a missing file (or `HILLBOMB_GOL=""`) means
everything goes to Overpass and behaviour is exactly as before the GOL existed. Tests
pin it off in `backend/tests/conftest.py`.

**Two tiers.** `--tier deploy` is 3 regions / ~200 MB and ships inside the Cloud Run
image. `--tier all` is all 34 (one per city in `spots.py`) / ~1 GB and is for local dev
and Collections builds — a `--clean` Collections rebuild is ~94 spots, which against
Overpass is ~94 cold queries. Build it before a big Collections run; a GOL-built spot
and an Overpass-built spot produce byte-identical route payloads.

**Coverage comes from the manifest, not the code.** `build_gol.py` writes
`<gol>.regions.json` listing what actually went in, and `osmsource` routes off that.
Otherwise a deploy-tier GOL plus a 34-region catalog would send a Denver search to a
file with no Colorado in it and return an empty network dressed up as a real one.

This is a latency change, not a compliance one — Overpass's published fair-use
threshold (~10k queries/day) is far above our traffic. A covered viewport goes from
~1.3 s to ~14 ms, and Angeles Crest from ~21 s to ~84 ms.

**Read `docs/local-osm-data.md` before touching this.** The two things that break
silently:

- **`gol build` must pass `--waynode-ids`.** GeoDesk otherwise reports untagged way
  vertices as `id` 0 — and untagged is what a plain street intersection is. Measured:
  15,773 of 15,817 way nodes came back as 0 without it, all collapsing onto one graph
  node. `geodesk_source` raises `MissingWaynodeIds` rather than build that graph.
- **Coverage requires *total* containment.** A partly-overlapping bbox served from the
  GOL returns a network truncated at the file's edge, which
  `overpass._contiguous_inbbox_runs` then trims into something that looks real.
  Partial overlap falls back to Overpass.

`describe_source()` names the source before the fetch so the UI can distinguish local
GOL / warm Overpass cache / cold Overpass query — three cases that differ by three
orders of magnitude in latency and used to share one status message.

`geodesk_source` reuses `overpass.py`'s tag parsing and bbox trimming rather than
reimplementing them, and `test_osmsource.py::test_geodesk_and_overpass_agree` runs one
bbox through both. Geometry is compared as a ratio (a GOL is a snapshot; ways edited
upstream since the build legitimately differ) but **tags are compared exactly** — one
gotcha there is that GeoDesk returns numeric tag values as numbers (`mtb:scale` as
`int`), which `geodesk_source._tags` normalises back to strings.

---

## Config and parameters

All tunable parameters live in `backend/config.py` as a `SearchConfig` dataclass with defaults. The goal during development is to have lots of knobs; unused ones will be pruned before launch.

```python
@dataclass
class SearchConfig:
    # Graph construction
    # Default 10m matches 3DEP 1/3 arc-sec resolution (continental US).
    # Set to 1.0 in areas with 1m lidar coverage; set to 30.0 when falling back to SRTM.
    # Finer sampling than the underlying dataset resolution gives false precision.
    elevation_sample_interval_m: float = 10.0
    peak_search_radius_m: float = 75.0           # ~1 city block; avoids duplicate peaks on same hilltop
    peak_min_elevation_delta_m: float = 4.0      # Filters flat-area noise; catches real hills
    grade_inflection_threshold: float = 0.04     # 4% grade change triggers an inflection node

    # Pathfinding
    max_paths_per_node: int = 3                  # Allows competing lines without combinatorial blowup
    max_routes: int = 25                         # Caps total routes emitted; keeps sidebar manageable
    priority_weight_speed: float = 1.0           # Multiplier on arrival speed in priority tuple

    # Path termination — profile-dependent values set per RiderProfile, not globally
    # min_continue_speed_kmh: longboard=5, cyclist=8
    # min_route_length_m:     longboard=60, cyclist=150
    # Flat sections do NOT terminate a path; routes may span multiple drops connected by flat.

    # Flow score penalties (each occurrence deducted from 100; mapped to A–F letter grade)
    flow_penalty_stoplight: float = 30.0
    flow_penalty_bigger_road: float = 25.0
    flow_penalty_equal_road: float = 15.0
    flow_penalty_stop_sign: float = 10.0       # Softer given incomplete OSM coverage
    flow_penalty_surface_cobble: float = 30.0  # Unpredictable grip, most dangerous surface
    flow_penalty_surface_gravel: float = 20.0  # Slide-out risk at speed
    flow_penalty_surface_unpaved: float = 15.0 # Could be smooth dirt; penalized not excluded

    # Physics — air density
    air_density_kg_m3: float = 1.225

    # Trail difficulty: see SAC_SCALE_TO_DIFFICULTY. `mtb:scale` 0-6, with `sac_scale`
    # as a coarse fallback. Untagged is None (unknown), never 0 (easy).


# Rider profiles — used as presets in the UI and as defaults for pathfinding Crr
RIDER_PROFILES = {
    "longboarder": RiderParams(
        weight_kg=80,
        drag_coefficient=0.75,    # Moderate tuck (full race tuck ~0.55, upright ~1.0)
        frontal_area_m2=0.35,     # CdA ≈ 0.26
        crr_physics=0.012,        # Urethane wheels on asphalt
        crr_pathfinding=0.020,    # Inflated ~67% to compensate for no air resistance in pathfinding
        min_continue_speed_kmh=5,
        min_route_length_m=60,
    ),
    "cyclist_upright": RiderParams(
        weight_kg=85,
        drag_coefficient=0.88,    # City/hybrid bike, sitting tall
        frontal_area_m2=0.42,     # CdA ≈ 0.37
        crr_physics=0.004,        # Clincher tires on asphalt
        crr_pathfinding=0.008,
        min_continue_speed_kmh=8,
        min_route_length_m=150,
    ),
    "cyclist_drops": RiderParams(
        weight_kg=80,
        drag_coefficient=0.70,    # Road bike on drop bars
        frontal_area_m2=0.32,     # CdA ≈ 0.22
        crr_physics=0.003,        # Road tires on asphalt
        crr_pathfinding=0.006,
        min_continue_speed_kmh=8,
        min_route_length_m=150,
    ),
    # Dirt. Higher Crr, a lower speed floor (a tech descent at 6 km/h is normal), and
    # a max_speed_kmh ceiling — see below.
    "gravel": RiderParams(..., crr_physics=0.010, min_continue_speed_kmh=6,
                          max_speed_kmh=55, rough_surface_categories=("cobblestone",)),
    "mtb":    RiderParams(..., crr_physics=0.030, min_continue_speed_kmh=4,
                          max_speed_kmh=40, rough_surface_categories=()),
}
```

**`max_speed_kmh` is a stand-in for a brake, which `physics.py` does not model.** On
tarmac the omission survives — drag and Crr land near reported speeds. On a loose 15%
fire road the force balance computes 70 km/h where a real rider is braking at 30, because
what limits them is traction, sightline and rock, none of which are forces. Only the dirt
profiles set it; both `simulate_speed_profile` and `_speed_at_node` clamp to it (the
latter matters because arrival speed is the priority-queue sort key). **A capped route's
`top_speed_kmh` reads "at the limit", not "this is how fast the hill is."**

**`rough_surface_categories` makes flow scoring rider-relative.** The surface penalty
deducts per edge, so a long gravel descent floors the score at zero — right for a road
cyclist who wanted tarmac, wrong for a gravel rider who came for the gravel. The penalty
*values* stay in `SearchConfig`; the *set they apply to* rides on the profile.

Parameters can be overridden per-request. The frontend sends only non-default values in the request body.

---

## C++ extension (post-MVP)

The C++ pathfinding extension lives in `cpp/`. It must expose an identical interface to `pathfinding.py` so the backend can swap implementations without changing any other code:

```python
# Both implementations must support this call signature:
routes = find_routes(graph: nx.DiGraph, config: SearchConfig, toggles: Toggles) -> Iterator[Route]
```

Use pybind11 for bindings. Build with CMake. The Python implementation in `pathfinding.py` is the reference; the C++ version is a performance optimization, not a rewrite of logic. If the algorithm changes, update both.

---

## Development notes

- **Animate candidates mode**: a checkbox in the UI (off by default) that flashes candidate paths on the map as the algorithm explores them. Implemented entirely on the frontend — the backend emits an additional `candidate` SSE event type when this mode is active (passed as a flag in the search request). Has no effect on pathfinding performance. May be removed if pathfinding is fast enough that the animation is imperceptible.
- **Physics model sync**: `physics.py` and `utils/physics.ts` must implement the same model, including the `max_speed_kmh` clamp. Add a comment in both files referencing the other. When changing one, always update the other.
- **Route wire shape**: adding a field to `pipeline.route_payload()` does *not* update the committed `backend/data/collections.json` — previously-built spots keep the old shape until rebuilt. `test_collections.py::test_committed_routes_match_the_current_wire_shape` fails when they drift; the fix is to re-run the collections build.
- **Grade color thresholds**: defined once in `utils/gradeColor.ts` and referenced from map layer paint expressions, Chart.js bar colors, and sparkline SVGs. Do not hardcode these values elsewhere.
- **Chart.js registration must list the controllers, and only production notices**: any component using Chart.js has to `ChartJS.register(...)` its controllers (`BarController`, `LineController`, …), not just its scales and elements. Omitting them *appears* to work everywhere you would look: importing `react-chartjs-2` registers all eight controllers as a side effect of its typed-chart exports. Those calls are `/* #__PURE__ */` and the package sets `"sideEffects": false`, so Rollup deletes them from a production bundle — and only there does the chart throw `"bar" is not a registered controller` on mount, which in React means the surrounding panel silently renders nothing. Dev, vitest and jsdom all tree-shake nothing and stay green. This shipped once already. It is guarded two ways: `ProfilePanel.registration.test.ts` mocks `react-chartjs-2` away to reproduce the tree-shaken condition in the fast suite, and the Playwright suite runs against the real built bundle.
- **Frontend tests come in two layers**: `npm test` (vitest + jsdom, `src/**`) for logic and component behaviour, and `npm run test:e2e` (Playwright, `frontend/e2e/`) which builds the production bundle, serves it exactly as Cloudflare Pages does, and drives it in Chromium. The split is load-bearing rather than stylistic — vitest never tree-shakes or minifies, so a whole class of bug (see the Chart.js note above) is invisible to it by construction. Anything that could differ between source and bundle belongs in `e2e/`. The shared fixture there fails a test on *any* console error, which is what catches a React subtree that throws and renders nothing while the page still looks alive. Note vitest's `include` is pinned to `src/**` so its default glob doesn't try to run the Playwright `.spec.ts` files.
- **Flow score**: computed in `scoring.py`, attached to the route before emission. The formula weights traffic signals, major road crossings, and rough surface types. It is displayed in the UI but does not affect route ranking.
- **Between-request caching**: Overpass and elevation queries for the same bbox and road type combination are expensive and rarely change. A near-term optimization (post-MVP) is a bbox-keyed in-memory or Redis cache for the raw OSM graph and elevation data, so re-searches with different toggles or parameters feel instant. Cache invalidation can be time-based (e.g. 24h TTL).
- **Serving the frontend in production**: Hillbomb deploys as **two things**, split along the line of what needs a server. The SPA and the collections JSON are static and identical for every visitor, so they sit on Cloudflare Pages; `POST /search` is the only thing that does per-request work, so it stays on Cloud Run. Every URL is resolved through `frontend/src/api.ts`: collections are always *relative* (same origin as the app in every environment), and search goes to `VITE_API_BASE`, which is empty everywhere except a production build. That empty default is what keeps `npm run dev`, the tests, and `docker run` on the old single-origin behaviour — the static block at the end of `main.py` still serves the SPA and `index.html` still goes out `no-store`, it just isn't the production path any more. The one cross-origin request is the SSE POST, so `HILLBOMB_ALLOWED_ORIGINS` must name the site origin in production. Build both halves with `scripts/build-static.sh`; see `docs/deploy.md`.
- **`GET /api/where` is the one URL on the static half that differs per visitor.** A Cloudflare Pages Function (`functions/api/where.js`) reads `request.cf` and returns the visitor's approximate lat/lon, so the Collections tab can open the region nearest them instead of always San Francisco. It is picked up automatically by `wrangler pages deploy` from the `functions/` directory at the repo root — nothing in `build-static.sh` produces it, and it exists **only** on the Cloudflare deploy. Under `npm run dev`, `docker run`, and the tests it 404s (or hits FastAPI's SPA fallback and returns HTML), and `useIpLocation` treats every one of those as "no location" and does nothing. Nothing may depend on it resolving. Its response must stay `Cache-Control: no-store`; a cached copy would pin every visitor to whichever metro warmed that colo first, which looks like working code from any single location.
- **`SearchControls` component**: the repo structure names this `SearchBar` but it covers toggles, road types, physics params, and advanced settings. Rename to `SearchControls` before the codebase grows.