/**
 * Where each half of the backend lives.
 *
 * Hillbomb deploys as two things, because only one of them needs a server:
 *
 *   static  — the SPA and the curated collections. Precomputed, identical for every
 *             visitor, so they sit on a CDN and no container is involved in loading
 *             the site or browsing Collections.
 *   dynamic — POST /search only. Real work per request, so it stays on Cloud Run.
 *
 * Collections are therefore fetched with RELATIVE paths: they are served from the same
 * origin as the app itself in every environment (CDN in production, the Vite dev
 * proxy locally, FastAPI's own routes under `docker run`). Search is fetched from
 * `API_BASE`, which is cross-origin in production and empty everywhere else.
 *
 * Empty default is load-bearing: with no VITE_API_BASE set, every URL here is relative
 * and the app behaves exactly as it did when one origin served everything — which is
 * what `npm run dev`, the test suite, and `docker run -p 8080:8080 hillbomb` all rely
 * on. Only a production build sets it. See docs/deploy.md.
 */
export const API_BASE: string = import.meta.env.VITE_API_BASE ?? ''

/** Streaming search. Cross-origin in production, so CORS applies — see main.py. */
export const searchUrl = (): string => `${API_BASE}/search`

/** Curated collections index: every city, every spot, no geometry. */
export const collectionsIndexUrl = (): string => '/collections/index.json'

/** One curated spot with its full routes. */
export const collectionSpotUrl = (slug: string): string =>
  `/collections/${encodeURIComponent(slug)}.json`

/**
 * Approximate visitor location from the CDN's IP geolocation.
 *
 * Relative like collections, and for the same reason — it is served by the static half
 * — but unlike collections it is the one URL there that is *not* identical for every
 * visitor. It exists only on the Cloudflare deploy, as a Pages Function
 * (`functions/api/where.js`); everywhere else this 404s and the caller degrades to no
 * location. See hooks/useIpLocation.ts.
 */
export const whereUrl = (): string => '/api/where'
