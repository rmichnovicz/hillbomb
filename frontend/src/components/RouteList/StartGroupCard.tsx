import { flowGradeColor } from '../../utils/gradeColor'
import { DownloadButton } from './DownloadButton'
import { SurfaceBar } from './SurfaceBar'
import { TrailGrade } from './TrailGrade'
import type { Route, StartGroup } from '../../types'

interface StartGroupCardProps {
  group: StartGroup
  isActive: boolean
  activeRouteId: string | null
  onSelectGroup: (startNodeId: string) => void
  onSelectRoute: (routeId: string) => void
  onHoverGroup: (id: string | null) => void
  onHoverRoute: (id: string | null) => void
  cardRef: (el: HTMLDivElement | null) => void
}

function formatLength(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`
}

/** Compact flow-grade indicator: a small colored dot plus the letter in muted
 *  text. Intentionally low-key — the grade is secondary to speed/length. */
function FlowGrade({ grade }: { grade: string }) {
  return (
    <span
      title={`Flow grade ${grade}`}
      style={{ display: 'inline-flex', alignItems: 'center', gap: '3px', flexShrink: 0 }}
    >
      <span style={{
        width: '7px',
        height: '7px',
        borderRadius: '50%',
        background: flowGradeColor(grade),
        display: 'inline-block',
      }} />
      <span style={{ fontSize: '11px', fontWeight: 600, color: '#9ca3af' }}>{grade}</span>
    </span>
  )
}

function RouteRow({
  route,
  isActive,
  onSelect,
  onHoverRoute,
}: {
  route: Route
  isActive: boolean
  onSelect: (routeId: string) => void
  onHoverRoute: (id: string | null) => void
}) {
  const { route_id, metadata, flow_grade, top_speed_kmh } = route
  const hasPhysics = top_speed_kmh !== undefined

  return (
    <div
      onClick={e => { e.stopPropagation(); onSelect(route_id) }}
      onMouseEnter={() => onHoverRoute(route_id)}
      onMouseLeave={() => onHoverRoute(null)}
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'space-between',
        padding: '7px 10px',
        borderRadius: '6px',
        cursor: 'pointer',
        background: isActive ? '#dbeafe' : 'transparent',
        border: isActive ? '1px solid #93c5fd' : '1px solid transparent',
        marginBottom: '4px',
      }}
    >
      <div style={{ minWidth: 0, flex: 1, marginRight: '8px' }}>
        <div style={{
          fontSize: '13px',
          fontWeight: isActive ? 600 : 400,
          color: '#111827',
          whiteSpace: 'nowrap',
          overflow: 'hidden',
          textOverflow: 'ellipsis',
        }}>
          {metadata.name}
        </div>
        <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '1px' }}>
          {formatLength(metadata.length_m)} · {Math.round(metadata.total_descent_m)} m ↓
        </div>
        <SurfaceBar surfacePcts={route.surface_pcts ?? {}} />
      </div>

      <div style={{ display: 'flex', alignItems: 'center', gap: '6px', flexShrink: 0 }}>
        {/* Renders nothing on an ungraded route, which is most of them. */}
        <TrailGrade difficulty={route.trail_difficulty} />
        {hasPhysics ? (
          <span style={{ fontSize: '12px', color: '#374151' }}>
            {Math.round(top_speed_kmh!)} km/h
          </span>
        ) : (
          <span style={{
            display: 'inline-block',
            width: '52px',
            height: '14px',
            borderRadius: '3px',
            background: 'linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%)',
            backgroundSize: '200% 100%',
            animation: 'shimmer 1.2s infinite',
          }} />
        )}
        <FlowGrade grade={flow_grade} />
        <DownloadButton route={route} />
      </div>
    </div>
  )
}

export function StartGroupCard({
  group,
  isActive,
  activeRouteId,
  onSelectGroup,
  onSelectRoute,
  onHoverGroup,
  onHoverRoute,
  cardRef,
}: StartGroupCardProps) {
  const best = group.routes[0]
  const { metadata, flow_grade, top_speed_kmh } = best
  const hasPhysics = top_speed_kmh !== undefined

  return (
    <div
      role="listitem"
      aria-selected={isActive}
      ref={cardRef}
      onMouseEnter={() => onHoverGroup(group.startNodeId)}
      onMouseLeave={() => onHoverGroup(null)}
      style={{
        border: isActive ? '2px solid #3b82f6' : '1px solid #e5e7eb',
        borderRadius: '8px',
        background: isActive ? '#eff6ff' : '#fff',
        marginBottom: '6px',
        overflow: 'hidden',
      }}
    >
      {/* Group header — click to expand/collapse */}
      <div
        onClick={() => onSelectGroup(group.startNodeId)}
        style={{ padding: '8px 10px', cursor: 'pointer' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '8px' }}>
          <div style={{ minWidth: 0, flex: 1 }}>
            <div style={{
              fontWeight: 600,
              fontSize: '13px',
              whiteSpace: 'nowrap',
              overflow: 'hidden',
              textOverflow: 'ellipsis',
            }}>
              {metadata.name}
            </div>
            <div style={{ fontSize: '11px', color: '#6b7280', marginTop: '1px' }}>
              {group.routes.length} {group.routes.length === 1 ? 'route' : 'routes'}
              {' · '}{Math.round(metadata.total_descent_m)} m ↓
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '8px', flexShrink: 0 }}>
            {/* The group header shows its headline route's grade. */}
            <TrailGrade difficulty={best.trail_difficulty} />
            {hasPhysics ? (
              <span style={{ fontSize: '13px', fontWeight: 600, color: '#111827' }}>
                {Math.round(top_speed_kmh!)} km/h
              </span>
            ) : (
              <span
                className="shimmer"
                style={{
                  display: 'inline-block',
                  width: '56px',
                  height: '15px',
                  borderRadius: '4px',
                  background: 'linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%)',
                  backgroundSize: '200% 100%',
                  animation: 'shimmer 1.2s infinite',
                }}
              />
            )}
            <FlowGrade grade={flow_grade} />
            <span style={{ fontSize: '10px', color: '#9ca3af' }}>{isActive ? '▲' : '▼'}</span>
          </div>
        </div>

        <SurfaceBar surfacePcts={best.surface_pcts ?? {}} />
      </div>

      {/* Expanded route list */}
      {isActive && (
        <div style={{
          padding: '0 8px 8px',
          borderTop: '1px solid #bfdbfe',
          paddingTop: '8px',
        }}>
          {group.routes.map(route => (
            <RouteRow
              key={route.route_id}
              route={route}
              isActive={route.route_id === activeRouteId}
              onSelect={onSelectRoute}
              onHoverRoute={onHoverRoute}
            />
          ))}
        </div>
      )}
    </div>
  )
}
