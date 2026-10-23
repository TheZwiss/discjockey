# Public release phase 6: public repo prep — implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
> This plan is a design (CLAUDE.md "Docs and plans"): it fixes decisions, interfaces, values and the behaviours tests
> must pin. The implementer reads the code and writes the code and the test bodies. "Check first: …" steps are the
> implementer's to do before deciding the detail they cover.

**Goal:** Everything the public repo needs before it exists: a scrubbed tree with a check that keeps it scrubbed,
the GPL-3.0 licence and exact third-party licence ids, the user manual / contributor guide split, CI for pushes and
tagged releases, and a script that builds the public orphan commit locally, without creating a repo or pushing.

**Architecture:** One checker (`scripts/check_public.sh`, a thin wrapper over a stdlib-only Python script) holds the
generic scrub rules; personal words live outside the tree (a local file, a CI secret), never in it. The old archive
moves to `docs/archive/pre-public/`, stays tracked in the private repo and is cut out only when the public commit is
built from git objects (`scripts/make_public_tree.sh`). Two GitHub workflows: `check.yml` on every push, `release.yml`
on `v*` tags (signed build, draft release). Docs follow last so they describe the finished scripts.

**Tech Stack:** bash 3.2 (macOS), Python 3.12 stdlib, git plumbing (`read-tree`, `write-tree`, `commit-tree`),
GitHub Actions on `macos-15`, `actionlint` (installed on the maintainer Mac), pytest.

**Spec:** `docs/2026-10-22-public-release-design.md` §6.3, §6.5, §7, §9, §11, §12 phase 6; `docs/issues.md` 15, 16, 18.

## Global Constraints

- Hard stops (need the user's go, never done by any task): creating the GitHub repo, `git push` anywhere, adding
  repository secrets, publishing a release, phase 7. No task runs `gh repo create`, `gh release`, `git push` or
  `git remote add`; the release workflow is written, never triggered.
- Public repo: `TheZwiss/discjockey`; release URL base `https://github.com/TheZwiss/discjockey/releases`.
- Author identity of the public commit: `<id>+TheZwiss@users.noreply.github.com`, name `TheZwiss` (spec §9).
- Licence: GPL-3.0 (spec §6.5). SPDX id for Discjockey's own code: `GPL-3.0-only` (decision, Task 5).
- Release CI: tag `v*`, `macos-15`, `REQUIRE_IDENTITY=1 scripts/build_app.sh` (which runs the self-test and makes
  `dist/Discjockey-<version>.dmg`), attached to a **draft** release (spec §7).
- Scrub rules (spec §9): no macOS user name of the maintainer, no real name, no university e-mail, no absolute
  `/Users/` path of a real person, no private repo URL. Test data uses made-up names (`spotify_user: 'dj'`).
- This plan and every file that goes public must pass the checker itself: never write the maintainer's user name,
  real name, home path or the private repo's name into a tracked file, this plan included.
- Tests offline, never touching the user's data or the login keychain (CLAUDE.md Invariants). A dedicated
  throwaway keychain in a temp folder is allowed for the opt-in signing round trip in Task 4.
- No new dependencies (no PyYAML: workflow tests use `actionlint` + text pins).
- Commit messages `type(scope): plain words`; any rebuilt `discjockey/hub/static/` in its own `build(hub): static`.

## Review Focus

1. **The checker trips on its own tests.** Test files that need a forbidden example must build it at runtime
   (string pieces joined, written into `tmp_path`), so `scripts/check_public.sh` on the repo stays green. Pinned in
   Task 1 by a test that runs the checker over the real tracked tree.
2. **A personal word leaks into CI logs.** The checker never prints a denylist match, only `denylist entry N`;
   the workflows pass the secret through `env:`, never interpolated into `run:` text. Pinned in Tasks 1 and 4.
3. **Untracked or ignored files in the maintainer's checkout** (`.venv/`, `dist/`, old `state.json`,
   `settings.json`, `.spotify_*.json`, issue 12) must never reach the public commit. `make_public_tree.sh` builds the
   tree from git objects only, never from the working directory. Pinned in Task 3 by a scratch repo holding an
   untracked and an ignored file with a forbidden string.
4. **A tag that doesn't match `__version__`, or a re-run of the release job,** must not make a wrong or second
   release: the version check runs before the build, a re-run uploads to the same draft with `--clobber`, and nothing
   ever publishes. Pinned in Task 4 by text pins on `release.yml`.
5. **The workflows also run on the private repo** once `main` is pushed there (macOS minutes billed, secrets
   absent). Every job carries `if: github.repository == 'TheZwiss/discjockey'`. Pinned in Task 4.

---

## Files

