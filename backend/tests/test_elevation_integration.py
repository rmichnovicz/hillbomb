"""
Integration tests for ElevationService.

These tests hit real external endpoints (USGS S3, skadi S3) on first run and
cache the results locally so subsequent runs don't need network access.

Cache locations:
  HTTP API responses (JSON):   tests/fixtures/elevation/http/<hash>.json
    → small, committed to git
  SRTM tile files (.hgt):      ~/.cache/hillbomb/srtm/
    → large, gitignored — auto-downloaded on first run
  3DEP tiles:                  not cached locally (HTTP COG via rasterio)

Run:      pytest -m integration
Skip CI:  pytest -m "not integration"  (the default)
"""

import hashlib
import json
from pathlib import Path
from unittest.mock import MagicMock

import httpx
import pytest

from backend.elevation import ElevationService, _DEP13_S3

# ── Fixture paths ─────────────────────────────────────────────────────────────

FIXTURE_DIR = Path(__file__).parent / "fixtures" / "elevation"
HTTP_CACHE_DIR = FIXTURE_DIR / "http"

# Real-world test coordinates
TWIN_PEAKS_COORDS = [
    (-122.4477, 37.7544),  # North Peak
    (-122.4527, 37.7519),  # South Peak
]
# Cape Town — non-US, SRTM-only
CAPE_TOWN_COORDS = [
    (18.4241, -33.9249),
]


# ── HTTP caching fixture ──────────────────────────────────────────────────────

def _cache_key(url: str, params: dict | None) -> str:
    sorted_params = sorted((params or {}).items())
    canonical = url + "?" + "&".join(f"{k}={v}" for k, v in sorted_params)
    return hashlib.sha256(canonical.encode()).hexdigest()[:20]


@pytest.fixture
def cached_http(monkeypatch):
    """
    Intercepts httpx.get in backend.elevation.
    Cache miss: hits the real endpoint, saves JSON response to FIXTURE_DIR/http/.
    Cache hit: loads the saved JSON and returns a mock response.

    Committed JSON files make tests network-free after the first run.
    """
    HTTP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    real_get = httpx.get

    def patched_get(url, *, params=None, timeout=None, **kwargs):
        key = _cache_key(url, params)
        cache_file = HTTP_CACHE_DIR / f"{key}.json"

        if cache_file.exists():
            stored = json.loads(cache_file.read_text())
            mock = MagicMock()
            mock.status_code = stored["status_code"]
            mock.json.return_value = stored["body"]
            if stored["status_code"] >= 400:
                mock.raise_for_status.side_effect = httpx.HTTPStatusError(
                    f"HTTP {stored['status_code']}", request=MagicMock(), response=mock
                )
            else:
                mock.raise_for_status.return_value = None
            return mock

        resp = real_get(url, params=params, timeout=timeout, **kwargs)
        if resp.status_code == 200:
            try:
                cache_file.write_text(json.dumps({
                    "url": url,
                    "params": dict(params or {}),
                    "status_code": resp.status_code,
                    "body": resp.json(),
                }, indent=2))
            except Exception:
                pass
        return resp

    monkeypatch.setattr(httpx, "get", patched_get)
    return HTTP_CACHE_DIR


@pytest.fixture
def svc(cached_http):
    """ElevationService using default tile dirs with cached HTTP calls."""
    return ElevationService()


# ── _Dep13TileCache URL construction ─────────────────────────────────────────

@pytest.mark.integration
def test_dep13_tile_url_sf_exists(svc):
    """Tile URL for SF area (lat=37, lon=-123) is well-formed."""
    url = svc._dep13._tile_url(37, -123)
    assert url is not None
    assert "n38w123" in url
    assert url.startswith(_DEP13_S3)


@pytest.mark.integration
def test_dep13_tile_url_none_for_cape_town(svc):
    """Cape Town (south hemisphere) returns None immediately — no network call."""
    assert svc._dep13._tile_url(-34, 18) is None


# ── _Dep13TileCache local tile sampling ───────────────────────────────────────

@pytest.mark.integration
def test_dep13_sample_twin_peaks(svc):
    """
    3DEP 1/3 arc-sec returns valid elevations for Twin Peaks, SF.
    Twin Peaks summits are ~281m; surrounding streets ~90m.
    First run downloads the tile; subsequent runs read from disk.
    """
    result = svc._dep13.sample(TWIN_PEAKS_COORDS)
    assert len(result) == 2
    for e in result:
        assert e is not None, "3DEP tile returned None for Twin Peaks — tile download may have failed"
        assert 50 <= e <= 400, f"Elevation {e}m outside expected range for SF"


@pytest.mark.integration
def test_dep13_sample_cape_town_returns_none(svc):
    """Cape Town is outside 3DEP coverage — all results should be None."""
    result = svc._dep13.sample(CAPE_TOWN_COORDS)
    assert result == [None]


# ── SRTM download ─────────────────────────────────────────────────────────────

@pytest.mark.integration
def test_srtm_download_sf_tile(svc):
    """
    Downloads N37W123 from skadi S3.
    Tile is saved to ~/.cache/hillbomb/srtm/ and reused on subsequent runs.
    """
    path = svc._srtm_tile_path(37, -123)
    if path.exists():
        pytest.skip("SRTM tile already cached — nothing to download")

    result = svc._download_srtm_tile(37, -123)
    assert result is True, "SRTM download failed"
    assert path.exists()
    assert path.stat().st_size > 1_000_000, "HGT tile suspiciously small"


@pytest.mark.integration
def test_srtm_download_southern_hemisphere(svc):
    """Downloads a southern-hemisphere SRTM tile (Cape Town area)."""
    path = svc._srtm_tile_path(-34, 18)
    if path.exists():
        pytest.skip("SRTM tile already cached")

    result = svc._download_srtm_tile(-34, 18)
    assert result is True
    assert path.exists()


# ── Full elevation cascade ────────────────────────────────────────────────────

@pytest.mark.integration
def test_get_elevations_twin_peaks(svc):
    """
    Twin Peaks, SF — elevation should be ~280m ASL.
    Uses 3DEP 1/3 arc-sec (HTTP COG from USGS S3).
    """
    elevs = svc.get_elevations(TWIN_PEAKS_COORDS)
    assert len(elevs) == len(TWIN_PEAKS_COORDS)
    for e in elevs:
        assert 50 <= e <= 400, f"Elevation {e}m outside expected range for SF"
    assert svc.resolution_m in (1.0, 10.0, 30.0)


@pytest.mark.integration
def test_get_elevations_cape_town_uses_srtm(svc):
    """Non-US coordinates must fall through to SRTM."""
    elevs = svc.get_elevations(CAPE_TOWN_COORDS)
    assert len(elevs) == 1
    # Central Cape Town is ~10m; Table Mountain is ~1086m
    assert 0 <= elevs[0] <= 1200, f"Elevation {elevs[0]}m outside expected range for Cape Town"
    assert svc.resolution_m == 30.0


@pytest.mark.integration
def test_get_elevations_empty_returns_empty(svc):
    assert svc.get_elevations([]) == []


@pytest.mark.integration
def test_resolution_m_set_after_call(svc):
    """resolution_m reflects the source that was actually used."""
    svc.get_elevations(TWIN_PEAKS_COORDS)
    assert svc.resolution_m in (1.0, 10.0, 30.0)
