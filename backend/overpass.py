"""
Query Overpass API for OSM ways and nodes within a bounding box.
Returns parsed OSMNode and OSMWay objects.

Results are disk-cached (pickle) under ~/.cache/hillbomb/overpass/ with a 24-hour
TTL. Set HILLBOMB_CACHE_DIR to override the cache root. Set HILLBOMB_CACHE_TTL to
override the TTL in seconds (0 = no cache).
"""

import hashlib
import os
import pickle
import time
import httpx
from pathlib import Path
from .types import OSMNode, OSMWay
from .config import DETECTION_ROAD_TYPES

OVERPASS_URL = "https://overpass-api.de/api/interpreter"
TIMEOUT_SECONDS = 60

_CACHE_ROOT = Path(os.environ.get("HILLBOMB_CACHE_DIR", str(Path.home() / ".cache" / "hillbomb")))
_OVERPASS_CACHE_DIR = _CACHE_ROOT / "overpass"
_CACHE_TTL = int(os.environ.get("HILLBOMB_CACHE_TTL", "86400"))  # 24 h


def _overpass_cache_path(bbox: tuple, road_types: set[str]) -> Path:
    key = f"{bbox}:{':'.join(sorted(road_types))}"
    digest = hashlib.sha1(key.encode()).hexdigest()[:16]
    return _OVERPASS_CACHE_DIR / f"{digest}.pkl"


def _fetch_road_types(road_types: set[str]) -> set[str]:
    """Rideable road types plus the bigger tiers we fetch only for crossing detection."""
    return set(road_types) | DETECTION_ROAD_TYPES


def _build_query(bbox: tuple[float, float, float, float], road_types: set[str]) -> str:
    """Overpass QL query: all ways matching road types + their nodes + traffic control nodes."""
    south, west, north, east = bbox
    bbox_str = f"{south},{west},{north},{east}"

    highway_filter = "|".join(sorted(_fetch_road_types(road_types)))

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
    road_types: set[str],
) -> tuple[dict[int, OSMNode], list[OSMWay]]:
    """
    Query Overpass and return (nodes_by_id, ways).
    bbox: (south, west, north, east) in decimal degrees.
    Results are cached to disk for _CACHE_TTL seconds.
    """
    if _CACHE_TTL > 0:
        cache_path = _overpass_cache_path(bbox, set(road_types))
        if cache_path.exists() and (time.time() - cache_path.stat().st_mtime) < _CACHE_TTL:
            with cache_path.open("rb") as f:
                return pickle.load(f)

    query = _build_query(bbox, road_types)

    headers = {"Accept": "*/*", "User-Agent": "hillbomb/0.1"}
    with httpx.Client(timeout=TIMEOUT_SECONDS + 10) as client:
        resp = client.post(OVERPASS_URL, data={"data": query}, headers=headers)
        resp.raise_for_status()
        data = resp.json()

    # First pass: collect all node coords and tags
    nodes_by_id: dict[int, OSMNode] = {}
    for el in data["elements"]:
        if el["type"] == "node":
            tags = el.get("tags", {})
            nodes_by_id[el["id"]] = OSMNode(
                id=el["id"],
                lat=el["lat"],
                lon=el["lon"],
                is_traffic_signal=tags.get("highway") == "traffic_signals",
                is_stop_sign=tags.get("highway") == "stop",
            )

    # Second pass: parse ways. Keep the whole fetched set (rideable + detection
    # tiers); traversability is decided downstream so detection roads survive into
    # the graph for the avoid-bigger/equal-roads toggles.
    fetch_types = _fetch_road_types(road_types)
    ways: list[OSMWay] = []
    for el in data["elements"]:
        if el["type"] != "way":
            continue
        tags = el.get("tags", {})
        highway = tags.get("highway", "")
        if highway not in fetch_types:
            continue

        node_ids = el.get("nodes", [])
        # Drop ways whose nodes weren't returned (outside bbox edge cases)
        node_ids = [n for n in node_ids if n in nodes_by_id]
        if len(node_ids) < 2:
            continue

        oneway, oneway_rev = _parse_oneway(tags)

        ways.append(OSMWay(
            id=el["id"],
            node_ids=node_ids,
            highway=highway,
            oneway=oneway,
            oneway_reverse=oneway_rev,
            is_bridge=tags.get("bridge", "no") not in ("no", ""),
            is_tunnel=tags.get("tunnel", "no") not in ("no", ""),
            surface=tags.get("surface", ""),
            name=tags.get("name", ""),
        ))

    if _CACHE_TTL > 0:
        _OVERPASS_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        with cache_path.open("wb") as f:
            pickle.dump((nodes_by_id, ways), f)

    return nodes_by_id, ways
