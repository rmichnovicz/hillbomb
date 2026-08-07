# Deploying Hillbomb

**Status: live, both halves**, as of 2026-08-07.

| | |
|---|---|
| Static | Cloudflare Pages project `hillbomb` → `https://hillbomb.pages.dev`, custom domain `hillbomb.app` |
| API | Cloud Run service `hillbomb`, project `hillbomb`, region `us-west1` |

**Cloud Run hands out two URLs for one service.** `gcloud run services describe` reports
`https://hillbomb-auxunbjxna-uw.a.run.app`, while the console also shows
`https://hillbomb-584159038747.us-west1.run.app`. Both are aliases for the same
service and both answer `/api/healthz` with 200 — don't go hunting for a second
deployment. `scripts/build-static.sh` bakes in whatever `gcloud` reports, so the SPA
uses the `a.run.app` form.

---

## The shape

**Two deployables, split along the line of what actually needs a server.**

- **Static** — the SPA and the curated collections. Precomputed, byte-identical for
  every visitor, so they live on Cloudflare Pages and no container is involved in
  loading the site or browsing Collections.
- **Dynamic** — `POST /search`, and nothing else. Real pipeline work per request, so
  it stays on Cloud Run.

```
                    ┌────────────────────────────────────┐
   browser ────────▶│  Cloudflare Pages                  │
        │           │   /                    → SPA       │  free, edge-cached,
        │           │   /collections/*.json  → 95 files  │  brotli'd automatically
        │           │   /api/where           → Function  │  per-visitor, no-store
        │           └────────────────────────────────────┘
        │
        │  POST /search only (cross-origin, CORS)
        ▼
   ┌──────────────────────────────┐
   │  Cloud Run: hillbomb         │
   │   /search      → SSE pipeline│
   │   data/hillbomb.gol (in image)│
   └───────┬──────────────┬───────┘
           │              │
    Overpass API     USGS 3DEP on S3
    (OSM ways, only    (elevation, COG byte-range reads)
     outside GOL
     coverage)
           │
   ┌───────▼──────────────────────┐
   │ GCS bucket, gcsfuse-mounted  │
   │ at /var/cache/hillbomb       │
   │  overpass/  cached OSM       │
   │  elevation/ cached samples   │
   └──────────────────────────────┘
```

### Why this changed

It used to be one Cloud Run service serving everything from one image, on the argument
that relative paths meant no CORS and no build-time API base URL. That argument was
real but it was buying the wrong thing. What it cost:

- **Every static byte woke a container.** With `--min-instances 0`, the first visitor
  after an idle period waited for a Python app, GDAL, and a 200 MB GOL to boot before
  receiving 489 bytes of HTML. Measured on the live service: **3.07 s cold vs 0.08 s
  warm.** Browsing Collections — precomputed data that never changes — paid that too.
- **Nothing was compressed.** Cloud Run doesn't compress and neither does Google's
  frontend. Confirmed live: `/collections/index.json` returned identical bytes with
  and without `Accept-Encoding: gzip, br`. Pages brotlis everything automatically, so
  that problem disappears rather than getting fixed.

The price is one cross-origin request. `POST /search` sends a JSON body, so it is not
a simple request and costs a preflight `OPTIONS` — allowed explicitly in `main.py`'s
CORS middleware, locked to the site origin via `HILLBOMB_ALLOWED_ORIGINS`. That is the
whole cost, and it is one env var on each side.

**The container can still serve everything itself**, and does under `docker run` —
`main.py` serves the same `/collections/*.json` URLs out of `collections.json`, and an
unset `VITE_API_BASE` leaves every URL relative. Local parity is intact; the split
exists only in production.

### What it costs

The domain, and nothing else. Cloudflare Pages' free tier covers this comfortably —
unlimited bandwidth on static assets, against limits of 20,000 files and 25 MiB per
file. Hillbomb ships **95 files totalling 2.3 MB**, the largest being the 136 KB
Vesuvius spot.

