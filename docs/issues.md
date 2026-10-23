# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 23. Sync page repeats views.split for a partial selection (minor, 2026-10-23)

Left over from the old contract gap G5: the time for a ticked subset now comes from the engine's table
(`estimate.minutes_by_downloads`), but `serviceRows` in `hub-ui/src/pages/sync/planModel.ts` still recomputes
`views.split` (which service the ticked downloads use) on the client. Same fix shape: the engine sends what the client
needs once (for example `uses` per account for every count), and the client looks it up.

## 20. Sync page offers the last run's tracks again after a finished sync (bug, 2026-10-23)

When a sync has finished and nothing is left to sync, the Sync page still offers to sync the last run's tracks, even
though they are fully synced. It shows "all complete" only after another Spotify read. Expected: right after the run
finishes, the page shows that everything is synced. Check first: whether the page's plan comes from the Spotify read
taken before the run and is not worked out again from the library once the run finishes.

## 9. Engine: a crashed sync leaves no note in `reports/` (from the Task 10B review, 2026-10-21)

- **A crash writes nothing the user can open.** `discjockey/hub/jobs.py` (around line 349) only prints the traceback to
  the terminal, so a sync that crashes before its RunFinished has no report. The end screen's crash card then has no
  Open report, and Show reports folder was dropped from it (it opened older runs only).
- **Fix at the root:** the engine writes a short crash note into `reports/` (when, the step it was on, the error in
  plain words, that the state is saved) and files it as the run's report, so the card's own "Open report" has
  something to open. Contract: `JobFinished` for a crash then carries the report like a finished run.
