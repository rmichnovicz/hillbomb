"""
M0 baseline benchmark for the elevation stage.

Measures what `ELEVATION_CACHE_IMPLEMENTATION_PLAN.md` M0 asks for: the real cost
of the current `elevation.py` against real viewports, before any of the terrain/
modules exist. The numbers this prints become the acceptance targets in that plan
— and decide the M0 stop-gate (if the warm path already clears target, M1-M4 are
unnecessary).

    python -m backend.scripts.bench_elevation                    # all fixtures
    python -m backend.scripts.bench_elevation --fixture dense_city
    python -m backend.scripts.bench_elevation --json out.json
    python -m backend.scripts.bench_elevation --keep-cache       # don't clear first

This is NOT `tests/test_elevation_perf.py`. That file times `_Dep13TileCache.sample`
on synthetic point grids — raster-level throughput. This one drives the same call
`main.py` makes (`get_elevations(coords, ..., cache_coords)`) over real OSM road
geometry, so it measures the stage as the pipeline actually experiences it: disk
cache probe included, real spatial distribution of road nodes included.

Four scenarios per fixture:

  cold           empty profile cache, fresh service — full raster fetch
  warm_instance  same service, same viewport — disk cache + open datasets + GDAL VSI
  cold_instance  new service, same disk cache — what a Cloud Run cold start sees
                 (min-instances 0, per the architecture doc)
  pan_50         viewport shifted east by 50% — measures how much of the overlap
                 the cache actually reuses
  same_cold_process     fresh interpreter, same viewport — pickle hit, nothing warm
  pan_50_cold_process   fresh interpreter, panned viewport — no pickle hit and no
                        warm GDAL blocks. The number the whole plan turns on.

`cold_instance` and `*_cold_process` are not the same measurement. A new
ElevationService drops its own state, but GDAL's block cache and /vsicurl range
cache are process-global, so a new service in the same process still reads warm
bytes. Only a new interpreter clears them.

`pan_50` is the load-bearing one. Half that viewport is terrain we just fetched, so
a cache that keys on geometry should reuse ~50% of it. The current cache keys the
FILE on a hash of the whole node set (elevation.py:596), so a pan produces a new
filename and an empty map — expect 0%. That gap is the entire premise of the plan.

Hits real Overpass and real USGS 3DEP. Overpass responses are disk-cached for 24 h
(overpass.py), so only the first run per fixture pays that cost.
"""

from __future__ import annotations

import argparse
import json
import shutil
import statistics
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path

from backend.config import DEFAULT_ROAD_TYPES
from backend.elevation import ElevationService
from backend.overpass import fetch_osm_data
from backend.pipeline import mark_traversable, traversable_node_ids

# ── Fixtures ──────────────────────────────────────────────────────────────────
#
# bbox is (south, west, north, east) — the convention fetch_osm_data expects.
# Sized like a real map viewport at z13-14 (~0.02 deg), so node counts are
# representative of an actual search rather than a synthetic stress grid.
#
# The four cover the density range that matters: block count per node scales with
# how spread out the road network is, so a mountain viewport with few long roads
# and a dense grid with many short ones stress different parts of the raster path.

FIXTURES: dict[str, dict] = {
    "dense_city": {
        "bbox": (37.788, -122.420, 37.802, -122.398),
        "desc": "SF Nob Hill / Union Square — dense grid, steep",
    },
    "suburb": {
        "bbox": (37.500, -122.292, 37.516, -122.268),
        "desc": "San Carlos — suburban curvilinear streets",
    },
    "mountain": {
        "bbox": (37.900, -122.620, 37.920, -122.584),
        "desc": "Mount Tamalpais — few long switchback roads",
    },
    "rural_highway": {
        "bbox": (38.048, -122.752, 38.076, -122.706),
        "desc": "Nicasio / Point Reyes — sparse rural highway",
    },
}

REPEATS = 3  # warm/cold-instance runs are cheap; take a median


# ── Result records ────────────────────────────────────────────────────────────

@dataclass
class ScenarioResult:
    scenario: str
    elapsed_ms: float
    n_coords: int
    n_missing: int          # coords the cache probe reported as not present
    reuse_pct: float        # 1 - n_missing/n_coords
    resolution_m: float
    samples_ms: list[float] = field(default_factory=list)
    # Set only for cold-process scenarios: full subprocess wall clock, which
    # includes interpreter + rasterio import. A real cold start pays this too,
    # but no cache design can remove it — kept separate so it can't flatter or
    # distort the in-process elevation numbers.
    process_wall_ms: float | None = None


