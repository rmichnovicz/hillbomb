# Hillbomb — Product Requirements Document

## Overview

Hillbomb is a web app for finding great downhill routes ("hill bombs") for cyclists and skateboarders. Users explore a map, define a search area, and the app finds, scores, and visualizes routes where a rider can achieve high speeds on a sustained downhill run with minimal dangerous intersections.

---

## Target Users

Cyclists and skateboarders looking to discover fast, fun downhill routes in their city. No account required for MVP. The app should work equally well for exploring a familiar neighborhood or scoping out routes in a new city.

---

## Core Concepts

**Hill bomb route**: A continuous downhill path along public roads or paths where a rider can achieve meaningful speed, with few or no interruptions from traffic signals or road crossings more major than the route itself.

**Flow score**: A secondary quality rating (displayed but not used for ranking) reflecting how clean and uninterrupted a route is — penalizes traffic signals, major road crossings, and poor surface types. Displayed as a letter grade (A–F) alongside each route.

**Rider settings**: Physical parameters used for the speed simulation — rider weight, drag coefficient, frontal area, and rolling resistance. These affect the speed profile visualization but not the pathfinding ranking.

---

## Tech Stack

- **Frontend**: React, MapLibre GL JS, react-map-gl, OpenFreeMap or Protomaps vector tiles
- **Backend**: Python, FastAPI
- **Graph / pathfinding**: NetworkX (MVP), pybind11 C++ extension (post-MVP performance optimization)
- **Physics simulation**: NumPy
- **OSM data**: Overpass API (queried at search time; self-hosted OSM is a far-future optimization)
- **Elevation data**: Open-Topo-Data (queried per node at graph-build time)
- **Streaming**: Server-sent events (SSE)
- **Route persistence**: Browser localStorage (no backend storage for MVP)

---

## Map & Search

### Search area
- The search area defaults to the current map viewport (bounding box).
- A "search this area" button appears when the user pans or zooms, matching the Google Maps pattern.
- The backend enforces a maximum bounding box size and a maximum total road length cap (set generously so it is rarely hit in practice; exact values TBD during development).
- A manual coordinate input is a post-MVP power-user feature.

### Map library
MapLibre GL JS. Chosen for its open-source BSD license, native OSM vector tile support, custom route overlay capabilities (color-coded by speed/grade), and compatibility with react-map-gl.

---

## Route Finding

### Graph construction
1. Query Overpass API for all ways (roads, paths) within the bounding box, filtered by the user's road type preferences.
2. Query Open-Topo-Data for elevation at each OSM node. Elevation is sampled at an interval matching the resolution of the elevation dataset (~30m for SRTM, the default Open-Topo-Data source). Sampling finer than the dataset resolution gives false precision. If a higher-resolution source is used, the interval should be revisited.
3. Build a sparse directed graph containing:
   - All intersection nodes
   - Local elevation peaks (candidate start points): local maxima within a configurable radius, above a configurable minimum elevation delta from surroundings
   - Local elevation valleys (candidate end points): local minima by the same logic
   - Significant grade inflection points: nodes where grade changes by more than a configurable threshold
   - **Edge direction**: respect OSM `oneway=yes` tags. One-way streets are represented as single directed edges; two-way streets get edges in both directions. A route may only travel in the legal direction of travel.
4. Bridges (`bridge=yes`) and tunnels (`tunnel=yes`) are treated as straight-line segments: ignore intermediate shape points, compute grade from endpoint elevations only, do not sample elevation in between.

### Pathfinding algorithm
A greedy descent search driven by a global priority queue.

**Priority queue tuple**: `(-is_extending_existing_path, -arrival_speed, -elevation)`
- Extending an existing active path always takes priority over starting a new one at the same elevation.
- Among same-type operations, faster arrival speed takes priority, then higher elevation.
- Implemented as a min-heap (Python `heapq`) with negated values.
- Stale entries (from paths that have since been terminated or capped) are discarded on pop via lazy deletion: each queue entry carries a path ID and sequence number, checked against current path state on pop.

**Descent rule**: Prefer edges where the next node is lower than the current node. The priority queue naturally deprioritizes paths that slow down on uphills via the arrival speed term, so no hard uphill cap is enforced — a path that can crest a rise with enough momentum will simply rank lower until it regains speed.

