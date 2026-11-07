# Own files become AIFF, and rekordbox's track follows them (issue 33): design

Status: design, 2026-11-07. No code yet. Plans built from it go in `docs/` as `…-plan.md`.

Issue 33 asks that a user's own files (imported from watched folders, or bought; MP3, M4A/AAC, WAV, FLAC) end up in
the library format, 16-bit AIFF. rekordbox's existing track for the file should follow the new file and keep
everything on it: cues, hot cues, beatgrid, history, playlists, My Tags, rating and colour. The bundle: "New track"
should line up sample-exactly, as "Same track" already does.

## 0. What is already known

- **The route is a direct write to rekordbox's `master.db`, made only while rekordbox is closed.** The user decided
  this. A maintainer did it by hand on 2026-10-31 for about 40 M4A tracks, outside Discjockey. Each M4A was decoded to
  16-bit AIFF with rekordbox's start delay kept, and the timing was checked against rekordbox's own waveform (0.0 ms).
  Then the tracks were repointed: the path columns and `PPTH` via pyrekordbox, and `FileType`, `FileSize`,
  `BitDepth`, `SampleRate` and `BitRate` set by hand. Every cue matched the backup, and the tracks played on the beat
  in rekordbox. The AIFFs kept their 48 kHz or 44.1 kHz rate, so **a change of sample rate is still untested**.
- **Gotchas from that run.** A USB stick exported before the repoint still pointed at the old `.m4a`, and rekordbox's
  sync skipped those tracks (0.1 s), so the stick had to be rebuilt. YouTube-rip M4As are AAC at 420–455 kbps. CDJs
  take AAC only up to 320 kbps, which is the likely reason they stutter or don't load.
- **Research findings (2026-11-07) this design relies on.** rekordbox places cues on its own decode timeline, which
  keeps the encoder delay that ffmpeg drops. The extra is 1105 or about 2257 samples on MP3s, about 1600 samples on
  ffmpeg-made 44.1 kHz M4As, and about 21.5 ms on 48 kHz M4As (the live run). It is 0 for AIFF and WAV. The offset can
  be measured per track from rekordbox's `PWV3` waveform to within about ±3 samples. The key is one fixed value, and it
  opened a rekordbox 7.2 database.
- **Checked again for this design** (read-only, on a copy of a maintainer's `master.db`):
  - The database is in **WAL mode**. The research said rollback journal; it is wrong on that point. The `-wal` and
    `-shm` files exist only while a connection is open.
  - `djmdProperty` has `DBID` and `DBVersion` = `6000`. `OrgFolderPath` is `''` and `rb_LocalFolderPath` is NULL on
    every row. `usn` is NULL everywhere (no cloud sync). `updated_at` is written like `2026-10-31 22:32:18.093 +00:00`.
  - **`contentFile` keeps an MD5 `Hash` and the `Size` of every ANLZ file.** After the live run's `PPTH` rewrite those
    are stale for the repointed tracks (2 bytes longer on disk). rekordbox has not flagged or fixed them since
    (`rb_file_hash_dirty` = 0).
  - rekordboxAgent's `options.json` names the library (`db-path`) and the analysis folder
    (`analysis-data-root-path`).

## 1. Decisions at a glance

| Question | Decision | Section |
|---|---|---|
| When is the AIFF made | One engine step, "make an AIFF and point rekordbox at it", with two triggers: Same track on an upgrade (any format), and later "Convert to AIFF", chosen by the user, suggested for files that won't play on CDJs. Never everything at import | §2 |
| Timing | New audio shifted onto **rekordbox's** timeline of the old file, measured from `PWV3` and snapped to the codec's known delay | §3 |
| Format | 16-bit / 44.1 kHz AIFF, the library format, made like every download | §3.5 |
| Name and tags | The download's name (`names.expected_stem`) and the download's tags (`audio.write_tags`), with artwork capped to a CDJ-safe size. The old name isn't kept, because Discjockey repoints rekordbox itself | §3.5, §4 |
| rekordbox's text columns | Left alone. The check card offers Reload Tag (question 4) | §5.11 |
| Rename without converting | The same repoint lets the user rename an own AIFF to its clean name. The "moving never renames" invariant gets a narrower reason; tidy-up is unchanged | §7.1 |
| Where | The old file's folder, under `Artist - Title.aiff`. The old file goes to `Superseded/` (mirrored). One journaled step | §4 |
| Key and code | Our own code (`discjockey/rekordbox/`), with the key in it. The only new dependency is `sqlcipher3-wheels`; no pyrekordbox | §5.2 |
| What rekordbox gets | The path, the file facts, `rb_local_usn`/`updated_at` and the `PPTH` path in the ANLZ files, plus `contentFile` hash and size. Nothing else | §5.5 |
| Safety | rekordbox closed (checked again just before the commit), schema guards, a backup of `master.db` and ANLZ files, an undo per field, crash recovery, refusal for cloud-synced tracks | §5 |
| USB sticks | A step in the rekordbox check: remove the track from the stick and export it again. The live test finds the smallest fix | §6 |
| Staging | A: read side + New track lined up. B: write side + Same track for any format. Live test. C: Convert without an upgrade. D: repoint after Discjockey's own moves (own issue) | §13 |

## 2. Shape: when the AIFF is made

**One step, two triggers.** The engine step `convert` takes one track whose current file isn't AIFF, plus a source
of audio. The source is either the parked upgrade (lossless or a better stream) or the current file itself. The step
writes `Artist - Title.aiff` lined up to rekordbox's timeline. If rekordbox has a track for the file, the step points
it at the new file. Then the old file moves to `Superseded/`.

1. **Same track on an upgrade (stage B).** This is the research's pick, and it is what the user asked first. Today
   Same track exists only for AIFF files (an in-place swap). From now on it is offered for any format when the
   versions are the same edit. For an AIFF file nothing changes: the swap stays in place, with no rekordbox write.
2. **Convert to AIFF without an upgrade (stage C).** The user chooses it for one or more of their own files. The
   To-do page suggests it for files that won't play well on CDJs. The audio stays the same; only the container and
   format change.

**Why not everything at import.**
- Converting lossy audio to AIFF doesn't improve the sound. It costs 5–10 times the disk space (a maintainer's
  collection would grow by about 15 GB).
- It would write rekordbox's database for every track at once, the riskiest write, in the biggest batch.
- It would run while the user is busy importing, not when they are deciding about a track. The user's go must come
  per action.
- After this design, a later upgrade of a converted track is a plain in-place AIFF swap anyway. So converting early
  only saves the database write for tracks that would never be upgraded.

