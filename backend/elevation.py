"""
ElevationService: resolution cascade for self-hosted elevation queries.
  1. USGS 3DEP 1m  (~1m lidar, partial CONUS)   — S3 COG via rasterio HTTP
  2. USGS 3DEP 1/3 arc-sec (~10m, full CONUS)   — local tile cache, auto-downloaded from S3
  3. SRTM 1 arc-sec (~30m, global)              — local HGT tiles, auto-downloaded

See CLAUDE.md §Elevation data for architecture details.
Physics and graph code use self.resolution_m after get_elevations() to set
config.elevation_sample_interval_m to the appropriate value.
"""

import gzip
import hashlib
import logging
import math
import os
import pickle
import threading
from collections import OrderedDict
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx
import numpy as np
import rasterio
import rasterio.transform
import rasterio.windows
from rasterio.session import AWSSession
import boto3

log = logging.getLogger(__name__)


class SearchCancelled(Exception):
    """Raised when an in-flight elevation query is aborted because the client
    disconnected. Treated as a normal early exit by the pipeline, not an error."""


def _check_cancel(should_cancel: Callable[[], bool] | None) -> None:
    """Raise SearchCancelled if the caller's cancellation signal is set.
    No-op when should_cancel is None, so callers (and tests) need not pass one."""
    if should_cancel is not None and should_cancel():
        raise SearchCancelled()

# ── GDAL/rasterio tuning for remote COG reads ──────────────────────────────────
# Set process-wide before any GDAL operation. These turn a windowed read over
# /vsicurl into a handful of HTTP range requests instead of a full-file scan:
#   GDAL_DISABLE_READDIR_ON_OPEN  — don't list the S3 "directory" on open
#   CPL_VSIL_CURL_ALLOWED_EXTENSIONS — only ever range-GET these extensions
#   GDAL_HTTP_MULTIRANGE / MERGE  — coalesce block reads into few requests
#   VSI_CACHE                      — cache fetched blocks in memory per dataset
#   GDAL_CACHEMAX                  — GDAL block cache (MB)
for _k, _v in {
    "GDAL_DISABLE_READDIR_ON_OPEN": "EMPTY_DIR",
    "CPL_VSIL_CURL_ALLOWED_EXTENSIONS": ".tif,.tiff,.hgt,.gz",
    "GDAL_HTTP_MULTIRANGE": "YES",
    "GDAL_HTTP_MERGE_CONSECUTIVE_RANGES": "YES",
    "VSI_CACHE": "TRUE",
    "VSI_CACHE_SIZE": "67108864",
    "GDAL_CACHEMAX": "512",
}.items():
    os.environ.setdefault(_k, _v)

# Unsigned boto3 session for public S3 buckets (3DEP, SRTM skadi).
# Avoids credential lookups and the "DummySession" fallback warning.
_AWS_SESSION = AWSSession(boto3.Session(), requester_pays=False, aws_unsigned=True)

_TNM_API = "https://tnmaccess.nationalmap.gov/api/v1/products"
_DATASET_1M = "Digital Elevation Model (DEM) 1 meter"

# 3DEP 1/3 arc-sec tiles: deterministic S3 path.
# Tile name: n{lat+1:02d}w{abs(lon):03d} (floor of coordinate).
# e.g. Twin Peaks (37.75, -122.45) → lat_tile=37, lon_tile=-123 → n38w123
_DEP13_S3 = "https://prd-tnm.s3.amazonaws.com/StagedProducts/Elevation/13/TIFF/current"

# Public S3 bucket (Mapzen/Tilezen skadi) hosting SRTM 1 arc-sec tiles as .hgt.gz
_SRTM_SKADI = "https://s3.amazonaws.com/elevation-tiles-prod/skadi"

_RES_1M = 1.0
_RES_13 = 10.0
_RES_SRTM = 30.0


