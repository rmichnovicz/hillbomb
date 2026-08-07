"""
Tests for the /collections/*.json endpoints and the build script's output handling.

No network here: the pipeline half of build_collections is covered by
test_hawk_hill_e2e.py (integration). What's tested here is everything around it —
serving, the index/detail split, incremental merge, and failure reporting.
"""

import json

import pytest
from fastapi.testclient import TestClient

from pathlib import Path

from .. import main
from ..config import DISCIPLINES
from ..pipeline import route_payload
from ..scripts import build_collections as bc
from ..scripts.export_static_collections import export
from ..spots import SPOTS, Spot
from ..types import Route


def _route(route_id="r1", name="Conzelman Road", top=84.4, length=1407.6, drop=165.8):
    return {
        "route_id": route_id,
        "start_node_id": 42,
        "geometry": {"type": "LineString", "coordinates": [[-122.49, 37.83], [-122.48, 37.82]]},
        "metadata": {
            "name": name, "length_m": length, "total_descent_m": drop,
            "avg_grade_pct": -11.8, "primary_highway": "secondary",
        },
        "elevations": [180.0, 14.2],
        "segment_distances": [1407.6],
        "flow_score": 100.0,
        "flow_grade": "A",
        "surface_pcts": {"paved": 100.0},
        "stops": [],
        "speed_profile": [20.0, 84.4],
        "top_speed_kmh": top,
        "avg_speed_kmh": 52.0,
    }


def _entry(slug="hawk-hill-conzelman", city="San Francisco Bay Area", routes=None):
    return {
        "slug": slug,
        "name": "Hawk Hill (Conzelman Road)",
        "city": city,
        "state": "CA",
        "blurb": "The classic Marin Headlands descent.",
        "disciplines": ["road"],
        "notes": "Often busy with tourists.",
        "confidence": "high",
        "bbox": [37.820, -122.515, 37.845, -122.470],
        "center": [-122.4925, 37.8325],
        "rider_profile": "cyclist_upright",
        "built_at": "2026-07-16T00:00:00+00:00",
        "routes": routes if routes is not None else [_route()],
    }


def _doc(entries):
    """Wrap entries into the on-disk document, grouped by city."""
    cities: list[dict] = []
    for e in entries:
        city = next((c for c in cities if c["city"] == e["city"]), None)
        if city is None:
            city = {"city": e["city"], "spots": []}
            cities.append(city)
        city["spots"].append(e)
    return {"version": 1, "cities": cities}


@pytest.fixture
def collections_file(tmp_path, monkeypatch):
    """Point the app at a temp collections.json and clear its mtime cache."""
    path = tmp_path / "collections.json"
    monkeypatch.setattr(main, "COLLECTIONS_PATH", path)
    monkeypatch.setattr(main, "_collections_cache", None)
    return path


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


# ── GET /collections/index.json ──────────────────────────────────────────────────

def test_index_returns_empty_when_not_built(collections_file, client):
    """An un-built checkout is a normal state, not a 500."""
    resp = client.get("/collections/index.json")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "cities": []}


def test_index_groups_spots_by_city(collections_file, client):
    collections_file.write_text(json.dumps(_doc([
        _entry(slug="hawk-hill-conzelman", city="San Francisco Bay Area"),
        _entry(slug="lookout-mountain", city="Denver"),
    ])))
    cities = client.get("/collections/index.json").json()["cities"]
    assert [c["city"] for c in cities] == ["San Francisco Bay Area", "Denver"]
    assert [s["slug"] for s in cities[0]["spots"]] == ["hawk-hill-conzelman"]


def test_index_omits_route_geometry(collections_file, client):
    """The index is fetched on tab open; route payloads are ~65 KB/spot and must not
    ride along. This is the whole reason for the two-endpoint split."""
    collections_file.write_text(json.dumps(_doc([_entry()])))
    spot = client.get("/collections/index.json").json()["cities"][0]["spots"][0]
    assert "routes" not in spot
    assert "geometry" not in spot


