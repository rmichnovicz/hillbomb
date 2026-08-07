# Elevation Cache Implementation Plan

## Objective

Implement a versioned, immutable elevation subsystem that works locally
and on Cloud Run.

## Modules

    terrain/
      methodology.py    # source policy + sampling → methodology_id
      geometry.py       # canonical segment encoding + hashing
      models.py
      catalog.py        # raster discovery + coverage index
      raster_reader.py
      block_cache.py    # in-process LRU, disposable
      sampler.py        # plan by block, read once, build profiles
      profile_store.py  # shard read/write, local + GCS
      service.py        # ElevationService facade
    scripts/
      compact_profiles.py

## Interfaces

Implement:

-   RasterReader
-   ProfileStore
-   ElevationService

Keep cloud implementations behind interfaces.

## Request Flow

    Canonicalize OSM way segments
            ↓
    LIST + GET shards for covering cells
            ↓
    Merge by geometry hash
            ↓
    Generate missing profiles
            ↓
    Publish one shard, create-if-absent
            ↓
    Run physics

## Batch Generation

Always batch:

1.  Sample every missing road.
2.  Resolve raster locations.
3.  Group by raster block.
4.  Read each block once.
5.  Build profiles for every segment the block covers, traversable or not.

## Methodology

Split into:

-   ElevationSource
-   GeometrySampling

Hash canonical JSON to produce methodology_id.

Resolve ElevationSource from the bbox coverage index before fetching. On
resolved-source failure, serve the fallback and skip the write.

## Profile Format

Arrow IPC + Zstandard.

Store:

-   distance
-   coordinates
-   elevation
-   raster id
-   source pixel
-   quality flags

## Shard Store

Runtime: prefix LIST per covering cell, concurrent GET, merge by geometry hash.

Shards are immutable and append-only; compaction is a separate offline step.

## Local Store

    profiles/
        {methodology_id}/
            {cell_id}/
                {shard_id}.arrow.zst

Write atomically.

Never overwrite.

## Cloud Store

-   Deterministic object names
-   Create-if-absent uploads
-   Ignore AlreadyExists
-   No locks

## Block Cache

Byte-bounded LRU of decoded raster blocks.

Correctness must never depend on the cache.

## Benchmarks

Create representative fixtures, extending `backend/tests/test_elevation_perf.py`:

-   dense city
-   suburb
-   mountain roads
-   rural highway

Measure:

-   samples
-   raster blocks
-   cache hit rate
-   bytes read
-   elevation latency
-   total latency

Every measurement is taken against current `elevation.py` first, in M0.

## Milestones

### M0 — Baseline (before writing any module)

-   ~~Build the four fixtures; benchmark current `elevation.py` cold and warm~~
    Done — `backend/scripts/bench_elevation.py`
-   Deploy current code to Cloud Run with min-instances 0; benchmark cold and
    warm instances separately so cold-start cost is a known number, not a guess
-   ~~Set the latency targets below from these numbers~~ Done — see M0 Results
-   Gate: if warm p50 already clears target, stop — the rest of this plan is
    unnecessary. **This gate has tripped. See M0 Results before starting M1.**

## M0 Results

Local, 2026-08-05, `python -m backend.scripts.bench_elevation`. Median across the
four fixtures; 3 repeats for warm scenarios, 1 for cold.

| scenario | median | reuse |
|---|---|---|
| cold (first-ever visit) | 946 ms | 0% |
| warm_instance | 6.7 ms | 100% |
| cold_instance (new service, same process) | 6.6 ms | 100% |
| same_cold_process (new interpreter, same viewport) | 6.7 ms | 100% |
| pan_50 (same process, panned viewport) | 9.1 ms | 0% |
| pan_50_cold_process (new interpreter, panned) | 795 ms | 0% |

Findings, in order of how much they change the plan:

1.  **The warm path needs no work.** 6.7 ms against a 150 ms target. Every
    same-viewport scenario is single-digit ms whether or not the process is
    fresh, because the pickle hit means no raster read happens at all.
2.  **Pan reuse is 0%, exactly as predicted** — the file key defect is real. But
    in-process it costs only 9 ms, because a 3DEP 1/3 arc-sec block is 512×512
    at 10 m ≈ 5.1 km across, wider than a viewport. A half-screen pan usually
    lands in blocks GDAL has already decoded in memory. The pickle bug is
    largely masked by GDAL's block cache underneath it.
3.  **The one case that costs real time is cold process + pan: 795 ms.** No
    pickle hit and no warm blocks. A geometry-keyed profile cache would turn
    this into the 6.7 ms `same_cold_process` case. That saving — ~0.8 s on
    requests that both hit a cold instance and pan — is the entire measurable
    benefit of this plan.
4.  **Cold cost is block-bound, not point-bound.** rural_highway (771 nodes) and
    dense_city (3351 nodes) cost about the same. Reducing points sampled saves
    nothing; only avoiding the block read helps.
5.  **Cold numbers are noisy: n=1 and ~3× run-to-run variance** (cold median was
    2786 ms on the first run, 946 ms on the second, same code and fixtures).
    Treat every cold figure here as an order of magnitude, not a target. Fix by
    repeating cold runs before relying on them.
6.  Interpreter + rasterio import is ~330 ms of any cold start. No cache design
    removes it.

Not yet measured: bytes downloaded and raster blocks read (GDAL issues range
requests through libcurl, so this needs real instrumentation — deferred to M2
where block grouping is the thing being optimised), and Cloud Run numbers.

### M1

-   Local raster reader
-   Geometry hashing
-   Raw profile generation
-   Golden tests

### M2

-   Block grouping
-   Block cache
-   Benchmarks against the M0 baseline

### M3

-   Local shard store + compaction script

### M4

-   Cloud Storage
-   Cloud Run deployment

## Migration

-   `ElevationService.get_elevations` / `missing_coords` keep their signatures —
    `main.py` and `gate.py` are untouched through M3.
-   `RequestGate` stays. It throttles cold raster reads, which still happen on a
    profile miss.
-   The 53 MB pickle cache is not migrated. Delete `~/.cache/hillbomb/elevation`
    at cutover.
-   `scripts/build_collections.py` runs the same pipeline, so a collections build
    warms the shared cache for free. Run it before deploy.

## Acceptance Criteria

-   Deterministic profile keys
-   Direction-independent geometry hashes
-   N concurrent requests over the same bbox lose no profile and corrupt no shard
-   Local and Cloud Run use same core code
-   Physics never cached
-   Methodology changes create new cache namespace
-   Previously-visited viewport, warm instance: p50 < 15 ms
    *(already met — 6.7 ms. Do not regress.)*
-   Previously-visited viewport, cold process: p50 < 15 ms
    *(already met — 6.7 ms)*
-   **50% viewport pan, cold process: p50 < 50 ms** *(currently 795 ms — the only
    latency criterion this plan actually moves)*
-   50% viewport pan reuses ≥ 80% of profiles *(currently 0%)*
-   Cold dense-city viewport: elevation stage < 3 s *(currently 0.4–3.4 s, n=1
    and noisy — re-measure with repeats before treating as a target)*
-   Dense-city viewport reads ≤ 25 objects
