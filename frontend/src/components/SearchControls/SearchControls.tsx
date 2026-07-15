import { useState, useEffect } from 'react'
import type { Toggles } from '../../types'

interface ToggleConfig {
  key: keyof Toggles
  label: string
  tooltip: string
}

const TOGGLE_CONFIGS: ToggleConfig[] = [
  {
    key: 'avoid_stoplights',
    label: 'Avoid stoplights',
    tooltip: 'Stop routes that hit a traffic signal. Signal coverage in OSM is reliable.',
  },
  {
    key: 'avoid_stop_signs',
    label: 'Avoid stop signs',
    tooltip: 'Stop routes at stop signs. Note: stop sign coverage in OSM is incomplete — many intersections may not be tagged.',
  },
  {
    key: 'avoid_bigger_roads',
    label: 'Avoid crossing bigger roads',
    tooltip: 'Stop routes that cross onto a higher road class (e.g. residential → primary).',
  },
  {
    key: 'avoid_equal_roads',
    label: 'Avoid crossing equal roads',
    tooltip: 'Stop routes when they transition to an equal-class but different road.',
  },
  {
    key: 'exclude_tunnels',
    label: 'Exclude tunnels',
    tooltip: 'Skip ways tagged as tunnels entirely.',
  },
  {
    key: 'exclude_bridges',
    label: 'Exclude bridges',
    tooltip: 'Skip ways tagged as bridges entirely.',
  },
  {
    key: 'stay_on_initial_road',
    label: "Don't leave initial road",
    tooltip: 'Keep routes on the road they start on. Connected ways sharing the same name are allowed; turning onto a differently-named road ends the route. Roads with no name in OSM only continue onto other unnamed ways.',
  },
  {
    key: 'animate_candidates',
    label: 'Animate candidates',
    tooltip: 'Flash candidate paths on the map as the algorithm explores them. Slower on large areas.',
  },
]

// Slider steps: [label, max_road_rank]
const ROAD_SIZE_STEPS: [string, number][] = [
  ['Paths & cycleways', 0],
  ['+ Service roads', 2],
  ['+ Residential', 3],
  ['+ Tertiary', 5],
  ['+ Secondary', 6],
  ['+ Primary', 7],
  ['All roads', 9],
]
const DEFAULT_ROAD_SIZE_STEP = 5  // "+ Primary" (rank 7)

export const ALL_SURFACE_CATEGORIES = ['paved', 'gravel', 'unpaved', 'cobblestone', 'unknown'] as const
export type SurfaceCategory = typeof ALL_SURFACE_CATEGORIES[number]

const SURFACE_LABELS: Record<SurfaceCategory, string> = {
  paved: 'Paved (asphalt, concrete)',
  gravel: 'Gravel / compacted',
  unpaved: 'Unpaved / dirt',
  cobblestone: 'Cobblestone / sett',
  unknown: 'Unknown / untagged',
}

const SURFACE_TITLES: Record<SurfaceCategory, string> = {
  paved: 'Include ways with a paved surface',
  gravel: 'Include ways with a gravel surface',
  unpaved: 'Include ways with an unpaved surface',
  cobblestone: 'Include ways with a cobblestone surface',
  unknown: 'Include ways with no surface tag in OSM (or an unrecognized one). Most roads are untagged — unchecking this is aggressive.',
}

export const MIN_DISTANCE_MAX_M = 3000
export const MIN_DISTANCE_STEP_M = 50

function formatDistance(m: number): string {
  if (m === 0) return 'No minimum'
  if (m < 1000) return `${m} m`
  return `${(m / 1000).toFixed(1)} km`
}

interface SearchControlsProps {
  isSearching: boolean
  toggles: Toggles
  onTogglesChange: (toggles: Toggles) => void
  roadSizeStep: number
  onRoadSizeChange: (step: number) => void
  allowedSurfaces: SurfaceCategory[]
  onAllowedSurfacesChange: (surfaces: SurfaceCategory[]) => void
  minDistanceM: number
  onMinDistanceChange: (m: number) => void
  onSearch: () => void
  onStop: () => void
  activeRouteId?: string | null
}