def test_index_summarizes_the_best_route(collections_file, client):
    collections_file.write_text(json.dumps(_doc([_entry()])))
    spot = client.get("/collections/index.json").json()["cities"][0]["spots"][0]
    assert spot["route_count"] == 1
    assert spot["top_speed_kmh"] == 84.4
    assert spot["length_m"] == 1407.6
    assert spot["total_descent_m"] == 165.8
    assert spot["flow_grade"] == "A"


def test_index_summary_uses_first_route_not_max(collections_file, client):
    """The builder sorts best-first, so the summary is routes[0] — not a re-derived max."""
    entry = _entry(routes=[_route("a", top=84.4), _route("b", top=99.9)])
    collections_file.write_text(json.dumps(_doc([entry])))
    spot = client.get("/collections/index.json").json()["cities"][0]["spots"][0]
    assert spot["top_speed_kmh"] == 84.4
    assert spot["route_count"] == 2


def test_index_handles_spot_with_no_routes(collections_file, client):
    """Shouldn't IndexError — degrade to zeroed stats."""
    collections_file.write_text(json.dumps(_doc([_entry(routes=[])])))
    spot = client.get("/collections/index.json").json()["cities"][0]["spots"][0]
    assert spot["route_count"] == 0
    assert spot["top_speed_kmh"] == 0
    assert spot["flow_grade"] == ""


def test_index_reports_corrupt_json(collections_file, client):
    collections_file.write_text("{not json")
    resp = client.get("/collections/index.json")
    assert resp.status_code == 500
    assert "corrupt" in resp.json()["detail"]
    assert "build_collections" in resp.json()["detail"], "error should say how to fix it"


# ── GET /collections/{slug}.json (detail) ──────────────────────────────────────────

def test_detail_returns_full_routes(collections_file, client):
    collections_file.write_text(json.dumps(_doc([_entry()])))
    spot = client.get("/collections/hawk-hill-conzelman.json").json()
    assert spot["slug"] == "hawk-hill-conzelman"
    assert len(spot["routes"]) == 1
    assert spot["routes"][0]["geometry"]["type"] == "LineString"
    assert spot["routes"][0]["speed_profile"]


def test_detail_404s_on_unknown_slug(collections_file, client):
    collections_file.write_text(json.dumps(_doc([_entry()])))
    assert client.get("/collections/no-such-spot.json").status_code == 404


def test_detail_404s_when_not_built(collections_file, client):
    assert client.get("/collections/hawk-hill-conzelman.json").status_code == 404


def test_detail_finds_spot_in_any_city(collections_file, client):
    collections_file.write_text(json.dumps(_doc([
        _entry(slug="hawk-hill-conzelman", city="San Francisco Bay Area"),
        _entry(slug="lookout-mountain", city="Denver"),
    ])))
    assert client.get("/collections/lookout-mountain.json").status_code == 200


def test_cache_is_invalidated_when_file_changes(collections_file, client):
    """A rebuild must be picked up without restarting the dev server."""
    collections_file.write_text(json.dumps(_doc([_entry(slug="one")])))
    assert client.get("/collections/index.json").json()["cities"][0]["spots"][0]["slug"] == "one"

    import os
    st = collections_file.stat()
    collections_file.write_text(json.dumps(_doc([_entry(slug="two")])))
    # Force a distinct mtime: the two writes can land in the same filesystem tick.
    os.utime(collections_file, (st.st_atime, st.st_mtime + 10))

    assert client.get("/collections/index.json").json()["cities"][0]["spots"][0]["slug"] == "two"


# ── Build script output handling ──────────────────────────────────────────────

@pytest.fixture
def out_path(tmp_path, monkeypatch):
    path = tmp_path / "collections.json"
    monkeypatch.setattr(bc, "OUT_PATH", path)
    return path


def _spot(slug, city="San Francisco Bay Area"):
    return Spot(
        slug=slug, name=slug, city=city, state="CA",
        bbox=(37.82, -122.52, 37.85, -122.47),
        osm_way_names=("Conzelman",), blurb="b",
    )