R2 is the wrong tool here despite being the obvious-sounding one: it would mean a
Worker in front of a bucket to serve objects Pages already serves for free. It becomes
right only if the corpus outgrows those file limits, or if you want to publish a spot
without redeploying the site.

### About the elevation cache — a correction worth reading

An earlier version of this plan said elevation streams ~50 MB tiles to local disk and
that this was the hard part of running on Cloud Run. **That is not the default
behaviour.** `HILLBOMB_DEP13_MODE` defaults to `cog`, which does windowed HTTP
byte-range reads straight out of the USGS COGs on S3 and downloads no tiles at all
(`elevation.py`, `_Dep13TileCache`). Continental-US searches therefore need no
persistent disk whatsoever.

The bucket is still worth having, but for a smaller and more honest reason: it lets the
**Overpass response cache** (24 h TTL) and the **per-coordinate elevation cache** survive
scale-to-zero and be shared between instances. That turns a repeated search of the same
area from ~15 s into near-instant, and it takes load off Overpass — which matters, see
the warning below. It costs pennies a month.

If you would rather skip it, drop the two `--add-volume*` flags and the service still
works correctly, just with a cold cache per instance.

---

## Prerequisites

### Google Cloud

`gcloud` (SDK 579 confirmed installed) and a billing-enabled project. You need to do the
sign-in yourself:

```bash
gcloud auth login
```

Then set the project you want to use, and confirm billing is on:

```bash
gcloud config set project YOUR_PROJECT_ID
```

```bash
gcloud beta billing projects describe YOUR_PROJECT_ID
```

### A domain

**`hillbomb.app`, registered through Cloudflare.** Registering there rather than
elsewhere is what lets the rest of this be simple: the DNS zone is already in the same
account as Pages, so attaching the domain in step 8 creates its own record and issues
its own certificate with nothing to delegate.

It is the domain and nothing else that costs money here. Pages is free at Hillbomb's
size — 95 files, 2.3 MB, against limits of 20,000 files and 25 MiB per file — and Cloud
Run's free tier covers the search traffic for a long while.

(If you ever move to a domain bought elsewhere, you point that registrar's nameservers
at Cloudflare and everything below is unchanged except `SITE_ORIGIN`.)

### Cloudflare, authenticated

`wrangler` runs via `npx`, so there's nothing to install, but you do need to sign in
yourself once:

```bash
npx wrangler login
```

---

## 1. Pick your names

Everything below uses these. Set them once in the shell you deploy from.

```bash
export PROJECT_ID="YOUR_PROJECT_ID"
export REGION="us-west1"
export SERVICE="hillbomb"
export CACHE_BUCKET="${PROJECT_ID}-hillbomb-cache"
export SITE_ORIGIN="https://hillbomb.app"
```

`us-west1` is a reasonable default: it is close to the USGS S3 buckets the elevation
reads come from, and most of the curated collection is in the western US. Any region
works.

`SITE_ORIGIN` is scheme and host, **no trailing slash** — it is compared against the
browser's `Origin` header verbatim, and a trailing slash makes it never match.

`.app` is on the HSTS preload list, so browsers refuse plain HTTP to it outright. That
removes the other half of this footgun for free: there is no `http://hillbomb.app`
variant to accidentally configure, and a `curl http://hillbomb.app` that appears to
hang or redirect is the TLD working as designed, not a broken deploy.

## 2. Enable the APIs

```bash
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com --project "$PROJECT_ID"
```

## 3. Create the cache bucket

```bash
gcloud storage buckets create "gs://${CACHE_BUCKET}" --project "$PROJECT_ID" --location "$REGION" --uniform-bucket-level-access
```

Cached OSM and elevation data is disposable — it is all re-fetchable — so expire it
rather than paying to keep it forever:

```bash
printf '{"rule":[{"action":{"type":"Delete"},"condition":{"age":30}}]}' > /tmp/hillbomb-lifecycle.json && gcloud storage buckets update "gs://${CACHE_BUCKET}" --lifecycle-file=/tmp/hillbomb-lifecycle.json
```

## 4. Give the service a identity that can reach the bucket