**Why not only at upgrade time (the CDJ fact).** Many of a DJ's own files will never get a lossless upgrade: rips,
bootlegs, edits that aren't on Qobuz. Some of them don't play reliably on CDJs (AAC above 320 kbps, sample rates or
codecs a player doesn't take). For those, converting is the fix, and the risk is the same as for an upgrade. So the
same step is offered without an upgrade, but only when the user chooses it, and only suggested where a CDJ problem is
likely. Stage C needs its own design round (§9.2), and its To-do group is a question for the user (§15).

**What Discjockey records.** A converted lossy file stays "not lossless" in Discjockey's records: its file row
keeps `status`, `source_format` and `source_kbps` from the old file. The Library then says "Your AIFF was made from
this" (the existing `NOW_TIP`), and upgrade checks go on for it. This matters because the file now looks lossless. The
import's sound check must not run again on a file the step wrote. The step writes the file row with its facts and
`placed_by = 'app'`. Check first: that a rescan of a row with known facts and an unchanged content key reads nothing
again.

## 3. Timing: lining the AIFF up to rekordbox's timeline

### 3.1 The model

rekordbox stores cues (`djmdCue.InMsec`, whole ms) and the grid (`PQTZ` in the ANLZ `.DAT`, ms) on its own decode
timeline of the old file. After the repoint it reads the same numbers against the AIFF, whose timeline starts at
sample 0. So the AIFF must hold, at every ms, the audio that rekordbox's decoder produced there from the old file.

The symbols:
- `t_ff`: a moment in ffmpeg's default decode of the old file. This is the gapless trim that `align.decode` and every
  Discjockey measurement use.
- `d` (seconds): rekordbox's offset for this track. A moment at `t_ff` sits at `t_ff + d` on rekordbox's timeline.
- `L` (samples at 44.1 kHz): `align.compare(current, new).offset_samples`. A positive `L` means the audio comes later
  in the new file.

The shift handed to the renderer (samples at 44.1 kHz; positive trims the start, negative puts silence in front, as
`upgrades.build_staged` does today) is:

- **from an upgrade:** `k = L − round(d · 44100)`
- **from the old file itself (stage C):** `k = −round(d · 44100)`

The renderer is one function, `audio.render_aiff(src, dst, shift_samples)`, used by the swap, by New track and by
`convert`. It decodes any format, resamples to 44.1 kHz with the library's filter (`audio.RESAMPLE`, triangular
dither), applies the shift **after** resampling, and writes `pcm_s16be` AIFF. `build_staged` becomes a thin call to
it. Its behaviour for AIFF→AIFF must stay byte-identical: no resampling when the input is already 16-bit/44.1, as
today.

### 3.2 Measuring `d` from `PWV3`

- **Read.** The track's `.EXT` file (`AnalysisDataPath` with `.EXT`, under the analysis root) holds the `PWV3` tag:
  one byte per column at 150 columns per second, height = `byte & 0x1F`.
- **Compare.** Decode the old file with ffmpeg's default decode (mono, native rate). Take the peak absolute sample
  of each 1/150 s window, and correlate that envelope with the heights for shifts from −60 to +80 ms in 0.25 ms steps,
  with a parabolic refinement. Skip the first 40 columns. This is the research's `rbwave.py` method.
  `rekordbox/timing.py` holds it as a pure function: `measure(heights, audio, sr) -> Measured(offset_s, score)`.
- **Expected delays.** `expected(codec, sr, trim_samples) -> list[float]`:
  - `trim_samples` is the start trim ffmpeg applies to this file: its default decode against the untrimmed decode,
    `-flags2 +skip_manual` for MP3 and `-ignore_editlist 1` for MP4. Check first: both flags with the bundled ffmpeg
    build, and that comparing the lengths of the two decodes gives the trim exactly.
  - MP3: `{0, trim, trim + 1152}` samples at the file's rate. M4A/AAC: `{0, trim}`. PCM, FLAC and ALAC: `{0}`.
- **Accept** when `score ≥ 0.90` and the measurement is within **0.25 ms** of one expected value. Then **use that
  expected value**, which is exact to the sample, not the measurement.
- **Refuse otherwise.** This covers a correlation below 0.90, or a value outside the set, such as the one MP3 at
  about +2455 samples and the one WAV at −8 ms in the research. The refusal text is "timing" (§8). The measured
  value goes into the `--json` details, for a later look at such cases.

### 3.3 By format

| Old file | Expected `d` | Notes |
|---|---|---|
| MP3, LAME/Lavc tag | 1105 samples, sometimes 1105 + 1152 | Measured. Which of the two can't be told from the header |
| MP3, no tag | 0 or 1105 (a missed tag) | Measured |
| M4A/AAC (ffmpeg, YouTube) | the edit list's skip (1024 + 576 at 44.1 kHz, about 21.5 ms at 48 kHz in the live run) | Measured. An Apple-made AAC has 2112 priming; the set covers it through `trim` |
| WAV 16/24-bit, AIFF | 0 | Calibration was 0 on 20 entries |
| WAV 32-bit float | 0 | Dithered to 16-bit |
| FLAC | 0 | Not measured on a real entry yet; it is a live-test item (§13) |
| 48 kHz anything | as above, in seconds | Resampled to 44.1 kHz. Cues are in ms, so they survive if rekordbox trusts the file. This is a live-test item |
| 24-bit / 88.2–192 kHz | 0 | Becomes 16/44.1. The original stays in `Superseded/` |

### 3.4 No analysis, or a disagreement

- **No `PWV3`** (the track was never analysed, or the ANLZ files are gone):
  - The track has **no cues** (`djmdCue` rows) **and no grid** (no `PQTZ`): the timing doesn't matter. Use `d = 0`
    and render the plain ffmpeg decode.
  - PCM or FLAC old file: use `d = 0` (the expected set has only 0).
  - MP3 or M4A with cues or a grid: **refuse** with "not analysed" (§8). One analysis in rekordbox fixes it.
- **Several rekordbox tracks for one file:** each is measured. They must agree on the same expected value, else
  refuse ("timing").
- **The file is not in rekordbox:** there are no cues to keep. Use `d = 0` for the timeline and skip the database
  part.

### 3.5 Format and tags of the new file

- **16-bit / 44.1 kHz AIFF**, made like every download (`audio.RESAMPLE`). This is the library format and the safest
  for every CDJ. An upgrade comes at 44.1 kHz anyway.
- **Tags: the download's set (the user's wish).** The new file gets exactly the ID3v2.3 frames that
  `audio.write_tags` writes on every download today:
  - TIT2 title, TPE1 artists joined by ", ", TALB album, TSRC ISRC, TPUB label
  - APIC cover (JPEG, type 3)
  - COMM, Discjockey's quality line (`quality.quality_line`)

  Where the values come from:
  - **From an upgrade:** the parked file's tags, copied with `audio.copy_tags`, as the swap does. They are Qobuz's
    names, cover, label and ISRC, plus the quality line of the new source.
  - **From the old file itself (stage C):** title and artists from the song record (`e["title"]`, `e["artists"]`).
    Album, ISRC, label and cover come from the song record when the song is linked to a playlist song (`songs.album`,
    `isrc`, `image_url`), else from the old file's tags. The comment is the quality line of the old file's format, so
    it says what the AIFF was made from.
  - **Two fields the download set lacks** are carried over from the old file when it has them: genre (TCON) and year
    (TDRC/TYER). They are the user's own, and a Reload Tag in rekordbox would otherwise clear them. Nothing else of
    the old tags is carried over; the old file keeps all of them in `Superseded/`.
  - Check first: the import's tag reader for own files (`importer` pass 1 / `identify`), to reuse for M4A, FLAC and
    WAV.
- **Artwork, CDJ-safe.** A new `audio.cdj_cover(data) -> bytes | None` gives a baseline JPEG at most 600 × 600 px
  (the size of Qobuz's `large`, which downloads use today) and at most 500 KB. It scales with the bundled ffmpeg
  (native `mjpeg`/`png` codecs) when the source is bigger or is a PNG. Every write goes through it, downloads
  included. Today's 600 px Qobuz covers pass unchanged, so downloads stay byte-identical. Large embedded art (3000 px,
  several MB) is a known cause of CDJ trouble. Check first: Pioneer's limit for embedded artwork.

## 4. Where the new file goes, and how it fits the invariants