def test_write_output_groups_by_city_in_spots_order(out_path, monkeypatch):
    monkeypatch.setattr(bc, "SPOTS", [_spot("a"), _spot("z", "Denver"), _spot("b")])
    bc.write_output({
        "b": _entry(slug="b"), "z": _entry(slug="z", city="Denver"), "a": _entry(slug="a"),
    })
    doc = json.loads(out_path.read_text())
    # Cities appear in first-seen SPOTS order, and spots within a city keep SPOTS order —
    # so rebuilding one spot never reshuffles the committed file.
    assert [c["city"] for c in doc["cities"]] == ["San Francisco Bay Area", "Denver"]
    assert [s["slug"] for s in doc["cities"][0]["spots"]] == ["a", "b"]


def test_write_output_drops_entries_for_deleted_spots(out_path, monkeypatch):
    monkeypatch.setattr(bc, "SPOTS", [_spot("a")])
    bc.write_output({"a": _entry(slug="a"), "removed": _entry(slug="removed")})
    doc = json.loads(out_path.read_text())
    assert [s["slug"] for s in doc["cities"][0]["spots"]] == ["a"]


def test_load_existing_round_trips(out_path, monkeypatch):
    monkeypatch.setattr(bc, "SPOTS", [_spot("a"), _spot("b")])
    bc.write_output({"a": _entry(slug="a"), "b": _entry(slug="b")})
    assert set(bc.load_existing()) == {"a", "b"}


def test_load_existing_is_empty_when_missing(out_path):
    assert bc.load_existing() == {}


def test_load_existing_survives_corrupt_file(out_path, capsys):
    """A corrupt file must not brick the builder — warn and start fresh."""
    out_path.write_text("{not json")
    assert bc.load_existing() == {}
    assert "not valid JSON" in capsys.readouterr().err


# ── --metadata-only refresh ───────────────────────────────────────────────────
#
# The point of this path is that a copy edit costs nothing: text gets re-stamped from
# SPOTS, and the expensive part of the entry — the routes — is not just preserved but
# never recomputed. These tests pin both halves of that bargain.

def _refresh_spot(slug="hawk-hill-conzelman", **overrides):
    """A Spot matching `_entry()`'s pipeline inputs, so nothing warns unless asked."""
    fields = dict(
        slug=slug, name="Hawk Hill (Conzelman Road)", city="San Francisco Bay Area",
        state="CA", bbox=(37.820, -122.515, 37.845, -122.470),
        osm_way_names=("Conzelman",), blurb="The classic Marin Headlands descent.",
        disciplines=("road",), notes="Often busy with tourists.", confidence="high",
    )
    return Spot(**{**fields, **overrides})


def test_refresh_metadata_restamps_changed_text():
    entries = {"hawk-hill-conzelman": _entry()}
    unbuilt = bc.refresh_metadata([_refresh_spot(blurb="Switchbacks down to the bridge.")], entries)
    assert unbuilt == []
    assert entries["hawk-hill-conzelman"]["blurb"] == "Switchbacks down to the bridge."


def test_refresh_metadata_leaves_routes_and_build_stamp_alone():
    """The whole justification for this flag: no pipeline run, so no route churn."""
    entries = {"hawk-hill-conzelman": _entry()}
    before_routes = json.dumps(entries["hawk-hill-conzelman"]["routes"])
    bc.refresh_metadata([_refresh_spot(blurb="new copy")], entries)
    entry = entries["hawk-hill-conzelman"]
    assert json.dumps(entry["routes"]) == before_routes
    assert entry["built_at"] == "2026-07-16T00:00:00+00:00"


def test_refresh_metadata_reports_spots_that_were_never_built():
    """Refreshing can't invent an entry — a new spot still needs a real build."""
    entries = {"hawk-hill-conzelman": _entry()}
    unbuilt = bc.refresh_metadata([_refresh_spot(), _refresh_spot("brand-new")], entries)
    assert unbuilt == ["brand-new"]


