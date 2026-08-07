"""
Where OSM data comes from: a local GeoDesk GOL where we have one, public Overpass
everywhere else.

The public Overpass instance is a community service with a published fair-use
threshold (~10k queries and ~1 GB per day). Nothing about Hillbomb's traffic
violates that, so this is not a compliance fix — it is a latency fix. A local GOL
answers a viewport query in milliseconds instead of seconds, and it answers it
when Overpass is down.

Coverage is deliberately partial, and deliberately different between environments:

  * **Locally** you want everything. Collections builds 100+ routes across 34
    metros, and doing that against Overpass is both slow and rude. Build the
    `all` tier once (several GB of downloads, ~1 GB of GOL) and every rebuild
    afterwards is local.
  * **On GCP** the GOL rides inside the container image, so every megabyte is
    cold-start pull time. Only regions marked `deploy=True` go in the `deploy`
    tier.

The tier that was actually built is recorded in a manifest written next to the
GOL, and `covering_region` reads *that*, not `COVERAGE_REGIONS`. This matters:
if the router used the full catalog against a deploy-tier GOL, a search in Denver
would be routed to a file that has no Denver in it and would come back with an
empty road network dressed up as a real one. The manifest is what makes it
impossible to claim coverage we didn't build.

Selection is by `HILLBOMB_GOL`, defaulting to `data/hillbomb.gol` in the repo so
local dev and the collections builder pick it up with no configuration. Absent
file, absent manifest, or a bbox outside the built regions — all fall back to
Overpass.
"""

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .overpass import fetch_osm_data as _fetch_overpass
from .types import OSMNode, OSMWay

log = logging.getLogger("hillbomb.osmsource")

Bbox = tuple[float, float, float, float]  # south, west, north, east

# Default location, so `uvicorn backend.main:app` and the collections builder use
# the GOL without anyone remembering to export anything. Repo-relative: this file
# is backend/osmsource.py, so parents[1] is the repo root.
DEFAULT_GOL = Path(__file__).resolve().parents[1] / "data" / "hillbomb.gol"


@dataclass(frozen=True)
class CoverageRegion:
    """An area we can ship local OSM data for.

    `bbox` is padded beyond the curated descents on purpose — see
    `covering_region` for why a request that only *partly* overlaps a region has
    to fall back to Overpass. Padding is what keeps an edge-of-town viewport on
    the fast path instead of bouncing to the network.

    `geofabrik` names the extracts the build script slices this region out of;
    several regions straddle a state line and need more than one.

    `deploy` marks the region for the small tier that ships to Cloud Run.
    """

    slug: str
    name: str
    bbox: Bbox
    geofabrik: tuple[str, ...]
    deploy: bool = False


