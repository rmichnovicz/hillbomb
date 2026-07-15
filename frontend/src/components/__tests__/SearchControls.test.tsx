import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import { SearchControls, DEFAULT_ROAD_SIZE_STEP, ALL_SURFACE_CATEGORIES } from '../SearchControls/SearchControls'
import type { SurfaceCategory } from '../SearchControls/SearchControls'
import type { Toggles } from '../../types'

function openAdvanced() {
  fireEvent.click(screen.getByRole('button', { name: /advanced settings/i }))
}

const DEFAULT_TOGGLES: Toggles = {
  avoid_stoplights: true,
  avoid_stop_signs: true,
  avoid_bigger_roads: true,
  avoid_equal_roads: true,
  exclude_tunnels: false,
  exclude_bridges: false,
  stay_on_initial_road: false,
  animate_candidates: false,
}

const DEFAULT_SURFACES: SurfaceCategory[] = [...ALL_SURFACE_CATEGORIES]

function renderControls(overrides: Partial<React.ComponentProps<typeof SearchControls>> = {}) {
  return render(
    <SearchControls
      isSearching={false}
      toggles={DEFAULT_TOGGLES}
      onTogglesChange={vi.fn()}
      roadSizeStep={DEFAULT_ROAD_SIZE_STEP}
      onRoadSizeChange={vi.fn()}
      allowedSurfaces={DEFAULT_SURFACES}
      onAllowedSurfacesChange={vi.fn()}
      minDistanceM={0}
      onMinDistanceChange={vi.fn()}
      onSearch={vi.fn()}
      onStop={vi.fn()}
      {...overrides}
    />
  )
}

describe('SearchControls', () => {
  it('renders Search button when not searching', () => {
    renderControls()
    expect(screen.getByRole('button', { name: /search/i })).toBeInTheDocument()
  })

  it('renders Stop button when searching', () => {
    renderControls({ isSearching: true })
    expect(screen.getByRole('button', { name: /stop/i })).toBeInTheDocument()
  })

  it('calls onSearch when Search is clicked', () => {
    const onSearch = vi.fn()
    renderControls({ onSearch })
    fireEvent.click(screen.getByRole('button', { name: /search/i }))
    expect(onSearch).toHaveBeenCalledOnce()
  })

  it('calls onStop when Stop is clicked', () => {
    const onStop = vi.fn()
    renderControls({ isSearching: true, onStop })
    fireEvent.click(screen.getByRole('button', { name: /stop/i }))
    expect(onStop).toHaveBeenCalledOnce()
  })

  it('renders a checkbox for every toggle and terrain type when advanced settings is open', () => {
    renderControls()
    openAdvanced()
    const expected = Object.keys(DEFAULT_TOGGLES).length + ALL_SURFACE_CATEGORIES.length
    expect(screen.getAllByRole('checkbox')).toHaveLength(expected)
  })

  it('hides checkboxes when advanced settings is collapsed', () => {
    renderControls()
    expect(screen.queryAllByRole('checkbox')).toHaveLength(0)
  })

  it('renders the road size slider when advanced settings is open', () => {
    renderControls()
    openAdvanced()
    expect(screen.getByRole('slider', { name: /max road size/i })).toBeInTheDocument()
  })

  it('calls onRoadSizeChange when slider is moved', () => {
    const onRoadSizeChange = vi.fn()
    renderControls({ onRoadSizeChange })
    openAdvanced()
    // Must differ from DEFAULT_ROAD_SIZE_STEP — React fires no change event for an unchanged value.
    const moved = DEFAULT_ROAD_SIZE_STEP - 1
    fireEvent.change(screen.getByRole('slider', { name: /max road size/i }), { target: { value: String(moved) } })
    expect(onRoadSizeChange).toHaveBeenCalledWith(moved)
  })

  it('shows avoid_stoplights as checked when advanced settings is open', () => {
    renderControls()
    openAdvanced()
    expect(screen.getByRole('checkbox', { name: /stoplights/i })).toBeChecked()
  })

  it('shows exclude_tunnels as unchecked by default', () => {
    renderControls()
    openAdvanced()
    expect(screen.getByRole('checkbox', { name: /tunnels/i })).not.toBeChecked()
  })

  it('calls onTogglesChange with updated value when a toggle is clicked', () => {
    const onTogglesChange = vi.fn()
    renderControls({ onTogglesChange })
    openAdvanced()
    fireEvent.click(screen.getByRole('checkbox', { name: /stoplights/i }))
    expect(onTogglesChange).toHaveBeenCalledWith(
      expect.objectContaining({ avoid_stoplights: false })
    )
  })

  it('reflects unchecked state when avoid_bigger_roads is false', () => {
    renderControls({ toggles: { ...DEFAULT_TOGGLES, avoid_bigger_roads: false } })
    openAdvanced()
    expect(screen.getByRole('checkbox', { name: /bigger roads/i })).not.toBeChecked()
  })

  it('shows all surface categories as checked by default', () => {
    renderControls()
    openAdvanced()
    expect(screen.getByRole('checkbox', { name: /^Paved/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /gravel/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /unpaved/i })).toBeChecked()
    expect(screen.getByRole('checkbox', { name: /cobblestone/i })).toBeChecked()
  })

  it('calls onAllowedSurfacesChange when a surface is unchecked', () => {
    const onAllowedSurfacesChange = vi.fn()
    renderControls({ onAllowedSurfacesChange })
    openAdvanced()
    fireEvent.click(screen.getByRole('checkbox', { name: /gravel/i }))
    expect(onAllowedSurfacesChange).toHaveBeenCalledWith(
      expect.not.arrayContaining(['gravel'])
    )
  })

  it('disables all checkboxes and slider while searching', () => {
    renderControls({ isSearching: true })
    openAdvanced()
    for (const cb of screen.getAllByRole('checkbox')) {
      expect(cb).toBeDisabled()
    }
    expect(screen.getByRole('slider', { name: /max road size/i })).toBeDisabled()
  })
})
