/**
 * A `page` that fails the test on any console error or uncaught exception.
 *
 * This is the fixture that would have caught the Chart.js controller bug: the app
 * looked fine in a screenshot (empty sidebar, map still interactive) while the
 * console carried '"bar" is not a registered controller'. Asserting on visible DOM
 * alone is not enough — a React subtree that throws just renders nothing.
 */
import { test as base, expect } from '@playwright/test'

type Fixtures = {
  /** Errors seen so far. Available mid-test for targeted assertions. */
  errors: string[]
}

export const test = base.extend<Fixtures>({
  errors: async ({ page }, use) => {
    const errors: string[] = []

    page.on('console', msg => {
      if (msg.type() === 'error') errors.push(msg.text())
    })
    // Uncaught exceptions don't always surface as console errors.
    page.on('pageerror', err => errors.push(`${err.name}: ${err.message}`))

    await use(errors)

    // Tiles and fonts come from a third-party CDN; a flaky one of those is not a
    // regression in this app, and failing on it would make the suite useless.
    const ours = errors.filter(e => !/openfreemap|maplibre|protomaps|font|tile/i.test(e))
    expect(ours, `unexpected console errors:\n${ours.join('\n')}`).toEqual([])
  },
})

export { expect }
