"""
Dev harness: run the full pipeline on a hardcoded Twin Peaks bbox.
Outputs routes.geojson in the working directory for visual inspection at geojson.io.

Usage:
  python -m backend.dev_run
"""

import json
import os
import pickle

from .overpass import fetch_osm_data
from .elevation import ElevationService
from .graph import build_graph
from .pathfinding import find_routes
from .physics import simulate_speed_profile
from .scoring import compute_flow_score
from .config import DEFAULT_ROAD_TYPES, SearchConfig, RIDER_PROFILES, Toggles

BBOX = (37.748, -122.454, 37.758, -122.440)  # Twin Peaks, SF
CACHE_PATH = "backend/_cache_twins.pkl"


def main():
    # ── 1. Data fetching (cached) ─────────────────────────────────────────────
    if os.path.exists(CACHE_PATH):
        with open(CACHE_PATH, "rb") as f:
            nodes, ways = pickle.load(f)
        print(f"[cache] Loaded {len(nodes)} nodes, {len(ways)} ways")
    else:
        print("Querying Overpass API...")
        nodes, ways = fetch_osm_data(BBOX, DEFAULT_ROAD_TYPES)
        print(f"  → {len(nodes)} nodes, {len(ways)} ways")

        used_ids = {nid for w in ways for nid in w.node_ids}
        active_nodes = {nid: n for nid, n in nodes.items() if nid in used_ids}
        print(f"Fetching elevations for {len(active_nodes)} nodes...")
        coords = [(n.lon, n.lat) for n in active_nodes.values()]
        elevs = ElevationService().get_elevations(coords)
        for node, elev in zip(active_nodes.values(), elevs):
            node.elevation = elev

        os.makedirs("backend", exist_ok=True)
        with open(CACHE_PATH, "wb") as f:
            pickle.dump((nodes, ways), f)
        print("  → cached to", CACHE_PATH)

    # ── 2. Graph ──────────────────────────────────────────────────────────────
    config = SearchConfig()
    print("Building graph...")
    G = build_graph(nodes, ways, config)
    peaks   = sum(1 for _, d in G.nodes(data=True) if d.get("is_peak"))
    valleys = sum(1 for _, d in G.nodes(data=True) if d.get("is_valley"))
    print(f"  → {G.number_of_nodes()} nodes, {G.number_of_edges()} edges, {peaks} peaks, {valleys} valleys")

    # ── 3. Pathfinding ────────────────────────────────────────────────────────
    params = RIDER_PROFILES["cyclist_upright"]
    toggles = Toggles()
    print("Running pathfinding...")
    routes = list(find_routes(G, nodes, config, params, toggles))
    print(f"  → {len(routes)} routes found")

    # ── 4. Physics + scoring ──────────────────────────────────────────────────
    for r in routes:
        profile, top, avg = simulate_speed_profile(r.elevations, r.segment_distances, params, config)
        r.speed_profile = profile
        r.top_speed_kmh = top
        r.avg_speed_kmh = avg
        compute_flow_score(r, G, nodes, config)

    # ── 5. Sort by top speed ──────────────────────────────────────────────────
    routes.sort(key=lambda r: -r.top_speed_kmh)

    for i, r in enumerate(routes[:10], 1):
        print(f"  {i:2d}. {r.name[:30]:30s}  len={r.length_m:5.0f}m  top={r.top_speed_kmh:5.1f}km/h  descent={r.total_descent_m:4.1f}m  flow={r.flow_grade}")

    # ── 5. GeoJSON output ─────────────────────────────────────────────────────
    features = []
    for i, r in enumerate(routes):
        features.append({
            "type": "Feature",
            "properties": {
                "rank": i + 1,
                "name": r.name,
                "length_m": round(r.length_m, 1),
                "descent_m": round(r.total_descent_m, 1),
                "avg_grade_pct": round(r.avg_grade_pct, 2),
                "top_speed_kmh": round(r.top_speed_kmh, 1),
                "avg_speed_kmh": round(r.avg_speed_kmh, 1),
                "flow_score": round(r.flow_score, 1),
                "flow_grade": r.flow_grade,
            },
            "geometry": {
                "type": "LineString",
                "coordinates": r.coordinates,
            },
        })

    out_path = "routes.geojson"
    with open(out_path, "w") as f:
        json.dump({"type": "FeatureCollection", "features": features}, f, indent=2)
    print(f"\nWrote {out_path} — drop it into https://geojson.io to inspect")


if __name__ == "__main__":
    main()
