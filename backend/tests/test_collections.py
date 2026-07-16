"""
Tests for the /collections endpoints and the build script's output handling.

No network here: the pipeline half of build_collections is covered by
test_hawk_hill_e2e.py (integration). What's tested here is everything around it —
serving, the index/detail split, incremental merge, and failure reporting.
"""

import json

import pytest
from fastapi.testclient import TestClient

from .. import main
from ..scripts import build_collections as bc
from ..spots import Spot


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
        "discipline": "cycling",
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


# ── GET /collections (index) ──────────────────────────────────────────────────

def test_index_returns_empty_when_not_built(collections_file, client):
    """An un-built checkout is a normal state, not a 500."""
    resp = client.get("/collections")
    assert resp.status_code == 200
    assert resp.json() == {"version": 1, "cities": []}


def test_index_groups_spots_by_city(collections_file, client):
    collections_file.write_text(json.dumps(_doc([
        _entry(slug="hawk-hill-conzelman", city="San Francisco Bay Area"),
        _entry(slug="lookout-mountain", city="Denver"),
    ])))
    cities = client.get("/collections").json()["cities"]
    assert [c["city"] for c in cities] == ["San Francisco Bay Area", "Denver"]
    assert [s["slug"] for s in cities[0]["spots"]] == ["hawk-hill-conzelman"]


def test_index_omits_route_geometry(collections_file, client):
    """The index is fetched on tab open; route payloads are ~65 KB/spot and must not
    ride along. This is the whole reason for the two-endpoint split."""
    collections_file.write_text(json.dumps(_doc([_entry()])))
    spot = client.get("/collections").json()["cities"][0]["spots"][0]
    assert "routes" not in spot
    assert "geometry" not in spot


def test_index_summarizes_the_best_route(collections_file, client):
    collections_file.write_text(json.dumps(_doc([_entry()])))
    spot = client.get("/collections").json()["cities"][0]["spots"][0]
    assert spot["route_count"] == 1
    assert spot["top_speed_kmh"] == 84.4
    assert spot["length_m"] == 1407.6
    assert spot["total_descent_m"] == 165.8
    assert spot["flow_grade"] == "A"


def test_index_summary_uses_first_route_not_max(collections_file, client):
    """The builder sorts best-first, so the summary is routes[0] — not a re-derived max."""
    entry = _entry(routes=[_route("a", top=84.4), _route("b", top=99.9)])
    collections_file.write_text(json.dumps(_doc([entry])))
    spot = client.get("/collections").json()["cities"][0]["spots"][0]
    assert spot["top_speed_kmh"] == 84.4
    assert spot["route_count"] == 2


def test_index_handles_spot_with_no_routes(collections_file, client):
    """Shouldn't IndexError — degrade to zeroed stats."""
    collections_file.write_text(json.dumps(_doc([_entry(routes=[])])))
    spot = client.get("/collections").json()["cities"][0]["spots"][0]
    assert spot["route_count"] == 0
    assert spot["top_speed_kmh"] == 0
    assert spot["flow_grade"] == ""


def test_index_reports_corrupt_json(collections_file, client):
    collections_file.write_text("{not json")
    resp = client.get("/collections")
    assert resp.status_code == 500
    assert "corrupt" in resp.json()["detail"]
    assert "build_collections" in resp.json()["detail"], "error should say how to fix it"


# ── GET /collections/{slug} (detail) ──────────────────────────────────────────

def test_detail_returns_full_routes(collections_file, client):
    collections_file.write_text(json.dumps(_doc([_entry()])))
    spot = client.get("/collections/hawk-hill-conzelman").json()
    assert spot["slug"] == "hawk-hill-conzelman"
    assert len(spot["routes"]) == 1
    assert spot["routes"][0]["geometry"]["type"] == "LineString"
    assert spot["routes"][0]["speed_profile"]


def test_detail_404s_on_unknown_slug(collections_file, client):
    collections_file.write_text(json.dumps(_doc([_entry()])))
    assert client.get("/collections/no-such-spot").status_code == 404


def test_detail_404s_when_not_built(collections_file, client):
    assert client.get("/collections/hawk-hill-conzelman").status_code == 404


def test_detail_finds_spot_in_any_city(collections_file, client):
    collections_file.write_text(json.dumps(_doc([
        _entry(slug="hawk-hill-conzelman", city="San Francisco Bay Area"),
        _entry(slug="lookout-mountain", city="Denver"),
    ])))
    assert client.get("/collections/lookout-mountain").status_code == 200


def test_cache_is_invalidated_when_file_changes(collections_file, client):
    """A rebuild must be picked up without restarting the dev server."""
    collections_file.write_text(json.dumps(_doc([_entry(slug="one")])))
    assert client.get("/collections").json()["cities"][0]["spots"][0]["slug"] == "one"

    import os
    st = collections_file.stat()
    collections_file.write_text(json.dumps(_doc([_entry(slug="two")])))
    # Force a distinct mtime: the two writes can land in the same filesystem tick.
    os.utime(collections_file, (st.st_atime, st.st_mtime + 10))

    assert client.get("/collections").json()["cities"][0]["spots"][0]["slug"] == "two"


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
