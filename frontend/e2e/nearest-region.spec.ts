/**
 * Opening the visitor's nearest curated region from IP geolocation.
 *
 * `/api/where` is a Cloudflare Pages Function — it does not exist under `vite preview`,
 * and it does not exist in the deployed bundle either, only on the CDN in front of it.
 * So every test here fulfils it by route interception, which is also what makes it
 * possible to be in Denver and Wichita in the same suite.
 *
 * These run against the production build for the usual reason (see playwright.config),
 * plus a specific one: the effect chain here is load-order sensitive — geolocation, the
 * collections index, and the MapLibre instance all arrive asynchronously and in no
 * guaranteed order — and jsdom does not have a map at all.
 */
import { test, expect } from './fixtures'

/** Somewhere in each region, close enough that `nearestCity` picks it. */
const SF = { lat: 37.7749, lon: -122.4194, city: 'San Francisco', region: 'California' }
const DENVER = { lat: 39.7392, lon: -104.9903, city: 'Denver', region: 'Colorado' }
// ~380 km from the nearest curated descent, past the 300 km cap.
const WICHITA = { lat: 37.6872, lon: -97.3301, city: 'Wichita', region: 'Kansas' }

type Where = { lat: number; lon: number; city: string; region: string } | null

/** Stub the Pages Function. `null` stands for "Cloudflare could not resolve it". */
async function stubWhere(page: import('@playwright/test').Page, where: Where): Promise<void> {
  await page.route('**/api/where', route =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(
        where === null
          ? { lat: null, lon: null, city: null, region: null, country: null }
          : { ...where, country: 'US' },
      ),
    }),
  )
}

const MOBILE = { width: 390, height: 844 }

/** The collapsed bottom sheet's label — the whole mobile payoff, in one string. */
const sheetLabel = (page: import('@playwright/test').Page) =>
  page.getByRole('button', { name: 'Expand panel' })

test.describe('nearest region from IP', () => {
  test('mobile opens the nearest region and names it on the collapsed sheet', async ({ page }) => {
    await page.setViewportSize(MOBILE)
    await stubWhere(page, SF)
    await page.goto('/')

    await expect(sheetLabel(page)).toContainText(/\d+ descents in San Francisco Bay Area/)
    // Collections, not Search — that is what puts the region's lines on the map.
    await expect(page.getByRole('tab', { name: 'Collections' })).toHaveAttribute('aria-selected', 'true')
    // And the sheet stays shut: the map keeps the screen.
    await expect(page.getByRole('button', { name: 'Expand panel' })).toBeVisible()
  })

  test('a different location opens a different region', async ({ page }) => {
    await page.setViewportSize(MOBILE)
    await stubWhere(page, DENVER)
    await page.goto('/')

    await expect(sheetLabel(page)).toContainText(/\d+ descents in Denver \/ Boulder/)
  })

  // NOT TESTED HERE: that the map actually flies to the region.
  //
  // It is a real failure mode — the region opens in the list while the map stays on
  // the hardcoded -122.44/37.76 default, which from San Francisco looks completely
  // correct — and it was verified by hand from a Denver stub. But every way of
  // asserting it (reading the map object out of the page, or watching which basemap
  // tiles get requested) needs the MapLibre style and tiles to actually load, and
  // those come from openfreemap.org. Run alongside the rest of the suite, that CDN
  // throttles enough that the assertion failed roughly two runs in three at both 6
  // and 3 workers, while passing every time on its own. A test that red-flags
  // two-thirds of clean runs is worse than the gap it covers.
  //
  // To reinstate it, the suite needs a local style fixture rather than a live CDN —
  // which would also settle the pre-existing flakiness in collections.spec's
  // map-click test.

  test.skip('the map ends up framed on the region, not the default viewport', async ({ page }) => {
    // The failure this exists for: the region opens in the list but the map never
    // moves, leaving it on the hardcoded -122.44/37.76 default. From San Francisco
    // that looks completely plausible, which is exactly why it needs a test and why
    // that test has to be somewhere other than San Francisco.
    //
    // Asserted on which basemap tiles get requested rather than by reading the map
    // object out of the page: the map exposes itself on its container only after its
    // style resolves, and under a parallel run that lost a 20s race often enough to
    // make the test useless. Tile requests need no page internals and no WebGL
    // introspection — if the viewport is over Colorado, Colorado tiles are fetched.
    const tiles: { z: number; lon: number; lat: number }[] = []
    page.on('request', req => {
      const m = req.url().match(/\/(\d+)\/(\d+)\/(\d+)(?:\.\w+)?(?:\?|$)/)
      if (!m) return
      const [z, x, y] = [Number(m[1]), Number(m[2]), Number(m[3])]
      // Below z9 one tile spans several states and can't tell these apart.
      if (z < 9 || z > 22) return
      const n = 2 ** z
      const lon = (x / n) * 360 - 180
      const lat = (Math.atan(Math.sinh(Math.PI * (1 - (2 * y) / n))) * 180) / Math.PI
      tiles.push({ z, lon, lat })
    })

    await page.setViewportSize(MOBILE)
    await stubWhere(page, DENVER)
    await page.goto('/')

    await expect(sheetLabel(page)).toContainText(/Denver \/ Boulder/)

    const overColorado = (t: { lon: number; lat: number }) =>
      t.lat > 37 && t.lat < 41.5 && t.lon > -109.5 && t.lon < -101.5

    await expect
      .poll(() => tiles.some(overColorado), {
        message:
          'no basemap tile over Colorado was ever requested — the map never left its ' +
          'default viewport',
        timeout: 30_000,
      })
      .toBe(true)
  })

  test('too far from anything curated: nothing is opened', async ({ page }) => {
    await page.setViewportSize(MOBILE)
    await stubWhere(page, WICHITA)
    await page.goto('/')

    // Falls back to the generic prompt, and stays on Search — exactly as before any
    // of this existed.
    await expect(sheetLabel(page)).toContainText('Tap to open search')
    await expect(page.getByRole('tab', { name: 'Search' })).toHaveAttribute('aria-selected', 'true')
  })

  test('no geolocation at all: nothing is opened', async ({ page }) => {
    await page.setViewportSize(MOBILE)
    await stubWhere(page, null)
    await page.goto('/')

    await expect(sheetLabel(page)).toContainText('Tap to open search')
  })

  test('desktop does not spend the region fetch until the tab is opened', async ({ page }) => {
    const spotFetches: string[] = []
    page.on('request', req => {
      const u = req.url()
      if (u.includes('/collections/') && !u.includes('index.json')) spotFetches.push(u)
    })

    await stubWhere(page, SF)
    await page.goto('/')
    await expect(page.getByRole('tab', { name: 'Search' })).toHaveAttribute('aria-selected', 'true')
    expect(spotFetches, 'desktop prefetched a region before the tab was opened').toEqual([])

    // Opening the tab then finds the region already chosen.
    await page.getByRole('tab', { name: 'Collections' }).click()
    await expect(page.getByRole('button', { name: /San Francisco Bay Area/ })).toBeVisible()
  })
})
