/**
 * Guards the bug that only ever appears in a production build.
 *
 * react-chartjs-2 registers all eight Chart.js controllers as a side effect of its
 * typed-chart exports (`createTypedChart('bar', BarController)` at module scope).
 * Those calls are marked /* #__PURE__ *\/ and the package sets "sideEffects": false,
 * so Rollup drops them from a production bundle — while dev, and vitest, keep them.
 * A ProfilePanel that forgets to register BarController therefore renders fine
 * everywhere except the deployed site, where it throws
 * '"bar" is not a registered controller' the moment a route is selected.
 *
 * So this test can't just render the component: under vitest the side effect is
 * always there. It mocks react-chartjs-2 away instead, reproducing the tree-shaken
 * production condition, and asserts ProfilePanel registers its own controllers.
 */
import { describe, it, expect, vi, beforeEach } from 'vitest'

// Stand in for react-chartjs-2 with a component that registers nothing — exactly
// what the real package amounts to once Rollup has shaken the typed charts out.
vi.mock('react-chartjs-2', () => ({ Chart: () => null }))

describe('ProfilePanel Chart.js registration', () => {
  beforeEach(() => {
    // Fresh module graph per test, so chart.js gets a clean registry rather than
    // one already populated by an earlier import.
    vi.resetModules()
  })

  it.each(['bar', 'line'])('registers the %s controller itself', async type => {
    // Import order matters: ProfilePanel first, so its own register() call runs.
    await import('../ProfilePanel/ProfilePanel')
    const { registry } = await import('chart.js')

    expect(() => registry.getController(type)).not.toThrow()
  })

  it.each(['category', 'linear'])('registers the %s scale itself', async type => {
    await import('../ProfilePanel/ProfilePanel')
    const { registry } = await import('chart.js')

    expect(() => registry.getScale(type)).not.toThrow()
  })

  it.each(['bar', 'line', 'point'])('registers the %s element itself', async type => {
    await import('../ProfilePanel/ProfilePanel')
    const { registry } = await import('chart.js')

    expect(() => registry.getElement(type)).not.toThrow()
  })
})