Cloud Run's default compute service account needs object access. Creating a dedicated
one is tidier:

```bash
gcloud iam service-accounts create hillbomb-run --display-name "Hillbomb Cloud Run" --project "$PROJECT_ID"
```

```bash
gcloud storage buckets add-iam-policy-binding "gs://${CACHE_BUCKET}" --member "serviceAccount:hillbomb-run@${PROJECT_ID}.iam.gserviceaccount.com" --role roles/storage.objectAdmin
```

## 5. Deploy the API

This builds the image with Cloud Build from the `Dockerfile` in the repo root and
deploys it. First run takes a few minutes (npm install + pip install).

```bash
gcloud run deploy "$SERVICE" --source . --project "$PROJECT_ID" --region "$REGION" --allow-unauthenticated --execution-environment gen2 --service-account "hillbomb-run@${PROJECT_ID}.iam.gserviceaccount.com" --memory 2Gi --cpu 2 --timeout 600 --concurrency 8 --min-instances 0 --max-instances 4 --add-volume "name=cache,type=cloud-storage,bucket=${CACHE_BUCKET}" --add-volume-mount "volume=cache,mount-path=/var/cache/hillbomb" --set-env-vars "HILLBOMB_CACHE_DIR=/var/cache/hillbomb,HILLBOMB_ALLOWED_ORIGINS=${SITE_ORIGIN}"
```

Why these values:

| Flag | Reason |
|---|---|
| `--execution-environment gen2` | Required for gcsfuse volume mounts. |
| `--timeout 600` | A cold `/search` is ~15–30 s, but the SSE stream is one long-lived request. The 5-minute default is uncomfortably close; 10 minutes is not. |
| `--concurrency 8` | Pathfinding is CPU-bound and `RequestGate` bounds concurrent elevation fetches **per process**. The default of 80 would queue requests behind each other inside one instance instead of scaling out. |
| `--cpu 2` | Graph construction and pathfinding are the slow stages and benefit from the second core. |
| `--memory 2Gi` | Graphs for a large bbox plus GDAL's 512 MB block cache. |
| `--min-instances 0` | Scale to zero. Idle cost is then nil, at the price of a cold start on the first hit. |
| `--max-instances 4` | A deliberate ceiling. See the Overpass warning below — this caps how hard a traffic spike can hammer a free public API on your behalf. |
| `--allow-unauthenticated` | Public, as chosen. |
| `HILLBOMB_ALLOWED_ORIGINS` | The site origin, so the cross-origin `POST /search` preflight passes. Unset it and the middleware falls back to `*`, which works but allows any page anywhere to drive your pipeline. |

## 6. Check the API

```bash
gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)'
```

Capture that — the SPA build needs it:

```bash
export VITE_API_BASE="$(gcloud run services describe "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --format 'value(status.url)')"
```

```bash
curl -fsS "$VITE_API_BASE/api/healthz" && curl -fsS "$VITE_API_BASE/collections/index.json" | head -c 200
```

**Use `/api/healthz`, not `/healthz`, for anything probing from outside.** Google's
frontend answers a bare `/healthz` itself, with its own branded 404 page — the request
never reaches the container. Confirmed on the live service: `/healthz` returns a Google
error page while `/healthz/`, `/health` and every other spelling reach the app. The
container's own HEALTHCHECK still uses `/healthz` over localhost, where the frontend is
not in the path.

The container still serves `/collections/*.json` and the SPA. In production nothing
asks it to — that is the fallback and local-parity path, and it is worth keeping
working precisely because it is what `docker run` and the dev server use.

## 7. Build the static site

```bash
scripts/build-static.sh
```

Two steps, and the script exists because of the second one. `npm run build` emits the
SPA into `frontend/dist`, but the collections JSON is **not** part of the Vite build —
it is exported from `backend/data/collections.json` afterwards by
`backend/scripts/export_static_collections.py`, which writes:

```
frontend/dist/collections/index.json      every city, every spot, no geometry (60 KB)
frontend/dist/collections/<slug>.json     one spot with its full routes (94 files)
```

