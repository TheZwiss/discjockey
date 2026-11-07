# rekordbox stage A: read side, and New track lined up (issue 33): plan

Status: plan, 2026-11-07. Design: `docs/2026-11-07-rekordbox-repoint-design.md` (the design). This plan builds its
§13 stage A only and fixes the interfaces stages B–E build on (design §5, §10, §11, §12). Branch `feat/rekordbox-a`
from `main`; group worktrees `.claude/worktrees/rb-a-<group>` on `feat/rekordbox-a-<group>`, each merged into the
stage branch when its review is green.

**Stage A in one line:** Discjockey can open and read rekordbox's library (never write it), measure where rekordbox's
timeline sits for a file, say per track what Same track, Convert and Rename would do (`rekordbox status`,
`rekordbox preview`), and New track renders a sample-exact AIFF instead of renaming the download.

**Not in stage A:** any write to `master.db` or an ANLZ file, batches, backups, the `convert`/`rename` steps, Same
track for non-AIFF files, text-column writes, Auto-upgrade (now on by default, design §2.5; stage C, nothing here
depends on it), multi-select, new hub screens, new bridge methods.

---

## 0. Decisions this plan adds to the design (with reasons)

1. **Reading never creates files next to `master.db`.** With rekordbox closed the read opens
   `file:<master.db>?mode=ro&immutable=1` (no locks, no `-wal`/`-shm` made); with rekordbox running it opens
   `?mode=ro` (it shares rekordbox's existing `-wal`/`-shm`). Reason: guard 4 ("unclean" = a `-wal`/`-shm` while
   closed) must never be tripped by our own read, and rekordbox must never find files we left. A test pins that a
   status and a preview leave the fixture folder byte-identical (names, sizes, mtimes).
2. **The MP3 expected set is the union** `{0, trim, trim + 1152, 1105, 1105 + 1152}` (native samples, deduplicated).
   The design's §3.2 (`{0, trim, trim+1152}`) and §3.3 ("no tag: 0 or 1105") disagree when ffmpeg trims something
   other than 1105. The candidates are at least 13 ms apart against a 0.25 ms tolerance, so the union can't snap a
   right measurement to a wrong value. Other lossy codecs (Vorbis, Opus, WMA): `{0, trim}` like AAC.
3. **`trim` is found by matching, not by lengths:** the lag at which the default decode's first 2 s equal the
   untrimmed decode sample for sample (max abs difference < 1e-6). The length difference also counts the end padding.
4. **New track renders only when the shift is known exactly.** `k = L − round(d · 44100)`; `d` known when measured and
   snapped, when the old file's format set is `{0}` (AIFF, WAV, FLAC, ALAC), or when no rekordbox track holds the
   file (or no rekordbox). `k == 0` keeps today's rename (no copy). `d` unknown (rekordbox unreadable for an MP3/M4A,
   "not analysed" with cues, "timing") → today's rename and today's words; New track never refuses, because it is
   the fallback the user picks when nothing else fits.
5. **The commands' human docs go into `CONTRIBUTING.md` › "The Terminal version"**, a new sub-section "Commands for
   scripts and agents". The design §10 says "the README's console section", which doesn't exist; the README sends
   Terminal users to CONTRIBUTING. Issue 39 gathers the entries from there into its agent docs.
6. **`rekordbox preview` also takes `--path <file>`.** Nothing in stage A prints song keys (`upgrade list` is stage
   B), so an agent needs a way in; a file the library doesn't know still gets the rekordbox part (entries, timing).
