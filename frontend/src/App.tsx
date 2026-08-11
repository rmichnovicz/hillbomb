import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useSearch } from './hooks/useSearch'
import { useCollections } from './hooks/useCollections'
import { usePersistedState } from './hooks/usePersistedState'
import { usePhysics } from './hooks/usePhysics'
import { useIsMobile } from './hooks/useIsMobile'
import { useSheetDrag } from './hooks/useSheetDrag'
import { useIpLocation } from './hooks/useIpLocation'
import { nearestCity } from './utils/geo'
import { HillbombMap } from './components/Map/HillbombMap'
import { RouteList } from './components/RouteList/RouteList'
import type { SortMode } from './components/RouteList/RouteList'
import { CollectionsPanel, spotMatchesFilter } from './components/Collections/CollectionsPanel'
import { ProfilePanel } from './components/ProfilePanel/ProfilePanel'
import { RiderSettings } from './components/RiderSettings/RiderSettings'
import { SearchControls, DEFAULT_ROAD_SIZE_STEP, ROAD_SIZE_STEPS } from './components/SearchControls/SearchControls'
import type { SurfaceCategory } from './components/SearchControls/SearchControls'
import { RIDER_PROFILES } from './types'
import type { RiderProfile, RiderParams, SearchOptions, Toggles, StartGroup } from './types'

type Tab = 'search' | 'collections'

const TAB_LABEL: Record<Tab, string> = { search: 'Search', collections: 'Collections' }

function TabBar({ tab, onChange }: { tab: Tab; onChange: (t: Tab) => void }) {
  return (
    <div role="tablist" aria-label="Route source" style={{ display: 'flex', gap: '4px' }}>
      {(Object.keys(TAB_LABEL) as Tab[]).map(t => (
        <button
          key={t}
          role="tab"
          aria-selected={tab === t}
          onClick={() => onChange(t)}
          style={{
            flex: 1,
            fontSize: '12px',
            fontWeight: tab === t ? 600 : 400,
            padding: '5px 10px',
            borderRadius: '5px',
            border: '1px solid',
            borderColor: tab === t ? '#3b82f6' : '#d1d5db',
            background: tab === t ? '#eff6ff' : '#fff',
            color: tab === t ? '#1d4ed8' : '#6b7280',
            cursor: 'pointer',
            minHeight: '32px',
          }}
        >
          {TAB_LABEL[t]}
        </button>
      ))}
    </div>
  )
}

const DEFAULT_TOGGLES: Toggles = {
  avoid_stoplights: true,
  avoid_stop_signs: true,
  avoid_bigger_roads: true,
  avoid_equal_roads: true,
  exclude_tunnels: false,
  exclude_bridges: false,
  stay_on_initial_road: true,
  animate_candidates: false,
}

const DEFAULT_ALLOWED_SURFACES: SurfaceCategory[] = ['paved']
const DEFAULT_MIN_DISTANCE_M = 500

/**
 * Floor on the mobile sheet's list column, below which the sheet body scrolls instead.
 *
 * The sheet is a fixed 65dvh and everything below the tabs except the list is
 * `flexShrink: 0` — the 190px profile chart, rider settings, the search controls. So the
 * list column is charged the whole overflow, and on a short window there was nothing
 * left to charge: at a 480px viewport it collapsed to 23px, clipping the spot header,
 * the back button and every route card with no way to reach them.
 *
 * 260px is what makes the *inside* of the column work, which is the part that bites —
 * it is not one number but three. The column also carries the spot header (55px) and
 * the sort row (36px) before a single card is drawn, so a 200px floor left a 73px slit
 * onto the cards. 260 leaves ~170px, or two full cards, and the sheet scrolls to reach
 * the chart and the controls below.
 *
 * Everything pinned stays pinned, deliberately. Letting it all flow in one scroller
 * reads better on a spot with three lines and much worse on a search with fourteen: the
 * chart and the "Search this area" button end up a thousand pixels down the list.
 */
const MOBILE_LIST_MIN_PX = 260

/**
 * The mobile sheet's three resting heights.
 *
 * `peek` is the label bar. `half` is the working position — list, chart and controls all
 * at once, with the map still readable behind it. `full` is for the job this sheet was
 * worst at: reading down a list of routes. At 65dvh the list column gets ~260px on a
 * phone, or two cards; at 92dvh it gets ~470px, or five, which is the difference between
 * paging through results and scanning them.
 *
 * Three *discrete* stops rather than free-drag, deliberately. `fitBottomInset` has to
 * know how much map the sheet is covering, and a snapped detent makes that a lookup;
 * a continuously-dragged height makes it a recompute on every frame of the gesture.
 */
const SHEET_DETENTS = ['peek', 'half', 'full'] as const
type SheetDetent = (typeof SHEET_DETENTS)[number]

const SHEET_HEIGHT: Record<SheetDetent, string> = {
  peek: '52px',
  half: '65dvh',
  full: '92dvh',
}