# Derived from the per-city union of spot bboxes in spots.py, padded by 0.2°
# (~22 km), except the three `deploy` regions whose boxes are hand-tuned wider
# because they are sized for the riding terrain rather than for the descents we
# happen to have curated so far. Geofabrik sources were resolved by intersecting
# each box against Geofabrik's index-v1.json.
#
# Adding a spot in a new city? `test_osmsource.py::test_every_spot_city_has_a_region`
# fails until a region is added here. See docs/local-osm-data.md.
COVERAGE_REGIONS: tuple[CoverageRegion, ...] = (
    CoverageRegion(
        slug="los-angeles",
        name="Los Angeles",
        bbox=(33.550, -119.000, 34.550, -117.250),
        geofabrik=("north-america/us/california",),
        deploy=True,
    ),
    CoverageRegion(
        slug="sf-bay-area",
        name="San Francisco Bay Area",
        bbox=(36.800, -123.150, 38.400, -121.200),
        geofabrik=("north-america/us/california",),
        deploy=True,
    ),
    CoverageRegion(
        slug="tahoe",
        name="Lake Tahoe",
        bbox=(38.600, -120.600, 39.550, -119.600),
        geofabrik=("north-america/us/california",
                  "north-america/us/nevada",),
        deploy=True,
    ),
    CoverageRegion(
        slug="acadia",
        name="Acadia",
        bbox=(44.147, -68.441, 44.573, -68.022),
        geofabrik=("north-america/us/maine",),
        deploy=False,
    ),
    CoverageRegion(
        slug="asheville",
        name="Asheville",
        bbox=(35.400, -82.744, 35.939, -81.955),
        geofabrik=("north-america/us/north-carolina",),
        deploy=False,
    ),
    CoverageRegion(
        slug="austin",
        name="Austin",
        bbox=(30.113, -97.980, 30.541, -97.571),
        geofabrik=("north-america/us/texas",),
        deploy=False,
    ),
    CoverageRegion(
        slug="boise",
        name="Boise",
        bbox=(43.438, -116.411, 43.976, -115.900),
        geofabrik=("north-america/us/idaho",),
        deploy=False,
    ),
    CoverageRegion(
        slug="boston",
        name="Boston",
        bbox=(42.140, -71.342, 42.547, -70.925),
        geofabrik=("north-america/us/massachusetts",),
        deploy=False,
    ),
    CoverageRegion(
        slug="columbia-gorge",
        name="Columbia Gorge",
        bbox=(45.466, -121.590, 45.926, -120.593),
        geofabrik=("north-america/us/oregon",
                  "north-america/us/washington",),
        deploy=False,
    ),
    CoverageRegion(
        slug="crested-butte",
        name="Crested Butte",
        bbox=(38.762, -107.249, 39.221, -106.786),
        geofabrik=("north-america/us/colorado",),
        deploy=False,
    ),
    CoverageRegion(
        slug="denver-boulder",
        name="Denver / Boulder",
        bbox=(39.516, -105.730, 40.277, -105.028),
        geofabrik=("north-america/us/colorado",),
        deploy=False,
    ),
    CoverageRegion(
        slug="great-lakes",
        name="Great Lakes",
        bbox=(43.048, -92.475, 47.673, -87.696),
        geofabrik=("north-america/us/iowa",
                  "north-america/us/michigan",
                  "north-america/us/minnesota",
                  "north-america/us/wisconsin",),
        deploy=False,
    ),
    CoverageRegion(
        slug="honolulu",
        name="Honolulu",
        bbox=(21.107, -158.042, 21.532, -157.611),
        geofabrik=("north-america/us/hawaii",),
        deploy=False,
    ),
    CoverageRegion(
        slug="jackson-northwest-wyoming",
        name="Jackson / Northwest Wyoming",
        bbox=(43.275, -111.157, 44.967, -109.177),
        geofabrik=("north-america/us/idaho",
                  "north-america/us/montana",
                  "north-america/us/wyoming",),
        deploy=False,
    ),
    CoverageRegion(
        slug="las-vegas",
        name="Las Vegas",
        bbox=(36.062, -115.855, 36.545, -115.388),
        geofabrik=("north-america/us/nevada",),
        deploy=False,
    ),
    CoverageRegion(
        slug="mid-atlantic",
        name="Mid-Atlantic",
        bbox=(39.018, -77.627, 40.539, -75.698),
        geofabrik=("north-america/us/delaware",
                  "north-america/us/maryland",
                  "north-america/us/pennsylvania",
                  "north-america/us/virginia",),
        deploy=False,
    ),
    CoverageRegion(
        slug="moab-southeast-utah",
        name="Moab / Southeast Utah",
        bbox=(37.069, -110.146, 38.829, -109.174),
        geofabrik=("north-america/us/utah",),
        deploy=False,
    ),
    CoverageRegion(
        slug="montana",
        name="Montana",
        bbox=(44.747, -113.992, 48.953, -109.208),
        geofabrik=("north-america/us/idaho",
                  "north-america/us/montana",
                  "north-america/us/wyoming",),
        deploy=False,
    ),
    CoverageRegion(
        slug="new-mexico",
        name="New Mexico",
        bbox=(34.961, -106.653, 35.948, -105.632),
        geofabrik=("north-america/us/new-mexico",),
        deploy=False,
    ),
    CoverageRegion(
        slug="new-york",
        name="New York",
        bbox=(41.101, -74.216, 44.604, -73.674),
        geofabrik=("north-america/us/connecticut",
                  "north-america/us/new-jersey",
                  "north-america/us/new-york",),
        deploy=False,
    ),
    CoverageRegion(
        slug="oregon-cascades",
        name="Oregon Cascades",
        bbox=(43.558, -122.725, 44.463, -121.598),
        geofabrik=("north-america/us/oregon",),
        deploy=False,
    ),
    CoverageRegion(
        slug="ozarks",
        name="Ozarks",
        bbox=(35.017, -94.396, 36.678, -92.965),
        geofabrik=("north-america/us/arkansas",
                  "north-america/us/missouri",),
        deploy=False,
    ),
    CoverageRegion(
        slug="pittsburgh",
        name="Pittsburgh",
        bbox=(40.264, -80.184, 40.668, -79.779),
        geofabrik=("north-america/us/pennsylvania",),
        deploy=False,
    ),
    CoverageRegion(
        slug="portland",
        name="Portland",
        bbox=(45.286, -122.914, 45.752, -121.879),
        geofabrik=("north-america/us/oregon",
                  "north-america/us/washington",),
        deploy=False,
    ),
    CoverageRegion(
        slug="salt-lake-city",
        name="Salt Lake City",
        bbox=(40.558, -112.011, 40.987, -111.500),
        geofabrik=("north-america/us/utah",),
        deploy=False,
    ),
    CoverageRegion(
        slug="seattle",
        name="Seattle",
        bbox=(47.419, -122.558, 47.850, -122.157),
        geofabrik=("north-america/us/washington",),
        deploy=False,
    ),
    CoverageRegion(
        slug="sedona",
        name="Sedona",
        bbox=(34.660, -111.964, 35.114, -111.441),
        geofabrik=("north-america/us/arizona",),
        deploy=False,
    ),
    CoverageRegion(
        slug="shenandoah-blue-ridge",
        name="Shenandoah & Blue Ridge",
        bbox=(37.293, -79.777, 38.936, -78.837),
        geofabrik=("north-america/us/virginia",
                  "north-america/us/west-virginia",),
        deploy=False,
    ),
    CoverageRegion(
        slug="sierra-nevada",
        name="Sierra Nevada",
        bbox=(39.368, -121.023, 39.827, -120.465),
        geofabrik=("north-america/us/california",),
        deploy=False,
    ),
    CoverageRegion(
        slug="southern-appalachians",
        name="Southern Appalachians",
        bbox=(34.523, -84.272, 36.377, -81.877),
        geofabrik=("north-america/us/georgia",
                  "north-america/us/north-carolina",
                  "north-america/us/south-carolina",
                  "north-america/us/tennessee",),
        deploy=False,
    ),
    CoverageRegion(
        slug="tucson",
        name="Tucson",
        bbox=(31.744, -111.830, 32.932, -109.494),
        geofabrik=("north-america/us/arizona",),
        deploy=False,
    ),
    CoverageRegion(
        slug="vermont",
        name="Vermont",
        bbox=(43.231, -73.185, 44.790, -71.693),
        geofabrik=("north-america/us/new-hampshire",
                  "north-america/us/vermont",),
        deploy=False,
    ),
    CoverageRegion(
        slug="washington",
        name="Washington",
        bbox=(47.110, -123.720, 49.114, -120.217),
        geofabrik=("north-america/us/washington",),
        deploy=False,
    ),
    CoverageRegion(
        slug="white-mountains",
        name="White Mountains",
        bbox=(43.803, -71.889, 44.268, -71.220),
        geofabrik=("north-america/us/new-hampshire",),
        deploy=False,
    ),
)

