# Library stage 4 "Import" — plan

Spec: `docs/2026-10-23-library-and-sources-design.md` §10, with §2, §3.3, §5.2, §5.5 (code boundaries), §6.3 (new
files, copies), §6.4 (offline), §7 (upgrades where the file is, mirrored `Superseded/`), §8.1/§8.3 (tidy-up targets),
§12 (unreadable files) and §13 ("Import", "UI", the live check). Leftovers: `docs/issues.md` #25. Orchestration:
`docs/2026-10-23-library-and-sources-orchestration.md`. Builds on `main` 0eb148b; branch `feat/library-4-import`.

**Goal:** folders of the user's own music (Setup, Settings → Watched folders) are imported in place: indexed, sound
judged, linked when certain, asked about when plausible; To-do shows questions and duplicates; lossy files get
upgrade checks spread over runs; import files tidy into `Library/` and back, across drives.

**Architecture.** The scan already inserts every new file of an import folder as an unlinked row (`placed_by
'import'`). The import is a hub write job (`importer.run_import`) that works through those rows in two passes,
recording each file's progress on its own row (`files.import_state`), so a stopped import resumes by construction:
pass 1 reads tags and creates a **song of its own** per file (key `local:<n>`); pass 2 judges the sound. Linking is
one pure module, `identify.py`, that the planner calls on every plan, so a playlist added months later still finds
the user's files; the import ends with a "link only" plan and save (no downloads). Questions and same-song duplicates
come out of the plan, same-audio duplicates out of the database, answers go into a new `decisions` table. Moves the
import needs (tidy-up from another drive, a duplicate to `Superseded/`) go through a new file-level journal with
**cross-drive staging**; the tidy-up's file moves leave the entry view.

