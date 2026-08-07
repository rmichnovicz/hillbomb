# Hillbomb

Hillbomb finds downhill runs (hill bombs) for skateboarders and cyclists.

Pan the map to somewhere hilly, hit **Search this area**, and it pulls the road network from
OpenStreetMap, drapes it over USGS elevation data, and runs a greedy descent search for the lines
that actually go down. Routes stream into the sidebar as the search finds them, each with a simulated
speed profile and a letter grade for how badly the run gets chopped up by lights, crossings, and bad
pavement. Every route downloads as GPX.

If you don't feel like hunting, the **Collections** tab has 94 known descents across 34 cities,
from Conzelman Road above the Golden Gate to the Downieville Downhill, already built and ready to
open.

Python + FastAPI on the back, React + MapLibre GL on the front, deployed as a static site on
Cloudflare Pages with a single search endpoint on Cloud Run.

## How a search works

Six stages, streamed to the browser over Server-Sent Events so routes show up as they finalize rather
than all at once at the end.

1. **Road network** ([`osmsource.py`](backend/osmsource.py)). Fetch every classified road in the
   viewport. Served from a local GeoDesk snapshot where one covers the bbox, from the Overpass API
   everywhere else.
2. **Elevation** ([`elevation.py`](backend/elevation.py)). Sample each node against the best DEM
   available for that area. See the cascade below.
3. **Graph** ([`graph.py`](backend/graph.py)). Build a sparse directed graph of intersections, peaks,
   valleys, and grade inflection points. One-way streets get one directed edge; `oneway=-1` gets
   reversed first.
4. **Pathfinding** ([`pathfinding.py`](backend/pathfinding.py)). Greedy descent off a priority queue
   seeded at peaks. A path ends when it hits a hard stop (signal, stop sign, crossing a bigger road),
   slows below walking pace, or bottoms out in a valley. Flat sections don't end it, so a route can
   link two steep drops with a connector between them.
5. **Physics** ([`physics.py`](backend/physics.py)). Integrate speed over the route from gravity, air
   drag, and rolling resistance.
6. **Flow score** ([`scoring.py`](backend/scoring.py)). Grade the route A through F on how much it
   gets interrupted.

**Fetch every road, ride only some of them.** Step 1 pulls the whole classified network, and each way
is then flagged traversable or not from your road types, rank ceiling, and surface filters.
Pathfinding won't expand onto a non-traversable edge, so you're never routed down an arterial, but the
arterial is still in the graph to trigger the stop when a descent crosses it. Fetching on geometry
alone also means changing toggles reuses the cached network.

**One pipeline, two callers.** [`pipeline.py`](backend/pipeline.py) holds the reusable middle:
traversability rules, surface classification, the physics-and-dedup-and-scoring finalizer, and
`route_payload()`, which is the single definition of a route's wire shape. Both the live `/search`
endpoint and the offline collections builder call it, so a curated route and a searched route come out
byte-identical. A test fails when the committed collections drift from the current payload shape.

## Where the data comes from

### Elevation

A resolution cascade, best available for the queried bbox:

| Dataset | Resolution | Coverage | Status |
|---|---|---|---|
| USGS 3DEP 1m lidar | ~1 m | Patchy, mostly urban US | Off by default |
| USGS 3DEP 1/3 arc-second | ~10 m | Continental US | The working default |
| SRTM 1 arc-second | ~30 m | Global | Fallback |

In practice almost everything comes from 1/3 arc-second. The 1m stage is implemented and sits behind
`HILLBOMB_USE_1M=true`, off because its coverage is patchy enough that the win is unreliable, and
checking for it means fetching a coverage index from the TNM API on startup, which costs cold-start
latency on every search whether or not the tile exists. Turning it on is one environment variable if
that tradeoff ever changes.

