# rekordbox stage B: the write side, batches, Same track for any format, Upgrade all (issue 33): plan

Status: plan, 2026-11-08. Design: `docs/2026-11-07-rekordbox-repoint-design.md` (the design). This plan builds its
§13 stage B: §2.1–§2.3, §4, §5, §6, §7.2, §8, §9.1, §10, §11, §12, on top of stage A
(`docs/2026-11-07-rekordbox-stage-a-plan.md`, merged 43e6797). Branch `feat/rekordbox-b` from `main`; group worktrees
`.claude/worktrees/rb-b-<group>` on `feat/rekordbox-b-<group>`, each merged into the stage branch when its checks are
green. No mockup round (the user's rule for this stage): §6 gives every UI task its full design direction.

**Stage B in one line:** Discjockey points rekordbox's track at a new file itself (rekordbox closed, a backup per
batch, journal, undo per field), so Same track works for any format; every upgrade action runs on one track, a
selection or all eligible ones as one batch with progress, Stop, Resume and batch undo; To-do gets multi-select, the
selection panel, Upgrade all and one check card per batch; the console gets the `upgrade`, `batch` and `rekordbox
checked/backups/restore` commands.

**Not in stage B:** Auto-upgrade and its switch (C), Convert to AIFF from the file itself, Give it its clean name,
the CDJ group, Make all lossless files AIFF, `aiff_plan`, multi-select in the Library table, `cdj_cover` (D), rekordbox
following Discjockey's moves (E), any write to a USB stick (§6: not now), the bridge reads `rekordbox_status()` and
`rekordbox_preview()` (§0.9).

---

## 0. Decisions this plan adds to the design (with reasons)

1. **The write lives in its own module, `rekordbox/write.py`.** `master.py` stays the read side and keeps its pinned
   "a write through `Master` fails" test. CLAUDE.md's `db.py` row becomes "rekordbox's `master.db` only through
   `discjockey/rekordbox/master.py` (reads) and `write.py` (writes)". Reason: the read side stays provably read-only,
   the write is reviewed on its own.
2. **One column list.** `READ_COLUMNS` grows by every column stage B reads or writes (§1.2), so `status()` already
   answers `unreadable`/`schema` for a library B couldn't write; eligibility, panels and commands then agree before
   anything runs. Reason: one guard list, the design's guard 2 ("every column we read or write").
3. **The rekordbox side of a batch is a `Session`** (`rekordbox/session.py`): `rekordbox.lock`, the start check,
   one keyed read open with a one-pass path index, `DBID`, the lazy backup. Stages C and D start their batches through
   the same object. Reason: the review notes (one open per batch, one index), and C/D only add item kinds.
4. **`timeline_offset` takes an open library.** New keyword `view: RekordboxView | None` (the session's open
   `Master`, its index and status); `None` keeps today's own open (preview, New track). Reason: review note (two
   opens per file, ~0.4 s each).
5. **Quick eligibility for screens and counts.** `eligible.same_track_quick(entry, rb, present)` is everything known
   without decoding: an upgrade, the file there, the stored alignment `exact`/`shifted`, and for a file that isn't an
   AIFF rekordbox `ready` or `none`. Views, Upgrade all's count and `upgrade list` use it; the batch runs the full
   `same_track` (with timing and cloud) per item when it gets to it. Reason: the full check decodes each file (1–3 s);
   a count on a button can't. What only the run knows comes back as the item's skip reason (design §7.2).
6. **The AIFF in-place swap's rekordbox write never runs forward in recovery.** It is one transaction after the
   file write; if it didn't commit (rekordbox open, a crash), the swap finishes as today and its check keeps the
   Reload Tag step (`reload_tag: true`). Reason: a swap changes no path, so rekordbox's track points at a good file
   either way; recovery only finishes the file side.
7. **A batch started with rekordbox closed stops when rekordbox opens, whatever the next item is** (an AIFF swap
   included). A batch started while rekordbox runs may hold only items that need no rekordbox write (AIFF swaps, files
   with no rekordbox track); it never writes text columns. Reason: an opened rekordbox may have the file on a deck
   (design §2.5 says the same for Auto-upgrade); the design's §5.6 leaves this open.
8. **Undo after a batch can't make `master.db` byte-identical.** Undo gives touched rows a fresh `rb_local_usn` and
   `updated_at` (design §5.9, so rekordbox sees the change) and leaves created lookup rows. "Back as before" is pinned
   as: music files and ANLZ files byte-identical; `master.db` equal row by row except exactly those columns, the
   `localUpdateCount` row and the created lookup rows (§5, RH). The brief's "byte-identical to the copy" is this.
