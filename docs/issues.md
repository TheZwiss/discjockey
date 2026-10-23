# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 23. README screenshots of "Open Anyway" (2026-10-23)

The README's Install and "Open Anyway" steps read complete without pictures; three screenshots would help. File
names and where each goes, as an image line right under its step:

- `docs/readme/open-anyway-1-warning.png`: the warning macOS shows the first time (under step 2).
- `docs/readme/open-anyway-2-privacy.png`: the Discjockey line with **Open Anyway** in System Settings, Privacy &
  Security (under step 4).
- `docs/readme/open-anyway-3-confirm.png`: the warning that shows once more, with its **Open** button (under step 6).

Take them on a Mac with a quarantined .dmg (issue 16's `xattr` line, or the draft release's download), crop each to
the dialog or the settings line, add them, then link them in the README. `tests/test_docs_links.py` fails while a
linked image isn't committed.

## 22. Go public (needs the user's go) (2026-10-23)

Decide before the go:

- The sample playlist names and the real artist names kept in test fixtures, the mockups and the screenshots: they
  identify no one. Keep them, or replace them with made-up ones?

Then, in this order (steps 4 to 11 are the ones `scripts/make_public_tree.sh` prints after a real run, as the
commands `tests/test_make_public_tree.py` replays against a scratch repo):

1. Look up your GitHub numeric id: GitHub's e-mail settings show the no-reply address
   `<id>+TheZwiss@users.noreply.github.com`.
2. Add your other e-mail addresses (e.g. a university one) to `~/.discjockey-public-denylist`, one per line, and
   run `scripts/check_public.sh --require-denylist`.
3. With every phase merged into `main` and the checkout clean: `scripts/make_public_tree.sh --dry-run --email
   <id>+TheZwiss@users.noreply.github.com`, then the same without `--dry-run`. It makes the local branch
   `public-main`: one commit, no parent, without `docs/archive/pre-public/`.
4. Install the push guard, then keep the old history by renaming, not copying. From the repo root, on `main`:
   `git rev-list --max-parents=0 --all --not public-main > "$(git rev-parse --git-common-dir)/private-roots"`,
   `cp scripts/public_push_guard.sh "$(git rev-parse --git-path hooks/pre-push)"`,
   `chmod +x "$(git rev-parse --git-path hooks/pre-push)"`, `git branch -m main archive/main`, then
   `git branch --unset-upstream archive/main`. The guard is a pre-push hook that lists the old history's root commits
   (the roots file) and refuses any push whose commits descend from one of them, whatever the command (`--all`,
   `--mirror`, `--tags`, `-u origin archive/main`); it is not tracked and `--no-verify` skips it, so never use that.
   From now on the old history lives only in local `archive/*` branches and tags, which are never pushed.
5. Create `TheZwiss/discjockey` on GitHub: public and empty (no README, no licence).
6. Add its three repository secrets: `SIGNING_P12_BASE64`, `SIGNING_P12_PASSWORD` (from `~/.discjockey-signing/`) and
   `PUBLIC_CHECK_DENYLIST` (the contents of `~/.discjockey-public-denylist`).
