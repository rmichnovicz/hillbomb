import { describe, it, expect } from 'vitest'
import { buildStartMarkerFeatures } from '../Map/HillbombMap'
import type { Route } from '../../types'

/**
 * Coordinates are real Hawk Hill values. The summit node (12604582833) carries two
 * descents — west toward Point Bonita and east back toward the bridge — which used to
 * collapse into a single chevron pointing whichever way the higher-ranked route went.
 */
const SUMMIT: [number, number] = [-122.49867, 37.82788]

function route(overrides: Partial<Route> & { coordinates: number[][] }): Route {
  const { coordinates, ...rest } = overrides
  return {
    route_id: 'r1',
    start_node_id: 12604582833,
    geometry: { type: 'LineString', coordinates },
    metadata: {
      name: 'Conzelman Road', length_m: 1000, total_descent_m: 100,
      avg_grade_pct: -10, primary_highway: 'residential',
    },
    elevations: [], segment_distances: [], flow_score: 100, flow_grade: 'A',
    surface_pcts: {}, stops: [], speed_profile: [], top_speed_kmh: 0, avg_speed_kmh: 0,
    ...rest,
  } as Route
}

// ~350 m out from the summit, far enough to clear dropInBearing's 30 m smoothing.
const westbound = [SUMMIT, [-122.5020, 37.8272], [-122.5050, 37.8265]]
const eastbound = [SUMMIT, [-122.4955, 37.8290], [-122.4930, 37.8300]]

describe('buildStartMarkerFeatures', () => {
  it('draws a marker per direction when one node drops two ways', () => {
    const features = buildStartMarkerFeatures([
      route({ route_id: 'west', coordinates: westbound }),
      route({ route_id: 'east', coordinates: eastbound }),
    ], null)

    expect(features).toHaveLength(2)
    expect(features.map(f => f.properties.route_id)).toEqual(['west', 'east'])
    const [a, b] = features.map(f => f.properties.bearing)
    expect(Math.abs(a - b)).toBeGreaterThan(45)
  })

  it('draws one marker when both routes leave in the same direction', () => {
    const features = buildStartMarkerFeatures([
      route({ route_id: 'best', coordinates: westbound }),
      // Same drop-in, diverging later — one chevron is correct here.
      route({ route_id: 'sibling', coordinates: [...westbound, [-122.5080, 37.8240]] }),
    ], null)

    expect(features).toHaveLength(1)
    expect(features[0].properties.route_id).toBe('best')
  })

  it('keeps the best-ranked route per direction, since routes arrive in rank order', () => {
    const features = buildStartMarkerFeatures([
      route({ route_id: 'east-best', coordinates: eastbound }),
      route({ route_id: 'east-worse', coordinates: [...eastbound, [-122.4900, 37.8310]] }),
    ], null)

    expect(features.map(f => f.properties.route_id)).toEqual(['east-best'])
  })

  it('separates markers from different start nodes even on the same bearing', () => {
    const features = buildStartMarkerFeatures([
      route({ route_id: 'a', start_node_id: 1, coordinates: westbound }),
      route({ route_id: 'b', start_node_id: 2, coordinates: westbound }),
    ], null)

    expect(features).toHaveLength(2)
  })

  it('flags every marker of the active group, not just the one that was clicked', () => {
    const features = buildStartMarkerFeatures([
      route({ route_id: 'west', coordinates: westbound }),
      route({ route_id: 'east', coordinates: eastbound }),
      route({ route_id: 'other', start_node_id: 99, coordinates: westbound }),
    ], '12604582833')

    expect(features.map(f => f.properties.is_active)).toEqual([1, 1, 0])
  })

  it('offsets each marker onto its own line so co-located starts do not stack', () => {
    const features = buildStartMarkerFeatures([
      route({ route_id: 'west', coordinates: westbound }),
      route({ route_id: 'east', coordinates: eastbound }),
    ], null)

    // Both routes start on the summit node; the markers must not land on the same point.
    expect(features[0].geometry.coordinates).not.toEqual(SUMMIT)
    expect(features[0].geometry.coordinates).not.toEqual(features[1].geometry.coordinates)
    // Each stays on the line it represents.
    expect(westbound).toContainEqual(features[0].geometry.coordinates)
    expect(eastbound).toContainEqual(features[1].geometry.coordinates)
  })

  it('falls back to the last vertex on a line shorter than the offset', () => {
    const stub = [SUMMIT, [-122.49875, 37.82791]] // ~9 m long
    const features = buildStartMarkerFeatures([route({ coordinates: stub })], null)
    expect(features[0].geometry.coordinates).toEqual(stub[1])
  })
})
