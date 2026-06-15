"""
Tests for the ElevationService resolution cascade and _Dep13TileCache.

External dependencies (rasterio, httpx) are mocked throughout — these tests
run fully in-process with no network or filesystem access.

Test sections:
  - Resolution cascade logic (1m → 1/3 arc-sec → SRTM)
  - resolution_m is set to match the winning source
  - Coverage check (_has_1m_coverage)
  - SRTM tile path naming
  - _Dep13TileCache: tile URL construction, sampling, failure caching
  - SRTM: auto-download on missing tile (_download_srtm_tile, _sample_srtm)
  - Startup coverage load (success + failure)
"""

import gzip
import threading
from pathlib import Path
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from ..elevation import (
    ElevationService,
    SearchCancelled,
    _Dep13TileCache,
    _DATASET_1M,
    _DEP13_S3,
    _RES_1M,
    _RES_13,
    _RES_SRTM,
    _SRTM_SKADI,
)


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def svc(tmp_path, monkeypatch):
    """ElevationService with HILLBOMB_USE_1M=false (default) — no startup HTTP call."""
    monkeypatch.delenv("HILLBOMB_USE_1M", raising=False)
    return ElevationService(srtm_dir=str(tmp_path), cache_dir=str(tmp_path))


@pytest.fixture
def svc_1m(tmp_path, monkeypatch):
    """ElevationService with HILLBOMB_USE_1M=true and coverage load suppressed."""
    monkeypatch.setenv("HILLBOMB_USE_1M", "true")
    with patch.object(ElevationService, "_load_1m_coverage"):
        return ElevationService(srtm_dir=str(tmp_path), cache_dir=str(tmp_path))


@pytest.fixture
def dep13(tmp_path):
    """Bare _Dep13TileCache for unit-testing its internals."""
    return _Dep13TileCache(tile_dir=tmp_path / "dep13")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_srtm_mock_dataset(values: list[float], nodata=None, is_geographic=True):
    """Mock dataset for SRTM tests — uses ds.sample() (one value per point)."""
    ds = MagicMock()
    ds.nodata = nodata
    ds.crs.is_geographic = is_geographic
    ds.sample.return_value = iter([[v] for v in values])
    ds.__enter__ = lambda s: s
    ds.__exit__ = MagicMock(return_value=False)
    return ds


def _make_dep13_entry(
    data_2d: np.ndarray,
    lon_origin: float = -122.6,
    lat_origin: float = 37.7,
    res: float = 0.01,
    nodata=None,
):
    """
    Return a (DatasetReader mock, Lock) for _Dep13TileCache._get_dataset.

    Resolution 0.01 deg/px is coarser than real 3DEP but keeps pixel indices
    small so tests don't need huge arrays:

      col = floor((lon - lon_origin) / res)
      row = floor((lat_origin - lat) / res)

    ds.read() returns the correct window subarray so the code's
    `data[vrows - r0, vcols - c0]` indexing works as with a real dataset.
    """
    import affine
    ds = MagicMock()
    ds.nodata = nodata
    ds.height, ds.width = data_2d.shape
    ds.transform = affine.Affine(res, 0.0, lon_origin, 0.0, -res, lat_origin)

    def _read(band, window=None):
        if window is None:
            return data_2d
        r, c = window.row_off, window.col_off
        return data_2d[r:r + window.height, c:c + window.width]

    ds.read.side_effect = _read
    return (ds, threading.Lock())


# ── Empty input ───────────────────────────────────────────────────────────────

def test_empty_coords_returns_empty(svc):
    assert svc.get_elevations([]) == []


# ── Coverage check ────────────────────────────────────────────────────────────

def test_has_1m_coverage_overlapping(svc):
    svc._1m_coverage = [(37.0, -123.0, 38.0, -122.0)]
    assert svc._has_1m_coverage(37.5, -122.5, 37.7, -122.3)


def test_has_1m_coverage_adjacent_does_not_overlap(svc):
    svc._1m_coverage = [(37.0, -123.0, 38.0, -122.0)]
    assert not svc._has_1m_coverage(38.0, -122.5, 38.5, -122.3)


def test_has_1m_coverage_no_tiles(svc):
    svc._1m_coverage = []
    assert not svc._has_1m_coverage(37.0, -122.0, 38.0, -121.0)