**Schema step 2 → 3** (`SCHEMA_VERSION = 3`, through `db._upgrade` like stage 2's). *Why:* new columns and a table.
No released version reads `library.db` (stages 1–4 ship together), so no released reader needs fencing off, but every
library a stage 1–3 build opened is at version 2 (the maintainer's live-check libraries, fixtures, scratch folders)
and would fail on the first query without the step. A stage-3 build opening version 3 stops with `db.NEWER`.

---

## Global constraints

- **Never delete or overwrite a music file.** The import only reads files (spec §1: no copy, move, rename or
  re-tag). A cross-drive move removes its source only after the verified copy is in place: the second half of a
  move, never a delete of the only copy (I7). Duplicates go to `Superseded/`.
- **Every file change goes through the journal**: `library.run_op` (entry view) or `library.move_files` (I7). No
  new path renames a file directly.
- **Qobuz protection stays on.** Upgrade checks of imported files are ordinary `upgrade` actions through
  `Acquirer._try` (pacing, the daily limit with carry-over, the auto-stop). The first-check cap (I4) only plans
  *fewer* of them; nothing skips a guard.
- **`planner.py`, `identify.py` and `hub/views.py` stay pure; only `db.py` writes SQL.** New writers (importer,
  folders, decisions, duplicates) use explicit `db` functions, never `db.snapshot` + `db.save`.
- **Never save a stale snapshot.** The snapshot carries `generation` (I2); explicit song/file writes bump it;
  `db.save` of an older one raises `StateError(STALE)`. *Why:* the save diffs paths against the rows, so a stale
  entry would silently move a row back to where the file used to be.
- **One writer at a time.** The import is a write job (`Jobs.start("import", …)`) under the library lock. Every
  other write meanwhile answers `busy` with W7. The console never imports (W10).
- **Offline is not gone** (§6.4): offline folders keep their rows. The importer skips their waiting rows (they wait
  until the drive is back). Duplicates and questions leave offline files out.
- **Words** are binding as given in I12. **Tests offline**, `tmp_path` libraries only. Two drives are simulated by
  monkeypatching the device test (I7), never by a real second volume. **Public repo:** `scripts/check_public.sh`
  before every commit. Fixtures use made-up names (`Example Artist`, `/Volumes/Example/Music`).

## Decided here (with reasons)

- **D1. Two passes, not one per file.** Pass 1 (tags, own song, codec) runs over every waiting file before pass 2
  (the sound check). *Why:* the sound check decodes the whole file (hours for 10,000 files), tags take milliseconds;
  a sync after a stopped import then already knows which songs the user has. Until pass 2, quality is provisional
  from the codec (lossless codec → `lossless`, else `not_lossless`), upgrade checks wait, and the Library shows W6
  `NOT_CHECKED`.
- **D2. Linking lives in the planner** (`identify.py` from `planner.plan`), not the importer. *Why:* a playlist
  added after the import must find the files the same way; one pure rule set. The import's last phase runs it (D6).
- **D3. "Plausible" is two cases** (spec §10.3): (a) same normalised title, different or missing artist, length
  within 2 s; (b) same artist and title, length off by 2–10 s. *Why:* title-only matches up to 10 s ("Intro") would
  flood To-do. At most one question per playlist song (nearest length) and per own song.
- **D4. A plausible match holds that playlist song's download until the answer** (W8, W9). *Why:* a "Yes" would
  otherwise leave two copies and waste Qobuz quota. "No, keep them apart" releases it to the next sync.
- **D5. ISRC links keep the 3-second check** (`SAME_LENGTH_MS`, stage 3 D4), own songs too; two different ISRCs
  are two recordings, never matched by name.
- **D6. The import ends by linking:** it plans from the hub's last read (`PreviewStore`, else it reads the
  playlists) and saves only the plan's song changes, as a sync does before its first download; no downloads. A read
  problem leaves linking to the next sync (W11).
- **D7. One file per song stays the rule.** A copy (same content key) becomes its own song and a same-audio
  duplicate; an own song certainly matching a playlist song that has a file is a same-song duplicate, not a second
  linked file. *Why:* the entry view (`_linked`) assumes one file per song; the lower id would silently win.
- **D8. Own songs on To-do only under Upgrade ready, the questions and Duplicates**, never Weak/Good lossy/Fake.
  *Why:* thousands of imported lossy files would bury the playlist to-dos; the Library shows their quality.
- **D9. First upgrade checks are capped per run:** at most `FIRST_CHECKS_PER_RUN = 25` and at most half of today's
  Qobuz allowance left (`Budget.remaining() // 2`; 25 when Qobuz is skipped); playlist songs' first, by playlist
  order, then own songs' by `first_seen`. A first check = an `upgrade` for an entry with no `last_upgrade_check`.
  *Why:* §10.5; at ~70 s per check 25 add half an hour, and half the allowance stays for playlist downloads. Check
  first: a lossy download gets `last_upgrade_check` at acquisition (`planner.apply_outcome`); if not, count only
  entries whose file is `placed_by` `import`/`user`.
- **D10. "Move to Superseded" is like replacing a file:** journaled, logged in `reports/operations.jsonl`
  (`ops.log_operation`), no move batch, no undo; `Superseded/`'s suffix rule applies. *Why:* a user-started
  replacement, as "Add as new file", covered by "replaced files move to Superseded/". If the moved file was a
  playlist song's and the other an own song's, the other takes over the playlist song (nothing downloads again).
- **D11. Watched folders never nest.** A folder inside the music folder or a watched folder, or holding the music
  folder, is refused (W5). One that contains import folders **merges** them (rows re-homed with prefixed paths, song
  links kept, their `watched_folders` rows gone). *Why:* closes #25's inner-watched-folder item; keeps every link.
- **D12. Removing a folder** drops its file rows and own songs left with no file (a parked upgrade's file stays in
  `Upgrades ready/`); playlist songs left with no file get `file_gone` today (downloaded at the next sync, rule 2),
  and W4 counts exactly those. Decisions naming its files go.
- **D13. No import from the console:** `discjockey` scans and prints W10. *Why:* an import takes hours and needs
  the window's progress and Stop; the console can't add folders either.
- **D14. The import starts by itself** after Add folder and when the window opens with files waiting (after the
  opening scan, no other job running); after Stop only on the next window open or "Continue import". *Why:* a Stop
  holds for the session.
- **D15. An imported file's source is `manual`** (as `db.set_quality` does). *Why:* no new `Source` value for the
  UI; `placed_by` still says who placed it.

## Review focus (per-group review and the stage review)

1. The import writes no file; every move goes through `run_op` / `move_files`; a cross-drive source goes only after
   the verified copy is in place, and every crash point recovers (I7's table).
2. A stopped import resumes with no file done twice or skipped; an unreadable file is listed and retried next time.
3. Certain / plausible / own song as D3/D5; no plausible song downloads before the answer; "No" is never re-asked.
4. No stale snapshot is ever saved (the generation test); tidy's file moves write no entry view.
5. Imported files' upgrade checks keep D9's cap, go through `_try`, and wait for pass 2.
6. Bridge methods never reject; every user-facing word is I12's.

---

## Interfaces (fixed here; groups build against them)

**I1. Schema step 2 → 3** (`db.SCHEMA_V3_STEP`, one statement per item, as `SCHEMA_V2_STEP`):

```sql
ALTER TABLE files ADD COLUMN import_state TEXT
  CHECK (import_state IN ('new', 'identified', 'done', 'unreadable'));  -- NULL: not an import file
ALTER TABLE files ADD COLUMN import_error TEXT;   -- the reason words of an unreadable file
CREATE INDEX files_import ON files (folder, import_state);
CREATE TABLE decisions (kind TEXT NOT NULL CHECK (kind IN ('same_song', 'keep_both')),
  a TEXT NOT NULL, b TEXT NOT NULL, answer TEXT NOT NULL, at TEXT NOT NULL, PRIMARY KEY (kind, a, b));
INSERT INTO meta (key, value) VALUES ('generation', '0');
```

`same_song`: a = the playlist song's key (its track token while it has none), b = the own song's key, answer `same` |
`not_same`. `keep_both`: a = the group id (I5), b = `''`, answer `keep`. Pins: v2 upgrades with rows unchanged.

**I2. Snapshot additions** (`db.snapshot`; read-only keys go in `SNAPSHOT_ONLY` / `READ_ONLY`):
- per entry: `import_state` (the linked file's, or None), `first_seen` (the file's);
- top level: `generation: int`, `decisions: {"same_song": [[a, b, answer], …], "keep_both": [group_id, …]}`.
- `db.save` raises `disk.StateError(STALE)` when `state["generation"]` differs from the stored one. Otherwise it
  writes, bumps the stored value and sets `state["generation"]` to it (so one writer keeps saving its own state).
  Every explicit writer in I6, plus `apply_scan`, `finish_move`, `set_placed_by` and `set_quality`, bumps it in its
  transaction. Check first: every caller of `scan_library` / `apply_scan` takes its snapshot after the scan
  (`run._open`, `tidy._begin`, `ops.run_single`, `hub/api.py`). Fix any that doesn't; the test suite will show them.

**I3. `discjockey/identify.py`** (new, pure):

```python
Match = Literal["certain", "plausible"]
def compare(artist: str, title: str, duration_ms: int | None, isrc: str | None,
            own: Mapping) -> tuple[Match, str] | None   # (match, why: "isrc"|"name"|"artist"|"length")
def own_name(tags: Mapping[str, str | None], file_name: str) -> tuple[str, str]   # (artist, title)
```

`compare` applies D3/D5: both ISRCs present → certain when equal and within `SAME_LENGTH_MS`, else None. Then names,
normalised as `planner._song_name` does (`matching.normalize_artist` of the first artist, `matching.normalize` of
the title). Certain: equal and ≤ 2000 ms. Plausible: D3 (a) or (b). An own song without a length is at most
plausible. A match on the tag's first artist only (the full artists differ, "Earth" against "Earth, Wind & Fire") is
never certain: it is plausible with `why` "artist". `own_name`: tags first; else a file name `Artist - Title` (split on the first spaced dash,
`matching._DASH`); else the stem is the title and the artist is `""`. Constants `CERTAIN_MS = 2000`,
`PLAUSIBLE_MS = 10000`.

**I4. Planner** (`planner.plan`):

```python
def plan(fetched, state, files, today, *, first_checks: int | None = None) -> Plan
@dataclass(frozen=True)
class Question:            # models.py
    song_key: str          # the playlist song's key, or its track token while it has none
    track: SourceTrack
    folder: str
    own_key: str
    file_id: int
    why: str               # "artist" | "no_artist" | "length"
    delta_s: int           # own length − track length, whole seconds (signed)
@dataclass(frozen=True)
class DuplicateGroup:      # models.py
    id: str                # "dup:" + "-".join(sorted file ids)
    why: str               # "same_audio" | "same_song"
    file_ids: tuple[int, ...]
```

`Plan` gains `questions: list[Question]`, `duplicates: list[DuplicateGroup]` (same-song only) and
`deferred_checks: int`. Own songs are entries whose key starts with `local:` (`models.is_own(key)`). Rules, in plan
order:
1. `_resolve` keeps token → ISRC → name. For a track left with no song, a new step before "new song": an own song
   `compare`s certain, or a stored `same` answer names it → the track links to it (its token becomes an alias, with
   a note, exactly like the ISRC step). Plausible and not answered `not_same` → a `Question`, and the song is wanted
   but held.
2. A wanted stored song with no file (rule 2): an own song certain (or answered `same`) → **merge**: the playlist
   song's entry takes the own song's file fields and the own entry is removed from `tracks`. `db.save` then moves
   the file row to the playlist song. **`_save_files` change:** a row found at the new place in an *import* folder
   keeps its `placed_by` (today it becomes `app`). Plausible → `Question`, held (no `acquire`).
3. A wanted song with a file: own songs that `compare` certain → a `same_song` `DuplicateGroup` of the two file
   ids, unless its id is in `decisions.keep_both`.
4. Own songs not wanted, online, not held, with a lossy file and `import_state == 'done'` → `upgrade` action, its
   track `models.track_of(key, e)` (moved from `ops.track_of`; `ops` imports it), folder `""`, order
   `(len(fetched), n)` by `first_seen`. Check first: that the acquirer's upgrade path doesn't use `Action.folder`
   for anything but placement of new files (stage 1 §7 puts a "new file" next to the current one).
5. Every `upgrade` for an entry with `import_state` not in (None, `done`) is left out. Then the D9 cap: first
   checks beyond `first_checks` (after sorting) are dropped and counted in `deferred_checks`. `None` means no cap
   (tests, dry runs).

`run.prepare` / `run.replan` pass `first_checks=run.first_check_room(state, settings)` (D9).
`run.link_only(paths, prep, emit)` saves `replan(prep).plan.state` and nothing else. Check first: reuse the save
`execute` makes before its first action; don't write a second one.

**I5. Duplicate groups from the database** (`db.duplicate_groups(conn) -> list[DuplicateGroup]`): online, not held
files sharing a `content_key`, why `same_audio`, minus decided ids; covers #25's "two new files with the same unknown
key" and §6.3's copies. Views merge them with `Plan.duplicates`; a pair in both shows once, as `same_audio`.

**I6. New `db` functions** (each one transaction, each bumps `generation`):
- `import_waiting(conn) -> list[ImportRow]` (rows with `import_state` `new`/`unreadable` in online import
  folders; `ImportRow(file_id, path, folder, state)`, path absolute), `import_counts(conn) -> dict[folder_id,
  ImportCounts(files, waiting, identified, unreadable)]`.
- `add_own_song(conn, file_id, facts: OwnFacts) -> str` (key `local:<n>`, n = 1 + the highest used; `OwnFacts`:
  artist, title, album, isrc, duration_ms, codec, status). Sets the row's `song`, `status`, `source='manual'`,
  `source_format`, `import_state='identified'`, `import_error=NULL`. A row that has a song already is left alone.
  Returns the key.
- `set_sound(conn, file_id, status, cutoff_hz, source_kbps)` → `import_state='done'`.
- `set_unreadable(conn, file_id, reason)` → `import_state='unreadable'`, `import_error=reason`.
- `add_watched_folder(conn, path, now) -> AddedFolder(id, merged: list[str])` (D11 merge inside);
  `removal_counts(conn, folder_id) -> RemovalCounts(files, redownload)`;
  `remove_watched_folder(conn, folder_id, today) -> RemovalCounts` (D12; the `library` folder is a ValueError).
- `set_decision(conn, kind, a, b, answer, now)`; `decisions(conn)` (for the snapshot).
- `duplicate_groups(conn)` (I5); `group_files(conn, group_id) -> list[DupFile]` (`file_id, song_key, path,
  status, cutoff_hz, source_format, online, in_playlists`).
- `add_pending(conn, op) -> str` / `drop_pending(conn, op_id)`: the op JSON carries `op_id` (uuid4 hex), and
  `drop_pending` deletes by `json_extract(op, '$.op_id')`.
- `finish_file_op(conn, op)` in **one** transaction: by `op["do"]`, `tidy_move` → the body of `finish_move(op["ref"])`;
  `supersede` → delete the file row `op["ref"]`, then the heir rule of D10 (`op["heir"]`: that row's song becomes
  the moved row's song and its own song is deleted); own songs left with no file are deleted. Then drop the pending
  row. Refactor `finish_move` into a transaction-free `_finish_move` that both use.
- `apply_scan` changes: new rows in an import folder get `import_state='new'`; a gone row whose song is own deletes
  that song. Copies too get `'new'` (D7: a copy is its own song).

**I7. The journal across drives** (`library.py`):

```python
def move_files(paths, do: Literal["tidy_move", "supersede"], renames: list[tuple[str, str]], *,
               ref: int, heir: int | None = None, label: str) -> None
```

Pending op: `{"kind": "files", "op_id", "do", "ref", "heir", "label", "renames": [[src, dst]], "staged": {i: path}}`;
steps `db.add_pending` → each rename → `db.finish_file_op`, no entry view. `recover_pending` recovers a `files` op's
renames as for `run_op`, calls `finish_file_op`, and then **replaces `state`'s contents in place** with a fresh
`db.snapshot`.

**One rename** (`library.move_path(root, src, dst, staged: str | None)`, used by `run_op`, `move_files` and both
recoveries): same device (`os.stat(src).st_dev` vs the nearest existing parent of `dst`) → `safe_rename` as today.
Other device → `staged = <dst's folder>/.<dst name>.discjockey-move` (recorded in the op **before** copying; not
an audio extension, so the scanner never sees it), then: copy src → staged, `full_fsync`, compare SHA-256, then
`safe_rename(staged, dst)` (refuses when dst exists) and `fsync_dir`. Only then unlink src. ENOSPC or any copy
error → remove staged, re-raise (callers word it with `tidy.failed_detail`). Recovery, per rename that crosses:

| src | staged | dst | Recovery |
|-----|--------|-----|----------|
| yes | any | no | remove staged; redo the move |
| yes | any | yes | dst's SHA-256 equals src's → unlink src (and staged) → done; else "both exist" as today |
| no | any | yes | done (remove a leftover staged) |
| no | yes | no | rename staged → dst when its size equals the recorded `size`, else "neither exists" (staged is kept) |

The op records `size` per crossing rename for the last row. `run_op` keeps its signature. Pins per row, plus a
crash after each step, simulated by monkeypatching `os.stat` devices.

**I8. The importer** (`discjockey/importer.py`, new; writer: the caller holds the lock):

```python
def run_import(paths, *, emit, token: CancelToken, link: Callable[[], str | None],
               read_tags=read_tags, probe=quality.probe, inspect=quality.inspect, now=datetime.now) -> ImportResult
@dataclass(frozen=True)
class ImportResult: files: int; own_songs: int; sound_checked: int; unreadable: int; left: int; stopped: bool
                    link_note: str | None
@dataclass(frozen=True)   # events.py, in jobs.EVENT_TYPES
class ImportProgress: phase: str; done: int; total: int; unreadable: int   # "scan" | "tags" | "sound" | "link"
```

Phases: `recover_pending` + `clear_tmp` + `scan_library` (`scan`) → pass 1 over `import_waiting` (`tags`:
`read_tags` (mutagen) → `identify.own_name` → `probe` → `add_own_song`; an error → `set_unreadable` with plain
words, never a traceback) → pass 2 over `identified` rows (`sound`: `inspect` → `quality.verdict` → `set_sound`) →
`link()` (`link`; W11 or None). `token.check()` before each file; a stop raises a `Cancelled` carrying the result
(like `tidy.Stopped`) after the current file is written. Progress at most every 25 files or 0.5 s. Earlier
unreadable rows are retried in pass 1 (this job's scan is §12's "next scan").

**I9. Folders and answers** (`discjockey/folders.py`, new; writers hold the lock):
- `check_import_folder(path, *, paths, support, program, home) -> FolderCheck` reuses `library.check_music_folder`'s
  system/support/app checks, plus W5's rules (D11), and fills `merges: list[str]` (`FolderCheck` gains `merges`,
  default `()`).
- `add(paths, path, now) -> AddedFolder`; `removal(paths, folder_id) -> RemovalCounts`; `remove(paths, folder_id)`.
- `answer_same_song(paths, song_key, own_key, same: bool)` → `set_decision`; `keep_both(paths, group_id)`;
  `supersede(paths, group_id, file_id, *, emit)`: re-reads the group (gone or changed → `OpProblem(CHANGED)`);
  target `planner.superseded_dir(path)` + `ops._superseded_name` (check first: that both handle absolute import
  paths as stage 1 §7 says); heir = the other file when the moved one is a playlist song's and the other is own's
  (D10); then `move_files("supersede", …)` and `ops.log_operation`.

**I10. Tidy-up for import folders:** `planner.tidy_target` also targets a file in an import folder (absolute
snapshot path) to `Library/<placement>/<name>`, unticked like any `import`/`user` row. `tidy._move_one`'s file branch
calls `move_files("tidy_move", [(src, dst)], ref=m.id, label=…)` (the op finishes the move); its folder branch takes
a fresh `library.open_state` right before `run_op`. Undo goes back across drives the same way.

**I11. Bridge** (hub ↔ UI; `docs/hub-bridge-contract.md`, `types.ts`, `contract.ts`, the fake, same commit):

| Method | Kind | Answer |
|--------|------|--------|
| `watched_folders()` | read, `LIBRARY_METHODS` | `{folders: WatchedFolderRow[], unreadable: {folder_id, path, reason}[], waiting: int, stopped: bool}` |
| `check_import_folder(path)` | read | `FolderCheck` (+ `merges`) |
| `removal_preview(folder_id)` | read | `{name, files, redownload}` |
| `add_watched_folder(path)` | write → job `import` | adds, then imports in the same job |
| `remove_watched_folder(folder_id)` | write → job `folders` | result `{files, redownload}` |
| `start_import()` | write → job `import` | "Continue import" |
| `answer_same_song(song_key, own_key, same)` | write → job `answer` | then replan |
| `keep_duplicates(group_id, paths)` | write → job `answer` | `paths`: the files as the card showed them (`changed` on any difference); then replan |
| `supersede_duplicate(group_id, file_id, paths)` | write → job `supersede` | `paths` as above; | `OpResult`-like `{result, recovered}` |
| `setup_skip_import()` | brief lock | `{ok}` (setting `import_skipped`) |

`WatchedFolderRow = {id, path, name, kind: 'library'|'import', state: 'online'|'offline'|'scanning'|'importing',
files, waiting, unreadable}`. The job `import` result: `ImportResult` as a dict. `stop()` stops it.
`todo()` groups gain `same_song` and `duplicate`; their items are `TodoItem & {pair}`:
`QuestionPair = {song_key, own_key, why, delta_s, track: {artist, title, duration_s, folder, link}, file: FileSide}`,
`DuplicatePair = {group_id, why, files: FileSide[]}`,
`FileSide = {file_id, song_key, path, artist, title, duration_s, quality, quality_label, online, audio_url,
in_playlist}`.
`TodoFilter` gains both keys. `sync_preview()` gains `waiting_answers: int`, `deferred_checks: int`.
`setup_status()` gains the step `existing` (after `music`; done when an import folder exists or `import_skipped`;
never blocks Continue). `library()` rows of a file whose `import_state` is `identified` carry `sound_checked:
false`. Busy for job kind `import`: W7.

**I12. Words** (binding; `views.py` / `jobs.py` / `folders.py` constants, the UI shows them as given):
- W1 Setup step `existing`: title **Your existing music**; Hint: "Add folders with music you already have.
  Discjockey indexes it where it is: nothing is copied, moved or renamed." Button **Add folder…**.
- W2 Settings row **Watched folders**; line: "Library only" · "{n} folders · {files} files" · "Importing ·
  {done} of {total}" · "{name} is offline".
- W3 Folder states: "Online" · "Offline: connect the drive" · "Checking for new files" · "Importing · {done} of
  {total}"; Library's row: "Your Library · always watched".
- W4 Remove: title "Remove {name}?"; "Discjockey forgets its {n} files. The files stay where they are."; when
  redownload > 0: "{m} songs from your playlists had their only copy there. They will be downloaded again at the
  next sync." (1: "1 song … had its only copy there. It will be …"); buttons **Remove folder**, **Cancel**.
- W5 Add refused: "This is inside your music folder, which Discjockey watches already." · "This folder holds your
  music folder. Choose a folder inside it instead." · "This is inside {other}, which Discjockey watches
  already."; merge Hint: "{other} is inside it and becomes part of it."
- W6 Import phases: "Looking for music files" · "Reading tags · {done} of {total}" · "Checking the sound · {done}
  of {total}" · "Linking to your playlists"; stopped: "Import stopped with {left} files to go. It carries on where
  it stopped." · button **Continue import**; done: "Imported {files} files." Couldn't read: header "Couldn't read
  ({n})", rows "{path}: {reason}", Hint "Tried again at the next import." `NOT_CHECKED` = "sound not checked yet".
- W7 Busy: "Discjockey is importing your music. Stop the import in Settings → Watched folders to do this now; it
  carries on later where it stopped."
- W8 To-do: groups `("same_song", "Is this the same song?", "a file of yours might be a playlist song")`,
  `("duplicate", "Duplicates", "the same song more than once")`, first in `TODO_GROUPS` after `rekordbox_check`.
  Question why: "Same title, different artist" · "Same title, no artist in your file" · "Same artist and title,
  {s} s longer" / "… {s} s shorter" · "Same artist and title, the length couldn't be read" (why `no_length`); note "Until you answer, Discjockey doesn't download this song."; buttons **Yes,
  it's the same song**, **No, keep them apart**. Duplicate why: "The same audio in {n} files" · "{n} files of the
  same song"; buttons **Keep both** (**Keep all** for n > 2), per file **Move to Superseded**; note "Nothing is
  deleted: the file goes to Superseded/."
- W9/W10 counts take a singular form for 1 ("1 song waits…", "1 file … waits…").
- W9 Sync preview Hints: "{n} songs wait for your answer on the To-do page." · "{n} first upgrade checks of your
  imported music wait for later runs, so today's Qobuz allowance isn't used up."
- W10 Console: "{n} files in your watched folders wait to be imported. Open the window to import them." · "{n}
  songs wait for your answer in the window (Is this the same song?)."
- W11 "Your playlists couldn't be read, so the imported files are linked to them at the next sync."
- Added by the groups (the UI shows them as given): W12 a folder row while the import runs: "Importing · {n} waiting"
  ("1 file waiting"), and Settings' Watched folders row shows the running phase line of W6 ("Reading tags · {done} of
  {total}"); W13 the remove dialog's body starts "This is the folder at {path}. " when another watched folder has the
  same name; W14 the Duplicates cards are labelled by the folder of each file (summary "In your playlists" on a
  playlist song's file); W15 Sync shows W9's hints as NoteCards, words unchanged.
- Added by the stage review's fixes: W16 Remove first finishes interrupted steps (recovery, as every writer), then is refused while a pending step still names a file in the folder: "Discjockey
  still has an unfinished change for this folder. Connect its drive and open Discjockey again, then remove it."; W17 a
  stopped change waits for a drive (recovery, and a scan it holds up), in two forms, one for all steps at once: the held form for every W17 line when any pending step holds the scan, the other only when none does. The scan is really held (a file of
  the step is in a folder that is there): "Couldn't finish a stopped change: the drive with {short path} isn't
  connected. Connect it; until then Discjockey doesn't look for new files." The scan of the other folders goes on
  (every file of the step is on the drive that is away): "Couldn't finish a stopped change: the drive with {short
  path} isn't connected. Connect it, and Discjockey finishes the change." (the path once, `~` for the home folder)

---

## Group 1 — The database (Opus)

**Read list:** this plan's Global constraints, D7, D11, D12, I1, I2, I5, I6; `discjockey/db.py` (lines 1–250
schema and constants, 280–340, 446–520 snapshot, 556–760 save and apply_scan, 800–860 finish_move); the outline of
`discjockey/models.py`; `tests/test_db.py` and `tests/test_db_migration.py` (outline + one fixture builder each).

Tasks:
1. **1.1 Step 2 → 3** (`db.SCHEMA_V3_STEP`, `_upgrade`, `SCHEMA_VERSION`): I1. Tests: a version 2 database (built
   by the existing fixture at version 2) upgrades; rows unchanged; a fresh `create` is at 3.
2. **1.2 Generation** (`snapshot`, `save`, `STALE` words: "Discjockey's records changed while this step was
   being prepared, so nothing was saved. Try again."): I2. Tests: save of a fresh snapshot passes and keeps
   saving; save after an explicit write raises and writes nothing.
3. **1.3 Snapshot keys** (`_entry`, `snapshot`, `SNAPSHOT_ONLY`, `READ_ONLY`): `import_state`, `first_seen`,
   `decisions`. Test: a stage-3 snapshot round-trips unchanged apart from the new keys.
4. **1.4 Import rows** (`import_waiting`, `import_counts`, `add_own_song`, `set_sound`, `set_unreadable`): I6.
   Tests: keys `local:1…` increase and never reuse after a delete; a row with a song is left alone; offline
   folders' rows aren't waiting.
5. **1.5 Folders** (`add_watched_folder`, `removal_counts`, `remove_watched_folder`): D11, D12. Tests: merge keeps
   song links and prefixes paths; a nested add or the library folder raises; removal counts exactly the playlist
   songs whose only file was there, sets their `file_gone`, deletes own songs, keeps playlist songs.
6. **1.6 Decisions and duplicates** (`set_decision`, `decisions`, `duplicate_groups`, `group_files`): I5. Tests:
   three files with one key form one group; a decided group is left out until a new copy changes its id; offline
   and held files are left out.
7. **1.7 Scan and save changes** (`apply_scan`, `_save_files`): I6's last item; I4 rule 2's `placed_by` change.
   Tests: new import-folder rows are `new`, Library rows NULL; a gone own song is deleted; a merge through `save`
   keeps `placed_by 'import'`.
8. **1.8 The file journal** (`add_pending`, `drop_pending`, `_finish_move` refactor, `finish_file_op`): I6. Tests:
   `tidy_move` equals today's `finish_move`; `supersede` with and without heir; all in one transaction (a
   failure leaves pending and rows as they were).

Checks while working: `uv run pytest -q tests/test_db.py tests/test_db_migration.py tests/test_db_moves.py
tests/test_library_scan.py tests/test_library_state.py tests/test_scanner.py`. At the end: the full suite.

## Group 2 — The journal across drives and the tidy-up (Opus)

**Read list:** Global constraints, D10, D11, I6 (journal items), I7, I10; `discjockey/library.py` lines 360–400
(fsync helpers), 453–645 (`run_op`, `recover_pending`); `discjockey/tidy.py` docstring and lines 117–290, 325–392,
450–506; `discjockey/planner.py` lines 22–154; the Group 1 diff of `db.py`.

Tasks:
1. **2.1 One rename** (`library.move_path`): I7 same/other device. Tests: same device = today; other device
   (monkeypatched `st_dev`) copies, verifies, renames, unlinks; ENOSPC leaves src and no staged; a SHA mismatch
   raises and keeps src.
2. **2.2 `run_op` crossing** (`run_op`, `recover_pending`'s rename loop): records `staged` and `size` before the
   copy. Tests: each row of I7's table after a crash at each step.
3. **2.3 `move_files`** (`library.move_files`, `recover_pending` `kind == "files"`, the in-place refresh): I7.
   Tests: a crash after the renames finishes on the next recovery; the refreshed state equals a fresh snapshot;
   `generation` stays consistent.
4. **2.4 Tidy's file moves** (`tidy._move_one`, `_run`, `tidy.recover`): I10. Tests: `tests/test_tidy.py` passes
   unchanged except where a test asserted the entry-view save; a batch mixing a folder move and file moves saves
   no stale state.
5. **2.5 Targets in import folders** (`planner.tidy_target`, `tidy_rows`): I10. Tests: an import file in a
   playlist targets `Library/<Folder>/<name>`, unticked; offline import → `offline`; a name taken → `name_taken`;
   an own song has no target.
6. **2.6 Cross-drive tidy and undo** (`tests/test_tidy.py`): a tidy from an "other drive" import folder into
   `Library/` and its undo, both through staging; undo's same-content-key rule still holds.

Checks while working: `uv run pytest -q tests/test_library_ops.py tests/test_library_state.py tests/test_tidy.py
tests/test_planner.py tests/test_db_moves.py tests/test_swap.py tests/test_upgrades.py`. At the end: the full suite.

## Group 3 — Identifying and planning (Opus)

**Read list:** Global constraints, D2–D9, I3, I4, I5; `discjockey/planner.py` (whole, 426 lines);
`discjockey/matching.py` lines 1–60; `discjockey/models.py` lines 1–175; `discjockey/run.py` lines 74–180;
`discjockey/ops.py` lines 117–123 (`track_of`); `discjockey/pacing.py` lines 33–80.

Tasks:
1. **3.1 `identify.py`**: I3. Tests (`tests/test_identify.py`): every row of D3/D5, including ISRC conflict, a
   missing artist, a missing length, `feat.` and `(Original Mix)` normalising; `own_name`'s three sources.
2. **3.2 Records** (`models.Question`, `DuplicateGroup`, `is_own`, `track_of` moved, `Plan` fields): I4.
3. **3.3 Linking new tracks to own songs** (`planner._resolve`): I4 rule 1. Tests: certain → alias with a note;
   plausible → question and no acquire; `not_same` → acquire; `same` → link; one question per song and per own
   song.
4. **3.4 Missing songs and duplicates** (`planner.plan`): I4 rules 2–3. Tests: a missing playlist song merges an
   own song (the own entry gone, its file fields on the song, nothing acquired); a song with a file gets a
   same-song group; `keep_both` hides it.
5. **3.5 Upgrade checks for imported files** (`planner.plan`): I4 rules 4–5, D9. Tests: own lossy `done` → one
   upgrade; `identified` → none; the cap keeps playlist first checks first and counts `deferred_checks`; `None`
   means no cap.
6. **3.6 Run** (`run.prepare`, `run.replan`, `run.first_check_room`, `run.link_only`, the console lines in
   `console.py`): W9/W10 counts reach `Prepared`. Tests (`tests/test_run.py`, `tests/test_console.py`): the cap
   from a Budget fixture; `link_only` saves links and downloads nothing; W10 printed only when counts > 0.

Checks while working: `uv run pytest -q tests/test_identify.py tests/test_planner.py tests/test_models.py
tests/test_run.py tests/test_console.py tests/test_apply_outcome.py tests/test_execute.py`. At the end: the full
suite.

## Group 4 — The import job, folders and answers (Opus)

**Read list:** Global constraints, D1, D6, D10–D15, I6, I7 (the `move_files` signature), I8, I9, W5, W6, W11;
`discjockey/quality.py` (whole, 138 lines); `discjockey/library.py` lines 645–780; `discjockey/events.py`
outline; `discjockey/ops.py` lines 1–110, 219–240; `discjockey/tidy.py` lines 55–72 (`Stopped`); the Group 1–3
diffs' new signatures only.

Tasks:
1. **4.1 Tags** (`importer.read_tags`): mutagen's easy tags (artist, title, album, isrc), any format of
   `AUDIO_EXTS`; missing tags → None. Tests with `tests/audio_helpers.py` files (tagged and untagged).
2. **4.2 `run_import`** (`importer.py`): I8 phases, two passes (D1), progress pacing. Tests
   (`tests/test_importer.py`): a folder of five files → five own songs, each `done`; provisional status from codec
   after pass 1; `NOT_CHECKED` state reachable.
3. **4.3 Stop and resume**: a stop after file 3 of pass 1 and one during pass 2; the next run does each remaining
   file once (count the `probe`/`inspect` calls). An unreadable file is listed, then retried and done next time.
4. **4.4 Offline and gone mid-import**: a folder offline at the start keeps its waiting rows; a file gone between
   scan and pass 1 → its row is left for the next scan (not unreadable).
5. **4.5 Folders** (`folders.check_import_folder`, `add`, `removal`, `remove`; `FolderCheck.merges`): I9, W5.
   Tests (`tests/test_folders.py`): each refusal, a merge, removal counts.
6. **4.6 Answers and duplicates** (`folders.answer_same_song`, `keep_both`, `supersede`): I9, D10. Tests: a
   supersede within one drive and across drives (monkeypatched device), with the heir rule, the operations log line,
   and a changed group refused.
7. **4.7 Event** (`events.ImportProgress`, `jobs.EVENT_TYPES`): `tests/test_events.py`.

Checks while working: `uv run pytest -q tests/test_importer.py tests/test_folders.py tests/test_events.py
tests/test_library_scan.py tests/test_quality.py`. At the end: the full suite.

## Group 5 — Hub wiring and the contract (Sonnet)

**Read list:** Global constraints, D4, D6, D8, D13, D14, I11, I12; `discjockey/hub/jobs.py` lines 160–260,
299–520, 543–676; `discjockey/hub/api.py` lines 55–110, 212–340, 483–560, 904–975, 1026–1123, 1254–1310,
1513–1576; `discjockey/hub/views.py` lines 600–760, 769–803; `docs/hub-bridge-contract.md` (the sections it
changes); `hub-ui/src/lib/bridge/types.ts`, `contract.ts`, `bridge/fake/` (outline, then the todo/settings/setup/
sync fixtures).

Tasks:
1. **5.1 Jobs** (`jobs.py`): job kinds `import`, `folders`, `answer`, `supersede`. `_busy` words per kind (W7 for
   `import`). `import_work(paths, store)`: `run_import` with `link` = replan from `store` (or `run.prepare` when
   it has no read) + `run.link_only` + `store.ready`. Answers end with a replan (`run.replan`) into the store.
   Tests `tests/test_hub_jobs.py`: busy words; a stopped import's `JobFinished.result.stopped`.
2. **5.2 Auto-start** (`api._attach`/the opening scan, `api.start_import`): D14. Check first where the opening scan
   runs (`jobs.scan_lock` callers). Tests `tests/test_hub_api_write.py`: starts after the opening scan when files
   wait; not after a Stop in the same session.
3. **5.3 Read methods** (`watched_folders`, `check_import_folder`, `removal_preview`; `views.watched_folders`): I11.
4. **5.4 Write methods** (`add_watched_folder`, `remove_watched_folder`, `answer_same_song`, `keep_duplicates`,
   `supersede_duplicate`, `setup_skip_import`; `setup_status` step `existing`): I11, never rejecting. Tests
   `tests/test_hub_api_music.py`, `tests/test_hub_api_setup.py`.
5. **5.5 Views** (`views.todo` with `questions`/`duplicates` arguments and D8, `todo_others`,
   `views.sync_preview` counts, `views.library` `sound_checked`, `TODO_GROUPS` W8): pure. Tests
   `tests/test_hub_views.py`: the pair shapes; a same-audio pair present in both sources shows once; own lossy
   songs absent from Weak.
6. **5.6 Contract** (`docs/hub-bridge-contract.md`, `types.ts`, `contract.ts`, `events.ts`): I11, `ImportProgress`.
7. **5.7 Fake backend**: the methods above plus scenarios `folders_importing`, `folders_offline`,
   `folders_couldnt_read`, `folders_library_only`, `setup_existing_empty`, `setup_existing_added`, `todo_same_song`,
   `todo_duplicates`, `todo_duplicates_three`, `sync_waiting_answers`. The fake's import advances
   `ImportProgress` on a timer and honours Stop.

Checks while working: `uv run pytest -q tests/test_hub_jobs.py tests/test_hub_api_write.py tests/test_hub_api_music.py
tests/test_hub_api_setup.py tests/test_hub_views.py tests/test_hub_events.py`; `cd hub-ui && npm run check && npx
vitest run src/lib/bridge`. At the end: the full Python suite.

## Group 6 — Settings → Watched folders and Setup's "Your existing music" (Opus, UI)

**Load the `apple-design` and `emil-design-eng` skills first**, then `docs/hub-design-language.md`; show before/after
shots to the orchestrator before design changes beyond this plan.

**Read list:** D11, D12, D14, I11, I12 (W1–W7); `hub-ui/src/pages/settings/` (Page, RowPanel, settingsModel +
test, shots.json); `hub-ui/src/pages/setup/` (Page, StepMusic, StepFooter, setupModel + test, shots.json);
`hub-ui/src/lib/stores/hub.ts`; the block catalogue (`#/dev/gallery`).

Tasks:
1. **6.1 The row** (`settingsModel.ts`): row `folders` in the first group, glyph, `rowLine` (W2), live counts from
   `$hub.job.last.ImportProgress`. Tests in `settingsModel.test.ts`.
2. **6.2 The panel** (`FoldersPanel.svelte` beside `RowPanel`): folders as aligned rows (name, path, W3 state,
   files); **Add folder…** (`pick_folder` → `check_import_folder` → W5 or add); phase line + Stop / **Continue
   import**; "Couldn't read (n)". Structured controls only, one filled button.
3. **6.3 Remove** (a confirm dialog from the existing dialog block): W4 from `removal_preview`.
4. **6.4 Setup step** (`StepExisting.svelte`, `setupModel.ts`): W1. The same add and list blocks as 6.2 (shared
   component, not copied); progress shown after adding; Continue always allowed; Skip = `setup_skip_import`.
   Tests in `setupModel.test.ts` (strip order, done rule).
5. **6.5 Shots** (`shots.json` of both pages): every scenario of 5.7 that belongs to these pages, at the three
   sizes.

Checks while working: `npm run check`, the touched `*.test.ts`, `npm run rules -- --page settings` and `--page
setup` on the new shots. At the end: `npm run build`.

## Group 7 — To-do cards and the Sync hints (Opus, UI)

**Load the `apple-design` and `emil-design-eng` skills first**, then `docs/hub-design-language.md`.

**Read list:** D4, D8, D10, I11, W8, W9; `hub-ui/src/pages/todo/` (Page, Details, WrongSongDialog, todoModel +
test, shots.json); `hub-ui/src/pages/sync/BeforeStart.svelte` and `planModel.ts`; `$lib/stores/player.ts`
outline.

Tasks:
1. **7.1 Model** (`todoModel.ts`): the two groups in the filter strip (under More if `FILTER_MAX` is reached),
   item keys from `song_key`/`group_id`, selection kept across reloads. Tests.
2. **7.2 Question details** (`QuestionDetails.svelte`): the playlist track and the file side by side, aligned
   (artist, title, length, where; the file's quality and ▶), why line, W8 note, the two buttons (one filled:
   **Yes, it's the same song**).
3. **7.3 Duplicate details** (`DuplicateDetails.svelte`): every file as a row (path, quality, ▶, **Move to
   Superseded**), **Keep both/all** in the foot, W8 note; a moved file's result through the usual job flow.
4. **7.4 Sync hints** (`BeforeStart.svelte`): W9 as `Hint`s under the plan's counts, linking to To-do.
5. **7.5 Shots** (`todo/shots.json`, `sync/shots.json`): `todo_same_song`, `todo_duplicates`,
   `todo_duplicates_three`, `sync_waiting_answers` at three sizes.

Checks while working: as Group 6, for `--page todo` and `--page sync`. At the end: `npm run build`.

## Group 8 — Docs (Sonnet)

**Read list:** this plan's D1–D15 and I12; `README.md` (its Library, To-do, Settings and Setup sections);
`docs/issues.md` #25; `CLAUDE.md` Layout table.

Tasks:
1. **8.1 README**: watched folders (adding, removing, offline, nothing moves on import), the import (progress,
   Stop, resume, "Couldn't read"), the two new To-do groups, upgrade checks spread over runs.
2. **8.2 `docs/issues.md`**: remove #25's cross-drive, same-unknown-key, tidy-up-for-import-folders and
   inner-watched-folder items. Narrow the entry-view item to what still uses it (the sync's `run_op` callers,
   `ops.py`, `upgrades.py`, folder moves). Add any leftover the groups reported.
3. **8.3 `CLAUDE.md` Layout**: rows for `identify.py`, `importer.py`, `folders.py`; the `library.py` row names
   `move_files`.

Checks: `uv run pytest -q tests/test_docs_citations.py tests/test_docs_links.py`; `scripts/check_public.sh`.

---

## Order and sizes

Groups 1 → 8, one at a time (2 and 3 need only 1; 4 needs 1–3; 6 and 7 need 5's contract and fake). Expected
changed lines with tests: G1 ≈ 900, G2 ≈ 800, G3 ≈ 900, G4 ≈ 1,000, G5 ≈ 1,300, G6 ≈ 900, G7 ≈ 800, G8 ≈ 150;
past 1,500 a group stops and reports.

## Stage checks

- **Python:** each group's files while working; the full suite once per group (`uv run pytest -q | tail -3`); CI
  on the stage branch push before the merge. Busy modules and their tests: `db.py` → `test_db*.py`,
  `test_library_scan.py`, `test_library_state.py`; `library.py` → `test_library_ops.py`, `test_library_state.py`,
  `test_library_scan.py`, `test_tidy.py`; `planner.py` → `test_planner.py`, `test_run.py`, `test_execute.py`,
  `test_apply_outcome.py`; `models.py` → `test_models.py`, `test_planner.py`.
- **Pins the stage review looks for:** I7's table with a crash at each step; the generation test (focus 4); resume
  counts (2); D3's cases and the held download (3); the D9 cap (5); `os.rename`/`shutil.move` only in `library.py`.
- **UI:** `npm run verify` once, by the orchestrator, in the background, before the merge. Screenshots in fake
  mode, looked at by the orchestrator: `node scripts/shots.mjs --port <p> --page settings` (`folders_library_only`,
  `folders_importing`, `folders_offline`, `folders_couldnt_read`, the remove dialog), `--page setup`
  (`setup_existing_empty`, `setup_existing_added`), `--page todo` (`todo_same_song`, `todo_duplicates`,
  `todo_duplicates_three`), `--page sync` (`sync_waiting_answers`), `--page library` (a `sound_checked: false` row).
- **Before the user's check, by the orchestrator:** a scratch run (`DISCJOCKEY_SUPPORT=<scratch> bin/discjockey
  hub`) with a scratch import folder of generated tones: add, stop, continue, remove, the To-do cards. No Qobuz.
- **Live check by the user — importing their own library, ~20 minutes plus the import itself.** Nothing downloads
  unless they start a sync. In the new build:
  1. Settings → Watched folders → **Add folder…**, a folder of their own music outside the music folder (ideally on
     another drive). *They see* the import start, its phase line counting up, the row's file count.
  2. **Stop** partway, then **Continue import**. *They see* it carry on where it stopped, not from zero.
  3. When done, the Library page lists their files; *they check* the quality of three or four tracks they know (one
     lossless, one MP3, one they suspect is fake).
  4. On To-do: one "Is this the same song?" with Yes, one with No, **Keep both** on one duplicate. *They see* each
     card leave; the Sync page shows no download for the Yes song or for songs they already had.
  5. In rekordbox, *they check* that the folder's tracks still play (nothing moved or renamed).
  6. On an external drive: eject it, return to the window. *They see* the folder offline, no new downloads for it.
  They report anything wrong and roughly how long the import took for how many files.
