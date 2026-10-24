# Library stage 2 "Tidy-up" — plan

Spec: `docs/2026-10-23-library-and-sources-design.md` §8 (the spec), with §5.2 (`move_batches`, `moves`), §12 ("a
move fails mid-tidy-up") and §13 ("Tidy-up", live check). Orchestration: `docs/2026-10-23-library-and-sources-orchestration.md`.
Builds on stage 1 (`docs/2026-10-23-library-stage-1-plan.md`, its I1–I4). Stage branch: `feat/library-2-tidy-up`, off
`feat/library-1-foundation`; both merge into `main` together and ship in one release (spec §4).

**Goal:** files move to where the playlist order puts them only when the user says so (the "Tidy up files" button,
the Playlists save question), with a preview, an optional folder rename on disk, a log of move batches and Undo.

**Architecture.** A file's *target* (`planner.tidy_target`) and the preview rows (`planner.tidy_rows`) are pure. The
engine (`discjockey/tidy.py`, new) records a batch and its planned moves (`db.start_batch`), moves file by file through
`library.run_op`, marks each move done or skipped, and closes the batch. Undo is a batch of its own, in reverse order.
A batch a crash left open is closed by the next writer's `recover_pending` (`tidy.recover`). `views.py` words it all.

**Issue 25 in this stage:** its "Stage 1 interim" bullet (group 4 removes it). The tidy-up writes its file rows
explicitly (`db.finish_move`), not through the entry view (issue 25's first bullet); the rest stays for stages 3–4.

---

## Global constraints

- **Never delete or overwrite a music file; every move through `library.run_op`.** A refused or failed move is a
  skipped move, never a retry onto another name.
- **A tidy-up never renames a file** (spec §8.3): `dst` has `src`'s file name, byte for byte; a taken name is
  skipped (`name_taken`), never given an ID.
- **Only `db.py` writes SQL; `planner.py` and `hub/views.py` stay pure;** `tidy.py` does the I/O. Option A stays:
  the sync never moves a file.
- **Stage 2 moves only files under `Library/`** (import folders: stage 4, issue 25's staging across drives).
- **Words** are binding as given in I6. **Tests offline, `tmp_path` libraries only** (`conftest.py` points
  `DISCJOCKEY_SUPPORT` at a temp folder). **Public repo:** `scripts/check_public.sh` before every commit.

## Parked for the user (the plan uses the recommendation; the orchestrator confirms before dispatching group 3)

- **P1. "Save, leave files where they are":** the files this save would have moved become placed by `user`, so a
  later tidy-up lists them unticked ("You put this here") and the console line doesn't count them. *Why:* the user
  chose where they stay; otherwise every console sync would nag about files the user decided to keep. The console
  line (I6) counts only rows a tidy-up would tick by default.
- **P2. Undo of a folder rename on disk** renames the folder back as a whole when the new name is there and the old
  one is free. `playlists.txt` keeps the new name (undo never edits it); files downloaded into the folder since go
  back with it. The undo preview says so (I6 `U_RENAME`).
- **P3. A tidy-up stopped mid-batch** (crash, power cut, Stop): the file in flight is finished or rolled back by
  `run_op`'s recovery; files not started are *not* moved on the next start (the next start may be a console sync,
  and the console never moves files); they are recorded as skipped (`stopped`) and the Tidy up button offers them
  again. The batch stays undoable for what it did move.

## Review focus (per-group review and the stage review)

1. After a crash anywhere in a batch, the next writer start leaves every move `done` or `skipped`, rows matching disk.
2. No code path renames a file, overwrites one, or moves a file without a batch row.
3. Undo moves a file back only when its row is at `dst` with the batch's key and `src` is free; the rest are listed.
4. Ticks follow `placed_by`; `tidy_up` moves only what the page sent, and only if it still looks as shown.
5. Bridge methods never reject; write methods return a `job_id`; busy/console as every write method.

---

## Interfaces (fixed here; groups build against them)

### I1. Schema step 1 → 2 — `db.py` (group 1)

`SCHEMA_VERSION = 2`; `UPGRADES[1]` runs these statements (one `execute` each, inside the open transaction):

```sql
CREATE TABLE move_batches (
  id INTEGER PRIMARY KEY,
  started TEXT NOT NULL, finished TEXT,       -- ISO seconds; finished NULL = still running or stopped by a crash
  started_by TEXT NOT NULL CHECK (started_by IN ('tidy', 'save', 'rename', 'undo')),
  about TEXT,                                 -- JSON {"from": old, "to": new} for 'rename', else NULL
  undoes INTEGER REFERENCES move_batches (id));
CREATE TABLE moves (
  id INTEGER PRIMARY KEY,
  batch INTEGER NOT NULL REFERENCES move_batches (id),
  seq INTEGER NOT NULL,                       -- order in the batch; an undo goes in reverse
  kind TEXT NOT NULL CHECK (kind IN ('file', 'folder')),
  file INTEGER REFERENCES files (id) ON DELETE SET NULL,   -- NULL for a folder move or a file row since gone
  label TEXT NOT NULL,                        -- "Artist - Title" of a file, the folder name of a folder move
  src TEXT NOT NULL, dst TEXT NOT NULL,       -- snapshot paths (stage 1 I2): Library/<...>
  content_key TEXT,                           -- the file's key when planned; undo needs it unchanged
  placed_before TEXT, placed_after TEXT,      -- placed_by before / after this move (folder moves: NULL)
  state TEXT NOT NULL CHECK (state IN ('planned', 'done', 'skipped')),
  reason TEXT, detail TEXT,                   -- skip reason code (I6) and its detail (the failure's words)
  UNIQUE (batch, seq));
CREATE INDEX moves_file ON moves (file);
CREATE INDEX moves_batch ON moves (batch);
```

Decisions and reasons:
- **A step, not a new `SCHEMA_V1`:** the mechanism exists for this (stage 1 task 1.1). `db.create` builds V1 and
  then applies every step, so a fresh database and an upgraded one are the same by construction (a test compares
  their `sqlite_master`). *Check first:* `create` doesn't already apply `UPGRADES`.
- **Batches never deleted** (spec §8.4), so no cascade; a `files` row may go (`SET NULL`): undo says `moved_on`.
- **`placed_before`/`placed_after`:** a tidy-up makes a file `app` (spec §8.4); its undo restores `placed_before`.
- **`label` stored:** the log must still name a file whose song is gone or whose row is unlinked.
- Readers refuse version 1 (`OLDER`) until a writer upgrades it; version 1 never shipped, so only dev copies see it.

### I2. Snapshot addition — `db.snapshot` (group 1)

An entry with a linked file gets ✱ `file_id: int` (in `READ_ONLY`; `save` ignores it); others have none.

### I3. Types

`models.py` (group 1 adds them after `ScanSummary`):

```python
@dataclass(frozen=True)
class PlannedMove:            # what tidy.py hands db.start_batch
    kind: str                 # "file" | "folder"
    file_id: int | None; label: str; src: str; dst: str
    content_key: str | None; placed_before: str | None; placed_after: str | None
    skip: tuple[str, str | None] | None = None   # (reason, detail): recorded skipped at once (undo's checks)
@dataclass(frozen=True)
class MoveRow:                # a moves row joined with its file row as it is now
    id: int; batch: int; seq: int; kind: str; file_id: int | None; label: str; src: str; dst: str
    content_key: str | None; placed_before: str | None; placed_after: str | None
    state: str; reason: str | None; detail: str | None
    now_path: str | None; now_key: str | None    # the file row's snapshot path and key today (None: no row)
@dataclass(frozen=True)
class BatchRow:
    id: int; started: str; finished: str | None; started_by: str; about: dict | None; undoes: int | None
    moved: int; skipped: int
    undoable: int             # done moves whose undo could run today (I4 db.batches)
    undone_by: int | None     # the latest undo batch of this one
@dataclass(frozen=True)
class BatchResult:            # what every engine entry point returns; views word it
    batch_id: int | None      # None: nothing was asked to move
    started_by: str; moved: int
    skipped: tuple[MoveRow, ...]   # with reason/detail
    stopped: bool
```

`planner.py` (group 2; pure, no import of `models.py` changes needed):

```python
@dataclass(frozen=True)
class TidyRow:
    track_id: str; file_id: int
    src: str; dst: str        # snapshot paths; dst = target folder + src's file name
    placed_by: str            # "app" | "user" | "import"
    skip: str | None          # None | "offline" | "not_found" | "name_taken"
    # ticked by default  <=>  skip is None and placed_by == "app"
```

### I4. Signatures

Group 1 — `db.py` (each takes an open connection; writes run in one `transaction`):
- `start_batch(conn, *, started_by: str, about: dict | None, undoes: int | None, moves: Sequence[PlannedMove],
  now: datetime) -> int` — the batch row and every move (`planned`, or `skipped` with its reason when `skip` is set)
  in one transaction; `seq` = position in `moves`.
- `finish_move(conn, move_id: int) -> None` — one transaction: the move `done`; for a `file` move its file row (by
  id) gets `dst`'s (folder, rel) and `placed_by = placed_after` (a no-op on the path when `run_op`'s save already
  wrote it). For a `folder` move every row of the library watched folder whose rel starts with `src`'s rel + "/" gets
  `dst`'s prefix instead (linked rows already moved by the save are unaffected), `placed_by` untouched.
- `skip_move(conn, move_id: int, reason: str, detail: str | None = None) -> None`.
- `set_placed_by(conn, file_ids: Collection[int], value: str) -> int` — for P1's "leave" choice.
- `close_batch(conn, batch_id: int, now: datetime) -> None` — sets `finished`; every move still `planned` becomes
  `skipped`/`stopped`.
- `open_batches(conn) -> list[int]` — `finished IS NULL`.
- `batch_moves(conn, batch_id: int) -> list[MoveRow]` — in `seq` order, with `now_path`/`now_key`.
- `batches(conn, limit: int = 20) -> tuple[list[BatchRow], int]` — newest first, plus the total count.
  `undoable`: done `file` moves whose file row is at `dst` with `content_key` unchanged and no row at `src`, plus done
  `folder` moves while any library row sits under `dst`'s prefix. SQL only, no disk.

Group 2 — pure:
- `planner.tidy_target(entry: dict, folder: str | None = None) -> str | None` — `folder_dir(folder or
  entry["folder"], entry["status"]) + "/" + basename(entry["path"])`; None when the entry has no `path`, isn't
  `in_playlists`, or its path isn't under `Library/`.
- `planner.tidy_rows(state: dict, folders: Mapping[str, str] | None = None, *, only: Collection[str] | None = None)
  -> list[TidyRow]` — `folders` overrides `entry["folder"]` per key (the save preview's new placement); `only`
  limits rows to those keys.
- `planner.out_of_place(state: dict) -> int` — rows that would be ticked by default.
- `playlists_file.placement(rows: list[Row], tracks_by_id, state) -> dict[str, str]` — key → folder under `rows`,
  for the songs of read playlists (wraps `_fetched` + `desired_folders`).
- `playlists_file.retargeted(old, new, tracks_by_id, state) -> dict[str, str]` — keys whose folder changes (fold),
  → their new folder.
- `playlists_file.renames(old, new) -> list[tuple[str, str]]` — (old folder, new folder) per playlist (same
  `playlist_id`) whose folder name changed other than in case, in `new`'s order.

Group 3 — `library.py`, `tidy.py`, `events.py`:
- `library.run_op(paths, state, track_id, renames, entry, *, entries: Mapping[str, dict] | None = None,
  label: str | None = None)` — `entries` are applied with `entry` (a folder move changes many songs' paths in one
  step); `label` names the step in `recover_pending`'s messages. The pending op stores both only when given, so
  stage-1 ops and their tests are unchanged.
- `events.MovesProgress(batch_id: int, done: int, total: int)` — after each move of a batch.
- `tidy.tidy_up(paths, moves: Sequence[tuple[int, str]], *, started_by: str = "tidy", emit, token, now) -> BatchResult`
  — `moves`: (file_id, src as the page showed it).
- `tidy.rename_folder(paths, old: str, new: str, *, emit, token, now) -> BatchResult`
- `tidy.undo(paths, batch_id: int, *, emit, token, now) -> BatchResult`
- `tidy.undo_preview(paths, state, batch_id: int) -> list[PlannedMove]` — read only, no lock.
- `tidy.after_save(paths, retargeted: Mapping[str, str], choice: SaveChoice, *, emit, token, now)
  -> list[BatchResult]` with `SaveChoice(files: str, renames: tuple[tuple[str, str], ...], moves:
  tuple[tuple[int, str], ...])` in `models.py` (group 3 adds it); `files` is `"leave"` or `"move"`.
- `tidy.recover(paths, state) -> list[tuple[str, bool]]` — closes open batches (task 3.5).
- `tidy.rename_offer(old: str, new: str, rows: list[Row], library_dirs: Collection[str]) -> str | None` — None when
  offered, else the reason code (`folder_taken`, `folder_in_use`, `no_folder`). Pure; views word it.

### I5. Bridge (group 5; contract doc, `types.ts`, `contract.ts`, fake backend in the same commit)

Read, any time (in `LIBRARY_METHODS`):
- `tidy_preview()` → `{rows: [TidyRowJSON], ticked: int, rekordbox: [R1, R2], undo_note: U1, empty: str | null}`.
  `TidyRowJSON` = `views.track_row` fields + `{file_id, from, to, from_path, placed_by, ticked, yours, skip,
  by_rename}`: `from`/`to` are folders relative to `Library/` (`""` = `Library` itself, shown as "Library");
  `from_path` is the snapshot path the page sends back; `yours` = placed by `user`/`import`; `skip` = `null` or
  `{reason, text}`; `by_rename` (save preview only) = the old folder name whose on-disk rename would put this file
  at its target, else `null`.
- `move_batches()` → `{batches: [{id, at, title, moved, skipped, undoable, undone_by, summary}], total}` (20 newest).
- `undo_preview(batch_id)` → `{batch_id, title, rows: [{label, from, to, skip}], moving: int, warning: [..],
  nothing_left: bool}`.

Changed:
- `preview_playlist_change(lines)`: `moves` is removed; new `tidy: {headline, rows: [TidyRowJSON]} | null` (the files
  this change retargets, `null` when none) and `renames: [{from, to, files, offered, why_not}]`. `kind` keeps its
  values; for `moves`/`rename` the headline is I6 `SAVE_HEADLINE`. `checklist` per I6.
- `playlists()` rows unchanged; new top-level `tidy: {waiting: int}` (= `planner.out_of_place`).
- `save_playlists(lines, loaded_version, files = null)` — `files`: `null` (nothing retargeted) or `{choice:
  "leave"|"move", renames: [[old, new]], moves: [[file_id, from_path]]}`. Result `{version, batches:
  [BatchResultJSON]}`.

Write jobs (busy/console as every write method):
- `tidy_up(moves)` — kind `tidy`; `moves`: `[[file_id, from_path]]`. Result `BatchResultJSON`.
- `undo_moves(batch_id)` — kind `undo_moves`. Result `BatchResultJSON`.
- `BatchResultJSON` = `{batch_id, title, moved, headline, skipped: [{label, from, to, reason, text}], stopped}`.

Event: `MovesProgress {batch_id, done, total}` during `tidy`, `undo_moves` and a moving `save_playlists`.

### I6. Words (binding)

| Key | Text |
|-----|------|
| `SAVE_HEADLINE` | "{n} files would sit in a different folder" / "1 file would sit in a different folder" (spec §8.2) |
| Save buttons | **Save and move the files** · **Save, leave files where they are** (spec §8.2) |
| Rename option | **Rename the folder on disk too** (spec §8.2); detail: "One folder move instead of {n} file moves." |
| `folder_taken` | "A folder called {new} is already in your Library." (not offered) |
| `folder_in_use` | "{old} is still the folder of another playlist." (not offered) |
| `no_folder` | not shown: there is no `Library/{old}` to rename |
| Tidy button | **Tidy up files** (spec §8.2) |
| Tidy empty | "Every file is where the playlist order puts it." |
| Row mark | "You put this here" (spec §8.3; `placed_by` user or import) |
| Count line `C` | one pair: "{n} files move from {A} to {B}."; 2–3 pairs: "{n} files move: {a} from {A} to {B}, {b} from {C} to {D}."; more: "{n} files move between {k} folders." (1 file: "1 file moves …") |
| `R1` | "rekordbox may show the moved tracks as missing." |
| `R2` | "Its Relocate finds them again by file name: Discjockey never renames them." |
| `U1` | "You can undo this on this page." |
| Confirm | **Move {n} files** / **Move 1 file** |
| Undo | **Undo** · "Nothing left to undo" · confirm **Move {n} files back** |
| `U_WARN` | "{n} files go back to where they were. rekordbox may show them as missing again; Relocate finds them by file name." |
| `U_RENAME` | "The folder goes back to its old name {old}, with everything in it. The playlist keeps the name {new}." |
| Batch titles | `tidy` "Tidy-up" · `save` "Saved playlists" · `rename` "Renamed {old} to {new}" · `undo` "Undo of: {title}" |
| Batch summary | "{n} files moved" / "1 file moved", + " · {k} not moved" when k > 0 |
| Result headline | "Moved {n} files." · undo: "Moved {n} files back." · plus "{k} not moved:" and the list |
| Checklist (`moves`, `rename`) | downloads line as today · "Nothing is deleted" · "Files move only if you choose to" · "Moves can be undone on this page" |
| Checklist (other kinds) | downloads line as today · "Nothing is deleted" · "Happens at the next sync, not right away" (`CHECK_CUES` goes) |
| Console (spec §8.2) | "{n} files are not where the playlist order puts them; tidy up in the window." / "1 file is not where the playlist order puts it; tidy up in the window." |
| Recovery message | "A tidy-up was stopped before it finished: {moved} moved, {left} not moved. You can undo it or tidy up the rest on the Playlists page." |
| Folder step label | "the folder rename {old} → {new}" (the `label` of `run_op`) |

Skip reasons (`reason` code → text; views own the text, `tidy.py` the `detail`):

| Code | Where | Text |
|------|-------|------|
| `offline` | preview, run, undo | "Offline, skipped" (spec §8.1) |
| `not_found` | preview, run | "Not where Discjockey last saw it" (held, ambiguous, or not in `state["files"]`) |
| `name_taken` | preview, run | "A file with this name is already in {to}" |
| `changed` | run | "Changed since the list was shown" (its row's path isn't the `from_path` the page sent) |
| `failed` | run, undo | "Couldn't move it: {detail}" |
| `stopped` | run, undo | "Not moved: the moves were stopped first" |
| `moved_on` | undo | file: "Moved or changed since"; folder: "The folder {new} isn't there any more" |
| `place_taken` | undo | file: "Another file is in its old place now"; folder: "A folder called {old} is in your Library again" |

`detail` for `failed` (`tidy.py`, from the `OSError`): EACCES/EPERM "Discjockey isn't allowed to change that folder";
ENOSPC "the drive is full"; EROFS "the drive is read-only"; ENOENT "it isn't there any more"; else `strerror`,
lower-cased. `R1`/`R2` are checked against the real rekordbox in the live check before release (spec §8.3).

---

## Task groups

| Group | Model | Area | Size (changed lines) | Depends on | Runs with |
|-------|-------|------|----------------------|------------|-----------|
| 1 Move log | Opus | `db.py`, `models.py` | ~550 | — | 2 |
| 2 Targets | Opus | `planner.py`, `playlists_file.py` | ~400 | — | 1 |
| 3 Engine | Opus | `tidy.py` new, `library.py`, `events.py`, `cli.py` | ~850 | 1, 2 | 4 |
| 4 Words and views | Sonnet | `hub/views.py` | ~550 | 1, 2 | 3 |
| 5 Bridge | Sonnet | `hub/api.py`, `hub/jobs.py`, contract, `types.ts`, `contract.ts`, fake | ~800 | 3, 4 | 7 |
| 6 Playlists page | Opus | `hub-ui/src/pages/playlists/` | ~800 | 5 | — |
| 7 Docs | Sonnet | README, CLAUDE.md, `docs/issues.md` | ~120 | 3 | 5 |

Rounds: (1 ∥ 2) → (3 ∥ 4) → (5 ∥ 7) → 6. Parallel groups share no file (`TidyRow` lives in `planner.py`; group 4
gets `rename_offer` passed in, so it doesn't need group 3). Merge 3 before 4.

---

## Group 1 — Move log (Opus)

**Read list:** this plan's Global constraints, I1–I4, I6 skip codes; `discjockey/db.py` lines 1–40, 142–180 (`check`,
`_upgrade`), 183–210 (`READ_ONLY`, columns), 269–300 (`snapshot_path`, `_Folders`), 373–480 (`create`, `_files`,
`snapshot`); `discjockey/models.py` (`grep -n "^class "`, then `ScanSummary`); `tests/test_db.py` (`grep -n "def
test_"` and its helpers). No other files.

### 1.1 Schema step 1 → 2
- `SCHEMA_V2_STEP` (the I1 statements) and `UPGRADES[1]`; `SCHEMA_VERSION = 2`; `create` applies the steps after
  `SCHEMA_V1`. Update the `UPGRADES` comment (no longer "Stage 2 adds").
- Tests (`tests/test_db.py`): a version-1 database opened by a writer (`check(upgrade=True)`) gets both tables and
  version 2, its rows untouched; a failing step leaves version 1 (the stage-1 test still holds with the real step
  table); fresh and upgraded `sqlite_master` are equal; a reader on version 1 answers `OLDER`.

### 1.2 Batch and move writes
- `start_batch`, `finish_move`, `skip_move`, `close_batch`, `set_placed_by` per I4. Paths in rows are snapshot paths; turn them into
  (folder, rel) with `_Folders.locate`. `finish_move` on a `file` move whose file row is gone (`file` NULL) only marks
  the move done.
- `finish_move`'s folder branch: prefix rewrite with `substr(path, 1, ?) = ?` (as `apply_scan` does), NFC; the
  `UNIQUE (folder, path)` can't collide because the target folder didn't exist (the engine checks).
- Tests (`tests/test_db_moves.py`, new): a batch with planned and pre-skipped moves; `finish_move` moves the row and
  sets `placed_by`; idempotent when the path is already there; folder prefix rewrite moves linked and unlinked rows,
  not `Old2/` (prefix must end at "/"); `close_batch` turns `planned` into `stopped`.

### 1.3 Batch reads
- `open_batches`, `batch_moves`, `batches` per I4; `undone_by` = max id of batches with `undoes = id`.
- Tests: `undoable` counts a done move whose row is at `dst` with the same key; not when the key changed, the row is
  gone, or a row is at `src`; a folder move counts while rows sit under `dst/`; `batches` is newest first with the
  total.

### 1.4 `file_id` in the snapshot
- ✱ `file_id` per I2; add to `READ_ONLY`.
- Tests (`tests/test_db.py`): present for linked entries, absent otherwise; `save` of a snapshot with a changed
  `file_id` writes nothing.
- Checks while working: `uv run pytest -q tests/test_db.py tests/test_db_moves.py tests/test_db_migration.py
  tests/test_library_state.py tests/test_library_scan.py`.

## Group 2 — Targets (Opus)

**Read list:** spec §8.1, §8.3 first paragraph; this plan's I3 `TidyRow`, I4 group 2; `discjockey/planner.py`
lines 1–72 (placement helpers) and 134–138 (`desired_folders`); `discjockey/playlists_file.py` lines 142–182
(`Change`, `_fetched`, `preview_change`); `tests/test_planner.py` and `tests/test_playlists_file.py` (`grep -n "def
test_"`, helper signatures). No other files.

### 2.1 `tidy_target`
- Per I4. *Why the current file name:* rekordbox's Relocate finds files by name (spec §8.3). Lossy statuses go to
  `not_lossless/` (`folder_dir` already folds `LOSSY`).
- Tests: lossless → `Library/F/name`; lossy → `Library/F/not_lossless/name`; `folder=` overrides; no path, not in
  playlists, or a path outside `Library/` → None; a name that isn't "Artist - Title" is kept as it is.

### 2.2 `tidy_rows`
- One row per entry with a target whose folder differs from the file's folder (compared with `fold`: a case-only
  difference is no move, as the planner's renames). Skip rules in this order: `online` False → `offline`; `held`, key
  in `state["ambiguous"]`, or path not in `state["files"]` → `not_found`; target name (fold) in `state["files"]` or
  already claimed by an earlier row → `name_taken`. A name another row of the same batch frees still counts as taken
  (one more tidy-up moves it; keeps batches order-free and undo simple).
- Order: by `fold` of the source folder, then of the file name. Rows carry `file_id` from the entry (I2).
- Tests: default ticks follow `placed_by`; each skip; two files with one target name (the second is `name_taken`);
  `only=`; `folders=` overriding; a file in a user subfolder of its own target folder (`Library/F/sub/x`) is a row.

### 2.3 `out_of_place`
- Count of rows with `skip is None and placed_by == "app"` (P1). Test: user-placed and skipped rows don't count.

### 2.4 `playlists_file` helpers
- `placement`, `retargeted`, `renames` per I4. `preview_change` may call `placement` instead of its two
  `desired_folders` calls (refactor, behaviour unchanged).
- Tests (`tests/test_playlists_file.py`): an order change retargets the shared tracks only; an unread playlist's
  tracks aren't in `retargeted`; `renames` ignores case-only renames and keeps `new`'s order.
- Checks while working: `uv run pytest -q tests/test_planner.py tests/test_playlists_file.py tests/test_execute.py
  tests/test_run.py`.

## Group 3 — Engine (Opus)

**Read list:** spec §8 (all), §12 "A move fails mid-tidy-up"; this plan's Parked P1–P3, Review focus, I1, I3–I4, I6;
`discjockey/library.py` lines 253–315 (`load_state`, `open_state`, `open_records`), 398–431 (`save_state`), 491–622
(`NameReserver`, `safe_rename`, `run_op`, `recover_pending`), 631–690 (`scan_library`); `discjockey/ops.py` lines
1–100 (`run_single`: the shape of a write op); `discjockey/events.py` (`grep -n "^class "`, `CancelToken`);
`discjockey/cli.py` lines 43–100; `tests/test_library_ops.py` (`grep -n "def test_"`, helpers); `tests/conftest.py`
fixture names. No other files.

### 3.1 `run_op` with several entries
- Per I4. `recover_pending`: when `done_any`, apply `op["entries"]` too; name the step by `op["label"]` when present.
- Tests (`tests/test_library_ops.py`): a folder rename step with entries, crashed after the rename, is finished and
  its entries applied; the message uses the label; a stage-1 op without the keys behaves as before.

### 3.2 The batch runner: `tidy_up` and `rename_folder`
- Every entry point (the caller holds the lock): `open_state`, `recover_pending` (messages emitted), `clear_tmp`,
  `scan_library`, then a fresh `open_state`. *Why scan:* a file moved by hand since the preview must be found where
  it is, not moved from a stale place.
- `tidy_up`: rows = `tidy_rows(state, only=…)` for the sent file ids; a sent id whose row's `src` isn't the sent
  path → `changed`; no row any more → `not_found`; a row with `skip` → that skip. `start_batch` with every sent move
  (pre-skipped ones included, so the log shows them). Then per planned move, in order: `token.check()`; `run_op(paths,
  state, key, [(src, dst)], {**entry, "path": dst})`; `finish_move`; emit `MovesProgress`. `FileExistsError` →
  `name_taken`; `FileNotFoundError` → `not_found`; other `OSError` → `failed` with I6's detail. Any of them: the file
  stays where it was (`run_op` drops a step that renamed nothing), the batch goes on (spec §12).
- `Cancelled` (Stop) between files: `close_batch` (the rest become `stopped`), then re-raise. *Check first:* what
  `JobFinished` a cancelled write job reports today; keep it, and make the job's result still carry the batch.
- `rename_folder`: offered only when `rename_offer(...)` is None at run time too; one `folder` move: `run_op(paths,
  state, key, [("Library/<old>", "Library/<new>")], None, entries={every linked entry under Library/<old>/: path
  rewritten}, label=…)`, then `finish_move` (the unlinked rows). `placed_by` unchanged: the files keep their place
  inside the folder.
- `rename_offer` (pure): `folder_taken` when `new` (fold) is in `library_dirs`; `folder_in_use` when a row of the
  new lines still uses `old`; `no_folder` when `old` isn't in `library_dirs`. *Check first:* `pf.validate` already
  refuses two lines with one folder (then `folder_in_use` only covers a switched-off line).
- Tests (`tests/test_tidy.py`, new, `tmp_path` libraries): a batch moves ticked files, rows and `placed_by` follow,
  names unchanged; a name taken at run time, a vanished source and a `PermissionError` (monkeypatched `os.rename`)
  are skipped and the rest move; a changed `from_path`; Stop after the first file; a folder rename moves linked and
  unlinked rows and refuses a taken name.

### 3.3 Undo
- `undo_preview(paths, state, batch_id)`: from `batch_moves`, done moves in reverse `seq`, each a `PlannedMove`
  `dst → src` with `placed_after = placed_before`; `skip` = `moved_on` when `now_path != dst` or `now_key !=
  content_key` (folder: `Library/<new>` isn't a folder); `place_taken` when `src` exists on disk (folder: the old
  folder exists); `offline` when the file row is offline. Moves that were skipped in the batch aren't listed.
- `undo`: the same entry steps as 3.2 (recover, scan, fresh state), the preview again, `start_batch(started_by="undo",
  undoes=batch_id)`, then the runner of 3.2 (shared code). Spec §8.4: only when still where the batch put it and the
  old place is free; every skipped file listed.
- Tests: undo restores paths and `placed_by`; each skip reason (file edited so the key changes, file moved by hand,
  old place taken, folder renamed again); undo of an undo; a batch with nothing left gives a batch of skips only
  and `moved == 0`; undo of a folder rename (P2).

### 3.4 `after_save`
- Writes `retargeted` into the entries' `folder` (one `save_state`), so targets are current without waiting for a
  sync. Then `files == "leave"`: every `tidy_rows(state, only=retargeted)` row with `placed_by == "app"` gets
  `placed_by = "user"` (P1; one `db.set_placed_by` call).
  `"move"`: each rename in `choice.renames` through `rename_folder` (a batch each, `started_by="rename"`), then
  `tidy_up(choice.moves, started_by="save")`; results in that order.
- Tests: leave marks only the retargeted app files; move with a rename and moves gives two batches; a rename refused
  at run time is a batch with one skipped move, and the moves still run.

### 3.5 Recovery and the console line
- `tidy.recover(paths, state)`: for each open batch, each `planned` move: done when its file row is at `dst`
  (`finish_move` for `placed_by`), or when `dst` exists on disk and `src` doesn't (folder: the folder renamed); else
  `stopped` (P3). `close_batch`; one I6 recovery message per batch. Called at the end of
  `library.recover_pending` (local import, as `recover_swap`) when the state is version 2 and `open_batches` isn't
  empty. *Check first:* every writer path (run, `ops.run_single`, the tidy entry points) calls `recover_pending`.
- `cli.sync`: after a sync, after "Nothing changed." and after a dry run, print I6's console line when
  `planner.out_of_place(state) > 0`, on the state the run saved (*check first:* `prep.state` is that state). Change
  "No downloads or moves needed." to "No downloads needed." (the sync makes no moves under option A).
- Tests (`tests/test_tidy.py`): a crash after the rename and before `finish_move` (monkeypatched to raise) → next
  `recover_pending` marks it done, the rest `stopped`, one message; a crash before the rename → `stopped`, the file
  where it was. `tests/test_cli.py`: the line, singular and plural, absent at 0.
- Checks while working: `uv run pytest -q tests/test_tidy.py tests/test_library_ops.py tests/test_library_state.py
  tests/test_run.py tests/test_cli.py tests/test_ops.py`.

## Group 4 — Words and views (Sonnet)

**Read list:** this plan's I3, I5, I6; `discjockey/hub/views.py` lines 1–42, 482–492 (`track_row`), 823–905
(`playlists`, `playlist_change`); `tests/test_hub_views.py` (`grep -n "def test_.*playlist"`, helpers); `docs/issues.md`
issue 25. No other files.

### 4.1 Rows and the tidy preview
- `views.tidy_row(row: TidyRow, e: dict, cover) -> dict` (I5 `TidyRowJSON`; `by_rename` given by the caller),
  `views.skip_text(reason, detail, *, to, old=None, new=None) -> str`, `views.tidy_preview(rows, state, cover) ->
  dict`, `views.folder_of(path) -> str` (`Library/F/x` → `F`, `Library/x` → `""`).
- Tests: every I6 skip text; ticks and `yours` by `placed_by`; `empty` text when there are no rows.

### 4.2 Batches and results
- `views.move_batches(rows: list[BatchRow], total) -> dict`, `views.batch_title(b)`, `views.batch_result(r:
  BatchResult, title) -> dict`, `views.undo_preview(batch: BatchRow, moves: list[PlannedMove]) -> dict` (`U_WARN`,
  `U_RENAME` for a folder batch, `nothing_left` when no move can run).
- Tests: titles per `started_by`; summary singular/plural with and without skips; result headlines.

### 4.3 The save preview
- `playlist_change` gains `library_dirs: Collection[str]` and `rename_offer: Callable` (the api passes
  `tidy.rename_offer`, so views stays pure and testable without group 3); drops `moves`; builds `tidy` from
  `tidy_rows(state, placement(new…), only=retargeted)` (the api passes both maps) with `SAVE_HEADLINE`; `renames`
  with `offered`/`why_not`/`files` (files under `Library/<old>/`); `by_rename` on rows the rename covers (src under
  `Library/<old>/`, dst the same path under `Library/<new>/`). Checklist per I6; delete `CHECK_CUES`.
  `playlists()` gains `tidy.waiting`.
- Tests (`tests/test_hub_views.py`): reorder → `tidy` rows and headline; rename → offered, and `folder_taken`; a
  switch-off → no `tidy`; checklist per kind.
- Remove issue 25's "Stage 1 interim" bullet in the same commit.
- Checks while working: `uv run pytest -q tests/test_hub_views.py tests/test_hub_api_playlists.py`.

## Group 5 — Bridge (Sonnet)

**Read list:** this plan's I4 (group 3), I5, I6; `discjockey/hub/api.py` `grep -n "@bridge" -A2`, lines 660–672
(`_single`), 728–800 (playlists methods), 927–942 (`rescan_library`), and where `LIBRARY_METHODS` is defined;
`discjockey/hub/jobs.py` lines 29–45 and `start`; `docs/hub-bridge-contract.md` headings, then the sections of
`preview_playlist_change`, `save_playlists`, `rescan_library` and Events; `hub-ui/src/lib/bridge/types.ts` (`grep -n
"save_playlists\|ChangePreview\|JobResults"`), `contract.ts`, `fake/bridge.ts` lines 620–730; `tests/test_hub_api_playlists.py`
and `tests/test_hub_api_write.py` (`grep -n "def test_"`, helpers). No other files.

### 5.1 Events and job kinds
- `MovesProgress` reaches the window like the other engine events (*check first:* `event_dict` needs nothing new);
  job kinds `tidy`, `undo_moves`; `JobResults` types for them and the new `save_playlists` result.

### 5.2 Read methods
- `tidy_preview`, `move_batches`, `undo_preview` per I5 (state via `self._state()`, batches via `db.batches` in a
  `with db.connect(...)`; a library without `library.db` yet answers empty lists). `preview_playlist_change` passes
  `library_dirs` (names of the direct folders of `Library/`), `placement`, `retargeted` and `tidy.rename_offer`.
  `playlists()` passes `planner.out_of_place(state)`.

### 5.3 Write methods
- `tidy_up(moves)`, `undo_moves(batch_id)` as write jobs; `save_playlists(lines, loaded_version, files=None)`:
  `pf.save`, then (when `files`) `tidy.after_save` with `retargeted` computed in the job from the rows before the save
  and the hub's last playlists read; `mark_stale` as today. Malformed `moves`/`files` answer `ok: false, kind:
  "refused"` before a job starts. All new methods in `LIBRARY_METHODS` (api and `contract.ts`).
- Tests: each job runs on a `tmp_path` library and returns its result shape; busy answer; `save_playlists` with
  `leave` and with `move`; a malformed `moves` refused.

### 5.4 Contract and fake backend
- `docs/hub-bridge-contract.md`, `types.ts`, `contract.ts` per I5, one example each, in the same commit as the api.
- Fake backend (`fake/bridge.ts` and a new `fake/tidy.ts`): rows derived from the fake tracks (out-of-place tracks
  where `folder` isn't their first playlist's), at least one `user` row, one `name_taken`, one `offline`; batches kept
  in `FakeState`; `tidy_up`/`undo_moves` jobs emit `MovesProgress` and update the fake tracks; `undo_preview` with one
  `moved_on`. Hooks a page scenario can switch: a failing move, a stopped batch, no rows. *Check first:* how
  `fake.test.ts` pins the base fake, and extend it.
- Checks: `uv run pytest -q tests/test_hub_api_playlists.py tests/test_hub_api_write.py tests/test_hub_events.py
  tests/test_docs_links.py`, `npx vitest run src/lib/bridge`, `npm run check`.

## Group 6 — Playlists page (Opus, a page task)

Loads the `apple-design` and `emil-design-eng` skills first. CLAUDE.md §12 lets it improve the design, keeping the
I6 words, the frames and blocks (`docs/hub-design-language.md`) and structured controls; it shows the orchestrator a
before/after of the change panel before a change that alters the page's layout.

**Read list:** spec §8.2–§8.4; this plan's Parked, I5, I6; `hub-ui/src/pages/playlists/` (all of `Page.svelte`,
`ChangePanel.svelte`, `changeModel.ts`, `fake.ts`; `grep -n "name" shots.json`); `docs/hub-design-language.md`
headings and the sections of the blocks it uses; `hub-ui/src/lib/bridge/types.ts` (the I5 types). No other files.

### 6.1 `tidyModel.ts` (pure, with `tidyModel.test.ts`)
- Tick state per `file_id` (defaults from `ticked`; skipped rows can't be ticked), the count line `C` from the
  ticked rows (pairs by `from`/`to`), the confirm label, hiding `by_rename` rows when the rename is chosen, the
  `moves` list the bridge gets (`[file_id, from_path]`).

### 6.2 The save question (change panel)
- For `moves`/`rename` kinds: `SAVE_HEADLINE`, the file list (from → to, checkbox, "You put this here", skipped rows
  with their reason and no checkbox), the warning (`C`, `R1`, `R2`, `U1`) above the buttons, the two save buttons,
  and "Rename the folder on disk too" where `offered` (or its `why_not`). The old `moves` view goes.

### 6.3 Tidy up files
- The **Tidy up files** button (with `tidy.waiting` when > 0), the preview (same list and warning; empty text),
  **Move N files**, progress from `MovesProgress`, the result with its "not moved" list.

### 6.4 Recent moves and undo
- The batch list (title, when, summary, **Undo** or "Nothing left to undo"), the undo confirmation from
  `undo_preview` (`U_WARN`/`U_RENAME`, rows that will be skipped), the result.

### 6.5 Fake scenarios and screenshots
- Scenarios in `fake.ts` (`?scenario=playlists:<name>`): `tidy-mixed` (ticked, "You put this here", `name_taken`,
  `offline`), `tidy-many` (about 40 rows across 4 folders), `tidy-empty`, `rename-offered`, `rename-taken`,
  `batches` (an undoable one, one with nothing left, an undo batch), `undo-skips` (each undo reason), `move-fails`
  (the result lists a failed and a stopped file). Shots in `shots.json` for each, light and dark for `tidy-mixed` and
  the save question; the agent takes them in fake mode and looks at each before reporting.
- Checks: `npx vitest run src/pages/playlists`, `npm run check`, `npm run rules -- --page playlists`,
  `npm run build` (commit `hub/static`).

## Group 7 — Docs (Sonnet)

**Read list:** this plan's Parked, I6; `README.md` headings and the sections on how the sync places files and on the
Playlists page; `CLAUDE.md` Layout and Invariants; `docs/issues.md` issue 25. No other files.

- **README:** a "Tidying up files" section: the sync never moves files; the save question; the button; the preview
  (ticks, "You put this here", skipped rows); renaming a folder on disk; undo and its limits; the console line. Plain
  English, README's tone; finish stage 1's sentence that points at Tidy up.
- **CLAUDE.md Invariants**, the names bullet becomes (spec §8.3, binding): "**Names in `Library/` are always
  `Artist - Title.<ext>`** for files Discjockey downloads or adds — no `(v2)`, `(new)` or similar suffixes; those
  exist only in `Superseded/`. The one exception: a file that is in the way of the correct name gets an ID added.
  **Moving never renames:** a tidy-up and its undo keep each file's name as it is, because rekordbox's Relocate finds
  files by name." New bullet: "**Files move only in a move batch the user started** (tidy-up, the Playlists save
  question, a folder rename on disk): logged in `library.db`, undoable; the sync never moves a file (option A)."
  Layout: a row for `discjockey/tidy.py`; `db.py`'s row mentions the move log.
- **`docs/issues.md`** issue 25: add "Tidy-up covers only files in `Library/`; stage 4 extends `tidy_rows` and the
  runner to import folders, staging across drives."
- Checks: `uv run pytest -q tests/test_docs_links.py tests/test_docs_citations.py`.

---

## Stage checks

- **Per group:** its named test files while working; once at the end `uv run pytest -q | tail -3`. New test files:
  `tests/test_db_moves.py`, `tests/test_tidy.py`, `hub-ui/src/pages/playlists/tidyModel.test.ts`.
- **Spec §13 "Tidy-up" pinned by:** targets (2.1–2.2), default ticks by placed-by (2.2), skipped rows (2.2, 3.2), a
  crash mid-batch (3.5), undo with each skip reason (3.3).
- **Reviews:** a Sonnet review per group (its tasks, I1–I6, CLAUDE.md's invariants); one Opus review of stages 1+2
  against spec §5–§8 before the merge. **CI:** push `feat/library-2-tidy-up`, read `gh run list` only.
- **Screenshots** (group 6, fake mode): the 6.5 scenarios; the orchestrator looks at `tidy-mixed`, the save question
  and `undo-skips` itself, then runs `npm run verify` once in the background before the merge.
- **Before the live check,** the orchestrator runs a tidy-up and an undo on a scratch copy (`DISCJOCKEY_SUPPORT`
  scratch, never the user's library) and reads the report and `library.db`'s batch rows.

### Live check for the user (rekordbox after a tidy-up and after an undo)

The orchestrator first makes a test copy (two small playlist folders, about 10 tracks) and starts Discjockey on it
with a scratch support folder. Your real library is never touched.

1. In rekordbox, drag the test music folder into **Collection**, so its tracks are in rekordbox.
2. Pick two of the test tracks and set a hot cue on each.
3. In Discjockey (the test copy), open **Playlists**, drag the second playlist to the top, and click **Save**.
4. Read the warning above the buttons. Choose **Save and move the files**, leave the ticks as they are, and confirm.
5. In rekordbox, look at the moved tracks. Note whether they show as missing (a red mark) or still play.
6. If they show as missing: select them, right-click, choose **Relocate**, and point it at the test music folder.
   Note whether rekordbox finds them, and whether your two hot cues are still there.
7. In Discjockey, under the recent moves on the Playlists page, click **Undo** on that tidy-up and confirm.
8. Do steps 5 and 6 again in rekordbox.
9. Tell the orchestrator: did the tracks show as missing after the move and after the undo, did Relocate find
   them, were the hot cues kept, and did the warning's words match what you saw?
10. In rekordbox, remove the test tracks from the collection (**Remove from Collection**; this doesn't touch any
    file). The orchestrator deletes the test copy afterwards.
