"""`python -m discjockey.hub.shapes --export` writes `hub-ui/src/lib/bridge/types.gen.ts` and `schemas.gen.json`;
`--check` exits 1 when either differs from what the shapes generate."""
from __future__ import annotations

import argparse
import sys

from discjockey.hub import shapes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m discjockey.hub.shapes", description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--export", action="store_true", help="write the generated files")
    group.add_argument("--check", action="store_true", help="exit 1 when a generated file is stale")
    args = parser.parse_args(argv)
    made = shapes.generated()
    if args.export:
        for path, text in made.items():
            path.write_text(text, encoding="utf-8")
            print(f"wrote {path}")
        return 0
    stale = [p for p, text in made.items() if not p.exists() or p.read_text(encoding="utf-8") != text]
    for path in stale:
        print(f"stale: {path} (run: uv run python -m discjockey.hub.shapes --export)", file=sys.stderr)
    return 1 if stale else 0


if __name__ == "__main__":
    sys.exit(main())