| File | Task | What |
|------|------|------|
| `scripts/check_public.sh` (new) | 1 | Entry point named by the spec; `exec python3 -I scripts/check_public.py "$@"` |
| `scripts/check_public.py` (new) | 1 | The rules, the scan, the report (stdlib only) |
| `tests/test_check_public.py` (new) | 1 | Rule tests on tmp trees + the whole-repo run |
| `docs/archive/*` → `docs/archive/pre-public/*` | 2 | `git mv`, then `.gitignore` gains `docs/archive/pre-public/` |
| `.gitignore` | 2 | the line above |
| scrubbed files (3 known, more if the checker finds them) | 2 | made-up names |
| `CLAUDE.md`, `hub-ui/src/pages/sync/planModel.ts`, `BeforeStart.svelte`, `docs/*.md` | 2 | archive citations → `pre-public/` |
| `tests/test_docs_citations.py` (new) | 2 | every cited `docs/archive/…` path resolves |
| `scripts/make_public_tree.sh` (new) | 3 | Builds the orphan commit on a local branch; `--dry-run` |
| `tests/test_make_public_tree.py` (new) | 3 | Scratch repos in `tmp_path` |
| `scripts/import_signing_identity.sh` (new) | 4 | Lays out `$DISCJOCKEY_SIGNING_DIR` from a `.p12` (CI) |
| `scripts/make_signing_identity.sh` | 4 | Only if the shared keychain layout is factored out (check first) |
| `.github/workflows/check.yml`, `.github/workflows/release.yml` (new) | 4 | Push CI, tag release |
| `tests/test_workflows.py`, `tests/test_import_signing_identity.py` (new) | 4 | actionlint + text pins; import refusals + opt-in round trip |
| `LICENSE` (new), `pyproject.toml`, `hub-ui/package.json` | 5 | GPL-3.0 |
| `packaging/licenses/ffmpeg.txt`, `packaging/licenses/ffmpeg-libraries/` (new), `packaging/collect_licenses.py` | 5 | Issue 18 |
| `README.md`, `CONTRIBUTING.md` (new), `CLAUDE.md`, `docs/issues.md`, spec §9 wording | 6 | Docs |
| `tests/test_docs_links.py` (new) | 6 | Every local image/link in README and CONTRIBUTING exists |

Left out on purpose:
- **Running the workflows.** They can only run on GitHub; pushing is a hard stop. They are proved offline
  (`actionlint`, text pins, the scripts they call tested locally). The first real run is the go-moment.
- **Rewriting the private history.** The public repo gets one orphan commit (spec §9); old commits never go public,
  so no `filter-repo` work.
- **README screenshots of "Open Anyway".** Agents can't capture the screen. The README reads fully without them and
  names the slots in issues.md (Task 6).
- **Renaming `/Users/you`, `/Users/dj`, `/Users/someone`, `/Users/x` in tests and fake data** (about 90 hits). They
  are made up and exercise real macOS path shapes (`~` shortening); the checker allows exactly these names.

---

### Task 1: The public check (`scripts/check_public.sh`) — model: sonnet

**Files:** Create `scripts/check_public.sh`, `scripts/check_public.py`, `tests/test_check_public.py`.

**Interfaces:**
- Produces (used by Tasks 2, 3, 4, 6):
  - `scripts/check_public.sh [--dir DIR] [--require-denylist]`.
    Without `--dir`: scans the tracked files of the repo the script lives in (`git ls-files -z` from the repo root),
    minus everything under `docs/archive/pre-public/`. With `--dir DIR`: scans every regular file under `DIR`, no
    exclusions (so Task 3 proves the exclusion happened).
  - Exit `0` clean, `1` findings, `2` usage error or missing required denylist.
  - Output: one line per finding, `<path>:<line>: <rule>: <shown>`, then a last line `N findings` (or
    `public check: clean (<files> files, denylist: <loaded K entries | not found>)`).
  - Denylist file: path from env `DISCJOCKEY_PUBLIC_DENYLIST`, default `~/.discjockey-public-denylist`. Format: one
    entry per line, `#` comments and blank lines ignored, matched case-insensitively with word boundaries at each end
    that is a word character.
  - Python API for tests (`scripts/check_public.py`, loaded like `tests/packaging_helpers.py` loads plain scripts):
    `scan(files: Iterable[tuple[str, bytes]], denylist: list[str]) -> list[Finding]`,
    `Finding(path: str, line: int, rule: str, shown: str)`, `load_denylist(path) -> list[str] | None`, `main(argv)`.

**Rules (generic, no personal literal anywhere in the script):**

| Rule id | Finds | Allowed | Shown in output |
|---------|-------|---------|-----------------|
| `home-path` | `/Users/<name>` | `<name>` in `{you, dj, someone, x, Shared}` and the bare `/Users/` | the match |
| `email` | e-mail addresses (text files only) | domains `example.com`/`.org`/`.net`, `users.noreply.github.com`, any `*.invalid` / `*.test` / `*.example`; `git@github.com`; "addresses" whose domain ends in an image extension (`.png .jpg .jpeg .gif .svg .webp`) or whose domain's first label is all digits (file names like `x@1280.png`, `pkg@1.2.3`) | the match |
| `repo-url` | `TheZwiss/<repo>` (case-insensitive) | `<repo>` = `discjockey`, or followed by nothing repo-like (e.g. `repos/TheZwiss` alone) | the match |
| `denylist` | any denylist entry | none | `denylist entry <N>` — never the word |

Decisions and reasons:
- **Personal words come from outside the tree.** A literal in the script (or a hash of a common name, which a name
  list reverses in seconds) would publish exactly what the check guards. The local file covers the maintainer's Mac;
  CI gets the same text from the secret `PUBLIC_CHECK_DENYLIST` (Task 4). The university e-mail needs no denylist
  entry at all: the generic `email` rule rejects every address outside the allowed domains.
- **The private repo URL is caught generically** (`repo-url`): any `TheZwiss/` repo other than `discjockey`.
- **`home-path` uses an allowlist** instead of "no `/Users/` at all": the app shortens real macOS home paths, and
  its tests need the shape. The spec wording is amended in Task 6 to say "no real person's `/Users/` path".
