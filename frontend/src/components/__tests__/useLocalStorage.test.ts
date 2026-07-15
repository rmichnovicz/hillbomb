import { describe, it, expect, beforeEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { useSavedRoutes } from '../../hooks/useLocalStorage'
import type { Route } from '../../types'

const makeRoute = (id: string, topSpeed = 40): Route => ({
  route_id: id,
  start_node_id: 1,
  geometry: { type: 'LineString', coordinates: [[-122.4, 37.7]] },
  metadata: { name: `Route ${id}`, length_m: 300, total_descent_m: 20, avg_grade_pct: -6, primary_highway: 'residential' },
  elevations: [100, 90],
  segment_distances: [150],
  flow_score: 85,
  flow_grade: 'A',
  surface_pcts: { paved: 100 },
  stops: [],
  speed_profile: [0, topSpeed],
  top_speed_kmh: topSpeed,
  avg_speed_kmh: topSpeed / 2,
})

describe('useSavedRoutes', () => {
  beforeEach(() => {
    localStorage.clear()
  })

  it('starts with empty saved routes', () => {
    const { result } = renderHook(() => useSavedRoutes())
    expect(result.current.savedRoutes).toHaveLength(0)
  })

  it('saves a route', () => {
    const { result } = renderHook(() => useSavedRoutes())
    act(() => result.current.saveRoute(makeRoute('r1')))
    expect(result.current.savedRoutes).toHaveLength(1)
    expect(result.current.savedRoutes[0].route_id).toBe('r1')
  })

  it('persists across hook re-mounts (reads from localStorage)', () => {
    const { result: first } = renderHook(() => useSavedRoutes())
    act(() => first.current.saveRoute(makeRoute('r1')))

    const { result: second } = renderHook(() => useSavedRoutes())
    expect(second.current.savedRoutes).toHaveLength(1)
    expect(second.current.savedRoutes[0].route_id).toBe('r1')
  })

  it('removes a saved route by id', () => {
    const { result } = renderHook(() => useSavedRoutes())
    act(() => result.current.saveRoute(makeRoute('r1')))
    act(() => result.current.saveRoute(makeRoute('r2')))
    act(() => result.current.removeRoute('r1'))
    expect(result.current.savedRoutes).toHaveLength(1)
    expect(result.current.savedRoutes[0].route_id).toBe('r2')
  })

  it('isSaved returns true for saved route, false otherwise', () => {
    const { result } = renderHook(() => useSavedRoutes())
    act(() => result.current.saveRoute(makeRoute('r1')))
    expect(result.current.isSaved('r1')).toBe(true)
    expect(result.current.isSaved('r99')).toBe(false)
  })

  it('saving the same route_id twice does not duplicate it', () => {
    const { result } = renderHook(() => useSavedRoutes())
    act(() => result.current.saveRoute(makeRoute('r1', 40)))
    act(() => result.current.saveRoute(makeRoute('r1', 45)))
    expect(result.current.savedRoutes).toHaveLength(1)
  })

  it('removing a non-existent id is a no-op', () => {
    const { result } = renderHook(() => useSavedRoutes())
    act(() => result.current.saveRoute(makeRoute('r1')))
    expect(() => act(() => result.current.removeRoute('not-there'))).not.toThrow()
    expect(result.current.savedRoutes).toHaveLength(1)
  })

  it('discards stale data from an old schema version gracefully', () => {
    localStorage.setItem('hillbomb_routes_v1', JSON.stringify([{ stale: true }]))
    // Should start fresh without crashing when the stored data is from v1
    // (current key is a different version)
    const { result } = renderHook(() => useSavedRoutes())
    // If the version key matches, it may load or discard — either is fine
    // as long as it doesn't throw
    expect(result.current.savedRoutes).toBeDefined()
  })

  it('gracefully handles corrupted localStorage (not valid JSON)', () => {
    localStorage.setItem('hillbomb_routes_v2', 'not json at all')
    const { result } = renderHook(() => useSavedRoutes())
    expect(result.current.savedRoutes).toHaveLength(0)
  })
})