@pytest.mark.parametrize("field,value", [
    ("bbox", (37.0, -122.9, 37.1, -122.8)),
    ("rider_profile", "longboarder"),
])
def test_refresh_metadata_warns_when_pipeline_inputs_drifted(capsys, field, value):
    """Text is still safe to refresh, but the routes no longer answer the current question."""
    entries = {"hawk-hill-conzelman": _entry()}
    bc.refresh_metadata([_refresh_spot(**{field: value})], entries)
    err = capsys.readouterr().err
    assert f"hawk-hill-conzelman.{field} changed" in err
    assert "--metadata-only" in err


def test_refresh_metadata_is_quiet_when_nothing_changed(capsys):
    entries = {"hawk-hill-conzelman": _entry()}
    bc.refresh_metadata([_refresh_spot()], entries)
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


def test_matches_spot_is_case_insensitive_substring():
    spot = _spot("x")
    assert bc._matches_spot("Conzelman Road", spot)
    assert bc._matches_spot("conzelman road", spot)
    assert not bc._matches_spot("Lincoln Boulevard", spot)


def test_matches_spot_checks_every_listed_name():
    spot = Spot(
        slug="x", name="x", city="c", state="CA", bbox=(37.8, -122.5, 37.9, -122.4),
        osm_way_names=("Panoramic Highway", "Ridgecrest"), blurb="b",
    )
    assert bc._matches_spot("Ridgecrest Boulevard", spot)
    assert not bc._matches_spot("Bolinas Road", spot)


# ── Route selection ───────────────────────────────────────────────────────────

class _R:
    """Just enough of a Route for _keep_best, which only reads total_descent_m."""

    def __init__(self, descent_m: float) -> None:
        self.total_descent_m = descent_m


def test_keep_best_caps_at_max_routes():
    kept = bc._keep_best([_R(400), _R(300), _R(200), _R(150)], max_routes=2)
    assert [r.total_descent_m for r in kept] == [400, 300]


def test_keep_best_drops_routes_far_below_the_headline():
    """A leftover stub on a one-road spot shouldn't ride along on rank alone."""
    kept = bc._keep_best([_R(400), _R(300), _R(40), _R(0)], max_routes=4)
    assert [r.total_descent_m for r in kept] == [400, 300], (
        "40 m is under 25% of the 400 m headline; 0 m is not a descent at all"
    )


def test_keep_best_applies_an_absolute_floor_on_small_spots():
    """On a short street bomb the relative floor is tiny, so the absolute one binds."""
    kept = bc._keep_best([_R(32), _R(20), _R(9)], max_routes=4)
    assert [r.total_descent_m for r in kept] == [32, 20], "9 m is below MIN_DESCENT_M"


def test_keep_best_always_keeps_the_headline_route():
    """Even a weak best route is the spot's headline — an empty spot is a build failure."""
    kept = bc._keep_best([_R(3), _R(1)], max_routes=4)
    assert [r.total_descent_m for r in kept] == [3]


# ── The committed build output ────────────────────────────────────────────────
#
# Everything above runs against fixtures. These run against the real
# backend/data/collections.json, because that file is committed and served
# verbatim — a fixture passing says nothing about what /collections actually
# returns.

_BUILT = Path(__file__).resolve().parents[1] / "data" / "collections.json"


def _built_doc() -> dict:
    if not _BUILT.exists():
        pytest.skip(f"{_BUILT} has not been built")
    return json.loads(_BUILT.read_text())


def _built_routes():
    return [
        (spot["slug"], route)
        for city in _built_doc().get("cities", [])
        for spot in city["spots"]
        for route in spot["routes"]
    ]


def test_committed_routes_match_the_current_wire_shape():
    """Guards the case that actually happened: a field added to route_payload()
    reaches new spots and silently leaves every previously-built route without it.

    46 of 73 routes shipped missing `trail_difficulty` this way — valid JSON,
    passing fixtures, and a required field absent at runtime for two thirds of the
    Collections tab. Rebuild with `python -m backend.scripts.build_collections`.
    """
    expected = set(route_payload(_reference_route()))
    stale = {slug for slug, route in _built_routes() if set(route) != expected}
    assert not stale, (
        f"{len(stale)} spot(s) were built against an older route shape: {sorted(stale)}. "
        f"Re-run the collections build."
    )


