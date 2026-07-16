/**
 * Curated collections loader.
 *
 * Two-stage on purpose, mirroring the backend split: the index is fetched once when
 * the tab is first opened (small — no geometry), and a spot's routes are fetched only
 * when the user picks it. Fetched spots are memoized, so revisiting one is instant.
 *
 * There is no streaming here: collections are precomputed, so a spot arrives whole.
 */
import { useState, useCallback, useRef } from 'react'
import type { CollectionCity, CollectionSpot, CollectionsIndex } from '../types'

/** The schema this client understands; the backend stamps it into the index. */
const SUPPORTED_VERSION = 1

export interface UseCollectionsReturn {
  cities: CollectionCity[]
  /** The opened spot, with routes. Null when none is selected. */
  activeSpot: CollectionSpot | null
  isLoadingIndex: boolean
  isLoadingSpot: boolean
  error: string | null
  /** Fetch the index. Safe to call repeatedly — only the first call hits the network. */
  loadIndex: () => void
  selectSpot: (slug: string) => void
  clearSpot: () => void
}

export function useCollections(): UseCollectionsReturn {
  const [cities, setCities] = useState<CollectionCity[]>([])
  const [activeSpot, setActiveSpot] = useState<CollectionSpot | null>(null)
  const [isLoadingIndex, setIsLoadingIndex] = useState(false)
  const [isLoadingSpot, setIsLoadingSpot] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const indexRequested = useRef(false)
  const spotCache = useRef(new Map<string, CollectionSpot>())
  // Guards against a slow earlier request overwriting a later selection.
  const pendingSlug = useRef<string | null>(null)

  const loadIndex = useCallback(() => {
    if (indexRequested.current) return
    indexRequested.current = true
    setIsLoadingIndex(true)

    ;(async () => {
      try {
        const res = await fetch('/collections')
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
        const res = await fetch(`/collections/${slug}`)
        if (!res.ok) throw new Error(`Server error: ${res.status}`)
        const spot: CollectionSpot = await res.json()
        spotCache.current.set(slug, spot)
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
  }, [])

  const clearSpot = useCallback(() => {
    pendingSlug.current = null
    setActiveSpot(null)
  }, [])

  return { cities, activeSpot, isLoadingIndex, isLoadingSpot, error, loadIndex, selectSpot, clearSpot }
}
