/**
 * Curated collections loader.
 *
 * Three-stage, mirroring how the tab is browsed: the index is fetched once when the
 * tab is first opened (small — no geometry), a *region* is fetched when the user
 * expands its folder (every spot in it, so the map can show the whole metro at once),
 * and an individual spot resolves from the same cache, so opening one after browsing
 * its region costs nothing.
 *
 * A whole region is ~200 KB of geometry across ~12 spots — small enough to pull in one
 * burst of parallel requests, which is why there's no bulk endpoint. `fetchSpot` dedups
 * both by cache and by in-flight promise, so expanding a region and immediately opening
 * a spot inside it issues one request, not two.
 *
 * There is no streaming here: collections are precomputed, so a spot arrives whole.
 */
import { useState, useCallback, useRef } from 'react'
import { collectionsIndexUrl, collectionSpotUrl } from '../api'
import type { CollectionCity, CollectionSpot, CollectionsIndex } from '../types'

/** The schema this client understands; the backend stamps it into the index. */
const SUPPORTED_VERSION = 1

export interface UseCollectionsReturn {
  cities: CollectionCity[]
  /** The expanded region folder, or null when the list is fully collapsed. */
  expandedCity: string | null
  /** Every spot in the expanded region, with routes, in index order. */
  citySpots: CollectionSpot[]
  /** The opened spot, with routes. Null when none is selected. */
  activeSpot: CollectionSpot | null
  isLoadingIndex: boolean
  isLoadingCity: boolean
  isLoadingSpot: boolean
  error: string | null
  /** Fetch the index. Safe to call repeatedly — only the first call hits the network. */
  loadIndex: () => void
  /** Expand a region (loading all its spots), or collapse it if already expanded. */
  toggleCity: (city: string) => void
  selectSpot: (slug: string) => void
  clearSpot: () => void
}

export function useCollections(): UseCollectionsReturn {
  const [cities, setCities] = useState<CollectionCity[]>([])
  const [expandedCity, setExpandedCity] = useState<string | null>(null)
  const [citySpots, setCitySpots] = useState<CollectionSpot[]>([])
  const [activeSpot, setActiveSpot] = useState<CollectionSpot | null>(null)
  const [isLoadingIndex, setIsLoadingIndex] = useState(false)
  const [isLoadingCity, setIsLoadingCity] = useState(false)
  const [isLoadingSpot, setIsLoadingSpot] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const indexRequested = useRef(false)
  const spotCache = useRef(new Map<string, CollectionSpot>())
  const inFlight = useRef(new Map<string, Promise<CollectionSpot>>())
  // Guard against a slow earlier request overwriting a later selection.
  const pendingSlug = useRef<string | null>(null)
  const pendingCity = useRef<string | null>(null)

  const loadIndex = useCallback(() => {
    if (indexRequested.current) return
    indexRequested.current = true
    setIsLoadingIndex(true)

    ;(async () => {
      try {
        const res = await fetch(collectionsIndexUrl())
        if (!res.ok) throw new Error(`Server error: ${res.status}`)
        const doc: CollectionsIndex = await res.json()
        if (doc.version !== SUPPORTED_VERSION) {
          throw new Error(
            `Collections data is version ${doc.version}, this app expects ${SUPPORTED_VERSION}. ` +
            `Rebuild with \`python -m backend.scripts.build_collections --clean\`.`
          )
        }
        setCities(doc.cities)
      } catch (err) {
        // Let the user retry: a failed index shouldn't be a permanent dead end.
        indexRequested.current = false
        setError(err instanceof Error ? err.message : 'Failed to load collections')
      } finally {
        setIsLoadingIndex(false)
      }
    })()
  }, [])

  /** One spot, from cache, from an in-flight request, or from the network. */
  const fetchSpot = useCallback((slug: string): Promise<CollectionSpot> => {
    const cached = spotCache.current.get(slug)
    if (cached) return Promise.resolve(cached)

    const pending = inFlight.current.get(slug)
    if (pending) return pending

    const request = (async () => {
      try {
        const res = await fetch(collectionSpotUrl(slug))
        if (!res.ok) throw new Error(`Server error: ${res.status}`)
        const spot: CollectionSpot = await res.json()
        spotCache.current.set(slug, spot)
        return spot
      } finally {
        inFlight.current.delete(slug)
      }
    })()
    inFlight.current.set(slug, request)
    return request
  }, [])

  const toggleCity = useCallback((city: string) => {
    // Collapsing: clear the region's routes off the map.
    if (expandedCity === city) {
      pendingCity.current = null
      setExpandedCity(null)
      setCitySpots([])
      setIsLoadingCity(false)
      return
    }

    const entry = cities.find(c => c.city === city)
    if (!entry) return

    setError(null)
    setExpandedCity(city)
    // A region and a spot are alternate map views; opening one closes the other.
    setActiveSpot(null)
    pendingSlug.current = null
    pendingCity.current = city

    const slugs = entry.spots.map(s => s.slug)
    const cached = slugs.map(s => spotCache.current.get(s))
    if (cached.every((s): s is CollectionSpot => !!s)) {
      setCitySpots(cached)
      setIsLoadingCity(false)
      return
    }

    setCitySpots([])
    setIsLoadingCity(true)
    ;(async () => {
      // allSettled, not all: one bad spot shouldn't blank the whole region.
      const settled = await Promise.allSettled(slugs.map(fetchSpot))
      if (pendingCity.current !== city) return
      const loaded = settled.flatMap(r => r.status === 'fulfilled' ? [r.value] : [])
      if (loaded.length === 0) setError(`Failed to load routes for ${city}`)
      setCitySpots(loaded)
      setIsLoadingCity(false)
    })()
  }, [cities, expandedCity, fetchSpot])

  const selectSpot = useCallback((slug: string) => {
    setError(null)

    const cached = spotCache.current.get(slug)
    if (cached) {
      pendingSlug.current = null
      setActiveSpot(cached)
      return
    }

    pendingSlug.current = slug
    setIsLoadingSpot(true)

    ;(async () => {
      try {
        const spot = await fetchSpot(slug)
        // A newer selection won the race — drop this result rather than clobber it.
        if (pendingSlug.current !== slug) return
        setActiveSpot(spot)
      } catch (err) {
        if (pendingSlug.current !== slug) return
        setError(err instanceof Error ? err.message : 'Failed to load spot')
      } finally {
        if (pendingSlug.current === slug) {
          pendingSlug.current = null
          setIsLoadingSpot(false)
        }
      }
    })()
  }, [fetchSpot])

  const clearSpot = useCallback(() => {
    pendingSlug.current = null
    setActiveSpot(null)
  }, [])

  return {
    cities, expandedCity, citySpots, activeSpot,
    isLoadingIndex, isLoadingCity, isLoadingSpot, error,
    loadIndex, toggleCity, selectSpot, clearSpot,
  }
}