/** Fraction of map height the sheet hides, for route-fitting. See `mobileFitInset`. */
const SHEET_MAP_COVER: Record<SheetDetent, number> = {
  // Collapsed it is 52px, which already fits inside the map's 60px base padding.
  peek: 0,
  half: 0.65,
  full: 0.92,
}

/**
 * Each label names what a tap does next, since a tap cycles rather than toggles.
 *
 * Deliberately not "Expand panel fully" for `half`: Playwright's `getByRole` matches
 * accessible names by substring, so that would also answer to "Expand panel" and every
 * test that waits for a collapsed sheet would match an open one.
 */
const SHEET_HANDLE_LABEL: Record<SheetDetent, string> = {
  peek: 'Expand panel',
  half: 'Maximize panel',
  full: 'Collapse panel',
}

export default function App() {
  const { isSearching, routes, statusMessage, error, startSearch, stopSearch } = useSearch()
  const collections = useCollections()
  const ipLocation = useIpLocation()

  const [tab, setTab] = useState<Tab>('search')
  const [activeGroupId, setActiveGroupId] = useState<string | null>(null)
  const [activeRouteId, setActiveRouteId] = useState<string | null>(null)
  const [hoveredGroupId, setHoveredGroupId] = useState<string | null>(null)
  const [hoveredRouteId, setHoveredRouteId] = useState<string | null>(null)
  const [scrubPosition, setScrubPosition] = useState<number | null>(null)
  // User-tunable settings are persisted across refreshes (versioned keys).
  const [sortMode, setSortMode] = usePersistedState<SortMode>('hillbomb_sortMode_v1', 'longest')
  const [riderProfile, setRiderProfile] = usePersistedState<RiderProfile>('hillbomb_riderProfile_v1', 'cyclist_upright')
  const [riderParams, setRiderParams] = usePersistedState<RiderParams>('hillbomb_riderParams_v1', RIDER_PROFILES.cyclist_upright)
  const [toggles, setToggles] = usePersistedState<Toggles>('hillbomb_toggles_v1', DEFAULT_TOGGLES)
  const [roadSizeStep, setRoadSizeStep] = usePersistedState('hillbomb_roadSizeStep_v1', DEFAULT_ROAD_SIZE_STEP)
  const [allowedSurfaces, setAllowedSurfaces] = usePersistedState<SurfaceCategory[]>('hillbomb_allowedSurfaces_v1', DEFAULT_ALLOWED_SURFACES)
  const [currentBbox, setCurrentBbox] = useState<[number, number, number, number]>([37.74, -122.47, 37.80, -122.40])
  const [hasSearched, setHasSearched] = useState(false)
  const [minDistanceM, setMinDistanceM] = usePersistedState('hillbomb_minDistanceM_v1', DEFAULT_MIN_DISTANCE_M)
  const [lastSuccessMaxLengthM, setLastSuccessMaxLengthM] = useState<number | null>(null)
  const prevIsSearchingRef = useRef(false)

  const isMobile = useIsMobile(640)
  const [mobileDetent, setMobileDetent] = useState<SheetDetent>('peek')
  // Most of the layout only cares whether there is a panel at all, not how tall it is.
  const mobilePanelOpen = mobileDetent !== 'peek'
  /** Open the sheet without overriding a height the reader has already chosen. */
  const openMobileSheet = useCallback(
    () => setMobileDetent(d => (d === 'peek' ? 'half' : d)),
    [],
  )

  const filteredRoutes = useMemo(
    () => minDistanceM > 0 ? routes.filter(r => r.metadata.length_m >= minDistanceM) : routes,
    [routes, minDistanceM],
  )

  // Selected discipline tags for the Collections tab; empty means show everything.
  const [disciplineFilter, setDisciplineFilter] = useState<string[]>([])

  // A region overview shows one line per spot — its headline route (the builder sorts
  // best-first). The alternate lines of a spot are variations on the same descent;
  // drawing all four of each would triple the ink for no extra information at this
  // zoom. Open a spot to see its other lines.
  //
  // Filtered by discipline alongside the sidebar: a line on the map for a spot the list
  // has hidden is unexplainable, and clicking it would open a spot you filtered out.
  const visibleCitySpots = useMemo(
    () => collections.citySpots.filter(s => spotMatchesFilter(s, disciplineFilter)),
    [collections.citySpots, disciplineFilter],
  )

  const cityOverviewRoutes = useMemo(
    () => visibleCitySpots.map(s => s.routes[0]).filter(Boolean),
    [visibleCitySpots],
  )

  // Spot slug → its headline route id, so hovering a spot card can light up its line.
  const spotHeadlineRouteId = useMemo(() => {
    const map = new Map<string, string>()
    for (const s of collections.citySpots) {
      if (s.routes[0]) map.set(s.slug, s.routes[0].route_id)
    }
    return map
  }, [collections.citySpots])

  // The reverse: which spot a line on the region overview belongs to, so clicking that
  // line can open its spot. Every route is indexed, not just the headline one, so this
  // still resolves if the overview ever draws more than one line per spot.
  const spotSlugByRouteId = useMemo(() => {
    const map = new Map<string, string>()
    for (const s of collections.citySpots) {
      for (const r of s.routes) map.set(r.route_id, s.slug)
    }
    return map
  }, [collections.citySpots])

  // Whatever the map and route list are currently showing. Collections and search are
  // separate sources of the same `Route` shape, so everything downstream of this —
  // grouping, the map, the profile panel, live physics — is identical for both.
  // In the collections tab an open spot wins over its region: you've drilled in.
  // The min-distance filter is deliberately search-only: a curated route is curated.
  const displayedRoutes = useMemo(
    () => tab === 'collections'
      ? (collections.activeSpot?.routes ?? cityOverviewRoutes)
      : filteredRoutes,
    [tab, collections.activeSpot, cityOverviewRoutes, filteredRoutes],
  )

  // Group routes by start_node_id; sort groups by selected sort mode
  const groups = useMemo((): StartGroup[] => {
    const map = new Map<string, typeof routes>()
    for (const r of displayedRoutes) {
      const key = String(r.start_node_id)
      const arr = map.get(key) ?? []
      arr.push(r)
      map.set(key, arr)
    }

    const sortValue = (r: typeof routes[0]) =>
      sortMode === 'longest' ? r.metadata.length_m : (r.top_speed_kmh ?? 0)

    const result: StartGroup[] = []
    for (const [startNodeId, rs] of map) {
      const sorted = [...rs].sort((a, b) => sortValue(b) - sortValue(a))
      result.push({
        startNodeId,
        routes: sorted,
        startCoord: sorted[0].geometry.coordinates[0] as [number, number],
      })
    }
    return result.sort((a, b) => sortValue(b.routes[0]) - sortValue(a.routes[0]))
  }, [displayedRoutes, sortMode])

  // Flattened sort order: route_id → global rank across all groups, in the order
  // the sidebar shows them. Used by the map to resolve overlapping route clicks
  // to the route that sorts first.
  const routeOrder = useMemo(() => {
    const order = new Map<string, number>()
    let i = 0
    for (const g of groups) for (const r of g.routes) order.set(r.route_id, i++)
    return order
  }, [groups])

  // When the active group changes, auto-select the best route in that group —
  // unless the current route already belongs to it (e.g. selected directly from
  // the map), in which case keep that specific route.
  // Intentionally excludes `groups` from deps — only re-seeds on group switch,
  // not on every physics update that re-sorts group members.
  useEffect(() => {
    if (!activeGroupId) { setActiveRouteId(null); return }
    const group = groups.find(g => g.startNodeId === activeGroupId)
    if (!group) return
    setActiveRouteId(prev =>
      group.routes.some(r => r.route_id === prev) ? prev : (group.routes[0]?.route_id ?? null),
    )
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [activeGroupId])

  const activeRoute = useMemo(
    () => activeRouteId ? displayedRoutes.find(r => r.route_id === activeRouteId) ?? null : null,
    [displayedRoutes, activeRouteId],
  )

  const livePhysics = usePhysics(activeRoute, riderParams)

  const activeRouteWithPhysics = useMemo(() => {
    if (!activeRoute || !livePhysics) return activeRoute
    return {
      ...activeRoute,
      speed_profile: livePhysics.speed_profile,
      top_speed_kmh: livePhysics.top_speed_kmh,
      avg_speed_kmh: livePhysics.avg_speed_kmh,
    }
  }, [activeRoute, livePhysics])

  // Track search completion to auto-adjust min distance slider
  useEffect(() => {
    const wasSearching = prevIsSearchingRef.current
    prevIsSearchingRef.current = isSearching
    if (!wasSearching || isSearching || !hasSearched) return
    if (routes.length > 0) {
      setLastSuccessMaxLengthM(Math.max(...routes.map(r => r.metadata.length_m)))
    } else if (lastSuccessMaxLengthM !== null) {
      setMinDistanceM(Math.round(lastSuccessMaxLengthM / 50) * 50)
    }
  }, [isSearching, hasSearched, routes, lastSuccessMaxLengthM])

  // Auto-expand mobile panel when routes arrive or a group is selected. To `half`, and
  // only from `peek` — someone who pulled the sheet to `full` to read the list should
  // not have it yanked back down by the next route that streams in.
  const hasRoutes = routes.length > 0
  useEffect(() => {
    if (isMobile && hasRoutes) openMobileSheet()
  }, [isMobile, hasRoutes, openMobileSheet])
  useEffect(() => {
    if (isMobile && activeGroupId) openMobileSheet()
  }, [isMobile, activeGroupId, openMobileSheet])

  // The mobile sheet body scrolls when it's too short for its pinned sections (see
  // MOBILE_LIST_MIN_PX). Switching tabs or opening a spot replaces what's in it, and a
  // scroll offset left over from the previous view puts the tab bar off the top of the
  // new one — so send it back to the start.
  const mobileSheetBodyRef = useRef<HTMLDivElement>(null)
  const activeSpotSlug = collections.activeSpot?.slug ?? null
  useEffect(() => {
    if (mobileSheetBodyRef.current) mobileSheetBodyRef.current.scrollTop = 0
  }, [tab, activeSpotSlug])

  // Destructured because the hook returns a fresh object each render — depending on
  // `collections` itself would re-run these effects/callbacks on every render. These
  // are useCallbacks: stable except toggleCity, which re-forms when the index or the
  // open region changes.
  const {
    loadIndex: loadCollectionsIndex,
    clearSpot: clearCollectionSpot,
    toggleCity: toggleCollectionCity,
    selectSpot: selectCollectionSpot,
  } = collections

  // Fetch the collections index on mount. This used to wait for the tab to be opened,
  // so that a user who never opened it never paid for it — but the index is 18 KB
  // brotli'd off the CDN, and waiting made it impossible to answer "is there anything
  // curated near this visitor?" before they had already chosen a tab. 18 KB is not
  // worth that. The per-spot geometry is still lazy, and that's where the weight is
  // (a large region is ~100 KB). loadIndex() dedups internally.
  useEffect(() => {
    loadCollectionsIndex()
  }, [loadCollectionsIndex])

  // Opening a spot: select its best line, which makes the map's fit-bounds effect
  // fly to it. Routes are already in `displayedRoutes` by the time this runs.
  useEffect(() => {
    const spot = collections.activeSpot
    if (!spot || spot.routes.length === 0) return
    setActiveGroupId(String(spot.routes[0].start_node_id))
    setScrubPosition(null)
  }, [collections.activeSpot])

  const clearSelection = useCallback(() => {
    setActiveGroupId(null)
    setActiveRouteId(null)
    setScrubPosition(null)
    // Hover is cleared too: the card the pointer was over may be unmounting with
    // this transition, and it can't send a mouseleave once it's gone.
    setHoveredGroupId(null)
    setHoveredRouteId(null)
  }, [])

  // Bumped whenever the map should re-frame the open region: opening one, backing out
  // of a spot into it, or returning to the tab. The map fits once per distinct key,
  // so without the counter a re-entry to the same region wouldn't move the viewport.
  const [regionFitToken, setRegionFitToken] = useState(0)
  const refitRegion = useCallback(() => setRegionFitToken(t => t + 1), [])

  // Non-null only while a region is the thing on screen; an open spot frames itself
  // via the map's active-group fit.
  const regionFitKey = tab === 'collections' && !collections.activeSpot && collections.expandedCity
    ? `${collections.expandedCity}#${regionFitToken}`
    : null

  const handleTabChange = useCallback((next: Tab) => {
    setTab(next)
    clearSelection()
    if (next === 'collections') refitRegion()
  }, [clearSelection, refitRegion])

  const handleToggleCity = useCallback((city: string) => {
    toggleCollectionCity(city)
    clearSelection()
    refitRegion()
  }, [toggleCollectionCity, clearSelection, refitRegion])

  // Open the curated region nearest the visitor, once, the first time the Collections
  // list and the IP geolocation are both available — so someone in Denver lands on
  // Denver instead of scrolling 34 folders past San Francisco to find it.
  //
  // One shot per mount, and it defers to the user in both directions: it never fires
  // if a region is already open, and once it has fired the region is theirs to change.
  // `nearestCity` returns null when nothing curated is within ~300 km, in which case
  // the right move is to leave the full list collapsed rather than guess.
  //
  // A hit also switches to the Collections tab, on every viewport. That is what draws
  // the region's lines on the map — `displayedRoutes` is keyed on the tab — and lines
  // on the map are the entire point: an empty map plus a button is a worse first screen
  // than real descents you can see. It is deliberately not conditional on viewport;
  // an earlier version left desktop on Search until you opened the tab, which meant
  // desktop paid for the geolocation and showed nothing for it.
  //
  // The cost, on mobile: the floating "Search this area" button is hidden on this tab,
  // so a hit trades one-tap search for one-tap curated content on first load. The sheet
  // itself stays collapsed — its label names the region, and the map keeps the screen.
  //
  // A miss changes nothing anywhere: no region, no tab switch, Search as before.
  const autoExpandedRef = useRef(false)
  useEffect(() => {
    if (autoExpandedRef.current) return
    if (!ipLocation || collections.cities.length === 0) return

    // Every input is in — this is the one chance to act, taken or not.
    autoExpandedRef.current = true
    if (collections.expandedCity) return

    const city = nearestCity(collections.cities, ipLocation.lat, ipLocation.lon)
    if (!city) return
    handleToggleCity(city)
    setTab('collections')
  }, [ipLocation, collections.cities, collections.expandedCity, handleToggleCity])

  const handleDisciplineFilterChange = useCallback((next: string[]) => {
    setDisciplineFilter(next)
    clearSelection()
    // A region whose every spot just got filtered out can't stay open: it would render
    // an empty folder and keep the map framed on lines that are no longer drawn.
    const open = collections.cities.find(c => c.city === collections.expandedCity)
    if (open && !open.spots.some(s => spotMatchesFilter(s, next))) {
      toggleCollectionCity(open.city)
    }
    refitRegion()
  }, [collections.cities, collections.expandedCity, toggleCollectionCity, clearSelection, refitRegion])

  const handleHoverSpot = useCallback((slug: string | null) => {
    setHoveredRouteId(slug ? spotHeadlineRouteId.get(slug) ?? null : null)
  }, [spotHeadlineRouteId])

  // Opening a spot unmounts the card that was hovered, so drop the highlight here
  // rather than wait for a mouseleave that will never come.
  const handleSelectSpot = useCallback((slug: string) => {
    setHoveredRouteId(null)
    selectCollectionSpot(slug)
  }, [selectCollectionSpot])

  /**
   * Move the sheet to a detent, re-fitting the map if that changed how much it covers.
   *
   * The fit that framed the open region ran against the old figure, so without this,
   * growing the sheet slides the region behind it. Only while a region is what's on
   * screen; an open spot and a search both frame themselves elsewhere.
   */
  const goToDetent = useCallback((next: SheetDetent) => {
    setMobileDetent(prev => {
      if (prev !== next && tab === 'collections' && !collections.activeSpot && collections.expandedCity) {
        refitRegion()
      }
      return next
    })
  }, [tab, collections.activeSpot, collections.expandedCity, refitRegion])

  /**
   * Tapping the handle cycles peek → half → full → peek.
   *
   * Cycling rather than toggling because `full` has to be reachable without a drag:
   * a keyboard user, or anyone whose gesture the browser eats, still needs every height.
   */
  const handleToggleMobilePanel = useCallback(() => {
    setMobileDetent(prev => {
      const next = SHEET_DETENTS[(SHEET_DETENTS.indexOf(prev) + 1) % SHEET_DETENTS.length]
      if (tab === 'collections' && !collections.activeSpot && collections.expandedCity) {
        refitRegion()
      }
      return next
    })
  }, [tab, collections.activeSpot, collections.expandedCity, refitRegion])

  /**
   * How much of the map the bottom sheet hides, as a fraction of its height.
   *
   * Capped below `full`'s real 0.92: at that height the map is a 60px strip, and asking
   * a fit to frame a route inside it produces a maximum zoom-out that reads as the map
   * lurching away. Past `half` the reader is looking at the list, not the map, so the
   * framing it had is the framing worth keeping.
   */
  const mobileFitInset = isMobile
    ? Math.min(SHEET_MAP_COVER[mobileDetent], SHEET_MAP_COVER.half)
    : 0

  // Resolved against the live viewport rather than cached: `dvh` follows rotation and
  // the mobile URL bar, and a drag that snapped to a stale height would fight both.
  const sheetHeightPx = useCallback((detent: SheetDetent) => {
    const spec = SHEET_HEIGHT[detent]
    return spec.endsWith('dvh')
      ? (parseFloat(spec) / 100) * window.innerHeight
      : parseFloat(spec)
  }, [])

  const { dragHeightPx: sheetDragHeightPx, handleProps: sheetDragHandleProps } = useSheetDrag({
    detents: SHEET_DETENTS,
    current: mobileDetent,
    heightOf: sheetHeightPx,
    onSettle: goToDetent,
  })

  /**
   * What the collapsed mobile sheet says about Collections.
   *
   * This is the whole mobile payoff of the nearest-region guess. The sheet is left
   * closed so the map — which on a phone is the app — keeps the screen, and this line
   * does the inviting instead: it names the region whose lines are already drawn
   * behind it, which a generic "tap to browse" cannot. With no region open (guess
   * missed, or nothing curated within range) it falls back to the generic prompt, and
   * mobile behaves exactly as it did before any of this.
   */
  const collectionsSummary = useMemo(() => {
    const count = visibleCitySpots.length
    if (!collections.expandedCity || count === 0) return 'Curated descents'
    return `${count} descent${count === 1 ? '' : 's'} in ${collections.expandedCity}`
  }, [collections.expandedCity, visibleCitySpots.length])

  const handleBackToCollections = useCallback(() => {
    clearCollectionSpot()
    clearSelection()
    refitRegion()
  }, [clearCollectionSpot, clearSelection, refitRegion])

  const handleSearch = useCallback(() => {
    const [, maxRoadRank] = ROAD_SIZE_STEPS[roadSizeStep]
    const options: SearchOptions = {
      bbox: currentBbox,
      rider_profile: riderProfile,
      toggles,
      max_road_rank: maxRoadRank,
      allowed_surface_categories: allowedSurfaces,
      crr_pathfinding: riderParams.crr_pathfinding,
    }
    startSearch(options)
    setHasSearched(true)
    setActiveGroupId(null)
    setActiveRouteId(null)
    setScrubPosition(null)
  }, [currentBbox, riderProfile, toggles, roadSizeStep, allowedSurfaces, riderParams.crr_pathfinding, startSearch])

  const handleSelectGroup = useCallback((startNodeId: string) => {
    setActiveGroupId(prev => prev === startNodeId ? null : startNodeId)
    setScrubPosition(null)
  }, [])

  const handleSelectRoute = useCallback((routeId: string) => {
    setActiveRouteId(routeId)
    setScrubPosition(null)
  }, [])

  // Selecting a path from the map: set its group and the specific route together
  // (no toggle). The guarded re-seed effect keeps this exact route.
  const handleSelectPath = useCallback((routeId: string, startNodeId: string) => {
    setActiveGroupId(startNodeId)
    setActiveRouteId(routeId)
    setScrubPosition(null)
    // While browsing a region the sidebar is showing spot cards, not routes, so a click
    // on the map would otherwise select a line the sidebar can't show. Follow it in:
    // open the spot that line belongs to, and its now-flat list highlights the route.
    if (tab === 'collections' && !collections.activeSpot) {
      const slug = spotSlugByRouteId.get(routeId)
      if (slug) {
        setHoveredRouteId(null)
        selectCollectionSpot(slug)
      }
    }
  }, [tab, collections.activeSpot, spotSlugByRouteId, selectCollectionSpot])

  if (isMobile) {
    return (
      <div style={{ position: 'relative', width: '100%', height: '100dvh', overflow: 'hidden', fontFamily: 'system-ui, sans-serif' }}>
        {/* Map: fills entire screen */}
        <div style={{ position: 'absolute', inset: 0 }}>
          <HillbombMap
            routes={displayedRoutes}
            activeGroupId={activeGroupId}
            activeRouteId={activeRouteId}
            hoveredGroupId={hoveredGroupId}
            hoveredRouteId={hoveredRouteId}
            routeOrder={routeOrder}
            onBoundsChange={setCurrentBbox}
            onSelectGroup={handleSelectGroup}
            onSelectPath={handleSelectPath}
            scrubPosition={scrubPosition}
            fitAllKey={regionFitKey}
            fitBottomInset={mobileFitInset}
          />
        </div>

        {/* Floating search/stop button — only when panel is collapsed, and only on
            the search tab (collections are precomputed; there's nothing to search). */}
        {!mobilePanelOpen && tab === 'search' && (
          <div style={{
            position: 'absolute',
            bottom: '68px',
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            pointerEvents: 'none',
            zIndex: 10,
          }}>
            <button
              onClick={isSearching ? stopSearch : handleSearch}
              style={{
                pointerEvents: 'auto',
                padding: '13px 28px',
                borderRadius: '28px',
                border: 'none',
                background: isSearching ? '#ef4444' : '#3b82f6',
                color: '#fff',
                fontWeight: 700,
                fontSize: '16px',
                cursor: 'pointer',
                boxShadow: '0 4px 16px rgba(0,0,0,0.3)',
                minHeight: '48px',
              }}
            >
              {isSearching ? 'Stop' : 'Search this area'}
            </button>
          </div>
        )}

        {/* Status toast — only when searching with panel collapsed */}
        {!mobilePanelOpen && isSearching && statusMessage && (
          <div style={{
            position: 'absolute',
            bottom: '128px',
            left: 0,
            right: 0,
            display: 'flex',
            justifyContent: 'center',
            zIndex: 10,
            pointerEvents: 'none',
          }}>
            <div style={{
              background: 'rgba(0,0,0,0.68)',
              color: '#fff',
              fontSize: '12px',
              padding: '5px 14px',
              borderRadius: '14px',
            }}>
              {statusMessage}
            </div>
          </div>
        )}

        {/* Bottom sheet panel. `hb-sheet` hides scrollbar chrome throughout — see index.css. */}
        <div className="hb-sheet" style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: sheetDragHeightPx !== null ? `${sheetDragHeightPx}px` : SHEET_HEIGHT[mobileDetent],
          background: '#f9fafb',
          borderRadius: '16px 16px 0 0',
          boxShadow: '0 -4px 24px rgba(0,0,0,0.15)',
          display: 'flex',
          flexDirection: 'column',
          // No transition mid-drag: the pointer is already setting the height every frame,
          // and easing toward a value that has already moved on just reads as lag.
          transition: sheetDragHeightPx !== null ? 'none' : 'height 0.28s cubic-bezier(0.32, 0.72, 0, 1)',
          overflow: 'hidden',
          zIndex: 5,
        }}>
          {/* Drag handle / collapsed summary. Draggable *and* clickable: the drag is the
              affordance the pill has always implied, the click is what keeps every height
              reachable from a keyboard. */}
          <button
            onClick={handleToggleMobilePanel}
            aria-label={SHEET_HANDLE_LABEL[mobileDetent]}
            {...sheetDragHandleProps}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '5px',
              padding: '10px 16px 8px',
              background: 'none',
              border: 'none',
              cursor: sheetDragHeightPx !== null ? 'grabbing' : 'grab',
              flexShrink: 0,
              width: '100%',
              boxSizing: 'border-box',
              ...sheetDragHandleProps.style,
            }}
          >
            <div style={{ width: 40, height: 4, background: '#d1d5db', borderRadius: 2 }} />
            {!mobilePanelOpen && (
              <span style={{
                fontSize: '12px',
                color: '#6b7280',
                // Region names run long ("Jackson / Northwest Wyoming") and this is a
                // 52px bar on a phone.
                maxWidth: '100%',
                overflow: 'hidden',
                textOverflow: 'ellipsis',
                whiteSpace: 'nowrap',
              }}>
                {/* Names what is in the sheet, and stops there. The "— tap to view"
                    suffixes these used to carry were teaching an affordance the handle
                    now has, on the one bar too narrow to spare the characters — long
                    region names ellipsize here already.
                    The empty state especially: it read "Tap to open search" while the
                    floating "Search this area" button sat directly above it, and tapping
                    the sheet does not search. What is behind it is the rider setup. */}
                {tab === 'collections'
                  ? (collections.activeSpot?.name ?? collectionsSummary)
                  : routes.length > 0
                  ? `${routes.length} route${routes.length !== 1 ? 's' : ''} found`
                  : isSearching
                  ? (statusMessage ?? 'Searching…')
                  : 'Rider setup & filters'}
              </span>
            )}
          </button>

          {/* Tabs — outside the scroller. The one thing worth 44 permanent pixels: it is
              how you get from a spot back to searching without scrolling to find it.
              Not rendered while collapsed: the whole sheet is 52px then, and 44 of them
              spent on tabs leaves the summary label with nothing and the body with zero
              height — which is every child of it unreachable, not merely clipped. */}
          {mobilePanelOpen && (
            <div style={{ flexShrink: 0, padding: '0 12px 8px' }}>
              <TabBar tab={tab} onChange={handleTabChange} />
            </div>
          )}

          {/* Everything else. The chart and the controls below stay pinned, and this
              scrolls when they don't all fit — see MOBILE_LIST_MIN_PX. */}
          <div ref={mobileSheetBodyRef} style={{ flex: 1, display: 'flex', flexDirection: 'column', overflowY: 'auto', WebkitOverflowScrolling: 'touch' }}>

            {/* Route list / collections — takes the slack, down to MOBILE_LIST_MIN_PX. */}
            <div style={{ flex: '1 1 auto', minHeight: `${MOBILE_LIST_MIN_PX}px`, overflow: 'hidden' }}>
              {tab === 'search' ? (
                <RouteList
                  groups={groups}
                  activeGroupId={activeGroupId}
                  activeRouteId={activeRouteId}
                  onSelectGroup={handleSelectGroup}
                  onSelectRoute={handleSelectRoute}
                  onHoverGroup={setHoveredGroupId}
                  onHoverRoute={setHoveredRouteId}
                  sortMode={sortMode}
                  onSortModeChange={setSortMode}
                  statusMessage={statusMessage}
                  isSearching={isSearching}
                  error={error}
                  hasSearched={hasSearched}
                  fillHeight={true}
                />
              ) : (
                <CollectionsPanel
                  cities={collections.cities}
                  expandedCity={collections.expandedCity}
                  activeSpot={collections.activeSpot}
                  isLoadingIndex={collections.isLoadingIndex}
                  isLoadingCity={collections.isLoadingCity}
                  isLoadingSpot={collections.isLoadingSpot}
                  error={collections.error}
                  onToggleCity={handleToggleCity}
                  onSelectSpot={handleSelectSpot}
                  onHoverSpot={handleHoverSpot}
                  onBack={handleBackToCollections}
                  groups={groups}
                  activeGroupId={activeGroupId}
                  activeRouteId={activeRouteId}
                  onSelectGroup={handleSelectGroup}
                  onSelectRoute={handleSelectRoute}
                  onSelectPath={handleSelectPath}
                  onHoverGroup={setHoveredGroupId}
                  onHoverRoute={setHoveredRouteId}
                  sortMode={sortMode}
                  onSortModeChange={setSortMode}
                  disciplineFilter={disciplineFilter}
                  onDisciplineFilterChange={handleDisciplineFilterChange}
                  fillHeight={true}
                />
              )}
            </div>

            {/* Profile panel — pinned below route list */}
            {activeRouteWithPhysics && (
              <div style={{ flexShrink: 0, borderTop: '1px solid #e5e7eb', background: '#fff' }}>
                <ProfilePanel
                  route={activeRouteWithPhysics}
                  onScrubPosition={setScrubPosition}
                />
              </div>
            )}

            {/* Rider settings — pinned, collapsible */}
            <div style={{ flexShrink: 0 }}>
              <RiderSettings
                profile={riderProfile}
                params={riderParams}
                onProfileChange={setRiderProfile}
                onParamsChange={setRiderParams}
                isSearching={isSearching}
                activeRouteId={activeRouteId}
              />
            </div>

            {/* Search controls — search tab only; collections are precomputed. */}
            {tab === 'search' && (
              <div style={{ flexShrink: 0 }}>
                <SearchControls
                  isSearching={isSearching}
                  toggles={toggles}
                  onTogglesChange={setToggles}
                  roadSizeStep={roadSizeStep}
                  onRoadSizeChange={setRoadSizeStep}
                  allowedSurfaces={allowedSurfaces}
                  onAllowedSurfacesChange={setAllowedSurfaces}
                  minDistanceM={minDistanceM}
                  onMinDistanceChange={setMinDistanceM}
                  onSearch={handleSearch}
                  onStop={stopSearch}
                  activeRouteId={activeRouteId}
                />
              </div>
            )}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div style={{ display: 'flex', height: '100vh', overflow: 'hidden', fontFamily: 'system-ui, sans-serif' }}>
      {/* Map */}
      <div style={{ flex: 1, position: 'relative' }}>
        <HillbombMap
          routes={displayedRoutes}
          activeGroupId={activeGroupId}
          activeRouteId={activeRouteId}
          hoveredGroupId={hoveredGroupId}
          hoveredRouteId={hoveredRouteId}
          routeOrder={routeOrder}
          onBoundsChange={setCurrentBbox}
          onSelectGroup={handleSelectGroup}
          onSelectPath={handleSelectPath}
          scrubPosition={scrubPosition}
          fitAllKey={regionFitKey}
        />
      </div>

      {/* Sidebar */}
      <div style={{
        width: '340px',
        borderLeft: '1px solid #e5e7eb',
        display: 'flex',
        flexDirection: 'column',
        background: '#f9fafb',
        overflow: 'hidden',
      }}>
        {/* Header */}
        <div style={{ padding: '12px 16px 10px', borderBottom: '1px solid #e5e7eb', flexShrink: 0 }}>
          <h1 style={{ margin: 0, fontSize: '18px', fontWeight: 700, color: '#111827' }}>Hillbomb</h1>
          <p style={{ margin: '2px 0 8px', fontSize: '11px', color: '#9ca3af' }}>Discover diabolical descents</p>
          <TabBar tab={tab} onChange={handleTabChange} />
        </div>

        {/* Route list / collections */}
        <div style={{ flex: 1, overflow: 'hidden' }}>
          {tab === 'search' ? (
            <RouteList
              groups={groups}
              activeGroupId={activeGroupId}
              activeRouteId={activeRouteId}
              onSelectGroup={handleSelectGroup}
              onSelectRoute={handleSelectRoute}
              onHoverGroup={setHoveredGroupId}
              onHoverRoute={setHoveredRouteId}
              sortMode={sortMode}
              onSortModeChange={setSortMode}
              statusMessage={statusMessage}
              isSearching={isSearching}
              error={error}
              hasSearched={hasSearched}
            />
          ) : (
            <CollectionsPanel
              cities={collections.cities}
              expandedCity={collections.expandedCity}
              activeSpot={collections.activeSpot}
              isLoadingIndex={collections.isLoadingIndex}
              isLoadingCity={collections.isLoadingCity}
              isLoadingSpot={collections.isLoadingSpot}
              error={collections.error}
              onToggleCity={handleToggleCity}
              onSelectSpot={handleSelectSpot}
              onHoverSpot={handleHoverSpot}
              onBack={handleBackToCollections}
              groups={groups}
              activeGroupId={activeGroupId}
              activeRouteId={activeRouteId}
              onSelectGroup={handleSelectGroup}
              onSelectRoute={handleSelectRoute}
              onSelectPath={handleSelectPath}
              onHoverGroup={setHoveredGroupId}
              onHoverRoute={setHoveredRouteId}
              sortMode={sortMode}
              onSortModeChange={setSortMode}
              disciplineFilter={disciplineFilter}
              onDisciplineFilterChange={handleDisciplineFilterChange}
            />
          )}
        </div>

        {/* Profile panel — shows best route in active group */}
        {activeRouteWithPhysics && (
          <div style={{ flexShrink: 0, borderTop: '1px solid #e5e7eb', background: '#fff' }}>
            <ProfilePanel
              route={activeRouteWithPhysics}
              onScrubPosition={setScrubPosition}
            />
          </div>
        )}

        {/* Rider settings */}
        <RiderSettings
          profile={riderProfile}
          params={riderParams}
          onProfileChange={setRiderProfile}
          onParamsChange={setRiderParams}
          isSearching={isSearching}
          activeRouteId={activeRouteId}
        />

        {/* Search controls + toggles — search tab only; collections are precomputed. */}
        {tab === 'search' && (
          <SearchControls
            isSearching={isSearching}
            toggles={toggles}
            onTogglesChange={setToggles}
            roadSizeStep={roadSizeStep}
            onRoadSizeChange={setRoadSizeStep}
            allowedSurfaces={allowedSurfaces}
            onAllowedSurfacesChange={setAllowedSurfaces}
            minDistanceM={minDistanceM}
            onMinDistanceChange={setMinDistanceM}
            onSearch={handleSearch}
            onStop={stopSearch}
            activeRouteId={activeRouteId}
          />
        )}
      </div>
    </div>
  )
}
