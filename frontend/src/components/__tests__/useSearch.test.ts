/**
 * Tests for hooks/useSearch.ts
 *
 * parseSSELine is tested as a pure function.
 * The hook is tested by stubbing global fetch with a fake streaming response
 * that we can push SSE events into synchronously.
 */
import { describe, it, expect, vi, beforeEach, afterEach } from 'vitest'
import { renderHook, act } from '@testing-library/react'
import { parseSSELine, useSearch } from '../../hooks/useSearch'
import type { SSEEvent } from '../../types'

// ── parseSSELine (pure function) ─────────────────────────────────────────────

describe('parseSSELine', () => {
  it('parses a status event', () => {
    const event = parseSSELine('data: {"type":"status","message":"Querying Overpass API..."}')
    expect(event).toEqual({ type: 'status', message: 'Querying Overpass API...' })
  })

  it('parses a done event', () => {
    expect(parseSSELine('data: {"type":"done"}')).toEqual({ type: 'done' })
  })

  it('parses an error event', () => {
    expect(parseSSELine('data: {"type":"error","message":"Overpass down"}')).toEqual({
      type: 'error', message: 'Overpass down',
    })
  })

  it('parses a route event with all required fields including physics', () => {
    const payload = {
      type: 'route', route_id: 'abc-123',
      geometry: { type: 'LineString', coordinates: [[-122.4, 37.7]] },
      metadata: { name: 'Test St', length_m: 300, total_descent_m: 20, avg_grade_pct: -6.7, primary_highway: 'residential' },
      elevations: [100, 90, 80], segment_distances: [150, 150],
      flow_score: 85, flow_grade: 'A',
      speed_profile: [0, 20, 35], top_speed_kmh: 35, avg_speed_kmh: 18,
    }
    const event = parseSSELine(`data: ${JSON.stringify(payload)}`) as Extract<SSEEvent, { type: 'route' }>
    expect(event.type).toBe('route')
    expect(event.route_id).toBe('abc-123')
    expect(event.flow_grade).toBe('A')
    expect(event.top_speed_kmh).toBe(35)
  })

  it('returns null for non-data lines', () => {
    expect(parseSSELine('')).toBeNull()
    expect(parseSSELine(': heartbeat')).toBeNull()
    expect(parseSSELine('event: message')).toBeNull()
  })

  it('returns null for malformed JSON', () => {
    expect(parseSSELine('data: {broken json')).toBeNull()
  })

  it('handles leading/trailing whitespace in data line', () => {
    expect(parseSSELine('data:  {"type":"done"} ')).toEqual({ type: 'done' })
  })
})

// ── useSearch hook — fetch mock helpers ──────────────────────────────────────

/** Build a fake fetch that streams the given SSE payloads */
function makeFakeFetch(payloads: object[]) {
  const encoder = new TextEncoder()
  const chunks = payloads.map(p => encoder.encode(`data: ${JSON.stringify(p)}\n\n`))
  let i = 0
  const stream = new ReadableStream({
    pull(controller) {
      if (i < chunks.length) {
        controller.enqueue(chunks[i++])
      } else {
        controller.close()
      }
    },
  })
  return vi.fn().mockResolvedValue(
    new Response(stream, { status: 200, headers: { 'Content-Type': 'text/event-stream' } })
  )
}

const BASE_ROUTE = {
  type: 'route' as const,
  route_id: 'r1',
  geometry: { type: 'LineString' as const, coordinates: [[-122.4, 37.7]] as [number, number][] },
  metadata: { name: 'Test St', length_m: 300, total_descent_m: 20, avg_grade_pct: -6, primary_highway: 'residential' },
  elevations: [100, 90], segment_distances: [150],
  flow_score: 90, flow_grade: 'A',
  speed_profile: [0, 25], top_speed_kmh: 25, avg_speed_kmh: 12,
}

const BASE_SEARCH = { bbox: [37.7, -122.5, 37.8, -122.4] as [number, number, number, number] }

