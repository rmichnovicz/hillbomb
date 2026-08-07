/** Proportional surface-mix bar with labels. Shared by StartGroupCard and RouteCard. */

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

export function SurfaceBar({ surfacePcts }: { surfacePcts: Record<string, number> }) {
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
