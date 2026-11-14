# CLI audit, area `todo` (issue 39, step 1)

Area: the To-do page (`hub-ui/src/pages/todo/`), the shared decision components and flows it hosts
(`hub-ui/src/lib/decisions/`: upgrade cards and batches, Same track, Replace/Discard, Upgrade all, Convert / Rename /
AIFF batches, check cards, the CDJ group, duplicates), "Find a version" / "Wrong song?", the bought file (drop),
Hide, batch resume and undo, rekordbox backups / restore, and the README sections "Reports and not_lossless.md",
"Upgrades" (incl. "Upgrade automatically when I sync"), "Making files AIFF", "rekordbox".
Sources read: the pages and libs named, `discjockey/hub/api.py` (by method), `views.py` (todo, check_view, upgrade_block,
track_detail), `batch_cmd.py`, `convert_cmd.py`, `rekordbox_cmd.py`, `settings_cmd.py`, `cli.py`, `app_main.py`,
CONTRIBUTING.md "Commands for scripts and agents", README sections above, the four stage plans' live-test sections.
Nothing was run against real data; one in-process `cli.parse_args` call (pure argparse, no data) was used to check
flag placement (section 5).

## 0. What the designer must know first (the short list)

1. **There is no read command for the To-do list.** `todo()` (api.py:937) is the only read of all groups; the console has
   `upgrade list` (Upgrade ready only), `convert --all cdj --dry-run` (the CDJ plan) and `batch list|show` (batches). There
   is none for: open rekordbox checks and which of them `can_undo`, Same song questions, Duplicates, Not found, Weak,
   Good lossy, Fake lossless, Other, hidden tracks, the chip counts, `check_tracks`.
