"""
COG (windowed byte-range) elevation reads over the Hawk Hill / Marin Headlands
area — the area exercised by test_hawk_hill_e2e.

Background
──────────
The 3DEP 1/3 arc-sec source can be read two ways:
  - "download": stream the whole ~200 MB n38w123 tile to disk on first touch,
    then read locally. Fast on warm repeats; brutal cold-start.
  - "cog" (default): open the tile over HTTP and read only the windowed byte
    ranges each query needs. No full-tile download — the design in CLAUDE.md.

These tests prove the COG path is (a) correct — its values match a per-point
ground-truth read of the same DEM — and (b) fast cold, without ever downloading
a full tile.

Run:   pytest -m integration -v backend/tests/test_elevation_cog.py
Skip:  pytest -m "not integration"   (the default)
"""

import math
import signal
import time
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
import rasterio

from backend.elevation import (
    _AWS_SESSION,
    ElevationService,
    _Dep13TileCache,
)

# Hawk Hill / Conzelman Road ridge — all within tile n38w123 (lat_tile 37, lon_tile -123).
# (west, south, east, north)
HAWK_HILL_BBOX = (-122.515, 37.820, -122.470, 37.845)
# The bbox runs west over the Pacific/bay, where 3DEP returns small negatives
# (NAVD88 tidal datum), up to the ~335 m Hawk Hill summit.
HAWK_HILL_ELEV_RANGE = (-5, 340)

# Deterministic ground-truth URL for n38w123 (matches _tile_url).
_N38W123_URL = (
    "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current"
    "/n38w123/USGS_13_n38w123.tif"
)


@contextmanager
def hard_timeout(seconds: int, label: str = ""):
    def _handler(signum, frame):
        raise TimeoutError(f"[TIMEOUT] {label!r} exceeded {seconds}s wall-clock limit")
    old = signal.signal(signal.SIGALRM, _handler)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old)


def make_grid(west, south, east, north, spacing_m):
    """Dense (lon, lat) grid at ~spacing_m metre intervals."""
    lat_c = (south + north) / 2
    dlat = spacing_m / 111_320
    dlon = spacing_m / (111_320 * math.cos(math.radians(lat_c)))
    lats = np.arange(south, north, dlat)
    lons = np.arange(west, east, dlon)
    lon_g, lat_g = np.meshgrid(lons, lats)
    return list(zip(lon_g.ravel().tolist(), lat_g.ravel().tolist()))


@pytest.fixture(scope="module")
def cog_cache(tmp_path_factory):
    """A COG-mode tile cache. tile_dir is unused in cog mode but kept for parity."""
    return _Dep13TileCache(tile_dir=tmp_path_factory.mktemp("cog_unused"), mode="cog")


# ── Correctness: windowed COG read == per-point ground truth ──────────────────

@pytest.mark.integration
def test_cog_matches_ground_truth_hawk_hill(cog_cache):
    """
    A scatter of points across Hawk Hill, read via the windowed COG path, must
    match a canonical per-point rasterio.sample() of the same remote DEM to
    within floating-point noise. Proves the rowcol→window→index math is correct.
    """
    # Coarse grid — the ground-truth read is one HTTP round trip *per point*.
    coords = make_grid(*HAWK_HILL_BBOX, spacing_m=400.0)
    assert 20 <= len(coords) <= 200, f"unexpected grid size {len(coords)}"

    with hard_timeout(60, "cog ground-truth"):
        got = cog_cache.sample(coords)

    # Ground truth: open the same remote COG and sample per point (the slow path).
    with hard_timeout(120, "ground-truth per-point sample"):
        with rasterio.Env(session=_AWS_SESSION):
            with rasterio.open(_N38W123_URL) as ds:
                nodata = ds.nodata
                truth = [
                    (float(v) if (v is not None and (nodata is None or v != nodata)) else None)
                    for (v,) in ds.sample(coords)
                ]

    compared = 0
    for g, t in zip(got, truth):
        if g is None or t is None:
            continue
        compared += 1
        assert abs(g - t) < 0.01, f"COG value {g} != ground truth {t}"
    assert compared >= len(coords) * 0.9, f"only {compared}/{len(coords)} points compared"


