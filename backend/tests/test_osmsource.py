"""
Source routing: which bboxes are served from the local GOL and which fall back to
Overpass.

The containment rule is the whole point of this module, so most of these tests are
about the boundary. A request that only *partly* overlaps a GOL region must fall
back — serving it locally returns a road network truncated at the file's edge,
which downstream code cannot distinguish from a genuinely sparse area.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from ..osmsource import (
    COVERAGE_REGIONS,
    DEPLOY_REGIONS,
    TIERS,
    covering_region,
    describe_source,
    fetch_osm_data,
    manifest_path,
    source_for,
)
from ..spots import SPOTS

BAY = next(r for r in COVERAGE_REGIONS if r.slug == "sf-bay-area")
TAHOE = next(r for r in COVERAGE_REGIONS if r.slug == "tahoe")
LA = next(r for r in COVERAGE_REGIONS if r.slug == "los-angeles")

# Twin Peaks Boulevard, well inside the Bay Area region.
SF_BBOX = (37.74577, -122.45089, 37.76110, -122.44567)


# ── containment ───────────────────────────────────────────────────────────────

def test_bbox_inside_a_region_is_covered():
    assert covering_region(SF_BBOX) is BAY


def test_a_regions_own_bbox_is_covered():
    """Containment is inclusive — a viewport exactly matching the region is fine."""
    for region in COVERAGE_REGIONS:
        assert covering_region(region.bbox) is region


def test_bbox_outside_every_region_falls_back():
    lisbon = (38.69, -9.25, 38.80, -9.10)
    assert covering_region(lisbon) is None


@pytest.mark.parametrize("nudge", ["west", "east", "south", "north"])
def test_bbox_hanging_over_one_edge_falls_back(nudge):
    """Partial overlap is a fallback condition, not a partial hit.

    A GOL holds nothing outside its build bbox. Served locally, a request
    straddling the edge comes back with every way trimmed at that edge by
    _contiguous_inbbox_runs — indistinguishable from real data, so descents would
    silently dead-end along an invisible line.
    """
    south, west, north, east = BAY.bbox
    spill = {
        "west": (south + 0.1, west - 0.1, north - 0.1, east - 0.1),
        "east": (south + 0.1, west + 0.1, north - 0.1, east + 0.1),
        "south": (south - 0.1, west + 0.1, north - 0.1, east - 0.1),
        "north": (south + 0.1, west + 0.1, north + 0.1, east - 0.1),
    }[nudge]
    assert covering_region(spill) is None


def test_bbox_spanning_two_regions_falls_back():
    """The Bay Area and Tahoe regions don't touch, so a box over both is in neither."""
    spanning = (37.0, -123.0, 39.4, -119.7)
    assert covering_region(spanning) is None


# Regions are named after the spot city they were derived from, which is what
# ties a curated descent to the local data that should serve it.
BY_CITY = {r.name: r for r in COVERAGE_REGIONS}


def test_every_spot_city_has_a_region():
    """Adding a spot in a new city must add a region, or Collections builds it
    against Overpass forever without anyone noticing."""
    missing = sorted({s.city for s in SPOTS} - set(BY_CITY))
    assert not missing, f"no CoverageRegion for: {missing}"


def test_every_spot_fits_inside_its_region():
    """Padding has to be generous enough to hold the curated descents.

    A spot hanging over its region's edge falls back to Overpass on every
    Collections rebuild — correct output, but it also means a user panning around
    that descent gets no benefit from data we did build for that area.
    """
    for spot in SPOTS:
        region = BY_CITY[spot.city]
        assert covering_region(spot.bbox, (region,)) is region, (
            f"{spot.slug} ({spot.bbox}) is not inside {region.slug} {region.bbox}"
        )


def test_region_slugs_are_unique():
    slugs = [r.slug for r in COVERAGE_REGIONS]
    assert len(slugs) == len(set(slugs))


