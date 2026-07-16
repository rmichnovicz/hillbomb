/**
 * Tests for hooks/useCollections.ts
 *
 * fetch is stubbed per-URL. The behaviors worth pinning are the ones that aren't
 * obvious from reading the hook: request dedup, the spot cache, the stale-response
 * guard, and that a failed index stays retryable.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act, waitFor } from '@testing-library/react'
import { useCollections } from '../../hooks/useCollections'

const INDEX = {
  version: 1,
  cities: [{
    city: 'San Francisco Bay Area',
    spots: [{
      slug: 'hawk-hill-conzelman',
      name: 'Hawk Hill (Conzelman Road)',
      state: 'CA',
      blurb: 'The classic Marin Headlands descent.',
      discipline: 'cycling',
      notes: '',
      center: [-122.4925, 37.8325],
      bbox: [37.82, -122.515, 37.845, -122.47],
      route_count: 3,
      length_m: 1407.6,
      total_descent_m: 165.8,
      avg_grade_pct: -11.8,
      top_speed_kmh: 84.4,
      flow_grade: 'A',
    }],
  }],
}

const SPOT = { ...INDEX.cities[0].spots[0], city: 'San Francisco Bay Area', rider_profile: 'cyclist_upright', built_at: '2026-07-16T00:00:00+00:00', routes: [{ route_id: 'r1' }] }

/** Route fetches by URL; unknown URLs reject so a typo fails loudly. */
function stubFetch(routes: Record<string, unknown>, status = 200) {
  return vi.fn((url: string) => {
    const body = routes[url]
    if (body === undefined) return Promise.reject(new Error(`unexpected fetch: ${url}`))
    return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body })
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', stubFetch({ '/collections': INDEX, '/collections/hawk-hill-conzelman': SPOT }))
})
afterEach(() => vi.unstubAllGlobals())

describe('useCollections', () => {
  it('starts empty and idle', () => {
    const { result } = renderHook(() => useCollections())
    expect(result.current.cities).toEqual([])
    expect(result.current.activeSpot).toBeNull()
    expect(result.current.error).toBeNull()
    expect(fetch).not.toHaveBeenCalled()
  })

  it('loads the index', async () => {
    const { result } = renderHook(() => useCollections())
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.cities).toHaveLength(1))
    expect(result.current.cities[0].city).toBe('San Francisco Bay Area')
    expect(result.current.isLoadingIndex).toBe(false)
  })

  it('only fetches the index once across repeated calls', async () => {
    const { result } = renderHook(() => useCollections())
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.cities).toHaveLength(1))
    act(() => result.current.loadIndex())
    act(() => result.current.loadIndex())
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('rejects an index with an unsupported schema version', async () => {
    vi.stubGlobal('fetch', stubFetch({ '/collections': { version: 99, cities: [] } }))
    const { result } = renderHook(() => useCollections())
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.error).toMatch(/version 99/))
    expect(result.current.cities).toEqual([])
  })

  it('surfaces a server error and stays retryable', async () => {
    vi.stubGlobal('fetch', stubFetch({ '/collections': {} }, 500))
    const { result } = renderHook(() => useCollections())
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.error).toMatch(/500/))

    // A failed index must not latch the dedup flag, or the tab is dead forever.
    vi.stubGlobal('fetch', stubFetch({ '/collections': INDEX }))
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.cities).toHaveLength(1))
  })

  it('loads a spot with its routes', async () => {
    const { result } = renderHook(() => useCollections())
    act(() => result.current.selectSpot('hawk-hill-conzelman'))
    await waitFor(() => expect(result.current.activeSpot).not.toBeNull())
    expect(result.current.activeSpot!.slug).toBe('hawk-hill-conzelman')
    expect(result.current.activeSpot!.routes).toHaveLength(1)
  })

  it('serves a revisited spot from cache without refetching', async () => {
    const { result } = renderHook(() => useCollections())
    act(() => result.current.selectSpot('hawk-hill-conzelman'))
    await waitFor(() => expect(result.current.activeSpot).not.toBeNull())
    expect(fetch).toHaveBeenCalledTimes(1)

    act(() => result.current.clearSpot())
    expect(result.current.activeSpot).toBeNull()

    act(() => result.current.selectSpot('hawk-hill-conzelman'))
    expect(result.current.activeSpot!.slug).toBe('hawk-hill-conzelman')  // synchronous
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it('ignores a slow response that a newer selection has superseded', async () => {
    const other = { ...SPOT, slug: 'other', routes: [] }
    let releaseSlow: (v: unknown) => void = () => {}
    const slow = new Promise(r => { releaseSlow = r })

    vi.stubGlobal('fetch', vi.fn((url: string) =>
      url === '/collections/hawk-hill-conzelman'
        ? slow.then(() => ({ ok: true, status: 200, json: async () => SPOT }))
        : Promise.resolve({ ok: true, status: 200, json: async () => other })
    ))

    const { result } = renderHook(() => useCollections())
    act(() => result.current.selectSpot('hawk-hill-conzelman'))  // slow
    act(() => result.current.selectSpot('other'))                // fast, wins
    await waitFor(() => expect(result.current.activeSpot?.slug).toBe('other'))

    await act(async () => { releaseSlow(null); await slow })
    expect(result.current.activeSpot!.slug).toBe('other')  // stale response dropped
  })

  it('surfaces a spot fetch failure', async () => {
    vi.stubGlobal('fetch', stubFetch({ '/collections/hawk-hill-conzelman': {} }, 404))
    const { result } = renderHook(() => useCollections())
    act(() => result.current.selectSpot('hawk-hill-conzelman'))
    await waitFor(() => expect(result.current.error).toMatch(/404/))
    expect(result.current.activeSpot).toBeNull()
  })
})
