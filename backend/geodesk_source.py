"""
Read the road network out of a local GeoDesk GOL file.

A GOL is a memory-mapped, spatially-indexed compilation of an .osm.pbf — no
server, no database, no port. `backend/scripts/build_gol.py` builds ours.

This module exists to produce output *identical* to `overpass.fetch_osm_data`,
not merely equivalent, so it deliberately reuses that module's tag parsing and
bbox trimming rather than reimplementing them. `test_osmsource.py` runs the same
bbox through both and diffs the result.

Import this only through `osmsource`, which keeps it optional — `geodesk` is not
a hard dependency and an install without it must still run on Overpass.
"""

import logging
import os
from typing import Any

from .overpass import (
    ROAD_NETWORK_TYPES,
    _contiguous_inbbox_runs,
    _parse_oneway,
    _parse_trail_difficulty,
)
from .types import OSMNode, OSMWay

log = logging.getLogger("hillbomb.geodesk")

# Opening a GOL memory-maps it and builds no in-process index worth speaking of,
# but it is still per-file setup we shouldn't repeat on every search.
# Keyed on (path, mtime) — see _world.
_worlds: dict[tuple[str, float], Any] = {}


class MissingWaynodeIds(RuntimeError):
    """Raised when the GOL was built without `--waynode-ids`.

    GeoDesk drops the OSM IDs of untagged way vertices by default and reports
    their `id` as 0. Hillbomb keys its graph on node IDs and detects an
    intersection as "two ways referencing the same node ID" — and a plain street
    intersection is almost always untagged. Without the IDs, every such vertex
    collapses into a single node 0 and the graph becomes nonsense: silently,
    since nothing else about the data looks wrong. Fail loudly instead.
    """


def _tags(feature: Any) -> dict[str, str]:
    """Feature tags as plain strings.

    GeoDesk parses numeric-looking tag values into Python numbers — `mtb:scale=1`
    arrives as `int` 1, not `"1"`. Overpass hands back strings for everything, and
    the parsers we share with it do string work (`_parse_trail_difficulty` slices
    the first character; `_parse_oneway` compares against `"-1"`). Normalising here
    is what lets both sources run through the same parsing code.

    Whole floats are rendered without the trailing `.0` so a `layer=-1` that came
    back as -1.0 still compares equal to Overpass's `"-1"`.
    """
    out: dict[str, str] = {}
    for key, value in dict(feature.tags).items():
        if isinstance(value, float) and value.is_integer():
            value = int(value)
        out[key] = value if isinstance(value, str) else str(value)
    return out


def _world(gol_path: str) -> Any:
    """Open (and cache) the GOL, re-opening it if the file has been replaced.

    Keyed on mtime, not path alone. `build_gol.py` swaps a rebuilt GOL in with
    `Path.replace`, which leaves any already-open handle mapped to the *old*
    inode — still readable, so a long-running dev server would go on serving the
    previous build's road network with nothing to indicate it.
    """
    try:
        stamp = os.stat(gol_path).st_mtime
    except OSError:
        stamp = 0.0
    key = (gol_path, stamp)
    world = _worlds.get(key)
    if world is None:
        from geodesk import Features

        world = Features(gol_path)
        # Only one build is ever live; holding older mmaps just pins deleted files.
        _worlds.clear()
        _worlds[key] = world
    return world


def fetch_osm_data(
    gol_path: str,
    bbox: tuple[float, float, float, float],
) -> tuple[dict[int, OSMNode], list[OSMWay]]:
    """Return (nodes_by_id, ways) for the classified road network in `bbox`.

    bbox is (south, west, north, east), matching `overpass.fetch_osm_data`.
    """
    from geodesk import Box

    south, west, north, east = bbox
    world = _world(gol_path)
    box = Box(west=west, south=south, east=east, north=north)

    nodes_by_id: dict[int, OSMNode] = {}

    def _record(node: Any) -> int:
        """Add a node to nodes_by_id if new, OR-ing traffic-control flags in."""
        nid = node.id
        if nid == 0:
            raise MissingWaynodeIds(
                "GOL contains anonymous way nodes (id 0). Rebuild it with "
                "`gol build --waynode-ids` — see backend/scripts/build_gol.py."
            )
        tags = _tags(node)
        is_signal = tags.get("highway") == "traffic_signals"
        is_stop = tags.get("highway") == "stop"
        existing = nodes_by_id.get(nid)
        if existing is None:
            nodes_by_id[nid] = OSMNode(
                id=nid,
                lat=node.lat,
                lon=node.lon,
                is_traffic_signal=is_signal,
                is_stop_sign=is_stop,
            )
        else:
            existing.is_traffic_signal = existing.is_traffic_signal or is_signal
            existing.is_stop_sign = existing.is_stop_sign or is_stop
        return nid

    # Applying a Box selects features whose *bounding box* intersects it, which is
    # a superset of Overpass's "has a node in the bbox". The extra ways have no
    # in-bbox nodes, so _contiguous_inbbox_runs yields no runs for them and they
    # drop out below — the same place Overpass's boundary-crossing ways get
    # trimmed. Superset in, identical set out.
    raw_ways = [
        (w, _tags(w), [_record(n) for n in w.nodes])
        for w in world("w[highway]")(box)
    ]

    # Tagged control nodes that sit on no way at all. Rare, and they can't affect
    # routing, but Overpass returns them so we do too — the equivalence test would
    # otherwise fail on a difference that doesn't matter.
    for n in world("n[highway]")(box):
        tags = _tags(n)
        if tags.get("highway") in ("traffic_signals", "stop"):
            _record(n)

    south, west, north, east = bbox
    inside = {
        nid
        for nid, n in nodes_by_id.items()
        if south <= n.lat <= north and west <= n.lon <= east
    }

    ways: list[OSMWay] = []
    for w, tags, node_ids in raw_ways:
        highway = tags.get("highway", "")
        if highway not in ROAD_NETWORK_TYPES:
            continue

        oneway, oneway_rev = _parse_oneway(tags)

        for run in _contiguous_inbbox_runs(node_ids, inside):
            if len(run) < 2:
                continue
            ways.append(
                OSMWay(
                    id=w.id,
                    node_ids=run,
                    highway=highway,
                    oneway=oneway,
                    oneway_reverse=oneway_rev,
                    is_bridge=tags.get("bridge", "no") not in ("no", ""),
                    is_tunnel=tags.get("tunnel", "no") not in ("no", ""),
                    surface=tags.get("surface", ""),
                    name=tags.get("name", ""),
                    trail_difficulty=_parse_trail_difficulty(tags),
                )
            )

    nodes_by_id = {nid: n for nid, n in nodes_by_id.items() if nid in inside}
    return nodes_by_id, ways
