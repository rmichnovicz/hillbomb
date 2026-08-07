/**
 * The visitor's approximate location, from Cloudflare's edge IP geolocation.
 *
 * Fetched once on mount, never blocking anything: the app renders its normal default
 * immediately and this only ever *upgrades* that default once the answer arrives. A
 * guess about which region to open is not worth a spinner.
 *
 * Returns null forever when there is no answer — which is the common case outside
 * production. `/api/where` is a Cloudflare Pages Function, so it exists on the CDN
 * deploy and nowhere else; under `npm run dev`, `docker run`, and the test suite the
 * request 404s (or, against FastAPI's SPA fallback, returns index.html with a 200).
 * Both are handled the same way — no location, no auto-selection, no error surfaced.
 * Nothing in the app should depend on this resolving.
 */
import { useState, useEffect } from 'react'
import { whereUrl } from '../api'

export interface IpLocation {
  lat: number
  lon: number
  /** Display/debug only — region selection is done on distance, never on these. */
  city: string | null
  region: string | null
  country: string | null
}

export function useIpLocation(): IpLocation | null {
  const [location, setLocation] = useState<IpLocation | null>(null)

  useEffect(() => {
    let cancelled = false

    ;(async () => {
      try {
        const res = await fetch(whereUrl())
        if (!res.ok) return
        const doc: unknown = await res.json()
        if (cancelled) return

        // Validated rather than trusted: the SPA fallback can answer this URL with
        // something that parses but isn't a location.
        if (!doc || typeof doc !== 'object') return
        const { lat, lon, city, region, country } = doc as Record<string, unknown>
        if (typeof lat !== 'number' || typeof lon !== 'number') return
        if (!Number.isFinite(lat) || !Number.isFinite(lon)) return

        setLocation({
          lat,
          lon,
          city: typeof city === 'string' ? city : null,
          region: typeof region === 'string' ? region : null,
          country: typeof country === 'string' ? country : null,
        })
      } catch {
        // Offline, 404, or a body that isn't JSON. All mean the same thing here.
      }
    })()

    return () => { cancelled = true }
  }, [])

  return location
}
