# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 23. Sync page repeats views.split for a partial selection (minor, 2026-10-23)

Left over from the old contract gap G5: the time for a ticked subset now comes from the engine's table
(`estimate.minutes_by_downloads`), but `serviceRows` in `hub-ui/src/pages/sync/planModel.ts` still recomputes
`views.split` (which service the ticked downloads use) on the client. Same fix shape: the engine sends what the client
needs once (for example `uses` per account for every count), and the client looks it up.

## 14. Folder field: a small gap before the last path part when a long path is cut (2026-10-23)

- **Cosmetic.** When a long path is shortened (`~/M… /Discjockey`) a small gap shows before the last part. One CSS
  change did not close it.

## 7. Sync page: two leftovers from the 9B review (M8)

- **"Later" ignores the panel's scope.** In `sync-scope` the DayBar's "Later 185" counts downloads in playlists the
  user turned off, next to "All 77" (`runTotals.after` counts the whole plan). Question for the user: should Later
  count only what's in scope?
- **Loose sentence under the list.** `sync-many-all-off`'s "232 more tracks left out: playlists or kinds you turned
  off on the right." sits outside any container (§4); make it a `Hint` or `NoteCard`.
