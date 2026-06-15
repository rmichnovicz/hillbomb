/**
 * MapLibre GL map with route overlays grouped by starting point.
 *
 * Active group: all routes solid + per-segment grade-colored line on best route.
 * Inactive groups: dashed, reduced opacity. Hovered group highlighted.
 * Start markers: clickable circles at each group's origin; highlighted when active.
 *
 * Grade color comes from gradeColor.ts paint expressions.
 */
import { useRef, useCallback, useEffect, useMemo } from 'react'
import Map, { Source, Layer, type MapRef } from 'react-map-gl/maplibre'
import type { Route } from '../../types'
import { GRADE_STOPS } from '../../utils/gradeColor'
import 'maplibre-gl/dist/maplibre-gl.css'

const MAP_STYLE = 'https://tiles.openfreemap.org/styles/liberty'

function gradeColorExpression() {
  const expr: unknown[] = ['step', ['abs', ['get', 'avg_grade_pct']]]
  expr.push(GRADE_STOPS[0].color)
  for (let i = 1; i < GRADE_STOPS.length; i++) {
    expr.push(GRADE_STOPS[i].grade * 100)
    expr.push(GRADE_STOPS[i].color)
  }
  return expr
}

function routeToFeature(r: Route) {
  return {
    type: 'Feature' as const,
    properties: {
      route_id: r.route_id,
      start_node_id: String(r.start_node_id),
      avg_grade_pct: r.metadata.avg_grade_pct,
    },
    geometry: r.geometry,
  }
}

interface HillbombMapProps {
  routes: Route[]
  activeGroupId: string | null
  activeRouteId: string | null
  hoveredGroupId: string | null
  hoveredRouteId: string | null
  onBoundsChange?: (bbox: [number, number, number, number]) => void
  onSelectGroup?: (startNodeId: string) => void
  onSelectRoute?: (routeId: string) => void
  scrubPosition?: number | null
}

