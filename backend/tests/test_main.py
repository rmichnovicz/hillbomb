"""
Tests for main.py — FastAPI SSE search endpoint.

Strategy: mock the expensive pipeline stages (network I/O, graph build, pathfinding)
so tests run in-process without hitting external APIs. We're testing:
  - HTTP contract (content-type, status codes, validation)
  - SSE event stream structure and ordering
  - That each pipeline stage produces the right event types
  - Error handling (invalid input → 422; pipeline error → error event)
"""

import json
from unittest.mock import MagicMock, patch
import networkx as nx
import pytest
from fastapi.testclient import TestClient

from ..elevation import ElevationService
from ..main import app
from ..types import OSMNode, OSMWay, Route

# ── Canned test data ──────────────────────────────────────────────────────────

_BBOX = [37.748, -122.454, 37.758, -122.440]

_NODES = {
    1: OSMNode(id=1, lat=37.750, lon=-122.450, elevation=120.0),
    2: OSMNode(id=2, lat=37.751, lon=-122.449, elevation=110.0),
    3: OSMNode(id=3, lat=37.752, lon=-122.448, elevation=100.0),
}

_WAYS = [
    OSMWay(id=101, node_ids=[1, 2, 3], highway="residential",
           oneway=False, oneway_reverse=False, surface="asphalt", name="Test Street"),
]


def _make_route(route_id: str = "r1", name: str = "Test Street") -> Route:
    return Route(
        route_id=route_id,
        node_ids=[1, 2, 3],
        coordinates=[[-122.450, 37.750], [-122.449, 37.751], [-122.448, 37.752]],
        elevations=[120.0, 110.0, 100.0],
        segment_distances=[130.0, 130.0],
        primary_highway="residential",
        name=name,
        length_m=260.0,
        total_descent_m=20.0,
        avg_grade_pct=-7.7,
    )


def _make_graph() -> nx.DiGraph:
    G = nx.DiGraph()
    for nid, n in _NODES.items():
        G.add_node(nid, lat=n.lat, lon=n.lon, elevation=n.elevation,
                   is_traffic_signal=False, is_stop_sign=False,
                   is_peak=(nid == 1), is_valley=(nid == 3))
    G.add_edge(1, 2, distance_m=130.0, grade=-0.077, highway="residential",
               hw_rank=3, surface="asphalt", is_bridge=False, is_tunnel=False,
               way_name="Test Street")
    G.add_edge(2, 3, distance_m=130.0, grade=-0.077, highway="residential",
               hw_rank=3, surface="asphalt", is_bridge=False, is_tunnel=False,
               way_name="Test Street")
    return G


# ── SSE parsing helpers ───────────────────────────────────────────────────────

def _parse_sse(body: bytes) -> list[dict]:
    """Parse SSE body into a list of event dicts."""
    events = []
    for line in body.decode().splitlines():
        line = line.strip()
        if line.startswith("data:"):
            payload = line[len("data:"):].strip()
            if payload:
                events.append(json.loads(payload))
    return events


@pytest.fixture
def client():
    """TestClient with ElevationService mocked out (suppresses startup HTTP call)."""
    mock_svc = MagicMock(spec=ElevationService)
    mock_svc.get_elevations.side_effect = (
        lambda coords, should_cancel=None, cache_coords=None: [110.0] * len(coords)
    )
    mock_svc.resolution_m = 10.0
    with patch("backend.main.ElevationService", return_value=mock_svc):
        with TestClient(app, raise_server_exceptions=False) as c:
            yield c


def _request_body(**overrides) -> dict:
    base = {"bbox": _BBOX}
    base.update(overrides)
    return base


# ── Patch helpers ─────────────────────────────────────────────────────────────

# ── HTTP contract ─────────────────────────────────────────────────────────────

def test_search_returns_200(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([_make_route()]))):
        resp = client.post("/search", json=_request_body())
    assert resp.status_code == 200


def test_search_content_type_is_event_stream(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([]))):
        resp = client.post("/search", json=_request_body())
    assert "text/event-stream" in resp.headers["content-type"]


def test_search_missing_bbox_returns_422(client):
    resp = client.post("/search", json={})
    assert resp.status_code == 422


def test_search_bbox_wrong_length_returns_422(client):
    resp = client.post("/search", json={"bbox": [1.0, 2.0, 3.0]})
    assert resp.status_code == 422