def test_has_1m_coverage_multiple_tiles_one_matches(svc):
    svc._1m_coverage = [
        (40.0, -75.0, 41.0, -74.0),
        (37.0, -123.0, 38.0, -122.0),
    ]
    assert svc._has_1m_coverage(37.5, -122.5, 37.6, -122.4)
    assert not svc._has_1m_coverage(35.0, -120.0, 35.5, -119.5)


# ── SRTM tile path ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("lat_tile,lon_tile,expected_name", [
    (37, -123, "N37W123.hgt"),
    (37, -122, "N37W122.hgt"),
    (0,  -1,   "N00W001.hgt"),
    (-1, -1,   "S01W001.hgt"),
    (-34, 18,  "S34E018.hgt"),
    (51,  0,   "N51E000.hgt"),
])
def test_srtm_tile_path(svc, lat_tile, lon_tile, expected_name):
    assert svc._srtm_tile_path(lat_tile, lon_tile).name == expected_name


# ── Resolution cascade ────────────────────────────────────────────────────────

def test_1m_disabled_by_default(svc):
    """With HILLBOMB_USE_1M unset, 1m source is never attempted even with coverage."""
    svc._1m_coverage = [(37.0, -123.0, 38.0, -122.0)]
    coords = [(-122.5, 37.5)]
    elevs_13 = [45.0]

    with patch.object(svc._dep13, "sample", return_value=elevs_13) as mock_13, \
         patch.object(svc, "_sample_1m_cog") as mock_1m:
        result = svc.get_elevations(coords)

    assert result == elevs_13
    mock_1m.assert_not_called()
    mock_13.assert_called_once_with(coords, None)


def test_1m_enabled_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("HILLBOMB_USE_1M", "true")
    with patch.object(ElevationService, "_load_1m_coverage"):
        svc = ElevationService(srtm_dir=str(tmp_path))
    assert svc._use_1m is True


def test_1m_disabled_flag(monkeypatch, tmp_path):
    monkeypatch.setenv("HILLBOMB_USE_1M", "false")
    svc = ElevationService(srtm_dir=str(tmp_path))
    assert svc._use_1m is False


def test_1m_succeeds_returns_1m_resolution(svc_1m):
    svc_1m._1m_coverage = [(37.0, -123.0, 38.0, -122.0)]
    coords = [(-122.5, 37.5), (-122.4, 37.6)]
    elevs_1m = [45.0, 52.0]

    with patch.object(svc_1m, "_sample_1m_cog", return_value=elevs_1m), \
         patch.object(svc_1m._dep13, "sample") as mock_13:
        result = svc_1m.get_elevations(coords)

    assert result == elevs_1m
    assert svc_1m.resolution_m == _RES_1M
    mock_13.assert_not_called()


def test_no_1m_coverage_skips_to_13(svc_1m):
    svc_1m._1m_coverage = []
    coords = [(-122.5, 37.5)]
    elevs_13 = [45.0]

    with patch.object(svc_1m._dep13, "sample", return_value=elevs_13) as mock_13, \
         patch.object(svc_1m, "_sample_1m_cog") as mock_1m:
        result = svc_1m.get_elevations(coords)

    assert result == elevs_13
    assert svc_1m.resolution_m == _RES_13
    mock_1m.assert_not_called()
    mock_13.assert_called_once_with(coords, None)


def test_1m_partial_failure_falls_through_to_13(svc_1m):
    svc_1m._1m_coverage = [(37.0, -123.0, 38.0, -122.0)]
    coords = [(-122.5, 37.5), (-122.4, 37.6)]

    with patch.object(svc_1m, "_sample_1m_cog", return_value=[45.0, None]), \
         patch.object(svc_1m._dep13, "sample", return_value=[45.0, 52.0]):
        result = svc_1m.get_elevations(coords)

    assert result == [45.0, 52.0]
    assert svc_1m.resolution_m == _RES_13


def test_13_succeeds_returns_13_resolution(svc):
    coords = [(-122.5, 37.5), (-122.4, 37.6)]
    with patch.object(svc._dep13, "sample", return_value=[45.0, 52.0]):
        result = svc.get_elevations(coords)
    assert result == [45.0, 52.0]
    assert svc.resolution_m == _RES_13