Skip that step and you deploy a site that looks perfect and whose every Collections
card 404s. The script refuses to run without `VITE_API_BASE` for the same class of
reason — unset, the SPA would POST `/search` to the CDN, which has no such route.

These files are build artifacts and are **not committed**. `collections.json` stays
the single source of truth; committing the exploded copy would double the repo's data
weight and give you two things to keep in sync. `test_collections.py` asserts the
exported files are byte-identical to what the API serves, so the two paths cannot
drift.

## 8. Deploy the static site

First time, create the project:

```bash
npx wrangler pages project create hillbomb --production-branch main
```

Then, now and on every subsequent deploy:

```bash
npx wrangler pages deploy frontend/dist --project-name hillbomb
```

That command uploads two things, and only one of them comes out of `frontend/dist`.
Wrangler also picks up the **`functions/` directory at the repo root** and bundles it as
Pages Functions — so `deploy` must be run from the repo root, not from `frontend/`. You
can confirm it happened in the output:

```
✨ Compiled Worker successfully
✨ Uploading Functions bundle
```

Miss those two lines and the site deploys perfectly with `/api/where` returning the
SPA's own HTML. Nothing breaks visibly: the Collections tab just stops opening the
visitor's nearest region and goes back to a collapsed list of 34 folders. Verify it
directly rather than by eye:

```bash
curl -sS -D- https://hillbomb.app/api/where -o /dev/stdout
```

Expect a JSON body with `lat`/`lon` and, importantly, `cache-control: no-store`.

### Preview deploys

`--branch <name>` (any name other than the production branch) publishes to a preview
alias instead of production — worth using for anything touching Functions:

```bash
npx wrangler pages deploy frontend/dist --project-name hillbomb --branch ip-geo --commit-dirty=true
```

Two URLs come back. The **deployment-specific** one (`https://<hash>.hillbomb.pages.dev`)
is live immediately; the **branch alias** (`https://ip-geo.hillbomb.pages.dev`) serves
`Deployment Not Found` for a few minutes while it propagates, exactly like the 522
flapping below. Test against the hash URL and don't diagnose anything from the alias
until it settles.

Attach the domain in the Cloudflare dashboard under **Workers & Pages → hillbomb →
Custom domains**. Certificates are issued automatically and free. There is no wrangler
command for this as of 4.120 — `wrangler pages` has no `domain` subcommand, so the
dashboard (or the REST API) is the only route.

### Expect 522s for the first few minutes after a first deployment

A brand-new Pages project serves intermittent `522 Connection timed out` while the
deployment propagates, and it is easy to mistake for a broken deploy because it is not
a clean failure — it flaps. Measured on this project's first deploy:

| Time after deploy | `hillbomb.pages.dev` error rate |
|---|---|
| ~1 min | several consecutive failures |
| ~10 min | 2 / 30 |
| ~20 min | 0 / 20 |

Two things make it diagnosable. The deployment-specific URL
(`<hash>.hillbomb.pages.dev`) stayed **0/10** throughout, so a clean result there
against a flapping production alias points at propagation rather than at your build.
And browsers cache the Cloudflare error page, so a tab that saw a 522 keeps showing it
long after `curl` is clean — hard-reload before concluding anything.

Don't diagnose this from a handful of requests. Eight consecutive 200s proved nothing
here; the flapping only showed up in a sample of thirty.

## 9. Check the whole thing

```bash
curl -fsS -o /dev/null -w '%{http_code} %{size_download}\n' "$SITE_ORIGIN/collections/index.json"
```

Confirm the CDN is compressing — this is the thing Cloud Run was silently not doing,
so it is worth seeing with your own eyes. The second number should be markedly smaller:

```bash
curl -sS -o /dev/null -w 'identity: %{size_download}\n' -H 'Accept-Encoding: identity' "$SITE_ORIGIN/collections/index.json" && curl -sS -o /dev/null -w 'brotli:   %{size_download}\n' -H 'Accept-Encoding: br' "$SITE_ORIGIN/collections/index.json"
```

Then open `$SITE_ORIGIN` in a browser and check both halves:

