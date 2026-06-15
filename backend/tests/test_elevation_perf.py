"""
Performance time trials for _Dep13TileCache.

What these tests measure
────────────────────────
  download    — first access to a tile not yet on disk (network + open)
  cold_open   — first ds.read() after tile exists on disk but dataset not open
  warm_sparse — ~200 points, open dataset, no I/O beyond GDAL's block cache
  warm_dense  — ~5 000 points, single window read + numpy indexing
  cross_tile  — query spanning two 1° tiles, read in parallel

Hard wall-clock timeouts via SIGALRM — each test kills itself before the
pytest process timeout would fire. Tests that exceed the limit fail loudly
rather than hanging the suite.

Run:   pytest -m integration -v tests/test_elevation_perf.py
Skip:  pytest -m "not integration"  (the default)
"""

import math
import signal
import time
from contextlib import contextmanager

import numpy as np
import pytest

from backend.elevation import ElevationService

# ── Hard timeout ──────────────────────────────────────────────────────────────

@contextmanager
def hard_timeout(seconds: int, label: str = ""):
    """SIGALRM hard kill. Raises TimeoutError before pytest's own timeout fires."""
    def _handler(signum, frame):
        raise TimeoutError(f"[TIMEOUT] {label!r} exceeded {seconds}s wall-clock limit")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


# ── Grid helpers ──────────────────────────────────────────────────────────────

def make_grid(west: float, south: float, east: float, north: float, spacing_m: float):
    """Dense (lon, lat) grid at ~spacing_m metre intervals."""
    lat_c = (south + north) / 2
    dlat = spacing_m / 111_320
    dlon = spacing_m / (111_320 * math.cos(math.radians(lat_c)))
    lats = np.arange(south, north, dlat)
    lons = np.arange(west, east, dlon)
    lon_g, lat_g = np.meshgrid(lons, lats)
    return list(zip(lon_g.ravel().tolist(), lat_g.ravel().tolist()))


# ── Search areas ──────────────────────────────────────────────────────────────
#
# All SF/Marin areas are within tile n38w123.
# Oakland Hills uses n38w122 — the cross-tile test deliberately hits both.

AREAS = {
    # SF
    "twin_peaks": {
        "bbox": (-122.460, 37.745, -122.440, 37.760),
        "desc": "Twin Peaks — dual-summit, 280 m",
        "elev_range": (60, 320),
    },
    "potrero_hill": {
        "bbox": (-122.410, 37.754, -122.390, 37.768),
        "desc": "Potrero Hill — residential grid, moderate grade",
        # Lower bound allows the NAVD88 tidal datum (~-1.6 m) where the eastern
        # edge meets the bay; 3DEP returns small negatives over water.
        "elev_range": (-5, 110),
    },
    "corona_heights": {
        "bbox": (-122.443, 37.762, -122.427, 37.772),
        "desc": "Corona Heights — steep rocky summit",
        "elev_range": (-5, 180),
    },
    # Marin
    "hawk_hill": {
        "bbox": (-122.495, 37.823, -122.468, 37.840),
        "desc": "Hawk Hill / Conzelman Rd — classic bomb",
        # West/south edges run over the Golden Gate; allow the tidal datum.
        "elev_range": (-5, 335),
    },
    "mill_valley": {
        "bbox": (-122.560, 37.900, -122.540, 37.916),
        "desc": "Mill Valley — steep tree-lined streets",
        "elev_range": (0, 425),
    },
}


# ── Service fixture (module-scoped so tile is shared across all tests) ────────

@pytest.fixture(scope="module")
def svc(tmp_path_factory):
    # This file specifically exercises the local-tile DOWNLOAD cache (download +
    # cold_open + warm reads from disk). The service default is now "cog"
    # (windowed HTTP reads, no download), so force download mode here.
    # COG-mode coverage lives in test_elevation_cog.py.
    cache = tmp_path_factory.mktemp("hillbomb_perf_cache")
    svc = ElevationService(cache_dir=str(cache))
    svc._dep13._mode = "download"
    return svc