export function SearchControls({
  isSearching,
  toggles,
  onTogglesChange,
  roadSizeStep,
  onRoadSizeChange,
  allowedSurfaces,
  onAllowedSurfacesChange,
  minDistanceM,
  onMinDistanceChange,
  onSearch,
  onStop,
  activeRouteId,
}: SearchControlsProps) {
  const [advancedOpen, setAdvancedOpen] = useState(false)

  useEffect(() => {
    if (isSearching) setAdvancedOpen(false)
  }, [isSearching])

  useEffect(() => {
    if (activeRouteId) setAdvancedOpen(false)
  }, [activeRouteId])

  const handleToggle = (key: keyof Toggles) => {
    onTogglesChange({ ...toggles, [key]: !toggles[key] })
  }

  const handleSurfaceToggle = (cat: SurfaceCategory) => {
    if (allowedSurfaces.includes(cat)) {
      onAllowedSurfacesChange(allowedSurfaces.filter(s => s !== cat))
    } else {
      onAllowedSurfacesChange([...allowedSurfaces, cat])
    }
  }

  const [roadLabel] = ROAD_SIZE_STEPS[roadSizeStep]

  return (
    <div style={{ borderTop: '1px solid #e5e7eb', background: '#fff' }}>
      {/* Search / Stop button — always visible */}
      <div style={{ padding: '12px 16px 10px' }}>
        <button
          onClick={isSearching ? onStop : onSearch}
          aria-label={isSearching ? 'Stop' : 'Search this area'}
          style={{
            width: '100%',
            padding: '9px',
            borderRadius: '6px',
            border: 'none',
            background: isSearching ? '#ef4444' : '#3b82f6',
            color: '#fff',
            fontWeight: 600,
            fontSize: '14px',
            cursor: 'pointer',
          }}
        >
          {isSearching ? 'Stop' : 'Search this area'}
        </button>
      </div>

      {/* Advanced settings — collapsible */}
      <button
        onClick={() => setAdvancedOpen(o => !o)}
        aria-expanded={advancedOpen}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '4px 16px 10px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: '12px',
          fontWeight: 600,
          color: '#374151',
          textAlign: 'left',
        }}
      >
        <span>Advanced settings</span>
        <span style={{ fontSize: '10px', color: '#9ca3af' }}>{advancedOpen ? '▾' : '▸'}</span>
      </button>

      {advancedOpen && (
        <div style={{ maxHeight: '195px', overflowY: 'auto', display: 'flex', flexDirection: 'column', gap: '12px', padding: '0 16px 14px' }}>

          {/* Road size slider */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#374151' }}>Max road size</span>
              <span style={{ fontSize: '12px', color: '#6b7280' }}>{roadLabel}</span>
            </div>
            <input
              type="range"
              min={0}
              max={ROAD_SIZE_STEPS.length - 1}
              step={1}
              value={roadSizeStep}
              disabled={isSearching}
              onChange={e => onRoadSizeChange(Number(e.target.value))}
              style={{ width: '100%', cursor: isSearching ? 'not-allowed' : 'pointer', opacity: isSearching ? 0.5 : 1 }}
              aria-label="Max road size"
              title="Limit which road classes are included in the search"
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#9ca3af', marginTop: '2px' }}>
              <span>Paths</span>
              <span>All roads</span>
            </div>
          </div>

          {/* Min distance slider */}
          <div>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: '4px' }}>
              <span style={{ fontSize: '12px', fontWeight: 600, color: '#374151' }}>Min distance</span>
              <span style={{ fontSize: '12px', color: minDistanceM > 0 ? '#3b82f6' : '#6b7280' }}>{formatDistance(minDistanceM)}</span>
            </div>
            <input
              type="range"
              min={0}
              max={MIN_DISTANCE_MAX_M}
              step={MIN_DISTANCE_STEP_M}
              value={minDistanceM}
              onChange={e => onMinDistanceChange(Number(e.target.value))}
              style={{ width: '100%', cursor: 'pointer' }}
              aria-label="Minimum route distance"
              title="Hide routes shorter than this distance"
            />
            <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: '10px', color: '#9ca3af', marginTop: '2px' }}>
              <span>Any</span>
              <span>3 km</span>
            </div>
          </div>

          {/* Terrain + behaviour checkboxes unified */}
          <div>
            <div style={{ fontSize: '12px', fontWeight: 600, color: '#374151', marginBottom: '6px' }}>
              Allowed terrain
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: '3px' }}>
              {ALL_SURFACE_CATEGORIES.map(cat => (
                <label
                  key={cat}
                  title={SURFACE_TITLES[cat]}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    fontSize: '12px',
                    color: '#374151',
                    cursor: isSearching ? 'not-allowed' : 'pointer',
                    opacity: isSearching ? 0.5 : 1,
                  }}
                >
                  <input
                    type="checkbox"
                    checked={allowedSurfaces.includes(cat)}
                    disabled={isSearching}
                    onChange={() => handleSurfaceToggle(cat)}
                    style={{ cursor: isSearching ? 'not-allowed' : 'pointer' }}
                  />
                  {SURFACE_LABELS[cat]}
                </label>
              ))}
              <div style={{ height: '1px', background: '#e5e7eb', margin: '4px 0' }} />
              {TOGGLE_CONFIGS.map(({ key, label, tooltip }) => (
                <label
                  key={key}
                  title={tooltip}
                  style={{
                    display: 'flex',
                    alignItems: 'center',
                    gap: '8px',
                    fontSize: '12px',
                    color: '#374151',
                    cursor: isSearching ? 'not-allowed' : 'pointer',
                    opacity: isSearching ? 0.5 : 1,
                  }}
                >
                  <input
                    type="checkbox"
                    aria-label={label}
                    checked={toggles[key] as boolean}
                    disabled={isSearching}
                    onChange={() => handleToggle(key)}
                    style={{ cursor: isSearching ? 'not-allowed' : 'pointer' }}
                  />
                  {label}
                </label>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}

export { DEFAULT_ROAD_SIZE_STEP, ROAD_SIZE_STEPS }
