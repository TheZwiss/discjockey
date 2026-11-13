# rekordbox stage D: Convert, Give it its clean name, the CDJ group, Make all lossless files AIFF (issue 33): plan

Status: plan, 2026-11-13. Design: `docs/2026-11-07-rekordbox-repoint-design.md` (the design). This plan builds its
§13 stage D (wish C): §2.1 Convert to AIFF and the `rename` step, §2.2's Convert and Rename rows, §2.4 Make all
lossless files AIFF, §7.1, §9.3's states 1–5 and the CDJ rule, §10's `convert` / `rename` rows, §11's `convert`,
`rename`, `aiff_plan`, `make_aiff`, and the "moving never renames" text. It stands on stages A–C (merged into `main`,
29e707f). Branch `feat/rekordbox-d` from `main`; group worktrees `.claude/worktrees/rb-d-<group>` on
`feat/rekordbox-d-<group>`, each merged into the stage branch when its checks are green. No full mockup round (the
user's rule): §6 gives each new UI state its direction; two new blocks are named as single-component mockup
candidates (§6.0).

**Stage D in one line:** a file of the user's own becomes a clean 16-bit/44.1 kHz AIFF (Convert to AIFF), or only gets
its clean name (Give it its clean name), with every rekordbox track of it pointed at the new file while rekordbox is
closed, as one AIFF batch (backup, journal, Stop/Resume, undo per track and batch, one check card), started on one
file, a selection in the Library or To-do, all lossless files of a Library view, or the new To-do group of files CDJs
won't play; every one of those has its console command.

**Not in stage D:** rekordbox following Discjockey's own moves (stage E, issue 40); a write to a USB stick; Reload Tag
words beyond stage B's; anything for users updating from an older version (no notes, no migration words; the new
file facts are filled silently, §0.3); a release (the user's live test comes first, §9).

---

## 0. Decisions this plan adds to the design (with reasons)

1. **One rule picks the action per file: "make it a clean AIFF".** `eligible.aiff_action(entry, facts, rb, timing,
   present, clean_path) -> tuple[str, Verdict]`: Convert when `eligible.convert` is eligible, else Rename when
   `eligible.rename` is, else the more telling skip (Convert's, except `clean_aiff`, which yields Rename's answer).
   Every "all" scope, every selection, the hub's `convert(track_ids)` and `discjockey convert <track>` use it; only
   `rename(...)` and `discjockey rename` ask Rename alone. Reason: design §2.4 counts "clean name only" inside Make all
   lossless files AIFF; the user never has to know which of the two a file needs.
2. **A parked upgrade wins.** `eligible.convert` and `rename` skip a track whose song has a parked upgrade, new
   reason `upgrade_waits` ("A better version is waiting: Same track makes it an AIFF."), and the CDJ group leaves such
   a track to Upgrade ready. Reason: converting the old file first costs a render and space for nothing, and two
   To-do groups would offer two answers for one file.
3. **The file's own facts are stored (schema V8).** `files` gains `file_codec TEXT`, `file_rate INTEGER`,
   `file_bits INTEGER`, `file_kbps INTEGER`: what the file at `path` is (not `source_format`, which says what it was
   made from and stays the old file's after a Convert, design §2.1). They reach the snapshot as read-only entry keys
   (like `placed_by`), written by: the import's pass 1 (it probes already), `ops.add_bought_file`, the convert and
   rename steps (known values), and a **facts fill** for own-file rows whose facts are NULL (rows from before V8, and
   a row whose content key changed: the scan clears its facts). Downloads never need them (their files are the
   library format; the CDJ rule and the plans look only at own files). Reason: the CDJ rule needs the rate and bit
   depth (a 24/192 FLAC from a shop is refused by every CDJ) and To-do must count without probing thousands of files.
   Check first: what starts `importer.run_import` without the user; the fill runs as the import's first pass when
   own rows lack facts, and, if no automatic start exists, from the hub's start-up recovery path under the library
   lock (ffprobe about 30 ms a file, resumable because a filled row is done).
4. **The CDJ rule flags only what the club players refuse** (§1.4): the formats and limits of the CDJ-3000 and the
   CDJ-2000NXS2 (the two players in clubs). FLAC, ALAC and 88.2/96 kHz files play on both and are **not** flagged;
   players that stop at 48 kHz or lack FLAC/ALAC (XDJ-RX3, XDJ-XZ, XDJ-700, CDJ-2000NXS) are served by Make all
   lossless files AIFF, which the README names for them. Reason: the group is "won't play", not "could be tidier";
   flagging every FLAC would put most of a lossless collection into To-do.
5. **Make all lossless files AIFF opens in the Library inspector, not a modal sheet.** The header's "Make AIFF…"
   opens the inspector on the view's plan; the same panel shows a selection of two or more rows. Reason: a batch over
   hundreds of files runs for many minutes; a modal would lock the window that long, and the stage B batch panel
   already lives in a side panel with its phases (decide, running, ended).
6. **"All" means the view, not the filter or the search.** Make all covers every file of the view on screen (All
   tracks, Not in a playlist, a playlist, a folder). A narrower set is a selection: ⌘A in the table selects the rows
   on screen. Reason: design §2.4 ("a playlist or folder view means its files"); the quality filter is about sound,
   and a search is a passing narrowing, so an "all" that changed with them would surprise.
7. **The plan is one read, `aiff_plan`, for the panel, the commands' `--dry-run` and the job's start.** It works from
   the snapshot and the stored facts, reads the tags (mutagen, milliseconds) only of own AIFF 16/44.1 files (whether
   they need new tags or only a name), opens rekordbox's library once read-only for cloud flags when it is `ready`,
   and never decodes: not analysed and timing are found by the run (as Upgrade all's count). A tag read is cached in
   memory by `(path, size, mtime_ns)` on the hub so reopening the panel is instant. Reason: design §1 ("counts on
   buttons are its result"), with a cost the panel can wait for behind a skeleton.
8. **Lossy files join only by name or by the CDJ group.** Make all's set is own files whose `file_codec` is
   lossless (`pcm_*`, `flac`, `alac`). A selection may hold lossy files: they are converted, and the panel says what
   it costs (§3). Reason: design §2.2.
9. **Convert from the file itself reuses the `convert` op.** `convert.convert_file` is `same_track`'s sibling: source
   = the current file, shift `k = −round(d · 44100)` (design §3.1), tags from `eligible.expected_tags` plus the
   cover, check reason `converted`, no parked download to hold. The journal entry gets `source: "file" | "upgrade"`;
   recovery and `undo_convert` treat a missing `held` as "nothing to hand back". Reason: one op, one recovery, one
   undo (design §2.1 "one engine step `convert`").
10. **`rename` is its own module and op** (`discjockey/rename.py`, ops `rename` / `rename_undo`): `move_path(old →
    new)` in the same folder, then rekordbox's identity columns, `PPTH` and `contentFile` in one transaction; audio,
    tags and file facts unchanged; check reason `renamed`. Order: journal → backup → move (`placed`) → rekordbox
    commit (`committed`) → end. Recovery decides by the rows' `FolderPath` as `convert` does (`convert`'s side
    helpers become public: `side_of`, `tracks_at`): old path → the file moves back (no rekordbox write, so it never
    waits for rekordbox); new path → finish; neither → help. Reason: design §7.1; `convert.py` (881 lines) would pass
    1300 with it.
11. **The cover of a converted file**: the song record's (`image_url`, fetched as downloads fetch it) when the song is
    linked to a playlist song, else the old file's embedded picture; either through the new `audio.cdj_cover`
    (baseline JPEG, at most 600 × 600 px and 500 KB; downloads go through it too, design §3.5). No official Pioneer
    limit for embedded artwork was found (§1.4 sources); the design's caps stay. A fetch that fails falls back to the
    old file's picture. Reason: design §3.5; a batch must not fail on a cover.
12. **Own songs' names are cleaned at import.** `identify.own_name` runs a title tag that holds "Artist - Title …"
    (with an empty artist tag) and pure tag brackets ("[FREE DL]") through `titles.split_title`'s rules, so new
    imports get names a clean file name can be made from. Existing records keep their names (they are what the
    Library shows; the clean name follows them). Check first: `split_title` with an empty uploader keeps the artist
    empty rather than inventing one. Reason: design §4 "fixed where the record is made, not in this step".
13. **Batch kind and scope.** `batches.start` derives `kind` from the actions (`same_track` only → `upgrade`,
    `convert`/`rename` only → `convert`, both → `mixed`). `started_by`: `user` (one file, a selection, `discjockey
    convert <track>`, `rename …`), `make_aiff` (Make all, `convert --all lossless`), `cdj_all` (Convert all, `convert
    --all cdj`). `scope` records where it started: `library:<view>[:<key>]`, `library:selection`, `todo:cdj`,
    `todo:selection`, `console`. A stopped convert batch offers Resume where it started: Library's header for
    `library:*`, To-do's CDJ group head for `todo:*`, `batch resume` always. Reason: design §2.4 ("Resume in the same
    place"); the schema already allows these starters and kinds.
14. **A selection in the Library holds any rows with a file**; downloads and clean files are listed as "left as they
    are" with their reason. Rows without a file (a playlist's waiting songs) can't join a multi-selection. Reason: the
    user selects by eye; the panel says what applies.
15. **Single-file Convert / Rename are batches of one** (`alone=True`, as stage B's single Replace): rekordbox open or
    `busy` before anything ran closes the batch instead of leaving a Resume.

---

## 1. Architecture (binding interfaces)

### 1.1 Modules

| Module | Change | Group |
|---|---|---|
| `db.py` | V8 step: the four `file_*` columns; `set_file_facts(conn, file_id, FileAudio)`, `files_without_facts(conn) -> list[(file_id, path)]` (own rows only); the scan's write clears the four when a row's content key changes; snapshot adds them as read-only keys | D1 |
| `models.py` | `FileAudio(codec, rate, bits, kbps)` (frozen); `OwnFacts` gains `audio: FileAudio` | D1 |
| `importer.py` | pass 1 stores `FileAudio`; a `facts` pass first (rows from `files_without_facts`); `own_name` cleaning lives in `identify.py` | D1 |
| `identify.py` | `own_name` cleaning (§0.12) | D1 |
| `ops.py` | `add_bought_file` writes the bought file's facts | D1 |
| `cdj.py` (new, pure) | `cdj_problem(audio: FileAudio, ext: str) -> CdjProblem \| None` (§1.4) | D1 |
| `audio.py` | `cdj_cover(data) -> bytes \| None`; `write_tags` and `copy_tags` callers pass covers through it; `embedded_cover(path) -> bytes \| None` (any format) | D1 |
| `rekordbox/eligible.py` | `upgrade_waits` in `REASONS` and in `convert`/`rename`; `aiff_action` (§0.1); `is_lossless_codec(codec)` | D1 |
| `convert.py` | `convert_file`, the `source` field, `converted` check, public `side_of` / `tracks_at`, `undo_convert` without `held` | D2 |
| `rename.py` (new) | `rename_file`, `recover_rename`, `undo_rename`, `recover_rename_undo` | D3 |
| `library.py` | `recover_pending` dispatches `rename` / `rename_undo`; their path keys reserved (`RENAME_PATH_KEYS`) | D3 |
| `upgrades.py` | `undo` dispatches an undo record of kind `rename`; `can_undo` holds for `converted` / `renamed` checks | D2, D3 |
| `report.py` | `check_text` for `converted` / `renamed` (§3), the USB step only for `converted` with rekordbox tracks | D2, D3 |
| `batches.py` | `RUNNABLE = ("same_track", "convert", "rename")`, kind derivation, `_item` dispatch, `_needs_write` for convert/rename, words for the new reason | D4 |
| `aiff_plan.py` (new) | `plan(paths, state, scope, *, rb, tags=…) -> AiffPlan` and its pure core (§1.3) | D4 |
| `batch_cmd.py` / `convert_cmd.py` (new if `batch_cmd.py` would pass ~900 lines: check first) | `convert`, `rename` (§2) | D5 |
| `hub/api.py`, `hub/views.py` | §4 | D6 |

### 1.2 The steps

```
convert.convert_file(paths, state, track_id, *, session, now=datetime.now, batch=None) -> Result
rename.rename_file(paths, state, track_id, *, session, now=datetime.now, batch=None) -> Result
```
Both raise `convert.Skipped(reason, message, detail)` (nothing written), `RekordboxOpened` (nothing written; the batch
stops) or `UpgradeProblem` (a failure, nothing written, or recovery's words), exactly as `convert.same_track`.

- **`convert_file`**: re-reads the facts (`audio.file_facts`) and asks `eligible.convert` with them and the session's
  status; `timeline_offset` on the session's open library (no track → `d = 0` and no database part; PCM/FLAC/ALAC with
  no `PWV3` → `d = 0`; MP3/M4A with cues and no `PWV3` → `not_analysed`; disagreement → `timing`; cloud → `cloud`);
  `check_space`; names: `NameReserver.choose(folder, expected_stem(artist, title), ".aiff", track_id)` with the old
  file's own name counted free (`replacement_dir` for the folder rule, design §4); render `audio.render_aiff(old,
  staged, −round(d · 44100))` (16/44.1 input copies its samples: test it); tags `write_tags(**expected_tags,
  cover=…)` plus TCON/TDRC carried over (design §3.5; the user's own comment kept); then design §5.8 steps 2–7 as
  `same_track` does. Step 7: the entry's `path` is the new file; `status`, `source`, `source_format`,
  `source_kbps`, `cutoff_hz` stay (design §2.1); the file row gets `placed_by = 'app'` and `FileAudio("pcm_s16be",
  44100, 16, None)`; the check `{reason: "converted", since, batch, rekordbox: {entries, kept} | null, undo}`.
- **`rename_file`**: `eligible.rename` with fresh facts (`clean_aiff` must hold: tags right, 16/44.1); the clean path
  from the reserver (own name free); a `RowChange` with identity columns only (new `write.rename_change(entry,
  new_path)`: `FolderPath`, `FileNameL`, `OrgFolderPath` by the §5.5 rule, no facts, no text) plus `PPTH` splices and
  `contentFile`; refused with `rename_blocked` (design §8 words, `{reason}` the cause's short words) when the file has
  a rekordbox track and the library is unreadable, a row is cloud, or rekordbox runs. A file with no rekordbox track is
  only moved. Check `{reason: "renamed", since, batch, rekordbox, undo}`.
- **Undo** (`upgrades.undo` → `undo_convert` / `undo_rename`): design §5.9 for both. `undo_rename` moves the file back
  to its old name (refused `in_the_way` when another file took it), rekordbox's identity columns and `PPTH` back
  where they still hold what was written (else `relocated`, nothing changed).

### 1.3 `aiff_plan`

```
Scope = {"kind": "tracks", "tracks": [key, …]}
      | {"kind": "lossless", "view": "all"|"unlisted"|"playlist"|"folder", "key": str | None}
      | {"kind": "cdj"}
plan(paths, state, scope, *, rb: Status, entries: Callable | None, tags: Callable[[Path], FileFacts]) -> AiffPlan
```
`AiffPlan.to_dict()` (the bridge's and the dry run's one shape):
```
{"scope": {..., "label": "All tracks" | "<playlist>" | "<folder>" | "Selection" | "Won't play well on CDJs"},
 "items":   [{"track", "name", "action": "convert"|"rename", "kind", "from", "path", "new_path", "superseded",
              "bytes", "cdj": {"short", "words"} | null}],
 "skipped": [{"track", "name", "reason", "message"}],
 "kinds":   [{"kind", "label", "n"}],            # in KIND_ORDER, only n > 0
 "lossy": int, "total": int,
 "space":   [{"drive", "needed", "free", "enough"}], "superseded_bytes": int,
 "rekordbox": {"state", "running", "needs_closed": bool}}
```
`kind`: `flac`, `wav`, `alac`, `aiff_hires` (an AIFF that isn't 16/44.1), `tags` (an AIFF 16/44.1 with wrong tags),
`name` (Rename), or the lossy codec (`mp3`, `aac`, `opus`, `vorbis`, …). Which files: `tracks` the given ones;
`lossless` the view's own files (the same membership `views.library` lists, without filter or search) with a lossless
`file_codec`; `cdj` the CDJ group's items (§1.5). Files with nothing to do (clean AIFF with its name, a download) are
`skipped` only in a `tracks` scope (the user picked them); in the "all" scopes they are left out. `bytes`:
`convert.needed_bytes(duration_s, 2)` for a Convert, 0 for a Rename. `space` per drive as `convert.space_needed`
counts it (the `.tmp` drive, plus the target drive when another). `needs_closed`: some item's file has a rekordbox
track (from `entries`, one read open; with the library `none` false, `unreadable` true for every file not AIFF).
The job (`make_aiff`, `convert`) plans again at its start and records the plan's items as the batch; the panel's
numbers are a preview.

### 1.4 The CDJ rule (`cdj.py`, pure)

`cdj_problem(audio, ext) -> CdjProblem(reason, short, words) | None`, first match wins (`audio` the stored facts; a
missing value never matches its rule):

| Reason | When | `short` (To-do row) | `words` (panel, Library details) |
|---|---|---|---|
| `format` | codec not in `mp3`, `aac`, `pcm_s16*/s24*`, `flac`, `alac` (Opus, Vorbis, WMA, AC-3, …) | "{Name} · CDJs don't play it" | "CDJs don't play {Name} files." |
| `bitrate` | `mp3` or `aac` above 320 kbps | "{MP3/AAC} {kbps} kbps · CDJs stop at 320" | "{MP3/AAC} at {kbps} kbps: CDJs play {MP3/AAC} only up to 320 kbps, so it may not load or may stutter." |
| `bits` | PCM or FLAC/ALAC not 16- or 24-bit (32-bit float or integer, 8-bit) | "{Name} {32-bit float} · CDJs play 16/24-bit" | "{Name} {32-bit float}: CDJs play only 16- and 24-bit files." |
| `rate_high` | lossless above 96 kHz; MP3/AAC above 48 kHz | "{Name} {192} kHz · CDJs stop at {96} kHz" | "{Name} at {192} kHz: CDJs play {Name} only up to {96} kHz." |
| `rate_low` | lossless below 44.1 kHz | "{Name} {22.05} kHz · CDJs need 44.1 kHz" | "{Name} at {22.05} kHz: CDJs play {Name} from 44.1 kHz." |

`{Name}` is `views.FORMAT_NAMES` / `CONTAINER_NAMES` (WAV, AIFF, FLAC, ALAC, MP3, AAC, Opus, Vorbis). Sources
(checked 2026-11-13): Pioneer DJ's CDJ-3000 specifications (MP3, AAC, WAV, AIFF, FLAC, ALAC:
https://www.pioneerdj.com/en-us/product/player/cdj-3000/white/specifications/), AlphaTheta's CDJ-3000X page (same
list: https://www.alphatheta.com/en/product/dj-player/cdj-3000x/black/), the CDJ-2000NXS2 operating instructions,
"Playable music file formats" (MP3 32–320 kbps at 32/44.1/48 kHz; AAC 16–320 kbps up to 48 kHz; WAV and AIFF 16/24-bit
at 44.1–96 kHz; ALAC and FLAC 16/24-bit at 44.1–96 kHz: https://docs.pioneerdj.com/Manuals/CDJ_2000NXS2_DRI1290A_manual/
page 7, mirrored at https://manualslib.com/manual/1196325/Pioneer-Cdj-2000nxs2.html?page=7), the XDJ-RX3
specifications (MP3, AAC, WAV, AIFF, FLAC; no ALAC: https://www.pioneerdj.com/en/product/all-in-one-system/xdj-rx3/black/specifications/).
Check first (D1): the CDJ-3000 manual's own table (AlphaTheta support) if it can be read; if it states other
limits than the NXS2's, the stricter of the two holds. Not flagged, with the reason in §0.4: FLAC, ALAC, 88.2/96 kHz,
VBR, a `WAVE_FORMAT_EXTENSIBLE` header (ffprobe can't tell it cheaply; noted in `docs/issues.md`).

### 1.5 The CDJ group

`views.todo` gains the group `("cdj", "Won't play well on CDJs", "CDJs refuse or stutter on these files")`, after
Upgrade ready. An item: an own file (`source == "manual"`) with a file, `cdj_problem` not None and no parked upgrade
(§0.2); hidden as any item. It is the one place To-do lists an own file outside Upgrade ready, questions and
duplicates (D8's rule amended: a problem Discjockey found, the user's answer to design §15). Item fields as any row
plus `cdj: {reason, short, words}` and `aiff: <aiff_action reason | null>` (the quick answer: Convert with the stored
facts, `timing` None); `detail` is `short`. The group carries `all: {n, k}` (n Convert can run now; k waits: drive
away, no name, rekordbox unreadable) and `stopped: {batch_id, left} | null` (the newest stopped batch with
`scope` `todo:*`).

### 1.6 Batches (D4)

`_item` per action: `same_track` as today; `convert`: `eligible.aiff_action` with fresh facts must still say
`convert`, then `convert.convert_file`; `rename`: `rename.rename_file`. An item whose answer changed (a Convert that
became a Rename because the user re-tagged meanwhile) is skipped with the new answer's reason, never switched
silently. `_needs_write`: a convert or rename item needs a write when its file has a rekordbox track (any format; with
no readable view: every such item). Operation log names `aiff_convert` / `aiff_rename`. `undo` and `checked` work
unchanged by check record.

---

## 2. Commands (D5; design §10)

| Command | Does |
|---|---|
| `discjockey convert (<track>…\|--all lossless\|--all cdj) [--in playlist:<name>\|folder:<path>\|unlisted] [--dry-run] [--json]` | Make each file a clean AIFF (§0.1). `--all lossless` is Make all lossless files AIFF over the whole library or `--in`'s view (`started_by` `make_aiff`); `--all cdj` the CDJ group (`cdj_all`; `--in` refused there, `bad_args`); tracks: `user` |
| `discjockey rename (<track>…\|--all) [--in …] [--dry-run] [--json]` | Give it its clean name only (`--all`: every own clean AIFF whose name isn't clean; `user`) |

- `--dry-run` prints `aiff_plan` (human: one line per item "FLAC → AIFF  Artist - Title  →  Artist - Title.aiff",
  the skipped with their words, the kinds, space per drive); `--json`: `{"ok": true, "dry_run": true, "plan":
  AiffPlan}`. Nothing is locked or written.
- A run: lock, `recover_pending`, plan, `batches.start(items, started_by, scope="console")`, `batches.run`; output and
  exit codes exactly as `upgrade apply` (`_finish`; 0–5; a single named track is `alone`). Nothing to do → exit 1,
  `kind: "refused"`, `reason: "nothing_to_do"`, message "Nothing to change: these are clean AIFFs already." (or the
  one track's own skip words).
- `batch list | show | resume | undo` and `rekordbox checked --batch` work for these batches unchanged (pinned).
- Progress on stderr: "Converting 3 of 52: Artist - Title" / "Renaming …".
- CONTRIBUTING.md > "Commands for scripts and agents" lists both, with the plan's JSON; the CDJ group's state for an
  agent is `convert --all cdj --dry-run --json`, a view's Make-all state `convert --all lossless --in … --dry-run`.

---

## 3. Words (binding; design §8 plus what D adds)

| Where | Text |
|---|---|
| To-do group | "Won't play well on CDJs" · hint "CDJs refuse or stutter on these files" |
| CDJ rule | §1.4's `short` and `words` |
| To-do group head | "Convert all · {n}"; while a `todo:*` batch is stopped "Resume · {k} left" (stage B's form) |
| Library header button | "Make AIFF…" · tip "Make all lossless files AIFF"; while a `library:*` batch is stopped "Resume · {k} left" |
| Panel, view | title "Make all lossless files AIFF" · sub "in {view label}" |
| Panel, selection | title "{n} tracks selected" · sub "{k} can become clean AIFF" (0: "Nothing to change") |
| Panel, CDJ (several or all) | title "{n} files for CDJs" · sub "Convert all · {k}" when it is the whole group |
| Kind labels | "FLAC → AIFF" · "WAV → AIFF" · "ALAC → AIFF" · "AIFF 24-bit or above 44.1 kHz → 16-bit" · "New tags" · "Clean name only" · "{MP3/AAC/Opus…} → AIFF" |
| Format sentence | design §8's, word for word |
| Lossy note (info NoteCard) | "{n} of these are lossy: an AIFF made from them sounds the same and takes 5–10 times the space." (1: "1 of these is lossy: …") |
| Space rows | "Needs {size} on {drive} · {free} free"; short (problem Hint) "Not enough space on {drive}: {size} needed, {free} free"; "Your originals ({size}) go to Superseded/ on the same drive." |
| rekordbox outcome rows | "Your tracks keep their cues, playlists and history" (one track: design §8's) · "Quit rekordbox before you start" while it runs (warn NoteCard: design §8 `rekordbox_open` problem words) |
| Skipped list | header "Left as they are · {n}"; each row its reason's words (`batches._words`) |
| `upgrade_waits` | "A better version is waiting: Same track makes it an AIFF." |
| `downloaded` (selection) | "Discjockey downloaded it: it is a clean AIFF already." |
| `clean_aiff` / `named_already` | "A clean AIFF with its clean name already." |
| Empty, view | "Every lossless file here is a clean AIFF already." |
| Empty, CDJ group gone | (no group; To-do's own empty states) |
| Buttons | single: "Convert to AIFF" · "Give it its clean name"; several: "Make {k} files AIFF" ("Make 1 file AIFF"); CDJ: "Convert {k} to AIFF" |
| Ended | "Made {n} files AIFF" · "{k} left as they are" · stopped: design §8's batch-stopped words |
| Library details card | label "AIFF"; `KeyValue` NOW "{format line}" · BECOMES "AIFF · 16-bit · 44.1 kHz" · NAME "{old} → {new}" · SPACE "+{size}; your original goes to Superseded/" (Rename: NAME only, no SPACE) |
| Rename blocked | design §8's, `{reason}`: "rekordbox is open" / "rekordbox's library can't be opened" / "the track is in Cloud Library Sync" |
| Check texts | design §8's `converted` and `renamed`; no rekordbox track: design §8's "Result note, no rekordbox track" |
| To-do check line (`check_status`) | `converted`: "an AIFF now: nothing to redo" / without rekordbox "an AIFF now, not in rekordbox"; `renamed`: "clean name now" |
| Batch row detail (To-do) | "{day} · Made AIFF" (kind `convert`); Same track and Auto-upgrade as today |
| README, XDJ note | "Playing on XDJ players (XDJ-RX3, XDJ-XZ, XDJ-700) or an older CDJ? They stop at 48 kHz and some don't play FLAC or ALAC: Make all lossless files AIFF makes every lossless file one they play." |

The UI builder may shorten a panel row to fit its block; each meaning stays, with a reason in the commit.

---

## 4. Bridge and contract (D6 Python, D7 TypeScript + fake; design §11)

- **`track()`** gains `aiff`: `{action: "convert"|"rename"|null, why_not: reason|null, kind, from, to, name_now,
  new_name, bytes, lossy: bool, cdj: {reason, short, words}|null}` or `null` (no file, a download, a parked upgrade:
  the upgrade decision stands). One `file_facts` read of the one file (the api already checks it exists) and the
  reserver; rekordbox from the cached status.
- **`library()`**: answer field `aiff_stopped: {batch_id, left} | null` (the newest stopped `library:*` batch). Rows
  unchanged (the table needs no AIFF answer per row).
- **`todo()`**: the `cdj` group (§1.5); `cdj` added to the filter list; `check_view` and `check_status` know
  `converted` / `renamed`; `_batch_item`'s detail by kind (§3).
- **`aiff_plan(scope)`** (read, `LIBRARY_METHODS`, inline like `spectrum`; check first how `spectrum` runs off the
  window's thread) → `AiffPlan`. The tag cache of §0.7 on `HubApi`.
- **Write jobs, kind `aiff_batch`, result `AiffBatchResult`, progress `BatchProgress`:** `convert(track_ids, origin)`
  (`origin` `library` | `todo`: the scope string; one id is `alone`), `rename(track_ids)`, `make_aiff(scope)` (`{kind:
  "lossless", view, key}` or `{kind: "cdj"}`; plans again, `refused` "Nothing to change: these are clean AIFFs
  already." when empty). `batch_resume` / `batch_undo` / `undo_upgrade` / `rekordbox_checked` unchanged.
- `docs/hub-bridge-contract.md` gets a section "Convert and clean names (issue 33 stage D)"; `types.ts` / `contract.ts`
  / `client.ts`, the fake backend (D7) with the scenarios §6.5 needs; contract tests pin every new shape.

---

## 5. Tests and behaviours to pin (offline; design §12)

**D1:** V8 on a V7 database (columns there, rows NULL, nothing else changed) and on a fresh one; pass 1 stores
`FileAudio`; the facts fill fills NULL own rows, skips downloads, resumes after a stop, and a row whose content key
the scan changes loses its facts; `add_bought_file` writes them; `cdj_problem`: every row of §1.4 both ways (320 kbps
not flagged, 321 flagged; 96 kHz FLAC not, 176.4 flagged; 48 kHz AAC not, 96 kHz MP3 flagged; 24-bit WAV not,
`pcm_f32le` flagged; Opus, Vorbis, WMA flagged; missing values never flag); `cdj_cover` (a 3000 px PNG → a ≤ 600 px,
≤ 500 KB baseline JPEG; a 600 px JPEG byte-identical; garbage → None); `own_name` ("X - Song [FREE DL]" with no artist
tag → ("X", "Song"); "Jay-Z" untouched; a tag pair already clean unchanged); `aiff_action` and `upgrade_waits` on
every §2.2 row.

**D2:** an MP3 (fixture, LAME) in rekordbox with cues → AIFF lined up (the clicks at rekordbox-timeline positions
±1 sample), every §5.5 column and nothing else (whole-row compare), text columns with a user edit kept; a 24-bit
96 kHz FLAC → 16/44.1; a 16/44.1 AIFF with wrong tags → samples identical, new tags; the user's own comment kept, genre
and year carried; the `expected_stem` name with an ID only when taken; old file mirrored into `Superseded/` under its
own name; the file row keeps `status`/`source_*`, gets `placed_by='app'` and the new `FileAudio`; no rekordbox → plain
conversion and the check says so; refusals (`not_analysed`, `timing`, `cloud`, `space`, rekordbox open at the commit →
rolled back) each with nothing changed; crash after each mark → recovery as `same_track`'s, the batch `stopped`;
undo (identity and facts back, later cue/rating/title edits kept, `relocated` refused, rekordbox open refused) and its
crash recovery; nothing written outside `move_path`.

**D3:** rename changes only `FolderPath`, `FileNameL` (`OrgFolderPath` only when equal), `PPTH`, `contentFile`; the
audio's and tags' bytes unchanged; the clean name taken → ID suffix; a case-only difference is `named_already`; two
items of one batch wanting one name → the second gets the ID; blocked (open, unreadable, cloud) with design §8's words
and nothing moved; a file with no rekordbox track only moves; crash between move and commit → moved back, no rekordbox
wait; after commit → finished; undo and its refusals (`in_the_way`, `relocated`); `recover_pending` dispatch.

**D4:** a batch of convert + rename items (kind `convert`; with a `same_track` item `mixed`); one backup, one
`rekordbox.lock`; per-item skip goes on; an item whose answer changed is skipped with the new reason; Stop between
items → `stopped`, Resume re-checks; rekordbox open at the start with any item's file in rekordbox → `RekordboxOpen`,
nothing changed, while a batch of files rekordbox doesn't have runs; batch undo newest first across convert and rename
items; `checked --batch`; `aiff_plan` per scope (view membership equals `views.library`'s, filter and search ignored;
lossless only for `lossless`; `cdj` equals the group; kinds, lossy count, space per drive, skipped in `tracks` only,
`needs_closed`); the plan never decodes (a test's `compare` and `timeline_offset` raise if called).

**D5:** both commands, human and `--json`, every scope, `--in` forms, `--dry-run` changes nothing (tree and
library.db equal), exit codes 0–5, `nothing_to_do`, `bad_args`, `batch resume/undo` on a stopped convert batch.

**D6/D7:** contract tests for `track().aiff`, `library().aiff_stopped`, the `cdj` group, `aiff_plan`, the three jobs;
views stay pure (facts and plans passed in); the fake answers every new method and scenario.

---

## 6. The UI: design direction, complete

Every UI group reads `docs/hub-design-language.md` first and loads the apple-design and emil-design-eng skills.
**Drift list (unchanged by this stage; compare every shot with `main`):** the foot bar, the sidebar and its icons
(Settings' icon never a sun), coloured service logos, the filter strip (SummaryStrip + Segmented), the table's row
grid and sticky heads, one filled button per screen, structured controls only (grouped rows, `Segmented`,
`ChoiceGroup`; never floating pills or loose prose), rekordbox lowercase in every word, Library names "Artist -
Title". Improve what you touch (design language §9), with a reason per change.

### 6.0 New blocks (single-component mockup candidates)

1. **Multi-select in the Library table** (`LibraryTable`): not a new block but the table's first use of
   `selectionModel`; one scope (rows with a file, `also` rows included; rows without a file `null`). ⌘-click, ⇧-click,
   ⌘A (the rows on screen: filter and search apply), Esc, ↑ ↓ as the model says; every selected row wears the picked
   wash (`.sel` = `ListRow selected pick`'s colours), only the anchor scrolls; `aria-multiselectable` on the grid,
   `aria-selected` per row. Right-click on a selected row keeps the selection; outside it selects that row alone.
   Double-click and Enter still play the anchor. Mockup: no (the pattern exists; the gallery's `gallery-selection`
   shows it).
2. **`AiffBatchPanel`** (`lib/decisions/`, + `AiffBatchFlow` in `flows.svelte.ts`, the window's one, as
   `UpgradeBatchFlow`): one `Panel` in three phases, built on UpgradeSelection's layout. **Decide:** head card (title
   and sub of §3); `fill` = the plan: a `Surface list` "What happens" with one `ListRow` per kind (label, count right
   in the count column), the format sentence as its `Hint`; the rekordbox outcome rows (`OutcomeList`: kept / step);
   the lossy `NoteCard` (info) when `lossy > 0`; Space as `KeyValue` rows per drive (a short drive in the problem tone)
   plus the Superseded line; "Left as they are · n" as a `ListSection` of `ListRow`s (cover, name, reason on the sub
   line, `wrap`). A plan of more than 8 items lists the items themselves under "Files" (collapsed `ListSection`,
   opened by its head) so the counts lead. **Running:** stage B's form (StatCard "{done} of {total}" with the track in
   work and its `ProgressBar`; the items with the 16 px mark column; Stop). **Ended:** "Made {n} files AIFF", the
   stopped/rekordbox-open `NoteCard`, the left ones with reasons; Done, or Resume · {k} left. Foot: the one filled
   button (§3's words; disabled with a `Hint` "Not enough space on …" or while rekordbox runs and `needs_closed`),
   Cancel as `link`. **Loading:** the head at its height, `Skeleton` rows in the fill ("Counting…" never as prose).
   **Empty:** `EmptyState` in the fill with §3's empty words, no filled button. Mockup: **yes, a single-component
   mockup is the coordinator's call** (it is the stage's one new decision panel; the builder has design decisions to
   make: the kinds list vs the per-file list, where space sits at 320 px).

### 6.1 Library details for one track (U1; design §9.3 state 2)

`TrackDetails.svelte` and `libraryModel.ts`. For a track whose `aiff.action` is not null, or whose `why_not` is
`rekordbox_unreadable`, `cloud` or `rename_blocked`: a card "AIFF" after the track card (where the decision cards
stand; never beside an upgrade, which wins). Rows as §3's `KeyValue`s (NAME through `MiddleText`, old → new on two
lines at 320 px if it doesn't fit); for a Convert with rekordbox `ready` the one-track outcome rows of design §8
(`OutcomeList`: kept "Your track keeps its cues, playlists and history", file "Becomes an AIFF file", step "Quit
rekordbox before you replace" only while it runs); a `cdj` answer as a warn `NoteCard` with its `words` above the
rows; `lossy` as the info `NoteCard` "An AIFF made from this sounds the same and takes 5–10 times the space."
Foot: the card's button (`WriteButton`, it starts a job): **filled** for a lossless file, a CDJ-flagged file or a
Rename; **outline** for any other lossy file (a choice that costs space, not a recommendation). It replaces "Open in
to-do" when the to-do item is this file's CDJ item. Blocked: the button disabled, the reason as the `Hint` under it
(design §8's rename-blocked or unreadable words). Running: the button's spinner, then the card gives way to the check
card the step left (the Library already shows check cards: CheckCards). A job problem (`rekordbox_open`, a skip) is a
warn `NoteCard` in the card, as UpgradeCards show theirs. Away or missing file: no card (the file's away words stand).
Not offered: a download, a clean AIFF with its name (no card at all).

### 6.2 Library table, selection and Make all (U2; states 3, 4)

`LibraryTable.svelte` (§6.0.1), `Page.svelte`, `stores/chrome.ts` (`detailsAfter`, `detailsSubject`), the new
`AiffBatchPanel`. **Subjects of the inspector:** one row → TrackDetails (as today); two or more → `AiffBatchPanel`
with `{kind: "tracks"}` (opened like a pick); the header's "Make AIFF…" → `AiffBatchPanel` with the view's
`{kind: "lossless", view, key}` (the selection clears; picking a row afterwards goes back to the details). The
inspector's rule "never empty" holds: the view plan is a subject while the view stands. **Header:** "Make AIFF…" as a
`Button` `outline` `sm` before the search field, only when the view has files; "Resume · {k} left" in its place while
`aiff_stopped`; while the flow runs it keeps its label and opens the panel. Below 1240 px the inspector steps the
browser back as today. The panel's done items refresh the table (the rows' format and name change), keeping the
selection on the same tracks.

### 6.3 To-do (U3; states 1, 5)

`pages/todo/*`, `todoModel.ts` (`MULTI_GROUPS` += `cdj`; `cdjAllKeys`, `wholeCdjGroup` as the upgrade pair),
`Details.svelte`, `lib/decisions/{CheckCards,BatchCheckCards,BatchCheckFoot}.svelte`. **The group:** its rows as any
To-do row (`detail` the `short`), head action "Convert all · {n}" (selects the group, as Upgrade all) or "Resume ·
{k} left". **One item's panel:** the track card; the warn `NoteCard` with `words`; the same rows as the Library's AIFF
card (§6.1: share them as one component `AiffCard` in `lib/decisions`, U1 builds it, U3 reuses it); foot "Convert to
AIFF" filled, Hide as today. **Several or all:** `AiffBatchPanel` (U2's) with `{kind: "tracks"}` or `{kind: "cdj"}`
when the selection is the whole group. **Check cards (state 5):** `converted`: the text, the USB step (stage B's
words) only with rekordbox tracks, no analyse step (the sound is the same); `renamed`: the text, no steps; no
rekordbox: the text's first sentence and the "not in your rekordbox collection" line, Done and Undo only. A batch of
converts is one `BatchCheckItem` ("{n} tracks", "{day} · Made AIFF"), its card lists each track with its new name.
Empty and no-selection states are To-do's own.

### 6.4 Shots (S1, S2) and fake scenarios (D7)

Each state a fake scenario and a `shots.json` entry, at 1100 and 1280 (2560 for the panels):
- **S1, Library (≤ 18):** details `aiff-flac`, `aiff-lossy`, `aiff-cdj`, `aiff-rename`, `aiff-blocked` (unreadable),
  `aiff-rename-blocked` (rekordbox open), `aiff-running`, `aiff-check-converted`; table `aiff-multi` (several
  selected), panel `aiff-selection` (mixed kinds + skipped), `aiff-selection-lossy`, `aiff-view` (Make all),
  `aiff-view-loading`, `aiff-view-empty`, `aiff-view-space` (a short drive), `aiff-rekordbox-open`, `aiff-panel-running`,
  `aiff-panel-stopped` (header Resume), `aiff-panel-ended`.
- **S2, To-do (≤ 10):** `cdj` (the group), `cdj-item`, `cdj-multi`, `cdj-all`, `cdj-resume`, `check-converted`,
  `check-converted-no-rekordbox`, `check-renamed`, `check-convert-batch`.
Each checked for meaning (every grey, colour, word, count), empty, first-open and no-selection states, icons at real
size, and against the drift list; findings reported, nothing fixed.

---

## 7. Task groups (one agent each, in this order, one at a time)

Every group: read `CLAUDE.md`, this plan and the design sections it names; touched tests while working, then
`~/.local/bin/uv run pytest -q | tail -3` once at the end (UI groups: `npx vitest run <files>`, `npm run check`,
`npm run rules -- --page <p> --only <shots>`; `npm run verify` only in V); `scripts/check_public.sh
--require-denylist` before each commit; commits `feat(convert): …`, `feat(hub): …`, `feat(hub-ui): …`, `test(…)`,
`docs(…)`, `build(hub): static`. Never start rekordbox, a real sync or the app; never read `~/Library/Pioneer`,
`~/Music/Discjockey` or the real library (RH only as written there); no waiter loops, no `pgrep`; long commands in
the background with a status line. Sizes are the record's, not hopes: each group is cut to land under ~200k.

| # | Group | Model, size | Files | Stop point |
|---|---|---|---|---|
| D1 | File facts, CDJ rule, cover, own names, eligibility | Sonnet, 170–200k | §1.1 D1 rows; tests `test_db.py` (V8), `test_importer.py`, `test_cdj.py` (new), `test_audio.py`, `test_identify.py`, `test_eligible.py`. **Check first:** §0.3's import start; §0.12's `split_title`; §1.4's CDJ-3000 table | V8 + fill + `cdj_problem` + `cdj_cover` + `own_name` + `aiff_action` green, committed |
| R-D1 | Review of D1 | Sonnet, 110–150k | the diff against §0.2–§0.4, §0.11–§0.12, §1.4, §5 D1: no own row left without a path to facts, downloads untouched, every write of a cover through `cdj_cover` | report; fix round (≤ 6 stated fixes, fresh Sonnet 150–200k) if needed |
| D2 | `convert_file`, its undo and recovery | Sonnet, 180–200k | `convert.py`, `upgrades.py` (undo dispatch, `can_undo`), `report.py` (`converted`), `rekordbox/write.py` only if a helper is missing; tests `test_convert.py`, `test_upgrades_undo.py` (check first the names). **Check first:** `undo_convert` and `recover_convert` without `held`; `render_aiff` copies 16/44.1 samples | every D2 behaviour green on a tmp library with a fixture rekordbox, committed |
| R-D2 | Review of D2 | Sonnet, 120–160k | against design §3.1, §3.5, §4, §5.5, §5.8, §5.9 and §5 D2: shift sign, the file row, nothing outside `move_path`, crash at every mark | report; fix round as R-D1 |
| D3 | `rename` | Sonnet, 170–200k | `rename.py`, `convert.py` (public `side_of`/`tracks_at`), `rekordbox/write.py` (`rename_change`), `library.py` (dispatch, path keys), `upgrades.py` (undo kind), `report.py` (`renamed`); tests `test_rename.py` (new) | every D3 behaviour green, committed |
| R-D3 | Review of D3 | Sonnet, 110–150k | against design §7.1, §5.8, §5.9 and §5 D3: identity-only write, collisions, recovery never waits for rekordbox | report; fix round as R-D1 |
| D4 | Batches and `aiff_plan` | Sonnet, 170–200k | `batches.py`, `aiff_plan.py`, `rekordbox/eligible.py` (words), tests `test_batches.py`, `test_aiff_plan.py` (new). **Check first:** `views.library`'s view membership as a function the plan can call without the view's rows (extract it there if not) | §5 D4 green, committed. **Stop point:** the coordinator reads all four engine reviews before D5 |
| R-D4 | Review of D4 | Sonnet, 110–150k | against §0.1, §0.6–§0.8, §0.13, §1.3, §1.6, §5 D4 | report; fix round as R-D1 |
| D5 | Commands and docs | Sonnet, 170–200k | `batch_cmd.py` or `convert_cmd.py`, `cli.py`, tests `test_batch_cmd.py`/`test_convert_cmd.py`; `CONTRIBUTING.md`, `README.md`, `CLAUDE.md`, `docs/issues.md` (§8) | every command on a fixture library, human and `--json`, committed |
| D6 | Bridge and views (Python) | Sonnet, 170–200k | `hub/api.py`, `hub/views.py`, `docs/hub-bridge-contract.md`, tests `test_hub_api*.py`, `test_views*.py` (check first the names) | §4's Python side and the contract doc green, committed |
| D7 | Types, fake, scenarios | Sonnet, 150–190k | `hub-ui/src/lib/bridge/{types,contract,client}.ts`, `bridge/fake/*`, the pages' `fake.ts` scenarios of §6.4 (data only), contract tests | `npm run check` + contract tests green; every §6.4 scenario reachable; the existing panels unchanged on the new shapes |
| RH | Rehearsal on a copy | Sonnet, 170–200k | `scripts/rekordbox_rehearsal.py`: `rehearse-convert` (§7.1) | its report; any FAIL → the coordinator decides a fix group before U1 |
| U1 | Library details + `AiffCard` | Sonnet, 160–200k (the direction is complete) | `lib/decisions/AiffCard.svelte` (+ model test), `pages/library/{TrackDetails.svelte,libraryModel.ts}` (+ tests), `shots.json` entries; `build(hub): static` | every §6.1 state reachable in fake mode; no shots, no dev server |
| U2 | Library table + `AiffBatchPanel` | **Opus**, 190–200k (the panel's layout decisions: kinds vs files, space at 320 px, loading and empty) | `pages/library/{LibraryTable,Page}.svelte`, `stores/chrome.ts` (+ test), `lib/decisions/{AiffBatchPanel.svelte,flows.svelte.ts}` (+ tests), the gallery entry, `docs/hub-design-language.md` (block row, decision log), `shots.json`; `build(hub): static` | every §6.2 state reachable; stop before To-do |
| U3 | To-do group and check cards | Sonnet, 170–200k | `pages/todo/*`, `todoModel.ts` (+ test), `lib/decisions/{CheckCards,BatchCheckCards,BatchCheckFoot}.svelte`, `shots.json`; `build(hub): static` | every §6.3 state reachable |
| S1 | Shots, Library | Sonnet, 110–140k | §6.4 S1 | findings report |
| S2 | Shots, To-do | Sonnet, 90–120k | §6.4 S2 | findings report |
| R2 | Stage review | Opus, 160–200k | the whole diff against this plan and the design: the invariant texts word for word, the words (§3), the contract, the drift list, RH's report, S1/S2's findings | report; fix rounds by kind (code/docs; UI), each ≤ 6 stated fixes, fresh Sonnet 150–200k |
| V | Verify and merge | coordinator | `npm run verify` once in the background (~20 min), `npm run smoke`, CI green on the stage branch; merge `Merge feat/rekordbox-d: Convert, clean names, the CDJ group, Make all lossless files AIFF` into `main`, push | **no release** before the user's live test (§9) |

Total: about 3.3–3.8 M tokens over 19 runs plus fix rounds; the engine (D1–D4 and their reviews) is about 40 %. It
writes the user's files and rekordbox's library, so every engine group is reviewed before the next builds on it, and
the stage gets the rehearsal and the Opus review. No re-check agent: fix rounds state their fixes and run the
touched tests.

### 7.1 The rehearsal, `rehearse-convert` (RH)

Same safety as `rehearse` (marked work folder, refuses while rekordbox runs or `-wal`/`-shm` lie beside the source,
every path an argument, names never leave `W`). Run once over a fresh `copy-db` + `copy-tracks` (one MP3, one M4A
44.1, one M4A 48 kHz, one AIFF or WAV pick); report PASS/FAIL with numbers, no names:
1. **Prepare** the scratch library with the copies as own songs (no parked upgrades) and derived picks made from the
   PCM pick, each repointed in the copy with Discjockey's writer: a FLAC (sample-identical), a 24-bit 96 kHz AIFF, a
   16/44.1 AIFF with wrong tags, the PCM pick renamed messy ("pick_final_v3.aiff"), and an AAC at 420 kbps from it
   (`aac -b:a 420k`; its rows keep the original's analysis, so `d` snaps to 0). One user edit of a title kept.
2. **Dry runs:** `convert --all lossless --in folder:<W/music/Library/Rehearsal> --dry-run --json` and `convert --all
   cdj --dry-run --json`: kinds equal the picks (flac 1, wav/aiff_hires/tags/name as made), the AAC in the CDJ plan
   only; tree, library.db and `dump(copy)` byte-equal before and after.
3. **Make all:** `convert --all lossless --in … --json`: batch `make_aiff`, kind `convert`; per item stage B's
   `check_run` checks (columns, text, ANLZ splice, backup = the before copy) plus: the FLAC's AIFF samples equal the
   source's; the 24/96 one is 16/44.1; the tags-only one's samples are identical; the renamed one changed only its
   path columns, `PPTH` and `contentFile` (whole-row diff) and its bytes are the file's.
4. **CDJ:** `convert --all cdj --json`: the AAC converted, `d` 0, its row 16/44.1 AIFF.
5. **Lossy by name:** `convert <mp3> <m4a44> <m4a48> --json`: the render matches ffmpeg's decode of the old file
   shifted by the snapped `d` (cross-correlation within ±1 sample); the text columns with the user's edit kept.
6. **Undo:** `batch undo <id> --json` for each batch: stage B's `check_undo` checks (old files back, rows as before,
   `PPTH` back, the renders in `.discjockey/undo/`).
7. **Clean up** `W`; nothing real in the repo. Stop point: any FAIL → the coordinator decides on a fix group.

---

## 8. Docs and issues

- **CLAUDE.md** (D5): "Moving never renames" becomes, word for word:
  > **Moving never renames:** a move (a tidy-up, its undo, a folder rename) keeps each file's name, so rekordbox's
  > (Auto) Relocate finds it by that name. A file gets a new name only in a step the user chose that points every
  > rekordbox track of that file at the new name itself, while rekordbox is closed (Convert to AIFF, Same track for a
  > file that isn't AIFF by hand or through Auto-upgrade, Give it its clean name). That step is refused when it can't.

  Layout: `convert.py`'s row "Same track for a file that isn't AIFF and Convert to AIFF (`convert_file`) … one of the
  two modules that give a file a new name outside the download paths"; a row for `rename.py` ("Give it its clean
  name: the `rename` op, its recovery and undo; the other one"); a row for `aiff_plan.py` ("read-only: what Convert,
  Rename and Make all lossless files AIFF would do over a scope; the panel's, the dry run's and the job's one
  answer"); a row for `cdj.py` ("pure: which own files CDJs refuse, with the words"); `batches.py` names `convert` /
  `rename` items; `db.py` names the files' facts columns.
- **README** (D5): Library: Convert to AIFF, Give it its clean name, Make all lossless files AIFF (where, what it
  does, lossy files only by choice, Superseded/, rekordbox closed, undo), multi-select in the Library; To-do: "Won't
  play well on CDJs" (what it flags and why, Convert all), the XDJ note (§3); rekordbox: the steps now include
  Convert and rename; console: `convert`, `rename`.
- **CONTRIBUTING.md** (D5): both commands with their JSON, the agents' way to read the CDJ group and a view's plan.
- **Contract** (D6), **design language** (U2: the panel's row, LibraryTable's multi-select, decision log entries;
  U1/U3 add rows only if they change a block).
- **Design corrections** (D5 commits them into the design, each "corrected in stage D; plan §0.n"): §2.2 `upgrade_waits`
  (§0.2); §2.4 the inspector instead of a sheet (§0.5) and "all" = the view (§0.6); §9.3's CDJ rule settled (§1.4,
  §0.4); §3.5's cover source (§0.11); §4's own-name check answered (§0.12).
- **Issues** (V): issue 33: "stage D merged (`<sha>`), live test pending (plan stage D §9); stage E open". New:
  `WAVE_FORMAT_EXTENSIBLE` WAVs some CDJs refuse (not detected yet). Issue 39: `convert` and `rename` are in.
- **Archive:** this plan moves to `docs/archive/` when its live test passes; the design stays until stage E.

---

## 9. The user's live test (about 15 minutes; only what needs a person with rekordbox)

A rekordbox backup first (File › Library › Backup). Throwaway 120 BPM click tracks, each analysed in rekordbox with
hot cues on clicks and in a playlist: one FLAC, one 24-bit 96 kHz WAV, one AIFF with a messy name ("click_final.aiff"),
one AAC at 420 kbps, one MP3. rekordbox closed for steps 1–4.
1. **Make all lossless files AIFF** on their folder's view: the FLAC and the WAV become AIFF, the AIFF gets its clean
   name. In rekordbox: AIFF/44.1/16, plays, cues and grid on the clicks, still in the playlist (also the 96 kHz one).
2. **To-do › Won't play well on CDJs:** the AAC is listed with its words; Convert all; rekordbox plays the AIFF with its
   cues on the clicks.
3. **The MP3 by hand** (Library › details › Convert to AIFF): cues on the clicks.
4. **Undo all** on each check card: the old files back, rekordbox plays them with their cues.
5. **rekordbox open:** Convert on one file: the "Quit rekordbox" words, nothing changed.
6. **Optional, if a CDJ or XDJ is at hand:** export the converted AAC's AIFF to a stick and load it.
After it passes: release on the user's go.