@pytest.fixture(scope="module")
def warm_sf_tile(svc):
    """
    Ensure n38w123 is on disk and open before any timing test runs.
    Allowed up to 120 s for the initial download (~40–80 MB tile).
    """
    with hard_timeout(120, "SF tile warm-up download"):
        svc._dep13.sample([(-122.45, 37.75)])


@pytest.fixture(scope="module")
def warm_marin_tile(svc, warm_sf_tile):
    """n38w123 covers both SF and Marin — warm_sf_tile is sufficient."""
    return  # same tile; fixture exists for clarity in test signatures


# ── Download timing (runs first; cold network) ────────────────────────────────

@pytest.mark.integration
def test_sf_tile_cold_download(svc):
    """
    Measures time for the first access to n38w123 (download + open + read).
    If the tile is already cached, the test is skipped.
    Allowed up to 120 s.
    """
    tile_path = svc._dep13._tile_path(37, -123)
    if tile_path.exists():
        pytest.skip("n38w123 already on disk — skipping download timing")

    with hard_timeout(120, "SF tile cold download"):
        t0 = time.perf_counter()
        result = svc._dep13.sample([(-122.45, 37.75)])
        elapsed = time.perf_counter() - t0

    assert result[0] is not None, "No elevation returned — download may have failed"
    print(f"\n  n38w123 cold download + first read: {elapsed:.2f}s")


# ── Single-tile warm reads ────────────────────────────────────────────────────

@pytest.mark.integration
@pytest.mark.parametrize("area_key", list(AREAS))
def test_warm_sparse(svc, warm_sf_tile, warm_marin_tile, area_key):
    """
    ~200 points at 100 m spacing — typical path node density.
    Limit: 3 s.  Expected: < 50 ms once dataset is open.
    """
    area = AREAS[area_key]
    coords = make_grid(*area["bbox"], spacing_m=100.0)
    assert 10 <= len(coords) <= 600, f"Unexpected sparse grid size {len(coords)}"

    with hard_timeout(3, f"warm_sparse/{area_key}"):
        t0 = time.perf_counter()
        result = svc._dep13.sample(coords)
        elapsed = time.perf_counter() - t0

    hits = sum(1 for v in result if v is not None)
    assert hits >= len(coords) * 0.9, f"Hit rate too low: {hits}/{len(coords)}"

    lo, hi = area["elev_range"]
    bad = [v for v in result if v is not None and not (lo <= v <= hi)]
    assert not bad, f"{len(bad)} elevations outside [{lo},{hi}]m for {area_key}: {bad[:3]}"

    print(f"\n  {area_key} sparse ({len(coords)} pts): {elapsed * 1000:.1f} ms")


@pytest.mark.integration
@pytest.mark.parametrize("area_key", list(AREAS))
def test_warm_dense(svc, warm_sf_tile, warm_marin_tile, area_key):
    """
    ~5 000 points at 10 m spacing — full overpass graph density.
    Limit: 5 s.  Expected: < 200 ms (single window read + numpy indexing).
    """
    area = AREAS[area_key]
    coords = make_grid(*area["bbox"], spacing_m=10.0)
    assert 500 <= len(coords) <= 60_000, f"Unexpected dense grid size {len(coords)}"

    with hard_timeout(5, f"warm_dense/{area_key}"):
        t0 = time.perf_counter()
        result = svc._dep13.sample(coords)
        elapsed = time.perf_counter() - t0

    hits = sum(1 for v in result if v is not None)
    assert hits >= len(coords) * 0.9, f"Hit rate too low: {hits}/{len(coords)}"

    throughput = len(coords) / elapsed
    print(
        f"\n  {area_key} dense ({len(coords)} pts): "
        f"{elapsed * 1000:.1f} ms  ({throughput:,.0f} pts/s)"
    )


