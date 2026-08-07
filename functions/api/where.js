/**
 * GET /api/where — the visitor's approximate location, from Cloudflare's IP geolocation.
 *
 * The one dynamic thing on the static half of the deploy. It exists so the Collections
 * tab can open the region nearest the visitor instead of always opening San Francisco.
 *
 * Cloudflare resolves this at the edge from the request IP and hands it to us on
 * `request.cf`, so there is no third-party geo API, no key, and no measurable latency —
 * the data is already attached to the request by the time this function runs.
 *
 * Accuracy is city-level and only on fixed broadband; mobile carriers and VPNs will put
 * a visitor in the wrong metro a fair amount of the time. That is acceptable because
 * this only picks a *default* — the full region list is right there — but it is the
 * reason nothing here is treated as authoritative or persisted.
 *
 * `cf.latitude`/`cf.longitude` are strings, and are absent entirely in some
 * environments (`wrangler pages dev` without `--ip-geolocation`, and any request
 * Cloudflare could not resolve). Absent is a normal answer, not an error: the response
 * is always 200 with nulls, and the client treats null as "no guess" and does nothing.
 */
export function onRequestGet({ request }) {
  const cf = request.cf ?? {}
  const lat = Number.parseFloat(cf.latitude)
  const lon = Number.parseFloat(cf.longitude)
  const located = Number.isFinite(lat) && Number.isFinite(lon)

  const body = {
    lat: located ? lat : null,
    lon: located ? lon : null,
    // Names are for display and debugging only — the region pick is done on distance.
    city: cf.city ?? null,
    region: cf.region ?? null,
    country: cf.country ?? null,
  }

  return new Response(JSON.stringify(body), {
    headers: {
      'content-type': 'application/json; charset=utf-8',
      // Load-bearing. This response is per-visitor by definition, and Pages will
      // happily cache a JSON 200 at the edge — which would pin every subsequent
      // visitor to whichever metro happened to warm that colo first. That failure
      // looks exactly like working code when you test it from one location.
      'cache-control': 'no-store',
    },
  })
}
