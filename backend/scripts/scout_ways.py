"""
Scout a bbox for candidate descents — the research tool behind `docs/adding-a-spot.md`.

Adding a spot means getting two fields right, `osm_way_names` and `bbox`, and until now
the only way to check either was openstreetmap.org by hand or a 30-second build. Both
are answerable straight from the local GOL in milliseconds, which is what this does.

    # Does this road exist under this name, and where exactly is it?
    python -m backend.scripts.scout_ways --bbox 37.82,-122.53,37.84,-122.48 --name Conzelman

    # What are the biggest named descents in this box?
    python -m backend.scripts.scout_ways --bbox 37.82,-122.53,37.84,-122.48 --list

`--name` prints, per matching OSM `name`: how many ways carry it, their `highway`
classes and rank, oneway direction, surface, total length, net elevation drop, and — the
field you actually came for — a **tight union bbox** ready to paste into `spots.py`.

`--list` inverts it: no name needed, every named way in the box ranked by elevation
drop. Use it to discover what is steep near a place, or to find the real name of a road
you only know by its popular one.

Read-only and offline: it reads the same GOL and elevation cache the pipeline reads and
writes nothing but stdout. It answers "does the data support this spot", not "is this
spot worth shipping" — that judgement, and the actual routes, still come from
`build_collections.py`.
"""

import argparse
import json
import math
import sys

from ..config import HIGHWAY_RANK
from ..elevation import ElevationService
from ..osmsource import covering_region, describe_source, fetch_osm_data
from ..types import OSMNode, OSMWay

# A bbox needs padding to be usable as a spot bbox: the graph needs the junctions at
# each end to know where the descent stops, and `_contiguous_inbbox_runs` trims any way
# crossing the edge. ~200 m is what docs/adding-a-spot.md asks for.
PAD_DEG_LAT = 0.0018
PAD_DEG_LON = 0.0022


