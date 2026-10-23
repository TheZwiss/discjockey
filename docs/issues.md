# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

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

Done 2026-10-23: v1.0.0 installed from the release, Open Anyway walked through (README screenshots), the window opens
on the music folder (now `~/Music/Discjockey`). Left:

- **One sync** in the installed app.
- **The sidebar update line** has never been seen on screen: it shows once a version after 1.0.0 is released (or with a
  scratch `DISCJOCKEY_SUPPORT` whose `cache/app_update.json` says `"version": "9.9.0"` with a fresh `checked_at`).
- **Keychain "Always Allow"** only comes up when a YouTube or SoundCloud login is read from Chrome; check it then.

## 14. Folder field: a small gap before the last path part when a long path is cut (2026-10-23)

- **Cosmetic.** When a long path is shortened (`~/M… /Discjockey`) a small gap shows before the last part. One CSS
  change did not close it.

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
