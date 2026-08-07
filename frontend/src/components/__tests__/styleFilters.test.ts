import { describe, it, expect } from 'vitest'
import { makeFilterNullSafe, patchStyleFilters } from '../../utils/styleFilters'
import type { StyleSpecification } from 'react-map-gl/maplibre'

/**
 * MapLibre types an ordered comparison by whichever side is a literal, so
 * `["<=", ["get", "ref_length"], 6]` compiles to an implicit number assertion on
 * the other side. A feature missing that property evaluates to null, the
 * assertion throws, and MapLibre warns "Expected value to be of type number, but
 * found null instead." once per expression per worker.
 *
 * The real case is OpenFreeMap Liberty's three highway-shield layers: they all
 * filter on `ref_length`, which OpenMapTiles omits from any road without a `ref`
 * — the overwhelming majority. So it fired on every page load.
 */
const SHIELD_FILTER = [
  'all',
  ['<=', ['get', 'ref_length'], 6],
  ['match', ['geometry-type'], ['LineString', 'MultiLineString'], true, false],
]

describe('makeFilterNullSafe', () => {
  it('guards a bare ordered comparison against a missing property', () => {
    expect(makeFilterNullSafe(['<=', ['get', 'ref_length'], 6])).toEqual([
      'all', ['has', 'ref_length'], ['<=', ['get', 'ref_length'], 6],
    ])
  })

  it('guards a comparison nested inside a combinator', () => {
    expect(makeFilterNullSafe(SHIELD_FILTER)).toEqual([
      'all',
      ['all', ['has', 'ref_length'], ['<=', ['get', 'ref_length'], 6]],
      ['match', ['geometry-type'], ['LineString', 'MultiLineString'], true, false],
    ])
  })

  it('covers every ordered operator', () => {
    for (const op of ['<', '<=', '>', '>=']) {
      expect(makeFilterNullSafe([op, ['get', 'rank'], 3])).toEqual([
        'all', ['has', 'rank'], [op, ['get', 'rank'], 3],
      ])
    }
  })

  /**
   * The guard is itself an `all` wrapping a comparison, so a second pass would
   * wrap it again — and again — growing the filter without bound. Nothing
   * re-runs this today, but the failure would be silent.
   */
  it('is a fixed point: re-running changes nothing', () => {
    const once = makeFilterNullSafe(SHIELD_FILTER)
    expect(makeFilterNullSafe(once)).toBe(once)
  })

  it('returns the input unchanged when nothing needs guarding', () => {
    const filter = ['all', ['==', ['get', 'class'], 'country'], ['has', 'name']]
    expect(makeFilterNullSafe(filter)).toBe(filter)
  })

  it('leaves equality comparisons alone — they are null-tolerant already', () => {
    const filter = ['==', ['get', 'maritime'], 1]
    expect(makeFilterNullSafe(filter)).toBe(filter)
  })

  it('leaves a comparison between two properties alone', () => {
    // No literal to type the comparison, so MapLibre inserts no assertion.
    const filter = ['<', ['get', 'a'], ['get', 'b']]
    expect(makeFilterNullSafe(filter)).toBe(filter)
  })
})

describe('patchStyleFilters', () => {
  const style = {
    version: 8,
    sources: {},
    layers: [
      { id: 'shields', type: 'symbol', source: 'x', filter: SHIELD_FILTER },
      { id: 'plain', type: 'line', source: 'x', filter: ['==', ['get', 'class'], 'road'] },
      { id: 'unfiltered', type: 'background' },
    ],
  } as unknown as StyleSpecification

  // `filter` is absent from some members of the LayerSpecification union
  // (background layers have none), so reach for it through a filtered view.
  const filterOf = (spec: StyleSpecification, i: number) =>
    (spec.layers[i] as { filter?: unknown }).filter

  it('rewrites only the layers that need it, and does not mutate the input', () => {
    const patched = patchStyleFilters(style)
    expect(filterOf(patched, 0)).toEqual([
      'all',
      ['all', ['has', 'ref_length'], ['<=', ['get', 'ref_length'], 6]],
      ['match', ['geometry-type'], ['LineString', 'MultiLineString'], true, false],
    ])
    expect(patched.layers[1]).toBe(style.layers[1])
    expect(patched.layers[2]).toBe(style.layers[2])
    expect(filterOf(style, 0)).toBe(SHIELD_FILTER)
  })
})