- **Collections tab populates.** All of it should come from the CDN — in devtools you
  should see no request to `*.run.app` at all while browsing.
- **"Search this area" returns routes.** This is the cross-origin path: look for a
  preflight `OPTIONS /search` followed by the `POST`. If the POST fails with a CORS
  error, `HILLBOMB_ALLOWED_ORIGINS` doesn't match `$SITE_ORIGIN` exactly — check for a
  trailing slash or an `http`/`https` mismatch.

---

## ⚠️ Overpass is the operational risk, and we have already tripped it

`POST /search` depends on the public Overpass API. That endpoint enforces per-IP limits
and **will block an IP that abuses it** — during development this repo's own research
tooling got `overpass-api.de` to refuse connections outright (not 429; connection
refused) after running many concurrent queries.

On a public deployment, every visitor's search goes out from *your* Cloud Run egress IP.
A modest amount of traffic can therefore get the whole service blocked at once.

Mitigations, cheapest first:

1. **Keep `--max-instances` low** and `--concurrency` modest, as above.
2. **Keep the GCS cache**, so repeated searches of the same area never re-query.
3. **Point at a different endpoint** if the main one blocks you. No code change needed —
   `overpass.py` reads `HILLBOMB_OVERPASS_URL`:
   ```bash
   gcloud run services update "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --set-env-vars "HILLBOMB_OVERPASS_URL=https://overpass.kumi.systems/api/interpreter"
   ```
   Mirrors are volunteer-run; treat them at least as carefully as the main instance.
4. **Ship the local GOL**, which removes Overpass from the path entirely for every
   covered region. This is now the main answer and it costs no extra infrastructure —
   `data/hillbomb.gol` rides along inside the container image, and Cloud Run's docs are
   explicit that image size does not consume instance memory (only runtime filesystem
   writes do). Build it before `gcloud builds submit`:
   ```bash
   python -m backend.scripts.build_gol --tier deploy --work-dir /tmp/golbuild --out data/hillbomb.gol
   ```
   **`--tier deploy`, not `--tier all`.** The `all` tier is the ~1 GB local cache used
   for Collections builds; `deploy` is the three-region ~200 MB file meant for the
   image. The build script warns above 500 MB. Both the GOL and its
   `.regions.json` manifest are copied in — the manifest is what tells the running
   service which regions this particular file actually covers, so a deploy-tier build
   can never be mistaken for the full one.

   If the GOL is absent the image still builds and every search uses Overpass, so this
   is opt-in per deploy. Watch cold-start pull time as coverage grows. See
   `docs/local-osm-data.md`.
5. **Run your own Overpass** if uncovered regions ever get real traffic. It is the
   durable answer for global coverage, and a substantial piece of infrastructure (a
   planet or region extract, plus regular diffs).

The Collections tab does **not** touch Overpass — and since the split it does not touch
Cloud Run either. It is flat JSON on the CDN, so an Overpass block, a failed revision,
or a Cloud Run outage all degrade live search while leaving the curated content fully
working.

---

## Environment variables

### Cloud Run (the API)

| Variable | Default | Purpose |
|---|---|---|
| `PORT` | `8080` | Injected by Cloud Run; the container honours it. |
| `HILLBOMB_ALLOWED_ORIGINS` | `*` | Comma-separated origins allowed to call `POST /search`. Set to the site origin in production — scheme and host, no trailing slash. |
| `HILLBOMB_CACHE_DIR` | `/var/cache/hillbomb` | Cache root. Point at the gcsfuse mount. |
| `HILLBOMB_STATIC_DIR` | `<repo>/static` | Built SPA. The image puts it here already. Serves the fallback and `docker run` path, not production. |
| `HILLBOMB_OVERPASS_URL` | overpass-api.de | Swap endpoints without a rebuild. |
| `HILLBOMB_GOL` | `/app/data/hillbomb.gol` | Local road-network snapshot. Ignored if the file isn't there; `""` disables it explicitly. Coverage comes from the sibling `.regions.json`, not from the code. |
| `HILLBOMB_CACHE_TTL` | `86400` | Overpass cache TTL, seconds. `0` disables. |
| `HILLBOMB_DEP13_MODE` | `cog` | `cog` = byte-range reads, no downloads. `download` = legacy whole-tile. |
| `HILLBOMB_MAX_CONCURRENT_ELEVATION` | `2` | Concurrent cold elevation fetches per process. |
| `HILLBOMB_MAX_QUEUE` | `20` | Queued searches before shedding with a `busy` event. |

