/**
 * MapLibre GL map with route overlays grouped by starting point.
 *
 * Active group: all routes solid + per-segment grade-colored line on best route.
 * Inactive groups: dashed, reduced opacity. Hovered group highlighted.
 * Start markers: clickable chevrons, one per distinct descent direction out of a
 * start node (a summit can drop two ways), pointing the way you'd drop in.
 *
 * Grade color comes from gradeColor.ts paint expressions.
 */
import { useRef, useCallback, useEffect, useMemo, useState } from 'react'
import Map, { Source, Layer, type MapRef, type StyleSpecification } from 'react-map-gl/maplibre'
import type { Map as MapLibreMap } from 'maplibre-gl'
import type { Route } from '../../types'
import { GRADE_STOPS } from '../../utils/gradeColor'
import { patchStyleFilters } from '../../utils/styleFilters'
import 'maplibre-gl/dist/maplibre-gl.css'

/** Map left uncovered when a fit has to reserve space for the bottom sheet. */
const MIN_VISIBLE_STRIP_PX = 80

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

// Walk `meters` along a polyline and return the vertex reached, or the last one if the
// line is shorter. Vertex-granular on purpose: no interpolation, so the returned point
// is always on the route.
function vertexAtDistance(coords: number[][], meters: number): number[] {
  let acc = 0
  for (let i = 1; i < coords.length; i++) {
    acc += haversineM(coords[i - 1], coords[i])
    if (acc >= meters) return coords[i]
  }
  return coords[coords.length - 1]
}

// Compass bearing (deg clockwise from north) of the descent's first ~30m, so the
// start chevron points the way you'd drop in. Smoothed past the first vertex to
// avoid noise from a tiny opening segment.
function dropInBearing(coords: number[][]): number {
  if (!coords || coords.length < 2) return 0
  const target = vertexAtDistance(coords, 30)
  const [lon1, lat1] = coords[0], [lon2, lat2] = target
  const φ1 = lat1 * Math.PI / 180, φ2 = lat2 * Math.PI / 180
  const Δλ = (lon2 - lon1) * Math.PI / 180
  const y = Math.sin(Δλ) * Math.cos(φ2)
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ)
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}

// Smallest angle between two compass bearings, so 350° and 10° read as 20° apart.
function bearingGapDeg(a: number, b: number): number {
  const d = Math.abs(a - b) % 360
  return d > 180 ? 360 - d : d
}

// Two descents can leave one node in opposite directions: the Hawk Hill summit drops
// west toward Point Bonita and east toward the bridge, both off node 12604582833.
// Keyed on start node alone, they collapsed into a single chevron pointing whichever
// way the higher-ranked route went, and the other descent got no marker at all. Real
// data splits cleanly here — the summits that share a node depart either ~0° apart
// (same drop, diverging later, one marker is right) or 113–180° apart.
const DISTINCT_DIRECTION_DEG = 45

// Markers sit this far down their own line rather than exactly on the start node. Two
// descents off one summit share that node, so anchoring both there would stack the
// chevrons on the same pixel — still visually merged, and only the top one clickable,
// since the click handler takes the first hit. Nudging each onto its own line separates
// them once you're zoomed in enough to tell the two descents apart anyway.
const MARKER_OFFSET_M = 25

/**
 * One start marker per distinct descent direction, best-ranked route per direction.
 *
 * `routes` must be in rank order; the first route seen for a direction is the one the
 * marker selects when clicked.
 */
