"""
Build the local GeoDesk GOL for the regions in `osmsource.COVERAGE_REGIONS`.

    # local cache — every region, several GB of downloads, ~1 GB of GOL
    python -m backend.scripts.build_gol --tier all \
        --work-dir /tmp/golbuild --out data/hillbomb.gol

    # what ships to Cloud Run — the three deploy regions, ~200 MB
    python -m backend.scripts.build_gol --tier deploy \
        --work-dir /tmp/golbuild --out data/hillbomb-deploy.gol

    # see what a tier covers without building it
    python -m backend.scripts.build_gol --tier all --list --work-dir . --out /dev/null

Alongside the GOL it writes `<out>.regions.json`, the manifest recording which
regions actually went in. `osmsource` reads coverage from that file, NOT from
COVERAGE_REGIONS — so a deploy-tier GOL cannot be mistaken for a full one and
asked to serve a bbox it has no data for.

The regions come from `osmsource` on purpose. If this script had its own list, the
set of areas we claim to cover and the set we actually built could drift, and the
failure mode of that drift is silent: `osmsource` would route a request to a GOL
that doesn't hold it and hand back a road network truncated at the file's edge.
One list, no drift.

Pipeline, per region:

    geofabrik extract  --osmium extract-->  region slice
                       --tags-filter---->   roads only
    all regions        --merge---------->   one pbf   --gol build-->  .gol

The tag filter is the whole reason this is cheap. Hillbomb reads exactly the 17
highway classes in `config.HIGHWAY_RANK` plus two node tags; everything else in
OSM — buildings, landuse, addresses, footways — is dropped before it ever reaches
`gol build`.

Requirements:
  * osmium-tool      `brew install osmium-tool`
  * the GOL utility  https://github.com/clarisma/geodesk-gol/releases (v2+)
                     point HILLBOMB_GOL_TOOL at the `gol` binary, or put it on PATH

Take the tool from `clarisma/geodesk-gol`, NOT the older `clarisma/gol-tool`
repo. The latter tops out at 1.2.0 and writes GOL format 1.0, which `geodesk` 2.x
refuses to open ("Unsupported Store Format"). It also has no `--waynode-ids`
option at all — its nearest equivalent is `--updatable`. v2 is a native binary,
so unlike 1.x it needs no JVM.

Licensing note: the `gol` build tool is AGPL-3.0, but it is a standalone CLI we
run to produce a data file — it is not linked into, distributed with, or invoked
by the service. The `geodesk` Python package the service *does* import is
LGPL-3.0, used unmodified as a library.
"""

import argparse
import json
import logging
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from ..config import HIGHWAY_RANK
from ..osmsource import COVERAGE_REGIONS, TIERS, CoverageRegion, manifest_path

log = logging.getLogger("hillbomb.build_gol")

GEOFABRIK_BASE = "https://download.geofabrik.de"

# Ways: exactly the classes ROAD_NETWORK_TYPES is derived from. Nodes: exactly the
# two traffic-control tags the pathfinder's hard-stop toggles read.
WAY_FILTER = f"w/highway={','.join(sorted(HIGHWAY_RANK))}"
NODE_FILTER = "n/highway=traffic_signals,stop"


def _run(cmd: list[str], what: str, hint: str = "") -> None:
    log.info("%s: %s", what, " ".join(cmd))
    t0 = time.perf_counter()
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        sys.stderr.write(proc.stdout)
        sys.stderr.write(proc.stderr)
        output = proc.stdout + proc.stderr
        # osmium reports a truncated source this way, and the message names the
        # region rather than the file at fault. Say which file to delete — note
        # that `osmium fileinfo` will call a truncated file healthy, because it
        # only reads the header. `osmium fileinfo -e` reads the whole thing.
        if "unexpected EOF" in output and hint:
            raise SystemExit(
                f"{what} failed (exit {proc.returncode}): {hint} is truncated. "
                f"Delete it and re-run — the download will be repeated.\n"
                f"Verify others with: osmium fileinfo -e <file>"
            )
        raise SystemExit(f"{what} failed (exit {proc.returncode})")
    log.info("%s: done in %.0fs", what, time.perf_counter() - t0)


