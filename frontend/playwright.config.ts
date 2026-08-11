/**
 * End-to-end tests against the PRODUCTION BUILD, which is the whole point.
 *
 * The unit suite runs in jsdom under vitest, where nothing is tree-shaken. That made
 * it structurally blind to the bug that shipped: react-chartjs-2 registers Chart.js
 * controllers as a /* #__PURE__ *\/ side effect, Rollup drops it, and the deployed
 * site throws '"bar" is not a registered controller' while dev and vitest stay green.
 *
 * So these tests build the real bundle and serve it exactly as Cloudflare Pages does
 * — no Vite dev server, no on-the-fly transform. Anything that only breaks after
 * minification and tree-shaking has to show up here or nowhere.
 */
import { defineConfig, devices } from '@playwright/test'

const PORT = 4173
// Paths below are relative to the repo root — the build chain cd's there first.
const PYTHON = process.env.PYTHON ?? 'backend/.venv/bin/python'

// Two steps, mirroring scripts/build-static.sh: Vite builds the SPA, then the
// collections are exported separately (they are not part of the Vite build, and
// without them every spot 404s). Deliberately `npm run build` rather than the deploy
// script, which does a full `npm ci` on every invocation.
const build = [
  'VITE_API_BASE=http://127.0.0.1:8000 npm --prefix frontend run build',
  `${PYTHON} -m backend.scripts.export_static_collections frontend/dist/collections --clean`,
].join(' && ')

export default defineConfig({
  testDir: './e2e',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  // Every test boots a MapLibre instance and pulls tiles and fonts from the live
  // openfreemap CDN, so workers contend for network, not CPU — Playwright's default of
  // half the cores overshoots badly. At 6 the suite lost three tests a run to timeouts
  // that all passed in isolation; at 3 it is stable and no slower in wall-clock.
  workers: process.env.CI ? 2 : 3,
  reporter: process.env.CI ? 'list' : [['list'], ['html', { open: 'never' }]],

  use: {
    baseURL: `http://127.0.0.1:${PORT}`,
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },

  projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],

  webServer: {
    // The export step runs from the repo root, so the whole chain does.
    // --host 127.0.0.1 matters: vite preview otherwise binds "localhost", which can
    // resolve to ::1 only, and the readiness poll below never connects.
    command: `cd .. && ${build} && cd frontend && npx vite preview --port ${PORT} --strictPort --host 127.0.0.1`,
    url: `http://127.0.0.1:${PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 180_000,
    stdout: 'pipe',
  },
})
