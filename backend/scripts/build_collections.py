"""
Offline builder for the Collections feature.

Runs the real search pipeline over each curated Spot and writes the resulting routes
to `backend/data/collections.json`, which `GET /collections` serves verbatim.

    python -m backend.scripts.build_collections                            # all spots
    python -m backend.scripts.build_collections --spot hawk-hill-conzelman
    python -m backend.scripts.build_collections --city "San Francisco Bay Area"
    python -m backend.scripts.build_collections --dry-run                  # list, don't build
    python -m backend.scripts.build_collections --clean                    # discard old output first

This is deliberately the same pipeline as `POST /search` (see backend/pipeline.py) —
not a reimplementation — so curated routes and searched routes are identical in shape.

Cold runs are network-bound (~15-30 s/spot: Overpass + elevation). Both go through the
normal disk cache at ~/.cache/hillbomb/, so rebuilds are fast and offline. Being slow is
fine; this is an offline script, not a request path.

Incremental by default: results merge into the existing JSON, so one broken spot can't
wipe out the others. Failures are reported per spot and the script exits non-zero if
anything failed, but it always builds every spot it can first.
"""

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from ..config import DEFAULT_ROAD_TYPES, RIDER_PROFILES, SearchConfig
from ..elevation import ElevationService
from ..graph import build_graph
from ..overpass import fetch_osm_data
from ..pathfinding import find_routes
from ..pipeline import RouteFinalizer, mark_traversable, route_payload, traversable_node_ids
from ..spots import SPOTS, Spot, by_city, by_slug

OUT_PATH = Path(__file__).resolve().parents[1] / "data" / "collections.json"

# Bumped when the JSON structure changes; the frontend refuses a version it doesn't know.
SCHEMA_VERSION = 1


class SpotBuildError(Exception):
    """A spot produced no usable routes — almost always bad osm_way_names or bbox."""


def _matches_spot(route_name: str, spot: Spot) -> bool:
    """Case-insensitive substring match of a route's name against the spot's OSM names."""
    lowered = route_name.lower()
    return any(name.lower() in lowered for name in spot.osm_way_names)


def build_spot(spot: Spot, elev_svc: ElevationService) -> dict:
    """Run the full pipeline for one spot and return its JSON entry.

    Raises SpotBuildError if the spot yields no routes on its named road(s), which is
    the signal that the spot definition — not the pipeline — needs fixing.
    """
    t0 = time.perf_counter()

    nodes, ways = fetch_osm_data(spot.bbox)
    if not ways:
        raise SpotBuildError(f"Overpass returned no ways in bbox {spot.bbox}")

    mark_traversable(
        ways,
        road_types=DEFAULT_ROAD_TYPES,
        max_road_rank=spot.max_road_rank,
        allowed_surface_categories=(
            set(spot.allowed_surface_categories)
            if spot.allowed_surface_categories is not None
            else None
        ),
    )

    # Fail early and specifically: if the named road isn't in the fetched data at all,
    # the bbox or the OSM name is wrong, and "no routes found" would be a misleading
    # way to report that.
    named_ways = [w for w in ways if _matches_spot(w.name, spot)]
    if not named_ways:
        raise SpotBuildError(
            f"No OSM way matching {list(spot.osm_way_names)} in bbox {spot.bbox}. "
            f"Check the exact `name` tag on openstreetmap.org, and that the bbox covers the road."
        )
    if not any(w.traversable for w in named_ways):
        classes = sorted({w.highway for w in named_ways})
        raise SpotBuildError(
            f"Found {len(named_ways)} way(s) named {list(spot.osm_way_names)} but none are "
            f"rideable at max_road_rank={spot.max_road_rank}. Their highway class is {classes}; "
            f"raise the spot's max_road_rank (see config.HIGHWAY_RANK)."
        )

    # Elevation only for nodes we might ride — same rule as the live pipeline. The cache
    # is keyed on the full network geometry so re-runs with different filters reuse it.
    used_ids = {nid for w in ways for nid in w.node_ids}
    active_nodes = {nid: n for nid, n in nodes.items() if nid in used_ids}
    traversable_ids = traversable_node_ids(ways)
    needed_nodes = {nid: n for nid, n in active_nodes.items() if nid in traversable_ids}

    coords = [(n.lon, n.lat) for n in needed_nodes.values()]
    cache_coords = [(n.lon, n.lat) for n in active_nodes.values()]
    elevs = elev_svc.get_elevations(coords, None, cache_coords)
    for node, elev in zip(needed_nodes.values(), elevs):
        node.elevation = elev

    config = SearchConfig()
    config.elevation_sample_interval_m = elev_svc.resolution_m
    params = RIDER_PROFILES[spot.rider_profile]

    G = build_graph(nodes, ways, config)

    finalizer = RouteFinalizer(G, nodes, config, params)
    matched = [
        route
        for raw in find_routes(G, nodes, config, params, spot.toggles)
        for route in finalizer.finalize(raw)
        if _matches_spot(route.name, spot)
    ]
    if not matched:
        raise SpotBuildError(
            f"Pipeline found no descent on {list(spot.osm_way_names)}. The road is in the graph, "
            f"so this is likely a real result: the descent may be shorter than the profile's "
            f"min_route_length_m ({params.min_route_length_m} m), or a toggle "
            f"(stay_on_initial_road={spot.toggles.stay_on_initial_road}) may be cutting it short."
        )

    # Best-first: a famous descent is defined by its drop, with length breaking ties.
    matched.sort(key=lambda r: (-r.total_descent_m, -r.length_m))
    kept = matched[:spot.max_routes]

    elapsed = time.perf_counter() - t0
    # flush: a cold build takes minutes and is usually piped to a log, where Python's
    # block buffering would otherwise hide all progress until the very end.
    print(
        f"    {len(matched)} route(s) on {'/'.join(spot.osm_way_names)}, keeping {len(kept)}"
        f" — best: {kept[0].length_m:.0f} m, {kept[0].total_descent_m:.0f} m drop,"
        f" {kept[0].top_speed_kmh:.0f} km/h, flow {kept[0].flow_grade}  [{elapsed:.1f}s]",
        flush=True,
    )

    south, west, north, east = spot.bbox
    return {
        "slug": spot.slug,
        "name": spot.name,
        "city": spot.city,
        "state": spot.state,
        "blurb": spot.blurb,
        "discipline": spot.discipline,
        "notes": spot.notes,
        "confidence": spot.confidence,
        "bbox": list(spot.bbox),
        # Where the map should fly to when the spot is opened.
        "center": [(west + east) / 2, (south + north) / 2],
        "rider_profile": spot.rider_profile,
        "built_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "routes": [route_payload(r) for r in kept],
    }


