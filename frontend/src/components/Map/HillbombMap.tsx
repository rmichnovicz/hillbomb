/**
 * MapLibre GL map with route overlays grouped by starting point.
 *
 * Active group: all routes solid + per-segment grade-colored line on best route.
 * Inactive groups: dashed, reduced opacity. Hovered group highlighted.
 * Start markers: clickable circles at each group's origin; highlighted when active.
 *
 * Grade color comes from gradeColor.ts paint expressions.
 */
import { useRef, useCallback, useEffect, useMemo, useState } from 'react'
import Map, { Source, Layer, type MapRef, type StyleSpecification } from 'react-map-gl/maplibre'
import type { Map as MapLibreMap } from 'maplibre-gl'
import type { Route } from '../../types'
import { GRADE_STOPS } from '../../utils/gradeColor'
import 'maplibre-gl/dist/maplibre-gl.css'

const STREET_STYLE = 'https://tiles.openfreemap.org/styles/liberty'

// Esri hybrid: World Imagery base + reference overlays for place/road labels.
// Raster-only, no API key required. Verify Esri usage terms before production.
const ESRI_ATTRIBUTION =
  'Imagery &copy; <a href="https://www.esri.com/">Esri</a>, Maxar, Earthstar Geographics'
const SATELLITE_STYLE: StyleSpecification = {
  version: 8,
  sources: {
    'esri-imagery': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
      attribution: ESRI_ATTRIBUTION,
    },
    'esri-transportation': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Transportation/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
    },
    'esri-places': {
      type: 'raster',
      tiles: ['https://server.arcgisonline.com/ArcGIS/rest/services/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}'],
      tileSize: 256,
    },
  },
  layers: [
    { id: 'esri-imagery', type: 'raster', source: 'esri-imagery' },
    { id: 'esri-transportation', type: 'raster', source: 'esri-transportation' },
    { id: 'esri-places', type: 'raster', source: 'esri-places' },
  ],
}

type MapStyleMode = 'street' | 'satellite'

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

function haversineM([lon1, lat1]: number[], [lon2, lat2]: number[]) {
  const R = 6371000, toR = Math.PI / 180
  const dφ = (lat2 - lat1) * toR, dλ = (lon2 - lon1) * toR
  const a = Math.sin(dφ / 2) ** 2 + Math.cos(lat1 * toR) * Math.cos(lat2 * toR) * Math.sin(dλ / 2) ** 2
  return 2 * R * Math.asin(Math.sqrt(a))
}

// Compass bearing (deg clockwise from north) of the descent's first ~30m, so the
// start chevron points the way you'd drop in. Smoothed past the first vertex to
// avoid noise from a tiny opening segment.
function dropInBearing(coords: number[][]): number {
  if (!coords || coords.length < 2) return 0
  let target = coords[coords.length - 1], acc = 0
  for (let i = 1; i < coords.length; i++) {
    acc += haversineM(coords[i - 1], coords[i])
    if (acc >= 30) { target = coords[i]; break }
  }
  const [lon1, lat1] = coords[0], [lon2, lat2] = target
  const φ1 = lat1 * Math.PI / 180, φ2 = lat2 * Math.PI / 180
  const Δλ = (lon2 - lon1) * Math.PI / 180
  const y = Math.sin(Δλ) * Math.cos(φ2)
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ)
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}

// Render a chevron marker to an ImageData for map.addImage. Drawn pointing up
// (north); the symbol layer rotates it by each start's drop-in bearing.
function chevronImage(opts: { color: string; sizePx: number; active?: boolean }): ImageData {
  const dpr = 2, S = opts.sizePx * dpr
  const c = document.createElement('canvas')
  c.width = S; c.height = S
  const ctx = c.getContext('2d')!
  ctx.scale(dpr, dpr)
  const w = opts.sizePx
  ctx.lineCap = 'round'; ctx.lineJoin = 'round'
  // Chevron pointing up, with a white halo for contrast. The active marker is
  // just a bolder version in the active color — no disc behind it.
  const drawChevron = (lineWidth: number, color: string) => {
    ctx.strokeStyle = color; ctx.lineWidth = lineWidth
    ctx.beginPath()
    ctx.moveTo(w * 0.25, w * 0.64); ctx.lineTo(w * 0.5, w * 0.36); ctx.lineTo(w * 0.75, w * 0.64)
    ctx.stroke()
  }
  drawChevron(opts.active ? 6 : 5, '#fff')
  drawChevron(opts.active ? 4 : 3, opts.color)
  return ctx.getImageData(0, 0, S, S)
}

