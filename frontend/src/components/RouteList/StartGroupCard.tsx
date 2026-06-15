import { flowGradeColor } from '../../utils/gradeColor'
import { downloadGPX } from '../../utils/gpx'
import type { Route, StartGroup } from '../../types'

const SURFACE_COLORS: Record<string, string> = {
  paved:       '#6b7280',
  gravel:      '#d97706',
  unpaved:     '#92400e',
  cobblestone: '#7c3aed',
  unknown:     '#d1d5db',
}

const SURFACE_LABELS: Record<string, string> = {
  paved:       'Paved',
  gravel:      'Gravel',
  unpaved:     'Unpaved',
  cobblestone: 'Cobblestone',
  unknown:     'Unknown',
}

function SurfaceBar({ surfacePcts }: { surfacePcts: Record<string, number> }) {
  const entries = Object.entries(surfacePcts).filter(([, pct]) => pct >= 1)
  if (entries.length === 0) return null
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '6px', marginTop: '3px', flexWrap: 'wrap' }}>
      {/* Proportional segmented bar */}
      <div style={{ display: 'flex', height: '4px', borderRadius: '2px', overflow: 'hidden', width: '60px', flexShrink: 0 }}>
        {entries.map(([cat, pct]) => (
          <div
            key={cat}
            title={`${SURFACE_LABELS[cat] ?? cat}: ${pct}%`}
            style={{ width: `${pct}%`, background: SURFACE_COLORS[cat] ?? '#9ca3af' }}
          />
        ))}
      </div>
      {/* Labels */}
      <div style={{ display: 'flex', gap: '5px', flexWrap: 'wrap' }}>
        {entries.map(([cat, pct]) => (
          <span key={cat} style={{ display: 'flex', alignItems: 'center', gap: '3px', fontSize: '10px', color: '#6b7280' }}>
            <span style={{ width: '6px', height: '6px', borderRadius: '1px', background: SURFACE_COLORS[cat] ?? '#9ca3af', flexShrink: 0, display: 'inline-block' }} />
            {pct >= 5 ? `${SURFACE_LABELS[cat] ?? cat} ${Math.round(pct)}%` : `${Math.round(pct)}%`}
          </span>
        ))}
      </div>
    </div>
  )
}

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
        <span style={{
          display: 'inline-block',
          padding: '1px 6px',
          borderRadius: '4px',
          fontSize: '11px',
          fontWeight: 700,
          color: '#fff',
          background: flowGradeColor(flow_grade),
        }}>
          {flow_grade}
        </span>
        <button
          onClick={e => { e.stopPropagation(); downloadGPX(route) }}
          title="Download GPX"
          aria-label="Download GPX"
          style={{
            display: 'flex',
            alignItems: 'center',
            justifyContent: 'center',
            width: '22px',
            height: '22px',
            borderRadius: '4px',
            border: '1px solid #d1d5db',
            background: '#fff',
            cursor: 'pointer',
            color: '#6b7280',
            fontSize: '12px',
            flexShrink: 0,
            padding: 0,
          }}
        >
          ↓
        </button>
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
        marginBottom: '8px',
        overflow: 'hidden',
      }}
    >
      {/* Group header — click to expand/collapse */}
      <div
        onClick={() => onSelectGroup(group.startNodeId)}
        style={{ padding: '12px', cursor: 'pointer' }}
      >
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
          <div>
            <div style={{ fontWeight: 600, fontSize: '14px' }}>{metadata.name}</div>
            <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>
              {group.routes.length} {group.routes.length === 1 ? 'route' : 'routes'}
            </div>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
            <span style={{
              display: 'inline-block',
              padding: '2px 8px',
              borderRadius: '4px',
              fontSize: '13px',
              fontWeight: 700,
              color: '#fff',
              background: flowGradeColor(flow_grade),
            }}>
              {flow_grade}
            </span>
            <span style={{ fontSize: '11px', color: '#9ca3af' }}>{isActive ? '▲' : '▼'}</span>
          </div>
        </div>

        <div style={{ marginTop: '8px', fontSize: '13px' }}>
          {hasPhysics ? (
            <span>Top: <strong>{Math.round(top_speed_kmh!)} km/h</strong></span>
          ) : (
            <span
              className="shimmer"
              style={{
                display: 'inline-block',
                width: '80px',
                height: '16px',
                borderRadius: '4px',
                background: 'linear-gradient(90deg, #f0f0f0 25%, #e0e0e0 50%, #f0f0f0 75%)',
                backgroundSize: '200% 100%',
                animation: 'shimmer 1.2s infinite',
              }}
            />
          )}
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
