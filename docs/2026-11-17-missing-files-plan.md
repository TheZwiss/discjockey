# Missing files wait and come back (issue 43): plan

Status: plan, 2026-11-17. Issue: `docs/issues.md` entry 43 (the user's decision of 2026-11-17 is binding). Changes
spec `docs/2026-10-23-library-and-sources-design.md` §6.3 (Gone) and §6.4, and answers issue 40's audit point "out of
every watched folder". Branch `feat/missing-files` from `main` (9168609b); group worktrees
`.claude/worktrees/mf-<group>` on `feat/missing-files-<group>`, each merged into the stage branch when its checks are
green. No mockup: one new To-do group built from the existing To-do blocks (§7 names them).

**In one line:** a file that one scan doesn't see is never decided: its row waits as missing with everything its song
has, a file with its content key anywhere in the watched folders links back to it, To-do lists the missing songs with
where they were, and only the user's word removes an own song ("Remove from library") or downloads a playlist song
again ("Download again"), for one song, a selection or all, from the window or a command.

**Not in this plan:** rekordbox following Discjockey's own moves (issue 40, stage E); any repoint of rekordbox for a
file that comes back (it comes back under its own name, so rekordbox's Relocate finds it as today); recovering songs a
v1.2.1 scan already deleted (§1.4); words for people updating from an older version.

---

## 0. Decisions (with reasons)

1. **"Missing" is its own column, `files.missing_since`** (schema 11, ISO seconds of the first scan that read the
   file's folder and didn't find the file; NULL: found at the last scan that read its folder). Not a reuse of `held`.
   Reason: `held` today means two things ("missing, but a move couldn't be ruled out" from the scanner, and "its audio
   changed and couldn't be judged" from `library.scan_library`), and the second one is a file that is there. One
   column per meaning, and the date is what To-do shows.
2. **`held` keeps only its second meaning**: the file is at its path, its audio changed outside Discjockey and the
   sound check failed; its song is left alone until it can be judged. The scanner stops producing `held`; its field in
   `ScanResult` is renamed `unjudged` (only `scan_library` fills it). The column keeps its name (the snapshot key
   `held` is read in many places and still means "leave this song alone"). Reason: with nothing ever decided by one
   scan, "held until a later scan decides" is the same as missing; the failed-judgment case is not about presence.
3. **Only linked rows wait.** A row linked to no song (an indexed file nobody's song has: "Also in this folder", a
   copy, a file the import hasn't read yet) whose file is not there is still deleted (`ScanResult.gone`): nothing of
   any song is lost, and a returning file is simply indexed again. Reason: the user's rule is about songs; keeping
   rows for nobody's files would grow the index without bound.
4. **A missing row is relinked by its content key wherever it shows up**, by the rules the scanner already has for a
   move (one candidate: Moved; two or more: ambiguous), every scan for as long as it waits. Its own path counts: a row
   whose file is back at its path is simply present again. Relinking takes the row's song back as it was: same
   `files.id`, same song id and key, parked upgrade, answers, checks, playlists, history.
5. **An ambiguous row is missing too** (its file is not at its path; `missing_since` is set) and To-do lists it in the
   Missing files group, saying it is in several places (§5.2). Reason: today an ambiguous own song is listed nowhere
   (Other lists only the planner's playlist songs); one group for "your file isn't where it was" covers both.
6. **`songs.file_gone` now means "the user asked for this song to be downloaded again"**: set only by Download again
   (§4.1) and by `folder remove` (D12, unchanged: the user's word). The scanner never sets it. It is cleared when the
   song's file is back (a relink, §2.3) or a new file is placed (`apply_outcome`, as today).
7. **Download again keeps the row until the download replaces it.** It sets `file_gone` and nothing else; the next
   sync downloads the song; the placed file takes over the same `files.id` (`db._save_files` moves the song's own row
   to the new place). Reason: until the sync, the file can still come back and relink (the download is then dropped
   from the plan), so Download again loses nothing, needs no undo and no confirm.
8. **Download again that finds nothing leaves the song waiting.** A redownload whose outcome is "not found" keeps
   the entry's file fields (its missing row stays), clears `file_gone` and keeps the parked upgrade; the song is back
   in Missing files with Download again offered. "Queued" (limit reached) keeps `file_gone` (tried at the next sync).
   Reason: today's "not found" outcome deletes the row (`test_missing_deletes_the_row_of_a_file_that_is_gone`), which
   would forget the content key the user may still bring back.
9. **A redownload that is placed lets a parked upgrade go, as any new file does today** (`apply_outcome` clears
   `upgrade`, the executor deletes the parked file in `Upgrades ready/`). Reason: the download runs the whole source
   hierarchy again, so it gets the best version there is (usually the very one that was parked); the weekly upgrade
   check looks again. The dry run and the panel say so for a song that has one (§5.3).
10. **Remove from library is final, with a confirm, no undo.** It deletes the own song's records exactly as a scan
    does today (its missing file row, the song, its aliases, the answers naming it) and deletes its parked upgrade's
    file in `Upgrades ready/` (Discjockey's own download, nobody's after the song goes). Reason for no undo: the file is
    not there, so nothing on disk changes; the answers and the parked version are what the confirm warns about; an
    undo would have to restore rows that later scans and imports may already contradict. Same as `folder remove`
    (`--yes`, no undo).
11. **The action follows the song, not a choice**: a song in a playlist (`in_playlists = 1`, an own key linked to a
    playlist song included) gets Download again; any other song (own, or a playlist song no playlist lists any more)
    gets Remove from library. A playlist song gets no Remove: the next sync would add it again as a new song and
    download it, which is Download again with its history lost.
12. **The planner leaves a missing row's song alone**, like an offline one: it is satisfied, gets no upgrade check, no
    question, no duplicate group, no tidy-up move, no AIFF step. Two exceptions, both the user's doing: `file_gone`
    (Download again) plans `acquire` reason `redownload`; a bought file under the expected name in its Library folder
    is adopted (rule 2's `adopt_bought`, as for a song with no file). The "vanished since the scan" branch
    (`planner.py`, `fold(e["path"]) not in on_disk`) waits instead of downloading.
13. **Missing files is a To-do group of its own, second in the order** (after Check in rekordbox): it holds own songs
    too (D8 gains this one exception) and wins over every other group a song could be in except Check in rekordbox
    (which lists every open check, as today). Reason: nothing else can be done with a song whose file isn't there;
    Upgrade ready, the CDJ group and Not found would offer actions that can't run.
14. **The window computes nothing**: each item carries its `missing` view (action, why not, words), the group its
    counts; the commands' `--all` and the window's head link read the same answer (`select`).

## 1. Storage (group E1)

### 1.1 Schema 11

`SCHEMA_V11_STEP = ("ALTER TABLE files ADD COLUMN missing_since TEXT",)`, `SCHEMA_VERSION = 11`, `UPGRADES[10]`. No
index (a handful of rows ever carry it). The comment block above the step says D1, D2 and D6 in two lines each. The
`held` comment in `SCHEMA_V1` (comments only, harmless for old files) is rewritten to D2's meaning, and `file_gone`
gets D6's.

### 1.2 Rows and snapshot

- `KnownFile` gains `missing: bool` (`missing_since IS NOT NULL`); `db.known_files` selects it.
- `_FILE_COLUMNS` and the entry gain `missing_since` (str | None), read-only (`READ_ONLY`), `None` for a song without
  a file (`_entry`'s no-file branch). `planner.MERGED_FIELDS` gains it next to `held`.
- `snapshot()["files"]` leaves out missing rows: `online and not held and missing_since is None`.
- `_save_files`: both `UPDATE`s that set `held = 0` also set `missing_since = NULL` (a save that places a file at a
  row's place means the file is there; this is how a redownload's placed file clears the mark, D7).
- The queries that take only files that are there add `AND f.missing_since IS NULL` beside `held = 0`:
  `import_unjudged`, `files_without_facts`, `duplicate_groups`, `group_files`; `import_waiting` and `import_left` read
  unlinked rows, which are never missing (D3): no change, the reviewer checks it.

### 1.3 Helpers every consumer uses

- `models.file_missing(e: Mapping) -> bool`: `bool(e.get("missing_since"))`. One name for the check, so a grep finds
  every consumer. (Not on `views`: planner, tidy, cdj and batches import `models` already.)
- `words.short_day(d: date, today: date) -> str`: "12 Nov" in `today`'s year, "12 Nov 2025" otherwise (English month
  abbreviations, no locale). Check first: no engine day formatter exists yet (grep `words.py`, `views.py`); if one
  does, use it.

### 1.4 What a v1.2.1 library already has

- Rows with `held = 1`: left as they are by the upgrade; the first scan sorts them (missing, or held again for a
  failed judgment, §2.2). Nothing reads them in between that matters: the window's opening scan and every sync scan
  first.
- Songs a v1.2.1 scan already deleted (own songs, their answers, their parked upgrades): gone; nothing remembers their
  content key, so nothing can link them. Not recovered.
- Playlist songs a v1.2.1 scan marked `file_gone` (their row is deleted): left as they are; the next sync downloads
  them, as v1.2.1 would have. Reason: there is no row to wait with and no key to relink; a playlist song without a
  file is downloaded at its retry anyway (rule 2, `reason="retry"`), so clearing the mark would only delay it.

## 2. The scan (group E1)

### 2.1 What the scanner decides (`scanner.py`, `ScanResult`)

| Case | Today | Now |
|---|---|---|
| Linked row, file at its path (unchanged / retagged / replaced) | present | present; `back` when it was missing |
| Linked row, path gone, its key in exactly one new file or indexed unlinked row | `moved` | `moved`; `back` when it was missing |
| Linked row, path gone, key in two or more | `ambiguous` | `ambiguous` (and marked missing, D5) |
| Linked row, path gone, nothing has its key | `gone` (row deleted, song loses its file) | `missing` |
| Linked row, path gone, walk couldn't see everything (unlisted subfolder, unreadable file of its size) | `held` | `missing` (the size rule and `hold_if_gone` go) |
| Linked row under a subfolder that couldn't be listed | kept, unchanged | kept as it was: present stays present, missing stays `missing` (from `KnownFile.missing`) |
| Unlinked row (not ambiguous), path gone | `gone` | `gone` (deleted, D3) |
| Row in an offline folder (whole folder, inner watched folder) | kept, `offline` | the same; `missing_since` untouched |
| Migrated row without a key, one same-named file | `moved` | the same; nothing found: `missing` |
| New file whose key a present row has | `copies` | the same |

`ScanResult` fields after the change: `offline`, `unchanged`, `retagged`, `replaced`, `moved`, `ambiguous`, `new`,
`copies`, `gone` (unlinked row ids), `missing` (linked row ids that wait, those missing before included), `back` (row
ids that were missing and are seen again: present at their path, retagged, replaced or moved), `unjudged` (was `held`;
`scan_library` only), `unreadable`, `unopenable`. The docstring states the rules of the table.

`_reconcile`'s `decide()` keeps its candidate rules (an unlinked row never takes an indexed copy; a linked or
ambiguous one does; a song's file wins a shared target) and ends in `missing` for a linked row with no candidate,
`gone` for an unlinked one. A missing row is in `_Sorting.missing` at every scan for as long as its path stays empty,
so it is matched again each time: that is the relink across scans (repro of issue 43).

### 2.2 What `apply_scan` writes (`db.py`)

In the one transaction, after today's online/offline and `held` handling (`held` is now cleared for rows of online
folders not in `unjudged`, as today with the new name):

- `missing` and `ambiguous` ids: `missing_since = COALESCE(missing_since, <scan stamp>)` (the first scan that missed
  it stays the date).
- `back` ids: `missing_since = NULL`, and the song's `file_gone = NULL` (a file that came back cancels a Download
  again the sync hasn't done yet, D6). `moved` writes its new place as today.
- `gone` ids: deleted, then `_drop_dead_decisions` (a keep_both group with an indexed file). **A `gone` id whose row
  is linked is marked missing instead, never deleted** (defence: the scanner never sends one; a test pins it).
- `_drop_fileless_own` is no longer called from `apply_scan` (still from `remove_watched_folder`), and the `file_gone`
  update leaves `apply_scan`.
- The docstring is rewritten to these rules.

### 2.3 `library.scan_library`: summary and words

- Failed judgments go into `result.unjudged` (was `held`).
- `ScanSummary` gains `missing` (rows newly missing at this scan: in `result.missing` and not `KnownFile.missing`
  before; an ambiguous row is not counted, as today) and `back` (`len(result.back)`); `gone` stays (unlinked rows dropped).
- Words (`SCAN_PARTS`, in this order): moved "file you moved" / "files you moved", new "new file" / "new files",
  back "missing file back" / "missing files back", missing "file missing" / "files missing", replaced "file changed"
  / "files changed". `gone` is no longer worded (an index row of nobody's file; the count stays in the summary and
  `--json`). When `missing > 0` the message adds a second sentence: "Missing files wait in To-do." Example:
  "Checked your Library: 1 file missing. Missing files wait in To-do."
- `HubApi.rescan_library`'s result and `library scan --json`: `{moved, new, gone, missing, back, changed, copies}`.
- A moved row that was missing counts as `back`, not `moved`.

## 3. Every consumer of a missing file (groups E2 and E3a)

Each row: where, the rule, the reason. "Left alone" means as an offline file today.

| Consumer | Rule for a song whose file row is missing |
|---|---|
| `planner.plan` rule 2/3 (`planner.py` ~l.495–515) | Before the `online` check: `if file_missing(e)`: a bought file under the expected name in `Library/<folder>` → `adopt_bought`; elif `file_gone` → `acquire` reason `redownload`; else nothing (satisfied). D12 |
| `planner.plan` "vanished since the scan" (`fold(e["path"]) not in on_disk`) | `continue` (wait; the next scan marks it), no `redownload`. D12 |
| `planner._Own.free` / `askable` | not free (no question, no duplicate group, no merge into a playlist song) |
| `planner._own_check_due` | not due (no upgrade check while missing) |
| `planner.tidy_rows` | skip `not_found` (as `held`) |
| `tidy._file_undo_skip` | `moved_on` (as `held`) |
| `apply_outcome` + `execute._acquire` for reason `redownload` | placed: as today (the row moves, D7, D9); `missing` outcome on an entry with a missing row: keep the file fields and the parked upgrade, clear `file_gone`, set `last_attempt` (D8; no `_drop_stale_upgrade`); queued/errored: as today. Check first: `apply_outcome`'s `missing` branch is the one place that clears `path`; the executor's three `_drop_stale_upgrade` calls |
| `views._group` | `missing_file` first (D13); `None` once `file_gone` is set (Download again: it leaves To-do, the Sync page lists it under "Download again") |
| `views.todo_listed` | an own or unlisted song is listed when its file is missing (D8's new exception) |
| `views.upgrade_ready_keys` (Upgrade all, `upgrade list`, Auto-upgrade's set) | left out (follows from `_group`); the parked upgrade stays |
| `cdj.group_members` (CDJ group, `aiff_plan` scope `cdj`) | not a member |
| `views.file_state` | `"file_missing"` after the offline checks (offline wins: its drive isn't there to tell). The stored mark, no disk I/O; Library rows and To-do items now carry it (contract, §6.3) |
| `views.next_due` / `next_check` | `"next_sync"` when `file_gone` is set (the Library row of a song after Download again says it is downloaded at the next sync) |
| `views._group` for `status == "missing"` and `file_gone` (no file row: after `folder remove`) | `None`: the sync downloads it; not listed as Not found ("nothing usable anywhere" is not true of it); the Library row's `wait` is `waiting` |
| `batches.present`, `eligible` (Same track, Convert, Rename, the AIFF plan's `waiting`) | unchanged: a live disk check answers `missing` → skip `file_missing`. Tests pin it for a missing row |
| `db.duplicate_groups` / `group_files`, `import_unjudged`, `files_without_facts` | left out (§1.2) |
| rekordbox steps, AIFF batches | unchanged (they go through `eligible`) |
| `folder remove` | unchanged: deletes the folder's rows, missing ones included; playlist songs losing their only file get `file_gone`, own songs go. The user's word (D6) |
| Sync preview (`report.py` group words) | `acquire:redownload` → "Download again (its file is missing)"; report section `redownloaded` → "Downloaded again (its file was missing)" |
| Dashboard, sidebar | through To-do's count (`chips.all`); nothing of their own |

Every row gets a test: the `views` rows (`_group`, `todo_listed`, `upgrade_ready_keys`, `file_state`, `next_due`)
in E3a, because they change the bridge's shapes (contract rule); every other row in E2 (§9.2).

## 4. The two actions (`discjockey/missing.py`; rules in E3a, writes in E3b)

One new module holds the issue's rules, so the views, the hub and the commands ask one place.

### 4.1 Rules (pure, E3a)

- `ACTIONS = ("download_again", "remove")`.
- `action_for(key, e) -> str`: `download_again` when `e["in_playlists"]`, else `remove` (D11).
- `why_not(key, e, state, action) -> str | None`, the first that applies, else None:
  `not_missing` (its file is back, or it has no file row), `wrong_action` (the other action is this song's),
  `found_twice` (`key in state["ambiguous"]`; Download again only: Remove may still run for an own song),
  `never` (`key in state["never"]`; Download again only), `check_open` (an open `rekordbox_check`; Remove only: its
  undo store would be left behind), `asked` (`file_gone` already set; Download again only).
- `REASONS: dict[str, str]`, the words (§5.4). They join `views`' reason words the way `eligible.REASONS` do; check
  first: whether the CLI's `partial`/`skipped` rows take reason words from a shared table (`hub/outcomes.py`), and
  register them there too.
- `view(key, e, state, place, today) -> dict | None`: the `missing` object of §5.2, None when the file isn't missing.

### 4.2 Download again (E3b)

`download_again(paths, keys, *, now) -> list[ItemResult]` under the caller's library lock: opens the state fresh,
re-checks `why_not` per song (a song that changed since the click is `skipped` with its reason, never switched),
sets `file_gone = now.date().isoformat()` on the rest, saves (`library.save_state`; one save for all), logs
`ops.log_operation(..., "download again", "done", "downloaded again at the next sync")` per song. Nothing else
changes: the row, the parked upgrade and every answer stay until the sync places a file (D7).

### 4.3 Remove from library (E3b)

`remove(paths, keys, *, now) -> list[ItemResult]` under the caller's library lock: fresh state, `why_not` per song,
then for the rest: pop the entries from `state["tracks"]` and save once. `db.save` already does the rest in one
transaction: `_save_files` deletes the released row whose file isn't there, the song row and its aliases go, and
`_drop_dead_decisions` drops the answers naming it. After the save commits, `library.delete_parked` for each removed
song's `upgrade["file"]` (after, so a crash leaves at worst an orphan file in `Upgrades ready/`, never a record
pointing at a deleted file). Log `"removed from library"` per song. Check first: that removing an entry whose row
`facts()` can't find takes `_save_files`' delete branch (it does today for `removed` songs: `released.update(...)`),
and that Favourites drop a key no song has (`views` leaves a gone key out today: `test_favourites_resolve_...`).

### 4.4 The dry run (E3b)

`preview(state, keys, action, place, today) -> dict`: `{action, items: [{track_id, artist, title, place, since,
will: bool, reason: str | null, words: str | null, upgrade_waiting: bool}], n, skipped, words}`. `n` counts `will`;
`words` is the one line a command prints ("2 songs download again at your next sync; 1 is skipped." / "Removes 1
song from your library."); `upgrade_waiting` marks a song whose parked version Download again lets go (D9) or Remove
deletes (D10). Read-only, no lock beyond the hub's read.

`ItemResult` is `batches.ItemResult`'s shape (`track_id`, `action`, `state` `done | skipped`, `reason`, `words`), so
the CLI's partial rule (`UPGRADE_PARTIAL`-like `("skipped",)`) and the result tables need nothing new. Check first:
whether reusing `batches.ItemResult` drags batch-only fields; if it does, a two-line dataclass of the same names in
`missing.py`.

## 5. What the views send (group E3a)

### 5.1 The To-do group

`TODO_GROUPS` gains, second: `("missing_file", "Missing files", "not where they were; put a file back and it links
again")`. Key `missing_file` (not `missing`: that word is the quality class of a song with no file). `views.todo`
takes `place: Callable[[str], str] | None` (the api passes `Sites.place`, as `track_detail` gets its `place`) and
puts every listed song whose `_group` is `missing_file` there, hidden ones as any item. The group carries
`all: {download_again: n, remove: m}`: items not hidden whose `missing.why_not` is null, by action (what the head link
and `--all` act on). The filter word `missing_file` joins `todo(filter=…)`'s list and `TodoFilter`.

### 5.2 An item

A `TodoItem` (`track_row` fields, `group: "missing_file"`, `file_state` as §3 says: `file_missing`, or `offline`
when its drive is away) plus:

- `detail`: "Missing since 12 Nov · was in Techno 2019" (`words.short_day` of `missing_since`; `place` of the row's
  path: the Folder column's words). An ambiguous one: "In 2 places now · keep one and it links again".
- `missing: {since: ISO date, place: str, action: "download_again" | "remove", why_not: str | null, words: str |
  null, upgrade_waiting: bool}` (`missing.view`); `words` is the reason's words when `why_not` is set.

### 5.3 The track's details (`views.track_detail`, the To-do and Library panels, `track show`)

`TrackDetail` gains `missing: MissingDetail | null`: the item's `missing` fields plus `line` and `hint`:

- `line`: "Not seen since 12 Nov. It was in Techno 2019." (ambiguous: "Found in 2 places: Techno 2019 and
  Old crates.").
- `hint`, by action: Download again: "Put the file back in any watched folder and it links again with everything it
  had. Or download it again at your next sync." Remove: "Put the file back in any watched folder and it links again
  with everything it had. Or remove the song from your library." Ambiguous: "Delete or move away the copies you
  don't want; the one left links again."
- With `upgrade_waiting`, `hint` adds: "Its better version waiting in Upgrade ready goes with it."

### 5.4 Words (binding)

| Where | Words |
|---|---|
| Group label / hint | "Missing files" / "not where they were; put a file back and it links again" |
| Row detail | "Missing since {day} · was in {place}"; ambiguous "In {n} places now · keep one and it links again" |
| AwayTag on a row (window `FILE_STATE_TAG.file_missing`) | "Missing" (was "File not found") |
| Buttons | "Download again"; "Remove from library…" (the dots: it asks first) |
| Selection panel buttons | "Download again · {n}"; "Remove from library · {m}…" |
| Group head link | "Select all · {n}" (selects the group; the selection panel acts) |
| Confirm (Remove) | title "Remove from your library?" (several: "Remove {m} songs from your library?"); body "Their files aren't in your watched folders. Discjockey forgets these songs, your answers about them and any better version waiting for them. If a file comes back later, it is added as a new song."; button "Remove", tone danger |
| `CONFIRM["missing remove"]` (command line) | the confirm's body, one line |
| Result words | "{n} song(s) download again at your next sync." / "Removed {n} song(s) from your library."; skipped ones add "{k} skipped: see why." |
| Reasons | `not_missing` "Its file is back."; `wrong_action` "This song gets {the other action} instead."; `found_twice` "Its file is in several places now: keep one and it links again."; `never` "You chose Never download for it."; `check_open` "Its rekordbox check is still open: finish it first."; `asked` "It downloads again at your next sync already." |
| Scan message | §2.3 |
| Sync preview / report | §3 last rows |

### 5.5 Library rows

`file_state` `file_missing` (from the stored mark) is now a value of `LibraryRow.file_state` and `TodoItem.file_state`
(today both exclude it). Nothing else changes in the Library: its panel shows `track.missing` (§7.3); actions stay in
To-do.

## 6. Bridge, commands, catalogue (E3a: reads; E3b: writes and commands)

### 6.1 Hub methods (`discjockey/hub/api.py`)

| Method | Kind | Answer |
|---|---|---|
| `todo(filter, show_hidden)` (changed, E3a) | read | the `missing_file` group (§5.1), items with `missing` |
| `track(track_id)` (changed, E3a) | read | `missing` (§5.3) |
| `library(...)` (changed, E3a) | read | rows may say `file_state: "file_missing"` |
| `rescan_library()` (changed, E1) | job `scan` | result gains `missing`, `back` (§2.3) |
| `missing_files_preview(track_ids: list[str], action: str)` (new, E3b) | read, in `LIBRARY_METHODS` | §4.4; an unknown action is `bad_args`; an unknown song as `_track_list` refuses today |
| `missing_files(track_ids: list[str], action: str)` (new, E3b) | write job, kind `missing_files`, `replanned_work` (the Sync page shows the planned download at once) | `{job_id}`; `JobFinished.result`: `{action, results: [ItemResult], done: [keys], skipped: [keys], words}`; every song skipped → `OpProblem(..., "changed")` with the results kept (`ctx.failed_result`, as `rekordbox_checked` does) |

Mirrors `upgrade` / `upgrade_preview` (one method, `action` names the verb), so the catalogue's `fixed` works as for
`upgrade discard`. Busy, console and sync-running answers as every write method. `remove` deletes no music file
(it is missing); the one deletion is the parked download (D10).

### 6.2 Commands (`discjockey/hub/catalog.py`, `select.py`, CLI)

| Command | Entry | Notes |
|---|---|---|
| `missing list [--hidden]` | `todo`, kind R, `fixed={"filter": "missing_file"}`, `locks={"rekordbox_r"}` | as `upgrade list` / `check list` |
| `missing download <track…> \| --all [--dry-run]` | `missing_files`, kind J, `fixed={"action": "download_again"}`, `dry_run="missing_files_preview"`, `locks={"library"}`, `partial=("skipped",)` | no `--yes`: nothing is lost (D7) |
| `missing remove <track…> \| --all [--dry-run] --yes` | `missing_files`, kind J, `fixed={"action": "remove"}`, `needs_yes=True`, `dry_run=…`, `locks={"library"}`, `partial=("skipped",)` | `CONFIRM["missing remove"]` |

- `select.py`: `DOWNLOAD_AGAIN = "download_again"`, `REMOVE_MISSING = "remove_missing"` join `VERB_ALL`;
  `download_again_ids(answer)` / `remove_missing_ids(answer)`: the `missing_file` group's items whose
  `missing.action` is the verb's and `missing.why_not` is null, from To-do's answer without hidden songs (as
  `upgrade_all_ids`). `catalog.ALL_OF` gains `"missing download"` and `"missing remove"`. The window's head link and
  `--all` read the same group, so they act on the same songs.
- `<track>` takes what `TRACKS` takes today (a path, a key). Check first: `HubApi._resolve_track` finds a song by the
  path of a missing row (it reads `files.path`, so it should); a test pins `missing download "<old path>"`.
- Human output: `missing list` renders through `cli/render/todo.py` (generic group table: check that `missing`'s
  nested object shows as its `words`/`since`/`place` columns, not as a raw dict; add the three to the item columns if
  not). The writes print the result table and `words` like `upgrade discard`.
- `--json`: the envelope of every command; `data` is the method's answer.
- `help --json`, the agent reference and `tests/test_hub_catalog.py` (T1) pick the entries up from the catalogue;
  `CONTRIBUTING.md` > "Commands for scripts and agents" gains the three lines (E3b).
- `tests/test_cli_locks.py` (T10): the two write entries take `library`; the list takes `rekordbox_r` as `todo`.

### 6.3 Contract and fake (same commit as the shapes, CLAUDE.md "Contract")

- `docs/hub-bridge-contract.md`: `todo()`'s filter list and a "Missing files (issue 43)" section: the group, the
  item's `missing`, `all`; `track()`'s `missing`; `file_state` on rows; `rescan_library`'s result; the two new
  methods with their shapes and problem kinds. E3a writes the read shapes, E3b the methods.
- `hub-ui/src/lib/bridge/types.ts` + `contract.ts`: `TodoGroupKey` / `TodoFilter` gain `missing_file`;
  `MissingView`, `MissingDetail`, `MissingAction`, `MissingPreview`, `MissingResult`; `TodoItem.missing?`,
  `TrackDetail.missing`; `LibraryRow.file_state` and `TodoItem.file_state` become `FileState | 'no_file'`.
- Fake backend: scenario `missing_files`: three missing songs (a playlist song, an own song with a parked upgrade, a
  playlist song found in two places), one hidden playlist song, a Library row of each; `missing_files` and
  `missing_files_preview` answer from the scenario's state and remove/mark items the way the engine does (the fake's
  existing upgrade/discard handlers are the model). Every existing scenario's `todo()` stays valid (`missing` absent).
  `npx vitest run` on the bridge tests (contract parity) in the group that changes the shape.

## 7. The window (group U1, Opus `ui-build`; precise direction, no mockup)

Read `docs/hub-design-language.md` first. Only existing blocks; nothing new centrally unless §12's critique finds a
missing pattern (then block + gallery + doc, CLAUDE.md). The window shows engine words and counts; it decides nothing
(the `derive` / `flows` checks).

### 7.1 The list (`pages/todo/Page.svelte`, `todoModel.ts`)

- The group appears as every group: a `ListSection` (label, count `openCount`, hint) among the rows of the one list
  `Surface`; filtered to it, the `Surface`'s own head. `MULTI_GROUPS` gains `missing_file` (⌘-click, ⇧-click, ⌘A).
- Rows: `ListRow` as today; `sub` = folder · `detail`; trailing: `AwayTag` with `file_missing` ("Missing") in the
  quality badge's slot (`rowAway` returns `file_missing` now; an `offline` item keeps "Offline"); the `.act` slot as
  today (HIDDEN).
- Head action (the `groupAction` / `cdjAction` slot, a third snippet): `Button variant="link" size="sm"` "Select all
  · n" when the group has two or more items that can act (n = `all.download_again + all.remove`); it selects the
  group's items that are not hidden, which opens the selection panel. No Resume (there is no batch).

### 7.2 One item (`pages/todo/Details.svelte`, `todoModel.actionsFor`)

- Head: `TrackHead` as every kind, Hide at the title's end.
- Body, first: `NoteCard tone="warn"` with `track.missing.line` as its title and `hint` as its text. Then what
  Details shows today for a file that is away (the facts `KeyValue` with the last path; no spectrum, no player: the
  `fileAway` branch already does this for `file_state != "here"`).
- `BoughtFile` (the drop zone) stays for a Download again song, only if E2's check passes (`add_bought_file` with
  the current file missing: nothing goes to Superseded; E2 pins it); else it is hidden for this group.
- Foot (`actionsFor().main`): Download again → `WriteButton` filled "Download again"; Remove → the foot's one button
  "Remove from library…" in the `danger` variant (the design language's minor destructive action; there is no filled
  danger), which opens `confirm` with §5.4's words, tone danger. `why_not` set: the button disabled with the
  reason's words as its tip and a `Hint` under it (the Upgrade ready reasons' pattern).
- After the job: the item leaves the group; the page moves on with `keepSelection` as after a Discard.

### 7.3 Library (`pages/library`, its details panel)

- Rows: the `AwayTag` "Missing" (§5.4) from `file_state`.
- Details: the same `NoteCard` (line + hint) where the away words show today (`fileAwayWords`), and a `Button
  variant="link"` "Open in To-do" to `#/todo?filter=missing_file&track=<key>` (To-do's `track` query exists:
  `selectFromTrack`). No action buttons in the Library (one place decides; the Library's file actions are about
  files that are there).

### 7.4 Several items (`lib/decisions/MissingSelection.svelte`, new, modelled on `UpgradeSelection`)

- A `Panel` while two or more `missing_file` items are selected (or Select all picked the group): head "{k} songs
  selected" (StatCard as UpgradeSelection's `selectedTitle`), then the selected rows (`ListRow`, × to drop one, the
  scrolling list of unknown length), each with its outcome word: "Downloads again", "Removed", or the `why_not`
  words dimmed.
- Foot: filled `WriteButton` "Download again · n" (when n > 0), `Button variant="danger"` "Remove from library ·
  m…" (when m > 0; it confirms with §5.4's plural words). n and m count the selected items by their engine
  `missing.action` with `why_not` null (formatting the engine's answers, as UpgradeSelection counts `same_track`).
  When only one kind is selected, only its button shows, and Download again stays the filled one.
- One job per press (`missing_files(keys, action)`); the panel shows the job's `words` and the skipped ones with their
  words (OutcomeList), then Done (as UpgradeSelection's ended phase, without Resume/Stop: no batch).
- The flow lives in `lib/decisions/flows.svelte.ts` (`MissingFlow`: `downloadAgain(keys)`, `remove(keys)` with the
  confirm), shared by Details and the selection panel; its pure parts (labels, counts from items, outcome words) in
  `decisionModel.ts` (or a `missingModel.ts` beside it) with `*.test.ts`.

### 7.5 Critique and shots

The builder critiques what it touches (spec §12: 1100 and 2560 widths, one filled button per panel, hierarchy,
consistency with the Upgrade ready and CDJ groups) and fixes it. It takes **no screenshots and runs no dev server**
(the shots agent does, §10). It runs `npm run check`, the touched `vitest` files and `npm run build`; `npm run
verify` once at the end of the branch (§10).

`pages/todo/shots.json` (+ `pages/library` if it has one) gains, all on scenario `missing_files`:
`todo-missing` (the group, its first item selected: a playlist song, Download again), `todo-missing-own` (the own
song with the parked upgrade: Remove, the hint's extra line), `todo-missing-twice` (the playlist song found in two
places: Download again disabled with its reason, the line names the two places), `todo-missing-selection` (Select all:
both buttons), `todo-missing-confirm` (the Remove confirm open), `library-missing` (a missing row and its details).

## 8. Docs (group D1, except the contract and CONTRIBUTING lines, which go with their code)

- Spec `docs/2026-10-23-library-and-sources-design.md` §6.3: "Gone" becomes **Missing** ("a known path is gone and
  nothing has its key: the row waits, marked missing since that scan, its song keeps everything and is left alone like
  an offline one; a file with its key anywhere in the watched folders later is Moved back to it; To-do lists it; only
  the user removes an own song or downloads a playlist song again; an index row of nobody's song is dropped"), and
  "Moved" says it holds across scans. §6.4 adds "nothing is decided by one scan" and that a missing file is not
  offline (its folder was read). §12 (error handling): the held rule is rewritten to D2. Each change names issue 43.
- README: the "Folder not found" bullet's last sentence ("A single song whose file was deleted … until the next
  scan.") becomes a **Missing files** bullet in the same list: what happens when a file is moved out of every watched
  folder or deleted (it waits in To-do under Missing files with where it was; nothing is downloaded or forgotten; put
  it back anywhere in a watched folder, under any name, and it links again with its upgrade, answers and rekordbox
  check; a playlist song: Download again; your own: Remove from library, which asks first). The To-do section's group
  list gains Missing files; the commands list gains `missing list | download | remove`; the lines about "files gone"
  (README l.52 and l.433 today: "files gone from your playlists" there is about playlists, check each) are checked
  and only the scan's meaning changed. README tone: plain English for a DJ, no internal words.
- `docs/issues.md`: entry 43 is removed in D1's commit (the last group). Entry 40's audit list: "out of every
  watched folder (gone: is the song downloaded again at the next sync?)" is answered in place: "out of every watched
  folder: waits as missing in To-do, never downloaded by itself (issue 43, README "Missing files")"; the rest of the
  audit stays open.
- `docs/hub-design-language.md`: only if U1 adds or changes a block (the AwayTag word is copy, not a block).
- The design spec's change log line (if the spec keeps one) and this plan's status line ("built") at the merge;
  the plan is archived with the stage's merge into `main` (CLAUDE.md "Finished plans").

## 9. Tests

The full Python suite once per group, in the foreground (`~/.local/bin/uv run pytest -q | tail -3`, Bash timeout
600000); while working only the touched files. UI groups: `npm run check`, touched `vitest`, `npm run build`.

### 9.1 Existing tests that pin today's deletion (each group rewrites those of its files; grep `gone`,
`file_gone`, `held`, `_drop_fileless_own`)

- `test_scanner.py`: `test_gone_when_nothing_has_the_key`, `test_a_file_removed_since_the_folder_was_listed_is_just_gone`,
  `test_migrated_row_without_key_two_names_is_ambiguous_none_is_gone`, `test_a_migrated_row_without_key_never_takes_an_indexed_file_by_name`
  → a linked row is `missing`, an unlinked one `gone`; `test_a_file_moved_into_an_unlistable_subfolder_is_held` →
  `missing`; `test_an_unreadable_file_holds_only_missing_rows_of_its_size` → deleted with the size rule (its
  replacement: an unreadable file of the same size changes nothing for a missing row); `test_a_gone_unlinked_row_never_takes_an_indexed_copy`
  stays.
- `test_library_scan.py`: `test_a_deleted_file_marks_its_song` → waits (path kept, `missing_since` set, no
  `file_gone`, words "Checked your Library: 1 file missing. Missing files wait in To-do."); `test_the_words_list_every_kind_of_change_in_order`
  → the new parts; `test_a_held_file_is_left_as_it_is_but_marked_held_until_it_is_seen` → `unjudged`;
  `test_a_file_moved_into_a_folder_the_scan_cant_list_is_held` → missing, then linked back once listable.
- `test_db_import.py`: `test_a_scan_that_loses_the_file_of_a_linked_own_song_marks_it_gone` → waits;
  `test_a_gone_own_song_is_deleted_and_a_gone_playlist_song_downloads_again` → split: `apply_scan` with linked ids in
  `gone` deletes nothing (§2.2's defence), and the deletion is `remove_watched_folder`'s (its own tests stay);
  `test_offline_and_held_rows_arent_waiting`, `test_offline_held_and_ambiguous_files_are_left_out` → `unjudged` and
  a missing row.
- `test_planner.py` (`test_a_file_gone_is_downloaded_again_at_once`, `..._takes_a_bought_file_first`: they stay for a
  song with no file row), `test_execute.py::test_a_file_gone_is_downloaded_again_into_the_placement_folder` (stays),
  `test_db.py::test_missing_deletes_the_row_of_a_file_that_is_gone` (stays for a non-redownload), `test_tidy.py`'s
  parametrize (gains `missing_since`), `test_auto_upgrade.py::test_hidden_held_missing_away_...` (gains a missing
  row), `test_hub_views.py::test_a_duplicate_group_with_a_file_offline_held_or_gone_is_not_shown` (gains missing).

### 9.2 New behaviours each group pins

E1 (scanner, db, scan words):
- **The repro, own song:** an imported own song (`local:n`) with a parked upgrade; its file moved out of every watched
  folder; scan → `missing == 1`, the song, its file row (`missing_since` set), its upgrade and answers are there,
  snapshot `files` leaves it out; moved back to the same path; scan → `back == 1`, the same song id and key, the same
  `files.id`, `missing_since` NULL, the upgrade still parked, no unlinked row, `import_waiting` empty.
- The same with the file put back under another name in another watched folder (an import folder): `moved`, same
  ids, `placed_by` user, `back == 1`.
- Missing for three scans, then back: `missing_since` is the first scan's stamp until then; `missing` counted once.
- Two copies appear: ambiguous, `missing_since` kept; one deleted: moved, back.
- An unlinked row whose file goes is deleted (`gone`), a keep_both answer naming it dropped.
- A row under an unlisted subfolder: present stays present, missing stays missing.
- `apply_scan` given a linked id in `gone` marks it missing (no delete).
- A Download-again mark (`file_gone`) is cleared when the row is back.
- `duplicate_groups`, `group_files`, `import_unjudged`, `files_without_facts` leave a missing row out; `_save_files`
  placing a file at a missing row's place clears the mark.
- Schema 10 → 11 upgrade of a file with a `held = 1` row: the column exists, the row unchanged; the next scan sorts it.

E2 (consumers): each row of §3: **the repro, playlist song**: a playlist song whose file is missing plans no action
(a dry-run plan from a made-up fetched playlist); with `file_gone` it plans `acquire` `redownload`; the redownload
placed moves the same `files.id` to the new place and clears `missing_since`; not found keeps the row, the parked
upgrade and clears `file_gone`; a bought file in its Library folder is adopted. Plus: tidy skip, undo skip, CDJ
group members, `free`/`askable`, `_own_check_due`, Same track's skip `file_missing` for a missing row (`batches.present`),
`add_bought_file` with the current file missing (check first, §7.2). (The duplicate and facts queries are E1's.)

E3a: §3's `views` rows (`file_state`, `next_due`, `upgrade_ready_keys` and so Auto-upgrade's set, `_group` for a
`file_gone` song with no row), the To-do group (order, label, hint, items, `all`, hidden, filter word, own songs listed, CDJ/upgrade groups
lose the song, `file_gone` songs leave it), `missing.view` and `why_not` per reason, `track()`'s `missing`,
Library rows' `file_state`, the contract parity test.

E3b: `missing_files` both actions (done, skipped with reasons, all skipped → `changed`), Remove deletes the parked
file after the save and nothing else on disk, Download again changes no row but `file_gone`; the preview; every
command's `--dry-run`, `--yes` refusal (`needs_yes`), `--all` (the same songs as the group's `all`), `--json`, the
lock (T10), `help --json` (T1), a missing row's old path as `<track>`.

U1: `todoModel` / `decisionModel` (or `missingModel`) tests for the row sub, the badge, the head label, the
selection counts and labels, the flow's confirm words; flows test for the two actions.

## 10. Groups, order, sizes, reviews

One agent at a time, in this order; each group branches from the stage branch after the previous one merged.
Sizes from the record (Sonnet engine group 150–310k, Opus UI build 300–400k, Sonnet review 110–140k, fresh fix round
115–145k).

| Group | Model / agent | Files | Deliverable | Expected |
|---|---|---|---|---|
| **E1** storage + scan | Sonnet | `db.py` (schema 11, snapshot, `_save_files`, `apply_scan`, `known_files`, the four queries), `models.py` (`KnownFile`, `ScanResult`, `ScanSummary`, `file_missing`), `scanner.py`, `library.scan_library` + words, `hub/api.rescan_library` result, `words.short_day`, contract doc's `rescan_library` line + `types.ts` scan result + fake; tests §9.1/§9.2 E1 | the repro (own song) green | 200–260k |
| **E2** consumers | Sonnet | `planner.py`, `execute.py`, `apply_outcome` (where it lives), `tidy.py`, `cdj.py`, `report.py` words; tests §9.2 E2 | the repro (playlist song) green | 150–210k |
| **E3a** views + read shapes | Sonnet | `missing.py` (rules, `view`), `views.py` (§3's `views` rows, To-do group, item, `track_detail`, rows), `hub/api.py` (`todo`, `track` pass `place`), contract doc, `types.ts`, `contract.ts`, fake scenario `missing_files` (reads); tests §9.2 E3a | `todo()` / `track()` answer the group | 210–260k |
| **E3b** actions + commands | Sonnet | `missing.py` (writes, preview), `hub/api.py` (two methods), `catalog.py`, `select.py`, `cli/` (render check), contract doc, `types.ts`, `contract.ts`, fake methods, CONTRIBUTING lines; tests §9.2 E3b | `missing download/remove` run end to end | 200–260k |
| **U1** the window | Opus `ui-build` | §7 (`pages/todo/*`, `lib/decisions/*`, `pages/library` details, `lib/format.ts`), shots.json entries; vitest | the group, panel, selection, Library note | 300–380k |
| **S1** shots | Sonnet | `node scripts/shots.mjs` on the six states of §7.5 at 1100 and 2560, compared to `main` for the To-do and Library pages; `npm run rules -- --page todo --only <shots>` | the shots and a list of what looks wrong (no fixes) | 80–120k |
| **D1** docs + rehearsal | Sonnet | spec, README, issues 43/40 (§8), `scripts/missing_files_rehearsal.py` (§10.2), its run | the rehearsal PASS; issue 43 removed | 120–160k |

E2 needs E1's `missing_since`; E3a needs E2's planner rules (a missing song plans nothing); E3b needs E3a's `missing.why_not`; U1
needs E3a+E3b's shapes and the fake; S1 needs U1; D1 last (it removes issue 43 and runs the rehearsal against the
whole stage). Interfaces between groups are §1.2–§1.3 (E1→E2, E3a), §3's planner rules (E2→E3a), §4.1
and §5 (E3a→E3b, U1), §6 (E3b→U1). Every `views.py` change is E3a's, so each shape change lands with its contract,
`types.ts` and fake in one commit.

### 10.1 Reviews

This writes `library.db` (a scan of every user's library runs it), so: a Sonnet review after each of E1, E2, E3a,
E3b and U1 (110–140k each; reviewers run only the touched tests, never the full suite), fixes by a fresh Sonnet
`fix-round` agent when the builder is over ~150k; then one **stage review** by Opus (~150k) over the whole branch
against this plan, issue 43's decision and CLAUDE.md §9.1, with the rehearsal's output in hand. `npm run verify`
once, before the merge (in the background with a status line). CI on push.

Estimate: builds ≈ 1.26–1.65M, reviews ≈ 0.55–0.7M, stage review ≈ 0.15M, fix rounds ≈ 0.35–0.45M: about 2.3–2.9M.

### 10.2 The rehearsal (D1; made-up data, the CLI end to end)

`scripts/missing_files_rehearsal.py --work W` (W outside the repo; refuses otherwise, and refuses unless it set
`DISCJOCKEY_SUPPORT=W/support` and `DISCJOCKEY_REKORDBOX=W/rb` (an empty folder) for every child process, printing
both first). Every step runs `bin/discjockey … --json` and checks the answer; PASS/FAIL per check, exit 0/1/2 as
`rekordbox_rehearsal.py`.

1. Setup: music folder `W/music`, an import folder `W/crate` with a click MP3 (`make_upgrade_test.py --click mp3
   --into W/crate`), `folder add W/crate` and its import, `--attach-upgrades --into W/crate` (a parked upgrade);
   `track show <path>` → key K, upgrade parked.
2. Own song: move the file to `W/away/`; `library scan` → `missing: 1`; `missing list` → one item, action `remove`;
   `track show K` → `missing.since` set, upgrade parked.
3. Back: move it to `W/crate/sub/renamed.mp3`; `library scan` → `back: 1`; `track show K` → same key, the new path,
   upgrade parked; `folder list` → nothing waiting to import; `missing list` empty.
4. Playlist song: a second click file placed as a playlist song's file in `W/music/Library/Rehearsal/` (seeded with
   the engine's own state functions, as the tests do). Check first: whether `sync plan --json` can plan from the
   stored playlist read without the network; if not, the script plans with `planner.plan` on the playlist it made up
   and runs everything else through the CLI. Move the file out; `library scan`; the plan holds no `acquire` for it;
   `missing download <key> --dry-run` → `n: 1`; `missing download <key>` → done; the plan holds `acquire`
   `redownload`; move the file back; `library scan` → `back: 1`; the plan holds no `acquire`, `file_gone` cleared.
5. Remove: move the own file out again; scan; `missing remove K --dry-run` → `n: 1`, `upgrade_waiting: true`;
   `missing remove K` without `--yes` → `needs_yes`, exit code of a refusal, nothing changed; with `--yes` → done;
   `track show K` → not found; the parked file is gone from `W/music/Upgrades ready/`; the click file in `W/away/`
   untouched.
6. Cleanup: the script deletes nothing outside W; the operator deletes W (the agent that runs it does, CLAUDE.md
   memory: own test files).

## 11. Check first (collected)

- `words.py` has no day formatter (§1.3).
- `apply_outcome`'s `missing` branch and the executor's `_drop_stale_upgrade` calls (§3, D8).
- `add_bought_file` with the current file missing (§7.2).
- `_resolve_track` by a missing row's path (§6.2).
- `cli/render/todo.py` shows the nested `missing` usefully (§6.2).
- Where reason words for command results live (`hub/outcomes.py`) (§4.1).
- `batches.ItemResult` reuse (§4.4).
- `sync plan` without the network (§10.2).
- `remove`'s save path deletes the row and the song; Favourites drop the key (§4.3).
