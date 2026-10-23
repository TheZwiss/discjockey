#!/bin/bash
# Builds dist/app/Discjockey.app and dist/Discjockey-<version>.dmg (spec public-release §5–§7). The same steps run in
# the release workflow. Signs with the "Discjockey Release" identity from ~/.discjockey-signing
# (scripts/make_signing_identity.sh), ad-hoc when it isn't there. Never installs anything into /Applications.
#
# usage: scripts/build_app.sh
#   REQUIRE_IDENTITY=1  fail instead of signing ad-hoc (releases)
#   SKIP_UI_BUILD=1     don't rebuild hub-ui to check the committed discjockey/hub/static
# Both take 1, true or yes; any other non-empty value is refused, so a typo never means "off".
#
# What it writes: everything under dist/ (gitignored). Outside it: hub-ui/node_modules (npm ci), uv's cache and its
# managed Python, __pycache__ in the checkout (PyInstaller imports discjockey to find its modules), and, during the
# signing step only, the signing keychain on the user's keychain search list (sign_app.py restores the list).
# The app bundles the checkout's discjockey/hub/static: step 1 builds hub-ui into dist/ui and fails when that
# differs, so the build never rewrites a committed file. With REQUIRE_IDENTITY=1 the checkout must also be clean
# (no uncommitted change to a tracked file), so a release matches a commit.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
DIST="$ROOT/dist"
UV="${UV:-$HOME/.local/bin/uv}"
VENV="$DIST/build/venv"
APP="$DIST/app/Discjockey.app"
VERSION="$(sed -n 's/^__version__ = "\(.*\)".*/\1/p' "$ROOT/discjockey/__init__.py")"
DMG="$DIST/Discjockey-$VERSION.dmg"
STEPS=8
CURRENT=""
SCRATCH=""
MNT=""
DMG_STATE=""  # "making" during step 8, "made" once the .dmg passed its checks; a failed one is removed

step() { CURRENT="$1/$STEPS ($2)"; echo "==> [$1/$STEPS] $2"; }

# on NAME: true for 1/true/yes, false when unset or empty, exits for anything else.
on() {
  case "${!1:-}" in
    "") return 1 ;;
    1 | true | yes) return 0 ;;
    *) echo "$1=${!1} is not understood: use 1, true or yes, or leave it unset" >&2; exit 2 ;;
  esac
}

# detach MOUNTPOINT: a just-made volume can be busy for a moment (Spotlight), so try again, then force.
detach() {
  for _ in 1 2 3; do
    hdiutil detach "$1" -quiet 2>/dev/null && return 0
    sleep 2
  done
  hdiutil detach "$1" -quiet -force
}

finish() {
  local status=$?
  [ -z "$SCRATCH" ] || rm -rf "$SCRATCH"
  if [ -n "$MNT" ]; then
    ! hdiutil info | grep -qF "$MNT" || detach "$MNT" || true
    rmdir "$MNT" 2>/dev/null || true
  fi
  if [ "$status" -ne 0 ]; then
    [ "$DMG_STATE" != making ] || rm -f "$DMG"
    echo "Build failed${CURRENT:+ in step $CURRENT}: see the lines above." >&2
  fi
}
trap finish EXIT

cd "$ROOT"
[ -n "$VERSION" ] || { echo "no __version__ in discjockey/__init__.py" >&2; exit 1; }
on REQUIRE_IDENTITY || true  # refuses a value it doesn't understand before anything is built
on SKIP_UI_BUILD || true
if on REQUIRE_IDENTITY && [ -n "$(git -C "$ROOT" status --porcelain --untracked-files=no 2>/dev/null)" ]; then
  echo "a release build needs a clean checkout: commit or stash your changes first" >&2
  exit 1
fi

step 1 "UI build (must match the committed discjockey/hub/static)"
if on SKIP_UI_BUILD; then
  echo "  skipped: bundling the committed discjockey/hub/static unchecked"
else
  (cd hub-ui && npm ci --silent && npm run build --silent -- --outDir "$DIST/ui" --emptyOutDir --logLevel warn)
  if ! diff -rq "$DIST/ui" discjockey/hub/static > "$DIST/ui-diff.txt"; then
    head -5 "$DIST/ui-diff.txt" >&2
    echo "discjockey/hub/static is not what hub-ui builds now: run 'cd hub-ui && npm run build' and commit it" \
      "(build(hub): static)" >&2
    exit 1
  fi
fi

step 2 "build venv (macOS 12 wheels for arm64)"
mkdir -p "$DIST/build"
"$UV" export --frozen --no-dev --group build --no-emit-project --quiet -o "$DIST/build/requirements.txt"
rm -rf "$VENV"
"$UV" venv --quiet --managed-python --python 3.12 "$VENV"
MACOSX_DEPLOYMENT_TARGET=12.0 "$UV" pip install --quiet --python "$VENV/bin/python" \
  --python-platform aarch64-apple-darwin -r "$DIST/build/requirements.txt"

step 3 "ffmpeg, ffprobe, deno (pinned, hash-checked)"
"$VENV/bin/python" packaging/fetch_tools.py --out "$DIST/tools" --cache "$DIST/cache"

step 4 "PyInstaller and the licences of what it bundles (a few minutes)"
rm -rf "$DIST/app" "$DIST/work"
DISCJOCKEY_VERSION="$VERSION" DISCJOCKEY_TOOLS_BIN="$DIST/tools/bin" DISCJOCKEY_LICENSES="$DIST/licenses" \
  PYTHONPATH="$ROOT" "$VENV/bin/pyinstaller" --noconfirm --clean --log-level WARN \
  --distpath "$DIST/app" --workpath "$DIST/work" packaging/discjockey.spec

step 5 "sign"
if on REQUIRE_IDENTITY; then
  "$VENV/bin/python" packaging/sign_app.py "$APP" --require-identity
else
  "$VENV/bin/python" packaging/sign_app.py "$APP"
fi

step 6 "minimum macOS"
"$VENV/bin/python" packaging/machos.py minos "$APP" --max 12.0

step 7 "self-test"
SCRATCH="$(mktemp -d)"
DISCJOCKEY_SUPPORT="$SCRATCH" "$APP/Contents/MacOS/Discjockey" --self-test
rm -rf "$SCRATCH"
SCRATCH=""

step 8 ".dmg"
DMG_STATE=making
rm -f "$DMG"
"$VENV/bin/dmgbuild" -s packaging/dmg_settings.py -D app="$APP" "Discjockey" "$DMG"
MNT="$(mktemp -d)"
hdiutil attach -nobrowse -readonly -noverify -mountpoint "$MNT" "$DMG" >/dev/null
[ -d "$MNT/Discjockey.app" ] && [ -L "$MNT/Applications" ] || { echo "the .dmg lacks the app or the link" >&2; exit 1; }
codesign --verify --deep --strict "$MNT/Discjockey.app"
inside="$(codesign -d -r- "$MNT/Discjockey.app" 2>&1 | grep '^designated')"
built="$(codesign -d -r- "$APP" 2>&1 | grep '^designated')"
[ "$inside" = "$built" ] || { echo "the app in the .dmg is signed differently" >&2; exit 1; }
detach "$MNT"
rmdir "$MNT"
MNT=""
DMG_STATE=made

echo "Built $APP ($(du -sh "$APP" | cut -f1)) and $DMG ($(du -h "$DMG" | cut -f1))"