DEPLOY_REGIONS = tuple(r for r in COVERAGE_REGIONS if r.deploy)

TIERS: dict[str, tuple[CoverageRegion, ...]] = {
    "deploy": DEPLOY_REGIONS,
    "all": COVERAGE_REGIONS,
}


def manifest_path(gol: str | os.PathLike) -> Path:
    """Where build_gol.py records which regions actually went into a GOL."""
    return Path(str(gol) + ".regions.json")


def _load_manifest(gol: str) -> tuple[CoverageRegion, ...]:
    """Regions present in `gol`, per its manifest. Empty if unreadable.

    Empty means "cover nothing", which routes every search to Overpass. That is
    the safe direction to fail: the alternative — assuming full coverage — serves
    truncated road networks that look completely legitimate downstream.
    """
    path = manifest_path(gol)
    try:
        data = json.loads(path.read_text())
    except FileNotFoundError:
        log.warning("%s has no manifest at %s; using Overpass for all searches",
                    gol, path)
        return ()
    except (OSError, json.JSONDecodeError) as exc:
        log.warning("could not read GOL manifest %s (%s); using Overpass", path, exc)
        return ()

    by_slug = {r.slug: r for r in COVERAGE_REGIONS}
    regions = []
    for entry in data.get("regions", []):
        known = by_slug.get(entry.get("slug", ""))
        # Trust the manifest's bbox, not the catalog's: the GOL was built from
        # whatever the bbox was at build time, and if the catalog has since been
        # edited the file on disk is the one telling the truth.
        regions.append(CoverageRegion(
            slug=entry["slug"],
            name=entry.get("name", entry["slug"]),
            bbox=tuple(entry["bbox"]),
            geofabrik=tuple(entry.get("geofabrik", ())),
            deploy=known.deploy if known else False,
        ))
    return tuple(regions)


_manifest_cache: dict[tuple[str, float], tuple[CoverageRegion, ...]] = {}