def test_committed_spots_cover_every_spot_in_spots_py():
    """A spot in SPOTS with no entry here is invisible in the UI."""
    built = {slug for slug, _ in _built_routes()}
    missing = {s.slug for s in SPOTS} - built
    assert not missing, f"Never built (or built with zero routes): {sorted(missing)}"


def test_committed_disciplines_are_in_the_vocabulary():
    for city in _built_doc().get("cities", []):
        for spot in city["spots"]:
            unknown = set(spot["disciplines"]) - set(DISCIPLINES)
            assert not unknown, f"{spot['slug']}: unknown discipline(s) {unknown}"


# ── The static export ─────────────────────────────────────────────────────────
#
# In production these URLs are served twice over: as flat files on the CDN, and by
# main.py from the same doc. Every environment below production uses the FastAPI
# path, so a divergence between the two is invisible until it ships — which makes
# this the only place it can be caught.


def _built_slugs() -> list[str]:
    return [
        spot["slug"]
        for city in _built_doc().get("cities", [])
        for spot in city["spots"]
    ]


def test_static_export_matches_the_api(tmp_path, client):
    """The CDN and FastAPI must answer the same URL with the same JSON.

    Not a formality: the index is *computed* from the doc rather than stored in it,
    so it has a real chance to drift. Both sides go through pipeline.collections_index
    precisely so they can't, and this asserts that stays true.
    """
    export(_built_doc(), tmp_path)

    assert json.loads((tmp_path / "index.json").read_text()) == \
        client.get("/collections/index.json").json()

    for slug in _built_slugs():
        assert json.loads((tmp_path / f"{slug}.json").read_text()) == \
            client.get(f"/collections/{slug}.json").json(), \
            f"{slug}.json on the CDN would differ from /collections/{slug}.json"


def test_static_export_writes_a_file_for_every_spot_in_the_index(tmp_path):
    """A spot listed in the index with no file behind it is a 404 on the CDN — the
    card renders, opening it fails. Nothing upstream of deploy would notice."""
    export(_built_doc(), tmp_path)

    listed = {
        spot["slug"]
        for city in json.loads((tmp_path / "index.json").read_text())["cities"]
        for spot in city["spots"]
    }
    on_disk = {p.stem for p in tmp_path.glob("*.json")} - {"index"}
    assert listed == on_disk


def test_static_export_index_carries_no_geometry(tmp_path):
    """The index is fetched on tab open by every visitor; the corpus is ~2.3 MB and
    the index must stay a rounding error against it. Geometry leaking in is the way
    that stops being true."""
    export(_built_doc(), tmp_path)
    index_text = (tmp_path / "index.json").read_text()

    assert "coordinates" not in index_text
    assert "speed_profile" not in index_text
    index_kb = len(index_text.encode()) / 1000
    assert index_kb < 250, f"index.json has grown to {index_kb:.0f} KB"


def _reference_route() -> Route:
    """A minimal Route, purely to enumerate route_payload()'s keys."""
    return Route(
        route_id="ref",
        node_ids=[1, 2],
        coordinates=[[-122.45, 37.75], [-122.44, 37.76]],
        elevations=[100.0, 90.0],
        segment_distances=[100.0],
        primary_highway="residential",
    )


def test_report_output_counts_only_what_was_written(capsys, monkeypatch):
    """Deleting a spot from SPOTS leaves a stale entry in `entries` that write_output
    drops — the summary must not count it. It reported 46 spots for a 45-spot file."""
    spot = Spot(
        slug="kept", name="Kept", city="Somewhere", state="CA",
        bbox=(37.0, -122.0, 37.1, -121.9), osm_way_names=("Kept Road",), blurb="b",
    )
    monkeypatch.setattr(bc, "SPOTS", [spot])
    entries = {
        "kept": {"slug": "kept", "routes": [{}, {}]},
        "deleted-from-spots-py": {"slug": "deleted-from-spots-py", "routes": [{}, {}, {}]},
    }
    bc._report_output(entries)
    out = capsys.readouterr().out
    assert "1 spot(s)" in out, out
    assert "2 route(s)" in out, out