@dataclass
class FixtureResult:
    name: str
    desc: str
    bbox: tuple[float, float, float, float]
    n_nodes_network: int    # every node in the fetched road network
    n_nodes_needed: int     # nodes on a traversable way — what elevation is fetched for
    n_ways: int
    overpass_ms: float
    scenarios: list[ScenarioResult] = field(default_factory=list)


# ── Geometry prep — mirrors main.py's elevation stage exactly ─────────────────

def prepare_viewport(bbox: tuple[float, float, float, float]):
    """Fetch OSM and derive (coords, cache_coords) the way main.py does.

    Kept deliberately in lockstep with backend/main.py's elevation stage: elevation
    is fetched only for traversable nodes, but the cache is keyed on the full
    toggle-independent network. Diverging here would benchmark a pipeline that
    doesn't exist.
    """
    t0 = time.perf_counter()
    nodes, ways = fetch_osm_data(bbox)
    overpass_ms = (time.perf_counter() - t0) * 1000

    mark_traversable(
        ways,
        road_types=DEFAULT_ROAD_TYPES,
        max_road_rank=6,  # SearchRequest's default (secondary) — benchmark the common case
        allowed_surface_categories=None,
    )

    used_ids = {nid for w in ways for nid in w.node_ids}
    active_nodes = {nid: n for nid, n in nodes.items() if nid in used_ids}

    traversable_ids = traversable_node_ids(ways)
    needed_nodes = {nid: n for nid, n in active_nodes.items() if nid in traversable_ids}

    coords = [(n.lon, n.lat) for n in needed_nodes.values()]
    cache_coords = [(n.lon, n.lat) for n in active_nodes.values()]
    return coords, cache_coords, ways, overpass_ms


def pan_east(bbox: tuple[float, float, float, float], frac: float = 0.5):
    """Shift the viewport east by `frac` of its width — a half-screen pan."""
    south, west, north, east = bbox
    dx = (east - west) * frac
    return (south, west + dx, north, east + dx)


# ── Measurement ───────────────────────────────────────────────────────────────

def time_call(svc: ElevationService, coords, cache_coords) -> tuple[float, int, float]:
    """One get_elevations call. Returns (elapsed_ms, n_missing_before, resolution_m)."""
    n_missing = len(svc.missing_coords(coords, cache_coords))
    t0 = time.perf_counter()
    elevs = svc.get_elevations(coords, None, cache_coords)
    elapsed_ms = (time.perf_counter() - t0) * 1000
    assert len(elevs) == len(coords), "get_elevations returned wrong length"
    return elapsed_ms, n_missing, svc.resolution_m


def cold_process_scenario(name: str, fixture: str, panned: bool,
                          cache_root: Path, n_coords: int) -> ScenarioResult:
    """Run one measurement in a FRESH PYTHON PROCESS.

    This is the only honest way to measure a Cloud Run cold start. Building a new
    ElevationService drops its own state, but GDAL's block cache and the /vsicurl
    range cache are process-global — a new service in the same process still reads
    warm bytes. Only a new process clears them.

    Matters because the same-viewport case hides this: the pickle cache hits, so
    no raster read happens and in-process GDAL state is irrelevant. It's the
    *panned* viewport in a fresh process — no pickle hit, no warm blocks — that
    shows the real cost the profile store is meant to remove.

    Reports in-process elapsed (excluding interpreter + rasterio import) so it is
    comparable to the other scenarios; import cost is logged separately since a
    real cold start pays it too but no cache design can fix it.
    """
    import subprocess

    cmd = [sys.executable, "-m", "backend.scripts.bench_elevation",
           "--child", fixture, "--cache-dir", str(cache_root)]
    if panned:
        cmd.append("--child-panned")

    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True,
                          cwd=str(Path(__file__).resolve().parents[2]))
    wall_ms = (time.perf_counter() - t0) * 1000

    if proc.returncode != 0:
        raise RuntimeError(f"child failed ({proc.returncode}): {proc.stderr[-500:]}")

    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    n = payload["n_coords"]
    return ScenarioResult(
        scenario=name,
        elapsed_ms=payload["elapsed_ms"],
        n_coords=n,
        n_missing=payload["n_missing"],
        reuse_pct=100.0 * (1 - payload["n_missing"] / n) if n else 0.0,
        resolution_m=payload["resolution_m"],
        samples_ms=[round(payload["elapsed_ms"], 1)],
        process_wall_ms=round(wall_ms, 1),
    )


