import type { Route } from '../types'

export function routeToGPX(route: Route): string {
  const { name } = route.metadata
  const coords = route.geometry.coordinates
  const elevs = route.elevations

  const trkpts = coords
    .map(([lon, lat], i) => {
      const ele = elevs[i] !== undefined ? `\n        <ele>${elevs[i].toFixed(1)}</ele>` : ''
      return `      <trkpt lat="${lat.toFixed(7)}" lon="${lon.toFixed(7)}">${ele}\n      </trkpt>`
    })
    .join('\n')

  return `<?xml version="1.0" encoding="UTF-8"?>
<gpx version="1.1" creator="Hillbomb" xmlns="http://www.topografix.com/GPX/1/1">
  <trk>
    <name>${escapeXML(name)}</name>
    <trkseg>
${trkpts}
    </trkseg>
  </trk>
</gpx>`
}

function escapeXML(s: string): string {
  return s.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')
}

export function downloadGPX(route: Route): void {
  const gpx = routeToGPX(route)
  const blob = new Blob([gpx], { type: 'application/gpx+xml' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${route.metadata.name.replace(/[^a-z0-9]/gi, '_')}.gpx`
  a.click()
  URL.revokeObjectURL(url)
}
