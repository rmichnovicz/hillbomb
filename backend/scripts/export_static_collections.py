"""
Explode the built collections doc into flat files a CDN can serve.

    python -m backend.scripts.export_static_collections frontend/dist/collections

`backend/data/collections.json` is one ~8 MB document and stays the committed source
of truth. This writes the shape the browser actually asks for:

    <out>/index.json          every city, every spot summary, no geometry
    <out>/<slug>.json         one spot with its full routes

Those are the same URLs `main.py` serves under `/collections/`, deliberately — see the
comment above the endpoints there. In production Cloudflare Pages serves these files
and the container is never in the path; in development and in `docker run` FastAPI
serves the identical URLs out of collections.json. Neither the frontend nor a test can
tell the difference, which is the point.

This is a BUILD ARTIFACT, not committed. Committing it would double the repo's data
weight and create a second copy of the corpus to keep in sync. Run it after
`npm run build` and before deploying — see docs/deploy.md.
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

from ..pipeline import collections_index

DOC_PATH = Path(__file__).resolve().parents[1] / "data" / "collections.json"


def export(doc: dict, out_dir: Path, *, indent: int | None = None) -> tuple[int, int]:
    """Write index.json plus one file per spot. Returns (spot count, bytes written)."""
    out_dir.mkdir(parents=True, exist_ok=True)

    written = 0

    def _dump(path: Path, payload: dict) -> None:
        nonlocal written
        # No trailing newline and no indent by default: these are machine-read over the
        # wire, and indent=2 inflates the corpus by roughly a third for no reader.
        text = json.dumps(payload, indent=indent)
        path.write_text(text)
        written += len(text.encode())

    _dump(out_dir / "index.json", collections_index(doc))

    spots = 0
    for city in doc.get("cities", []):
        for entry in city.get("spots", []):
            _dump(out_dir / f"{entry['slug']}.json", entry)
            spots += 1

    return spots, written


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    parser.add_argument("out_dir", type=Path,
                        help="directory to write index.json and <slug>.json into")
    parser.add_argument("--doc", type=Path, default=DOC_PATH,
                        help=f"collections doc to read (default: {DOC_PATH})")
    parser.add_argument("--clean", action="store_true",
                        help="delete out_dir first, so a removed spot leaves no stale "
                             "file behind on the CDN")
    parser.add_argument("--indent", type=int, default=None,
                        help="pretty-print with this indent (default: compact)")
    args = parser.parse_args()

    if not args.doc.exists():
        # An un-built checkout is a normal state everywhere else in this codebase, but
        # here it would silently deploy an empty Collections tab. Fail loudly instead.
        print(f"error: {args.doc} does not exist. Build it first with\n"
              f"  python -m backend.scripts.build_collections", file=sys.stderr)
        return 1

    try:
        doc = json.loads(args.doc.read_text())
    except json.JSONDecodeError as exc:
        print(f"error: {args.doc} is not valid JSON ({exc}). Rebuild with\n"
              f"  python -m backend.scripts.build_collections --clean", file=sys.stderr)
        return 1

    if args.clean and args.out_dir.exists():
        shutil.rmtree(args.out_dir)

    spots, written = export(doc, args.out_dir, indent=args.indent)

    if spots == 0:
        print(f"error: {args.doc} contains no spots — nothing to deploy.", file=sys.stderr)
        return 1

    where = args.out_dir.relative_to(Path.cwd()) if args.out_dir.is_relative_to(Path.cwd()) else args.out_dir
    print(f"wrote index.json + {spots} spots ({written / 1_000_000:.1f} MB) to {where}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