**Path extension**: On each pop, extend the path to the next node by following the best available downhill edge. "Best" is defined by the pathfinding score function: grade × length, penalized by intersection crossings per the active toggle settings.

**Node cap**: A configurable `max_paths_per_node` limits how many active (in-progress) paths may simultaneously pass through any given node. This prevents combinatorial explosion at busy intersections without requiring merge logic. The cap applies to active paths only; completed paths that terminate at a node are not counted.

**Path termination**: A path is finalized (emitted as a complete route) when any of the following occur:
- The path reaches a node where `max_paths_per_node` is already at capacity
- The path hits a hard stop per the active toggle settings (stoplight, major road crossing, etc.)
- The rider's estimated speed drops below `min_continue_speed_kmh` (profile-dependent; lower for longboards which coast more freely)
- The path reaches a valley node

Flat sections do not terminate a path — a route may include a flat connector between two steep drops and be treated as a single run.

**Minimum route filter**: Before emitting, routes are filtered only by minimum length (profile-dependent; shorter for longboards where a single steep block is meaningful). No minimum average grade or top speed filter — let the ranking surface quality, don't discard results preemptively.

### Physics for pathfinding vs. visualization
- **Pathfinding**: Uses grade as a proxy for speed potential with an inflated rolling resistance coefficient to compensate for the absence of air resistance. Fast to compute, conservative enough to avoid dead-end paths.
- **Visualization**: Full physics simulation using NumPy — models air resistance, rolling resistance, and rider parameters over the route's elevation profile to produce a speed-over-distance curve.
- Rider settings (weight, drag coefficient, frontal area, rolling resistance) update the speed visualization live without re-running pathfinding.

### Rider profiles

Three built-in presets. All are editable via the rider settings panel.

| Parameter | Longboarder | Cyclist (upright) | Cyclist (drop bars) |
|---|---|---|---|
| Weight (kg) | 80 | 85 | 80 |
| Drag coefficient (Cd) | 0.75 | 0.88 | 0.70 |
| Frontal area (m²) | 0.35 | 0.42 | 0.32 |
| CdA | 0.26 | 0.37 | 0.22 |
| Crr — physics sim | 0.012 | 0.004 | 0.003 |
| Crr — pathfinding proxy | 0.020 | 0.008 | 0.006 |

Notes:
- Longboarder modeled in a moderate tuck (not full race tuck, not fully upright). Full race tuck CdA is ~0.18; fully upright is ~0.45.
- Cyclist upright is a city/hybrid bike rider sitting tall — the most common hill bombing setup.
- Pathfinding Crr is inflated ~60–70% above the physics Crr to compensate for the absence of air resistance in the grade-proxy model, making path termination thresholds appropriately conservative.

### Route scoring and ranking
Routes are ranked by **estimated top speed** (primary), then **run length before forced stop** (secondary). Flow score is computed and displayed separately but does not affect ranking.

### Configurable parameters (all tunable during development, pruned later)

**Graph construction**
| Parameter | Default | Rationale |
|---|---|---|
| `elevation_sample_interval_m` | 30 | Matches SRTM dataset resolution (~30m); finer sampling gives false precision |
| `peak_search_radius_m` | 75 | ~1 city block radius; avoids duplicate peaks on the same hilltop |
| `peak_min_elevation_delta_m` | 4 | Filters flat-area noise; low enough to catch real hills in mildly hilly cities |
| `grade_inflection_threshold` | 0.04 | 4% grade change triggers an inflection node; catches meaningful steep-to-flat transitions |

**Pathfinding**
| Parameter | Default | Rationale |
|---|---|---|
| `max_paths_per_node` | 3 | Allows a few competing lines through busy intersections without combinatorial blowup |
| `max_routes` | 25 | Caps total routes emitted; keeps the sidebar manageable in very hilly cities |
| `priority_weight_speed` | 1.0 | Multiplier on arrival speed in the priority tuple; tune to shift balance between speed and elevation |

