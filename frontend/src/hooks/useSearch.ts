/**
 * SSE streaming hook.
 *
 * Uses fetch() + ReadableStream instead of EventSource because the backend
 * endpoint is POST /search — EventSource is GET-only.
 * AbortController handles the stop button and new-search cancellation.
 */
import { useState, useRef, useCallback } from 'react'
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
      let doneSeen = false
      let errorSeen = false
      try {
        const response = await fetch('/search', {
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

        while (true) {
          const { done, value } = await reader.read()
          if (done) break
          buffer += decoder.decode(value, { stream: true })

          // SSE events are delimited by double newlines
          const parts = buffer.split('\n\n')
          buffer = parts.pop() ?? ''

          for (const part of parts) {
            for (const line of part.split('\n')) {
              const event = parseSSELine(line)
              if (!event) continue
              handleEvent(event, () => { doneSeen = true }, () => { errorSeen = true })
            }
          }
        }

        if (!doneSeen && !errorSeen) {
          setError('Connection lost — results may be incomplete.')
          setIsSearching(false)
        }
      } catch (err) {
        if (err instanceof Error && err.name === 'AbortError') return
        setError(err instanceof Error ? err.message : 'Unknown error')
        setIsSearching(false)
      }
    }

    function handleEvent(event: SSEEvent, onDone?: () => void, onError?: () => void) {
      switch (event.type) {
        case 'status':
          setStatusMessage(event.message)
          break

        case 'route': {
          const newRoute: Route = {
            route_id: event.route_id,
            start_node_id: event.start_node_id,
            geometry: event.geometry,
            metadata: event.metadata,
            elevations: event.elevations,
            segment_distances: event.segment_distances,
            flow_score: event.flow_score,
            flow_grade: event.flow_grade,
            surface_pcts: event.surface_pcts,
            speed_profile: event.speed_profile,
            top_speed_kmh: event.top_speed_kmh,
            avg_speed_kmh: event.avg_speed_kmh,
          }
          setRoutes(prev =>
            [...prev, newRoute].sort((a, b) => b.top_speed_kmh - a.top_speed_kmh)
          )
          break
        }

        case 'error':
          onError?.()
          setError(event.message)
          setIsSearching(false)
          abortRef.current?.abort()
          break

        case 'done':
          onDone?.()
          setIsSearching(false)
          setStatusMessage(null)
          break
      }
    }

    run()
  }, [])

  return { isSearching, routes, statusMessage, error, startSearch, stopSearch }
}