def built_regions(gol: str) -> tuple[CoverageRegion, ...]:
    """Regions in `gol`, cached on (path, manifest mtime).

    Keying on mtime rather than path alone means rebuilding the GOL under a
    running dev server picks up the new coverage instead of serving yesterday's
    region list until someone restarts.
    """
    try:
        stamp = manifest_path(gol).stat().st_mtime
    except OSError:
        stamp = 0.0
    key = (gol, stamp)
    if key not in _manifest_cache:
        _manifest_cache[key] = _load_manifest(gol)
    return _manifest_cache[key]


def covering_region(
    bbox: Bbox, regions: tuple[CoverageRegion, ...] | None = None
) -> CoverageRegion | None:
    """The region wholly containing `bbox`, or None.

    Containment must be *total*, not overlapping. A partly-covered request served
    from the GOL comes back with the road network truncated at the GOL's edge —
    and `overpass._contiguous_inbbox_runs` then trims every way at that edge and
    returns it as though it were real. Descents would stop dead at an invisible
    line with nothing logged and no error raised. Overlap is therefore a fallback
    condition, not a partial-hit condition.

    `regions` defaults to the full catalog; the request path passes the regions
    the GOL was actually built with.
    """
    south, west, north, east = bbox
    for region in (COVERAGE_REGIONS if regions is None else regions):
        r_south, r_west, r_north, r_east = region.bbox
        if r_south <= south and north <= r_north and r_west <= west and east <= r_east:
            return region
    return None


_warned_missing: set[str] = set()


def gol_path() -> str | None:
    """Path to a usable local GOL, or None.

    A configured-but-absent path returns None rather than raising. The Dockerfile
    sets HILLBOMB_GOL unconditionally and copies the GOL with a glob, so an image
    built without one has the variable set and the file missing — and the right
    behaviour there is to serve every search from Overpass, not to fail every
    search in a covered region. Warned once per path so the misconfiguration is
    still visible in logs.

    HILLBOMB_GOL="" explicitly disables the local source without deleting the file.
    """
    raw = os.environ.get("HILLBOMB_GOL")
    if raw is not None and not raw.strip():
        return None
    path = raw or str(DEFAULT_GOL)
    if not os.path.exists(path):
        # Only warn about a path someone asked for. The default being absent is
        # the ordinary state of a fresh checkout, not a misconfiguration.
        if raw and path not in _warned_missing:
            _warned_missing.add(path)
            log.warning("HILLBOMB_GOL=%s does not exist; using Overpass for all searches", path)
        return None
    return path


def describe_source(bbox: Bbox) -> tuple[str, str]:
    """(source, human message) for `bbox`, without fetching anything.

    Three outcomes, and the user should be able to tell them apart: a local GOL
    hit is instant, a warm Overpass cache hit is nearly instant, and a cold
    Overpass query is seconds-to-tens-of-seconds and may sit in a retry backoff.
    Showing "Querying Overpass API..." for all three makes the fast paths look
    broken and the slow path look hung.
    """
    gol = gol_path()
    if gol:
        region = covering_region(bbox, built_regions(gol))
        if region is not None:
            return "geodesk", f"Reading local map data ({region.name})..."

    from .overpass import is_cached

    if is_cached(bbox):
        return "overpass-cache", "Loading cached map data..."
    return "overpass", "Querying Overpass API..."


def source_for(bbox: Bbox) -> str:
    """Which backend will serve `bbox`. See describe_source."""
    return describe_source(bbox)[0]


def fetch_osm_data(
    bbox: Bbox,
    on_retry: Callable[[str, int, int, float], None] | None = None,
) -> tuple[dict[int, OSMNode], list[OSMWay]]:
    """Fetch the classified road network in `bbox`, from whichever source has it.

    Same signature and same return shape as `overpass.fetch_osm_data` — this is a
    drop-in replacement for it at the call sites, and the two sources are held to
    producing matching output by `test_osmsource.py`.

    `on_retry` is only ever invoked by the Overpass path; there is nothing to
    retry against a local file.
    """
    gol = gol_path()
    if gol:
        region = covering_region(bbox, built_regions(gol))
        if region is not None:
            # Imported lazily: geodesk is an optional dependency, and an install
            # without it must still run the Overpass path normally.
            from . import geodesk_source

            log.info("osm source: geodesk (%s)", region.slug)
            return geodesk_source.fetch_osm_data(gol, bbox)
        log.info("osm source: overpass (bbox outside GOL coverage)")

    return _fetch_overpass(bbox, on_retry=on_retry)
