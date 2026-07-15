"""
End-to-end integration test: Hawk Hill / Conzelman Road, Marin Headlands.

Conzelman Road runs east-west along the Marin Headlands ridge, just north of
the Golden Gate Bridge. Two classic descent routes:
  - Frontside: heads east from Hawk Hill toward the bridge (secondary descent)
  - Backside: heads west and curves north, descending the far side of the hill

Both routes are on OSM ways named "Conzelman Road", tagged as `secondary`.

This test hits the real Overpass and 3DEP elevation APIs on first run, then
uses the disk cache (HILLBOMB_CACHE_DIR, default ~/.cache/hillbomb/) for all
subsequent runs so the test suite stays fast and offline-capable.

To force a fresh fetch: delete ~/.cache/hillbomb/overpass/ and
~/.cache/hillbomb/elevation/, or set HILLBOMB_CACHE_TTL=0 for Overpass.
"""

import pytest

from ..config import RIDER_PROFILES, SearchConfig, Toggles
from ..elevation import ElevationService
from ..graph import build_graph
from ..overpass import fetch_osm_data
from ..pathfinding import find_routes

# Bounding box that captures the full Conzelman Road ridge and both descents.
# south, west, north, east — decimal degrees
HAWK_HILL_BBOX = (37.820, -122.515, 37.845, -122.470)

# Conzelman Road is tagged `secondary`; include surrounding road types for
# context so the graph has proper intersections.
HAWK_HILL_ROAD_TYPES = {
    "secondary", "secondary_link",
    "tertiary", "tertiary_link",
    "unclassified",
    "residential",
}


@pytest.mark.integration
def test_conzelman_road_ways_present_in_osm():
    """Overpass must return at least one way named 'Conzelman Road' in this bbox."""
    nodes, ways = fetch_osm_data(HAWK_HILL_BBOX)
    conzelman = [w for w in ways if "Conzelman" in w.name]
    assert conzelman, (
        "No Conzelman Road ways returned from Overpass. "
        "Check bbox or road_types (Conzelman Road is tagged `secondary`)."
    )


@pytest.mark.integration
def test_hawk_hill_routes_found():
    """
    Full pipeline: fetch OSM → enrich elevation → build graph → pathfind.
    Expects at least one route on Conzelman Road with real descent and length.
    """
    nodes, ways = fetch_osm_data(HAWK_HILL_BBOX)
    # The full road network is fetched; mark which tiers are rideable here.
    for w in ways:
        w.traversable = w.highway in HAWK_HILL_ROAD_TYPES

    elev_svc = ElevationService()
    node_list = list(nodes.values())
    coords = [(n.lon, n.lat) for n in node_list]
    elevations = elev_svc.get_elevations(coords)
    for node, elev in zip(node_list, elevations):
        node.elevation = elev

    config = SearchConfig(max_routes=25)
    config.elevation_sample_interval_m = elev_svc.resolution_m

    params = RIDER_PROFILES["cyclist_upright"]
    toggles = Toggles(
        avoid_stoplights=True,
        avoid_stop_signs=True,
        avoid_bigger_roads=True,
        avoid_equal_roads=False,
    )

    G = build_graph(nodes, ways, config)

    peak_nodes = [nid for nid, d in G.nodes(data=True) if d.get("is_peak")]
    assert peak_nodes, (
        "Graph has no peak nodes — elevation data may be flat or incorrect. "
        f"Node elevation range: {min(n.elevation for n in node_list):.0f}–"
        f"{max(n.elevation for n in node_list):.0f} m"
    )

    routes = list(find_routes(G, nodes, config, params, toggles))
    assert routes, "No routes found at all in the Hawk Hill area."

    conzelman_routes = [r for r in routes if "Conzelman" in r.name]
    assert conzelman_routes, (
        f"No routes named 'Conzelman Road' found among {len(routes)} total route(s). "
        f"Routes found: {sorted({r.name for r in routes})}"
    )

    best = max(conzelman_routes, key=lambda r: r.total_descent_m)
    assert best.length_m >= 500, (
        f"Best Conzelman route is only {best.length_m:.0f} m — expected >= 500 m"
    )
    assert best.total_descent_m >= 50, (
        f"Best Conzelman route descends only {best.total_descent_m:.1f} m — expected >= 50 m"
    )