- **Binary files** (a NUL byte in the first 8 KB) get `home-path`, `repo-url` and `denylist` (latin-1 decoded) but not
  `email`, which random compressed bytes can match. Screenshot PNGs can carry text chunks; the scan reads them too.
- **Paths are scanned as well as contents** (a finding on a path reports line `0`): a file named after a person leaks
  the same way.
- `python3 -I`, stdlib only: CI runs the check before `uv sync`, and `-I` keeps the checkout off `sys.path`.
- Missing denylist: a warning line, exit unaffected; with `--require-denylist` it is exit `2` with
  `denylist not found: <path> (set DISCJOCKEY_PUBLIC_DENYLIST)`.

- [ ] **Step 1: Tests first.** `tests/test_check_public.py`, all on `tmp_path` trees or in-memory `scan()` input.
  Every forbidden sample is built at runtime from pieces. Pin:
  - each rule finds its sample and reports the right path and line; allowed forms pass (`/Users/you/Music`,
    `a@example.com`, `12345+TheZwiss@users.noreply.github.com`, `shot@1280.png`, `TheZwiss/discjockey`,
    `api.github.com/repos/TheZwiss/discjockey/releases/latest`);
  - a denylist hit prints `denylist entry 2` and the word appears nowhere in stdout or stderr;
  - denylist matching is case-insensitive and whole-word (`Sample` matches `sample`, not `samples`);
  - a binary file with an e-mail-like byte run is clean; one with a home path is a finding;
  - a file *path* containing a denylist word is a finding;
  - `--dir` scans `docs/archive/pre-public/` when present; repo mode skips it (git-init a tmp repo with both);
  - `--require-denylist` with no file → exit 2; findings → exit 1; clean → exit 0;
  - **the real repo** (`scripts/check_public.sh` on this checkout, denylist env pointed at an empty tmp file) exits 0.
    This test is expected to fail until Task 2 is done: mark it `xfail(strict=True)` here and remove the mark in Task 2.
- [ ] **Step 2:** implement; run `~/.local/bin/uv run pytest tests/test_check_public.py -q`; run
  `shellcheck scripts/check_public.sh`.
- [ ] **Step 3:** run the checker on the repo and save its finding count in the report (it sizes Task 2).
- [ ] **Step 4: Commit** `feat(release): public check for personal data in the tree`.

---

### Task 2: Scrub the tree and move the archive — model: opus

Judgment across many files: what counts as the maintainer's real data, screenshots that may show it, recorded
fixtures, and citations that must keep resolving.

**Files:** `git mv docs/archive/* docs/archive/pre-public/` (everything there today, the phase 1–5 plans of this
spec included: they carry worktree paths); `.gitignore`; the files the checker names; citations in `CLAUDE.md`,
`hub-ui/src/pages/sync/planModel.ts`, `hub-ui/src/pages/sync/BeforeStart.svelte`, `docs/issues.md`,
`docs/2026-10-20-hub-design-system-design.md`, the spec; create `tests/test_docs_citations.py`.

**Interfaces:**
- Consumes: `scripts/check_public.sh` (Task 1).
- Produces: archive location `docs/archive/pre-public/` (Task 3 excludes it, Task 6 documents it); a local denylist
  at `~/.discjockey-public-denylist` (mode 600).

Decisions:
- **Archive stays tracked in the private repo; `.gitignore` only matters after the switch.** Spec §9 wants it on disk
  in the checkout and in the private repo. If this branch untracked it (`git rm --cached`), merging into `main` would
  *delete* the files from the maintainer's main checkout. So: `git mv` first (before the ignore line exists, so git
  never refuses an ignored target), then add `docs/archive/pre-public/` to `.gitignore`. The tracked files stay
  tracked; the ignore line keeps them out of the public repo after the cutover, when they are restored onto disk
  untracked (Task 6 writes that step into issues.md).
- **Citations:** every literal `docs/archive/<file>` in a tracked file becomes `docs/archive/pre-public/<file>`.
  CLAUDE.md's mapping of `spec "hub"`, `spec sources-and-limits`, `spec settings-setup` and the engine spec moves the
  same way. Docstrings that cite only a short name (`spec "hub" 6.8`) stay as they are. Future archived plans go to
  `docs/archive/` (public), as the spec says.
