# Elevation Cache Architecture

## Goal

Elevation is the pipeline's slowest stage, and today it re-fetches terrain it
already has. The disk cache is keyed on a hash of the viewport's entire node set
(`elevation.py:596`), so panning the map produces a new key and a full refetch.
The local cache is currently 127 files / 53 MB covering a handful of cities —
mostly duplicated overlap.

Fix: cache elevation per road segment, content-addressed, so overlapping
viewports share it.

Constraints:

-   rare, bursty traffic on Cloud Run; no Redis, no managed SQL, no distributed
    locks
-   tolerate slow cold raster reads
-   never cache physics
-   same code path locally and in cloud
-   DEM source and sampling changes must not corrupt or silently reuse old data

## Core Design

    OSM geometry
        ↓
    Canonical OSM way segments
        ↓
    Versioned raw elevation profiles
        ↓
    Physics simulation (always recomputed)
        ↓
    Ranked routes

### Principles

-   Cloud Optimized GeoTIFFs (COGs) are the authoritative elevation dataset.
    They are already block-organized for HTTP range reads, so we do not re-store
    raster blocks — we store sampled road profiles, which are ~10× smaller and
    skip the ~96% of block pixels that no road touches.
-   Immutable road elevation profiles are the persistent cache.
-   Cloud Run instances only maintain disposable local caches.
-   Physics simulations are never cached.

## Deployment

Cloud Run configuration:

-   Min instances: 0 — tolerate cold starts. A cold start discards the block
    cache, the open raster handles and the GDAL VSI cache, so the first request
    to a new instance pays full raster cost. That is the case the profile store
    exists to fix: profiles survive the instance, in-memory caches do not.
    Keeping an instance warm (~$15–25/mo) is a future option if M0/M4 numbers
    show cold starts dominating real usage.
-   Concurrency: 1 (memory headroom for raster reads; revisit once profiles
    shrink the working set)
-   CPU: 2--4
-   Memory: 4--8 GB
-   Max instances: small safety limit

## Cache Identity

    ProfileKey =
        geometry_hash
        + methodology_id

Methodology ID is derived from `elevation_source_id` and `geometry_sampling_id`.

Changing road filters or physics **must not** invalidate elevation profiles.

Changing DEM source, interpolation, or sampling **must**.

`elevation_source_id` is the source resolved for the request bbox from the
coverage index *before* any raster read — not the source that happened to
answer. Today `_fetch_cascade` picks by fallback mid-query and can merge 3DEP
with SRTM inside one result, which makes the key uncomputable up front. If the
resolved source fails, serve the fallback for that request and write no profile:
a transient 3DEP outage must not permanently cache 30 m data under a 10 m key.

## Geometry

The cache unit is an OSM way split at shared nodes, taken straight from
`overpass.py`. It is not an `nx.DiGraph` edge — the graph does not exist yet at
elevation-fetch time (`build_graph` consumes already-enriched nodes), and its
peak/valley tags are derived from the elevation we are about to fetch.

Canonicalize each segment:

1.  Remove duplicate consecutive coordinates.
2.  Quantize coordinates.
3.  Encode deterministically.
4.  Compare forward/reverse.
5.  Use lexicographically smaller encoding.
6.  Hash.

Forward and reverse directions share one cached profile.

## Cached Profile

Each cached profile stores only terrain observations: geometry hash, methodology
ID, distance, longitude, latitude, elevation, raster provenance, quality flags.

No grades, speeds, or physics outputs.

## Storage

    Cloud Storage
    ├── dem/
    ├── methodologies/
    └── profiles/{methodology_id}/{cell_id}/{shard_id}.arrow.zst

One object per segment would mean thousands of ~50–100 ms GETs for a dense
viewport, dominating every other cost. Profiles are packed into ~1 km grid cells
instead, so a viewport reads 10–20 objects.

A cell accumulates segments over time, so it is not one immutable object — it is
a set of immutable append-only shards. Each request writes one shard containing
what it generated. A read is one prefix LIST per cell plus concurrent GETs,
merged by geometry hash; duplicates across shards are byte-identical by
construction, so merge order is irrelevant. No locks, no read-modify-write.
`scripts/compact_profiles.py` merges a cell's shards and deletes the originals.

Shards are Arrow + Zstandard.

## Raster Strategy

For each request:

1.  Determine missing profiles.
2.  Sample all missing road geometries.
3.  Group sample points into raster blocks.
4.  Read each raster block once.
5.  Generate profiles.
6.  Publish one shard, using create-if-absent.

No distributed locks.

Duplicate work is acceptable.

While a block is decoded in memory, sample every segment it covers — not only
the currently-traversable ones. The raster read is already paid for; the
marginal cost is numpy indexing and ~10 bytes/point. This makes the cache
independent of `road_types` rather than merely tolerant of a stable
`road_types`.

## Local Runtime Caches

-   Raster catalog
-   Open raster handles
-   Decoded raster block LRU

These caches are disposable.

## Retention

Profiles are immutable and never overwritten, so a methodology bump strands its
entire namespace permanently. Sweep `profiles/{methodology_id}/` for any
methodology outside the current set and older than 30 days.

## Metrics

Track:

-   profile hits/misses
-   shards read per request
-   raster blocks read
-   block cache hit rate
-   bytes downloaded
-   generation time
-   physics time
-   total latency

## Non-goals

Do not initially implement:

-   Redis
-   Managed SQL
-   Distributed locks
-   A SQLite profile index — a stale negative costs a redundant raster read,
    the most expensive operation in the system, to save a cheap object listing,
    and the snapshot download lands on the cold-start path we are shortening
-   A persistent raster block cache — the USGS COGs already serve that role
    over range reads
-   Cached physics simulations
-   Kubernetes
-   Persistent local disks
