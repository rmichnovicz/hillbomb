"""Unit tests for Overpass parsing — focused on bbox trimming.

Overpass returns whole ways that merely touch the bbox, dragging in nodes
outside it where we never fetched the cross streets. These tests verify that
fetch_osm_data trims ways to their contiguous in-bbox runs and drops the
out-of-bbox nodes entirely.
"""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from ..overpass import (
    ROAD_NETWORK_TYPES,
    _contiguous_inbbox_runs,
    _overpass_cache_path,
    _parse_trail_difficulty,
    fetch_osm_data,
)

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
        status_code = 200
        headers: dict = {}

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


# ── Rate-limit backoff ────────────────────────────────────────────────────────
#
# Overpass sheds load with 429 (rate limited) and 504 (slot timeout). Both are
# transient. The collections builder fetches ~24 bboxes back to back and hits this
# every time without a retry, so the backoff is load-bearing, not decorative.


class _FakeResp:
    def __init__(self, status_code, headers=None, elements=None):
        self.status_code = status_code
        self.headers = headers or {}
        self._elements = elements or []

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=MagicMock(), response=MagicMock()
            )

    def json(self):
        return {"elements": self._elements}


def _client_returning(responses):
    """An httpx.Client stand-in that yields `responses` in order, recording calls."""
    calls = []

    class _Client:
        def __init__(self, *a, **k):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def post(self, *a, **k):
            calls.append(1)
            resp = responses[len(calls) - 1]
            # An Exception entry simulates a transport-level failure (connection
            # refused, DNS, read timeout) rather than an HTTP status response.
            if isinstance(resp, Exception):
                raise resp
            return resp

    return _Client, calls


def _fetch_with_responses(responses):
    client_cls, calls = _client_returning(responses)
    with patch("backend.overpass.httpx.Client", client_cls), \
         patch("backend.overpass._CACHE_TTL", 0), \
         patch("backend.overpass.time.sleep") as slept:
        result = fetch_osm_data(BBOX)
    return result, calls, slept


def test_retries_on_429_then_succeeds():
    responses = [_FakeResp(429), _FakeResp(200, elements=[])]
    (nodes, ways), calls, slept = _fetch_with_responses(responses)
    assert len(calls) == 2, "should have retried after the 429"
    assert nodes == {} and ways == []
    slept.assert_called_once()


def test_retries_on_504():
    """504 is a slot timeout, not a permanent failure."""
    _, calls, _ = _fetch_with_responses([_FakeResp(504), _FakeResp(200, elements=[])])
    assert len(calls) == 2


def test_does_not_retry_on_400():
    """A malformed query is our bug — retrying just wastes Overpass's time."""
    client_cls, calls = _client_returning([_FakeResp(400)])
    with patch("backend.overpass.httpx.Client", client_cls), \
         patch("backend.overpass._CACHE_TTL", 0), \
         patch("backend.overpass.time.sleep"):
        with pytest.raises(httpx.HTTPStatusError):
            fetch_osm_data(BBOX)
    assert len(calls) == 1


def test_raises_after_exhausting_attempts():
    """Give up eventually rather than hanging forever — and surface the real error."""
    client_cls, calls = _client_returning([_FakeResp(429)] * 4)
    with patch("backend.overpass.httpx.Client", client_cls), \
         patch("backend.overpass._CACHE_TTL", 0), \
         patch("backend.overpass._MAX_ATTEMPTS", 4), \
         patch("backend.overpass.time.sleep"):
        with pytest.raises(httpx.HTTPStatusError):
            fetch_osm_data(BBOX)
    assert len(calls) == 4


def test_backoff_is_exponential():
    responses = [_FakeResp(429), _FakeResp(429), _FakeResp(200, elements=[])]
    with patch("backend.overpass._BACKOFF_BASE_S", 5.0):
        _, _, slept = _fetch_with_responses(responses)
    assert [c.args[0] for c in slept.call_args_list] == [5.0, 10.0]


def test_honors_retry_after_header():
    """Overpass tells us when to come back; obey it instead of guessing."""
    responses = [_FakeResp(429, headers={"Retry-After": "42"}), _FakeResp(200, elements=[])]
    _, _, slept = _fetch_with_responses(responses)
    assert slept.call_args_list[0].args[0] == 42.0


def test_falls_back_to_backoff_on_unparseable_retry_after():
    """The HTTP-date form is legal; don't crash on it."""
    responses = [
        _FakeResp(429, headers={"Retry-After": "Wed, 21 Oct 2026 07:28:00 GMT"}),
        _FakeResp(200, elements=[]),
    ]
    with patch("backend.overpass._BACKOFF_BASE_S", 5.0):
        _, _, slept = _fetch_with_responses(responses)
    assert slept.call_args_list[0].args[0] == 5.0


# ── Retry notifications ───────────────────────────────────────────────────────
#
# The frontend shows these as status text. Without them an Overpass outage is up
# to ~35 s of silent spinner, which reads as "the app is broken" rather than
# "the upstream is down and we're waiting".