3DEP tiles are Cloud-Optimized GeoTIFFs on public USGS S3, read anonymously with no AWS account. A
search opens the tile by URL and does one windowed read per tile covering all its queried points, so a
2.5 km viewport over San Francisco pulls 1.7 MB in two range requests out of a 223 MB tile. That's
block granularity, not point granularity: GDAL fetches whole 512-pixel blocks overlapping the window,
which for float32 LZW runs about 850 KB each. Opening a tile costs nine HTTP round trips before any
pixels arrive, which is why the last eight stay open in an LRU.
`HILLBOMB_DEP13_MODE=download` pulls whole tiles instead, faster on warm repeats if you're working one
area hard. SRTM is the exception and does cache `.hgt` tiles locally.

Bridges and tunnels get their interior elevations replaced with a linear ramp between the two
endpoints. A DEM samples the ground, so without that correction a bridge reads as a plunge into the
creek bed and back out again.

### What actually gets cached

Everything hangs off one root, `HILLBOMB_CACHE_DIR`, defaulting to `~/.cache/hillbomb`:

| What | Written when |
|---|---|
| Overpass responses, 24 h TTL | Any bbox the local GOL doesn't cover |
| Per-coordinate elevation samples | Every search |
| SRTM `.hgt` tiles | Only outside 3DEP coverage |
| 3DEP tiles | Never, unless you opt into `download` mode |

On Cloud Run that root points at a GCS bucket mounted with gcsfuse, on a 30-day lifecycle rule. It's
there for the two sample caches, which then survive scale-to-zero and are shared between instances,
taking a repeat search of the same area from about 15 s to near-instant. Nothing needs it to be
correct: drop the volume and the service runs cold per instance.

### OSM

The source is picked per request: a local GeoDesk `.gol` snapshot when the viewport falls wholly
inside a region the file covers, public Overpass otherwise. Both paths return identical structures,
and a test runs one bbox through both. A covered viewport goes from about 1.3 s to 14 ms. Details in
[docs/local-osm-data.md](docs/local-osm-data.md).

The GOL ships inside the container image rather than in the bucket with the caches, which is backwards
from what its size suggests. GeoDesk queries it through an mmap, so a lookup is a scatter of small
random reads against whatever pages it needs. That's the access pattern gcsfuse handles worst, and
it's the same reason the 3DEP tiles stay as HTTP range reads instead of moving into the bucket. The
file is also immutable and versioned with the deploy, so there's nothing to share or expire. Immutable
data inside the image, disposable data outside it.

## Collections

Curated famous descents, grouped by city. Roads don't move, so instead of re-deriving Conzelman Road
on every page view, the real pipeline runs once offline and the output gets committed: 94 spots, 34
cities, 224 routes.

```bash
python -m backend.scripts.build_collections                            # everything
python -m backend.scripts.build_collections --spot hawk-hill-conzelman # one spot
python -m backend.scripts.build_collections --metadata-only            # copy edits, no route churn
```

A spot is a data entry in [`backend/spots.py`](backend/spots.py), so adding one is a list append plus
a build. The field that decides whether it works is `osm_way_names`, which has to be the literal OSM
`name` tag ("Conzelman Road"), not the name people use ("Hawk Hill"). Runbook in
[docs/adding-a-spot.md](docs/adding-a-spot.md), design notes in
[docs/collections.md](docs/collections.md).

In production those routes aren't endpoints at all: an export script explodes the committed document
into flat files served from the CDN. FastAPI serves the same URLs locally and under `docker run`, so
nothing about Collections is exercised only in prod.

## Dirt

Gravel and MTB are first-class, which took more than a Crr bump.

`mtb:scale` and `sac_scale` collapse into one 0 to 6 integer per way, carried through to the route's
hardest segment and shown on the card. Coverage is thin, so `None` means unknown rather than easy, and
the difficulty filter lets untagged ways through. It can narrow a trail search; it can't keep
singletrack out of a road search.