7. Push `public-main` as the new repo's `main`: `git push <public-url> public-main:main`.
8. Point the checkout's `origin` at the public repo (`git remote set-url origin <public-url>`, `git fetch --prune
   origin` so the old remote-tracking branches go), then `git switch public-main`, `git branch -m public-main main`
   and `git branch -u origin/main`. The daily branch is `main`, tracking `origin/main`, so a plain `git push` works.
9. Restore `docs/archive/pre-public/` from `archive/main` onto disk, untracked (it is gitignored):
   `git restore --source=archive/main --worktree -- docs/archive/pre-public`.
10. Set `user.name` (the handle) and `user.email` (the no-reply address) in this repo's git config; the global name
    would otherwise author every commit. The push guard also refuses a denylisted name, e-mail or message.
11. Every other local branch and tag from before the cutover carries the private history: the printed loops put each
    under `archive/` (branches without an upstream; tags as `archive/<name>`); `git branch --list` and
    `git tag --list` show what is left, `git worktree list` the old worktrees (`git worktree remove <path>`). Delete
    instead with `git branch -D` / `git tag -d` if you prefer. Never push one of them.
12. Tag `v1.0.0` and push that tag by name: `git push origin v1.0.0` (never `--tags`, `--all` or `--mirror`): the
    release workflow makes a draft release.
13. Issue 16 runs against the draft. Then the user publishes it after a look.

## 21. Global audio controls for track previews (wish, 2026-10-23)

A track preview started on any page keeps playing after you leave that page, which is right. But nothing outside that
page lets you control it any more. Wanted: controls that follow you everywhere once a preview has started.

- **Controls:** play/pause, previous and next track (within the list the preview was started from), and shuffle
  (random order within that list).
- **Form, an idea to design from:** a floating control pill that appears when a preview starts and stays while it is
  paused. The user can hide it, and bring it back from anywhere (e.g. a small control in the sidebar or the window
  chrome).
- **Mandatory:** whoever designs or builds this loads the `apple-design` skill (and `emil-design-eng`) first and
  follows its guidelines; no work on it starts without them. Also `docs/hub-design-language.md`.
- **Bar:** the best UX and an extremely intuitive UI. A new pattern is added centrally (block + gallery + doc), and before/after visuals
  are shown before it is applied.

## 20. Sync page offers the last run's tracks again after a finished sync (bug, 2026-10-23)

When a sync has finished and nothing is left to sync, the Sync page still offers to sync the last run's tracks, even
though they are fully synced. It shows "all complete" only after another Spotify read. Expected: right after the run
finishes, the page shows that everything is synced. Check first: whether the page's plan comes from the Spotify read
taken before the run and is not worked out again from the library once the run finishes.

## 16. Live check: the installed app (phase 7, spec public-release §11)

Mark the .dmg as downloaded first (`xattr -w com.apple.quarantine "0081;$(printf %x $(date +%s));Safari;"
dist/Discjockey-<version>.dmg`; a file built on this Mac carries no quarantine mark and opens without "Open Anyway"),
or install from the phase 6 draft release, so the README's Open Anyway steps are checked too. Needs a human:
install from `dist/Discjockey-<version>.dmg` (drag to Applications, "Open Anyway"); the window opens
with the music folder, every page reads; one sync; one Chrome login prompt answered "Always Allow"; then build again,
install over it, and the keychain grant is still there. Phase 7 moves the user's own setup across first.
A built app's window has not been seen with a screenshot yet (screen capture was blocked): look at it first.
Also look at the sidebar update line in the real window (phase 5): it was never seen on screen, only its pieces. Start
a scratch window with `DISCJOCKEY_SUPPORT=<scratch folder>` holding a `config.json` and a `cache/app_update.json`
with `"version": "9.9.0"` and a fresh `checked_at`: under the brand it must say "Discjockey 9.9 is available" in two
even lines, and the link opens the release page. (Checked live without a screen: the window keeps its page-server
port across restarts, moves off a port another program holds, and a second window gets its own port.)

## 14. Folder field: a small gap before the last path part when a long path is cut (2026-10-23)

- **Cosmetic.** When a long path is shortened (`~/M… /Discjockey`) a small gap shows before the last part. One CSS
  change did not close it.

## 12. Old runtime files in the checkout (2026-10-23)

- **They stay after the move to the music folder and the support folder:** `state.json`, `settings.json`, `reports/`,
  `not_lossless.md`, `.spotify_*.json`, `.streamrip/` and `.cache/` in the maintainer's checkout. Nothing reads them
  now. Delete them only when the user says so.

## 11. Live check: signing in from Settings (Settings/Setup redesign, 2026-10-22)

- **Not tried in the real window yet** (the user couldn't test before the merge). Restart the app, open Settings and
  sign in to YouTube and SoundCloud both ways: a login found in Chrome → **Use this login**, and **Sign in** → the
  browser opens → Discjockey notices the login by itself. Also one Qobuz **Check again**.

## 9. Engine: a crashed sync leaves no note in `reports/` (from the Task 10B review, 2026-10-21)

- **A crash writes nothing the user can open.** `discjockey/hub/jobs.py` (around line 349) only prints the traceback to
  the terminal, so a sync that crashes before its RunFinished has no report. The end screen's crash card then has no
  Open report, and Show reports folder was dropped from it (it opened older runs only).
- **Fix at the root:** the engine writes a short crash note into `reports/` (when, the step it was on, the error in
  plain words, that the state is saved) and files it as the run's report, so the card's own "Open report" has
  something to open. Contract: `JobFinished` for a crash then carries the report like a finished run.

## 7. Live check: bought file by drag and drop (was hub plan Task 74; needs a bought WAV, AIFF or FLAC)

- **Sync: "Later" ignores the panel's scope (from the 9B review, M8).** In `sync-scope` the DayBar's "Later 185"
  counts downloads in playlists the user turned off, next to "All 77" (`runTotals.after` counts the whole plan).
  Question for the user: should Later count only what's in scope?
- **Sync: loose sentence under the list (Task 9C, from the 9B review M8).** `sync-many-all-off`'s "232 more tracks
  left out: playlists or kinds you turned off on the right." sits outside any container (§4); make it a `Hint` or
  `NoteCard` in 9C.

When the user has bought a track: drag the file from Downloads, and once from the Desktop, onto the To-do drop zone
(highlight while dragging, the file lands in Library as "Artist - Title.aiff", the to-do row goes away). Problems
become their own fix.

## 6. Live check: one upgrade swap in rekordbox (was hub plan Task 75; needs a ready upgrade)

When a sync parks an upgrade (To-do chip "upgrade ready"): run the swap from the hub, then check in rekordbox that cue
points and beatgrid are still in place. If no upgrade turns up for a long time, add a way to park a chosen candidate
as an upgrade (hub spec §9).

## 4. Contract gaps G3 and G5 (minor, from the hub plan)

- **G3 — no waveform data for the Library mini player.** Derived from the spectrum matrix (mean per column), which is
  an approximation. A `waveform` field (peak per column) in `spectrum()` would be exact.
- **G5 — no estimate for a partial selection.** `sync_preview().estimate` covers the whole plan; when the user
  unticks actions the page recomputes with the hub spec §6.9 formula, so the formula exists twice. Better:
  `sync_estimate(selected)`.
