/// <reference types="vitest/config" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      '/search': 'http://localhost:8000',
      '/collections': 'http://localhost:8000',
    },
  },
  test: {
    globals: true,
    environment: 'jsdom',
    setupFiles: ['./src/test-setup.ts'],
    // Scoped to src/ so vitest's default glob doesn't pick up e2e/*.spec.ts —
    // those are Playwright specs and throw "did not expect test() to be called
    // here" when run under vitest. Run them with `npm run test:e2e`.
    include: ['src/**/*.{test,spec}.{ts,tsx}'],
  },
})
