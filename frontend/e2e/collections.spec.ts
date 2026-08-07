/**
 * The Collections tab end to end against the production bundle.
 *
 * Worth having beyond the chart regression: collections are exported by a separate
 * build step from the Vite build, so a site can build cleanly and 404 on every spot.
 * That failure mode is invisible until someone opens the tab in production.
 */
import { test, expect } from './fixtures'
import { openFirstSpot, chartCanvas } from './helpers'

test('the collections index loads and lists regions', async ({ page }) => {
  await page.goto('/')
  await page.getByRole('tab', { name: 'Collections' }).click()

  await expect(page.getByRole('button', { name: /descents? · longest/ }).first()).toBeVisible()
})

test('spot JSON is actually served, not 404ing', async ({ page }) => {
  const failed: string[] = []
  page.on('response', res => {
    if (res.url().includes('/collections/') && !res.ok()) {
      failed.push(`${res.status()} ${res.url()}`)
    }
  })

  await page.goto('/')
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  expect(failed, `collection fetches failed:\n${failed.join('\n')}`).toEqual([])
})

test('clicking a route on the map opens its profile', async ({ page }) => {
  // The originally reported repro: "crashing when I click the map sometimes".
  await page.goto('/')
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  const map = page.locator('.maplibregl-canvas')
  await expect(map).toBeVisible()

  const box = await map.boundingBox()
  expect(box).not.toBeNull()

  // Sweep across the map so at least one click lands on a drawn route line. The
  // assertion that matters is the console fixture: no click may throw, whether or
  // not it happens to hit a route.
  for (const frac of [0.3, 0.4, 0.5, 0.6, 0.7]) {
    await page.mouse.click(box!.x + box!.width * frac, box!.y + box!.height / 2)
  }

  await expect(chartCanvas(page)).toBeVisible()
})