// Red octagon "STOP" sign for stop-sign nodes on the selected route.
function stopSignImage(sizePx: number): ImageData {
  const dpr = 2, S = sizePx * dpr
  const c = document.createElement('canvas')
  c.width = S; c.height = S
  const ctx = c.getContext('2d')!
  ctx.scale(dpr, dpr)
  const w = sizePx, cx = w / 2, cy = w / 2, r = w / 2 - 1.5
  ctx.beginPath()
  for (let i = 0; i < 8; i++) {
    // π/8 offset gives flat top and bottom edges (a road-sign octagon).
    const a = Math.PI / 8 + i * Math.PI / 4
    const x = cx + r * Math.cos(a), y = cy + r * Math.sin(a)
    i ? ctx.lineTo(x, y) : ctx.moveTo(x, y)
  }
  ctx.closePath()
  ctx.fillStyle = '#d01e2f'; ctx.fill()
  ctx.lineWidth = 1.5; ctx.strokeStyle = '#fff'; ctx.stroke()
  ctx.fillStyle = '#fff'
  ctx.font = `bold ${Math.round(w * 0.3)}px sans-serif`
  ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
  ctx.fillText('STOP', cx, cy + 0.5)
  return ctx.getImageData(0, 0, S, S)
}

// Three-light traffic-signal head for traffic_signals nodes.
function trafficSignalImage(sizePx: number): ImageData {
  const dpr = 2, S = sizePx * dpr
  const c = document.createElement('canvas')
  c.width = S; c.height = S
  const ctx = c.getContext('2d')!
  ctx.scale(dpr, dpr)
  const w = sizePx
  const hw = w * 0.46, hh = w * 0.92
  const x0 = (w - hw) / 2, y0 = (w - hh) / 2, rad = hw * 0.22
  // Rounded-rect housing
  ctx.beginPath()
  ctx.moveTo(x0 + rad, y0)
  ctx.arcTo(x0 + hw, y0, x0 + hw, y0 + hh, rad)
  ctx.arcTo(x0 + hw, y0 + hh, x0, y0 + hh, rad)
  ctx.arcTo(x0, y0 + hh, x0, y0, rad)
  ctx.arcTo(x0, y0, x0 + hw, y0, rad)
  ctx.closePath()
  ctx.fillStyle = '#1f2937'; ctx.fill()
  ctx.lineWidth = 1.5; ctx.strokeStyle = '#fff'; ctx.stroke()
  const colors = ['#ef4444', '#f59e0b', '#22c55e']
  const lr = hw * 0.26
  for (let i = 0; i < 3; i++) {
    ctx.beginPath()
    ctx.arc(x0 + hw / 2, y0 + hh * (0.22 + i * 0.28), lr, 0, Math.PI * 2)
    ctx.fillStyle = colors[i]; ctx.fill()
  }
  return ctx.getImageData(0, 0, S, S)
}

// Each entry knows how to (re)build its own ImageData. Registered on load and on
// styleimagemissing so the icons survive a base-layer (street/satellite) swap.
const MARKER_IMAGES: { id: string; make: () => ImageData }[] = [
  { id: 'start-chevron', make: () => chevronImage({ color: '#7c5cd6', sizePx: 22 }) },
  { id: 'start-chevron-active', make: () => chevronImage({ color: '#f0436e', sizePx: 30, active: true }) },
  { id: 'stop-sign', make: () => stopSignImage(20) },
  { id: 'traffic-signal', make: () => trafficSignalImage(20) },
]
const MARKER_IMAGE_IDS = new Set(MARKER_IMAGES.map(m => m.id))

function ensureMarkerImages(map: MapLibreMap) {
  for (const { id, make } of MARKER_IMAGES) {
    if (!map.hasImage(id)) map.addImage(id, make(), { pixelRatio: 2 })
  }
}