def _fetch_capturing_retries(responses, max_attempts=4):
    seen = []
    client_cls, calls = _client_returning(responses)
    with patch("backend.overpass.httpx.Client", client_cls), \
         patch("backend.overpass._CACHE_TTL", 0), \
         patch("backend.overpass._MAX_ATTEMPTS", max_attempts), \
         patch("backend.overpass._BACKOFF_BASE_S", 5.0), \
         patch("backend.overpass.time.sleep"):
        result = fetch_osm_data(BBOX, on_retry=lambda *a: seen.append(a))
    return result, seen, calls


def test_on_retry_reports_status_attempt_and_delay():
    _, seen, _ = _fetch_capturing_retries([_FakeResp(429), _FakeResp(200, elements=[])])
    assert seen == [("429", 1, 4, 5.0)]


def test_on_retry_fires_once_per_retry_with_growing_delay():
    responses = [_FakeResp(429), _FakeResp(504), _FakeResp(200, elements=[])]
    _, seen, _ = _fetch_capturing_retries(responses)
    assert [(s[0], s[3]) for s in seen] == [("429", 5.0), ("504", 10.0)]


def test_on_retry_not_called_when_first_attempt_succeeds():
    _, seen, _ = _fetch_capturing_retries([_FakeResp(200, elements=[])])
    assert seen == []


def test_transport_error_is_retried_and_reported():
    """A real outage is a connection error, not a 429.

    Retrying only on status codes meant the one case this message exists for --
    Overpass being genuinely unreachable -- failed instantly with no retry and no
    notification.
    """
    responses = [httpx.ConnectError("connection refused"), _FakeResp(200, elements=[])]
    _, seen, calls = _fetch_capturing_retries(responses)
    assert len(calls) == 2, "should have retried after the transport error"
    assert seen == [("ConnectError", 1, 4, 5.0)]


def test_transport_error_still_raises_once_attempts_exhausted():
    responses = [httpx.ConnectError("refused")] * 3
    client_cls, calls = _client_returning(responses)
    with patch("backend.overpass.httpx.Client", client_cls), \
         patch("backend.overpass._CACHE_TTL", 0), \
         patch("backend.overpass._MAX_ATTEMPTS", 3), \
         patch("backend.overpass.time.sleep"):
        with pytest.raises(httpx.ConnectError):
            fetch_osm_data(BBOX)
    assert len(calls) == 3


# ── Trail difficulty ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("tags,expected", [
    ({}, None),
    ({"mtb:scale": "0"}, 0),
    ({"mtb:scale": "3"}, 3),
    ({"mtb:scale": "6"}, 6),
    # Modifiers are common in the wild; the leading digit is what we keep.
    ({"mtb:scale": "2+"}, 2),
    ({"mtb:scale": "1-"}, 1),
    # Junk is treated as absent rather than guessed at.
    ({"mtb:scale": "7"}, None),
    ({"mtb:scale": "yes"}, None),
    ({"mtb:scale": ""}, None),
    # sac_scale is the fallback when mtb:scale is missing.
    ({"sac_scale": "mountain_hiking"}, 2),
    ({"sac_scale": "difficult_alpine_hiking"}, 6),
    ({"sac_scale": "not_a_real_value"}, None),
    # Both present: the harder of the two wins.
    ({"mtb:scale": "1", "sac_scale": "alpine_hiking"}, 4),
    ({"mtb:scale": "5", "sac_scale": "hiking"}, 5),
])
def test_parse_trail_difficulty(tags, expected):
    assert _parse_trail_difficulty(tags) is expected


def test_fetch_osm_data_reads_trail_difficulty_onto_the_way():
    """The tag has to survive the parse, not just the helper."""
    elements = [
        {"type": "node", "id": 1, "lat": 0.5, "lon": 0.5},
        {"type": "node", "id": 2, "lat": 0.6, "lon": 0.6},
        {"type": "way", "id": 10, "nodes": [1, 2],
         "tags": {"highway": "path", "mtb:scale": "4"}},
    ]
    client_cls, _ = _client_returning([_FakeResp(200, elements=elements)])
    with patch("backend.overpass.httpx.Client", client_cls), \
         patch("backend.overpass._CACHE_TTL", 0):
        _nodes, ways = fetch_osm_data(BBOX)
    assert [w.trail_difficulty for w in ways] == [4]


def test_track_is_in_the_fetched_network():
    """Fire roads and gravel doubletrack are `highway=track`; without it in
    ROAD_NETWORK_TYPES nothing downstream can reach unpaved terrain at all."""
    assert "track" in ROAD_NETWORK_TYPES


def test_cache_key_changes_with_the_fetched_network():
    """A widened ROAD_NETWORK_TYPES must retire cached responses, not reuse them.

    Keyed on bbox alone, adding `track` left every cached entry in place: within TTL,
    still served, and missing every fire road the new query asks for.
    """
    before = _overpass_cache_path(BBOX)
    with patch("backend.overpass.ROAD_NETWORK_TYPES", frozenset({"residential", "track"})):
        after = _overpass_cache_path(BBOX)
    assert before != after


def test_cache_key_is_stable_for_the_same_inputs():
    assert _overpass_cache_path(BBOX) == _overpass_cache_path(BBOX)
    assert _overpass_cache_path(BBOX) != _overpass_cache_path((0.0, 0.0, 2.0, 2.0))
