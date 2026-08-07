# Hillbomb — single image serving both the API and the built frontend.
#
# One image, one origin, on purpose: VITE_API_BASE is deliberately left unset in the
# frontend build below, so every URL the SPA fetches stays relative and is answered by
# this same container — including "/collections/*.json", which main.py serves out of
# collections.json. No CORS, no API base URL, nothing to configure.
#
# This is NOT the production topology. Production splits the static half onto
# Cloudflare Pages and keeps only POST /search here (see docs/deploy.md). The image
# stays whole anyway: it is how the app runs locally, how the API deploys, and the
# fallback if the CDN is ever taken out of the picture.
#
#   docker build -t hillbomb .
#   docker run --rm -p 8080:8080 hillbomb
#
# Deploy: see docs/deploy.md.

# ── Stage 1: build the SPA ────────────────────────────────────────────────────
# Deliberately NOT pinned. This stage only emits JS/CSS/HTML, which is
# architecture-independent, so letting it build natively avoids emulating a whole
# npm install on an Apple Silicon machine.
#
# It previously said `--platform=$BUILDPLATFORM`, which is the idiomatic way to say
# that — under BuildKit. Cloud Build uses the LEGACY docker builder, which does not
# define that variable, so it expanded to "" and the build died on
# `failed to parse platform`. It worked locally and only ever failed in the cloud.
# Omitting the flag gets the same behaviour on both builders.
FROM node:22-slim AS frontend

WORKDIR /app
# Copy manifests first so the dependency layer is cached independently of source
# edits — otherwise every frontend change reinstalls node_modules.
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci

COPY frontend/ ./
# `npm run build` is `tsc -b && vite build`, so a type error fails the image build
# rather than shipping. That is the behaviour we want.
RUN npm run build


# ── Stage 2: runtime ──────────────────────────────────────────────────────────
# linux/amd64 is pinned deliberately, for two reasons that both bite otherwise:
#
#   1. Cloud Run runs amd64. An arm64 image built on an Apple Silicon machine
#      deploys and then fails to start there.
#   2. rasterio publishes a cp313 manylinux wheel for x86_64 but NOT for aarch64.
#      On arm64 pip falls back to building from source, which needs a system GDAL
#      (`gdal-config`) that this image does not have — the build dies at
#      "A GDAL API version must be specified".
#
# Pinning here means `docker build` on any machine produces the artifact Cloud Run
# actually runs. On Apple Silicon that costs emulation time; correctness is worth it.
#
# Caveat: this pin is honoured by BuildKit only. The LEGACY builder (`DOCKER_BUILDKIT=0`,
# which is what Cloud Build uses) parses the flag and then ignores it, building for the
# host instead. That is harmless on Cloud Build, whose workers are x86_64 anyway — but it
# does mean a legacy build on an arm64 machine will fail on the missing gdal-config.
# Build locally with BuildKit (the default) and this is a non-issue.
FROM --platform=linux/amd64 python:3.13-slim AS runtime

# PYTHONUNBUFFERED: Cloud Run collects stdout; block buffering would hide logs
#   until a buffer fills, which makes a crash look silent.
# PYTHONDONTWRITEBYTECODE: the filesystem is ephemeral and RAM-backed; .pyc files
#   would just consume memory.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

# No system GDAL: rasterio's x86_64 manylinux wheel bundles it. That is true only
# on amd64, which is why the platform above is pinned rather than left to default.
#
# libexpat1 IS still needed. The bundled GDAL links against it, and python:*-slim
# does not ship it — without it the image builds cleanly and then dies on the first
# `import rasterio` with "libexpat.so.1: cannot open shared object file". That is a
# runtime failure, not a build one, so it surfaces as a Cloud Run revision failing
# its health check rather than as a broken build.
#
# curl is here only for the container's own healthcheck.
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl ca-certificates libexpat1 \
 && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt ./backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /app/dist ./static

# The local road-network snapshot, if one was built (backend/scripts/build_gol.py).
# Build it first, drop it at data/hillbomb.gol, and it ships in the image.
#
# Image content does NOT count against Cloud Run's per-instance memory — only
# runtime writes to the filesystem do — so a few hundred MB here costs nothing at
# runtime and keeps scale-to-zero. It does grow the image, so watch cold-start
# pull time as the covered regions grow.
#
# Note the file name: hillbomb-DEPLOY.gol, built with `--tier deploy`. The plain
# data/hillbomb.gol is the ~820 MB all-tier build for local dev and Collections,
# and .dockerignore/.gcloudignore exclude it outright so it can never be uploaded
# or shipped by accident.
#
# The trailing "*" makes the GOL optional: an image built without one still works,
# because osmsource.gol_path() ignores a HILLBOMB_GOL that doesn't exist and every
# search falls through to Overpass. data/.keep is copied alongside it because a
# Docker glob matching zero files is a build error — .keep guarantees a match, and
# is not a .md precisely because both ignore files drop *.md from the context.
COPY data/.keep data/hillbomb-deploy.gol* ./data/

# Non-root: Cloud Run does not require it, but nothing here needs root and the
# writable paths below are explicitly chowned.
RUN useradd --create-home --uid 1001 hillbomb \
 && mkdir -p /var/cache/hillbomb \
 && chown -R hillbomb:hillbomb /var/cache/hillbomb /app
USER hillbomb

# Default cache root. On Cloud Run this is overridden to the gcsfuse mount so the
# Overpass and elevation caches survive scale-to-zero (see docs/deploy.md); left
# unmounted it still works, just per-instance and ephemeral.
ENV HILLBOMB_CACHE_DIR=/var/cache/hillbomb

# Local road-network snapshot. Ignored if the file isn't in the image, in which
# case every search uses Overpass. Coverage comes from the sibling .regions.json
# manifest, not from the region catalog in code. See backend/osmsource.py.
ENV HILLBOMB_GOL=/app/data/hillbomb-deploy.gol

# Cloud Run injects PORT and it is not always 8080; honour it rather than assume.
ENV PORT=8080
EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=3s --start-period=10s --retries=3 \
  CMD curl -fsS "http://localhost:${PORT}/healthz" || exit 1

# Single worker: RequestGate bounds concurrent elevation fetches per PROCESS, so
# multiple workers in one container would multiply that limit without knowing.
# Scale with Cloud Run instances instead, where each gets its own gate.
CMD exec uvicorn backend.main:app --host 0.0.0.0 --port "${PORT}" --workers 1
