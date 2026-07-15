"""
End-to-end integration test: Lincoln Boulevard, San Francisco Presidio.

Lincoln Boulevard runs along the western edge of the Presidio, above the coastal
cliffs. Between its El Camino Del Mar junction (south, ~37.789, -122.482) and
Stone Street (north, ~37.804, -122.476) the road crests near 87 m and drops both
ways — the southbound side is a ~70 m, 1.6 km descent that makes a fine hill bomb.

This route is the reason two changes exist:

  1. **Secondary roads are rideable by default.** Lincoln Boulevard is tagged as a
     mix of `tertiary` and `secondary` in OSM; the descent runs largely over the
     `secondary` segments. With secondary excluded the path can't stay on Lincoln
     and only a short tertiary stub survives (see the contrast assertion below).

  2. **Seeding from descent starts, not just peaks.** The Lincoln crest is a broad
     ridge that need not register as a detected `is_peak`; pathfinding now seeds
     from any node where the road tips downhill, so the descent starts at the top
     regardless of peak tagging.

Like the Hawk Hill test, this hits the real Overpass and 3DEP elevation APIs on
first run, then uses the disk cache (HILLBOMB_CACHE_DIR, default ~/.cache/hillbomb/)
for subsequent runs so the suite stays fast and offline-capable.
"""

import pytest

from ..config import DEFAULT_ROAD_TYPES, HIGHWAY_RANK, RIDER_PROFILES, SearchConfig, Toggles
from ..elevation import ElevationService
from ..graph import build_graph
from ..overpass import fetch_osm_data
from ..pathfinding import find_routes

# Default cap = secondary. Matches the "Max road size" slider's default and
# SearchRequest.max_road_rank, the control that actually decides road size.
_RANK_SECONDARY = 6
_RANK_TERTIARY = 5

# Bounding box over the Lincoln Boulevard corridor from the El Camino Del Mar
# junction up past Stone Street.  south, west, north, east — decimal degrees.
LINCOLN_BBOX = (37.788, -122.484, 37.806, -122.472)

# This area is dense, so the greedy search emits many routes; use a cap well above
# the ~300 the full search produces so it isn't truncated before the good Lincoln
# descents (which seed from a mid-height crest) are reached.
_MAX_ROUTES = 500


def _enrich_elevation(nodes):
    elev_svc = ElevationService()
    node_list = list(nodes.values())
    coords = [(n.lon, n.lat) for n in node_list]
    for node, elev in zip(node_list, elev_svc.get_elevations(coords)):
        node.elevation = elev
    return elev_svc.resolution_m


def _find_lincoln_routes(max_road_rank: int):
    """Run the full pipeline capped at `max_road_rank` (mirrors main._is_rideable);
    return (lincoln_routes, all_routes)."""
    nodes, ways = fetch_osm_data(LINCOLN_BBOX)
    for w in ways:
        w.traversable = (
            w.highway in DEFAULT_ROAD_TYPES
            and HIGHWAY_RANK.get(w.highway, 3) <= max_road_rank
        )

    config = SearchConfig(max_routes=_MAX_ROUTES)
    config.elevation_sample_interval_m = _enrich_elevation(nodes)

    G = build_graph(nodes, ways, config)
    params = RIDER_PROFILES["cyclist_upright"]
    toggles = Toggles()  # defaults: avoid stoplights/stop signs/bigger roads
    routes = list(find_routes(G, nodes, config, params, toggles))
    return [r for r in routes if r.name == "Lincoln Boulevard"], routes


@pytest.mark.integration
def test_lincoln_boulevard_present_and_partly_secondary():
    """Overpass must return Lincoln Boulevard, with some segments tagged secondary.

    The `secondary` tagging is the whole reason secondary roads are rideable by
    default — if OSM ever reclassifies these ways, this test should flag it.
    """
    nodes, ways = fetch_osm_data(LINCOLN_BBOX)
    lincoln = [w for w in ways if w.name == "Lincoln Boulevard"]
    assert lincoln, "No Lincoln Boulevard ways returned from Overpass — check bbox."
    secondary = [w for w in lincoln if w.highway in ("secondary", "secondary_link")]
    assert secondary, (
        "Expected some Lincoln Boulevard segments tagged `secondary`; got "
        f"{sorted({w.highway for w in lincoln})}."
    )


@pytest.mark.integration
def test_lincoln_boulevard_descent_found_by_default():
    """With default road types (secondary included), the Lincoln descent is found.

    The full pipeline should surface a long Lincoln Boulevard hill bomb — the
    southbound drop from the crest is ~1.6 km with ~70 m of descent.
    """
    lincoln_routes, all_routes = _find_lincoln_routes(_RANK_SECONDARY)
    assert lincoln_routes, (
        f"No 'Lincoln Boulevard' route among {len(all_routes)} total. "
        "The default cap includes secondary, so the descent should appear. "
        f"Routes found: {sorted({r.name for r in all_routes})[:20]}"
    )

    best = max(lincoln_routes, key=lambda r: r.total_descent_m)
    assert best.length_m >= 800, (
        f"Best Lincoln route is only {best.length_m:.0f} m — expected >= 800 m. "
        "A short result usually means the descent couldn't stay on the secondary "
        "segments of Lincoln Boulevard."
    )
    assert best.total_descent_m >= 50, (
        f"Best Lincoln route descends only {best.total_descent_m:.1f} m — expected >= 50 m."
    )


@pytest.mark.integration
def test_excluding_secondary_loses_the_lincoln_descent():
    """Contrast: without secondary rideable, only a short Lincoln stub survives.

    This pins down *why* secondary-by-default matters — the descent rides the
    secondary segments, so capping at tertiary collapses the ~1.6 km route to a stub.
    """
    lincoln_routes, _ = _find_lincoln_routes(_RANK_TERTIARY)
    best_len = max((r.length_m for r in lincoln_routes), default=0.0)
    assert best_len < 500, (
        f"Without secondary, the best Lincoln route is {best_len:.0f} m — expected a "
        "short stub (< 500 m). If this grew, the descent no longer depends on "
        "secondary segments and the default-road-types rationale should be revisited."
    )