2. **Hub-only state the console cannot see.** (a) `HubApi._store.prep` (the last playlists read's plan: the "Is this the same
   song?" questions and the same-song duplicate groups, `_todo` api.py:603, `_decided_now` api.py:719) lives in memory;
   (b) `_shown[track_id]` (api.py:554 `_remember`, called by `todo`/`track`) is the snapshot every single-track write is
   compared with (`ops.run_single` ops.py:81: `snapshot(entry) != expect` -> `changed`): `hide`, `use_candidate`,
   `use_link`, `reject_current`, `add_bought_file`, and one-track New track / Discard (`_each_work` api.py:2014) are
   refused with "changed" unless this hub process showed the track first; (c) `_dropped` (the file of the last OS drop,
   api.py:1389 `_on_drop`) and `_selected` (`select()`); (d) the duplicate/answer precondition `shown` (paths "as the card showed
   them", folders.py:`_current`). A command has no such memory: each needs an explicit "I looked at this" token or none.
3. **The window composes the rekordbox to-do steps itself** (`decisionModel.ts:checkCard`, `batchCheckCard`,
   `replacedCard`). The engine only has one sentence per check (`report.check_text`, in `views.check_view().text`) and
   `report.USB_STEP`. Console output after `upgrade apply` / `convert` prints only the USB line (batch_cmd.py:252-254),
   not "Reload Tag / Analyse again / Relocate". An agent that upgrades must tell the user what to do in rekordbox, and
   no command gives the steps.
4. **Duplicated rules, two copies:** `eligible.same_track_quick` + `rekordbox/preview.py:REASON_WORDS` (24 keys, engine)
   vs `decisionModel.ts:SAME_TRACK_WHY` + `WHY_NOT_LINE` (UI, shorter words); `candidate_row`'s `length_ok` / `matches`
   (engine) vs `candidates.ts:lengthTone/matchTone` (UI thresholds 3 s and 80 %, the engine fields are ignored);
   `groupIdOf` (UI) vs `models.group_id` (engine); `cdjAllKeys` (UI) vs the CDJ plan.
5. **Console batches are invisible to the window's Resume links for convert batches:** `convert`/`rename` start batches with
   `scope="console"` (convert_cmd.py:293) but the CDJ head asks `stopped_batch(scope="todo:")` (api.py:641) and the Library
   header `library:`; so a stopped console Convert is resumable only by `batch resume <id>`. Upgrade batches have no scope
   filter (`kinds=("upgrade",)`, api.py:639) and do show.
6. **`bought_name` is always `.wav`** (views.py track_detail: `Library/<folder>/<stem>.wav`) while `add_bought_file` accepts
   WAV, AIFF, FLAC, MP3 (ops.py:166-172) and names the result `.aiff` for FLAC/MP3.
7. **From the app bundle, the bare sync with flags is not reachable**: `app_main.py:34` hands only a first argument that is
   in `CLI_COMMANDS` to the CLI; `Discjockey --yes --json` falls through to the window (app_main.py:38-41). README
   ("`--yes --json` after the program runs a sync") and CONTRIBUTING read as if it works for the app.
8. Issue 41 (To-do multi-select for Hide, Find a version, Mark as bought) is open: those actions are one-track in the window
   today; the rule "one, a selection, or all eligible" applies to the new commands.

---

## 1. Actions and reads

Legend: trigger = where the user presses it. "lock" = the library lock (`jobs.start` takes it; console `library.run_lock`).
"Long run" names the events of the job (`JobStarted`/`JobFinished` are always there and are left out).
`none` = no console command.

### 1.1 Reads

| Method (api.py line) | Trigger | What it does | Hub's own safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `todo(filter, show_hidden)` :937 | To-do page load (`Page.svelte:188 load`), after every finished job (`filesVersion`), filter / Show hidden change, drive events; the Library page for `decisionFor`; the sidebar count uses `_todo(count_only)` | Reads library.db/state, the last plan (`prep`), db duplicate groups, per-file presence (`batches.present` stat per parked-upgrade/CDJ file), rekordbox cached status, the CDJ plan (one read-open of rekordbox's library; cached by records generation `_cdj_cache` api.py:644). Side effect: `_remember` fills `_shown` | read only, no lock, works during jobs (cached rekordbox state, no lookup) | no (CDJ plan: seconds) | **none** for the whole read. Partial: `upgrade list --json` (upgrade_ready only, no held songs, no hidden), `convert --all cdj --dry-run --json` (CDJ plan items; no per-row hidden/`aiff` wait reason), `batch list/show` | no list read of: checks (`rekordbox_check` items, `can_undo`, batch items), same_song, duplicate, not_found, weak, good_lossy, fake, other; chips; `check_tracks`; `hidden_count`; `empty`. Same-song questions + same-song duplicates exist only in hub memory (`prep`) |
| `track(track_id)` :906 | selecting an item (`Page.svelte:281 loadTrack`), after every job | the details payload: `views.track_detail` + `upgrade` block + `aiff` card (`plans.file_answer`) + rekordbox status; `_remember` | read only | no | **none**. Partial: `rekordbox preview <key> --json` (eligible per action, timing, entries, new_file; no quality/source/links), `upgrade list` rows (now/new/alignment/same_track/auto_*) | no per-track details read: status, quality_label, cutoff_hz, quality_line, format_line, source_*, source_how, next_qobuz_check, rejected_sources, buy_links, free_downloads, bought_name, hidden, upgrade block, aiff card, file_state, place, playlists |
| `select(track_id)` :1163 | each selection change (`Page.svelte:277`) | sets `_selected` (hub memory) so a dropped file goes to that track | none | no | none | only meaningful for drops; a command takes the track in the argument |
| `spectrum(track_id, which)` :1130 | details open (`Details.svelte:64 loadSpectra`), the Library | decodes the file (ffmpeg) into the picture: `{cols, bands, max_hz, duration_s, floor_db, data (base64 dB matrix), waveform (base64 peak envelope), which, cutoff_hz}` (`hub/spectrum.py:63`) | read only, off the window thread | seconds per file | none | the numbers behind the picture (see 3b) have no command; `rekordbox preview` decodes but returns no spectrum |
| `media_url(track_id, which)` :1140 | no UI caller (`client.ts:40` only) | mints a local media-server URL for a file | read only | no | none | not for agents (a person listens); a path is enough for an agent |
| `rekordbox_status()` :775 | `AiffFlow.read` (flows.svelte.ts:111: card shows, window focus, after a job), the Sync page | `{state: ready|none|unreadable, running}`; state cached on master.db mtime+size | read only, no music folder needed | no | `rekordbox status --json` (rekordbox_cmd.py:81): more fields (`version`, `library`, `problem`, `db_version`) | bridge lacks `problem` (unclean/busy) and version; console answer is fresh each call, hub's is cached |
| `job_status()` :876 | the hub store poll; `Page.svelte:112,121` `adopt` of a batch the window did not start | current/last write job snapshot (`kind`, `track_id`, `batch_kind`, `last` events incl. `BatchProgress`, `stopping`), `console_running`, read status | read only | no | none. Poll a console batch with `batch show <id> --json` (no lock; states running/stopped/done and items) | no "what is running now" for other processes; a hub job started elsewhere can't be seen from a command |
| `aiff_plan(scope)` :929 | AiffBatchPanel opens / scope changes / `filesVersion` / window focus (`flows.svelte.ts:394 load`); scopes `{tracks}`, `{lossless, view, key}`, `{cdj}` | `AiffPlan.to_dict()`: items, skipped, waiting, kinds, lossy, total, space per drive, superseded_bytes, rekordbox `{state, running, needs_closed}`; reads tags (cached) and one read-open of rekordbox | read only; off thread | seconds | `convert <keys> | --all lossless [--in …] | --all cdj --dry-run --json` (convert_cmd.py:259; same object); `rename … --dry-run` = `only="rename"` plan | console dry run fills missing audio facts first (takes the lock, writes library.db, convert_cmd.py:261-264); console's CDJ `held` lacks the plan's questions and same-song duplicates (convert_cmd.py:183-197) |
| `setup_status()` :1149 | Settings › Upgrades reads `auto_upgrade` (`UpgradesPanel.svelte`) | settings/tools/logins summary; key `auto_upgrade` (missing key = on) | read only | no | `settings auto-upgrade --json` (reads the one key) | other keys: other audit |
| `runs()` :1118, `run(run_id)` :1122 | Dashboard / All runs / Sync end (README "Reports and not_lossless.md") | list and one run's report JSON (`reports/<time>.json`) | read only | no | none; the sync's `--json` returns `report` (path of the `.md`); `.json` beside it | no command lists reports; an agent reads `.discjockey/reports/` by hand |
| `open_report(run_id)` :1200 | "Open report" on cards | opens `reports/<id>.md` in the default app | id must match `RUN_ID`, path inside the music folder | no | none | person-only action; agent reads the file |

### 1.2 Writes: upgrades, checks, batches

| Method | Trigger | What it does | Hub's own safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `upgrade(track_ids, mode)` :2117 `mode=swap` | "Replace with lossless" with Same track picked (`UpgradeFoot` -> `UpgradeFlow.upgrade` flows.svelte.ts:55; `UpgradeSelection.replace` :60 -> `UpgradeBatchFlow.start` :274) | one AIFF batch (job `upgrade_batch`, `batch_kind` upgrade, `started_by` user): per track `batches.run`: AIFF audio swapped in place, or a new AIFF + rekordbox track pointed at it (**writes master.db**), old file to `Superseded/`; one backup per batch; records the batch in library.db | lock; rekordbox must be closed for tracks that need a rekordbox write (`rekordbox_open` stops the batch, rolls the track back); refusal per track with reason; batch of one: closed instead of stopped; Stop between tracks; undo until Done; no confirm for Replace (UI hint only) | yes: `BatchProgress` (batch_id, done, total, track_id, name) | `upgrade apply <keys…> --way same-track [--dry-run] [--json]` (batch_cmd.py:559) | UI sends only items for which `goes(i,'swap')`; the console sends all named keys and the engine skips (results list them); no `_shown` check in console |
| `upgrade` `mode=add_new` | Replace with New track picked | per track one after the other, job `upgrade_add_new`, no batch record, no backup; new AIFF placed, old to `Superseded/` | lock; one-track precondition `_shown` (`changed`); Stop between tracks | yes: `BatchProgress(batch_id=0, …)` | `upgrade apply <keys…> --way new-track` | `--all` is refused for new-track (batch_cmd.py:560) |
| `upgrade` `mode=discard` | "Discard the new version" / "Discard n new versions" (confirm in UI: `flows.svelte.ts:56`, `decisionModel.ts:discardConfirm`) | deletes the parked file in `Upgrades ready/` (Discjockey's own download), the version is never offered again; job `upgrade_discard` | lock; UI confirm only (engine none); one-track `_shown` check | yes: `BatchProgress(0,…)` | `upgrade discard <keys…> [--json]` (batch_cmd.py:588) | no `--dry-run`, no `--yes` (the window confirms); irreversible deletion of Discjockey's own file |
| `upgrade_all()` :2135 | "Upgrade all · n" head link selects the group; Replace with the whole group (`Page.svelte:329 upgradeAll`, `UpgradeBatchFlow.start(..., all=true)`) | recomputes the list itself: `_todo(upgrade_ready)` items with `same_track is None`, not hidden; one batch, `started_by upgrade_all` | as swap; `refused` "no upgrades" when none | yes: `BatchProgress` | `upgrade apply --all --way same-track` (batch_cmd.py:571-575) | console list = `views.upgrade_ready_keys(state)` with no `held` (batch_cmd.py:337; docstring views.py:1522 says the console cannot know `held`); neither refuses while a stopped batch waits (the window hides "Upgrade all" then and shows only "Resume") |
| `batch_resume(batch_id)` :2198 | "Resume · k left" (panel and group head: `Page.svelte:334 resume`, `:346 resumeCdj`) | runs the `planned` tracks of a stopped batch again (each asked again); job `batch_resume`, `batch_kind` of the row (upgrade/convert/mixed) | `ValueError` for unknown/not-stopped; lock; same rekordbox rules | yes: `BatchProgress` | `batch resume <id> [--json]` (batch_cmd.py:702) | window decides which flow follows by `batch_kind` (flows.svelte.ts:241); head link visibility by `scope` prefix (note 5) |
| `batch_undo(batch_id)` :2208 | **no UI caller** (the window undoes by track ids) | undoes every track a batch did, newest first; job `batch_undo` | lock; rekordbox closed where a step wrote it (`rekordbox_open`) | yes: no BatchProgress; `UndoResult` at the end | `batch undo <id> [--json]` (batch_cmd.py:715) | UI "Undo all" on a batch card uses `undo_upgrade(ids)` of the card's can-undo tracks (`undoFoot`), which can differ from "the whole batch" |
| `undo_upgrade(track_ids)` :2215 | "Undo the replace / conversion / clean name", "Undo all n", "Undo n", "Undo this one", "Undo all from this sync" (`flows.svelte.ts:72`, `:222`; confirm `undoAsk`) | puts files back (swap: old audio back in the file; added/new AIFF: old file back, new waits in Upgrades ready again), rekordbox track/text back (**master.db**), records; refuses per track (file changed since, relocated); job `undo_upgrade` | lock; confirm in UI; per-track refusal; whole job `refused` when nothing could be undone; rekordbox closed | yes | `upgrade undo <keys…> [--json]` (batch_cmd.py:636) | no read of which tracks `can_undo` (engine `upgrades.can_undo`, upgrades.py:764); UI offers only `can_undo && !refused` ids |
| `rekordbox_checked(track_ids)` :2096 | "Done, checked in rekordbox" (`flows.svelte.ts:64`, `:213`) | drops the track's `rekordbox_check` and with it the undo; for a swap deletes Discjockey's kept copy of the new version and releases the backup (README "Upgrades"); job `rekordbox_checked` | lock; `changed` when nothing to check; **no confirm** (undo ends) | no | `rekordbox checked <keys…> | --batch <id> [--json]` (batch_cmd.py:725) | no list of open checks to take keys from |
| `convert(track_ids, origin)` :2161 | "Convert to AIFF" / "Give it its clean name" (`AiffFlow.run` :125), AIFF panel for a selection or the CDJ list (`AiffBatchFlow.start` :417) | one AIFF batch (job `aiff_batch`, `batch_kind` convert): per file the engine decides Convert or clean name only (`eligible.aiff_action`); renders AIFF 16-bit/44.1, tags + cover, name `Artist - Title.aiff`; old file to `Superseded/`; rekordbox track pointed at it (**master.db**) while closed; facts filled first; `origin` library/todo = batch `scope` `<origin>:selection` | lock; backup; Stop between files; undo; space; refusals per file; one song = batch of one | yes: `BatchProgress` | `convert <keys…> [--dry-run] [--json]` (convert_cmd.py) | console batch scope is `console` (convert_cmd.py:293), not `origin:selection` |
| `rename(track_ids)` :2169 | "Give it its clean name" (library origin only) | as convert with `only="rename"`: a clean AIFF gets its clean name; a file that needs Convert is left (`needs_convert`) | as convert | yes | `rename <keys…> | --all [--in …] [--dry-run]` | UI always sends `origin=library` for rename |
| `make_aiff(scope)` :2175 | "Make AIFF…" (Library, other audit), "Convert all · n" head link / Convert with the whole CDJ group selected (`Page.svelte:341 convertAll`, `wholeCdjGroup`) | plans again, runs the plan's items as one batch; `{kind:"lossless", view, key}` (`started_by make_aiff`) or `{kind:"cdj"}` (`cdj_all`, scope `todo:cdj`) | as convert; nothing to change ends `refused` | yes | `convert --all lossless [--in playlist:<name>|folder:<path>|unlisted]`, `convert --all cdj` | console `--in` syntax differs from the bridge's `{view,key}`; CDJ `held` differs (note above) |
| `stop()` :1724 | Stop in batch panels (`UpgradeBatchFlow.stop`, `AiffBatchFlow.stop`), the foot | cancels the running write job after the current item | any job | n/a | Ctrl-C of the console process: once = stop between tracks (exit 5), twice 1 s apart = at once (batch_cmd.py:165-188) | no command stops a run in another process |
| `set_auto_upgrade(on)` :2318 | Settings › Upgrades switch, Setup › Downloads (`UpgradesPanel.svelte:set`) | saves `settings.auto_upgrade`; job `set_auto_upgrade`; turning on moves nothing until the next sync | lock; bool check | no | `settings auto-upgrade [on|off] [--json]` (settings_cmd.py:28) | none (the read without a value exists) |

### 1.3 Writes: the other groups (same song, duplicates, find a version, bought file, hide)

| Method | Trigger | What it does | Hub's own safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `answer_same_song(song_key, own_key, same)` :1836 | "Yes, it's the same song" / "No, keep them apart" (`QuestionDetails.svelte:answer`) | `db.set_decision("same_song", …)` in library.db; then plans again from the last read (`replanned_work`, jobs.py:821; with no `prep` nothing is replanned); no file moves | lock; `ValueError` for bad keys, `changed` when `song_key` is not a playlist song; no confirm | no (job kind `answer`) | **none** | needs the question list (`song_key`, `own_key`): only in `prep`; engine fn `folders.answer_same_song` takes keys |
| `keep_duplicates(group_id, paths)` :1849 | "Keep both" / "Keep all" (`DuplicateFlow.#keepAll` flows.svelte.ts:166) | `db.set_decision("keep_both")`; the group is not asked again | lock; `changed` when the group's files/paths differ from the card (`folders._current`); no confirm | no (kind `answer`) | **none** | `paths` = "as shown": a command must read the group first |
| `supersede_duplicate(group_id, file_id, paths)` :1863 | "Keep the AIFF" etc. (`DuplicateFlow.#keepOne` flows.svelte.ts:172) | moves ONE file of the group to `Superseded/` (journaled, across drives verified copy; never deleted), its row goes, an own song may take over a playlist song (`_heir`); no move batch, no undo; log line | lock; `changed` check (as above); recover_pending first; no confirm | yes: `Message` events only (kind `supersede`) | **none** | "keep one of three" is the window running this twice, recomputing `group_id` (`groupIdOf`) and `paths` after each; the engine has no "keep this one" call |
| `hide(track_id, hidden)` :1757 | "Hide" / "Unhide" (`Details.svelte:96`) | `ops.set_hidden`: sets `hidden` on the record; the to-do list leaves it out; weekly upgrade checks go on; rewrites `not_lossless.md`; log line | lock; `_shown` precondition (`changed`) | no (kinds `hide`/`unhide`) | **none** | UI offers it only for groups `improvable`/`other`/`cdj` and never for checks (`todoModel.ts:actionsFor`); engine accepts any track |
| `add_bought_file(track_id)` :1885 | drop a file on the selected to-do (`BoughtFile.svelte:26`; `FileDropped` event) | copies the dropped file into `.tmp`, FLAC/MP3 -> AIFF there, places it under the expected name where a lossless replacement goes, adopts it like a bought file (`ops.add_bought_file` ops.py:156); old lossy file to `Superseded/` by the planner | lock; `_dropped` must be this track's (`NO_DROP` refused); `_shown`; refuses lossless tracks, other formats, a name taken | no (kind `add_bought_file`) | **none** | the file path lives in hub memory from the OS drop; the engine function takes `src: Path`, so a command can take a path. README "Reports and not_lossless.md": saving the file under the exact name by hand also works (next sync adopts it) |
| `search_candidates(track_id)` :1665 | "Wrong song?" / "Find a version" dialog opens (`WrongSongDialog.svelte:39`) | searches Qobuz (logs in), YouTube Music, SoundCloud, YouTube; scores; `{candidates[], notes[], track_duration_s, current_quality_label}`; each candidate `{source, id, title, artist, duration_s, url, key, score, matches, length_ok, length_diff_s, can_preview, current, rejected}` | refused while a sync runs (`_no_sync_running` :1301, `sync_running`); skips DRM-protected (`candidates.protected`) | seconds | **none** | candidates exist only in the result; `use_candidate` needs the row sent back (`to_candidate` needs `url` unless Qobuz) |
| `preview(track_id, candidate)` :1697 | ▶ on a candidate | downloads a 20-second clip into the cache, returns a media URL | no sync running; `protected` removes the row | seconds | none | person listens; not for agents |
| `use_candidate(track_id, candidate)` :1898, `use_link(track_id, url)` :1908 | "Use this", "Use link" | downloads the version (Qobuz counts against the daily limit), replaces the current file (old to `Superseded/`), records rejected sources; job kinds `use_candidate`/`use_link` | `ops.refusal` (budget, accounts, DRM `protected`), Qobuz streak counters, `_shown` precondition, lock | yes: `StepChanged`/`Progress`, `SourceChosen`, `AccountUsage` | **none** | needs a stable candidate reference |
| `reject_current(track_id)` :1921 | "None of these" (confirm `candidates.ts:NONE_CONFIRM`) | the current file moves to `Superseded/`, its source is marked rejected, the next sync searches again | confirm in UI; lock; `_shown` | no (kind `reject_current`) | **none** | |
| `show_in_finder(track_id, which)` :1172 | "Show in Finder" (Other group, `Details.svelte:finder`) | `open -R` on the file | file must be in the library | no | none (`upgrades_cmd.py` interactive "f") | person-only; an agent prints the path (`upgrade list` `file`) |
| `open_external(url)` :1216 | buy links (Beatport, Bandcamp), FREE download links, source link, "Open in Spotify/Qobuz" | opens the system browser | http(s) only | no | none | person-only; URLs are in `track()` (`buy_links`, `free_downloads`, `source_url`, `track_link`) |

### 1.4 Used by this area's journeys, owned elsewhere (rows kept short)

| Method | Used for | Today's command |
|---|---|---|
| `start_sync(selected)` :1710 | the sync that ends with Auto-upgrade; stage C test | `discjockey --yes --json` (whole plan; the window can untick actions, the console cannot; no flag to skip downloads or run only the upgrade phase) |
| `sync_preview()` :800 | the before-start line (rekordbox open + upgrades waiting) | `discjockey --dry-run --json` (`counts`, `auto_upgrade` block with `would` rows) |
| `add_watched_folder(path)` :1808 | "imported into a scratch watched folder" (test tracks) | none |
| `refresh(auto)` :812 / `stop_refresh()` :872 | the To-do header's read status | none (shell/sync audit) |

---

## 2. Logic the window does itself

`todoModel.ts` = `hub-ui/src/pages/todo/todoModel.ts`; `decisionModel.ts`, `aiffModel.ts`, `aiffBatchModel.ts`,
`flows.svelte.ts` = `hub-ui/src/lib/decisions/`.

| file:function | What it decides | Engine has it? |
|---|---|---|
| `todoModel.ts:cdjAllKeys` / `cdjReachable` / `wholeCdjGroup` | which CDJ rows Convert all reaches: not hidden and `aiff === null`; whether a selection "is the whole group" (then scope `{kind:"cdj"}`, else the track list) | the CDJ plan (`aiff_plan` scope cdj: `total`, `waiting[]`, `waits`); the UI re-derives the row set from item fields. Known case: console and hub once differed (fixed); remaining difference: console `held` (convert_cmd.py:183) |
| `todoModel.ts:upgradeAllKeys` / `wholeUpgradeGroup` | which rows "Upgrade all" selects: every non-hidden item of the group; whole group => `upgrade_all()` instead of `upgrade(ids)` | `upgrade_all` recomputes (`same_track is None`, not hidden, api.py:2138); count `group.all.n` (views `_upgrade_all` :1721) |
| `decisionModel.ts:goes` + `NOWHERE` (`no_upgrade`, `file_missing`, `away`) | which selected items a way replaces: Same track = `same_track` null; New track = reason not in NOWHERE; the list sent to `upgrade()` is pre-filtered | engine skips per track with a reason; `NOWHERE` list is UI only |
| `decisionModel.ts:selectionWays` / `beforeLine` | n/m/k counts for a selection ("5 upgrades keep their cues. 2 need your choice and stay."), the New track count, whether Same track is offered, "Files that aren't AIFF become AIFF files" | engine only for the whole group (`all {n,m,k}`) |
| `decisionModel.ts:canSwap`, `upgradeWays`, `defaultWay`; `flows.svelte.ts:UpgradeFlow.way` (:48) | whether the "In rekordbox" choice exists (`swap_safe && swap_possible`), the default (Same track), and, with no choice, which mode Replace sends: `swap` for a non-AIFF file when rekordbox state is `none` (a clean new AIFF), else `add_new` | engine has `swap_safe`, `swap_possible`, `swap_how`, `why_not`; **the mode to send is decided in the UI**; console requires `--way` |
| `decisionModel.ts:sameTrackWhy` (SAME_TRACK_WHY), `WHY_NOT_LINE` | the words for each `same_track`/`why_not` reason | `rekordbox/preview.py:REASON_WORDS` (24 keys, different wording) |
| `decisionModel.ts:checkCard`, `batchCheckCard`, `USB_STEP`, `RELOCATE_NEW`, `BEATGRID`, `keptLine`, `inRekordbox` | the numbered rekordbox steps after a replace/convert: Reload Tag (only `reload_tag`), Analyse again (+ "lock the beatgrid first"), Relocate (added file), Auto Relocate (moved), USB stick; per-track lists in a batch; whether a check has anything left (`inRekordbox`: `rekordbox.entries>0`, or `reason==='swapped'` for old records) | `report.check_text` (one sentence per reason), `report.usb_step`; **not** the structured steps |
| `decisionModel.ts:replacedCard`, `undoAsk`, `undoTitle`, `undoLabel`, `doneLabel`, `undoManyConfirm`, `undoneToast` | words of Undo/Done per kind (upgrade / convert / clean name; Done vs "Done, checked in rekordbox") | `views.undone_words`, `UNDONE_*` (job result `words`); the rest UI |
| `decisionModel.ts:undoFoot` | which tracks Undo offers: `can_undo && !refused[track]`; "Undo all {n}" only when all can; "{k} can't be undone"; "Undo all from this sync" when `batch.started_by === 'auto_upgrade'` | `can_undo` per item (`upgrades.can_undo`); the rest UI |
| `decisionModel.ts:batchEnd`, `endRows`, `endNote`, `canTryAgain`, `endWords`, `progressRows`, `runLabel` | the running/ended view of a batch: Resume offered only when `r.batch !== null && r.state==='stopped' && planned left`; Try again for `rekordbox_open`/`busy`/`failed` without Resume; rows done/skipped/failed/left with reasons; sentences ("Stopped after 2 of 4", "rekordbox was opened, so Discjockey stopped after 3 of 8") | `BatchResult` (`state`, `stop_reason`, `results[]`); console prints its own sentences (batch_cmd.py:226-300) |
| `decisionModel.ts:groupIdOf` + `flows.svelte.ts:DuplicateFlow.#keepOne` (:172) | the id of the group left after a file moved (`dup:<sorted ids>`), the loop of one `supersede_duplicate` job per file that goes, stop on first failure, toast "Moved n files to Superseded/." | `models.group_id`; the loop and `paths` bookkeeping are UI |
| `decisionModel.ts:keepWords`, `fileWords`, `keepLabel`, `fileFormat`, `lastFolder`; `DuplicateFlow.pick` (:159) | the button "Keep the AIFF / the lossless file / the one in Old"; default pick = `pair.recommended`; "Goes to Superseded/" per other file | engine gives `recommended`, `recommended_why`; label rules UI |
| `decisionModel.ts:decisionFor` | which decision a track waits for in the Library: check > duplicate > upgrade | no |
| `decisionModel.ts:autoNotes` | one of two: "waits for rekordbox" else the refusal (mirrors `views.upgrade_detail`) | yes (`views.upgrade_detail` api.py list `detail`) |
| `decisionModel.ts:checkTracks`, `batchRowName`, `batchRowSub`, `batchListTitle`, `checkRow` | batch row words ("3 tracks upgraded", "today · Same track", "Made AIFF", "Clean name", "Upgraded during your sync"), per-track row notes | `batch.kind`, `started`, `started_by` fields only |
| `todoModel.ts:headerSub` | the page's sub-line: sums chips (`upgrade_ready+not_found+weak+good_lossy+fake+other` = "not lossless yet"; questions = `same_song+duplicate`), `check_tracks`, `cdj`; "Nothing to do" | engine gives `chips`, `check_tracks` |
| `todoModel.ts:segOptions`, `FILTER_ORDER`, `FILTER_LABEL`, `FILTER_DOT`, `FILTER_MAX` | the filter strip: short labels, order, which groups show (zero hidden except All and the chosen), dot colour, five before "More" | engine `TODO_GROUPS` labels (views.py:1490), chips |
| `todoModel.ts:itemKey` | an item's identity: `group/track_id`, `same_song/<song_key>/<own_key>`, `duplicate/<group_id>`, batch `key` `batch:<id>` | only batch items carry `key` |
| `todoModel.ts:MULTI_GROUPS`, `multiScope`, `multiCdj`, `multiChecks` | which groups may be selected several at once (upgrade_ready, rekordbox_check, cdj) and what two or more selected mean | no |
| `todoModel.ts:actionsFor` / `IMPROVABLE` | which controls a track offers: listen, versions `find` (missing) vs `wrong_song`, `noneOfThese` (not for missing), buy links and drop zone (`missing`/`not_lossless`/`fake_lossless` and not a lossless-version upgrade), hide/unhide (improvable, other, cdj; never for checks), upgrade `{swap, primary}`, showInFinder (other group, file there), rekordboxDone (check group), the foot's one filled button `main` | no "what can I do with this item" answer in the engine |
| `todoModel.ts:rowOff`, `rowWaits`, `rowDim`, `rowBadge`, `queueRows` | dimmed rows (not in a playlist, except pair/cdj/check; away; CDJ file that waits), the badge (a batch with mixed qualities = "MIXED"; a question shows its file's quality), which rows ▶ queues | `in_playlists`, `file_state`, `aiff`, quality fields |
| `todoModel.ts:compareLines`, `filePlace`, `fileFolder`, `linkService`, `NO_VALUE` | the Same song table (title/artist/length/where; which line differs by `why`; home as `~`; drive name first; "Open in Spotify/Qobuz") | `pair` data, `why`; no composed lines |
| `todoModel.ts:qobuzText`, `freeHint`, `filedAs` | "not there yet · looks again on 20 Oct", free-download hint, "will be filed as Library/…/Artist – Title" | `next_qobuz_check`, `free_downloads`, `bought_name` |
| `todoModel.ts:dropDecision` | which dropped file is taken (`track_id` must be the selected one; unreadable -> message; nothing selected -> shell toast) | `_on_drop` api.py:1389 (readability, `NOT_SELECTED`) |
| `todoModel.ts:keepSelection`, `selectFromTrack`, `selectAfterHide`, `heldChecks`, `withHeldItem`, `ghostOf`, `holdApplies`, `findHeld`, `keepPinned`, `moveSelection`, `batchListStep`, `coalesce`, `openCount` | view state: selection after a re-fetch, "the item just acted on" stays in the list, pinned batch panels, next item after Hide, `?track=`/`?filter=` deep links (also `file:<id>`, a batch containing the track), refresh per finished track | pure view state, not needed by an agent (except "which to-do items is a track in", which has no command) |
| `aiffModel.ts:aiffShown`, `aiffAction`, `aiffVariant`, `aiffBlocked`, `aiffRows`, `aiffOutcomes`, `aiffNotes`, `aiffProblem` | when the AIFF card shows (`action !== null` or a blocking `why_not`; not with a decision/away); Convert vs Rename; filled vs outline button (`lossy && !cdj && !rename`); why the button is off (Rename also waits while rekordbox runs or is unreadable: UI rule on `rb`); rows Now/Becomes/Name/Space; outcome rows only with a readable rekordbox | `track().aiff` `{action, why_not, kind, from, to, name_now, new_name, bytes, lossy, cdj}` |
| `aiffBatchModel.ts:blockReason`, `listShape` (> `FILES_MAX` 8 = counts per kind), `panelHead`, `runLabel`, `planOutcomes`, `leftRows`, `panelPhase`, `scopeKey` | why Make/Convert is off (a short drive, then rekordbox running with `needs_closed`), the button words ("Make 52 files AIFF", "Convert 12 to AIFF", "Give 3 files their clean names"), what is "Left as they are" | `AiffPlan` (`space[].enough`, `rekordbox.needs_closed`, `skipped`, `waiting`) |
| `flows.svelte.ts:AiffBatchFlow.start` (:417) | selection -> `convert(tracks, origin)`; view or CDJ -> `make_aiff(scope)`; `renames` = plan items all `rename` | engine decides per file |
| `flows.svelte.ts:UpgradeBatchFlow.adopt` / `AiffBatchFlow.adopt`; `resumeIsAiff/Upgrade` (:241) | follow a batch job the window did not start; which flow owns a `batch_resume` (by `batch_kind`) | `job_status().job.batch_kind` |
| `Page.svelte:headResume` / `groupAction` / `cdjAction` | "Upgrade all · n" shown from 2 (`upgradeAllShown`) and not while a stopped batch exists; "Resume · k left" replaces it; same for CDJ; disabled while a write runs (`writeBlockedReason`) | `group.all`, `group.stopped` |
| `Page.svelte:load` (:188) | the answer is fetched again after every job; a deep link to a track outside the chip switches to All; the held item is put back into the section it stood in | no |
| `Details.svelte:aiff` (:85) / `act` (:44) | the AIFF card shows only for an item of the CDJ group without an upgrade, file there | `track().aiff` null rules (no file, download, parked upgrade) |
| `WrongSongDialog.svelte:blocked` (:33) / `candidates.ts:lengthTone` (LENGTH_OK_S 3), `matchTone` (>= 80), `previewOffer` (never Qobuz), `canUse` (not current, not rejected) | searching disabled while a sync runs; green/yellow tones; ▶ offered; "Use this" offered | `length_ok`, `matches`, `can_preview`, `current`, `rejected` are sent and ignored for tones |
| `WrongSongDialog.svelte:preview/use/after` | a `protected` answer removes that candidate from the list (`gone` set) | engine `candidates.mark_protected` remembers it |
| `lib/stores/hub.ts:writeBlockedReason`, `networkReadsAllowed` | buttons off while a write job runs, a console run holds the lock, or a sync runs | engine answers `busy`, `console`, `sync_running` itself |
| `lib/autoUpgrade.ts:autoUpgradeOn` | missing key reads as on | `settings.auto_upgrade` default true (settings_cmd.py) |

---

## 3. Screen states

Source list: `cli-inventory/6-screen-states.md` (todo: 81 shots; the Library's decision and AIFF shots use the same
components). "Data" = what an agent needs to decide or report; "View" = pure window state.

| Family (shots) | Read that gives the data today | Data an agent needs | View only |
|---|---|---|---|
| List, counts, empty: `todo-big`, `todo-filter-none`, `todo-hidden-shown`, `todo-all-hidden`, `todo-all-lossless`, `todo-nothing-to-decide`, `todo-open-in` | bridge `todo(filter, show_hidden)`; **no command** | `chips`, `check_tracks`, `hidden_count`, `groups[].items` (+`all`, `stopped`), `empty` | the chosen chip (a pref `todo.filter`), the open More menu, sections vs one group, scroll |
| Console running: `todo-console`, `todo-wrong-song-during-sync` | `job_status().console_running` / `job` | whether another process or a sync holds the lock | the disabled buttons |
| One track, other groups: `todo-weak-selected`, `todo-fake-selected`, `todo-not-found`, `todo-other`, `todo-offline-selected` | `track` (+ the `todo` item); no command | status, quality, cutoff, file_state, source, free downloads, buy links, `next_qobuz_check`, item `detail` | selection, spectra loading, the player |
| Find a version / Wrong song: `todo-wrong-song`, `-protected`, `-offline`, `-long`, `todo-no-candidates`, `todo-search-slow`, `todo-use-this` | `search_candidates`; no command | candidates, notes, rejected/current flags | dialog open, ▶ playing, the typed link, a running use's progress (events `StepChanged`/`Progress`; only the window's `run` store) |
| Bought file drop: `todo-dragging`, `todo-drop-blocked`, `todo-drop-add`, `todo-drop-*` | event `FileDropped` + hub memory `_dropped`; `track().bought_name` | expected name, whether the track accepts a file | the drag highlight; the dropped file (hub memory only) |
| Same song: `todo-same-song`, `todo-same-song-length` | `todo` item with `pair` (QuestionPair) | song side, file side, `why`, links | none |
| Duplicates: `todo-duplicates`, `-three`, `-pick`, `-tie` | `todo` item with `pair` (DuplicatePair: files, `recommended`, `recommended_why`) | files, qualities, recommended | the picked radio (default recommended) |
| Upgrade, one track: `todo-upgrade-swap`, `-replaced-filtered`, `-mismatch`, `-aiff-same`, `-aiff-new-track`, `-aiff-shifted`, `-mp3-same`, `-different`, `-unknown`, `-compare-playing`, `-rekordbox-open`, `-refused`, `-unreadable`, `-no-rekordbox`, `-undo` | `track().upgrade` (+ rekordbox state `rekordbox_status`); command: `upgrade list` rows + `rekordbox preview` | alignment, `swap_safe`, `swap_possible`, `swap_how`, `why_not`, `rekordbox {state, running}`, quality lines | the picked way, the A/B player, spectra |
| After a replace: `todo-after-swap`, `-after-add-same`, `-after-add-shifted-old`, `-after-add-different`, `-after-no-undo`, `-after-undo-confirm`, `todo-upgrade-done` | `todo` item `check` + `can_undo` (no command) | check fields, `can_undo`, old file place | "item just acted on" hold, confirm dialog |
| Several upgrades / Upgrade all: `todo-upgrade-multi`, `-all`, `-running`, `-stopped`, `todo-resume-link` | selection panel: `todo` rows (`same_track`) + group `all`/`stopped`; running: `job_status().job.last.BatchProgress` + events; end: `JobFinished.result` (BatchResult); command: `batch show <id>`, `batch list` | which rows go, counts n/m/k, progress, per-track result, stopped batch id + left | the selection itself, ✕ on a row, panel phase and focus; the **ended view is held only by the window** (lost on reload; for swap batches `batch show` has the data, for New track/Discard (`batch: null`) nothing keeps it) |
| Checks: `todo-rekordbox-check`, `todo-check-batch-row`, `-batch`, `-batch-kept`, `-undo-confirm`, `-undo-refused`, `-rekordbox-open`, `todo-check-multi`, `-repointed`, `-converted`, `-converted-no-rekordbox`, `-renamed`, `-convert-batch` | `todo` rekordbox_check items (`check`, `can_undo`, batch items `batch {id,size,started,started_by,kind,tracks}`); no command | check fields, steps (composed in UI), refused-row reasons (from the `undo_upgrade` result) | the selection of several checks; `ChecksFlow.problem` (kept until the next pick) |
| Auto-upgrade marks: `todo-auto-waits`, `-auto-waits-panel`, `-auto-refused`, `-auto-refused-panel`, `-auto-refused-choice`, `-auto-batch` | `todo` item `detail`, `track().upgrade.auto_waits/auto_refused`; command: `upgrade list --json` (`auto_waits`, `auto_refused`) and `batch list` (`started_by auto_upgrade`) | refusal reason + words, waits flag, batch starter | none |
| CDJ group: `todo-cdj`, `-cdj-item`, `-cdj-multi`, `-cdj-all`, `-cdj-resume` | `todo` cdj items (`cdj`, `aiff`), group `all {n,k}`, `stopped`; `aiff_plan({cdj})`; command: `convert --all cdj --dry-run --json` | plan items/waiting/skipped/space, per-row reason, stopped batch | the AIFF panel phase, pinned scope |
| AIFF cards and panels (Library shots `library-aiff-*`, To-do `todo-check-converted`…): flac, lossy, cdj, rename, blocked, running, stopped, ended, view, space | `track().aiff`, `aiff_plan`, `rekordbox_status`; command: `convert/rename … --dry-run --json`, `rekordbox preview` | `AiffPlan` fields, blocked reason | panel phases, the fold of "Files" |
| Library decision shots (`library-decision-*`, `library-upgrade*`) | `todo` + `track` | as above | which decision shows |

---

## 3b. Information shown

Everything a person reads or sees in this area, with where it comes from and whether a command gives it. "`todo.*`" =
a field of the `todo()` payload; "`track.*`" = `track()`; UI-composed sources are `file:function`. Command column: `none`
unless a command is named.

### To-do page: header, filter, list

| Surface | What is shown | Source | Command today |
|---|---|---|---|
| Header | title "To-do"; sub-line: "N tracks are not lossless yet", "N questions about your files", "N tracks to check in rekordbox", "N files won't play well on CDJs", or "Nothing to do" | `todo.chips`, `todo.check_tracks`; words `todoModel.ts:headerSub` | none |
| Header | last playlists read, Read playlists / login problem | `job_status().read_status` (shell) | none (sync audit) |
| Sidebar nav | to-do count | `sidebar()` -> `_todo(count_only).chips.all` | none |
| Filter strip | labels All, rekordbox, Same song?, Duplicates, Upgrades, CDJs, Not found, Weak, Good lossy, Fake lossless, Other; counts; coloured dot (lossless/missing/weak/good_lossy/fake); zero groups hidden; five then "More" | `todo.chips`; `todoModel.ts:FILTER_LABEL/FILTER_DOT/FILTER_MAX/segOptions` | none |
| List head | label "All to-dos" or the group's label; count of open items; group hint ("a better version is waiting for you") | `todo.groups[].label/hint` (views.py:1490 `TODO_GROUPS`); `todoModel.ts:openCount` | none |
| List head | "Show hidden · N" / "Hide hidden tracks" | `todo.hidden_count`, the `show_hidden` argument | none |
| Group head | "Upgrade all · n" (from 2, hidden while a stopped batch waits), "Resume · k left", "Convert all · n" | `groups[upgrade_ready].all.n`, `.stopped`; `groups[cdj].all.n`, `.stopped`; `decisionModel.ts:upgradeAllLabel/resumeLabel/convertAllLabel/upgradeAllShown` | none; partial `upgrade list` (count), `batch list` (stopped batch, `planned` = left), `convert --all cdj --dry-run` (`total`, `waiting[].n`) |
| Empty list | "Everything is lossless.", "Only hidden tracks are left.", "Nothing here.", panel "Nothing to decide" | `todo.empty`; `copy.ts` EMPTY | none |
| Row | cover thumbnail | `cover_url` (`self._cover(self._images())`, local image URL) | none (path of the image not given) |
| Row | name "Artist – Title" (or "{n} tracks upgraded" / "{n} tracks" for a batch) | `artist`, `title`; `format.ts:artistTitle`; `decisionModel.ts:batchRowName` | `upgrade list` (artist, title) for upgrades only |
| Row | sub-line "folder · detail" (detail per group: upgrade "Lossless ready · cues can stay" / "different edit" / "not compared", "Waits for rekordbox to be closed", "{Short} · not upgraded at your sync"; check "Reload Tag, analyse again" etc.; Not found "next try in 3 days"; Other "MOVE BLOCKED · a file is in the way"; question/duplicate why; CDJ `short` "AAC 420 kbps · CDJs stop at 320"; source and kbps for weak/good lossy) | `folder`, `detail` from `views._detail`, `upgrade_detail`, `check_status`, `question_why`, `cdj.short` | none (parts only: `upgrade list` fields `now`, `new`, `alignment`, `same_track`, `auto_*`) |
| Row (batch) | sub "today · Same track" / "Made AIFF" / "Clean name" / "Upgraded during your sync"; tooltip = names of its tracks | `batch.started`, `batch.kind`, `batch.started_by`, `check.reason`; `decisionModel.ts:batchRowSub`; `localDay/sinceText` | `batch list` (kind, started_by, started) |
| Row | quality badge ("LOSSLESS", "16.5 kHz", "FAKE · 16.0 kHz", "NOT FOUND", "MIXED" for a batch with different qualities; a question shows its file's) with quality colour | `quality`, `quality_label` (`views.quality_class/quality_label`, WEAK_HZ 17000); `todoModel.ts:rowBadge` | none |
| Row | "Offline" / "Folder not found" tag in place of the badge, tooltip "Offline: connect the drive" | `file_state` (`views.row_file_state`); `format.ts:rowAway`, `FILE_STATE_TAG/WORDS` | `upgrade list` / `rekordbox preview` give `away` as a reason only |
| Row | trailing badge UPGRADE / FREE (tooltip "The artist gives it away for free") / HIDDEN | `upgrade_ready`, `free`, `hidden` | none |
| Row | dimmed = not in any playlist (except question, duplicate, CDJ, check rows), or file away, or CDJ file whose Convert waits | `in_playlists`, `pair`, `group`, `file_state`, `aiff`; `todoModel.ts:rowOff/rowWaits/rowDim` | none |
| Row | selected wash, multi-select marker (groups upgrade_ready, rekordbox_check, cdj) | view; `MULTI_GROUPS` | n/a |
| List | order: groups in `TODO_GROUPS` order (check, same song, duplicates, upgrade ready, CDJ, not found, weak, good lossy, fake, other); inside a group: batches first, then folder, artist, title (case/accent-folded) | `views.todo` sort (views.py ~1900) | `upgrade list` sorts by playlists.txt folder order (`upgrades.ready`), not this order |

### Details panel of one track

| Surface | What is shown | Source | Command today |
|---|---|---|---|
| Track card | 64 px cover; title; "Artist · 3:12 · place" (place = folder or "Rekordbox Library › Hardtechno"); quality badge + "↑" when an upgrade is ready; the word ("verified lossless", "lossy, hard to hear", "lossy, audible", "fake lossless", "no file yet", "sound not checked yet") ; "Not checked" badge | `track.cover_url/title/artist/duration_s/place/quality/quality_label/upgrade_ready/sound_checked`; `trackHeadModel.ts:headLine`, `format.ts:qualityWords` | none |
| Track card | "Open in Spotify/Qobuz ↗" | `track.track_link {url,label,service}` | none |
| Track card | Hide / Unhide link (only for improvable/other/cdj groups; never for checks) | `track.hidden`; `todoModel.ts:actionsFor` | none |
| Check card "In rekordbox" | summary ("same track, cues kept" / "a new track"), numbered steps (Reload Tag, Analyse again + "(lock the beatgrid first…)", Relocate, Auto Relocate, USB stick), hint "Kept your own title and artist in rekordbox", lead sentence for a Convert | `item.check {reason, moved, reload_tag, match, aligned, offset_ms, rekordbox{entries,kept}, text}`; `decisionModel.ts:checkCard` | none; the one sentence is `check.text` (`report.check_text`), also written into every run report's `rekordbox_check` section |
| Check card | "Replaced with lossless / the better version / Converted to AIFF / Given its clean name": two rows (file name, where; old file, where), the date ("today", "31 Oct"), the Undo promise ("Undo puts your old audio back in the file.") | `check.old_path`, `check.old_name`, `check.since`, `item.path`, `item.quality`; `decisionModel.ts:replacedCard`, `sinceText` | none |
| Check card (other) | note: the engine's whole instruction | `item.check.text` / `item.detail` | none |
| Foot (check) | "Done, checked in rekordbox" (or "Done"), "Undo the replace / the conversion / the clean name" shown only while `can_undo`; an undo's refusal text under it | `item.can_undo`; `decisionModel.ts:doneLabel/undoLabel/undoAsk`; `UpgradeFlow.undoProblem` (the job's refused message) | none |
| Upgrade cards | heading "Upgrade ready" (+ " · 256 kbps version"), "found 18 Oct" | `upgrade.what`, `upgrade.found`; `format.ts:upgradeLabel/foundText` | `upgrade list`: `parked` (file); no `what`/`found` |
| Upgrade cards | two spectrum pictures (Now, New) | `spectrum(id,'current'/'upgrade')` (see Pictures) | none |
| Upgrade cards | "Now" = what the current AIFF was made from ("Opus · 135 kbps") or the quality label; tooltip "Your AIFF was made from this"; "New" = `upgrade.format_line` ("FLAC · 24-bit") | `track.source_format_line`, `track.quality_label`; `upgrade.format_line`; `decisionModel.ts:nowLabel/nowTip` | `upgrade list` `now`, `new` (quality text) |
| Upgrade cards | A/B compare player with both audio files and the track length | `track.audio_url`, `upgrade.audio_url`, `track.duration_s` | none (a person listens) |
| Upgrade cards | "Edit" row with dot: "The same edit as yours" / "The same edit, 4 ms apart" / "A different edit" / "Couldn't compare them" | `upgrade.alignment {result, offset_ms}`; `decisionModel.ts:editLine` | `upgrade list` `alignment` (result only, no ms) |
| Upgrade cards | "In rekordbox" choice: "Same track · Cues and beatgrid stay" (recommended) with outcome rows ("Your track keeps its cues, playlists and history", "Moved 4 ms to sit on your cues", "Becomes an AIFF file", "Quit rekordbox before you replace"), "New track · Relocate your old track to keep cues" / "Set the cues again" with rows ("rekordbox lists it as a new track", "A different edit: set the cues again", "Unsure if your cues fit: listen first"), "Your old file is kept in Superseded/" | `upgrade.swap_safe/swap_possible/swap_how/alignment/rekordbox`; `decisionModel.ts:upgradeWays` | none; `rekordbox preview` `eligible`, `timing`, `new_file`, `superseded` |
| Upgrade cards | with no choice: card "In rekordbox" / "The new file" ("No rekordbox on this Mac: the new file is a new track") and the why-not line ("Same track needs the track analysed in rekordbox first. Analyse it there, or replace it as a new track.") | `upgrade.why_not`, `upgrade.rekordbox.state`; `decisionModel.ts:WHY_NOT_LINE/NO_REKORDBOX` | `upgrade list` `same_track` (reason key); `rekordbox preview` `eligible.same_track` + words in human output |
| Upgrade cards | Auto-upgrade: yellow note with the refusal's words; Hint "Waits for rekordbox: it goes in at your next sync, or quit it and press Replace." | `upgrade.auto_refused {reason,message,at}`, `upgrade.auto_waits`; `decisionModel.ts:autoNotes/AUTO_WAITS_HINT` | `upgrade list` `auto_refused`, `auto_waits` |
| Upgrade foot | "Replace with lossless" / "Replace with the better version", "Discard the new version" (tooltip "Deletes the new version; it isn't offered again"), "You can undo a replace until you press Done", button busy states | `upgrade.what`; `decisionModel.ts:replaceLabel` | none |
| Cutoff card | number "16.5 kHz" and "where the highs end · lossless reaches about 22 kHz" / "no clear edge in the highs" / "a lossy file inside the WAV", over the spectrum | `track.cutoff_hz`, `track.status`, `track.path`, `track.sound_checked`; `format.ts:cutoffStat` | none |
| Current file card | spectrum, player (audio_url, waveform envelope, length), Format ("AIFF · 16-bit"), Source (e.g. "YouTube Music" link, " · Opus · 135 kbps", sub "found by its ISRC"), Qobuz line, "Wrong song?" | `track.format_line/source_full/source_url/source_format_line/source_how`, `next_qobuz_check`, `audio_url`; `copy.ts:SOURCE_HOW_WORDS`, `todoModel.ts:qobuzText` | none |
| "Still looking" card (no file) | "Qobuz: not there yet · looks again on 20 Oct", "Others: <detail>" | `track.next_qobuz_check`, `item.detail` | none |
| "Get a lossless file" | FREE badge + "Download on SoundCloud" / host link, title, "from <uploader>", hint ("The artist's own file · usually WAV or 320 kbps MP3"); "or buy" Beatport / Bandcamp links | `track.free_downloads[] {url, host, direct, title, uploader}`, `track.buy_links`; `todoModel.ts:freeHint` | none; `.discjockey/not_lossless.md` lists buy links (README "Reports and not_lossless.md") |
| Drop zone | the expected file name ("will be filed as Library/Hard_Bounce/Armin Hermann – Get Naughty"), states idle / dragging / busy / blocked with macOS's message, "Add <file> again" | `track.bought_name` (always `.wav`), `FileDropped {name, readable, message}`; `todoModel.ts:filedAs` | none; `not_lossless.md` shows the exact name |
| AIFF card (CDJ item) | rows Now ("FLAC · 24-bit · 96 kHz"), Becomes ("AIFF · 16-bit · 44.1 kHz"), Name (old, new), Space ("+31 MB; your original goes to Superseded/"); warn note with the CDJ reason ("AAC 420 kbps · CDJs stop at 320"); info note "An AIFF made from this sounds the same and takes 5–10 times the space."; outcome rows ("Your track keeps its cues, playlists and history", "Becomes an AIFF file", "Quit rekordbox before you start" only while rekordbox runs); button "Convert to AIFF" / "Give it its clean name"; Hint why it is off (rekordbox can't be opened, Cloud Library Sync, no free name, rekordbox open for a rename) | `track.aiff {action, why_not, kind, from, to, name_now, new_name, bytes, lossy, cdj{short,words}}`, `rekordbox_status`; `aiffModel.ts:aiffRows/aiffNotes/aiffOutcomes/aiffBlocked/aiffLabel` | `convert <key> --dry-run --json` (plan item: `from`, `path`, `new_path`, `bytes`, `kind`, `cdj`), `rekordbox preview` (`eligible`); no per-file `why_not` words except in human output |
| Toasts, banners | success words per job ("Upgrade undone. Your old file is back.", "Moved 2 files to Superseded/."), problem words per kind (`copy.ts:problemCopy`), "recovered" info toast (interrupted steps finished) | job result `words`, `recovered`; `JobFinished` `problem`/`message` | job JSON `message`, `recovered` (console prints too) |
| Disabled controls | "Wait until the current change is finished.", "A sync is running in the terminal.", "Not while a sync runs. Try again when it's finished." | `job_status` `job.running`, `console_running`; `copy.ts` | exit 3 `busy` / `kind: busy` |

### Question, duplicates, dialog

| Surface | What is shown | Source | Command today |
|---|---|---|---|
| Same song | why title ("Same title, different artist", "Same artist and title, 4 s longer", …); table playlist song vs your file: title (file's tag or file name), artist ("—" when none), length ("—"), where (playlist folder vs file's folder/"~", drive first); the differing line in full strength; file quality badge, ▶; "Open in Spotify/Qobuz"; note "Until you answer, Discjockey doesn't download this song." | `item.detail` (`views.question_why`), `pair {song_key, own_key, why, track{title,artist,duration_s,folder,link}, file{…}}`; `todoModel.ts:compareLines/filePlace/linkService` | none |
| Duplicates | why ("The same audio in 2 files", "3 files of the same song"); per file: quality badge + format ("AIFF"), last folder (+ " · in your playlists"), full path tooltip, ▶; the recommended pick and `recommended_why`; "Goes to Superseded/" on the others; "Keep both"/"Keep all" row; button "Keep the AIFF" / "Keep the one in Old" / "Choose the file that stays"; "Not deleted: kept in Superseded/" | `pair.files[] {file_id, path, quality, quality_label, in_playlist, …}`, `pair.recommended`, `recommended_why`; `decisionModel.ts:fileWords/keepWords/fileFormat/lastFolder` | none |
| Find a version dialog | title "Pick another version: Artist – Title"; "Spotify: 3:12 · sorted by how well they match · ▶ plays a 20-second preview"; per row: source name, title, second line (artist; "current · you marked it as wrong"; "rejected before"), length with tone (green within 3 s of Spotify's, yellow else), match % with tone (green from 80), ▶ (not for Qobuz: "Qobuz versions have no preview."), "Use this"; "Nothing found. Paste a link if you know one."; notes (e.g. "Qobuz was not searched: …"); "Searching Qobuz, YouTube Music, SoundCloud and YouTube…"; "Searching isn't possible while a sync runs."; download progress ("Downloading… 42 %", "Checking the length…") | `search_candidates` payload (`candidates[]`, `notes`, `track_duration_s`); `candidates.ts`; run events for progress | none |
| "None of these" confirm | "The current file moves to Superseded, and the next sync searches again. Your playlists stay as they are." | `candidates.ts:NONE_CONFIRM` | none |

### Selection and batch panels

| Surface | What is shown | Source | Command today |
|---|---|---|---|
| Upgrade selection | title "N upgrades selected"; before-line; one row per track (cover, name, sub; dimmed + reason where it stays: "needs your choice", "file not found", "drive not connected", "rekordbox is open", "analyse it again in rekordbox"); ✕ leave out; "In rekordbox" with "Same track · n" / "New track · N" + outcomes; "Replace n with lossless" (off: "None of these can be replaced this way"); "Discard n new versions"; Hint | `todo` items `same_track`, `detail`; `decisionModel.ts:selectionWays/beforeLine/goes/sameTrackWhy/replaceManyLabel/discardLabel` | `upgrade list` (`same_track` key per track); `upgrade apply --dry-run` (`planned`/`skipped` + reason per track, `space`, `rekordbox.needs_rekordbox_closed`) |
| Running batch | big number "3" "of 8 done", "Upgrading · Artist – Title" / "Making AIFF · …" / "Giving clean names", progress bar, rows marked waiting / working / passed / done / skipped / failed, Stop (and "Stopping…") | `BatchProgress {batch_id, done, total, track_id, name}`; `decisionModel.ts:progressRows/runLabel/runUnit`, `aiffBatchModel.ts:aiffRunLabel` | stderr lines "3 of 8: name" / "Converting 3 of 52: name"; `batch show <id>` while running (items + counts) |
| Ended batch | number "12" "tracks" "upgraded, your cues stayed" / "made AIFF" / "given their clean names"; notes ("Stopped after 2 of 4.", "rekordbox was opened, so Discjockey stopped after 3 of 8. Quit rekordbox and press Resume.", "Discjockey is already changing your rekordbox library in another window or the Terminal."); "N not upgraded" list with reasons; "N left" / "Still to do" list; Resume · k left / Try again / Done | `JobFinished.result` BatchResult (`state`, `stop_reason`, `results[]`); `decisionModel.ts:batchEnd/endNote/endGroups`, `aiffBatchModel.ts:aiffEndNote/madeWords` | final JSON of `upgrade apply`/`convert` (counts + `results[]` with `reason`, `message`); human summary lines (`_batch_lines`); result items carry only the song key, no artist/title |
| Batch check card | "In rekordbox" steps for the tracks rekordbox has; names listed under Reload Tag / Auto Relocate; "Upgraded n today" (or "Made AIFF", "Clean names", "Changed") with a row per track: new file name, kept-text note ("Kept your own title in rekordbox"), "Not in your rekordbox collection, so there was nothing to keep there", "Undo this one"; foot "Done, checked in rekordbox", "Undo all n" / "Undo n" / "Undo all from this sync", "k can't be undone", a refused row's reason | `item.batch {id,size,started,started_by,kind,tracks}`, `check.*`, `can_undo`, undo result rows; `decisionModel.ts:batchCheckCard/checkRow/undoFoot/batchListTitle` | `batch show <id>` (items, not open-check state); none for `can_undo` |
| Several checks selected | "N checks selected" over "n tracks", rows with the to-do row's line | `todo` items; `decisionModel.ts:checksTitle/tracksSummary` | none |
| AIFF batch panel | head "12 files for CDJs · Convert all · 9" / "Make all lossless files AIFF · in Hard Bounce" / "3 tracks selected · 2 can become clean AIFF"; the plan list (each file with kind "FLAC → AIFF", "Clean name only"; above 8 files counts per kind with "Files" folded); "Left as they are" with reasons or counts; format sentence "Every file becomes a 16-bit/44.1 kHz AIFF…"; lossy note "2 of these are lossy…"; "Needs 4.2 GB on Example Drive · 120 GB free"; outcome rows; button "Make 52 files AIFF" / "Convert 9 to AIFF" / "Give 3 files their clean names"; Hint "Quit rekordbox before you start" or "Not enough space on …: 4.2 GB needed, 1.0 GB free"; empty: "Every lossless file here is a clean AIFF already." / "Nothing to change: these are clean AIFFs already." | `AiffPlan` (`items[] {track,name,action,kind,from,path,new_path,superseded,bytes,cdj}`, `skipped`, `waiting`, `kinds[] {kind,label,n}`, `lossy`, `total`, `space[] {drive,needed,free,enough}`, `superseded_bytes`, `rekordbox`); `aiffBatchModel.ts` | `convert … --dry-run` human lines + JSON `plan` (the same object); drive name (`driveName`: "this Mac" vs /Volumes name) and 8-file folding are UI |

### Pictures and sound (name the data)

| Picture | Data behind it | Where the engine has it | Command today |
|---|---|---|---|
| Spectrum (Now, New, Current file, cutoff card) | a matrix `cols x bands` of dB values, 8-bit, base64 (`data`), `max_hz`, `floor_db`, `duration_s`; the dashed cutoff line at `cutoff_hz` (current file only); axis label top-left = `max_hz` | `hub/spectrum.py:matrix/encode` via `spectrum(paths, rel)`; `cutoff_hz` stored per track by `quality.py` (verdict + `views.quality_class`, `WEAK_HZ` 17 kHz) | none; numbers an agent could use: `cutoff_hz`, `quality_label`, `status` (in `track()`/todo rows, no command) |
| Waveform (mini player, compare player scrub) | `waveform`: base64 peak envelope of `cols` values 0-255 | `spectrum.py:peaks/encode_waveform` | none |
| Cover thumbnails | image URL per track | `HubApi._cover(_images())` (embedded art or downloaded image in the library) | none |
| Quality colour (badge, dot, dimming) | `quality` in {lossless, good_lossy, weak, fake, missing} | `views.quality_class` | none |
| Sound (▶ players) | `audio_url` (local media server), 20 s candidate clips | `media.py`; `candidates.preview` | none (person listens) |

---

## 4. Journeys

Legend: P = only a person can do it. "agent tells" = what the agent must say to the user.

### J1. See what is waiting
| Step | Bridge | Command today |
|---|---|---|
| Open To-do, read counts and groups | `todo("all")`, `sidebar` | none (see section 0.1) |
| Filter to one group, Show hidden | `todo(group, true)` | none |
| Upgrade list only | `todo("upgrade_ready")` | `upgrade list --json` |
| CDJ list only | `todo("cdj")`, `aiff_plan({cdj})` | `convert --all cdj --dry-run --json` |

### J2. Upgrade one track (README "Upgrades")
| Step | Bridge | Command today |
|---|---|---|
| Look at Now / New, same edit?, Same track possible? | `track`, `spectrum` x2, `rekordbox_status` | `upgrade list --json` (alignment, same_track), `rekordbox preview <key> --json` |
| Listen to both (P) | A/B player | none; agent tells the user which track and that listening is theirs |
| Quit rekordbox (P) | `rekordbox_status.running` | `rekordbox status --json` (`running`) |
| Choose Same track / New track | `upgrade([id], "swap"|"add_new")` | `upgrade apply <key> --way same-track|new-track [--dry-run]` |
| Wait, read result | job events | JSON result; exit 0/1/3/4/5 |
| Do the steps in rekordbox (P): analyse again, Reload Tag if asked, Relocate for New track, rebuild USB stick | `todo` item `check` | none for the steps; the sentence is `check.text`; agent tells the user the steps (section 0.3) |
| Done | `rekordbox_checked([id])` | `rekordbox checked <key>` |
| or Undo | `undo_upgrade([id])` | `upgrade undo <key>` (needs rekordbox closed for a rekordbox write) |
| or Discard | `upgrade([id], "discard")` | `upgrade discard <key>` |

### J3. Upgrade several / Upgrade all, Stop, Resume
| Step | Bridge | Command today |
|---|---|---|
| Choose the tracks (⌘-click, ⇧, ⌘A, "Upgrade all · n") | view; `todo` rows | `upgrade list`, then keys or `--all` |
| See how many keep cues / need a choice / wait | selection panel (`selectionWays`) | `upgrade apply --dry-run --json` (`planned`, `skipped`, reasons) |
| Replace | `upgrade(ids,"swap")` or `upgrade_all()` | `upgrade apply <keys>|--all --way same-track` |
| Progress "3 of 8" | `BatchProgress` | stderr lines; `batch show <id>` |
| Stop | `stop()` | Ctrl-C (SIGINT) |
| Quit rekordbox if it stopped the batch (P), Resume | `batch_resume(id)` | `batch resume <id>` |
| Undo all from the batch | `undo_upgrade(ids)` / `batch_undo(id)` | `batch undo <id>` or `upgrade undo <keys>` |

### J4. Upgrade automatically when I sync (README)
| Step | Bridge | Command today |
|---|---|---|
| Read / set the switch | `setup_status.auto_upgrade`, `set_auto_upgrade` | `settings auto-upgrade [on|off]` |
| See that rekordbox is open and upgrades wait | `rekordbox_status`, `sync_preview` | `rekordbox status`, `discjockey --dry-run --json` (`auto_upgrade` block) |
| Sync | `start_sync` | `discjockey --yes --json` (downloads too; see 7. note in section 5) |
| See "wait for rekordbox" / refused reasons | `todo` row detail, `track.upgrade.auto_*` | sync JSON `auto_upgrade.results[]`; `upgrade list` `auto_waits/auto_refused` |
| Undo all from this sync | `undo_upgrade(batch tracks)` | `batch list` (find `started_by auto_upgrade`), `batch undo <id>` |

### J5. Is this the same song? / Duplicates
| Step | Bridge | Command today |
|---|---|---|
| See the question or the group | `todo("same_song"|"duplicate")` | none |
| Answer yes / no | `answer_same_song` | none |
| Keep both / all | `keep_duplicates` | none |
| Keep one (the others go to `Superseded/`) | `supersede_duplicate` x (n-1) | none |

### J6. Not found, weak, fake: find a version, buy, drop a bought file (README "Reports and not_lossless.md")
| Step | Bridge | Command today |
|---|---|---|
| See not-lossless tracks | `todo`, file `.discjockey/not_lossless.md` | none; the file is readable |
| Search other versions | `search_candidates` | none |
| Listen to a clip (P) | `preview` | none |
| Use a version / a pasted link | `use_candidate`, `use_link` | none |
| None of these | `reject_current` | none |
| Buy (P, browser), save the file under the exact name or drag it onto the track (P) | `open_external`, OS drop + `add_bought_file` | none; saving under the exact name by hand is picked up by the next sync |
| Hide / Unhide | `hide` | none |
| Free download (P: follow/like in a browser) | `open_external` | none |

### J7. rekordbox check: Done / Undo (single, batch, selection)
See J2/J3: `rekordbox_checked`, `undo_upgrade`, `batch_undo`; commands `rekordbox checked`, `upgrade undo`, `batch undo`.
No list of open checks; the agent keeps the keys from the run's JSON.

### J8. Files that play on every player (README "Making files AIFF")
| Step | Bridge | Command today |
|---|---|---|
| One file: see the card, Convert or clean name | `track.aiff`, `convert([id])` / `rename([id])` | `convert <key> --dry-run`, `convert <key>`, `rename <key>` |
| Selection / a Library view | `aiff_plan`, `convert(ids)`, `make_aiff({lossless,view,key})` | `convert <keys>|--all lossless [--in …]` |
| CDJ group, Convert all / selection | `todo("cdj")`, `aiff_plan({cdj})`, `make_aiff({cdj})` | `convert --all cdj [--dry-run]` |
| Stop, Resume | `stop`, `batch_resume` | Ctrl-C, `batch resume <id>` |
| rekordbox open: quit it (P) | `rekordbox_status` | `rekordbox status` |
| Do the USB step (P) | check card | none (USB line in the console summary only) |
| Undo the conversion / clean name | `undo_upgrade` | `upgrade undo <key>` / `batch undo <id>` |

### J9. rekordbox safety net (README "rekordbox", "When something breaks")
| Step | Bridge | Command today |
|---|---|---|
| Is rekordbox's library readable, is it open | `rekordbox_status` | `rekordbox status --json` |
| What would happen to one file | `track.aiff`, `track.upgrade` | `rekordbox preview <key>|--path <file> --json` |
| List backups | none | `rekordbox backups --json` |
| Restore (rekordbox closed (P)) | none | `rekordbox restore <backup> --yes` |
| Undo moved tracks first | `undo_upgrade` | `batch undo <id>` |

### J10. Reports
| Step | Bridge | Command today |
|---|---|---|
| Read the last run's report, runs list | `runs`, `run`, `open_report` | the sync's `--json` `report` path; files in `.discjockey/reports/`; no list command |
| not_lossless.md | file | none |

### J11. Extra journeys: the issue 33 live tests (stages A to D), to be run by an agent later

Notes for every test: the agent must set `DISCJOCKEY_SUPPORT=<scratch>` and `DISCJOCKEY_REKORDBOX=<fixture or empty>` for
anything but the real live test (CONTRIBUTING). The test tracks come from `scripts/make_upgrade_test.py` (a script, not a
command; stage A step 3 adds `--keep-lossy m4a`). "Backup rekordbox" (File › Library › Backup) is P; copying
`~/Library/Pioneer/rekordbox/` aside is a plain file copy (no command; unrelated to `rekordbox backups`, which lists
Discjockey's own copies).

#### Stage A, plan section 8 (`docs/2026-11-07-rekordbox-stage-a-plan.md:471`)
| Step | Who | Bridge | Command today |
|---|---|---|---|
| 1a. `rekordbox status`: "ready", the right library, "rekordbox is closed" | agent | `rekordbox_status` (state, running only) | `rekordbox status --json` |
| 1b. open rekordbox, run it again: "rekordbox … is open" | open rekordbox: **P**; read: agent | `rekordbox_status.running` | `rekordbox status --json` (`running`, `version`) |
| 2. `rekordbox preview --path <file>` on an MP3, a 48 kHz M4A, an AIFF; compare offsets with the research numbers (MP3 1105 or 2257 samples, M4A ~21.5 ms, AIFF 0) | agent | none (the details' AIFF card has only the plan) | `rekordbox preview --path <file> --json` (`timing.offset_samples`, `entries[].offset_ms`) |
| 3a. make a test track with `make_upgrade_test.py --keep-lossy m4a` | agent | none | the script |
| 3b. import it into rekordbox, analyse, set 3 hot cues on clear beats, quit rekordbox | **P** | none | none |
| 3c. get Discjockey to know the file (scratch watched folder) | agent | `add_watched_folder` | none |
| 3d. choose **New track** | agent | `upgrade([id], "add_new")` | `upgrade apply <key> --way new-track [--dry-run]` (key from `upgrade list`) |
| 3e. open rekordbox, right-click the old track › Relocate, choose the new `.aiff` | **P** | none | none (agent tells the user the new file path: `upgrade apply` result `results[].path`) |
| 3f. check: rekordbox accepts an `.m4a` track relocated to an `.aiff`, the three cues on the same beats, plays without a click at the start | **P** (looks, listens) | none | none (`rekordbox preview --path <new>` shows `entries[].cues` only after rekordbox re-read the file) |
| 3g. remove the test files | agent | none | the script's docstring |

#### Stage B, plan section 9 (`docs/2026-11-07-rekordbox-stage-b-plan.md:760`)
| Step | Who | Bridge | Command today |
|---|---|---|---|
| 0a. File › Library › Backup in rekordbox; a spare USB stick | **P** | none | none |
| 0b. copy `~/Library/Pioneer/rekordbox/` aside; make the four click tracks with a parked upgrade each, import into a scratch watched folder | agent | `add_watched_folder`, `start_import` | none (script + file copy) |
| 1. in rekordbox: import the four, analyse, 3 hot cues each, one track in two playlists, play one, edit one title, export all four to the stick, quit | **P** | none | none |
| 2a. To-do › Upgrade ready: Upgrade all, Replace; watch progress | agent | `todo("upgrade_ready")`, `upgrade_all()`, `BatchProgress` | `upgrade list --json`; `upgrade apply --all --way same-track --json` (progress on stderr) |
| 2b. press Stop once midway | agent | `stop()` | SIGINT to the running `upgrade apply` (Ctrl-C; no stop command); the exit is 5, `batch` id in the JSON |
| 2c. Resume | agent | `batch_resume(id)` | `batch resume <id>` |
| 3. open rekordbox: each track shows AIFF, 44.1 kHz, 16-bit; plays; cues and grid on the clicks (48 kHz M4A and FLAC included); the edited title stayed, the other names are the clean ones; artist/album rows sort and search normally; history and both playlists hold the track | **P** looks / plays; agent can read: new file paths and `rekordbox.entries/kept` per track | none | `batch show <id> --json` (`results[].path`, `rekordbox {entries, kept}`); `rekordbox preview --path <new> --json` (cues, grid, `fields_kept`) |
| 4. quit and reopen rekordbox; seek in the former MP3 (no stutter); analyse one again with the grid locked: waveform refreshes | **P** | none | none |
| 5. edit a title in Track info, quit, Finder Get Info: did rekordbox write the title into the file's tags; note Reload Tag's exact menu name and fields | **P** | none | none (tags could be read with ffprobe, not a Discjockey command) |
| 6. USB stick: plain sync; stick's own track list in Devices; else rebuild; note which result | **P** | none | none |
| 7a. open rekordbox, then **Undo all** on the batch card: it says to quit rekordbox | open rekordbox **P**; agent runs undo | `undo_upgrade(ids)` (job fails `rekordbox_open`) | `batch undo <id> --json` -> exit 4, `kind: rekordbox_open`, results `waiting`, nothing undone |
| 7b. quit rekordbox, Undo all again; old files back with cues | quit **P**; undo agent; look **P** | `undo_upgrade` | `batch undo <id>` |
| 8. relocate by hand: one `.mp3` track relocated to an `.aiff` file works or not; whether rekordbox follows a file Discjockey moved into `Superseded/` by itself | **P** | none | none |
| 9a. leave rekordbox closed a minute, tell the agent | **P** | none | none |
| 9b. agent checks master.db wasn't touched by rekordboxAgent meanwhile, `contentFile` accepted (no re-analysis prompt) | agent (master.db, read-only per the user's rules) / **P** (the prompt) | none | none: no command shows master.db modification, `contentFile` values, or per-field repoint (`rekordbox status` gives `problem`; `rekordbox preview` reads the new file's entries) |

#### Stage C, plan section 9 (`docs/2026-11-09-rekordbox-stage-c-plan.md:551`)
| Step | Who | Bridge | Command today |
|---|---|---|---|
| 0. throwaway click tracks each with a parked same-edit upgrade; backup rekordbox | agent / **P** (backup) | `add_watched_folder` | script |
| 1a. rekordbox open (**P**), Sync page: the before-start line shows | agent reads | `rekordbox_status`, `sync_preview` (auto-upgrade info) | `rekordbox status --json`; `discjockey --dry-run --json` (`auto_upgrade.results[].state` `would`/`waiting`). No command prints the Sync page's line itself |
| 1b. run the sync; ends with "… wait for rekordbox to be closed" | agent | `start_sync([...])` | `discjockey --yes --json` -> `auto_upgrade.waiting`, results `reason rekordbox_open`; **no flag to run only the upgrade phase or skip downloads** (`--limit N` needs N >= 1); use a scratch library whose playlists are all downloaded |
| 1c. To-do marks both "Waits for rekordbox to be closed"; nothing changed in rekordbox | agent / **P** looks | `todo` row detail, `track.upgrade.auto_waits` | `upgrade list --json` (`auto_waits: true`) |
| 2a. quit rekordbox | **P** | none | none |
| 2b. Sync again: both upgraded; end screen's Upgraded list and summary line | agent | `start_sync` | `discjockey --yes --json` (`auto_upgrade {batch, backup, done, results[]}`, summary line on stderr) |
| 2c. rekordbox shows the AIFF with its cues | **P** | none | `rekordbox preview --path <new>` for the database side |
| 2d. To-do's card says "Undo all from this sync" | agent | `todo` batch item `batch.started_by == "auto_upgrade"` | `batch list --json` (`started_by: auto_upgrade`); the words are UI |
| 3. "Undo all from this sync": both back with cues in rekordbox | agent; look **P** | `undo_upgrade(ids)` | `batch undo <id>` (rekordbox closed) |
| 4a. Settings › Upgrades off | agent | `set_auto_upgrade(false)` | `settings auto-upgrade off` |
| 4b. Sync with an upgrade waiting: nothing moves | agent | `start_sync` | `discjockey --yes --json` (`auto_upgrade: null`); `upgrade list` still lists it |

#### Stage D, plan section 9 (`docs/2026-11-13-rekordbox-stage-d-plan.md:556`)
| Step | Who | Bridge | Command today |
|---|---|---|---|
| 0. backup rekordbox (**P**); click tracks (FLAC, 24-bit 96 kHz WAV, messy-named AIFF, AAC 420 kbps, MP3), each analysed with hot cues in a playlist (**P**); rekordbox closed for 1 to 4 (**P**) | agent / **P** | none | script |
| 1a. Make all lossless files AIFF on the folder's view: see the plan | agent | `aiff_plan({lossless, view:"folder", key})` | `convert --all lossless --in folder:<path> --dry-run --json` |
| 1b. run it: FLAC and WAV become AIFF, the AIFF gets its clean name | agent | `make_aiff({...})` | `convert --all lossless --in folder:<path> --json` |
| 1c. in rekordbox: AIFF/44.1/16, plays, cues and grid on the clicks, still in the playlist (also the 96 kHz one) | **P** | none | `rekordbox preview --path <new> --json` for entries/cues |
| 2a. To-do › Won't play well on CDJs: the AAC is listed with its words | agent | `todo("cdj")`, `aiff_plan({cdj})` | `convert --all cdj --dry-run --json` (`plan.items[].cdj.words`); console `held` can differ from the window's |
| 2b. Convert all; rekordbox plays the AIFF with cues | agent; **P** (plays) | `make_aiff({cdj})` | `convert --all cdj`; rekordbox look **P** |
| 3. the MP3 by hand (Library › details › Convert to AIFF) | agent; look **P** | `track.aiff`, `convert([id],"library")` | `convert <key> --dry-run`, `convert <key>` |
| 4. Undo all on each check card: old files back, rekordbox plays them with cues | agent; look **P** | `undo_upgrade(ids)` / `batch_undo` | `batch undo <id>` / `upgrade undo <key>` |
| 5a. open rekordbox (**P**) | **P** | none | none |
| 5b. Convert on one file: "Quit rekordbox" words, nothing changed | agent | `convert([id])` -> `rekordbox_open`; the card's Hint comes from `rekordbox_status` | `convert <key>` -> exit 4 `kind: rekordbox_open` (a single named song is closed unrun, nothing to resume); `rekordbox preview <key>` shows `eligible` |
| 6. optional: export the converted AAC's AIFF to a stick and load it in a CDJ/XDJ | **P** | none | none |

---

## 5. Today's commands, judged for agents

Files: `discjockey/cli.py` (parse), `batch_cmd.py`, `convert_cmd.py`, `rekordbox_cmd.py`, `settings_cmd.py`,
`upgrades_cmd.py`, `app_main.py`.

1. **Discoverability.** There is no index of commands or JSON shapes in the program: `cli.py:51-75` has one prose
   `description=` for the command group; each shape is documented only in CONTRIBUTING.md. `upgrade` (non-interactive) and
   `upgrades` (interactive, `upgrades_cmd.py:147`, `input()`) differ by one letter; `rekordbox` holds read (`status`, `preview`),
   write (`checked`, `restore`) and list (`backups`) commands, while the same batches are under `batch`. From the app bundle
   the program is `Discjockey.app/Contents/MacOS/Discjockey <command>` and only the names in `CLI_COMMANDS`
   (`app_main.py:21`) work; a leading flag (`--yes`, `--json`, `--dry-run`: the bare sync) opens the window
   (`app_main.py:34-41`).
2. **Which folder it acts on.** `library.resolve_paths()` uses `$DISCJOCKEY_SUPPORT` and `config.json`; rekordbox's place uses
   `$DISCJOCKEY_REKORDBOX`. No command prints the resolved music/support folder or rekordbox library (`rekordbox status`
   prints `library` only for rekordbox). An agent cannot confirm that it works on the intended library before a write.
3. **Naming.** Same thing, different words: `--way same-track|new-track` (batch_cmd.py:47) vs bridge `swap|add_new` vs the
   window's "Same track / New track"; the song key is `track` in results (`ItemResult`), `track_id` in the bridge,
   `batch.tracks[].track_id`; `--all` is a flag for `upgrade apply` and `rename` but takes `lossless|cdj` for `convert`
   (convert_cmd.py:94); `--batch ID` (flag) in `rekordbox checked` vs positional `<id>` in `batch resume|undo|show`;
   `--in playlist:<name>|folder:<path>|unlisted` (convert_cmd.py:110) vs the bridge's `{view,key}`.
4. **Flag placement is silent.** Verified with `cli.parse_args`: `--json upgrade list` parses with `json=False` (the
   top-level `--json` is the sync's, cli.py:59, the sub-command has its own, batch_cmd.py:67): prints text, exit 0, no
   warning. `--yes upgrade apply …` is accepted and ignored; `upgrade apply … --yes` is "unrecognized arguments" (exit 2).
   `--dry-run` uses `default=argparse.SUPPRESS` (batch_cmd.py:84, convert_cmd.py:85), so it is absent from the namespace,
   handled with `getattr`.
5. **What a song is called on the command line.** A song key (`<playlist-service id>` or `local:<n>` for own files).
   `convert_cmd.py:82` and `cli.py:85` say "as the library's JSON prints them", but no command prints a library JSON; keys
   come from `upgrade list` (parked upgrades), `convert --all cdj --dry-run` (CDJ files), a batch's results, or the
   sync's report. No search by artist/title; no listing for Weak/Not found/Other/duplicates. Result JSON carries only
   keys (`ItemResult` batches.py:91: track, action, state, reason, message, path, rekordbox), no artist/title (the human
   lines add names: batch_cmd.py:124 `_name`).
6. **Exit codes differ per command.** Batch family: 0 done/dry/read, 1 refused or failed or some skipped, 2 no library or
   usage error, 3 busy, 4 rekordbox open, 5 stopped (batch_cmd.py:11-17,42). Sync: 0/1/2/3/130 (cli.py:9). `rekordbox
   status|preview`: 0/1/2 (rekordbox_cmd.py:5). `settings`: 0-3 (settings_cmd.py:5). Ctrl-C is 5 in batches and 130 in the
   sync. Exit 1 means refused, failed, crashed and "some tracks skipped" (the JSON `ok` stays true in that last case:
   exit code and `ok` disagree by design). Exit 2 is both "no music folder" and an argparse usage error (which prints
   text, not JSON). JSON `kind` values: `refused|failed|busy|rekordbox_open|stopped` here, `needs_yes|crashed|not_set_up|
   login_expired|offline|...` in the sync, versus 20 `ProblemKind`s in the bridge (`types.ts:3`: `changed`, `protected`,
   `console`, `sync_running`, `setup_off` … never printed by a command).
7. **Errors on stdout.** `rekordbox_cmd.failed/say` print the failure (human or JSON) to stdout (rekordbox_cmd.py:35-51); progress
   lines go to stderr (batch_cmd.py:191). In the sync's `--json` mode all human lines go to stderr (cli.py:302); the
   batch commands only have JSON on stdout when `--json` is given.
8. **Prompts and confirmations.** No batch/convert command prompts. The bare sync prompts "Proceed? [y/N]" unless `--yes`
   (cli.py:242; with `--json` and no `--yes`/`--dry-run` it refuses, :298); `upgrades`, `setup`, `update` are interactive.
   Confirmations the window asks are missing as flags: `upgrade discard` (deletes the parked file; window confirms),
   `upgrade undo` / `batch undo` (window confirms), `rekordbox checked` (ends the undo; the window does not confirm). Only
   `rekordbox restore` has `--yes` (batch_cmd.py:108, refuses with `needs_yes`).
9. **Dry runs.** `upgrade apply --dry-run` (no lock, no decode; quick answers only, "the real run checks each track
   again", batch_cmd.py:448), `convert|rename --dry-run` (the full plan; may take the lock to fill facts), sync `--dry-run`.
   None for `discard`, `undo`, `batch resume|undo`, `checked`, `restore` (needs `--yes` instead). The bridge has no dry run
   but `aiff_plan`.
10. **Long runs and progress.** The command blocks until the batch ends; progress is stderr text ("2 of 5: name",
    "Converting 3 of 52: name"), JSON only at the end; no `--follow`/event stream; no detach. The only polling is
    `batch show <id>` from another process (no lock). A killed process leaves the batch `running`/`stopped` for the next
    writer's `recover_pending`. Stop is Ctrl-C (a second one within 1 s is ignored: `CTRL_C_REPEAT_S`, batch_cmd.py:43).
11. **The library lock while the app is open.** Writing commands take `library.run_lock` and exit 3 immediately
    (`LockHeld` -> `busy`, batch_cmd.py:157) while the window runs a write job; the window's own writes answer `console`
    while a command holds the lock (`jobs.py:368 console_running`, `start` :435). Read commands take no lock. The app being
    open without a job is fine. A console change is not pushed to an open window (it only learns through the lock probe).
12. **Single-track guard missing in console.** Hub: `hide`, one-track add_new/discard, `use_*`, `reject_current`,
    `add_bought_file` fail with `changed` unless the entry equals what the window last showed (`ops.py:89`). Console
    commands act on the current record with no "I looked at this" token (acceptable for an agent that read just before,
    but a different safety).
13. **Missing reads** (section 0.1) are the biggest agent problem: after `upgrade apply` the agent cannot ask what is left
    to check or undo; `batch show` lists items, not open checks.
14. **Selection.** One/several/all: `upgrade apply` keys or `--all`; `discard`, `undo`, `checked`: keys (`checked --batch`); no `--all`
    for undo/discard/checked; `convert|rename` keys or `--all`; nothing for hide, same song, duplicates, find a version.
15. **`settings`** has one setting (`auto-upgrade`, settings_cmd.py:28). It writes `settings.json` under the lock the window uses.
16. **`rekordbox preview`** decodes the file (seconds) and takes no lock but opens rekordbox's library read-only
    (`problem: busy` while rekordbox is open) (rekordbox_cmd.py:132).
17. **`batch list`** shows the newest 20 only (`db.aiff_batches(limit=20)` db.py:1757), `count` is the total; no `--all`/paging.
18. **Console batches use scope `console`** (convert_cmd.py:293); the window's Resume heads filter on `todo:` / `library:`
    (note 5 in section 0).

---

## 6. Coverage list

Bridge methods this file covers (section 1 rows), one per line:

todo
track
select
spectrum
media_url
rekordbox_status
job_status
aiff_plan
setup_status
runs
run
open_report
upgrade
upgrade_all
batch_resume
batch_undo
undo_upgrade
rekordbox_checked
convert
rename
make_aiff
stop
set_auto_upgrade
answer_same_song
keep_duplicates
supersede_duplicate
hide
add_bought_file
search_candidates
preview
use_candidate
use_link
reject_current
show_in_finder
open_external
start_sync
sync_preview
add_watched_folder
refresh
stop_refresh
sidebar
start_import
