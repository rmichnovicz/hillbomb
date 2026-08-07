import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import {
  CollectionsPanel,
  availableDisciplines,
  filterCities,
  spotMatchesFilter,
} from '../Collections/CollectionsPanel'
import type { CollectionCity, CollectionSpot, Route, StartGroup } from '../../types'

const SUMMARY = {
  slug: 'hawk-hill-conzelman',
  name: 'Hawk Hill (Conzelman Road)',
  state: 'CA',
  blurb: 'The classic Marin Headlands descent.',
  disciplines: ['road'],
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
  trail_difficulty: null,
  flow_grade: 'A',
  surface_pcts: { paved: 100 },
  stops: [],
  speed_profile: [20, 84.4],
  top_speed_kmh: 84.4,
  avg_speed_kmh: 52,
}

const SPOT: CollectionSpot = { ...SUMMARY, city: 'San Francisco Bay Area', rider_profile: 'cyclist_upright', built_at: '2026-07-16T00:00:00+00:00', routes: [ROUTE] }
const GROUPS: StartGroup[] = [{ startNodeId: '42', routes: [ROUTE], startCoord: [-122.49, 37.83] }]

// Hawk Hill's real shape: two descents share the summit node and one leaves elsewhere.
const SUMMIT: [number, number] = [-122.49867, 37.82788]
function line(route_id: string, end: [number, number], start = SUMMIT, start_node_id = 42): Route {
  return { ...ROUTE, route_id, start_node_id, geometry: { type: 'LineString', coordinates: [start, end] } }
}
const THREE_ROUTE_GROUPS: StartGroup[] = [
  {
    startNodeId: '42',
    routes: [line('west', [-122.52841, 37.82316]), line('east', [-122.49398, 37.83353])],
    startCoord: SUMMIT,
  },
  {
    startNodeId: '99',
    routes: [line('bridge', [-122.48368, 37.83373], [-122.49382, 37.83358], 99)],
    startCoord: [-122.49382, 37.83358],
  },
]
const THREE_ROUTE_SPOT: CollectionSpot = {
  ...SPOT,
  routes: THREE_ROUTE_GROUPS.flatMap(g => g.routes),
}

function renderPanel(overrides: Partial<React.ComponentProps<typeof CollectionsPanel>> = {}) {
  return render(
    <CollectionsPanel
      cities={CITIES}
      expandedCity={null}
      activeSpot={null}
      isLoadingIndex={false}
      isLoadingCity={false}
      isLoadingSpot={false}
      error={null}
      onToggleCity={vi.fn()}
      onSelectSpot={vi.fn()}
      onHoverSpot={vi.fn()}
      onBack={vi.fn()}
      groups={[]}
      activeGroupId={null}
      activeRouteId={null}
      onSelectGroup={vi.fn()}
      onSelectRoute={vi.fn()}
      onSelectPath={vi.fn()}
      onHoverGroup={vi.fn()}
      onHoverRoute={vi.fn()}
      sortMode="longest"
      onSortModeChange={vi.fn()}
      disciplineFilter={[]}
      onDisciplineFilterChange={vi.fn()}
      {...overrides}
    />
  )
}

const SF = 'San Francisco Bay Area'

