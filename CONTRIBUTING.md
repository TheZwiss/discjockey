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

- **Start with** `discjockey help --json`: the index of every command (below). `discjockey help <noun> [<verb>]`
  describes one noun or one command, `discjockey where --json` says which folders this process works on. Every command
  and flag is listed there; this file holds no hand-written command shapes.
- **Grammar:** `discjockey <noun> <verb> [ids] [flags]`. `--json`, `--jsonl`, `--verbose`, `--no-color`, `--wait`,
  `--detach` and `--wait-busy` stand anywhere on the line; a flag a command does not take is a usage error, never
  ignored. `--dry-run` shows what a command that changes things would do; `--yes` is what such a command needs to run
  (a command never prompts). `discjockey call <method> [--args <json|->]` sends a bridge method the window's own
  payload, through the same refusals as the noun-verb command. `discjockey app open` opens the window.
- **The answer:** with `--json`, stdout holds exactly one object, for a usage error and a crash too; without it the
  answer is a text page, and notices and problems go to stderr. The keys, in this order: `v` (1), `command`,
  `outcome`, `reason`, `message`, `data`, `next` (commands to run next), `person_steps` (what only the person can do),
  `recovered` (always a list), `job`, `as_of` (`{scanned_at, read_at}`: when the index was last scanned and the
  playlists last read, from the stored records; both `null` without a music folder), `sandbox`.
- **Exit codes** are the outcome's: 0 `ok`, 1 `failed`, 2 `bad_args`, 3 `busy`, 4 `needs_person`, 5 `stopped`,
  6 `partial`, 7 `refused`, 8 `running`. `reason` is one word of the closed list in `discjockey/hub/outcomes.py`.
- **Jobs** (commands that change the library, and reads that can take minutes) run in a worker process that outlives
  the command; the first stderr line is `Job job:… started (follow: <path> job follow job:…)`, so a killed call still
  has the id. A command that starts a job waits as follows: `--detach` answers `ok` (exit 0, `job` set) once the job
  runs; `--wait S` answers the job's own envelope, or `running` (exit 8, with the progress and any `person_steps`) after
  S seconds while the job goes on; with no flag a terminal follows to the end and anything else waits 90 s. `job list
  [--all]`, `job show <job|current> [--log]`, `job follow <job|current> [--jsonl] [--from-end]`, `job wait <job|current>
  [--wait S]` and `job stop <job|current> [--now]` work on any job from any process (`current` is the one running write
  job of this music folder); Ctrl-C in the command that started a job stops it safely, a second press a second later
  stops it at once. A `--jsonl` answer is one event per line, then the envelope.
- **Scratch folders:** a command run by hand always sets `DISCJOCKEY_SUPPORT=<scratch folder>` and
  `DISCJOCKEY_REKORDBOX=<fixture folder or an empty folder>`: without them it reads, and a job writes, the real
  library and the real rekordbox library. `where` prints what a process resolved.
- **Not rebuilt yet:** the sync (no command), `setup`, `update`, `upgrades`, `upgrade`, `batch`, `convert`,
  `rename`, `settings`, `batch resume | undo` and `rekordbox checked | backups | restore` still run the old command line
  (`cli/legacy.py`; `discjockey <word> --help` prints their flags and exit codes). The sync takes `--dry-run` (changes
  nothing), `--yes` (no question), `--limit N` (at most N downloads), `--extra N` (N more Qobuz downloads today),
  `--verbose` and `--json` (needs `--yes` or `--dry-run`; one object `{"ok", "exit_code", "dry_run", "report",
  "counts", "auto_upgrade"}`, every human line on stderr); exit 0 done, 1 errors in the run, 2 setup problem or no
  music folder, 3 another run holds the library, 130 stopped (Ctrl-C once stops after the current step, twice stops at
  once). `batch resume | undo`, `upgrade`, `convert`, `rename` and `settings` take `--json` (and `--dry-run` where a plan can be shown) too.
  Each word leaves with the group that builds its replacement.

`help --json` layout: `data` is `{command, version, global_flags: [{flag, says}], commands: [...]}`. Each command:
`command` (`rekordbox status`), `kind` (`R` read, `RJ` read that may run as a job, `J` write job, `J-control`
stops a job, `B` brief save, `words` for `help`, `where`, `app open` and `call`), `writes`, `job` (runs as a job),
`args` (`{name, word, positional, many, required, type}`: what the person types), `flags` (the ones beside the
arguments: `--dry-run`, `--yes`, `--limit`, `--offset`), `needs_yes`, `dry_run`, `locks`, `reasons` (the `reason`s the
command may answer with), `example` and `usage`. A command that is not built yet is not listed.

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
