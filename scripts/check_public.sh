#!/bin/bash
# Checks that the tree holds no personal data before it goes to a public repo (spec public-release, phase 6).
# Stdlib Python only, in isolated mode (-I): CI runs this before `uv sync`, and -I keeps the checkout off sys.path.
#
# usage: scripts/check_public.sh [--dir DIR] [--require-denylist]
#   (no --dir)            scans the tracked files of this repo, minus docs/archive/pre-public/
#   --dir DIR             scans every regular file under DIR, no exclusions
#   --require-denylist    a missing denylist file is an error (exit 2) instead of a warning
#   DISCJOCKEY_PUBLIC_DENYLIST   the denylist file (default ~/.discjockey-public-denylist): one word per line
# exit: 0 clean, 1 findings, 2 usage error or missing required denylist
set -euo pipefail
exec python3 -I "$(dirname "${BASH_SOURCE[0]}")/check_public.py" "$@"