def test_deploy_tier_is_a_subset_of_all():
    assert set(DEPLOY_REGIONS) <= set(COVERAGE_REGIONS)
    assert TIERS["deploy"] == DEPLOY_REGIONS
    assert TIERS["all"] == COVERAGE_REGIONS
    # A deploy tier that grew to everything would silently blow up the image.
    assert len(DEPLOY_REGIONS) < len(COVERAGE_REGIONS)


def test_every_region_names_a_source_extract():
    for r in COVERAGE_REGIONS:
        assert r.geofabrik, f"{r.slug} has no Geofabrik source; build_gol cannot build it"


# ── routing ───────────────────────────────────────────────────────────────────

def test_without_a_gol_everything_goes_to_overpass(monkeypatch):
    monkeypatch.setenv("HILLBOMB_GOL", "")
    assert source_for(SF_BBOX).startswith("overpass")

    with patch("backend.osmsource._fetch_overpass", return_value=({}, [])) as fake:
        fetch_osm_data(SF_BBOX)
    fake.assert_called_once()


@pytest.fixture
def fake_gol(tmp_path, monkeypatch):
    """A HILLBOMB_GOL pointing at a file that exists, with a deploy-tier manifest.

    The GOL contents are never read — every test using this mocks the reader. The
    manifest is real, because coverage is decided from it.
    """
    path = tmp_path / "hillbomb.gol"
    path.write_bytes(b"")
    manifest_path(path).write_text(json.dumps({
        "gol": path.name,
        "regions": [
            {"slug": r.slug, "name": r.name, "bbox": list(r.bbox),
             "geofabrik": list(r.geofabrik)}
            for r in DEPLOY_REGIONS
        ],
    }))
    monkeypatch.setenv("HILLBOMB_GOL", str(path))
    return str(path)


def test_covered_bbox_uses_the_gol(fake_gol):
    assert source_for(SF_BBOX) == "geodesk"

    with patch("backend.geodesk_source.fetch_osm_data", return_value=({}, [])) as fake:
        fetch_osm_data(SF_BBOX)
    fake.assert_called_once_with(fake_gol, SF_BBOX)


def test_a_gol_path_that_does_not_exist_falls_back(monkeypatch):
    """The Dockerfile sets HILLBOMB_GOL whether or not the GOL was built.

    Failing every covered search because the file is absent would be the worst
    possible reading of a partial-coverage design.
    """
    monkeypatch.setenv("HILLBOMB_GOL", "/nonexistent/hillbomb.gol")
    # "overpass" vs "overpass-cache" depends on the developer's ~/.cache/hillbomb,
    # which tests must not depend on. What is under test is that it isn't geodesk.
    assert source_for(SF_BBOX).startswith("overpass")

    with patch("backend.osmsource._fetch_overpass", return_value=({}, [])) as fake:
        fetch_osm_data(SF_BBOX)
    fake.assert_called_once()


def test_uncovered_bbox_uses_overpass_even_with_a_gol(fake_gol):
    lisbon = (38.69, -9.25, 38.80, -9.10)
    assert source_for(lisbon).startswith("overpass")

    with patch("backend.osmsource._fetch_overpass", return_value=({}, [])) as fake:
        fetch_osm_data(lisbon)
    fake.assert_called_once()


def test_on_retry_reaches_overpass(monkeypatch):
    """The retry callback is Overpass-only, but it must still be forwarded."""
    monkeypatch.setenv("HILLBOMB_GOL", "")
    cb = object()
    with patch("backend.osmsource._fetch_overpass", return_value=({}, [])) as fake:
        fetch_osm_data(SF_BBOX, on_retry=cb)
    assert fake.call_args.kwargs["on_retry"] is cb


# ── the manifest decides coverage, not the catalog ────────────────────────────

def test_a_region_in_the_catalog_but_not_the_gol_falls_back(fake_gol):
    """The headline reason the manifest exists.

    `fake_gol` is a deploy-tier build: three California regions. Denver is in
    COVERAGE_REGIONS but not in that file. Routed by the catalog, this search
    would query a GOL with no Colorado in it and get an empty road network back
    — which downstream is indistinguishable from "no rideable roads here".
    """
    denver = next(r for r in COVERAGE_REGIONS if r.slug == "denver-boulder")
    assert covering_region(denver.bbox) is denver          # catalog says yes
    assert source_for(denver.bbox) != "geodesk"            # manifest says no

    with patch("backend.osmsource._fetch_overpass", return_value=({}, [])) as fake:
        fetch_osm_data(denver.bbox)
    fake.assert_called_once()


