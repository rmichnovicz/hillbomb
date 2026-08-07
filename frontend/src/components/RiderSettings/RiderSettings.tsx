import { useState, useEffect } from 'react'
import { RIDER_PROFILES } from '../../types'
import type { RiderParams, RiderProfile } from '../../types'

interface RiderSettingsProps {
  profile: RiderProfile
  params: RiderParams
  onProfileChange: (profile: RiderProfile) => void
  onParamsChange: (params: RiderParams) => void
  isSearching: boolean
  activeRouteId?: string | null
}

const PROFILE_EMOJI: Record<RiderProfile, string> = {
  longboarder: '🛹',
  cyclist_upright: '🚲',
  cyclist_drops: '🚴',
  gravel: '🚵',
  mtb: '⛰️',
}

const PROFILE_LABEL: Record<RiderProfile, string> = {
  longboarder: 'Longboard',
  cyclist_upright: 'Upright',
  cyclist_drops: 'Drops',
  gravel: 'Gravel',
  mtb: 'MTB',
}

interface SliderRowProps {
  label: string
  value: number
  min: number
  max: number
  step: number
  format: (v: number) => string
  onChange: (v: number) => void
}

function SliderRow({ label, value, min, max, step, format, onChange }: SliderRowProps) {
  return (
    <div style={{ display: 'flex', alignItems: 'center', gap: '8px', marginBottom: '8px' }}>
      <span style={{ width: '90px', fontSize: '12px', color: '#374151', flexShrink: 0 }}>{label}</span>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={e => onChange(Number(e.target.value))}
        style={{ flex: 1 }}
        aria-label={label}
      />
      <span style={{ width: '48px', fontSize: '12px', color: '#6b7280', textAlign: 'right', flexShrink: 0 }}>
        {format(value)}
      </span>
    </div>
  )
}

export function RiderSettings({ profile, params, onProfileChange, onParamsChange, isSearching, activeRouteId }: RiderSettingsProps) {
  const [isOpen, setIsOpen] = useState(false)

  useEffect(() => {
    if (isSearching) setIsOpen(false)
  }, [isSearching])

  useEffect(() => {
    if (activeRouteId) setIsOpen(false)
  }, [activeRouteId])

  const set = (key: keyof RiderParams, value: number) =>
    onParamsChange({ ...params, [key]: value })

  return (
    <div style={{ borderTop: '1px solid #e5e7eb' }}>
      <button
        onClick={() => setIsOpen(o => !o)}
        aria-expanded={isOpen}
        style={{
          width: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
          padding: '10px 16px',
          background: 'none',
          border: 'none',
          cursor: 'pointer',
          fontSize: '12px',
          fontWeight: 600,
          color: '#374151',
          textAlign: 'left',
        }}
      >
        <span>Rider profile {PROFILE_EMOJI[profile]}</span>
        <span style={{ fontSize: '10px', color: '#9ca3af' }}>{isOpen ? '▾' : '▸'}</span>
      </button>

      {isOpen && (
        <div style={{ padding: '0 16px 12px' }}>
          {/* Grid, not a flex row: five profiles in one row leaves each ~40px wide. */}
          <div style={{
            display: 'grid',
            gridTemplateColumns: 'repeat(3, 1fr)',
            gap: '6px',
            marginBottom: '10px',
          }}>
            {(Object.keys(RIDER_PROFILES) as RiderProfile[]).map(p => (
              <button
                key={p}
                onClick={() => {
                  onProfileChange(p)
                  // Spread the whole preset so switching *off* a capped profile drops
                  // max_speed_kmh rather than carrying the cap onto tarmac.
                  onParamsChange({ ...RIDER_PROFILES[p], weight_kg: params.weight_kg })
                }}
                aria-pressed={profile === p}
                style={{
                  fontSize: '11px',
                  padding: '4px 0',
                  borderRadius: '4px',
                  border: '1px solid',
                  borderColor: profile === p ? '#3b82f6' : '#d1d5db',
                  background: profile === p ? '#eff6ff' : '#fff',
                  color: profile === p ? '#1d4ed8' : '#374151',
                  cursor: 'pointer',
                  fontWeight: profile === p ? 600 : 400,
                }}
              >
                {PROFILE_LABEL[p]} {PROFILE_EMOJI[p]}
              </button>
            ))}
          </div>

          <SliderRow
            label="Weight (kg)"
            value={params.weight_kg}
            min={40} max={140} step={1}
            format={v => `${v} kg`}
            onChange={v => set('weight_kg', v)}
          />
          <SliderRow
            label="Drag coeff."
            value={params.drag_coefficient}
            min={0.3} max={1.3} step={0.01}
            format={v => v.toFixed(2)}
            onChange={v => set('drag_coefficient', v)}
          />
          <SliderRow
            label="Frontal area"
            value={params.frontal_area_m2}
            min={0.15} max={0.70} step={0.01}
            format={v => `${v.toFixed(2)} m²`}
            onChange={v => set('frontal_area_m2', v)}
          />
          <SliderRow
            label="Rolling resist."
            value={params.crr_physics}
            min={0.001} max={0.030} step={0.001}
            format={v => v.toFixed(3)}
            onChange={v => set('crr_physics', v)}
          />

          {/* Only the dirt profiles carry a cap, so the row appears with them rather
              than sitting at "off" for everyone. The note is doing real work: without
              it a pegged-flat speed profile looks like a bug in the chart. */}
          {params.max_speed_kmh != null && (
            <>
              <SliderRow
                label="Top speed"
                value={params.max_speed_kmh}
                min={15} max={90} step={1}
                format={v => `${v} km/h`}
                onChange={v => set('max_speed_kmh', v)}
              />
              <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '-4px', marginBottom: '4px' }}>
                Braking isn't modelled; off-road the sim would run away without this.
              </div>
            </>
          )}

          <div style={{ borderTop: '1px solid #f3f4f6', marginTop: '4px', paddingTop: '8px' }}>
            <SliderRow
              label="Search Crr"
              value={params.crr_pathfinding}
              min={0.001} max={0.050} step={0.001}
              format={v => v.toFixed(3)}
              onChange={v => set('crr_pathfinding', v)}
            />
            <div style={{ fontSize: '11px', color: '#9ca3af', marginTop: '-4px', marginBottom: '4px' }}>
              Lower = explores further. Re-search to apply.
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