def _mb(path: Path) -> float:
    return path.stat().st_size / 1e6


def download(slug: str, work: Path) -> Path:
    """Fetch a Geofabrik extract, e.g. "north-america/us/california".

    Downloads to a `.part` file and renames on completion. Writing straight to
    the final name means an interrupted download — Ctrl-C, a dropped connection,
    a parent process exiting — leaves a truncated .pbf that the `dest.exists()`
    check below then happily reuses on the next run. That surfaces much later and
    much less helpfully as `PBF error: unexpected EOF` from osmium, and the file
    it names looks perfectly ordinary (`osmium fileinfo` reads only the header, so
    it reports the file as fine).
    """
    dest = work / f"{slug.rsplit('/', 1)[-1]}-latest.osm.pbf"
    if dest.exists():
        log.info("have %s (%.0f MB)", dest.name, _mb(dest))
        return dest
    url = f"{GEOFABRIK_BASE}/{slug}-latest.osm.pbf"
    log.info("downloading %s", url)
    t0 = time.perf_counter()
    part = dest.with_suffix(dest.suffix + ".part")
    part.unlink(missing_ok=True)
    try:
        urllib.request.urlretrieve(url, part)
    except BaseException:
        part.unlink(missing_ok=True)
        raise
    part.replace(dest)
    log.info("downloaded %s (%.0f MB) in %.0fs", dest.name, _mb(dest), time.perf_counter() - t0)
    return dest


def slice_region(region: CoverageRegion, work: Path) -> Path:
    """Cut `region` out of its source extracts and strip it to roads."""
    south, west, north, east = region.bbox
    bbox_arg = f"{west},{south},{east},{north}"  # osmium wants W,S,E,N

    pieces: list[Path] = []
    for slug in region.geofabrik:
        src = download(slug, work)
        piece = work / f"{region.slug}--{slug.rsplit('/', 1)[-1]}.osm.pbf"
        _run(
            ["osmium", "extract", "--overwrite", "-b", bbox_arg, str(src), "-o", str(piece)],
            f"extract {region.slug} from {src.name}",
            hint=str(src),
        )
        pieces.append(piece)

    if len(pieces) == 1:
        combined = pieces[0]
    else:
        # Tahoe straddles the CA/NV line. osmium merge drops objects that appear
        # in more than one input, so the shared border data doesn't double up.
        combined = work / f"{region.slug}--merged.osm.pbf"
        _run(
            ["osmium", "merge", "--overwrite", *[str(p) for p in pieces], "-o", str(combined)],
            f"merge {region.slug} sources",
        )

    roads = work / f"{region.slug}-roads.osm.pbf"
    # No -R: referenced nodes must come along, or the ways have no geometry.
    _run(
        ["osmium", "tags-filter", "--overwrite", str(combined),
         WAY_FILTER, NODE_FILTER, "-o", str(roads)],
        f"tag-filter {region.slug}",
    )
    log.info("region %s: %.1f MB of roads", region.slug, _mb(roads))
    return roads