def test_search_unknown_rider_profile_returns_400(client):
    resp = client.post("/search", json=_request_body(rider_profile="unicorn"))
    assert resp.status_code == 400


# ── SSE event ordering and structure ─────────────────────────────────────────

def test_done_event_is_last(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([_make_route()]))):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    assert events, "Expected at least one event"
    assert events[-1]["type"] == "done"


def test_status_events_emitted_before_routes(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([_make_route()]))):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    types = [e["type"] for e in events]
    # At least one status event must appear before the first route event
    first_route = next((i for i, t in enumerate(types) if t == "route"), len(types))
    status_before_route = [t for t in types[:first_route] if t == "status"]
    assert status_before_route, "Expected status events before first route"


def test_route_event_has_required_fields(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([_make_route()]))):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    route_events = [e for e in events if e["type"] == "route"]
    assert route_events, "Expected at least one route event"
    r = route_events[0]
    for field in ("route_id", "geometry", "metadata", "flow_score", "flow_grade",
                  "speed_profile", "top_speed_kmh", "avg_speed_kmh"):
        assert field in r, f"Missing field '{field}' in route event"


def test_route_geometry_is_linestring(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([_make_route()]))):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    route_event = next(e for e in events if e["type"] == "route")
    assert route_event["geometry"]["type"] == "LineString"
    assert isinstance(route_event["geometry"]["coordinates"], list)


def test_route_event_includes_physics_fields(client):
    """Physics is now embedded in the route event — no separate physics event."""
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([_make_route()]))):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    assert not any(e["type"] == "physics" for e in events), "Separate physics events should not exist"
    route_event = next(e for e in events if e["type"] == "route")
    assert isinstance(route_event["speed_profile"], list)
    assert route_event["top_speed_kmh"] >= 0
    assert route_event["avg_speed_kmh"] >= 0


def test_multiple_routes_each_have_physics(client):
    G = _make_graph()
    routes = [_make_route(f"r{i}", f"Street {i}") for i in range(3)]
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter(routes))):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    route_events = [e for e in events if e["type"] == "route"]
    # Dedup may reduce count (all 3 share the same nodes), so just check all have physics
    for r in route_events:
        assert "speed_profile" in r
        assert "top_speed_kmh" in r


def test_no_routes_still_emits_done(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([]))):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    assert any(e["type"] == "done" for e in events)


# ── Pipeline error handling ───────────────────────────────────────────────────

def test_overpass_failure_emits_error_event(client):
    with patch("backend.main.fetch_osm_data", side_effect=RuntimeError("Overpass down")):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    error_events = [e for e in events if e["type"] == "error"]
    assert error_events, "Expected an error event on pipeline failure"
    assert "message" in error_events[0]


def test_error_event_followed_by_no_done(client):
    """On fatal error, we do NOT emit done — frontend should detect the error event."""
    with patch("backend.main.fetch_osm_data", side_effect=RuntimeError("boom")):
        resp = client.post("/search", json=_request_body())
    events = _parse_sse(resp.content)
    types = [e["type"] for e in events]
    assert "error" in types
    assert "done" not in types


# ── Request options ───────────────────────────────────────────────────────────

def test_custom_rider_profile_accepted(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([]))):
        resp = client.post("/search", json=_request_body(rider_profile="longboarder"))
    assert resp.status_code == 200


def test_custom_road_types_accepted(client):
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([]))):
        resp = client.post("/search", json=_request_body(road_types=["residential", "tertiary"]))
    assert resp.status_code == 200


def test_toggles_passed_through(client):
    """Toggles in request should flow into find_routes call."""
    G = _make_graph()
    with (patch("backend.main.fetch_osm_data", return_value=(_NODES, _WAYS)),
          patch("backend.main.build_graph", return_value=G),
          patch("backend.main.find_routes", return_value=iter([])) as mock_find):
        client.post("/search", json=_request_body(
            toggles={"avoid_stoplights": False, "exclude_tunnels": True}
        ))
        _, kwargs = mock_find.call_args
        # find_routes(G, nodes, config, params, toggles) — toggles is positional index 4
        toggles_arg = kwargs.get("toggles") or mock_find.call_args[0][4]
        assert toggles_arg.avoid_stoplights is False
        assert toggles_arg.exclude_tunnels is True
