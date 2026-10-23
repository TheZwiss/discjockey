# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 23. Sync page repeats views.split for a partial selection (minor, 2026-10-23)

Left over from the old contract gap G5: the time for a ticked subset now comes from the engine's table
(`estimate.minutes_by_downloads`), but `serviceRows` in `hub-ui/src/pages/sync/planModel.ts` still recomputes
`views.split` (which service the ticked downloads use) on the client. Same fix shape: the engine sends what the client
needs once (for example `uses` per account for every count), and the client looks it up.
