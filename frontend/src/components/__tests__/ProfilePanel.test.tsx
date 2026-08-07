/**
 * Mounting ProfilePanel is the whole point of these tests.
 *
 * Chart.js v4 is tree-shakeable and react-chartjs-2's generic <Chart> registers
 * nothing on its own, so a missing ChartJS.register() argument is invisible to the
 * type checker and to the build — it only shows up as a runtime throw the first time
 * a chart is constructed ('"bar" is not a registered controller'). Rendering the
 * component for real is the only thing that catches it.
 */
import { describe, it, expect, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import { ProfilePanel } from '../ProfilePanel/ProfilePanel'
import type { Route } from '../../types'

const route: Route = {
  route_id: 'r1',
  start_node_id: 1,
  geometry: {
    type: 'LineString',
    coordinates: [[-122.5, 37.83], [-122.499, 37.829], [-122.498, 37.828]],
  },
  metadata: {
    name: 'Conzelman Road',
    length_m: 220,
    total_descent_m: 18,
    avg_grade_pct: -8.2,
    primary_highway: 'tertiary',
  },
  elevations: [180, 171, 162],
  segment_distances: [110, 110],
  flow_score: 85,
  flow_grade: 'B',
  surface_pcts: { paved: 100 },
  trail_difficulty: null,
  stops: [],
  speed_profile: [0, 24.5, 38.1],
  top_speed_kmh: 38.1,
  avg_speed_kmh: 26.4,
}

describe('ProfilePanel', () => {
  it('renders the elevation/speed chart without throwing', () => {
    // Chart.js registration failures surface as an uncaught throw during render.
    expect(() => render(<ProfilePanel route={route} />)).not.toThrow()
    expect(screen.getByRole('img')).toBeInTheDocument()
  })

  it('renders nothing for a route too short to chart', () => {
    const stub = { ...route, elevations: [180], segment_distances: [], speed_profile: [0] }
    const { container } = render(<ProfilePanel route={stub} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('renders when physics has not arrived yet (speed profile absent)', () => {
    const noPhysics = { ...route, speed_profile: [] }
    expect(() => render(<ProfilePanel route={noPhysics} />)).not.toThrow()
  })

  it('does not scrub on mount', () => {
    const onScrubPosition = vi.fn()
    render(<ProfilePanel route={route} onScrubPosition={onScrubPosition} />)
    expect(onScrubPosition).not.toHaveBeenCalled()
  })
})

describe('ProfilePanel hook ordering', () => {
  it('survives a route changing to one too short to chart', () => {
    const { rerender } = render(<ProfilePanel route={route} onScrubPosition={() => {}} />)
    const stub = { ...route, elevations: [180], segment_distances: [], speed_profile: [0] }
    expect(() => rerender(<ProfilePanel route={stub} onScrubPosition={() => {}} />)).not.toThrow()
  })
})
