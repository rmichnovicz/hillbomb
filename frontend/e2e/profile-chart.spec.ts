/**
 * The profile chart, exercised in a real browser against the production bundle.
 *
 * Regression origin: the deployed site threw '"bar" is not a registered controller'
 * whenever a route got selected, because Rollup tree-shook away the controller
 * registration that react-chartjs-2 performs as a pure side effect. Nothing in
 * jsdom or the dev server can reproduce that — only a built bundle can.
 */
import { test, expect } from './fixtures'
import { openFirstSpot, chartCanvas, canvasIsPainted } from './helpers'

test.beforeEach(async ({ page }) => {
  await page.goto('/')
})

test('opening a curated spot renders the elevation/speed chart', async ({ page }) => {
  await openFirstSpot(page)

  const chart = chartCanvas(page)
  await expect(chart).toBeVisible()

  // Visible is not enough — a canvas that Chart.js failed to draw into is still a
  // visible canvas. Assert it actually has pixels on it.
  expect(await canvasIsPainted(chart)).toBe(true)
})

test('no controller-registration error reaches the console', async ({ page, errors }) => {
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  // Named explicitly so a future regression names itself in the failure output,
  // rather than showing up as a generic "unexpected console errors".
  expect(errors.filter(e => /is not a registered controller/.test(e))).toEqual([])
})

test('the chart survives switching between spots', async ({ page }) => {
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  // Back out and open a different spot: unmounts one chart and builds another,
  // which is where a stale-canvas or double-register bug would surface.
  await page.getByRole('button', { name: /←/ }).click()
  const spots = page.getByRole('button').filter({ hasText: /km \d|↓/ })
  await spots.nth(1).click()

  const chart = chartCanvas(page)
  await expect(chart).toBeVisible()
  expect(await canvasIsPainted(chart)).toBe(true)
})

test('hovering the chart does not throw', async ({ page }) => {
  await openFirstSpot(page)
  const chart = chartCanvas(page)
  await expect(chart).toBeVisible()

  // Scrubbing runs the onHover handler, tooltip layout and the map-pin callback —
  // all code paths that never execute on a plain mount.
  const box = await chart.boundingBox()
  expect(box).not.toBeNull()
  for (const frac of [0.2, 0.5, 0.8]) {
    await page.mouse.move(box!.x + box!.width * frac, box!.y + box!.height / 2)
  }
  await page.mouse.move(box!.x - 20, box!.y - 20) // leave, clearing the scrub
})
