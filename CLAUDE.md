# CLAUDE.md — Discjockey

Discjockey keeps a lossless DJ library in step with the user's Spotify playlists: Qobuz as 16-bit AIFF first, then the
best fallback (YouTube Music, SoundCloud, YouTube), and it never deletes a music file. Two front ends share one engine:
the console (`discjockey`) and the hub, a Mac window (pywebview + Svelte). `README.md` is the user's manual — read it for
how a feature behaves from the user's side. `CONTRIBUTING.md` holds the developer notes (checkout, UI workflow,
building, releasing).

The repo is public (github `TheZwiss/discjockey`); users install the signed app from its releases. A maintainer
develops on a Mac that also holds their own library, and tests never touch a real library.

---

## Layout

A user's data never sits in the repo and none of it is in git — never test against it:

- **The music folder** (whatever the user chose in Setup, suggested `~/Music/Discjockey`): `playlists.txt` (the only
  config), `Library/<Folder>/` (+ `not_lossless/`), `Superseded/`, `Upgrades ready/`, and the hidden `.discjockey/`
  (`library.db`, `state.v1.json` (the old records, kept as a copy after the migration), `reports/`, `not_lossless.md`, the lock).
- **The support folder** `~/Library/Application Support/Discjockey/`: logins, `settings.json`, `config.json` (names
  the music folder), caches, `tools/` (updated yt-dlp, spec public-release §6.4). For a developer run against a
  scratch library set `DISCJOCKEY_SUPPORT=<scratch folder>` (Setup then asks for a music folder). Tests point it at a
  temp folder by themselves.

