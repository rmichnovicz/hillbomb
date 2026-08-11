/**
 * The mobile bottom sheet on a browser window that isn't tall.
 *
 * The sheet is a fixed 65dvh, and everything in it below the tabs except the route list
 * is `flexShrink: 0` — the 190px profile chart, rider settings, the search controls. So
 * the list column is charged the entire overflow. Selecting a route in a 480px-tall
 * window collapsed it to 23px with 213px of content clipped: the spot header, the back
 * button and every route card gone, with no way to reach them and no way out of the spot.
 *
 * Only Playwright can catch this. jsdom has no layout engine — every element there is
 * 0×0, so a test that asserts "the back button is visible" passes in vitest whether the
 * fix is present or not.
 */
import { test, expect } from './fixtures'
import { openFirstSpot, chartCanvas } from './helpers'

/** Short enough that the sheet cannot fit its pinned sections. A landscape phone,
 *  or a desktop browser window someone has dragged down to a strip. */
const SHORT = { width: 390, height: 480 }

/**
 * Expand the bottom sheet.
 *
 * Explicitly, rather than letting Playwright's auto-scroll drive the collapsed sheet's
 * 22px of body — which is what these tests used to do, and which quietly passed while
 * asserting almost nothing about a layout nobody could see.
 */
async function openSheet(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: 'Expand panel' }).click()
  await expect(page.getByRole('tab', { name: 'Collections' })).toBeVisible()
}

/** The scrolling body of the bottom sheet: the nearest scrollable ancestor. */
async function sheetScroll(locator: import('@playwright/test').Locator) {
  return locator.evaluate(el => {
    for (let node = el.parentElement; node; node = node.parentElement) {
      if (getComputedStyle(node).overflowY === 'auto') {
        return { height: node.clientHeight, scrollHeight: node.scrollHeight, scrollTop: node.scrollTop }
      }
    }
    return null
  })
}

test('a route stays escapable when the window is short', async ({ page }) => {
  await page.setViewportSize(SHORT)
  await page.goto('/')
  await openSheet(page)
  await openFirstSpot(page)

  // openFirstSpot lands on a spot with a route already selected, so the profile chart
  // is claiming its ~190px — the condition that used to crush the list column.
  await expect(chartCanvas(page)).toBeVisible()

  const back = page.getByRole('button', { name: /^←/ })
  await expect(back).toBeVisible()

  // toBeVisible() only checks the box is non-empty; a clipped-away element still has
  // size. What matters is that it can actually be clicked, and that it goes back.
  await expect(back).toBeInViewport()
  await back.click()
  await expect(page.getByRole('button', { name: /descents? · longest/ }).first()).toBeVisible()
})

test('selecting a route scrolls the list to it, not the header off the top', async ({ page }) => {
  // The list scrolls to the selected card. Done with scrollIntoView that walked every
  // scrollable ancestor, which on this sheet meant scrolling the body too and undoing
  // the fix above — so assert both halves: the card comes into view, the header stays.
  await page.setViewportSize(SHORT)
  await page.goto('/')
  await openSheet(page)
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  const back = page.getByRole('button', { name: /^←/ })
  const cards = page.getByRole('listitem')
  const count = await cards.count()
  test.skip(count < 2, 'this spot has one line; nothing to scroll to')

  const last = cards.nth(count - 1)
  await last.scrollIntoViewIfNeeded()
  await last.click()

  await expect(last).toBeInViewport()
  await expect(back).toBeInViewport()
})

test('the short-window sheet scrolls instead of clipping', async ({ page }) => {
  await page.setViewportSize(SHORT)
  await page.goto('/')
  await openSheet(page)
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  const metrics = await sheetScroll(page.getByRole('button', { name: /^←/ }))
  expect(metrics, 'the sheet body should be a scroll container').not.toBeNull()
  expect(
    metrics!.scrollHeight,
    'nothing overflows, so the fix is untested here — pick a shorter viewport',
  ).toBeGreaterThan(metrics!.height)
})

test('the route list keeps a usable share of a short window', async ({ page }) => {
  // The first fix stopped the clipping but left the list a 73px slit — the spot header
  // and the sort row were taking 127 of its 200px floor before a card was drawn. This
  // is the assertion that a fix for "I cannot reach it" hasn't shipped "I can reach it,
  // barely": a whole route card, plus enough of the next to show the list continues.
  await page.setViewportSize(SHORT)
  await page.goto('/')
  await openSheet(page)
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  const card = page.getByRole('listitem').first()
  const cardBox = await card.boundingBox()
  const list = await sheetScroll(card)   // the list's own scroller, inside the sheet
  expect(cardBox && list).toBeTruthy()

  expect(
    list!.height,
    `route list is ${list!.height}px, less than the ${Math.round(cardBox!.height)}px card in it`,
  ).toBeGreaterThan(cardBox!.height * 1.5)
})

test('switching tabs returns the short-window sheet to the top', async ({ page }) => {
  // The scroll offset is the sheet's, not the new tab's. Left alone it puts the tab bar
  // off the top of whatever you just switched to.
  await page.setViewportSize(SHORT)
  await page.goto('/')
  await openSheet(page)
  await openFirstSpot(page)
  await expect(chartCanvas(page)).toBeVisible()

  const back = page.getByRole('button', { name: /^←/ })
  const scrollSheetToBottom = () =>
    back.evaluate(el => {
      for (let node = el.parentElement; node; node = node.parentElement) {
        if (getComputedStyle(node).overflowY === 'auto') {
          node.scrollTop = node.scrollHeight
          return node.scrollTop
        }
      }
      return 0
    })

  expect(await scrollSheetToBottom(), 'the sheet should have somewhere to scroll').toBeGreaterThan(0)

  await page.getByRole('tab', { name: 'Search' }).click()
  // Anchored on rider settings, not a route card: the Search tab has no cards until
  // someone searches, and this test is about the sheet, not about what's in it.
  const after = await sheetScroll(page.getByRole('button', { name: /Rider profile/ }))
  expect(after?.scrollTop, 'switching tabs should return the sheet to the top').toBe(0)
})
