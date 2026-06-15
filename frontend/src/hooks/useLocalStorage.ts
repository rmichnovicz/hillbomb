import { useState, useCallback } from 'react'
import type { Route } from '../types'

const STORAGE_KEY = 'hillbomb_routes_v2'

function load(): Route[] {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return []
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function save(routes: Route[]): void {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(routes))
  } catch {
    // Quota exceeded or private mode — silently ignore
  }
}

export interface UseSavedRoutesReturn {
  savedRoutes: Route[]
  saveRoute: (route: Route) => void
  removeRoute: (routeId: string) => void
  isSaved: (routeId: string) => boolean
}

export function useSavedRoutes(): UseSavedRoutesReturn {
  const [savedRoutes, setSavedRoutes] = useState<Route[]>(() => load())

  const saveRoute = useCallback((route: Route) => {
    setSavedRoutes(prev => {
      if (prev.some(r => r.route_id === route.route_id)) return prev
      const next = [...prev, route]
      save(next)
      return next
    })
  }, [])

  const removeRoute = useCallback((routeId: string) => {
    setSavedRoutes(prev => {
      const next = prev.filter(r => r.route_id !== routeId)
      save(next)
      return next
    })
  }, [])

  const isSaved = useCallback(
    (routeId: string) => savedRoutes.some(r => r.route_id === routeId),
    [savedRoutes],
  )

  return { savedRoutes, saveRoute, removeRoute, isSaved }
}
