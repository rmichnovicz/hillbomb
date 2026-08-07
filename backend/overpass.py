"""
Query Overpass API for OSM ways and nodes within a bounding box.
Returns parsed OSMNode and OSMWay objects.

Results are disk-cached (pickle) under ~/.cache/hillbomb/overpass/ with a 24-hour
TTL. Set HILLBOMB_CACHE_DIR to override the cache root. Set HILLBOMB_CACHE_TTL to
override the TTL in seconds (0 = no cache).
"""

import hashlib
import logging
import os
import pickle
import time
import httpx
from pathlib import Path
from typing import Callable
from .types import OSMNode, OSMWay
from .config import HIGHWAY_RANK, MAX_TRAIL_DIFFICULTY, SAC_SCALE_TO_DIFFICULTY

log = logging.getLogger("hillbomb.overpass")

# Overridable so a self-hosted or mirror instance can be pointed at without a code
# change — and so outage behaviour can be exercised against a dead endpoint.
OVERPASS_URL = os.environ.get(
    "HILLBOMB_OVERPASS_URL", "https://overpass-api.de/api/interpreter"
)
TIMEOUT_SECONDS = 60

# Overpass runs a small number of slots per client IP and sheds anything beyond them:
# 429 when the rate limit is hit, 504 when a slot times out. Both are transient and
# the published usage policy asks clients to back off rather than retry immediately.
# Without this, any script fetching several bboxes in a row (the collections builder
# fetches 24) reliably fails partway through.
_RETRY_STATUS = frozenset({429, 504})
_MAX_ATTEMPTS = int(os.environ.get("HILLBOMB_OVERPASS_ATTEMPTS", "4"))
_BACKOFF_BASE_S = float(os.environ.get("HILLBOMB_OVERPASS_BACKOFF", "5"))

# The whole classified road network is fetched on every search, independent of
# the rider's rideable road_types. Traversability (what may actually be ridden)
# is decided per-way downstream in main.py; bigger roads still need to be in the
# graph so the avoid-bigger/equal-roads toggles can stop a descent at a crossing.
# Keying the fetch on geometry alone (not road_types) also lets re-searches with
# different toggles or road settings reuse the cached OSM data.
ROAD_NETWORK_TYPES: frozenset[str] = frozenset(HIGHWAY_RANK)

_CACHE_ROOT = Path(os.environ.get("HILLBOMB_CACHE_DIR", str(Path.home() / ".cache" / "hillbomb")))
_OVERPASS_CACHE_DIR = _CACHE_ROOT / "overpass"
_CACHE_TTL = int(os.environ.get("HILLBOMB_CACHE_TTL", "86400"))  # 24 h


def _overpass_cache_path(bbox: tuple) -> Path:
    """Cache path for a bbox, keyed on the bbox AND the set of highway classes fetched.

    The network types belong in the key because they decide what the response
    *contains*. Keyed on bbox alone, adding `track` to HIGHWAY_RANK — which widened
    ROAD_NETWORK_TYPES and so the query — left every cached entry silently stale:
    still valid by TTL, still returned, and missing every fire road the new query
    asks for. Folding the types in retires those entries the moment the set changes,
    which is the behaviour the TTL was already pretending to give.

    Deliberately NOT keyed on road_types/toggles — those filter what is *ridden*
    downstream (see mark_traversable), so re-searching the same bbox with different
    rider settings must keep hitting the same cache entry.
    """
    key = f"{bbox}|{','.join(sorted(ROAD_NETWORK_TYPES))}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return _OVERPASS_CACHE_DIR / f"{digest}.pkl"


def is_cached(bbox: tuple[float, float, float, float]) -> bool:
    """True if `bbox` would be served from the disk cache rather than the network.

    Read by osmsource.describe_source so the UI can distinguish a warm cache hit
    (near-instant) from a cold query (seconds, possibly a retry backoff) before
    the fetch starts. Cheap — one stat() — and racy only in the direction of
    understating: an entry expiring between this check and the fetch just means
    the status text said "cached" for a query that went to the network.
    """
    if _CACHE_TTL <= 0:
        return False
    path = _overpass_cache_path(bbox)
    try:
        return (time.time() - path.stat().st_mtime) < _CACHE_TTL
    except OSError:
        return False


def _retry_delay(resp: httpx.Response, attempt: int) -> float:
    """Seconds to wait before retrying. Honors Retry-After, else exponential backoff."""
    header = resp.headers.get("Retry-After")
    if header:
        try:
            # Only the delta-seconds form is handled; the HTTP-date form is rare here
            # and the exponential fallback is a fine answer for it.
            return max(0.0, float(int(header)))
        except ValueError:
            pass
    return _BACKOFF_BASE_S * (2 ** (attempt - 1))


