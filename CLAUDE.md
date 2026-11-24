# CLAUDE.md — Discjockey

Discjockey keeps a lossless DJ library in step with the user's Spotify, Qobuz, SoundCloud and YouTube Music playlists: Qobuz as 16-bit AIFF first, then the
best fallback (YouTube Music, SoundCloud, YouTube), and it never deletes a music file. Two front ends share one engine:
the console (`discjockey`) and the hub, a Mac window (pywebview + Svelte). `docs/manual.md` is the user's manual — read it for
how a feature behaves from the user's side. `CONTRIBUTING.md` holds the developer notes (checkout, UI workflow,
building, releasing).

The repo is public (github `TheZwiss/discjockey`); users install the signed app from its releases. A maintainer
develops on a Mac that also holds their own library, and tests never touch a real library.

## This codebase is yours

An orchestrating Claude session and the agents it dispatches write and maintain all of this code; the user reads
results, not diffs. So the codebase is yours: you are responsible for keeping it correct and maintainable, and you
(or the next agent, who is you without your memory) will build on whatever you leave. Every shortcut, hidden bug,
unclear name, flaky test or half-finished move comes back to bite you in a later phase. Work accordingly:

- Write code you would be glad to find next week with no context: correct first, tested by behaviour, named plainly,
  and explained where the why is not obvious.
- Fix root causes, never symptoms; no workaround the next change has to step around.
- What you touch you leave at least as clear as you found it: no dead code, no duplicate path, no stale doc or test.
- A bug, flaky test or confusing piece you meet is yours: fix it if it is in the files you touch, otherwise report it
  (`docs/issues.md`, or your report). Never step past it silently. Work a later planned group owns is reported, not
  done (scope rule, `.claude/scope-check.sh`).
- "Green" means you believe it is right, not that the tests happen to pass.

---

## Layout

A user's data never sits in the repo and none of it is in git — never test against it:

- **The music folder** (whatever the user chose in Setup, suggested `~/Music/Discjockey`): `playlists.txt` (the only
  config), `Library/<Folder>/` (+ `not_lossless/`), `Superseded/`, `Upgrades ready/`, and the hidden `.discjockey/`
  (`library.db`, `state.v1.json` (the old records, kept as a copy after the migration), `reports/`, `not_lossless.md`, the lock).
- **The support folder** `~/Library/Application Support/Discjockey/`: logins, `settings.json`, `config.json` (names
  the music folder), caches, `tools/` (updated yt-dlp, spec public-release §6.4), `pace.json` + `pace.lock` (the one
  pacing of every Qobuz and account request of this Mac: `pacing.SharedPacer`, an `flock` held only to read and write,
  never while waiting; the failure streak and its pause live in each service's `usage` row in library.db and end when
  the next sync starts, in any process). For a developer run against a
  scratch library set `DISCJOCKEY_SUPPORT=<scratch folder>` (Setup then asks for a music folder). Tests point it at a
  temp folder by themselves.

