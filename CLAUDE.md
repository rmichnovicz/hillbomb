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
│   │   │   ├── Collections/   # Curated famous descents tab (browse by city → spot routes)
│   │   │   ├── ProfilePanel/  # Elevation + speed profile chart, scrub interaction
│   │   │   ├── RiderSettings/ # Physics parameter sliders
│   │   │   └── SearchControls/ # "Search this area" button, toggle controls, physics params, advanced settings
│   │   ├── hooks/
│   │   │   ├── useSearch.ts       # SSE connection, streaming route ingestion
│   │   │   ├── useCollections.ts  # Curated collections index + per-spot fetch
│   │   │   ├── usePhysics.ts      # Client-side physics sim (NumPy equiv in JS)
│   │   │   └── useLocalStorage.ts # Saved routes persistence
│   │   ├── types/             # Shared TypeScript types (Route, Node, Edge, RiderParams)
│   │   └── utils/
│   │       └── gradeColor.ts  # Grade → color mapping (shared by chart and sparklines)
├── backend/
│   ├── main.py            # FastAPI app, SSE endpoint, /collections endpoints
│   ├── pipeline.py        # Shared pipeline core — used by BOTH main.py and the collections builder
│   ├── overpass.py        # Overpass API queries, way parsing
│   ├── elevation.py       # Open-Topo-Data queries, per-node elevation enrichment
│   ├── graph.py           # Sparse graph construction, peak/valley detection
│   ├── pathfinding.py     # Greedy descent algorithm, priority queue, route scoring
│   ├── physics.py         # NumPy speed profile simulation
│   ├── scoring.py         # Flow score computation
│   ├── spots.py           # Curated famous descents (the Collections source data)
│   ├── config.py          # All tunable parameters (see Parameters section)
│   ├── scripts/
│   │   └── build_collections.py  # Offline builder: Spot → routes → collections.json
│   └── data/
│       └── collections.json      # Build output; COMMITTED
├── cpp/                   # C++ pathfinding extension (post-MVP)
│   ├── pathfinding.cpp
│   ├── CMakeLists.txt
│   └── bindings.cpp       # pybind11 bindings, must expose same interface as pathfinding.py
├── docs/
│   ├── collections.md     # Collections feature doc — read before touching Collections
│   └── research/          # Raw research backlog (famous descents; 10 not yet promoted to spots.py)
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

1. **Overpass query** (`overpass.py`): fetch all ways in bbox matching road type filter. Parse nodes and way geometry.
2. **Elevation enrichment** (`elevation.py`): query the `ElevationService` for elevation at each node. Sample at `elevation_sample_interval_m` intervals along ways. Cache results within a request. See **Elevation data** section for source details. Elevation is fetched **only for nodes on a traversable way** — non-traversable ways (bigger roads, surface/rank-excluded) are kept in the graph for crossing detection, which uses road rank + way name only, never elevation; their nodes stay at `elevation=0.0`. The disk cache file is keyed on the **full network geometry** (toggle-independent, passed as `cache_coords`), not the queried subset, and stores a per-coordinate map, so re-searches with different surface/road filters reuse every coordinate already fetched and only query newly-needed ones. Peak/valley detection in `graph.py` is correspondingly restricted to nodes touched by a traversable edge so the unfetched zeros can't create spurious peaks or pollute a real node's neighbourhood.
3. **Graph construction** (`graph.py`): build sparse graph with intersection nodes, peak nodes, valley nodes, and grade inflection nodes. Tag bridge/tunnel ways and treat them as straight-line segments (start and end elevation only, no intermediate sampling).
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

A hand-curated set of famous descents (Hawk Hill, etc.) grouped by city, precomputed
offline and served as static JSON — so a new user has world-class routes to look at
without panning around hunting for a hill. Roads don't move, so we run the real pipeline
once, offline, and commit the output rather than paying ~15 s of Overpass + elevation per
view.

```
GET /collections         → index: spots by city, metadata + headline stats, NO geometry
GET /collections/{slug}  → one spot with its full routes
```

Split in two because one spot's routes are ~65 KB of geometry/elevation/speed samples;
the index stays small enough to load on tab open, and the heavy part loads per spot.

**Read `docs/collections.md` before touching this.** Short version: spots are data in
`backend/spots.py`; `python -m backend.scripts.build_collections` builds them; the
output is committed. The field that decides whether a spot works is `osm_way_names` —
it must be the exact OSM `name` tag ("Conzelman Road"), not the popular name ("Hawk Hill").

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

| Priority | Dataset | Resolution | Coverage | Source |
|---|---|---|---|---|
| 1 | USGS 3DEP 1m | ~1m (lidar) | Partial US — urban areas, patchy | S3 COG |
| 2 | USGS 3DEP 1/3 arc-sec | ~10m | Continental US | S3 COG |
| 3 | SRTM 1 arc-sec | ~30m | Global | Local tiles |