7. **Licences:** `sqlcipher3-wheels` 0.5.7's wheel carries only the Python binding's zlib licence (checked
   2026-11-07: one `LICENSE`, 889 bytes). SQLCipher (BSD-style, with SQLite's public-domain notice) and OpenSSL
   (Apache-2.0) are linked into its `.so` with no text in the wheel, so they become hand-kept texts in
   `packaging/licenses/`. The design §5.2 assumed all three were in `dist-info/licenses/`.
8. **Exact pin** `sqlcipher3-wheels==0.5.7` (the others use ranges): it carries the crypto and its defaults decide
   whether the key opens the file; a bump is a deliberate change with the licence test failing until the texts
   follow (§4.3).
9. **The New track check card drops "Auto Relocate finds the new file by name"** for all records (design §7.2: the
   claim is wrong whenever the name or the extension changes, and the old file with the old name now sits in
   `Superseded/`, where Auto Relocate could find it instead). The step becomes a manual Relocate; the stage A live
   check (§8) confirms it, including `.m4a` → `.aiff`.

---

## 1. Architecture (binding interfaces)

### 1.1 The package `discjockey/rekordbox/`

| Module | Owns | I/O |
|---|---|---|
| `__init__.py` | Docstring: what the package owns, the "read only in stage A" line, credit to pyrekordbox and rekordbox-edit for the published format knowledge (no code copied). Re-exports the names below | – |
| `locate.py` | `Place`, `locate()`: options.json, fallbacks, `DISCJOCKEY_REKORDBOX`, the app version | reads files |
| `master.py` | `KEYS`, the keyed read-only open, guards 1, 2 and 4, `Entry`, `entries_for`, `cue_counts`, `status()` | SQLCipher reads |
| `process.py` | `running() -> bool` (`/bin/ps -Axco comm=`, exact line `rekordbox`) | one subprocess |
| `anlz.py` | PMAI parsing: tag spans, `PPTH`, `PQTZ` beat count, `PWV3` heights. Stage B adds `splice_ppth` here | reads bytes |
| `timing.py` | **Pure.** `measure`, `expected`, `decide` | none |
| `probe.py` | ffmpeg side of timing: native mono decode (reuses `quality.decode_mono`), `start_trim` | ffmpeg |
| `offset.py` | `timeline_offset(old_file, ...)`: everything above composed into one answer per file | composes |
| `eligible.py` | **Pure.** Per action `Eligible` or `Skip(reason)` (design §2.2), `expected_tags`, `tags_clean`, `text_plan` | none |
| `preview.py` | `preview(...)`: the read-only answer `rekordbox preview` prints and the bridge's later `rekordbox_preview` returns | composes |

`CLAUDE.md`'s layout gets one row for the package. The `db.py` row's "Nothing else writes SQL" becomes "Nothing else
touches `library.db`'s SQL; rekordbox's `master.db` only through `discjockey/rekordbox/master.py`".

### 1.2 Types and signatures

Names and fields are binding; the implementer picks internals.

```
Place(db: Path, share: Path, source: "options" | "default" | "override", app_version: str | None)
locate(env=os.environ, home=Path.home()) -> Place | None          # None: no master.db (rekordbox 5's datafile.edb counts as none)

Status(state: "ready" | "none" | "unreadable", running: bool, version: str | None, library: str | None,
       problem: None | "unclean" | "busy" | "key" | "db_version" | "schema", db_version: str | None, dbid: str | None)
status(place: Place | None, running: Callable[[], bool] = process.running) -> Status

Entry(id: str, folder_path: str, file_name: str, file_type: int, analysis_path: str | None, title: str,
      artist: str, album: str, label: str, isrc: str, comment: str, cloud: bool, created_at: str | None)
open_read(place, running: bool) -> contextmanager[Master]            # raises Unreadable(problem)
Master.entries_for(path: Path) -> list[Entry]
Master.cue_counts(ids: list[str]) -> dict[str, int]

anlz.read(path) -> Anlz(header_len, tags: list[Tag(fourcc, start, header_len, total_len)], data: bytes)
anlz.ppth(a) -> str | None;  anlz.beat_count(a) -> int;  anlz.pwv3_heights(a) -> np.ndarray | None  # uint8, & 0x1F

Measured(offset_s: float, score: float)
timing.measure(heights, audio, sr) -> Measured | None                # None: too short to measure
timing.expected(codec: str, sr: int, trim_samples: int) -> list[float]   # seconds, deduplicated, ascending
timing.decide(measured: Measured, expected: list[float]) -> Decided(offset_s | None, reason: None | "timing")

probe.start_trim(path, codec) -> int                                  # native samples ffmpeg drops at the start

TimelineOffset(samples: int | None,                                   # d in 44.1 kHz samples; None = unknown
               why: "no_rekordbox" | "not_in_rekordbox" | "format" | "no_cues" | "measured"
                    | "not_analysed" | "timing" | "unreadable",
               rekordbox: Status, entries: list[EntryTiming])
EntryTiming(entry: Entry, cues: int, grid: bool, pwv3: bool, offset_ms: float | None, expected_ms: float | None,
            score: float | None)
timeline_offset(old_file: Path, *, place=<locate()>, running=process.running, decode=quality.decode_mono,
                trim=probe.start_trim, probe_audio=quality.probe) -> TimelineOffset
```

`Master` is read-only in stage A: it has no method that writes, and its connection is opened read-only (§0.1), so
a write would fail in SQLite itself. Stage B adds a separate `open_write` beside it with guards 3, 5, 6 and 7.

`KEYS` is a tuple of 64-hex-character strings tried in order; the open sends `PRAGMA key = '<hex>'` as its first
statement (passphrase form, SQLCipher 4 defaults), then a read of `sqlite_master` proves the key. **Check first:**
the value is the one pyrekordbox publishes; take it from pyrekordbox's published source fetched into a scratch folder
(never from a rekordbox install) and compare with the research notes of 2026-11-07 the coordinator holds; then
confirm the passphrase form against the coordinator's research copy only if they hand you one. Tests don't depend
on the real value (the fixture is built with `KEYS[0]`); the maintainer's acceptance run (§8) proves it.

### 1.3 Finding rekordbox (design §5.1)

- `DISCJOCKEY_REKORDBOX=<folder>` replaces everything: `<folder>/master.db`, `<folder>/share`, `app_version` None.
- Else `~/Library/Application Support/Pioneer/rekordboxAgent/storage/options.json` (`db-path`,
  `analysis-data-root-path`); else `~/Library/Pioneer/rekordbox/master.db` and `…/share`. **Check first:** the file's
  shape (pyrekordbox reads it as a list of `[name, value]` pairs under `options`); an unreadable file falls back.
- `app_version`: the newest `/Applications/rekordbox */rekordbox.app/Contents/Info.plist`
  `CFBundleShortVersionString`; shown and logged, never a guard.
- An ANLZ path is `share` + `AnalysisDataPath` (it starts with `/PIONEER/USBANLZ/…`); `.EXT` beside the `.DAT`.
  **Check first:** the join on pyrekordbox's published code.

### 1.4 Guards in stage A (read side only)

1. Key opens → else `unreadable`, `problem: "key"`. 2. `djmdProperty.DBVersion` in `{"6000"}` → else
`unreadable`, `"db_version"`. Every column stage A reads exists (`PRAGMA table_info` on `djmdContent`, `djmdArtist`,
`djmdAlbum`, `djmdLabel`, `djmdCue`, `djmdProperty`, `contentFile`, `agentRegistry`) → else `unreadable`,
`"schema"`. The column list is one constant (`READ_COLUMNS`) stage B extends with what it writes. 4. A `-wal` or `-shm`
beside `master.db` while rekordbox is not running → state stays `ready`, `problem: "unclean"` (stage B refuses
writes on it; reading is still right). Running and the open fails → `ready`, `running: true`, `problem: "busy"`.
`dbid` comes from `djmdProperty.DBID`.

### 1.5 Finding the track (design §5.4)

`entries_for(path)`: rows with `rb_local_deleted = 0` and `FileType <> 25` whose `FolderPath`, NFC-normalised and
case-folded, equals the absolute path's; on APFS also when `os.path.samefile` holds for a row whose folded path
differs only in form. Artist, album and label come by id from their lookup tables (`''` when the id is NULL or has no
row). `cloud` is `usn IS NOT NULL OR rb_local_synced <> 0`. **Check first:** `rb_LocalFolderPath` stays out of the
match unless a fixture row from the research shows it filled (design §5.5).

### 1.6 ANLZ (binding layout; **check first** against Deep Symmetry's crate-digger analysis docs)

Big-endian. File header: `PMAI`, `u32 header_len`, `u32 file_len`. Then tags back to back: `fourcc`, `u32
header_len`, `u32 total_len`. `PPTH`: `u32 path_len` (bytes), then UTF-16BE with a trailing NUL. `PQTZ`: after its
header `u32 0`, `u32 0x00800000`, `u32 beat_count`, then 8-byte beats (`u16 number, u16 tempo×100, u32 time_ms`).
`PWV3` (in `.EXT`): header with `u32 entry_bytes` (1), `u32 entries`, `u32 0x00960000`, then one byte per column at
150 columns per second; height `byte & 0x1F`. The parser keeps the original bytes and each tag's span, so stage B's
splice can rewrite one tag and keep every other byte; an unknown tag is skipped by its `total_len`. A malformed
file (lengths past the end, wrong magic) is "no analysis", never a crash.

### 1.7 Timing (design §3.2–§3.4; binding values)

- Envelope: the old file's default ffmpeg decode, mono, native rate; peak absolute sample per 1/150 s window, for
  any fractional start. Build a running max over one window length in O(n) (block prefix/suffix maxima with
  `np.maximum.accumulate`) and sample it per shift; a per-shift re-scan of windows is too slow (6 min × 561 shifts).
- Shifts −60 ms to +80 ms in 0.25 ms steps; score = Pearson correlation of heights and envelope over the columns
  from 40 on; best shift refined by a parabola through its neighbours.
- Accept when `score ≥ 0.90` and the refined value is within **0.25 ms** of an expected value: use **that expected
  value**. Else `timing`. Expected sets: PCM (any `pcm_*`), FLAC, ALAC `{0}`; AAC and other lossy `{0, trim}`;
  MP3 as §0.2. Several entries for one file must snap to the same value, else `timing`.
- No `PWV3` for a track (no `AnalysisDataPath`, file missing, unparsable): no cues and no grid → `no_cues`, d = 0;
  format set `{0}` → `format`, d = 0; else `not_analysed`, d unknown.
- `d` → 44.1 kHz samples: `round(d_s × 44100)`.
- Speed target: one 6-minute file measured (decode included) in under 3 s on the maintainer's Mac.

### 1.8 Rendering (design §3.1)

`audio.render_aiff(src, dst, shift_samples)`: one ffmpeg run; any input; `RESAMPLE` (and `-sample_fmt s16`) only
when the input is not already 16-bit/44.1 kHz PCM, so such an input keeps its samples exactly; the shift is applied
after resampling (`atrim=start_sample=k,asetpts=PTS-STARTPTS` for k > 0, `adelay=delays=<−k>S:all=1` for k < 0);
`pcm_s16be` AIFF; no metadata (callers tag). Raises `ConversionError`. `quality.probe` gains `bits: int | None` and
`channels: int | None` (defaults keep its callers), which `render_aiff` reads to decide. `upgrades.build_staged`
keeps its shift-0 copy and otherwise calls `render_aiff` then `copy_tags`.

### 1.9 New track lined up (design §7.2)

`upgrades.add_new(paths, state, track_id, upgrade, compare=align.compare_files, offset=rekordbox.timeline_offset,
now=datetime.now)`:
1. Precondition as today; **measure `L` again** (`compare`), as `swap` does.
2. Same edit (`exact`/`shifted`) and `offset(old).samples` known → `k = L − d`. `k == 0` → today's rename, check
   `aligned: true`. Else render: `build_staged(parked, .discjockey/.tmp/<track>/new.aiff, k)`, then one `run_op`
   with three renames in this order: old → `Superseded/…` (as today), staged → the new name (as today's target
   rule), parked → `_held_place(…)` (kept for the undo, as `swap`). Any failure before `run_op` removes the work
   folder and raises `UpgradeProblem` ("Nothing was changed; the {what} is still waiting.").
3. Different/unknown edit, or `d` unknown → today's rename, `aligned: false`.

Check record: `{reason: "added_as_new", since, match, offset_ms, aligned: bool}` plus `undo`. The undo record of a
rendered add gains `held` and `rendered: true`; `file_key` is the render's key. `undo` of a rendered add: one
`run_op`: the render → a free place in `.discjockey/undo/<track>/` (pruned by `_prune_undo`, as a swap's kept copy
is: Discjockey's own file whose audio exists as the download), held → parked, old → its old path. Records without
`rendered` undo as today. **Check first:** that `run_op` takes a source in `.discjockey/.tmp/` to a watched folder on
another drive (`journal_crossings`), and that `clear_tmp` removes a work folder a crash left.

Callers: `hub/api.py` passes `self._svc.timeline_offset` (a new `Services` field, default
`rekordbox.timeline_offset`); `upgrades_cmd` the default.

---

## 2. Commands (agent-ready; design §10)

`cli.py` moves to argparse sub-commands. No command is still the sync; `setup`, `update`, `upgrades`, `hub` keep
their behaviour and the top-level flags (`--yes`, `--dry-run`, `--limit`, `--verbose`, `--extra`) keep working
(every existing `tests/test_cli.py` case passes unchanged). New: `rekordbox` with `status` and `preview`.

**`discjockey rekordbox status [--json]`.** Read-only, no library lock, no music folder needed. Human lines:
`ready` → "rekordbox library found: {library}" and "rekordbox {version} is open." / "rekordbox is closed." (no
version: "rekordbox is open."); `none` → "No rekordbox library on this Mac."; `unreadable` → "Discjockey can't open
this rekordbox version's library yet."; `problem: "unclean"` adds "rekordbox didn't close normally last time. Open
rekordbox and quit it before Discjockey changes anything there." JSON: `{"ok": true, "state", "running", "version",
"library", "problem", "db_version"}`. Exit 0 whenever it answered (none and unreadable are answers); 1 only on an
unexpected error (`{"ok": false, "kind": "failed", "message"}`).

**`discjockey rekordbox preview (<track> | --path <file>) [--json]`.** Read-only, no library lock (it reads the
snapshot with `library.load_state`), decodes the old file (1–3 s). JSON:

```
{"ok": true, "track": "<key>" | null, "file": "<abs path>", "codec", "sample_rate", "bits",
 "new_file": "<path>" | null, "superseded": "<path>" | null,
 "rekordbox": {"state", "running", "problem"},
 "timing": {"result": <TimelineOffset.why>, "offset_samples": int | null},
 "entries": [{"id", "cues", "grid", "pwv3", "offset_ms", "expected_ms", "score", "cloud", "fields_kept": [..]}],
 "eligible": {"same_track": null | "<reason>", "convert": null | "<reason>", "rename": null | "<reason>"}}
```

`null` in `eligible` means eligible. `new_file` is the name Same track (non-AIFF) or Convert would give
(`NameReserver.choose(folder, expected_stem(...), ".aiff", key)` on a fresh reserver; nothing is reserved), the
file's own path for an AIFF swap; `superseded` where the old file would go. With `--path` for a file the library
doesn't know: `track` null, `new_file`/`superseded` null, every `eligible` value `"not_in_library"`. Exit 0 when
answered; 1 for an unknown key or a file that isn't there (`kind: "refused"`, `reason: "unknown_track"` /
`"file_missing"`) or a failed decode (`kind: "failed"`); 2 no music folder (with a key) as `cli.main` does today.
Human output: the file, rekordbox's state, one line per entry (cues, grid, offset and score), one line per action
("Same track: possible" or "Same track: not now ({reason in words})").

**Reason keys (binding, `eligible.REASONS`; words in §3):** `no_upgrade`, `needs_choice` (different or unknown
edit), `file_missing`, `away`, `rekordbox_unreadable`, `timing`, `not_analysed`, `cloud`, `downloaded` (a file
Discjockey downloaded: `source` isn't `manual`), `clean_aiff` (Convert: nothing to do), `named_already`,
`needs_convert` (Rename: not a clean AIFF), `no_name` (no artist or title), `not_in_library`, `auto_refused`
(reserved for stage C). Stage B adds the run-time refusals (`unclean`, `changed`, `space`) to the same list.

**Eligibility rules** are the design's §2.2 table, as pure functions over `(entry, facts, rb: Status, timing:
TimelineOffset | None)`; `facts` = `FileFacts(ext, codec, sample_rate, bits, tags: {title, artist, album},
has_cover)`, read by a new `audio.file_facts(path)` (ffprobe through `quality.probe`, tags with mutagen).
`expected_tags(entry, old_tags)` follows design §3.5 (title and artists from the record; album from the record when
linked, else the old tag); `tags_clean` compares NFC-stripped TIT2/TPE1/TALB and the cover when the record has one.
`text_plan(entry_row, old_tags, clean) -> {field: "write" | "kept"}` is design §5.11's rule (fields title, artist,
album, label, isrc, comment; empty and missing equal; artist as the joined string); `fields_kept` lists the `kept`
ones. **Check first:** the entry fields (`album`, `isrc`, `image_url`, how several artists are stored) and
`importer.read_tags`, whose reader `file_facts` reuses.

---

## 3. Words the user sees in stage A

| Where | Text |
|---|---|
| `report.check_text`, added_as_new, `aligned` and exact/shifted | "This is the same edit, lined up with your old file to the sample. In rekordbox: relocate your old track to the new file (right-click › Relocate); its cues fit exactly." |
| Same, not aligned (old records and unknown `d`) | today's `SAME_EDIT_CHECK` / `SHIFTED_EDIT_CHECK`, unchanged |
| `views.check_status` | unchanged ("relocate, analyse again") |
| To-do / Library check card (`decisionModel.checkCard`), first step for every added_as_new | "Right-click your old track › **Relocate** › choose the new file" (replaces "The track shows as missing: Auto Relocate finds the new file by name") |
| Same card, second step when `aligned` | "Analyse it again" · note "· your cues fit exactly" (not aligned: today's notes) |
| Reason words in `preview` (human) | `needs_choice` "it's a different edit, so you choose", `rekordbox_unreadable` "Same track needs a rekordbox library Discjockey can open", `not_analysed` / `timing` / `cloud` as design §8 without "Nothing was changed", `downloaded` "a file Discjockey downloaded is clean already", `clean_aiff` "already a clean AIFF", `named_already` "already has its clean name", `needs_convert` "needs Convert to AIFF first", `no_name` "no artist or title known", `away` "its drive isn't connected", `file_missing` "the file isn't where Discjockey expects it", `no_upgrade` "no better version is waiting", `not_in_library` "not a file of your library" |

**Screens:** no new screen, state or block. Only words inside the existing check card change (the "Check in rekordbox"
group on To-do, the Library details' check). No design round (CLAUDE.md "UI only after an approved mockup" is about
new UI); the change still goes through the UI checks: vitest on `decisionModel`, `npm run check`, rules on the touched
shots, one look at the two cards, `npm run verify` once before the merge, `build(hub): static`.

**Contract:** `check_view` gains `aligned: boolean` (false for old records). `docs/hub-bridge-contract.md`,
`types.ts` (`RekordboxCheckView`), `contract.ts`, the fake (`replaced(...)` in `pages/todo/fake.ts`: the existing
`after-add-same` becomes aligned; a new `after-add-shifted-old` keeps the old words) and `shots.json` in the same
commit.

---

## 4. Tests and fixtures (offline, fast)

### 4.1 `tests/conftest.py`
Two autouse fixtures: `DISCJOCKEY_REKORDBOX` → an empty temp folder (state `none`) for every test; and
`discjockey.rekordbox.process.running` → a stub returning False (no test depends on the maintainer's open
rekordbox). A test pins both, and that `locate()` under the override never reads `~/Library` (a `home` that doesn't
exist).

### 4.2 `tests/rekordbox_helpers.py`
- `make_master(folder, rows, key=KEYS[0], version="6000", dbid="1234567890")`: SQLCipher with the same `PRAGMA key`,
  WAL mode, then a clean close (no `-wal`/`-shm` left). Tables: `djmdContent` with rekordbox 7's full column list
  (one constant here; **check first:** the names from pyrekordbox's published table definitions, names only),
  `djmdArtist`, `djmdAlbum`, `djmdLabel`, `djmdCue`, `contentCue`, `contentFile`, `djmdProperty`, `agentRegistry`,
  `djmdSongPlaylist`, `djmdSongHistory`, `djmdSongMyTag`, with rows carrying cues, playlists and history. Stage B's
  whole-row compare uses the same builder, so it is complete now.
- `make_anlz(path, tags)`: PMAI files with `PPTH`, `PQTZ`, `PWV3` and one unknown tag (`PVB2`-like bytes).
- `pwv3_from(audio, sr, extra_s)`: heights as rekordbox shows them: the audio delayed by `extra_s`, peak per 1/150 s,
  scaled to 0–31, plus a little noise.
- `clicks(seconds, sr, bpm=120)`: a click track with a varied click shape so the correlation has one peak.

### 4.3 Audio fixtures
- M4A (bundled ffmpeg's native `aac`), FLAC, 24-bit/96 kHz FLAC, 48 kHz WAV, 16-bit AIFF: made in the test.
- Two MP3 click tracks, committed under `tests/fixtures/` (`clicks-lame.mp3` with a LAME/Xing tag, `clicks-notag.mp3`
  without; 30 s mono, 64 kbps, under 300 KB each), made once with an ffmpeg that has `libmp3lame` (the bundled one
  hasn't, issue 19). The exact commands go into `rekordbox_helpers.py`'s docstring, as `test_ops.py` documents
  `noise-128k.mp3`.
- No real music, no real library, no real `master.db`.

### 4.4 Behaviours to pin (stage A share of design §12)
- **Open and guards:** the right key opens; a wrong key → `unreadable/key`; `DBVersion` 5999 → `db_version`; a
  missing read column (one in a lookup table too) → `schema`; a `-wal` with rekordbox closed → `ready/unclean`;
  running + open failing → `ready/busy`; no `master.db` → `none`; a `datafile.edb` only → `none`.
- **No trace:** status and preview leave the fixture folder identical (no new files, same bytes and mtimes).
- **Read-only:** a write through `Master`'s connection fails (proves the read-only open).
- **Lookup:** exact path, NFD vs NFC, case variants; deleted and streaming rows ignored; two rows for one file both
  returned; lookup names joined, NULL ids → `''`; `cloud` from `usn` and `rb_local_synced`.
- **ANLZ:** `PPTH`, beat count and heights read back; an unknown tag skipped; truncated and wrong-magic files →
  no analysis.
- **Timing (pure):** a synthetic shift recovered within ±5 samples and snapped to the expected value; score below
  0.90 → `timing`; a value off every expected value by > 0.25 ms → `timing`; two entries disagreeing → `timing`;
  each §1.7 no-`PWV3` branch; the MP3 union set.
- **Timing (ffmpeg):** `start_trim` of the test M4A equals its edit list's skip and of `clicks-lame.mp3` its tag's
  delay; `timeline_offset` on M4A and both MP3s with `pwv3_from(trim)` → `measured` with the exact snapped value.
- **Render:** a 16/44.1 AIFF keeps its samples exactly at shift 0 and is shifted by exactly k samples (both signs);
  24-bit/96 kHz FLAC and 48 kHz WAV → 16-bit/44.1 kHz; the clicks of the test M4A and the MP3 fixtures sit, after
  `render_aiff(old, k = −d)`, at their rekordbox-timeline positions (`pwv3_from`'s) to ±1 sample.
- **New track:** same edit + AIFF old file → rendered with `L`; MP3 old file with an analysed entry → `L − d`;
  `k == 0` → renamed as today, `aligned: true`; `d` unknown → renamed as today, `aligned: false`; different edit →
  renamed as today; the parked file held in `.discjockey/undo/`; undo of a rendered add puts the old file and the
  parked download back and moves the render into `.discjockey/undo/`; "Done" deletes the held copy; an old record
  without `rendered` undoes as today; a crash inside the `run_op` finishes on recovery (existing harness); a render
  failure leaves nothing and no work folder.
- **Words:** `check_text` for aligned, not aligned and old records; `checkCard` steps (vitest).
- **Eligibility (pure):** every row of design §2.2 both ways; `tags_clean`; `text_plan` (equal → write, edited →
  kept, empty vs missing equal).
- **Commands:** `status` and `preview` human and `--json` shapes, exit codes 0/1/2, `--path` inside and outside the
  library, no lock taken (a held lock doesn't block them).
- **Packaging:** the hand-kept list includes `openssl.txt` and `sqlcipher.txt`; `PRAGMA cipher_version` and
  `PRAGMA cipher_provider_version` of the installed module equal the versions on those texts' first lines; the
  self-test's keyed check passes, and fails for a module that opens the file without the key.

---

## 5. Task groups (one agent each, in this order)

Every group: read `CLAUDE.md` and this plan; run its touched tests while working, the full `uv run pytest -q | tail -3`
once at the end, `scripts/check_public.sh --require-denylist` before each commit; commits `feat(rekordbox): …`,
`test(rekordbox): …`, `build(deps): …`. Hard stop at about 80 tool calls: commit what is green and report what is
left. Never start rekordbox, never read `~/Library/Pioneer` or the real library, no waiter loops or `pgrep`.

### A0. The dependency, packaging, self-test — Sonnet, ~130–170k
Files: `pyproject.toml`, `uv.lock`, `packaging/licenses/{sqlcipher,openssl}.txt`, `packaging/collect_licenses.py`
(`hand_kept_label` lines: "SQLCipher {v} community (built into sqlcipher3-wheels {pin}): BSD-3-Clause-style, with
SQLite (public domain)", "OpenSSL {v} (built into sqlcipher3-wheels {pin}): Apache-2.0"; the versions from the texts'
first lines, the pin from `pyproject.toml`), `packaging/discjockey.spec` (only if the check below needs a hidden
import), `discjockey/selftest.py`, tests.
1. `uv add 'sqlcipher3-wheels==0.5.7'`; commit `build(deps): add sqlcipher3-wheels 0.5.7` with the reason line: "to
   read rekordbox's encrypted master.db (issue 33): SQLCipher 4.12 and OpenSSL 3.6 linked statically, zlib licence;
   the only new dependency of the rekordbox work, pinned exactly because it carries the crypto".
2. Licence texts: SQLCipher Community Edition's licence (Zetetic) with SQLite's public-domain notice; OpenSSL's
   Apache-2.0 text; first line names the exact version. **Check first:** both texts from the projects' own
   repositories at those versions.
3. Self-test: `sqlcipher3` in `THIRD_PARTY`; a new `check_sqlcipher(work)`: create a keyed file with a throwaway key,
   reopen with it and read the row, reopen without it and expect failure. It uses `sqlcipher3` directly (A1's module
   doesn't exist yet); A1 switches it to `rekordbox.master`'s open helper.
4. **Check first** (background, status line): `scripts/build_app.sh` with `SKIP_UI_BUILD=1`; the built app's
   `--self-test` passes; the licences folder has both texts; `codesign --verify --deep --strict` passes (the `.so` is
   signed by `sign_app.py`). Add a hidden import only if the self-test says the module is missing. Delete the build
   output afterwards.
5. CI needs nothing new (`uv sync --frozen` on `macos-15` installs the arm64 wheel); the group confirms on its
   branch push that `check.yml` is green.
Stop point: the dependency commit and the packaging commit green.

### A1. rekordbox read side: locate, key, guards, lookup — Opus, ~250–300k
Files: `discjockey/rekordbox/{__init__,locate,master,process}.py`, `tests/rekordbox_helpers.py` (`make_master`),
`tests/conftest.py`, `tests/test_rekordbox_master.py`, `tests/test_rekordbox_locate.py`, `selftest.py` (use the open
helper), `CLAUDE.md` (layout row, `db.py` row, the conftest mention in the `tests/` row).
Builds §1.2–§1.5 and §4.1–§4.2's `make_master`. Pins §4.4 "Open and guards", "No trace", "Read-only", "Lookup".
**Check first:** that `sqlcipher3.connect(uri, uri=True)` takes the `immutable=1` and `mode=ro` URIs and `PRAGMA key`
as first statement; that a `mode=ro` open beside an existing `-wal`/`-shm` (the fixture opened by a second writer
connection standing in for rekordbox) reads committed rows.
Stop point: status works end to end on the fixture (Python call, no command yet).

### A2. ANLZ and timing — Opus, ~280–330k
Files: `discjockey/rekordbox/{anlz,timing,probe,offset}.py`, `tests/rekordbox_helpers.py` (`make_anlz`,
`pwv3_from`, `clicks`), `tests/fixtures/clicks-*.mp3`, `tests/test_rekordbox_anlz.py`,
`tests/test_rekordbox_timing.py`.
Builds §1.6, §1.7, `timeline_offset`. Pins §4.4 "ANLZ", "Timing (pure)", "Timing (ffmpeg)".
**Check first:** the ffmpeg flags for the untrimmed decode with the bundled build (`-flags2 +skip_manual` for MP3,
`-ignore_editlist 1` for MP4) and §0.3's matching on the test M4A and both MP3s; the ANLZ layout against
crate-digger's docs. The timing tests run on the bundled ffmpeg in CI (`needs_ffmpeg` where a test decodes).
Stop point: `timeline_offset` answers `measured` with the exact value for the M4A and both MP3 fixtures.

### A3. Render and New track lined up — Opus, ~220–280k
Files: `discjockey/audio.py` (`render_aiff`), `discjockey/quality.py` (`probe`: `bits`, `channels`),
`discjockey/upgrades.py` (`build_staged`, `add_new`, `undo` for rendered adds, module docstring), `discjockey/report.py`
(`ALIGNED_EDIT_CHECK`, `check_text`), `discjockey/hub/api.py` (`Services.timeline_offset`, the call),
`discjockey/upgrades_cmd.py` (the call), `scripts/make_upgrade_test.py` (`--keep-lossy m4a`, for the live check §8),
tests `test_audio.py`, `test_upgrades.py`, `test_upgrade_undo.py`, `test_report.py`, `test_make_upgrade_test.py`.
Builds §1.8, §1.9 and the engine half of §3. Pins §4.4 "Render", "New track", the engine "Words".
**Check first:** §1.9's two checks; that `swap`'s results stay byte-identical (its tests unchanged).
Stop point: New track renders and undoes on a tmp library.

### A4. Words in the window, contract, README — Sonnet (words fixed by §3), ~150–200k
Files: `discjockey/hub/views.py` (`check_view.aligned`), `docs/hub-bridge-contract.md`, `hub-ui/src/lib/bridge/types.ts`,
`contract.ts`, `hub-ui/src/lib/decisions/decisionModel.ts` (+ its `.test.ts`), `hub-ui/src/pages/todo/fake.ts`,
`hub-ui/src/pages/todo/shots.json`, `hub-ui/src/pages/library/shots.json` if its check shot changes,
`hub-ui/src/lib/dev/Gallery.svelte` (its New track sample words), `README.md` (Upgrades › New track: the new file is
lined up to the sample when Discjockey can measure rekordbox's timing; Relocate your old track to it by hand; the
Auto Relocate sentence goes; the rekordbox section's last bullet follows).
Own checks: `npx vitest run src/lib/decisions`, `npm run check`, `npm run rules -- --page todo --only <added shots>`,
one screenshot of each card at 1280 looked at, `npm run build` → `build(hub): static`. `npm run verify` is not run
here (once per branch, §6).
Stop point: the two cards shot and looked at.

### A5. Eligibility, preview, the commands, agent entries — Sonnet, ~200–260k
Files: `discjockey/rekordbox/{eligible,preview}.py`, `discjockey/audio.py` (`file_facts`), `discjockey/cli.py`,
`tests/test_rekordbox_eligible.py`, `tests/test_rekordbox_preview.py`, `tests/test_cli.py`, `CONTRIBUTING.md`
("Commands for scripts and agents": both commands, flags, JSON shapes, exit codes, that they are read-only and take
no lock), `docs/issues.md` (issue 39: "issue 33 stage A's commands are in CONTRIBUTING.md › Commands for scripts and
agents; gather them"; issue 33: stage A built, live check pending).
Builds §2. Pins §4.4 "Eligibility", "Commands".
Stop point: both commands on the fixture library and fixture rekordbox.

### R. Stage review — Opus, ~140–170k; fix round — fresh Sonnet, ~115–145k
The review reads the diff against this plan and the design (interfaces for stage B, the read-only rule, timing values,
words, no trace on `master.db`), runs the full suite once, and lists findings by severity. Minors are fixed in the
same fix round (no leftovers). Then `npm run verify` once in the background (about 20 min), CI green on the stage
branch push, merge into `main` (`Merge feat/rekordbox-a: rekordbox read side, New track lined up`).

Total: about 1.4–1.8 M tokens over 7 agent runs, one at a time.

---

## 6. Docs, issues and the end of the stage

- **README:** §3's New track text (A4). The rekordbox commands aren't for the window's user; the README's existing
  pointer to CONTRIBUTING covers them.
- **CONTRIBUTING.md:** the agent entries (A5).
- **CLAUDE.md:** the package row and the `db.py` row (A1); the commands row is unchanged (the new commands live in
  CONTRIBUTING). The invariant texts of design §2.5 and §7.1 change in stages B–D, not here.
- **Contract:** `aligned` (A4). **Design language:** untouched (no block changes).
- **Issues:** issue 33's entry says "stage A merged (`<sha>`), live check pending; stages B–E open"; issue 39's line
  (A5). A finding out of scope goes into `docs/issues.md`.
- **Archive:** when the live check (§8) passes, `git mv docs/2026-11-07-rekordbox-stage-a-plan.md docs/archive/`
  in the same commit that records it; the design stays in `docs/` until stage E (or its last stage) is done. Any
  stage A gap left open moves into issue 33.
- **No release** for stage A: it changes New track only; the next release waits for stage B's live test (design §13).

---

## 7. Interfaces stage B builds on (so A doesn't need redoing)

- `master.py`: `READ_COLUMNS` grows into the write guard's list; `open_write` sits beside `open_read`; `Entry` already
  carries the identity and text columns undo needs.
- `anlz.Anlz` keeps the original bytes and spans: `splice_ppth(a, new_name) -> bytes` adds to it.
- `timeline_offset` is what `convert` calls for `d`; its `entries` hold the measurements the batch JSON prints.
- `eligible.REASONS` is the one list of reason keys for `--json`, the bridge and the words; stage B appends.
- `preview()` is the body of the later bridge method `rekordbox_preview(track_id)` (decodes: run it where the
  spectrum read runs, design §11).
- `render_aiff` is the renderer of `convert`; `text_plan` is §5.11's rule the write applies.
- `Services.timeline_offset` is the injection point; stage B adds `Services.rekordbox` (place, `running`, open).

---

## 8. Live check at the end of stage A (the user, about 15 minutes)

Run by the maintainer on their Mac with rekordbox closed for steps 1–2; only reads rekordbox's library.

1. `discjockey rekordbox status`: "ready", the right library, "rekordbox is closed"; then open rekordbox and run it
   again: "rekordbox … is open". (The acceptance of design §13: the key opens their rekordbox 7 library.)
2. `discjockey rekordbox preview --path <file>` on three tracks the research measured (an MP3, a 48 kHz M4A, an
   AIFF): the offsets agree with the research numbers (MP3 1105 or 2257 samples, M4A about 21.5 ms, AIFF 0). The
   agent compares; the user only runs the commands or lets the agent run them.
3. **New track, by ear and by cue:** with `scripts/make_upgrade_test.py --keep-lossy m4a` (A3 adds this option: the
   test's lossy copy stays an `.m4a` instead of being converted back to AIFF) make a test track; import it into
   rekordbox, analyse it, set three hot cues on clear beats, quit rekordbox. In the window choose **New track** for
   it. Open rekordbox, right-click the old track › **Relocate**, choose the new `.aiff`. Check: rekordbox accepts an
   `.m4a` track relocated to an `.aiff` file (if not, the card's words change before any release), the three cues
   sit on the same beats, and it plays without a click at the start. Remove the test files afterwards (the script's
   docstring says how).