def test_a_gol_without_a_manifest_covers_nothing(tmp_path, monkeypatch):
    """An unreadable manifest must mean no coverage, never assumed coverage."""
    path = tmp_path / "hillbomb.gol"
    path.write_bytes(b"")
    monkeypatch.setenv("HILLBOMB_GOL", str(path))

    assert source_for(SF_BBOX) != "geodesk"


def test_a_corrupt_manifest_covers_nothing(tmp_path, monkeypatch):
    path = tmp_path / "hillbomb.gol"
    path.write_bytes(b"")
    manifest_path(path).write_text("{not json")
    monkeypatch.setenv("HILLBOMB_GOL", str(path))

    assert source_for(SF_BBOX) != "geodesk"


def test_manifest_bbox_wins_over_the_catalog(tmp_path, monkeypatch):
    """The file on disk was built from the bbox in its manifest.

    If the catalog has been edited since, the manifest is the one telling the
    truth about what data is actually in the file.
    """
    path = tmp_path / "hillbomb.gol"
    path.write_bytes(b"")
    # Same slug as a real region, but a box covering only a sliver of it.
    manifest_path(path).write_text(json.dumps({"regions": [
        {"slug": "sf-bay-area", "name": "San Francisco Bay Area",
         "bbox": [37.75, -122.46, 37.76, -122.45], "geofabrik": []},
    ]}))
    monkeypatch.setenv("HILLBOMB_GOL", str(path))

    assert source_for(SF_BBOX) != "geodesk"                 # SF_BBOX is wider
    assert source_for((37.752, -122.455, 37.755, -122.452)) == "geodesk"


# ── status text ───────────────────────────────────────────────────────────────

def test_status_text_distinguishes_all_three_sources(fake_gol):
    """Local, warm cache and cold query differ by orders of magnitude in latency.

    One message for all three makes the fast paths look broken and the slow path
    look hung.
    """
    source, message = describe_source(SF_BBOX)
    assert source == "geodesk"
    assert "local" in message.lower()
    assert "San Francisco Bay Area" in message

    lisbon = (38.69, -9.25, 38.80, -9.10)
    with patch("backend.overpass.is_cached", return_value=True):
        source, message = describe_source(lisbon)
    assert source == "overpass-cache"
    assert "cached" in message.lower()

    with patch("backend.overpass.is_cached", return_value=False):
        source, message = describe_source(lisbon)
    assert source == "overpass"
    assert "Overpass" in message

    assert len({describe_source(SF_BBOX)[1]}) == 1


# ── the two sources must agree ────────────────────────────────────────────────

# A GOL is a snapshot of a Geofabrik extract; Overpass is live. Ways edited on
# OSM since the build legitimately differ, so exact equality is the wrong bar —
# measured against a same-day extract, a 17k-way SF viewport disagreed on 3 ways,
# all of them edited upstream that morning. Geometry is therefore checked as a
# ratio; tags are checked exactly, because a tag difference on a way both sources
# agree on the shape of cannot be vintage — it is a parsing bug.
MIN_GEOMETRY_AGREEMENT = 0.99