**Path termination**
| Parameter | Longboarder | Cyclist | Rationale |
|---|---|---|---|
| `min_continue_speed_kmh` | 5 | 8 | Longboard wheels coast more freely at low speed; bikes stall out sooner |
| `min_route_length_m` | 60 | 150 | A single steep block is meaningful on a longboard; bikes want more sustained distance |

**Flow score weights** (each occurrence deducted from 100; mapped to A–F letter grade)
| Parameter | Default | Rationale |
|---|---|---|
| `purity_penalty_stoplight` | 30 | Hard interruption, significant danger |
| `purity_penalty_bigger_road` | 25 | Significant cross-traffic danger |
| `purity_penalty_equal_road` | 15 | Meaningful cross-traffic risk |
| `purity_penalty_stop_sign` | 10 | Softer given incomplete OSM coverage |
| `purity_penalty_surface_cobble` | 30 | Unpredictable grip, bone-rattling at speed — most dangerous surface |
| `purity_penalty_surface_gravel` | 20 | Slide-out risk at speed |
| `purity_penalty_surface_unpaved` | 15 | Could be a smooth dirt path; penalized but not assumed unrideable |

---

## Intersection Avoidance Toggles

All toggles are **on by default**. Each can be independently disabled.

| Toggle | Behavior when on |
|---|---|
| Avoid stoplights | Hard stop: terminate path at any node tagged `highway=traffic_signals` |
| Avoid stop signs | Hard stop: terminate path at any node tagged `highway=stop` (note: OSM stop sign coverage is incomplete) |
| Avoid intersecting with bigger roads | Hard stop: terminate path where the route crosses a way of higher OSM highway classification |
| Avoid intersecting with equal roads | Hard stop: terminate path where the route crosses a way of the same OSM highway classification |

Tunnels are a separate optional toggle: tunnels may be excluded from routes entirely or flagged in the UI, since a tunnel mid-route is a significantly different riding experience.

---

## Search Controls

All search parameters are accessible before running a search. Changing any of these requires re-running the search (unlike rider settings, which update live post-search).

### Intersection avoidance toggles
See "Intersection Avoidance Toggles" section — all exposed in the UI, all on by default.

### Road type filter
Users can toggle which OSM `highway` types are included in the search graph. Presented as a checklist of road types from most to least major. Defaults:

| Road type | Default | Notes |
|---|---|---|
| `motorway`, `trunk` | Off | Not suitable for cyclists or skateboarders |
| `primary` | Off | High traffic; excluded by default |
| `secondary` | Off | Moderate traffic; excluded by default |
| `tertiary` | On | Quieter arterials; often good for long descents |
| `unclassified` | On | |
| `residential` | On | Core use case |
| `service` | On | Alleys, driveways; can have great steep sections |
| `cycleway`, `path` | On | Ideal when available |
| `living_street` | On | Shared pedestrian/vehicle space; low traffic |

### Physics parameters
All rider physics parameters are exposed in the search controls panel as well as the post-search rider settings panel. Pre-search, they affect pathfinding (via the Crr proxy). Post-search, adjusting them only updates the speed profile visualization without re-running pathfinding.

A **rider profile** selector (Longboarder / Cyclist upright / Cyclist drop bars) sets all physics parameters at once. Individual parameters can then be overridden via sliders:
- Rider weight (kg)
- Drag coefficient (Cd)
- Frontal area (m²)
- Rolling resistance — physics sim (Crr)
- Rolling resistance — pathfinding proxy (Crr pathfinding)

### Advanced parameters
A collapsible "advanced" section exposes the pathfinding tuning parameters for power users and development:
- `max_paths_per_node`
- `max_routes`
- `peak_search_radius_m`
- `peak_min_elevation_delta_m`
- `grade_inflection_threshold`
- `priority_weight_speed`
- `min_continue_speed_kmh`
- `min_route_length_m`
- Animate candidates checkbox

---

## Road & Surface Types

Surface type (`surface` tag) is not used to exclude routes but contributes to the flow score: gravel, cobblestone, and unpaved surfaces lower flow. Users cannot filter by surface type directly, but the flow score badge on each route card reflects surface quality.

---

## Route Visualization