export function buildStartMarkerFeatures(routes: Route[], activeGroupId: string | null) {
  const claimed: { groupId: string; bearing: number }[] = []
  const features = []
  for (const r of routes) {
    const coords = r.geometry.coordinates
    const groupId = String(r.start_node_id)
    const bearing = dropInBearing(coords)
    const merged = claimed.some(
      c => c.groupId === groupId && bearingGapDeg(c.bearing, bearing) < DISTINCT_DIRECTION_DEG,
    )
    if (merged) continue
    claimed.push({ groupId, bearing })
    features.push({
      type: 'Feature' as const,
      properties: {
        start_node_id: groupId,
        route_id: r.route_id,
        is_active: groupId === activeGroupId ? 1 : 0,
        bearing,
      },
      geometry: {
        type: 'Point' as const,
        coordinates: vertexAtDistance(coords, MARKER_OFFSET_M),
      },
    })
  }
  return features
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

/**
 * Fetch the street style and hand back a filter-patched copy, or the bare URL if
 * that fails for any reason. See utils/styleFilters.ts for what is patched and why.
 *
 * The patch has to happen *before* MapLibre sees the style. Doing it after —
 * `setFilter` from an `onStyleData`/`onLoad` handler — is both too late (the
 * first tiles have already been parsed against the unpatched filters, which is
 * when the warnings fire) and actively harmful: calling `setFilter` from inside
 * `styledata` during style init leaves the map with a loaded style, no source
 * caches, and nothing on screen. So we fetch the JSON ourselves, rewrite it, and
 * pass an object rather than a URL. MapLibre would have made this exact request
 * anyway, so it costs one cache hit, not one round trip.
 *
 * Falling back to the URL keeps a network hiccup from costing us the base map —
 * the warnings come back, the map still works.
 */
function useStreetStyle(): string | StyleSpecification | null {
  const [style, setStyle] = useState<string | StyleSpecification | null>(null)
  useEffect(() => {
    let cancelled = false
    fetch(STREET_STYLE)
      .then(r => (r.ok ? r.json() : Promise.reject(new Error(String(r.status)))))
      .then((spec: StyleSpecification) => { if (!cancelled) setStyle(patchStyleFilters(spec)) })
      .catch(() => { if (!cancelled) setStyle(STREET_STYLE) })
    return () => { cancelled = true }
  }, [])
  return style
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
  /**
   * Fit the viewport around *every* displayed route. Fires once per distinct
   * non-null value, so the caller controls when — a collections region opening,
   * say — without the map re-zooming on every routes update. Null disables it.
   */
  fitAllKey?: string | null
  /**
   * Fraction of the map's height hidden behind UI along the bottom edge — on mobile,
   * the bottom sheet. Fits reserve that much extra space so the routes they just
   * framed don't land underneath it.
   *
   * Read from the live container height at fit time rather than passed in pixels, so
   * it survives rotation and viewport changes without the caller tracking them.
   */
  fitBottomInset?: number
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
  fitAllKey = null,
  fitBottomInset = 0,
}: HillbombMapProps) {
  const mapRef = useRef<MapRef>(null)
  const [styleMode, setStyleMode] = useState<MapStyleMode>('street')
  const streetStyle = useStreetStyle()
  const lastFitAllKey = useRef<string | null>(null)

  // Hand the MapLibre instance to the e2e suite. Where the viewport ended up is the
  // only way to tell "fitted to the region" from "still on the hardcoded default",
  // and that difference is invisible in a screenshot taken from the default's own
  // city. Nothing in the app reads this.
  //
  // A callback ref, not an effect: react-map-gl publishes the handle through
  // `useImperativeHandle` on a *later* render than the one that mounts <Map>, so
  // an effect keyed on mount — or on anything else this component knows about —
  // reads a ref that is still null. The callback fires when the handle actually
  // attaches. Going through the ref rather than `onLoad` keeps the handle from
  // waiting on tiles.
  const attachMapRef = useCallback((ref: MapRef | null) => {
    mapRef.current = ref
    const map = ref?.getMap()
    if (map) {
      (map.getContainer() as HTMLElement & { _hillbombMap?: MapLibreMap })._hillbombMap = map
    }
  }, [])

  /**
   * Uniform padding, plus whatever the bottom sheet is covering.
   *
   * Clamped: MapLibre rejects padding that leaves no viewport, and an open sheet at
   * 65dvh plus base padding gets close enough to that on a short phone to matter.
   */
  const fitPadding = useCallback((base: number): number | { top: number; bottom: number; left: number; right: number } => {
    const height = mapRef.current?.getMap().getContainer().clientHeight ?? 0
    if (fitBottomInset <= 0 || height <= 0) return base
    const room = Math.max(0, height - base - MIN_VISIBLE_STRIP_PX)
    return {
      top: base,
      left: base,
      right: base,
      bottom: Math.min(base + fitBottomInset * height, room),
    }
  }, [fitBottomInset])

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
      { padding: fitPadding(80), duration: 600 },
    )
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeGroupId]) // intentionally exclude routes: don't re-zoom as routes stream in

  // Zoom to fit every displayed route when the caller asks for it by key. `routes` is
  // in the deps because the key typically arrives before the routes it refers to (a
  // region's spots are still loading); the ref makes it fire on the first render that
  // has both, and not again for the same key.
  useEffect(() => {
    if (!fitAllKey || !mapRef.current || routes.length === 0) return
    if (lastFitAllKey.current === fitAllKey) return
    lastFitAllKey.current = fitAllKey
    const coords = routes.flatMap(r => r.geometry.coordinates)
    if (coords.length === 0) return
    const lons = coords.map(c => c[0])
    const lats = coords.map(c => c[1])
    mapRef.current.fitBounds(
      [[Math.min(...lons), Math.min(...lats)], [Math.max(...lons), Math.max(...lats)]],
      // A metro's worth of descents spans tens of km; cap the zoom so a region with a
      // single spot doesn't slam into street level.
      { padding: fitPadding(60), maxZoom: 14, duration: 800 },
    )
  }, [fitAllKey, routes, fitPadding])

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

  const startMarkerFeatures = useMemo(
    () => buildStartMarkerFeatures(routes, activeGroupId),
    [routes, activeGroupId],
  )

  // Inactive routes render at full opacity so overlapping dashes don't compound
  // into darker blobs in dense areas. "Recede when a group is selected" is
  // encoded via lighter color, not alpha (alpha would reintroduce stacking).
  const isFaded = !!activeGroupId
  const inactiveLineColor = isFaded ? '#c4b5fd' : '#a78bfa'
  const inactiveCasingColor = isFaded ? '#94a3b8' : '#475569'

  // The street style is fetched and rewritten before the map is built (see
  // useStreetStyle), so hold the mount until it lands. It is one request to a CDN
  // MapLibre would have hit anyway, and mounting early would mean building the map
  // twice — once per style — on a cold load.
  if (!streetStyle) return <div style={{ width: '100%', height: '100%' }} />

  return (
    <Map
      ref={attachMapRef}
      mapStyle={styleMode === 'satellite' ? SATELLITE_STYLE : streetStyle}
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
      // common case promptly; the styleimagemissing listener remains a backstop.
      onLoad={e => {
        const map = e.target
        ensureMarkerImages(map)
        // react-map-gl exposes no onStyleImageMissing prop, so the backstop is
        // attached straight to the MapLibre instance. onLoad fires once per map,
        // so this registers exactly one listener.
        map.on('styleimagemissing', ev => {
          if (MARKER_IMAGE_IDS.has(ev.id)) ensureMarkerImages(map)
        })
      }}
      onStyleData={e => {
        ensureMarkerImages(e.target)
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
          const props = markerHits[0].properties
          const id = props?.start_node_id
          if (id) {
            // A node can carry one marker per direction, so select the descent this
            // chevron actually points down rather than the group's best route — on a
            // two-way summit those are different routes.
            if (props?.route_id) onSelectPath?.(String(props.route_id), String(id))
            else onSelectGroup?.(String(id))
            return
          }
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