@pytest.mark.integration
def test_geodesk_and_overpass_agree(real_gol):
    """Run one bbox through both sources and diff.

    This is the test that matters. It catches a GOL built without
    `--waynode-ids` (every untagged vertex would collapse onto id 0), and any
    drift in tag parsing between the two readers.

    Needs a built GOL: HILLBOMB_GOL=data/hillbomb.gol pytest -m integration -k agree
    """
    gol = real_gol

    from .. import geodesk_source
    from ..overpass import fetch_osm_data as overpass_fetch

    g_nodes, g_ways = geodesk_source.fetch_osm_data(gol, SF_BBOX)
    o_nodes, o_ways = overpass_fetch(SF_BBOX)

    # Two empty results are trivially equal. Twin Peaks has ~136 ways; anything
    # near zero means one source returned nothing and the rest proves nothing.
    assert len(o_ways) > 50, f"Overpass returned only {len(o_ways)} ways — bad fixture?"
    assert any(n.is_traffic_signal for n in o_nodes.values())
    assert any(n.is_stop_sign for n in o_nodes.values())

    def key(w):
        return (w.id, tuple(w.node_ids))

    g_keys = {key(w) for w in g_ways}
    o_keys = {key(w) for w in o_ways}
    agreement = len(g_keys & o_keys) / len(o_keys)
    assert agreement >= MIN_GEOMETRY_AGREEMENT, (
        f"only {agreement:.3%} of ways match. A handful is upstream editing; a "
        f"large gap is a reader bug or a GOL built for a different area. "
        f"Overpass-only: {sorted(w[0] for w in o_keys - g_keys)[:10]}"
    )

    shared = g_keys & o_keys
    assert len(shared) > 50

    # Node identity and position, over the nodes both sources returned.
    for nid in set(g_nodes) & set(o_nodes):
        g_node, o_node = g_nodes[nid], o_nodes[nid]
        assert g_node.lat == pytest.approx(o_node.lat, abs=1e-7)
        assert g_node.lon == pytest.approx(o_node.lon, abs=1e-7)
        assert g_node.is_traffic_signal == o_node.is_traffic_signal
        assert g_node.is_stop_sign == o_node.is_stop_sign

    # Tags: exact, no tolerance. This is the half that catches _tags() regressing
    # (geodesk hands back mtb:scale as an int, Overpass as a string).
    g_by_key = {key(w): w for w in g_ways}
    o_by_key = {key(w): w for w in o_ways}
    for k in shared:
        for field in ("highway", "oneway", "oneway_reverse", "is_bridge",
                      "is_tunnel", "surface", "name", "trail_difficulty"):
            assert getattr(g_by_key[k], field) == getattr(o_by_key[k], field), (
                f"way {k[0]}: {field} differs"
            )


# ── an interrupted build must not leave claimed-but-incomplete data ────────────

def test_build_stages_the_gol_and_writes_the_manifest_last(tmp_path, monkeypatch):
    """A killed build must never leave a partial GOL with a manifest vouching for it.

    That combination reads as an empty road network in a region we claim to
    cover, which surfaces as "no hill bombs found" — indistinguishable from flat
    terrain. So the build writes to a scratch path, retires the old manifest
    before swapping, and writes the new manifest only once the file is in place.
    """
    from ..scripts import build_gol

    out = tmp_path / "hillbomb.gol"
    out.write_bytes(b"previous build")
    manifest_path(out).write_text(json.dumps({"regions": [
        {"slug": "sf-bay-area", "name": "San Francisco Bay Area",
         "bbox": list(BAY.bbox), "geofabrik": []},
    ]}))

    seen = {}

    def fake_run(cmd, what):
        if cmd[1] == "build":
            target = Path(cmd[3])
            # The live file and its manifest must both be untouchable at this point.
            seen["built_to_scratch"] = target != out
            seen["live_gol_intact"] = out.read_bytes() == b"previous build"
            seen["manifest_still_there"] = manifest_path(out).exists()
            target.write_bytes(b"new build")

    monkeypatch.setattr(build_gol, "_run", fake_run)
    monkeypatch.setattr(build_gol, "slice_region", lambda r, w: tmp_path / "roads.osm.pbf")
    monkeypatch.setenv("HILLBOMB_GOL_TOOL", "/bin/true")
    (tmp_path / "roads.osm.pbf").write_bytes(b"")

    build_gol.build(out, tmp_path / "work", (BAY,))

    assert seen["built_to_scratch"], "gol build wrote straight over the live file"
    assert seen["live_gol_intact"]
    assert out.read_bytes() == b"new build"
    assert not list(tmp_path.glob("*.building")), "scratch file left behind"

    written = json.loads(manifest_path(out).read_text())
    assert [r["slug"] for r in written["regions"]] == ["sf-bay-area"]
