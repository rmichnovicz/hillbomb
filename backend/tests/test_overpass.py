"""Unit tests for Overpass parsing — focused on bbox trimming.

Overpass returns whole ways that merely touch the bbox, dragging in nodes
outside it where we never fetched the cross streets. These tests verify that
fetch_osm_data trims ways to their contiguous in-bbox runs and drops the
out-of-bbox nodes entirely.
"""

from unittest.mock import patch

from ..overpass import _contiguous_inbbox_runs, fetch_osm_data

# south, west, north, east — a 1°×1° box at the origin's NE quadrant.
BBOX = (0.0, 0.0, 1.0, 1.0)


def test_contiguous_runs_keeps_single_inbbox_stretch():
    inside = {1, 2, 3}
    assert _contiguous_inbbox_runs([1, 2, 3, 4, 5], inside) == [[1, 2, 3]]


def test_contiguous_runs_splits_dip_out_and_back():
    # A way that exits the bbox and re-enters must split, not bridge the gap.
    inside = {1, 2, 4, 5}
    assert _contiguous_inbbox_runs([1, 2, 3, 4, 5], inside) == [[1, 2], [4, 5]]


def test_contiguous_runs_leading_and_trailing_outside():
    inside = {2, 3}
    assert _contiguous_inbbox_runs([1, 2, 3, 4], inside) == [[2, 3]]


def _node(nid, lat, lon, tags=None):
    el = {"type": "node", "id": nid, "lat": lat, "lon": lon}
    if tags:
        el["tags"] = tags
    return el


def _fetch_with_elements(elements):
    """Run fetch_osm_data against a mocked Overpass response (cache disabled)."""
    class _Resp:
        def raise_for_status(self):
            pass

        def json(self):
            return {"elements": elements}

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            return _Resp()

    with patch("backend.overpass.httpx.Client", _Client), \
         patch("backend.overpass._CACHE_TTL", 0):
        return fetch_osm_data(BBOX)


def test_fetch_trims_way_crossing_boundary():
    # Way runs from inside the bbox (n1, n2) out past the east edge (n3).
    elements = [
        _node(1, 0.5, 0.5),
        _node(2, 0.5, 0.9),
        _node(3, 0.5, 1.5),  # outside (lon > 1.0)
        {"type": "way", "id": 100, "nodes": [1, 2, 3],
         "tags": {"highway": "residential"}},
    ]
    nodes, ways = _fetch_with_elements(elements)

    assert 3 not in nodes, "out-of-bbox node must be dropped"
    assert set(nodes) == {1, 2}
    assert len(ways) == 1
    assert ways[0].node_ids == [1, 2], "way trimmed at the bbox boundary"


def test_fetch_splits_way_that_re_enters_bbox():
    elements = [
        _node(1, 0.5, 0.2),
        _node(2, 0.5, 1.5),  # outside
        _node(3, 0.5, 0.8),
        _node(4, 0.5, 0.9),
        {"type": "way", "id": 200, "nodes": [1, 2, 3, 4],
         "tags": {"highway": "residential"}},
    ]
    nodes, ways = _fetch_with_elements(elements)

    assert 2 not in nodes
    # First run [1] is too short (single node) and is dropped; [3, 4] survives.
    assert [w.node_ids for w in ways] == [[3, 4]]