def _haversine_m(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Metres between two (lon, lat) pairs."""
    lon1, lat1 = a
    lon2, lat2 = b
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    h = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(h))


def _way_coords(way: OSMWay, nodes: dict[int, OSMNode]) -> list[tuple[float, float]]:
    return [(nodes[n].lon, nodes[n].lat) for n in way.node_ids if n in nodes]


def _way_length_m(coords: list[tuple[float, float]]) -> float:
    return sum(_haversine_m(coords[i], coords[i + 1]) for i in range(len(coords) - 1))


class _NameGroup:
    """Every way sharing one OSM `name`, treated as one candidate road."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.ways: list[OSMWay] = []
        self.coords: list[list[tuple[float, float]]] = []

    def add(self, way: OSMWay, coords: list[tuple[float, float]]) -> None:
        self.ways.append(way)
        self.coords.append(coords)

    @property
    def length_m(self) -> float:
        return sum(_way_length_m(c) for c in self.coords)

    @property
    def all_coords(self) -> list[tuple[float, float]]:
        return [c for run in self.coords for c in run]

    def union_bbox(self, pad: bool = True) -> tuple[float, float, float, float]:
        lons = [c[0] for c in self.all_coords]
        lats = [c[1] for c in self.all_coords]
        south, north = min(lats), max(lats)
        west, east = min(lons), max(lons)
        if pad:
            south, north = south - PAD_DEG_LAT, north + PAD_DEG_LAT
            west, east = west - PAD_DEG_LON, east + PAD_DEG_LON
        return (round(south, 5), round(west, 5), round(north, 5), round(east, 5))

    @property
    def highways(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for w in self.ways:
            out[w.highway] = out.get(w.highway, 0) + 1
        return out

    @property
    def max_rank(self) -> int:
        return max((HIGHWAY_RANK.get(w.highway, 0) for w in self.ways), default=0)

    @property
    def surfaces(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for w in self.ways:
            out[w.surface or "(untagged)"] = out.get(w.surface or "(untagged)", 0) + 1
        return out

    @property
    def oneway_count(self) -> int:
        return sum(1 for w in self.ways if w.oneway or w.oneway_reverse)


def _group_by_name(
    ways: list[OSMWay], nodes: dict[int, OSMNode], substrings: list[str] | None
) -> list[_NameGroup]:
    groups: dict[str, _NameGroup] = {}
    for way in ways:
        if not way.name:
            continue
        if substrings and not any(s.lower() in way.name.lower() for s in substrings):
            continue
        coords = _way_coords(way, nodes)
        if len(coords) < 2:
            continue
        groups.setdefault(way.name, _NameGroup(way.name)).add(way, coords)
    return list(groups.values())


def _elevation_stats(
    groups: list[_NameGroup], service: ElevationService
) -> dict[str, tuple[float, float, float]]:
    """(min, max, drop) elevation per group name.

    One `get_elevations` call for every group's every node, because the service caches
    per coordinate and reads a DEM tile once per window — a call per group would read
    the same tile repeatedly and defeat that. The drop reported is max-minus-min over
    the whole named road, which is the honest ceiling on what a descent on it could be,
    not a claim that a single route achieves it.
    """
    index: list[tuple[str, int]] = []
    coords: list[tuple[float, float]] = []
    for g in groups:
        for c in g.all_coords:
            index.append((g.name, len(coords)))
            coords.append(c)
    if not coords:
        return {}
    elevations = service.get_elevations(coords)
    per_name: dict[str, list[float]] = {}
    for (name, i) in index:
        per_name.setdefault(name, []).append(elevations[i])
    return {
        name: (min(v), max(v), max(v) - min(v))
        for name, v in per_name.items()
        if v
    }


def _fmt_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{k}×{v}" for k, v in sorted(counts.items(), key=lambda kv: -kv[1]))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        description="Scout a bbox for candidate descents (verifies osm_way_names + bbox)."
    )
    ap.add_argument(
        "--bbox",
        required=True,
        help="south,west,north,east — the search box, which may be loose; --name reports a tight one",
    )
    ap.add_argument(
        "--name",
        action="append",
        default=[],
        help="case-insensitive substring of the OSM `name` tag; repeatable",
    )
    ap.add_argument(
        "--list",
        action="store_true",
        help="list every named way in the bbox, ranked by elevation drop",
    )
    ap.add_argument("--limit", type=int, default=30, help="rows to print in --list mode")
    ap.add_argument(
        "--min-length",
        type=float,
        default=300.0,
        help="in --list mode, skip roads shorter than this many metres",
    )
    ap.add_argument("--no-elevation", action="store_true", help="skip the DEM lookup")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    args = ap.parse_args(argv)

    try:
        south, west, north, east = (float(x) for x in args.bbox.split(","))
    except ValueError:
        ap.error("--bbox must be four numbers: south,west,north,east")
    bbox = (south, west, north, east)
    if not (south < north and west < east):
        ap.error(f"--bbox {bbox} is not south,west,north,east (south<north, west<east)")

    if not args.name and not args.list:
        ap.error("give --name to verify a road, or --list to discover what is in the box")

    source, message = describe_source(bbox)
    region = covering_region(bbox)
    if not args.json:
        print(f"source: {source} — {message}", file=sys.stderr)
        if source.startswith("overpass") and region is not None:
            print(
                f"note: {region.name} is a coverage region but this bbox is not wholly "
                f"inside it (or the GOL lacks it); falling back to Overpass",
                file=sys.stderr,
            )

    nodes, ways = fetch_osm_data(bbox)
    groups = _group_by_name(ways, nodes, args.name or None)
    if args.list:
        groups = [g for g in groups if g.length_m >= args.min_length]

    if not groups:
        if args.name:
            print(f"no way named like {args.name} in bbox {bbox}", file=sys.stderr)
            print(
                "  the bbox may miss the road, or the OSM `name` tag differs from the "
                "popular name — try --list to see what is actually there",
                file=sys.stderr,
            )
        else:
            print(f"no named way over {args.min_length:.0f} m in bbox {bbox}", file=sys.stderr)
        return 1

    elev: dict[str, tuple[float, float, float]] = {}
    if not args.no_elevation:
        elev = _elevation_stats(groups, ElevationService())

    groups.sort(key=lambda g: elev.get(g.name, (0, 0, 0))[2] or g.length_m, reverse=True)
    if args.list:
        groups = groups[: args.limit]

    rows = []
    for g in groups:
        lo, hi, drop = elev.get(g.name, (0.0, 0.0, 0.0))
        length = g.length_m
        rows.append(
            {
                "name": g.name,
                "ways": len(g.ways),
                "length_m": round(length),
                "drop_m": round(drop),
                "avg_grade_pct": round(100 * drop / length, 1) if length else 0.0,
                "elev_min_m": round(lo),
                "elev_max_m": round(hi),
                "highway": g.highways,
                "max_rank": g.max_rank,
                "oneway_ways": g.oneway_count,
                "surface": g.surfaces,
                "bbox": list(g.union_bbox()),
            }
        )

    if args.json:
        print(json.dumps({"bbox": list(bbox), "source": source, "roads": rows}, indent=2))
        return 0

    for r in rows:
        print(f"\n{r['name']}  ({r['ways']} way(s))")
        print(
            f"  {r['length_m']} m long, {r['drop_m']} m of relief "
            f"({r['elev_min_m']}–{r['elev_max_m']} m), avg {r['avg_grade_pct']}%"
        )
        print(f"  highway: {_fmt_counts(r['highway'])}  (max_road_rank >= {r['max_rank']})")
        print(f"  surface: {_fmt_counts(r['surface'])}")
        if r["oneway_ways"]:
            print(
                f"  oneway: {r['oneway_ways']} of {r['ways']} ways — check the legal "
                f"direction is DOWNhill before shipping"
            )
        s, w, n, e = r["bbox"]
        print(f"  bbox=({s}, {w}, {n}, {e})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
