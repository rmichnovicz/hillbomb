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

const SUMMARY = {
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
}

const INDEX = {
  version: 1,
  cities: [{
    city: 'San Francisco Bay Area',
    spots: [SUMMARY, { ...SUMMARY, slug: 'twin-peaks-blvd', name: 'Twin Peaks Blvd' }],
  }],
}

const SPOT = { ...SUMMARY, city: 'San Francisco Bay Area', rider_profile: 'cyclist_upright', built_at: '2026-07-16T00:00:00+00:00', routes: [{ route_id: 'r1' }] }
const SPOT2 = { ...SPOT, slug: 'twin-peaks-blvd', name: 'Twin Peaks Blvd', routes: [{ route_id: 'r2' }] }

/** Load the index and expand the one region, the normal way in. */
async function openRegion(result: { current: ReturnType<typeof useCollections> }) {
  act(() => result.current.loadIndex())
  await waitFor(() => expect(result.current.cities).toHaveLength(1))
  act(() => result.current.toggleCity('San Francisco Bay Area'))
  await waitFor(() => expect(result.current.isLoadingCity).toBe(false))
}

/** Route fetches by URL; unknown URLs reject so a typo fails loudly. */
function stubFetch(routes: Record<string, unknown>, status = 200) {
  return vi.fn((url: string) => {
    const body = routes[url]
    if (body === undefined) return Promise.reject(new Error(`unexpected fetch: ${url}`))
    return Promise.resolve({ ok: status >= 200 && status < 300, status, json: async () => body })
  })
}

beforeEach(() => {
  vi.stubGlobal('fetch', stubFetch({
    '/collections/index.json': INDEX,
    '/collections/hawk-hill-conzelman.json': SPOT,
    '/collections/twin-peaks-blvd.json': SPOT2,
  }))
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
    vi.stubGlobal('fetch', stubFetch({ '/collections/index.json': { version: 99, cities: [] } }))
    const { result } = renderHook(() => useCollections())
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.error).toMatch(/version 99/))
    expect(result.current.cities).toEqual([])
  })

  it('surfaces a server error and stays retryable', async () => {
    vi.stubGlobal('fetch', stubFetch({ '/collections/index.json': {} }, 500))
    const { result } = renderHook(() => useCollections())
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.error).toMatch(/500/))

    // A failed index must not latch the dedup flag, or the tab is dead forever.
    vi.stubGlobal('fetch', stubFetch({ '/collections/index.json': INDEX }))
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
      url === '/collections/hawk-hill-conzelman.json'
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

  it('loads every spot in a region when its folder is expanded', async () => {
    const { result } = renderHook(() => useCollections())
    await openRegion(result)
    expect(result.current.expandedCity).toBe('San Francisco Bay Area')
    expect(result.current.citySpots.map(s => s.slug)).toEqual(['hawk-hill-conzelman', 'twin-peaks-blvd'])
  })

  it('clears the region on collapse so its routes leave the map', async () => {
    const { result } = renderHook(() => useCollections())
    await openRegion(result)
    act(() => result.current.toggleCity('San Francisco Bay Area'))
    expect(result.current.expandedCity).toBeNull()
    expect(result.current.citySpots).toEqual([])
  })

  it('opens a spot from the region without refetching it', async () => {
    const { result } = renderHook(() => useCollections())
    await openRegion(result)
    const before = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length

    act(() => result.current.selectSpot('twin-peaks-blvd'))
    expect(result.current.activeSpot!.slug).toBe('twin-peaks-blvd')  // synchronous, from cache
    expect(fetch).toHaveBeenCalledTimes(before)
  })

  it('re-expands a visited region from cache', async () => {
    const { result } = renderHook(() => useCollections())
    await openRegion(result)
    const before = (fetch as unknown as ReturnType<typeof vi.fn>).mock.calls.length

    act(() => result.current.toggleCity('San Francisco Bay Area'))  // collapse
    act(() => result.current.toggleCity('San Francisco Bay Area'))  // re-expand
    expect(result.current.citySpots).toHaveLength(2)
    expect(result.current.isLoadingCity).toBe(false)
    expect(fetch).toHaveBeenCalledTimes(before)
  })

  it('expanding a region closes any open spot', async () => {
    const { result } = renderHook(() => useCollections())
    act(() => result.current.loadIndex())
    await waitFor(() => expect(result.current.cities).toHaveLength(1))
    act(() => result.current.selectSpot('hawk-hill-conzelman'))
    await waitFor(() => expect(result.current.activeSpot).not.toBeNull())

    act(() => result.current.toggleCity('San Francisco Bay Area'))
    expect(result.current.activeSpot).toBeNull()
  })

  it('keeps the spots that loaded when one of a region fails', async () => {
    vi.stubGlobal('fetch', stubFetch({
      '/collections/index.json': INDEX,
      '/collections/hawk-hill-conzelman.json': SPOT,
      // twin-peaks-blvd is absent → its fetch rejects
    }))
    const { result } = renderHook(() => useCollections())
    await openRegion(result)
    expect(result.current.citySpots.map(s => s.slug)).toEqual(['hawk-hill-conzelman'])
    expect(result.current.error).toBeNull()
  })

  it('surfaces a spot fetch failure', async () => {
    vi.stubGlobal('fetch', stubFetch({ '/collections/hawk-hill-conzelman.json': {} }, 404))
    const { result } = renderHook(() => useCollections())
    act(() => result.current.selectSpot('hawk-hill-conzelman'))
    await waitFor(() => expect(result.current.error).toMatch(/404/))
    expect(result.current.activeSpot).toBeNull()
  })
})