def test_13_partial_falls_through_to_srtm(svc):
    coords = [(-80.0, 10.0), (-79.0, 11.0)]
    with patch.object(svc._dep13, "sample", return_value=[None, None]), \
         patch.object(svc, "_sample_srtm", return_value=[300.0, 350.0]):
        result = svc.get_elevations(coords)
    assert result == [300.0, 350.0]
    assert svc.resolution_m == _RES_SRTM


def test_13_partial_srtm_fills_gaps(svc):
    coords = [(-80.0, 10.0), (-79.0, 11.0), (-78.0, 12.0)]
    with patch.object(svc._dep13, "sample", return_value=[300.0, None, 320.0]), \
         patch.object(svc, "_sample_srtm", return_value=[0.0, 350.0, 0.0]):
        result = svc.get_elevations(coords)
    assert result == [300.0, 350.0, 320.0]
    assert svc.resolution_m == _RES_13  # majority from 1/3 arc-sec


def test_all_srtm_sets_srtm_resolution(svc):
    coords = [(-80.0, 10.0), (-79.0, 11.0)]
    with patch.object(svc._dep13, "sample", return_value=[None, None]), \
         patch.object(svc, "_sample_srtm", return_value=[300.0, 350.0]):
        svc.get_elevations(coords)
    assert svc.resolution_m == _RES_SRTM


# ── _Dep13TileCache: tile URL construction ────────────────────────────────────

def test_dep13_tile_url_sf(dep13):
    url = dep13._tile_url(37, -123)
    assert url == f"{_DEP13_S3}/n38w123/USGS_13_n38w123.tif"


def test_dep13_tile_url_denver(dep13):
    url = dep13._tile_url(39, -105)
    assert url == f"{_DEP13_S3}/n40w105/USGS_13_n40w105.tif"


def test_dep13_tile_url_lat0_west(dep13):
    url = dep13._tile_url(0, -1)
    assert url == f"{_DEP13_S3}/n01w001/USGS_13_n01w001.tif"


def test_dep13_tile_url_none_south_hemisphere(dep13):
    assert dep13._tile_url(-34, 18) is None


def test_dep13_tile_url_none_east_hemisphere(dep13):
    assert dep13._tile_url(51, 0) is None
    assert dep13._tile_url(37, 10) is None


# ── _Dep13TileCache: sample() ─────────────────────────────────────────────────

def test_dep13_sample_returns_elevations(dep13):
    """Valid SF coords return expected elevations from the mocked dataset.

    Transform: origin (-122.6, 37.7) at 0.01 deg/px
      col = floor((lon - (-122.6)) / 0.01)   row = floor((37.7 - lat) / 0.01)
      (-122.5, 37.6) → col=10, row=10
      (-122.55, 37.55) → col=5, row=15
    """
    data = np.zeros((30, 30), dtype=np.float32)
    data[10, 10] = 45.0
    data[15, 5] = 52.0
    entry = _make_dep13_entry(data)
    coords = [(-122.5, 37.6), (-122.55, 37.55)]

    with patch.object(dep13, "_get_dataset", return_value=entry):
        result = dep13.sample(coords)

    assert result[0] == pytest.approx(45.0)
    assert result[1] == pytest.approx(52.0)


def test_dep13_sample_outside_conus_returns_none(dep13):
    """Cape Town (south hemisphere) → _tile_name returns None → _get_dataset not reached."""
    result = dep13.sample([(18.0, -34.0)])
    assert result == [None]


def test_dep13_sample_get_dataset_failure_returns_none(dep13):
    """When _get_dataset returns None (bad tile), result is None."""
    with patch.object(dep13, "_get_dataset", return_value=None):
        result = dep13.sample([(-122.5, 37.5)])
    assert result == [None]


def test_dep13_sample_nodata_treated_as_none(dep13):
    data = np.full((30, 30), -9999.0, dtype=np.float32)
    entry = _make_dep13_entry(data, nodata=-9999.0)
    with patch.object(dep13, "_get_dataset", return_value=entry):
        result = dep13.sample([(-122.5, 37.6)])
    assert result == [None]