# ── Speed: cold COG read is fast and never downloads a full tile ──────────────

@pytest.mark.integration
def test_cog_cold_read_is_fast_no_download(cog_cache, tmp_path):
    """
    A full Hawk Hill grid read cold via COG must complete quickly (a windowed
    byte-range fetch, not a ~200 MB tile download) and write nothing to disk.
    """
    coords = make_grid(*HAWK_HILL_BBOX, spacing_m=15.0)
    assert len(coords) > 1_000, f"grid too small: {len(coords)}"

    fresh = _Dep13TileCache(tile_dir=tmp_path / "cold", mode="cog")
    with hard_timeout(30, "cog cold read"):
        t0 = time.perf_counter()
        result = fresh.sample(coords)
        cold_ms = (time.perf_counter() - t0) * 1000

    hits = sum(1 for v in result if v is not None)
    assert hits >= len(coords) * 0.9, f"hit rate low: {hits}/{len(coords)}"

    lo, hi = HAWK_HILL_ELEV_RANGE
    bad = [v for v in result if v is not None and not (lo <= v <= hi)]
    assert not bad, f"{len(bad)} elevations outside [{lo},{hi}]m: {bad[:3]}"

    # COG mode must not stage any local .tif tiles.
    assert not list((tmp_path / "cold").glob("*.tif")), "COG mode wrote a local tile"

    # Warm read (dataset now open in LRU) should be fast.
    with hard_timeout(10, "cog warm read"):
        t0 = time.perf_counter()
        fresh.sample(coords)
        warm_ms = (time.perf_counter() - t0) * 1000

    print(f"\n  hawk_hill COG ({len(coords)} pts): cold {cold_ms:.0f} ms, warm {warm_ms:.0f} ms")


# ── Full service path: get_elevations in COG mode over Hawk Hill ──────────────

@pytest.mark.integration
def test_get_elevations_cog_mode_hawk_hill(monkeypatch, tmp_path):
    """
    End-to-end: ElevationService in COG mode returns plausible Hawk Hill
    elevations at 1/3 arc-sec resolution, with no local tile download.
    """
    monkeypatch.setenv("HILLBOMB_DEP13_MODE", "cog")
    svc = ElevationService(cache_dir=str(tmp_path))

    coords = make_grid(*HAWK_HILL_BBOX, spacing_m=30.0)
    with hard_timeout(30, "get_elevations cog"):
        elevs = svc.get_elevations(coords)

    assert len(elevs) == len(coords)
    lo, hi = HAWK_HILL_ELEV_RANGE
    in_range = [e for e in elevs if lo <= e <= hi]
    assert len(in_range) >= len(coords) * 0.9, "too many elevations out of range"
    assert max(elevs) - min(elevs) > 100, "expected real relief across Hawk Hill"
    assert svc.resolution_m == 10.0
    assert not list((tmp_path / "dep13").glob("*.tif")), "COG mode wrote a local tile"


# ── Optional cross-check against download mode (only if tile already on disk) ──

@pytest.mark.integration
def test_cog_matches_download_mode_if_tile_present(cog_cache):
    """
    If the n38w123 tile is already on disk from a prior download-mode run, COG
    and download reads must agree. Skipped when no local tile exists (we won't
    trigger a ~200 MB download just for this comparison).
    """
    default_dir = Path.home() / ".cache" / "hillbomb" / "dep13"
    if not (default_dir / "USGS_13_n38w123.tif").exists():
        pytest.skip("no local n38w123 tile — skipping download-mode cross-check")

    coords = make_grid(*HAWK_HILL_BBOX, spacing_m=40.0)
    dl = _Dep13TileCache(tile_dir=default_dir, mode="download")

    r_cog = cog_cache.sample(coords)
    r_dl = dl.sample(coords)

    compared = 0
    for a, b in zip(r_cog, r_dl):
        if a is None or b is None:
            continue
        compared += 1
        assert abs(a - b) < 0.01, f"cog {a} != download {b}"
    assert compared >= len(coords) * 0.9
