#!/usr/bin/env bash
#
# Build the complete static site — SPA + curated collections — into frontend/dist,
# ready to hand to Cloudflare Pages.
#
#   VITE_API_BASE=https://hillbomb-xxx.us-west1.run.app scripts/build-static.sh
#
# Two steps, and the second is the one worth having a script for. `npm run build`
# alone produces a site that looks complete and whose Collections tab 404s on every
# spot, because the collection JSON is not part of the Vite build — it is exported
# from backend/data/collections.json afterwards. That failure is invisible until
# someone opens the tab in production.
#
# NOT used by the Dockerfile. That image serves everything from one origin, so it
# wants VITE_API_BASE unset and its collections served by FastAPI out of
# collections.json. This script exists only for the split CDN deploy.
#
# See docs/deploy.md.

set -euo pipefail

cd "$(dirname "$0")/.."

if [[ -z "${VITE_API_BASE:-}" ]]; then
  cat >&2 <<'EOF'
error: VITE_API_BASE is not set.

  On the CDN the SPA is on a different origin than the API, so the search URL has to
  be baked in at build time. Unset, it defaults to same-origin and every search would
  POST to the CDN, which has no /search and would 404 — a site that loads perfectly
  and cannot search.

  Set it to the Cloud Run service URL:

    export VITE_API_BASE="$(gcloud run services describe hillbomb \
        --region us-west1 --format 'value(status.url)')"

  (Same-origin builds don't use this script — see the Dockerfile.)
EOF
  exit 1
fi

PYTHON="${PYTHON:-backend/.venv/bin/python}"
if [[ ! -x "$PYTHON" ]]; then
  PYTHON="$(command -v python3)"
fi

echo "==> building SPA (VITE_API_BASE=$VITE_API_BASE)"
( cd frontend && npm ci && npm run build )

echo "==> exporting collections"
# --clean so a spot removed from spots.py doesn't linger as a stale file on the CDN.
"$PYTHON" -m backend.scripts.export_static_collections frontend/dist/collections --clean

echo
echo "==> frontend/dist is ready. Deploy it with:"
echo "    npx wrangler pages deploy frontend/dist --project-name hillbomb"
