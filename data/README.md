# `data/`

Holds `hillbomb.gol`, the local road-network snapshot for the regions in
`backend/osmsource.py`. **Not committed** — it is a build artifact of a few
hundred MB. See `.gitignore`.

Build it:

```bash
python -m backend.scripts.build_gol --work-dir /tmp/golbuild --out data/hillbomb.gol
```

Then point the service at it:

```bash
HILLBOMB_GOL=data/hillbomb.gol uvicorn backend.main:app
```

Without it, every search goes to Overpass — which is the default and is fine.

This README exists for a second reason: the Dockerfile copies `data/hillbomb.gol*`
with a glob so the GOL is optional, and a Docker glob matching *zero* files fails
the build. Copying this file alongside it guarantees at least one match. Don't
delete it.
