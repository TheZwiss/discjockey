# Contributing to Discjockey

Notes for running Discjockey from its source code, changing it and releasing it. [docs/manual.md](docs/manual.md) is the
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

`bin/discjockey` is the launcher: it runs `uv sync`, then the engine (`python -m discjockey`). `bin/discjockey app open`
opens the window; `DISCJOCKEY_HUB_DEBUG=1 bin/discjockey app open` keeps its log in the terminal.

Your own library and logins live in the support folder `~/Library/Application Support/Discjockey/`. To try things
without touching them, point Discjockey at a scratch folder: `DISCJOCKEY_SUPPORT=/tmp/dj bin/discjockey app open` (Setup
then asks for a music folder). Without the app, ffmpeg, ffprobe and deno come from your `PATH`
(`brew install ffmpeg deno`).

## Terminal version

The window's engine has a command line with the same abilities (issue 39). One program, two homes: `bin/discjockey` in
a checkout, `/Applications/Discjockey.app/Contents/MacOS/Discjockey` in the installed app. Both run `cli.main`. In
the app, any argument but `--check-tools`, `--self-test`, `app open` and a Finder start goes to the command line, and
no argument from a shell prints the short help (a window never opens on a probe). `discjockey where` prints the
absolute path of the program.

### Commands for scripts and agents

[AGENTS.md](AGENTS.md) holds all of it: the grammar, the answer's keys, exit codes, jobs, dry runs, the `help --json`
layout, the safety rules and a task map. Keep it current when a command is added or changed. For developers: a command
run by hand always sets `DISCJOCKEY_SUPPORT` and `DISCJOCKEY_REKORDBOX` to scratch folders (AGENTS.md, "If you work on
Discjockey's code").

## Tests

```
uv run pytest -q
```

Tests are offline: `tests/conftest.py` blocks the network and PyPI and stubs yt-dlp, and every test library lives in
a temporary folder. The audio tests need ffmpeg and ffprobe on your `PATH` and skip without them. The workflow
test also runs `actionlint` on both workflows when it is installed (`brew install actionlint`) and skips without it,
so CI, whose runner has none, never lints them: run the tests on a Mac with it before changing a workflow.

The suite waits for nothing a test does not need, so it runs in about a minute: `tests/conftest.py` installs three
test-only changes (the production code and its defaults stay as they are, and each has a marker that turns it off for
the one test that pins the real thing):

- `tests/speed_sqlcipher.py`: SQLCipher's key stretching (about 30 ms on every open of a rekordbox library) runs once
  per key and salt; `real_sqlcipher_kdf` uses SQLCipher's own passphrase derivation.
- `tests/tool_memo.py`: an ffprobe or ffmpeg run on bytes already seen in this worker, the same way, is answered from
  memory (the program runs for the first of each); `real_tools` runs every call for real.
- `tests/speed_durability.py`: `F_FULLFSYNC` and library.db's `synchronous`/`fullfsync` pragmas do not wait for the
  drive (a test never cuts the power); `real_durability` runs with the real ones.

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
the engine and the page regenerates the shapes (`uv run python -m discjockey.hub.shapes --export`) and keeps the rules in
[docs/hub-bridge-contract.md](docs/hub-bridge-contract.md) true, in the same commit.

**Dev switches of the fake backend.** In fake mode `window.__fake.ctx.s` is the fake's state; set a field in the
browser console and the next call sees it. `s.briefBusy = true` makes both brief saves (Favourites, crate switches)
answer `busy`; `s.unread` and `s.emptyRead` list the playlist folders the fake treats as never read, or read and empty. Two scenarios build on them:
`library:crates_busy` is `library:crates` with `briefBusy` on, and `library:first_look` shows its folders and crates with
no Favourites. The other scenarios are listed in the toolbar. Songs of the user's own come from `fake/own.ts` (a
deterministic generator): `normal` and the scenarios built on it have a watched Music folder with 24 of them, the
`folders_*` scenarios thousands, the crate scenarios their own folders, and one function (`listedCounts`) gives the sidebar, Settings and the folder's page the same count.

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
2. Run the checks locally (CI runs only the public check, the Python tests and the hub/static comparison; the release
   job runs no tests): `uv run pytest -q` and `cd hub-ui && npm run verify` must pass.
3. Tag the commit `v<version>` (for example `git tag v1.0.1`) and push that tag by name:
   `git push origin v1.0.1`. Never `--tags`, `--all` or `--mirror`, and never an `archive/*` branch or tag (the
   maintainer's local copy of the private history from before the repository went public; a local pre-push hook,
   `scripts/public_push_guard.sh`, refuses such a push, and `--no-verify` must not be used). The workflow refuses a tag that
   doesn't match `__version__`.
4. The `release` workflow runs the public check, builds ffmpeg, builds and signs the app, runs its self-test and
   attaches `Discjockey-<version>.dmg` to a **draft** release.
5. Look at the draft: download the `.dmg`, install it, open it. Then publish the draft by hand on GitHub. Nothing is
   published by the workflow itself, and a published release is never replaced.

The workflows read three repository secrets:

| Secret | What it holds |
|--------|---------------|
| `SIGNING_P12_BASE64` | The signing identity's `.p12` (`~/.discjockey-signing/discjockey-release.p12`), base64-encoded |
| `SIGNING_P12_PASSWORD` | That `.p12`'s password (`~/.discjockey-signing/p12.pass`) |
| `PUBLIC_CHECK_DENYLIST` | The denylist for the public check: the contents of `~/.discjockey-public-denylist` |