def _post_with_retry(
    client: httpx.Client,
    query: str,
    on_retry: Callable[[str, int, int, float], None] | None = None,
) -> dict:
    """POST the query, backing off on Overpass's transient rejections.

    Raises the underlying HTTPStatusError once attempts are exhausted, so callers
    still see a real failure rather than an empty result.

    `on_retry(reason, attempt, max_attempts, delay_s)` is invoked before each
    sleep so a caller can tell the user what's happening instead of leaving them
    watching a spinner for up to 35 s. It is called on the calling thread — see
    main.py, which hops to the event loop to turn these into SSE status events.
    """
    for attempt in range(1, _MAX_ATTEMPTS + 1):
        last = attempt == _MAX_ATTEMPTS
        try:
            resp = client.post(
                OVERPASS_URL,
                data={"data": query},
                headers={"Accept": "*/*", "User-Agent": "hillbomb/0.1"},
            )
        except httpx.TransportError as exc:
            # A real outage looks like this — connection refused, DNS failure,
            # read timeout — not like a 429. Retrying only status codes meant a
            # genuine outage failed on the first attempt with no backoff.
            if last:
                raise
            delay = _BACKOFF_BASE_S * (2 ** (attempt - 1))
            reason = type(exc).__name__
            log.warning("Overpass unreachable (%s) (attempt %d/%d); retrying in %.0fs",
                        reason, attempt, _MAX_ATTEMPTS, delay)
            if on_retry:
                on_retry(reason, attempt, _MAX_ATTEMPTS, delay)
            time.sleep(delay)
            continue

        if resp.status_code not in _RETRY_STATUS or last:
            resp.raise_for_status()
            return resp.json()
        delay = _retry_delay(resp, attempt)
        log.warning(
            "Overpass returned %d (attempt %d/%d); retrying in %.0fs",
            resp.status_code, attempt, _MAX_ATTEMPTS, delay,
        )
        if on_retry:
            on_retry(str(resp.status_code), attempt, _MAX_ATTEMPTS, delay)
        time.sleep(delay)
    raise AssertionError("unreachable: loop either returns or raises")  # pragma: no cover


def _build_query(bbox: tuple[float, float, float, float]) -> str:
    """Overpass QL query: the full road network + traffic control nodes in the bbox."""
    south, west, north, east = bbox
    bbox_str = f"{south},{west},{north},{east}"

    highway_filter = "|".join(sorted(ROAD_NETWORK_TYPES))

    return f"""
[out:json][timeout:{TIMEOUT_SECONDS}];
(
  way["highway"~"^({highway_filter})$"]({bbox_str});
  node["highway"="traffic_signals"]({bbox_str});
  node["highway"="stop"]({bbox_str});
);
out body;
>;
out skel qt;
""".strip()


def _contiguous_inbbox_runs(node_ids: list[int], inside: set[int]) -> list[list[int]]:
    """Split a way's node sequence into maximal runs of consecutive in-bbox nodes.

    Overpass returns whole ways that merely touch the bbox, so a way exiting the
    bbox drags in nodes outside it — where we never fetched the cross streets, so
    those stretches look intersection-free and let a descent run off the edge.
    Dropping out-of-bbox nodes and keeping only contiguous in-bbox runs trims each
    way at the boundary (the rare dip-out-and-back way splits into two runs rather
    than collapsing into one false edge across the gap)."""
    runs: list[list[int]] = []
    current: list[int] = []
    for nid in node_ids:
        if nid in inside:
            current.append(nid)
        elif current:
            runs.append(current)
            current = []
    if current:
        runs.append(current)
    return runs


def _parse_trail_difficulty(tags: dict) -> int | None:
    """Fold `mtb:scale` and `sac_scale` into one 0-6 grade, or None if neither is set.

    `mtb:scale` values carry modifiers in the wild — "2+", "1-", "0+" all appear — so
    only the leading integer is read and the +/- nuance is dropped. Anything outside
    0-6, or unparseable, is treated as absent rather than guessed at.

    See config.SAC_SCALE_TO_DIFFICULTY on why the hiking scale is a defensible
    fallback but not an equivalent, and why the two are combined with max().
    """
    grades: list[int] = []

    raw = tags.get("mtb:scale", "")
    if raw:
        digits = raw.strip()[:1]
        if digits.isdigit() and 0 <= int(digits) <= MAX_TRAIL_DIFFICULTY:
            grades.append(int(digits))

    sac = SAC_SCALE_TO_DIFFICULTY.get(tags.get("sac_scale", ""))
    if sac is not None:
        grades.append(sac)

    return max(grades) if grades else None