### Static build (baked in at build time, not runtime)

| Variable | Default | Purpose |
|---|---|---|
| `VITE_API_BASE` | `""` | Origin of the search API. Empty means same-origin, which is what dev, the test suite, and `docker run` all want. `scripts/build-static.sh` requires it. |

---

## Updating

**Two deployables, and they do not have to move together.** Most changes touch one:

| What changed | What to re-run |
|---|---|
| Frontend code | steps 7–8 |
| A spot's copy, or a rebuilt `collections.json` | steps 7–8 |
| Backend pipeline, config, or the GOL | step 5 |
| A field added to `pipeline.route_payload()` | rebuild collections, then 5 **and** 7–8 |

That last row is the one to watch: the route wire shape is shared, so the SPA and the
committed collections have to agree. `test_collections.py` fails when they don't.

Re-running the `gcloud run deploy` command in step 5 rebuilds and rolls out. Cloud Run
keeps the old revision serving until the new one passes health checks.

To roll back the API:

```bash
gcloud run services update-traffic "$SERVICE" --project "$PROJECT_ID" --region "$REGION" --to-revisions PREVIOUS_REVISION=100
```

To roll back the static site, promote an earlier deployment from **Workers & Pages →
hillbomb → Deployments** in the Cloudflare dashboard. Pages keeps every deployment
addressable at its own URL, so you can check one before promoting it.

## Two build facts worth keeping

Both were found by building the image locally, and both would otherwise have surfaced as
a *failed Cloud Run revision* rather than a failed build.

**The runtime stage is pinned to `linux/amd64`, deliberately.** Cloud Run runs amd64, so
an arm64 image built on an Apple Silicon machine deploys and then refuses to start. It is
also the only architecture that works at all here: rasterio publishes a cp313 manylinux
wheel for x86_64 but **not** for aarch64, so on arm64 pip falls back to compiling from
source and dies on the missing `gdal-config`. The `FromPlatformFlagConstDisallowed`
lint warning from BuildKit is expected and is the point.

**`libexpat1` is installed even though GDAL is bundled.** rasterio's wheel carries its own
GDAL, but that GDAL links system libexpat, and `python:*-slim` does not ship it. Without
it the image builds perfectly and then dies on the first `import rasterio` with
`libexpat.so.1: cannot open shared object file`.

## Local parity

Two things to test locally, and they are not the same thing.

**The image** is what runs the API in production:

```bash
docker build -t hillbomb .
```

```bash
docker run --rm -p 8080:8080 hillbomb
```

Then open `http://localhost:8080`. The container ignores your `~/.cache/hillbomb`, so
the first search is a genuine cold start — which is the point. Note this runs the app
in its *single-origin* configuration: `VITE_API_BASE` is unset in the image build, so
the SPA talks to the container it came from and FastAPI serves the collection JSON out
of `collections.json`. That is deliberate — it keeps the container a complete,
self-contained way to run Hillbomb — but it means `docker run` does **not** exercise
the cross-origin path that production uses.

**The static bundle** is what Cloudflare actually serves. Serving `frontend/dist` from
any plain static file server reproduces it exactly, since Pages adds nothing at
request time but compression and caching:

```bash
VITE_API_BASE="https://hillbomb-584159038747.us-west1.run.app" scripts/build-static.sh && python3 -m http.server 5175 --directory frontend/dist
```

At `http://localhost:5175` the Collections tab loads entirely from disk and searches go
cross-origin to the real Cloud Run service — which is the production topology, on your
machine. This is also where a CORS misconfiguration shows up as a browser error rather
than as a silent success.
