# Own files become AIFF, and rekordbox's track follows them (issue 33): design

Status: design, 2026-11-07, with the user's answers and wishes of the same day built in. No code yet. Plans built
from it go in `docs/` as `…-plan.md`.

Issue 33 asks that a user's own files (imported from watched folders, or bought; MP3, M4A/AAC, WAV, FLAC, AIFF) end up
in the library format, 16-bit AIFF with a clean name and clean tags. rekordbox's existing track for the file follows
the new file and keeps everything on it: cues, hot cues, beatgrid, history, playlists, My Tags, rating and colour.
The bundle: "New track" lines up sample-exactly, as "Same track" already does. The user's wishes on top: upgrades
can run by themselves on a sync (A), "Upgrade all" in To-do (B), "Make all lossless files AIFF" in one click (C), and
every action works on one file, a selection, or everything eligible.

## 0. What is already known

- **The route is a direct write to rekordbox's `master.db`, made only while rekordbox is closed.** The user decided
  this. A maintainer did it by hand on 2026-10-31 for about 40 M4A tracks, outside Discjockey: each M4A was decoded to
  16-bit AIFF with rekordbox's start delay kept (checked against rekordbox's own waveform: 0.0 ms), then the path
  columns and `PPTH` were rewritten with pyrekordbox and `FileType`, `FileSize`, `BitDepth`, `SampleRate` and
  `BitRate` set by hand. Every cue matched the backup and the tracks played on the beat. The AIFFs kept their 48 or
  44.1 kHz rate, so **a change of sample rate is still untested**.
- **Gotchas from that run.** A USB stick exported before the repoint still pointed at the old `.m4a`, and rekordbox's
  sync skipped those tracks. rekordbox's device view offered only "remove from playlist", the tracks sat in several
  playlists, and the user rebuilt the whole stick. YouTube-rip M4As are AAC at 420–455 kbps; CDJs take AAC only up
  to 320 kbps, the likely reason they stutter or don't load.
- **Research findings (2026-11-07).** rekordbox places cues on its own decode timeline, which keeps the encoder delay
  that ffmpeg drops: 1105 or about 2257 samples on MP3s, about 1600 samples on ffmpeg-made 44.1 kHz M4As, about
  21.5 ms on 48 kHz M4As, 0 for AIFF and WAV. The offset can be measured per track from rekordbox's `PWV3` waveform to
  within about ±3 samples. The key is one fixed value, and it opened a rekordbox 7.2 database.
- **Checked on a copy of a maintainer's `master.db`** (read-only): the database is in **WAL mode** (`-wal`/`-shm`
  exist only while a connection is open); `djmdProperty` has `DBID` and `DBVersion` = `6000`; `OrgFolderPath` is `''`
  and `rb_LocalFolderPath` NULL on every row; `usn` is NULL everywhere (no cloud sync); `updated_at` looks like
  `2026-10-31 22:32:18.093 +00:00`. **`contentFile` keeps an MD5 `Hash` and the `Size` of every ANLZ file**; after
  the live run's `PPTH` rewrite those are stale for the repointed tracks, and rekordbox hasn't flagged or fixed them
  (`rb_file_hash_dirty` = 0). rekordboxAgent's `options.json` names the library (`db-path`) and the analysis folder
  (`analysis-data-root-path`).

## 1. Decisions at a glance

**The batch rule (general, binding).** Every action of this feature (Same track, Convert to AIFF, Give it its clean
name, and their undo and "checked") runs on **one track, the tracks the user selected, or all eligible tracks** of a
scope, through **one engine path: a batch** (a batch of one is just a batch). Per batch: one rekordbox check at the
start (one quit), one backup, one `rekordbox.lock`, one job with progress, Stop between tracks, Resume for what is
left, undo per track and for the whole batch, and one rekordbox check card. Eligibility is one pure function per
action (§2.2); the hub and the commands use the same one.

