import { useRef, useEffect, useMemo } from 'react'
import { StartGroupCard } from './StartGroupCard'
import { RouteCard } from './RouteCard'
import { buildDescentLabels } from '../../utils/routeLabel'
import type { StartGroup } from '../../types'

export type SortMode = 'longest' | 'fastest'

interface RouteListProps {
  groups: StartGroup[]
  activeGroupId: string | null
  activeRouteId: string | null
  onSelectGroup: (startNodeId: string) => void
  onSelectRoute: (routeId: string) => void
  onHoverGroup: (id: string | null) => void
  onHoverRoute: (id: string | null) => void
  sortMode: SortMode
  onSortModeChange: (mode: SortMode) => void
  statusMessage: string | null
  isSearching: boolean
  error: string | null
  /** True once at least one search has been started — distinguishes the
   *  initial prompt from a completed search that found nothing. */
  hasSearched?: boolean
  /** When false, the list grows with its content instead of filling parent height. Use in scrollable panels. */
  fillHeight?: boolean
  /**
   * Render every route as its own top-level card instead of folders keyed on start
   * point. Used by Collections, where the spot is already one named descent and a
   * folder per starting point is a level of nesting with nothing in it.
   */
  flat?: boolean
  /** Required by `flat`: selects a route and its group together, without toggling. */
  onSelectPath?: (routeId: string, startNodeId: string) => void
  /**
   * Content rendered above the first card, *inside* the scroll container. For prose that
   * belongs to the list but must not compete with it for height — a pinned block of it
   * eats the cards on a short screen, where scrolling costs nothing.
   */
  listHeader?: React.ReactNode
}

export function RouteList({
  groups,
  activeGroupId,
  activeRouteId,
  onSelectGroup,
  onSelectRoute,
  onHoverGroup,
  onHoverRoute,
  sortMode,
  onSortModeChange,
  statusMessage,
  isSearching,
  error,
  hasSearched = false,
  fillHeight = true,
  flat = false,
  onSelectPath,
  listHeader,
}: RouteListProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  // Groups arrive sorted, and their members are sorted within each group, so flattening
  // preserves the ranking the sidebar already implies.
  const flatRoutes = useMemo(() => groups.flatMap(g => g.routes), [groups])

  // Names depend on the whole set: two lines running the same way need Upper/Lower to
  // tell them apart, which a single route can't know about itself.
  const descentLabels = useMemo(
    () => (flat ? buildDescentLabels(flatRoutes) : new Map<string, string>()),
    [flat, flatRoutes],
  )

  // In flat mode cards are keyed on route, so scroll to the selected route rather than
  // to the group that contains it.
  const scrollToId = flat ? activeRouteId : activeGroupId
  useEffect(() => {
    if (!scrollToId) return
    const el = cardRefs.current.get(scrollToId)
    const container = scrollContainerRef.current
    if (!el || !container) return

    // Deliberately not scrollIntoView: it walks *every* scrollable ancestor, so on the
    // mobile sheet it scrolls the body as well and pushes the spot header — and the way
    // back out of the spot — off the top. Move this list and nothing else.
    const view = container.getBoundingClientRect()
    const card = el.getBoundingClientRect()
    if (card.top < view.top) {
      container.scrollBy({ top: card.top - view.top, behavior: 'smooth' })
    } else if (card.bottom > view.bottom) {
      container.scrollBy({ top: card.bottom - view.bottom, behavior: 'smooth' })
    }
  }, [scrollToId])

  return (
    <div
      role="list"
      style={{
        display: 'flex',
        flexDirection: 'column',
        ...(fillHeight ? { height: '100%', overflow: 'hidden' } : {}),
      }}
    >
      {/* Status bar */}
      {(isSearching || statusMessage || error) && (
        <div
          style={{
            padding: '8px 12px',
            fontSize: '12px',
            color: error ? '#dc2626' : '#6b7280',
            borderBottom: '1px solid #e5e7eb',
            flexShrink: 0,
          }}
        >
          {error ?? statusMessage ?? 'Searching…'}
        </div>
      )}

      {/* Sort controls */}
      {groups.length > 0 && (
        <div style={{ padding: '6px 8px', display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0, borderBottom: '1px solid #f3f4f6' }}>
          <span style={{ fontSize: '11px', color: '#9ca3af' }}>Sort:</span>
          {(['longest', 'fastest'] as SortMode[]).map(mode => (
            <button
              key={mode}
              onClick={() => onSortModeChange(mode)}
              aria-pressed={sortMode === mode}
              style={{
                fontSize: '11px',
                padding: '2px 8px',
                borderRadius: '4px',
                border: '1px solid',
                borderColor: sortMode === mode ? '#3b82f6' : '#d1d5db',
                background: sortMode === mode ? '#eff6ff' : '#fff',
                color: sortMode === mode ? '#1d4ed8' : '#6b7280',
                fontWeight: sortMode === mode ? 600 : 400,
                cursor: 'pointer',
              }}
            >
              {mode === 'longest' ? 'Longest' : 'Fastest'}
            </button>
          ))}
        </div>
      )}

      {/* Group cards */}
      <div ref={scrollContainerRef} style={{ ...(fillHeight ? { flex: 1, overflowY: 'auto' } : {}), padding: '8px' }}>
        {listHeader}
        {groups.length === 0 && !isSearching && !error && (
          <p style={{ textAlign: 'center', color: '#9ca3af', fontSize: '13px', marginTop: '24px', padding: '0 16px', lineHeight: 1.5 }}>
            {hasSearched
              ? 'No hill bombs found in this area. Try panning to hillier terrain, widening the map, or relaxing the road/surface filters below.'
              : 'Search an area to find hill bombs.'}
          </p>
        )}
        {flat
          ? flatRoutes.map(route => (
              <RouteCard
                key={route.route_id}
                route={route}
                label={descentLabels.get(route.route_id) ?? route.metadata.name}
                isActive={route.route_id === activeRouteId}
                onSelect={(routeId, startNodeId) =>
                  onSelectPath ? onSelectPath(routeId, startNodeId) : onSelectRoute(routeId)
                }
                onHoverRoute={onHoverRoute}
                cardRef={el => {
                  if (el) cardRefs.current.set(route.route_id, el)
                  else cardRefs.current.delete(route.route_id)
                }}
              />
            ))
          : groups.map(group => (
              <StartGroupCard
                key={group.startNodeId}
                group={group}
                isActive={group.startNodeId === activeGroupId}
                activeRouteId={activeRouteId}
                onSelectGroup={onSelectGroup}
                onSelectRoute={onSelectRoute}
                onHoverGroup={onHoverGroup}
                onHoverRoute={onHoverRoute}
                cardRef={el => {
                  if (el) cardRefs.current.set(group.startNodeId, el)
                  else cardRefs.current.delete(group.startNodeId)
                }}
              />
            ))}
      </div>
    </div>
  )
}
