/** GPX download button for a single route. Shared by StartGroupCard and RouteCard. */
import { useState } from 'react'
import { downloadGPX } from '../../utils/gpx'
import type { Route } from '../../types'

/** Tray-and-arrow download icon. Inherits color via `currentColor`. */
function DownloadIcon() {
  return (
    <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 21h14" />
    </svg>
  )
}

export function DownloadButton({ route }: { route: Route }) {
  const [hover, setHover] = useState(false)
  return (
    <button
      onClick={e => { e.stopPropagation(); downloadGPX(route) }}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      title="Download GPX"
      aria-label="Download GPX"
      style={{
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        width: '24px',
        height: '24px',
        borderRadius: '6px',
        border: 'none',
        background: hover ? '#eff6ff' : 'transparent',
        cursor: 'pointer',
        color: hover ? '#2563eb' : '#9ca3af',
        flexShrink: 0,
        padding: 0,
        transition: 'background 120ms, color 120ms',
      }}
    >
      <DownloadIcon />
    </button>
  )
}