# ── Output file ───────────────────────────────────────────────────────────────

def load_existing() -> dict[str, dict]:
    """Read collections.json into {slug: entry}. Missing/unreadable file → empty."""
    if not OUT_PATH.exists():
        return {}
    try:
        doc = json.loads(OUT_PATH.read_text())
    except json.JSONDecodeError as exc:
        print(f"warning: {OUT_PATH} is not valid JSON ({exc}); starting fresh", file=sys.stderr)
        return {}
    return {
        entry["slug"]: entry
        for city in doc.get("cities", [])
        for entry in city.get("spots", [])
    }


def write_output(entries: dict[str, dict]) -> None:
    """Write {slug: entry} back out, grouped by city in SPOTS order.

    Structure is always rebuilt from SPOTS, so building one spot never reorders the
    file and the committed diff stays readable. Entries whose spot has been deleted
    from SPOTS are dropped here.
    """
    cities: list[dict] = []
    for spot in SPOTS:
        entry = entries.get(spot.slug)
        if entry is None:
            continue
        city = next((c for c in cities if c["city"] == spot.city), None)
        if city is None:
            city = {"city": spot.city, "spots": []}
            cities.append(city)
        city["spots"].append(entry)

    doc = {"version": SCHEMA_VERSION, "cities": cities}
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(doc, indent=2) + "\n")


def _report_output(entries: dict[str, dict]) -> None:
    where = OUT_PATH.relative_to(Path.cwd()) if OUT_PATH.is_relative_to(Path.cwd()) else OUT_PATH
    n_routes = sum(len(e["routes"]) for e in entries.values())
    n_cities = len({s.city for s in SPOTS if s.slug in entries})
    print(f"\nWrote {where} — {len(entries)} spot(s), {n_cities} cit(ies), {n_routes} route(s)")


# ── CLI ───────────────────────────────────────────────────────────────────────

def select_spots(args) -> list[Spot]:
    if args.spot:
        spot = by_slug(args.spot)
        if spot is None:
            raise SystemExit(
                f"Unknown spot '{args.spot}'. Known: {', '.join(s.slug for s in SPOTS)}"
            )
        return [spot]
    if args.city:
        spots = by_city(args.city)
        if not spots:
            raise SystemExit(
                f"No spots in city '{args.city}'. Known: {', '.join(sorted({s.city for s in SPOTS}))}"
            )
        return spots
    return list(SPOTS)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build curated collections JSON from backend/spots.py.",
    )
    parser.add_argument("--spot", help="build a single spot by slug")
    parser.add_argument("--city", help="build every spot in a metro")
    parser.add_argument("--clean", action="store_true",
                        help="discard existing output instead of merging into it")
    parser.add_argument("--dry-run", action="store_true",
                        help="list the spots that would be built, then exit")
    args = parser.parse_args()

    spots = select_spots(args)

    if args.dry_run:
        print(f"Would build {len(spots)} spot(s):")
        for s in spots:
            print(f"  {s.slug:32s} {s.city:26s} {'/'.join(s.osm_way_names):24s} "
                  f"rank<={s.max_road_rank} confidence={s.confidence}")
        return 0

    entries = {} if args.clean else load_existing()
    elev_svc = ElevationService()
    failures: list[tuple[str, str]] = []

    for i, spot in enumerate(spots, 1):
        print(f"[{i}/{len(spots)}] {spot.slug} — {spot.name}", flush=True)
        try:
            entries[spot.slug] = build_spot(spot, elev_svc)
        except SpotBuildError as exc:
            # Expected class of failure: the spot definition is wrong. Keep going —
            # one bad spot shouldn't block the rest of the build.
            print(f"    FAILED: {exc}", file=sys.stderr, flush=True)
            failures.append((spot.slug, str(exc)))
        except Exception as exc:  # network, elevation, pathfinding — unexpected
            print(f"    ERROR: {type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
            failures.append((spot.slug, f"{type(exc).__name__}: {exc}"))
        # Write after every spot: a cold build is minutes of network work, and losing
        # all of it to a crash on spot 20 would be miserable.
        write_output(entries)

    _report_output(entries)

    if failures:
        print(f"\n{len(failures)} spot(s) failed:", file=sys.stderr)
        for slug, msg in failures:
            print(f"  {slug}: {msg}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
