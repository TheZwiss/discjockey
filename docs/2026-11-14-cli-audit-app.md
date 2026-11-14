# CLI audit, area `app` (issue 39, step 1)

Evidence for the designer of the agent CLI. Area: everything outside Library and To-do: the Dashboard and All runs,
Sync (read, plan, run, end screen), Download limits, Playlists (playlists.txt, sources, tidy-up), Settings, Setup, and
the app shell (sidebar counts, the library lock and busy state, update check, jobs and events layer). Also today's
`cli.py` sync command, `setup_cmd.py` and `settings_cmd.py`. README sections: Updates, One-time setup, Settings, Where
things live, playlists.txt, Daily use, When something breaks, Account risk. Nothing was run; every statement comes from
reading the code at the checkout of 2026-11-14 (`file:line` are of that checkout, `hub-ui/src` paths are relative to
`hub-ui/src`). Where a claim is an inference and not a line of code, it says "inferred".

Short names used below: `api.py` = `discjockey/hub/api.py`, `jobs.py` = `discjockey/hub/jobs.py`, `views.py` =
`discjockey/hub/views.py`. "Window" = the pywebview app. "Console" = a `discjockey ...` process.

## 0. Where state lives (the designer needs this first)

| State | Lives in | Who sees it |
|---|---|---|
| Records of tracks, files, move batches, watched folders, Favourites, crate switches, "never download", usage per day, warning signs | `<music>/.discjockey/library.db` (SQLite) | window re-reads it on every call (`api.py:405` `_state` = `library.load_state`); a console reads the same file |
| Settings (limits, extra, accounts, switches, skipped steps, `auto_upgrade`, `read_liked_music`, last login checks, `warnings_seen`) | `<support>/settings.json`; support = `~/Library/Application Support/Discjockey` or `$DISCJOCKEY_SUPPORT` (`library.py:37`) | read fresh on every call (`api.py:408-412`); `settings.py` is the one codec |
| Which folder is the music folder | `<support>/config.json` (`library.write_music_folder`) | the window binds it at start and never swaps it while open (`api.py:2636` docstring) |
| Spotify Client ID + user name, Spotify token, Qobuz login (streamrip config, MD5 of password), browser choice per account | `<support>/` files (`api.py:2243-2262`, `qobuz.py:302-308`, `settings.accounts`) | `setup_status` says only whether they exist |
| playlists.txt | `<music>/playlists.txt`; optimistic version = hash of the bytes (`playlists_file.py:65`, `save` refuses a stale version `:135-140`) | window and any editor |
| Run reports | `<music>/.discjockey/reports/<YYYY-MM-DD_HHMMSS>.md` + `.json`, `not_lossless.md` | `runs` / `run` read the `.json` (`api.py:457-465`) |
| The library lock | `<music>/.discjockey/.lock`, `flock`, holds the PID of the holder (`library.py:228-250`, PID written `:246-247`) | every writer takes it |
| **Window memory only (lost when the window closes, invisible to a console)** | `PreviewStore` (`jobs.py:~599-707`): the last plan (`prep`), `read_at`, last read problem, `auto_read` (one automatic read per session), `stale`; `Jobs.current` (the running or last write job with its recorded events); `Jobs.refresh`, `Jobs.sign_in`; `HubApi._infos`, `_extra_tracks` (playlist names/covers/tracks read on the Playlists page), `_import_stopped`, `_import_auto_done`, `_selected`, `_qobuz_streak` | only through bridge reads |
| **Window localStorage (per window port, `window_port.py`; not readable by any command)** | `sync.scope` (playlists/folders switched off for the sync, weekly checks switched off: `pages/sync/planModel.ts:12`, `lib/stores/syncScope.ts:13-22`), `sync.howMany` (`planModel.ts:42`), `sync.lastSelection` (`pages/sync/selection.ts:5`), sidebar form, browser width, closed folds, library sort/filter, `todo.filter`, details hidden | the UI alone |

Consequence stated once: the Sync plan an agent would want to read (`sync_preview`, `dashboard.ready`, `limits.still_to_load`,
`read_status`) exists only in the window's memory after a "Read playlists", and the Sync page's switches, ticks and
"how many" choice exist only in the window (ticks are not even in localStorage: only the last started selection is).

## 1. Actions and reads

Common safety, referenced as S1 to S6 in the tables:

- **S1** Every bridge method answers `{ok:true,...}` or `{ok:false, kind, message[, service, setting]}`, never a traceback (`api.py:167-193`, kinds in `lib/bridge/types.ts:3`). Methods in `LIBRARY_METHODS` (`api.py:94-108`) answer `no_library` first when no music folder is bound or it is gone (`_need_library` `api.py:345`).
- **S2** Write job (`Jobs.start`, `jobs.py:427`): one at a time (`busy`), refused while a console run holds the lock (`console`, `jobs.py:436`), runs under the library lock and keeps the Mac awake (`jobs.py:521-532`). The bridge answers `{job_id}` at once; the outcome is the `JobFinished` event `{job_id, kind, ok, problem, message, result, service}`, also kept in `job_status().job.finished`. A job that holds the lock first finishes interrupted steps (`library.recover_pending`; the window shows the messages as a toast, `lib/bridge/client.ts:236-239`).
- **S3** Settings save outside a job (`_update_settings`, `api.py:2382`, uses `Jobs.lock_briefly`, `jobs.py:377`): takes the lock for the moment of the save; `busy` or `console` instead of waiting.
- **S4** Brief records write (`_brief_write`, `api.py:995`): no engine lock (works during a sync), SQLite wait up to 1.5 s, then `busy`.
- **S5** Network reads that would pace badly: `_no_sync_running` (`api.py:1301`) answers `sync_running` while the window's sync or any console run is on.
- **S6** Plain reads: no lock, no job.

Long run legend: "job" = write job with events (S2). Events are the 22 types of `lib/bridge/events.ts:20-34`.

### 1.1 Sync: read the plan, run it, follow it

| Method (api.py line) | Where the user triggers it | What it does | Hub's own safety | Long run? | Today's command | Gap |
|---|---|---|---|---|---|---|
| `sync_preview()` 800 | Sync page (opens, after every `JobFinished`, `dataVersion` bump): plan, kinds strip, "This run" panel | Reads the stored plan (`PreviewStore.prep`), no network: `groups[]` of actions (each `key [kind, track_id, to_dir]`, `kind`, `reason`, `folder`, `in[]` collections, `run` index, cover), `estimate` (limit, left, per-account `uses_by_downloads`, `minutes_by_downloads`), `never[]`, `dropped[]`, `ambiguous[]`, `notes[]`, `folders[]`, `collections{}`, `waiting_answers`, `deferred_checks`, `auto_upgrade {on, ready}`, `read_status`, `empty` (`views.py:2033-2082`) | S6. `empty: "no_preview"` until a read happened in this window session | no | `--dry-run` (`cli.py:199-203`): re-reads playlists (network), prints the plan as text; `--json` gives only `counts` by kind, no per-track list | No read of the plan as data. Dry-run JSON lacks tracks, action keys, estimate, never/dropped/ambiguous/notes, waiting answers, auto-upgrade rows (those are only in the text). No way to read a plan without a re-read (the plan lives in window memory). |
| `refresh(auto)` 812 | "Read playlists" in the page header (every playlist page), automatically when the window opens (`auto=true`) | Job kind `refresh` (`Jobs.start_refresh`, `jobs.py:441`): `run.prepare(dry_run=True)` = scan Library/ into library.db when the lock is free, read every enabled playlist over the network (rate-limit waits), plan, store the plan in memory; also reads each playlist's name/owner/cover for the Playlists page (`jobs.py:~656-690`). | No library lock of its own (scan under `scan_lock`, `jobs.py:397`; skipped when a job or console holds the lock). `busy` if a read runs; refused while the window's sync runs. `auto=true` only once per session (`AUTO_READ_DONE`, `api.py:818-820`). Own Stop (`stop_refresh`). | yes: `JobStarted(refresh)`, `ReadingPlaylist(index,total,folder)`, `Message`, `Waiting`, `JobFinished(result {actions})`; minutes | none; nearest `--dry-run` (but takes the lock for the whole read, `cli.py:333`, and stores nothing) | No "read playlists" that updates what the window/agent reads next. Reading is bound to a process: nothing persists the plan. |
| `stop_refresh()` 872 | "Stop reading" | Cancels the read and finishes the job at once; late data is dropped (`jobs.py:479`) | only the read job | no | Ctrl-C of a dry run | none |
| `job_status()` 876 | Shell (`refreshHub`, `lib/stores/hub.ts:166-186`), account panels (restore a waiting sign-in) | Snapshot: `job` {id, kind, track_id, batch_kind, running, stopping, `last` newest event per type, `usage[]`, `results[]` (ActionFinished), `finished`, `actions[]`}, `sign_in`, `refresh_running`, `console_running` (lock probe, `jobs.py:368`), `read_status` {read_at, minutes_ago, problem, problem_service, message, stale, reading, offline, auto_read, services[{service, connected}]} | S6 | no | none | A console cannot ask "is a run going, which, how far". `console_running` and `read_status` have no command. |
| `start_sync(selected)` 1710 | Sync page "Start sync" | Job kind `sync` (`sync_work`, `jobs.py:~690-745`): needs a stored plan ("Read your playlists first (↻)" otherwise); recovery, `.tmp` cleanup, **fresh** `run.prepare` (reads playlists again), keeps only actions whose `[kind, track_id, to_dir]` key was in the preview **and** is in `selected` (`run.select_actions`, `run.py:293-312`; others get a "queued" result: "left out" or "new since the preview"), logs in to Qobuz only when needed, `run.execute` (downloads, converts, analyses, files, report), then the Auto-upgrade phase (rekordbox) when its switch is on; then re-plans the stored preview (`preview_after_run`, `jobs.py:~748`) | S2; `busy`/`console`. Resets the Qobuz auto-stop streak. Stop works between steps. A crash is filed with a crash note as the run's report (`jobs.py:~720-735`). | yes, 1 to 2 h per 60 downloads: `JobStarted(sync)`, `ReadingPlaylist`, `RunStarted(total, actions[])`, per action `ActionStarted`, `StepChanged(search\|download\|check\|convert\|analyse\|compare)`, `Progress(done,total,unit)`, `Waiting(search\|between\|break\|fallback, remaining)`, `SourceChosen`, `Checked`, `AccountUsage`, `ActionFinished(result)`; last phase `BatchProgress`; `RunFinished(exit_code, report_path)`; `JobFinished(result {exit_code, report, actions, new_since_preview})` | `discjockey [--yes] [--dry-run] [--limit N] [--extra N] [--verbose] [--json]` (`cli.py:174-261`): plans and runs **everything** the fresh plan holds; no selection, no preview binding | Biggest gap. A console sync cannot be given the actions a person reviewed (keys), a subset by playlist/folder/kind, or "the first N in scope" except `--limit` (downloads only, ignored by the dry-run). No progress as data except stderr text. See sections 2 and 5. |
| `stop()` 1724 | "Stop safely" (Sync live view, foot), Cancel on imports/tidy/Spotify login | Cancels the running write job's token: it ends after its current step, nothing half done (`jobs.py:469`) | only the window's own job; returns `{stopped: bool}` | no | Ctrl-C in the console process (`cli.py:152-171`: first press stops after the current step, a second one a second later stops at once; repeats within 1 s are ignored `:30`); the lock file holds the holder's PID (`library.py:247`) so a second process could send SIGINT, undocumented | No `stop` command for a run another process holds; no stop for a hub job from outside. |
| `never_download(track_id, never)` 1762 | Sync plan row "Never download", fold "Download again" | Job kind `never_download`: writes `state["never"][track_id]` in library.db, rewrites `not_lossless.md`, logs the operation; the stored plan moves the track at once (`views.planned`); only `acquire` rows can be set (`canNever`, `planModel.ts:74`) | S2; "not in the sync plan any more" `changed` when the track left the plan; nothing is downloaded or deleted; undo = same call with `never=false` | no (job, instant) | none | No command to mark/unmark, nor to list the never list (only inside `sync_preview.never`). |
| `rekordbox_status()` 775 | Sync page (opens, window focus) | `{state: ready\|none\|unreadable, running}`: cached read-open of rekordbox's library + process check; works without a music folder | S6 | no | `discjockey rekordbox status [--json]` (`cli.py:78`, `rekordbox_cmd.py` `run_status`) | Exists. JSON is a superset (adds version, library, problem, db_version). |
| `spectrum(track_id, which)` 1130 | Sync live card ("analysed" card) next to Library/To-do | Spectrum image data for a track's file | S6 | no | none | Probably no agent need (the run results carry `cutoff_hz` and `status`); Library/To-do audit decides. |

