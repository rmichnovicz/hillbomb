import { useRef, useEffect } from 'react'
import { StartGroupCard } from './StartGroupCard'
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
}: RouteListProps) {
  const scrollContainerRef = useRef<HTMLDivElement>(null)
  const cardRefs = useRef<Map<string, HTMLDivElement>>(new Map())

  useEffect(() => {
    if (!activeGroupId) return
    const el = cardRefs.current.get(activeGroupId)
    if (el) el.scrollIntoView({ behavior: 'smooth', block: 'nearest' })
  }, [activeGroupId])

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
        {groups.length === 0 && !isSearching && !error && (
          <p style={{ textAlign: 'center', color: '#9ca3af', fontSize: '13px', marginTop: '24px', padding: '0 16px', lineHeight: 1.5 }}>
            {hasSearched
              ? 'No hill bombs found in this area. Try panning to hillier terrain, widening the map, or relaxing the road/surface filters below.'
              : 'Search an area to find hill bombs.'}
          </p>
        )}
        {groups.map(group => (
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
