import { describe, it, expect } from 'vitest'
import { buildDescentLabels, descentDirection } from '../../utils/routeLabel'
import type { Route } from '../../types'

/** Real Hawk Hill summit; the two descents off it leave 156° apart. */
const SUMMIT: [number, number] = [-122.49867, 37.82788]

function route(route_id: string, coords: number[][], elevations: number[] = [200, 100]): Route {
  return {
    route_id,
    start_node_id: 42,
    geometry: { type: 'LineString', coordinates: coords as [number, number][] },
    metadata: {
      name: 'Conzelman Road', length_m: 1000, total_descent_m: 100,
      avg_grade_pct: -10, primary_highway: 'residential',
    },
    elevations, segment_distances: [], flow_score: 100, flow_grade: 'A',
    surface_pcts: {}, trail_difficulty: null, stops: [], speed_profile: [], top_speed_kmh: 0, avg_speed_kmh: 0,
  }
}

describe('descentDirection', () => {
  it('reads the net heading, not the opening metres', () => {
    // Starts heading north, but the run ends well west of where it began.
    const switchback = route('r', [SUMMIT, [-122.49860, 37.83100], [-122.52841, 37.82316]])
    expect(descentDirection(switchback)).toBe('West')
  })

  it('returns null for geometry it cannot read', () => {
    expect(descentDirection(route('r', [SUMMIT]))).toBeNull()
  })
})

describe('buildDescentLabels', () => {
  it('names Hawk Hills two summit descents by where they go', () => {
    const labels = buildDescentLabels([
      route('west', [SUMMIT, [-122.52841, 37.82316]]),
      route('east', [SUMMIT, [-122.49398, 37.83353]]),
    ])
    expect(labels.get('west')).toBe('West descent')
    expect(labels.get('east')).toBe('Northeast descent')
  })

  it('qualifies two same-direction lines top to bottom', () => {
    const labels = buildDescentLabels([
      route('low', [[-122.28, 37.889], [-122.285, 37.8885]], [120, 60]),
      route('high', [[-122.26, 37.897], [-122.265, 37.8965]], [340, 280]),
    ])
    expect(labels.get('high')).toBe('Upper West descent')
    expect(labels.get('low')).toBe('Lower West descent')
  })

  it('uses Upper/Middle/Lower for three same-direction lines', () => {
    const labels = buildDescentLabels([
      route('a', [[-122.26, 37.897], [-122.265, 37.8965]], [340, 280]),
      route('b', [[-122.27, 37.893], [-122.275, 37.8925]], [220, 160]),
      route('c', [[-122.28, 37.889], [-122.285, 37.8885]], [120, 60]),
    ])
    expect([...labels.values()]).toEqual([
      'Upper West descent', 'Middle West descent', 'Lower West descent',
    ])
  })

  it('numbers beyond three rather than inventing more position words', () => {
    const labels = buildDescentLabels(
      [340, 260, 180, 100].map((e, i) =>
        route(`r${i}`, [[-122.26 - i * 0.01, 37.9], [-122.265 - i * 0.01, 37.8995]], [e, e - 50])),
    )
    expect([...labels.values()]).toEqual([
      'West descent 1', 'West descent 2', 'West descent 3', 'West descent 4',
    ])
  })

  it('falls back to the road name when direction cannot be derived', () => {
    const labels = buildDescentLabels([route('degenerate', [SUMMIT])])
    expect(labels.get('degenerate')).toBe('Conzelman Road')
  })
})
