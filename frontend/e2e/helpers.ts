import { expect, type Locator, type Page } from '@playwright/test'

/**
 * The chart canvas, as distinct from the MapLibre one.
 *
 * react-chartjs-2 gives its canvas role="img"; MapLibre's carries no role. That is
 * the only stable difference between the two canvases on the page — the app styles
 * everything inline and has no test ids.
 */
export const chartCanvas = (page: Page): Locator => page.getByRole('img')

/** Open Collections → first region → first spot. */
export async function openFirstSpot(page: Page): Promise<void> {
  // The Search/Collections switcher is a real tablist, so these are tabs, not buttons.
  await page.getByRole('tab', { name: 'Collections' }).click()

  const region = page.getByRole('button', { name: /descents? · longest/ }).first()
  await expect(region).toBeVisible()
  await region.click()

  // Spot cards are the buttons carrying route stats (distance / descent / speed).
  const spot = page.getByRole('button').filter({ hasText: /km ·? ?↓|↓ ?\d+ ?m/ }).first()
  await expect(spot).toBeVisible()
  await spot.click()
}

/**
 * True when the canvas has any non-transparent pixel.
 *
 * Chart.js failing to build a chart leaves a correctly-sized, entirely blank canvas,
 * so "is it visible" passes while nothing was drawn. Reading the bitmap is the only
 * assertion that distinguishes the two.
 */
export async function canvasIsPainted(canvas: Locator): Promise<boolean> {
  return canvas.evaluate((el: HTMLCanvasElement) => {
    const ctx = el.getContext('2d')
    if (!ctx || !el.width || !el.height) return false
    const { data } = ctx.getImageData(0, 0, el.width, el.height)
    for (let i = 3; i < data.length; i += 4) {
      if (data[i] !== 0) return true // any pixel with alpha
    }
    return false
  })
}