| Path | What |
|------|------|
| `bin/discjockey` | Launcher: `uv sync`, then `.venv/bin/python -m discjockey` (under `caffeinate` except for `app open`) |
| `discjockey/` | Engine. Each module's docstring says what it owns; read that before opening the file |
| `discjockey/planner.py`, `discjockey/hub/views.py` | Pure: no I/O, no clock. Keep them that way |
| `discjockey/library.py` | Everything on disk: paths (music folder, `.discjockey/`, support folder), `config.json`, the library lock and the support lock (`support_lock`: `<support>/.support.lock`, waited for 2 s, then `SupportBusy`; every read-change-write of `settings.json` (`settings.update_settings`), `config.json`, the login files and `tools/` holds it), names, crash-safe ops (`run_op` for single steps and the upgrade swap with its undo, `move_files` / `move_path` for file moves, also across drives; all journal in library.db's `pending` past the entry view (`db.journal_step` / `end_step` / `replace_pending`): a step writes only its own songs and file rows, and the caller's other unsaved changes wait for its next save), `scan_library` |
| `discjockey/db.py` | `library.db`: the schema, the migration from `state.json`, the move log (batches and moves), the AIFF batches (`aiff_batches` / `aiff_items`, outside library state like the move log; both batch tables carry `via` `window` | `terminal`, schema 10; `end_step(item=…)` closes an item with its step), the files' own facts (`file_codec`, `file_rate`, `file_bits`, `file_kbps`: what the file at `path` is, schema 8, read back as `models.entry_audio`; `facts_failed`, schema 9: a file ffprobe answered for but found no audio in, marked `<size>:<mtime_ns>` so it isn't probed again until the file changes; `set_file_facts`, `set_facts_failed`, `files_without_facts`, `facts_missing`), the missing mark (`files.missing_since`, schema 11, issue 43: the first scan that read a linked file's folder and didn't find the file; the row waits with everything its song has and `apply_scan` clears the mark when the file is seen again; `models.file_missing(entry)` is the one check; `held` now means only "its audio changed and the sound check failed"), the stored playlists reads (schema 12, issue 39 phase 2: `reads`, the records' `playlist_reads` / `playlist_tracks` with every `SourceTrack` fact the planner uses, `playlist_infos`; `store_read` / `load_read` / `read_head`, `run.store_read` / `run.prepared_from_read`; a read id is `read:<n>`; a track's own SoundCloud link token and the record label are never stored; a private set's token stays in its ref, the record's identity, as in playlists.txt), Favourites and crate visibility (all of it outside library state: they never bump `generation` or enter `snapshot`), every query. Nothing else touches `library.db`'s SQL; rekordbox's `master.db` only through `discjockey/rekordbox/master.py` (reads) and `write.py` (writes) |
| `discjockey/sources/` | Playlist services, one module per service (`spotify.py`, `qobuz.py`, `soundcloud.py`, `youtube_music.py`) behind one interface (`recognise`, `canonical_link`, `login_state` (`ok`, `missing` or `not_needed`: SoundCloud and YouTube Music are read without a login), `open` → a `Reader` with `fetch` and `info`, optionally `expand` for a link that names no playlist yet (short SoundCloud links, `you/likes`; `hub/api.add_playlist` calls it); `base.py` holds `SourceError`, `LoginState`, `Reader`). `__init__.py` is the registry (`SOURCES`) with `recognise`, `expand`, `read`, `read_infos` and `service_list` (the four names in words). A new service is a new module plus one registry line. Reads are anonymous and use no pacer, budget or usage row (only the `you/likes` expansion uses the SoundCloud login, and YouTube Music's Liked music (`LM`) the YouTube login, only while Settings' `read_liked_music` is on and the account is not paused; `LL` and `WL` are still refused); yt-dlp is imported lazily inside the new modules. Songs and playlists are named by tokens (`models.token`): a Spotify id stays bare, every other service's id is `service:id`. A SoundCloud set lists only its first few tracks in full: every other one is a stub `{id, kind, monetization_model, policy}` (a `policy` does not make it full), which the reader fetches in batches (`tracks?ids=`, with the set's token) and skips, never keeps nameless, when SoundCloud no longer shows it; a track without a title is never searched by name (`SourceTrack.named`). A private SoundCloud track carries its secret link token (its own, else its private set's) on `SourceTrack` for the upload step: not a dataclass field, so `asdict`, `repr`, events and reports never hold it; `Candidate.secret` hands it to `fallback` (`stream_url(..., secret)`), and `fallback.scrub` strips any `secret_token=` from messages and errors |
| `discjockey/rekordbox/` | rekordbox's library, read in stage A and, in stage B, written by issue 33 (design `docs/2026-11-07-rekordbox-repoint-design.md`): `locate.py` finds `master.db` and the analysis `share` folder (`DISCJOCKEY_REKORDBOX=<folder>` replaces the lookup; tests set it to an empty folder), `master.py` opens it (SQLCipher, the key in `KEYS`, always read-only and never leaving a `-wal`/`-shm` beside it), checks it (`status`: `ready`/`none`/`unreadable` with the problem; `READ_COLUMNS` is the one list of columns read or, in stage B, written) and finds the tracks that hold a file (`entries_for`, optionally through a `PathIndex` from `index()`; `cue_counts`; a batch's `RekordboxView` bundles the open library, its index and its status for `timeline_offset(view=…)`), `process.py` tells whether rekordbox runs, `anlz.py` reads the analysis files (`PPTH`, the `PQTZ` grid, the `PWV3` waveform; a broken file is "no analysis"), `timing.py` (pure) measures rekordbox's offset from the waveform and snaps it to the format's expected values, `probe.py` finds ffmpeg's start trim, `offset.timeline_offset` gives one answer per file (`d` in 44.1 kHz samples, or why it's unknown), `eligible.py` (pure) says per track whether Same track, Convert and Rename can run and why not (`REASONS`, `upgrade_waits` among them: a parked upgrade wins; `same_track_quick` is the answer for counts and screens, without reading the file; `aiff_action` is the one answer for "make it a clean AIFF": Convert, else Rename, else the more telling skip), `write.py` is the only writer (`open_write` checks guards 1–4 and 7, the `Writer` repoints a track, writes its text columns and finds or makes artist/album/label rows with rekordbox's scheme, stamps each changed row with its own `rb_local_usn`, splices `PPTH` (`anlz.splice_ppth`, rekordbox 7 keeps `?/<name>` there) and updates `contentFile`, rolls everything back when rekordbox opens before the commit, and undoes per field), `backup.py` keeps one backup per batch in `.discjockey/rekordbox/backups/` (reuse while master.db's hash holds, prune, `restore`), `lock.py` is `rekordbox.lock` (`writer_lock`, retried for 2 s, then `Busy`: one writer per Mac; sessions, `restore` and recoveries that write analysis files hold it; `reader_lock`: a shared, non-blocking hold every reader of master.db takes, False while a writer holds it, so the reader answers `writing` and never opens master.db), `session.py` is a batch's rekordbox side (`rekordbox.lock`, the start check, one read open and index, the backup before the first write), `preview.py` is the read-only answer behind `rekordbox preview` (`CliApi.rekordbox_preview` adds the words; both rekordbox reads, `status` and `preview`, are commands of `discjockey/cli/`, issue 39) |
| `discjockey/titles.py` | Pure: splits an uploader's title ("Artist - Title [FREE DL]", a YouTube video title) into artists and a clean title, and cleans a channel name (`split_title`, `clean_uploader`). SoundCloud and YouTube Music sources apply it when they parse an entry, so linking, the Qobuz search and file names see clean names |
| `discjockey/qobuz.py` | The Qobuz **download** client (streamrip: login, search, download one track). Reading Qobuz playlists is `sources/qobuz.py`, which opens its own login per read |
| `discjockey/batches.py` | AIFF batches (issue 33): Same track over a list of tracks as one job, rows in library.db (`aiff_batches` / `aiff_items`): `start`, `batch_undo_preview` (the dry run of `batch undo aiff:<n>`), `run` (one `rekordbox.Session`, one backup, per item a skip/fail/done, Stop between items, rekordbox opening stops the batch; raises `Stopped`, `RekordboxOpen`, `Busy` or `Refused` with the `BatchResult`), `resume`, `undo` (newest first, refused tracks listed; rekordbox open at the start undoes nothing, opening meanwhile raises `RekordboxOpen` and Stop `UndoStopped`, the rest `waiting`), `close_unrun` (the console's batch of one that met rekordbox open or `Busy`), `end_auto` (closes an `auto_upgrade` batch that Stop, rekordbox opening or `Busy` cut short: its `planned` items are skipped, the backup id kept, no Resume), `checked`, `recover` (called by `library.recover_pending`; a crashed `auto_upgrade` batch is ended through `end_auto`). `start(started_by="auto_upgrade", scope="sync")` and `run(require_closed=True)` are the sync's Auto-upgrade batch; with the switch off, `started_by="download_again"` is its batch of placements alone (`SYNC_STARTED_BY` holds both: `end_auto`, `recover` and the no-Resume rule treat them alike). Stage D: an item is `same_track`, `convert` (`convert.convert_file`), `rename` (`rename.rename_file`) or, issue 43, `place` (`convert.place_parked`: the parked better version for a song whose file is missing, in the batch's `upgrade` kind, operation `upgrade_place`; `convert.PARKED_GONE` when the parked file is no longer there), the batch kind `upgrade` / `convert` / `mixed`, `started_by` `user`, `make_aiff` or `cdj_all`, `scope` what was picked (`library:<view>[:<key>]`, `library:selection` / `todo:selection` from the window, `selection` from a command, `todo:cdj`; the old `console` scope is gone: older console batches say `terminal` with no scope) and `via` where it started (`window` | `terminal`, schema 10: `start(via=…)`; a command's batch says `terminal`); a Convert or Rename item asks `eligible.aiff_action` with fresh facts and is skipped (never switched) when its answer changed; `undo` puts a Convert→Rename chain back with two undos. `upgrade_preview` (+ `preview_row`, `preview_space`, `quick_reason`) is the read-only dry run of an upgrade (Same track `swap` or New track `add_new`): `items` per song, space per drive, `needs_rekordbox_closed`; the one answer of `upgrade apply --dry-run` and `upgrade discard --dry-run` |
| `discjockey/aiff_plan.py` | The read-only plan behind Make all lossless files AIFF, a selection's Convert and the CDJ group's Convert all (issue 33 stage D): `plan(paths, state, scope, *, rb, entries, tags, only)` → `AiffPlan` (`to_dict()` is the bridge's and the dry run's one shape: items with action, kind, names, space, `skipped` for a selection only, `waiting` (files that can't run now: counted in every scope, never as items), kinds, lossy count, room per drive, `needs_closed`). Scopes: `tracks`, `lossless` (a Library view's files, `views.library_files`, whose stored codec is lossless by `quality.is_lossless_codec`) and `cdj` (`cdj.group_members`). Reads the tags only of own AIFFs in the library format, never decodes, changes nothing |
| `discjockey/cdj.py` | Pure: which own files the club players (CDJ-3000, CDJ-2000NXS2) refuse or stutter on (issue 33 stage D): `cdj_problem(audio, ext)` → `CdjProblem(reason, short, words)` or `None` (reasons `format`, `bitrate`, `bits`, `rate_high`, `rate_low`; the first match wins, a missing value never matches; FLAC, ALAC and 88.2/96 kHz are not flagged; the docstring names the limits and their sources), and `group_members(state)` → `{key: CdjProblem}`, the one answer To-do's "Won't play well on CDJs" group and Convert all (`aiff_plan`'s `cdj` scope) share (own files with stored facts, no parked upgrade, not hidden, not waiting as missing: issue 43) |
| `discjockey/auto_upgrade.py` | The sync's last phase, Auto-upgrade (issue 33 stage C; design §2.5): which upgrades (`plan`: To-do's Upgrade ready list filtered by `eligible.same_track_quick`, exactly Upgrade all's set), the rekordbox check (rekordbox running at the start: no batch, no backup, every track waits except those a held refusal leaves alone), one AIFF batch (`run_phase`), the `auto_refused` / `auto_waits` records on the parked upgrade (`refusal_holds`, `stamps`) and the run's block (`Outcome`, also the report's and `--json`'s `auto_upgrade`). The same phase puts the parked better version in for songs the user asked to download again whose file is missing (issue 43, D9: `missing.place_keys`, batch action `place`, `convert.place_parked`), first in the batch and also with the switch off (`started_by` `download_again`: only placements run); switched off with nothing to place, it returns before anything of rekordbox is looked at |
| `discjockey/convert.py` | Same track for a file that isn't AIFF and Convert to AIFF (issue 33): the parked upgrade (`same_track`) or the user's own file itself (`convert_file`) becomes a new 16-bit/44.1 kHz AIFF with the clean name, lined up with rekordbox's timeline of the old file, and every rekordbox track of the old file is pointed at it (one batch item; the journaled `convert` op, `source` `upgrade` or `file`, with its recovery and `convert_undo`; `place_parked`, issue 43: the same op for a song whose file is missing and whose better version is parked (`superseded` None, no Superseded/ step, `timeline_offset(codec=…)` for rekordbox's offset of the missing file, no rekordbox text written, check `placed_missing`; its undo has no old file and writes the row's first `missing_since` back through `end_op(missing=…)`); Convert's own step, space, names and recovery words; on an AIFF whose old file held the clean name it chains into `rename_file`). Builds on `rbstep` for what every rekordbox file step shares. One of the two modules (with `rename.py`) that give a file a new name outside the download paths |
| `discjockey/rbstep.py` | The kit every rekordbox file step shares (issue 33 stage D, D4c; Convert and Give it its clean name both build on it, never on each other): the refusal (`Skipped`, `skipped(reason)`, the words `REFUSED` / `CONVERT_REFUSED` / `OWN_FILE_REFUSED` (a step on the user's own file says no "New track"), `raise_refusal`), the journal entry's rekordbox part (`op_rekordbox`, `plan_splices`, `backup_tracks`, `journal_record`, `with_audio`, `finished_at`, `abs_path`), the commit point and recovery (`side_of`, `tracks_at`, `anlz_back`, `anlz_undo_back`, `clear_leftovers`, `rekordbox_lock`, `stop_batch`, `ours`) and the recovery/undo words both say. Callers use it module-qualified (`rbstep.name`), so a test's `monkeypatch.setattr(rbstep, …)` reaches every use; nothing is re-exported from `convert` |
| `discjockey/rename.py` | Give it its clean name (issue 33 stage D): an own AIFF 16/44.1 with the right tags gets `Artist - Title.aiff` in its own folder (`rename_file`, the clean name or with the song's ID when taken: `clean_path`) and every rekordbox track of it is pointed at the new name in the same step (`write.rename_change`: the path columns, `PPTH`, `contentFile` only); one journaled `rename` op (`backed_up`, `placed`, `committed`) with its recovery (`recover_rename`, decided by the rows' `FolderPath` through `rbstep.side_of`, never waiting for rekordbox unless an analysis file must come back). The other module that gives a file a new name outside the download paths. Reuses the shared step kit `rbstep` (`skipped`, `plan_splices`, `op_rekordbox`, `backup_tracks`, `journal_record`, `raise_refusal`, `side_of`, `tracks_at`). Its undo (`undo_rename`, from `upgrades.undo`: the same file back to its old name, refused when another file took it; rekordbox's identity columns and `PPTH` back where they still hold what was written) is the journaled `rename_undo` op with `recover_rename_undo`; `convert.convert_file` on an AIFF whose old file held the clean name runs `rename_file` right after (the user's file kept its name and became an AIFF, so the chain's result and check say "converted"; the rename keeps the Convert's check and undo in its `before`: two undos return the original) |
| `discjockey/cli/legacy.py` | The old command line, moved unchanged: the sync (no command), `setup` and `update` until their groups of issue 39 rebuild them (`upgrade …`, `batch …`, `rekordbox …`, `check done`, `aiff convert \| rename`, `folder add \| remove`, `settings show \| set auto-upgrade` and `sync run --auto-upgrade-only` are the new command line's; the removed words `upgrades`, `upgrade undo`, `rekordbox checked`, `convert`, `rename` and `settings auto-upgrade` answer `bad_args` that says what to say instead, `cli/parser.py` `MOVED`) |
| `discjockey/tidy.py` | The tidy-up: move batches (tidy-up, save question, folder rename), undo, recovery of batches a crash left open; every move through `run_op` or `library.move_files` (the file journal, staging across drives) |
| `discjockey/scanner.py` | Walks the watched folders (`Library/` and the import folders) against the index's file rows and returns a `ScanResult`. Reads only, no SQL; `db.apply_scan` writes it, `library.scan_library` ties the two together. A scan decides nothing about a song (issue 43): a linked row whose file isn't found is `missing` and is matched again by its content key at every scan; only an unlinked row's is dropped |
| `discjockey/identify.py` | Pure: whether a playlist song and a song of the user's own (a file the import read) are the same song (`compare`: certain or plausible), and an own song's name from its tags or file name. The planner calls it on every plan |
| `discjockey/importer.py` | The import of watched folders (`run_import`, a write job): scan, pass 1 tags (it stores each file's facts), pass 2 sound check, then linking to the playlists (`run.link_only`); `fill_facts` is the facts pass alone, for own files that have none (rows from before schema 8, a changed file): the import starts it first, `aiff convert` / `aiff rename` run it before they plan, and `library facts` is it as a command. It is two halves: `read_facts` (the probing, pure of library.db, yields `FactRead`s) and `store_facts` (writes them); a dry run reads a few in memory (`aiff_plan.with_facts`) and stores none. Progress lives on each file's row, so a stop resumes; nothing is copied, moved or renamed |
| `discjockey/folders.py` | Watched-folder actions and the To-do answers for the import: check, add, remove, "Is this the same song?", Keep both, Move to Superseded. Every file change through `library.move_files` |
| `discjockey/content_key.py` | The content key of an audio file (`1:<payload length>:<sha256>` over windows of the audio, so it survives renames, moves and tag edits; how a moved file is found) and `AUDIO_EXTS` |
| `discjockey/run.py` | One sync run, front-end independent, and its Auto-upgrade phase (`upgrade_phase`, after the plan's actions or in `finish_quietly`): with the switch on, upgrades and placements; with it off, only the placements for songs the user asked to download again whose file is missing (issue 43: `missing.place_keys`, `started_by` `download_again`), else it returns before anything of rekordbox is looked at; and that phase alone (`auto_upgrade_only`: `sync run --auto-upgrade-only`, no playlist read, never the planner, a report of kind `auto_upgrade_only`); `console.py` and `hub/jobs.py` render its `events.py` events |
| `discjockey/__main__.py`, `discjockey/cli/`, `discjockey/tools.py`, `discjockey/tool_updates.py` | `python -m discjockey` runs `tools.activate()` (bundled ffmpeg/ffprobe/deno first on `PATH`, a newer downloaded yt-dlp first on `sys.path`) before `cli/` imports anything that imports yt-dlp; `--check-tools <folder>` is the update check's child process (spec public-release §6.1, §6.4); `tool_updates.py` updates yt-dlp from PyPI into `<support>/tools/` (never `uv.lock`), keeps one previous, rolls back |
| `discjockey/cli/` | The command line (issue 39): `__init__.main` is the one entry; `parser.py` is generated from the catalogue (`hub/catalog.py`: one built entry = one command, flags from the `HubApi` method's signature; global flags anywhere; `route` sends a line whose command is not built to `legacy.py`), `call.py` runs every entry (`run(entry, args, flags)`: reads and brief saves call the `HubApi` method, `resolve` turns typed words into arguments, `--dry-run` runs the entry's `dry_run` method, `needs_yes` refuses without `--yes`; J and RJ start a registry job and its worker, `worker.py`), `follow.py` is the job client (`attach`: `--detach`, `--wait`, the default wait; `drive`; `job list|show|follow|wait|stop`, `--now`, Ctrl-C, read from the registry's files alone), `housekeeping.py` is the command line's own words (`help`, `help --json`, `where`, `app open`, `call <method>`, the `job` words; `CliApi.freshness()` fills the envelope's `as_of`), `envelope.py` the one answer object and its exit codes (`hub/outcomes.py`), `bind.py` binds the headless `CliApi` (`hub/api.py`: a `HubApi` subclass that adds the `cli_first` methods the window must not see; nothing watches), `render/` the text pages (`layout.py` the framework, `generic.py` prints any payload, `todo.py` and `track.py` the hand pages of `todo list` / `upgrade list` / `check list` and `track show`, picked by `render.page_for(command)`). One command may be several entries (`catalog.primary` is the one whose signature the parser reads: the write): `aiff convert` is `convert` (named songs, `--rows`), `make_aiff` (`--all [--in C \| --todo cdj]`: `ALL_METHOD` swaps it in) and `aiff_plan`, the read that is every aiff command's `--dry-run` (a read job: its worker saves the plan); `aiff rename` is `rename` (`--all` is `select_listing`'s `rename_all`) and its own `aiff_plan` with `only` rename. A cli module computes nothing: tests/test_cli_frame.py (T3) pins what it may call. Golden pages: `tests/cli_golden/` |
| `discjockey/app_main.py`, `discjockey/selftest.py` | The app's program (spec public-release §5): `--check-tools` first, then `--self-test` (imports, bundled programs, tone → AIFF, the keyed SQLCipher open rekordbox's library needs, UI file, the update check; scratch support folder, no network), then, with `tools.activate()`, the window for a Finder start (no argument with launchd as the parent, or the single `-psn_…`), else `cli.main`: any argument but `--check-tools`, `--self-test`, `app open` and a Finder start goes to the command line (`Discjockey.app/Contents/MacOS/Discjockey rekordbox restore …`), and no argument from a shell prints the short help. `python -m discjockey.app_main --self-test` runs it in a checkout |
| `discjockey/hub/` | Window: `api.py` (bridge methods), `views.py` (screen JSON), `jobs.py` (background work + events), `media.py`, `spectrum.py`; `plan_store.py` (issue 39: a dry run's plan in `<support>/plans/`, `--plan` binds a run to it), `select.py` (pure: which songs a listing selects, the one rule behind `--rows` / `--all`; `CliApi.select_listing`), `windows.py` (which windows are open: each window holds an `flock` on `<support>/windows/<pid>.json`, `count_open` is `where`'s `windows_open`; never touches `.window.lock`). The window learns of other processes' jobs from the registry (`Jobs.watch_registry`, once a second: `ConsoleBusy` names the job, its kind and `line` and carries `text`, the banner's words (`words.holder_text`); a foreign job's end is the window's own `JobFinished` from `result.json`); the lock probe stays only for a holder with no registry entry |
| `discjockey/hub/outcomes.py`, `ids.py`, `catalog.py`, `registry.py`, `discjockey/problem.py` | Issue 39's engine base: `outcomes.py` is the one table of exit numbers, the closed list of reasons with their words, `KIND_OUTCOME` (every bridge problem kind → outcome), the precedence and the person steps (the `bridge` decorator adds `outcome`, `reason`, `next`, `person_steps`, `data` to every problem answer, beside `{ok, kind, message}`); `ids.py` parses and prints typed ids (`aiff:12`, `moves:12`, `job:…`, `report:…`, `folder:<path>`; pure); `catalog.py` is every bridge method as a command entry (flags generated from the signature, `planned` until the command is built; tests T1); `registry.py` is the cross-process job record in `<support>/jobs/<job:8hex>/` (`state.json`, the `alive` flock a job holds its whole life, the capped `events.jsonl` + `events.tail.jsonl`, `result.json`, the `stop` file `CancelToken(stop_file)` watches; a job is `lost` when its state says running and nobody holds `alive`, never decided by pid; `new_job_id` gives every job id, the window's too; the window's jobs are in it as well, `via: window`, each with its `library_lock` (what `worker._holder` and `api._library_job_elsewhere` read) and its `progress` from `ProgressReducer`, which the worker shares); `problem.py` is the base of `OpProblem`, `jobs.Busy`, `rekordbox.lock.Busy` and `library.LockHeld` carrying `reason`, `next`, `person_steps`, `data` |
| `discjockey/words.py` | The words the engine owns for the command line (issue 39, design §8.3): `person_steps(track_id, check, new_path)` makes `check_view`'s `person_steps` (`step:relocate_new` for an added file, `step:reload_tag` for a swap, Same track or Convert; `say` is `report.check_text` plus the USB step, `then` is `check done <track>`). Later groups add their words here. It also holds the window's banner words for another process's job (`JOB_TITLES`, `job_title`, `holder_text`, `holder_where`, `UNNAMED_HOLDER`), made by `Jobs._holder_of` and carried as `ConsoleBusy.text` / `ConsoleBusy.where`, `JobStatus.console` and `Busy.data.holder` |
| `discjockey/hub/static/` | **Build output** of `hub-ui` (committed). Never edit by hand |
| `hub-ui/` | Svelte 5 + Vite + TS. `src/lib/bridge` (only `client.ts` touches `window.pywebview`), `bridge/fake` (offline backend), `components`, `stores`, `pages/<page>/` |
| `hub-ui/src/lib/frames` | The two page frames (`ListPanelFrame`, `ColumnFrame`) and `Panel`; the design system's blocks are in `lib/components`, its catalogue is the gallery `#/dev/gallery` (fake mode) |
| `packaging/` | The app build (spec public-release §5–§6.6): `tools.json` pins deno (URL + SHA-256) and FFmpeg's source release with its configure arguments (`fetch_tools.py` fails on a hash mismatch and builds ffmpeg/ffprobe with `build_ffmpeg.sh` on a cache miss), `licenses/` the hand-kept licence texts (see the next row; `collect_licenses.py` adds those of every distribution with files in the app; the spec runs it on what Analysis collected), `discjockey.spec` (PyInstaller; entry `launch.py`, Info.plist from `app_info.py`), `dmg_settings.py` (dmgbuild); `scripts/build_app.sh` runs them all. Plain scripts, never a Python package (it would shadow PyPI's `packaging`); tests load them with `tests/packaging_helpers.py` |
| `packaging/licenses/ffmpeg.txt` | The bundled ffmpeg's notice: GPL-3.0-or-later, built from the pinned source without external libraries (issue 19), the macOS libraries it uses, and its configuration line, which a test pins against `tools.json`'s configure arguments. A new `--enable-lib…` needs its licence text here and a GPL-3.0-compatible licence |
| `LICENSE` | GPL-3.0, byte for byte `packaging/licenses/GPL-3.0.txt` (a test compares them) |
| `scripts/check_public.sh` | The public check (`check_public.py` does the work, stdlib only): a real person's `/Users/` path, e-mail addresses outside the allowed domains, other repos of the account, and the words of a denylist kept outside the tree (`~/.discjockey-public-denylist`, or `DISCJOCKEY_PUBLIC_DENYLIST`) |
| `scripts/make_public_tree.sh` | Builds the public repo's first commit as a local, parentless branch (`public-main`) from a ref minus `docs/archive/pre-public/`, after the public check passes on exactly that tree; prints the go-moment steps. Sends nothing |
| `scripts/public_push_guard.sh` | The pre-push hook those steps install: refuses any push whose commits descend from a private-history root commit (the roots are written at install time) |
| `scripts/import_signing_identity.sh` | CI: imports the "Discjockey Release" identity from its `.p12` (`SIGNING_P12_PASSWORD`) into its own keychain in `DISCJOCKEY_SIGNING_DIR` |
| `.github/workflows/` | `check.yml`: every push and pull request (public check, pytest with the pinned tools, committed `hub/static` matches a fresh hub-ui build; not `npm run verify`); `release.yml`: a `v*` tag → the same checks, the signed app, its self-test, the .dmg on a **draft** release. Both run only in `TheZwiss/discjockey` |
| `dist/` | Build output (gitignored): `app/`, the .dmg, `tools/`, `licenses/` + `bundled-sources.txt` (what they cover), `ui/` (the check build), `cache/` (downloads by hash, the ffmpeg build by its recipe), `build/venv`, `work/` |
| `tests/` | pytest. `conftest.py` blocks network + PyPI, stubs yt-dlp, points `DISCJOCKEY_REKORDBOX` at an empty folder and answers "rekordbox isn't running"; helpers `hub_`, `audio_`, `tools_`, `rekordbox_helpers.py` (`make_master` builds a rekordbox library); the speed-ups of `speed_*.py` and `tool_memo.py` (SQLCipher key once per key, repeated ffprobe/ffmpeg answered from memory, no drive flushes) each have an opt-out marker `real_*` for the test that pins the real thing (CONTRIBUTING.md, Tests) |
| `docs/hub-design-language.md` | **Living. Read first for any UI work:** the hub's design rules with do/don't, the blocks, the rule checker, Sync as the reference page |
| `docs/hub-page-brief.md` | The playbook a page agent follows to redesign one hub page (phase 2) |
| `discjockey/hub/shapes/` | Every bridge and command payload as a TypedDict with each field's meaning; `python -m discjockey.hub.shapes --export` generates `hub-ui/src/lib/bridge/types.gen.ts` and `schemas.gen.json`; test mode checks every answer and job result against them |
| `docs/hub-bridge-contract.md` | The rules between `discjockey/hub` and `hub-ui` (shapes are generated), pinned by tests |
| `docs/issues.md` | Open bugs, wishes and pending live checks |
| `docs/hub-mockups/` | Approved HTML mockups; `hub-ui/scripts/shots.mjs --compare` renders against them |
| `CONTRIBUTING.md` | Developer notes: checkout, the Terminal version, tests, the UI workflow, building, the public check, releasing and the CI secrets |
| `docs/archive/` | Finished specs, plans and handovers. `pre-public/` holds everything archived before the repo went public (gitignored, on the maintainer's disk only); plans archived from now on go into `docs/archive/` itself and are public. See "Docs and plans" |

Gitignored runtime files (`state.json`, `settings.json`, `reports/`, `not_lossless.md`, `.spotify_*.json`, `.streamrip/`)
are leftovers of an old layout in the maintainer's checkout; nothing writes them there any more.

---

## Commands

| What | Command (from the repo root unless noted) |
|------|------|
| Python tests | `~/.local/bin/uv run pytest -q` |
| UI check + tests + trial build | `cd hub-ui && npm run verify` |
| UI build into `discjockey/hub/static/` | `cd hub-ui && npm run build` |
| Built-app smoke test (WebKit, stub bridge) | `cd hub-ui && npm run smoke` (after build) |
| Fake-mode dev server | `cd hub-ui && npm run dev` (fake backend, `?scenario=…`, toolbar) |
| Screenshots | `cd hub-ui && node scripts/shots.mjs --port <dev port> --page <page> [--sizes min,default,large] [--compare]` or `--all` → `hub-ui/screenshots/<name>@<w>.png`; sizes default to all three (1100×700, 1280×800, 2560×1440) |
| Design rule checker | `cd hub-ui && npm run rules [-- --page P --only a,b --force]` (also part of `npm run verify`) |
| Hub window in the terminal | `DISCJOCKEY_HUB_DEBUG=1 bin/discjockey app open` |
| Dry run (changes no music files, writes no report) | `bin/discjockey --dry-run` |
| Signing identity (once per maintainer Mac) | `scripts/make_signing_identity.sh` → `~/.discjockey-signing/` (own keychain + password, `.p12` for the password manager and CI). Refuses to replace an existing one |
| Sign an app by hand | `.venv/bin/python packaging/sign_app.py dist/app/Discjockey.app` (ad-hoc without the identity; `--require-identity` for releases) |
| Build the app + .dmg | `scripts/build_app.sh` (background, ~5–10 min) → `dist/app/Discjockey.app`, `dist/Discjockey-<version>.dmg`; the app bundles the checkout's `hub/static` and the build fails when `hub-ui` builds something else (`SKIP_UI_BUILD=1` skips that check), `REQUIRE_IDENTITY=1` refuses ad-hoc signing and a checkout with uncommitted changes. Never copy the result into `/Applications` |
| Self-test of a built app | `DISCJOCKEY_SUPPORT=$(mktemp -d) dist/app/Discjockey.app/Contents/MacOS/Discjockey --self-test` |
| rekordbox and upgrade commands by hand | `DISCJOCKEY_SUPPORT=<scratch folder> DISCJOCKEY_REKORDBOX=<fixture folder or empty folder> bin/discjockey rekordbox status\|preview\|backups\|restore …` (`restore`, `batch undo`, `track undo` and `upgrade discard` need `--yes`; `--dry-run` first), `bin/discjockey upgrade …`, `bin/discjockey aiff convert …` and `aiff rename …` (`--dry-run` first, then the same line with `--plan <id>`), `bin/discjockey batch …`, `bin/discjockey check …`, `bin/discjockey folder add \| remove …` (`remove` needs `--yes`; `--dry-run` first), `bin/discjockey settings show` and `settings set auto-upgrade on\|off`, and the sync with `--dry-run` only (the old words: `bin/discjockey setup --help` / `update --help`, the sync's flags in CONTRIBUTING.md; the rebuilt ones: `bin/discjockey help --json`, see CONTRIBUTING.md > "Commands for scripts and agents"). Never without both overrides on the maintainer's Mac: they would read, and every command `help --json` lists with `writes: true` would write, the real rekordbox library, music folder and support folder. Print both variables before running anything |
| Scratch run (own support folder, asks for a music folder; runs in the terminal) | `DISCJOCKEY_SUPPORT=/tmp/dj bin/discjockey app open` |
| Public check (before every commit) | `scripts/check_public.sh` (`--dir DIR` scans a folder instead of the tracked files); the maintainer adds `--require-denylist`, which fails when the denylist file is missing, unreadable or empty |
| Public tree, trial | `scripts/make_public_tree.sh --dry-run --email <id>+TheZwiss@users.noreply.github.com` (the real run only at the go-moment, `docs/issues.md`) |
| Release | bump `__version__` + `pyproject.toml`, commit, `git tag v<version>`, push the tag by name (`git push origin v<version>`, never `--tags`/`--all`/`--mirror`) → `release.yml` makes a draft release; the maintainer publishes it by hand (`CONTRIBUTING.md`) |

Never start a real sync, upgrade swap or Qobuz download yourself: it touches the user's library and counts against
their Qobuz daily limit. Long commands run in the background with a status line.

---

## Invariants

- **Never delete or overwrite a music file.** Replaced files move to `Superseded/`. Every file change goes through
  `library.run_op`, or `library.move_files` / `move_path` for moves (the file journal; crash-safe, resumable, across
  drives). A new code path that writes into `Library/` or a watched folder without one of them is a bug.
- **Names in `Library/` are always `Artist - Title.<ext>`** for files Discjockey downloads or adds — no `(v2)`,
  `(new)` or similar suffixes; those exist only in `Superseded/`. The one exception: a file that is in the way of the
  correct name gets an ID added. **Moving never renames:** a move (a tidy-up, its undo, a folder rename) keeps each
  file's name, so rekordbox's (Auto) Relocate finds it by that name. A file gets a new name only in a step the user
  chose that points every rekordbox track of that file at the new name itself, while rekordbox is closed (Convert to
  AIFF, Same track for a file that isn't AIFF by hand or through Auto-upgrade, Give it its clean name, Download again
  for a song whose file is missing and whose better version is waiting). That step is refused when it can't.
- **Files move only in a batch the user started:** a move batch (tidy-up, the Playlists save question, a folder
  rename on disk) or an AIFF batch (Same track, Convert to AIFF, Give it its clean name, Download again with a better
  version waiting, Upgrade all, Make all lossless files AIFF), logged in `library.db` and undoable. The sync itself never moves a file (option A), with one
  exception: **Auto-upgrade**, a switch that is on by default and shown in Setup and Settings, is the user's standing
  go for Same track on upgrades that need no decision (a measured same edit) while it is on. The sync then runs them
  as one AIFF batch at its end, only while rekordbox is closed, with the same backup, journal and undo as a batch
  started by hand. Switched off, the sync puts in no upgrade of its own accord. One thing runs with the switch on or
  off: the sync's last batch also places the better version already parked for a song whose file is missing and that
  the user asked for with Download again (issue 43). That is the user's go for that song, not a standing one: it
  runs only while rekordbox is closed, with the same backup, journal and undo, and it moves and deletes no file of
  the user's (the missing file is not there; the parked download goes where the download would have).
- **Qobuz protection stays on:** pacing, the daily limit with carry-over, and the pause after 3 failures in a row.
  Never add a path that skips them, not even for tests against the real service.
- **Tests are offline and never touch the user's data.** Use `tmp_path` libraries and the fixtures; no real Spotify,
  Qobuz or yt-dlp calls.
- **One writer at a time:** the library lock (`.lock`) is shared by console runs and hub jobs; hub write methods
  answer `busy`/`console` instead of waiting. The exceptions are brief saves that answer at once and start no job.
  `set_favourites`, `set_crate_shown` and `set_crates_shown` take no library lock: they wait up to 1.5 s on
  `library.db`, then answer `busy`; that is safe because no job writes those records. `setup_skip_import` and every
  other settings save outside a job take the library lock only for the moment of the save (`lock_briefly`: `busy` while
  a job writes, `console` while a terminal run does). Every read-change-write of a support-folder file (settings,
  config, the login files, `tools/`) holds the support lock (`.support.lock`) for the change: it waits 2 s, then
  answers `busy` with the reason `support_lock`. **Lock order: support lock, then library lock, then `rekordbox.lock`**
  (never a lock after a later one): a settings write (`HubApi._update_settings`, `set_music_folder`) takes the support
  lock around the read-change-write and the library lock briefly inside it (`lock_briefly`), so a settings job
  (`_settings_job`, `hold_library=False`) holds no library lock for its run. rekordbox readers take `rekordbox.lock` shared and without waiting,
  and never open master.db while a writer holds it (they answer `writing`); a writer retries for 2 s.
- **Bridge methods never reject:** `{"ok": true, …}` or `{"ok": false, "kind", "message"}`; write methods return a
  `job_id` and finish with a `JobFinished` event, except the brief saves above, which answer their result at once
  and start no job.
- User-facing text is plain English for a non-technical DJ — no jargon, no stack traces (see the manual's tone).

---

## Principles

- **No band-aids.** Trace a bug to its root cause; never patch the symptom in the UI when the engine is wrong.
- **Refactor when necessary.** If a fix needs a poorly designed function reworked, rework it instead of building on it.
- **Think long-term, check for debt.** Before finishing, ask whether the change adds technical debt; if it does, find
  the better design.
- **Be independent.** Fix problems you notice on the way; note the ones out of scope in `docs/issues.md`.
- **No new dependencies without a reason** stated in the commit. Versions in `hub-ui/package.json` are pinned exactly.
- **Agent-ready.** An AI agent the user points at Discjockey must be able to do everything the user can do in the hub,
  without the window. That means a console command for every action and every screen's state. Each command runs without
  prompts (confirmations as flags), can print `--json`, and ends with an exit code that tells success, busy and failure
  apart. Every command is listed by `discjockey help --json`, generated from the catalogue
  (`discjockey/hub/catalog.py`). A new or changed hub action brings its command and its catalogue row in the same
  change. An agent's command counts as the user starting it, so the same invariants hold: the lock, Qobuz protection,
  never deleting a file, moves only in batches the user started, and a dry run where the hub has one. How to use them
  is in CONTRIBUTING.md > "Commands for scripts and agents"; issue 39 holds the audit of today's gaps.

## Critical rules

- No placeholder code, `TODO` comments, `# ...rest of code` or "similar to above". Every function is fully
  implemented, with its error handling and edge cases.
- Never skip files or leave a component half done: all states (loading, empty, error, busy) are handled.
- If something fails, fix it before moving on.
- **Done means verified:** `uv run pytest -q` green; for any `hub-ui` change also `npm run verify`, `npm run build`
  and `npm run smoke` green; for visible changes, screenshots in fake mode (and the real window where the fake can't
  show it) looked at by you. Ask the user only for what needs a human: sound, feel, rekordbox, decisions.
- **Scale the checks to the change; the full suite runs once.** `npm run verify` takes about 20 minutes (its rule
  checker shoots every page), so it runs **once per branch, before the merge**, never after each fix or review round.
  The full Python suite runs in parallel (pytest-xdist, `-n auto --dist worksteal` is the default) in about a minute: run it once at the
  end of a task, with `| tail -3`, never after each edit. CI (`check.yml`) runs it again on every branch push.
  While working and for a fix, check only what changed: `npm run check`, the touched tests
  (`npx vitest run <file>`, `uv run pytest -q tests/test_<x>.py`), `npm run rules -- --page P --only <shots>` for
  the shots it affects, one screenshot or a measuring script for a visual or motion fix, and `npm run build` when
  the user will run the app. Anything over a minute goes in the background with a status line.
- New behaviour gets tests: new engine logic in `tests/`; the window's formatting in a pure `*Model.ts` / `*.ts` with a
  `*.test.ts` next to it; a fake scenario + `shots.json` entry for each new screen state. The window computes no fact,
  decision or state (design §9.1): a `*Model.ts` only formats what the engine sent, and the `derive` and `flows` checks
  enforce it from phase 5. Design §9.1 in words: a computation the window does today **moves into the engine**
  (`HubApi`, the pure `views.py`, `words.py`) when it does any of: (a) decides which items an action applies to, what it
  will do, or whether it may run; (b) produces a fact, count, order, state, colour/tone or dimming the person reads; (c)
  produces a sentence that carries data. It **stays in the window** only when it is: layout and geometry; which panel,
  menu, dialog or fold is open; focus, selection, scroll, hover; audio playback; timers and animation; an unsent draft;
  per-window view preferences (the sort and filter remembered per view, A–Z, widths, folded sections, details hidden).
  Where the window *uses* a moved answer, it calls the bridge field instead of its own copy, and the copy is deleted in
  the same change.
- **UI work reads `docs/hub-design-language.md` first; pages use only the blocks; a missing pattern is added
  centrally (block + gallery + doc), never built in a page.** The core rules, in short:
  - More space shows more, never bigger: fixed sizes; extra width shows columns, extra height shows rows.
  - One filled button per screen (per dialog in a dialog).
  - Choices are `ToggleGroup` rows or `Segmented`, never loose pills.
  - No prose on the background: one-line `Hint` under its control, `InfoTip`, or `NoteCard`.
  - Pages use only the blocks; a missing pattern is added centrally.
  - `npm run verify` (it runs the rule checker) green before the merge; per fix, `npm run rules` on the touched shots.
  - Improve, don't preserve: critique what you touch (edges, grouping, space at 1100 and 2560, hierarchy,
    consistency, intent) and fix what you find; consistency is absolute; every change names a reason, system changes
    happen once in the block, and taste goes to the user (spec §12).

---

## Docs and plans

- **Everything tracked is public.** Never write a home path, a real name or a private address into a tracked file
  (made-up `/Users/you`, `/Users/dj` and `example.com` are fine); `scripts/check_public.sh` must pass before every
  commit (the maintainer's checkout has the denylist, so there it runs with `--require-denylist`).
- **Contract:** a change to an answer of `api.py`, a shape of `views.py` or a job result changes its TypedDict in
  `discjockey/hub/shapes/` and regenerates (`uv run python -m discjockey.hub.shapes --export`), and the fake's builder
  of that payload, in the same commit; `client.ts` (the `Bridge` signature and its answer type) when a method's
  parameters or answer shape change, and `contract.ts` when a bridge method is added or removed;
  `docs/hub-bridge-contract.md` when a rule changes. An event changes its dataclass,
  `tests/fixtures/hub_events.schema.json`, `hub-ui/src/lib/bridge/events.ts` (type and `EVENT_FIELDS`), the fake's
  emitter and the doc's Events section, in the same commit.
- **Design language:** any change to `hub-ui/src/lib/styles/tokens.css`, a frame or a block updates
  `docs/hub-design-language.md` (and the gallery) in the same commit; a system-level design decision goes into its
  decision log with its reason.
- **Manual:** update `docs/manual.md` when user-visible behaviour, commands or folders change. Not for internal refactors.
  `README.md` is the short landing page (what it is, download, install, quick start); touch it only when one of those changes.
- **Issues:** a bug or wish you find but don't fix goes into `docs/issues.md` (newest on top); remove the entry in
  the commit that fixes it.
- **New specs and plans** go in `docs/` as `YYYY-MM-DD-<topic>-design.md` / `-plan.md`.
- **Plans are designs, not pre-written code.** A plan fixes the decisions, not the lines of code. It covers the
  architecture, each task's files, the exact interfaces between tasks (names, signatures, event and data shapes), the
  binding values (URLs, limits, words the user sees) and the behaviours each task's tests must pin, with the reason
  for each decision. It leaves out full code and full test bodies, except a short snippet where the exact form is the
  decision. The implementer reads the code and writes the exact implementation and tests. A planner reads only what
  the design depends on. Where it isn't sure, it writes "check first: …" into the task, and the implementer does
  that check. Aim for about 300–600 lines. **This overrides the `superpowers:writing-plans` skill** where they
  conflict: its "complete code in every step", "no placeholders" and "code blocks required" rules don't apply here.
  A "check first: …" step, or a behaviour to test without the test's body, is not a placeholder.
- **Finished plans must always be archived.** When a plan's last task is done (or the user drops it), in the same
  change: move the plan, its design spec and any handover or test-sheet files that belonged to it into
  `docs/archive/` (`git mv`), and carry every task or gap still open into `docs/issues.md`. `docs/` top level holds
  only living documents and plans in progress.
- **`docs/archive/pre-public/`** holds the specs and plans archived before the repo went public. It is gitignored:
  it exists on the maintainer's disk only, never in a public clone. Docstrings cite these specs; open one only when
  you need the reason behind a decision, and if it isn't there, go by the code and its tests.
- **Don't read `docs/archive/`** unless the user asks or you need the reason behind a decision. Code docstrings cite
  sections such as `spec "hub" 6.8`, `spec sources-and-limits §2` or `spec settings-setup §13`; those are
  `docs/archive/pre-public/2026-10-15-hub-design.md`, `docs/archive/pre-public/2026-10-18-sources-and-limits-design.md`
  and `docs/archive/pre-public/2026-10-22-settings-setup-design.md` (engine spec:
  `docs/archive/pre-public/2026-10-13-dj-sync-design.md`). Open the
  cited section with a search, never the whole file — the plans run to thousands of lines.

---

## Git

- Commit messages: `type(scope): what changed, in plain words` (`feat`, `fix`, `test`, `docs`, `build`; scopes like
  `hub`, `hub-ui`, `sync`, `upgrades`). The rebuilt `discjockey/hub/static/` goes in its own `build(hub): static` commit.
- Larger work on a branch (`fix/<topic>`, feature names), merged into `main` with `Merge <branch>: <summary>`.
- `archive/*` branches and tags (the maintainer's local copy of the private history from before the repo went public)
  are never pushed, merged or used as a base; a new branch starts from `main`. The maintainer's checkout has a local
  pre-push hook (`scripts/public_push_guard.sh`, installed at the go-moment) that refuses any push carrying that
  history; never skip it with `--no-verify`.
- Never commit secrets: `.spotify_*.json`, `.streamrip/`, `settings.json` stay ignored.
- Commits use the GitHub no-reply address (`<id>+TheZwiss@users.noreply.github.com`) set in this repo's own git
  config, never a personal e-mail (spec public-release §9).
