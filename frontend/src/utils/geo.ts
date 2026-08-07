/**
 * Great-circle distance and nearest-region selection.
 *
 * Used to turn Cloudflare's IP geolocation (see functions/api/where.js) into "which
 * curated region should the Collections tab open?". Kept pure and separate from the
 * fetch so the choice is testable without a network.
 */
import type { CollectionCity } from '../types'

const EARTH_RADIUS_KM = 6371

const toRad = (deg: number): number => (deg * Math.PI) / 180

/** Great-circle distance in km between two [lat, lon] points. */
export function haversineKm(
  lat1: number, lon1: number,
  lat2: number, lon2: number,
): number {
  const dLat = toRad(lat2 - lat1)
  const dLon = toRad(lon2 - lon1)
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2
  return 2 * EARTH_RADIUS_KM * Math.asin(Math.min(1, Math.sqrt(a)))
}

/**
 * The region containing the curated descent closest to a point, or null if even that
 * one is further than `maxKm`.
 *
 * Scored on the nearest *spot*, not on the region's centroid, because these regions
 * are wildly different shapes. "Denver / Boulder" is a metro; "Great Lakes" is five
 * descents spread from Michigan's Keweenaw Peninsula to southern Wisconsin, and its
 * centroid lands in Lake Michigan. Measured against the real catalog, centroids put
 * Chicago 523 km from everything (no match at all, when Holy Hill is 160 km away) and
 * New York City 238 km from "New York" (Bear Mountain is 67 km away). Scoring on the
 * nearest spot fixes both and asks the question the user actually has: is there
 * anything good near me?
 *
 * The distance cap is the other half, and it matters as much. Nearest-of-34 always
 * returns *something*, so without it a visitor in Wichita gets confidently dropped
 * into the Ozarks — a guess presented as an answer. Past the cap, leave the list
 * collapsed and let them choose.
 */
export function nearestCity(
  cities: CollectionCity[],
  lat: number,
  lon: number,
  maxKm = 300,
): string | null {
  let best: string | null = null
  let bestKm = Infinity

  for (const city of cities) {
    for (const spot of city.spots) {
      if (!spot.center) continue
      // `center` is [lon, lat]; haversineKm takes lat first.
      const km = haversineKm(lat, lon, spot.center[1], spot.center[0])
      if (km < bestKm) {
        bestKm = km
        best = city.city
      }
    }
  }

  return bestKm <= maxKm ? best : null
}
