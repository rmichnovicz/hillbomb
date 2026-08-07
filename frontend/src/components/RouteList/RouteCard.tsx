/**
 * One route as a top-level, directly selectable card.
 *
 * The flat counterpart to StartGroupCard. A curated spot is a single named descent, so
 * its handful of lines don't need a folder per starting point in front of them —
 * Hawk Hill's three lines sat behind two collapsed groups, one of which held a single
 * route. Selecting a card sets the route *and* its group in one go, so the map behaves
 * exactly as it does when the line itself is clicked.
 */
import { flowGradeColor } from '../../utils/gradeColor'
import { DownloadButton } from './DownloadButton'
import { SurfaceBar } from './SurfaceBar'
import { TrailGrade } from './TrailGrade'
import type { Route } from '../../types'

function formatLength(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`
}

export function RouteCard({
  route,
  label,
  isActive,
  onSelect,
  onHoverRoute,
  cardRef,
}: {
  route: Route
  /** Display name from buildDescentLabels — depends on the route's siblings. */
  label: string
  isActive: boolean
  onSelect: (routeId: string, startNodeId: string) => void
  onHoverRoute: (id: string | null) => void
  cardRef: (el: HTMLDivElement | null) => void
}) {
  const { route_id, metadata, flow_grade, top_speed_kmh } = route
  const hasPhysics = top_speed_kmh !== undefined

  return (
    <div
      role="listitem"
      aria-selected={isActive}
      ref={cardRef}
      onClick={() => onSelect(route_id, String(route.start_node_id))}
      onMouseEnter={() => onHoverRoute(route_id)}
      onMouseLeave={() => onHoverRoute(null)}
      style={{
        border: isActive ? '2px solid #3b82f6' : '1px solid #e5e7eb',
        borderRadius: '8px',
        background: isActive ? '#eff6ff' : '#fff',
        marginBottom: '6px',
        padding: '8px 10px',
        cursor: 'pointer',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
        <div style={{ minWidth: 0, flex: 1 }}>
          {/* The direction leads: every line of a spot shares one road name, so
              "Conzelman Road" three times over says nothing about which is which. */}
          <div style={{
            fontWeight: isActive ? 700 : 600,
            fontSize: '13px',
            whiteSpace: 'nowrap',
            overflow: 'hidden',
            textOverflow: 'ellipsis',
          }}>
            {label}
          </div>
          <div style={{
            fontSize: '11px', color: '#6b7280', marginTop: '1px',
            whiteSpace: 'nowrap', overflow: 'hidden', textOverflow: 'ellipsis',
          }}>
            {metadata.name} · {formatLength(metadata.length_m)} · {Math.round(metadata.total_descent_m)} m ↓
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
          {/* Renders nothing on an ungraded route, which is most of them. */}
          <TrailGrade difficulty={route.trail_difficulty} />
          {hasPhysics ? (
            <span style={{ fontSize: '13px', fontWeight: 600, color: '#111827' }}>
              {Math.round(top_speed_kmh!)} km/h
            </span>
          ) : (
            <span
              className="shimmer"
              style={{
                display: 'inline-block', width: '56px', height: '15px', borderRadius: '4px',
                background: 'linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%)',
                backgroundSize: '200% 100%', animation: 'shimmer 1.2s infinite',
              }}
            />
          )}
          <span
            title={`Flow grade ${flow_grade}`}
            style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', flexShrink: 0 }}
          >
            <span style={{
              width: '7px', height: '7px', borderRadius: '50%',
              background: flowGradeColor(flow_grade), display: 'inline-block',
            }} />
            <span style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af' }}>{flow_grade}</span>
          </span>
          <DownloadButton route={route} />
        </div>
      </div>

      <SurfaceBar surfacePcts={route.surface_pcts ?? {}} />
    </div>
  )
}