def run_child(fixture: str, panned: bool, cache_root: Path) -> int:
    """Child mode: one timed get_elevations in this fresh process, JSON to stdout."""
    bbox = FIXTURES[fixture]["bbox"]
    if panned:
        bbox = pan_east(bbox, 0.5)
    coords, cache_coords, _, _ = prepare_viewport(bbox)
    svc = ElevationService(cache_dir=str(cache_root))
    elapsed_ms, n_missing, res = time_call(svc, coords, cache_coords)
    print(json.dumps({
        "elapsed_ms": round(elapsed_ms, 1),
        "n_coords": len(coords),
        "n_missing": n_missing,
        "resolution_m": res,
    }))
    return 0


def scenario(name: str, svc_factory, coords, cache_coords, repeats: int = 1) -> ScenarioResult:
    """Run one scenario `repeats` times, reporting the median.

    svc_factory is called once per repeat, so a scenario that wants a *fresh*
    service (cold_instance) gets one each time and a scenario that wants the same
    one (warm_instance) closes over it.
    """
    samples, missing_first, res = [], None, 0.0
    for _ in range(repeats):
        svc = svc_factory()
        ms, n_missing, res = time_call(svc, coords, cache_coords)
        samples.append(ms)
        if missing_first is None:
            missing_first = n_missing

    n = len(coords)
    return ScenarioResult(
        scenario=name,
        elapsed_ms=statistics.median(samples),
        n_coords=n,
        n_missing=missing_first or 0,
        reuse_pct=100.0 * (1 - (missing_first or 0) / n) if n else 0.0,
        resolution_m=res,
        samples_ms=[round(s, 1) for s in samples],
    )


def run_fixture(key: str, cache_root: Path, clear: bool,
                cold_process: bool = True) -> FixtureResult:
    fx = FIXTURES[key]
    bbox = fx["bbox"]
    print(f"\n── {key}: {fx['desc']}", flush=True)

    coords, cache_coords, ways, overpass_ms = prepare_viewport(bbox)
    print(f"   overpass {overpass_ms:.0f} ms · {len(ways)} ways · "
          f"{len(cache_coords)} network nodes · {len(coords)} traversable nodes",
          flush=True)

    result = FixtureResult(
        name=key,
        desc=fx["desc"],
        bbox=bbox,
        n_nodes_network=len(cache_coords),
        n_nodes_needed=len(coords),
        n_ways=len(ways),
        overpass_ms=round(overpass_ms, 1),
    )

    elev_dir = cache_root / "elevation"
    if clear and elev_dir.exists():
        shutil.rmtree(elev_dir)

    # 1. cold — nothing on disk, fresh service.
    svc = ElevationService(cache_dir=str(cache_root))
    r = scenario("cold", lambda: svc, coords, cache_coords)
    result.scenarios.append(r)
    print(f"   cold           {r.elapsed_ms:>9.0f} ms  "
          f"({r.n_missing}/{r.n_coords} missing, {r.resolution_m:.0f} m source)", flush=True)

    # 2. warm_instance — same service: disk cache, open datasets, GDAL VSI all hot.
    r = scenario("warm_instance", lambda: svc, coords, cache_coords, REPEATS)
    result.scenarios.append(r)
    print(f"   warm_instance  {r.elapsed_ms:>9.1f} ms  "
          f"({r.reuse_pct:.0f}% reuse)  {r.samples_ms}", flush=True)

    # 3. cold_instance — new service each repeat: disk cache survives, in-memory
    #    caches do not. This is the Cloud Run min-instances 0 case.
    r = scenario("cold_instance",
                 lambda: ElevationService(cache_dir=str(cache_root)),
                 coords, cache_coords, REPEATS)
    result.scenarios.append(r)
    print(f"   cold_instance  {r.elapsed_ms:>9.1f} ms  "
          f"({r.reuse_pct:.0f}% reuse)  {r.samples_ms}", flush=True)

    # 4. pan_50 — half-screen pan. Half this viewport was fetched a moment ago.
    pan_bbox = pan_east(bbox, 0.5)
    p_coords, p_cache_coords, _, p_overpass_ms = prepare_viewport(pan_bbox)
    overlap = len(set(p_coords) & set(coords))
    r = scenario("pan_50", lambda: svc, p_coords, p_cache_coords)
    r.reuse_pct = 100.0 * (1 - r.n_missing / r.n_coords) if r.n_coords else 0.0
    result.scenarios.append(r)
    print(f"   pan_50         {r.elapsed_ms:>9.0f} ms  "
          f"({r.n_coords} nodes, {overlap} geometrically shared with the "
          f"original, {r.reuse_pct:.0f}% actually reused)", flush=True)

    if not cold_process:
        return result

    # 5. Fresh interpreter, same viewport. Should hit the pickle, so GDAL never
    #    warms up and this is a pure cache-read measurement.
    r = cold_process_scenario("same_cold_process", key, False, cache_root, len(coords))
    result.scenarios.append(r)
    print(f"   same_cold_proc {r.elapsed_ms:>9.1f} ms  "
          f"({r.reuse_pct:.0f}% reuse, {r.process_wall_ms:.0f} ms incl. interpreter start)",
          flush=True)

    # 6. Fresh interpreter, panned viewport — the number the plan turns on.
    #    Step 4 just wrote a cache file FOR the panned viewport, which would make
    #    this a warm hit and measure nothing. Reset to the state a real user is in
    #    when they pan: original viewport cached, panned viewport not.
    if elev_dir.exists():
        shutil.rmtree(elev_dir)
    ElevationService(cache_dir=str(cache_root)).get_elevations(coords, None, cache_coords)

    r = cold_process_scenario("pan_50_cold_process", key, True, cache_root, len(coords))
    result.scenarios.append(r)
    print(f"   pan_cold_proc  {r.elapsed_ms:>9.0f} ms  "
          f"({r.reuse_pct:.0f}% reuse, {r.process_wall_ms:.0f} ms incl. interpreter start)",
          flush=True)

    return result