describe('CollectionsPanel — browse', () => {
  it('renders a collapsed folder per city, with no spot cards showing', () => {
    renderPanel()
    expect(screen.getByRole('button', { name: /san francisco bay area/i })).toHaveAttribute('aria-expanded', 'false')
    expect(screen.getByRole('button', { name: /denver/i })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /hawk hill/i })).not.toBeInTheDocument()
  })

  it('summarizes a folder so it is worth opening', () => {
    renderPanel()
    const folder = screen.getByRole('button', { name: /san francisco bay area/i })
    expect(folder).toHaveTextContent('1 descent')
    expect(folder).toHaveTextContent('longest 1.4 km')
    expect(folder).toHaveTextContent('up to 84 km/h')
  })

  it('calls onToggleCity when a folder is clicked', () => {
    const onToggleCity = vi.fn()
    renderPanel({ onToggleCity })
    fireEvent.click(screen.getByRole('button', { name: /san francisco bay area/i }))
    expect(onToggleCity).toHaveBeenCalledWith(SF)
  })

  it('renders a card per spot with its headline stats once expanded', () => {
    renderPanel({ expandedCity: SF })
    expect(screen.getByRole('button', { name: /san francisco bay area/i })).toHaveAttribute('aria-expanded', 'true')
    const card = screen.getByRole('button', { name: /hawk hill/i })
    expect(card).toHaveTextContent('1.4 km')
    expect(card).toHaveTextContent('166 m')
    expect(card).toHaveTextContent('84 km/h')
    expect(card).toHaveTextContent('The classic Marin Headlands descent.')
  })

  it('expands only the open folder', () => {
    renderPanel({ expandedCity: SF })
    expect(screen.queryByRole('button', { name: /lookout mountain/i })).not.toBeInTheDocument()
  })

  it('says the expanded region is on the map', () => {
    renderPanel({ expandedCity: SF })
    expect(screen.getByText(/shown on the map/i)).toBeInTheDocument()
  })

  it('shows a loading line instead of cards while the region loads', () => {
    renderPanel({ expandedCity: SF, isLoadingCity: true })
    expect(screen.getByText(/loading 1 descent/i)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /hawk hill/i })).not.toBeInTheDocument()
  })

  it('calls onSelectSpot with the slug when a card is clicked', () => {
    const onSelectSpot = vi.fn()
    renderPanel({ expandedCity: SF, onSelectSpot })
    fireEvent.click(screen.getByRole('button', { name: /hawk hill/i }))
    expect(onSelectSpot).toHaveBeenCalledWith('hawk-hill-conzelman')
  })

  it('reports spot hover so the map can highlight that line', () => {
    const onHoverSpot = vi.fn()
    renderPanel({ expandedCity: SF, onHoverSpot })
    const card = screen.getByRole('button', { name: /hawk hill/i })
    fireEvent.mouseEnter(card)
    expect(onHoverSpot).toHaveBeenCalledWith('hawk-hill-conzelman')
    fireEvent.mouseLeave(card)
    expect(onHoverSpot).toHaveBeenLastCalledWith(null)
  })

  it('shows a build hint when nothing has been built', () => {
    renderPanel({ cities: [] })
    expect(screen.getByText(/build_collections/)).toBeInTheDocument()
  })

  it('shows the error instead of the list', () => {
    renderPanel({ error: 'Server error: 500' })
    expect(screen.getByText('Server error: 500')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /san francisco bay area/i })).not.toBeInTheDocument()
  })

  it('shows a loading state while the index loads', () => {
    renderPanel({ cities: [], isLoadingIndex: true })
    expect(screen.getByText(/loading collections/i)).toBeInTheDocument()
  })

  it('formats sub-kilometre descents in metres', () => {
    renderPanel({ cities: [{ city: 'X', spots: [{ ...SUMMARY, length_m: 840 }] }], expandedCity: 'X' })
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
    expect(screen.queryByRole('button', { name: /denver/i })).not.toBeInTheDocument()
  })

  it('calls onBack from the back link, which names the region it returns to', () => {
    const onBack = vi.fn()
    renderPanel({ activeSpot: SPOT, groups: GROUPS, onBack })
    fireEvent.click(screen.getByRole('button', { name: /← San Francisco Bay Area/ }))
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

  // Hawk Hill's three lines used to sit behind two collapsed start-point folders, one
  // of which held a single route. A spot is one named descent; show its lines outright.
  it('lists every route outright instead of nesting them under start points', () => {
    renderPanel({ activeSpot: THREE_ROUTE_SPOT, groups: THREE_ROUTE_GROUPS })
    const cards = screen.getAllByRole('listitem')
    expect(cards).toHaveLength(3)
    // No "N routes" folder summary, and nothing needs expanding to be seen.
    expect(screen.queryByText(/2 routes/)).not.toBeInTheDocument()
  })

  it('names each line by the direction it descends, not the shared road name', () => {
    renderPanel({ activeSpot: THREE_ROUTE_SPOT, groups: THREE_ROUTE_GROUPS })
    expect(screen.getByText('West descent')).toBeInTheDocument()
    expect(screen.getByText('Northeast descent')).toBeInTheDocument()
    // The road name still shows, demoted to the stat line.
    expect(screen.getAllByText(/Conzelman Road ·/)).toHaveLength(3)
  })

  it('selects a route and its group together when a card is clicked', () => {
    const onSelectPath = vi.fn()
    renderPanel({ activeSpot: THREE_ROUTE_SPOT, groups: THREE_ROUTE_GROUPS, onSelectPath })
    fireEvent.click(screen.getByText('Northeast descent'))
    expect(onSelectPath).toHaveBeenCalledWith('east', '42')
  })
})

