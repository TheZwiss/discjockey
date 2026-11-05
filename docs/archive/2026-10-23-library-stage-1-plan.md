# Library stage 1 "Foundation" — plan

Spec: `docs/2026-10-23-library-and-sources-design.md` §5, §6, §7 (the spec). Orchestration:
`docs/2026-10-23-library-and-sources-orchestration.md`. Stage branch: `feat/library-1-foundation`. Stages 1 and 2
ship together (spec §4): this branch is merged into `main` together with stage 2's, never released alone.

**Goal:** the library's records move from `state.json` into `.discjockey/library.db` (songs, files, watched folders);
a scanner indexes `Library/` with content keys and finds files the user moved; the planner follows option A (it never
moves a file on its own, a moved file is not downloaded again).

**Architecture in one paragraph.** `db.py` owns the schema, the migration and every query. The engine keeps working
on the dict it knows today (the *snapshot*: `{"tracks": {key: entry}, "pending", "never", "qobuz_usage", …}`); `db.py`
builds that snapshot from the rows (one entry = a song joined with its file) and `library.save_state` writes back
only what changed, in one transaction. `run_op` keeps its shape. `scanner.py` walks the watched folders and returns a
`ScanResult` (no SQL); `db.apply_scan` writes it. `planner.py` stays pure and gets three new read-only facts per entry
(`online`, `placed_by`, `file_gone`) plus `state["ambiguous"]` and `state["files"]` (the index's online paths).

**Why keep the entry dict instead of rewriting the engine onto Song/File objects.** About 40 call sites in
`execute.py`, `ops.py`, `upgrades.py`, `run.py`, `report.py`, `hub/api.py`, `hub/views.py` and ~180 test lines work on
entries. Spec §5.4 asks that callers "change little". The snapshot is exactly the "plain snapshot" of §5.5, the
diffing save gives one transaction per step (§5.4), and the rows underneath already have the songs/files split that
stages 2–4 need. Later stages narrow the seam where they touch callers (noted in `docs/issues.md`, task 3.7).

---

## Global constraints

- **Never delete or overwrite a music file; every file change through `library.run_op`** (CLAUDE.md Invariants).
  The scanner only reads. `db.py` never touches music files.
- **Only `db.py` writes SQL** (spec §5.5). Other modules call its functions.
- **`planner.py` and `hub/views.py` stay pure** (no I/O, no clock).
- **SQLite settings (binding):** `journal_mode=WAL`, `synchronous=FULL`, `foreign_keys=ON`, `fullfsync=ON`,
  `checkpoint_fullfsync=ON`, `busy_timeout=5000`. `fullfsync` is the SQLite form of `library.full_fsync` (macOS only
  hands data to the drive otherwise). If `PRAGMA journal_mode=WAL` doesn't answer `wal` (some network volumes), go on
  in the default journal mode and emit nothing: correctness doesn't depend on WAL.
- **No new dependency** (`sqlite3`, `hashlib` are stdlib; `mutagen` is already a dependency, tests may use it).
- **One connection per call** (`db.connect(path)` opened in a `with` and closed): the hub reads from several threads,
  console and hub are separate processes, SQLite opens in about a millisecond. No connection cache.
- **Paths:** rows store POSIX paths relative to their watched folder, NFC-normalised (as `list_files` does today).
  The snapshot gives root-relative paths (`Library/<…>`) for files of the `library` watched folder, as today.
- **User-facing words** are given per task; plain English, no jargon (CLAUDE.md).
- **Tests offline, `tmp_path` libraries only.** No real library, Spotify, Qobuz or yt-dlp.
- **Public repo:** no home paths or real names in tracked files; `scripts/check_public.sh` before every commit.

## Review focus (for the per-group and the stage review)

1. A crash at any step (migration, `run_op`, a scan) leaves a library the next run can use, and `state.json` is
   untouched until `library.db` is in place.
2. `save_state` writes only changed rows, re-keys exactly the files whose entry file fields changed, and loses no
   entry key (unknown keys survive in `songs.extra`).
3. A scan with nothing changed reads no file contents (one `stat` per file); an offline folder's files keep their
   rows and their songs stay satisfied; nothing is ever marked gone because a folder couldn't be read.
4. The planner never produces a move; a moved file is neither moved back nor downloaded again.
5. Replacements (swap, add as new, bought file, use candidate) land in the current file's folder; `Superseded/` and
   `Upgrades ready/` mirror it.

---

## Interfaces (fixed here; groups build against them)

### I1. The schema (schema version 1) — `db.py`

```sql
CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
  -- schema_version, created, migrated_from (SHA-256 of the state.json it was built from, or absent)
CREATE TABLE songs (
  id INTEGER PRIMARY KEY,
  key TEXT NOT NULL UNIQUE,      -- the engine's and the bridge's track id (the Spotify id for every stage-1 song)
  artist TEXT NOT NULL, title TEXT NOT NULL,
  artists TEXT, album TEXT, image_url TEXT,  -- JSON list / text; NULL in stage 1, filled by stage 3's sources
  duration_ms INTEGER, isrc TEXT,
  folder TEXT,                   -- placement folder: the playlists.txt folder of the first playlist that has it
  in_playlists INTEGER NOT NULL DEFAULT 1, added TEXT,
  last_attempt TEXT, last_upgrade_check TEXT, upgrade TEXT, rejected_sources TEXT, declined_streams TEXT,
  free_downloads TEXT, originals_searched TEXT, qobuz_searched TEXT,   -- JSON where the entry holds a list/dict
  file_gone TEXT,                -- day a scan found its file gone; rule 2 downloads again at once
  extra TEXT                     -- JSON object: every other entry key (hidden, rekordbox_check, …)
);
CREATE INDEX songs_isrc ON songs (isrc);
CREATE TABLE song_ids (service TEXT NOT NULL, id TEXT NOT NULL,
  song INTEGER NOT NULL REFERENCES songs (id) ON DELETE CASCADE, PRIMARY KEY (service, id));
CREATE TABLE watched_folders (id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE,
  kind TEXT NOT NULL CHECK (kind IN ('library', 'import')), added TEXT NOT NULL, last_scan TEXT);
CREATE TABLE files (
  id INTEGER PRIMARY KEY,
  song INTEGER REFERENCES songs (id) ON DELETE SET NULL,
  folder INTEGER NOT NULL REFERENCES watched_folders (id),
  path TEXT NOT NULL,            -- relative to the watched folder, POSIX, NFC
  size INTEGER, mtime_ns INTEGER, content_key TEXT,   -- NULL only for a migrated file that wasn't on disk
  placed_by TEXT NOT NULL CHECK (placed_by IN ('app', 'user', 'import')),
  online INTEGER NOT NULL DEFAULT 1,
  first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  status TEXT, source TEXT, source_id TEXT, source_format TEXT, cutoff_hz INTEGER, source_kbps INTEGER,
  ambiguous TEXT,                -- JSON list of snapshot paths that could be this (moved) file; else NULL
  UNIQUE (folder, path)
);
CREATE INDEX files_key ON files (content_key);
CREATE INDEX files_song ON files (song);
CREATE TABLE never (song_key TEXT PRIMARY KEY, data TEXT NOT NULL);            -- JSON {artist, title, folder, at}
CREATE TABLE qobuz_usage (id INTEGER PRIMARY KEY CHECK (id = 1), data TEXT NOT NULL);  -- JSON {days, signals}
CREATE TABLE pending (id INTEGER PRIMARY KEY, op TEXT NOT NULL);              -- JSON, today's pending-op shape
```

Decisions and reasons:
- **`songs.key`** keeps the engine's and the bridge's track id unchanged in stage 1 (no contract change). It is
  opaque text; stage 3 decides the key of a song first seen on another service. `song_ids` holds
  `('spotify', key)` plus one `spotify` row per alias (spec §5.2).
- **`songs.folder`** isn't in spec §5.2's list but is needed: a song with no file still has a placement folder
  (rule 2, the Library page groups by it, stage 2's tidy-up targets compare against it).
- **`songs.file_gone`**: today a vanished file is downloaded again at once (rule 3, reason `redownload`). Under the
  new model the scan removes the file row (spec §6.3 "Gone"), so the song looks like rule 2's "no file", which waits
  for `last_attempt` to be due. The column keeps today's behaviour; `apply_outcome` clears it.
- **`files.ambiguous`**: spec §6.3 "Moved, more than one new file has that key: nothing is decided". The known row is
  kept with its candidates so every view and report can show them, and each scan decides again.
- **One linked file per song in stage 1.** The schema allows more (stage 4's duplicates "two files linked to the
  same song"); stage 1 code never links a second one. The snapshot uses the song's linked file with the lowest id.
- **No `move_batches` / `moves` in schema 1.** Stage 2 designs them and adds them as schema version 2 through the
  upgrade-step mechanism (task 1.2). Stage 1 leaves the room they need: stable `files.id`, `content_key` (undo
  checks "same content key"), `placed_by`.

### I2. The snapshot — what `library.load_state` returns and `planner.plan` receives

Shape (same keys as today's `state.json`, plus the read-only ones marked ✱):

```python
{"version": 2,                                   # 2 = backed by library.db; 1 = a state.json read before migration
 "tracks": {key: entry},                         # every song; entry = ENTRY_KEYS ∪ extra keys ∪ ✱ below
 "pending": [op, ...], "never": {key: {...}}, "qobuz_usage": {"days": {}, "signals": []},
 "ambiguous": {key: [snapshot path, ...]},       # ✱ songs whose file moved to one of several places
 "files": [snapshot path, ...]}                  # ✱ sorted online indexed files (replaces library.list_files)
# entry extras: "online": bool ✱, "placed_by": "app"|"user"|"import"|None ✱, "file_gone": "YYYY-MM-DD"|None
```

An entry with a linked file has `path` (snapshot path), `status` and the quality fields from the file row; one
without has `path: None, status: "missing"`. `save_state` ignores ✱ keys; `file_gone` is a song column and writable.

### I3. Scanner types — `models.py` (added by group 2, used by groups 1 and 3)

```python
@dataclass(frozen=True)
class WatchedFolder: id: int; path: Path; kind: str                       # "library" | "import"
@dataclass(frozen=True)
class KnownFile: id: int; folder: int; rel: str; size: int | None; mtime_ns: int | None
                 content_key: str | None; linked: bool; ambiguous: bool
@dataclass(frozen=True)
class SeenFile: folder: int; rel: str; size: int; mtime_ns: int; content_key: str
@dataclass
class ScanResult:
    offline: list[int]                     # watched folder ids
    unchanged: int
    retagged: list[tuple[int, SeenFile]]   # file id -> same key, new size/mtime
    replaced: list[tuple[int, SeenFile]]   # file id -> other key (audio replaced outside Discjockey)
    moved: list[tuple[int, SeenFile]]      # file id -> its one new place
    ambiguous: list[tuple[int, list[str]]] # file id -> snapshot paths (I2) of every candidate
    new: list[SeenFile]                    # unknown keys, incl. every ambiguous candidate
    copies: list[SeenFile]                 # the key of a file that is still there
    gone: list[int]                        # file ids
    unreadable: list[tuple[int, str, str]] # folder id, rel, reason (kept, tried again next scan)
```

### I4. Key signatures

- `content_key.content_key(path: Path) -> str` — group 2.
- `scanner.scan(folders: list[WatchedFolder], known: list[KnownFile], *, exclude: list[Path],
  snapshot_path: Callable[[int, str], str], key_of=content_key, mounted=os.path.ismount) -> ScanResult` — group 2.
  `snapshot_path(folder_id, rel)` gives I2's path, so `ambiguous` candidates are what views and reports show.
- `db.connect(path: Path) -> sqlite3.Connection`; `db.check(conn)` (version, raises `StateError`);
  `db.create(path, state: dict, *, library: Path, facts, now)`; `db.snapshot(conn, library: Path) -> dict`;
  `db.save(conn, state: dict, *, library: Path, facts, now) -> int` (rows changed);
  `db.migrate(paths, *, facts, now, emit)` — group 1. `facts: Callable[[str], FileFacts | None]` takes a snapshot
  path and returns `FileFacts(size, mtime_ns, content_key)` or `None` when no file is there; group 3 passes the real
  one (stat + `content_key`), group 1's tests a fake. Keeps `db.py` free of file I/O except its own database file.
- `db.watched_folders(conn) -> list[WatchedFolder]`, `db.known_files(conn) -> list[KnownFile]`,
  `db.apply_scan(conn, result, now)`, `db.set_quality(conn, file_id, status, cutoff_hz, source_format)` — group 3.
- `library.load_state(paths) -> dict` (reader), `library.open_state(paths, emit=no_emit) -> dict` (writer: migrates
  first; caller holds the lock), `library.save_state(paths, state)`, `run_op(paths, state, track_id, renames, entry)`
  (unchanged), `recover_pending(paths, state)` (unchanged), `library.scan_library(paths, emit) -> ScanSummary` —
  group 3. `ScanSummary(moved, new, gone, replaced, copies, offline: int)`.
- `planner.mirror_dir(path) -> str`, `superseded_dir(path) -> str`, `upgrades_ready_dir(path) -> str`,
  `replacement_dir(entry, status) -> str` — group 4.

---

## Task groups

| Group | Model | Area | Size (changed lines) | Depends on | Parallel with |
|-------|-------|------|----------------------|------------|---------------|
| 1 Database and migration | Opus | `db.py` new | ~1,000 | — | 2 |
| 2 Content keys and scanner | Opus | `content_key.py`, `scanner.py` new | ~900 | — | 1 |
| 3 Engine on the database | Opus | `library.py`, callers, test sweep | ~1,300 | 1, 2 | 4 |
| 4 Option A placement | Opus | `planner.py`, `execute.py`, `ops.py`, `upgrades.py` | ~700 | 1, 2 (snapshot keys only) | 3 |
| 5 Hub, contract, docs | Sonnet | `hub/api.py`, `hub/views.py`, hub-ui wiring, docs | ~500 | 3, 4 | — |

Groups 1+2 run first, in two worktrees. Then 3+4 in two worktrees: group 4 builds on the snapshot keys (I2), which it
can fake in planner tests; it must not touch `save_state`/`load_state` call lines (group 3's), so their merges don't
conflict. Merge order 3 then 4; whoever merges second re-runs the touched tests. Group 5 last.

---

## Group 1 — Database and migration (Opus)

**Read list:** spec §5 (all), §12 first two bullets, §13 "db / migration"; this plan's I1–I4; `discjockey/library.py`
lines 1–25 and 219–290 (`load_state`, `save_state`, `write_json_atomic`, `full_fsync`, `fsync_dir`) and 406–475
(`run_op`, `recover_pending`); `discjockey/planner.py` `ENTRY_KEYS`; `grep -rn '\["[a-z_]*"\] = \|{\*\*e, "' discjockey`
(every entry key written anywhere). No other files.

### 1.1 `db.py`: connection, schema, version check
- New module `discjockey/db.py`, docstring: "Owns library.db: the schema, the migration from state.json, every query.
  Nothing else writes SQL (spec library-and-sources §5.5)."
- `SCHEMA_VERSION = 1`; `connect` applies the binding pragmas; `check(conn)` raises `library.StateError` (import it,
  don't redefine) when `meta.schema_version` is higher than `SCHEMA_VERSION` or the file isn't a database.
- Words (binding): newer: *"This music folder was last used by a newer Discjockey. Update Discjockey, then try
  again. Nothing was changed."*; unreadable: *"Discjockey can't read its records of this music folder
  (.discjockey/library.db): {reason}. Nothing was changed."*
- **Upgrade steps:** `UPGRADES: dict[int, Callable[[Connection], None]]` (version n → n+1), applied in one
  transaction on open when the stored version is lower. Empty in stage 1; stage 2 adds `move_batches`/`moves`.
  Tests pin the mechanism with a monkeypatched step (applied once, version bumped, a failing step leaves the old
  version).
- Tests (`tests/test_db.py`, new): newer version refused with the words; a non-database file refused; pragmas set
  (`journal_mode`, `synchronous`, `foreign_keys`); upgrade-step mechanism as above.

### 1.2 Entry ↔ rows mapping, `create`, `snapshot`
- Column mapping: every `ENTRY_KEYS` song field → its `songs` column (JSON-encode lists/dicts); `aliases` →
  `song_ids`; file fields (`path`, `status`, `source`, `source_id`, `source_format`, `cutoff_hz`, `source_kbps`) →
  the linked `files` row; any other key (`hidden`, `rekordbox_check`, future ones) → `songs.extra`. **Check first:**
  the grep in the read list — every key found that is a property of the *file* (not the song) gets a reason in the
  commit for where it went; stage 1 keeps it in `extra` unless it is in `ENTRY_KEYS`.
- Snapshot paths: `files.folder` = the `library` watched folder → `"Library/" + path`; any other folder → the
  absolute POSIX path (stage 4 decides more). A snapshot path not under `Library/` and not absolute is a
  `ValueError` in `save`.
- `create(path, state, *, library, facts, now)`: builds a fresh database at `path` from a snapshot-shaped dict
  (used by the migration and by tests): the `library` watched folder (`kind='library'`, path = `library`), one song
  per entry, one file row per entry with a path (`placed_by='app'`, `facts(path)` for size/mtime/key, all three
  NULL when `facts` returns None), pending/never/qobuz_usage. One transaction.
- `snapshot(conn, library)`: I2 exactly. Also: on every open, if the `library` row's path differs from `library`
  (the music folder moved, a drive renamed), update it — reason: `Library/` always belongs to the music folder the
  user chose; a stale path would make it offline.
- Tests: a state.json-shaped fixture with aliases, a missing track, a parked `upgrade`, `never`, `qobuz_usage`,
  `hidden`, an unknown key → `create` → `snapshot` gives back the same `tracks`/`pending`/`never`/`qobuz_usage`
  (✱ keys aside) — the round trip is the main pin; `ambiguous` and `files` built from rows.

### 1.3 `save`: the diffing write
- `save(conn, state, *, library, facts, now) -> int` in one `BEGIN IMMEDIATE` transaction: read the current rows,
  compare with `state`, write only differences:
  - song fields/aliases/extra changed → update that song (and its `song_ids`); new key → insert; a key gone from
    `state["tracks"]` → delete the song (its file rows: unlinked if `facts` still finds the file, else deleted).
  - **file fields changed** (any of path, status, source, source_id, source_format, cutoff_hz, source_kbps):
    - path changed and a row already exists at the new path (an unlinked file found by a scan, e.g. a bought file)
      → link that row, write the quality fields, `placed_by='app'` (the app adopted it there); the old linked row: unlinked if its file still exists, else deleted.
    - path changed, no row there → update the linked row in place (path, folder, `placed_by='app'`).
    - always re-read `facts(new path)` for size/mtime/key (spec §6.2 "changes Discjockey makes itself update the
      stored key in the same operation" — a swap writes new audio under the same path).
    - path became None (`status: "missing"`) → the linked row: unlinked if its file still exists, else deleted.
  - `pending`: replace all rows when the list differs (it is short). `never`, `qobuz_usage`: update what differs.
- Returns the number of changed rows (tests pin "only changed rows are written").
- Version guard: `state["version"] != 2` → `StateError` (a v1 dict is never saved into the database).
- **Performance budget:** a save with one changed entry on a 10,000-song library under about 100 ms on a Mac
  (measure once with a generated database; not a test). If it is slower, read `(key, digest)` pairs instead of full
  rows; don't add a cache that outlives the connection.
- Tests: one changed entry writes one row; a new path re-keys via `facts` and sets `placed_by='app'`; linking an
  existing unlinked row; missing → unlink vs delete; removed key; pending replace; ✱ keys ignored;
  `file_gone` written; v1 dict refused.

### 1.4 `migrate`: state.json → library.db
- `migrate(paths, *, facts, now, emit)`, caller holds the lock. Steps (spec §5.3):
  1. Load `state.json` with today's v1 reader (move `load_state`'s body to `library._load_v1`; the message for any
     other version stays word for word: *"state.json has version N, this Discjockey only knows version 1. Nothing
     was changed."* — that is what an older Discjockey prints for the stub).
  2. Recover its pending steps (spec §5.3) by calling the `recover: Callable[[dict], None]` argument with the v1
     dict: full signature `migrate(paths, *, facts, now, emit, recover)`. Group 3 passes `library.recover_pending`
     run with `_migrating` set, so it saves to `state.json` as today (task 3.1); group 1's tests pass a fake. Reason:
     the two groups share no code before the merge.
  3. `create` into `library.db.tmp` (deleted first if left over), with content keys (`facts`), then
     `meta.migrated_from` = SHA-256 of `state.json`'s bytes.
  4. `full_fsync` the database file, rename `library.db.tmp` → `library.db`, `fsync_dir`.
  5. Rename `state.json` → `state.v1.json` (overwrites an older backup: reason, it is the newest copy).
  6. Write the stub `{"version": 2, "moved_to": "library.db"}` as `state.json` (`write_json_atomic`).
- **Resuming** (at the start of `migrate`, and called by `library.open_state` whenever `library.db` exists):
  `library.db` exists and `state.json` is v1 → SHA-256 equal to `meta.migrated_from`: do steps 5–6; different
  (an older Discjockey ran in between): move `library.db` to `library.db.discarded` and migrate again. `library.db`
  exists, no `state.json`, `state.v1.json` exists → step 6.
- Emit once before step 3: `Message("info", "Updating Discjockey's records of your library (only this once; it can
  take a minute)...")`.
- Failure (any exception before step 4): remove the `.tmp`, raise `StateError` with *"Discjockey couldn't update its
  records of your library ({reason}). Nothing was changed; it tries again next time."* (spec §12).
- Tests (`tests/test_db_migration.py`, new; spec §13): fixtures with aliases, pending ops (a plain rename and a
  `kind: "swap"` op), missing files, parked upgrades migrate to the expected rows; a crash injected after each of
  steps 1–6 (monkeypatch the step's function to raise) leaves a library the next `migrate` finishes, and before
  step 4 leaves `state.json` byte-identical; the stub has exactly the shape above; `_load_v1` refuses the stub with
  the old message; the hash-mismatch path discards and rebuilds; a file listed in `state.json` but not on disk
  becomes a row with NULL facts.

---

## Group 2 — Content keys and scanner (Opus)

**Read list:** spec §6 (all), §12 third bullet, §13 "Content key" and "Scanner"; this plan's I3, I4;
`discjockey/library.py` `list_files` (lines 292–303); `tests/audio_helpers.py` (`grep -n "^def "`, then
`write_aiff`, `to_aac`); `discjockey/models.py` (whole, 114 lines). No other files.

### 2.1 `content_key.py`
- Docstring: "A fingerprint of a file's audio bytes that survives renames, moves and tag edits (spec
  library-and-sources §6.2)."
- Binding values: `AUDIO_EXTS = (".aiff", ".aif", ".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus")`,
  `WINDOW = 256 * 1024`. Key = `f"1:{payload_length}:{sha256_hex}"` where the hash runs over the start, middle and
  end windows of the payload (middle starts at `(length - WINDOW) // 2`); a payload of at most `3 * WINDOW` is
  hashed whole. The leading `1:` is the algorithm version, so a later change can re-key.
- Payload per format (each a list of `(offset, length)` byte ranges so non-contiguous payloads work):
  AIFF/AIFC `SSND` chunk data; WAV `data` chunk; FLAC: frames after the last metadata block (skip a leading ID3v2
  first); MP3: after ID3v2 (syncsafe size, footer flag) up to an ID3v1 `TAG` (128 bytes) and/or APEv2 footer
  (`APETAGEX`); M4A: the data of every top-level `mdat` atom in order (64-bit sizes, size 0 = to the end);
  Ogg/Opus: the page *bodies* after the last header packet (Vorbis 3, Opus 2; packets end at a lacing value < 255),
  page headers excluded — reason: a longer comment packet renumbers every later page, so header bytes change while
  the audio doesn't.
- Anything unparsable (truncated chunk, bad magic, zero-length payload) → the same windows over the whole file
  (spec). Errors reading the file (permission, gone) propagate as `OSError`; the scanner handles them.
- Tests (`tests/test_content_key.py`, new): for each format, a generated file (`audio_helpers.write_aiff` and
  ffmpeg conversions; **check first:** how `to_aac` reaches ffmpeg in tests, and use the same for FLAC/MP3/WAV/Ogg/
  Opus) → its payload is found (key length part equals the known audio size where easy to compute: AIFF/WAV);
  editing tags with mutagen (title, a 100 KB picture) keeps the key; changing one audio sample changes it; a
  truncated file falls back to whole-file windows; a renamed copy has the same key.

### 2.2 `scanner.py`: walking
- Docstring: "Walks the watched folders and sorts every audio file against the index (spec library-and-sources
  §6.1, §6.3, §6.4). Reads only; returns a ScanResult that db.apply_scan writes."
- Walk each folder with `os.walk` (no symlinks followed; symlinked files skipped — reason: a link can point outside
  the watched folder or loop), skipping names starting with `.`, any path in `exclude` (the caller passes the music
  folder's `Superseded/`, `Upgrades ready/`, `.discjockey/`), and files whose lower-cased suffix isn't in
  `AUDIO_EXTS`. Rels NFC-normalised. A folder inside another watched folder is not walked again; its files belong
  to the outer folder's id.
- **Offline (§6.4):** a folder is offline when its path doesn't exist, or it is under `/Volumes/<name>` and
  `mounted(Path("/Volumes", name))` is false. An offline folder isn't walked; its id goes in `offline`; its known
  files appear in no list. A folder that vanishes mid-walk (top-level `onerror`, or it no longer exists after the
  walk) → offline, its partial results dropped, the scan goes on (§12).
- **A subfolder that can't be listed:** its known files are treated as unchanged, never gone — reason: a
  permission error must not trigger downloads.
- Unchanged = same rel, `st_size`, `st_mtime_ns`: no read. Everything else is keyed with `key_of`; an `OSError`
  goes to `unreadable` and its known row (if any) is left as it is.

### 2.3 `scanner.py`: reconciling (§6.3)
- Order: (1) per folder, match known rows by rel → unchanged / retagged (same key) / replaced (other key);
  (2) known rows whose rel is gone (plus rows already `ambiguous`) vs new files by `content_key`: exactly one new
  file with the key → `moved`; several → `ambiguous` with every candidate's `snapshot_path(folder, rel)` (I4);
  none → `gone`.
  (3) A known row with `content_key` NULL (a migrated file that wasn't at its path) matches by file name instead:
  exactly one new file whose `fold(name)` equals it and that no other row claims → `moved`; several → `ambiguous`;
  none → `gone`. Reason: it carries today's rule-3 by-name search over the update once, and only for those rows.
  (4) New files with the key of a known file that is still there → `copies`; the rest → `new`. A file used as a
  `moved` target is in neither list.
- Moves across watched folders count (the key is global); a move into an offline folder can't be seen, so a
  known row in an online folder whose key isn't found stays `gone` — accepted, same as today's behaviour.
- Tests (`tests/test_scanner.py`, new, `tmp_path` folders, a counting fake `key_of`): every case of §6.3 (unchanged
  with zero `key_of` calls, retagged, replaced, moved, moved with two candidates, gone, copy, new); a migrated row
  without key found by name; hidden folders, excluded folders and non-audio skipped; nested watched folders scanned
  once; offline by missing path and by an unmounted `/Volumes/X` (fake `mounted`) keep their rows out of every list;
  a folder removed mid-scan (fake `key_of` deletes it) becomes offline; an unlistable subfolder (chmod 000) marks
  nothing gone; an unreadable file goes to `unreadable`.

---

## Group 3 — Engine on the database (Opus)

**Read list:** this plan (whole); spec §5.3–§5.5, §6.4 last paragraph; `discjockey/db.py`, `discjockey/scanner.py`
docstrings and outlines; `discjockey/library.py` (whole, 542 lines); `discjockey/run.py` lines 60–125 and 160–245;
`grep -n 'save_state\|load_state\|state_file\|list_files\|recover_pending\|clear_tmp' discjockey/*.py
discjockey/hub/*.py`; `discjockey/hub/jobs.py` lines 157–360 (`Jobs`, `lock_briefly`); `discjockey/cli.py` lines
40–60 and 110–130. Tests: `grep -rln 'state_file\|save_state\|load_state\|state\.json' tests/` and
`grep -n "^def " tests/hub_helpers.py`.

### 3.1 `library.py`: reader, writer, save
- `load_state(paths) -> dict` (reader, no lock): `library.db` exists → `db.check` + `db.snapshot`; else `state.json`
  v1 → `_load_v1` + the ✱ keys filled in (`online: True`, `placed_by: "app"` for entries with a path, `ambiguous:
  {}`, `files`: the old `list_files` walk) — reason: the hub can show a library before its first write migrates
  it; no `state.json` and no db → `empty_state()` (now the v2 shape). The stub without a db → `StateError`
  *"Discjockey's records of this music folder (.discjockey/library.db) are missing. A copy of the older records is
  in .discjockey/state.v1.json. Nothing was changed."* (no automatic restore: it could download or misplace files
  the old copy doesn't know).
- `open_state(paths, emit=no_emit) -> dict` (writer; caller holds the lock): finishes or runs `db.migrate`, creates
  an empty database for a library that has neither file, then returns `load_state(paths)`.
- `save_state(paths, state)`: version 2 → `db.save` with the real `facts` (stat + `content_key` of
  `paths.root / snapshot path`, None when missing); version 1 → `write_json_atomic` as today only while
  `_migrating` is set, else `StateError` (a programming error, never seen by a user; message plain anyway).
  `NoLibrary(MUSIC_GONE)` when `.discjockey/` is gone, as today.
- `run_op` / `recover_pending` / `clear_tmp` / `NameReserver`: unchanged logic; they call `save_state(paths, …)`.
  The "one committed transaction per step" of spec §5.4 is `run_op`'s three saves.
- Remove `list_files` (replaced by `state["files"]`) and `Paths.state_file`'s use for state; add
  `Paths.db_file` (`.discjockey/library.db`) and `Paths.state_backup` (`.discjockey/state.v1.json`); keep
  `state_file` for the migration and the stub.
- Tests: rework `tests/test_library_state.py` (14 tests) and the `run_op` / `recover_pending` tests in
  `tests/test_library_ops.py` onto the database: a crash before, between and after the renames recovers as today
  (the pending row survives a crash; `recover_pending` reads the table); reader fallback on v1; writer migrates; a v1
  dict refused outside the migration; missing-db message.

### 3.2 `db.py` scan queries and `library.scan_library`
- In `db.py`: `watched_folders`, `known_files`, `apply_scan(conn, result, now)` in one transaction: offline → set
  `online=0` for that folder's rows (and back to 1 when a later scan finds it online); retagged/replaced → size,
  mtime, key, `last_seen`; moved → rel/folder, `placed_by='user'`, `ambiguous=NULL`; ambiguous → JSON candidates;
  new/copies → insert unlinked rows with `placed_by='import'` (spec §2: "found there by a scan"; when the sync
  adopts one as a bought file, `save` makes it `'app'`, since the app put it in place); gone → delete the row and set the
  song's `file_gone` to today; `watched_folders.last_scan`; `last_seen` for the rest of an online folder in one
  `UPDATE`. `set_quality(…)`.
- `library.scan_library(paths, emit) -> ScanSummary` (caller holds the lock): `open_state` first, then `scanner.scan`
  with `exclude` = Superseded, Upgrades ready, .discjockey and `snapshot_path` from I2; `apply_scan`; then for each
  `replaced` file still linked to a song: the quality check the bought-file path uses (**check first:** what
  `ops.add_bought_file` calls — `quality.inspect` / `analyze` — and reuse that, not a copy), stored with
  `set_quality`, `source="manual"`, `source_id=None` — reason: the file no longer is the download it was; its
  quality decides upgrades from now on.
- One `Message("info", …)` only when something changed. Words (binding): *"Checked your Library: {parts}."* where
  parts are, in this order and only when non-zero, "1 file you moved" / "{n} files you moved", "1 new file" /
  "{n} new files", "1 file gone" / "{n} files gone", "1 file changed" / "{n} files changed", joined with ", ".
  Offline folders aren't mentioned in stage 1 (only import folders can be offline; stage 4 words them).
- Tests (`tests/test_library_scan.py`, new): end to end on a `tmp_path` library with real small AIFFs: a file moved
  by hand inside `Library/` keeps its song and becomes `placed_by: "user"`; a deleted file sets `file_gone`; a
  replaced file is re-judged; the message words; nothing changed → no message and zero key reads.

### 3.3 `run.py`: scan before planning
- `prepare`: `open_state` (instead of `load_state`), `recover_pending` + `clear_tmp` (non-dry, as today), then
  `scan_library` (dry runs too — spec §6.4), then reload the snapshot, fetch, plan with `state["files"]`.
  **Check first:** whether every caller of `prepare(dry_run=True)` (cli dry run, `hub/jobs.py: refresh_work`) holds
  the lock. The scan and the migration write `library.db`, so they need it: take it in the caller the way that
  caller already takes it for writes (console: `library.run_lock`; hub: the refresh job is a write job or uses
  `Jobs.lock_briefly`). If a caller can't get it (a terminal run holds it), skip the scan and read with
  `load_state` — the plan is then as fresh as the last scan, and nothing is written.
- `replan`, `open_qobuz` (record the signal via `open_state`/`save_state`), `finish_quietly`, `execute.save`: the new
  signatures. Plan's ambiguous list comes from the planner (group 4) — no change here.
- Tests: `tests/test_run.py` cases for "a file moved by hand is not downloaded again" (end to end through
  `prepare`, fake Spotify) and "a dry run scans".

### 3.4 Callers: new signatures
- Every `save_state(paths.state_file, …)` → `save_state(paths, …)`; every load that is followed by a save →
  `open_state(paths)`: `ops.py: run_single`, `upgrades_cmd.py` line ~132, `hub/api.py` lines ~633, ~646 (budget
  saves) and ~911 (never toggle), `run.py` as above. Pure readers (`hub/api.py: _state`) stay on `load_state`.
  `library.list_files(...)` → `state["files"]` (`run.py`, `hub/api.py` ~782).
- **Check first:** `report.py` and `views.py` read only `state["tracks"]`/`pending`; confirm they don't iterate
  over every key of the state (the new ✱ keys would surprise them).

### 3.5 Test sweep
- **Check first:** the ~180 lines found by the read-list grep. Mechanical rules: `save_state(paths.state_file, s)` →
  `save_state(paths, s)`; assertions reading `state.json` → `library.load_state(paths)`; setups that write a v1
  `state.json` and then call a writer function directly (not through `prepare`/`run_single`/a bridge method) → the
  new helper `tests/hub_helpers.py: write_state(paths, state)` (calls `db.create` with real facts). Setups going
  through an entry point may keep writing v1 JSON: the entry point migrates it, which exercises the migration.
- Keep every existing assertion's meaning; a test whose meaning changes under option A belongs to group 4 (leave it
  failing only if group 4 owns it — list it in the report, don't delete it).

### 3.6 Files the scan must ignore
- `.discjockey/library.db*` sits under `.discjockey/` (excluded). `Library/` is the only `library` folder. Pin with
  a test that a stray `library.db` copied into `Library/` isn't indexed (not audio).

### 3.7 `docs/issues.md`
- Add: "Engine still works on the entry view of the database (stage 1 seam): move callers to explicit song/file
  writes as stages 3–4 touch them." and "Import folders on another drive: `run_op` renames across drives aren't
  atomic (stage 4 must stage in the target drive)."

**Group 3 checks while working:** `tests/test_library_state.py`, `tests/test_library_ops.py`, `tests/test_db*.py`,
`tests/test_library_scan.py`, `tests/test_run.py`, `tests/test_ops.py`, `tests/test_upgrades.py`,
`tests/test_swap.py`, `tests/test_execute.py`, `tests/test_hub_api_write.py`, `tests/test_cli.py`.

---

## Group 4 — Option A placement (Opus)

**Read list:** spec §7 (all), §6.3 "Moved"/"Gone"; this plan's I2, I4 and Review focus; `discjockey/planner.py`
(whole, 244 lines); `discjockey/execute.py` lines 97–235; `discjockey/ops.py` lines 160–235 and 258–345;
`discjockey/upgrades.py` lines 98–135 and 204–300; `grep -n '"move"\|"adopt"' discjockey/*.py discjockey/hub/*.py`.
Tests: `grep -n "def test_" tests/test_planner.py tests/test_execute.py tests/test_upgrades.py tests/test_swap.py
tests/test_ops.py`.

### 4.1 Pure placement helpers — `planner.py`
- `mirror_dir(path)`: for `Library/<F>/…/<name>`: `<F>/<subfolders>` with a `not_lossless` component directly below
  `<F>` dropped; a file directly in `Library/` → `""`. Stage 1 has only `Library/` files, so the helper takes
  `Library/` paths; its docstring says stage 4 adds spec §7's `<watched folder name>/<subfolders>` case for import
  folders (it then needs the watched folder, which the snapshot will carry). Reason: one place decides the mirror.
- `superseded_dir(path)` = `"Superseded/" + mirror` (or `"Superseded"`); `upgrades_ready_dir(path)` likewise.
- `replacement_dir(entry, status)`: where a file replacing the song's current file goes. No current file →
  `folder_dir(entry["folder"], status)` (today). Current file in a playlist-style folder (`Library/<F>` or
  `Library/<F>/not_lossless`) → `folder_dir(<F>, status)` — so lossless leaves `not_lossless/` and a lossy
  replacement stays in it, as today. Anywhere else → the current file's folder unchanged (spec §7: "the
  `not_lossless/` → folder move happens only for a file in a playlist folder's `not_lossless/`").
- Tests (`tests/test_planner.py`): each helper's cases above.

### 4.2 Planner rules — `planner.py: plan`
- For every wanted song: `e["folder"] = w.folder` (the placement folder follows the order; the note for a missing
  song that changed folder stays as today).
- Rule 2 (no file): bought file first as today; then `file_gone` set → `acquire` reason `redownload` at once; else
  retry when due.
- Rule 3: `online` false → satisfied, no action at all (no upgrade either: the file can't be reached); key in
  `state["ambiguous"]` → one `ambiguous` entry with those paths, no action; path not in `files` (vanished since the
  scan) → `acquire` reason `redownload`. **The by-name search is removed**, and with it the `adopt` kind.
- Rule 4 removed: no `move` actions, ever.
- Rule 5: bought file looked for in `Library/<w.folder>/` and in the current file's folder (deduplicated); weekly
  upgrade checks as today.
- `apply_outcome`: an acquisition's `placed`/`missing` outcome clears `file_gone`.
- `KIND_RANK` keeps `adopt_bought`, `acquire`, `upgrade`. Remove the `move`/`adopt` executor paths
  (`execute.py: _move`, `_adopt`), their `STEP_VERBS` (`run.py`), console `VERBS` (`console.py`) and report labels
  (`report.py` line ~53) — reason: dead code; stage 2's tidy-up moves through its own batches.
  **Check first:** `hub/views.py` counts `moves`/`adopts` and reads `a.kind in ("move", "adopt")`; leave views to
  group 5 (it owns the contract) and only make sure nothing here breaks them.
- Tests (spec §13 "Planner"): a file moved by hand to another folder (entry path elsewhere, `placed_by: "user"`)
  gets no action and no download; a song whose placement folder changed gets no move; new downloads follow the
  playlist order (first playlist's folder); offline → nothing (not even the weekly check); ambiguous → listed,
  nothing done; `file_gone` → immediate `redownload`; a bought file next to the current file is adopted. Rework the
  existing rule-3/rule-4 tests in `tests/test_planner.py` to these meanings.

### 4.3 Replacements land in the current file's folder
- `execute.py: _adopt_bought`: old file → `superseded_dir(old)`; the bought file → `replacement_dir(e, status)`.
- `execute.py: _park`: `Upgrades ready/` path via `upgrades_ready_dir(e["path"])`. **Check first** its current
  destination expression.
- `ops.py: _superseded_name`, `_move_away`: `superseded_dir(e["path"])`. `ops.py: add_bought_file`: destination
  `replacement_dir(e, status)` + expected name. `ops.py: use_candidate`: `replacement_dir(e, ready.status)`.
- `upgrades.py: add_new`: old → `superseded_dir`, new → `replacement_dir(e, status)` (the correct "Artist - Title"
  name, as today). `upgrades.py: swap`: backup → `superseded_dir`; the not_lossless check at line ~279 becomes "the
  file is in a playlist folder's `not_lossless/`" (`Library/<F>/not_lossless/<name>`, exactly) instead of "its
  parent is called not_lossless".
- Words: unchanged (the existing results already say "moved to Superseded").
- Tests: add as new for a file the user keeps in `Library/Sets/2024/` lands there and the old one in
  `Superseded/Sets/2024/`; a lossless swap of `Library/<F>/not_lossless/x` moves up to `Library/<F>/` (any direct
  child of `Library/` counts as a playlist folder, in `playlists.txt` or not), while `Library/A/B/not_lossless/x`
  stays where it is; bought file next to the current file; `use_candidate` into the current folder. Run `tests/test_swap.py`,
  `tests/test_upgrades.py`, `tests/test_ops.py`, `tests/test_execute.py` while working.

---

## Group 5 — Hub, contract, docs (Sonnet)

**Read list:** this plan's Group 5 and I4 (`scan_library`, `ScanSummary`); `docs/hub-bridge-contract.md` (headings,
then the sections for the methods named below); `discjockey/hub/api.py` (`grep -n "@bridge" -A3`, then one existing
write method that starts a job, e.g. the never toggle near line 905); `discjockey/hub/views.py` lines 140–165 and
740–760; `hub-ui/src/lib/bridge/types.ts`, `contract.ts`, the fake backend's index (`grep -n`); `README.md`
headings + the sections on `.discjockey/` and on how the sync places files; `CLAUDE.md` Layout.

### 5.1 `rescan_library` bridge method and the window's triggers
- `api.rescan_library()` → write method, job kind `"scan"`, work = `library.scan_library(paths, emit)`, result
  `{"moved", "new", "gone", "changed", "copies"}` (ints). Busy/console answers as every write method (CLAUDE.md
  Invariants). **Check first:** what other write methods return while no music folder is bound, and do the same.
- hub-ui: a pure `hub-ui/src/lib/stores/rescanModel.ts` (`shouldRescan(hiddenSince: number | null, now: number):
  boolean` → true when the window was in the background for more than `60_000` ms) with a `*.test.ts`; a small
  listener (`visibilitychange` + window `focus`/`blur`) calls `rescan_library` once on start and then whenever
  `shouldRescan` says so (spec §6.4: "when the window opens, and when the window comes back to the front after
  more than a minute"). `busy`/`console` answers are ignored silently (a running sync scans by itself).
  **Check first:** that a finished job already refreshes the visible page's view; if not, refresh on the `scan`
  job's `JobFinished` when any count is non-zero.
- No visible change: the scan's `JobFinished` shows no toast. Contract: `docs/hub-bridge-contract.md`,
  `types.ts`, `contract.ts`, fake backend (`rescan_library` answers a finished no-change scan) in the same commit.
- Tests: `tests/test_hub_api_write.py` (job runs, result counts, busy answer), the vitest for `rescanModel`.

### 5.2 Views after option A
- `views.py` counts: drop `moves`/`adopts` from the Sync preview counts and `from_folder` for move/adopt actions
  (the planner no longer makes them). **Check first:** whether hub-ui renders these counts; remove them there too
  (contract change: doc, `types.ts`, `contract.ts`, fake). If removing them changes a page visibly, take one fake-mode
  screenshot of the Sync page and look at it.
- `views.playlist_change` (the Playlists page's "N files move to the new folder name") is **not** changed in stage
  1: stage 2 replaces it with the tidy-up question (spec §8.2). Add to `docs/issues.md`: "Stage 1 interim:
  Playlists' save preview still says files move; stage 2 replaces it with the tidy-up question (ships together)."

### 5.3 README, CLAUDE.md, contract doc
- README: `.discjockey/` now holds `library.db` (Discjockey's records), `state.v1.json` (the copy of the old
  records, kept after the update); the one-time "Updating Discjockey's records…" message; files moved or renamed by
  hand inside `Library/` are found where they are and not downloaded again; the sync doesn't move files when the
  playlist order or folder names change (phrase it for the stage 1+2 release: point at "Tidy up", which stage 2
  documents — write the sentence so stage 2 only adds its section); replaced files go to `Superseded/` mirroring
  the file's folder. Plain English, README's tone.
- CLAUDE.md Layout: `.discjockey/` contents (`library.db` instead of `state.json`), new rows for `discjockey/db.py`
  (schema, migration, every query; nothing else writes SQL), `discjockey/scanner.py`, `discjockey/content_key.py`;
  `library.py`'s row ("`run_op` backed by `db.py`").
- `docs/hub-bridge-contract.md`: `rescan_library`, the `scan` job kind, any removed count fields.
- Checks while working: `uv run pytest -q tests/test_hub_api_write.py tests/test_hub_views.py
  tests/test_hub_sync.py tests/test_docs_links.py tests/test_docs_citations.py`, `npx vitest run
  src/lib/stores/rescanModel.test.ts`, `npm run check`, `npm run build` (commit `hub/static`).

---

## Stage checks

- **Per group, while working:** the test files listed in each group (they cover `library.py`, `db.py`,
  `planner.py`, `models.py`, which many tests use — orchestration §6).
- **Per group, once at the end:** the full Python suite, `uv run pytest -q | tail -3` (~25 s in parallel).
- **New test files:** `tests/test_db.py`, `tests/test_db_migration.py`, `tests/test_content_key.py`,
  `tests/test_scanner.py`, `tests/test_library_scan.py`, `hub-ui/src/lib/stores/rescanModel.test.ts`.
- **Reviews:** one Sonnet review per group against its tasks and CLAUDE.md's invariants; one Opus review of the
  whole branch against spec §5–§7 before the merge (with stage 2).
- **hub-ui changes** (group 5): the orchestrator runs `npm run verify` once in the background before the merge;
  one fake-mode screenshot of the Sync page only if 5.2 removes rendered counts.
- **CI:** push `feat/library-1-foundation` before the merge; read `gh run list` only.
- **Live check for the user:** none for stage 1 (spec §13). Stages 1 and 2 merge and ship together; stage 2's live
  check (rekordbox after a tidy-up and an undo) covers the release. Before that release, the orchestrator runs one
  migration against a *copy* of a real-shaped scratch library (`DISCJOCKEY_SUPPORT` scratch, never the user's) and
  reads its report.
- **Docs in this stage:** `README.md`, `CLAUDE.md` Layout, `docs/hub-bridge-contract.md`, `docs/issues.md`
  (3.7, 5.2).