class _Dep13TileCache:
    """
    LRU cache of locally-stored 3DEP 1/3 arc-sec tiles.

    Tiles are downloaded on first access from USGS S3 and stored on disk.
    The last `max_open` tiles are kept open as rasterio datasets; repeated
    searches in the same area skip both download and open overhead.

    Dense point batches are served with a single window read per tile —
    O(tiles) disk reads regardless of point count. This is the key difference
    from rasterio.sample(), which does one internal read per point.

    Thread safety:
      - Concurrent downloads of different tiles run in parallel.
      - Reads of the same open dataset are serialized via a per-dataset lock
        (rasterio DatasetReader is not thread-safe).
      - Different tiles can be read concurrently.
    """

    def __init__(self, tile_dir: Path, max_open: int = 8, mode: str = "cog") -> None:
        self._tile_dir = tile_dir
        self._max_open = max_open
        # "cog": open the tile over HTTP and read only the windowed byte ranges
        #        for each query (no full-tile download — the documented design).
        # "download": stream the whole tile to disk on first touch, then read
        #        locally. Faster on warm repeats, but pays a ~200 MB download
        #        the first time any 1° tile is touched.
        self._mode = mode
        # LRU: (lat_tile, lon_tile) → (DatasetReader, per-dataset read lock)
        self._lru: OrderedDict = OrderedDict()
        self._lru_lock = threading.Lock()
        # Per-tile download locks — prevent duplicate concurrent downloads
        self._dl_locks: dict[tuple[int, int], threading.Lock] = {}
        self._dl_locks_lock = threading.Lock()
        # Tiles that failed this process lifetime — skip re-attempts
        self._bad_tiles: set[tuple[int, int]] = set()

    def _tile_name(self, lat_tile: int, lon_tile: int) -> str | None:
        """Return USGS tile name string, or None if outside 3DEP coverage (N/W hemi only)."""
        if lat_tile < 0 or lon_tile >= 0:
            return None
        return f"n{lat_tile + 1:02d}w{abs(lon_tile):03d}"

    def _tile_path(self, lat_tile: int, lon_tile: int) -> Path:
        name = self._tile_name(lat_tile, lon_tile)
        fname = f"USGS_13_{name}.tif" if name else f"dep13_{lat_tile}_{lon_tile}.tif"
        return self._tile_dir / fname

    def _tile_url(self, lat_tile: int, lon_tile: int) -> str | None:
        name = self._tile_name(lat_tile, lon_tile)
        if name is None:
            return None
        return f"{_DEP13_S3}/{name}/USGS_13_{name}.tif"

    def _dl_lock(self, key: tuple[int, int]) -> threading.Lock:
        with self._dl_locks_lock:
            if key not in self._dl_locks:
                self._dl_locks[key] = threading.Lock()
            return self._dl_locks[key]

    def _ensure_local(self, lat_tile: int, lon_tile: int) -> Path | None:
        """Return local path for tile, streaming it down from S3 if not present."""
        key = (lat_tile, lon_tile)
        if key in self._bad_tiles:
            return None
        path = self._tile_path(lat_tile, lon_tile)
        if path.exists():
            return path
        url = self._tile_url(lat_tile, lon_tile)
        if url is None:
            self._bad_tiles.add(key)
            return None
        with self._dl_lock(key):
            if path.exists():
                return path
            log.info("Downloading 3DEP 1/3\" tile (%d,%d)…", lat_tile, lon_tile)
            tmp = path.with_suffix(".tmp")
            try:
                self._tile_dir.mkdir(parents=True, exist_ok=True)
                with httpx.stream("GET", url, timeout=120, follow_redirects=True) as resp:
                    resp.raise_for_status()
                    with tmp.open("wb") as f:
                        for chunk in resp.iter_bytes(1 << 20):
                            f.write(chunk)
                tmp.rename(path)
                log.info("Saved 3DEP tile %s (%.1f MB)", path.name, path.stat().st_size / 1e6)
                return path
            except Exception as exc:
                log.warning("3DEP tile download failed (%d,%d): %s", lat_tile, lon_tile, exc)
                tmp.unlink(missing_ok=True)
                self._bad_tiles.add(key)
                return None

    def _open_dataset(self, lat_tile: int, lon_tile: int):
        """Open a tile's rasterio dataset per the configured mode. None on failure."""
        key = (lat_tile, lon_tile)
        if self._mode == "cog":
            url = self._tile_url(lat_tile, lon_tile)
            if url is None:
                self._bad_tiles.add(key)
                return None
            # /vsicurl windowed reads: only the requested blocks are fetched.
            return rasterio.open(url)

        path = self._ensure_local(lat_tile, lon_tile)
        if path is None:
            return None
        return rasterio.open(str(path))

    def _get_dataset(self, lat_tile: int, lon_tile: int):
        """Return (DatasetReader, read_lock) for a tile, downloading/opening as needed."""
        key = (lat_tile, lon_tile)
        if key in self._bad_tiles:
            return None
        with self._lru_lock:
            if key in self._lru:
                self._lru.move_to_end(key)
                return self._lru[key]

        try:
            ds = self._open_dataset(lat_tile, lon_tile)
        except Exception as exc:
            log.warning("Failed to open 3DEP tile (%d,%d): %s", lat_tile, lon_tile, exc)
            self._bad_tiles.add(key)
            return None
        if ds is None:
            return None

        entry = (ds, threading.Lock())
        with self._lru_lock:
            self._lru[key] = entry
            self._lru.move_to_end(key)
            if len(self._lru) > self._max_open:
                _, (evicted_ds, _) = self._lru.popitem(last=False)
                try:
                    evicted_ds.close()
                except Exception:
                    pass
        return entry

    def sample(
        self,
        coords: list[tuple[float, float]],
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[float | None]:
        """
        Return elevations (meters) for (lon, lat) pairs. None for points outside coverage.

        Groups points by tile, reads each tile's bounding window in a single ds.read()
        call, then indexes with numpy — O(tiles) disk reads regardless of point count.
        Multi-tile queries run tile reads in parallel via a thread pool.

        Raises SearchCancelled (between tile reads) if should_cancel() becomes true.
        """
        results: list[float | None] = [None] * len(coords)

        tile_to_indices: dict[tuple[int, int], list[int]] = {}
        for i, (lon, lat) in enumerate(coords):
            tile_to_indices.setdefault((int(math.floor(lat)), int(math.floor(lon))), []).append(i)

        def _read_tile(lat_tile: int, lon_tile: int, indices: list[int]) -> list[tuple[int, float]]:
            """Read one tile. Returns (result_index, elevation) pairs for valid non-nodata points."""
            entry = self._get_dataset(lat_tile, lon_tile)
            if entry is None:
                return []
            ds, read_lock = entry

            tile_lons = np.array([coords[i][0] for i in indices])
            tile_lats = np.array([coords[i][1] for i in indices])

            try:
                rows, cols = rasterio.transform.rowcol(ds.transform, tile_lons, tile_lats)
                rows = np.asarray(rows)
                cols = np.asarray(cols)

                valid = (rows >= 0) & (rows < ds.height) & (cols >= 0) & (cols < ds.width)
                if not valid.any():
                    return []

                vrows = rows[valid]
                vcols = cols[valid]
                r0, r1 = int(vrows.min()), int(vrows.max())
                c0, c1 = int(vcols.min()), int(vcols.max())

                window = rasterio.windows.Window(c0, r0, c1 - c0 + 1, r1 - r0 + 1)
                with read_lock:
                    data = ds.read(1, window=window)

                nodata = ds.nodata
                vals = data[vrows - r0, vcols - c0]
                valid_indices = np.asarray(indices)[valid]

                return [
                    (int(idx), float(val))
                    for idx, val in zip(valid_indices.tolist(), vals.tolist())
                    if nodata is None or val != nodata
                ]
            except Exception as exc:
                log.warning("3DEP tile read failed (%d,%d): %s", lat_tile, lon_tile, exc)
                return []

        tile_items = list(tile_to_indices.items())

        if len(tile_items) == 1:
            (lt, lo), idxs = tile_items[0]
            _check_cancel(should_cancel)
            for idx, val in _read_tile(lt, lo, idxs):
                results[idx] = val
        else:
            with ThreadPoolExecutor(max_workers=min(len(tile_items), 4)) as ex:
                futs = {
                    ex.submit(_read_tile, lt, lo, idxs): (lt, lo)
                    for (lt, lo), idxs in tile_items
                }
                for fut in as_completed(futs):
                    # Abort as soon as a disconnect is seen; outstanding tile reads
                    # finish on their threads but their results are discarded.
                    _check_cancel(should_cancel)
                    try:
                        for idx, val in fut.result():
                            results[idx] = val
                    except Exception as exc:
                        lt, lo = futs[fut]
                        log.warning("Tile read task error (%d,%d): %s", lt, lo, exc)

        return results


class ElevationService:
    """
    Elevation queries with automatic source selection and local tile caching.
    Initialize once at app startup.
    """

    def __init__(self, srtm_dir: str | None = None, cache_dir: str | None = None) -> None:
        _cache_root = Path(
            cache_dir
            or os.environ.get("HILLBOMB_CACHE_DIR", str(Path.home() / ".cache" / "hillbomb"))
        )
        self._srtm_dir = Path(srtm_dir or os.environ.get("SRTM_DIR", str(_cache_root / "srtm")))
        self._elev_cache_dir = _cache_root / "elevation"
        # HILLBOMB_USE_1M=true enables the 1m lidar source; off by default because
        # the TNM coverage index fetch adds cold-start latency and 1m tiles are
        # patchy — 1/3 arc-sec is the reliable CONUS baseline.
        self._use_1m = os.environ.get("HILLBOMB_USE_1M", "false").lower() == "true"
        # (south, west, north, east) bboxes of available 1m tiles
        self._1m_coverage: list[tuple[float, float, float, float]] = []
        # URL cache for 1m COG lookups only (TNM API results)
        self._tile_url_cache: dict[tuple[str, int, int], str | None] = {}
        self._locks_lock = threading.Lock()
        # Per-tile download locks for SRTM
        self._download_locks: dict[tuple[int, int], threading.Lock] = {}
        # Written under _locks_lock; read by caller immediately after the call.
        self.resolution_m: float = _RES_13

        dep13_max_open = int(os.environ.get("HILLBOMB_DEP13_CACHE_SIZE", "8"))
        # "cog" (default): windowed byte-range reads over HTTP, no full-tile
        # download. "download": stream whole tiles to disk (legacy behaviour).
        dep13_mode = os.environ.get("HILLBOMB_DEP13_MODE", "cog").lower()
        self._dep13 = _Dep13TileCache(
            tile_dir=_cache_root / "dep13",
            max_open=dep13_max_open,
            mode=dep13_mode,
        )

        if self._use_1m:
            self._load_1m_coverage()

    # ── startup ───────────────────────────────────────────────────────────────

    def _load_1m_coverage(self) -> None:
        """Fetch 1m tile extents from TNM API. Logs a warning and continues on failure."""
        try:
            resp = httpx.get(
                _TNM_API,
                params={
                    "datasets": _DATASET_1M,
                    "prodFormats": "GeoTiff",
                    "max": 2000,
                    "outputFormat": "JSON",
                },
                timeout=20,
            )
            resp.raise_for_status()
            items = resp.json().get("items", [])
            for item in items:
                bb = item.get("boundingBox")
                if bb:
                    self._1m_coverage.append((
                        float(bb["minY"]), float(bb["minX"]),
                        float(bb["maxY"]), float(bb["maxX"]),
                    ))
            log.info("Loaded %d 1m coverage tiles from TNM", len(self._1m_coverage))
        except Exception as exc:
            log.warning("1m coverage index unavailable (%s) — 1m source disabled", exc)

    # ── coverage check ────────────────────────────────────────────────────────

    def _has_1m_coverage(self, south: float, west: float, north: float, east: float) -> bool:
        for ts, tw, tn, te in self._1m_coverage:
            if south < tn and north > ts and west < te and east > tw:
                return True
        return False

    # ── SRTM: local HGT tiles + on-demand download ───────────────────────────

    def _tile_lock(self, lat_tile: int, lon_tile: int) -> threading.Lock:
        key = (lat_tile, lon_tile)
        with self._locks_lock:
            if key not in self._download_locks:
                self._download_locks[key] = threading.Lock()
            return self._download_locks[key]

    def _srtm_tile_path(self, lat_tile: int, lon_tile: int) -> Path:
        lat_prefix = "N" if lat_tile >= 0 else "S"
        lon_prefix = "E" if lon_tile >= 0 else "W"
        name = f"{lat_prefix}{abs(lat_tile):02d}{lon_prefix}{abs(lon_tile):03d}.hgt"
        return self._srtm_dir / name

    def _download_srtm_tile(self, lat_tile: int, lon_tile: int) -> bool:
        """Download an SRTM tile from the public skadi S3 bucket. Returns True on success."""
        path = self._srtm_tile_path(lat_tile, lon_tile)
        lat_prefix = "N" if lat_tile >= 0 else "S"
        lon_prefix = "E" if lon_tile >= 0 else "W"
        name_stem = f"{lat_prefix}{abs(lat_tile):02d}{lon_prefix}{abs(lon_tile):03d}"
        lat_dir = f"{lat_prefix}{abs(lat_tile):02d}"
        url = f"{_SRTM_SKADI}/{lat_dir}/{name_stem}.hgt.gz"

        log.info("Downloading SRTM tile %s from skadi...", name_stem)
        try:
            self._srtm_dir.mkdir(parents=True, exist_ok=True)
            resp = httpx.get(url, timeout=60, follow_redirects=True)
            resp.raise_for_status()
            path.write_bytes(gzip.decompress(resp.content))
            log.info("Saved SRTM tile %s (%d KB)", name_stem, path.stat().st_size // 1024)
            return True
        except Exception as exc:
            log.warning("Failed to download SRTM tile %s: %s", name_stem, exc)
            path.unlink(missing_ok=True)
            return False

    def _sample_srtm(
        self,
        coords: list[tuple[float, float]],
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[float]:
        """
        Sample SRTM elevations. Missing tiles are downloaded automatically from
        skadi S3. Returns 0.0 for any tile that can't be obtained or read.

        Raises SearchCancelled (between tiles) if should_cancel() becomes true.
        """
        results: list[float] = [0.0] * len(coords)

        tile_to_indices: dict[tuple[int, int], list[int]] = {}
        for i, (lon, lat) in enumerate(coords):
            tile_to_indices.setdefault((int(math.floor(lat)), int(math.floor(lon))), []).append(i)

        for (lat_tile, lon_tile), indices in tile_to_indices.items():
            # Checked before each tile so an in-progress download is the longest
            # a cancel can be delayed by (one tile, not the whole query).
            _check_cancel(should_cancel)
            path = self._srtm_tile_path(lat_tile, lon_tile)
            if not path.exists():
                with self._tile_lock(lat_tile, lon_tile):
                    if not path.exists():
                        if not self._download_srtm_tile(lat_tile, lon_tile):
                            continue

            tile_coords = [coords[i] for i in indices]
            try:
                with rasterio.open(str(path)) as ds:
                    nodata = ds.nodata
                    for idx, (val,) in zip(indices, ds.sample(tile_coords)):
                        if val is not None and (nodata is None or val != nodata):
                            results[idx] = float(val)
            except Exception as exc:
                log.warning("SRTM read failed (%s): %s", path.name, exc)

        return results

    # ── 1m COG sampling (HTTP, no local cache) ────────────────────────────────

    def _sample_1m_cog(
        self,
        coords: list[tuple[float, float]],
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[float | None]:
        """Sample 3DEP 1m elevations via HTTP COG. URL is looked up from TNM API.

        Raises SearchCancelled (between tiles) if should_cancel() becomes true."""
        results: list[float | None] = [None] * len(coords)

        tile_to_indices: dict[tuple[int, int], list[int]] = {}
        for i, (lon, lat) in enumerate(coords):
            tile_to_indices.setdefault((int(math.floor(lat)), int(math.floor(lon))), []).append(i)

        for (lat_tile, lon_tile), indices in tile_to_indices.items():
            # Each tile means a TNM lookup + a remote COG open; check before each.
            _check_cancel(should_cancel)
            cache_key = ("1m", lat_tile, lon_tile)
            with self._locks_lock:
                cached = self._tile_url_cache.get(cache_key, "unchecked")

            url: str | None = None
            if cached == "unchecked":
                south, west = float(lat_tile), float(lon_tile)
                try:
                    resp = httpx.get(
                        _TNM_API,
                        params={
                            "datasets": _DATASET_1M,
                            "bbox": f"{west},{south},{west + 1},{south + 1}",
                            "prodFormats": "GeoTiff",
                            "max": 5,
                            "outputFormat": "JSON",
                        },
                        timeout=10,
                    )
                    resp.raise_for_status()
                    for item in resp.json().get("items", []):
                        dl = item.get("downloadURL", "")
                        if dl.lower().endswith((".tif", ".tiff")):
                            url = dl
                            break
                except Exception as exc:
                    log.warning("TNM 1m lookup failed (tile %d,%d): %s", lat_tile, lon_tile, exc)
                with self._locks_lock:
                    self._tile_url_cache[cache_key] = url
            elif cached is not None:
                url = cached
            # else: cached is None → previously failed, skip

            if not url:
                continue
            tile_coords = [coords[i] for i in indices]
            try:
                with rasterio.Env(session=_AWS_SESSION):
                    with rasterio.open(url) as ds:
                        if not ds.crs.is_geographic:
                            continue
                        nodata = ds.nodata
                        for idx, (val,) in zip(indices, ds.sample(tile_coords)):
                            if val is not None and (nodata is None or val != nodata):
                                results[idx] = float(val)
            except Exception as exc:
                log.warning("1m COG read failed (%s): %s", url[:60], exc)

        return results

    # ── public API ────────────────────────────────────────────────────────────

    def get_elevations(
        self,
        coords: list[tuple[float, float]],
        should_cancel: Callable[[], bool] | None = None,
    ) -> list[float]:
        """
        Returns elevations (meters ASL) for a list of (lon, lat) pairs.
        Selects the best available source and falls back through the cascade.
        Sets self.resolution_m to reflect the dominant source used.
        Results are cached to disk; cache is keyed by the sorted coordinate set
        so the same logical request always hits the same cache entry.

        should_cancel, if given, is polled between cascade stages and between tile
        reads inside each source; when it becomes true the query aborts by raising
        SearchCancelled rather than running to completion. Used so a disconnected
        client's request stops fetching network/disk data almost immediately.
        """
        if not coords:
            return []

        key = ",".join(f"{lon:.6f},{lat:.6f}" for lon, lat in sorted(coords))
        cache_path = self._elev_cache_dir / f"{hashlib.sha1(key.encode()).hexdigest()[:16]}.pkl"
        if cache_path.exists():
            try:
                with cache_path.open("rb") as f:
                    cached = pickle.load(f)
                if cached.get("coords") == coords:
                    with self._locks_lock:
                        self.resolution_m = cached.get("resolution_m", _RES_13)
                    return cached["elevations"]
            except Exception as exc:
                log.warning("Elevation cache read failed (%s): %s", cache_path.name, exc)

        lats = [c[1] for c in coords]
        lons = [c[0] for c in coords]
        south, west = min(lats), min(lons)
        north, east = max(lats), max(lons)

        _check_cancel(should_cancel)

        # Stage 1: 3DEP 1m (partial CONUS) — only when HILLBOMB_USE_1M=true
        if self._use_1m and self._has_1m_coverage(south, west, north, east):
            r1m = self._sample_1m_cog(coords, should_cancel)
            if all(v is not None for v in r1m):
                with self._locks_lock:
                    self.resolution_m = _RES_1M
                result = [v for v in r1m]  # type: ignore[misc]
                self._write_elev_cache(cache_path, coords, result)
                return result

        _check_cancel(should_cancel)

        # Stage 2: 3DEP 1/3 arc-sec (full CONUS) — local tile cache
        r13 = self._dep13.sample(coords, should_cancel)
        if all(v is not None for v in r13):
            with self._locks_lock:
                self.resolution_m = _RES_13
            result = [v for v in r13]  # type: ignore[misc]
            self._write_elev_cache(cache_path, coords, result)
            return result

        _check_cancel(should_cancel)

        # Stage 3: SRTM local tiles (global fallback) — auto-downloaded
        log.info("Falling back to SRTM for bbox (%.3f,%.3f,%.3f,%.3f)", south, west, north, east)
        srtm = self._sample_srtm(coords, should_cancel)
        merged = [
            (float(r13[i]) if r13[i] is not None else srtm[i])
            for i in range(len(coords))
        ]
        covered_by_13 = sum(1 for v in r13 if v is not None)
        with self._locks_lock:
            self.resolution_m = _RES_13 if covered_by_13 > len(coords) // 2 else _RES_SRTM
        self._write_elev_cache(cache_path, coords, merged)
        return merged

    def _write_elev_cache(self, path: Path, coords: list[tuple[float, float]], elevations: list[float]) -> None:
        try:
            self._elev_cache_dir.mkdir(parents=True, exist_ok=True)
            with path.open("wb") as f:
                pickle.dump({"coords": coords, "elevations": elevations, "resolution_m": self.resolution_m}, f)
        except Exception as exc:
            log.warning("Elevation cache write failed (%s): %s", path.name, exc)