### 1.2 Dashboard, runs, reports

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `dashboard()` 764 | Dashboard (opens, every `dataVersion` bump); Sync (BeforeStart "up to date" panel: last run + upgrades count; LiveView: Qobuz today) | `views.dashboard` (`views.py:353`): `greeting` (time of day), `read_status`, `tiles` {lossless share + `by_quality`, `qobuz_today`, `still_to_load`, `account_today`}, `ready` {counts, actions, estimate} (from the window's in-memory plan), `needs_you` {upgrades, swappable, not_found, weak}, `folders[]` (per playlist: tracks, lossless share, by_quality), `last_runs[]` (8), `has_more_runs`, `next_checks`, `empty` (`no_playlists`\|`not_set_up`\|`empty_library`) | S6 | no | none | Whole screen has no command. `ready`/`still_to_load`/`next_checks` are null without a window-memory plan. |
| `runs()` 1118 | All runs page; Settings "Reports" row (count) | Every report `.json` as `run_summary`: run_id, started, finished, `duration_s`, `exit_code`, `counts {lossless, lossy, problems, moved}`, `stopped_after` (only exit 130), `auto_upgrade` block + `line` (`views.py:262-297`) | S6 | no | none (a sync prints "Report: <path>" at its end, `cli.py:227,257`; JSON `report`) | No list of runs. An agent can read `.discjockey/reports/` by file if it knows the folder. |
| `run(run_id)` 1122 | End screen of a sync, a run opened from Dashboard/All runs, "up to date" panel (stats of the last run) | `run_detail`: summary + `sections{<name>: [Result]}`, `needs_you[]` (problem rows with a track), `for_rekordbox {new_files, folders}`, `upgrades_ready`, `report_md` ("reports/<id>.md"), `queued`, `folder_order` (`views.py:300-321`). `Result` = {section, folder, artist, title, track_id, note, status, source, cutoff_hz, path, error_kind, found_status} | S6; `refused` "That run report is not there any more." for an unknown id (`RUN_ID` pattern `api.py:61`) | no | none | No way to read a run in structured form from the console except the sync's own end JSON (`counts`, report path). |
| `open_report(run_id)` 1200 | End screen "Full report", problem cards "Open report" | Opens `reports/<id>.md` with the default app (`open_path`) | S6; run id pattern checked | no | none | Not needed for agents if `run` returns the path (it returns a relative `report_md`). |
| `reveal(rel_path)` 1177 | Settings (Music folder "Show in Finder", Reports folder), end screen (a playlist folder), Library/shell | Shows a place in Finder: a path inside the music folder, or an absolute path inside a watched import folder; refuses any other path | S6; `ValueError` for places the library doesn't know (`_watched_place`, `_inside_root`) | no | none | Opens a GUI. For an agent: print the path (human step if it should look). |

### 1.3 Shell and app-wide reads

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `sidebar()` 771 | Shell (after every job, console end, drives change; `refreshHub`) | `views.sidebar` (`views.py:1411`): `todo` count (the To-do count, `_todo(count_only)`), `all_tracks`, `not_in_playlist`, `limits_warning` (an unseen warning sign or a service paused today), `favourites[]`, `playlists[]` {name, ref, service, enabled, songs}, `watched[]` (import folders with crates, state here/offline/missing), `library_folders[]` | S6 | no | none | Counts and the nav signals have no command. |
| `setup_status()` 1149 (function `api.py:226`) | Shell gate, Setup, Settings rows, many panels | `{music {state ok\|missing\|not_chosen, path}, tools {ffmpeg, ffprobe, deno}, spotify_app, spotify_login, spotify_user, qobuz, playlists, complete, next_step, version, qobuz_skipped, spotify_skipped, youtube_music {liked_music, can_turn_on, listed}, auto_upgrade, existing, import_folders, import_skipped, qobuz_last_check, accounts{youtube, soundcloud}}`; never a secret | S6; works without a music folder | no | `settings auto-upgrade` reads one field; `rekordbox status` another | No read for the rest. `complete` and `next_step` do not count "Your existing music" (`api.py:265-271`); the window computes its own step list (section 2). |
| `app_update()` 1224 | Shell (boot, sidebar line), Settings > About | The last answer of the update check `{state: available\|up_to_date\|unknown, current, latest, url}`; never the network (cached in `<support>/cache/app_update.json`, GitHub at most once a day, window ticks every hour `api.py:145`) | S6 | no | none | A console never checks for a newer version. |
| `rescan_library()` 1791 | Window start; window back to the front after more than 60 s (`lib/stores/rescan.ts`, `rescanModel.ts:6`) | Job kind `scan`: indexes Library/ against library.db (files moved/replaced by hand), re-plans the stored plan if anything changed; returns `{moved, new, gone, changed, copies}` | S2; the page ignores busy/console answers | yes (seconds to minutes; no progress event) | none; every sync and dry run scans first (`run.py:90-95`) | No explicit "scan" command; a dry run is the only console way and it takes the lock. |
| `quit()` 2605 | Settings > Programs and music folder change: "close, open Discjockey again" | Destroys the window after 0.3 s; refused while a job runs (`busy`) | refused with a running write job | no | none | Window-only; not for agents. |
| `open_external(url)` 1216 | Every external link (Spotify dashboard, Qobuz password page, buy links, release page) | Opens an `https://` URL in the system browser | URL pattern only | no | none | Human/GUI step; the agent should print the URL for the user. |
| `library(...)` 881, `track(id)` 906, `hide(id, bool)` 1757, `select(id)` 1163 | Called from shell code (BrowserColumn, `lib/listen.ts`, Foot, router/SearchField) | Library/To-do territory | see Library and To-do audits | | | Covered by the Library and To-do audit files. |

### 1.4 Download limits

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `limits(service)` 1105 | Limits page (`#/limits/<service>`; `service` qobuz\|youtube\|soundcloud) | `views.limits` (`views.py:481`): `cards[3]` {service, set_up, used, allowance, warnings, new_warnings, paused}, and for a set-up service `usage` {today {used, allowance, limit, carry_over, extra, remaining}, `days[14]`, `still_to_load` (needs the window's plan), `setting` {limit, extra_today, recommended, zones[], min 1, max 500, extra_max 200}, `assessment`, `what_if`, `signals[]` (14 days, each `new`, `clears_in`), `signal_summary`, `behind` ("Qobuz" when the account sits behind it), `last_download`} | S6 | no | none | No limits read. `--extra` is the only limit knob on a command. |
| `limits_what_if(service, limit, extra_today)` 1109 | Limits page: drag the risk scale / type a number (throttled 150 ms, `limitsModel.ts:12`) | Pure calculation (`views.limits_what_if`, `views.py:465`): `assessment`, `allowance_today`, `remaining_today`, `days_to_load` (null for an account behind Qobuz), `run_minutes` | `ValueError` outside 1..500 / 0..200; `refused` for a service not set up | no | none | Could be a flag of a read. |
| `save_limits(service, limit, extra_today)` 1729 | Limits page foot "Save N a day" | Job kind `save_limits`: `settings.with_limit(service, limit, today if extra else None, extra)` to settings.json | S2; set-up service only (`refused` "Set up X first."); bounds as above | job (instant): `JobFinished(result {service, limit, extra_today})` | `--extra N` on the sync only: Qobuz, one-time for today (`run.py:111-115`, saved into settings.json **even with `--dry-run`**), range 1..200 else `config_invalid` exit 2; daily limit: none (hand-edit settings.json) | No command for the daily limit of any service; `--extra` is Qobuz-only while the window's extra is per service. |
| `mark_warnings_seen(service)` 1744 | Limits page "Got it" | Job `mark_warnings_seen`: `settings.warnings_seen[service] = now`; the card and the sidebar dot go quiet; signs stay listed 14 days | S2 | job (instant) | none | No command; the "new" flag on signs is a read of `limits`. |

### 1.5 Playlists and sources (playlists.txt)

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `playlists()` 1423 | Playlists page; Sync (names for the login hint); Setup "First playlist" | `views.playlists` (`views.py:2374`): `version` (hash), `problem` (file can't be parsed), `rows[]` {index, folder, link, playlist_id, service, service_name, enabled, info {name, owner, cover...}, `needs_setting`, tracks, `quality` by quality}, `overlaps[]` (tracks in several playlists, where they land), `empty`, `tidy {waiting}` (files out of place) | S6; names/covers only after a window read (`_infos` is memory) | no | none; playlists.txt is a text file (README "playlists.txt") | No read of the structured list; `info`/`tracks` exist only after a window read. |
| `add_playlist(url)` 1429 | Playlists "Add to the list", Setup "First playlist" | Resolves a pasted link: expands short links (`sources.expand`), cleans it, recognises the service, needs that service's login (`not_set_up`), reads name/owner/cover and all tracks over the network (SoundCloud/YouTube Music in one read), a Liked music link only while Settings allows it (`setting_off`); stores facts in memory; answers {playlist_id, service, link, info, tracks, readable, suggested_folder, hint}. Adds nothing to the file. | `_no_sync_running` (S5); records warning signs of a Liked music read | no (seconds) | none | No console check of a link. `suggested_folder` is an engine rule (`api.py` `suggest_folder`, `:2670`). |
| `preview_playlist_change(lines)` 1473 | Playlists, while a draft is unsaved (debounced 300 ms) | "What this change does" for edited lines: new downloads and days, tracks left out, per-folder file counts, the **save question** (files that would sit in another folder: `tidy` rows each with `ticked`, `skip`, `yours`, and `renames[]` offers `offered`/`why_not`/`files`), reroutes, `problem` (invalid lines); one-time reads of unread playlists | S5; changes nothing | no (can read playlists: seconds to minutes) | none | No dry run of a playlists.txt change. |
| `save_playlists(lines, loaded_version, files)` 1523 | Playlists "Save" and the save question's two buttons; Setup adds the first playlist | Job kind `save_playlists`: validates all rows (`pf.validate` = the sync's own parser, also off rows), writes playlists.txt atomically **only if** `loaded_version` still equals the file's hash (`changed` = "changed elsewhere" otherwise), marks the plan stale; with `files {choice leave\|move, renames [[old,new]], moves [[file_id, from_path]]}` also moves/renames folders on disk as undoable batches (`tidy.after_save`); `leave` makes the files "yours" | S2; version check; nothing deleted; moves only in the batch the user chose; Stop keeps what moved (`failed_result`) | job; with moves: `MovesProgress(batch_id, done, total)`; `JobFinished(result {version, batches[]})` | none (edit the file by hand: no lock, no version check on the editor's side; the code comment says the caller holds the run lock `playlists_file.py:136`) | No console way to add, remove, rename, reorder, switch off a playlist, nor to answer the save question. |
| `set_read_liked_music(on)` 2302 | Settings > YouTube Music "Read my Liked music" | Job: `settings.read_liked_music`; turning on needs a YouTube account (`not_set_up`); off never touches playlists.txt | S2 | job (instant) | none | No command. |
| `add_liked_music()` 2332 | Settings > YouTube Music "Add Liked music to Playlists"; Playlists link field | Job: appends `Liked_music = <link>` (or `Liked_music_2` ...) to playlists.txt, marks plan stale | S2; `setting_off` while the choice is off; `exists` when listed already | job (instant): result {folder} | none | No command. |

### 1.6 Tidy up files and move batches (Playlists page)

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `tidy_preview()` 1588 | Playlists "Tidy up files" | Every file the playlist order would put elsewhere (`planner.tidy_rows`): rows {file_id, from_path, artist, title, `ticked` default, `yours` (user's own placement), `skip` reason}, counts, rekordbox warning | S6 | no | the sync prints only a count line "N files are not where the playlist order puts them; tidy up in the window" (`cli.py:105-130`, `planner.out_of_place`); "the console never moves files" | No list, no move. |
| `tidy_up(moves)` 1620 | Move button (ticks as the list shows) | Job kind `tidy`: moves the chosen `[[file_id, from_path]]` to their playlist folder as one batch; result BatchResult {batch_id, moved, skipped[{reason...}]}; never renames files | S2; path as the preview showed (a changed file is skipped and listed); nothing deleted; undoable; Stop between files | job: `MovesProgress`; `JobFinished(result BatchResult)` | none | No command; defaults (`ticked`, `yours` untouched) are computed in the engine, the ticks in the window (`tidyModel.ts:78`). |
| `move_batches()` 1594 | Playlists panel "Recent moves" | The 20 newest batches (tidy-ups, saves, renames, undos), with titles and whether undoable | S6 | no | none | No list. |
| `undo_preview(batch_id)` 1606 | Click "Undo" on a move | Move by move what an undo would do, `Can't move back` reasons | S6 | no | none | |
| `undo_moves(batch_id)` 1638 | Undo confirmation button | Job `undo_moves`: undoes a batch as a batch of its own | S2; skips changed files and lists them | job: `MovesProgress`, `JobFinished` | none | |

### 1.7 Settings: logins and accounts (Qobuz, YouTube Premium, SoundCloud Go+, Spotify)

Account services: `qobuz`, `youtube`, `soundcloud` (downloads) and playlist services `spotify`, `qobuz`, `soundcloud`, `youtube_music`.

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `downloads_view()` 1153 | Settings (source ladder + panels), Setup "Downloads" | `views.downloads` (`views.py:422`): per source `state` (`on`\|`off`\|`skipped`\|`paused`\|`used_up`\|`no_premium`\|`unreadable`), `last_check {ok, problem, kbps, at}`, saved `browser`, `profile`, `profile_name`, `tracks` count, and `library {lossless, account, free}` by rung | S6 | no | none | No read of the login state; `qobuz_last_check`/`accounts` exist in `setup_status`. |
| `find_logins(service)` 2441 | Account panel opens | Which installed browsers/profiles hold a YouTube or SoundCloud login: `browsers[] {id, name, default, readable, problem, profiles[{id, name, signed_in}]}`; reads cookie names from copies, never asks macOS for a password | S6 | no | none | |
| `setup_account(service, browser, profile)` 2407 | "Use this login", "Check again" (accounts) | Job `setup_account`: checks the login in that browser profile with one real lookup (`check_account`), saves browser+profile and the check into settings.json when ok or `no_premium` (YouTube without Premium is kept for Liked music); result {saved, check {ok, problem, kbps, message}} | S2; may open a macOS keychain prompt ("Chrome Safe Storage": human clicks Always Allow) | job, seconds | none | No console command; today's `setup` has no YouTube/SoundCloud step at all. |
| `account_sign_in(service, browser, profile)` 2457 | "Sign in" | Own slot `Jobs.start_sign_in` (`jobs.py:453`): opens the sign-in page in the browser, waits up to 10 min for a login to show up (`_SIGN_IN_TIMEOUT` `api.py:147`), then checks and saves as `setup_account` | not while a sync runs or starts meanwhile (`sync_running`); runs beside write jobs without the lock; Cancel = `stop_sign_in`; only one at a time | yes: `SignInPhase(waiting\|checking)`, `JobFinished` | none | **Human step** (the login is typed in the browser); an agent can only start it and wait. |
| `stop_sign_in()` 2510 | "Cancel" | Cancels the waiting sign-in | | no | none | |
| `open_privacy_settings()` 2515 | Safari card button | Opens System Settings at Full Disk Access | | no | none | Human step. |
| `setup_check_account(service)` 2554 | not called by any UI file (kept in the bridge and client) | Re-checks the saved login synchronously (not a job) and records it | S5; `refused` when not set up | seconds | none | Unused by the window; duplicate of `setup_account` with the saved browser. |
| `setup_forget_account(service)` 2568 | "Sign out" (YouTube/SoundCloud, after a confirm) | Job: removes `accounts[service]` from settings.json (the browser keeps its login) | S2; the window asks first (`accountFlow.svelte.ts:122-131`) | job (instant) | none | |
| `qobuz_check_login()` 2521 | Qobuz "Check again" | Job: logs in with the saved login, one test search; records `qobuz_last_check` (failed only when Qobuz refuses the login) | S2+S5 (`sync_running`) | job, seconds | none (the sync itself logs in: `cli.py:235-241`) | |
| `setup_qobuz_login(email, password)` 2356 | Qobuz form "Sign in" | Job: stores the login (MD5 of the password, `qobuz.py:302-308`), test search; records the check; clears `skipped`; the password is read out of the field and not kept (`takeSecret`) | S2; a refused login restores the old config; password goes in a method argument | job, seconds | `discjockey setup` asks e-mail and password at a prompt (`setup_cmd.py:124-134`, `qobuz.interactive_login` `qobuz.py:250`) | No non-interactive way: the password must not sit on argv; designer must choose stdin/env/file. |
| `setup_skip_qobuz()` 2391 | "I don't have Qobuz" | Job: `qobuz_skipped=true` | S2 | job (instant) | none: `setup` cannot skip Qobuz (`setup_cmd.py:107-112` fails when login fails) | |
| `setup_save_client_id(client_id)` 2243 | Spotify step / Settings "Spotify app (Client ID)" | Job: validates 32 hex chars (`api.py:2247`), writes `spotify_app.json` | S2 | job (instant) | `setup` asks for the ID (`setup_cmd.py:61-75`, same check) | |
| `setup_spotify_login()` 2274 | "Connect" / "Connect again" | Job: opens the system browser for Spotify's login, waits for the callback (up to 5 min or `stop`), stores the token and the user name, clears `spotify_skipped`, clears a stored read problem about Spotify | S2; Stop = Cancel | yes (minutes, human): `JobFinished(result {user})` | `discjockey setup` does it (`setup_cmd.py:89-97`, prints the link too) | **Human step** (browser login). |
| `spotify_sign_out()` 2260 | Settings > Spotify "Sign out" (after a confirm) | Job: deletes the token, keeps the Client ID | S2 | job (instant) | none | |
| `setup_skip_spotify()` 2292 | "I don't use Spotify" | Job: `spotify_skipped=true`; connecting later un-skips | S2 | job (instant) | `setup` with Enter and none saved sets it (`setup_cmd.py:98-102`) | |

### 1.8 Settings: other rows

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `set_auto_upgrade(on)` 2318 | Settings > Upgrades, Setup > Downloads | Job `set_auto_upgrade`: `settings.auto_upgrade` (on by default); never touches waiting upgrades | S2; `refused` for a non-boolean | job (instant) | `settings auto-upgrade [on\|off] [--json]` (`settings_cmd.py:24-62`) | Exists. Needs a music folder even for a read (`settings_cmd.py:43-44`). Only setting with a command. |
| `setup_check_tools()` 2228 | Settings > Programs, Setup > Programs | `{tools {ffmpeg, ffprobe, deno: bool}, missing[], hints{brew install ...}, redirect_uri, download_tools {yt-dlp: version, "built in"\|"updated", waiting restart, back version}, download_tools_problem}` | S6 | no | `setup` prints missing programs with the brew line (`setup_cmd.py:85-88`) | No JSON read. |
| `update_tools()` 2578 | Settings > Programs "Update download tools" | Job: newest yt-dlp (+ yt-dlp-ejs) from PyPI into `<support>/tools`, hash-checked, tested in a fresh process (`tool_updates.update`); result {before, after, restart}; needs reopening the app | S2; `check` = Stop; current version stays when anything fails | job, minutes? seconds; result `restart:true` | `discjockey update` (`setup_cmd.py:137-148`, `cli.py:337-339`) | Exists; text only, no `--json` (`cli.py:98` rejects it), takes the library lock and a music folder though it only touches `<support>` (`cli.py:326-339`). |
| `rollback_tools()` 2592 | Settings > Programs "Go back to ..." (after a confirm) | Job: yt-dlp as before the last update | S2; `refused` when nothing to go back to | job | none | |
| `open_licenses()` 1207 | Settings > About "Show licences" | Opens the licences folder in Finder | | no | none | GUI only. |
| `set_favourites(keys)` 1013 | Library/Sync browser column (drag, context menu) via `lib/stores/hub.ts:204` | Replaces the Favourites list (`playlist:<ref>` / `folder:<path>` keys, order) | S4; keeps stored keys whose target is gone | no | none | Library agent covers the rows; the writer lives in shell code. |
| `set_crate_shown(path, shown)` 1041, `set_crates_shown(paths, shown)` 1054 | Settings > Watched folders crate switches (All / None), browser column "Hide" | Records whether a crate (sub-folder of a watched folder) is a row in the sidebar; `shown` true\|false\|null (back to the default); `set_crates_shown` is all-or-nothing | S4; `ValueError` unless every path is a crate of a watched folder now | no | none | |

### 1.9 Setup, music folder

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `pick_folder(start)` 2617 | Setup "Choose...", Settings "Change...", missing screen, Add folder... | Native macOS folder dialog; `{path}` or null on cancel | `refused` without a window | human | none | **Human step by nature**; an agent passes a path to the next call. |
| `check_music_folder(path)` 2629 | Setup/Settings after choosing | What the folder would be: `{path, exists, usable, problem, kind: new\|empty\|discjockey_library\|other_files, message}`; changes nothing | S6 | no | `setup` ask_music_folder uses `library.check_music_folder` (`setup_cmd.py:157-177`) | |
| `set_music_folder(path)` 2636 | "Use this folder" (asks first for `other_files`; asks to close the app when one is bound) | Writes `config.json`; makes a new folder; binds the library at once when none was bound, else `{restart:true}` (a bound library is never swapped while the window is open); runs the first read | takes the library lock briefly (`lock_briefly`) unless the old folder is gone; `refused` for an unusable folder | no | `discjockey setup`'s first question (`setup_cmd.py:157-177`, `cli.py:326-331`) | No non-interactive form; `setup` cannot change an existing choice (once chosen the question is not asked). |
| `retry_music_folder()` 2663 | Missing-folder screen "Try again" | Binds the library when the folder is back; answers `{music}` | | no | none | |
| `setup_skip_import()` 2400 | Setup "Your existing music" Skip / Continue with no folder | Brief settings save (not a job): `import_skipped=true` | S3 | no | none | |

### 1.10 Watched folders and the import (Settings > Watched folders, Setup > Your existing music)

| Method | Trigger | What it does | Safety | Long? | Today | Gap |
|---|---|---|---|---|---|---|
| `watched_folders()` 969 | Settings, Setup, Library | `views.watched_folders`: folders (Library first, then imports) {id, kind, path, state here\|offline\|missing, counts (files, imported, linked, ...), crates[], too_many}, `unreadable[]`, `waiting`, `stopped` (this session), `phase` of a running import | S6 | no | none | The console only says "N files in your watched folders wait to be imported. Open the window to import them." (`console.py:~27`, `cli.py:185-186`): by design the console never imports. |
| `check_import_folder(path)` 1071 | Add folder... | Whether a folder can be watched; `merges[]`, `merge_hints[]` | S6 | no | none | |
| `add_watched_folder(path)` 1808 | Add folder... | Watches the folder and imports it in the same job (kind `import`) | S2; checked first (`refused` with the words); busy while an import runs | yes: `ImportProgress(phase scan\|facts\|tags\|sound\|link, done, total, unreadable)`; `JobFinished(message "Imported 3 files.", result ImportResult)`; stopped = problem `stopped` with the result | none | No import from the console at all (`console.py` IMPORT_WAITING). Also starts by itself when the window opens (`api.py:850-870` `_auto_import`, once per session unless the user stopped one). |
| `start_import()` 1818 | "Continue import" | Same import, where it stopped | S2 | yes (as above) | none | |
| `removal_preview(folder_id)` 1091 | Remove (asks first) | `{name, files, redownload}`: what removing takes away | S6 | no | none | |
| `remove_watched_folder(folder_id)` 1824 | "Remove folder" after confirm | Job kind `folders`: stops watching; files stay; the plan is made again; `{files, redownload}` | S2 | job (fast) | none | |

## 2. Logic the window does itself

"Engine has it?" = whether a bridge payload or engine function already gives the same answer. Numbered U1..; count at the end.

### Sync (`pages/sync/`)

| # | `file:function` | What it decides | Engine has it? |
|---|---|---|---|
| U1 | `planModel.ts:110 memberOn`, `:100 targetOn`, `:116 inScope` | Which plan rows are "in" the sync: a song is out only when **every** playlist/folder it belongs to (`row.in[]`) is switched off; a folder switched off takes folders inside it; weekly checks switched off remove rows by kind. The switches are in localStorage (`syncScope.ts:13-22`, key `sync.scope`) | Engine gives `in[]` and `collections{}` (`views.py:2033`, `_members`) but not the switches. **No switch state in the engine.** |
| U2 | `planModel.ts:52 kindOf`, `:60 WHY`, `:189 KIND_SHARE`, `:204 kindShares`, `:230 weeklyItems`, `:238 planCounts` | Row kind (new / retry / redownload / bought / weekly) from `kind`+`reason`; the strip's counts and words; per-collection counts for switch tooltips | Partly: `groups[].key` is `acquire:new`... and `counts` (`views.py:180 plan_counts`: new, retries, redownloads, bought, weekly_checks) but not per collection |
| U3 | `planModel.ts:277 presets`, `:286 defaultHowMany`, `:287 presetN`, `:301 presetTicks` | The "how many" chips (5, 10, 25, 50, "fits today", All) and which rows a chip ticks: every non-download in scope plus the first N downloads in scope in run order | Engine has `estimate.left` and the `run` order; not the presets. CLI `--limit N` (`cli.py:46`, `execute.py:90-140`) is the same idea, computed separately, and ignores scope and ticks |
| U4 | `selection.ts:24 carryTicks`, `BeforeStart.svelte:127-144` | Ticks after a re-read: an old row keeps its tick, a new row is ticked, a vanished one is dropped | none (window state) |
| U5 | `planModel.ts:119 chosenOf`, `BeforeStart.svelte:251-260` | What Start sends: ticked rows in scope, as `[kind, track_id, to_dir]` keys | Engine takes the keys (`run.select_actions`); the choosing is only in the window |
| U6 | `planModel.ts:313 nextSyncSet`, `:367 runTotals`, `:386 runCount`, `:395 runsNothingToday`, `:479 mayWaitToday` | `uses = min(downloads, left)`, which ticked downloads wait for the next sync, "nothing runs today" (Start disabled), days and "Later" counts | Engine gives `estimate.left/limit`, `minutes_by_downloads[]`, per-account `uses_by_downloads[]` (`views.py:208 sync_estimate`) and `days_to_load` (`views.py:123`); the `min`, the waiting set and the days are repeated in `lib/days.ts` |
| U7 | `planModel.ts:343 serviceRows` | Per account "uses N of M left" text from `uses_by_downloads` | Table is the engine's; text is UI |
| U8 | `selection.ts:6 SECONDS_PER_DOWNLOAD=70`, `:49 minutesLeft` | Time left during a run (70 s per remaining download, ceil minutes) | `views.py:38,110 run_minutes` (5-minute rounding, different rule) |
| U9 | `planModel.ts:17 shouldAutoRead`, `stores/hub.ts:46 readBlockIn`, `:67 readNeedsSetupIn`, `:34-39 writeBusy/syncRunning/writeBlockedReason` | When the page starts the session's read; which service blocks reading (login missing/expired); "setup first"; "write blocked" (job running or console) | Engine has `read_status.auto_read/problem/services`, `console_running`, `job.running`; the combination is UI |
| U10 | `planModel.ts:419 startNote` | The one note under Start: console running, nothing today, rekordbox open vs Auto-upgrade plan | Engine gives `auto_upgrade {on, ready}` and `rekordbox_status.running`; the rule is UI (also in `auto_upgrade.before_start_line` for the console) |
| U11 | `pages/sync/view.ts:14 whichView` | Which of before / live / end shows | view state |
| U12 | `stores/run.ts:55 reduceRun`, `:130 runFromSnapshot` | The live run state (index/total, current action, step, rate, waiting, results, usage) from events or from `job_status().job` | Engine has the events and the snapshot; the reducer is UI (a console needs its own) |
| U13 | `cardState.ts:180 verdict`, `:204` | Quality badge of a result: weak = lossy with `cutoff_hz <= 17000` | `views.py:39,56 WEAK_HZ`, `quality_class` (same threshold, duplicated) |
| U14 | `endModel.ts:11 NEW_FILE_SECTIONS`, `:44 lastSyncStats`, `:159 endModel`, `:84 endTitle`, `:134 groupByFolder`, `:111 autoRows` | What "added", "moved", "need you" mean; titles by exit code (130 "stopped", 1 "some problems"); the notes (stopped after N, waiting N, new since the check); grouping new files by folder; Auto-upgrade parts (upgraded / still waiting / couldn't go in) | `views.py:49 NEW_FILE_SECTIONS` (same list), `run_summary counts` (a **different** "added" = lossless+lossy sections, `views.py:262`), `report.py` `summary` for the console. Two definitions in the engine and UI of "what a run did" |
| U15 | `results.ts:11-22 isLossless/isLossy/chipCounts` | Chips All/Lossless/Lossy/Problems on the live list | engine `LOSSLESS_SECTIONS` (`views.py:45`) differs in detail |
| U16 | `planModel.ts:451 matches`, `format.ts foldText` | Search in the plan (accent/case folded artist+title) | none needed by CLI |

### Dashboard and runs (`pages/dashboard/`)

| # | `file:function` | Decides | Engine has it? |
|---|---|---|---|
| U17 | `dashboardModel.ts:66 nextSync` | Panel state: running / unread / up to date / ready; count = `runCount`, time = `runTime` | engine `ready`, `estimate`; state machine is UI |
| U18 | `dashboardModel.ts:38 gate`, `:47 limitsLine`, `:56 dayInput` | Which service's limit counts ("Qobuz when set up, else first account"), `used + left`, days later | `views.py:156 gate` (same rule, repeated) |
| U19 | `dashboardModel.ts:86 needsRows`, `:17 healthCard`, `:101 folderLine` | The three Needs-you rows and their words, health percentage rounding | counts are the engine's (`needs_you`), words UI |
| U20 | `dashboardModel.ts:118 runLine`, `:135 runTotals`, `:145 groupByMonth` | Run status (ok / failed / stopped by exit code or `stopped_after`), totals over all runs, month groups after 10 runs | `run_summary` gives the raw numbers |

### Limits (`pages/limits/limitsModel.ts`)

| # | Function | Decides | Engine has it? |
|---|---|---|---|
| U21 | `:216 suggestion` | "Try 40 a day": two or more new pace signs in 7 days and limit above "careful" | none |
| U22 | `:186 warningRows`, `:148 SIGNAL_ORDER`, `:127 serviceStatus`, `:123 defaultService` | Per-kind grouping of signs, order, "Paused today / N new warnings / All good", first set-up service | engine gives `signals[]`, cards (`paused`, `new_warnings`) |
| U23 | `:17 zoneIndex`, `:25 riskOf`, `limits/Page.svelte level` | Which zone/level a limit is in (verdict words 1..5) | engine gives `zones[]` and `assessment` |
| U24 | `:62 clampLimit`, `:67 extraOptions`, `:56 footerLabels`, `:101 backlog` | Range (UI slider 150, field to `setting.max`), extra choices (None +5 +10 +20 +40), Save labels, backlog line | engine validates 1..500 / 0..200 (`api.py:1731-1734`) |

### Playlists (`pages/playlists/`, `lib/components/addRowModel.ts`)

| # | Function | Decides | Engine has it? |
|---|---|---|---|
| U25 | `changeModel.ts` `addRow, remove, rename, toggle, reorder, moveBy, isDirty, priorities, lines` | The draft: all edits of playlists.txt happen client-side; the engine only sees the final list | `playlists_file.py` loads/saves rows but has no operations |
| U26 | `addRowModel.ts:9 folderProblem`, `:58 playlistKey`, `:68 hasLink` | Folder name rules and "this playlist is in the list already" (a copy of `sources.recognise`) | `tidy.check_folder_names` (`tidy.py:306`), `pf.validate`; duplicate by link: `sources.recognise` (not checked whether the engine refuses duplicates) |
| U27 | `tidyModel.ts:69 groups`, `:78 initialTicks`, `:109 tickedRows`, `:116 movesOf`, `:154 initialQuestion`, `:163 carryOver`, `:223 saveFiles` | The save question: which rows start ticked (engine `ticked`), renames on by default, and the payload `{choice, renames, moves}` | engine gives `tidy.rows` with `ticked`/`skip`/`yours` and `renames[]` with `offered`; the payload is built in the UI |
| U28 | `changeModel.ts:183 panelFor`, `:214 overlapCards`, `:241 folderBars`, `:249 folderChanges`, `:123 readsOff`, `:131 infoLine` | Which panel view shows; cards per playlist that gives tracks away; per-folder deltas; "reads as off" while a setting is off; the line under a playlist | engine gives `overlaps`, `folders`, `needs_setting` |

### Settings, Setup, shell

| # | Function | Decides | Engine has it? |
|---|---|---|---|
| U29 | `settings/settingsModel.ts:81 rowLine`, `:138 firstAttention` | The state line and tone of every Settings row; which row opens first (first problem/warn) | state facts yes, the sentences and "needs the user" rule no |
| U30 | `lib/components/accountModel.ts:125 stateLine`, `:142 isWorking`, `:215 firstFound`, `:233 accountPhase`, `:282 checkPhase` | Account state line, "counts as set up", the browser/profile offered first (default browser first, first signed-in profile), phase after a check | `downloads_view` gives `state`, `last_check`; the choice of profile is UI |
| U31 | `settingsModel.ts:74 spotifyState`, `:172 toolsCard`, `:181 needsReopen`, `:232 likedPanel` | Spotify connected / left out / not connected; tools card ("built in"/"updated", reopen needed); Liked music panel | partial |
| U32 | `setup/setupModel.ts:30 stepsDone`, `:55 firstStep`, `:67 reachable`, `:90 nextRule`, `:124 doneRedirect`, `:21 checkClientId` | Setup's six steps (adds optional "Your existing music" that the engine's `complete`/`next_step` skip, `api.py:265-271`), which step is reachable, why Continue is off, the Client ID check | `setup_status.complete`, `next_step` (5 steps); regex duplicated at `api.py` `CLIENT_ID` |
| U33 | `lib/components/watchedFoldersModel.ts` `folderLine, folderMark, phaseLine, phaseShare, importView, canContinue, settingsLine, removeWords` | Import progress words, "can continue", remove dialog text | engine gives counts and `phase` |
| U34 | `settings/cratesModel.ts:11 ALL_MAX=25`, `shell/browserModel.ts:101 TOO_MANY=25`, `:513 crateShownValue` | Crates default hidden under a folder with more than 25; what `shown` value is saved (null when the default already gives it) | `too_many` flag from the engine (D8); the stored value rule is UI |
| U35 | `shell/sidebarModel.ts` `navCount, navTip, railPill` | Count column "12/40", To-do pill capped "99+" | engine gives `todo`, run index/total |
| U36 | `lib/musicFolder.ts:15 musicGate`, `:43 needsConfirm`, `musicFolderFlow.ts:43 useFolder` | Gate screens (Setup only / missing folder); when to ask "other files" and "Discjockey closes" | engine `music.state`, `check.kind` |
| U37 | `stores/rescan.ts`, `rescanModel.ts:6` | When the window asks for a Library scan: at start and after 60 s in the background | none |
| U38 | `stores/hub.ts:139-146 dataVersion` | Which events make pages read again (every `JobFinished`, `ConsoleBusy(false)`, `DrivesChanged`) | n/a (event design) |
| U39 | `lib/copy.ts` (`WRITE_BLOCKED`, `BANNER`, `problemCopy`, `successCopy`), `lib/format.ts` | The sentences for problem kinds and job successes | engine messages are plain English per call (`jobs.py:178-180`), the titles per kind are UI |

Count: 39 places where the UI decides or composes something a command would need to match. Biggest for an agent: U1, U3, U5 (sync selection), U25/U27 (playlist edits and the save question), U32 (setup progress), U14 (what a run did).

## 3. Screen states (from `6-screen-states.md`)

Column "Agent needs" separates data/decisions (D) from pure view state (V). "Read" = bridge read that gives the state; "none" = only the window holds it.

### Dashboard (13)

| Family | Shots | Read that gives it | Agent needs |
|---|---|---|---|
| Normal, big, grown | `dashboard`, `dashboard-big`, `dashboard-grown` | `dashboard()` | D |
| Empty/first run | `dashboard-first-run` | `dashboard().empty` (`no_playlists`/`not_set_up`) + `setup_status` | D |
| Plan not read | `dashboard-unread` | `dashboard().ready == null`; `read_status.read_at` null | D (depends on window memory) |
| Read problems | `dashboard-login-expired`, `dashboard-offline`, `dashboard-qobuz-not-connected` | `dashboard().read_status` (`problem`, `problem_service`, `offline`, `services[].connected`) | D |
| Running | `dashboard-syncing` | `job_status().job` (running sync) + events; `nextSync` state is UI (U17) | D |
| Up to date | `dashboard-up-to-date` | `dashboard().ready.actions == 0` | D |
| Error | `dashboard-error` | a failed bridge call (no state) | V |
| Runs | `runs`, `runs-empty` | `runs()` | D |

### Sync (57)

| Family | Shots | Read | Agent needs |
|---|---|---|---|
| Plan before start | `sync-before`, `sync-many`, `sync-many-all-off`, `sync-many-kinds`, `sync-long-plan`, `sync-long-plan-5`, `sync-long-plan-all`, `sync-long-names`, `sync-weekly-only`, `sync-weekly-only-off`, `sync-never-open` | `sync_preview()` for the rows; scope/ticks/how-many are **window only** | D (plan) + window-only D (switches, ticks, preset) |
| Scope and switches | `sync-scope`, `sync-folder-off`, `sync-filter-switches`, `sync-crates-under-off`, `sync-filter-none`, `sync-nothing-ticked` | none (localStorage `sync.scope`, ticks in memory) | D, **gap** |
| Search | `sync-search`, `sync-search-ticked` | none | V |
| Limits and money | `sync-no-qobuz`, `sync-no-qobuz-25`, `sync-qobuz-backup`, `sync-limit-reached`, `sync-downloads-wait`, `sync-before-qobuz-not-connected` | `sync_preview().estimate`, `limits()`, `downloads_view()` | D |
| Up to date | `sync-before-up-to-date`, `sync-before-up-to-date-console`, `sync-before-up-to-date-answers`, `sync-before-up-to-date-wait`, `sync-waiting-answers` | `sync_preview().empty`, `dashboard().last_runs`, `run(id)` (stats U14), `waiting_answers`; `-wait` is a loading state | D / V |
| Reading | `sync-reading`, `sync-rereading` | `job_status().refresh_running`, `ReadingPlaylist` events | D |
| Read problems | `sync-before-offline`, `sync-before-login-expired`, `sync-before-no-login` | `read_status` | D |
| Console busy | `sync-before-console` | `job_status().console_running` | D |
| Auto-upgrade note | `sync-before-auto-rekordbox-open`, `sync-before-auto-ready` | `sync_preview().auto_upgrade` + `rekordbox_status().running` | D |
| Running | `sync-downloading`, `sync-downloading-upload`, `sync-own-cover`, `sync-converting`, `sync-running-pause-list`, `sync-auto-running` | `job_status().job` snapshot, then events | D |
| Short-lived card states | `sync-analysed` (4 s UI timer `cardState.ts:10`) | none | V |
| Pauses | `sync-pause`, `sync-pause-reduced` (reduced motion), `sync-break` | `Waiting` event (`search/between/break/fallback`, `remaining`) | D (+V for motion) |
| Stopping | `sync-stopping`, `sync-stop-refused` | `job_status().job.stopping`; `stop()` failure | D |
| End | `sync-end`, `sync-end-stopped`, `sync-end-auto`, `sync-end-auto-waiting` | `run(id)` | D |
| Failed | `sync-failed-login-expired`, `sync-crashed`, `sync-failed-qobuz-not-set-up` | `JobFinished` (`problem`, `message`, `service`), crash report via `run(id)` | D |

### Limits (15)

| Family | Shots | Read | Agent needs |
|---|---|---|---|
| Cards / usage | `limits-qobuz-only`, `limits-all-good`, `limits-backlog-moving-to-90`, `limits-all-three-youtube`, `limits-only-youtube`, `limits-youtube-paused`, `limits-youtube-risky` | `limits(service)` | D |
| Warnings | `limits-qobuz-warnings`, `limits-got-it`, `limits-seen` | `limits().usage.signals[].new`, `cards[].new_warnings` | D |
| Draft | `limits-try-40` | `limits_what_if` + UI suggestion (U21); the draft is window only | D |
| Not set up / empty / loading / error | `limits-not-set-up`, `limits-nothing`, `limits-loading`, `limits-save-refused` | `limits().usage == null`; `save_limits` failure | D / V |

### Playlists (38)

| Family | Shots | Read | Agent needs |
|---|---|---|---|
| List | `playlists-first-run`, `playlists-big`, `playlists-problem`, `playlists-saved`, `playlists-during-sync`, `playlists-switch-off` | `playlists()` (`problem`, `rows`, `empty`) | D |
| Draft edits (window-only unsaved state) | `playlists-reorder`, `playlists-rename`, `playlists-menu`, `playlists-changed-elsewhere` (save answer `changed`) | draft: none; version: `playlists().version` | V (draft) / D (conflict) |
| Overlaps | `playlists-overlaps`, `playlists-many-overlaps` | `playlists().overlaps` | D |
| Adding | `playlists-add-found`, `playlists-add-preview`, `playlists-add-unreadable` | `add_playlist` | D |
| Change preview / save question | `playlists-big-move`, `playlists-rename-offered`, `playlists-rename-leave`, `playlists-rename-taken` | `preview_playlist_change` | D |
| Sources rows | `playlists-qobuz-row`, `playlists-qobuz-unreadable`, `playlists-qobuz-not-connected`, `playlists-soundcloud-row`, `playlists-soundcloud-likes-row`, `playlists-soundcloud-unreadable`, `playlists-youtube-music-row`, `playlists-youtube-mix-refused` | `playlists().rows[].info/service`, `read_status.services`, `add_playlist` errors | D |
| Liked music | `playlists-liked-off`, `playlists-liked-on`, `playlists-liked-listed-off` | `playlists().rows[].needs_setting`, `setup_status.youtube_music` | D |
| Tidy up | `playlists-tidy-mixed`, `playlists-tidy-many`, `playlists-tidy-empty`, `playlists-tidy-only-yours`, `playlists-tidy-moving`, `playlists-move-fails` | `tidy_preview`, `MovesProgress`, `JobFinished` | D |
| Move log | `playlists-batches`, `playlists-undo-skips` | `move_batches`, `undo_preview` | D |

### Settings (60)

| Family | Shots | Read | Agent needs |
|---|---|---|---|
| Music folder | `settings-music`, `settings-music-change`, `settings-music-blocked`, `settings-music-saved` | `setup_status.music`, `check_music_folder`; `blocked` = `job_status` | D |
| Accounts | `settings-qobuz-only`, `settings-yt-found`, `settings-yt-waiting`, `settings-all-youtube`, `settings-no-premium`, `settings-signed-out`, `settings-safari`, `settings-no-browsers`, `settings-paused`, `settings-qobuz-rejected`, `settings-qobuz-google` (help text only), `settings-console`, `settings-youtube-free-login` | `downloads_view`, `find_logins`, `job_status().sign_in`, `SignInPhase` | D (`-qobuz-google`: V) |
| Programs and tools | `settings-tools-missing`, `settings-updated`, `settings-tools`, `settings-tools-updated`, `settings-tools-waiting`, `settings-tools-back-confirm` (a dialog: V), `settings-tools-update-failed`, `settings-tools-unread`, `settings-tools-updating`, `settings-tools-going-back`, `settings-tools-check-fails`, `settings-tools-newest` | `setup_check_tools`, `JobFinished` of `update_tools`/`rollback_tools` | D |
| Spotify | `settings-spotify`, `settings-spotify-off`, `settings-spotify-skipped` | `setup_status` (`spotify_*`), `read_status.services` | D |
| About, reports | `settings-about`, `settings-about-up-to-date`, `settings-about-update`, `settings-about-unknown`, `settings-about-loading`, `settings-about-missing`, `settings-reports` | `setup_status.version`, `app_update`, `runs()` | D |
| Watched folders | `settings-folders-library-only`, `settings-folders-importing`, `settings-folders-stopped`, `settings-folders-offline`, `settings-folders-missing`, `settings-folders-couldnt-read`, `settings-folders-long-names`, `settings-folders-remove`, `settings-folders-added`, `settings-folders-crates`, `settings-folders-too-many`, `settings-folders-crates-busy`, `settings-folders-crates-many-folders` | `watched_folders`, `removal_preview`, `ImportProgress`, `job_status` | D |
| YouTube Music | `settings-youtube-music`, `settings-youtube-music-on`, `settings-youtube-music-free-off`, `settings-youtube-music-free-on`, `settings-youtube-music-no-login` | `setup_status.youtube_music`, `downloads_view.youtube` | D |
| Upgrades | `settings-upgrades-on`, `settings-upgrades-off`, `settings-upgrades-toggled` | `setup_status.auto_upgrade` (also `settings auto-upgrade`) | D |

### Setup (36)

| Family | Shots | Read | Agent needs |
|---|---|---|---|
| Music folder | `setup-music-new`, `setup-music-pick-first`, `setup-music-existing`, `setup-music-library`, `setup-music-refused`, `setup-music-console`, `setup-music-forced`, `setup-music-done` | `setup_status.music`, `check_music_folder` | D |
| Programs | `setup-tools-missing` | `setup_check_tools` | D |
| Spotify | `setup-spotify`, `setup-spotify-waiting`, `setup-spotify-failed`, `setup-spotify-skipped`, `setup-spotify-skip` | `setup_status`, `job_status` (login job), `JobFinished` | D |
| Downloads | `setup-downloads`, `setup-downloads-qobuz-only`, `setup-downloads-all`, `setup-downloads-yt-found`, `setup-downloads-waiting`, `setup-downloads-timeout`, `setup-downloads-cancelled`, `setup-downloads-no-browsers`, `setup-downloads-safari`, `setup-soundcloud-no-go`, `setup-no-qobuz`, `setup-downloads-auto`, `setup-downloads-auto-off` | `downloads_view`, `find_logins`, `SignInPhase`, `setup_status` | D |
| First playlist | `setup-playlists-guide`, `setup-playlists-liked-off`, `setup-playlists`, `setup-playlists-done` | `playlists()`, `setup_status.playlists` | D |
| Existing music | `setup-existing-empty`, `setup-existing-added`, `setup-existing-importing` | `watched_folders`, `setup_status.existing` | D |
| Whole guide | `setup-console`, `setup-unreachable` (bridge failure) | `job_status`; none | D / V |

### Shell (`lib/dev/shots.json`, 33)

| Family | Shots | Read | Agent needs |
|---|---|---|---|
| Real app states | `base-shell-syncing`, `base-shell-dashboard`, `base-shell-pause`, `base-shell-console` (`console_running`), `base-shell-first-run` (`setup_status`), `base-shell-music-missing`, `base-shell-music-missing-still`, `base-shell-no-music-redirect` (`setup_status.music.state`), `base-shell-update` (`app_update`), `base-shell-favourites` (`sidebar().favourites`) | named reads | D |
| View state | `base-shell-foot-sync`, `base-shell-foot-hidden-sync`, `base-shell-folded`, `base-shell-toasts` (toasts have no source other than job results) | none | V |
| Design gallery and frames (not app states) | `base-gallery`, `base-gallery-toggles`, `base-gallery-foot`, `base-gallery-sourceladder`, `base-gallery-accountpanel`, `base-gallery-accountpanel-menu`, `base-gallery-secrets`, `base-gallery-guide`, `base-gallery-explain`, `base-gallery-dialog-tip`, `base-frame-todo`, `base-frame-library`, `base-frame-playlists`, `base-frame-step`, `base-gallery-folderfield`, `base-gallery-badge`, `base-gallery-columns`, `base-gallery-listline`, `base-gallery-watchedfolders` | none | V |

States only the window holds that an agent **needs** (gap): the Sync scope switches, ticks and chosen preset; a playlists.txt draft (an agent edits the file or calls commands instead); a running job seen from outside; the in-memory plan.

## 3b. Information shown (per page, panel, card, row)

"Source" = bridge field, or `file:function` where the UI computes it. "Command today" = exact command or none. Unless a cell says otherwise, no command gives it. Not every tooltip was read: rows marked "not checked" were not opened.

### Sync, before the start

| Where | Shown | Source | Command today |
|---|---|---|---|
| Header slot | "Playlists read N min ago", "Reading . 3 of 7", OFFLINE badge, "Stopped reading.", "Your playlists changed since.", Read playlists disabled with reason ("Connect Qobuz first.", "Not while a sync runs.") | `read_status` (`read_at`, `minutes_ago`, `stale`, `offline`, `reading`), `ReadingPlaylist`; reasons from `hub.ts:46,67` | none |
| Read-problem card | Problem title, message, "Connect" link, which playlists are not read ("Hard_Bounce, Powertrance and 2 more aren't read until Qobuz is connected. Your other playlists sync as usual.") | `read_status.problem/message/service`; sentence `planModel.ts:28 readBlockLine` from `playlists().rows` | text only on a failed sync/dry run (exit 2 + message) |
| Kinds strip | Total to sync, "in 4 playlists and 1 folder", per-kind bar with counts and tips (New downloads, Files gone, Missing songs, Lossy files, Bought files), dimmed part for a weekly check switched off | `planModel.ts:204 kindShares`, `:219 stripLine`, `KIND_SHARE` tips | dry run text prints groups with counts (`rep.render_plan`); `--json` `counts` by kind only |
| Plan sections | Section per playlist/folder (name, "N of M ticked . K next sync"), tick per row, cover, "Artist - Title", why icon and tag ("not downloaded yet", "not found last time", "file gone", "bought file", "weekly check"), "next sync" tag on downloads over today's limit, "Never download" button | `groups[].actions[]` (`kind`, `reason`, `folder`, `cover_url`, `in`, `run`); `planModel.ts:52 kindOf`, `:313 nextSyncSet`, `:492 sections`, `:482 sectionSummary` | dry run text lists rows (not the next-sync tag); none structured |
| Dimming | Rows of a left-out collection are not listed; "N more tracks left out" note names where the switches are; the plan dims while re-reading | `planModel.ts:169 leftOutTitle`, `:173 leftOutBody`, `BeforeStart.svelte:306` | none |
| Search | "N matches", "Tick only these", "Nothing matches" | `planModel.ts:451` | none |
| Folds | Never download (with Download again), Left your playlists, More than one file, planner notes | `never[]`, `dropped[]`, `ambiguous[]`, `notes[]` | none (notes may be in the dry-run text: not checked) |
| Run panel ("This run") | How many (chips 5/10/25/50, "N . fits today", All N), Today / Later bar and days, time ("~75 min"), per-account "uses 10 of 10 left", Weekly checks switches with counts, "Start sync . 66 tracks", hints (console running, nothing today, N upgrades go in at the end, rekordbox open warning), "N songs wait for your answer on the To-do page", deferred first upgrade checks | `estimate`, `planModel.ts:277,367,343,386,419,503,510`; `waiting_answers`, `deferred_checks`, `auto_upgrade` | dry run prints the count/time/budget lines (`cli.py:184-198`, `run.budget_text`) and the waiting lines (`console.py:28`) as text |
| Up to date | "Up to date", tracks in playlists, playlists count, last sync (when, stats, quality bar), upgrades count, To-do count | `in_playlists`, `folders`, `dashboard.last_runs[0]`, `run(id)` via `endModel.ts:44`, `needs_you.upgrades`, `sidebar.todo` | none |
| Sidebar tooltips on switches | "Name . 12 tracks to sync" / "left out" / "switched off on the Playlists page" / "switch it once the sync ends" | `planModel.ts:258 switchTip` | none |

### Sync, running and end

| Where | Shown | Source | Command today |
|---|---|---|---|
| Progress card | "Track 4 of 6", bar (finished share), "~N min left", "Qobuz 12 of 60 today . YouTube Premium 3 of 30 today", message line ("Reading your playlists . 2 of 7 . Powertrance") | `RunStarted/ActionStarted` total/index, `selection.ts:49` (70 s each), `AccountUsage`, `dashboard.tiles`, `ReadingPlaylist` | console prints progress lines (`console.py` ConsolePrinter: not checked in detail) |
| Live card | Cover, "Now . folder", Artist - Title, "from Qobuz . exact / ISRC / name / upload / fallback", steps list with the current one, Progress (bytes or seconds) and rate (smoothed), length check "file 4:02 vs track 4:01", countdown for pauses and breaks | `Action`, `StepChanged`, `Progress`, `SourceChosen`, `Checked`, `Waiting`; `cardState.ts` | stderr/stdout text lines only |
| Analysed card (4 s) | Quality verdict and spectrum thumbnail | `ActionFinished.result` (`status`, `cutoff_hz`), `spectrum()` matrix (engine `hub/spectrum.py`, not checked) | none |
| Result list | Chips All/Lossless/Lossy/Problems with counts; Problems first; badge per row ("LOSSLESS", "16.0 kHz . audibly lossy", "FAKE . 16.0 kHz", "NOT FOUND", "NO INTERNET . retried next run", "UPGRADE READY", "MOVED -> folder") | `Result` (`section`, `status`, `cutoff_hz`, `error_kind`, `found_status`), `cardState.ts:180 verdict`, `results.ts` | the sync's end text summary lists counts (`rep.summary`); `--json` counts by section |
| Stop | "Stop safely", "Stopping..." title, hint, red reason if refused | `job.stopping`, `stop()` failure message | Ctrl-C message (`cli.py:163`) |
| End screen | Title ("Sync finished", "... with some problems", "Sync stopped"), when and "took N min", cards added (with quality bar), moved, need you; notes (stopped after N, Auto-upgrade line, N upgrades ready, N new since the check, N checked nothing better yet, N wait for the next sync); Needs you list with Fix links and shop links; new files per playlist folder with "Show in Finder"; Auto-upgrade parts with row sub-lines ("Waits for rekordbox to be closed", "Same AIFF, lossless audio", To-do's short refusal reason); Other changes ("from Bouncy", "found again after you moved it") | `run(id)` fields; `endModel.ts` | `rep.summary` text + `report` path; counts in JSON |

### Dashboard and All runs

| Where | Shown | Source | Command today |
|---|---|---|---|
| Header | Greeting ("Good evening" by hour: <5 or >=18 evening, <12 morning) | `views.py:324 greeting` | none |
| Health card | "NN% lossless . X of N tracks . K not found", quality bar with legend | `tiles.lossless` (`views.py:101 lossless_share`), `dashboardModel.ts:17` | none |
| Needs you | Rows Upgrades ready (sub "N can be swapped, cues stay"), Not found ("buy links ready"), Weak versions ("audibly lossy (<= 17 kHz)") with counts, "Nothing needs you right now"; each links to a To-do filter | `needs_you` (`views.py:343`), `dashboardModel.ts:86` | none |
| Folders | Per playlist: tracks, lossless share %, quality bar, "empty" | `folders[]` | none |
| Next sync panel | Running / not read / up to date / ready with count and time, day bar, "Qobuz . 60 today", "Download limits" link, last runs | `ready`, `tiles`, `dashboardModel.ts:66` | none |
| Last runs / All runs | "Today 14:02 . 38 min", parts "12 lossless . 3 lossy . 2 problems . 1 moved" with colour (ok/warn/bad), "stopped by you after 5 tracks", status mark, month groups, totals panel | `runs()`, `dashboardModel.ts:118,135,145` | none |

### Limits

| Where | Shown | Source | Command today |
|---|---|---|---|
| Service cards | Name, today's used/allowance bar, status "Paused today" (red) / "N new warnings" (yellow) / "All good . N seen" (green) | `cards[]`, `limitsModel.ts:128` | none |
| Today | Allowance sentence "60 + 12 carried over + 5 extra", remaining, "last download 21:47"/date, "resets ..." tooltip (not checked) | `usage.today`, `limitsModel.ts:88,94` | none |
| Backlog | "N tracks, about 3 days at 60 a day", "done today", "Nothing waiting", "Qobuz sets the pace" for an account behind Qobuz | `usage.still_to_load`, `behind`, `limitsModel.ts:101` | none |
| 14-day chart | Bar per day, coloured by zone, tooltip "18 Oct . 40 downloads . normal" | `usage.days[]`, `zones[]`, `limitsModel.ts:114` | none |
| Warning signs | One row per kind: bad (title, count, latest time and message, NEW, "clears in N days") or ok ("Login always worked"), suggestion "Try 40 a day" | `signals[]`, `limitsModel.ts:186,216` | none |
| Panel | Risk scale with zones and the draft, verdict title/sub per level (1 "Slow and very careful" ... 5 "Risky"), colour tone by zone, "instead of N days", "instead of 1 h", extra choices, Save/Back labels, honest note per service | `setting.zones`, `assessment`, `what_if` (`days_to_load`, `run_minutes`), `limitsModel.ts:29,43,56,136` | none |

### Playlists

| Where | Shown | Source | Command today |
|---|---|---|---|
| Row | Priority number (1..n; switched-off or setting-off rows blank), cover, folder name, service logo + "name", owner ("yours", "collaborative", name), unreadable service words in red, quality bar + "6 of 11 lossless" (only wide), track count, switch, change line "gets 27 more"/"gives 20 away", dimming when switched off or its setting is off ("Liked music reading is off") | `rows[]` (`info`, `quality`, `tracks`, `needs_setting`), `changeModel.ts:110,131,154,249` | none (the file's own lines) |
| List head | "N playlists . M switched off" | `changeModel.ts:148 listSummary` | none |
| Panel, nothing unsaved | "In several playlists" cards (how many stay, where the rest land), Recent moves (title, when, N files, Undo or "Nothing left to undo") | `overlaps`, `move_batches` | none |
| Panel, unsaved | New downloads and days, tracks left out, per-folder DeltaBar, reroutes by route, save question (headline "N files would sit in a different folder", C line "8 files move from A to B.", warning R1/R2/U1, "yours" group, "Can't move" with reasons, rename switch "One folder move instead of 7 file moves.") | `preview_playlist_change`, `tidyModel.ts:11-60,134` | none |
| Tidy/undo progress and result | "N of M" bar, done ticks, "N not moved:" list with reason and tone | `MovesProgress`, `BatchResult.skipped[]`, `tidyModel.ts:289-316` | none |
| Tidy up button | Orange with the count while files are out of place | `playlists().tidy.waiting` | text line after a sync (`cli.py:105-122`) |

### Settings, Setup, shell

| Where | Shown | Source | Command today |
|---|---|---|---|
| Source ladder | Rungs Qobuz, artist's own file, premium streams, free streams, lit by state; counts by rung and the note where Qobuz-less songs come from | `downloads_view.library`, `ladderModel.ts` (not checked) | none |
| Settings rows | State line + mark per row ("via Chrome (DJ) . 256 kbps . checked today", "connected as name", "left out", "public playlists . Liked music on", path "~/Music/Discjockey", "all there"/"ffmpeg missing", "Automatic at the end of each sync", "3 sync reports", "1.2.1 . up to date") | `settingsModel.ts:81`, `accountModel.ts:125` | `settings auto-upgrade` only |
| Account panel | State headline and sub, what it gives ("about 256 vs 130 kbps"), tracks from this source, risk note, browser/profile offers (found / none / unreadable), waiting text "Waiting for you to sign in in Chrome", Safari Full Disk Access hint, first-use macOS keychain warning, last check date | `accountModel.ts` (many) | none |
| Programs | Per tool present/missing with the brew line, yt-dlp version and "built in"/"updated", "waiting to restart", "Go back to X", before -> after lines | `setup_check_tools`, `settingsModel.ts:151-216` | `setup` prints missing tools; `update` prints before/after (`setup_cmd.py:145`) |
| Watched folders | Rows with short path (middle cut), state mark (ok, offline, not found), counts "1,240 files", phase line and bar of a running import, "Couldn't read (N)" list with where and reason, crate switches with counts and tooltip path | `watched_folders`, `watchedFoldersModel.ts` | none |
| Setup | Step strip (done, current, open, locked), Continue enabled/off with the reason line ("Choose your music folder first.") | `setupModel.ts:76,90` | `setup` prompts |
| Sidebar | To-do count and pill ("99+"), running sync "12/40", warning dot on Download limits, update line "Discjockey 1.3 is available" | `sidebar`, `sidebarModel.ts`, `appUpdate.ts:11` | none |
| Banners | "A sync is running in the terminal. You can look around; changes wait until it's finished." and read-status banner with Connect link | `console_running`, `read_status`, `copy.ts:136` | none |
| Toasts | Job success and problem sentences, "recovered" notices ("finished an interrupted step") | `JobFinished`, `copy.ts successCopy/problemCopy`, `OpResult.recovered` | the batch commands print `recovered` (CONTRIBUTING); sync: not checked |
| Pictures | Covers (cached cover file or the service's image URL: `api.py:525-533`), spectrum (`spectrum()`; engine `hub/spectrum.py`, not checked), playlist covers (`info.cover`), service logos (static) | `cover_url`, `image_url` | none |

Everything in these tables with "none" is only visible in the window today.

## 4. Journeys

H = a step only a person can do (tell the user what to do). Commands refer to today's.

| # | Journey | Steps | Bridge | Command today |
|---|---|---|---|---|
| J1 | First run, music folder | pick or type a folder, check, "other files" confirm, use | `setup_status`, `pick_folder` (H), `check_music_folder`, `set_music_folder` | `discjockey setup` first question (prompt, TTY) |
| J2 | Existing music | add folders, watch the import, skip | `check_import_folder`, `add_watched_folder`, `watched_folders`, `ImportProgress`, `stop`, `start_import`, `setup_skip_import` | none (the console never imports) |
| J3 | Programs | read missing tools, install with brew (H), check again | `setup_check_tools` | `setup` prints them |
| J4 | Spotify | create app in Spotify's dashboard (H), paste Client ID, log in in browser (H), or skip | `setup_save_client_id`, `setup_spotify_login`, `spotify_sign_out`, `setup_skip_spotify` | `setup` (prompt + browser) |
| J5 | Qobuz | e-mail+password (Google/Apple/Facebook users first set a password on the web: H), or skip | `setup_qobuz_login`, `setup_skip_qobuz`, `qobuz_check_login` | `setup` (prompt, cannot skip) |
| J6 | YouTube Premium / SoundCloud Go+ | see found logins, use one, or sign in in the browser (H, up to 10 min), macOS keychain "Always Allow" (H), Safari Full Disk Access (H), check again, sign out | `find_logins`, `setup_account`, `account_sign_in`, `stop_sign_in`, `open_privacy_settings`, `setup_check_account`, `setup_forget_account`, `downloads_view` | none |
| J7 | Auto-upgrade switch | read/set | `set_auto_upgrade`, `setup_status` | `settings auto-upgrade [on\|off]` |
| J8 | First playlist / edit playlists | paste a link, check it, name the folder, add; reorder, rename, switch off, remove; preview the change; answer the save question (move or leave files, rename folder on disk); save | `add_playlist`, `playlists`, `preview_playlist_change`, `save_playlists` | none (edit playlists.txt by hand) |
| J9 | Liked music | turn on in Settings (needs YouTube login), add the line | `set_read_liked_music`, `add_liked_music` | none |
| J10 | Daily sync | read playlists, review plan, choose collections/weekly checks/how many/ticks, never-download, start, follow, stop, end screen, open report, then rekordbox (H: add new files in rekordbox; quit rekordbox before Auto-upgrade ends) | `refresh`, `sync_preview`, `never_download`, `rekordbox_status`, `start_sync`, `job_status`+events, `stop`, `run`, `open_report` | `discjockey [--dry-run]` then `discjockey --yes [--limit N] [--json]` (no selection) |
| J11 | Past runs | list, open one | `runs`, `run` | none |
| J12 | Download limits | read, try a limit, save, extra for today, "Got it" | `limits`, `limits_what_if`, `save_limits`, `mark_warnings_seen` | `--extra N` (Qobuz) on the sync |
| J13 | Tidy up and undo | preview, untick, move, stop, undo | `tidy_preview`, `tidy_up`, `move_batches`, `undo_preview`, `undo_moves`, `stop` | none (a count line after a sync) |
| J14 | Watched folders and crates | add/remove, show crates in the sidebar | `watched_folders`, `removal_preview`, `remove_watched_folder`, `set_crate_shown(s)` | none |
| J15 | Change the music folder / drive missing | change (app closes: H reopen), try again, choose another | `set_music_folder`, `quit`, `retry_music_folder` | none (`setup` cannot change an existing choice) |
| J16 | Update tools | update, restart (H), go back | `setup_check_tools`, `update_tools`, `rollback_tools`, `quit` | `discjockey update` (no rollback) |
| J17 | App updates | see that a newer version exists, open the release page (H) | `app_update`, `open_external` | none |
| J18 | When something breaks | read the problem kind and message, "another run is still going", offline, login expired, 403 | `JobFinished.problem/message`, `read_status`, `job_status.console_running` | exit codes and text (section 5) |
| J19 | Account risk | read warning signs, paused services, Liked music pause | `limits().signals`, `cards[].paused`, `sidebar.limits_warning` | none |

## 5. Today's commands in my area, judged for agents

### 5.1 The sync (`discjockey`, no command; `cli.py`)

- **No name, no discoverability.** The sync is the command with no sub-command (`cli.py:53-60`); `--help` shows flags then a list of sub-commands. The sub-commands `setup`, `update`, `upgrades`, `hub` also accept `--yes --dry-run --limit --verbose --extra` and ignore them (`cli.py:40-49,71-74`).
- **The installed app cannot run it.** `app_main.py:34` routes to the CLI only when the first argument is in `CLI_COMMANDS` (`:21`); `--dry-run`, `--yes`, `--json` as first argument open the window (`:38-41`, "unknown arguments are ignored" `:11`). A user of the .app has no sync command in the Terminal.
- **`--json`** needs `--yes` or `--dry-run`, else exit 1 `needs_yes` (`cli.py:298-300`); one object on stdout, human lines to stderr (`:302`). Success `{"ok", "exit_code", "dry_run", "report", "counts", "auto_upgrade"}` (`:202,206`); problems `{"ok":false,"kind","message"[,"reason","report"]}` (`:148-149`). `ok:true` also with exit_code 1 (`:206`). `counts` has different keys for a dry run (`acquire:new`...) and a real run (report sections) (`:133-145`). A declined "Proceed?" gives `ok:true, report:null, counts:{}` (`:247`). Setup problems carry the engine's own `kind` (`:182`).
- **Exit codes:** 0 done (also dry run, also a declined prompt), 1 errors in the run / crash / `needs_yes` / `failed`, 2 setup problem / no music folder / no keyboard (`EOFError`, `:353-356`, with `_main` returning `None` and `--json` printing `failed`) **and also an argparse usage error**, 3 another run holds the lock (`:347-349`), 130 stopped (`:350-352`, and the stopped run `:210`). Differs from the batch commands (0-5: 4 rekordbox open, 5 Ctrl-C) and `settings` (0-3): CONTRIBUTING:109-116.
- **Dry run:** takes the lock for its whole duration (`cli.py:333` wraps `sync()`), re-reads the network, scans Library/. JSON has counts only (`:202`). `--limit` is ignored by it. **`--extra N` writes settings.json even with `--dry-run`** (`run.py:111-115`, called from `cli.py:179`).
- **Prompt:** `input("Proceed? [y/N]")` unless `--yes` (`:242`); no TTY gives exit 2.
- **Selection:** none: not by song, playlist, folder or kind, only `--limit N` = first N downloads (`execute.py:90-140`). The plan a person (or agent) looked at is not bound to the run: a run re-plans (`run.prepare`), there is no `new_since_preview` safety (`run.select_actions` is only used by the window, `jobs.py` `sync_work`).
- **Long run and progress:** blocks 1 to 2 h; human text lines (`ConsolePrinter`), no event stream, no JSON progress, no `status`/`wait` command; stop by SIGINT only (`:152-171`); the PID is in the lock file (`library.py:247`). `bin/discjockey` runs `uv sync` and `caffeinate -i` (`bin/discjockey:5,12`); the .app has neither.
- **Songs are named** in the text plan as "Artist - Title" under folder; in JSON never (no per-track data except batch commands' keys).
- **Never imports, never answers "Is this the same song?":** prints "wait ... Open the window" lines (`console.py:28-35`, `cli.py:185-186`).
- **Errors:** plain text on stdout (`cli.py:181,240,328`), not stderr, without `--json`; a crash re-raises the traceback without `--json` (`:215-216`).

### 5.2 `setup` (`setup_cmd.py`)

- Fully interactive, no flags, no `--json`: music folder (`:165-172`), Client ID (`:68`), Qobuz choice 1/2 and password via streamrip's prompter (`:128-134`, `qobuz.py:250`), then writes a playlists.txt template (`:114-116`) and prints an alias tip (`:118-120`).
- Needs a real Terminal; `EOFError` -> exit 2 (`cli.py:353`).
- Cannot skip Qobuz (a failed login returns 2, `:107-112`), no YouTube/SoundCloud step, cannot change an existing music folder (the question is only asked when none is chosen, `cli.py:326-331`), no sign-out, no status.
- Exit 0 done, 2 problem or missing programs (`:121`), 3 busy, 130 Ctrl-C.
- The Spotify login prints a link and opens the browser (H).

### 5.3 `update` (`setup_cmd.py:137-148`, `cli.py:337-339`)

- Text only; `--json` is refused (`cli.py:98-99`). Exits 2 when no music folder is chosen (`cli.py:326-329`) and 3 while the window works, although it only touches `<support>/tools` (it takes the library lock, `:333`). Prints before/after, "Start Discjockey again" (`:146-147`). No rollback command.

### 5.4 `settings auto-upgrade` (`settings_cmd.py`)

- Good model: positional `on|off`, bare = read, `--json` `{"ok":true,"auto_upgrade":bool}`, exit 0/1/2/3 (`:41-62`), read takes no lock, write takes it. Flaws: needs a music folder even for a read (`:43-44`); the docstring says the window shows the value "at once" (`:8`), but the window refreshes its settings view only on `JobFinished`/`ConsoleBusy(false)` (`stores/hub.ts:139-141`) and the 3 s console probe (`jobs.py:566`) can miss a short command (inferred).
- One setting only; limits, Liked music, skips, accounts have none.

### 5.5 `hub` (`cli.py:318-320`) and `rekordbox status`

- `hub` opens the window; no lock held while it is open (`:320` comment). `rekordbox status` is the reference for a read command: no lock, no music folder, JSON (CONTRIBUTING:61-66).

### 5.6 Behaviour while the window app is open

| Fact | Where |
|---|---|
| One lock file for everything: `flock` on `<music>/.discjockey/.lock`; the console tries 6 times 20 ms (about 100 ms) then `LockHeld` -> exit 3 | `library.py:204,228-250`; `cli.py:347-349`; `settings_cmd.py:61-62` |
| The window holds the lock only while a write job runs, during a brief settings save, and during a scan; **idle window = free lock**. But the window starts with a scan + read and may start the import by itself (`refresh(auto=True)` -> `_opening_scan`, `_auto_import`, `api.py:812-870`) and rescans when it comes to the front after 60 s (`rescan.ts`): a console command in those moments exits 3. No `--wait`/retry flag | `jobs.py:377-417,521-532` |
| A console sync holds the lock from before the plan until the end, **including `--dry-run` and the "Proceed?" question** | `cli.py:333-343` |
| While it holds the lock the window goes read-only: every write method answers `console` ("A sync is running in the terminal. Wait until it has finished."), Start is disabled, a banner shows. Detection is a probe every 3 s, `ConsoleBusy` fires only on change: a command shorter than 3 s is never noticed | `jobs.py:173,368-376,436,566-575`; `stores/hub.ts:124-125,139-141`; `shell/Banners.svelte` |
| Network reads refused in the window while a console sync runs (`sync_running`): searches, previews, Playlists add/preview, account checks, sign-in start | `api.py:1301-1305` |
| Read playlists in the window while a console run holds the lock still works but plans on the last scan and writes nothing | `jobs.py:397-417`, `run.py:87-99` |
| After the console ends the window re-reads its pages (`ConsoleBusy(false)` bumps `dataVersion`), but its stored plan (`PreviewStore`) is **not** updated by a console run: Sync may keep listing songs the console already downloaded until "Read playlists" (inferred from `jobs.py` `preview_after_run` being called only by hub jobs) | `jobs.py:~748`, `hub.ts:139` |
| Window reads library.db and settings.json fresh on every call, so a console's changes appear at the next read; there is no push from a console | `api.py:405-412` |
| Brief records writes (Favourites, crate switches) take no lock and work during a console run | `api.py:995-1010` |
| A console `setup` may change `config.json` under a running window; the window keeps its bound folder until restarted | `api.py:2636-2662` |
| A text editor or console edit of playlists.txt while the window has an unsaved draft: the window's save answers `changed` ("changed elsewhere") via the version hash; the editor side has no lock and no check | `playlists_file.py:135-140` |
| Two windows on one support folder are allowed (second takes a temporary port) | `window_port.py` docstring |
| The sign-in slot runs beside write jobs without the lock, and refuses to check while a sync starts | `jobs.py:453`, `api.py:2480-2500` |
| Logs: there is no log file; tracebacks and warnings go to the stderr of whoever started the app (lost for the .app); the persistent record is `reports/` and crash notes | `jobs.py:545-546` `traceback.print_exc`; `run.py:548-550` (not checked beyond grep) |

### 5.7 Smaller problems

- Three JSON dialects: sync (`_problem`), `settings` and batch commands (`rekordbox_cmd.say/failed`, `reason`), bridge (`kind`/`message`); `kind` vocabularies differ (setup kinds vs `refused/failed/busy/rekordbox_open/stopped`).
- Songs and files are named by the library's song key in batch commands, by "Artist - Title" text in the sync; no key in the sync output.
- Env overrides: `DISCJOCKEY_SUPPORT`, `DISCJOCKEY_REKORDBOX` (CONTRIBUTING:95-98): needed for every test run of a command.

## 6. Coverage list (bridge methods covered in this file, 73)

sync_preview
refresh
stop_refresh
job_status
start_sync
stop
never_download
rekordbox_status
spectrum
dashboard
runs
run
open_report
reveal
sidebar
setup_status
app_update
rescan_library
quit
open_external
library
track
hide
select
limits
limits_what_if
save_limits
mark_warnings_seen
playlists
add_playlist
preview_playlist_change
save_playlists
set_read_liked_music
add_liked_music
tidy_preview
tidy_up
move_batches
undo_preview
undo_moves
downloads_view
find_logins
setup_account
account_sign_in
stop_sign_in
open_privacy_settings
setup_check_account
setup_forget_account
qobuz_check_login
setup_qobuz_login
setup_skip_qobuz
setup_save_client_id
setup_spotify_login
spotify_sign_out
setup_skip_spotify
set_auto_upgrade
setup_check_tools
update_tools
rollback_tools
open_licenses
set_favourites
set_crate_shown
set_crates_shown
pick_folder
check_music_folder
set_music_folder
retry_music_folder
setup_skip_import
watched_folders
check_import_folder
add_watched_folder
start_import
removal_preview
remove_watched_folder

Methods of the Library and To-do areas are not listed here (`library`, `track`, `hide`, `select` appear only as shell callers).
