import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { CollectionsPanel } from '../Collections/CollectionsPanel'
import type { CollectionCity, CollectionSpot, Route, StartGroup } from '../../types'

const SUMMARY = {
  slug: 'hawk-hill-conzelman',
  name: 'Hawk Hill (Conzelman Road)',
  state: 'CA',
  blurb: 'The classic Marin Headlands descent.',
  discipline: 'cycling' as const,
  notes: '',
  center: [-122.4925, 37.8325] as [number, number],
  bbox: [37.82, -122.515, 37.845, -122.47] as [number, number, number, number],
  route_count: 3,
  length_m: 1407.6,
  total_descent_m: 165.8,
  avg_grade_pct: -11.8,
  top_speed_kmh: 84.4,
  flow_grade: 'A',
}

const CITIES: CollectionCity[] = [
  { city: 'San Francisco Bay Area', spots: [SUMMARY] },
  { city: 'Denver', spots: [{ ...SUMMARY, slug: 'lookout-mountain', name: 'Lookout Mountain', state: 'CO' }] },
]

const ROUTE: Route = {
  route_id: 'r1',
  start_node_id: 42,
  geometry: { type: 'LineString', coordinates: [[-122.49, 37.83], [-122.48, 37.82]] },
  metadata: { name: 'Conzelman Road', length_m: 1407.6, total_descent_m: 165.8, avg_grade_pct: -11.8, primary_highway: 'secondary' },
  elevations: [180, 14.2],
  segment_distances: [1407.6],
  flow_score: 100,
  flow_grade: 'A',
  surface_pcts: { paved: 100 },
  stops: [],
  speed_profile: [20, 84.4],
  top_speed_kmh: 84.4,
  avg_speed_kmh: 52,
}

const SPOT: CollectionSpot = { ...SUMMARY, city: 'San Francisco Bay Area', rider_profile: 'cyclist_upright', built_at: '2026-07-16T00:00:00+00:00', routes: [ROUTE] }
const GROUPS: StartGroup[] = [{ startNodeId: '42', routes: [ROUTE], startCoord: [-122.49, 37.83] }]

function renderPanel(overrides: Partial<React.ComponentProps<typeof CollectionsPanel>> = {}) {
  return render(
    <CollectionsPanel
      cities={CITIES}
      activeSpot={null}
      isLoadingIndex={false}
      isLoadingSpot={false}
      error={null}
      onSelectSpot={vi.fn()}
      onBack={vi.fn()}
      groups={[]}
      activeGroupId={null}
      activeRouteId={null}
      onSelectGroup={vi.fn()}
      onSelectRoute={vi.fn()}
      onHoverGroup={vi.fn()}
      onHoverRoute={vi.fn()}
      sortMode="longest"
      onSortModeChange={vi.fn()}
      {...overrides}
    />
  )
}

describe('CollectionsPanel — browse', () => {
  it('renders a section per city', () => {
    renderPanel()
    expect(screen.getByRole('heading', { name: /san francisco bay area/i })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: /denver/i })).toBeInTheDocument()
  })

  it('renders a card per spot with its headline stats', () => {
    renderPanel()
    const card = screen.getByRole('button', { name: /hawk hill/i })
    expect(card).toHaveTextContent('1.4 km')
    expect(card).toHaveTextContent('166 m')
    expect(card).toHaveTextContent('84 km/h')
    expect(card).toHaveTextContent('The classic Marin Headlands descent.')
  })

  it('calls onSelectSpot with the slug when a card is clicked', () => {
    const onSelectSpot = vi.fn()
    renderPanel({ onSelectSpot })
    fireEvent.click(screen.getByRole('button', { name: /hawk hill/i }))
    expect(onSelectSpot).toHaveBeenCalledWith('hawk-hill-conzelman')
  })

  it('shows a build hint when nothing has been built', () => {
    renderPanel({ cities: [] })
    expect(screen.getByText(/build_collections/)).toBeInTheDocument()
  })

  it('shows the error instead of the list', () => {
    renderPanel({ error: 'Server error: 500' })
    expect(screen.getByText('Server error: 500')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /hawk hill/i })).not.toBeInTheDocument()
  })

  it('shows a loading state while the index loads', () => {
    renderPanel({ cities: [], isLoadingIndex: true })
    expect(screen.getByText(/loading collections/i)).toBeInTheDocument()
  })

  it('formats sub-kilometre descents in metres', () => {
    renderPanel({ cities: [{ city: 'X', spots: [{ ...SUMMARY, length_m: 840 }] }] })
    expect(screen.getByRole('button', { name: /hawk hill/i })).toHaveTextContent('840 m')
  })
})

describe('CollectionsPanel — detail', () => {
  it('shows the spot header and its routes', () => {
    renderPanel({ activeSpot: SPOT, groups: GROUPS })
    expect(screen.getByText('Hawk Hill (Conzelman Road)')).toBeInTheDocument()
    expect(screen.getByText(/San Francisco Bay Area, CA/)).toBeInTheDocument()
    expect(screen.getByRole('list')).toBeInTheDocument()  // RouteList
  })

  it('hides the browse list while a spot is open', () => {
    renderPanel({ activeSpot: SPOT, groups: GROUPS })
    expect(screen.queryByRole('heading', { name: /denver/i })).not.toBeInTheDocument()
  })

  it('calls onBack from the back link', () => {
    const onBack = vi.fn()
    renderPanel({ activeSpot: SPOT, groups: GROUPS, onBack })
    fireEvent.click(screen.getByRole('button', { name: /all collections/i }))
    expect(onBack).toHaveBeenCalledOnce()
  })

  it('shows notes when the spot has them', () => {
    renderPanel({ activeSpot: { ...SPOT, notes: 'Closed to cars on weekends.' }, groups: GROUPS })
    expect(screen.getByText('Closed to cars on weekends.')).toBeInTheDocument()
  })

  it('omits the notes callout when there are none', () => {
    renderPanel({ activeSpot: SPOT, groups: GROUPS })
    expect(screen.queryByText(/closed to cars/i)).not.toBeInTheDocument()
  })
})
