/**
 * Human names for the individual lines of a curated spot.
 *
 * A spot is one named road, so every route in it carries the same `metadata.name` —
 * Hawk Hill lists three "Conzelman Road"s, which tells a rider nothing about which is
 * which. What distinguishes them is where they go: the west drop to Point Bonita versus
 * the east one back toward the bridge.
 *
 * Direction is derived from the descent's net heading, start to finish, not from its
 * opening metres — a canyon road switchbacks constantly, and the direction a rider means
 * is the one the whole run travels.
 *
 * Direction alone separates most spots, but not a street cut into blocks that all run
 * the same way: Marin Avenue has three southwest lines, Baxter three northwest. Those
 * get an Upper/Middle/Lower qualifier by start elevation, which is what a rider calls
 * them anyway. Labels therefore depend on a route's siblings — build them for the whole
 * set at once, not one at a time.
 */
import type { Route } from '../types'

const COMPASS = [
  'North', 'Northeast', 'East', 'Southeast',
  'South', 'Southwest', 'West', 'Northwest',
] as const

/** Compass bearing in degrees clockwise from north, from the first point to the last. */
function netBearing(coords: number[][]): number {
  const [lon1, lat1] = coords[0]
  const [lon2, lat2] = coords[coords.length - 1]
  const φ1 = lat1 * Math.PI / 180, φ2 = lat2 * Math.PI / 180
  const Δλ = (lon2 - lon1) * Math.PI / 180
  const y = Math.sin(Δλ) * Math.cos(φ2)
  const x = Math.cos(φ1) * Math.sin(φ2) - Math.sin(φ1) * Math.cos(φ2) * Math.cos(Δλ)
  return (Math.atan2(y, x) * 180 / Math.PI + 360) % 360
}

/** The eight-point compass direction a route travels, e.g. "West", "Northeast". */
export function descentDirection(route: Route): string | null {
  const coords = route.geometry?.coordinates
  if (!coords || coords.length < 2) return null
  // 45° sectors centred on each compass point, so 337.5°–22.5° reads as North.
  return COMPASS[Math.round(netBearing(coords) / 45) % 8]
}

/** Where a run starts, for ordering same-direction siblings top to bottom. */
function startElevation(route: Route): number {
  return route.elevations?.[0] ?? 0
}

/** Position words for 2 and 3 same-direction siblings; beyond that, plain numbering. */
function positionWords(count: number): string[] | null {
  if (count === 2) return ['Upper', 'Lower']
  if (count === 3) return ['Upper', 'Middle', 'Lower']
  return null
}

/**
 * route_id → display name, e.g. "West descent" or "Upper Southwest descent".
 *
 * Routes with no usable geometry fall back to their road name, so a card is never left
 * without a title.
 */
export function buildDescentLabels(routes: Route[]): Map<string, string> {
  const byDirection = new Map<string, Route[]>()
  for (const r of routes) {
    const dir = descentDirection(r)
    if (!dir) continue
    const siblings = byDirection.get(dir) ?? []
    siblings.push(r)
    byDirection.set(dir, siblings)
  }

  const labels = new Map<string, string>()
  for (const r of routes) labels.set(r.route_id, r.metadata.name)

  for (const [dir, siblings] of byDirection) {
    if (siblings.length === 1) {
      labels.set(siblings[0].route_id, `${dir} descent`)
      continue
    }
    const highestFirst = [...siblings].sort((a, b) => startElevation(b) - startElevation(a))
    const words = positionWords(highestFirst.length)
    highestFirst.forEach((r, i) => {
      labels.set(r.route_id, words ? `${words[i]} ${dir} descent` : `${dir} descent ${i + 1}`)
    })
  }

  return labels
}