- **Made-up names** for the known hits: Spotify user id `dj`, display name `Sam Rivers` (in
  `hub-ui/src/pages/settings/settingsModel.test.ts` and `docs/hub-mockups/design-system/settings.html`). The spec's
  own hits (the user name, the surname, the private repo's name) are reworded without them (e.g. "the private repo").
  `CLAUDE.md`'s private repo line goes (Task 6 rewrites that paragraph; here only enough for the check).
- **`DJ Downloader`** (the maintainer's real music folder name) in `tests/fixtures/hub_events_*.jsonl` and
  `tests/hub_helpers.py`: replace with `DJ Music` consistently. Not a check rule (it identifies no one), but spec §9
  says files that refer to the user's real library are fixed.
- The denylist file is created by the implementer with: the macOS user name, each part of the maintainer's real name
  and the personal e-mail address (the agent knows these from its environment; never written into a tracked file or
  a report). The university e-mail is left to the user (Task 6 issue entry); the `email` rule covers it meanwhile.

- [ ] **Step 1: Check first:**
  - run the checker with the denylist in place; list findings by file (counts only in the report);
  - the 18 PNGs under `docs/hub-design-language/`: look at each (Read shows images) for a real name, real playlist
    or account names, a home path; if one shows real data, re-take it in fake mode with `hub-ui/scripts/shots.mjs`
    under the same file name and size. Also run the checker's binary rules over them (Step 2 does);
  - `tests/fixtures/hub_events_*.jsonl` and `scripts/record_hub_events.py`: were they recorded from the real
    library (real playlist names, real track lists)? If yes, replace names with made-up ones consistently with the
    tests that read them;
  - `git grep -n -i -e qobuz -e spotify -- tests/fixtures` for real account ids or tokens (there must be none);
  - whether any `hub-ui` change alters the production build (`npm run build`, then `git status discjockey/hub/static`).
- [ ] **Step 2:** fix every finding; move the archive; update citations; remove the `xfail` from Task 1's whole-repo
  test.
- [ ] **Step 3: Test** `tests/test_docs_citations.py`: every `docs/archive/<path>` string in a tracked text file
  resolves to an existing file, except under `docs/archive/pre-public/` when that folder is absent (the public
  clone). Pins the move and keeps future citations honest.
- [ ] **Step 4: Verify:** `scripts/check_public.sh --require-denylist` exit 0; full `uv run pytest -q`; `cd hub-ui &&
  npm run verify` (test file changed); `npm run build` + `npm run smoke` only if the build output changed.
- [ ] **Step 5: Commit** in two commits: `docs: move the pre-public archive to docs/archive/pre-public` (the move,
  `.gitignore`, citations, citation test) and `chore(release): made-up names in tests, mockups and fixtures`.

---

### Task 3: The go-moment script (`scripts/make_public_tree.sh`) — model: sonnet

**Files:** Create `scripts/make_public_tree.sh`, `tests/test_make_public_tree.py`.

**Interfaces:**
- Consumes: `scripts/check_public.sh --dir DIR --require-denylist` (Task 1); `docs/archive/pre-public/` (Task 2).
- Produces: `scripts/make_public_tree.sh --email <id>+TheZwiss@users.noreply.github.com [--name TheZwiss]
  [--ref HEAD] [--branch public-main] [--dry-run]`.
  - Exit `0` done, `1` refused (each refusal one plain line on stderr), `2` usage.
  - Real run: creates local branch `<branch>` pointing at one parentless commit; prints its SHA, file count and the
    go-moment steps (text only, Task 6 copies them into issues.md). Never checks the branch out.
  - Dry run: does everything up to the commit, prints `would commit <N> files (<size>) as "Discjockey <version>" by
    <name> <email>`, creates no commit and no ref.

Steps of the script, in order, with the reason for each:
1. **Refuse** when: not inside a git repo; `--email` missing or not matching
   `^[0-9]+\+TheZwiss@users\.noreply\.github\.com$` (spec §9; the numeric id is the user's, looked up at the
   go-moment); `<branch>` already exists (never move a ref the user may have pushed); `--ref` is `HEAD` and tracked
   files have uncommitted changes (`git status --porcelain --untracked-files=no`, same test `build_app.sh` uses).
2. **Tree from git objects only**: a temporary index (`GIT_INDEX_FILE` in a `mktemp -d` folder removed on exit),
   `git read-tree <ref>`, remove `docs/archive/pre-public` from that index (`git rm -r --cached --quiet
   --ignore-unmatch`), `git write-tree`. Reason: the working directory holds ignored and untracked personal files
   (Review Focus 3); the user's real index is never touched.
3. **Check the exact tree**: `git archive <tree>` extracted into the temp folder, then
   `scripts/check_public.sh --dir <that folder> --require-denylist` (run from the *source* checkout's script, so a
   tree that deleted its checker can't pass). Also refuse when the tree lacks `LICENSE`, `README.md`,
   `CONTRIBUTING.md`, `.github/workflows/check.yml`, `.github/workflows/release.yml`, or contains
   `docs/archive/pre-public`.
4. **Version** from the extracted `discjockey/__init__.py` (`__version__`); message `Discjockey <version>`.
5. **Commit** (skipped in dry run): `git commit-tree <tree> -m <message>` with `GIT_AUTHOR_NAME/EMAIL` and
   `GIT_COMMITTER_NAME/EMAIL` set to the given identity (no `-p`: orphan); `git branch <branch> <sha>`.
6. **Never** `push`, `remote`, `gh`, `checkout`/`switch`, `reset`, `config`. The go-moment steps are printed:
   create the repo (user's go), set the three secrets, `git push <public-url> <branch>:main`, switch the checkout to
   it, restore the archive onto disk untracked with
   `git restore --source=archive/main --worktree -- docs/archive/pre-public`, set `user.email` to the no-reply
   address in the repo config.

- [ ] **Step 1: Tests first** (`tests/test_make_public_tree.py`), each on a scratch repo built in `tmp_path`: `git
  init`, a minimal tree (`LICENSE`, `README.md`, `CONTRIBUTING.md`, the two workflow files, `discjockey/__init__.py`
  with `__version__ = "1.0.0"`, `scripts/` copied from the checkout), `docs/archive/pre-public/` with an `old.md` holding a
  forbidden home path built at runtime, plus an untracked and an ignored file holding a forbidden string, plus a bare
  repo in `tmp_path` added as `origin`. Denylist via `DISCJOCKEY_PUBLIC_DENYLIST` pointing at a tmp file. Pin:
  - real run: branch exists, its commit has no parent, author and committer are exactly the given name/email, the
    message is `Discjockey 1.0.0`, its tree lacks `docs/archive/pre-public` and the untracked/ignored files, and
    otherwise equals the source tree;
  - the source checkout is unchanged: same `HEAD`, same branch, `git status --porcelain` identical before/after, the
    real index file's mtime unchanged;
  - the bare `origin` has no refs afterwards (nothing pushed);
  - dry run: prints `would commit`, creates no ref, `git count-objects` may grow but `git for-each-ref` is identical;
  - refusals, each with nothing created: bad e-mail (`me@example.com`), existing branch, dirty tracked file, a
    tracked file outside the archive with a forbidden path (the check fails → no commit), a tree missing `LICENSE`,
    no denylist file;
  - static pin: the script text contains none of `git push`, `gh `, `remote add`, `checkout`, `switch`.
- [ ] **Step 2:** implement (bash 3.2: no `mapfile`, quote every path, `set -euo pipefail`, `trap` cleanup);
  `shellcheck`; run the tests.
- [ ] **Step 3: Dry run on a scratch clone of this checkout** (`git clone --no-local` of the worktree into the
  scratchpad, then `scripts/make_public_tree.sh --dry-run --email 1+TheZwiss@users.noreply.github.com` inside it).
  Expected now: refused for missing `CONTRIBUTING.md`/`LICENSE`/workflows (they come in Tasks 4–6); Task 6 repeats it
  green. Delete the scratch clone.
- [ ] **Step 4: Commit** `feat(release): make_public_tree.sh builds the public orphan commit locally`.

---

### Task 4: CI workflows and the CI signing import — model: sonnet

**Files:** Create `.github/workflows/check.yml`, `.github/workflows/release.yml`, `scripts/import_signing_identity.sh`,
`tests/test_workflows.py`, `tests/test_import_signing_identity.py`; maybe modify `scripts/make_signing_identity.sh`.

**Interfaces:**
- Consumes: `scripts/check_public.sh` (Task 1); `scripts/build_app.sh` with `REQUIRE_IDENTITY=1` (exists);
  `packaging/sign_app.py`'s signing-folder layout: `$DISCJOCKEY_SIGNING_DIR/discjockey-release.keychain-db`,
  `identity.sha1`, `keychain.pass` (exists, spec §6.3).
- Produces:
  - Repository secrets the user adds at the go-moment (names are binding, Task 6 documents them):
    `SIGNING_P12_BASE64` (base64 of `~/.discjockey-signing/discjockey-release.p12`), `SIGNING_P12_PASSWORD`
    (contents of `p12.pass`), `PUBLIC_CHECK_DENYLIST` (contents of the local denylist file).
  - `scripts/import_signing_identity.sh <file.p12>`, password from env `SIGNING_P12_PASSWORD`, target
    `$DISCJOCKEY_SIGNING_DIR` (required in this script: no default, so CI can never write into a home folder by
    accident). Writes the same three files `make_signing_identity.sh` writes, with a fresh random keychain password,
    and `security set-key-partition-list -S apple-tool:,apple: -s` so `codesign` never prompts. Never touches the
    search list (`sign_app.py` adds and restores it). Refuses when the folder already holds an identity, the file is
    missing, the password is empty or wrong, or the `.p12` holds no `Discjockey Release` code-signing identity.

**`check.yml`** (name `check`): `on: push` (all branches) and `pull_request`; `permissions: contents: read`;
`concurrency` per ref with cancel-in-progress; one job on `macos-15`, `timeout-minutes: 30`,
`if: github.repository == 'TheZwiss/discjockey'`. Steps:
1. `actions/checkout`.
2. Public check: the secret goes in through `env:` into a file in `$RUNNER_TEMP`, `DISCJOCKEY_PUBLIC_DENYLIST` points
   at it; `--require-denylist` when the secret is non-empty (pull requests from forks get no secrets; they still get
   the generic rules).
3. `astral-sh/setup-uv`, `uv sync --frozen`, the pinned tools on `PATH` (see check first), `uv run pytest -q`.
4. `actions/setup-node`, `npm ci` and `npm run verify` in `hub-ui`.

**`release.yml`** (name `release`): `on: push: tags: ['v*']` only; `permissions: contents: write`;
`concurrency: release-${{ github.ref }}`, no cancel; one job on `macos-15`, `timeout-minutes: 60`, the same
repository guard. Steps:
1. Checkout.
2. **Version gate before anything else:** `v` + `discjockey.__version__` must equal `$GITHUB_REF_NAME`, else fail
   with `tag <tag> does not match version <version>` (Review Focus 4).
3. Public check with `--require-denylist` (always: a release without the full check is refused).
4. uv sync + pytest, node + `npm ci` + `npm run verify` (as in `check.yml`; spec §7's `npm run build` is covered by
   `build_app.sh` step 1, which builds into `dist/ui` and fails unless it equals the committed `hub/static`;
   building into the tree would dirty the checkout that `REQUIRE_IDENTITY=1` insists is clean).
5. Signing: decode `SIGNING_P12_BASE64` into `$RUNNER_TEMP/release.p12`, `DISCJOCKEY_SIGNING_DIR=$RUNNER_TEMP/signing`,
   run `scripts/import_signing_identity.sh`.
6. `REQUIRE_IDENTITY=1 scripts/build_app.sh` (self-test and .dmg checks are inside it).
7. Draft release with `gh` and `GH_TOKEN: ${{ github.token }}`: if no release exists for the tag,
   `gh release create <tag> --draft --verify-tag --title "Discjockey <version>" --generate-notes <dmg>`; if a draft
   exists (re-run), `gh release upload <tag> <dmg> --clobber`; if a *published* release exists, fail (never replace
   a shipped .dmg).
8. `if: always()`: `security delete-keychain` on the CI keychain, remove `release.p12`.

Decisions: actions pinned by full commit SHA with the version in a comment (the release job holds the signing key;
a moved tag must not run new code with it); secrets only ever in `env:`; no `pull_request_target`; no
`workflow_dispatch` on release (a release always comes from a tag).

- [ ] **Step 1: Check first:**
  - which tests skip or fail without `ffmpeg`/`ffprobe`/`deno` on `PATH` (`tests/audio_helpers.py`, `test_audio.py`,
    `test_acquire.py`, `test_ops.py`, `test_quality.py` look them up). If they would skip, add a step that runs
    `packaging/fetch_tools.py --out dist/tools --cache dist/cache` (the hash-pinned builds) and prepends their folder
    to `PATH`, so CI tests what the app ships; cache `dist/cache` by `packaging/tools.json`'s hash;
  - whether `npm run verify` (`scripts/rules.mjs`) needs a Playwright browser; if so add
    `npx playwright install webkit` (pinned by the exact `playwright` version in `package.json`);
  - the Node version the hub is built with locally (`node --version`), and pin `setup-node` to that major;
  - the uv version (`~/.local/bin/uv --version`) to pin in `setup-uv`;
  - the current commit SHAs of the action versions you use (`gh api repos/<owner>/<action>/git/ref/tags/<tag>` is a
    read; allowed);
  - how `make_signing_identity.sh` writes the keychain (create, unlock, settings, import, partition list, SHA-1 via
    `security find-identity -p codesigning`); if the keychain half can move into a sourced
    `scripts/signing_keychain.sh` used by both scripts without changing `make_signing_identity.sh`'s behaviour, do
    that (one layout, can't drift); otherwise mirror it and pin the layout by the round-trip test;
  - that macOS's `security import` reads the `-legacy` PKCS#12 that `make_signing_identity.sh` exports (it does
    locally today; the round trip proves it).
- [ ] **Step 2: Tests first.**
  - `tests/test_workflows.py`: run `actionlint` on both files when it is on `PATH` (skip with a reason otherwise; the
    implementer's run must not skip). Text pins (no YAML library): `release.yml` triggers only on `v*` tags; contains
    `--draft` and never `--draft=false`, `gh release edit` or `--latest`; runs `REQUIRE_IDENTITY=1 scripts/build_app.sh`;
    the version gate comes before `build_app.sh`; `contents: write` only in `release.yml`, `contents: read` in
    `check.yml`; both run on `macos-15` and carry the repository guard; both run `scripts/check_public.sh`; no
    `${{ secrets.` inside a `run:` block; every `uses:` is pinned to a 40-hex SHA; no `pull_request_target`.
  - `tests/test_import_signing_identity.py`: refusals without touching any keychain (missing file, empty password,
    unset `DISCJOCKEY_SIGNING_DIR`, existing identity in the target). Opt-in round trip behind
    `DISCJOCKEY_KEYCHAIN_TESTS=1`: `make_signing_identity.sh` into temp folder A, import `A/discjockey-release.p12`
    with `A/p12.pass` into temp folder B; `identity.sha1` equal; `sign_app.find_identity(B)` finds it; both
    keychains deleted in a `finally` (and the login keychain and search list unchanged before/after).
- [ ] **Step 3:** implement; `shellcheck` the new script; `actionlint`; tests; run the opt-in round trip once and
  note it in the report (it must never pop a password dialog: if it would, stop and note it).
- [ ] **Step 4: Commit** `feat(release): CI on every push, signed draft release on a v* tag`.

---

### Task 5: Licences — model: sonnet

**Files:** Create `LICENSE`, `packaging/licenses/ffmpeg-libraries/<library>.txt` (one per library); modify
`pyproject.toml`, `hub-ui/package.json`, `packaging/licenses/ffmpeg.txt`, `packaging/collect_licenses.py` (only if it
doesn't copy subfolders), the licence tests; remove issue 18 from `docs/issues.md`.

**Interfaces:**
- Consumes: nothing from Tasks 1–4 (the checker must stay green).
- Produces: `LICENSE` (Task 3 requires it; Task 6 links it); the licence folder the app carries gains
  `ffmpeg-libraries/`.

Decisions:
- **`LICENSE` = the verbatim GPL-3.0 text**, the same bytes as `packaging/licenses/GPL-3.0.txt` (a test pins they are
  identical, so they can't drift). Spec §6.5: streamrip GPL-3.0-only and mutagen GPL-2.0-or-later force GPL-3.0.
- **SPDX `GPL-3.0-only`** for Discjockey's own code: it matches streamrip (the binding part), says what the spec
  says, and promises nothing about a licence that doesn't exist yet. `pyproject.toml` gets `license = "GPL-3.0-only"`;
  `hub-ui/package.json` gets `"license": "GPL-3.0-only"`.
- **The app says where its own source is**: GPL-3.0 §6 binary distribution needs the corresponding source offered.
  The licences index (`collect_licenses.py` `HEADER` or a `discjockey.txt`) names
  `https://github.com/TheZwiss/discjockey` and that the source of version `<v>` is the tag `v<v>`.
- **Issue 18 done fully:** exact SPDX ids in `ffmpeg.txt`, and each library's licence text with its copyright lines
  in `packaging/licenses/ffmpeg-libraries/`. Reason: BSD, MIT and ISC licences require their notice in binary
  distributions; naming them is not enough. Where a project has no SPDX id for a part (the AOMedia patent licence),
  use `LicenseRef-<Name>` and include that text too.

- [ ] **Step 1: Check first** (web lookups):
  - the library versions in the pinned ffmpeg 9.0.2 build (`packaging/tools.json` → the build's page at
    `martin-riedl.de`; does it publish a version list or a licence bundle per build? If it publishes a bundle, take
    the texts from there);
  - for each of the 27 libraries in `ffmpeg.txt`, the licence file in its own repo at that version, and its exact
    SPDX id — in particular whether `-only` or `-or-later` (libbluray, libklvanc, libzvbi, LAME, x264, x265),
    FreeType (`FTL OR GPL-2.0-or-later`?), Fontconfig (`HPND-sell-variant`?), HarfBuzz (`MIT-Modern-Variant`?), SVT-AV1
    (`BSD-3-Clause-Clear` + AOMedia patent licence?), libaom and rav1e (`BSD-2-Clause` + AOMedia patent licence),
    libvmaf (`BSD-2-Clause-Patent`), zimg (`WTFPL`), OpenSSL 3 (`Apache-2.0`) and which "small support libraries"
    (libogg, …) the build links, each named with its id;
  - any library whose licence is not GPL-3.0-compatible (a `GPL-2.0-only` part would be): if found, stop that
    sub-step and write it in the report as a blocker for the user's decision, with the source;
  - that `packaging/licenses/GPL-3.0.txt` is byte-identical to `https://www.gnu.org/licenses/gpl-3.0.txt`;
  - whether uv accepts the PEP 639 `license` string in a project without `[build-system]` (`uv lock --check`, then
    `uv sync`);
  - which tests pin `ffmpeg.txt` or the licence folder (`git grep -l licenses tests/`).
- [ ] **Step 2: Tests:** `LICENSE` equals `GPL-3.0.txt` byte for byte; every library line in `ffmpeg.txt` has a
  valid-looking SPDX expression (ids from a small allow set the implementer writes from Step 1, `LicenseRef-` allowed)
  and a matching file in `ffmpeg-libraries/`; every `--enable-lib*` in the configuration line has a row (the
  configuration line is the source of truth); the collected licence folder of a build includes `ffmpeg-libraries/`
  (extend the existing `collect_licenses` test); the licences index names the public source URL.
- [ ] **Step 3:** implement; `uv run pytest -q`; `scripts/check_public.sh` (licence texts carry copyright e-mails of
  third parties: if the `email` rule flags one, add that domain to the checker's allowed list only when it is a
  published project address, and say so in the commit).
- [ ] **Step 4: Commit** `docs(release): GPL-3.0 LICENSE and exact licences of ffmpeg's libraries (issue 18)`.

---

### Task 6: README, CONTRIBUTING, CLAUDE.md, issues — model: opus

A rethink of who each document is for, across several files; judgment on wording a non-technical DJ reads.

**Files:** `README.md`, create `CONTRIBUTING.md`, `CLAUDE.md`, `docs/issues.md`, the spec (§9 wording only), create
`tests/test_docs_links.py`.

**Interfaces:**
- Consumes: the commands and names of Tasks 1–5 (exact: `scripts/check_public.sh`, `scripts/make_public_tree.sh`,
  `scripts/import_signing_identity.sh`, secrets `SIGNING_P12_BASE64` / `SIGNING_P12_PASSWORD` /
  `PUBLIC_CHECK_DENYLIST`, `~/.discjockey-public-denylist`, `docs/archive/pre-public/`, `LICENSE`).
- Produces: the README image slots (file names below) that the human screenshot item fills.

**README.md — the user manual** (keep its tone: plain English for a DJ, no jargon):
- Top: what it is, then one line on what it needs.
- **Download**: link to `https://github.com/TheZwiss/discjockey/releases/latest`, the `.dmg` name.
- **Requirements**: Apple Silicon, macOS 12 Monterey or later, Spotify Premium with own playlists, a Qobuz
  subscription (check first what Setup actually requires and say exactly that).
- **Install and "Open Anyway"**: the existing steps, each step a numbered item that reads complete without a
  picture. Image slots, added later by the user: `docs/readme/open-anyway-1-warning.png` (after the step that shows
  the warning), `docs/readme/open-anyway-2-privacy.png` (System Settings line), `docs/readme/open-anyway-3-confirm.png`
  (the last Open). The README does **not** link them yet (no broken images, no TODO markers); the issue entry says
  where each goes.
- **Updates** (the existing paragraph: daily check, nothing about you is sent).
- **Setup** and everything else the README says today, minus developer notes ("from a source checkout: run
  `bin/discjockey hub`" moves to CONTRIBUTING).
- **Legal note** (spec §9), its own short section near the top or before "Account risk": what the tool does, that it
  needs the user's own Qobuz and Spotify accounts, that each user is responsible for following those services'
  terms. Plain, no legalese.
- **Licence**: GPL-3.0, link `LICENSE`, bundled components' licences inside the app (Settings → This Mac).

**CONTRIBUTING.md — developer notes** (new): checkout and `uv sync`, `bin/discjockey`, the dry run, tests, the UI
workflow (`npm run dev/verify/build/smoke`, fake mode, screenshots, `docs/hub-design-language.md` first), building the
app (`scripts/build_app.sh`), the signing identity, the public check (what it checks, the denylist file and env var),
and **how to release**: bump `__version__` and `pyproject.toml`, commit, tag `v<version>`, push the tag, the workflow
makes a draft release, look at it, publish by hand. Plus the CI secrets by name and what each holds. Short; link to
CLAUDE.md for the binding project rules rather than repeating them.

**CLAUDE.md:**
- The opening paragraph loses "Single user, private repo (…), runs on the user's Mac against their real library";
  it says the repo is public (`TheZwiss/discjockey`), a maintainer develops on a Mac, and tests never touch a real
  library.
- "Layout" loses the `DJ Downloader/` description and `old_download_pipeline/` line (it is untracked); the music
  folder and support folder bullets stay as generic descriptions; table rows gain `.github/workflows/`,
  `scripts/check_public.sh`, `scripts/make_public_tree.sh`, `scripts/import_signing_identity.sh`, `LICENSE`,
  `CONTRIBUTING.md`, `packaging/licenses/ffmpeg-libraries/`; the `docs/archive/` row says: `pre-public/` holds
  everything archived before the repo went public (gitignored, maintainer's disk only); new archived plans go in
  `docs/archive/` and are public.
- "Commands" gains: public check, `make_public_tree.sh --dry-run`, release by tag.
- "Docs and plans" gains the `pre-public` rule (cited specs live in `docs/archive/pre-public/`; don't read them
  unless needed; they are not in the public clone) and: **everything tracked is public — never write a home path, a
  real name or a private address into a tracked file; `scripts/check_public.sh` must pass before every commit.**
- "Git" gains: commits use the no-reply address set in the repo config (spec §9).

**Spec §9 amendments** (living until phase 7 is archived): the scrub bullet says "no real person's `/Users/` path
(made-up `/Users/you`, `/Users/dj`, `/Users/someone`, `/Users/x` are allowed)", the personal words come from a local
file and a CI secret; the archive bullet says it stays tracked in the private repo until the cutover and is restored
onto disk untracked after it.

**docs/issues.md** (newest on top):
- **19. Go public (needs the user's go)**: the go-moment checklist printed by `make_public_tree.sh`, in order: look
  up the GitHub numeric id; add the university e-mail to `~/.discjockey-public-denylist`; run the script (dry run,
  then real); create `TheZwiss/discjockey` (public, empty); add the three secrets; push the branch as `main`; switch
  the checkout and restore `docs/archive/pre-public` untracked; keep the old history as `archive/main`; set
  `user.email`; first tag `v1.0.0` → draft release; the user publishes after a look. Then issue 16 runs against the
  draft.
- **20. README screenshots of "Open Anyway"**: the three file names and where each goes; take them on a Mac with a
  quarantined .dmg (issue 16's `xattr` line), crop to the dialog, then link them in the README.
- **15** gains the secret names it maps to.
- **18** is already removed by Task 5.

- [ ] **Step 1: Check first:** what Setup requires today (Spotify Premium? Qobuz plan?) from `README.md`'s "One-time
  setup" and `hub-ui/src/pages/setup/`; every place in README that is developer-facing (`git grep -n -e uv -e npm -e
  pytest -e bin/discjockey README.md`).
- [ ] **Step 2: Test** `tests/test_docs_links.py`: every relative link and image in `README.md` and
  `CONTRIBUTING.md` resolves to a tracked file; README has a `## Download`, an "Open Anyway" section and the legal
  note's heading (names as written); the release URL is the public one.
- [ ] **Step 3:** write the docs; run `scripts/check_public.sh --require-denylist`, `uv run pytest -q`.
- [ ] **Step 4: Final verification of the phase** (everything, in the background with a status line):
  `uv run pytest -q`; `cd hub-ui && npm run verify`; `actionlint .github/workflows/*.yml`;
  `scripts/check_public.sh --require-denylist`; and the dry run on a fresh scratch clone
  (`git clone --no-local`, `scripts/make_public_tree.sh --dry-run --email 1+TheZwiss@users.noreply.github.com`) now
  green — then also a real run in that clone, inspect the branch (`git show --stat`, author, no parent, no
  `docs/archive/pre-public`), and delete the clone.
- [ ] **Step 5: Commit** `docs: README as the user manual, CONTRIBUTING for developers, CLAUDE.md for a public repo`.
  This plan stays in `docs/` until the go-moment is done (issue 19); then it is archived to `docs/archive/` (public).

---

## Self-review

- Spec coverage: §9 scrub + check (Tasks 1–2), archive move (2), fresh history + no-reply author (3), README split +
  legal note + CLAUDE.md (6), what goes public (3's tree checks), CI on every push (4); §7 tag workflow, draft,
  self-test (4, via `build_app.sh`); §6.3 CI rebuilds the signing folder from the .p12 secret (4); §6.5 LICENSE (5);
  issue 18 (5); issue 15 secrets (4, 6); issue 16 points at the draft (6). Phase 6's "then (with the user's go) the
  public repo and the first draft release" is issue 19, not a task.
- Names used across tasks: `check_public.sh --dir --require-denylist`, `DISCJOCKEY_PUBLIC_DENYLIST`,
  `~/.discjockey-public-denylist`, `docs/archive/pre-public/`, `make_public_tree.sh --email --name --ref --branch
  --dry-run`, branch `public-main`, secrets `SIGNING_P12_BASE64` / `SIGNING_P12_PASSWORD` / `PUBLIC_CHECK_DENYLIST`,
  `import_signing_identity.sh <file.p12>` + `SIGNING_P12_PASSWORD` + `DISCJOCKEY_SIGNING_DIR`.
