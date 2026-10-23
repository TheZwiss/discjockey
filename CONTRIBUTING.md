# Contributing to Discjockey

Notes for running Discjockey from its source code, changing it and releasing it. [README.md](README.md) is the
user's manual: read it for how a feature behaves from the user's side. The binding project rules (invariants,
layout, commands, how docs and plans are kept) are in [CLAUDE.md](CLAUDE.md); this file doesn't repeat them.

## Getting started

You need a Mac with Apple Silicon, [uv](https://docs.astral.sh/uv/) and, for the window's interface, Node.js.

```
git clone https://github.com/TheZwiss/discjockey.git
cd discjockey
uv sync
cd hub-ui && npm ci
```

`bin/discjockey` is the launcher: it runs `uv sync`, then the engine (`python -m discjockey`). `bin/discjockey hub`
opens the window; `DISCJOCKEY_HUB_DEBUG=1 bin/discjockey hub` keeps its log in the terminal.

Your own library and logins live in the support folder `~/Library/Application Support/Discjockey/`. To try things
without touching them, point Discjockey at a scratch folder: `DISCJOCKEY_SUPPORT=/tmp/dj bin/discjockey hub` (Setup
then asks for a music folder). Without the app, ffmpeg, ffprobe and deno come from your `PATH`
(`brew install ffmpeg deno`).

## The Terminal version

The engine also runs in Terminal. `bin/discjockey setup` asks Setup's questions there, the music folder first (it
needs a real Terminal window), and at the end prints a line that lets you type just `discjockey`:

```
discjockey --dry-run      shows what would happen, changes nothing
discjockey                shows the plan, asks "Proceed?", then does it
discjockey --limit 10     only the first 10 downloads
discjockey --extra 20     allows 20 more Qobuz downloads today only
discjockey upgrades       goes through the waiting lossless versions
discjockey update         gets the newest yt-dlp
```

- The Mac stays awake while a run goes (`caffeinate`). Ctrl-C once stops safely after the current track; Ctrl-C
  again stops at once. Both are safe, and the next run continues where this one stopped.
- `discjockey upgrades` offers the To-do page's choices as letters: **s** swap, **a** add as a new file, **d**
  discard, **f** show in Finder, **l** later (or Enter), **q** quit. A swap that has started is finished first, even
  on Ctrl-C. It writes a report of what you decided.
- While a Terminal run is busy, the window's buttons that change something are switched off.

Never start a real sync, upgrade swap or Qobuz download while working on the code unless you mean to: it changes
your library and counts against your Qobuz daily limit. `--dry-run` changes nothing.

## Tests

```
uv run pytest -q
```

Tests are offline: `tests/conftest.py` blocks the network and PyPI and stubs yt-dlp, and every test library lives in
a temporary folder. The audio tests need ffmpeg and ffprobe on your `PATH` and skip without them. The workflow
test also runs `actionlint` on both workflows when it is installed (`brew install actionlint`) and skips without it,
so CI, whose runner has none, never lints them: run the tests on a Mac with it before changing a workflow.

## The window's interface (`hub-ui/`)

Read [docs/hub-design-language.md](docs/hub-design-language.md) first: it holds the design rules, the blocks every
page is built from and the rule checker. From `hub-ui/`:

| What | Command |
|------|---------|
| Dev server with a fake backend (no engine, no network) | `npm run dev`, then pick a state with `?scenario=…` or the toolbar |
| Type check, unit tests, design rules, trial build | `npm run verify` |
| Build into `discjockey/hub/static/` (committed) | `npm run build` |
| Smoke test of the built page in WebKit | `npm run smoke` (after a build) |
| Screenshots of a page in fake mode | `node scripts/shots.mjs --port <dev port> --page <page>` → `hub-ui/screenshots/` |

The fake backend's catalogue of blocks is the gallery at `#/dev/gallery`. A change that touches the bridge between
the engine and the page updates [docs/hub-bridge-contract.md](docs/hub-bridge-contract.md) in the same commit.

## Building the app

```
scripts/build_app.sh
```

It takes 5 to 10 minutes and makes `dist/app/Discjockey.app` and `dist/Discjockey-<version>.dmg`: it downloads
deno and FFmpeg's source release (both pinned by hash in `packaging/tools.json`), builds ffmpeg and ffprobe from that
source with `packaging/build_ffmpeg.sh` (only the Xcode command line tools, no external libraries; a few more minutes
the first time, then cached in `dist/cache/`), builds the app with PyInstaller, signs it, runs its self-test and makes
the `.dmg`. Check a built app with
`DISCJOCKEY_SUPPORT=$(mktemp -d) dist/app/Discjockey.app/Contents/MacOS/Discjockey --self-test`.

**Signing.** Every build is signed with a self-signed identity called "Discjockey Release", so macOS remembers the
user's keychain and Full Disk Access grants from one version to the next. The maintainer makes it once with
`scripts/make_signing_identity.sh` (it goes to `~/.discjockey-signing/`, in a keychain of its own, with a `.p12`
copy for safekeeping). Without it, a local build is signed ad hoc, which is fine for testing. CI rebuilds the
identity from the `.p12` with `scripts/import_signing_identity.sh <file.p12>` (`SIGNING_P12_PASSWORD` and
`DISCJOCKEY_SIGNING_DIR` in the environment).

## The public check

Everything in this repository is public. `scripts/check_public.sh` scans the tracked files for personal data: a real
person's `/Users/` path (made-up ones like `/Users/you` are fine), e-mail addresses outside `example.com` and
GitHub's no-reply domain, links to other repositories of the account, and the words in a denylist that lives
outside the repository: `~/.discjockey-public-denylist` (one word per line, for example your name and your other
e-mail addresses), or the file named in `DISCJOCKEY_PUBLIC_DENYLIST`. Run it before every commit:

```
scripts/check_public.sh
```

Without a denylist it warns and checks the generic rules only. The maintainer, who has the denylist, runs it as
`scripts/check_public.sh --require-denylist`, which exits 2 when the file is missing, unreadable or has no entries.

CI runs it on every push with the denylist from a secret. The maintainer's history from before the repository went
public lives in `docs/archive/pre-public/`, which is gitignored and only on the maintainer's disk.

## Releasing

1. Set the new version in `discjockey/__init__.py` (`__version__`) and in `pyproject.toml` (a test fails when they
   differ). Commit.
2. Tag the commit `v<version>` (for example `git tag v1.0.1`) and push that tag by name:
   `git push origin v1.0.1`. Never `--tags`, `--all` or `--mirror`, and never an `archive/*` branch or tag (the
   maintainer's local copy of the private history from before the repository went public; a local pre-push hook,
   `scripts/public_push_guard.sh`, refuses such a push, and `--no-verify` must not be used). The workflow refuses a tag that
   doesn't match `__version__`.
3. The `release` workflow runs the same checks as every push, builds and signs the app, runs its self-test and
   attaches `Discjockey-<version>.dmg` to a **draft** release.
4. Look at the draft: download the `.dmg`, install it, open it. Then publish the draft by hand on GitHub. Nothing is
   published by the workflow itself, and a published release is never replaced.

The workflows read three repository secrets:

| Secret | What it holds |
|--------|---------------|
| `SIGNING_P12_BASE64` | The signing identity's `.p12` (`~/.discjockey-signing/discjockey-release.p12`), base64-encoded |
| `SIGNING_P12_PASSWORD` | That `.p12`'s password (`~/.discjockey-signing/p12.pass`) |
| `PUBLIC_CHECK_DENYLIST` | The denylist for the public check: the contents of `~/.discjockey-public-denylist` |