def test_dep13_sample_read_exception_returns_none(dep13):
    data = np.zeros((30, 30), dtype=np.float32)
    ds, lock = _make_dep13_entry(data)
    ds.read.side_effect = Exception("disk error")
    with patch.object(dep13, "_get_dataset", return_value=(ds, lock)):
        result = dep13.sample([(-122.5, 37.6)])
    assert result == [None]


def test_dep13_sample_bad_tiles_skips_download(dep13, tmp_path):
    """Tiles in _bad_tiles skip the download attempt and return None immediately."""
    dep13._bad_tiles.add((37, -123))

    download_attempted = []
    real_stream = __import__("httpx").stream

    with patch("httpx.stream", side_effect=lambda *a, **kw: download_attempted.append(a) or real_stream(*a, **kw)):
        result1 = dep13.sample([(-122.5, 37.6)])
        result2 = dep13.sample([(-122.5, 37.6)])

    assert result1 == [None]
    assert result2 == [None]
    assert len(download_attempted) == 0, "download should be skipped for bad tiles"


def test_dep13_sample_coords_spanning_two_tiles(dep13):
    """Points in two different tiles are handled independently.

    Tile n38w123 (lon_tile=-123): (-122.5, 37.6) → col=10, row=10 with origin (-122.6, 37.7)
    Tile n38w122 (lon_tile=-122): (-121.5, 37.6) → col=10, row=10 with origin (-121.6, 37.7)
    Each entry gets its own origin so coords map to small pixel indices.
    """
    data_a = np.zeros((30, 30), dtype=np.float32)
    data_a[10, 10] = 45.0
    data_b = np.zeros((30, 30), dtype=np.float32)
    data_b[10, 10] = 80.0
    entry_a = _make_dep13_entry(data_a, lon_origin=-122.6)           # covers tile n38w123
    entry_b = _make_dep13_entry(data_b, lon_origin=-121.6)           # covers tile n38w122

    def fake_get(lat_tile, lon_tile):
        return entry_a if lon_tile == -123 else entry_b

    coords = [(-122.5, 37.6), (-121.5, 37.6)]
    with patch.object(dep13, "_get_dataset", side_effect=fake_get):
        result = dep13.sample(coords)

    assert result[0] == pytest.approx(45.0)
    assert result[1] == pytest.approx(80.0)


# ── SRTM auto-download: _download_srtm_tile ───────────────────────────────────

def test_download_srtm_tile_success(svc, tmp_path):
    hgt_bytes = b"\x00\x64" * 100
    gz_bytes = gzip.compress(hgt_bytes)
    mock_resp = MagicMock()
    mock_resp.content = gz_bytes

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        ok = svc._download_srtm_tile(37, -123)

    assert ok is True
    assert (tmp_path / "N37W123.hgt").exists()
    assert (tmp_path / "N37W123.hgt").read_bytes() == hgt_bytes
    called_url = mock_get.call_args[0][0]
    assert "N37/N37W123.hgt.gz" in called_url
    assert _SRTM_SKADI in called_url


def test_download_srtm_tile_southern_hemisphere(svc):
    gz_bytes = gzip.compress(b"\x00" * 10)
    mock_resp = MagicMock()
    mock_resp.content = gz_bytes

    with patch("httpx.get", return_value=mock_resp) as mock_get:
        svc._download_srtm_tile(-34, 18)

    called_url = mock_get.call_args[0][0]
    assert "S34/S34E018.hgt.gz" in called_url


def test_download_srtm_tile_http_failure_returns_false(svc):
    with patch("httpx.get", side_effect=Exception("timeout")):
        ok = svc._download_srtm_tile(37, -123)
    assert ok is False


# ── SRTM sampling: _sample_srtm with auto-download ───────────────────────────

def test_sample_srtm_missing_tile_triggers_download(svc, tmp_path):
    """When tile is absent, _download_srtm_tile is called and then the tile is read."""
    mock_ds = _make_srtm_mock_dataset([250.0])

    def fake_download(lat_tile, lon_tile):
        (tmp_path / f"N{lat_tile:02d}W{abs(lon_tile):03d}.hgt").touch()
        return True

    with patch.object(svc, "_download_srtm_tile", side_effect=fake_download) as mock_dl, \
         patch("rasterio.open", return_value=mock_ds):
        result = svc._sample_srtm([(-122.5, 37.5)])

    mock_dl.assert_called_once_with(37, -123)
    assert result == [250.0]


