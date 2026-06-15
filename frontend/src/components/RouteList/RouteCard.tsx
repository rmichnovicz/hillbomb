import { flowGradeColor } from '../../utils/gradeColor'
import type { Route } from '../../types'

interface RouteCardProps {
  route: Route
  isActive: boolean
  onSelect: (routeId: string) => void
  onSave: (routeId: string) => void
  isSaved: boolean
}

function formatLength(m: number): string {
  return m >= 1000 ? `${(m / 1000).toFixed(1)} km` : `${Math.round(m)} m`
}

export function RouteCard({ route, isActive, onSelect, onSave, isSaved }: RouteCardProps) {
  const { route_id, metadata, flow_grade, top_speed_kmh, avg_speed_kmh } = route

  return (
    <div
      role="listitem"
      aria-selected={isActive}
      onClick={() => onSelect(route_id)}
      style={{
        padding: '12px',
        border: isActive ? '2px solid #3b82f6' : '1px solid #e5e7eb',
        borderRadius: '8px',
        cursor: 'pointer',
        background: isActive ? '#eff6ff' : '#fff',
        marginBottom: '8px',
      }}
    >
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start' }}>
        <div>
          <div style={{ fontWeight: 600, fontSize: '14px' }}>{metadata.name}</div>
          <div style={{ fontSize: '12px', color: '#6b7280', marginTop: '2px' }}>
            {formatLength(metadata.length_m)} &middot; {Math.round(metadata.total_descent_m)} m descent
          </div>
        </div>

        <span
          style={{
            display: 'inline-block',
            padding: '2px 8px',
            borderRadius: '4px',
            fontSize: '13px',
            fontWeight: 700,
            color: '#fff',
            background: flowGradeColor(flow_grade),
          }}
        >
          {flow_grade}
        </span>
      </div>

      <div style={{ marginTop: '8px', display: 'flex', gap: '12px', fontSize: '13px' }}>
        <>
          <span>Top: <strong>{Math.round(top_speed_kmh)} km/h</strong></span>
          <span>Avg: <strong>{Math.round(avg_speed_kmh)} km/h</strong></span>
        </>

        <button
          onClick={e => { e.stopPropagation(); onSave(route_id) }}
          aria-label={isSaved ? 'Saved' : 'Save'}
          style={{
            marginLeft: 'auto',
            fontSize: '12px',
            padding: '2px 8px',
            borderRadius: '4px',
            border: '1px solid #d1d5db',
            background: isSaved ? '#e0f2fe' : '#fff',
            cursor: 'pointer',
          }}
        >
          {isSaved ? 'Saved' : 'Save'}
        </button>
      </div>
    </div>
  )
}