9. **No `rekordbox_status()` / `rekordbox_preview()` bridge methods in B.** No B screen reads them: `api.py` reads a
   cached status and passes it into the views (`upgrade_block.rekordbox`, To-do's counts), and agents have the
   commands. Stage C adds `rekordbox_status()` for the Sync page's line. Reason: no method without a reader.
10. **Every upgrade action takes a list** (the batch rule and the user's rule "every action: one, a selection or
    all"): `upgrade(track_ids, mode)` for `swap` (Same track), `add_new` and `discard`; `undo_upgrade(track_ids)`;
    `rekordbox_checked(track_ids)`. Only Same track is an AIFF batch (`aiff_batches`); New track and Discard on several
    tracks are one job that runs them one after the other (progress, Stop between, per-track results, no batch record,
    no Resume: each is quick and has its own undo). Reason: the design's batch is for the steps that write rekordbox.
11. **The "moving never renames" invariant changes in B, not D.** Same track for a file that isn't AIFF gives the
    file a new name (`Artist - Title.aiff`) in B already. B writes design §7.1's text with B's one step named; D adds
    Convert and Give it its clean name to it. Reason: the invariant must be true on `main` after the merge.
12. **`rb_local_usn`.** Design §5.5: one `localUpdateCount + 1` per transaction, every changed row gets it. **Check
    first (B2):** how pyrekordbox's published code numbers changed rows (its `autoincrement_local_update_count`); if it
    gives each changed row its own number, do that (rows in id order) and note the correction in the design's §5.5.
13. **`Length`** = whole seconds rounded down (`frames // 44100`). RH compares rekordbox's own AIFF rows with their
    durations; if rekordbox rounds, B's fix round follows.
14. **`rekordbox restore` tells what it leaves.** After a restore, tracks Discjockey repointed since that backup
    point at their old paths, whose files are in `Superseded/`. The command lists them (`missing_after`) and its text
    says "Undo those batches first (`discjockey batch undo`), or Relocate them in rekordbox". The design didn't say.
15. **No `cdj_cover` in B.** Same track takes the parked download's tags as the swap does (`copy_tags`); the cover is
    the one every download already has. The cap matters for own files' covers, converted in D.

---

## 1. Architecture (binding interfaces)

### 1.1 Modules

| Module | New/changed | Owns |
|---|---|---|
| `rekordbox/master.py` | changed | `Entry` grows; `READ_COLUMNS` grows; `Master.index()`; `entries_for(path, index=None)` |
| `rekordbox/write.py` | new | `open_write`, `Writer`: guards 3, 4, 5, 7 on the write connection, `repoint`, `write_text`, `undo_repoint`, find-or-create lookup rows, `contentFile`, `agentRegistry`, the stamp |
| `rekordbox/anlz.py` | changed | `splice_ppth(a, new_path) -> bytes`, `md5_size(path)` |
| `rekordbox/backup.py` | new | `Backup` (one per batch, reuse, manifest), `backups()`, `prune`, `restore` |
| `rekordbox/session.py` | new | `Session`: `rekordbox.lock`, start check, one read open + index, lazy backup, `view()` for `timeline_offset` |
| `rekordbox/offset.py` | changed | `timeline_offset(..., view=None)` |
| `rekordbox/eligible.py` | changed | `same_track_quick`; `REASONS` += `unclean`, `changed`, `space`, `rekordbox_open`, `rename_blocked` |
| `discjockey/convert.py` | new | The `convert` op (design §5.8 steps 1–7), `recover_convert`, `undo_convert` (design §5.9), `recover_convert_undo` |
| `discjockey/batches.py` | new | AIFF batches: `start`, `run`, Stop, `resume`, `undo`, `checked`, `recover` (running → stopped) |
| `discjockey/upgrades.py` | changed | `swap` writes rekordbox's text columns and `FileSize` (§0.6); `undo` dispatches `convert` records; `upgrade_status` words |
| `discjockey/library.py` | changed | `recover_pending` dispatches `convert`/`convert_undo`; path keys; `_prune_undo` also prunes backups |
| `discjockey/db.py` | changed | schema 7: `aiff_batches`, `aiff_items` and their queries; `end_step` can close a batch item |
| `discjockey/events.py` | changed | `BatchProgress` |
| `discjockey/batch_cmd.py` | new | `upgrade …`, `batch …`, `rekordbox checked/backups/restore` (`rekordbox_cmd.py` keeps status/preview) |
| `discjockey/hub/api.py`, `views.py`, `jobs.py` | changed | bridge methods, cached status, views (§4) |

### 1.2 `master.py` additions (B1)

```
Entry(..., artist_id: str | None, album_id: str | None, label_id: str | None, org_folder_path: str,
      local_folder_path: str | None, file_size: int | None, uuid: str | None)   # + the stage A fields
PathIndex(by_path: dict[str, list[str]], by_name: dict[str, list[tuple[str, str]]])   # folded path -> ids; name -> (id, path)
Master.index() -> PathIndex                     # one pass over djmdContent (not deleted, not streaming)
Master.entries_for(path, index: PathIndex | None = None) -> list[Entry]   # same answer with or without the index
```

`READ_COLUMNS` adds: `djmdContent`: `UUID`, `OrgFolderPath`, `rb_LocalFolderPath`, `FileSize`, `BitDepth`,
`SampleRate`, `BitRate`, `Length`, `rb_local_usn`, `updated_at`; `djmdArtist`/`djmdAlbum`/`djmdLabel`: `UUID`,
`SearchStr` (where the table has it: **check first** on pyrekordbox's published table definitions; `make_master`'s
`TABLES` follow), `rb_local_usn`, `rb_local_deleted`, `created_at`, `updated_at`; `contentFile`: `ID`, `rb_local_usn`,
`updated_at`; `agentRegistry`: `updated_at`; `djmdProperty`: unchanged. A test pins that a library missing any one of
them is `unreadable/schema`.

### 1.3 `write.py` (B2)

```
open_write(place, *, dbid: str, running=process.running) -> contextmanager[Writer]
    # refuses (WriteRefused(reason)) with nothing opened for writing: rekordbox running -> "rekordbox_open";
    # -wal/-shm beside master.db -> "unclean"; key/version/schema -> "rekordbox_unreadable"; DBID != dbid -> "other_library"
Writer.repoint(changes: list[RowChange], anlz: list[AnlzChange], *, running) -> Committed
    # one transaction: BEGIN IMMEDIATE; per row its before values of FolderPath and FileNameL still there, else
    # rollback -> Refused("changed"); cloud row -> Refused("cloud"); UPDATEs; lookup find-or-create; contentFile;
    # agentRegistry; the ANLZ files written as `<name>.dj-new` and renamed over the originals; guard 3 again; COMMIT.
    # rekordbox appeared -> rollback, the ANLZ files restored from `anlz[i].backup`, raise RekordboxOpened
Writer.write_text(changes: list[RowChange], *, running) -> Committed      # the swap's write: text + FileSize only
Writer.undo_repoint(record: RepointRecord, *, running) -> UndoOutcome      # design §5.9 step 1 and 3; refuses
                                                                           # ("relocated") with nothing changed
RowChange(id, before: dict[str, object], after: dict[str, object], text: dict[str, TextChange])
TextChange(field, before_shown: str, write: str | None, kept: bool)       # from eligible.text_plan
AnlzChange(path: Path, old_sha256: str, new_bytes: bytes, backup: Path)
Committed(usn: int, stamp: str, created: dict[str, list[str]],           # lookup rows made: table -> ids
          rows: list[RepointRow])                                         # what undo needs, per row
RepointRecord(dbid, rows: list[RepointRow], anlz: list[{path, old_sha256, new_sha256, backup}])
RepointRow(id, identity_before, identity_after, facts_before, text: {field: {before, wrote}}, kept: [fields],
           contentfile_before: [{id, hash, size}])
```

- **Identity columns:** `FolderPath` (the new absolute path, NFC), `FileNameL`, and `OrgFolderPath` /
  `rb_LocalFolderPath` only when each equalled the old `FolderPath` (design §5.5). **File facts:** `FileType` 12,
  `FileSize`, `BitDepth` 16, `SampleRate` 44100, `BitRate` `44100 × 16 × channels // 1000` (1411 for stereo),
  `Length` (§0.13). **Stamp:** `rb_local_usn` (§0.12), `updated_at` `YYYY-MM-DD HH:MM:SS.fff +00:00` (UTC, ms).
- **Text columns** (design §5.11): `Title`, `ISRC`, `Commnt` written in place; `ArtistID`, `AlbumID`, `LabelID` set to
  a found or created row: active (`rb_local_deleted = 0`) row with `Name` equal (NFC, exact), lowest `ID` when several,
  else a new row with rekordbox's scheme for `ID`, `UUID`, `SearchStr`, `rb_local_usn` and timestamps. **Check first:**
  the scheme from pyrekordbox's published `add_artist`/`add_album`/`add_label` and how it picks a new `ID` (names
  only; no code copied); RH compares created rows with rekordbox's own on the copy. Existing lookup rows are never
  updated or deleted. A field written only where `text_plan` says `write` and the clean value is not empty and differs from
  what is shown; `Commnt` also only over nothing or a quality line Discjockey wrote (any other comment is the user's). Genre, year, rating, colour, key, BPM, artwork, My Tags: never touched.
- **`contentFile`**: per spliced ANLZ file the row with `ContentID` = the track and `Path` = that file's path in the
  analysis folder: `Hash` = MD5 hex of the new bytes, `Size`; `rb_*` flags unchanged. **Check first:** the `Path`
  form (`/PIONEER/USBANLZ/…/ANLZ0000.DAT` like `AnalysisDataPath`, or another root) on pyrekordbox's published
  schema notes; RH confirms on the copy.
- **`agentRegistry`** `registry_id = 'localUpdateCount'`: `int_1` raised once per transaction (§0.12), `updated_at`.
- **Undo** (`undo_repoint`): identity columns must hold exactly `identity_after`, else `relocated` and nothing
  changes; then in one transaction: identity back; file facts back whatever they hold; each text column (and id
  column) back to `before` only where it still holds `wrote`; fresh stamp; `PPTH` back only where the file's `PPTH`
  still names our new path (a re-analysis rewrote it otherwise), `contentFile` for the files spliced back; guard 3
  before COMMIT. Lookup rows created stay (an unused row is what rekordbox leaves after an edit; **check first** on
  the copy in RH that such rows don't show as entries anywhere).

### 1.4 `anlz.py` (B2)

`splice_ppth(a: Anlz, new_path: str) -> bytes`: the file with the first `PPTH` tag's body replaced by the new path
(UTF-16BE, trailing NUL, `path_len` updated), the tag's `total_len` and the file header's `file_len` updated, every
other byte kept in order. `PPTH` holds the audio file's whole path (**check first** against crate-digger and a stage A
fixture: design §5.5's `?/<name>` form is wrong if the tag holds the full path; the splice replaces whatever path is
there only when it equals the row's old `FolderPath`, NFC and case-folded, else leaves the file alone and records
`ppth: "other"`). Pure; `read(splice_ppth(a, p))` round-trips.

### 1.5 `backup.py` (B2)

```
Backup.ensure(paths, place, *, dbid, batch_id, tracks: list[tuple[str, list[Path]]]) -> Backup
    # before a batch's first rekordbox write: reuse the newest backup whose manifest's master_sha256_after equals
    # master.db's current SHA-256 (add this batch's ANLZ folders and its id), else a new one
Backup.close(paths, backup, *, batch_id)        # at the batch's end: master_sha256_after
backups(paths) -> list[BackupInfo(id, created, batches, size, tracks)]
prune(paths, keep_ids: set[str])                 # keeps keep_ids + the newest 3
restore(paths, place, backup_id, *, running) -> RestoreResult(saved_current: str, missing_after: list[...])
```

Folder `<music>/.discjockey/rekordbox/backups/<UTC YYYYMMDDTHHMMSSZ>[-n]/`: `master.db` (a plain file copy, made only
after guard 4 holds, then SHA-256 checked against the source), `share/<AnalysisDataPath's folder>/` per track (every
file of that folder), `manifest.json` (`app_version`, `dbid`, `db_version`, `master_sha256_before`,
`master_sha256_after` (null until `close`), `batches`, `tracks`). `keep_ids` = backups named by any undo record or
any `running`/`stopped` batch (§1.7). `restore` refuses while rekordbox runs or `-wal`/`-shm` exist, first makes a
backup of the current `master.db` (`saved_current`), then copies master.db to `master.db.dj-new` beside the original,
fsyncs, renames over; the backup's ANLZ files the same way, one by one.

### 1.6 `session.py` (B2)

```
Session.open(paths, *, place=<locate()>, running=process.running, items_need_write: Callable[[RekordboxView], bool])
    -> contextmanager[Session]
Session.state: Status;  Session.view() -> RekordboxView | None;  Session.dbid
Session.writer() -> contextmanager[Writer]       # open_write; the backup is ensured before the first one
RekordboxView(master: Master, index: PathIndex, status: Status)
```

- Takes `<support>/rekordbox.lock` (flock, non-blocking) for its whole life → else `Busy` ("Discjockey is already
  changing your rekordbox library in another window or the Terminal.").
- Start check: `running()`; one read open (`open_read`: immutable when closed, `mode=ro` when running) and the index.
  If rekordbox runs and `items_need_write(view)` → `RekordboxOpen` before anything changed (design §5.6, §0.7); a read
  that fails while rekordbox runs counts as "needs a write" for every non-AIFF item.
- `none` (no library) and `unreadable` are answers, not errors: the items decide (eligibility).
- The read connection is closed before the first write transaction opens (two connections to one file never overlap).

### 1.7 library.db, schema 7 (B1)

```
aiff_batches(id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK (kind IN ('upgrade','convert','mixed')),
  started_by TEXT NOT NULL CHECK (started_by IN ('user','upgrade_all','make_aiff','cdj_all','auto_upgrade')),
  scope TEXT, started TEXT NOT NULL, ended TEXT, state TEXT NOT NULL CHECK (state IN ('running','stopped','done')),
  stop_reason TEXT CHECK (stop_reason IN ('stop','rekordbox_open','busy','crash')), backup TEXT)
aiff_items(batch INTEGER NOT NULL REFERENCES aiff_batches (id) ON DELETE CASCADE, seq INTEGER NOT NULL,
  track TEXT NOT NULL, action TEXT NOT NULL CHECK (action IN ('same_track','convert','rename')),
  state TEXT NOT NULL CHECK (state IN ('planned','done','skipped','failed','undone')),
  reason TEXT, result TEXT, PRIMARY KEY (batch, seq))
```

Outside library state (no `generation` bump, not in `snapshot`), like the move log. Queries: `start_aiff_batch(conn,
kind, started_by, scope, items, now) -> int`, `aiff_batch(conn, id) -> AiffBatchRow | None` (with its items),
`aiff_batches(conn, limit=20) -> (rows, total)`, `set_aiff_item(conn, batch, seq, state, reason, result)`,
`set_aiff_batch(conn, id, *, state, stop_reason=None, backup=None, ended=None)`, `running_aiff_batches(conn)`.
`db.end_step(..., item=(batch, seq, result))` marks the item `done` **in the same transaction** that ends the step,
so a crash can't leave a finished step with a `planned` item (Resume would then skip it as `no_upgrade`). The schema
step is `SCHEMA_V7_STEP` in `UPGRADES` like v5 and v6 (the mechanism every library goes through; nothing else for
older versions).

### 1.8 The `convert` op (B3, B4)

`convert.same_track(paths, state, track_id, upgrade, *, session, compare, now, batch: tuple[int, int] | None) ->
Result` for a current file that isn't AIFF. Journal op (library.db `pending`):

```
{"kind": "convert", "track_id", "batch": [id, seq] | null, "source": "upgrade",
 "old": <rel>, "new": <rel>, "superseded": <rel>, "staged": <rel .tmp/<track>/convert.aiff>,
 "old_sha256", "new_sha256", "parked": <rel>, "held": <rel .discjockey/undo/...>,
 "entry": <the entry after>, "before": <_before(e)>, "check": {...},
 "rekordbox": null | {"dbid", "backup", "rows": [RepointRow-like before/after], "anlz": [{path, old_sha256,
   new_sha256, backup}]},
 "marks": {"backed_up", "placed", "committed", "superseded"}}
```

Order (design §5.8): measure `L` again (`compare`; not `exact`/`shifted` → skip `needs_choice`); `d` from
`timeline_offset(old, view=session.view())` (`not_analysed`/`timing`/`cloud` → skip with that reason, nothing
written); free space (§1.9); 1 render `build_staged(parked, staged, L − d)` + `copy_tags`, hash; plan the rows
(`text_plan` against the old file's tags, `audio.file_facts`) and the ANLZ splices; 2 journal; 3 backup (session),
mark; 4 `move_path(staged → new)`, mark; 5 `Writer.repoint`, mark `committed`; 6 `move_path(old → superseded)`, mark;
7 end: entry `_upgraded(e, upgrade, new)`, file rows (`placed_by = 'app'`), the batch item, the check with its undo
record, the parked download to `held` (as `_hold`). No rekordbox track (or `none`): steps 3 and 5 are skipped.

- **Name and place:** `NameReserver.choose(folder, expected_stem(e["artist"], e["title"]), ".aiff", track_id)`;
  folder = the old file's, except a file in a playlist folder's `not_lossless/`: `replacement_dir(e, upgrade
  status)`, as `add_new`. `superseded`: `superseded_dir(old, watched_root(...))` under the old name (moving never
  renames).
- **Check record:** `{"reason": "repointed", "since", "match", "offset_ms", "aligned": true, "batch": id | null,
  "rekordbox": {"entries": [ids], "kept": [fields]} | null, "undo": {"kind": "convert", "before", "file": new,
  "old": superseded, "file_key", "old_key", "held", "repoint": RepointRecord | null}}`.
- **Recovery** (`recover_convert`, design §5.8): decided by the row's `FolderPath` (old / new / neither) when the op
  has rekordbox rows, else by the marks; rekordbox running while ANLZ files must come back → the op waits
  (`library._Waits` with the words of §3); another `DBID` → files only; the item's batch → `stopped`, `crash`.
  **Check first:** that `recover_pending`'s `_Waits` lets the rest of the run go on (design §14).
- **Undo** (`undo_convert`, op `convert_undo`, design §5.9): needs rekordbox closed when the step wrote it
  (`rekordbox_open`), refuses `relocated` (identity changed), checks the new and the old file's content key (`_unchanged`: a tag
  edit by rekordbox does not stop the undo, other audio does); old file back from `Superseded/` (`move_path`), `Writer.undo_repoint`, the new AIFF to
  `.discjockey/undo/<track>/` (deleted by `_prune_undo` once no record names it), the held download back to
  `Upgrades ready/`, the entry `before`. Journaled with marks, `recover_convert_undo` finishes or rolls back.

### 1.9 Space

Before rendering an item: needed = `ceil(duration_s × 44100) × 2 × channels + 4096` on the `.discjockey/.tmp` drive,
plus the same on the target folder's drive when `crosses()` (the staged copy of `move_path`). Not enough → skip
`space` with "{size} needed, {free} free" in the item's result. A batch's dry run sums it per drive.

### 1.10 Batches (B5)

```
batches.start(paths, items: list[tuple[str, str]], *, started_by, scope=None, now) -> int      # planned items
batches.run(paths, batch_id, *, emit, token, compare, now, running=process.running, place=<locate()>) -> BatchResult
batches.resume(paths, batch_id, ...) -> BatchResult           # only `planned` items, eligibility again
batches.undo(paths, batch_id | track_ids, ...) -> UndoResult  # newest first, one Session, refused listed
batches.checked(paths, track_ids) -> list[Result]             # forget_undo per track; frees backups to prune
batches.recover(paths)                                        # every `running` batch -> `stopped` ('crash')
BatchResult(batch, state, stop_reason, total, done, skipped, failed, results: list[ItemResult], backup)
ItemResult(track, action, state, reason, message, path, rekordbox: {entries, kept} | None)
```

- `run`: library lock held by the caller (as every write job); `Session.open` once (`items_need_write` = any
  `same_track` item whose file isn't AIFF and has an entry in the index); per item: `token.check()`, rekordbox opened
  since the start (§0.7) → stop `rekordbox_open`; full eligibility (`eligible.same_track` with the session's view and
  `audio.file_facts`) → skip with reason; AIFF → `upgrades.swap(..., session=…)`; else `convert.same_track`; a
  `RekordboxOpened` from a commit check → that item `planned` again, batch `stopped`/`rekordbox_open`; any other
  error → item `failed` with its plain message, the batch goes on. `BatchProgress` before each item and after the
  last. `Stopped` (Stop) and `RekordboxOpen` carry the `BatchResult` (as `tidy.Stopped`). `ops.log_operation` per
  item; `report.write_not_lossless` once at the end. `Backup.close` at the end, also when stopped.
- Problem kinds a batch ends with: none (done, skips included), `stopped`, `rekordbox_open`, `busy` (rekordbox.lock),
  `refused` (nothing eligible: "None of these can be upgraded right now." with each reason in the result).
- `checked` and `undo` take a batch's done items or any list of tracks; a batch whose items are all undone or checked
  ends (`done`).

### 1.11 Events and bridge shapes (B7)

`BatchProgress(batch_id: int, done: int, total: int, track_id: str | None, name: str | None)`: `done` items handled,
`track_id`/`name` the item now in work (null after the last). JSON results are `BatchResult`/`UndoResult` as dicts;
the commands print the same dicts (one shape for both, design §10).

---

## 2. Commands (B6; design §10)

New module `discjockey/batch_cmd.py`, wired into `cli.py`'s argparse sub-commands. Every command: no prompts, `--json`
prints one object at the end, the library lock as the hub takes it, exit codes:

| Code | Meaning |
|---|---|
| 0 | done for every track (skips none), or a dry run, or a read |
| 1 | refused or failed, or some tracks skipped/failed (each result says why) |
| 2 | no music folder or no setup |
| 3 | busy: the library lock or `rekordbox.lock` is held |
| 4 | rekordbox is open: nothing done, or the batch stopped there (resume after quitting it) |
| 5 | stopped (Ctrl-C between tracks): `batch resume <id>` |

Ctrl-C during a batch: the token stops it between tracks (a track in work finishes or rolls back), exit 5; the sync's
own 130 stays for the sync.

| Command | Does |
|---|---|
| `upgrade list [--json]` | Read, no lock. The parked upgrades as To-do lists them: `[{track, artist, title, folder, file, now, new, alignment, same_track: null \| reason, auto_refused: null}]` (`same_track` from `same_track_quick`) |
| `upgrade apply (<track>… \| --all) --way same-track\|new-track [--dry-run] [--json]` | `same-track`: one batch (`--all`: Upgrade all, `started_by` `upgrade_all`; else `user`). `new-track`: the tracks one after the other (§0.10). `--all` only with `same-track` (else exit 1, `refused`) |
| `upgrade discard <track>… [--json]` | Discard each |
| `upgrade undo <track>… [--json]` | Undo each track's replace, newest first, one job |
| `batch list [--json]` / `batch show <id> [--json]` | Batches (state, started_by, counts, backup) / one with its items |
| `batch resume <id> [--json]` / `batch undo <id> [--json]` | Resume a stopped batch / undo all its done tracks |
| `rekordbox checked (<track>… \| --batch <id>) [--json]` | "Done, checked in rekordbox" |
| `rekordbox backups [--json]` | `[{id, created, batches, tracks, size}]` |
| `rekordbox restore <backup> --yes [--json]` | Design §5.7 + §0.14; without `--yes`: exit 1, `reason: "needs_yes"`, nothing done |

**`--dry-run`** (apply only): no lock beyond a snapshot read, nothing written, no decode: per track `{track, action,
state: "planned" | "skipped", reason, file, new_file, superseded}` (from `same_track_quick` and `preview`'s naming
helpers), totals and `space: [{drive, needed, free}]`; it says the run re-checks each track. JSON failure shape as
design §10 (`kind`: `rekordbox_open` | `refused` | `changed` | `failed` | `busy`; `reason`; `message`; `details`).
Human output: one line per track ("Upgraded: Artist - Title → Artist - Title.aiff", "Skipped: … (reason in
words)"), then the summary; the reason words are `preview.REASON_WORDS` plus §3's new ones. `discjockey upgrades`
(interactive) stays; its `s` runs a batch of one (Same track for any format) and its tip becomes §3's console tip.
A batch of one named track that meets rekordbox open or a busy `rekordbox.lock` before anything ran is closed, not left
`stopped` (`batches.close_unrun`, in `apply` as in `upgrades` and the window); a new batch closes the unrun items of
earlier stopped batches for the same songs (`later_batch`), so each song waits in one batch only. The app's program
runs these commands too (`app_main.CLI_COMMANDS`), so the README's restore advice can name a path the app has.

**CONTRIBUTING.md** › "Commands for scripts and agents": one entry per command (flags, JSON, exit codes, lock, what it
changes), the exit-code table, and that an agent's command counts as the user starting it. `docs/issues.md` issue 39:
"stage B's commands are in CONTRIBUTING.md; gather them".

---

## 3. Words (binding; design §8 plus what B adds)

Design §8's rows for Same track (non-AIFF outcomes), the reasons (unreadable, no rekordbox), `rekordbox_open`, batch
stopped, the refusals (unreadable, not analysed, timing, cloud, unclean, changed, space), undo (rekordbox open,
refused), the result notes (no rekordbox track, kept edit), Upgrade all's before-line, the check text `repointed`, the
Reload Tag step (for a swap whose text write didn't run, and a batch card listing such tracks), the USB step **result
3** (until the live test), the console tip. Added here:

| Where | Text |
|---|---|
| Upgrade all's before-line, extra clause when some wait for another reason | "{k} wait for something else." (each row says what) |
| Group head link | "Upgrade all · {n}" (n = quick-eligible); "Resume · {k} left" while a stopped upgrade batch exists |
| Selection panel title | "{N} upgrades selected" / "{N} checks selected" |
| Selection Replace button | "Replace {n} with lossless" (the better-version wording of `replaceLabel` when any isn't lossless: "Replace {n} with the better versions") |
| Selection Discard | "Discard {N} new versions" · confirm "Throw away {N} new versions?" / "Your current files stay. These versions are not offered again." |
| Progress line | "{done} of {total} done" (the number and its unit) over "Upgrading · {Artist – Title}", with a ProgressBar labelled "Upgrading" |
| Batch done | "{n} upgraded, your cues stayed." · skipped: "{m} not upgraded" with each reason |
| Stopped by Stop | "Stopped after {done} of {total}." · button "Resume · {k} left" |
| Batch check row (To-do list) | name "{n} tracks upgraded", sub "{date} · Same track" |
| Batch card foot | "Done, checked in rekordbox" (filled) · "Undo all {n}" |
| Per-track undo in a batch card | icon button, title "Undo this one" |
| Busy (rekordbox.lock) | "Discjockey is already changing your rekordbox library in another window or the Terminal." |
| Recovery waits for rekordbox | "Quit rekordbox so Discjockey can finish an interrupted replace for {name}." (design §5.8) |
| Recovery messages | design §5.8's three |
| Undo refused (the track was moved or removed in rekordbox since the replace) | "This track was moved or removed in rekordbox since the replace, so Discjockey can't put it back safely. Nothing was changed." (reason words: the same in one clause) |
| A track planned in a later batch | reason `later_batch`, "it was planned again in a later batch" |
| Restore, human | "Restored rekordbox's library from {id}. Your library as it was is saved as {saved}." + §0.14's line when tracks point at Superseded/ |

The UI agent may shorten panel rows to fit; each meaning stays, with the reason in its commit.

---

## 4. Bridge and contract (B7; design §11)

Into `docs/hub-bridge-contract.md`, `types.ts` + `contract.ts`, and the fake backend, in one commit:

- **`upgrade(track_ids: list[str], mode)`** (`swap|add_new|discard`; a string is `refused`, bad input): `swap` is Same
  track for any format and runs a batch (job kind `upgrade_batch`, result `BatchResult`); `add_new`/`discard` run the
  list one after the other (job kinds `upgrade_add_new`/`upgrade_discard`, result `{results: [ItemResult]}`).
  `upgrade_all()`: job `upgrade_batch`, `started_by` `upgrade_all`. Per-item progress is `BatchProgress` for all
  three. New problem kind **`rekordbox_open`** (the job's `result` is the stopped `BatchResult` when items ran).
- **`batch_resume(batch_id)`**, **`batch_undo(batch_id)`**: jobs `batch_resume` / `batch_undo`.
  The hub's batch card ("Undo all {n}") sends `undo_upgrade` over its own undoable tracks; `batch_undo` is for the console.
- **`undo_upgrade(track_ids: list[str])`**: one job, newest first; result `UndoResult {results: [ItemResult]}`;
  `rekordbox_open`, `refused` per item inside. It sends no `BatchProgress` (only `batch_undo` does).
- **`rekordbox_checked(track_ids: list[str])`**: one job; the batch card sends its done tracks.
- **`upgrade_block`**: `swap_possible` now means "Same track is possible" (`same_track_quick`); new `swap_how`
  (`"in_place" | "new_aiff"`), `rekordbox: {"state", "running"}` (the cached status), `why_not` (a `REASONS` key or
  null), `auto_refused: null` (stage C fills it). `upgrade_status`'s row line: "cues can stay" whenever Same track is
  possible.
- **`check_view`**: reasons `repointed` (`converted`, `renamed` are stage D's), `aligned`, `reload_tag`, `batch:
  {id, size} | null`, `rekordbox: {entries: number, kept: [fields]} | null`.
- **`todo()`**: the `upgrade_ready` group gains `all: {n, m, k}` (quick-eligible, need a choice, wait for something
  else) and `stopped: {batch_id, left} | null`; the `rekordbox_check` group lists a batch of 2+ as one item
  `BatchCheckItem {key: "batch:<id>", group: "rekordbox_check", batch: {id, size, started, tracks: [TodoItem-like
  rows with check + can_undo]}}` (a type guard `isBatch` like `isDuplicate`); a batch of one stays a plain item.
  Counts: a batch counts as one to-do in `chips`.
- **Cached status:** `api._rekordbox_status()` keyed on `master.db`'s mtime and size plus `running()`; never opened
  while any write job of this hub runs (a sync, import or tidy-up runs the recovery first, which can write rekordbox;
  it answers the last value then). Views stay pure: the status is passed in.
- **Services:** `Services.rekordbox_running` (default `process.running`) and `Services.rekordbox_place` (default
  `locate`), so tests and the fake never touch a real library.
- `_single`'s "the entry as the page showed it" check stays for one-track calls of `add_new`/`discard`; a batch
  re-checks each item by its eligibility instead (a selection was never shown entry by entry).

---

## 5. Tests and fixtures (offline)

### 5.1 Helpers (`tests/rekordbox_helpers.py`, B1–B2)
- `make_master`: lookup rows with every scheme column filled the way the check-first found; `contentFile` rows whose
  `Path`, `Hash`, `Size` match the ANLZ files `make_anlz` wrote for the row (option `anlz=True`); an
  `rb_LocalFolderPath`/`OrgFolderPath` option per row; `usn`/`rb_local_synced` for cloud rows.
- `dump(db) -> dict[table, list[tuple]]`: every row of every table, ordered, via a keyed read-only open; `diff(a, b)`
  lists `(table, id, column, before, after)`. The whole-db compare of every write test uses it.
- `rb_library(tmp, specs)`: a music folder with own songs (`own_entry`), parked upgrades (a FLAC or AIFF render of the
  same clicks, so `align.compare` says `exact`/`shifted`), a fixture rekordbox whose rows point at the files, ANLZ
  files with `PWV3` (`pwv3_from`), `PQTZ`, `PPTH`; returns paths, keys, row ids.
- `running_after(n)`: a `running()` stub that answers True from its n-th call (rekordbox opening mid-batch).
- Crash injection: **check first** the existing pattern (`test_upgrades.py`: `test_a_rendered_add_is_crash_safe`,
  `renames_done`, monkeypatched steps) and use the same for steps 1–7 and the undo's steps.

### 5.2 Behaviours to pin, by group
- **B1:** `Entry`'s new fields; index lookup equals `entries_for` without it (exact, NFD/NFC, case, deleted,
  streaming, two rows, samefile); `timeline_offset(view=…)` equals the own-open answer and opens nothing; schema 7
  from 6 and fresh are equal; `aiff_*` queries; `end_step(item=…)` writes the item in the step's transaction (a
  failure leaves both unwritten); `same_track_quick` every branch; `REASONS` grown; a missing B column → `schema`.
- **B2 (write):** exactly design §5.5's columns change, `dump` diff equals the expected list; `OrgFolderPath` and
  `rb_LocalFolderPath` follow only when equal; stamp format and `localUpdateCount`; text: equal-to-tag written,
  edited kept (and listed), find reuses (lowest id among equals, deleted ignored), create makes one with the scheme,
  existing lookup rows byte-equal; `contentFile` MD5/size of the new ANLZ bytes; before values changed → `changed`,
  nothing written; cloud → `cloud`; rekordbox running at the commit check → rolled back, ANLZ files byte-identical to
  before, `RekordboxOpened`; `-wal` → `unclean`; other `DBID` → `other_library`; `undo_repoint`: identity, facts,
  text-only-where-ours, user's later title edit and cue added kept, `relocated` refuses with nothing changed, `PPTH`
  left when re-analysed. **Splice:** `PPTH` changed, every other tag byte-identical, lengths right, a path that isn't
  the row's left alone. **Backup:** files, manifest, SHA checks, reuse while the hash holds, a new one after an
  outside change, prune keeps referenced + newest 3, restore refuses while running and with `-wal`, restores both
  sides, saves the current first, lists `missing_after`. **Session:** `rekordbox.lock` busy; running + a needed write
  → `RekordboxOpen`, nothing written; running + only AIFF swaps → goes on; one read open per session.
- **B3 (convert + recovery):** the new file's name (`expected_stem`, an ID only when taken), place (`not_lossless/`
  rule), tags = the parked file's; the AIFF's clicks at the rekordbox-timeline positions to ±1 sample (M4A made in
  the test, both MP3 fixtures, a 48 kHz WAV); old file mirrored into `Superseded/` under its own name; file rows,
  `placed_by='app'`; held download; the check record; no rekordbox track / `none` → no database touched and the note;
  skips `needs_choice`, `not_analysed`, `timing`, `cloud`, `space` with nothing written; nothing written outside
  `move_path`; **a crash after each of steps 1–7** → recovery restores exactly the old state before the commit
  (files, ANLZ, `dump`, no created rows referenced) and finishes after it; rekordbox open during an ANLZ rollback →
  waits, next start finishes; another `DBID` → files only; the item's batch → `stopped`/`crash`.
- **B4 (undo + swap write):** convert undo restores files byte-identical, ANLZ byte-identical, `dump` equal except
  §0.8's columns; refusals (`rekordbox_open`, `relocated`, a file changed); crash at each undo step → recovery
  finishes or rolls back; swap with rekordbox closed and a track: text columns + `FileSize` written, undo puts them
  back per field; swap with rekordbox running: today's result and `reload_tag: true`; a crash after the file write
  and before the text write → recovery finishes the swap, writes nothing to rekordbox, `reload_tag: true`; every
  existing swap/undo test unchanged.
- **B5 (batches):** one backup and one `rekordbox.lock` for N tracks; per-item skip goes on; Stop between items →
  `stopped`/`stop`, the rest `planned`; rekordbox opening mid-batch (`running_after`) → the item in work rolled back,
  `stopped`/`rekordbox_open`, the rest `planned`; Resume does only `planned` ones and re-checks them; batch undo
  newest first, a refused one stays listed; `checked` ends undo for each and frees the backup for prune; a crash
  marks `running` → `stopped`; a mixed AIFF/MP3 batch; a batch of one; `BatchProgress` sequence.
- **B6 (commands):** exit codes 0–5, each JSON shape, one id / several / `--all` give the same per-track results as
  the bridge for the same library, `--dry-run` writes nothing (fixture folder and music folder unchanged), `restore`
  without `--yes` refuses, `--all` with `new-track` refuses, busy → 3, Ctrl-C (token) → 5.
- **B7 (bridge):** every method's shape (contract tests), `rekordbox_open` as a job problem, `todo()`'s batch item and
  `all`/`stopped`, `upgrade_block` fields, the cached status (one open per mtime), the fake mirrors each.

---

## 6. The UI (U1, U2): design direction, complete

Read first: `docs/hub-design-language.md`; load the skills `apple-design` and `emil-design-eng`. Pages use only the
blocks; the two block changes below go into the block, the gallery and the design language's block table + decision
log in the same commit. No single-component mockup is needed: everything is composed of existing blocks
(`ListRow`, `ListSection`, `Surface`, `ChoiceGroup`, `OutcomeList`, `NumberedSteps`, `ProgressBar`, `WriteButton`,
`Button`, `Hint`, `NoteCard`, `Cover`, `Badge`, `StatusMark`).

**Drift list (must not change):** the foot bar (player), the sidebar and its icons, every other page, Settings' icon
(never a sun), the coloured service logos, the filter strip, the row grid (`--row-cols`), the single-item upgrade card
(spectra, ComparePlayer, Edit row), the existing check card for a single track, the list's sticky section heads,
one filled button per screen. Choices stay `ChoiceGroup`/`Segmented`/grouped rows, never floating pills.

### 6.1 Multi-select (U1): a shared pure model + the list

- **Model** `hub-ui/src/lib/components/selectionModel.ts` (pure, `.test.ts` beside it; the Library table uses it in D):
  `Selection = { keys: string[]; anchor: string | null }`; `click(sel, key, mods: {meta, shift}, order: string[],
  scopeOf: (k) => string | null)`; `selectAll(sel, order, scopeOf)`; `keep(sel, before, after)` (keys gone from the
  list drop out; the anchor moves like `keepSelection`); `only(sel)` (the one key when exactly one). Rules: a plain
  click selects one; ⌘-click toggles a key **within the anchor's scope** (another scope: starts over with that key);
  ⇧-click selects the range anchor…key within the scope (in list order); ⌘A selects every key of the anchor's scope;
  Escape returns to the anchor alone; ↑/↓ move a single selection (multi ends). A scope that doesn't allow several
  (`multi(scope) === false`) behaves like a plain click.
- **To-do:** scope = the item's group; multi allowed in `upgrade_ready` and `rekordbox_check` only (other groups'
  actions aren't this stage's; issues.md gets the follow-up, see §8). `Page.svelte`'s `selKey` becomes a `Selection`;
  `selected` (one item) is `only(sel)`; held items (`TodoHold`) keep working for a single selection.
- **Rows:** every selected row gets `ListRow selected pick` (the orange wash) — one look for one or several; focus
  ring stays on the anchor's row. No tick boxes (the wash already says it; tick boxes would add a column to every
  row). Each row of a multi-select group is a toggle (`aria-pressed`), see the design-language decision log 2026-11-09: listbox/grid roles can't own the section heads' buttons.
- **Group head action (block change):** `ListSection` and `Surface` (list head) gain `action?: Snippet` at the head's
  end, after the summary, a `Button variant="link" size="sm"` (the "Show hidden" style). Used for "Upgrade all · {n}"
  (selects every item of the group, the anchor its first) and, while a stopped upgrade batch exists, "Resume · {k}
  left" in its place (runs `batch_resume` at once: it was confirmed when it started). Hidden when n = 0 and nothing is
  stopped. Gallery: `gallery-listsection` gains the action state.

### 6.2 The selection panel for Upgrade ready (U1): `lib/decisions/UpgradeSelection.svelte` + `UpgradeSelectionFoot`

Shown when 2+ items of the group are selected. Same `Panel` frame as the single panel (head, fill, foot).

- **Head (as built, F3):** the before-line (§3: "{n} upgrades keep their cues. {m} need your choice and stay." +
  "{k} wait for something else." when k > 0) is an info `NoteCard` in the panel head, only when something stays (the
  choice's "keep their cues" row says it otherwise), said once. The list is labelled "{N} upgrades selected" (the
  "Upgrade all · n" link counts the ones that go, the note says why the panel's N is larger). Originally: a `Surface
  kind="card"` labelled "{N} upgrades selected", summary = the before-line. Inside: the selected
  tracks as compact `ListRow`s (cover 28, "Artist – Title", sub = how it goes: "Same track" / "needs your choice" /
  the reason in words), scrolling inside the card after 6 rows, each with a muted ✕ trailing button to drop it from the
  selection.
- **"In rekordbox"** `ChoiceGroup` (as the single panel): "Same track · {n}" (recommended; outcomes: "Your tracks keep
  their cues, playlists and history", "Files that aren't AIFF become AIFF files", "Quit rekordbox before you
  replace") and "New track · {N}" (outcomes as today's New track, in plural). With n = 0: no choice, the card says
  "a new track" and why (as today's fixed card).
- **Foot:** filled `WriteButton` "Replace {n or N} with lossless" (the picked way's count; disabled with n = 0 under
  Same track), plain "Discard {N} new versions" (confirm), centred Hint "You can undo a replace until you press Done".
  When the selection is the whole group and Same track is picked, the button calls `upgrade_all()`, else
  `upgrade(ids, mode)`.
- **Running** (a batch or a list job of this panel, or found running on mount: **check first** how `MovesPanel`
  finds a running tidy job after a remount; do the same): the fill becomes `ProgressBar` (label "Upgrading", `pace`
  value) + the progress line + the same rows with `StatusMark` ✓ / skipped / now; the foot is one `Button` "Stop"
  (busy "Stopping"). The list keeps its selection; other rows stay clickable (they show their own panel; the job goes
  on and shows in this panel again when the group is reselected).
- **Result** (until the next pick): a `Surface` "Done" with the counts line and the not-upgraded rows with reasons
  (wrap); foot: filled "Done" (clears the result and selects the group's first item). **Stopped by Stop:** `NoteCard`
  info "Stopped after {done} of {total}." and filled "Resume · {k} left". **`rekordbox_open`:** `NoteCard` warn with
  §8's words (stopped mid-way: the batch-stopped line), filled "Resume · {k} left" (it re-checks rekordbox). **Refused**
  (nothing eligible): the result card with every reason.
- **One track** keeps today's single panel; a press there now also runs a batch of one, and a `rekordbox_open` comes
  back as the job's `ProblemCard`/toast with §8's words (`problemCopy` gains the kind).

### 6.3 The single upgrade panel (U1)

`decisionModel.upgradeWays(up, …)` reads `swap_possible` (now any format) and `swap_how`: "Same track" outcomes for
`new_aiff` are design §8's three; for `in_place` as today. No choice: the reason line from `why_not`
(`rekordbox_unreadable` → "Same track needs a rekordbox library Discjockey can open"; rekordbox `none` and a non-AIFF
file: the card says "a new track" with "No rekordbox on this Mac: the new file is a new track", and its button runs
`swap` (the clean AIFF, undoable); that card is titled "The new file", not "In rekordbox"); the other reasons as today,
each with its next step (F3, shown as body text): unreadable "… Update Discjockey, or replace it as a new track.", not
analysed "… Analyse it there, or replace it as a new track.", timing "… Analyse it again, or replace it as a new
track.", cloud "… Replace it as a new track instead.", file missing "… Put it back, then try again.", away "…
Connect it, then try again.". The tip line becomes the §8 console tip's meaning
("Quit rekordbox before you replace") only where a rekordbox write follows.

### 6.4 The check card per batch (U2): `lib/decisions/BatchCheckCards.svelte` + foot

- **List:** a batch of 2+ is one row in "Check in rekordbox": `Cover` of its first track, name "{n} tracks upgraded",
  sub "{date} · Same track", trailing `Badge` muted "{n}". Multi-select (§6.1) works on these rows and single checks.
- **Panel:** `Surface tone="warn"` "In rekordbox" with `NumberedSteps`: "Analyse them again, so the waveform shows the
  full sound" (note "(lock the beatgrid first if you set it by hand)"), the USB step result 3, and the Reload Tag step
  only when some track has `reload_tag` (listing those tracks by name; never for kept fields: Reload Tag would
  overwrite the user's own edit). Then a `Surface`
  "Upgraded" with one compact row per track: "Artist – Title", sub = new file name; a muted "Kept your own title" line
  (wrap) where `kept` isn't empty; "This file isn't in your rekordbox collection…" where `entries` is 0; trailing an
  undo icon button ("Undo this one"; hidden once undone or when `can_undo` is false). Summary of the card: since-date.
- **Foot:** filled "Done, checked in rekordbox" (all its done tracks), plain "Undo all {n}" (confirm: "Undo {n}
  replaces?" / "Your old files go back where they were. The new versions wait in Upgrades ready again."), the undo
  refusal Hint (problem tone) listing refused tracks with reasons; `rekordbox_open` → the §8 undo words.
- **Several checks selected:** panel "{N} checks selected" with the rows, foot "Done, checked in rekordbox" for all
  and "Undo all {n}" when every track can undo, else "Undo {n}" (those that can) over the muted "{k} can't be undone".
- **A single `repointed` check** keeps today's card layout: steps (analyse again, USB result 3), "Replaced with
  lossless" rows (new file, old file in `Superseded/`), Undo.

### 6.5 Fake backend and shots
Fake scenarios + `shots.json` entries (To-do, 1280 default; the shots agent also takes 1100 for the panels):
`todo-upgrade-multi` (3 selected, mixed), `todo-upgrade-all` (whole group, k > 0), `todo-upgrade-running`,
`todo-upgrade-stopped`, `todo-upgrade-rekordbox-open`, `todo-upgrade-done` (with skips), `todo-upgrade-refused`,
`todo-upgrade-mp3-same` (single, non-AIFF, recommended), `todo-upgrade-unreadable`, `todo-upgrade-no-rekordbox`,
`todo-check-batch`, `todo-check-batch-kept` (kept fields + Reload Tag), `todo-check-batch-undo-refused`,
`todo-check-multi`, `todo-check-repointed` (single), `todo-resume-link`, plus the none-selected and first-open
states of the page unchanged (drift). Gallery: `gallery-listsection` with action, `gallery-selection` (the model in a
list).

---

## 7. Task groups (one agent each, in this order, one at a time)

Every group: read `CLAUDE.md`, this plan and the design sections it names; touched tests while working, then
`~/.local/bin/uv run pytest -q | tail -3` once at the end (UI groups: `npx vitest run <files>`, `npm run check`,
`npm run rules -- --page todo --only <shots>`; `npm run verify` only once on the stage branch, §7 V);
`scripts/check_public.sh --require-denylist` before each commit; commits `feat(rekordbox): …`, `feat(upgrades): …`,
`feat(hub-ui): …`, `test(…)`, `docs(…)`, `build(hub): static`. Hard stop at about 80 tool calls: commit what is green
and report what is left. Never start rekordbox, never read `~/Library/Pioneer` or the real library (except RH, only
as written there), no waiter loops or `pgrep`, long commands in the background with a status line.

### B1. Records, read-side additions, quick eligibility — Sonnet, ~170–230k
Files: `discjockey/db.py` (schema 7, queries, `end_step(item=…)`), `discjockey/models.py` (`AiffBatchRow`,
`AiffItemRow`), `discjockey/rekordbox/{master,offset,eligible}.py`, `tests/rekordbox_helpers.py` (`dump`, `diff`,
`make_master` options), tests `test_db*.py`, `test_rekordbox_master.py`, `test_rekordbox_timing.py` (view),
`test_rekordbox_eligible.py`. Builds §1.2, §1.7, §0.4, §0.5. Pins §5.2 B1.
Stop point: schema 7 and the index green; `timeline_offset(view=…)` equal to the own open.

### B2. The rekordbox write, splice, backup, session — Opus, ~280–330k
Files: `discjockey/rekordbox/{write,backup,session,anlz,__init__}.py`, `tests/rekordbox_helpers.py` (lookup scheme,
`contentFile` rows, `running_after`), `tests/test_rekordbox_write.py`, `test_rekordbox_backup.py`,
`test_rekordbox_session.py`, `test_rekordbox_anlz.py`, `CLAUDE.md` (the package row: "reads and, in stage B,
writes"; the `db.py` row §0.1).
Builds §1.3–§1.6. Pins §5.2 B2. **Check first:** §0.12, §1.3's lookup scheme and `contentFile.Path`, §1.4's `PPTH`
form; that a `BEGIN IMMEDIATE` on a keyed `sqlcipher3` connection opened read-write (no `mode=ro`) leaves no `-wal`
after a clean close (rekordbox's own WAL mode; guard 4 must hold after our write too).
Stop point: a fixture repoint and its undo leave `dump` as pinned; the backup round-trips.

### B3. The convert step and its recovery — Opus, ~260–320k
Files: `discjockey/convert.py`, `discjockey/library.py` (`recover_pending` dispatch, `CONVERT_PATH_KEYS` in
`op_paths`, `undo_paths` for convert records), `discjockey/upgrades.py` (shared helpers made public where convert
needs them: `_upgraded`, `_before`, `_held_place`, `_hold`, `build_staged`), `tests/test_convert.py`,
`tests/test_convert_recovery.py`.
Builds §1.8 steps and recovery, §1.9. Pins §5.2 B3. **Check first:** §1.8's `_Waits` question; that `move_path`
takes `.discjockey/.tmp/` → a watched folder on another drive (`journal_crossings`), as stage A checked for `run_op`.
Stop point: Same track for an MP3 and an M4A on a tmp library, crash at every step recovered.

### B4. Undo per track, and the swap's rekordbox write — Opus, ~220–280k
Files: `discjockey/convert.py` (`undo_convert`, `recover_convert_undo`), `discjockey/upgrades.py` (`swap(...,
session=None)`: §0.6; `undo` dispatch; `upgrade_status`), `discjockey/library.py` (`forget_undo` for convert records:
the held download; `_prune_undo` also calls `backup.prune` with the ids undo records name), `discjockey/report.py`
(`check_text` for `repointed`, the Reload Tag text for `reload_tag`), tests `test_convert_undo.py`,
`test_upgrades.py`, `test_upgrade_undo.py`, `test_report.py`.
Pins §5.2 B4. Stop point: undo of an MP3 Same track back to the byte; swap writes and undoes text columns.

### B5. Batches — Sonnet, ~200–260k
Files: `discjockey/batches.py`, `discjockey/events.py` (`BatchProgress`), `discjockey/library.py`
(`recover_pending` → `batches.recover`), `discjockey/upgrades_cmd.py` (its `s` through a batch of one, §2),
`tests/test_batches.py`. Builds §1.10. Pins §5.2 B5.
Stop point: a mixed batch with a skip, Stop, Resume, rekordbox opening mid-batch, batch undo.

### R1. Engine review — Opus, ~140–170k; fix round — fresh Sonnet, ~115–145k
Reads the diff of B1–B5 against §0–§1, §5 and design §5: the write's columns, the guards (where each is checked),
the commit point and every crash window, the undo's per-field rule, the backup's consistency, the lock. Runs the full
suite once. Minors fixed in the same fix round. **Stop point:** the coordinator reads the review before B6.

### B6. Commands, CONTRIBUTING, README, CLAUDE.md — Sonnet, ~220–280k
Files: `discjockey/batch_cmd.py`, `discjockey/cli.py`, `discjockey/rekordbox_cmd.py` (shared output helpers only),
`tests/test_batch_cmd.py`, `tests/test_cli.py`, `CONTRIBUTING.md` (§2), `README.md` (Upgrades: Same track for any
format with rekordbox closed, the selection and Upgrade all, Undo all, Resume; rekordbox: when Discjockey changes its
library, what it changes and never changes, the text-column rule, backups and where they are, undo, USB sticks (result
3's words); When something breaks: `rekordbox restore`; Where things live: `.discjockey/rekordbox/backups/`),
`CLAUDE.md` (Invariants: §8's texts; the Layout row for `convert.py`, `batches.py`, `batch_cmd.py`; the commands row
pointing at CONTRIBUTING), `docs/issues.md` (issue 39 line). Builds §2. Pins §5.2 B6.
Stop point: every command on a fixture library and fixture rekordbox, human and `--json`.

### B7. Bridge, views, contract, fake — Sonnet, ~220–290k
Files: `discjockey/hub/{api,views,jobs}.py`, `docs/hub-bridge-contract.md`, `hub-ui/src/lib/bridge/{types,contract}.ts`,
`hub-ui/src/lib/bridge/events.ts` (`BatchProgress`), `hub-ui/src/lib/bridge/fake/*` (batches with progress, Stop,
`rekordbox_open`, the batch check item), `hub-ui/src/lib/copy.ts` (`rekordbox_open` words), `hub-ui/src/lib/decisions/
flows.svelte.ts` (lists in, one track = a list of one; no new UI), tests `test_hub_*.py`, `fake.test.ts`.
Builds §4. Pins §5.2 B7. The existing single panels keep working on the new shapes (vitest + `npm run check`).
Stop point: contract tests green; the fake answers every new method.

### RH. Rehearsal on a copy of the real library — Opus, ~200–260k
Builds `scripts/rekordbox_rehearsal.py` (committed: it holds no real data, takes every path as an argument, refuses
to run on a library while rekordbox runs or `-wal`/`-shm` exist beside the source), then runs it once and reports.
1. **Preconditions:** `process.running()` is false and the source `master.db` has no `-wal`/`-shm`; else stop and
   report (no waiting). All work under `<scratchpad>/rehearsal/` (never inside the repo).
2. **Copy:** `cp` the source `master.db` to `<scratch>/rb/master.db` before anything opens it (it is never opened in
   place), then open only the copy. Pick 4–6 tracks from the copy: an MP3 with cues and a grid, a 44.1 kHz M4A, a
   48 kHz M4A if one exists, an AIFF, one track in two playlists; prefer tracks with hot cues. Copy their audio files
   and their ANLZ folders (`share/PIONEER/USBANLZ/<a>/<b>/`) into `<scratch>/music/Library/Rehearsal/` and
   `<scratch>/rb/share/…`. The user's files are read only to copy them; their names never leave the scratch folder
   (the report names tracks as "MP3 #1" etc.).
3. **Prepare the copy** (with Discjockey's own write primitives): point each chosen row's `FolderPath`/`FileNameL` at
   its scratch copy and splice `PPTH` + `contentFile` the same way, change one chosen row's `Title` (a user edit to
   keep); set up a scratch Discjockey library (`DISCJOCKEY_SUPPORT=<scratch>/support`, music folder `<scratch>/music`)
   with the copies as own songs and, per track, a parked upgrade made from its own audio (an AIFF render of the
   decode: the same edit, `exact`), alignment filled by `upgrades.check`.
4. **Before:** `dump(copy)`, SHA-256 of every ANLZ and audio file, `timeline_offset` per file.
5. **Run:** `DISCJOCKEY_SUPPORT=… DISCJOCKEY_REKORDBOX=<scratch>/rb bin/discjockey upgrade apply --all --way
   same-track --json` (background, status line).
6. **Check with Discjockey's reader:** per changed row exactly §1.3's columns changed (`diff` against before equals
   the expected list; nothing else in any table); `FolderPath`/`FileNameL` = the new AIFF, which exists;
   `FileType` 12, `FileSize` = its size, 16/44100/1411, `Length` vs the file and vs rekordbox's own AIFF rows (§0.13);
   `rb_local_usn` and `updated_at` as pinned, `localUpdateCount` (§0.12; also compare with how rekordbox's own rows
   are numbered in the copy); every `djmdCue`, `contentCue`, `djmdSongPlaylist`, `djmdSongHistory`, `djmdSongMyTag`
   row of those tracks byte-equal; text columns per §5.11 (the edited title kept and reported, the others written or
   equal), created lookup rows compared field by field with rekordbox's own (scheme), reused ones unchanged;
   `contentFile` `Hash`/`Size` = MD5/size of the new ANLZ files; `PPTH` = the new path, every other ANLZ tag
   byte-equal; **timing:** `timing.measure` of the new AIFF against the old `PWV3` snaps to 0 (the AIFF sits on
   rekordbox's timeline); the AIFF swap: text + `FileSize` only; the backup: `master.db` byte-equal to the "before"
   copy, ANLZ folders present, manifest right; the master.db copy has no `-wal`/`-shm` after the run.
7. **Undo:** `bin/discjockey batch undo <id> --json`; check: audio files and ANLZ files byte-identical to before;
   `dump` equal to before except §0.8's columns (listed exactly); the parked downloads back in `Upgrades ready/`.
8. **Clean up:** delete `<scratch>/rehearsal/`; nothing real goes into the repo; report each check as pass/fail with
   numbers (no names). **Stop point:** any fail → the coordinator decides on a fix group before U1.

### U1. To-do multi-select, selection panel, Upgrade all, progress (UI build) — Opus, ~280–350k
Files: `hub-ui/src/lib/components/{selectionModel.ts,selectionModel.test.ts,ListSection.svelte,Surface.svelte}`,
`hub-ui/src/lib/decisions/{UpgradeSelection,UpgradeSelectionFoot}.svelte`, `decisionModel.ts` (+ test),
`UpgradeCards.svelte` (§6.3), `pages/todo/{Page.svelte,todoModel.ts,todoModel.test.ts,fake.ts,shots.json}`,
`lib/dev/Gallery.svelte`, `docs/hub-design-language.md` (block table, decision log: multi-select pattern, head
action). Builds §6.1–§6.3 and §6.5's U1 states. No shots beyond one look per state at 1280 to build against; `npm
run build` → `build(hub): static`.
Stop point: every U1 state reachable in fake mode.

### U2. Batch check card, check multi-select (UI build) — Opus, ~240–310k
Files: `hub-ui/src/lib/decisions/{BatchCheckCards,BatchCheckFoot}.svelte`, `CheckCards.svelte` (repointed),
`decisionModel.ts` (+ test), `pages/todo/{Page.svelte,Details.svelte,todoModel.ts,fake.ts,shots.json}`, the gallery,
the design language. Builds §6.4 and its §6.5 states. `build(hub): static`.

### S. Shots — Sonnet, ~120–160k
Every §6.5 shot at 1280 (panels also at 1100), compared with `main`'s shots of the same page for drift (§6 drift
list: foot bar, sidebar, other groups' rows, the single panels), each checked for meaning (every grey, colour, word
and count), empty, first-open and no-selection states, icons at real size. Reports findings; fixes nothing.

### R2. Stage review — Opus, ~150–180k; fix rounds — fresh Sonnet, ~115–145k each (code/docs, UI)
The diff against this plan and the design, the words (§3), the contract, the drift list, CLAUDE.md's invariants.
Minors fixed in the same rounds (no leftovers).

### V. Verify and merge
`npm run verify` once in the background (about 20 min), `npm run smoke`, CI green on the stage branch push; merge
`Merge feat/rekordbox-b: rekordbox write side, batches, Same track for any format, Upgrade all` into `main`. No
release. Then the user's live test (§9).

Total: about 3.0–3.6 M tokens over 13 agent runs plus fix rounds. The engine (B1–B5, R1) is about half; it is the
first write into a user's rekordbox library, so it gets its own review before anything builds on it.

---

## 8. Docs and issues

- **CLAUDE.md** (B6): "**Files move only in a batch the user started:** a move batch (tidy-up, the Playlists save
  question, a folder rename on disk) or an AIFF batch (Same track, Upgrade all), logged in `library.db` and undoable.
  The sync itself never moves a file (option A)." (stage C adds the Auto-upgrade exception, D adds its actions).
  "**Moving never renames:** a move (a tidy-up, its undo, a folder rename) keeps each file's name, so rekordbox's
  (Auto) Relocate finds it by that name. A file gets a new name only in a step the user chose that points every
  rekordbox track of that file at the new name itself, while rekordbox is closed (Same track for a file that isn't
  AIFF). That step is refused when it can't." Never delete or overwrite: unchanged (a convert writes a new file, moves
  the old one). Layout rows (§1.1), the `db.py` row (§0.1).
- **Contract** (B7), **design language** (U1, U2), **README** + **CONTRIBUTING** (B6).
- **Issues:** issue 33: "stage B merged (`<sha>`), live test pending; stages C–E open" (V). Issue 39: B6's line. New
  entry: "To-do multi-select for the other groups' actions (Hide, Find a version, …): the selection model is there
  (issue 33 stage B)". Issue 40 unchanged. A finding out of scope goes into `docs/issues.md`.
- **Design corrections** (B2/B6 commit them into the design doc where a check-first changes it): §0.8, §0.11–§0.14,
  `PPTH`'s form, `rb_local_usn`.
- **Archive:** the stage A plan moves to `docs/archive/` with its live check (stage A plan §6); this plan moves there
  when the live test (§9) passes; the design stays until the last stage.

---

## 9. The user's live test (about 30 minutes; only steps that need a person with rekordbox)

Before: in rekordbox File › Library › Backup; the agent copies `~/Library/Pioneer/rekordbox/` aside and prepares the
synthetic 120 BPM click tracks (one LAME MP3, one 48 kHz M4A, one FLAC, one AIFF), imported into a scratch watched
folder, each with a parked lossless upgrade (`scripts/make_upgrade_test.py`), and a spare USB stick.

1. In rekordbox: import the four, analyse them, set three hot cues on clicks of each, put one track in two
   playlists, play one, edit one title, export all four to the spare stick. Quit rekordbox.
2. In Discjockey, To-do › Upgrade ready: press **Upgrade all**, then Replace. Watch the progress; press Stop once
   midway, then Resume.
3. Open rekordbox: each track shows AIFF, 44.1 kHz, 16-bit; it plays; the cues and the grid sit on the clicks (the
   48 kHz M4A and the FLAC included); the edited title stayed, the other names are the clean ones; the artist/album
   rows sort and search normally; history and both playlists hold the track.
4. Quit and reopen rekordbox: all of it stays. Seek around in the former MP3 (no stutter). Analyse one again with the
   grid locked: the waveform refreshes.
5. In rekordbox, edit a title in Track info, quit, and check in Finder (Get Info) whether rekordbox wrote it into the
   file's tags (design §5.11's hole). Note Reload Tag's exact menu name and which fields it replaces.
6. USB stick (design §6), in order: a plain sync; if the stick keeps the old file, the stick's own track list in
   Devices and what it offers; else rebuild. Note which result it was (it decides the words).
7. Open rekordbox, then in Discjockey's To-do › Check in rekordbox press **Undo all** on the batch's card: it says to
   quit rekordbox. Quit, Undo all again: the old files come back in rekordbox with their cues.
8. Relocate by hand: one `.mp3` track relocated to an `.aiff` file works or not (README's words); whether rekordbox
   follows a file Discjockey moved into `Superseded/` by itself.
9. Leave rekordbox closed for a minute after quitting, then tell the agent: it checks that `master.db` wasn't touched
   by rekordboxAgent meanwhile and that rekordbox accepted the `contentFile` values (no re-analysis prompt).

If 3 fails for 48 kHz: own 48 kHz files render at their own rate (a fix group). If 9's `contentFile` fails: design
§5.5's fallback. If 3's names fail: design §5.11's fallback. After a pass: the release waits for the user's go.