def test_sample_srtm_download_failure_returns_zero(svc):
    with patch.object(svc, "_download_srtm_tile", return_value=False):
        result = svc._sample_srtm([(-122.5, 37.5)])
    assert result == [0.0]


def test_sample_srtm_existing_tile_skips_download(svc, tmp_path):
    tile = tmp_path / "N37W123.hgt"
    tile.touch()
    mock_ds = _make_srtm_mock_dataset([300.0])

    with patch.object(svc, "_download_srtm_tile") as mock_dl, \
         patch("rasterio.open", return_value=mock_ds):
        result = svc._sample_srtm([(-122.5, 37.5)])

    mock_dl.assert_not_called()
    assert result == [300.0]


def test_sample_srtm_nodata_returns_zero(svc, tmp_path):
    (tmp_path / "N37W123.hgt").touch()
    mock_ds = _make_srtm_mock_dataset([-32768.0], nodata=-32768.0)
    with patch("rasterio.open", return_value=mock_ds):
        result = svc._sample_srtm([(-122.5, 37.5)])
    assert result == [0.0]


# ── Startup: _load_1m_coverage ────────────────────────────────────────────────

def test_load_1m_coverage_populates_list():
    tnm_response = {
        "items": [
            {"boundingBox": {"minY": 37.0, "minX": -123.0, "maxY": 38.0, "maxX": -122.0}},
            {"boundingBox": {"minY": 40.0, "minX": -75.0, "maxY": 41.0, "maxX": -74.0}},
        ]
    }
    mock_resp = MagicMock()
    mock_resp.json.return_value = tnm_response

    with patch("httpx.get", return_value=mock_resp), \
         patch.object(ElevationService, "__init__", lambda self, **kw: None):
        svc = ElevationService.__new__(ElevationService)
        svc._1m_coverage = []
        svc._load_1m_coverage()

    assert len(svc._1m_coverage) == 2
    assert (37.0, -123.0, 38.0, -122.0) in svc._1m_coverage


def test_load_1m_coverage_http_failure_leaves_empty_list():
    with patch("httpx.get", side_effect=Exception("network down")), \
         patch.object(ElevationService, "__init__", lambda self, **kw: None):
        svc = ElevationService.__new__(ElevationService)
        svc._1m_coverage = []
        svc._load_1m_coverage()

    assert svc._1m_coverage == []


# ── Cancellation ───────────────────────────────────────────────────────────────

def test_get_elevations_cancelled_before_any_source(svc):
    """A tripped cancel signal aborts get_elevations with SearchCancelled before
    it touches any elevation source."""
    with patch.object(svc, "_sample_1m_cog") as m1m, \
         patch.object(svc._dep13, "sample") as m13, \
         patch.object(svc, "_sample_srtm") as msrtm:
        with pytest.raises(SearchCancelled):
            svc.get_elevations([(-122.5, 37.5)], should_cancel=lambda: True)
    m1m.assert_not_called()
    m13.assert_not_called()
    msrtm.assert_not_called()


def test_sample_srtm_cancel_skips_download(svc):
    """_sample_srtm checks the cancel signal before working a tile, so a tripped
    signal means no download is attempted."""
    with patch.object(svc, "_download_srtm_tile") as mock_dl:
        with pytest.raises(SearchCancelled):
            svc._sample_srtm([(-122.5, 37.5)], should_cancel=lambda: True)
    mock_dl.assert_not_called()


def test_dep13_sample_cancel_skips_read(dep13):
    """_Dep13TileCache.sample aborts before reading a tile when cancelled."""
    with patch.object(dep13, "_get_dataset") as mock_get:
        with pytest.raises(SearchCancelled):
            dep13.sample([(-122.5, 37.5)], should_cancel=lambda: True)
    mock_get.assert_not_called()


def test_not_cancelling_runs_normally(svc, tmp_path):
    """should_cancel returning False must not change behavior."""
    (tmp_path / "N37W123.hgt").touch()
    mock_ds = _make_srtm_mock_dataset([300.0])
    with patch("rasterio.open", return_value=mock_ds):
        result = svc._sample_srtm([(-122.5, 37.5)], should_cancel=lambda: False)
    assert result == [300.0]
