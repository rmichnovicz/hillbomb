/**
 * The mobile sheet's three detents, and the drag that moves between them.
 *
 * Playwright rather than vitest for two reasons that both come down to jsdom having no
 * layout: the detent heights are `dvh` and only mean something against a real viewport,
 * and the drag is decided by pixel distance and velocity, neither of which exists in a
 * world where every element is 0×0.
 *
 * These have to be real trusted events, too — `setPointerCapture` throws on a pointerId
 * the browser does not consider active, so a hand-dispatched PointerEvent exercises the
 * fallback path rather than the one users get.
 */
import { test, expect, type Page } from '@playwright/test'

const MOBILE = { width: 390, height: 844 }

/** Detent heights as fractions of viewport height; `peek` is a flat 52px. */
const HALF = 0.65
const FULL = 0.92

const handle = (page: Page) => page.getByRole('button', { name: /panel$/ })

async function sheetHeight(page: Page): Promise<number> {
  return page.locator('.hb-sheet').evaluate(el => el.getBoundingClientRect().height)
}

/**
 * Wait for the height transition to finish.
 *
 * Polling the box rather than waiting a fixed time: the transition is 280ms of
 * main-thread animation, and a hardcoded sleep is exactly the kind of thing that passes
 * on a quiet machine and fails in a parallel run.
 */
async function settled(page: Page): Promise<number> {
  let last = -1
  await expect.poll(async () => {
    const h = await sheetHeight(page)
    const stable = h === last
    last = h
    return stable
  }, { timeout: 5_000 }).toBe(true)
  return last
}

/** Drag the handle by `dy` (negative is up, i.e. taller), slowly enough not to flick. */
async function dragHandle(page: Page, dy: number, steps = 12) {
  const box = await handle(page).boundingBox()
  if (!box) throw new Error('no sheet handle')
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2

  await page.mouse.move(x, y)
  await page.mouse.down()
  for (let i = 1; i <= steps; i++) {
    await page.mouse.move(x, y + (dy * i) / steps)
    // Slow enough that velocity stays under the flick threshold, so this test measures
    // the nearest-detent path and the flick test below measures the other one.
    await page.waitForTimeout(20)
  }
  await page.mouse.up()
}

test.beforeEach(async ({ page }) => {
  await page.setViewportSize(MOBILE)
  await page.goto('/')
})

test('tapping the handle cycles peek → half → full → peek', async ({ page }) => {
  // Cycling, not toggling, so `full` is reachable without a pointer gesture at all.
  expect(await settled(page)).toBe(52)

  await handle(page).click()
  expect(await settled(page)).toBeCloseTo(MOBILE.height * HALF, -1)

  await handle(page).click()
  expect(await settled(page)).toBeCloseTo(MOBILE.height * FULL, -1)

  await handle(page).click()
  expect(await settled(page)).toBe(52)
})

test('the handle label names what the next tap does', async ({ page }) => {
  // Not cosmetic: it is the accessible name, and it is the only thing telling a screen
  // reader that the control has three positions rather than two.
  await expect(handle(page)).toHaveAttribute('aria-label', 'Expand panel')
  await handle(page).click()
  await expect(handle(page)).toHaveAttribute('aria-label', 'Maximize panel')
  await handle(page).click()
  await expect(handle(page)).toHaveAttribute('aria-label', 'Collapse panel')
})

test('dragging the handle up settles on the nearest detent', async ({ page }) => {
  await handle(page).click()                       // peek → half
  const half = await settled(page)

  // Most of the way from half to full: nearest-detent should land on full.
  await dragHandle(page, -(MOBILE.height * (FULL - HALF) * 0.8))
  const after = await settled(page)

  expect(after).toBeGreaterThan(half)
  expect(after).toBeCloseTo(MOBILE.height * FULL, -1)
})

test('a small drag springs back instead of changing detent', async ({ page }) => {
  await handle(page).click()
  const half = await settled(page)

  // 30px is a fidget, not an intent. It must not leave the sheet at 30px off a detent,
  // which is what a drag that sets height without snapping would do.
  await dragHandle(page, -30)
  expect(await settled(page)).toBeCloseTo(half, -1)
})

test('a flick moves exactly one detent, never two', async ({ page }) => {
  // A hard swipe from peek could plausibly be read as "give me everything". It must not:
  // skipping the middle detent leaves people unable to find it again.
  const box = await handle(page).boundingBox()
  if (!box) throw new Error('no sheet handle')
  const x = box.x + box.width / 2
  const y = box.y + box.height / 2

  await page.mouse.move(x, y)
  await page.mouse.down()
  await page.mouse.move(x, y - 400, { steps: 3 })   // fast: few steps, no waits
  await page.mouse.up()

  expect(await settled(page)).toBeCloseTo(MOBILE.height * HALF, -1)
})

test('full detent fits the chart and controls without a second scroller', async ({ page }) => {
  // The point of the detent. At half, the sheet body has to scroll to reach the pinned
  // chart and settings; at full it does not, so the nested-scroller situation that
  // started all of this simply stops existing.
  await handle(page).click()
  await handle(page).click()
  await settled(page)

  const scrollers = await page.locator('.hb-sheet').evaluate(sheet =>
    [...sheet.querySelectorAll('div')].filter(d => {
      const oy = getComputedStyle(d).overflowY
      return (oy === 'auto' || oy === 'scroll') && d.scrollHeight > d.clientHeight
    }).length,
  )

  expect(scrollers, 'nothing should need to scroll at full detent on an empty search tab')
    .toBe(0)
})
