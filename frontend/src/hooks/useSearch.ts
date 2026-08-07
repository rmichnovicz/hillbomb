/**
 * SSE streaming hook.
 *
 * Uses fetch() + ReadableStream instead of EventSource because the backend
 * endpoint is POST /search — EventSource is GET-only.
 * AbortController handles the stop button and new-search cancellation.
 *
 * In production this is the one request that leaves the CDN's origin (see api.ts), so
 * it is also the only one subject to CORS. A POST with a JSON body is not a simple
 * request, so it costs a preflight OPTIONS — allowed explicitly in main.py's CORS
 * middleware. Nothing else about the stream changes cross-origin.
 */
import { useState, useRef, useCallback } from 'react'
import { searchUrl } from '../api'
import type { Route, SearchOptions, SSEEvent } from '../types'

export interface UseSearchReturn {
  isSearching: boolean
  routes: Route[]
  statusMessage: string | null
  error: string | null
  startSearch: (options: SearchOptions) => void
  stopSearch: () => void
}

/** Parse a single raw SSE line ("data: {...}") into a typed event.
 *  Exported for unit testing. */
export function parseSSELine(line: string): SSEEvent | null {
  if (!line.startsWith('data:')) return null
  const json = line.slice(5).trim()
  try {
    return JSON.parse(json) as SSEEvent
  } catch {
    return null
  }
}

function buildSearchBody(options: SearchOptions): Record<string, unknown> {
  const { bbox, road_types, rider_profile, toggles, max_road_rank, allowed_surface_categories, crr_pathfinding } = options
  const body: Record<string, unknown> = { bbox }
  if (rider_profile) body.rider_profile = rider_profile
  if (road_types?.length) body.road_types = road_types
  if (toggles) body.toggles = toggles
  if (max_road_rank !== undefined) body.max_road_rank = max_road_rank
  if (allowed_surface_categories !== undefined) body.allowed_surface_categories = allowed_surface_categories
  if (crr_pathfinding !== undefined) body.crr_pathfinding = crr_pathfinding
  return body
}

export function useSearch(): UseSearchReturn {
  const [isSearching, setIsSearching] = useState(false)
  const [routes, setRoutes] = useState<Route[]>([])
  const [statusMessage, setStatusMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)

  const stopSearch = useCallback(() => {
    abortRef.current?.abort()
    abortRef.current = null
    setIsSearching(false)
  }, [])

  const startSearch = useCallback((options: SearchOptions) => {
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setRoutes([])
    setError(null)
    setStatusMessage(null)
    setIsSearching(true)

    async function run() {
      try {
        const response = await fetch(searchUrl(), {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify(buildSearchBody(options)),
          signal: controller.signal,
        })

        if (!response.ok || !response.body) {
          setError(`Server error: ${response.status}`)
          setIsSearching(false)
          return
        }

        const reader = response.body.getReader()
        const decoder = new TextDecoder()
        let buffer = ''
        let terminated = false

        // SSE events are delimited by double newlines.
        const drain = (flush = false): boolean => {
          const parts = buffer.split('\n\n')
          buffer = flush ? '' : parts.pop() ?? ''
          for (const part of parts) {
            for (const line of part.split('\n')) {
              const event = parseSSELine(line)
              if (event && handleEvent(event)) return true
            }
          }
          return false
        }

        while (!terminated) {
          const { done, value } = await reader.read()
          if (done) {
            buffer += decoder.decode()
            terminated = drain(true)
            break
          }
          buffer += decoder.decode(value, { stream: true })
          terminated = drain()
        }

        // Stream closed without a `done`/`error` event — treat as incomplete.
        if (!terminated) {
          setError('Connection lost — results may be incomplete.')
          setIsSearching(false)
        }
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Unknown error')
        setIsSearching(false)
      }
    }

    /** Apply one event. Returns true if it terminates the stream (done/error). */
    function handleEvent(event: SSEEvent): boolean {
      switch (event.type) {
        case 'queued':
          // Server is busy fetching elevation for other searches; we're in line.
          setStatusMessage(
            event.position === 1
              ? 'Waiting for a free slot…'
              : `Busy — you're #${event.position} in line…`
          )
          return false

        case 'busy':
          // Queue is full; no work was done. Surface as a retryable message and
          // end the search — the "Search this area" button is the retry.
          setError(event.message)
          setStatusMessage(null)
          setIsSearching(false)
          return true

        case 'status':
          setStatusMessage(event.message)
          return false

        case 'route':
          // The route event is a structural superset of Route (extra `type`).
          setRoutes(prev =>
            [...prev, event].sort((a, b) => b.top_speed_kmh - a.top_speed_kmh)
          )
          return false

        case 'candidate':
          // Animate-candidates overlay is rendered elsewhere; ignored here.
          return false

        case 'error':
          setError(event.message)
          setIsSearching(false)
          return true

        case 'done':
          setIsSearching(false)
          setStatusMessage(null)
          return true

        default:
          // Exhaustiveness check — fails to compile if a new event type is unhandled.
          event satisfies never
          return false
      }
    }

    run()
  }, [])

  return { isSearching, routes, statusMessage, error, startSearch, stopSearch }
}