The dirt profiles set a `max_speed_kmh` ceiling, which is a stand-in for a brake, since `physics.py`
doesn't model one. On tarmac the omission survives fine, because drag and rolling resistance land near
reported speeds. On a loose 15% fire road the force balance says 70 km/h while a real rider is braking
at 30, and what's actually limiting them is traction and sightlines, none of which are forces. A
capped route's top speed reads "at the limit," not "this is how fast the hill is."

Flow scoring is rider-relative for the same reason. The surface penalty deducts per edge, so a long
gravel descent floors the score at zero. That's the right answer for a road cyclist who wanted tarmac
and the wrong one for a gravel rider who came for the gravel, so the penalty values live in the config
while the set of surfaces they apply to rides on the rider profile.

One more dirt-specific wrinkle: the road rank hierarchy tracks traffic danger on pavement, so off
pavement the "stop at bigger roads" rule misfires. A trail crossing a dirt forest road reads as meeting
a bigger road and kills the descent. The Downieville spot turns that toggle off for exactly this
reason.

## Rider profiles

Physics and pathfinding are tuned per rider. A longboarder coasts further on urethane and is happy
with a short steep drop; a road cyclist needs a longer run and carries speed differently. Five presets
live in [`backend/config.py`](backend/config.py) (`RIDER_PROFILES`) and every parameter is overridable
per request. The sliders in the UI re-run the same simulation client-side in TypeScript, so dragging
one updates the speed curve with no round trip. The two implementations have to stay in sync, and both
files say so at the top.

## Running it

Backend (Python 3.11 or newer, 3.13 in the deployed image):

```bash
cd backend && python -m venv .venv && source .venv/bin/activate && pip install -r requirements.txt
```

```bash
uvicorn backend.main:app --reload --port 8000
```

Frontend (Node 20 or newer), second terminal:

```bash
cd frontend && npm install && npm run dev
```

Open the URL Vite prints. It proxies `/search` and `/collections` to port 8000, so both halves need to
be up. The first search in a new area is slow while elevation gets fetched. After that it's cached.

## Tests

```bash
backend/.venv/bin/python -m pytest -m "not integration"
```

```bash
cd frontend && npm test
```

1,343 backend tests and 143 frontend tests. Dropping the `-m` marker also runs the integration tests,
which hit live Overpass and USGS and will fail if either is down or rate limiting.

## Deploying

The SPA and the collections JSON go to Cloudflare Pages. `POST /search` is the only thing doing work
per request, so it stays on Cloud Run.

```bash
VITE_API_BASE=https://your-service.run.app scripts/build-static.sh
```

Every URL resolves through [`frontend/src/api.ts`](frontend/src/api.ts). Collections are always
relative, search goes to `VITE_API_BASE`, and that variable is empty everywhere except a production
build, which is what keeps dev, the tests, and `docker run` on single-origin behavior. Full runbook in
[docs/deploy.md](docs/deploy.md).

## Caveats

**Stop signs are badly mapped in OSM.** The avoid-stop-signs toggle only knows about `highway=stop`
nodes, and plenty of real ones aren't tagged. Traffic signals are mapped far better, so that toggle is
reliable.

**TIGER-era bridge tags are a mess.** Imports routinely tag hundreds of meters of ordinary road as
`bridge=yes`. Muir Woods Road has one way with 51 nodes over 624 m. The deck ramp flattens real
undulation on those, though drop, length, and geometry stay correct.

**This suggests lines on public roads.** It knows nothing about traffic, construction, closures, or
whether a run is a good idea today. Ride within your ability and obey traffic law.

## Layout

```
backend/    FastAPI app, pipeline stages, curated spots, tests
frontend/   React, MapLibre GL, Chart.js
docs/       Deploy runbook, OSM data notes, collections docs, route research
scripts/    Static site build
```

[CLAUDE.md](CLAUDE.md) goes deep on architecture, conventions, and why things are the way they are.
Read it before changing anything.

## License

MIT. See [LICENSE](LICENSE).