interface HillbombMapProps {
  routes: Route[]
  activeGroupId: string | null
  activeRouteId: string | null
  hoveredGroupId: string | null
  hoveredRouteId: string | null
  routeOrder?: Map<string, number>
  onBoundsChange?: (bbox: [number, number, number, number]) => void
  onSelectGroup?: (startNodeId: string) => void
  onSelectPath?: (routeId: string, startNodeId: string) => void
  scrubPosition?: number | null
}

export function HillbombMap({
  routes,
  activeGroupId,
  activeRouteId,
  hoveredGroupId,
  hoveredRouteId,
  routeOrder,
  onBoundsChange,
  onSelectGroup,
  onSelectPath,
  scrubPosition,
}: HillbombMapProps) {
  const mapRef = useRef<MapRef>(null)
  const [styleMode, setStyleMode] = useState<MapStyleMode>('street')

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

  // Stop signs / traffic signals on the selected route (start and end included).
  const activeRouteStopFeatures = useMemo(() => {
    if (!activeRoute?.stops?.length) return []
    return activeRoute.stops.map((s, i) => ({
      type: 'Feature' as const,
      properties: { kind: s.type, idx: i },
      geometry: { type: 'Point' as const, coordinates: s.coord },
    }))
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
          bearing: dropInBearing(r.geometry.coordinates),
        },
        geometry: {
          type: 'Point' as const,
          coordinates: r.geometry.coordinates[0],
        },
      }))
  }, [routes, activeGroupId])

  // Inactive routes render at full opacity so overlapping dashes don't compound
  // into darker blobs in dense areas. "Recede when a group is selected" is
  // encoded via lighter color, not alpha (alpha would reintroduce stacking).
  const isFaded = !!activeGroupId
  const inactiveLineColor = isFaded ? '#c4b5fd' : '#a78bfa'
  const inactiveCasingColor = isFaded ? '#94a3b8' : '#475569'

  return (
    <Map
      ref={mapRef}
      mapStyle={styleMode === 'satellite' ? SATELLITE_STYLE : STREET_STYLE}
      initialViewState={{ longitude: -122.44, latitude: 37.76, zoom: 13 }}
      style={{ width: '100%', height: '100%' }}
      onMoveEnd={handleMoveEnd}
      // Register marker icons proactively. `styleimagemissing` alone is unreliable:
      // MapLibre fires it once per missing id, and if the symbol layer first renders
      // before this React handler is attached, that single fire is missed and the
      // icons (start chevrons, stop/signal markers) never appear. `styledata` fires
      // when the style spec is ready and again after every base-layer (street/
      // satellite) swap — independent of whether the base tiles have loaded — so the
      // images are always present before the symbol layers draw. onLoad covers the
      // common case promptly; onStyleImageMissing remains a backstop.
      onLoad={e => ensureMarkerImages(e.target)}
      onStyleData={e => ensureMarkerImages(e.target)}
      onStyleImageMissing={e => {
        if (MARKER_IMAGE_IDS.has(e.id)) ensureMarkerImages(e.target)
      }}
      interactiveLayerIds={['start-markers-symbol', 'inactive-route-lines', 'active-group-lines', 'hovered-glow-line']}
      onClick={e => {
        if (!mapRef.current) return
        const map = mapRef.current
        // queryRenderedFeatures throws if asked for a layer not currently in the
        // style. The route layers mount conditionally (active group, hover), so
        // only query the ones that exist right now.
        const existing = (ids: string[]) => ids.filter(id => map.getLayer(id))
        // Start markers select the group (auto-selects its best route)
        const markerLayers = existing(['start-markers-symbol'])
        const markerHits = markerLayers.length
          ? map.queryRenderedFeatures(e.point, { layers: markerLayers })
          : []
        if (markerHits.length > 0) {
          const id = markerHits[0].properties?.start_node_id
          if (id) { onSelectGroup?.(String(id)); return }
        }
        // Route lines are thin; widen the hit area with a small pixel box so the
        // whole path is easy to click, not just the start marker.
        const r = 6
        const box: [[number, number], [number, number]] = [
          [e.point.x - r, e.point.y - r],
          [e.point.x + r, e.point.y + r],
        ]
        const lineLayers = existing(['inactive-route-lines', 'active-group-lines', 'hovered-glow-line'])
        const lineHits = lineLayers.length
          ? map.queryRenderedFeatures(box, { layers: lineLayers })
          : []
        // Among overlapping routes, pick the one ranked first in the current sort.
        let bestRank = Infinity
        let bestRouteId: string | null = null
        let bestStartNodeId: string | null = null
        for (const f of lineHits) {
          const rid = f.properties?.route_id
          if (!rid) continue
          const rank = routeOrder?.get(String(rid)) ?? Infinity
          if (bestRouteId === null || rank < bestRank) {
            bestRank = rank
            bestRouteId = String(rid)
            bestStartNodeId = f.properties?.start_node_id != null ? String(f.properties.start_node_id) : null
          }
        }
        if (bestRouteId && bestStartNodeId) onSelectPath?.(bestRouteId, bestStartNodeId)
      }}
    >
      {/* Inactive routes */}
      {inactiveFeatures.length > 0 && (
        <Source
          id="inactive-routes"
          type="geojson"
          data={{ type: 'FeatureCollection', features: inactiveFeatures }}
        >
          {/* Casing beneath the dashes so they read against light map tiles.
              Opaque so overlapping casings don't stack into dark blobs. */}
          <Layer
            id="inactive-route-casing"
            type="line"
            paint={{
              'line-color': inactiveCasingColor,
              'line-width': 5,
            }}
            layout={{ 'line-join': 'round', 'line-cap': 'round' }}
          />
          <Layer
            id="inactive-route-lines"
            type="line"
            paint={{
              // Flat violet — inactive routes are de-emphasized and must not be
              // mistaken for the grade ramp (green→red) used on the selected route.
              // Full opacity (no line-opacity) so overlaps don't compound.
              'line-color': inactiveLineColor,
              'line-width': 3.5,
              'line-dasharray': [2, 1.5],
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
              // Muted neutral so only the selected route carries grade color
              'line-color': '#94a3b8',
              'line-width': 3,
              'line-opacity': 0.65,
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
            id="start-markers-symbol"
            type="symbol"
            layout={{
              'icon-image': ['case', ['==', ['get', 'is_active'], 1], 'start-chevron-active', 'start-chevron'],
              'icon-rotate': ['get', 'bearing'],
              'icon-rotation-alignment': 'map',
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'icon-anchor': 'center',
            }}
          />
        </Source>
      )}

      {/* Stop signs / traffic signals on the selected route */}
      {activeRouteStopFeatures.length > 0 && (
        <Source
          id="active-route-stops"
          type="geojson"
          data={{ type: 'FeatureCollection', features: activeRouteStopFeatures }}
        >
          <Layer
            id="active-route-stops-symbol"
            type="symbol"
            layout={{
              'icon-image': ['case', ['==', ['get', 'kind'], 'traffic_signal'], 'traffic-signal', 'stop-sign'],
              'icon-allow-overlap': true,
              'icon-ignore-placement': true,
              'icon-anchor': 'center',
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

      {/* Street / Satellite toggle — top-right corner */}
      <div
        style={{
          position: 'absolute',
          top: 10,
          right: 10,
          display: 'flex',
          borderRadius: 6,
          overflow: 'hidden',
          boxShadow: '0 1px 4px rgba(0,0,0,0.3)',
          fontSize: 13,
          fontWeight: 600,
          zIndex: 1,
        }}
        role="group"
        aria-label="Map base layer"
      >
        {(['street', 'satellite'] as const).map(mode => (
          <button
            key={mode}
            type="button"
            onClick={() => setStyleMode(mode)}
            aria-pressed={styleMode === mode}
            style={{
              padding: '6px 12px',
              border: 'none',
              cursor: 'pointer',
              background: styleMode === mode ? '#3b82f6' : '#fff',
              color: styleMode === mode ? '#fff' : '#1f2937',
            }}
          >
            {mode === 'street' ? 'Street' : 'Satellite'}
          </button>
        ))}
      </div>
    </Map>
  )
}