describe('useSearch hook', () => {
  beforeEach(() => {
    vi.stubGlobal('AbortController', AbortController)
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('starts as idle with no routes', () => {
    const { result } = renderHook(() => useSearch())
    expect(result.current.isSearching).toBe(false)
    expect(result.current.routes).toHaveLength(0)
    expect(result.current.error).toBeNull()
  })

  it('sets isSearching=true when search starts', async () => {
    vi.stubGlobal('fetch', makeFakeFetch([{ type: 'done' }]))
    const { result } = renderHook(() => useSearch())
    await act(async () => {
      result.current.startSearch(BASE_SEARCH)
    })
    // After done event resolves, isSearching goes back to false
    expect(result.current.isSearching).toBe(false)
  })

  it('updates statusMessage on status events', async () => {
    // No `done` here: `done` intentionally clears the status, so we observe the
    // last status the stream delivered before it closed.
    vi.stubGlobal('fetch', makeFakeFetch([
      { type: 'status', message: 'Building graph...' },
    ]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.statusMessage).toBe('Building graph...')
  })

  it('clears statusMessage on done', async () => {
    vi.stubGlobal('fetch', makeFakeFetch([
      { type: 'status', message: 'Building graph...' },
      { type: 'done' },
    ]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.statusMessage).toBeNull()
  })

  it('appends routes as they arrive', async () => {
    vi.stubGlobal('fetch', makeFakeFetch([BASE_ROUTE, { type: 'done' }]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.routes).toHaveLength(1)
    expect(result.current.routes[0].route_id).toBe('r1')
  })

  it('route event includes physics data directly', async () => {
    const routeWithPhysics = { ...BASE_ROUTE, speed_profile: [0, 25, 40], top_speed_kmh: 40, avg_speed_kmh: 22 }
    vi.stubGlobal('fetch', makeFakeFetch([routeWithPhysics, { type: 'done' }]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    const route = result.current.routes.find(r => r.route_id === 'r1')
    expect(route?.top_speed_kmh).toBe(40)
    expect(route?.speed_profile).toEqual([0, 25, 40])
  })

  it('sets isSearching=false on done event', async () => {
    vi.stubGlobal('fetch', makeFakeFetch([{ type: 'done' }]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.isSearching).toBe(false)
  })

  it('sets error and isSearching=false on error event', async () => {
    vi.stubGlobal('fetch', makeFakeFetch([{ type: 'error', message: 'Overpass timeout' }]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.error).toBe('Overpass timeout')
    expect(result.current.isSearching).toBe(false)
  })

  it('routes from a previous search are cleared on a new search', async () => {
    vi.stubGlobal('fetch', makeFakeFetch([BASE_ROUTE, { type: 'done' }]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.routes).toHaveLength(1)

    vi.stubGlobal('fetch', makeFakeFetch([{ type: 'done' }]))
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.routes).toHaveLength(0)
  })

  it('stopSearch aborts and sets isSearching=false', () => {
    // Never resolves — simulates a long-running request
    const neverResolves = vi.fn().mockReturnValue(new Promise(() => {}))
    vi.stubGlobal('fetch', neverResolves)
    const { result } = renderHook(() => useSearch())
    act(() => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.isSearching).toBe(true)
    act(() => { result.current.stopSearch() })
    expect(result.current.isSearching).toBe(false)
  })

  it('routes are sorted by top_speed_kmh descending immediately on route event', async () => {
    const slow = { ...BASE_ROUTE, route_id: 'slow', top_speed_kmh: 20, avg_speed_kmh: 15, speed_profile: [] }
    const fast = { ...BASE_ROUTE, route_id: 'fast', top_speed_kmh: 55, avg_speed_kmh: 40, speed_profile: [] }
    vi.stubGlobal('fetch', makeFakeFetch([slow, fast, { type: 'done' }]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.routes[0].route_id).toBe('fast')
    expect(result.current.routes[1].route_id).toBe('slow')
  })

  it('stream closing without done sets error and clears isSearching', async () => {
    vi.stubGlobal('fetch', makeFakeFetch([
      { type: 'status', message: 'Searching for hill bombs...' },
      BASE_ROUTE,
      // no done — simulates server crash / network drop
    ]))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.error).toBe('Connection lost — results may be incomplete.')
    expect(result.current.isSearching).toBe(false)
    // routes received before the drop are preserved
    expect(result.current.routes).toHaveLength(1)
  })

  it('fetch error sets error state', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('Network failure')))
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(result.current.error).toBe('Network failure')
    expect(result.current.isSearching).toBe(false)
  })

  it('sends POST with JSON body including bbox', async () => {
    const mockFetch = makeFakeFetch([{ type: 'done' }])
    vi.stubGlobal('fetch', mockFetch)
    const { result } = renderHook(() => useSearch())
    await act(async () => { result.current.startSearch(BASE_SEARCH) })
    expect(mockFetch).toHaveBeenCalledWith('/search', expect.objectContaining({
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
    }))
    const body = JSON.parse((mockFetch.mock.calls[0][1] as RequestInit).body as string)
    expect(body.bbox).toEqual(BASE_SEARCH.bbox)
  })
})
