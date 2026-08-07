import { describe, it, expect } from 'vitest'
import { haversineKm, nearestCity } from '../../utils/geo'
import type { CollectionCity, CollectionSpotSummary } from '../../types'

/** A spot summary with only the field `nearestCity` reads filled in for real. */
function spot(lon: number, lat: number): CollectionSpotSummary {
  return {
    slug: `s${lon},${lat}`, name: 'x', state: 'XX', blurb: '', disciplines: [],
    notes: '', center: [lon, lat], bbox: [lat, lon, lat, lon], route_count: 1,
    length_m: 0, total_descent_m: 0, avg_grade_pct: 0, top_speed_kmh: 0, flow_grade: '',
  }
}

// Centers are [lon, lat].
const CITIES: CollectionCity[] = [
  { city: 'San Francisco Bay Area', spots: [spot(-122.44, 37.77)] },
  { city: 'Denver / Boulder', spots: [spot(-105.10, 39.90)] },
  { city: 'Los Angeles', spots: [spot(-118.40, 34.10)] },
  { city: 'Portland', spots: [spot(-122.68, 45.52)] },
  { city: 'Seattle', spots: [spot(-122.33, 47.61)] },
  // A sprawling region, like the real "Great Lakes": five descents across three
  // states whose mean position is open water, hundreds of km from any of them.
  { city: 'Great Lakes', spots: [spot(-87.99, 47.47), spot(-92.01, 46.85), spot(-88.24, 43.25)] },
]

describe('haversineKm', () => {
  it('is zero for a point against itself', () => {
    expect(haversineKm(37.77, -122.44, 37.77, -122.44)).toBe(0)
  })

  it('matches a known distance (SF → LA ≈ 547 km)', () => {
    expect(haversineKm(37.77, -122.44, 34.10, -118.40)).toBeCloseTo(546.5, 0)
  })

  it('is symmetric', () => {
    const a = haversineKm(37.77, -122.44, 45.52, -122.68)
    const b = haversineKm(45.52, -122.68, 37.77, -122.44)
    expect(a).toBeCloseTo(b, 9)
  })
})

describe('nearestCity', () => {
  it('picks the region the visitor is standing in', () => {
    expect(nearestCity(CITIES, 37.79, -122.40)).toBe('San Francisco Bay Area')
    expect(nearestCity(CITIES, 39.74, -104.99)).toBe('Denver / Boulder')
  })

  // The case timezone can't do: these two share America/Los_Angeles but are 250 km
  // apart, so distance has to be what separates them.
  it('separates Portland from Seattle', () => {
    expect(nearestCity(CITIES, 45.51, -122.67)).toBe('Portland')
    expect(nearestCity(CITIES, 47.60, -122.33)).toBe('Seattle')
  })

  it('returns null when nothing curated is within range', () => {
    // Wichita, KS — nothing here is close.
    expect(nearestCity(CITIES, 37.69, -97.34)).toBeNull()
  })

  it('honors a custom range cap', () => {
    expect(nearestCity(CITIES, 37.69, -97.34, 1000)).toBe('Denver / Boulder')
  })

  // The reason this scores on the nearest spot rather than a regional centroid:
  // Chicago is ~160 km from the Wisconsin descent but ~520 km from the mean of the
  // three, so a centroid would report no match at all.
  it('finds a sprawling region by its closest spot, not its mean position', () => {
    expect(nearestCity(CITIES, 41.88, -87.63)).toBe('Great Lakes')
  })

  it('returns null for an empty catalog', () => {
    expect(nearestCity([], 37.77, -122.44)).toBeNull()
  })

  it('skips regions with no spots rather than ranking them at NaN', () => {
    const withEmpty: CollectionCity[] = [{ city: 'Empty', spots: [] }, ...CITIES]
    expect(nearestCity(withEmpty, 37.79, -122.40)).toBe('San Francisco Bay Area')
  })
})