### Route list (sidebar)
- Routes displayed as cards, ranked by top speed.
- Each card shows: route name (auto-generated from street names), top speed, run length, descent (m), and a sparkline elevation thumbnail color-coded by grade.
- Route name is derived from the street name of the steepest segment. If that segment has no name, fall back to the starting street name.
- Flow score displayed as a badge (A–F) on each card, not affecting rank order.
- Selecting a card highlights the route on the map and opens the profile panel.

### Map display
- Active route rendered as a solid colored polyline.
- Other candidate routes rendered as dimmed dashed polylines.
- Start and end nodes marked with distinct icons.
- Hovering the elevation profile chart scrubs a pin along the corresponding point on the map route, and vice versa.

### Elevation and speed profile panel
A bottom panel that opens when a route is selected, showing:
- **Elevation profile**: bar chart with bars color-coded continuously by grade (green → yellow → orange → red → dark red for increasing steepness)
- **Speed line**: line overlay on a secondary Y axis showing estimated speed over distance, computed from the full physics model
- Forced stop events (stoplights, major crossings) marked on the speed line with icons
- Stat bar: estimated top speed, average speed, total descent, run length, flow score
- Scrub interaction: hovering the chart moves a cursor and syncs a pin on the map

### Rider settings panel
A tab alongside the profile panel with the same physics sliders as the pre-search controls. Adjusting any slider immediately re-runs the NumPy physics simulation and updates the speed line and stat bar without re-running pathfinding.

---

## Streaming Loading State

Search results are streamed from the backend via SSE in the following phases:

1. `status: querying Overpass API...`
2. `status: fetching elevation data for N nodes...`
3. `status: building route graph...`
4. `route: { route_id, geometry, metadata, flow_score }` — emitted immediately when a path is finalized by pathfinding
5. `physics: { route_id, speed_profile, top_speed, avg_speed }` — emitted when the NumPy simulation for that route completes
6. `candidate: { geometry }` — emitted during pathfinding exploration (only when animate candidates mode is active)
7. `done`
8. `error: { message }` — emitted if a fatal error occurs (Overpass timeout, elevation API failure, etc.); the frontend shows an inline error message and keeps any routes already received

`route` and `physics` events are decoupled so route cards appear immediately without waiting for the physics sim. Cards show a loading shimmer on the speed stat until the matching `physics` event arrives. Route cards are sorted into rank order as they arrive; rank order may update as more routes stream in.

A **stop button** is visible while a search is in progress. Clicking it closes the SSE connection on the client side; any routes already received are kept and displayed. The backend does not need explicit notification — it will encounter a broken pipe on the next SSE write and exit the stream naturally.

An optional **animate candidates** mode (checkbox in the UI, off by default) flashes candidate paths on the map as the algorithm explores them. This is a development/debugging aid and has no effect on pathfinding performance — the animation is purely a frontend rendering decision. If pathfinding is fast enough that the animation is imperceptible, the feature may be removed.

---

## Route Persistence

Routes are saved to **browser localStorage** for MVP. No backend storage or user accounts are required.

Sharing: routes can be shared via a generated URL encoding the bounding box and route parameters. Deep-linking to a specific route is a post-MVP feature.

---

## Roadmap

### MVP
- Viewport-based search with "search this area" button
- Overpass + Open-Topo-Data pipeline
- Greedy descent pathfinding in NetworkX
- Intersection avoidance toggles (stoplight, stop sign, bigger road, equal road)
- Route list with sparklines and purity badge
- Elevation + speed profile panel with scrub interaction
- Rider settings panel (live physics update)
- SSE streaming with phase status messages
- localStorage route saving

### Post-MVP (prioritized)
1. **C++ pathfinding extension** via pybind11 — drop-in replacement behind the same Python interface
2. **URL-based route sharing** — encode route params in shareable link
3. **Tunnel toggle** — option to exclude tunnels from routes
4. **Manual bbox input** — coordinate entry for power users
5. **User accounts** — save and name routes across sessions and devices; initially via session token or localStorage, eventually with a proper auth system
6. **Pre-cached featured routes** — curated routes seeded manually, explorable without running a search
7. **Self-hosted OSM data** — replace Overpass with a local PostGIS + osm2pgsql stack for performance and rate-limit independence
8. **Path hierarchy** — store paths sharing a common suffix as a trie-like structure for deduplication and UI grouping
