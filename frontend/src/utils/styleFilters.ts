/**
 * Null-safety patch for a third-party base style's layer filters.
 *
 * MapLibre types an ordered comparison by whichever side is a literal, so
 * `["<=", ["get", "ref_length"], 6]` compiles with an implicit
 * `["number", ["get", "ref_length"]]` assertion on the other side. A feature
 * that lacks the property evaluates to null, the assertion throws, and MapLibre
 * logs `Expected value to be of type number, but found null instead.` — once per
 * expression instance per worker.
 *
 * OpenFreeMap's Liberty style ships three such filters (the US-interstate, US
 * and non-US highway-shield layers, all keyed on `ref_length`), and OpenMapTiles
 * omits `ref_length` from any road without a `ref` — 234 of 238 features in a
 * typical SF viewport. So it fired three times on every page load, at any zoom
 * past 9, for every visitor.
 *
 * The warning is cosmetic: a filter that throws evaluates to `false`, which is
 * the same answer the guard gives and the right one — no `ref` means no shield
 * to draw. We rewrite it anyway because a console that cries wolf on every load
 * is a console nobody reads, and because the e2e fixture asserts on console
 * output.
 */
import type { StyleSpecification } from 'react-map-gl/maplibre'

const ORDERED_OPS = new Set(['<', '<=', '>', '>='])

/** True for a filter {@link makeFilterNullSafe} already guarded. */
function isNullGuarded(filter: unknown[]): boolean {
  const [op, has, cmp] = filter
  return (
    op === 'all' && filter.length === 3 &&
    Array.isArray(has) && has[0] === 'has' &&
    Array.isArray(cmp) && ORDERED_OPS.has(cmp[0]) &&
    Array.isArray(cmp[1]) && cmp[1][0] === 'get' && cmp[1][1] === has[1]
  )
}

/**
 * Wrap every `[<|<=|>|>=, ["get", k], <number>]` in a `["has", k]` guard.
 *
 * Returns the input array itself when nothing changed — {@link patchStyleFilters}
 * relies on that identity to leave untouched layers alone.
 */
export function makeFilterNullSafe(filter: unknown): unknown {
  if (!Array.isArray(filter)) return filter
  const [op, lhs, rhs] = filter
  if (op === 'all' || op === 'any' || op === '!') {
    // Without this, the guard added below is itself an `all` wrapping a
    // comparison, so a second pass wraps it again — and again — growing the
    // filter without bound. Nothing re-runs this today; the failure would be
    // silent if something ever did.
    if (isNullGuarded(filter)) return filter
    const patched = filter.slice(1).map(makeFilterNullSafe)
    return patched.some((v, i) => v !== filter[i + 1]) ? [op, ...patched] : filter
  }
  if (
    ORDERED_OPS.has(op) &&
    Array.isArray(lhs) && lhs[0] === 'get' && typeof lhs[1] === 'string' &&
    typeof rhs === 'number'
  ) {
    return ['all', ['has', lhs[1]], filter]
  }
  return filter
}

/** Apply {@link makeFilterNullSafe} to every layer filter in a style document. */
export function patchStyleFilters(style: StyleSpecification): StyleSpecification {
  return {
    ...style,
    layers: style.layers.map(layer => {
      if (!('filter' in layer) || layer.filter === undefined) return layer
      const safe = makeFilterNullSafe(layer.filter)
      return safe === layer.filter ? layer : { ...layer, filter: safe as never }
    }),
  }
}