**Minimum for continental US is 1/3 arc-sec.** SRTM is the global fallback only — outside the US, or if 3DEP COG queries fail.

### Access strategy

**3DEP (both 1m and 1/3 arc-sec)**: queried as Cloud-Optimized GeoTIFFs (COGs) directly from USGS S3 via `rasterio`. No local storage required — rasterio fetches only the HTTP byte ranges needed for the queried coordinates. Cost is negligible at Hillbomb's query volume.

```python
import rasterio

# rasterio handles HTTP range requests transparently
with rasterio.open("s3://prd-tnm-opendata/StagedProducts/Elevation/13/TIFF/...") as src:
    elevations = [val[0] for val in src.sample(coords)]  # coords as (lon, lat)
```

**SRTM**: download tiles locally (~27GB global, less if restricted to needed regions). HGT tiles are queried with rasterio the same way.

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

- Coverage check for 1m is done once per bbox (not per point) using a pre-loaded coverage index.
- `elevation_sample_interval_m` in `SearchConfig` should match the resolution of the source actually used. The service sets this on the returned result so the graph builder uses the right interval.
- For bridges/tunnels, only the two endpoint coordinates are queried regardless of interval.

### Tile index for 1m coverage

1m lidar coverage is not uniform. Before querying 1m COGs, the service checks a lightweight coverage index (GeoJSON polygons of available 1m tiles, fetched from the TNM API at startup or bundled statically) to determine whether 1m data exists for the bbox. If not, skip directly to 1/3 arc-sec.

---

## OSM data notes

- **One-way streets**: the pathfinding graph is a directed graph (`nx.DiGraph`). Ways tagged `oneway=yes` get a single directed edge; all other ways get edges in both directions. The pathfinding algorithm must only traverse edges in their legal direction. `oneway=-1` means the way is one-way in the reverse of the geometry direction — handle this by reversing the edge. `cycleway:oneway` and similar tags may override the main oneway tag for bicycle travel; treat these as out-of-scope for MVP and document the limitation.
- **Stop sign coverage is incomplete in OSM**. The "avoid stop signs" toggle uses `highway=stop` nodes, but many stop signs are not mapped. This is expected behavior — document it in the UI tooltip for the toggle.
- **Traffic signal coverage is much better**. The "avoid stoplights" toggle is reliable.
- **Bridge/tunnel handling**: ways tagged `bridge=yes` or `tunnel=yes` are treated as straight-line segments. Intermediate shape points are ignored. Grade is computed from start-node elevation to end-node elevation over straight-line distance. Tunnels and bridges may each be excluded entirely via the `exclude_tunnels` / `exclude_bridges` toggles (pathfinding skips those edges). Bridges/tunnels whose straight-line span exceeds `max_bridge_span_m` are always dropped during graph construction.
- **Highway classification hierarchy** (for "avoid bigger/equal roads" toggles): `motorway > trunk > primary > secondary > tertiary > unclassified > residential > service > path/cycleway`. Link variants (e.g. `motorway_link`) are treated as equivalent to their parent class.
- **Fetch the whole network, filter for riding**: the "avoid bigger roads" toggle can only stop a descent at a road that exists in the graph. Rather than guess which bigger roads to fetch, the Overpass query always fetches the **entire classified road network** in the bbox (`overpass.ROAD_NETWORK_TYPES`, derived from `HIGHWAY_RANK`), independent of the rider's `road_types`. Keying the fetch on geometry alone also lets re-searches with different toggles/road settings reuse the cached OSM data. Each way is then tagged **traversable** in `main.py` — `highway ∈ road_types`, within `max_road_rank`, surface allowed — and `graph.py` carries that flag onto its edges. Pathfinding never expands onto a non-traversable edge (so bigger roads are never *ridden*), but their presence at a junction still triggers the bigger/equal-road hard stop via successor ranks. This adapts to any custom rideable set: narrow `road_types` to just `residential` and a crossing with a `tertiary` road is still detected.

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
}
```

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
- **Physics model sync**: `physics.py` and `usePhysics.ts` must implement the same model. Add a comment in both files referencing the other. When changing one, always update the other.
- **Grade color thresholds**: defined once in `utils/gradeColor.ts` and referenced from map layer paint expressions, Chart.js bar colors, and sparkline SVGs. Do not hardcode these values elsewhere.
- **Flow score**: computed in `scoring.py`, attached to the route before emission. The formula weights traffic signals, major road crossings, and rough surface types. It is displayed in the UI but does not affect route ranking.
- **Between-request caching**: Overpass and elevation queries for the same bbox and road type combination are expensive and rarely change. A near-term optimization (post-MVP) is a bbox-keyed in-memory or Redis cache for the raw OSM graph and elevation data, so re-searches with different toggles or parameters feel instant. Cache invalidation can be time-based (e.g. 24h TTL).
- **`SearchControls` component**: the repo structure names this `SearchBar` but it covers toggles, road types, physics params, and advanced settings. Rename to `SearchControls` before the codebase grows.