describe('CollectionsPanel — descriptions', () => {
  // Browse cards stay scannable: the notes are gotchas, and twelve of them stacked in a
  // region folder buries the thing you're actually scanning for.
  it('shows only the blurb on a browse card, not the notes', () => {
    renderPanel({
      cities: [{ city: SF, spots: [{ ...SUMMARY, notes: 'Gates close at sunset.' }] }],
      expandedCity: SF,
    })
    const card = screen.getByRole('button', { name: /hawk hill/i })
    expect(card).toHaveTextContent('The classic Marin Headlands descent.')
    expect(card).not.toHaveTextContent('Gates close at sunset.')
  })

  it('shows both descriptions once a spot is open', () => {
    renderPanel({
      activeSpot: { ...SPOT, notes: 'Gates close at sunset.' },
      groups: GROUPS,
    })
    expect(screen.getByText('The classic Marin Headlands descent.')).toBeInTheDocument()
    expect(screen.getByText('Gates close at sunset.')).toBeInTheDocument()
  })
})

// ── Discipline filter ─────────────────────────────────────────────────────────

const SKATE = { ...SUMMARY, slug: 'dolores', name: 'Dolores Street', disciplines: ['skate'] }
const BOTH = { ...SUMMARY, slug: 'marin-ave', name: 'Marin Avenue', disciplines: ['road', 'skate'] }
const MIXED_CITIES: CollectionCity[] = [
  { city: SF, spots: [SUMMARY, SKATE, BOTH] },
  { city: 'Denver', spots: [{ ...SUMMARY, slug: 'lookout', name: 'Lookout Mountain' }] },
]

describe('discipline filtering', () => {
  it('treats an empty filter as show-everything', () => {
    expect(spotMatchesFilter(SKATE, [])).toBe(true)
    expect(filterCities(MIXED_CITIES, [])).toEqual(MIXED_CITIES)
  })

  it('matches a spot on any one of its tags', () => {
    expect(spotMatchesFilter(BOTH, ['skate'])).toBe(true)
    expect(spotMatchesFilter(BOTH, ['road'])).toBe(true)
    expect(spotMatchesFilter(SUMMARY, ['skate'])).toBe(false)
  })

  it('drops a city with no matching spots rather than showing an empty folder', () => {
    const result = filterCities(MIXED_CITIES, ['skate'])
    expect(result.map(c => c.city)).toEqual([SF])
    expect(result[0].spots.map(s => s.slug)).toEqual(['dolores', 'marin-ave'])
  })

  it('unions across selected tags', () => {
    const result = filterCities(MIXED_CITIES, ['road', 'skate'])
    expect(result.map(c => c.city)).toEqual([SF, 'Denver'])
  })

  it('derives chips from the tags actually in use, in vocabulary order', () => {
    expect(availableDisciplines(MIXED_CITIES)).toEqual(['road', 'skate'])
  })

  it('surfaces a new tag automatically, with no frontend change', () => {
    const withGravel = [{ city: SF, spots: [SUMMARY, { ...SUMMARY, slug: 'g', disciplines: ['gravel'] }] }]
    expect(availableDisciplines(withGravel)).toEqual(['road', 'gravel'])
  })

  it('never offers a chip for a tag no spot claims', () => {
    expect(availableDisciplines(MIXED_CITIES)).not.toContain('mtb')
  })
})

describe('CollectionsPanel — filter bar', () => {
  it('renders a chip per tag in use plus All', () => {
    renderPanel({ cities: MIXED_CITIES })
    expect(screen.getByRole('button', { name: 'All' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Road bike' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Skate' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'MTB' })).not.toBeInTheDocument()
  })

  it('hides the bar when the whole index is one sport — nothing to filter', () => {
    renderPanel({ cities: CITIES })
    expect(screen.queryByRole('button', { name: 'All' })).not.toBeInTheDocument()
  })

  it('toggles a tag on', () => {
    const onDisciplineFilterChange = vi.fn()
    renderPanel({ cities: MIXED_CITIES, onDisciplineFilterChange })
    fireEvent.click(screen.getByRole('button', { name: 'Skate' }))
    expect(onDisciplineFilterChange).toHaveBeenCalledWith(['skate'])
  })

  it('toggles a selected tag back off', () => {
    const onDisciplineFilterChange = vi.fn()
    renderPanel({ cities: MIXED_CITIES, disciplineFilter: ['skate'], onDisciplineFilterChange })
    fireEvent.click(screen.getByRole('button', { name: 'Skate' }))
    expect(onDisciplineFilterChange).toHaveBeenCalledWith([])
  })

  it('keeps every chip visible while a filter is active, so the others stay reachable', () => {
    renderPanel({ cities: MIXED_CITIES, disciplineFilter: ['skate'] })
    expect(screen.getByRole('button', { name: 'Road bike' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /denver/i })).not.toBeInTheDocument()
  })

  it('explains an empty result instead of showing a blank list', () => {
    renderPanel({ cities: MIXED_CITIES, disciplineFilter: ['gravel'] })
    expect(screen.getByText(/no curated descents tagged gravel yet/i)).toBeInTheDocument()
  })
})