def build(out: Path, work: Path, regions: tuple[CoverageRegion, ...]) -> None:
    work.mkdir(parents=True, exist_ok=True)

    road_pbfs = [slice_region(r, work) for r in regions]

    if len(road_pbfs) == 1:
        merged = road_pbfs[0]
    else:
        merged = work / "hillbomb-roads.osm.pbf"
        _run(
            ["osmium", "merge", "--overwrite", *[str(p) for p in road_pbfs], "-o", str(merged)],
            "merge regions",
        )

    gol_tool = os.environ.get("HILLBOMB_GOL_TOOL") or shutil.which("gol")
    if not gol_tool:
        raise SystemExit(
            "gol tool not found. Download v2+ from "
            "https://github.com/clarisma/geodesk-gol/releases and set "
            "HILLBOMB_GOL_TOOL to the binary, or put gol on PATH."
        )

    # Build to a scratch path and swap, never in place. Building over the live
    # file means that a build killed partway (Ctrl-C, a laptop asleep, a parent
    # process exiting) leaves a *partially written* GOL on disk next to a manifest
    # that still vouches for it — which reads as an empty road network and shows
    # up as "no hill bombs found" in a region we supposedly cover. Nothing about
    # that state looks broken from the outside.
    staged = out.with_suffix(out.suffix + ".building")
    staged.unlink(missing_ok=True)
    # --waynode-ids is not optional for us. See geodesk_source.MissingWaynodeIds:
    # without it every untagged intersection vertex reports id 0 and the graph
    # silently collapses.
    _run([gol_tool, "build", "--waynode-ids", str(staged), str(merged)], "gol build")

    manifest = manifest_path(out)
    # Retire the old manifest *before* swapping the file in. If the process dies
    # between these two steps the GOL has no manifest, which means no coverage and
    # every search falls back to Overpass — correct, just slower. The reverse order
    # would leave the previous tier's manifest describing the new file.
    manifest.unlink(missing_ok=True)
    out.unlink(missing_ok=True)
    staged.replace(out)

    # The manifest is what osmsource trusts for coverage — not COVERAGE_REGIONS.
    # Written last, so a GOL is only ever claimed as covering regions once it is
    # complete and in place.
    manifest.write_text(json.dumps({
        "gol": out.name,
        "regions": [
            {"slug": r.slug, "name": r.name, "bbox": list(r.bbox),
             "geofabrik": list(r.geofabrik)}
            for r in regions
        ],
    }, indent=1) + "\n")

    log.info("=" * 68)
    for r in sorted(regions, key=lambda r: r.slug):
        log.info("  %-28s %s", r.slug, r.bbox)
    log.info("-" * 68)
    log.info("regions          : %8d", len(regions))
    log.info("merged roads pbf : %8.1f MB  %s", _mb(merged), merged.name)
    log.info("GOL              : %8.1f MB  %s", _mb(out), out.name)
    log.info("manifest         : %s", manifest.name)
    log.info("=" * 68)
    if _mb(out) > 500:
        log.warning(
            "This GOL is %.0f MB. That is fine on a workstation but too big to ship "
            "in the Cloud Run image — deploy with --tier deploy instead.", _mb(out)
        )


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--work-dir", type=Path, required=True,
                    help="scratch space for downloads and intermediates (needs ~3x the source pbf)")
    ap.add_argument("--out", type=Path, required=True, help="output .gol path")
    ap.add_argument("--tier", choices=sorted(TIERS), default="deploy",
                    help="'deploy' = the small set that ships in the Cloud Run image "
                         "(default); 'all' = every region, for a local cache")
    ap.add_argument("--regions", nargs="*", metavar="SLUG",
                    help="explicit region slugs; overrides --tier")
    ap.add_argument("--list", action="store_true",
                    help="print the regions that would be built, then exit")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    if args.regions:
        wanted = set(args.regions)
        regions = tuple(r for r in COVERAGE_REGIONS if r.slug in wanted)
        missing = wanted - {r.slug for r in regions}
        if missing:
            raise SystemExit(f"unknown region slug(s): {', '.join(sorted(missing))}")
    else:
        regions = TIERS[args.tier]

    if args.list:
        sources = sorted({s for r in regions for s in r.geofabrik})
        for r in sorted(regions, key=lambda r: r.slug):
            print(f"{r.slug:28} {str(r.bbox):46} {', '.join(s.rsplit('/', 1)[-1] for s in r.geofabrik)}")
        print(f"\n{len(regions)} regions, {len(sources)} Geofabrik extracts to download")
        return

    build(args.out, args.work_dir, regions)


if __name__ == "__main__":
    main()