export function HillbombMap({
  routes,
  activeGroupId,
  activeRouteId,
  hoveredGroupId,
  hoveredRouteId,
  onBoundsChange,
  onSelectGroup,
  onSelectRoute,
  scrubPosition,
}: HillbombMapProps) {
  const mapRef = useRef<MapRef>(null)

  const handleMoveEnd = useCallback(() => {
    if (!onBoundsChange || !mapRef.current) return
    const b = mapRef.current.getBounds()
    onBoundsChange([b.getSouth(), b.getWest(), b.getNorth(), b.getEast()])
  }, [onBoundsChange])

  // Zoom to fit all routes in the active group when selection changes
  useEffect(() => {
    if (!activeGroupId || !mapRef.current) return
    const groupRoutes = routes.filter(r => String(r.start_node_id) === activeGroupId)
    if (groupRoutes.length === 0) return
    const allCoords = groupRoutes.flatMap(r => r.geometry.coordinates)
    const lons = allCoords.map(c => c[0])
    const lats = allCoords.map(c => c[1])
    mapRef.current.fitBounds(
      [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
      { padding: 80, duration: 600 },
    )
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeGroupId]) // intentionally exclude routes: don't re-zoom as routes stream in

  // Scrub pin: interpolate position along active route geometry
  const scrubCoord = (() => {
    if (scrubPosition == null || !activeRouteId) return null
    const route = routes.find(r => r.route_id === activeRouteId)
    if (!route) return null
    const coords = route.geometry.coordinates
    if (coords.length < 2) return null
    const idx = Math.min(Math.floor(scrubPosition * (coords.length - 1)), coords.length - 2)
    const t = (scrubPosition * (coords.length - 1)) - idx
    const [lon1, lat1] = coords[idx]
    const [lon2, lat2] = coords[idx + 1]
    return [lon1 + (lon2 - lon1) * t, lat1 + (lat2 - lat1) * t] as [number, number]
  })()

  // Inactive routes: not in active group
  const inactiveFeatures = useMemo(() =>
    routes
      .filter(r => String(r.start_node_id) !== (activeGroupId ?? ''))
      .map(routeToFeature),
    [routes, activeGroupId],
  )

  // Glow: hoveredRouteId takes priority over hoveredGroupId
  const hoveredGlowFeatures = useMemo(() => {
    if (hoveredRouteId) {
      const r = routes.find(r => r.route_id === hoveredRouteId)
      return r ? [routeToFeature(r)] : []
    }
    if (hoveredGroupId) {
      return routes
        .filter(r => String(r.start_node_id) === hoveredGroupId)
        .map(routeToFeature)
    }
    return []
  }, [routes, hoveredGroupId, hoveredRouteId])

  // Active group routes excluding the selected one (which gets its own highlighted layer)
  const activeGroupSecondaryFeatures = useMemo(() => {
    if (!activeGroupId) return []
    return routes
      .filter(r => String(r.start_node_id) === activeGroupId && r.route_id !== activeRouteId)
      .map(routeToFeature)
  }, [routes, activeGroupId, activeRouteId])

  const activeRoute = routes.find(r => r.route_id === activeRouteId)

  // Per-segment features for the selected route so each segment gets its own grade color
  const activeRouteSegmentFeatures = useMemo(() => {
    if (!activeRoute) return []
    const coords = activeRoute.geometry.coordinates
    const elevs = activeRoute.elevations
    const dists = activeRoute.segment_distances
    if (!elevs || !dists || coords.length < 2) return []
    const features = []
    for (let i = 0; i < coords.length - 1; i++) {
      const dist = dists[i] || 1
      const gradePct = ((elevs[i + 1] - elevs[i]) / dist) * 100
      features.push({
        type: 'Feature' as const,
        properties: { avg_grade_pct: gradePct },
        geometry: {
          type: 'LineString' as const,
          coordinates: [coords[i], coords[i + 1]],
        },
      })
    }
    return features
  }, [activeRoute])

  // One start-point marker per unique group, with is_active flag for styling
  const startMarkerFeatures = useMemo(() => {
    const seen = new Set<string>()
    return routes
      .filter(r => {
        const key = String(r.start_node_id)
        if (seen.has(key)) return false
        seen.add(key)
        return true
      })
      .map(r => ({
        type: 'Feature' as const,
        properties: {
          start_node_id: String(r.start_node_id),
          is_active: String(r.start_node_id) === activeGroupId ? 1 : 0,
        },
        geometry: {
          type: 'Point' as const,
          coordinates: r.geometry.coordinates[0],
        },
      }))
  }, [routes, activeGroupId])

  const inactiveOpacity = activeGroupId ? 0.2 : 0.45

  return (
    <Map
      ref={mapRef}
      mapStyle={MAP_STYLE}
      initialViewState={{ longitude: -122.44, latitude: 37.76, zoom: 13 }}
      style={{ width: '100%', height: '100%' }}
      onMoveEnd={handleMoveEnd}
      interactiveLayerIds={['start-markers-circle', 'inactive-route-lines', 'active-group-lines', 'hovered-glow-line']}
      onClick={e => {
        if (!mapRef.current) return
        // Start markers select the group
        const markerHits = mapRef.current.queryRenderedFeatures(e.point, {
          layers: ['start-markers-circle'],
        })
        if (markerHits.length > 0) {
          const id = markerHits[0].properties?.start_node_id
          if (id) { onSelectGroup?.(String(id)); return }
        }
        // Route line click selects both the group and the specific route
        const lineHits = mapRef.current.queryRenderedFeatures(e.point, {
          layers: ['inactive-route-lines', 'active-group-lines', 'hovered-glow-line'],
        })
        if (lineHits.length > 0) {
          const props = lineHits[0].properties
          if (props?.start_node_id) onSelectGroup?.(String(props.start_node_id))
          if (props?.route_id) onSelectRoute?.(String(props.route_id))
        }
      }}
    >
      {/* Inactive routes */}
      {inactiveFeatures.length > 0 && (
        <Source
          id="inactive-routes"
          type="geojson"
          data={{ type: 'FeatureCollection', features: inactiveFeatures }}
        >
          <Layer
            id="inactive-route-lines"
            type="line"
            paint={{
              'line-color': gradeColorExpression() as unknown as string,
              'line-width': 3,
              'line-opacity': inactiveOpacity,
              'line-dasharray': [3, 3],
            }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
        </Source>
      )}

      {/* Active group secondary routes (solid but thinner than best) */}
      {activeGroupSecondaryFeatures.length > 0 && (
        <Source
          id="active-group"
          type="geojson"
          data={{ type: 'FeatureCollection', features: activeGroupSecondaryFeatures }}
        >
          <Layer
            id="active-group-lines"
            type="line"
            paint={{
              'line-color': gradeColorExpression() as unknown as string,
              'line-width': 4,
              'line-opacity': 0.75,
            }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
        </Source>
      )}

      {/* Selected route — white halo on full path, then per-segment grade colors on top */}
      {activeRoute && (
        <Source
          id="active-route-halo"
          type="geojson"
          data={{ type: 'Feature', properties: {}, geometry: activeRoute.geometry }}
        >
          <Layer
            id="active-route-bg"
            type="line"
            paint={{ 'line-color': '#fff', 'line-width': 9, 'line-opacity': 0.85 }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
        </Source>
      )}
      {activeRouteSegmentFeatures.length > 0 && (
        <Source
          id="active-route"
          type="geojson"
          data={{ type: 'FeatureCollection', features: activeRouteSegmentFeatures }}
        >
          <Layer
            id="active-route-line"
            type="line"
            paint={{
              'line-color': gradeColorExpression() as unknown as string,
              'line-width': 6,
            }}
            layout={{ 'line-join': 'round', 'line-cap': 'butt' }}
          />
        </Source>
      )}

      {/* Hover glow — renders above all route lines so it shows on inactive, secondary, and active routes alike */}
      {hoveredGlowFeatures.length > 0 && (
        <Source
          id="hovered-glow"
          type="geojson"
          data={{ type: 'FeatureCollection', features: hoveredGlowFeatures }}
        >
          <Layer
            id="hovered-glow-outer"
            type="line"
            paint={{ 'line-color': '#fff', 'line-width': 20, 'line-opacity': 0.10 }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
          <Layer
            id="hovered-glow-mid"
            type="line"
            paint={{ 'line-color': '#fff', 'line-width': 12, 'line-opacity': 0.22 }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
          <Layer
            id="hovered-glow-inner"
            type="line"
            paint={{ 'line-color': '#fff', 'line-width': 7, 'line-opacity': 0.45 }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
          <Layer
            id="hovered-glow-line"
            type="line"
            paint={{
              'line-color': gradeColorExpression() as unknown as string,
              'line-width': 4,
            }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
        </Source>
      )}

      {/* Start point markers */}
      {startMarkerFeatures.length > 0 && (
        <Source
          id="start-markers"
          type="geojson"
          data={{ type: 'FeatureCollection', features: startMarkerFeatures }}
        >
          <Layer
            id="start-markers-circle"
            type="circle"
            paint={{
              'circle-radius': ['case', ['==', ['get', 'is_active'], 1], 10, 7],
              'circle-color': ['case', ['==', ['get', 'is_active'], 1], '#ef4444', '#3b82f6'],
              'circle-stroke-width': 2,
              'circle-stroke-color': '#fff',
            }}
          />
        </Source>
      )}

      {/* Scrub pin */}
      {scrubCoord && (
        <Source
          id="scrub-pin"
          type="geojson"
          data={{ type: 'Feature', properties: {}, geometry: { type: 'Point', coordinates: scrubCoord } }}
        >
          <Layer
            id="scrub-pin-circle"
            type="circle"
            paint={{
              'circle-radius': 8,
              'circle-color': '#fff',
              'circle-stroke-width': 3,
              'circle-stroke-color': '#3b82f6',
            }}
          />
        </Source>
      )}
    </Map>
  )
}