| Path | What |
|------|------|
| `bin/discjockey` | Launcher: `uv sync`, then `.venv/bin/python -m discjockey` (under `caffeinate` except for `hub`) |
| `discjockey/` | Engine. Each module's docstring says what it owns; read that before opening the file |
| `discjockey/planner.py`, `discjockey/hub/views.py` | Pure: no I/O, no clock. Keep them that way |
| `discjockey/library.py` | Everything on disk: paths (music folder, `.discjockey/`, support folder), `config.json`, lock, names, crash-safe ops (`run_op` for single steps, `move_files` / `move_path` for file moves, also across drives; both backed by `db.py`), `scan_library` |
| `discjockey/db.py` | `library.db`: the schema, the migration from `state.json`, the move log (batches and moves), the playlists' read records, Favourites and crate visibility (all three outside library state: they never bump `generation` or enter `snapshot`), every query. Nothing else writes SQL |
| `discjockey/sources/` | Playlist services, one module per service (`spotify.py`, `qobuz.py`) behind one interface (`recognise`, `canonical_link`, `login_state`, `open` → a `Reader` with `fetch` and `info`; `base.py` holds `SourceError`, `LoginState`, `Reader`). `__init__.py` is the registry (`SOURCES`) with `recognise`, `read` and `read_infos`. A new service is a new module plus one registry line. Songs and playlists are named by tokens (`models.token`): a Spotify id stays bare, every other service's id is `service:id` |
| `discjockey/qobuz.py` | The Qobuz **download** client (streamrip: login, search, download one track). Reading Qobuz playlists is `sources/qobuz.py`, which opens its own login per read |
| `discjockey/tidy.py` | The tidy-up: move batches (tidy-up, save question, folder rename), undo, recovery of batches a crash left open; every move through `run_op` or `library.move_files` (the file journal, staging across drives) |
| `discjockey/scanner.py` | Walks the watched folders (`Library/` and the import folders) against the index's file rows and returns a `ScanResult`. Reads only, no SQL; `db.apply_scan` writes it, `library.scan_library` ties the two together |
| `discjockey/identify.py` | Pure: whether a playlist song and a song of the user's own (a file the import read) are the same song (`compare`: certain or plausible), and an own song's name from its tags or file name. The planner calls it on every plan |
| `discjockey/importer.py` | The import of watched folders (`run_import`, a write job): scan, pass 1 tags, pass 2 sound check, then linking to the playlists (`run.link_only`). Progress lives on each file's row, so a stop resumes; nothing is copied, moved or renamed |
| `discjockey/folders.py` | Watched-folder actions and the To-do answers for the import: check, add, remove, "Is this the same song?", Keep both, Move to Superseded. Every file change through `library.move_files` |
| `discjockey/content_key.py` | The content key of an audio file (`1:<payload length>:<sha256>` over windows of the audio, so it survives renames, moves and tag edits; how a moved file is found) and `AUDIO_EXTS` |
| `discjockey/run.py` | One sync run, front-end independent; `console.py` and `hub/jobs.py` render its `events.py` events |
| `discjockey/__main__.py`, `discjockey/cli.py`, `discjockey/tools.py`, `discjockey/tool_updates.py` | `python -m discjockey` runs `tools.activate()` (bundled ffmpeg/ffprobe/deno first on `PATH`, a newer downloaded yt-dlp first on `sys.path`) before `cli.py` imports anything that imports yt-dlp; `--check-tools <folder>` is the update check's child process (spec public-release §6.1, §6.4); `tool_updates.py` updates yt-dlp from PyPI into `<support>/tools/` (never `uv.lock`), keeps one previous, rolls back |
| `discjockey/app_main.py`, `discjockey/selftest.py` | The app's program (spec public-release §5): `--check-tools` first, then `--self-test` (imports, bundled programs, tone → AIFF, UI file, the update check; scratch support folder, no network), else `tools.activate()` and the hub. `python -m discjockey.app_main --self-test` runs it in a checkout |
| `discjockey/hub/` | Window: `api.py` (bridge methods), `views.py` (screen JSON), `jobs.py` (background work + events), `media.py`, `spectrum.py` |
| `discjockey/hub/static/` | **Build output** of `hub-ui` (committed). Never edit by hand |
| `hub-ui/` | Svelte 5 + Vite + TS. `src/lib/bridge` (only `client.ts` touches `window.pywebview`), `bridge/fake` (offline backend), `components`, `stores`, `pages/<page>/` |
| `hub-ui/src/lib/frames` | The two page frames (`ListPanelFrame`, `ColumnFrame`) and `Panel`; the design system's blocks are in `lib/components`, its catalogue is the gallery `#/dev/gallery` (fake mode) |
| `packaging/` | The app build (spec public-release §5–§6.6): `tools.json` pins deno (URL + SHA-256) and FFmpeg's source release with its configure arguments (`fetch_tools.py` fails on a hash mismatch and builds ffmpeg/ffprobe with `build_ffmpeg.sh` on a cache miss), `licenses/` the hand-kept licence texts (see the next row; `collect_licenses.py` adds those of every distribution with files in the app; the spec runs it on what Analysis collected), `discjockey.spec` (PyInstaller; entry `launch.py`, Info.plist from `app_info.py`), `dmg_settings.py` (dmgbuild); `scripts/build_app.sh` runs them all. Plain scripts, never a Python package (it would shadow PyPI's `packaging`); tests load them with `tests/packaging_helpers.py` |
| `packaging/licenses/ffmpeg.txt` | The bundled ffmpeg's notice: GPL-3.0-or-later, built from the pinned source without external libraries (issue 19), the macOS libraries it uses, and its configuration line, which a test pins against `tools.json`'s configure arguments. A new `--enable-lib…` needs its licence text here and a GPL-3.0-compatible licence |
| `LICENSE` | GPL-3.0, byte for byte `packaging/licenses/GPL-3.0.txt` (a test compares them) |
| `scripts/check_public.sh` | The public check (`check_public.py` does the work, stdlib only): a real person's `/Users/` path, e-mail addresses outside the allowed domains, other repos of the account, and the words of a denylist kept outside the tree (`~/.discjockey-public-denylist`, or `DISCJOCKEY_PUBLIC_DENYLIST`) |
| `scripts/make_public_tree.sh` | Builds the public repo's first commit as a local, parentless branch (`public-main`) from a ref minus `docs/archive/pre-public/`, after the public check passes on exactly that tree; prints the go-moment steps. Sends nothing |
| `scripts/public_push_guard.sh` | The pre-push hook those steps install: refuses any push whose commits descend from a private-history root commit (the roots are written at install time) |
| `scripts/import_signing_identity.sh` | CI: imports the "Discjockey Release" identity from its `.p12` (`SIGNING_P12_PASSWORD`) into its own keychain in `DISCJOCKEY_SIGNING_DIR` |
| `.github/workflows/` | `check.yml`: every push and pull request (public check, pytest with the pinned tools, committed `hub/static` matches a fresh hub-ui build; not `npm run verify`); `release.yml`: a `v*` tag → the same checks, the signed app, its self-test, the .dmg on a **draft** release. Both run only in `TheZwiss/discjockey` |
| `dist/` | Build output (gitignored): `app/`, the .dmg, `tools/`, `licenses/` + `bundled-sources.txt` (what they cover), `ui/` (the check build), `cache/` (downloads by hash, the ffmpeg build by its recipe), `build/venv`, `work/` |
| `tests/` | pytest. `conftest.py` blocks network + PyPI, stubs yt-dlp; helpers `hub_`, `audio_`, `tools_helpers.py` |
| `docs/hub-design-language.md` | **Living. Read first for any UI work:** the hub's design rules with do/don't, the blocks, the rule checker, Sync as the reference page |
| `docs/hub-page-brief.md` | The playbook a page agent follows to redesign one hub page (phase 2) |
| `docs/hub-bridge-contract.md` | Living contract between `discjockey/hub` and `hub-ui`, pinned by tests |
| `docs/issues.md` | Open bugs, wishes and pending live checks |
| `docs/hub-mockups/` | Approved HTML mockups; `hub-ui/scripts/shots.mjs --compare` renders against them |
| `CONTRIBUTING.md` | Developer notes: checkout, the Terminal version, tests, the UI workflow, building, the public check, releasing and the CI secrets |
| `docs/archive/` | Finished specs, plans and handovers. `pre-public/` holds everything archived before the repo went public (gitignored, on the maintainer's disk only); plans archived from now on go into `docs/archive/` itself and are public. See "Docs and plans" |

Gitignored runtime files (`state.json`, `settings.json`, `reports/`, `not_lossless.md`, `.spotify_*.json`, `.streamrip/`)
are leftovers of an old layout in the maintainer's checkout; nothing writes them there any more.

---

## Commands

| What | Command (from the repo root unless noted) |
|------|------|
| Python tests | `~/.local/bin/uv run pytest -q` |
| UI check + tests + trial build | `cd hub-ui && npm run verify` |
| UI build into `discjockey/hub/static/` | `cd hub-ui && npm run build` |
| Built-app smoke test (WebKit, stub bridge) | `cd hub-ui && npm run smoke` (after build) |
| Fake-mode dev server | `cd hub-ui && npm run dev` (fake backend, `?scenario=…`, toolbar) |
| Screenshots | `cd hub-ui && node scripts/shots.mjs --port <dev port> --page <page> [--sizes min,default,large] [--compare]` or `--all` → `hub-ui/screenshots/<name>@<w>.png`; sizes default to all three (1100×700, 1280×800, 2560×1440) |
| Design rule checker | `cd hub-ui && npm run rules [-- --page P --only a,b --force]` (also part of `npm run verify`) |
| Hub window in the terminal | `DISCJOCKEY_HUB_DEBUG=1 bin/discjockey hub` |
| Dry run (changes no music files, writes no report) | `bin/discjockey --dry-run` |
| Signing identity (once per maintainer Mac) | `scripts/make_signing_identity.sh` → `~/.discjockey-signing/` (own keychain + password, `.p12` for the password manager and CI). Refuses to replace an existing one |
| Sign an app by hand | `.venv/bin/python packaging/sign_app.py dist/app/Discjockey.app` (ad-hoc without the identity; `--require-identity` for releases) |
| Build the app + .dmg | `scripts/build_app.sh` (background, ~5–10 min) → `dist/app/Discjockey.app`, `dist/Discjockey-<version>.dmg`; the app bundles the checkout's `hub/static` and the build fails when `hub-ui` builds something else (`SKIP_UI_BUILD=1` skips that check), `REQUIRE_IDENTITY=1` refuses ad-hoc signing and a checkout with uncommitted changes. Never copy the result into `/Applications` |
| Self-test of a built app | `DISCJOCKEY_SUPPORT=$(mktemp -d) dist/app/Discjockey.app/Contents/MacOS/Discjockey --self-test` |
| Scratch run (own support folder, asks for a music folder; runs in the terminal) | `DISCJOCKEY_SUPPORT=/tmp/dj bin/discjockey hub` |
| Public check (before every commit) | `scripts/check_public.sh` (`--dir DIR` scans a folder instead of the tracked files); the maintainer adds `--require-denylist`, which fails when the denylist file is missing, unreadable or empty |
| Public tree, trial | `scripts/make_public_tree.sh --dry-run --email <id>+TheZwiss@users.noreply.github.com` (the real run only at the go-moment, `docs/issues.md`) |
| Release | bump `__version__` + `pyproject.toml`, commit, `git tag v<version>`, push the tag by name (`git push origin v<version>`, never `--tags`/`--all`/`--mirror`) → `release.yml` makes a draft release; the maintainer publishes it by hand (`CONTRIBUTING.md`) |

Never start a real sync, upgrade swap or Qobuz download yourself: it touches the user's library and counts against
their Qobuz daily limit. Long commands run in the background with a status line.

---

## Invariants

- **Never delete or overwrite a music file.** Replaced files move to `Superseded/`. Every file change goes through
  `library.run_op`, or `library.move_files` / `move_path` for moves (the file journal; crash-safe, resumable, across
  drives). A new code path that writes into `Library/` or a watched folder without one of them is a bug.
- **Names in `Library/` are always `Artist - Title.<ext>`** for files Discjockey downloads or adds — no `(v2)`,
  `(new)` or similar suffixes; those exist only in `Superseded/`. The one exception: a file that is in the way of the
  correct name gets an ID added. **Moving never renames:** a tidy-up and its undo keep each file's name as it is,
  because rekordbox's Relocate finds files by name.
- **Files move only in a move batch the user started** (tidy-up, the Playlists save question, a folder rename on
  disk): logged in `library.db`, undoable; the sync never moves a file (option A).
- **Qobuz protection stays on:** pacing, the daily limit with carry-over, and the pause after 3 failures in a row.
  Never add a path that skips them, not even for tests against the real service.
- **Tests are offline and never touch the user's data.** Use `tmp_path` libraries and the fixtures; no real Spotify,
  Qobuz or yt-dlp calls.
- **One writer at a time:** the library lock (`.lock`) is shared by console runs and hub jobs; hub write methods
  answer `busy`/`console` instead of waiting. The exception is the brief saves `setup_skip_import`, `set_favourites`
  and `set_crate_shown`: they take no library lock, wait up to 1.5 s on `library.db`, then answer `busy`; that is safe
  because no job writes those records.
- **Bridge methods never reject:** `{"ok": true, …}` or `{"ok": false, "kind", "message"}`; write methods return a
  `job_id` and finish with a `JobFinished` event, except the same three brief saves, which answer their result at once
  and start no job.
- User-facing text is plain English for a non-technical DJ — no jargon, no stack traces (see README's tone).

---

## Principles

- **No band-aids.** Trace a bug to its root cause; never patch the symptom in the UI when the engine is wrong.
- **Refactor when necessary.** If a fix needs a poorly designed function reworked, rework it instead of building on it.
- **Think long-term, check for debt.** Before finishing, ask whether the change adds technical debt; if it does, find
  the better design.
- **Be independent.** Fix problems you notice on the way; note the ones out of scope in `docs/issues.md`.
- **No new dependencies without a reason** stated in the commit. Versions in `hub-ui/package.json` are pinned exactly.

## Critical rules

- No placeholder code, `TODO` comments, `# ...rest of code` or "similar to above". Every function is fully
  implemented, with its error handling and edge cases.
- Never skip files or leave a component half done: all states (loading, empty, error, busy) are handled.
- If something fails, fix it before moving on.
- **Done means verified:** `uv run pytest -q` green; for any `hub-ui` change also `npm run verify`, `npm run build`
  and `npm run smoke` green; for visible changes, screenshots in fake mode (and the real window where the fake can't
  show it) looked at by you. Ask the user only for what needs a human: sound, feel, rekordbox, decisions.
- **Scale the checks to the change; the full suite runs once.** `npm run verify` takes about 20 minutes (its rule
  checker shoots every page), so it runs **once per branch, before the merge**, never after each fix or review round.
  The full Python suite runs in parallel (pytest-xdist, `-n auto` is the default) in about 25 s: run it once at the
  end of a task, with `| tail -3`, never after each edit. CI (`check.yml`) runs it again on every branch push.
  While working and for a fix, check only what changed: `npm run check`, the touched tests
  (`npx vitest run <file>`, `uv run pytest -q tests/test_<x>.py`), `npm run rules -- --page P --only <shots>` for
  the shots it affects, one screenshot or a measuring script for a visual or motion fix, and `npm run build` when
  the user will run the app. Anything over a minute goes in the background with a status line.
- New behaviour gets tests: engine logic in `tests/`, UI logic in a pure `*Model.ts` / `*.ts` with a `*.test.ts` next
  to it, a fake scenario + `shots.json` entry for each new screen state.
- **UI work reads `docs/hub-design-language.md` first; pages use only the blocks; a missing pattern is added
  centrally (block + gallery + doc), never built in a page.** The core rules, in short:
  - More space shows more, never bigger: fixed sizes; extra width shows columns, extra height shows rows.
  - One filled button per screen (per dialog in a dialog).
  - Choices are `ToggleGroup` rows or `Segmented`, never loose pills.
  - No prose on the background: one-line `Hint` under its control, `InfoTip`, or `NoteCard`.
  - Pages use only the blocks; a missing pattern is added centrally.
  - `npm run verify` (it runs the rule checker) green before the merge; per fix, `npm run rules` on the touched shots.
  - Improve, don't preserve: critique what you touch (edges, grouping, space at 1100 and 2560, hierarchy,
    consistency, intent) and fix what you find; consistency is absolute; every change names a reason, system changes
    happen once in the block, and taste goes to the user (spec §12).

---

## Docs and plans

- **Everything tracked is public.** Never write a home path, a real name or a private address into a tracked file
  (made-up `/Users/you`, `/Users/dj` and `example.com` are fine); `scripts/check_public.sh` must pass before every
  commit (the maintainer's checkout has the denylist, so there it runs with `--require-denylist`).
- **Contract:** any change to `discjockey/hub/api.py`, `views.py` shapes or `jobs.py` events updates
  `docs/hub-bridge-contract.md`, `hub-ui/src/lib/bridge/types.ts` + `contract.ts`, and the fake backend in the same
  commit.
- **Design language:** any change to `hub-ui/src/lib/styles/tokens.css`, a frame or a block updates
  `docs/hub-design-language.md` (and the gallery) in the same commit; a system-level design decision goes into its
  decision log with its reason.
- **README:** update it when user-visible behaviour, commands or folders change. Not for internal refactors.
- **Issues:** a bug or wish you find but don't fix goes into `docs/issues.md` (newest on top); remove the entry in
  the commit that fixes it.
- **New specs and plans** go in `docs/` as `YYYY-MM-DD-<topic>-design.md` / `-plan.md`.
- **Plans are designs, not pre-written code.** A plan fixes the decisions, not the lines of code. It covers the
  architecture, each task's files, the exact interfaces between tasks (names, signatures, event and data shapes), the
  binding values (URLs, limits, words the user sees) and the behaviours each task's tests must pin, with the reason
  for each decision. It leaves out full code and full test bodies, except a short snippet where the exact form is the
  decision. The implementer reads the code and writes the exact implementation and tests. A planner reads only what
  the design depends on. Where it isn't sure, it writes "check first: …" into the task, and the implementer does
  that check. Aim for about 300–600 lines. **This overrides the `superpowers:writing-plans` skill** where they
  conflict: its "complete code in every step", "no placeholders" and "code blocks required" rules don't apply here.
  A "check first: …" step, or a behaviour to test without the test's body, is not a placeholder.
- **Finished plans must always be archived.** When a plan's last task is done (or the user drops it), in the same
  change: move the plan, its design spec and any handover or test-sheet files that belonged to it into
  `docs/archive/` (`git mv`), and carry every task or gap still open into `docs/issues.md`. `docs/` top level holds
  only living documents and plans in progress.
- **`docs/archive/pre-public/`** holds the specs and plans archived before the repo went public. It is gitignored:
  it exists on the maintainer's disk only, never in a public clone. Docstrings cite these specs; open one only when
  you need the reason behind a decision, and if it isn't there, go by the code and its tests.
- **Don't read `docs/archive/`** unless the user asks or you need the reason behind a decision. Code docstrings cite
  sections such as `spec "hub" 6.8`, `spec sources-and-limits §2` or `spec settings-setup §13`; those are
  `docs/archive/pre-public/2026-10-15-hub-design.md`, `docs/archive/pre-public/2026-10-18-sources-and-limits-design.md`
  and `docs/archive/pre-public/2026-10-22-settings-setup-design.md` (engine spec:
  `docs/archive/pre-public/2026-10-13-dj-sync-design.md`). Open the
  cited section with a search, never the whole file — the plans run to thousands of lines.

---

## Git

- Commit messages: `type(scope): what changed, in plain words` (`feat`, `fix`, `test`, `docs`, `build`; scopes like
  `hub`, `hub-ui`, `sync`, `upgrades`). The rebuilt `discjockey/hub/static/` goes in its own `build(hub): static` commit.
- Larger work on a branch (`fix/<topic>`, feature names), merged into `main` with `Merge <branch>: <summary>`.
- `archive/*` branches and tags (the maintainer's local copy of the private history from before the repo went public)
  are never pushed, merged or used as a base; a new branch starts from `main`. The maintainer's checkout has a local
  pre-push hook (`scripts/public_push_guard.sh`, installed at the go-moment) that refuses any push carrying that
  history; never skip it with `--no-verify`.
- Never commit secrets: `.spotify_*.json`, `.streamrip/`, `settings.json` stay ignored.
- Commits use the GitHub no-reply address (`<id>+TheZwiss@users.noreply.github.com`) set in this repo's own git
  config, never a personal e-mail (spec public-release §9).