- **Place.** The new file goes in the old file's folder (`planner.replacement_dir`: "anywhere else: the current file's
  folder"). For a file in a playlist folder's `not_lossless/`, the folder rule is the same as `add_new`'s.
- **Name: the download's name, not the old one.** The name is
  `NameReserver.choose(folder, expected_stem(e["artist"], e["title"]), ".aiff", track_id)`. This is the call
  `execute.py` uses for downloads and `add_new` and `add_bought_file` use for replacements. So the name follows the
  same rules: the first artist, the title as the song record has it (features and mix names written as the service
  writes them), `sanitize_stem`, the length cap, and an ID only when the name is taken. There is no second scheme.
- **Why the old name isn't kept.** Keeping a file's name existed only so rekordbox's Relocate could find it. Here
  Discjockey points the rekordbox track at the new file itself, so the old (often messy) name has no job left.
- **The rule that comes with it:** a step that gives a file a new name **must** repoint every rekordbox track of that
  file in the same step. When it can't, because rekordbox is unreadable, open or cloud-synced, the step is refused, so
  a track is never left looking for a name that no longer exists. When the file has no rekordbox track, the new name
  needs nothing.
- **How clean the name is depends on the song record.**
  - An own song linked to a playlist song carries the service's names.
  - An unlinked one carries the names the import read from its tags or file name.
  - Check first: whether the import cleans own songs' names the way `titles.split_title` cleans uploader titles. If
    it doesn't, an unlinked rip's name can still carry "(Official Video)". That is the record's problem, fixed where
    the record is made, not in this step.
- **The old file** moves to `superseded_dir(path, watched_root(...))`, which mirrors its watched folder, under its own
  name. **Moving never renames.**
- **Never delete, never overwrite.** The new file is a new name. The old file is moved, never written.
- **Every file change through `move_path`.** It is the cross-drive staging copy with its journal, because watched
  folders can sit on other drives than the music folder, where `.tmp/` is. The step is journaled in library.db's
  `pending` as a new op kind, `convert`, with its own marks and recovery (`convert.recover`), like `swap`.
  `run_op` can't carry it as it is, because a database write has to sit between the renames (§5.8).
- **Batches.** Like `swap` and `add_new`, the step is one action the user started on one track. It is not a move
  batch. Its undo lives in the rekordbox check's undo record, as for upgrades today. Stage C's "convert several" is
  N steps in one job, each with its own undo.
- **Offline or missing.** If the old file's drive or folder is away (`file_state`), the step is refused. Free space
  is checked before rendering: the staged size, plus the target drive when it is another drive.

## 5. The rekordbox write

### 5.1 Finding rekordbox

- **Where.** `rekordbox/locate.py` reads `~/Library/Application Support/Pioneer/rekordboxAgent/storage/options.json`
  (`db-path`, `analysis-data-root-path`). If it is missing, it falls back to `~/Library/Pioneer/rekordbox/master.db`
  and `…/share`. The app's version comes from the newest `/Applications/rekordbox */rekordbox.app` Info.plist and is
  shown and logged only, never a guard.
- **`DISCJOCKEY_REKORDBOX=<folder>`** replaces the whole lookup (`<folder>/master.db`, `<folder>/share`), for tests
  and scratch runs. `tests/conftest.py` sets it to an empty temp folder for **every** test, so no test can reach a
  real library, and a test pins that.
- **Not installed** (no `master.db`): state `none`. Same track for files that aren't AIFF is not offered (§7.2). New
  track and the AIFF swap work as today.
- **rekordbox 5** (`datafile.edb`): treated as `none`. Discjockey supports rekordbox 6 and 7. Both use `master.db`
  with `DBVersion` 6000.

### 5.2 The key: our own code, not pyrekordbox

**Decision: Discjockey's own small package `discjockey/rekordbox/`, with the key as a constant. The only new
dependency is `sqlcipher3-wheels` (pinned).** The reasons:

- **What we need is small.** We open one encrypted SQLite file, read a few columns of 5 tables, update about 12
  columns of 1–2 rows plus a counter, read one ANLZ tag (`PWV3`), and change one (`PPTH`) byte for byte. That is
  roughly 400 lines with tests.
