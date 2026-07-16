import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useSearch } from './hooks/useSearch'
import { useCollections } from './hooks/useCollections'
import { usePersistedState } from './hooks/usePersistedState'
import { usePhysics } from './hooks/usePhysics'
import { useIsMobile } from './hooks/useIsMobile'
import { HillbombMap } from './components/Map/HillbombMap'
import { RouteList } from './components/RouteList/RouteList'
import type { SortMode } from './components/RouteList/RouteList'
import { CollectionsPanel } from './components/Collections/CollectionsPanel'
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

export default function App() {
  const { isSearching, routes, statusMessage, error, startSearch, stopSearch } = useSearch()
  const collections = useCollections()

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
  const [mobilePanelOpen, setMobilePanelOpen] = useState(false)

  const filteredRoutes = useMemo(
    () => minDistanceM > 0 ? routes.filter(r => r.metadata.length_m >= minDistanceM) : routes,
    [routes, minDistanceM],
  )

  // Whatever the map and route list are currently showing. Collections and search are
  // separate sources of the same `Route` shape, so everything downstream of this —
  // grouping, the map, the profile panel, live physics — is identical for both.
  // The min-distance filter is deliberately search-only: a curated route is curated.
  const displayedRoutes = useMemo(
    () => tab === 'collections' ? (collections.activeSpot?.routes ?? []) : filteredRoutes,
    [tab, collections.activeSpot, filteredRoutes],
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

  // Auto-expand mobile panel when routes arrive or a group is selected
  const hasRoutes = routes.length > 0
  useEffect(() => {
    if (isMobile && hasRoutes) setMobilePanelOpen(true)
  }, [isMobile, hasRoutes])
  useEffect(() => {
    if (isMobile && activeGroupId) setMobilePanelOpen(true)
  }, [isMobile, activeGroupId])

  // Fetch the collections index the first time the tab is opened — not on mount, so
  // a user who never opens it never pays for it. loadIndex() dedups internally.
  useEffect(() => {
    if (tab === 'collections') collections.loadIndex()
  }, [tab, collections])

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
  }, [])

  const handleTabChange = useCallback((next: Tab) => {
    setTab(next)
    clearSelection()
  }, [clearSelection])

  const handleBackToCollections = useCallback(() => {
    collections.clearSpot()
    clearSelection()
  }, [collections, clearSelection])

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
  }, [])

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

        {/* Bottom sheet panel */}
        <div style={{
          position: 'absolute',
          bottom: 0,
          left: 0,
          right: 0,
          height: mobilePanelOpen ? '65dvh' : '52px',
          background: '#f9fafb',
          borderRadius: '16px 16px 0 0',
          boxShadow: '0 -4px 24px rgba(0,0,0,0.15)',
          display: 'flex',
          flexDirection: 'column',
          transition: 'height 0.28s cubic-bezier(0.32, 0.72, 0, 1)',
          overflow: 'hidden',
          zIndex: 5,
        }}>
          {/* Drag handle / collapsed summary */}
          <button
            onClick={() => setMobilePanelOpen(o => !o)}
            aria-label={mobilePanelOpen ? 'Collapse panel' : 'Expand panel'}
            style={{
              display: 'flex',
              flexDirection: 'column',
              alignItems: 'center',
              gap: '5px',
              padding: '10px 16px 8px',
              background: 'none',
              border: 'none',
              cursor: 'pointer',
              flexShrink: 0,
              width: '100%',
              boxSizing: 'border-box',
            }}
          >
            <div style={{ width: 40, height: 4, background: '#d1d5db', borderRadius: 2 }} />
            {!mobilePanelOpen && (
              <span style={{ fontSize: '12px', color: '#6b7280' }}>
                {tab === 'collections'
                  ? (collections.activeSpot?.name ?? 'Tap to browse collections')
                  : routes.length > 0
                  ? `${routes.length} route${routes.length !== 1 ? 's' : ''} found — tap to view`
                  : isSearching
                  ? (statusMessage ?? 'Searching…')
                  : 'Tap to open search'}
              </span>
            )}
          </button>

          {/* Panel content: route list scrolls, controls pinned at bottom */}
          <div style={{ flex: 1, display: 'flex', flexDirection: 'column', overflow: 'hidden' }}>

            {/* Tabs */}
            <div style={{ flexShrink: 0, padding: '0 12px 8px' }}>
              <TabBar tab={tab} onChange={handleTabChange} />
            </div>

            {/* Route list / collections — grows to fill space, scrolls internally */}
            <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
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
                  activeSpot={collections.activeSpot}
                  isLoadingIndex={collections.isLoadingIndex}
                  isLoadingSpot={collections.isLoadingSpot}
                  error={collections.error}
                  onSelectSpot={collections.selectSpot}
                  onBack={handleBackToCollections}
                  groups={groups}
                  activeGroupId={activeGroupId}
                  activeRouteId={activeRouteId}
                  onSelectGroup={handleSelectGroup}
                  onSelectRoute={handleSelectRoute}
                  onHoverGroup={setHoveredGroupId}
                  onHoverRoute={setHoveredRouteId}
                  sortMode={sortMode}
                  onSortModeChange={setSortMode}
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
          <p style={{ margin: '2px 0 8px', fontSize: '11px', color: '#9ca3af' }}>Find the best descents near you</p>
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
              activeSpot={collections.activeSpot}
              isLoadingIndex={collections.isLoadingIndex}
              isLoadingSpot={collections.isLoadingSpot}
              error={collections.error}
              onSelectSpot={collections.selectSpot}
              onBack={handleBackToCollections}
              groups={groups}
              activeGroupId={activeGroupId}
              activeRouteId={activeRouteId}
              onSelectGroup={handleSelectGroup}
              onSelectRoute={handleSelectRoute}
              onHoverGroup={setHoveredGroupId}
              onHoverRoute={setHoveredRouteId}
              sortMode={sortMode}
              onSortModeChange={setSortMode}
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
