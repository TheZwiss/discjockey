# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 20. Sync page offers the last run's tracks again after a finished sync (bug, 2026-10-23)

When a sync has finished and nothing is left to sync, the Sync page still offers to sync the last run's tracks, even
though they are fully synced. It shows "all complete" only after another Spotify read. Expected: right after the run
finishes, the page shows that everything is synced. Check first: whether the page's plan comes from the Spotify read
taken before the run and is not worked out again from the library once the run finishes.

## 14. Folder field: a small gap before the last path part when a long path is cut (2026-10-23)

- **Cosmetic.** When a long path is shortened (`~/M… /Discjockey`) a small gap shows before the last part. One CSS
  change did not close it.

## 9. Engine: a crashed sync leaves no note in `reports/` (from the Task 10B review, 2026-10-21)

- **A crash writes nothing the user can open.** `discjockey/hub/jobs.py` (around line 349) only prints the traceback to
  the terminal, so a sync that crashes before its RunFinished has no report. The end screen's crash card then has no
  Open report, and Show reports folder was dropped from it (it opened older runs only).
- **Fix at the root:** the engine writes a short crash note into `reports/` (when, the step it was on, the error in
  plain words, that the state is saved) and files it as the run's report, so the card's own "Open report" has
  something to open. Contract: `JobFinished` for a crash then carries the report like a finished run.

## 7. Sync page: two leftovers from the 9B review (M8)

- **"Later" ignores the panel's scope.** In `sync-scope` the DayBar's "Later 185" counts downloads in playlists the
  user turned off, next to "All 77" (`runTotals.after` counts the whole plan). Question for the user: should Later
  count only what's in scope?
- **Loose sentence under the list.** `sync-many-all-off`'s "232 more tracks left out: playlists or kinds you turned
  off on the right." sits outside any container (§4); make it a `Hint` or `NoteCard`.

## 4. Contract gaps G3 and G5 (minor, from the hub plan)

- **G3 — no waveform data for the Library mini player.** Derived from the spectrum matrix (mean per column), which is
  an approximation. A `waveform` field (peak per column) in `spectrum()` would be exact.
- **G5 — no estimate for a partial selection.** `sync_preview().estimate` covers the whole plan; when the user
  unticks actions the page recomputes with the hub spec §6.9 formula, so the formula exists twice. Better:
  `sync_estimate(selected)`.
