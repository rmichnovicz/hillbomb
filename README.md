# Hillbomb

Find great downhill routes — "hill bombs" — for skateboarders and cyclists.

Pan the map to somewhere hilly, hit **Search this area**, and Hillbomb pulls the road network from
OpenStreetMap, drapes it over USGS lidar elevation data, and runs a greedy descent search to find the
lines that actually go down. Routes stream into the sidebar as they're found, each with a simulated
speed profile and a flow score that grades how much a run gets interrupted by lights, crossings, and
rough pavement.

## How it works

A search runs as a pipeline, streamed back to the browser over Server-Sent Events so routes appear as
soon as they're found rather than all at once at the end:

1. **Overpass** (`backend/overpass.py`) — fetch the classified road network in the viewport.
2. **Elevation** (`backend/elevation.py`) — enrich each node with elevation, using a resolution
   cascade: USGS 3DEP 1m lidar where it exists, 3DEP 1/3 arc-second (~10m) across the continental US,
   SRTM (~30m) globally. 3DEP is read straight from Cloud-Optimized GeoTIFFs on S3 via HTTP range
   requests, so there's nothing to download up front.
3. **Graph** (`backend/graph.py`) — build a sparse directed graph of intersections, peaks, valleys,
   and grade inflection points. One-way streets get a single directed edge.
4. **Pathfinding** (`backend/pathfinding.py`) — greedy descent from a priority queue, seeded at peaks.
   Paths terminate on a hard stop (stoplight, stop sign, crossing a bigger road), when they slow below
   a walking pace, or when they bottom out in a valley.
5. **Physics** (`backend/physics.py`) — simulate speed over the route from gravity, air drag, and
   rolling resistance.
6. **Scoring** (`backend/scoring.py`) — grade each route A–F on how well it flows.

The whole road network gets fetched, but only roads you'd actually ride are traversable. Bigger roads
stay in the graph as non-traversable edges purely so a descent can *detect* — and stop at — the moment
it would cross one.

## Running it

Backend (Python 3.11+):

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cd .. && uvicorn backend.main:app --reload --port 8000
```

Frontend (Node 20+), in a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Open the URL Vite prints. It proxies `/search` to the backend on port 8000, so both need to be
running.

Elevation data is fetched from public USGS S3 buckets anonymously — no AWS account or API keys
needed. The first search in a new area is slow while elevation is fetched; results are cached to disk
and keyed on geometry, so re-searching the same area with different settings is fast.

## Tests

```bash
# Backend — unit and integration
python -m pytest -m "not integration"   # fast, no network
python -m pytest                        # includes tests that hit real Overpass/USGS endpoints

# Frontend
cd frontend && npm test
```

Integration tests are marked so they can be deselected; they hit live external services and will fail
if those are down or rate-limiting.

## Rider profiles

Physics and pathfinding are tuned per rider. Longboarders coast further on urethane wheels and are
happy with short steep drops; cyclists need longer runs and carry speed differently. Presets live in
`backend/config.py` (`RIDER_PROFILES`) and every parameter is overridable per request — the sliders in
the UI re-run the simulation client-side without a round-trip.

## A few caveats

- **Stop signs are badly mapped in OSM.** The "avoid stop signs" toggle only knows about
  `highway=stop` nodes, and plenty of real stop signs aren't tagged. Traffic signals are mapped much
  better, so that toggle is reliable.
- **This suggests routes on public roads.** It doesn't know about traffic, construction, road
  closures, or whether a run is a good idea. Ride within your abilities and obey traffic law.

## Layout

```
backend/    FastAPI app, pipeline stages, tests
frontend/   React + MapLibre GL + Chart.js
```

`CLAUDE.md` documents the architecture, conventions, and the reasoning behind key decisions in much
more depth — start there if you're changing anything.

## License

MIT — see [LICENSE](LICENSE).