def _parse_oneway(tags: dict) -> tuple[bool, bool]:
    """Return (oneway_forward, oneway_reverse)."""
    val = tags.get("oneway", "no")
    if val in ("yes", "1", "true"):
        return True, False
    if val == "-1":
        return False, True
    return False, False


def fetch_osm_data(
    bbox: tuple[float, float, float, float],
    on_retry: Callable[[str, int, int, float], None] | None = None,
) -> tuple[dict[int, OSMNode], list[OSMWay]]:
    """
    Query Overpass for the full road network in the bbox and return (nodes_by_id, ways).
    bbox: (south, west, north, east) in decimal degrees.
    Results are cached to disk for _CACHE_TTL seconds. Filtering the network down to
    what is rideable happens downstream (main.py); see ROAD_NETWORK_TYPES.

    `on_retry` is forwarded to _post_with_retry; see there for the signature. A
    cache hit never calls it — there is nothing to retry.
    """
    if _CACHE_TTL > 0:
        cache_path = _overpass_cache_path(bbox)
        if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < _CACHE_TTL:
            with cache_path.open("rb") as f:
                return pickle.load(f)

    query = _build_query(bbox)

    with httpx.Client(timeout=TIMEOUT_SECONDS + 10) as client:
        data = _post_with_retry(client, query, on_retry)

    # First pass: collect all node coords and tags.
    # A traffic-control node almost always also lies on a way, so it appears
    # twice in `elements`: once tagged (from `out body`) and once untagged (from
    # the `>; out skel qt;` recurse-down). The untagged copy must never clear a
    # flag the tagged copy set — OR the flags in rather than overwriting, so the
    # element order in the response can't silently drop every signal/stop sign.
    nodes_by_id: dict[int, OSMNode] = {}
    for el in data["elements"]:
        if el["type"] == "node":
            tags = el.get("tags", {})
            is_signal = tags.get("highway") == "traffic_signals"
            is_stop = tags.get("highway") == "stop"
            existing = nodes_by_id.get(el["id"])
            if existing is None:
                nodes_by_id[el["id"]] = OSMNode(
                    id=el["id"],
                    lat=el["lat"],
                    lon=el["lon"],
                    is_traffic_signal=is_signal,
                    is_stop_sign=is_stop,
                )
            else:
                existing.is_traffic_signal = existing.is_traffic_signal or is_signal
                existing.is_stop_sign = existing.is_stop_sign or is_stop

    # Nodes inside the queried bbox. Ways are trimmed to these so descents can't
    # run off the edge along a road whose cross streets we never fetched.
    south, west, north, east = bbox
    inside = {
        nid for nid, n in nodes_by_id.items()
        if south <= n.lat <= north and west <= n.lon <= east
    }

    # Second pass: parse ways. Keep the whole road network; traversability is
    # decided downstream so bigger roads survive into the graph for the
    # avoid-bigger/equal-roads toggles.
    ways: list[OSMWay] = []
    for el in data["elements"]:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        highway = tags.get("highway", "")
        if highway not in ROAD_NETWORK_TYPES:
            continue

        oneway, oneway_rev = _parse_oneway(tags)

        # A way that crosses the bbox boundary becomes one OSMWay per in-bbox run.
        for run in _contiguous_inbbox_runs(el.get("nodes", []), inside):
            if len(run) < 2:
                continue
            ways.append(OSMWay(
                id=el["id"],
                node_ids=run,
                highway=highway,
                oneway=oneway,
                oneway_reverse=oneway_rev,
                is_bridge=tags.get("bridge", "no") not in ("no", ""),
                is_tunnel=tags.get("tunnel", "no") not in ("no", ""),
                surface=tags.get("surface", ""),
                name=tags.get("name", ""),
                trail_difficulty=_parse_trail_difficulty(tags),
            ))

    # Drop out-of-bbox nodes so they never reach the graph or the elevation cache.
    nodes_by_id = {nid: n for nid, n in nodes_by_id.items() if nid in inside}

    if _CACHE_TTL > 0:
        _OVERPASS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with cache_path.open("wb") as f:
            pickle.dump((nodes_by_id, ways), f)

    return nodes_by_id, ways
