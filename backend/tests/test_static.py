"""
Tests for serving the built SPA out of the API process (see the static block at the
bottom of main.py).

The block only registers when the static directory exists at import time, so these
tests reload the module with HILLBOMB_STATIC_DIR pointed at a fixture tree, then
reload it back so the rest of the suite sees the normal API-only app.
"""

import importlib

import pytest
from fastapi.testclient import TestClient

from .. import main as main_module


@pytest.fixture
def static_client(tmp_path, monkeypatch):
    dist = tmp_path / "dist"
    (dist / "assets").mkdir(parents=True)
    (dist / "index.html").write_text("<!doctype html><title>hillbomb</title>")
    (dist / "assets" / "index-abc123.js").write_text("console.log(1)")
    (dist / "favicon.svg").write_text("<svg/>")
    # A file OUTSIDE the static root, as a traversal target.
    (tmp_path / "secret.txt").write_text("TOP SECRET")

    monkeypatch.setenv("HILLBOMB_STATIC_DIR", str(dist))
    reloaded = importlib.reload(main_module)
    try:
        with TestClient(reloaded.app) as client:
            yield client
    finally:
        monkeypatch.delenv("HILLBOMB_STATIC_DIR", raising=False)
        importlib.reload(main_module)


def test_serves_the_spa_shell_at_root(static_client):
    resp = static_client.get("/")
    assert resp.status_code == 200
    assert "hillbomb" in resp.text


def test_unknown_path_falls_back_to_the_shell(static_client):
    """Deep links are client-side routes; a 404 here would break every shared URL."""
    resp = static_client.get("/some/deep/link")
    assert resp.status_code == 200
    assert "hillbomb" in resp.text


def test_index_is_not_cached(static_client):
    """index.html names the content-hashed bundles. A cached copy pointing at
    bundles a new deploy has replaced is exactly how you get a blank page."""
    assert static_client.get("/").headers["cache-control"] == "no-store"


def test_real_files_are_served(static_client):
    assert static_client.get("/favicon.svg").status_code == 200
    assert static_client.get("/assets/index-abc123.js").text == "console.log(1)"


def test_hashed_assets_are_cacheable(static_client):
    """Assets must NOT inherit index.html's no-store, or every load refetches 1.5 MB."""
    resp = static_client.get("/assets/index-abc123.js")
    assert resp.headers.get("cache-control") != "no-store"
    assert "etag" in resp.headers


@pytest.mark.parametrize("path", [
    "/../secret.txt",
    "/..%2fsecret.txt",
    "/assets/../../secret.txt",
    "/%2e%2e/secret.txt",
])
def test_path_traversal_cannot_escape_the_static_root(static_client, path):
    """full_path is attacker-controlled and is joined onto a filesystem path."""
    resp = static_client.get(path)
    assert "TOP SECRET" not in resp.text


def test_api_routes_still_win_over_the_spa_catch_all(static_client):
    """The catch-all is registered last precisely so it cannot shadow the API."""
    assert static_client.get("/collections/index.json").status_code == 200
    assert static_client.get("/healthz").json() == {"status": "ok"}
    # An unknown collection must 404 as JSON, not fall through to the SPA shell.
    resp = static_client.get("/collections/definitely-not-a-spot.json")
    assert resp.status_code == 404


def test_healthz_is_also_served_under_api(static_client):
    """Cloud Run's frontend answers a bare /healthz itself with a Google 404 page, so
    that path never reaches the container from outside. External probes must have a
    path that does. Verified against the live service."""
    assert static_client.get("/api/healthz").json() == {"status": "ok"}


def test_healthz_does_no_io():
    """A liveness probe that depends on Overpass or S3 reports a healthy container
    as unhealthy whenever an upstream has a bad day."""
    with TestClient(main_module.app) as client:
        assert client.get("/healthz").json() == {"status": "ok"}
        assert client.get("/api/healthz").json() == {"status": "ok"}
