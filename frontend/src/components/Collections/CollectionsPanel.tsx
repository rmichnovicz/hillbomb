/**
 * The Collections tab: curated famous descents, grouped by city.
 *
 * Two modes, one component so App only has to place one element per layout:
 *   - browse: cities, each with spot cards (loaded from the lightweight index)
 *   - detail: a header for the opened spot, then the ordinary RouteList of its routes
 *
 * Collection routes are plain `Route`s, so the detail view is just RouteList — the
 * cards, sparklines, hover and selection behavior all come along for free.
 */
import { RouteList } from '../RouteList/RouteList'
import type { SortMode } from '../RouteList/RouteList'
import type { CollectionCity, CollectionSpot, CollectionSpotSummary, StartGroup } from '../../types'

const DISCIPLINE_LABEL: Record<CollectionSpotSummary['discipline'], string> = {
  cycling: 'Cycling',
  skate: 'Skate',
  both: 'Cycling · Skate',
}

function formatDistance(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`
}

function FlowBadge({ grade }: { grade: string }) {
  if (!grade) return null
  const color = grade.startsWith('A') ? '#16a34a'
    : grade.startsWith('B') ? '#65a30d'
    : grade.startsWith('C') ? '#ca8a04'
    : grade.startsWith('D') ? '#ea580c'
    : '#dc2626'
  return (
    <span
      title={`Flow grade ${grade}`}
      style={{
        fontSize: '10px', fontWeight: 700, color: '#fff', background: color,
        borderRadius: '3px', padding: '1px 5px', lineHeight: 1.5,
      }}
    >
      {grade}
    </span>
  )
}

function SpotCard({ spot, onSelect }: { spot: CollectionSpotSummary; onSelect: (slug: string) => void }) {
  return (
    <button
      onClick={() => onSelect(spot.slug)}
      style={{
        display: 'block', width: '100%', textAlign: 'left', cursor: 'pointer',
        background: '#fff', border: '1px solid #e5e7eb', borderRadius: '8px',
        padding: '10px 12px', marginBottom: '8px', font: 'inherit',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'baseline', justifyContent: 'space-between', gap: '8px' }}>
        <span style={{ fontSize: '13px', fontWeight: 600, color: '#111827' }}>{spot.name}</span>
        <FlowBadge grade={spot.flow_grade} />
      </div>

      <div style={{ display: 'flex', gap: '10px', margin: '5px 0 6px', fontSize: '11px', color: '#6b7280' }}>
        <span>{formatDistance(spot.length_m)}</span>
        <span>↓ {Math.round(spot.total_descent_m)} m</span>
        <span>{Math.round(spot.top_speed_kmh)} km/h</span>
      </div>

      <p style={{ margin: 0, fontSize: '11px', color: '#9ca3af', lineHeight: 1.45 }}>{spot.blurb}</p>

      <div style={{ marginTop: '6px', fontSize: '10px', color: '#c0c4cc' }}>
        {DISCIPLINE_LABEL[spot.discipline]} · {spot.state}
        {spot.route_count > 1 && ` · ${spot.route_count} lines`}
      </div>
    </button>
  )
}

function SpotHeader({ spot, onBack }: { spot: CollectionSpot; onBack: () => void }) {
  return (
    <div style={{ padding: '8px 12px 10px', borderBottom: '1px solid #e5e7eb', flexShrink: 0, background: '#fff' }}>
      <button
        onClick={onBack}
        style={{
          background: 'none', border: 'none', padding: 0, cursor: 'pointer',
          fontSize: '11px', color: '#3b82f6', fontWeight: 600, marginBottom: '4px',
        }}
      >
        ← All collections
      </button>
      <div style={{ fontSize: '14px', fontWeight: 700, color: '#111827' }}>{spot.name}</div>
      <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '1px' }}>{spot.city}, {spot.state}</div>
      {spot.notes && (
        <p style={{
          margin: '7px 0 0', fontSize: '11px', color: '#92400e', lineHeight: 1.45,
          background: '#fffbeb', border: '1px solid #fde68a', borderRadius: '5px', padding: '5px 7px',
        }}>
          {spot.notes}
        </p>
      )}
    </div>
  )
}

interface CollectionsPanelProps {
  cities: CollectionCity[]
  activeSpot: CollectionSpot | null
  isLoadingIndex: boolean
  isLoadingSpot: boolean
  error: string | null
  onSelectSpot: (slug: string) => void
  onBack: () => void
  // RouteList props, used for the opened spot's routes.
  groups: StartGroup[]
  activeGroupId: string | null
  activeRouteId: string | null
  onSelectGroup: (startNodeId: string) => void
  onSelectRoute: (routeId: string) => void
  onHoverGroup: (id: string | null) => void
  onHoverRoute: (id: string | null) => void
  sortMode: SortMode
  onSortModeChange: (mode: SortMode) => void
  fillHeight?: boolean
}

export function CollectionsPanel({
  cities,
  activeSpot,
  isLoadingIndex,
  isLoadingSpot,
  error,
  onSelectSpot,
  onBack,
  groups,
  activeGroupId,
  activeRouteId,
  onSelectGroup,
  onSelectRoute,
  onHoverGroup,
  onHoverRoute,
  sortMode,
  onSortModeChange,
  fillHeight = true,
}: CollectionsPanelProps) {
  const frame = (children: React.ReactNode) => (
    <div style={{
      display: 'flex', flexDirection: 'column',
      ...(fillHeight ? { height: '100%', overflow: 'hidden' } : {}),
    }}>
      {children}
    </div>
  )

  const message = (text: string, color = '#9ca3af') => (
    <p style={{
      textAlign: 'center', color, fontSize: '13px', marginTop: '24px',
      padding: '0 16px', lineHeight: 1.5,
    }}>
      {text}
    </p>
  )

  if (activeSpot) {
    return frame(
      <>
        <SpotHeader spot={activeSpot} onBack={onBack} />
        <div style={{ flex: 1, minHeight: 0, overflow: 'hidden' }}>
          <RouteList
            groups={groups}
            activeGroupId={activeGroupId}
            activeRouteId={activeRouteId}
            onSelectGroup={onSelectGroup}
            onSelectRoute={onSelectRoute}
            onHoverGroup={onHoverGroup}
            onHoverRoute={onHoverRoute}
            sortMode={sortMode}
            onSortModeChange={onSortModeChange}
            statusMessage={null}
            isSearching={false}
            error={null}
            hasSearched={true}
            fillHeight={fillHeight}
          />
        </div>
      </>
    )
  }

  if (error) return frame(message(error, '#dc2626'))
  if (isLoadingIndex) return frame(message('Loading collections…'))
  if (isLoadingSpot) return frame(message('Loading routes…'))
  if (cities.length === 0) {
    return frame(message(
      'No collections have been built yet. Run `python -m backend.scripts.build_collections` to generate them.'
    ))
  }

  return frame(
    <div style={{ ...(fillHeight ? { flex: 1, overflowY: 'auto' } : {}), padding: '8px' }}>
      {cities.map(city => (
        <section key={city.city} style={{ marginBottom: '14px' }}>
          <h2 style={{
            margin: '0 0 7px', fontSize: '11px', fontWeight: 700, color: '#6b7280',
            textTransform: 'uppercase', letterSpacing: '0.04em',
          }}>
            {city.city}
          </h2>
          {city.spots.map(spot => (
            <SpotCard key={spot.slug} spot={spot} onSelect={onSelectSpot} />
          ))}
        </section>
      ))}
    </div>
  )
}