- **pyrekordbox's ANLZ save is the wrong tool.** `AnlzFile.save()` rebuilds the file and drops tags it doesn't know
  (rekordbox-edit documents the loss of `PVB2`, FLAC's seek index). We need a byte splice anyway, and we must update
  `contentFile`'s hash, which pyrekordbox's `update_content_path` doesn't do.
- **Its weight in the app.** pyrekordbox pulls in SQLAlchemy, psutil, construct, bidict and python-dateutil: four
  more distributions to sign, collect licences for and keep current in the PyInstaller app. Its `commit()` also
  rewrites `masterPlaylists6.xml`, which we never want touched.
- **A key change reaches users the same way either way:** a Discjockey release. With pyrekordbox it would take two
  releases (theirs, then ours). Own code takes one. `KEYS` is a tuple tried in order, so a new key can be added
  without dropping the old one.
- **Licence.** pyrekordbox is MIT, so it was never a blocker. The user decided the EULA question ("we don't tiptoe
  around"). Credit pyrekordbox and rekordbox-edit in the package docstring for the published format knowledge. No
  code is copied.
- **The open itself.** `PRAGMA key='<64 hex chars>'` as a passphrase, with SQLCipher 4 defaults, exactly as
  pyrekordbox opens it. Check first: confirm on a copy that the passphrase form, not the raw `x'…'` form, is the one
  that opens it.
- **The dependency.** `sqlcipher3-wheels` 0.5.7 has a cp312 macOS 11 arm64 wheel, with SQLCipher 4.12 and OpenSSL
  linked in statically. Its licences are zlib (the binding), BSD-style (SQLCipher) and Apache-2.0 (OpenSSL), all
  GPL-3.0 compatible, and its `dist-info/licenses/` carries them. The commit names this reason. Check first:
  - `collect_licenses.py` picks up both licence files.
  - PyInstaller collects `sqlcipher3._sqlite3`; a hidden import may be needed.
  - The app's signing covers the `.so`.
  - `selftest.py` gets a step that opens an in-memory SQLCipher database with a key.

### 5.3 Guards (all before any write; each one refuses with nothing changed)

1. **The key opens it.** If it doesn't, state `unreadable`: "Discjockey can't open this rekordbox version's library
   yet."
2. **`DBVersion` is in the allow-list `{"6000"}`, and every column we read or write exists** (`PRAGMA table_info`).
   If not, the state is also `unreadable`.
3. **rekordbox is not running.** One call to `/bin/ps -Axco comm=` and an exact match on `rekordbox`.
   `rekordboxAgent` doesn't count; check first, in the live test, that the agent never writes `master.db` while
   rekordbox is closed (compare the file's mtime). The check runs at the start of the job **and again inside the write
   transaction, just before the commit**.
4. **rekordbox closed cleanly.** There are no `master.db-wal` / `-shm` files while rekordbox is closed. If there are,
   refuse ("unclean"): "Open rekordbox and quit it once." That also makes a file copy a consistent backup.
5. **No cloud sync on the track.** If `usn IS NOT NULL` or `rb_local_synced <> 0` on any row we would write, refuse
   ("cloud"). This is per track, so a library that was synced once doesn't block every track.
6. **One Discjockey writer per Mac.** A file lock, `<support>/rekordbox.lock`, is held for the whole write and undo,
   so two music folders can't write the same `master.db`. The library lock covers only one library.
7. **The same rekordbox library.** The journal records `DBID`. Recovery or undo on a Mac whose `master.db` has
   another `DBID` (the music folder on an external drive, opened on another Mac) touches nothing in rekordbox and
   says so.

### 5.4 Finding the track

- **The rows.** `entries_for(place, path)` returns the `djmdContent` rows with `rb_local_deleted = 0` whose
  `FolderPath`, NFC-normalized and case-folded, equals the old file's absolute path. For APFS, a candidate also counts
  when `os.path.samefile` holds. Streaming rows (`FileType` 25) never match.
- **None:** the file isn't in rekordbox. The step converts and skips the database (§3.4). The result says "This file
  isn't in your rekordbox collection, so there was nothing to keep there."
- **One:** the normal case.
- **Several** (case or normalization variants): all are repointed in one transaction, each with its own undo record,
  if their measurements agree (§3.4).

### 5.5 What changes, and what doesn't

| Where | Column / data | New value |
|---|---|---|
| `djmdContent` | `FolderPath` | the new file's absolute path, as rekordbox writes it (NFC) |
| | `FileNameL` | the new file name |
| | `OrgFolderPath` | the new path **only if** it equalled the old `FolderPath`, else unchanged (it is `''` in practice) |
| | `rb_LocalFolderPath` | unchanged (NULL in practice). Check first: if a row has it equal to the old path, treat it like `OrgFolderPath` |
| | `FileType` | 12 (AIFF) |
| | `FileSize` | the new file's size |
| | `BitDepth`, `SampleRate`, `BitRate` | 16, 44100, 1411 |
| | `Length` | the new file's whole seconds (as rekordbox stores it) |
| | `rb_local_usn` | `localUpdateCount + 1` |
| | `updated_at` | now, formatted as `YYYY-MM-DD HH:MM:SS.fff +00:00` |
| `agentRegistry` | `localUpdateCount.int_1` | +1, once per transaction; `updated_at` the same now |
| ANLZ `.DAT` `.EXT` `.2EX` `.3EX` | `PPTH` | `?/<new name>` when it held `?/<old name>`. A byte splice: the tag's and the file header's lengths are updated, every other byte is kept |
| `contentFile` | `Hash`, `Size` of each changed ANLZ file | the new MD5 and size. This mirrors rekordbox's own invariant (`Hash` = MD5 of the file); `rb_*` flags unchanged |

**Unchanged:** `ID`, `UUID`, `AnalysisDataPath`, `BPM`, `KeyID`, ratings, colour, comment, artwork, and every table
keyed by `ContentID`. That includes `djmdCue`, `contentCue`, `djmdSongPlaylist`, `djmdSongHistory`, `djmdSongMyTag`,
`djmdSongHotCueBanklist`, `djmdSongRelatedTracks` and `djmdSongSampler`. The waveform, grid, `PVBR` and phrase tags
in the ANLZ files are kept as they are. A test compares every other column and table before and after, byte for byte.

The live run wrote the type columns and `PPTH` but left `contentFile` stale, and rekordbox worked. Updating
`contentFile` is the more consistent choice but is not proven yet. It is on the live-test list. If it causes trouble,
the fallback is to leave `PPTH` and `contentFile` alone. That fallback is not proven either, so the test decides.

### 5.6 rekordbox open: what the user sees

The step checks at the start (guard 3). If rekordbox is open, the job ends with kind **`rekordbox_open`** and nothing
changed: "rekordbox is open. Quit rekordbox, then press Replace again. Discjockey changes your rekordbox track only
while rekordbox is closed." The console exits with code 4.

The design round (§9) decides whether the panel also shows rekordbox's state live, for example by asking
`rekordbox_status` when the panel opens, or offers "Replace when rekordbox is closed". The engine never waits by
itself.

### 5.7 Backup

- **When.** Before the first write of a job, if no backup newer than `master.db`'s current content exists, Discjockey
  copies the following into `<music folder>/.discjockey/rekordbox/backups/<UTC time>/`:
  - `master.db` (a file copy, which is consistent because rekordbox is closed with no `-wal`, per guard 4)
  - the ANLZ folders of the tracks to change
  - `manifest.json`: the app version, `DBID`, `DBVersion`, the master.db SHA-256 before and after, and the track ids
- **Dedup.** After the commit, the manifest records master.db's SHA-256. The next job reuses that backup when the
  file still has that hash, and adds only the new tracks' ANLZ folders. So 30 Same-tracks in a row make one copy of
  `master.db` (about 8 MB for a collection of about 800 tracks).
- **Kept** while an undo refers to it, plus the newest 3. Pruned at the same clean-up as `.discjockey/undo/`
  (`library._prune_undo`'s caller).
- **Restoring the whole database** is the last resort, because it throws away every rekordbox change since. It is a
  console command with `--yes` (§10), not a hub button. It backs up the current `master.db` first and refuses while
  rekordbox runs.

### 5.8 Order of the step, and crash recovery

**Invariant:** at every point, each rekordbox track points at a file that exists. **The commit point is the
`master.db` transaction.** The row's `FolderPath` is the marker that tells recovery which side of it a crash
happened on.

1. **Render** the AIFF into `.discjockey/.tmp/<track>/convert.aiff`, then hash it. A failure here leaves nothing.
2. **Journal** the `convert` op (`pending`). It records: the track, the old and new paths, the `Superseded/` path,
   the staged path, the SHA-256 of the staged and old files, the parked upgrade (if any) and its held place, `DBID`,
   and per rekordbox row the before and after values of §5.5's columns. Per ANLZ file it records the path, the old
   and new SHA-256 and the backup id.
3. **Back up** (§5.7), then mark `backed_up`.
4. **Place the new file:** `move_path(staged → new)`, then mark `placed`.
5. **Write rekordbox:**
   1. `BEGIN IMMEDIATE`. Check that each row still has its before values in `FolderPath` and `FileNameL`. If not,
      roll back and refuse with "changed".
   2. Run the `UPDATE`s, including `contentFile`.
   3. Write the spliced ANLZ files next to the originals (`.dj-new`) and rename them over the originals.
   4. Check guard 3 again, then **COMMIT**, then mark `committed`.
   If rekordbox appeared in the meantime, roll back, restore the ANLZ files from the backup, and refuse with
   `rekordbox_open`.
6. **Move the old file** to `Superseded/` (`move_path`).
7. **End the op.** This writes the song entry (path, the upgrade's status/source, or the kept status for stage C),
   the file rows, and the rekordbox check with its undo record. For an upgrade, the parked download goes to
   `.discjockey/undo/<track>/`, as `swap` does with `_hold`.

**Recovery (`convert.recover`, called from `recover_pending`):**
- **Not committed** (each row's `FolderPath` is still the old one): roll back.
  - ANLZ files whose SHA-256 is the "new" one are restored from the backup copy.
  - The placed new file, if its SHA-256 is the staged one, goes back to `.tmp/` and is dropped. It is Discjockey's own
    render, and its source (the parked file or the old file) is untouched.
  - The op is dropped. Message: "The replace for {name} was not finished; your file and your rekordbox track are as
    they were."
- **Committed** (`FolderPath` is the new path): finish steps 6–7. Message: "Finished an interrupted replace for
  {name}."
- **Neither** (rekordbox changed the row since): do nothing in rekordbox. Finish or roll back only the files, by
  which file the row names, and say "needs your help" with both paths.
- **Rolling back the ANLZ files needs rekordbox closed.** If rekordbox is open, the op **waits**, as an offline drive
  does (`_Waits`), with "Quit rekordbox so Discjockey can finish an interrupted replace for {name}." Check first:
  that `recover_pending`'s waits let other work continue, as for offline drives.
- **`DBID` differs** (another Mac): only the file side is resolved. The message names the rekordbox step that is left
  for the other Mac.

### 5.9 Undo, per field

The undo is offered while the rekordbox check stands, as today ("Undo the replace"). It needs rekordbox closed (same
guard and words, "Quit rekordbox to undo"). It is journaled as op `convert_undo`, with the same invariant in reverse:

1. Read and decide first.
   - **Identity columns** (`FolderPath`, `FileNameL`, and `OrgFolderPath` if we changed it) must hold exactly what we
     wrote. If they don't, the user relocated or changed the track in rekordbox, so **refuse with nothing changed**.
   - The new file's SHA-256 must be what Discjockey wrote, and the old file in `Superseded/` must have its recorded
     key (as `upgrades._unchanged`).
2. Move the old file back from `Superseded/` to its place.
3. In one transaction, set the identity columns back, and set the **file-fact columns** (`FileType`, `FileSize`,
   `BitDepth`, `SampleRate`, `BitRate`, `Length`) back **whatever they hold now**. They describe the file the row
   points at, and rekordbox may have re-read them. Stamp a fresh `rb_local_usn` and `updated_at`.
   Splice `PPTH` back to the old name only where it still holds our new name; where rekordbox rewrote the ANLZ file (a
   new analysis), leave it. Update `contentFile` for the files that were spliced.
4. Move the new AIFF into `.discjockey/undo/<track>/`. The next clean-up deletes it. It is Discjockey's own render,
   its SHA-256 is checked, and its audio still exists as the parked download, which goes back to `Upgrades ready/`, or
   as the old file. This is consistent with "never delete a music file" in the way `delete_parked` and `forget_undo`
   are.

**Everything else the user did in rekordbox since is kept:** new cues, a re-analysis, ratings, playlists. Cues set
on the AIFF also fit the old file, because both sit on the same timeline. That is why the undo goes field by field
rather than restoring the whole database. "Done, checked in rekordbox" ends the undo (`forget_undo`) and releases the
backup.

### 5.10 Cloud Library Sync

Cloud-synced tracks are refused (guard 5) until someone tests how an outside write spreads to other devices. The words
are under "cloud" in §8. A track that was never synced can be changed even when the account is logged in.

### 5.11 rekordbox's own text columns (title, artist, album, label, year, genre, comment)

rekordbox reads a file's tags only at import and on **Reload Tag**. After the repoint, its track still shows the
names it read from the old file, or the ones the user typed into rekordbox. Discjockey **leaves these columns alone**,
and the check card offers rekordbox's own Reload Tag as a step.

**Why not write the clean values into the database:**
- **The columns aren't plain text.** Artist, album, label, genre, composer and remixer are ids into lookup tables
  (`djmdArtist`, `djmdAlbum`, `djmdLabel`, `djmdGenre` …). Writing a clean artist means finding or creating rows there,
  with rekordbox's id scheme, `UUID`, `SearchStr` and `rb_local_usn`. That is a much bigger write surface than §5.5,
  and offline tests can't show that rekordbox accepts it.
- **Discjockey can't tell a user's edit from an imported tag for sure.** A rule like "update only where the database
  still equals the old file's tag" fails on tags rekordbox normalised at import. A wrong guess overwrites something
  the user typed, and that is the one thing they asked never to lose.
- **Reload Tag is rekordbox's own operation.** It is per track and under the user's control. It is already the step
  after today's swap ("Reload Tag so the comment shows the new source"). Its cost is that it replaces the text fields
  the user edited in rekordbox with the file's values. The step's words say so, and the user decides per track.

**Never touched, by Discjockey or by these steps:** rating, colour, My Tags, play count, cues, grid, key and BPM.
rekordbox's Reload Tag doesn't read those from the file either. Check first, in the live test: which fields Reload
Tag replaces on an AIFF (title, artist, album, genre, comment, year, label, artwork are expected).

Writing the clean values for fields the user never edited is a product choice (question 4).

## 6. USB sticks exported before the repoint

What we know: rekordbox's device sync didn't notice the change, and the stick kept the old file. Discjockey doesn't
write to the stick: `export.pdb` and `exportLibrary.db` are rekordbox's device formats, and a wrong write could
break a stick before a gig.

- **What Discjockey says.** The rekordbox check after every repoint has the step "On a USB stick? In rekordbox, remove
  the track from the stick, then export it again (a sync alone keeps the old file there)." The README's rekordbox
  section explains it once.
- **Live test.** It finds the smallest fix that works:
  1. Remove the track from the device, then sync.
  2. Or do the bumped `rb_local_usn`/`updated_at` plus a consistent `contentFile` already make a plain sync pick it
     up? The live run's stale `contentFile` may have been why the sync skipped it.
  3. Rebuild only if neither works.
  The step's words follow the result.
- **Later, only if the steps prove tedious.** Discjockey could look at a plugged-in rekordbox stick
  (`/Volumes/*/PIONEER/rekordbox/`) and list which repointed tracks still have their old file there. This is not
  designed here.

## 7. The stale waveform and analysis; what changes in the words

**After a repoint, the ANLZ files still describe the old file.** That covers the waveform, the grid, the key and
phrase analysis, and `PVBR` (an MP3 seek index).
- **The grid and cues are right**, because the new audio sits on the same timeline.
- **After a pure conversion (stage C)** the audio is the same, so nothing needs redoing.
- **After an upgrade**, the waveform shows the lossy sound until the track is analysed again. This is the same step as
  after today's swap: "analyse it again (lock the beatgrid first if you set it by hand)".
- **The live test checks** that a leftover `PVBR` doesn't disturb seeking in an AIFF.

### 7.1 Rename without converting (an own AIFF with a messy name)

**What it does.** The same repoint can give an own file that **is already AIFF** (or WAV) its clean name: the
download's name (§4), in the same folder, through `move_path`, with every rekordbox track repointed. Only the path
columns, `PPTH` and `contentFile` change; the file facts are the same file. The audio and the tags are untouched.
Setting the download's tags is part of Convert, not of Rename. Rename needs rekordbox closed when the file has a
rekordbox track, and is refused otherwise. It is undoable per field, as in §5.9. It is a product choice whether to
offer it (question 5). If yes, it goes with stage C: the same design round, one more action in the Library details,
and `discjockey rename <track>… [--dry-run] [--json]`.

**The invariant changes.** CLAUDE.md today says: "**Moving never renames:** a tidy-up and its undo keep each file's
name as it is, because rekordbox's Relocate finds files by name." That reason was true only because Discjockey
couldn't repoint rekordbox. The new text:

> **A file keeps its name unless rekordbox follows it.** A move (a tidy-up, its undo, a folder rename) keeps each
> file's name, because rekordbox may be open or on another Mac, and then Relocate has only the name to find the file
> by. A file gets a new name only in a step the user chose that also repoints every rekordbox track of that file while
> rekordbox is closed (Convert, Same track for a file that isn't AIFF, Rename). It is refused when it can't.

**Tidy-up keeps its current behaviour, with no renames.**
- A tidy-up moves hundreds of files in one batch and is often run with rekordbox open.
- Coupling it to a database write would make the most common batch depend on rekordbox being closed.
- Its undo would have to unwind the database for every file.
- Repointing after moves, without renaming, is stage D (question 2).
- A tidy-up that also cleans names would be a later, separate choice.

### 7.2 What changes on the screens

**Same track** (To-do upgrade panel, Library details; `upgrade_status`, `cue_text`, `swap_possible`):
- **Offered** for the same edit (`exact`/`shifted`) when the file is AIFF (the in-place swap, unchanged), or when the
  file isn't AIFF and rekordbox's state is `ready`, or `none`/no track for that file (convert only, no database part).
- **Not offered** for a file that isn't AIFF when rekordbox is `unreadable`. The reason line says why (§8).
- **Problems known only when Replace is pressed** come back as the job's problem, and the user can then pick New
  track: rekordbox open, not analysed, timing, cloud, unclean close. The panel can show them earlier through the
  read-only `rekordbox_preview`; whether it does is up to the design round.

**New track (the bundle).**
- When the versions are the same edit, `add_new` now **renders** the new file shifted by `k = L − round(d · 44100)`,
  instead of renaming the parked file as it is.
  - `d` is measured when rekordbox has an analysed track for the old file. It is 0 for an AIFF or WAV file, or when
    there is no rekordbox track.
  - The parked file is held for the undo, as `swap` does.
- A different or unknown edit is renamed as today; shifting it would mean nothing.
- `report.SHIFTED_EDIT_CHECK` ("fit to within N ms") is no longer used for new checks; they say the cues fit. Records
  from before keep their words (the check gets `aligned: true`).
- For an old file that isn't AIFF, the check stops advising Relocate if the live test confirms that Relocate can't
  change a file's type.

**The rekordbox check To-do item.**
- **New reason `repointed`:** the summary is "same track, now AIFF". The steps are Reload Tag (the clean names, §5.11),
  "analyse it again" (with the beatgrid note), and the USB step.
- **New reason `converted` (stage C):** Reload Tag and the USB step, with the hint "The sound and your cues are as
  before."
- **New reason `renamed` (§7.1):** Reload Tag is optional. If the file is on a USB stick, the USB step.
- **Swap and `added_as_new`** keep their steps, with the New track words above.
- **"Undo the replace"** needs rekordbox closed only when the step wrote to rekordbox.

**README.**
- **Upgrades.** Same track is no longer "only offered for an AIFF file": for MP3, M4A, WAV or FLAC it becomes an AIFF
  and the rekordbox track follows, which needs rekordbox closed. Remove the New track claim "Auto Relocate … finds the
  new file by its name and links your old track to it". It is probably wrong across file types; the live test
  settles the replacement words.
- **rekordbox.** Add when Discjockey changes rekordbox's library, what it changes, the backup folder, the undo, and
  USB sticks.
- **When something breaks.** Add `rekordbox restore`.
- **Console.** Add the new commands (until issue 39's agent docs exist, then there as well).

## 8. Words the user sees (binding)

| Where | Text |
|---|---|
| Same track outcome rows (file isn't AIFF) | "Your track keeps its cues, playlists and history" · "Becomes an AIFF file" · "Quit rekordbox before you replace" |
| Reason, no rekordbox library readable | "Same track needs a rekordbox library Discjockey can open" |
| Reason, no rekordbox on this Mac | "No rekordbox on this Mac: the new file is a new track" |
| Problem `rekordbox_open` | "rekordbox is open. Quit rekordbox, then press Replace again. Discjockey changes your rekordbox track only while rekordbox is closed." |
| Refused, unreadable | "Discjockey can't open this rekordbox version's library yet, so nothing was changed. Choose New track, or update Discjockey." |
| Refused, not analysed | "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues sit. Nothing was changed. Analyse it in rekordbox, quit rekordbox, and try again, or choose New track." |
| Refused, timing | "Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. Choose New track, or analyse the track again in rekordbox and try again." |
| Refused, cloud | "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet. Nothing was changed. Choose New track instead." |
| Refused, unclean | "rekordbox didn't close normally last time. Open rekordbox, quit it, and try again. Nothing was changed." |
| Refused, changed | "Your rekordbox track changed while Discjockey was working on it, so nothing was changed. Try again." |
| Refused, space | "There isn't enough free space for the new AIFF file ({size} needed). Nothing was changed." |
| Undo, rekordbox open | "Quit rekordbox to undo: Discjockey points your rekordbox track back at your old file only while rekordbox is closed." |
| Undo refused | "This track was changed in rekordbox since (relocated?), so Discjockey can't undo the replace safely. Nothing was changed." |
| Check text `repointed` | "The lossless audio is in a new AIFF file with a clean name, and your rekordbox track now plays it with its cues, playlists and history. In rekordbox: Reload Tag to show the new names (it replaces names you changed in rekordbox), and analyse it again so the waveform shows the full sound. If the track is on a USB stick, remove it from the stick and export it again." |
| Check text `converted` | "Your file is now an AIFF with a clean name, and your rekordbox track plays it with its cues, playlists and history. The sound is the same. In rekordbox: Reload Tag to show the new names (it replaces names you changed in rekordbox). If the track is on a USB stick, remove it from the stick and export it again." |
| Check text `renamed` | "Your file has its clean name now, and your rekordbox track follows it with its cues, playlists and history. If the track is on a USB stick, remove it from the stick and export it again." |
| Reload Tag step (check card) | "Right-click the track › **Reload Tag** to show the new names" · note "(replaces names you changed in rekordbox)" |
| Refused, rename blocked | "Discjockey can only give this file its new name while it can point your rekordbox track at it, and it can't right now ({reason}). Nothing was changed." |
| Result note, no rekordbox track | "This file isn't in your rekordbox collection, so there was nothing to keep there." |
| Console tip (`discjockey upgrades`) | "Quit rekordbox first: for a file that isn't AIFF, Discjockey points your rekordbox track at the new file." |

The UI agent may shorten the panel rows to fit the blocks. Each meaning stays, and a reason is given for every
change.

## 9. Screens, and which need a design round

### 9.1 Stage B: the upgrade panel and the check card

The upgrade panel ("In rekordbox" card, To-do and Library details) and the check card change only inside existing
blocks: options, outcome rows, reason, steps. This is a **short Opus design round with a mockup** of these states,
compared with main:
1. **MP3 own file, same edit, rekordbox found:** the Same track choice, recommended, with its outcome rows.
2. **The same, rekordbox unreadable:** no choice, with the reason.
3. **The same, no rekordbox on this Mac:** what replacing means.
4. **Replace pressed while rekordbox is open:** the problem state, and how "try again" works.
5. **The rekordbox check after a repointed Same track:** steps, Undo, Done.
6. **Undo pressed while rekordbox is open.**
7. **New track, same edit, MP3 old file:** the changed check card.

The designer also decides whether the panel shows rekordbox's live state or the preview's findings (§5.6, §7.2).

### 9.2 Stage C: Convert to AIFF

This needs a **full design round with a mockup**. The states:
1. **The To-do group** (working name "Won't play well on CDJs"): the list, the panel for one file (why, what converting
   does, the disk space), and convert-all with one quit of rekordbox.
2. **The Library details action** "Convert to AIFF" for an own file that isn't AIFF.
3. **A conversion of several files running:** progress and Stop.
4. **The `converted` check card.**
5. **The empty state, and the state with no rekordbox.**
6. **If question 5 is a yes, Rename:** the Library details action for an own AIFF whose name isn't the clean one (old
   name → new name), the refusal when rekordbox can't follow, and the `renamed` check card.

The CDJ rule is a pure function in one place, `cdj_problem(facts) -> str | None`, for example "AAC at 420 kbps:
CDJs play AAC only up to 320 kbps". It flags AAC or MP3 above 320 kbps, codecs CDJs don't play (Opus, Vorbis, WMA),
and 32-bit float WAV. Check first: Pioneer's format tables for CDJ-3000, CDJ-2000NXS2 and XDJ players, and which of
FLAC, ALAC and high sample rates to flag.

## 10. Commands (agent-ready)

The commands follow the CLAUDE.md rule. They run without prompts; confirmations are flags. `--json` prints one
object at the end. A command that changes things takes the library lock, as the hub does.

**Exit codes** (the existing `cli.main` codes plus one; issue 39 may renumber them globally):

| Code | Meaning |
|---|---|
| 0 | done (or a dry run that would work) |
| 1 | refused or failed (the message says why; `kind` in JSON) |
| 2 | no music folder or no setup |
| 3 | Discjockey is busy (lock held) |
| 4 | rekordbox is open: quit it and run again |

**JSON shapes.** Success is `{"ok": true, …}`. Failure is `{"ok": false, "kind": "rekordbox_open" | "refused" |
"changed" | "failed", "reason": "<refusal key from §8>", "message": "…", "details": {…}}`. This is the bridge's
shape plus `reason`.

**Commands:**

| Command | Does | Stage |
|---|---|---|
| `discjockey rekordbox status [--json]` | `{"state": "ready"\|"none"\|"unreadable", "running": bool, "version": "7.2.18"\|null, "library": "<path>", "problem": str\|null}`. Read-only, no lock | A |
| `discjockey rekordbox preview <track> [--json]` | Read-only. What Same track or Convert would do: `{"file", "new_file", "superseded", "entries": [{"id", "cues", "grid", "offset_ms", "expected_ms", "score", "cloud"}], "same_track": {"possible": bool, "reason": str\|null}}` | A |
| `discjockey upgrade list [--json]` | The parked upgrades as on the To-do page: id, artist, title, now/new quality, alignment, `same_track` possible and why not | B |
| `discjockey upgrade apply <track> --way same-track\|new-track [--dry-run] [--json]` | The hub's Replace. `--dry-run` prints what the preview says and changes nothing. Result: `{"section", "path", "note", "rekordbox": {"entries": [ids], "backup": "<id>"}\|null}` | B (New track lined up in A) |
| `discjockey upgrade discard <track> [--json]` | The hub's Discard | B |
| `discjockey upgrade undo <track> [--json]` | "Undo the replace" | B |
| `discjockey rekordbox checked <track> [--json]` | "Done, checked in rekordbox" | B |
| `discjockey rekordbox backups [--json]` | Lists the backups: id, time, tracks, kept because of an undo or not | B |
| `discjockey rekordbox restore <backup> --yes [--json]` | The whole database back (§5.7). Without `--yes` it refuses (code 1) | B |
| `discjockey convert <track>… [--dry-run] [--json]` | Stage C's Convert to AIFF. One result per track in `results: […]`; exit 0 only if all were done | C |
| `discjockey rename <track>… [--dry-run] [--json]` | §7.1's Rename (if question 5 is a yes). `--dry-run` prints the old and new name per track. Same result shape as `convert` | C |

`<track>` is the song's key as `upgrade list --json` and the Library's JSON print it. The interactive
`discjockey upgrades` stays; its "s" (swap) becomes Same track for any format. Issue 39 lists these commands in the
agent docs. Until those docs exist, the README's console section lists them.

## 11. Bridge and contract

These changes go into `docs/hub-bridge-contract.md`, `types.ts`/`contract.ts` and the fake backend, in the same
commit:
- **`upgrade(track_id, mode)`:** the modes are unchanged. `swap` on a file that isn't AIFF runs `convert` with the
  upgrade as the source. The new problem kind is `rekordbox_open`, and refusals carry `reason`.
- **`upgrade_block`:**
  - `swap_possible` now means "Same track is possible".
  - New `swap_how`: `"in_place" | "new_aiff"`.
  - New `rekordbox`: `{"state": "ready"|"none"|"unreadable"}`, the cached status (below).
- **`check_view`:** the new reasons `repointed` and `converted`, plus `aligned`.
- **New read `rekordbox_status()`:** it answers at once and is cached by master.db's mtime and size. It opens the
  library read-only (`mode=ro`), never during a write. Check first: a read-only open while rekordbox holds the `-wal`
  file; if it fails, the state is `ready` with "running".
- **New read `rekordbox_preview(track_id)`:** it decodes the old file (1–3 s). Check first: whether reads that decode,
  like the spectrum, run inline or as a job; do the same.
- **Stage C:** a new write, `convert(track_ids)`, which is a job with progress events.
- **Views stay pure.** `api.py` reads the rekordbox status and passes it into `views.py`.
- **Services.** `svc.rekordbox` (place, `running()`, `open()`) is injected, so tests and the fake never touch a real
  library.

## 12. Testing, offline

**Helpers.** `tests/rekordbox_helpers.py`:
- `make_master(tmp, rows, key=KEY, version="6000")` builds a SQLCipher database with the same `PRAGMA key` and WAL
  mode. It has the tables and columns we touch (`djmdContent` with its real 78 column names, `djmdCue`, `contentCue`,
  `contentFile`, `djmdProperty`, `agentRegistry`, `djmdSongPlaylist`, `djmdSongHistory`, `djmdSongMyTag`) and a few
  rows with cues, playlists and history.
- `make_anlz(path, tags)` writes PMAI files with `PPTH`, `PQTZ`, `PWV3` and an unknown tag (random bytes).
- `pwv3_from(audio, sr, extra_s)` makes heights the way rekordbox's timeline would show them.

**Audio fixtures.**
- M4A is made in the test with the bundled ffmpeg's native `aac` encoder.
- MP3 can't be made in the test, because the bundled ffmpeg has no MP3 encoder (issue 19). So two small synthetic
  click-track MP3s, one LAME-tagged and one without a tag, are committed under `tests/fixtures/`, made once by a
  documented script.
- No real music and no real library. `DISCJOCKEY_REKORDBOX` points at a temp folder in every test (§5.1).

**Behaviours to pin:**
- **Guards:**
  - a wrong key or `DBVersion` → `unreadable`; a missing column → `unreadable`
  - a `-wal` file left over → "unclean"
  - rekordbox running at the start → `rekordbox_open` with nothing changed; running at the commit → rolled back
    with nothing changed (an injected `running`)
  - a cloud row → refused
  - another `DBID` in recovery → rekordbox untouched
- **Lookup:** exact, NFC/NFD and case variants; deleted rows ignored; several rows all repointed; none → converted
  without a database write.
- **The write:**
  - exactly §5.5's columns change, and every other column and table is byte-equal (whole-row compare)
  - `OrgFolderPath` follows only when it was equal
  - `localUpdateCount` goes up once and `rb_local_usn` takes its value
  - `updated_at` has the right format
- **The ANLZ splice:** `PPTH` changed; every other tag, including the unknown one, byte-identical; the lengths
  right; `contentFile` gets the MD5 and size.
- **Timing:**
  - a synthetic shift is recovered within ±5 samples and snapped to the expected value
  - a score below 0.90, or a value outside the set → "timing"
  - no `PWV3` with cues on an MP3 → "not analysed"; no `PWV3` with no cues and no grid → plain conversion
  - the output AIFF has its clicks at the rekordbox-timeline positions to ±1 sample at 44.1 kHz (M4A made in the
    test; MP3 from the fixtures)
- **The step:**
  - the name `Artist - Title.aiff`: the same `expected_stem` result a download of that song gets, with an ID only
    when taken; the old file mirrored into `Superseded/` under its own name
  - the tags are exactly `write_tags`' frames plus TCON/TYER from the old file
  - `cdj_cover` makes a 3000 px PNG a JPEG of at most 600 px and 500 KB, and leaves a 600 px JPEG byte-identical
  - a new name with a rekordbox track it can't repoint is refused with nothing changed
  - Rename (§7.1) changes only the path columns, `PPTH` and `contentFile`
  - no rekordbox text column (`Title`, `ArtistID`, `AlbumID`, `Commnt`, `GenreID`, `Rating`, `ColorID` …) changes
  - the file row keeps the old quality and `placed_by='app'`
  - nothing written outside `move_path`
  - free space checked
- **Crash at every step (1–7):** before the commit, recovery restores exactly the old state (files, ANLZ, database);
  after it, recovery finishes; rekordbox open during an ANLZ rollback → waits.
- **Undo:**
  - identity and file facts restored
  - later cue, rating and title edits kept
  - `FolderPath` changed by the user → refused with nothing changed
  - rekordbox open → `rekordbox_open`
  - `PPTH` left alone when re-analysed
- **New track:** a same-edit add renders a shifted file (AIFF old file: exact with `L`; MP3 old file with a track:
  `L − d`); a different edit is renamed as today; old checks keep their words.
- **Commands:** exit codes 0, 1, 3 and 4, the JSON shapes, `--dry-run` changes nothing, `restore` without `--yes`
  refuses.
- **App:** the self-test opens a keyed in-memory database.

## 13. Staging

**Stage A: read side, plus New track lined up.** Ships safely with no rekordbox write.
- `discjockey/rekordbox/` read side: locate, key, guards, `entries_for`, ANLZ reading, timing.
- The `sqlcipher3-wheels` dependency and its self-test step.
- `audio.render_aiff`.
- `add_new` shifted, with its words and the README's corrected New track text.
- The `rekordbox status` and `rekordbox preview` commands.
- Acceptance on the maintainer's Mac: `rekordbox status` and `preview` on a few real tracks agree with the research
  numbers. This is read-only and run by the maintainer.

**Stage B: write side, plus Same track for any format.**
- The `convert` op with its backup, recovery and undo.
- The upgrade's Same track for files that aren't AIFF.
- The commands `upgrade …` and `rekordbox checked/backups/restore`.
- The UI after §9.1's design round.
- Merge into main once CI and verify are green, then **the live test before any release**.

**The live test** (the user, about 20 minutes, on throwaway tracks only). A rekordbox backup comes first
(File › Library › Backup), and the agent copies `~/Library/Pioneer/rekordbox/`. The tracks are synthetic 120 BPM click
tracks: one LAME MP3, one 48 kHz M4A and one FLAC. Each gets hot cues on clicks, a playlist, a play, and an export to
a spare stick. Then, through `discjockey convert` or `upgrade apply`, with rekordbox closed, the test checks:
1. rekordbox shows AIFF/44.1/16, plays it, and the cues and grid sit on the clicks, including on the 48 kHz one
   (the rate change) and the FLAC.
2. Reopening rekordbox keeps all of it.
3. `PVBR` does no harm to seeking.
4. Re-analysis with the grid locked refreshes the waveform.
5. Undo brings back the old file with its cues.
6. The USB question (§6): which smallest action updates the stick.
7. Manual Relocate `.mp3` → `.aiff` works or not, which sets the README words. Reload Tag on the repointed AIFF:
   which fields it replaces, and that it keeps rating, colour and My Tags.
8. Whether rekordbox follows a file moved into `Superseded/` by itself (the README's bought-copy claim).
9. rekordboxAgent leaves `master.db` alone while rekordbox is closed.
10. The `contentFile` update is accepted.

If 1 fails for 48 kHz, render own 48 kHz files at their own rate and resample the upgrade to it. If 10 fails, use the
fallback in §5.5. After the test passes: release on the user's go.

**Stage C: Convert to AIFF without an upgrade** (CDJ). The design round (§9.2), then the `convert` bridge method,
the command and the To-do group, after the user answers question 1.

**Stage D (its own issue): repoint after Discjockey's own moves.** Today these need Relocate: a swap that moves out of
`not_lossless/`, a tidy-up, and a duplicate moved to `Superseded/`. The same engine can repoint them. This depends on
question 2.

## 14. Check first (collected)

- ffmpeg's untrimmed decode flags for MP3 and MP4 with the bundled build (§3.2).
- The tag readers for own files to reuse (§3.5); a rescan not re-checking a row the step wrote (§2).
- The passphrase form of the key (§5.2); PyInstaller, licences and signing for `sqlcipher3` (§5.2).
- `rb_LocalFolderPath` on rows where it isn't NULL (§5.5).
- `recover_pending`'s waits for a `rekordbox is open` wait (§5.8).
- A read-only open while rekordbox runs in WAL mode (§11); inline vs job for `rekordbox_preview` (§11).
- Pioneer's CDJ format tables for `cdj_problem` (§9.2); Pioneer's limit for embedded artwork (§3.5).
- Whether the import cleans own songs' names like `titles.split_title` (§4).
- Which fields rekordbox's Reload Tag replaces on an AIFF (§5.11, live test).

## 15. Questions for the user

1. **Convert without an upgrade (stage C):** should the To-do page get a group of files that likely won't play well on
   CDJs (for example AAC above 320 kbps), with "Convert to AIFF" and the same action in a track's details?
   *Recommendation: yes.* Many YouTube rips will never get a lossless upgrade, converting fixes the stutter, and the
   risk is the same tested step as Same track. Without the group, the user only finds out at the CDJ.
2. **Repoint after Discjockey's own moves (stage D):** should rekordbox follow files that Discjockey moves (a swap out
   of `not_lossless/`, a tidy-up, a duplicate moved to `Superseded/`), so that Relocate is never needed? *Recommendation:
   yes, as its own issue after stage B's live test.* It removes the most common manual rekordbox step. It would also
   mean the database is written on more actions than "Replace".
3. **Lossless own files (FLAC, WAV, 24-bit):** should "Convert to AIFF" also be offered for them, making 16-bit/44.1
   kHz with the original kept in `Superseded/`? *Recommendation: offered when the user picks a track, and suggested
   only when a CDJ problem is likely.* It matches "own files end up as AIFF", while 24-bit files never get converted to
   16-bit without the user asking.
4. **rekordbox's text columns:** after a repoint, should Discjockey also write the clean title, artist, album, label
   and year into rekordbox's database for the fields the user never edited there? The other way is to leave them and
   let the user press Reload Tag per track (§5.11). *Recommendation: leave them, with Reload Tag as a step.* Writing
   artist and album means creating rows in rekordbox's lookup tables, a bigger untested write. Telling a user's edit
   from an imported tag is a guess that could overwrite what the user typed. Reload Tag is rekordbox's own operation,
   and the user controls it per track.
5. **Rename without converting:** should an own file that is already AIFF (or WAV) be offered "Give it its clean name"
   (the download's name), with rekordbox following (§7.1)? Tidy-up stays as it is, without renames.
   *Recommendation: yes, in stage C, as a Library details action for one or more tracks, not as a To-do group.* It
   uses the same tested repoint, it is what the clean-name wish means for files that need no conversion, and a
   suggestion list of "bad names" would be guesswork.
