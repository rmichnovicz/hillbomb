import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { RouteCard } from '../RouteList/RouteCard'
import type { Route } from '../../types'

const makeRoute = (overrides: Partial<Route> = {}): Route => ({
  route_id: 'r1',
  geometry: { type: 'LineString', coordinates: [[-122.4, 37.7]] },
  metadata: { name: 'Twin Peaks Blvd', length_m: 650, total_descent_m: 55, avg_grade_pct: -8.5, primary_highway: 'residential' },
  elevations: [250, 220, 195],
  segment_distances: [300, 350],
  flow_score: 85,
  flow_grade: 'A',
  top_speed_kmh: 42,
  avg_speed_kmh: 30,
  speed_profile: [0, 25, 42],
  ...overrides,
})

describe('RouteCard', () => {
  it('renders the route name', () => {
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={vi.fn()} isSaved={false} />)
    expect(screen.getByText('Twin Peaks Blvd')).toBeInTheDocument()
  })

  it('renders top speed when available', () => {
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={vi.fn()} isSaved={false} />)
    expect(screen.getByText(/42/)).toBeInTheDocument()
  })

  it('renders the flow grade badge', () => {
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={vi.fn()} isSaved={false} />)
    expect(screen.getByText('A')).toBeInTheDocument()
  })

  it('renders route length formatted in meters or km', () => {
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={vi.fn()} isSaved={false} />)
    // 650m or 0.65 km — either format is acceptable
    expect(screen.getByText(/650|0\.65/)).toBeInTheDocument()
  })

  it('renders total descent', () => {
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={vi.fn()} isSaved={false} />)
    expect(screen.getByText(/55/)).toBeInTheDocument()
  })

  it('calls onSelect when card is clicked', () => {
    const onSelect = vi.fn()
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={onSelect} onSave={vi.fn()} isSaved={false} />)
    fireEvent.click(screen.getByText('Twin Peaks Blvd'))
    expect(onSelect).toHaveBeenCalledWith('r1')
  })

  it('applies active styling when isActive=true', () => {
    const { container } = render(<RouteCard route={makeRoute()} isActive={true} onSelect={vi.fn()} onSave={vi.fn()} isSaved={false} />)
    // Active card should have some visual distinction (class, aria, etc.)
    expect(container.firstChild).toHaveAttribute('aria-selected', 'true')
  })

  it('renders a save button', () => {
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={vi.fn()} isSaved={false} />)
    expect(screen.getByRole('button', { name: /save/i })).toBeInTheDocument()
  })

  it('calls onSave when save button is clicked', () => {
    const onSave = vi.fn()
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={onSave} isSaved={false} />)
    fireEvent.click(screen.getByRole('button', { name: /save/i }))
    expect(onSave).toHaveBeenCalledWith('r1')
  })

  it('shows "saved" state when isSaved=true', () => {
    render(<RouteCard route={makeRoute()} isActive={false} onSelect={vi.fn()} onSave={vi.fn()} isSaved={true} />)
    expect(screen.getByRole('button', { name: /saved/i })).toBeInTheDocument()
  })
})
