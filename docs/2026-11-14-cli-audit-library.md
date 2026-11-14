# CLI audit (issue 39, step 1): the `library` area

Evidence for the designer, not a design. Area: the Library page and everything it hosts: browsing, the track details
(inspector), listening (foot bar), watched folders and the import, "Is this the same song?" and duplicates, Superseded,
tidy-up and its undo, folder renames on disk, Favourites and crates, Make AIFF… (Library side only). Sources read:
`hub-ui/src/pages/library/*`, `hub-ui/src/lib/{shell,stores,decisions,components}`, `hub-ui/src/pages/playlists/{MovesPanel,
ChangePanel,tidyModel}`, `discjockey/hub/api.py` (by method), `views.py`, `jobs.py`, `tidy.py`, `batch_cmd.py`,
`convert_cmd.py`, `cli.py`, README ("Your existing music", "Tidying up files", "Listening through a list", "The Library
page", "Folders", "Making files AIFF"), CONTRIBUTING "Commands for scripts and agents". Line numbers are of the checkout
this was written in.

Words used below: **bridge** = a `HubApi` method; **job** = a write method that returns `{"job_id"}` and ends with a
`JobFinished` event; **brief save** = a write that takes no library lock and answers at once (CLAUDE.md invariants);
**key** = a song's key (`track_id` in the hub, `track` in the console JSON: Spotify id bare, `service:id`, `own:<n>`
for the user's own files, `models.OWN_PREFIX`).

---

## 0. Findings the designer must not miss

1. **There is no console read of the library at all.** No command lists tracks, a playlist, a folder, the sidebar,
   the watched folders, the move log or a track's details. Yet `cli.py:85` and `convert_cmd.py:82` tell the agent to
   take song keys "as the library's JSON prints it": that JSON does not exist. Keys come only from `upgrade list`
   (parked upgrades only, `batch_cmd.py:365`), `batch show` and a sync report.
2. **Nothing of the file-moving half of this area has a command:** tidy-up, undo of a move batch, folder rename on
   disk, the Playlists save question, Keep / Keep both / Move to Superseded, "Is this the same song?", adding and
   removing a watched folder, the import, Favourites, crate switches, rescan. Only the AIFF half (convert, rename,
   Make AIFF, upgrade, batch, rekordbox checked) has commands.
3. **Two different "batches", one number space.** `move_batches` / `undo_moves(batch_id)` are tidy-up, save and
   folder-rename batches (library.db move log); `batch list | show | resume | undo <id>` are AIFF batches
   (`aiff_batches`). Both ids are plain integers; `batch undo 3` and `undo_moves(3)` mean different things.
4. **The window holds state the engine does not**: the selection, ⌘A's meaning, the details/hidden state, the running
   batch panel's view, the player queue, per-view sort and filter (localStorage prefs), the hub's `_import_stopped`
   flag, `_import_auto_done`, `PreviewStore.prep` (the last playlist read: it feeds `library().rows[].track_link`,
   the import's linking, `todo()` questions and every `replanned_work`). The "Is this the same song?" questions live
   only in that in-memory plan (`convert_cmd.py` `_held` docstring says so): an agent without the window cannot list
   them (a sync `--dry-run` prints only their count, `cli.py:185`).
5. **Single-track hub writes carry a window-session precondition.** `HubApi._shown` (`api.py:311`, filled by
   `library()`, `track()`, `todo()` through `_remember`, `api.py:554`) holds each track as the page last showed it;
   `ops.run_single` (`ops.py:89`) refuses `changed` when the stored entry differs or was never shown. A command is a
   new process each time, so this check has no console form (the batch/convert/upgrade commands do not use it, except
   the one-track `upgrade apply --way new-track` / `discard` path in the hub `_each_work`, `api.py:2020`).
6. **The window triggers things by itself** that a command line must either do on request or consciously skip:
   `rescan_library` at window open and after >60 s in the background (`rescan.ts`, `rescanModel.ts:7`), the first
   playlist read at open (`refresh(auto)`, `api.py:812`) which scans Library/ and starts the import by itself once per
   session (`_auto_import`, `api.py:849`, decision D14), and the media server for ▶ (`media.py`).
7. **The app binary only runs a console command when `argv[0]` is in `CLI_COMMANDS`** (`app_main.py:25,36`). The
   plain sync (`Discjockey --yes --json`) is not a command word, so it opens the window instead.

---

## 1. Actions and reads

Columns: method (api.py line) · where the user triggers it · what it does · the hub's own safety · long run (kind +
events) · today's command · gap. "Writes db" = writes `library.db`; "moves files" = changes the user's files.

### 1a. Reads

| Method | Where / control | What it does | Hub safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `library(view, key, query, filter, sort)` api.py:881 | Library page: every collection click, filter chip, search (200 ms debounce), sort header; browser column Play (`BrowserColumn.svelte:319`) | Reads library.db + state; one view `all\|unlisted\|playlist\|folder`, `query` (folded substring of "artist title"), `filter` (`all lossless good_lossy weak fake upgrade_ready`), `sort` (`title artist length quality folder order`, `-` = desc). Returns rows (+`also`), `chips`, `summary`, `subtitle`, `songs`, `read_at`, `enabled`, `empty`, `aiff_stopped`. Side effect: `_remember` | ValueError on unknown view/filter/no key; unknown playlist/folder = `empty: "gone"`, not an error. Needs bound music folder (`LIBRARY_METHODS`) | no | **none** | no library read; also `rows[].track_link` and a playlist's waiting/NOT FOUND rows depend on the window's `PreviewStore.prep` / read records |
| `track(track_id)` :906 | Select a row (click, ↑ ↓, `?track=`) | One track's details: `file_state` incl. `file_missing` (checks the disk for this one file), quality lines, `place`, `playlists`, `source_*`, `track_link`, `next_qobuz_check`, `upgrade` block (alignment, `swap_safe/swap_possible/swap_how/why_not`, rekordbox state, `auto_refused/auto_waits`), and `aiff` = `plans.file_answer` (what Convert/Rename would do) | `changed` if the key is unknown; not asked by the page for a song still `waiting` (UI skips it, `Page.svelte:238`) | no (decodes nothing) | **none**; closest: `convert <key> --dry-run --json` (the `aiff` part), `rekordbox preview <key>` (eligibility, decodes 1–3 s), `upgrade list` (upgrade part) | no per-track read |
| `todo(filter, show_hidden)` :937 | Library inspector calls `api.todo('all', true)` once per files version (`Page.svelte:259`) to find the rekordbox check and duplicate group of the selected track | The whole to-do list incl. hidden items | `_remember` for non-pair items | no | partial: `upgrade list` (Upgrade ready group only) | the check/duplicate/question items have no read; see To-do audit |
| `sidebar()` :771 | hub store `refreshHub` after every `JobFinished`, `ConsoleBusy`, `DrivesChanged`; browser column + rail | Counts and lists: `all_tracks`, `not_in_playlist`, `todo`, favourites (resolved), playlists (`ref`, `songs`, `enabled`), `library_folders`, `watched` (each with `crates[]`, `too_many`, `crate_count`, `state`) | none | no | **none** | no read of the collections list |
| `watched_folders()` :969 | Settings → Watched folders, Setup "Your existing music" (flow `watchedFoldersFlow.svelte.ts:42`); not the Library page itself | Folder rows (`state online\|offline\|missing\|scanning\|importing`, `files`, `waiting`, `unreadable`, crates), the unreadable file list, `waiting` total, `stopped` | `stopped` is the hub's in-memory `_import_stopped` | polled 1 s while an import runs | **none** (sync prints "n files wait", `cli.py:185`) | no read; `stopped` has no meaning outside a window session |
| `removal_preview(folder_id)` :1091 | Remove on a folder row, before the confirm dialog | `{name, files, redownload}`; read only | ValueError for the Library or an unknown id | no | **none** | none |
| `check_import_folder(path)` :1071 | Add folder…, after the Mac folder dialog | `{path, exists, usable, problem, kind, message, merges, merge_hints}`; changes nothing | refusal words (inside music folder / inside a watched folder / holds the music folder, W5) | no | **none** | none |
| `aiff_plan(scope)` :929 | Library: header Make AIFF… (scope `lossless`), a multi-selection (scope `tracks`); To-do's CDJ group (`cdj`) | Read-only plan: items (action, kind, names, bytes, `superseded`), `skipped` (selection only), `waiting`, `kinds`, `lossy`, `space` per drive, `needs_closed`; reads tags only of own AIFFs | `ValueError` bad scope; runs off the window thread | no (one read) | `convert … --dry-run [--json]` and `rename … --dry-run` (`convert_cmd.py:85`), same `AiffPlan.to_dict()`; for a dry run that finds facts missing it takes the library lock (`convert_cmd.py:218`) | none for the plan; selection by ⌘A has no equivalent (see §2 D16) |
| `tidy_preview()` :1588 | Playlists → Tidy up files | `planner.tidy_rows(state)`: each file the playlist order would put elsewhere: `file_id`, `from_path`, `from`, `to`, `ticked`, `yours`, `skip{reason,text}`, the rekordbox notes, the "yours" header/control words | reads on-disk state only (no scan first) | no | **none** (the sync prints a count line, `cli.py:100`, via `planner.out_of_place`) | no preview = no dry run for tidy-up |
| `move_batches()` :1594 | Playlists → panel "Recent moves" (`ChangePanel.svelte:107`) | The 20 newest move batches (tidy, save, folder rename, undo) with `undoable`, `undone_by`, summary | none | no | **none** (`batch list` is AIFF batches, a different table) | see finding 3 |
| `undo_preview(batch_id)` :1606 | Undo on a recent move / on a result | What undo would do move by move: `rows` (`kind file\|folder`, `from`, `to`, `skip`), `moving`, `warning[]`, `nothing_left` | ValueError for a non-int / unknown batch | no | **none** | none |
| `rekordbox_status()` :775 | Convert card (`AiffFlow.read`, `flows.svelte.ts:111`) when it shows, again on window focus; Sync page | `{state ready\|none\|unreadable, running}`; works without a music folder | cached open of master.db | no | `rekordbox status [--json]` (`cli.py:78`, `rekordbox_cmd.py`) | none; the UI reads the same answer |
| `job_status()` :876 | hub store at boot and after each job event | the running/last write job snapshot, `console_running`, `refresh_running`, `sign_in`, `read_status` | none | no | **none** | no way to ask "is something running" except an exit-3 lock refusal |
| `spectrum(track_id, which)` :1130 | Track details: the spectrum picture (and the upgrade's) | 400×128 dB matrix + waveform of the current/upgrade file, cached in the support folder; decodes audio | `_file_of` refuses a missing file; import files only through `_imported` (online, inside their folder) | no (slow first time) | **none** | a picture for the eye; `cutoff_hz`/`quality` in the rows already carry the verdict |
| `media_url(track_id, which)` :1140 | No UI caller (rows/details carry `audio_url`) | Token URL on the hub's local media server (127.0.0.1, random port) | server only while the window runs; `refused` otherwise | no | **none** | human-only (listening); an agent has the file `path` |

### 1b. Writes in the Library page itself

| Method | Where / control | What it does | Hub safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `set_favourites(keys)` :1013 | Right-click Add/Remove favourites, drag into Favourites, ⌥↑/⌥↓ (`BrowserColumn.svelte:233`, `hub.ts:202`) | Replaces the favourites list (`playlist:<ref>` / `folder:<path>`), writes library.db, answers the stored list; stored keys that don't exist now stay in place | **brief save**: no library lock, waits 1.5 s on library.db then `busy`; keys must start `playlist:`/`folder:`; page puts its list back on refusal | no | **none** | none; order semantics = whole-list replace |
| `set_crate_shown(path, shown)` :1041 | Right-click a crate → Hide from sidebar / Show in sidebar; Settings switch | Stores a per-crate override (`true`/`false`/`null` = back to the default) | brief save; `path` must be a crate of a watched folder now (`ValueError` otherwise) | no | **none** | none |
| `set_crates_shown(paths, shown)` :1054 | Settings' All / None, a folder's switches | The same for several crates, one transaction | brief save; all-or-nothing | no | **none** | none |
| `rescan_library()` :1791 | Automatic: window open, back to the front after >60 s (`rescan.ts:12`) | Indexes Library/ against library.db (moved/replaced files found); if it changed anything, plans the stored preview again | job kind `scan`; `busy`/`console` answers are ignored by the page; takes the lock | `JobStarted/JobFinished` (kind `scan`); the hub keeps it out of the job slot (`hub.ts:SCAN_KIND`) | **none** (a sync scans, `run.py:238`; `upgrade list` / `batch` read stale records) | an agent cannot refresh the index; every read would be as old as the last scan |
| `show_in_finder(track_id, which)` :1172 | Details → Show in Finder; row menu | `open -R <file>` (current or parked upgrade file) | `_file_of` refuses a missing file | no | **none** | opens the user's Finder; an agent can read `path` and tell the user |
| `reveal(rel_path)` :1177 | Browser column menu → Show in Finder; Settings; end screen | Finder on a folder: a path inside the music folder, or an absolute path inside a watched import folder | `_inside_root` / `_watched_place`: no `..`, symlinks resolved inside the folder, only places the library knows | no | **none** | same |
| `open_external(url)` :1216 | Row menu "Open in {Service}", every external link, `main.ts:36` | System browser; only `https?://` | regex check | no | **none** | opens a browser: person-only; the URL is in `track_link.url` / `source_url` |
| `select(track_id)` :1163 | `main.ts:39`: `select(null)` on every route change away from To-do | Sets the hub's "current to-do item" (drop target for a dragged file) | none | no | **none** | window-only state (drag and drop) |
| `refresh(auto)` :812 / `stop_refresh()` :872 | Library header "Read playlists" slot for a playlist never read (`ReadStatus.svelte:46-47`) | Reads all playlists from the services (network), scans, with `auto` starts the first import | one auto read per session; not while a sync runs | job kind `refresh`; `ReadingPlaylist`, `JobFinished` | the sync's own read only (`discjockey --dry-run`) | owned by the sync audit; listed because Library has the button |
| `stop()` :1724 | Stop on the import card, on a batch panel, on the moves panel | Cancels the running write job after its current step (a file in work finishes) | none | ends the job with `problem: "stopped"` | Ctrl-C of one's own process (`batch_cmd._interruptible`, `cli._ctrl_c`) | no way to stop a job started by the window or by another process |

### 1c. Writes: watched folders, import, duplicates, same song

| Method | Where / control | What it does | Hub safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `add_watched_folder(path)` :1808 | Settings / Setup → Add folder… (after `pick_folder` dialog + `check_import_folder`) | Watches the folder and imports it in the same job; writes library.db; **reads files, copies/moves/renames nothing** | re-checks like `check_import_folder` (refused with its words); `busy` while an import runs; takes the lock | job `import`: `ImportProgress` (phase `scan\|facts\|tags\|sound\|link`, done, total, unreadable); result `ImportResult` (files, own songs, sound_checked, failed, left, stopped); the link phase reads the playlists (`run.prepare`, network) when the hub has no preview | **none** (README: "the console never imports") | no add, no import |
| `start_import()` :1818 | Continue import (after Stop or a crash) | The same import again, where it stopped | `busy`; clears the `_import_stopped` session flag | same | **none** | |
| `remove_watched_folder(folder_id)` :1824 | Remove (after `removal_preview` + a confirm dialog) | Forgets the folder's files in library.db; files stay; replans the preview | `ValueError` for the Library; the confirm is client-side | job `folders`; result `{files, redownload}` | **none** | the dialog's confirmation has no flag form |
| `answer_same_song(song_key, own_key, same)` :1836 | To-do "Is this the same song?" (shown in To-do, part of the import) | Yes: links the file to the song; No: the song downloads at the next sync; writes library.db; replans | `ValueError` if not str/str/bool | job `answer` | **none** | the questions themselves have no read (finding 4) |
| `keep_duplicates(group_id, paths)` :1849 | Library details or To-do: "Keep both" / "Keep all" | Marks the duplicate group answered; nothing moves | `changed` when the group's files differ from `paths`; `ValueError` for a malformed group id | job `answer` | **none** | |
| `supersede_duplicate(group_id, file_id, paths)` :1863 | Library details or To-do: "Keep the AIFF" etc. (`DuplicateFlow.#keepOne`, `flows.svelte.ts:172`) | Moves one file of the group to `Superseded/` via `library.move_files` (journaled, crash-safe); **moves a user file** | `changed` if `paths` aren't the group's; never deletes; no undo (D10) | job `supersede`; result `{result, recovered}` | **none** | "keep this one" = N-1 calls, the UI recomputes the group id in JS (§2 D10) |

### 1d. Writes: tidy-up, move undo, save question

| Method | Where / control | What it does | Hub safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `tidy_up(moves)` :1620 | Playlists → Tidy up files → "Move N files" | Moves the chosen `[file_id, from_path]` files to where the playlist order puts them (`tidy.tidy_up`: recovery, `.tmp` cleared, **scan first**, then one move batch); never renames a file; never retries onto another name; writes library.db move log | `ValueError` for malformed/empty moves; per-move skips with reasons (drive offline, name taken, file moved since the preview, system refused); not while an import runs (`busy` words); takes the lock | job `tidy`; `MovesProgress(batch_id, done, total)`; result `BatchResultJSON {batch_id, title, moved, headline, skipped[], stopped}` | **none** (README: "the console never moves files") | tidy-up needs a command that is a dry run (= `tidy_preview`) then a move; the user's "batch they started" rule is the agent's call |
| `undo_moves(batch_id)` :1638 | Undo on a recent move, a result, or the batch list | Puts a move batch back, newest first, as a batch of its own; folder rename undo also puts the playlist name back | `ValueError` for unknown batch; per-move skips (file moved/changed since, old place taken) | job `undo_moves`; `MovesProgress`; `BatchResultJSON` | **none** | |
| `preview_playlist_change(lines)` :1473 | Playlists: the panel while the list has unsaved edits (shared with the Playlists audit) | Pure planner on the unsaved lines: what changes, `placement`, `retargeted` files, the rename offers (`tidy.rename_offer`, folder rename allowed or why not); may read an unread playlist once (network) | not while a sync runs | no | **none** | |
| `save_playlists(lines, loaded_version, files)` :1523 | Playlists → Save / "Save and move the files" / "Save, leave files where they are" | Writes `playlists.txt`; with `files = {choice: "move", renames: [[old,new]], moves: [[file_id, from_path]]}` renames folders on disk and moves files as move batches; `leave` records the files as the user's own placement | `changed` if `loaded_version` is stale; a Stop still delivers the batches so far; takes the lock | job `save_playlists`; `MovesProgress`; result `{version, batches[BatchResultJSON]}` | **none** (edit the file by hand: no move question, no undo) | `files` is the answer to a question the window composes (§2 D39) |

### 1e. Writes: AIFF and upgrade decisions hosted by the Library details

| Method | Where / control | What it does | Hub safety | Long run | Today's command | Gap |
|---|---|---|---|---|---|---|
| `convert(track_ids, origin)` :2161 | Details → Convert to AIFF / Give it its clean name (one track, `AiffFlow.run`, `flows.svelte.ts:125`); a multi-selection's panel (origin `library`) | One AIFF batch: per file `eligible.aiff_action` decides Convert or only the name; facts fill first; originals to `Superseded/`; rekordbox repointed while closed; backup; moves/writes user files | one song is `alone` (rekordbox open or `Busy` before anything ran closes the batch: no Resume); plan again at start; lock | job `aiff_batch`; `BatchProgress`; result BatchResult + `recovered` | `convert <track>…` (`convert_cmd.py`) | none; JSON uses `track`, hub `track_id` |
| `rename(track_ids)` :2169 | same card for a clean AIFF with a wrong name | Rename's answer alone | as above | `aiff_batch` | `rename <track>…` | none |
| `make_aiff(scope)` :2175 | Header **Make AIFF…** (`{kind:"lossless", view, key}`) | Plans again at start, runs the plan's items as one batch (`started_by make_aiff`, scope `library:<view>[:<key>]`); search and quality filter do not narrow it | nothing to change ends `refused`; lock | `aiff_batch`; `BatchProgress` | `convert --all lossless [--in playlist:<name>\|folder:<path>\|unlisted]` | `--in` does not take All-with-a-search; a playlist is named by its name, a folder by its path |
| `batch_resume(batch_id)` :2198 | Header "Resume · k left", the batch panel | Carries on a stopped AIFF batch, each item asked again | `ValueError` unless `state == "stopped"` | `batch_resume`; `BatchProgress` | `batch resume <id>` | |
| `batch_undo(batch_id)` :2208 | **No UI caller** (the panel uses `undo_upgrade` per track); the To-do batch card's "Undo all" resolves to `undo_upgrade` | Undoes every track a batch did, newest first | refused while rekordbox open and a change to take back | `batch_undo` | `batch undo <id>` | |
| `undo_upgrade(track_ids)` :2215 | Details → Undo the replace / the conversion / the clean name (asks first) | Puts a swap, an added file, a Same track, a Convert or a clean name back | refusals per track in `results`; `rekordbox_open` | `undo_upgrade`; result UndoResult (+`words`) | `upgrade undo <track>…` | confirm is client-side (flows 72-77, 222-) |
| `upgrade(track_ids, mode)` :2117 | Details → Replace with lossless (`swap` = Same track, `add_new` = New track) or Discard (`discard`) | Replaces a track with its parked better version | `swap`: one AIFF batch, `alone` for one track; `add_new`/`discard` of one track check `_shown` (finding 5); Discard asks confirm client-side | `upgrade_batch`, `upgrade_add_new`, `upgrade_discard`; `BatchProgress` | `upgrade apply (<track>… \| --all) --way same-track\|new-track [--dry-run]`, `upgrade discard <track>…` | |
| `rekordbox_checked(track_ids)` :2096 | Details → Done, checked in rekordbox | Ends the reminder (and the undo) | `changed` when nothing to check | `rekordbox_checked` | `rekordbox checked (<track>… \| --batch ID)` | |
| `hide(track_id, hidden)` :1757 | **No Library control** (To-do's Details only; the Library shows `hidden` in rows and the NOT FOUND tooltip) | Sets/unsets "good enough, hide" on a track | `_single`: `_shown` precondition (finding 5) | job `hide`/`unhide` | **none** | listed because the brief names "hide"; the crate "Hide from sidebar" is `set_crate_shown` |

---

## 2. Logic the window does itself

`A?` = does an agent need the same answer (D = a decision or data; W = only words or layout; V = view state).
"Engine" says where the engine already has it, or **no**.

| # | file:function | What it decides | Engine already has it? | A? |
|---|---|---|---|---|
| D1 | `Page.svelte:159` `askLibrary` + `libraryModel.ts:522` `libraryCalls` + `router.resolveTarget` | A route name may be a playlist or a Library folder (old link): ask as playlist first, then as `folder: Library/<name>`, take the first answer that isn't `empty: "gone"` | no (engine answers `gone`; the choice is the page's) | D |
| D2 | `Page.svelte:70,188`, `libraryModel.ts:36,53` `defaultSort`/`viewSort` | Which sort goes with each call: own choice, else the saved pref per view kind (+ the legacy shared key), else `order` (playlist) / `artist` | default yes (`views.library` `sort or "order"/"artist"`, views.py:1308); the saved sort is localStorage | W |
| D3 | `Page.svelte:111-116`, `libraryModel.ts:194` `filterKey` | The quality filter is remembered per collection, search is cleared on a folder change | no (localStorage) | V |
| D4 | `Page.svelte:212` `keepHeld`, `libraryModel.ts:149-166` (`Hold`, `withHeld`), `lib/decisions/hold.ts` | After an action the acted-on track stays on the table (asked again without filter/search, then from All); a duplicate's Keep moves the selection to the track that holds a kept file | no | V (but the "which track holds the kept file now" is a data question) |
| D5 | `decisionModel.ts:359` `decisionFor` + `Page.svelte:259` `todoAt` | What decision a track's details wait for, in To-do's order: the rekordbox check (item in group `rekordbox_check`, `!pair`, same `track_id`, also inside a batch item's tracks), a duplicate group one of whose files has this `song_key` or `path`, else the parked upgrade | no per-track read; the pieces are `todo()` groups + `track().upgrade` | D |
| D6 | `libraryModel.ts:179` `inTodo`, `:184` `rowInTodo` | Whether "Open in to-do" is offered: `in_playlists && !hidden && (status !== 'lossless' \|\| upgrade_ready)`; a song without a file only when `wait === 'not_found' && !hidden` | **differs from the engine**: `views._group` (views.py:1505) requires `sound_checked`, `todo_listed` (views.py:1513) also lists an own file with an upgrade that is in no playlist and drops questions in `held` and "never download" songs | D (a divergence: console and hub can disagree) |
| D7 | `libraryModel.ts:458` `footAction`, `aiffModel.ts:40` `aiffShown`, `:54` `aiffVariant` | Which foot the details show: the decision's, else Convert/Rename card (only for a file that is there, `aiff.action` set or `why_not` in `rekordbox_unreadable\|cloud\|rename_blocked`), its button filled or outline (lossy non-CDJ non-rename = outline), "Open in to-do" with it | engine gives `aiff {action, why_not, lossy, cdj}`; the rest is UI | D (partly) |
| D8 | `decisionModel.ts:99` `upgradeWays`, `:16` `canSwap`, `:127` `defaultWay` | Which of Same track / New track an upgrade offers, which is the default (Same track where `swap_safe && swap_possible`), what each does ("becomes an AIFF", "set cues again", the line why Same track can't) | engine gives the facts (`swap_safe`, `swap_possible`, `swap_how`, `why_not`, alignment); the composition is UI; console `upgrade list` gives only `same_track` (quick reason) | D |
| D9 | `flows.svelte.ts:55-58,72-` | Confirmations: **Discard asks, Replace does not, Undo asks** (`undoAsk`, `undoManyConfirm`); remove-folder asks (`watchedFoldersFlow.svelte.ts:98`) | no | D (flags in the console) |
| D10 | `flows.svelte.ts:172` `#keepOne` + `decisionModel.ts:347` `groupIdOf` | "Keep file X of N" = N-1 `supersede_duplicate` jobs one after the other; after each the group id is recomputed in JS (`'dup:' + sorted ids joined '-'`, the same formula as `models.group_id`, models.py:531) and `paths` is the files left; stops at the first failure; "Keep both/all" = one `keep_duplicates` | engine has `models.group_id` and one-file `supersede`; no "keep this one" operation | D |
| D11 | `decisionModel.ts:337` `keepWords`, `flows.svelte.ts:155` `pick` | The default pick is `group.recommended` (engine: a clearly better file); the button is named by the result ("Keep the AIFF") | `recommended` yes (`views.recommend`, views.py:1675) | W |
| D12 | `aiffModel.ts:59` `aiffBlocked` | The Rename button is off while rekordbox runs or is unreadable; Convert is left to the engine | engine refuses at run (`rekordbox_open`) | W |
| D13 | `aiffBatchModel.ts:92` `blockReason`, `:66` `runLabel`, `:43` `listShape` (`FILES_MAX = 8`) | The filled button is off when a drive has too little room (`space[].enough`) or rekordbox runs and `needs_closed`; label "Make k files AIFF" / "Give k files their clean names" / "Convert k to AIFF"; files list vs counts per kind above 8 items | plan carries `space`, `rekordbox`; the refusal at run is the engine's (`batches.run`); **check first** whether a run refuses too little space | D (run-blocking) / W |
| D14 | `aiffBatchModel.ts:136` `leftRows`, `:147` `panelPhase`, `:104` `planOutcomes`, `:84` `spaceRows`, `:77` `driveName` | "Left as they are" rows (selection: skipped by track; view: `waiting` counted by reason), phase `loading\|error\|empty\|decide\|running\|ended`, outcome lines, drive named "this Mac" for non-/Volumes paths | data in the plan; the words are UI (the console prints the raw drive path, `convert_cmd.py` `_plan_lines`) | W |
| D15 | `libraryModel.ts:561` `tableScope`, `:567` `selectAllRows`, `selectionModel.ts` | What "select" means: only rows with a file (a song with `file_state === 'no_file'` can't be in a multi-selection; away rows can, the plan then leaves them out with a reason); **⌘A = every row on screen after filter and search, in table order incl. the playlist's `also` rows**; ⌘-click toggles, ⇧-click a range | `convert --all lossless --in` is "the whole view", which **ignores search and filter** (README says so), so ⌘A has no console form | D |
| D16 | `libraryModel.ts:577` `keepTableSelection`, `:588` `inspectorSubject`, `Page.svelte:84-93,378-` | After a new table answer a multi-selection keeps the rows still listed; the inspector shows one track, the batch panel (2+ rows), the view's plan, or nothing | no | V |
| D17 | `libraryModel.ts:344` `playable`, `:539` `playQueue`, `lib/listen.ts`, `queueModel.ts:68` `snapshot` | ▶ queues the rows with `file_state === 'here'` in the shown order (filter, search, sort applied; a playlist's songs then its `also`); the snapshot filter in `queueModel.snapshot` is `path !== null` (slightly different rule) | no | V (human: listening) |
| D18 | `libraryModel.ts:222-266,281,295` (`optionalColumns`, `playlistColumnFor`, `artistColumnFor`, `columnsAt`, `hasSubfolders`, `tooManyFor`) | Which table columns exist: Playlist column only if some row is in a playlist, Artist column only if some row has an artist, Subfolder only when crates sit inside; widths and thresholds | engine gives the data (`playlists[]`, `artist`, `subfolder`, sidebar `crate_count`, `too_many`) | V |
| D19 | `libraryModel.ts:396` `subtitleParts`, `:419` `pageEmpty`, `:446` `alsoHint`, `:597-608` | Words and parts: "13 of 18 downloaded" from `songs{listed, with_file}`; which of six empty states (`library gone never_read empty search filter`) from `lib.empty`, `read_at`, view, query, filter | engine `empty` is only `gone\|empty_library\|no_match`; `read_at` and `songs` are there | W |
| D20 | `libraryModel.ts:368` `nextTryLine`, `:376` `notFoundTip`, `:381` `localDay`; `format.ts:153` `dayMonth` | "next try in N days": date arithmetic against the browser's local day from `next_try` / `next_qobuz_check` | engine has the date (`views.next_due` views.py:574, `next_check` :586) | W |
| D21 | `Page.svelte:233-238`, `libraryModel.ts:499` `noFileNote`, `:510` `playlistsLine` | A playlist song with `file_state === 'no_file'`: the page does not call `track()` for `wait === 'waiting'` (engine may not know it); details come from the row; the note says what happens next (waits for the next sync, Qobuz first / looked and nothing usable, To-do has more) | the row carries `wait`, `next_try`; words are UI | D (a `track` read of such a song is not valid) |
| D22 | `format.ts:59` `qualityWords`, `:267` `cutoffStat`, `:238` `rowAway`, `:245` `fileAwayWords` | Words for quality, the cutoff ("where the highs end", "no clear edge", the fake lossless format), why a file is away | engine words exist in part (`quality_label`, `quality_line`) | W |
| D23 | `browserModel.ts:309` `browserList` | The collections list as drawn: **"Not in a playlist" only if `not_in_playlist > 0`**, sections Favourites / Playlists / Folders, Playlists in playlists.txt order or A–Z (pref), watched folders with their visible crates (a folded watched folder hides them), the Library folders no playlist uses, **one row per folder path** (`once`), filter by folded names, the "Search tracks for …" hand-off | engine `sidebar()` gives the raw lists | V (except the hidden-crate rule, D24) |
| D24 | `browserModel.ts:327` `isHidden`, `:513` `crateShownValue` | A crate is hidden if the local override says so, else its `hidden` default; what `set_crate_shown` is sent: only an override that differs from the default (`true` under a folder with too many, `false` under one with few), else `null` | default is the engine's (`views.crates`, views.py:1383-1391: `hidden = not overrides.get(path, not too_many)`, `CRATE_LIMIT = 25`); the client decides what to store | D |
| D25 | `browserModel.ts:216` `revealPath` | Which collections can be shown in Finder: a playlist → `Library/<name>`; a folder only when under `Library/` or its state is `here` | `api.reveal` accepts any place inside the music folder or a watched folder | W |
| D26 | `browserModel.ts:458` `moveKey`, `BrowserColumn.svelte:297-310`, `hub.ts:202` `saveFavourites` | Favourites: add = append, remove = filter, drag/⌥↑↓ = new order; the whole ordered list is sent; the sidebar is re-read after a refusal | engine replaces the list as sent | D |
| D27 | `browserModel.ts:517` `playCall`, `BrowserColumn.svelte:315` `play` | Browser Play = `library(view,key,'', 'all', the page's saved sort)` then `playQueue` | no | V |
| D28 | `rescan.ts`, `rescanModel.ts:7` `shouldRescan` | When the index is refreshed: at start and after >60 s in the background | no trigger in the engine | D |
| D29 | `watchedFoldersModel.ts` `importView`, `canContinue`, `folderLine`, `folderMark`, `settingsLine`, `phaseLine`, `phaseShare` | Import card state: `running` (from `job.last.ImportProgress`), `stopped` (hub `folders.stopped` && `waiting > 0`), `done`/`failed` (last job of this session); **Continue import offered = `waiting > 0` and no import running** | rows have `state`, `waiting`, `stopped`; `stopped` is session memory of the hub | D |
| D30 | `watchedFoldersFlow.svelte.ts:73-86` `add`, `:92-103` `remove` | The add sequence: dialog → `check_import_folder` → refusal words or `add_watched_folder` (which checks again); removal asks with the preview's numbers | engine re-checks on add | W |
| D31 | `tidyModel.ts:69-118` `groups`, `initialTicks`, `toggleGroup`, `tickedRows`, `movesOf` | What a tidy-up sends: the rows the engine ticked (`ticked`), unticking by hand, the "You put these here" group ticked all at once by "Put these in playlist order too", main group first then "yours"; skipped rows never ticked | `ticked`, `yours`, `skip` come from the engine; the "all default-ticked" is just the engine's flags | D |
| D32 | `tidyModel.ts:157-232` `initialQuestion`, `carryOver`, `visibleRows`, `folderRows`, `saveFiles`, `saveMoving` | The save question: folder renames **offered and on by default**, a rename that is on hides the files it carries (`by_rename`), a newer preview keeps the user's ticks, `leave` sends no renames/moves | `rename_offer`/`by_rename` from `preview_playlist_change`; the combination is UI | D |
| D33 | `tidyModel.ts:136` `countLine`, `:51-62`, `:294-316` `outcomeOf`, `resultUndo` | "8 files move from A to B", result counts, Undo target (one batch → its confirmation, several → the list) | engine has `moved`, `skipped`, `headline` | W |
| D34 | `libraryModel.ts:548` `rowMenu` | Row menu items: Show details, Show in Finder (file there), Open in {Service} (`track_link.label`), Open in to-do (`rowInTodo`) | `track_link` from engine | W |
| D35 | `Page.svelte:289-294` | The upgrade's spectrum is asked only when the details carry `upgrade` | — | V |
| D36 | `format.ts:48` `sizeWords` vs `convert.size_words`, `libraryModel.ts` `OFF_TIP` etc. | Two implementations of the size words ("1.2 GB", "35 MB"); the console prints `convert.size_text` | duplicate (comment in `format.ts` says it mirrors the engine) | W |
| D37 | `hub.ts:122-157` `reduceHub`, `refreshHub` | Which events refresh what: every `JobFinished`, `ConsoleBusy{running:false}` and `DrivesChanged` re-read job_status, setup_status, sidebar, app_update; `filesVersion` also bumps on drives | no | V |

Checks of the divergence in D6 for the designer: an unchecked own file (provisional quality `good_lossy`, no
`sound_checked`) is "to do" for the UI and not for `_group`; an own file in no playlist with a parked upgrade is on
To-do (engine) and has no "Open in to-do" in the Library (UI).

---

## 3. Screen states

State families from `6-screen-states.md` for this area (`hub-ui/src/pages/library/shots.json` 114 names, the base
shell shots of the Library chrome, `playlists-*` tidy/undo/rename shots, `settings-folders-*` and `setup-existing-*`
import shots, `todo-duplicates*` and `todo-same-song*`). "Data" = what an agent needs; "View" = what only a person
looks at.

| Family (shot names) | What it shows | Read that gives an agent the data | Kind |
|---|---|---|---|
| `library-all`, `-big`, `-empty`, `-sorted-quality-desc`, `-search-no-match`, `-filter*`, `-filtered-away/-back`, `-filter-upgrades`, `-unchecked*`, `-untagged`, `-first-look` | All tracks, filtered, searched, sorted, empty library, files whose sound isn't checked | `library(view, key, query, filter, sort)`: **no command** | Data |
| `library-playlist*` (`-away-selected`, `-waiting-selected`, `-not-found-selected`, `-off`, `-never-read`, `-empty`, `-gone`, `-no-match`), `library-not-in-playlist`, `library-unlisted-empty`, `library-own-upload` | A playlist's songs in order incl. waiting / NOT FOUND, `Also in this folder`, a switched-off, never-read or gone playlist | `library(view=playlist, key)`: **none**; `rows[].wait/next_try/file_state`, `songs`, `read_at`, `enabled`, `also`, `empty` | Data |
| `library-folder*` (`-selected`, `-no-upgrades`, `-crate`, `-offline`, `-library`, `-empty`, `-gone`, `-too-many(-focus)`), `library-crates*`, `library-favourites`, `library-filter-crates*`, `library-ejected(-back)`, `library-come-back` | A watched folder or crate, offline/missing folder, too many crates, favourites | `library(view=folder, key)` + `sidebar()` (`watched[].state`, `crates[]`, `too_many`, `favourites`): **none** | Data |
| `library-*-selected`, `-long-panel-*`, `-fake-*`, `-weak-selected`, `-lossless-selected`, `-soundcloud-*`, `-youtube-music-selected`, `-source-how`, `-offline-selected`, `-folder-missing-selected`, `-file-missing-selected`, `-track-gone` | One track's details: quality, source, playlists, away reasons, spectrum | `track(id)` (+`spectrum`): **none** (`rekordbox preview <key>` for eligibility only) | Data (spectrum picture = View) |
| `library-decision-*` (`upgrade`, `replaced`, `after-add`, `duplicate`, `replaced-filtered`, `kept-other`), `library-upgrade*`, `library-upgrade-mismatch` | Which decision the selected track waits for; the check card after a replace; duplicate choice | `todo('all', true)` + `track().upgrade` joined by `decisionFor` (D5): partial via `upgrade list`; checks/duplicates **none** | Data |
| `library-aiff-*` (`flac`, `lossy`, `cdj`, `rename`, `blocked`, `rename-blocked`, `check-converted`, `multi`, `selection`, `selection-lossy`, `view`, `view-empty`, `view-loading`, `view-space`, `rekordbox-open`) | The Convert card and the batch panel's plan for a track / selection / view | `track().aiff`, `aiff_plan(scope)`: `convert … --dry-run --json` (`items`, `skipped`, `waiting`, `kinds`, `space`, `rekordbox`) | Data (loading/empty/blocked = derived, D13/D14) |
| `library-aiff-running`, `-panel-running`, `-panel-stopped(-ended)`, `-panel-ended`, header "Resume · k left" | A running, stopped or ended AIFF batch | `job_status()` / `BatchProgress` / `library().aiff_stopped`: console `batch list`, `batch show <id>` (no events) | Data (the panel's `view` object is window state) |
| `library-now-playing*`, `library-playing*`, `library-keys` | Foot bar, queue, shuffle, hidden player, End of …, can't play | none: the queue and the audio element live in the window (`player.ts`, `queueModel.ts`); `audio_url` is only valid with the window's media server | View / person |
| `library-browser*`, `-inspector*`, `-details-hidden*`, `-pick-opens`, `-first-open-*`, `-closed-*`, `-long-titles-1100`, `-context-menu`, `library-console` | Layout, panel open/hidden, row menu; `library-console` is the console-busy banner | layout: none needed. Console busy: `job_status().console_running`; for an agent a lock refusal (exit 3 `busy`) | View (console busy = Data) |
| `library-crates-busy`, `-folder-too-many*` | A crate switch refused (`busy`), too many crates | `set_crate_shown` answers `busy` | Data |
| `playlists-tidy-*` (`mixed`, `many`, `empty`, `only-yours`, `moving`), `playlists-move-fails`, `playlists-big-move` | Tidy-up preview, three groups, progress, "not moved" reasons | `tidy_preview()`, `MovesProgress`, `BatchResultJSON`: **none** | Data |
| `playlists-batches`, `playlists-undo-skips`, `playlists-rename-*` (`offered`, `leave`, `taken`) | Recent moves, undo preview with skips, the folder-rename offer on save | `move_batches()`, `undo_preview(id)`, `preview_playlist_change(lines)`: **none** | Data |
| `settings-folders-*` (`library-only`, `importing`, `stopped`, `offline`, `missing`, `couldnt-read`, `long-names`, `remove`, `added`, `crates`, `too-many`, `crates-busy`, `crates-many-folders`), `setup-existing-*`, `base-gallery-watchedfolders`, `base-gallery-folderfield` | Watched folders, import card (running/stopped/done/failed), unreadable files, crate switches, remove dialog | `watched_folders()`, `removal_preview`, `check_import_folder`, `ImportProgress`, `JobFinished(import)`: **none** | Data (card state D29) |
| `todo-same-song*`, `todo-duplicates*` | The import's questions and duplicate groups | duplicates: `todo()`; same-song questions: only in the window's plan (finding 4) | Data (questions unreachable) |
| `base-shell-favourites`, `base-frame-library`, `base-shell-folded`, `base-shell-foot*` | Favourites drag, chrome form, foot | `sidebar().favourites` for the data; the rest is layout | Data / View |

**Held only by the window (not data an agent can ask for):** the selection and its anchor (`?track=`), details
open/hidden by hand (pref `detailsHidden`), the player queue/shuffle/position, the open batch panel's `view`
(`aiffBatch`, `upgradeBatch`), `Hold`, the per-view sort and filter (localStorage), folded sections, A–Z, browser
width, `_import_stopped`, `_import_auto_done`, `PreviewStore.prep`/`read_at`, `_shown`.

---

## 3b. Information shown

Every piece of information the window shows in this area, with its source and whether any command gives it today.
Source: bridge field (`method.field`) or computed in the UI (`file:function`). Command today: exact or **none**. Where
a cell says "not checked" the field or the exact words were not read. Every "none" is a gap: the CLI must give an
agent and a human at least this. Today the only commands that print anything of the area are `convert|rename
--dry-run` (the plan), `upgrade list`, `batch list|show`, `rekordbox status|preview|checked|backups`.

### Library page: header and strip

| Shown | Source | Command today |
|---|---|---|
| Page title (All tracks, Not in a playlist, playlist folder name, folder name) | `library.title`; before the answer `libraryModel.ts:531` `targetTitle` | none |
| Subtitle parts ("N tracks", "every folder" / "in no playlist" / "{Service} playlist", breadcrumb); "13 of 18 downloaded" instead of the count | `library.subtitle`, `library.songs{listed,with_file}`; composed in `libraryModel.ts:396` `subtitleParts` | none |
| Summary strip: tracks, lossless share (percent bar), by-quality counts, "Upgrades ready", "Not lossless yet", "To do" count; dashed bar end for songs without a file | `library.summary{tracks, lossless_share, by_quality, upgrades_ready, not_lossless, to_do}`, `library.songs` | none (sync `--dry-run` prints plan counts only) |
| Quality filter chips with counts (All, Lossless, Good lossy, Weak, Fake only if >0 or chosen, Upgrade ready) and coloured dots | `library.chips`; labels/dots/order in `libraryModel.ts:200` `FILTERS`, `:207` `segOptions` | none |
| Search field text, placeholder, "Search tracks for …" hand-off | UI (`SearchField`, `browserModel.ts:140` `searchTracksHref`) | none |
| Header button "Make AIFF…" (hidden when no files, empty library or view gone), tooltip "Make all lossless files AIFF", or "Resume · k left" with tooltip | `library.aiff_stopped{batch_id,left}`; `libraryModel.ts:602` `aiffHeader` | none (`batch list` shows stopped AIFF batches; its `left` = `planned`) |
| "Show some in the sidebar…" link with "N folders with music, too many for the sidebar" tooltip | `sidebar.watched[].too_many/crate_count`; `libraryModel.ts:295` `tooManyFor` | none |
| Details toggle: icon, struck-through icon, "Show details" dashed, tooltips ("Select a track to see its details", "Hidden by you: …") | UI pref `detailsHidden` (`stores/chrome.ts`), `Page.svelte:441` | none (window view state) |
| "Read playlists" slot / read status ("read 2 min ago", problems) for a never-read playlist | `job_status.read_status`; `ReadStatus.svelte` | none (sync only) |
| Empty states and their words: library empty ("Open Sync"), playlist/folder gone, never read ("This playlist wasn't in the last read."), "This playlist is empty.", "Every track is in a playlist.", "No music in this folder.", "Nothing in X matches “q”.", "No tracks with this quality here." and the "Clear search / Show all / All tracks" actions | `library.empty` (`gone|empty_library|no_match`), `read_at`, `view`; the choice and words in `libraryModel.ts:419` `pageEmpty` | none |
| Skeleton while loading, ProblemCard with the engine's message and Retry | UI state; `Res.kind/message` | none |

### Library page: the table

| Shown | Source | Command today |
|---|---|---|
| Rows, their order, the sort arrow on the head | `library.rows[]` order (engine sort `views.SORTS`); sort value from UI pref | none |
| Playlist `#` column (position) | `rows[].position` (`order` sort) | none |
| Cover (dashed empty cover for a song without a file) | `rows[].cover_url`; dashed = `file_state === 'no_file'` | none |
| Title, artist, length (m:ss), title tooltip with full name | `rows[].title/artist/duration_s`; `format.ts` duration | none |
| "in {place}" note after the title in a playlist view | `rows[].place`; `libraryModel.ts:322` `titleNote` | none |
| Dimmed row = song left every playlist (not own) — tooltip "Not in any playlist any more"; or file away; or song without a file | `rows[].in_playlists`, `own`, `file_state`; `libraryModel.ts:330` `rowOff`, `:351` `rowDim`, `:334` `rowTitleTip` | none |
| Folder column ("where the file sits"), Subfolder column, Playlist badge with "+n" and tooltip "In A, B" | `rows[].place`, `rows[].subfolder`, `rows[].playlists`; `libraryModel.ts:306,311,316` | none |
| Which columns show at the table's width | UI `libraryModel.ts:264` `columnsAt` | n/a (layout) |
| Quality badge (class, label such as "FAKE · 16.0 kHz", kHz), tooltip "Show details", "sound not checked yet" variant | `rows[].quality`, `quality_label`, `cutoff_hz`, `sound_checked` | none |
| "UPGRADE" badge | `rows[].upgrade_ready` | `upgrade list` (parked ones only) |
| "Waiting" / "Switched off" (muted) and "NOT FOUND" (red) for songs without a file, with tooltips (next try in N days, "You hid it from To-do", "Downloads at the next sync") | `rows[].wait`, `next_try`, `hidden`, `library.enabled`; `libraryModel.ts:362` `waitWords`, `:376` `notFoundTip`, `:368` `nextTryLine` | none |
| Away tag ("Offline", "Folder not found", "File not found") and its tooltip | `rows[].file_state` (`offline|folder_missing`); words `format.ts:225-235` | none |
| "Also in this folder" section head with hint ("files in X that aren't in this playlist" / "…until the playlist is read") and the files | `library.also`; `libraryModel.ts:446` `alsoHint` | none |
| Empty line above the section ("This playlist is empty.", "None of the playlist's songs match …") | `libraryModel.ts:419` `pageEmpty.line` | none |
| Row menu: Show details / Show in Finder / Open in {Service} / Open in to-do (which items exist) | `rows[].track_link{label,url}`, `file_state`; `libraryModel.ts:548` `rowMenu`, `:184` `rowInTodo` (diverges, D6) | none |
| Selected rows wash, multi-selection count in the panel title | UI selection (`selectionModel.ts`) | none (window state) |
| Row heights/windowing above 300 rows | UI | n/a |

### Library inspector: one track

| Shown | Source | Command today |
|---|---|---|
| Head: cover, "Artist – Title", "length · in {place}" (or "not downloaded yet"), quality badge with words ("verified lossless", "lossy, hard to hear", "lossy, audible", "fake lossless", "sound not checked yet", "no file yet") | `track.*` (`quality`, `quality_label`, `sound_checked`, `place`); `format.ts:59` `qualityWords` | none (`rekordbox preview` gives codec only) |
| "Open in {Service}" link on the head | `track.track_link` | none |
| Track not here any more / failed load card | `track()` `changed|refused` | none |
| Convert / Give-it-its-clean-name card: now, becomes, name, space, rekordbox outcomes ("keeps its cues…"), lossy note, CDJ note, blocked reasons, button label and filled/outline | `track.aiff` (`action`, `why_not`, `lossy`, `cdj`, names, bytes); words `aiffModel.ts` `aiffRows`, `aiffOutcomes`, `aiffNotes`, `aiffBlocked`; rekordbox state `rekordbox_status` | `convert <key> --dry-run` (items/skipped/space/rekordbox; the words differ) |
| Upgrade cards: Now/New comparison, quality lines, edit line ("The same edit, 3 ms apart"), "In rekordbox" choice and its outcomes, waits-for-rekordbox hint, auto-refused note, Replace/Discard labels | `track.upgrade{alignment, swap_safe, swap_possible, swap_how, why_not, rekordbox, auto_refused, auto_waits, what}`; words `decisionModel.ts:99,132,142,151,158-175` | `upgrade list` (`now`, `new`, `alignment`, `same_track`, `auto_refused`, `auto_waits`) |
| Compare player for Now vs New | `upgrade.audio_url` + file; human | none (person) |
| Rekordbox check card: steps (Reload Tag, analyse again, USB stick), what was replaced, kept fields, Undo wording | To-do item `check` / `rekordbox_check` (`todo()`); words `decisionModel.ts:176-290` | `rekordbox checked` acts; the steps are **none** |
| Duplicate card "Which file stays?": files with format, folder, quality, "Goes to Superseded/", recommended pick, button "Keep the AIFF", "Not deleted: kept in Superseded/" | To-do duplicate item `pair{group_id, files[], recommended}`; `decisionModel.ts:319,337` | none |
| Cutoff StatCard: "{n.n} kHz — where the highs end, lossless reaches about 22 kHz" / "no clear edge" / "a lossy file inside the WAV" | `track.cutoff_hz`, `status`, `path`; `format.ts:267` `cutoffStat` | none |
| Spectrum picture and waveform; "Offline: connect the drive" in place of it | `spectrum.spectrum{matrix 400×128 dB re loudest, floor −100, waveform peaks, cutoff_hz}` (`spectrum.py`); engine verdict also in `quality`, `quality_label`, `cutoff_hz`, `status` | none for the matrix; the verdict is in `library`/`track` (none) |
| Mini player: play/pause, scrubber, position, length | `track.audio_url`, `track.duration_s`; window audio | none (person) |
| Current file card: Format, Source (+ source URL link, source format, "exact Qobuz track / found by ISRC / found by name / the playlist's own upload / picked by you"), Playlists (names or "–"), Added (day month), File name; "Show in Finder" | `track.format_line`, `source_full`, `source_url`, `source_format_line`, `source_how`, `playlists`, `added`, `path`; `copy.ts` `sourceHowWords`; `libraryModel.ts:468` `fileName`, `:510` `playlistsLine`, `:474` `shortUrl` | none |
| Away words for the file ("Offline: connect the drive", "Folder not found", "This file isn't there any more.") | `track.file_state` (incl. `file_missing`); `format.ts:245` | none |
| Song without a file: NoteCard "downloads at the next sync…" / "No source had a usable copy… Qobuz looks again on 12 Mar", switched-off note, Open in to-do button | row `wait`, `next_try`, `hidden`, `library.enabled`, `track.next_qobuz_check`; `libraryModel.ts:499` `noFileNote` | none |
| Foot buttons (Replace, Discard, Done, Undo, Keep…, Convert, Open in to-do) and the hints under them | UI (`libraryModel.ts:458` `footAction`) over the above | the actions have commands; the choice of buttons is none |

### Library inspector: several rows and Make AIFF…

| Shown | Source | Command today |
|---|---|---|
| Panel title ("N tracks selected", "Make all lossless files AIFF · in {view}"), sub "k can become clean AIFF" | `aiff_plan.total`, `scope.label`; `aiffBatchModel.ts:47` `panelHead` | `convert … --dry-run` (plan.total, scope.label; words differ) |
| Format sentence, lossy note, files list (≤8) or counts per kind, "Left as they are" rows with reasons, waiting counts by reason | `plan.items/kinds/skipped/waiting/lossy`; `aiffBatchModel.ts:23-143` | `convert --dry-run` prints items, skipped, waiting, kinds, lossy line |
| Room per drive ("Needs 3.1 GB on this Mac · 40 GB free", short drive in red), "Your originals (size) go to Superseded/" | `plan.space`, `superseded_bytes`; `aiffBatchModel.ts:84,104` | `convert --dry-run` prints space and originals lines (raw drive path) |
| "Quit rekordbox before you start" and button off | `plan.rekordbox{running,needs_closed}`; `blockReason` | `convert --dry-run` prints the open-rekordbox line |
| Button label ("Make 52 files AIFF", "Give k files their clean names") | `aiffBatchModel.ts:66` `runLabel` | none |
| Running: "Making AIFF · Artist – Title", done of total, per-file rows with tick, Stop | `BatchProgress{done,total,track_id,name}` | stderr line "Converting 3 of 52: …" (human only) |
| Ended: "Made 52 files AIFF", "k left as they are", notes for stopped/rekordbox open, Resume, Try again | `JobFinished.result` BatchResult; `aiffBatchModel.ts:160-185`, `decisionModel.ts:512-572` | `convert` JSON `results[]`, `batch show` |

### Browser column, rail, sidebar

| Shown | Source | Command today |
|---|---|---|
| All tracks count; Not in a playlist count (row hidden at 0) | `sidebar.all_tracks`, `not_in_playlist`; `browserModel.ts:325` | none |
| Favourites rows (service logo or folder icon, name, count), "Drag a playlist or folder here" when empty, "!" for an away folder | `sidebar.favourites[]`; `browserModel.ts:254` `favouriteRow`, `:27` | none |
| Playlists rows: service logo, name, song count (or none for never read), dimmed when switched off, order (playlists.txt or A–Z) | `sidebar.playlists[]{name,ref,service,enabled,songs}`; `browserModel.ts:309` | none |
| Folders: watched folder rows with count, crates indented, fold arrow, "!" and tooltip "Offline: connect the drive" / "Folder not found", hidden crates (not listed), Library folders no playlist uses | `sidebar.watched[]{path,name,files,state,crates[],too_many}`, `library_folders[]`; `browserModel.ts:179-195` tips | none |
| Row tooltips (playlist: service, enabled, songs; folder: path, files) | `browserModel.ts:172-190` | none |
| Filter matches with highlighted letters, section "none" line "No playlist or folder called “x”" | UI `browserModel.ts:128-169,384` | n/a |
| Rail: page icons, To-do count pill (99+), sync progress "12/40", warning mark on Download limits, tooltip words, shortcut key caps | `sidebar.todo`, `sidebar.limits_warning`, `job_status`/run events; `sidebarModel.ts` | none |
| Now playing row (when the player is hidden) | UI `footModel.ts:rowShown` | none (person) |

### Foot bar

| Shown | Source | Command today |
|---|---|---|
| Playing title, "Artist · list name", cover, ▶/⏸/loading/error state, "Can't play this file.", "End of {list}" | `stores/player.ts`, `footModel.ts:25` `footPlayer`; track from the queue snapshot | none (window audio; nothing to ask) |
| Position, length, scrubber fraction, shuffle state, prev/next availability | `player.ts`, `queueModel.ts` | none |
| Sync part ("Sync 4 of 6", "Upgrading · k of n", protection pause countdown, "Qobuz 12 of 60 today") | run events; `shell/activity.ts` | sync `--json` only at the end; no live read |

### Watched folders and import (Settings / Setup cards; Library depends on them)

| Shown | Source | Command today |
|---|---|---|
| Folder rows: name, short path (drive named first), "Always watched" / "Online" / "Offline: connect the drive" / "Folder not found: …" / "Checking for new files" / "Importing · n waiting" / "n file waiting", mark ✓ ! spinner | `watched_folders.folders[]{kind,state,path,name,files,waiting,unreadable}`; `watchedFoldersModel.ts:25,131,148` | none |
| Import card: phase line ("Reading tags · 340 of 1,500"), progress share, stopped line ("Import stopped with n files to go…"), "Imported n files.", failure line, Continue import / Stop | `ImportProgress`, `job.finished.result` ImportResult, `watched_folders.stopped/waiting`; `watchedFoldersModel.ts:117-150` | none |
| "Couldn't read (n)" list: file, folder, reason, "Tried again at the next import." | `watched_folders.unreadable[]{folder_id,path,reason}` | none |
| Settings row line ("2 folders · 1,204 files", "X is offline", "Library only") | `watchedFoldersModel.ts:187` `settingsLine` | none |
| Add refusal words and merge hints ("takes over …") | `check_import_folder.message/merge_hints` | none |
| Remove dialog: "Remove X?", "Discjockey forgets its n files. The files stay where they are.", "n songs … downloaded again at the next sync" | `removal_preview{name,files,redownload}`; `watchedFoldersModel.ts:181` `removeWords` | none |
| Crate switches list (per crate label, files, shown/hidden, "All / None", search) | `watched_folders.folders[].crates[]` (`hidden`, `files`, `has_crates`) | none |
| "Is this the same song?" and duplicates groups in To-do | To-do items (see To-do audit); same-song questions only in the window's plan | none |

### Tidy up and undo (Playlists page panel)

| Shown | Source | Command today |
|---|---|---|
| Tidy preview: three groups (default moves, "You put these here", "Can't move"), per file cover, "Artist – Title", from → to, tick state, "n of m ticked", skip reason words | `tidy_preview.rows[]{file_id,from,to,from_path,ticked,yours,skip{reason,text}}`, `yours{header,control,count,movable}`; `tidyModel.ts` | none |
| Count line ("8 files move from A to B.", "… between 4 folders.") and warning card (rekordbox may show tracks missing; Relocate by file name; "You can undo this on this page.") | `tidy_preview.rekordbox[]`, `undo_note`; `tidyModel.ts:136` `countLine` | sync prints only "n files are not where the playlist order puts them" (`cli.py:100`) |
| Empty states ("Every file is where the playlist order puts it.", only-yours note) | `tidy_preview.empty` | none |
| Progress: "n of m files moved", per-row ✓ | `MovesProgress{batch_id,done,total}` | none |
| Result: "Moved n files.", "k not moved:" with each reason; Undo / Done | `BatchResultJSON{batch_id,title,moved,headline,skipped[]{label,from,to,reason,text},stopped}` | none |
| Recent moves list: title ("Tidy-up", "Saved playlists", "Renamed A to B", "Undo of: …"), time, "n files moved · k not moved", Undo or "Nothing left to undo" | `move_batches.batches[]{id,at,title,moved,skipped,undoable,undone_by,summary}` | none (`batch list` is AIFF) |
| Undo preview: rows going back (↩), "Can't move back" with reasons, "n of m go back", warnings, folder rows "the whole folder · 7 files" | `undo_preview{title,rows[],moving,warning[],nothing_left}`; `tidyModel.ts:55,258` | none |
| Save question: "n files would sit in a different folder", rename options (offered, why not, "One folder move instead of 7 file moves."), leave-hint words | `preview_playlist_change` (`placement`, `retargeted`, renames `{from,to,files,offered,why_not}`, `by_rename`); `tidyModel.ts:32,47,197` | none |
| Recovery messages after a crash ("A tidy-up was stopped before it finished: …") | `tidy.RECOVERED*`, via `recovered` in job results / toast | printed by write commands as `recovered` (AIFF/upgrade only) |

### Toasts, banners, dialogs of this area

| Shown | Source | Command today |
|---|---|---|
| "Can't play this file." toast; "Nothing here can play right now." with the folder's away words | `libraryModel.ts` / `BrowserColumn.svelte:315` | none |
| Problem toasts with the engine's `kind` title and `message` (busy "Discjockey is importing your music…", console running, changed, refused) | `Res.kind/message`, `copy.ts` `problemCopy`, `WRITE_BLOCKED` | exit code + `kind`/`message` JSON for the AIFF commands only |
| Success toast "Moved n files to Superseded/." after Keep; undo toast ("Upgrade undone. Your old file is back.") | `flows.svelte.ts:172-196`, `UndoResult.words` | `upgrade undo` prints per-track lines (words not checked) |
| Confirm dialogs: Discard, Undo, Remove folder, leave unsaved Playlists | UI | none (see §5: no flag form) |
| "Console is running" banner | `job_status.console_running`, `ConsoleBusy` | n/a (exit 3 `busy`) |

---

## 4. Journeys

Marks: **[P]** only a person can do it (the agent must tell the user), **[W]** has an effect only in the window.

| # | Journey | Steps → bridge → command today |
|---|---|---|
| J1 | Find tracks | open Library → `sidebar()` (the collections) → click a name → `library(view, key, '', filter, sort)` → type in the search field → `library(..., query)` → quality chip → `library(..., filter)` → sort header → `library(..., sort)`. Command: **none for every step**. |
| J2 | Look at one track | select a row → `track(id)` (+ `todo('all', true)` for decisions, `spectrum` for the picture) → read quality, source, playlists, place, upgrade. Command: **none** (`rekordbox preview <key>` / `convert <key> --dry-run` for parts). |
| J3 | Listen through a list | ▶ on a cover → `listen()` builds the queue from the shown rows → `track(id)` per item for `audio_url` → the window's `<audio>`; foot bar, shuffle, hide, stop. **[P] [W]**: the agent can only name the file (`path`) and tell the user. |
| J4 | Show a file / open the song's page | details "Show in Finder" → `show_in_finder`; row menu "Open in {Service}" → `open_external`; folder row → `reveal`. **[P]** (opens the user's Finder/browser). Command: none. |
| J5 | Organise the sidebar | right-click → Add to favourites → `set_favourites([...])`; drag to reorder → `set_favourites`; Hide/Show crate → `set_crate_shown`; Settings All/None → `set_crates_shown`. Command: **none**. Drag and drop is **[P]** (the same result is one `set_favourites` call). |
| J6 | Add a folder of own music | Settings → Add folder… → `pick_folder` **[P]** (Mac dialog; the agent would pass a path) → `check_import_folder(path)` → `add_watched_folder(path)` (job `import`, `ImportProgress` phases scan/facts/tags/sound/link) → on Stop: `stop()`; later `start_import()` (Continue import); `watched_folders()` shows `waiting`, `unreadable`. Import starts by itself when the window opens with files waiting (`_auto_import`). Command: **none**. |
| J7 | Stop watching a folder | Remove → `removal_preview(id)` → confirm → `remove_watched_folder(id)` (job `folders`) → `watched_folders()`. Command: **none**. |
| J8 | Answer the import's questions | To-do "Is this the same song?" → `answer_same_song(song_key, own_key, same)`; Duplicates: pick the file that stays → `supersede_duplicate(group, file_id, paths)` for each file that goes (one at a time, group id recomputed), or **Keep both/all** → `keep_duplicates(group, paths)`. Hosted by Library details for a track in a group (`DuplicateFlow`). Command: **none**; questions have no read. |
| J9 | Tidy up files | Playlists → Tidy up files → `tidy_preview()` → untick / "Put these in playlist order too" → `tidy_up([[file_id, from_path], …])` (job `tidy`, `MovesProgress`) → result (`moved`, `skipped[]`, `stopped`) → optional Undo. Command: **none**; only a count in the sync output (`cli.py:100`). |
| J10 | Undo moves | Playlists → Recent moves → `move_batches()` → Undo → `undo_preview(id)` → `undo_moves(id)` (job, `MovesProgress`) → result. Command: **none** (`batch undo` is the AIFF namespace). |
| J11 | Save a playlist change that moves files / rename a folder on disk | edit lines → `preview_playlist_change(lines)` (rename offers, retargeted files) → Save: "Save and move the files" / "Save, leave files where they are" → `save_playlists(lines, version, {choice, renames, moves})` (job, `MovesProgress`, result `{version, batches[]}`) → Undo from J10. Command: **none** (hand-editing `playlists.txt` leaves the files and records unmoved). |
| J12 | Convert one file to AIFF / give it its clean name | select a track → `track(id).aiff` (card: now / becomes / space, `why_not`) → `rekordbox_status()` → Convert → `convert([id], 'library')` or `rename([id])` (job `aiff_batch`, `BatchProgress`) → check card: **[P] reload tags / Rebuild the stick in rekordbox**, then Done → `rekordbox_checked([id])`, or Undo → `undo_upgrade([id])`. Commands: `convert <key>` / `rename <key>`, `rekordbox checked <key>`, `upgrade undo <key>`. **[P]** quit rekordbox before; the check steps in rekordbox. |
| J13 | Make AIFF for a selection or a whole view | ⌘-click / ⇧-click / ⌘A → `aiff_plan({tracks})`; header Make AIFF… → `aiff_plan({lossless, view, key})` → Make k files AIFF → `convert(ids)` / `make_aiff(scope)` (job `aiff_batch`) → Stop → `stop()`; "Resume · k left" → `batch_resume(id)`; the batch's check row → `rekordbox_checked(ids)`; "Undo all" → `undo_upgrade(ids)` (the UI) or `batch_undo(id)` (no UI caller). Commands: `convert <keys>` / `convert --all lossless [--in …]` (+`--dry-run`), `batch list/show/resume/undo`, `rekordbox checked --batch`. ⌘A on a searched/filtered view: **no command** (D15). **[P]** quit rekordbox; rekordbox side checks. |
| J14 | Replace a track with its better version from the Library | details decision `upgrade` → pick Same track / New track (D8) → Replace → `upgrade([id], 'swap'\|'add_new')`; Discard (asks) → `upgrade([id], 'discard')`; check card → Done / Undo as J12. Commands: `upgrade apply <key> --way same-track\|new-track`, `upgrade discard`, `upgrade undo`, `rekordbox checked`. **[P]** quit rekordbox; New track needs a Relocate in rekordbox. |
| J15 | Keep the index current / read playlists | window open or back after >60 s → `rescan_library()` (job `scan`); first read `refresh(true)` (scan + auto import); header "Read playlists" for a never-read playlist → `refresh()`; Stop → `stop_refresh()`. Commands: none for the scan; the sync does both (`run.py:238`). |
| J16 | Clear out `Superseded/` | The app never deletes (invariant). The user deletes by hand in Finder once rekordbox no longer uses a file (README "Folders"). There is no screen, read or action for Superseded. **[P]** (deleting). Gap: no read of what sits there and what rekordbox still points at (`rekordbox restore` prints `missing_after` only). |

---

## 5. Today's commands in this area, judged for agents

Commands: `convert`, `rename` (`convert_cmd.py`), `upgrade list|apply|discard|undo`, `batch list|show|resume|undo`,
`rekordbox status|preview|checked|backups|restore` (`batch_cmd.py`, `rekordbox_cmd.py`, `cli.py`), `settings
auto-upgrade`, the sync `--dry-run --json`, plus the interactive `setup` and `upgrades`.

**Discoverability.** `discjockey --help` lists commands with one-line descriptions (`cli.py:56-69`), nothing machine
readable (no `commands --json`, no schema). The app binary's list of command words is a second copy
(`app_main.py:25`, pinned by a test). `convert --help` says keys come "as the library's JSON prints them"
(`convert_cmd.py:82`; `cli.py:85` the same) but no command prints a library JSON (finding 1). How an agent finds the
music folder and support folder is only the env/`config.json` logic of `library.resolve_paths`; no `where` command;
JSON paths are relative to the music folder for `Library/` files and absolute for watched-folder files.

**Naming a song or a file.** By key only (`convert <key>…`, `upgrade apply <key>…`, `rekordbox checked <key>…`,
`rekordbox preview <key>`). `rekordbox preview --path FILE` takes any file, `convert` does not. No lookup by artist
and title or by path; keys come from `upgrade list` or `batch show` only. Tidy-up needs integer `file_id` plus the
`from_path` the preview showed (`file_moves`, `api.py:2694`); duplicates need a group id (`dup:12-15`) plus the group's
`paths`; same song needs `song_key` and `own_key`; folders have an integer id (`removal_preview`, `remove_watched_folder`)
and a path (`reveal`, `set_crate_shown`); favourites use `playlist:<ref>` / `folder:<path>`; AIFF batches an integer.

**Argument style, not uniform.** `convert --all {lossless,cdj}` takes a choice (`convert_cmd.py:94`), `rename --all`
is a flag (`:99`); `--in playlist:<name>|folder:<path>|unlisted` (`:83,106-115`) is a prefixed string, a playlist
named by its name, a folder by its path; `upgrade apply --way same-track|new-track` (`batch_cmd.py:83`) uses
hyphens while the engine says `same_track`/`add_new` (`WAYS`, `:47`); `rekordbox checked --batch ID`, `batch resume <id>`
positional; `--dry-run` is `default=argparse.SUPPRESS` on `upgrade apply`/`convert`/`rename` (`batch_cmd.py:84`,
`convert_cmd.py:85`) and absent on `upgrade discard`/`undo`/`batch undo`/`rekordbox checked`; `--yes` exists only on
the sync and `rekordbox restore`.

**JSON shape.** Success `{"ok": true, …}`, failure `{"ok": false, "kind", "message", "reason"?, …}`; a finished batch
with skips is still `ok: true` and exits 1 (CONTRIBUTING). Naming differs from the bridge: console `track` vs hub
`track_id`; `upgrade list` rows vs hub `library` rows have different fields (`artist`, `title`, `folder`, `file`,
`parked`, `now`, `new`); the dry run is `{"ok", "dry_run", "plan"}` for `convert`/`rename` but
`{"ok","dry_run","way","total","planned","skipped","space","rekordbox"}` for `upgrade apply` (`batch_cmd.py:484`);
`rekordbox status`/`preview` print a different object per command; `settings auto-upgrade` prints `{"ok","auto_upgrade"}`.
`--json` exists on each command separately (`batch_cmd.py:67`, `convert_cmd.py:86`, `rekordbox_cmd`, `cli.py:59` for the
sync only) and `--json` on `setup`/`update`/`upgrades`/`hub` is a usage error (`cli.py:99`).

**Exit codes differ by command.** `batch_cmd.py:41`: `OK 0, FAILED 1, NO_LIBRARY 2, BUSY 3, REKORDBOX_OPEN 4, STOPPED 5`;
`convert`/`rename` reuse them. The sync: 0, 1, 2, 3, **130** for stopped (`cli.py:9`), no 4. `settings`: own constants
0/1/2/3 (`settings_cmd.py:19`). `rekordbox status|preview`: 0/1/2 only, no 3 (no lock). An argparse usage error is
also exit 2, the same as "no music folder", and prints text on stderr even with `--json` (`check_args`:
`batch_cmd.py:113-121`, `convert_cmd.py:104-107`, `cli.py:99-101`); CONTRIBUTING says so (lines 90-93).

**Prompts.** Never in the new commands; the sync asks `Proceed? [y/N]` unless `--yes` (`cli.py:242`); with `--json`
and no `--yes`/`--dry-run` it refuses `needs_yes` (`cli.py:299`); `setup` and `upgrades` still prompt (`input()`:
`setup_cmd.py:69,128,133`, `upgrades_cmd.py:151`). Confirmations the window asks are **not** asked by the console and
have no flag: Discard (`flows.svelte.ts:55`), undo (`:72`, `:222`), remove folder; `upgrade discard` and `batch undo`
run at once, `rekordbox restore` needs `--yes` (`batch_cmd.py:57,761`).

**Dry run.** Present for `convert`/`rename`/`upgrade apply` (the plan = the window's panel); absent for `upgrade
discard`, `upgrade undo`, `batch undo`, `rekordbox checked`. A `convert --dry-run` may still take the library lock and
write (`importer.fill_facts`) when own files have no stored facts (`convert_cmd.py:218-232`): exit 3 if the window
holds the lock. Tidy-up has a dry run in the hub (`tidy_preview`) and none in the console.

**Long runs and progress.** Progress is human lines on stderr (`batch_cmd._progress` :191, `convert_cmd._progress`
"Converting 3 of 52: …"); with `--json` stdout holds one final object. No JSON-lines events, no job id to poll, no
`batch` "follow". `batch list`/`show` read the db without the lock, so a second process can poll `state`/`done` of a
batch; nothing documents it as the way. A batch can only be stopped by Ctrl-C of the process that runs it
(`batch_cmd._interruptible` :166: first press stops after the track, second 1 s later at once); `stop()` of the hub
cannot reach a console run, and a console cannot stop a window job. Exit 4/5 leave a resumable batch.

**While the app is open.** The hub holds the library lock only while a job runs; a console write command then exits 3
`busy` with `LOCK_HELD` text (`batch_cmd.py:44,155`); the window shows the console's run through `ConsoleBusy` polled
every 3 s (`jobs.py:566`). Reads (`upgrade list`, `batch list|show`, `rekordbox status`) take no lock and work while the
window runs or is closed; they read the records as the last scan left them (no `rescan` command). Two `convert`
processes at once: the second exits 3.

**One / several / all.** Songs: a list of keys or `--all` (`upgrade apply --all` = Upgrade all; `convert --all
lossless|cdj`; `rename --all`); a view by `--in`; a batch by `--batch` (`rekordbox checked`); nothing for "the rows
that match this search/filter" (⌘A), for "everything the tidy-up ticks", or for "all favourites/crates". `--all cdj`
excludes songs in a listed duplicate group (hub `_decided_now`; console `_held` `convert_cmd.py:121`), but cannot
exclude songs with an open same-song question: that list is not on disk (docstring `_held`).

**Not reachable from the app binary.** `Discjockey.app/Contents/MacOS/Discjockey --yes --json` (the plain sync) opens
the window (`app_main.py:36`); only the listed command words run in the console.

**Hub/console differences to keep in mind:** the console never scans before reading (`upgrade list`,
`batch show`); the hub always scans at window start; the hub's single-track writes check `_shown` (finding 5); the
hub's `track()` refuses a song that was only just read; the console finishes interrupted steps first
(`library.recover_pending`) before every write command, as the hub does at job start.

---

## 6. Coverage list

Bridge methods covered by this audit, one per line.

```
library
track
todo
sidebar
watched_folders
removal_preview
check_import_folder
aiff_plan
tidy_preview
move_batches
undo_preview
rekordbox_status
job_status
spectrum
media_url
set_favourites
set_crate_shown
set_crates_shown
rescan_library
show_in_finder
reveal
open_external
select
refresh
stop_refresh
stop
add_watched_folder
start_import
remove_watched_folder
answer_same_song
keep_duplicates
supersede_duplicate
tidy_up
undo_moves
preview_playlist_change
save_playlists
convert
rename
make_aiff
batch_resume
batch_undo
undo_upgrade
upgrade
rekordbox_checked
hide
```

Counts: 44 methods covered; with no command at all: 31 (`library track todo(partial) sidebar watched_folders
removal_preview check_import_folder tidy_preview move_batches undo_preview job_status spectrum media_url
set_favourites set_crate_shown set_crates_shown rescan_library show_in_finder reveal open_external select
add_watched_folder start_import remove_watched_folder answer_same_song keep_duplicates supersede_duplicate tidy_up
undo_moves preview_playlist_change save_playlists hide`); UI-side decisions in §2: 37 (D1–D37), of which 15 decide
something an agent needs (D1, D4, D5, D6, D7, D8, D9, D10, D13, D15, D21, D24, D26, D28, D29, D31, D32); journeys in §4: 16.