# ── Reporting ─────────────────────────────────────────────────────────────────

def summarize(results: list[FixtureResult]) -> None:
    def med(scn: str, attr: str = "elapsed_ms") -> float:
        vals = [getattr(s, attr) for r in results for s in r.scenarios if s.scenario == scn]
        return statistics.median(vals) if vals else float("nan")

    print("\n" + "═" * 78)
    print("M0 BASELINE — current elevation.py")
    print("═" * 78)
    print(f"{'scenario':<16}{'median ms':>12}{'median reuse':>16}")
    for scn in ("cold", "warm_instance", "cold_instance", "pan_50",
                "same_cold_process", "pan_50_cold_process"):
        if any(s.scenario == scn for r in results for s in r.scenarios):
            print(f"{scn:<16}{med(scn):>12.1f}{med(scn, 'reuse_pct'):>15.0f}%")

    dense = next((r for r in results if r.name == "dense_city"), None)
    if dense:
        cold = next(s for s in dense.scenarios if s.scenario == "cold")
        print(f"\ndense_city cold: {cold.elapsed_ms / 1000:.1f} s for "
              f"{cold.n_coords} nodes")

    pan_reuse = med("pan_50", "reuse_pct")
    print(f"\nPan reuse is the premise check: {pan_reuse:.0f}%. "
          f"{'Cache survives a pan — re-examine the plan.' if pan_reuse > 20 else 'A half-screen pan reuses nothing; the plan targets a real defect.'}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="M0 elevation baseline benchmark")
    ap.add_argument("--fixture", action="append", choices=list(FIXTURES),
                    help="run only these fixtures (repeatable)")
    ap.add_argument("--json", type=Path, help="write full results here")
    ap.add_argument("--cache-dir", type=Path,
                    default=Path.home() / ".cache" / "hillbomb-bench",
                    help="isolated cache root; not your real ~/.cache/hillbomb")
    ap.add_argument("--keep-cache", action="store_true",
                    help="don't clear the elevation cache before each fixture "
                         "(makes 'cold' meaningless — for repeat warm runs)")
    ap.add_argument("--no-cold-process", action="store_true",
                    help="skip the fresh-process scenarios (they respawn Python "
                         "per measurement and dominate runtime)")
    # Internal: re-invoked by cold_process_scenario. Not for direct use.
    ap.add_argument("--child", choices=list(FIXTURES), help=argparse.SUPPRESS)
    ap.add_argument("--child-panned", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args(argv)

    if args.child:
        return run_child(args.child, args.child_panned, args.cache_dir)

    keys = args.fixture or list(FIXTURES)
    args.cache_dir.mkdir(parents=True, exist_ok=True)
    print(f"cache root: {args.cache_dir}")

    results = []
    for k in keys:
        try:
            results.append(run_fixture(k, args.cache_dir,
                                       clear=not args.keep_cache,
                                       cold_process=not args.no_cold_process))
        except Exception as exc:  # one bad fixture shouldn't lose the others
            print(f"   FAILED: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)

    if not results:
        print("no fixtures completed", file=sys.stderr)
        return 1

    summarize(results)

    if args.json:
        args.json.write_text(json.dumps([asdict(r) for r in results], indent=2))
        print(f"\nwrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