# ── Cross-tile query (parallel reads) ────────────────────────────────────────

@pytest.mark.integration
def test_cross_tile_sf_and_oakland(svc, warm_sf_tile):
    """
    Twin Peaks (n38w123) + Oakland Hills (n38w122) in one call.
    n38w122 may be a cold download — allowed up to 120 s.
    After both tiles are open, repeated calls should be fast (< 5 s).
    Verifies parallel tile read path in _Dep13TileCache.sample().
    """
    coords_sf = make_grid(-122.460, 37.745, -122.440, 37.760, spacing_m=50.0)   # n38w123
    coords_oak = make_grid(-122.080, 37.745, -122.060, 37.760, spacing_m=50.0)  # n38w122
    coords = coords_sf + coords_oak
    n_sf = len(coords_sf)

    with hard_timeout(120, "cross_tile cold"):
        t0 = time.perf_counter()
        result = svc._dep13.sample(coords)
        elapsed_cold = time.perf_counter() - t0

    sf_hits = sum(1 for v in result[:n_sf] if v is not None)
    oak_hits = sum(1 for v in result[n_sf:] if v is not None)
    assert sf_hits >= n_sf * 0.9, f"SF hit rate low: {sf_hits}/{n_sf}"
    assert oak_hits >= len(coords_oak) * 0.9, f"Oakland hit rate low: {oak_hits}/{len(coords_oak)}"

    print(f"\n  cross_tile cold ({len(coords)} pts, 2 tiles): {elapsed_cold * 1000:.1f} ms")

    # Warm cross-tile read — both datasets now open
    with hard_timeout(5, "cross_tile warm"):
        t0 = time.perf_counter()
        svc._dep13.sample(coords)
        elapsed_warm = time.perf_counter() - t0

    print(f"  cross_tile warm ({len(coords)} pts, 2 tiles): {elapsed_warm * 1000:.1f} ms")


# ── Repeat-call stability ─────────────────────────────────────────────────────

@pytest.mark.integration
def test_repeat_calls_stable(svc, warm_sf_tile):
    """
    Three consecutive dense calls on the same area.
    No call should be more than 3× the fastest — detects re-open / cache eviction bugs.
    Limit: 3 s each.
    """
    coords = make_grid(*AREAS["twin_peaks"]["bbox"], spacing_m=15.0)
    times = []

    for _ in range(3):
        with hard_timeout(3, "repeat_call"):
            t0 = time.perf_counter()
            svc._dep13.sample(coords)
            times.append(time.perf_counter() - t0)

    ratio = max(times) / min(times)
    assert ratio < 3.0, (
        f"Repeat-call times inconsistent (ratio {ratio:.1f}×): "
        f"{[f'{t * 1000:.1f}ms' for t in times]}"
    )
    print(f"\n  repeat x3 ({len(coords)} pts): {[f'{t * 1000:.1f}ms' for t in times]}")


# ── Stress: very large dense grid ────────────────────────────────────────────

@pytest.mark.integration
def test_very_large_grid(svc, warm_sf_tile):
    """
    ~30 000 points at 5 m spacing over Twin Peaks — stress test for window read.
    Limit: 10 s.  Window read should handle this in a single ds.read() call.
    """
    coords = make_grid(*AREAS["twin_peaks"]["bbox"], spacing_m=5.0)
    assert len(coords) > 5_000, f"Grid too small: {len(coords)}"

    with hard_timeout(10, "very_large_grid"):
        t0 = time.perf_counter()
        result = svc._dep13.sample(coords)
        elapsed = time.perf_counter() - t0

    hits = sum(1 for v in result if v is not None)
    assert hits >= len(coords) * 0.9
    print(
        f"\n  very_large ({len(coords)} pts at 5m): "
        f"{elapsed * 1000:.1f} ms  ({len(coords) / elapsed:,.0f} pts/s)"
    )