| Question | Decision | Section |
|---|---|---|
| Actions | Same track (an upgrade), Convert to AIFF (the file itself), Give it its clean name (an AIFF that only has a messy name). One engine step `convert` plus `rename` | §2.1 |
| Scopes | One, a selection (multi-select in Library and To-do), all eligible (Upgrade all, Make all lossless files AIFF, the CDJ group's Convert all, Auto-upgrade) | §2.2–§2.5 |
| Lossy files | Converted only when the user picks them or from the CDJ group, never by an "all" over the library: AIFF from lossy costs 5–10× the space for no gain in sound | §2.2 |
| Lossless files | Every one can become a clean AIFF (FLAC, WAV, ALAC, 24-bit or 96 kHz AIFF, an AIFF with a messy name or tags), one at a time or all at once | §2.4 |
| Auto-upgrade | A switch in Setup and Settings, on by default: the user's standing go for Same track on upgrades that need no decision, run at the end of a sync while rekordbox is closed | §2.5 |
| Timing | New audio shifted onto **rekordbox's** timeline of the old file, measured from `PWV3` and snapped to the codec's known delay | §3 |
| Format | 16-bit / 44.1 kHz AIFF, the library format, for every source, lossless ones too | §3.5 |
| Name and tags | The download's name (`names.expected_stem`) and tags (`audio.write_tags`), artwork capped CDJ-safe | §3.5, §4 |
| rekordbox's text columns | Discjockey writes the clean title, artist, album, label, ISRC and comment, **only for fields where rekordbox still shows what the old file's tag said**; the user's own edits stay. Reload Tag is the fallback if the live test fails | §5.11 |
| Where | The old file's folder, under `Artist - Title.aiff`; the old file to `Superseded/` (mirrored). One journaled step per track | §4 |
| Key and code | Our own code (`discjockey/rekordbox/`), with the key in it. The only new dependency is `sqlcipher3-wheels` | §5.2 |
| Safety | rekordbox closed (checked again before every commit), schema guards, a backup per batch, journal, undo per field, crash recovery, refusal for cloud-synced tracks | §5 |
| USB sticks | The live test first checks whether a plain sync picks up the new file; the words follow the result. No write to the stick now | §6 |
| Staging | A: read side + New track lined up. B: write side, batches, Same track for any format, Upgrade all, text columns, multi-select in To-do; live test. C: Auto-upgrade. D: Convert, Rename, CDJ group, Make all lossless AIFF, multi-select in Library. E (issue 40): rekordbox follows Discjockey's own moves; hand moves stay with rekordbox's Relocate | §13 |

## 2. Shape: actions, eligibility and the four ways to start

### 2.1 One step, three actions

**The step.** `convert` takes one track and a source of audio: the parked upgrade (lossless or a better stream) or
the current file itself. It writes `Artist - Title.aiff` lined up to rekordbox's timeline (§3), points every
rekordbox track of the old file at it and writes the clean text columns (§5), then moves the old file to
`Superseded/`. Its sibling `rename` (§7.1) gives an AIFF its clean name and repoints, with no new audio. The AIFF
in-place swap of today stays as it is (§7.2).

| Action (user's words) | For | Step |
|---|---|---|
| **Same track** (an upgrade) | a parked better version that is the same edit | AIFF now: the in-place swap. Anything else: `convert` from the parked file |
| **Convert to AIFF** | an own file that isn't a clean AIFF: any other format, an AIFF that isn't 16-bit/44.1 kHz, or one whose tags aren't the download's | `convert` from the file itself (an AIFF 16/44.1 is copied sample for sample with the new tags; old one to `Superseded/`) |
| **Give it its clean name** | an own AIFF 16/44.1 whose tags are right and whose name isn't `Artist - Title.aiff` | `rename` |

**Why "Convert" also covers an AIFF with wrong tags.** Rewriting tags inside a file overwrites a music file. A new
file with the clean tags and the old one in `Superseded/` keeps the "never overwrite" invariant at the cost of the
file's size once.

**What Discjockey records.** A converted lossy file stays "not lossless" in Discjockey's records: its file row keeps
`status`, `source_format` and `source_kbps` from the old file, the Library says "Your AIFF was made from this" (the
existing `NOW_TIP`), and upgrade checks go on for it. The step writes the file row with its facts and
`placed_by = 'app'`, so the import's sound check doesn't run again. Check first: that a rescan of a row with known
facts and an unchanged content key reads nothing again.

**Why nothing happens at import by itself.** Converting lossy audio doesn't improve the sound and costs 5–10× the
space (a maintainer's collection would grow by about 15 GB), and the biggest rekordbox write would run while the user
is busy importing. Every conversion is started by the user: per click, per selection, per "all", or once for good
through Auto-upgrade.

### 2.2 Eligibility (pure, one place)

`rekordbox/eligible.py` (pure: no I/O) answers per track and action `Eligible | Skip(reason)`, from the song entry,
the file's facts (format, bit depth, rate, tags read at import), the parked upgrade and the rekordbox state. Views and
commands call the same function; counts on buttons are its result.

| Action | Eligible when | Never eligible |
|---|---|---|
| Same track | a parked upgrade whose alignment is `exact` or `shifted` (measured again when it runs, as `swap` does), the current file on disk, and, for a file that isn't AIFF, rekordbox `ready` or `none` | `different` or `unknown` edit (needs the user's choice: New track or Discard); rekordbox `unreadable` for a non-AIFF file; refused before by Auto-upgrade and nothing changed since (§2.5) |
| Convert to AIFF | an own file on disk that isn't a clean AIFF (§2.1), with an artist and title in its record | a file Discjockey downloaded (already clean); a file away (offline drive) |
| Give it its clean name | an own AIFF 16/44.1 with right tags and a name other than its `expected_stem` (an ID suffix only where the name is taken) | as Convert |

"Right tags" (`tags_clean`) means TIT2, TPE1 and TALB equal what `write_tags` would write from the song record, and a
cover is there when the record has one. Label, ISRC, comment, genre and year aren't compared: they only add, and a
user's own genre or year is carried over anyway (§3.5).

**The "all" scopes:**
- **Upgrade all** (To-do): every eligible Same track (§2.3).
- **Make all lossless files AIFF** (Library): every file whose format is lossless (FLAC, WAV, ALAC, AIFF) and that is
  eligible for Convert or Rename (§2.4).
- **Convert all** in the CDJ group (To-do): every file `cdj_problem` flags (§9.3).
- **Auto-upgrade**: Upgrade all, started by the sync (§2.5).

A lossy file the CDJ rule doesn't flag is converted only when the user picks or selects it.

**Per-track refusals inside a batch** (rekordbox can't follow: not analysed, timing, cloud; space; the file changed)
skip that track with its reason and the batch goes on. rekordbox open is the one refusal that stops a batch (§5.6).

### 2.3 Upgrade all (To-do)

The To-do page's **Upgrade ready** group carries "Upgrade all (N)", N being the eligible Same tracks. Before it starts
the panel says how many become Same track and how many need a choice and stay ("12 upgrades keep their cues. 3 need
your choice and stay."). One quit of rekordbox (only if one of them needs a rekordbox write), one backup, one batch.
The rest stay in the group with their question. Selecting several items of the group gives the same action for the
selection.

### 2.4 Make all lossless files AIFF (Library)

**Where.** In the Library, as an action on the view on screen: All means the whole library, a playlist or folder
view means its files. It isn't a To-do: it is a tidy-up the user decides to do, not a problem Discjockey found. The
same action is offered for a selection of tracks.

**Before it starts**, a sheet shows (computed by a read-only `aiff_plan(scope)`):
- the counts by kind: "FLAC → AIFF 40 · WAV → AIFF 12 · AIFF 24-bit or above 44.1 kHz → 16-bit 9 · new tags 7 ·
  clean name only 30";
- the skipped ones with their reason (not analysed in rekordbox, Cloud Library Sync, drive away, no artist known);
- disk space: what the new files need on each drive against what is free there; the old files' size, which moves to
  `Superseded/` (on the same drive, so it takes no new space);
- that rekordbox must be closed, and one sentence on the format: "Every file becomes a 16-bit/44.1 kHz AIFF, the
  format every CDJ plays and every download has; your original stays in Superseded/."

**Running.** Progress per track (n of N, the track's name), Stop between tracks. A stopped or interrupted batch shows
"Resume (k left)" in the same place and in `discjockey batch resume`; resuming checks each left track's eligibility
again. Undo for the whole batch from its check card or `discjockey batch undo`; per track as for any batch.

### 2.5 Auto-upgrade on sync (Settings)

**The switch.** Settings › Upgrades: "Upgrade automatically when I sync", `settings.json` key `auto_upgrade`,
**on by default** (the user's decision, 2026-11-07; a missing key reads as on). It is a standing go to change
rekordbox's library and move files with no click; the go is the switch being on. So that a new user sees it once,
**Setup shows it as a switch that starts on**, with one plain line saying what it does (§8), and the user can turn
it off there or later in Settings (the row's Hint and InfoTip say the same). It is set like `read_liked_music`: a
`Settings` field, the bridge write `set_auto_upgrade(on)`, the command `discjockey settings auto-upgrade on|off`.
It still does only measured same-edit upgrades and waits while rekordbox is open (below).

**Which upgrades.** Exactly Upgrade all's set (§2.2): a measured same edit (`exact`/`shifted`, measured again), lossless
or a better stream. A different edit or an unsure match always waits for the user. Turning the switch on also covers
the upgrades already waiting; its Hint says so.

**When.** At the end of a sync run, after its downloads and upgrade checks, under the same library lock, as the run's
last phase (`auto_upgrade`). A dry run lists what it would upgrade and changes nothing. Stopping the sync stops the
phase between tracks; the rest is eligible again at the next sync.

**rekordbox open.** Checked once when the phase starts: **if rekordbox runs, nothing is upgraded** in this run, AIFF
swaps included (rekordbox may have the file loaded on a deck). They wait in To-do's Upgrade ready group, marked
"waits for rekordbox to be closed", and are done at the next sync with rekordbox closed, or at once with Upgrade all.
If rekordbox opens during the phase, the track in work rolls back at its commit check (§5.8), the phase ends, and the
rest waits the same way. The engine never waits and never asks to quit.

**A refusal** (timing, not analysed, cloud, space) leaves the upgrade waiting with its reason, recorded on it
(`auto_refused: {reason, at, anlz_mtime}`). Later syncs skip it until the user acts or rekordbox analyses the track
again (the ANLZ file's mtime changes), so a sync doesn't decode it again each time.

**Backup and undo.** One backup per run's batch. Undo per track and "Undo all from this sync" on the batch's check
card.

**What the user sees afterwards.**
- The sync's result list: a section "Upgraded" with one row per track, and the waiting or refused ones with their
  reason. The run summary line: "Upgraded 12 tracks; your cues stayed. 3 wait for rekordbox to be closed."
- To-do's "Check in rekordbox": one card for the batch (§7.2): analyse again (lock the grid first), the USB step (§6),
  Undo per track or all, Done.
- The report (`reports/`) lists them under "Upgraded", with the backup's id.

**The invariant changes.** CLAUDE.md today: "**Files move only in a move batch the user started** (tidy-up, the
Playlists save question, a folder rename on disk): logged in `library.db`, undoable; the sync never moves a file
(option A)." The new text:

> **Files move only in a batch the user started:** a move batch (tidy-up, the Playlists save question, a folder
> rename on disk) or an AIFF batch (Same track, Convert to AIFF, Give it its clean name, Upgrade all, Make all
> lossless files AIFF), logged in `library.db` and undoable. The sync itself never moves a file (option A), with one
> exception: **Auto-upgrade**, a switch that is on by default and shown in Setup and Settings, is the user's standing
> go for Same track on upgrades that need no decision (a measured same edit) while it is on. The sync then runs them
> as one AIFF batch at its end, only while rekordbox is closed, with the same backup, journal and undo as a batch
> started by hand. Switched off, the sync moves no file.

## 3. Timing: lining the AIFF up to rekordbox's timeline

### 3.1 The model

rekordbox stores cues (`djmdCue.InMsec`, whole ms) and the grid (`PQTZ` in the ANLZ `.DAT`, ms) on its own decode
timeline of the old file. After the repoint it reads the same numbers against the AIFF, whose timeline starts at
sample 0. So the AIFF must hold, at every ms, the audio rekordbox's decoder produced there from the old file.

- `t_ff`: a moment in ffmpeg's default decode of the old file (the gapless trim `align.decode` and every Discjockey
  measurement use).
- `d` (seconds): rekordbox's offset for this track; a moment at `t_ff` sits at `t_ff + d` on rekordbox's timeline.
- `L` (samples at 44.1 kHz): `align.compare(current, new).offset_samples`; positive means the audio comes later in
  the new file.

The shift handed to the renderer (samples at 44.1 kHz; positive trims the start, negative puts silence in front, as
`upgrades.build_staged` does today): **from an upgrade** `k = L − round(d · 44100)`; **from the file itself**
`k = −round(d · 44100)`.

The renderer is one function, `audio.render_aiff(src, dst, shift_samples)`, used by the swap, New track and
`convert`. It decodes any format, resamples to 44.1 kHz with the library's filter (`audio.RESAMPLE`, triangular
dither), applies the shift **after** resampling, and writes `pcm_s16be` AIFF. `build_staged` becomes a thin call to
it; AIFF→AIFF stays byte-identical (no resampling when the input is already 16-bit/44.1).

### 3.2 Measuring `d` from `PWV3`

- **Read.** The track's `.EXT` file (`AnalysisDataPath` with `.EXT`, under the analysis root) holds `PWV3`: one byte
  per column at 150 columns per second, height = `byte & 0x1F`.
- **Compare.** Decode the old file with ffmpeg's default decode (mono, native rate), take the peak absolute sample of
  each 1/150 s window, and correlate that envelope with the heights for shifts from −60 to +80 ms in 0.25 ms steps,
  with a parabolic refinement; skip the first 40 columns (the research's `rbwave.py` method). `rekordbox/timing.py`
  holds it as a pure function: `measure(heights, audio, sr) -> Measured(offset_s, score)`.
- **Expected delays.** `expected(codec, sr, trim_samples) -> list[float]`. `trim_samples` is the start trim ffmpeg
  applies to this file: its default decode against the untrimmed decode (`-flags2 +skip_manual` for MP3,
  `-ignore_editlist 1` for MP4; check first: both flags with the bundled ffmpeg, and that the lengths of the two
  decodes give the trim exactly). MP3: `{0, trim, trim + 1152}` samples; M4A/AAC: `{0, trim}`; PCM, FLAC, ALAC: `{0}`.
- **Accept** when `score ≥ 0.90` and the measurement is within **0.25 ms** of one expected value; then **use that
  expected value**, exact to the sample.
- **Refuse otherwise** ("timing", §8): a correlation below 0.90 or a value outside the set (the research's MP3 at
  about +2455 samples, its WAV at −8 ms). The measured value goes into the `--json` details.

### 3.3 By format

| Old file | Expected `d` | Notes |
|---|---|---|
| MP3, LAME/Lavc tag | 1105 samples, sometimes 1105 + 1152 | Measured; the header can't tell which |
| MP3, no tag | 0 or 1105 (a missed tag) | Measured |
| M4A/AAC (ffmpeg, YouTube) | the edit list's skip (1024 + 576 at 44.1 kHz, about 21.5 ms at 48 kHz) | Measured. Apple's 2112 priming is covered through `trim` |
| WAV 16/24-bit, AIFF | 0 | Calibration was 0 on 20 entries |
| WAV 32-bit float | 0 | Dithered to 16-bit |
| FLAC, ALAC | 0 | Not measured on a real entry yet: a live-test item |
| 48 kHz anything | as above, in seconds | Resampled to 44.1 kHz; a live-test item |
| 24-bit / 88.2–192 kHz | 0 | Becomes 16/44.1; the original stays in `Superseded/` |

### 3.4 No analysis, or a disagreement

- **No `PWV3`** (never analysed, or the ANLZ files are gone): with **no cues and no grid** the timing doesn't matter
  (`d = 0`); a PCM, FLAC or ALAC file uses `d = 0` (its set has only 0); an MP3 or M4A with cues or a grid is
  **refused** with "not analysed" (§8).
- **Several rekordbox tracks for one file:** each is measured; they must agree on the same expected value, else
  "timing".
- **Not in rekordbox:** `d = 0`, and the database part is skipped.

### 3.5 Format and tags of the new file

- **16-bit / 44.1 kHz AIFF for every source**, lossless ones too, made like every download (`audio.RESAMPLE`). It is
  the library format, plays on every CDJ, and an upgrade comes at 44.1 kHz anyway. A 24-bit or 96 kHz original loses
  nothing audible and stays whole in `Superseded/`. The user sees the reason in one sentence where they start a batch
  (§2.4, §8).
- **Tags: the download's set.** Exactly the ID3v2.3 frames `audio.write_tags` writes on every download: TIT2 title,
  TPE1 artists joined by ", ", TALB album, TSRC ISRC, TPUB label, APIC cover (JPEG, type 3), COMM Discjockey's quality
  line (`quality.quality_line`).
  - **From an upgrade:** the parked file's tags (`audio.copy_tags`, as the swap does): Qobuz's names, cover, label and
    ISRC, and the new source's quality line.
  - **From the file itself:** title and artists from the song record; album, ISRC, label and cover from the song
    record when it is linked to a playlist song (`songs.album`, `isrc`, `image_url`), else from the old file's tags.
    The comment is the quality line of the old file's format, unless the old file's comment is the user's own (not
    empty, not a quality line Discjockey wrote: Mixed In Key's "1A - Energy 6"): then it stays in the new file, and
    rekordbox's `Commnt` is written only over nothing or a quality line, like genre and year otherwise.
  - **Carried over from the old file when it has them:** genre (TCON) and year (TDRC/TYER), the user's own. Nothing
    else; the old file keeps all its tags in `Superseded/`. Check first: the import's tag reader for own files
    (`importer` pass 1 / `identify`), to reuse for M4A, FLAC, WAV and AIFF.
- **Artwork, CDJ-safe.** A new `audio.cdj_cover(data) -> bytes | None` gives a baseline JPEG of at most 600 × 600 px
  and 500 KB, scaled with the bundled ffmpeg (native `mjpeg`/`png`) when the source is bigger or a PNG. Every write
  goes through it, downloads included; today's 600 px Qobuz covers pass byte-identical. Check first: Pioneer's limit
  for embedded artwork.

## 4. Where the new file goes, and how it fits the invariants

- **Place:** the old file's folder (`planner.replacement_dir`: "anywhere else: the current file's folder"); a file in
  a playlist folder's `not_lossless/` follows `add_new`'s folder rule.
- **Name: the download's name.** `NameReserver.choose(folder, expected_stem(e["artist"], e["title"]), ".aiff",
  track_id)`, the call downloads, `add_new` and `add_bought_file` use: the first artist, the record's title,
  `sanitize_stem`, the length cap, an ID only when the name is taken. Keeping the old name existed only so rekordbox's
  Relocate could find the file; Discjockey now points the track at the new file itself.
- **The rule that comes with it:** a step that gives a file a new name **must** repoint every rekordbox track of that
  file in the same step. When it can't (rekordbox unreadable, open or cloud-synced), the step is refused. A file with
  no rekordbox track needs nothing.
- **How clean the name is depends on the song record.** A linked own song carries the service's names; an unlinked
  one the names the import read. Check first: whether the import cleans own songs' names like `titles.split_title`;
  if not, that is fixed where the record is made, not in this step.
- **The old file** moves to `superseded_dir(path, watched_root(...))` under its own name. **Moving never renames.**
- **Never delete, never overwrite.** The new file is a new name; the old file is moved, never written.
- **Every file change through `move_path`** (cross-drive staging with its journal: watched folders can sit on other
  drives than `.tmp/`). The step is journaled in library.db's `pending` as op kind `convert` (and `rename`), with its
  own marks and recovery, like `swap`; `run_op` can't carry it, because a database write sits between the renames
  (§5.8).
- **Offline or missing:** refused per track (`file_state`). Free space is checked per track before rendering (the
  staged size, plus the target drive when it is another), and for the whole batch in its preview.

## 5. The rekordbox write

### 5.1 Finding rekordbox

- `rekordbox/locate.py` reads `~/Library/Application Support/Pioneer/rekordboxAgent/storage/options.json`
  (`db-path`, `analysis-data-root-path`), falling back to `~/Library/Pioneer/rekordbox/master.db` and `…/share`. The
  app version (newest `/Applications/rekordbox */rekordbox.app` Info.plist) is shown and logged, never a guard.
- **`DISCJOCKEY_REKORDBOX=<folder>`** replaces the lookup (`<folder>/master.db`, `<folder>/share`). `tests/conftest.py`
  sets it to an empty temp folder for **every** test, and a test pins that.
- **Not installed** (no `master.db`): state `none`; the steps convert and skip the database. **rekordbox 5**
  (`datafile.edb`) counts as `none`. Supported: rekordbox 6 and 7 (`master.db`, `DBVersion` 6000).

### 5.2 The key: our own code, not pyrekordbox

**Decision: Discjockey's own package `discjockey/rekordbox/`, with the key as a constant. The only new dependency is
`sqlcipher3-wheels` (pinned).**
- **What we need is small:** open one encrypted SQLite file, read and update a few columns of a few tables (§5.5,
  §5.11), read one ANLZ tag (`PWV3`) and splice one (`PPTH`).
- **pyrekordbox's ANLZ save is the wrong tool:** `AnlzFile.save()` rebuilds the file and drops tags it doesn't know
  (`PVB2`, FLAC's seek index), and its `update_content_path` doesn't update `contentFile`.
- **Its weight in the app:** SQLAlchemy, psutil, construct, bidict and python-dateutil to sign, license and keep
  current; its `commit()` rewrites `masterPlaylists6.xml`, which we never want touched.
- **A key change reaches users in one release** (ours), not two. `KEYS` is a tuple tried in order.
- **Licence:** pyrekordbox is MIT; the user decided the EULA question. The package docstring credits pyrekordbox and
  rekordbox-edit for the published format knowledge; no code is copied.
- **The open:** `PRAGMA key='<64 hex chars>'` as a passphrase with SQLCipher 4 defaults, as pyrekordbox does. Check
  first, on a copy: the passphrase form, not the raw `x'…'` form, opens it.
- **The dependency:** `sqlcipher3-wheels` 0.5.7 has a cp312 macOS 11 arm64 wheel with SQLCipher 4.12 and OpenSSL
  linked statically; zlib, BSD-style and Apache-2.0 licences, all GPL-3.0 compatible, in its `dist-info/licenses/`.
  Check first: `collect_licenses.py` picks them up; PyInstaller collects `sqlcipher3._sqlite3`; signing covers the
  `.so`; `selftest.py` opens a keyed in-memory database.

### 5.3 Guards (before any write; each refuses with nothing changed)

1. **The key opens it**, else state `unreadable`.
2. **`DBVersion` is in `{"6000"}`, and every column we read or write exists** (`PRAGMA table_info`, the lookup tables
   of §5.11 included), else `unreadable`.
3. **rekordbox is not running:** `/bin/ps -Axco comm=`, exact match on `rekordbox` (`rekordboxAgent` doesn't count;
   the live test checks that the agent never writes `master.db` while rekordbox is closed). Checked when a batch
   starts **and inside every track's write transaction, just before the commit**.
4. **rekordbox closed cleanly:** no `master.db-wal` / `-shm` while it is closed, else "unclean". That also makes a
   file copy a consistent backup.
5. **No cloud sync on the track:** `usn IS NOT NULL` or `rb_local_synced <> 0` on a row we would write → "cloud", per
   track.
6. **One Discjockey writer per Mac:** `<support>/rekordbox.lock`, held for a whole batch and its undo.
7. **The same rekordbox library:** the journal records `DBID`; recovery or undo against another `DBID` touches nothing
   in rekordbox and says so.

### 5.4 Finding the track

`entries_for(place, path)` returns the `djmdContent` rows with `rb_local_deleted = 0` whose `FolderPath`,
NFC-normalized and case-folded, equals the old file's absolute path (on APFS also when `os.path.samefile` holds);
streaming rows (`FileType` 25) never match. **None:** convert without the database ("This file isn't in your
rekordbox collection…"). **One:** the normal case. **Several:** all repointed in one transaction, each with its own
undo record, if their measurements agree.

### 5.5 What changes, and what doesn't

| Where | Column / data | New value |
|---|---|---|
| `djmdContent` | `FolderPath`, `FileNameL` | the new file's absolute path (NFC) and name |
| | `OrgFolderPath` | the new path **only if** it equalled the old `FolderPath` (it is `''` in practice) |
| | `rb_LocalFolderPath` | unchanged (NULL in practice). Check first: if a row has it equal to the old path, treat it like `OrgFolderPath` |
| | `FileType`, `FileSize`, `BitDepth`, `SampleRate`, `BitRate`, `Length` | 12 (AIFF), the new size, 16, 44100, 1411, whole seconds |
| | text columns | §5.11's rule |
| | `rb_local_usn`, `updated_at` | each changed or created row its own next number (`localUpdateCount + 1`, `+ 2`, …: created lookup rows, then tracks, then `contentFile` rows; corrected in stage B from a copy of a rekordbox 7 library, where rekordbox numbers rows one by one); now as `YYYY-MM-DD HH:MM:SS.fff +00:00` |
| `agentRegistry` | `localUpdateCount.int_1` | the last number given; its `updated_at` is left (rekordbox doesn't refresh it per count) |
| ANLZ `.DAT` `.EXT` `.2EX` `.3EX` | `PPTH` | `?/<new name>` where it held `?/<old name>`: a byte splice, lengths updated, every other byte kept |
| `contentFile` | `Hash`, `Size` of each changed ANLZ file | the new MD5 and size (rekordbox's own invariant); `rb_*` flags unchanged |

**Unchanged:** `ID`, `UUID`, `AnalysisDataPath`, `BPM`, `KeyID`, rating, colour, artwork, and every table keyed by
`ContentID` (`djmdCue`, `contentCue`, `djmdSongPlaylist`, `djmdSongHistory`, `djmdSongMyTag`,
`djmdSongHotCueBanklist`, `djmdSongRelatedTracks`, `djmdSongSampler`); the waveform, grid, `PVBR` and phrase tags. A
test compares every other column and table before and after, byte for byte.

The live run left `contentFile` stale and rekordbox worked. Updating it is the more consistent choice but unproven;
the live test decides, and the fallback is to leave `PPTH` and `contentFile` alone.

### 5.6 rekordbox open

When a batch starts and any of its tracks needs a rekordbox write, rekordbox must be closed: if it runs, the job ends
with kind **`rekordbox_open`** and nothing changed (§8; console exit code 4). A batch whose tracks need no rekordbox
write (AIFF swaps while rekordbox runs, files not in rekordbox) goes ahead; Auto-upgrade is stricter (§2.5). If
rekordbox opens during a batch, the track in work rolls back at its commit check, the batch stops with
`rekordbox_open`, and the rest waits for Resume. The engine never waits by itself. The design round (§9) decides
whether panels show rekordbox's live state (`rekordbox_status`).

### 5.7 Backup, one per batch

- **When:** before a batch's first rekordbox write, if no backup newer than `master.db`'s current content exists,
  into `<music folder>/.discjockey/rekordbox/backups/<UTC time>/`: `master.db` (a file copy, consistent because of
  guard 4), the ANLZ folders of **all** the batch's tracks, and `manifest.json` (app version, `DBID`, `DBVersion`,
  master.db's SHA-256 before and after, the batch id and track ids).
- **Reuse:** the manifest records master.db's SHA-256 after the batch; the next batch reuses that backup while the
  file still has that hash and adds only its tracks' ANLZ folders (about 8 MB of `master.db` for about 800 tracks).
- **Kept** while an undo refers to it, plus the newest 3; pruned with `.discjockey/undo/` (`library._prune_undo`'s
  caller).
- **Restoring the whole database** is the last resort (it drops every rekordbox change since): the command
  `rekordbox restore <backup> --yes` (§10), not a hub button. It backs up the current `master.db` first and refuses
  while rekordbox runs. After a restore, tracks Discjockey repointed since that backup point at their old paths,
  whose files are in `Superseded/`: the result lists them (`missing_after`, `[{"id", "path", "was"}]`) and the
  words say "Undo those batches first (`discjockey batch undo`), or Relocate them in rekordbox" (corrected in stage
  B; plan §0.14).

### 5.8 Order of one track's step, and crash recovery

**Invariant:** every rekordbox track points at a file that exists at every moment. **The commit point is the
`master.db` transaction**; the row's `FolderPath` tells recovery which side of it a crash happened on.

1. **Render** into `.discjockey/.tmp/<track>/convert.aiff` and hash it. A failure leaves nothing.
2. **Journal** the `convert` op (`pending`): the track, the batch id, old and new paths, the `Superseded/` path, the
   staged path, the SHA-256 of the staged and old files, the parked upgrade (if any) and its held place, `DBID`, per
   rekordbox row the before and after values of §5.5 and §5.11 (lookup rows created included), per ANLZ file the path,
   old and new SHA-256 and the backup id.
3. **Back up** (§5.7, once per batch), then mark `backed_up`.
4. **Place the new file:** `move_path(staged → new)`, mark `placed`.
5. **Write rekordbox:** `BEGIN IMMEDIATE`; check each row still holds its before values in `FolderPath` and
   `FileNameL` (else roll back, "changed"); run the `UPDATE`s and lookup inserts, `contentFile` included; write the
   spliced ANLZ files as `.dj-new` and rename them over the originals; check guard 3 again, **COMMIT**, mark
   `committed`. If rekordbox appeared, roll back, restore the ANLZ files from the backup, and stop with
   `rekordbox_open`.
6. **Move the old file** to `Superseded/` (`move_path`).
7. **End the op:** the song entry (path, the upgrade's status/source or the kept status), the file rows, the batch
   item's state, and the rekordbox check with its undo record; an upgrade's parked download goes to
   `.discjockey/undo/<track>/`, as `swap` does with `_hold`.

**Recovery (`convert.recover`, from `recover_pending`):**
- **Not committed** (`FolderPath` still old): ANLZ files with the "new" SHA-256 come back from the backup; the placed
  new file (its SHA-256 the staged one, Discjockey's own render) goes back to `.tmp/` and is dropped; the op is
  dropped. "The replace for {name} was not finished; your file and your rekordbox track are as they were."
- **Committed** (`FolderPath` new): finish steps 6–7. "Finished an interrupted replace for {name}."
- **Neither** (rekordbox changed the row since): rekordbox untouched; only the files are resolved by which file the row
  names; "needs your help" with both paths.
- **The ANLZ rollback needs rekordbox closed:** while it runs the op **waits**, as an offline drive does (`_Waits`):
  "Quit rekordbox so Discjockey can finish an interrupted replace for {name}." Check first: that `recover_pending`'s
  waits let other work continue.
- **Another `DBID`:** only the file side is resolved; the message names the rekordbox step left for the other Mac.
- The batch the crash interrupted is marked `stopped` (§5.12) and offers Resume.

### 5.9 Undo, per field, per track and per batch

The undo is offered while the rekordbox check stands. It needs rekordbox closed when the step wrote to rekordbox
("Quit rekordbox to undo"). Op `convert_undo`, the same invariant in reverse:
1. **Decide first.** Identity columns (`FolderPath`, `FileNameL`, and `OrgFolderPath` if we changed it) must hold
   exactly what we wrote, else the user relocated or changed the track: **refuse with nothing changed**. The new
   file's SHA-256 must be ours, and the old file in `Superseded/` must have its recorded key (as `upgrades._unchanged`).
2. Move the old file back from `Superseded/`.
3. In one transaction: the identity columns back; the file-fact columns back **whatever they hold now** (they describe
   the file the row points at); each text column back to its before value **only where it still holds what we
   wrote** (an edit the user made since stays); lookup rows we created are left (an unused row is what rekordbox
   leaves after an edit too; check first); fresh `rb_local_usn` and `updated_at`. `PPTH` back only where it still
   holds our name (a re-analysis rewrote it otherwise), and `contentFile` for the files spliced.
4. The new AIFF goes to `.discjockey/undo/<track>/`; the next clean-up deletes it (Discjockey's own render, SHA-256
   checked; its audio still exists as the parked download, back in `Upgrades ready/`, or as the old file), as
   `delete_parked` and `forget_undo` do.

Everything the user did in rekordbox since is kept: cues set on the AIFF also fit the old file, because both sit on
the same timeline. **Undo of a batch** runs the per-track undo for each of its done tracks, newest first, in one job
with one quit and one `rekordbox.lock`: rekordbox open at the start undoes nothing, opening meanwhile or Stop ends it
before the next track (the rest listed as waiting); a track whose undo is refused stays and is listed with its reason. "Done,
checked in rekordbox" ends the undo for the track or the batch (`forget_undo`) and releases the backup.

### 5.10 Cloud Library Sync

Cloud-synced tracks are refused (guard 5) until someone tests how an outside write spreads to other devices. A track
that was never synced can be changed even when the account is logged in.

### 5.11 rekordbox's text columns: Discjockey writes them, but never over the user's edits

**The decision (re-made on the user's question).** After a repoint Discjockey writes the clean values into rekordbox
itself, so the user needs no Reload Tag. The fair look:
- **The surface is bounded.** `Title`, `ISRC` and `Commnt` are plain columns of `djmdContent`. Artist, album and label
  are ids (`ArtistID`, `AlbumID`, `LabelID`) into `djmdArtist`, `djmdAlbum`, `djmdLabel`, filled by
  **find-or-create**: an active row whose `Name` equals the clean value (NFC, exact; several → the lowest `ID`), else a
  new row with rekordbox's own scheme for `ID`, `UUID`, `SearchStr`, `rb_local_usn` and the timestamps (check first:
  read the scheme from rekordbox's own rows on a copy, and how pyrekordbox's published `add_artist` does it). Existing
  lookup rows are never edited or deleted: renaming an artist row would rename every track of that artist. Genre and
  year don't change (the new file carries the old ones). Artwork isn't written (rekordbox keeps its own cached cover).
- **The user's edits are safe by rule.** A field gets the clean value only where **rekordbox's value still equals the
  old file's tag** for that field, read at repoint time (both NFC and trimmed; an empty field and a missing tag count
  as equal; the artist compared as the joined string). Where they differ, the user (or rekordbox's import) changed it:
  it stays, and the result says "kept your own {field}". A field rekordbox normalised at import also stays: the safe
  side, just not updated. This is safer than Reload Tag, which replaces every text field of the selected tracks,
  edits included.
- **The one hole, checked first in the live test:** whether rekordbox 7 writes an info edit into the file's tags. If
  it does, an edit looks like the file's tag. Then the rule also skips a field when the old file changed after
  rekordbox imported it (file mtime later than the row's `created_at`), and those tracks keep the Reload Tag step.
- **Undo per field** (§5.9) and the whole-row test (§12) cover it; the guard list grows by the lookup tables' columns.

**Fallback** if the live test shows rekordbox rejects or mangles the written fields (created rows, sort order, search):
the columns are left alone and the check card gives Reload Tag in the user's words, for the batch's tracks only: "In
rekordbox's Collection, select the tracks listed here (⌘-click each), right-click › **Reload Tag**. Don't select all:
Reload Tag replaces every name you changed in rekordbox on the tracks you select." Check first: the menu item's exact
name in rekordbox 7. When: after the batch, before the next USB export. (The user's ⌘A idea would reload every track
in the collection and lose edits on all of them.)

**Never touched:** rating, colour, My Tags, play count, cues, grid, key and BPM.

### 5.12 Batches in library.db

- **Records:** two new tables in `db.py`: `aiff_batches` (id, kind `upgrade`/`convert`/`mixed`, started by `user`,
  `upgrade_all`, `make_aiff`, `cdj_all` or `auto_upgrade`, scope, started/ended, state `running`/`stopped`/`done`,
  backup id) and `aiff_items` (batch, track, action, state `planned`/`done`/`skipped`/`failed`/`undone`, reason,
  result). They stay out of the move log on purpose: the move log's rows are moves that tidy-up's undo walks.
- **One job:** `rekordbox.lock` and the library lock for the whole batch; guard 3 at the start; one backup; items in
  order, each its own journaled step (§5.8); `JobProgress` per item; Stop is checked between items.
- **Stop, crash, rekordbox opening:** the batch is `stopped` with its `planned` items. **Resume** runs them again
  (eligibility re-checked per item); Auto-upgrade batches aren't resumed (the next sync plans afresh).
- **The check:** each track keeps its own check and undo record (today's `library.upgrade_undo`), now with the batch
  id; To-do shows them as one card per batch (§7.2).

## 6. USB sticks exported before the repoint

What we know: after the live run, rekordbox's device sync didn't notice the change and the stick kept the old file;
the device view offered only "remove from playlist", the tracks were in several playlists, and the user rebuilt the
stick. The live run had stale `contentFile` hashes and no `rb_local_usn` bump, so it doesn't settle what a consistent
write does.

**Live test, in this order** (one track exported to a spare stick in two playlists before the repoint):
1. **A plain sync.** After the repoint (consistent `contentFile`, bumped `rb_local_usn`/`updated_at`), open rekordbox
   and sync the stick the way the user always does. Check the stick: a new `.aiff` under `Contents/`, and the CDJ (or
   rekordbox's device browser) loads it with the cues.
2. **If not, what rekordbox offers on the device's own track list** (the stick's All Tracks view, not a playlist):
   check whether a "remove from device" item exists there, removes the track from every playlist on the stick at
   once, and whether the next sync puts the new file back into those playlists.
3. **Else rebuild:** the user's known way.

**Discjockey writing the stick, weighed honestly.** The stick holds `PIONEER/rekordbox/export.pdb` (DeviceSQL pages,
described by Deep Symmetry's crate-digger and rekordcrate), `exportLibrary.db` (newer players) and its own ANLZ files.
A repoint there means copying the AIFF into `Contents/`, rewriting the track row's path strings (which changes row
lengths, so pages must be rebuilt), the same in `exportLibrary.db`, and `PPTH` on the stick. It can't be tested
offline against a real CDJ, firmware differs between players, and a wrong write breaks a stick before a gig.
**Not now.** If the test lands on 3 and rebuilding proves a real burden, it becomes its own issue with its own design.

**The words follow the result** (§8 has all three): result 1 → "sync it in rekordbox as usual"; result 2 → the exact
menu path; result 3 → "rebuild the stick before your next gig", once per batch, with the README explaining how.
Until the test, stage B's words are result 3's, because that is what is known to work.

## 7. The stale waveform; rename; what changes on the screens

**After a repoint, the ANLZ files still describe the old file:** waveform, grid, key, phrases and `PVBR` (an MP3 seek
index). The grid and cues are right, because the audio sits on the same timeline. After Convert the audio is the same,
so nothing needs redoing. After an upgrade the waveform shows the lossy sound until the track is analysed again (as
after today's swap: "analyse it again (lock the beatgrid first if you set it by hand)"). The live test checks that a
leftover `PVBR` doesn't disturb seeking in an AIFF.

### 7.1 Give it its clean name (an own AIFF with a messy name)

The `rename` step gives an own AIFF 16/44.1 with right tags its clean name (§4), in the same folder, through
`move_path`, with every rekordbox track repointed: only the path columns, `PPTH` and `contentFile` change; the audio,
tags and file facts don't. Refused while rekordbox can't follow (open, unreadable, cloud) when the file has a
rekordbox track. Undoable per field (§5.9). Offered in the Library details for one or several tracks, and inside Make
all lossless files AIFF.

**The invariant changes.** CLAUDE.md today: "**Moving never renames:** a tidy-up and its undo keep each file's name as
it is, because rekordbox's Relocate finds files by name." The new text:

> **Moving never renames:** a move (a tidy-up, its undo, a folder rename) keeps each file's name, so rekordbox's
> (Auto) Relocate finds it by that name. A file gets a new name only in a step the user chose that points every
> rekordbox track of that file at the new name itself, while rekordbox is closed (Convert to AIFF, Same track for a
> file that isn't AIFF, Give it its clean name). That step is refused when it can't.

**Moves (the user's decision).** A move keeps the name and never waits for rekordbox; tidy-up keeps its behaviour,
with no renames. **Discjockey's own moves** (a tidy-up, its undo, a folder rename on disk, a swap out of
`not_lossless/`, a duplicate to `Superseded/`) get rekordbox following them too, with this design's engine and
safety: that is stage E, issue 40, after stage B's live test. **Moves the user makes by hand** in Finder stay with
rekordbox's own (Auto) Relocate, which finds them by name; issue 40 also audits what Discjockey itself does then.

### 7.2 What changes on the screens

**Same track** (To-do upgrade panel, Library details; `upgrade_status`, `cue_text`, `swap_possible`): offered when
§2.2 says eligible. Not offered for a file that isn't AIFF while rekordbox is `unreadable` (the reason line says
why). Problems known only when it runs (open, not analysed, timing, cloud, unclean) come back as the job's problem or
the item's skip reason; the panel can show them earlier through the read-only `rekordbox_preview` (design round).

**The AIFF in-place swap** also writes the text columns (§5.11) and `FileSize` when rekordbox is closed and has the
track; while rekordbox runs it swaps as today and its card keeps the Reload Tag step.

**New track (the bundle).** For the same edit, `add_new` now **renders** the new file shifted by
`k = L − round(d · 44100)` (`d` measured when rekordbox has an analysed track for the old file; 0 for AIFF/WAV or no
track) instead of renaming the parked file; the parked file is held for the undo, as `swap` does. A different or
unknown edit is renamed as today. `report.SHIFTED_EDIT_CHECK` ("fit to within N ms") is no longer used for new checks;
older records keep their words (new checks carry `aligned: true`). For an old file that isn't AIFF, the check stops
advising Relocate if the live test confirms Relocate can't change a file's type.

**The rekordbox check card.** New reasons `repointed` (an upgrade became a new AIFF), `converted` and `renamed`, plus
`swapped` and `added_as_new` as today. **One card per batch**: a batch of one looks like today's card; a bigger one
lists its tracks, gives each step once (analyse again for upgrades, the USB step, Reload Tag only where §5.11 left a
field or the fallback holds), shows "kept your own {field}" where it applies, and offers Undo per track, Undo all and
Done for all.

**Multi-select (new, both lists).** Library's table and To-do's list select one item today (`selected: string |
null` in `LibraryTable.svelte` and `todoModel.ts`). Both get multi-select (⌘-click, ⇧-click, ⌘A within the view or
group), built once in the list blocks and the design language, not per page. To-do selects within one group.

**README.** Upgrades: Same track for any format (rekordbox closed), Upgrade all, Auto-upgrade; drop the New track
claim "Auto Relocate … finds the new file by its name" (the live test settles the words). rekordbox: when Discjockey
changes rekordbox's library, what it changes, the text-column rule, backups, undo, USB sticks. Library: Convert, Give
it its clean name, Make all lossless files AIFF. Settings: Auto-upgrade. When something breaks: `rekordbox restore`.
Console: the new commands (and issue 39's agent docs).

## 8. Words the user sees (binding)

| Where | Text |
|---|---|
| Same track outcome rows (file isn't AIFF) | "Your track keeps its cues, playlists and history" · "Becomes an AIFF file" · "Quit rekordbox before you replace" |
| Reason, rekordbox unreadable | "Same track needs a rekordbox library Discjockey can open" |
| Reason, no rekordbox on this Mac | "No rekordbox on this Mac: the new file is a new track" |
| Problem `rekordbox_open` (any batch) | "rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only while rekordbox is closed." |
| Batch stopped by rekordbox opening | "rekordbox was opened, so Discjockey stopped after {done} of {total}. Quit rekordbox and press Resume." |
| Refused, unreadable | "Discjockey can't open this rekordbox version's library yet, so nothing was changed. Choose New track, or update Discjockey." |
| Refused, not analysed | "rekordbox hasn't analysed this track yet, so Discjockey can't tell exactly where your cues sit. Nothing was changed. Analyse it in rekordbox, quit rekordbox, and try again." |
| Refused, timing | "Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. Analyse the track again in rekordbox and try again." |
| Refused, cloud | "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet. Nothing was changed." |
| Refused, unclean | "rekordbox didn't close normally last time. Open rekordbox, quit it, and try again. Nothing was changed." |
| Refused, changed | "Your rekordbox track changed while Discjockey was working on it, so nothing was changed. Try again." |
| Refused, space | "There isn't enough free space for the new AIFF files ({size} needed, {free} free). Nothing was changed." |
| Refused, rename blocked | "Discjockey can only give this file its new name while it can point your rekordbox track at it, and it can't right now ({reason}). Nothing was changed." |
| Undo, rekordbox open | "Quit rekordbox to undo: Discjockey points your rekordbox track back at your old file only while rekordbox is closed." |
| Undo refused | "This track was moved or removed in rekordbox since the replace, so Discjockey can't put it back safely. Nothing was changed." |
| Result note, no rekordbox track | "This file isn't in your rekordbox collection, so there was nothing to keep there." |
| Result note, kept edit | "Kept your own {title / artist / album / label / comment} in rekordbox." |
| Format sentence (batch sheet, Convert) | "Every file becomes a 16-bit/44.1 kHz AIFF, the format every CDJ plays and every download has; your original stays in Superseded/." |
| Upgrade all, before | "{n} upgrades keep their cues. {m} need your choice and stay." |
| Auto-upgrade switch (Settings, on by default) | "Upgrade automatically when I sync" · Hint "Same-edit upgrades replace your files at the end of a sync while rekordbox is closed; cues stay, and you can undo each one. Also the ones waiting now." |
| Auto-upgrade switch (Setup, starts on) | "Upgrade automatically when I sync" · line "When a lossless version is the same recording, the sync puts it in place of your file; your cues stay. Only while rekordbox is closed; your old file goes to Superseded/." |
| Auto-upgrade, sync summary | "Upgraded {n} tracks; your cues stayed." · "{m} wait for rekordbox to be closed." |
| Auto-upgrade, waiting item | "Waits for rekordbox to be closed: it is upgraded at your next sync, or press Upgrade all." |
| Check text `repointed` | "The better audio is in a new AIFF with a clean name, and your rekordbox track plays it with its cues, playlists and history. In rekordbox, analyse it again so the waveform shows the full sound (lock the beatgrid first if you set it by hand)." |
| Check text `converted` | "Your file is now an AIFF with a clean name and tags, and your rekordbox track plays it with its cues, playlists and history. The sound is the same." |
| Check text `renamed` | "Your file has its clean name now, and your rekordbox track follows it with its cues, playlists and history." |
| Reload Tag step (fallback, §5.11) | "In rekordbox's Collection, select the tracks listed here (⌘-click each), right-click › **Reload Tag**. Don't select all: it replaces every name you changed in rekordbox on the tracks you select." |
| USB step, result 1 | "On a USB stick? Sync it in rekordbox as usual; it picks up the new file." |
| USB step, result 2 | "On a USB stick? In rekordbox's Devices, open the stick's track list, right-click the track › {menu item}, then sync the stick." |
| USB step, result 3 (until the test) | "On a USB stick? The stick still plays the old file. Rebuild the stick in rekordbox before your next gig." |
| Console tip (`discjockey upgrades`) | "Quit rekordbox first: for a file that isn't AIFF, Discjockey points your rekordbox track at the new file." |

The UI agent may shorten panel rows to fit the blocks; each meaning stays, with a reason for every change.

## 9. Screens, and which need a design round

No visuals are designed here. Each list is the states a design round (Opus, with a mockup compared with main) covers.

### 9.1 Stage B: upgrades, batches, the check card, multi-select in To-do

1. **MP3 own file, same edit, rekordbox found:** Same track, recommended, with its outcome rows.
2. **The same, rekordbox unreadable**, and **no rekordbox on this Mac.**
3. **rekordbox open when Replace or Upgrade all is pressed**, and a batch stopped mid-way (Resume).
4. **Upgrade ready group with Upgrade all:** its count, the before-line, mixed groups (some need a choice).
5. **Multi-select in To-do** (a new list-block pattern): several Upgrade ready items selected and their action; several
   check cards selected and Done.
6. **A running batch:** progress, Stop.
7. **The batch check card:** one track and many; "kept your own …"; Undo per track and all; undo with rekordbox open.
8. **New track, same edit, MP3 old file:** the changed check card.

### 9.2 Stage C: Auto-upgrade

A small round (Setup row, Settings row + Sync results; mockup only for the new states): the Setup row, a switch that
starts on with its one line (§8), where it sits among Setup's steps; the Settings switch with its Hint and
InfoTip; the sync's result list with the "Upgraded" section and waiting rows; the summary line; an Upgrade ready item
marked "waits for rekordbox to be closed"; the Sync page's before-start line when rekordbox is open and the switch is on.

### 9.3 Stage D: Convert, Rename, the CDJ group, Make all lossless files AIFF

A full design round:
1. **The To-do group** (working name "Won't play well on CDJs"): the list, one file's panel (why, what converting
   does, the space), Convert all, multi-select.
2. **Library details** for one track (Convert to AIFF; Give it its clean name with old name → new name; the refusal
   when rekordbox can't follow) and for **several selected tracks** (counts per action, one button).
3. **Multi-select in the Library table** (the pattern from 9.1, in the table block).
4. **Make all lossless files AIFF:** where the action sits in the Library view, the before sheet (counts, skipped,
   space, Superseded, format sentence), progress and Stop, Resume, the empty state (nothing to do).
5. **The `converted` and `renamed` check cards**, and the state with no rekordbox.

The CDJ rule is one pure function, `cdj_problem(facts) -> str | None` (for example "AAC at 420 kbps: CDJs play AAC
only up to 320 kbps"): AAC or MP3 above 320 kbps, codecs CDJs don't play (Opus, Vorbis, WMA), 32-bit float WAV. Check
first: Pioneer's format tables for CDJ-3000, CDJ-2000NXS2 and XDJ players, and which of FLAC, ALAC and high rates to
flag.

## 10. Commands (agent-ready)

They follow CLAUDE.md's rule: no prompts (confirmations are flags), `--json` prints one object at the end, a command
that changes things takes the library lock as the hub does. Every action takes the three scopes: **one id, several
ids, or `--all`** (with the action's eligibility, §2.2), plus `--dry-run`, which prints the plan (per track: action,
old → new name, skip reason; totals; space) and changes nothing.

**Exit codes** (the existing `cli.main` codes plus two; issue 39 may renumber globally):

| Code | Meaning |
|---|---|
| 0 | done for every track (or a dry run that would work) |
| 1 | refused or failed, or some tracks skipped or failed (each result says why; `kind` in JSON). JSON `ok` stays `true` when a batch ran to its end with skipped or failed tracks (exit 1); `ok: false` with a `kind` is for a refusal, `busy`, `rekordbox_open` or `stopped` (corrected in stage B) |
| 2 | no music folder or no setup |
| 3 | Discjockey is busy (lock held) |
| 4 | rekordbox is open: nothing done (or the batch stopped there); quit it and run again or resume |
| 5 | stopped (Ctrl-C or a stop): resume with `batch resume <id>` |

**JSON.** Success `{"ok": true, …}`; failure `{"ok": false, "kind": "rekordbox_open" | "refused" | "changed" |
"failed" | "busy" | "stopped", "reason": "<refusal key, §8>", "message": "…", "details": {…}}` (a problem of a batch also carries the batch's fields: `batch`, `state`, `results`, … so the id to resume is there). A batch prints `{"ok", "batch": <id>,
"state", "results": [{"track", "action", "state", "reason", "path", "rekordbox": {"entries": [ids], "kept": [fields]}
| null}], "backup": "<id>" | null}`.

| Command | Does | Stage |
|---|---|---|
| `discjockey rekordbox status [--json]` | `{"state": "ready"\|"none"\|"unreadable", "running", "version", "library", "problem"}`. Read-only, no lock | A |
| `discjockey rekordbox preview <track> [--json]` | Read-only: what Same track, Convert or Rename would do (`file`, `new_file`, `superseded`, `entries: [{id, cues, grid, offset_ms, expected_ms, score, cloud, fields_kept}]`, `eligible: {action: reason\|null}`) | A |
| `discjockey upgrade list [--json]` | The parked upgrades as on To-do: id, names, now/new quality, alignment, eligible for Same track and why not, `auto_refused` | B |
| `discjockey upgrade apply (<track>…\|--all) --way same-track\|new-track [--dry-run] [--json]` | Replace. `--all` only with `same-track`: Upgrade all | B |
| `discjockey upgrade discard <track>… [--json]` | Discard | B |
| `discjockey upgrade undo <track>… [--json]` | Undo the replace of one or several tracks, newest first, as one job (stage B: several tracks, not one) | B |
| `discjockey batch list [--json]` / `batch show <id> [--json]` | Batches with their state and items | B |
| `discjockey batch resume <id> [--json]` / `batch undo <id> [--json]` | Resume a stopped batch; undo all its done tracks | B |
| `discjockey rekordbox checked (<track>…\|--batch <id>) [--json]` | "Done, checked in rekordbox" | B |
| `discjockey rekordbox backups [--json]` / `rekordbox restore <backup> --yes [--json]` | List backups; the whole database back (§5.7; without `--yes`: code 1, `reason: "needs_yes"`; the result lists `missing_after`) | B |
| `discjockey settings auto-upgrade on\|off [--json]` | The Settings switch | C |
| `discjockey` (the sync) | With the switch on, the run's `--json` gains `auto_upgrade: {"batch", "done", "waiting", "refused"}`; `--dry-run` lists what it would upgrade | C |
| `discjockey convert (<track>…\|--all lossless\|cdj) [--in playlist:<name>\|folder:<name>] [--dry-run] [--json]` | Convert to AIFF; `--all lossless` is Make all lossless files AIFF (renames included where only the name is wrong), `--all cdj` the CDJ group | D |
| `discjockey rename (<track>…\|--all) [--in …] [--dry-run] [--json]` | Give it its clean name | D |

`<track>` is the song's key as `upgrade list --json` and the Library's JSON print it. The interactive
`discjockey upgrades` stays; its "s" (swap) becomes Same track for any format. Issue 39 lists the commands in the
agent docs; until then the README's console section does.

## 11. Bridge and contract

Into `docs/hub-bridge-contract.md`, `types.ts`/`contract.ts` and the fake backend, in the same commit:
- **`upgrade(track_ids, mode)`:** takes a list (one id is a list of one); `swap` on a file that isn't AIFF runs
  `convert` from the upgrade; new problem kind `rekordbox_open`; refusals carry `reason`. **`upgrade_all()`** starts
  Upgrade all. Both are jobs with per-item progress events and a batch id in the result.
- **`batch_resume(id)`, `batch_undo(id)`, `rekordbox_checked(track_ids | batch)`:** write jobs.
- **`upgrade_block`:** `swap_possible` means "Same track is possible"; new `swap_how` (`"in_place" | "new_aiff"`),
  `rekordbox: {"state"}` (cached), `auto_refused`.
- **`check_view`:** reasons `repointed`, `converted`, `renamed`; `aligned`; `batch` (id, tracks, kept fields).
- **`rekordbox_status()`:** answers at once, cached by master.db's mtime and size; opens read-only (`mode=ro`), never
  during a write. Check first: a read-only open while rekordbox holds the `-wal`; if it fails, `ready` with "running".
- **`rekordbox_preview(track_id)`:** decodes the old file (1–3 s). Check first: whether reads that decode (the
  spectrum) run inline or as a job; do the same.
- **`set_auto_upgrade(on)`** (stage C); **`convert(track_ids)`, `rename(track_ids)`, `aiff_plan(scope)`** (read) and
  **`make_aiff(scope)`** (stage D).
- **Views stay pure:** `api.py` reads the rekordbox status and passes it in. **Services:** `svc.rekordbox` (place,
  `running()`, `open()`) is injected, so tests and the fake never touch a real library.

## 12. Testing, offline

**Helpers** (`tests/rekordbox_helpers.py`): `make_master(tmp, rows, key=KEY, version="6000")` builds a SQLCipher
database with the same `PRAGMA key` and WAL mode, with the tables and columns we touch (`djmdContent` with its real 78
column names, `djmdArtist`, `djmdAlbum`, `djmdLabel`, `djmdCue`, `contentCue`, `contentFile`, `djmdProperty`,
`agentRegistry`, `djmdSongPlaylist`, `djmdSongHistory`, `djmdSongMyTag`) and rows with cues, playlists and history;
`make_anlz(path, tags)` writes PMAI files with `PPTH`, `PQTZ`, `PWV3` and an unknown tag; `pwv3_from(audio, sr,
extra_s)` makes heights as rekordbox's timeline would show them.

**Audio fixtures:** M4A made in the test with the bundled ffmpeg's `aac` encoder; two small synthetic click-track
MP3s (LAME-tagged and untagged) committed under `tests/fixtures/`, made once by a documented script (the bundled
ffmpeg has no MP3 encoder, issue 19); FLAC and 24-bit AIFF made in the test. No real music, no real library;
`DISCJOCKEY_REKORDBOX` points at a temp folder in every test.

**Behaviours to pin:**
- **Guards:** wrong key, `DBVersion` or a missing column (lookup tables included) → `unreadable`; a leftover `-wal`
  → "unclean"; rekordbox running at the start → `rekordbox_open`, nothing changed; running at a commit → that track
  rolled back, the batch `stopped`, the rest `planned`; a cloud row → that track skipped; another `DBID` in recovery
  → rekordbox untouched.
- **Lookup:** exact, NFC/NFD and case variants; deleted rows ignored; several rows all repointed; none → converted
  without a database write.
- **The write:** exactly §5.5's columns change, every other column and table byte-equal (whole-row compare);
  `OrgFolderPath` follows only when equal; `localUpdateCount` up once per transaction; `updated_at` format.
- **Text columns:** a field equal to the old tag gets the clean value; a field the user edited stays and is reported
  "kept"; find reuses an existing artist/album/label row, create makes one with the scheme, existing rows are never
  changed; genre, year, rating, colour, My Tags untouched; undo restores only fields still holding our value.
- **The ANLZ splice:** `PPTH` changed, every other tag byte-identical, lengths right, `contentFile` MD5 and size.
- **Timing:** a synthetic shift recovered within ±5 samples and snapped; score below 0.90 or off-set → "timing"; no
  `PWV3` with cues on an MP3 → "not analysed"; no `PWV3`, no cues, no grid → plain conversion; the AIFF's clicks at
  the rekordbox-timeline positions to ±1 sample (M4A made in the test, MP3 from the fixtures).
- **The step:** the `expected_stem` name with an ID only when taken; the old file mirrored into `Superseded/` under its
  own name; tags exactly `write_tags`' frames plus TCON/TYER; a 24-bit 96 kHz FLAC becomes 16/44.1; an AIFF 16/44.1
  with wrong tags is copied sample-identical with new tags; `cdj_cover` makes a 3000 px PNG a ≤ 600 px, ≤ 500 KB JPEG
  and leaves a 600 px JPEG byte-identical; a new name it can't repoint → refused; Rename changes only the path
  columns, `PPTH` and `contentFile`; the file row keeps the old quality and `placed_by='app'`; nothing written
  outside `move_path`; free space checked.
- **Eligibility (pure):** every row of §2.2's table, both ways; `tags_clean`; `cdj_problem`.
- **Batches:** one backup for N tracks; one `rekordbox.lock`; per-item skip goes on; Stop between items → `stopped`;
  Resume does only the planned ones and re-checks them; batch undo newest first, a refused track stays listed;
  `rekordbox checked --batch` ends every undo of it.
- **Auto-upgrade:** a missing `auto_upgrade` key reads as on; off → the sync changes no file; on → only eligible upgrades, at the run's end, one batch;
  rekordbox running → nothing done, all waiting; `auto_refused` skipped until the ANLZ mtime changes; a dry run
  changes nothing; the run's JSON block.
- **Crash at every step (1–7):** before the commit, recovery restores exactly the old state (files, ANLZ, database,
  text columns, no created rows left referenced); after it, recovery finishes; rekordbox open during an ANLZ rollback
  → waits; the interrupted batch is `stopped`.
- **Undo:** identity and file facts restored; later cue, rating and title edits kept; `FolderPath` changed by the user
  → refused; rekordbox open → `rekordbox_open`; `PPTH` left alone when re-analysed.
- **New track:** a same-edit add renders a shifted file (AIFF old file: `L`; MP3 old file with a track: `L − d`); a
  different edit is renamed as today; old checks keep their words.
- **Commands:** exit codes 0–5, the JSON shapes, one id / several / `--all` give the same per-track results as the
  bridge, `--dry-run` changes nothing, `restore` without `--yes` refuses.
- **App:** the self-test opens a keyed in-memory database.

## 13. Staging

**Stage A: read side, plus New track lined up.** No rekordbox write. `discjockey/rekordbox/` read side (locate, key,
guards, `entries_for`, ANLZ reading, timing), `eligible.py`, the `sqlcipher3-wheels` dependency and its self-test
step, `audio.render_aiff`, `add_new` shifted with its words and the README's corrected New track text, the commands
`rekordbox status` and `preview`. Acceptance: on the maintainer's Mac, `status` and `preview` on a few real tracks
agree with the research numbers (read-only, run by the maintainer).

**Stage B: write side, batches, Same track for any format, Upgrade all (wish B).** The `convert` op with backup,
recovery and undo; the text columns (§5.11); `aiff_batches`/`aiff_items`, Stop/Resume, batch undo; Same track for any
format; Upgrade all; multi-select in To-do; the batch check card; the commands `upgrade …`, `batch …`,
`rekordbox checked/backups/restore`; the UI after §9.1's round. Merge into main once CI and verify are green, then
**the live test before any release**.

**The live test** (the user, about 30 minutes, on throwaway tracks only). A rekordbox backup first (File › Library ›
Backup), and the agent copies `~/Library/Pioneer/rekordbox/`. Synthetic 120 BPM click tracks: one LAME MP3, one
48 kHz M4A, one FLAC, one AIFF with a messy name; each gets hot cues on clicks, a playlist (one track in two), a play,
an edited title on one, and an export to a spare stick. Then, with rekordbox closed, one `upgrade apply`/`convert`
batch over them. Checks:
1. rekordbox shows AIFF/44.1/16, plays it, cues and grid on the clicks (also the 48 kHz one and the FLAC).
2. Reopening rekordbox keeps all of it; `PVBR` does no harm to seeking; re-analysis with the grid locked refreshes the
   waveform.
3. The text columns: the clean title, artist, album show; the edited title stayed; created artist/album rows sort and
   search normally. Does rekordbox write an info edit into the file's tags (§5.11)? Reload Tag's exact menu name, and
   which fields it replaces.
4. Batch undo brings back the old files with their cues.
5. USB (§6): plain sync first, then the device's own track list, else rebuild.
6. Manual Relocate `.mp3` → `.aiff` works or not (the README's words); whether rekordbox follows a file moved into
   `Superseded/` by itself (the README's bought-copy claim).
7. rekordboxAgent leaves `master.db` alone while rekordbox is closed; the `contentFile` update is accepted.

If 1 fails for 48 kHz, own 48 kHz files render at their own rate and the upgrade is resampled to it. If 7's
`contentFile` fails, §5.5's fallback; if 3 fails, §5.11's fallback. After the test passes: release on the user's go.

**Stage C: Auto-upgrade on sync (wish A).** After the live test, because it writes without a click. The Setup
and Settings switch (on by default), the run's last phase, `auto_refused`, the summary and result section, the run's JSON block, the invariant
text in CLAUDE.md, the README; §9.2's small round.

**Stage D: Convert, Give it its clean name, the CDJ group, Make all lossless files AIFF (wish C).** §9.3's full
round, then `convert`, `rename`, `aiff_plan`, `make_aiff`, multi-select in the Library table, the CDJ group, the
commands, the new "moving never renames" text in CLAUDE.md.

**Stage E (issue 40, after stage B's live test): rekordbox follows Discjockey's own moves** (§7.1), with its own
design round. Moves the user makes by hand stay with rekordbox's Relocate.

## 14. Check first (collected)

- ffmpeg's untrimmed decode flags for MP3 and MP4 with the bundled build (§3.2).
- The tag readers for own files (§3.5); a rescan not re-checking a row the step wrote (§2.1).
- The passphrase form of the key; PyInstaller, licences and signing for `sqlcipher3` (§5.2).
- `rb_LocalFolderPath` on rows where it isn't NULL (§5.5).
- rekordbox's scheme for new `djmdArtist`/`djmdAlbum`/`djmdLabel` rows, and whether unused created rows are harmless
  (§5.11, §5.9).
- `recover_pending`'s waits for a "rekordbox is open" wait (§5.8).
- A read-only open while rekordbox runs in WAL mode; inline vs job for `rekordbox_preview` (§11).
- Pioneer's CDJ format tables for `cdj_problem` (§9.3); Pioneer's limit for embedded artwork (§3.5).
- Whether the import cleans own songs' names like `titles.split_title` (§4).
- Live test: rekordbox writing edits into file tags, Reload Tag's name and fields (§5.11); USB (§6).

## 15. Questions for the user

None open. The answers of 2026-11-07 are built in: the CDJ group with Convert to AIFF (§9.3), rekordbox following
Discjockey's own moves as issue 40 (stage E), every file convertible to AIFF, lossless ones included (§2.2, §2.4),
the text columns written with the user's edits kept (§5.11), Give it its clean name (§7.1), and the wishes A, B, C
and the batch rule (§1, §2).
