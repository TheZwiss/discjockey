# CLI audit supplement A (issue 39, step 1b)

UI files no audit of `docs/2026-11-14-cli-audit-{library,todo,app}.md` names: Library table and details, row and
track components, decision cards and feet, players, watched folders, import. Evidence for the designer, not a design.
"Command today" = what `CONTRIBUTING.md` › "Commands for scripts and agents" lists: `sync [--json]`,
`rekordbox status|preview|checked|backups|restore`, `upgrade list|apply|discard|undo`, `batch list|show|resume|undo`,
`convert`, `rename`, `settings auto-upgrade`. There is no console read of the library, playlists, folders or a
track's details (see library audit finding 1).

### hub-ui/src/pages/library/LibraryTable.svelte

The Library page's track table. Caller: `hub-ui/src/pages/library/Page.svelte`. Row data = `library.rows[]` /
`library.also[]` (bridge `library()`), all of it `LibraryRow` (`TrackRow` + `sound_checked, file_state, wait,
next_try, position, place, subfolder, playlists, track_link`). The model functions live in `libraryModel.ts`.

**1. Information shown** (command today: **none** for every row unless noted; no command reads the library)

| Shown | Source | Command |
|---|---|---|
| Column head: `#` (playlist only), Track, Artist, Folder, Subfolder, Playlist, Length, Quality; sort arrow on the sorted head; only Track/Artist/Length/Quality (+`#` in a playlist, +Folder in All tracks / Not in a playlist) sort, Subfolder and Playlist are plain names | `LABEL`; `libraryModel:sortColumns`, `sortState`; engine `views.SORTS` | none |
| Which optional columns exist for the table's kind and which are visible at the measured width (Folder/Subfolder, Playlist, Length) | `libraryModel:columnsAt`, `columnThresholds`; `playlistColumn` / `artistColumn` flags come from the page | none (layout; a command prints all fields) |
| ⓘ "Keys and clicks" text (sort, select, ⌘-click, ⇧-click, ⌘A, Esc, double-click/Enter/cover plays, ⌘I, right-click menu) | literal in this file | n/a (window help; an agent needs the command list instead) |
| `#` position in a playlist, in playlist order | `rows[].position` | none |
| Cover; dashed empty cover for a song with no file; playing/hover state | `rows[].cover_url`, `file_state === 'no_file'`; `stores/player` (`playing`) | none |
| Title, with tooltip = "Artist - Title" (+ "Not in any playlist any more" for a dimmed leftover) | `rows[].title/artist`; `libraryModel:rowTitleTip` | none |
| Note "in {place}" after the title (playlist view, file outside the playlist's own folder, only with a file) | `rows[].place`; `libraryModel:titleNote` | none |
| Artist | `rows[].artist` | none |
| Length m:ss, "–" for a song without file and length | `rows[].duration_s`; `format:duration`, this file | none |
| Folder cell (where the file sits, middle-cut with "›"), "–" if none | `rows[].place`; `libraryModel:folderCell` | none |
| Subfolder cell (crate / folders below), "–" if none | `rows[].subfolder`; `libraryModel:subfolderCell` | none |
| Playlist badge (first playlist in playlists.txt order) with "+n" and tooltip "In A, B, C"; "–" for a song in none | `rows[].playlists`; `libraryModel:playlistCell` | none |
| Quality badge: class colour, label ("LOSSLESS", "FAKE · 16.0 kHz", ...), "Not checked" (muted, tooltip "The sound hasn't been checked yet") when the sound is not judged; tooltip "Show details" | `rows[].quality/quality_label/sound_checked`; engine `views.quality_label` | none |
| For a song without a file, in the same cell: red **NOT FOUND** badge (tooltip "Nothing usable found yet, tried again at the next sync / next try in N days. To-do has other ways to get it." or "... You hid it from To-do.") or muted **Waiting** (tip "Downloads at the next sync") or **Switched off** (tip "Switched off: its files stay, nothing new downloads") | `rows[].wait` (`not_found`/`waiting`), `next_try`, `hidden`; `off` = page's `library.enabled === false`; `libraryModel:waitWords`, `notFoundTip`, `nextTryLine`, `localDay` | none |
| Away tag (warn mark + "Offline" / "Folder not found"; tooltip "Offline: connect the drive" / "Folder not found") replaces the quality badge when the file's drive or watched folder is away | `rows[].file_state` (`offline`/`folder_missing`); `format:rowAway`, `FILE_STATE_TAG/WORDS` | none |
| "UPGRADE" badge in the last slot | `rows[].upgrade_ready` | `upgrade list` lists the parked ones as To-do shows them (not the same filter as every row's flag) |
| Dim of cover and title: song left every playlist and is not own, or file not `here` | `libraryModel:rowDim`, `rowOff` | none |
| "Also in this folder" section head, count, hint; "empty line" above it ("This playlist is empty." etc.) | `library.also`, `alsoHint` / `emptyLine` from page (`libraryModel:alsoHint`, `pageEmpty`) | none |
| Skeleton (8 lines) while loading with no rows | UI state | n/a |
| Selected rows (orange wash), multi-select | `stores/selection`, `selectionModel` | n/a (window state) |
| Context menu items in order: Show details; Show in Finder (file is `here`); "Open in {Service}" (`track_link.label`); Open in to-do (when on to-do) | `libraryModel:rowMenu`, `rowInTodo`, `playable`, `rows[].track_link` | none |

**2. Decisions the file takes itself** (engine has it? where)

- `libraryModel:rowInTodo` / `inTodo`: a row is "on the to-do list" when (no file) `wait === 'not_found' && !hidden`,
  else `in_playlists && !hidden && (status !== 'lossless' || upgrade_ready)`. Engine: `views.todo`/`_group` decide
  the real list; this is a second copy that the library audit already notes diverges (D6). A command must use the
  engine's.
- `libraryModel:rowDim` / `rowOff`: dim = `!in_playlists && !own` or `file_state !== 'here'`. Engine: only the input fields.
- `libraryModel:playable`: file plays iff `file_state === 'here'` (also decides who gets Show in Finder, who the
  player queue holds, who Enter/double-click plays). Engine: `views.file_state` (`:869`) gives the state.
- `libraryModel:waitWords` + `notFoundTip` + `nextTryLine`: the words for Waiting / Switched off / NOT FOUND and the
  "next try in N days" arithmetic against the local day. Engine: `views.next_due` (`:574`) gives the day, the words
  are UI only.
- `libraryModel:titleNote`: "in {place}" only in a playlist view, with `place` and a file. UI only.
- `libraryModel:folderCell/subfolderCell/playlistCell`: "–" for empty, first playlist + "+n". UI only.
- `libraryModel:columnsAt`, `gridColumns`, `tableLines`, `windowSlice`: layout only.
- `libraryModel:tableScope`, `selectAllRows`, `moveSelection`, `selectionModel.click`: multi-select rules. A song with
  no file cannot join a selection; `⌘A` = all rows with a file on screen after filter and search. This is the
  "selection" that the AIFF panel and `convert <keys>` act on; the engine's `aiff_plan` decides what each file may do.
- `libraryModel:sortColumns` / `isSort`: which sorts exist per view (engine `views.SORTS` is the truth; `order` is a
  playlist's; Folder only in All/Not in a playlist). Defaults: playlist `order`, others `artist`. Saved per view kind
  in the browser (`library.sort.<view>`).
- Windowing above 300 lines, scroll to the selected row: layout.

**3. Actions** (control · what it ends in)

- Header click · sort: `onsort` -> page reloads `library(sort=...)` (no write).
- Click / ↑ ↓ / ⌘-click / ⇧-click / ⌘A / Esc · selection, opens details through the page (`onselect`); no bridge call here.
- Click on a quality badge · selects the row and opens the details (`ondetails`).
- Enter, double-click, the cover · play (`onplay` -> `stores/player` queue; audio is served by `audio_url`; no bridge write).
- Right-click menu: Show details (`ondetails`); Show in Finder (`onfinder` -> `api.show_in_finder` via the page); Open in {Service} (`api.open_external(url)`); Open in to-do (`ontodo` -> navigates to `/todo?track=`).

### hub-ui/src/pages/library/TrackDetails.svelte

The Library inspector for one selected track (`Panel`). Caller: `pages/library/Page.svelte`. Data: bridge `track(track_id)`
(`TrackDetail`), the to-do item for the same track (`decision`, `decisionFor` over `todo()`), `spectrum(track_id, which)`
for the pictures, the selected row for `pending`. The decision cards themselves are in the files `CheckCards`, `DuplicateChoice`,
`UpgradeCards`, `AiffCard` and the feet (sections below).

**1. Information shown** (command today: **none** unless noted)

| Shown | Source | Command |
|---|---|---|
| Track card (`TrackHead`: cover, name, "Artist · length · place", quality badge + words, "Open in {Service}") | `track.*`; see `TrackHead.svelte` section | none |
| Place line "in Hardtechno › 2019" (empty for none); "not downloaded yet" for a song without a file | `track.place`; `libraryModel:placeLine`, `NO_FILE_PLACE` | none |
| Quality words: "verified lossless", "lossy, hard to hear", "lossy, audible", "fake lossless", "no file yet", "sound not checked yet" | `track.quality/quality_label/sound_checked`; `format:qualityWords` | none |
| Which card follows the track card: AIFF card (Convert / clean name), rekordbox check, "Which file stays?", upgrade Now/New cards, else cutoff StatCard | `decision` (`decisionFor`), `track.aiff`, `track.upgrade`; `aiffShown`, `upgrading` here | none for the choice; the contents see the card sections |
| Cutoff StatCard: "{n.n} kHz", "where the highs end, lossless reaches about 22 kHz" / "no clear edge in the highs" / "where the highs end, a lossy file inside the {FLAC/WAV}"; not shown for lossless, no file, or a sound not checked | `track.cutoff_hz/status/path/sound_checked`; `format:cutoffStat` | none |
| Spectrum picture and waveform (64 px), "no file", away reason in its place, loading, error | `spectrum()` -> `spectrum.matrix/waveform/cutoff_hz` (`discjockey/spectrum.py`); `away` words | none |
| Current file card: Format ("FLAC · 24-bit", "Opus · 135 kbps") | `track.format_line` | none (`rekordbox preview` prints codec/rate/bits only) |
| Source: name ("YouTube Music", "bought", "your own file"), link to the page when it is not the song's own, " · {source format}", and a second line: "exact Qobuz track" / "found by ISRC" / "found by name" / "picked by you" / "the playlist's own upload" | `track.source_full/source_name/source_url/source_format_line/source_how`; `copy:sourceHowWords`, `libraryModel:shortUrl` | none |
| Playlists: every playlist by name, "–" for none, hidden while not read | `track.playlists/in_playlists`; `libraryModel:playlistsLine` | none |
| Added "12 Mar 2026" ("–" if none) | `track.added`; `format:dateShort` | none |
| File: the file's name (middle-cut) | `track.path`; `libraryModel:fileName` | none (`rekordbox preview` prints the whole path) |
| "Show in Finder" link (not for a file that is away) | `track.file_state` | none |
| Away words: "Offline: connect the drive" / "Folder not found" / "This file isn't there any more." | `track.file_state`; `format:fileAwayWords` | none |
| Song without a file (`pending`): head (dashed cover, "Artist · length · not downloaded yet", NOT FOUND or Waiting / Switched off), one note: "It downloads at the next sync: from Qobuz when it has it, else from the best other source." / "Its playlist is switched off, so nothing new downloads. Switch it on in Playlists to get this song." / "No source had a usable copy when the sync looked. Qobuz looks again {at the next sync / on 12 Mar}. {To-do has links to buy it or get it another way. / You hid it from To-do.}" | selected `LibraryRow` (`wait`, `hidden`), `pending.next` = `track.next_qobuz_check`, `pending.off` = playlist switched off; `libraryModel:noFileNote` | none |
| Gone: "This track isn't here any more." / failed: ProblemCard (kind + engine message + Retry) / skeleton | `track()` answer `changed`/`refused`; UI state | none |
| Foot: which button(s): upgrade (Replace / Discard), check (Done / Undo), duplicate (Keep), AIFF (Convert or clean name), Open in to-do (before or after the AIFF button), none | `libraryModel:footAction` | the actions have commands; **the choice of buttons is none** |

**2. Decisions the file takes itself**

- `aiffShown(t.aiff, decision, away)` (`lib/decisions`): AIFF card only without a decision and for a file that is there. Engine: `views.track` builds `track.aiff` (`aiff_plan`/`eligible.aiff_action`); the "no decision" part is UI only (the to-do item decides).
- `upgrading = decision.kind === 'upgrade' && !!t.upgrade`: Now/New cards replace the cutoff card, spectrum and player.
- `libraryModel:footAction`: decision wins; else `inTodo(t)` (in a playlist, not hidden, not lossless or upgrade ready) -> Open in to-do; with an AIFF card: `aiff` only when not on to-do or the file is CDJ-bad (`aiff.cdj`); else filled AIFF button first (`aiff_todo`), outline AIFF second (`todo_aiff`). UI only; engine has `views.todo` for the to-do membership.
- `canSwap(t.upgrade)` / `upgradeWays(...)` / `UpFlow.way(...)`: which "In rekordbox" choices exist (see `UpgradeCards`).
- `format:cutoffStat`: when the cutoff card appears and its label by status and format. UI only (engine gives `cutoff_hz`, `status`).
- `libraryModel:noFileNote`: which of three notes, the `dayMonth` of Qobuz's next check. Engine gives `next_qobuz_check` (`views.track`) and `next_due`.
- `hasFile = status !== 'missing'`: Current file card exists only then.
- `aiffFlow.attach()`: asks `rekordbox_status()` on selection and on window focus while the AIFF card shows.

**3. Actions**

- Show in Finder -> `onfinder` -> `show_in_finder(track_id, 'current')`.
- Open in to-do (foot; for a not-found song only when not hidden) -> navigates to `/todo?track=`.
- Play (MiniPlayer ▶) -> `onlisten` (starts the folder's queue from this track).
- Retry (ProblemCard) -> `onretry` (reloads `track()`).
- Foot buttons are hosted: Replace / Discard (`upgrade`, `upgrade_all`-style via `UpgradeFoot`), Done, Undo (`rekordbox_checked`, `undo_upgrade`), Keep... (`keep_duplicates`, `supersede_duplicate`), Convert / clean name (`convert`, `rename`); see the feet's sections.
- The "In rekordbox" choice (`upFlow.picked`) and the duplicate's kept files (`dupFlow`) are window state.

### hub-ui/src/lib/components/ListRow.svelte

Generic: shows its caller's data (lead / name / sub / optional / trailing snippets). Callers: `lib/decisions/AiffBatchPanel`,
`BatchCheckCards`, `UpgradeSelection`, `lib/components/UnreadableList`, `WatchedFolderList`, `pages/settings/Page`,
`pages/playlists/{ChangePanel,TidyList,Row,MovesPanel}`, `pages/setup/StepPlaylists`, `pages/limits/Page`, `pages/todo/Page`,
`pages/dashboard/{Page,RunRow}`, `pages/sync/plan/{PlanRows,PlanFolds,UpToDatePanel,RunPanel}`, `pages/sync/{RunList,EndScreen}`.
Own rules only (no data): the optional column shows at a list width >= 680 px (layout); `off` dims name and lead; `selected` + `pick`
marks the chosen row; `multi` toggles. Information shown: none of its own. Actions: its `onclick` goes to the caller. No decision a command needs.

### hub-ui/src/lib/decisions/BatchCheckCards.svelte

To-do's panel while one **batch item** ("3 tracks upgraded") or two or more **rekordbox checks** are selected. Caller:
`pages/todo/Page.svelte`. Data: the `TodoItem`s with `check` (`todo()`; a batch item has `batch{id,size,started,started_by,kind,tracks}`).
Words are built in `lib/decisions/decisionModel.ts`; the engine's `views.check_view` gives only `reason, since, match,
offset_ms, moved, aligned, reload_tag, batch, rekordbox{entries,kept}, text (report.check_text), old_path, old_name`.

**1. Information shown** (command today: `batch show <id>` gives the batch row + `results` per track `{track, action, state, reason, message, path, rekordbox:{entries, kept}}`; `rekordbox checked` acts; no command gives the words below)

| Shown | Source | Command |
|---|---|---|
| Card "In rekordbox" (yellow, "waits for the user"), summary "same track, cues kept" / "same tracks, cues kept" | `decisionModel:batchCheckCard` | none (the hint that rekordbox still has to be told is only implied by `batch show`'s `rekordbox` and `rekordbox checked`) |
| Lead sentence for a Convert-only batch: "Your files are now AIFFs with clean names and tags, and your rekordbox tracks play them with their cues, playlists and history. The sound is the same."; for one track, that check's own `text` | `decisionModel:CONVERTED_BATCH_LEAD`; `check.text` = `report.check_text` | none |
| Numbered steps, each only when it applies: (1) "This one shows as missing / These show as missing: Auto Relocate finds ... by name, cues and all" + the track names; (2) "In rekordbox's Collection, select this track / these tracks (command-click each), right-click > Reload Tag, don't select all: it replaces every name you changed in rekordbox" + the track names; (3) "Analyse it / them again, so the waveform shows the full sound (lock the beatgrid first if you set it by hand)"; (4) "On a USB stick? The stick still plays the old file(s). Rebuild the stick in rekordbox before your next gig" | `batchCheckCard`; `check.reload_tag`, `check.moved`, `check.reason`, `check.rekordbox.entries` | none |
| List title: "Upgraded" / "Made AIFF" / "Clean names" / "Changed" (mix); several checks: "{N} checks selected"; summary "n" or "n track(s)"; hint "today" / "on 31 Oct" | `decisionModel:batchListTitle`, `checksTitle`, `tracksSummary`, `sinceText`; `batch.started`, `check.since` | `batch list` / `batch show` give `kind`, `started`, `total` (no title words) |
| One row per track: cover, name ("Artist – Title"), sub = the new file's name (batch) or the to-do row's own line `detail` (several checks), notes: "Kept your own title and artist in rekordbox" (from `check.rekordbox.kept`), "Not in your rekordbox collection, so there was nothing to keep there" (repointed/converted/renamed and not in rekordbox) | `decisionModel:checkRow`, `keptLine`, `NOT_IN_REKORDBOX`, `inRekordbox`; `item.path`, `item.detail` | `batch show` gives `path`, `rekordbox.kept`; `upgrade list`/To-do `detail` words: none |
| Row warning after a refused undo ("Not undone" or the engine's message) in the notice colour | `flow.problem.rows` (`undoProblem`, from `undo_upgrade` result `results[].message`) | `batch undo` / `upgrade undo` print `results[].message` |
| "Undo this one" button on a row while `can_undo` | `item.can_undo` (engine, `views.todo`) | `upgrade undo <track>` acts; "can_undo" itself: none |

**2. Decisions the file takes itself** (all in `decisionModel.ts`)

- `inRekordbox(check)`: a check is "in rekordbox" iff `check.rekordbox.entries > 0`, or for an old record without it `reason === 'swapped'`. Engine: only the stored `rekordbox` record; the rule is UI-only. A command needs the same rule (`batch show`'s `rekordbox` is null/entries today).
- `isOwnCheck`: `converted` and `renamed` checks need no Reload Tag / analyse step; `renamed` needs nothing at all. UI only.
- `batchCheckCard`: which steps show and for which tracks (Reload Tag only for tracks with `reload_tag`; Auto Relocate only for `swapped && moved`; analyse only for upgrades; USB for every non-rename in rekordbox), singular/plural words, the bold parts. UI only; the same instruction exists as one sentence per check in `report.check_text` (`report.py:52-55`) that the engine and sync report already use.
- `batchListTitle`, `checksTitle`, `tracksSummary`: counts and kind words. UI only.
- `checkTracks(items)`: a batch item stands for its tracks; several checks selected count tracks, the title counts list items. UI only.
- `focusAfterRowGone`: focus only.

**3. Actions**

- Done for all (foot) -> `rekordbox_checked(track_ids)` (see `BatchCheckFoot`).
- Undo all / Undo n (foot) -> `undo_upgrade(track_ids)`.
- "Undo this one" per row -> `undo_upgrade([track_id])` after a confirm (`undoAsk`: question and body words, `decisionModel:undoAsk`).

### hub-ui/src/lib/decisions/BatchCheckFoot.svelte

Foot of the card above. Caller: `lib/decisions/BatchCheckCards.svelte` (`fromSync` = `isAutoBatch(batch.started_by)`).

**1. Information shown** (command today: none for the words)

| Shown | Source | Command |
|---|---|---|
| Filled button "Done, checked in rekordbox" (or "Done" when every check is a Convert or clean name of a file rekordbox doesn't hold) | `decisionModel:doneLabel`, `isOwnCheck`, `inRekordbox` | none |
| Undo button: "Undo all {n}" when every track can go, else "Undo {n}", "Undo all from this sync" for the sync's batch; tooltip by kind ("Puts your old files back; the new versions wait again" / "Puts your old files back" / "Puts your old names back" / mixes) | `decisionModel:undoFoot`, `undoAllLabel`, `UNDO_SYNC_LABEL`, `undoTitle`; `batch.started_by === 'auto_upgrade'` | none |
| Muted "{k} can't be undone" | `undoFoot` (`!can_undo` count) | none |
| NoteCard after an undo: "{track} not undone", "{k} not undone: each row says why", or the engine's message (rekordbox open ...), tone warn or problem | `decisionModel:undoProblem`, `undoProblemLine`; from `undo_upgrade` job result | `batch undo` / `upgrade undo` give per-track state/reason/message; `rekordbox_open` is exit 4 |
| Busy states ("Undoing") | `flow.busy` | n/a |

**2. Decisions the file takes itself**

- `undoFoot`: which tracks are offered for undo (`can_undo` and not refused in this pick), the button label, the "can't be undone" count. Engine: `can_undo` comes from `views.todo` (the check's undo record still valid); the label is UI.
- `doneLabel`: see above. UI only.
- `undoAsk` / `undoManyConfirm` (confirm dialog before an undo): title/body/confirm words by kind (`converted`, `renamed`, upgrade): UI only. Nothing in a command asks (a command never prompts); the words differ from `undo`'s.

**3. Actions**

- Done -> `rekordbox_checked(track_ids)` (command: `rekordbox checked <track>… | --batch <id>`).
- Undo -> `undo_upgrade(track_ids)` after a confirm (command: `upgrade undo <track>…`, `batch undo <id>`).

### hub-ui/src/lib/components/WatchedFolderList.svelte

Generic list that shows its caller's data (`WatchedFolderRow[]`, bridge `watched_folders()`). Callers:
`pages/settings/FoldersPanel.svelte`, `pages/setup/StepExisting.svelte` (and `lib/dev/Gallery`). The words come from
`lib/components/watchedFoldersModel.ts`; the library audit's "Watched folders and import" table lists the same items.

**1. Information shown** (command today: **none**: no command lists watched folders or import state)

| Shown | Source | Command |
|---|---|---|
| Row per folder, in the engine's order (Library first) | `watched_folders.folders[]` | none |
| Name (+ short path in a Remove label when another folder has the same name) | `folders[].name/path`; `watchedFoldersModel:folderLabel`, `sharesName`, `musicFolder:shortPath` | none |
| State line: "Always watched" (Library) / "Online" / "Offline: connect the drive" / "Folder not found: moved, renamed or deleted? Put it back or remove it here." / "Checking for new files" / "Importing" / "1 file waiting" / "Importing · n waiting" | `folders[].kind/state/waiting`; `watchedFoldersModel:folderLine`; `format:OFFLINE_WORDS`, `FOLDER_NOT_FOUND_LINE` | none |
| Mark: tick (online/library), warn "!" (offline or missing), spinner (scanning/importing) | `watchedFoldersModel:folderMark` | none |
| The folder's path, for import folders only (one line; the parents give way, the drive's name comes first as "Drive › Folder"); full path as tooltip | `folders[].path`; `watchedFoldersModel:fitPath`, `pathParts` (layout), `shortPath` (home as "~") | none |
| File count right-aligned (1,240), tooltip "1,240 files" | `folders[].files` | none |
| Remove x on import folders (tooltip why it is off while another change runs: the caller's `removeOff`) | `kind === 'import'`; caller flow | none |
| Picked row (Settings; an import folder with crates) | `folders[].crates.length`, `picked` | none |
| Skeleton while loading | UI state | n/a |

**2. Decisions the file takes itself**

- `watchedFoldersModel:folderLine` and `folderMark`: the state words and the mark from `state` (and `waiting`). Engine gives `state`; words UI only.
- `pickable(f)`: only an import folder with crates is a row to pick. Engine has `crates`.
- Remove is shown for import folders only (the Library cannot be removed). Engine rule: `watched` folder of kind `library` is fixed.
- `sharesName`: names that differ only by case count as the same (the label then carries the short path).

**3. Actions**

- Click on a pickable row -> `onpick` (the caller shows the crate switches; no bridge call here).
- x Remove -> `onremove(f)` -> the caller asks `removal_preview(folder_id)` then `remove_watched_folder(folder_id)` (job).

### hub-ui/src/lib/decisions/UpgradeCards.svelte

The upgrade decision's two cards (comparison; "In rekordbox"). Callers: `pages/library/TrackDetails.svelte`, `pages/todo/Details.svelte`.
Data: `track()` -> `TrackDetail.upgrade` (`Upgrade`), the two spectra (`spectrum(track_id, 'current'|'new')`), `audio_url`s. Words: `decisionModel.ts`, `format.ts`.

**1. Information shown** (command today: `upgrade list` gives per upgrade `track, artist, title, folder, file, parked, now, new, alignment, same_track, auto_refused, auto_waits`; `upgrade apply --dry-run` gives `new_file`, `superseded`, `space`, `rekordbox`; the sentences below: **none**)

| Shown | Source | Command |
|---|---|---|
| Warn note with the sync's refusal words (above the cards), when the Auto-upgrade phase refused it and it is not waiting for rekordbox | `upgrade.auto_refused{reason,message,at}`, `auto_waits`; `decisionModel:autoNotes` | `upgrade list`: `auto_refused{reason,message,at}`, `auto_waits` |
| Card title "Upgrade ready" or "Upgrade ready · 256 kbps version"; summary "found 18 Oct" | `upgrade.what`, `upgrade.found`; `format:upgradeLabel`, `foundText` | `upgrade list`: `parked`, `new`; the title words **none** |
| Two spectra (28 px) Now and New | `spectrum()` matrix (`discjockey/spectrum.py`) | none |
| "NOW" line: what the current download was made from ("Opus · 135 kbps") or, for an own or bought file, the quality label; tooltip "Your AIFF was made from this" | `track.source_format_line`, `track.quality_label`; `decisionModel:nowLabel`, `nowTip` | `upgrade list`: `now` (check it is the same wording) |
| "NEW" line ("FLAC · lossless", "MP3 · 320 kbps") | `upgrade.format_line` | `upgrade list`: `new` |
| Compare player (Now/New) | see `ComparePlayer.svelte` | none (person) |
| "Edit" row with a dot: "The same edit as yours" / "The same edit, 3 ms apart" / "A different edit" / "Couldn't compare them" | `upgrade.alignment{result,offset_ms,...}`; `decisionModel:editLine` | `upgrade list`: `alignment` (raw result and offset; words **none**) |
| "In rekordbox" choice: Same track (recommended: "Cues and beatgrid stay") vs New track ("Relocate your old track to keep cues" or "Set the cues again"), with outcome lists: "Your track keeps its cues, playlists and history", "Moved 3 ms to sit on your cues", "Becomes an AIFF file", "Quit rekordbox before you replace", "rekordbox lists it as a new track", "Relocate your old track: cues fit", "A different edit: set the cues again", "Unsure if your cues fit: listen first" | `upgrade.swap_safe/swap_possible/swap_how/alignment/rekordbox`; `decisionModel:upgradeWays` | `upgrade list`: `same_track` (null or reason); `upgrade apply --dry-run --way ...`: `rekordbox.needs_rekordbox_closed`; the outcome sentences **none** |
| Card with no choice: title "In rekordbox" or "The new file" (no rekordbox on this Mac), summary "a new track", outcomes, the reason line | `decisionModel:upgradeWays`, `waysTitle` | none |
| Reason Same track can't run, in words: "Same track needs a rekordbox library Discjockey can open. Update Discjockey, or replace it as a new track." / "...analysed in rekordbox first..." / "...analysed again..." / "can't change a track in rekordbox's Cloud Library Sync yet..." / "...your file where Discjockey expects it..." / "...your file's drive connected..." / "Same track needs the same edit" / "needs a measured match" / "isn't possible for this track right now" / "needs an AIFF file" | `upgrade.why_not` key + `alignment.result`; `decisionModel:WHY_NOT_LINE`, `upgradeWays` | `upgrade list` `same_track` gives the key; the sentence **none** |
| Line "Your old file is kept in Superseded/" always; "Quit rekordbox before you replace" tip when a rekordbox write follows | `decisionModel:KEPT_FILE`, `QUIT_REKORDBOX` | `upgrade apply --dry-run`: `superseded` path, `rekordbox.needs_rekordbox_closed` |

**2. Decisions the file takes itself** (`decisionModel.ts`; the engine's `eligible`/`views` has the underlying facts)

- `canSwap(up) = swap_safe && swap_possible`: whether the choice shows. Engine: `swap_possible`/`why_not` from `rekordbox/eligible` (REASONS); `swap_safe` is the alignment rule. A command's `same_track` already folds this.
- `upgradeWays`: which of Same track / New track are offered, their outcome lines, which is recommended (Same track), the default way (`way`), the "quit rekordbox" tip (only for in-place AIFF with rekordbox `ready`), the "no rekordbox on this Mac" special case. New track's availability: always (`goes`: not for `no_upgrade`, `file_missing`, `away`). The engine has the eligibility; the rest is UI. `upgrade apply --way same-track|new-track` has no recommendation.
- `editLine`/`cueTone`: green for exact/shifted, yellow for different, grey for unknown; the "shifted" ms rounding. UI only.
- `nowLabel`: source format of an AIFF's origin, else quality label. UI only (engine gives both fields).
- `autoNotes`: waiting beats refused (only one of the two shows). The same rule `views.upgrade_detail` uses for the to-do row.

**3. Actions**

- Pick Same track / New track -> `onway` (window state `upFlow.picked`; the foot's Replace then calls `upgrade(track_ids, 'swap'|'add_new')`). Command: `upgrade apply --way same-track|new-track`.
- Compare player and spectra: listening, no write.

### hub-ui/src/lib/components/TrackHead.svelte

Generic: shows its caller's data (head of a track's details panel). Callers: `pages/library/TrackDetails.svelte`, `pages/todo/Details.svelte`,
`pages/todo/DuplicateDetails.svelte`. What it shows: a 64 px cover (dashed when `empty`), the title (`h2`), a line "Artist · 3:12 · place" (parts that exist,
`trackHeadModel:headLine`), the state badge and its `word` (shown whole beside the badge or not at all: `wordHidden`, then the badge tooltip carries it), an optional
`action` (To-do's Hide), `children`, and a row at the foot "{Service logo} Open in {Service}" (`link` = `track_link{label,url,service}`; service names from
`copy:PLAYLIST_SERVICE_NAMES`). All data come from the caller (`TrackDetail` / `LibraryRow`: `cover_url, title, artist, duration_s, track_link`): command today **none**
(no command gives a track's artist/title/length/link; `upgrade list` gives artist/title for parked upgrades only). Decisions: word-hidden by measuring (layout only).
Action: the link -> `api.open_external(url)` (through `ExternalLink`).

### hub-ui/src/lib/components/ComparePlayer.svelte

A/B player for the upgrade decision. Callers: `lib/decisions/UpgradeCards.svelte`. It decodes both files in the browser (`fetch` of `track.audio_url` and
`upgrade.audio_url`, Web Audio) and plays one at the same offset.

**1. Information shown** (command today: **none**; this is listening, for a person)

| Shown | Source | Command |
|---|---|---|
| Play/pause button (spinner while both files load), A/B switch labelled "Now" / "New", time "0:42 / 3:12" (the track's length until both are decoded, then the shorter of the two), seek bar (appears after the first play), "Can't play these files." + Try again | UI state; labels from the caller (`a.label`, `b.label`); length `track.duration_s` or the decoded buffers | none for playing; the two files' paths are given: `upgrade list` gives `file` (the current one) and `parked` (the better version) |

**2. Decisions the file takes itself:** none a command needs (playback phases; arrow keys seek 5 s; both buffers are cut to the shorter length).

**3. Actions:** play/pause, switch A/B, seek: window audio only, no bridge call. Starting it stops the foot player (`player.stop`, `claimSound`).

### hub-ui/src/lib/components/MiniPlayer.svelte

A track's own player in the details panel. Callers: `pages/library/TrackDetails.svelte`, `pages/todo/Details.svelte` (and `lib/dev/Gallery`).
Input: `url` (`track.audio_url`), `title` ("Artist – Title"), `track_id`, `envelope` (the waveform peaks from `spectrum().spectrum.waveform` via `envelope()`), `length_s`
(`track.duration_s`), `start` (the page starts its list as a queue).

**1. Information shown** (command today: **none**; listening for a person)

| Shown | Source | Command |
|---|---|---|
| Play/pause/loading button (grey ring and 60% opacity when there is no file or it can't play) | `stores/player` (`$player.url/track_id/playing/loading`) | none |
| Waveform of 80 bars from the file's peak envelope (played part in the accent colour), or a plain 4 px bar without an envelope | `spectrum().spectrum.waveform` | none |
| Position / length "1:05 / 3:12"; or the player's error text in place of the time | `$player.position_s/duration_s/error`; `track.duration_s` | none |

**2. Decisions the file takes itself:** `active` = this file or this `track_id` is the playing sound; a click on the bar of an idle player starts it first. Arrow keys seek 5 s. Nothing a command needs.

**3. Actions:** play/pause/seek on the window's player (`player.play`, `player.toggle`, `player.seek`, or the page's `start`); no bridge call.

### hub-ui/src/lib/components/PlayButton.svelte

Generic: the round play/pause button. Callers: `lib/shell/NowPlayingRow.svelte`, `lib/shell/Foot.svelte`, `lib/decisions/FilePlay.svelte`, `lib/components/ComparePlayer.svelte`,
`lib/components/MiniPlayer.svelte`. Shows its caller's state: `playing|paused|loading`, label "Play" / "Pause" / "Loading" (tooltip and VoiceOver, with `subject` e.g. "Play Neonfieber.aiff");
off (grey ring) when disabled. Information shown: none of its own. Action: its `onclick` goes to the caller (window audio).

### hub-ui/src/lib/shell/NowPlayingRow.svelte

The hidden player folded into the sidebar foot ("Now playing" row). Caller: `lib/shell/Sidebar.svelte`. Data: `stores/player` state (`PlayerState`) via `footModel:footPlayer`; nothing from the engine.

**1. Information shown** (command today: **none**; window audio state, no engine data)

| Shown | Source | Command |
|---|---|---|
| Group label "Now playing" (full sidebar only) | literal | n/a |
| Title of the playing track; tooltip "Artist – Title · list name · Show player" | `queue current`, `footModel:footPlayer.title/tooltip`; list name `queue.source.label` | none |
| Play/pause/loading button (grey when `error`) | `footPlayer.play` | none |
| 2 px position line under the title (fraction played) | `footPlayer.frac` | none |
| "Show player" button (arrow up) | UI | n/a |
| Rail form: the three controls stacked, one tooltip | UI (`rail`) | n/a |

**2. Decisions the file takes itself:** `footModel:rowShown(p)` = a queue exists and the foot bar is hidden; `footPlayer.play` = error beats loading beats playing. Window state; no engine equivalent and none needed.

**3. Actions:** play/pause (`player.toggle`), Show player (`player.show`); no bridge call.

### hub-ui/src/lib/shell/RowLead.svelte

Generic: a 14 px lead for a browser-column / sidebar row. Callers: `lib/shell/BrowserColumn.svelte`, `lib/shell/Sidebar.svelte`. It shows what `CollectionRow.lead` says:
the service's logo for a playlist (`row.service`), a folder outline for a stand-alone folder (watched folder, pinned crate, Library folder no playlist uses), a yellow "!" (`warn`) for
a folder whose drive or folder is away, or nothing. The meaning (which service, folder vs playlist, away) is computed in `browserModel` from `sidebar()` (`sidebar.playlists[].service`, `sidebar.watched[].state`);
see the library audit "Browser column, rail, sidebar". Command today: **none**. No action.

### hub-ui/src/lib/decisions/FilePlay.svelte

The ▶ on one file of an import question or duplicate group (To-do). Callers: `lib/decisions/DuplicateChoice.svelte`, `pages/todo/QuestionDetails.svelte`.
Data: `FileSide` (`file_id, path, audio_url, online`) of the item; plays as a queue of the item's playable files.

**1. Information shown:** the play button (state from `decisionModel:fileState`: playing/loading/paused for this file), screen-reader name = the file's name (`decisionModel:fileName`); grey and off when
`!file.online || !file.audio_url` (offline drive or no address). Command today: **none** (`FileSide` data (path, quality, online) has no command; for a person to listen).
**2. Decisions:** `off` = not online or no audio address; the queue = the item's files in shown order, starting at this one (`decisionModel:fileQueue`: only playable files); the foot's link back = `source` (To-do, or the Library track).
**3. Actions:** press -> `player.playQueue(...)` or `player.toggle()`; no bridge call (the audio address is already in the item).

### hub-ui/src/lib/decisions/DuplicateChoice.svelte

"Which file stays?" for a duplicate group (same audio or same song, two or more files). Callers: `pages/library/TrackDetails.svelte`,
`pages/todo/DuplicateDetails.svelte`. Data: To-do item `pair: DuplicatePair {group_id, why, files: FileSide[], recommended, recommended_why}` (bridge `todo()`).

**1. Information shown** (command today: **none**: no command lists duplicate groups or answers one)

| Shown | Source | Command |
|---|---|---|
| Group title "Which file stays?"; summary "no clear winner" and hint "Same quality and format. Keep the one in the folder rekordbox uses." when there is no recommendation | `pair.recommended === null` | none |
| One row per file: quality badge (class, label), format name ("AIFF", "WAV", "FLAC", "MP3", "M4A", "AAC", "OGG", "Opus", "ALAC", else the extension in capitals), the file's last folder (or its file name when it is in no folder) + " · in your playlists" when `in_playlist`, full path as tooltip | `pair.files[].quality/quality_label/path/in_playlist`; `decisionModel:fileFormat`, `lastFolder`, `fileName` | none |
| "Recommended" reason on the recommended file (`recommended_why`, e.g. "Recommended: best quality") | `pair.recommended`, `pair.recommended_why` (engine `views.recommend`) | none |
| The recommended file is picked on opening | `DuplicateFlow.pick`: `chosen ?? recommended ?? null` | none |
| Each file that won't stay says "Goes to Superseded/" while another is picked | `pick` is a file id and this row is not it | none |
| Last row "Keep both" (2 files) / "Keep all" (3+) with "Both stay; this to-do goes away" / "All stay; this to-do goes away" | `decisionModel:keepLabel` | none |
| Play button per file (see `FilePlay.svelte`) | `files[].audio_url/online` | none |

**2. Decisions the file takes itself**

- `DuplicateFlow.pick(g)` = the user's choice, else the engine's `recommended`, else nothing (then the foot is off). Engine: `views.recommend` decides `recommended` (the better sound, then AIFF); the default-pick rule is UI, but it is just "take the recommendation".
- `fileFormat`: extension -> format name (table in `decisionModel.ts`). UI only.
- The "goes to Superseded/" marking: every file except the picked one (and none for Keep both/all). UI only; the engine's rule is `supersede_duplicate`.

**3. Actions**

- Pick a file or Keep both / Keep all -> `flow.chosen` (window state; the foot acts, see `DuplicateFoot`).
- Play a file -> `FilePlay`.

### hub-ui/src/lib/decisions/DuplicateFoot.svelte

Foot of "Which file stays?". Callers: `pages/library/TrackDetails.svelte`, `pages/todo/DuplicateDetails.svelte`. Shares the `DuplicateFlow` with `DuplicateChoice`.

**1. Information shown** (command today: **none**)

| Shown | Source | Command |
|---|---|---|
| Filled button named by the result: "Keep the AIFF" / "Keep the lossless file" / "Keep the FLAC file" (quality label) / "Keep the one in Old" (folder, up to 16 characters) / "Keep this file" / "Keep both" / "Keep all"; off and "Choose the file that stays" until a pick | `decisionModel:keepWords`, `fileWords` | none |
| Line under it "Not deleted: kept in Superseded/" (when one file is kept) | `decisionModel:SUPERSEDED_NOT_DELETED` | none |

**2. Decisions the file takes itself**

- `decisionModel:fileWords`: which short name tells the kept file apart (format when unique among the files, else quality label, else the folder name when <= 16 characters, else none). UI only; a command needs only the file chosen, not this name.
- `DuplicateFlow.keep(g, pick)` (`flows.svelte.ts`): **Keep both/all** = one call `keep_duplicates(group_id, all paths)`; **Keep one** = **a loop of one `supersede_duplicate(group_id', file_id, remaining paths)` per file that leaves**, with the group id recomputed after each step (`decisionModel:groupIdOf`: `"dup:" + sorted file ids`); stops at the first failure; toast "Moved n files to Superseded/." / the engine's note for one. The sequencing and the changing group id are decided in the UI, not in the engine. The engine has `supersede_duplicate` (`api.py`) per file only.
- Which paths are passed along (`g.files.map(f => f.path)`): UI builds the list from the item.

**3. Actions**

- Keep ... -> `keep_duplicates(group_id, paths)` (Keep both/all) or `supersede_duplicate(group_id, file_id, paths)` once per leaving file (jobs). No command exists.

### hub-ui/src/pages/todo/DuplicateDetails.svelte

The To-do details panel of one duplicate group. Caller: `pages/todo/Page.svelte`. Data: a `DuplicateItem` from `todo()`.

**1. Information shown** (command today: **none**)

| Shown | Source | Command |
|---|---|---|
| Track card (`TrackHead`): cover, title, "Artist · 3:12 · {folder}" (the item's `folder`, not a place line), no badge, and under it the item's `detail` sentence (the why of the group) | `item.cover_url/title/artist/duration_s/folder/detail` (`views.todo` duplicate items; `detail` words come from the engine) | none |
| The choice (`DuplicateChoice`) and its foot (`DuplicateFoot`) | see above | none |

**2. Decisions:** none of its own; the `DuplicateFlow` is created here and keyed by the group; `onacted(keep)` lets the page follow the song that holds a kept file.

**3. Actions:** Keep ... as in `DuplicateFoot` (bridge `keep_duplicates`, `supersede_duplicate`). Page-level to-do actions (Hide etc.) are in the to-do audit.

### hub-ui/src/lib/decisions/CheckCards.svelte

The rekordbox check one replace, Convert or clean name left, for one track. Callers: `pages/library/TrackDetails.svelte`, `pages/todo/Details.svelte`.
Data: the to-do item (`todo()` -> `TodoItem.check: RekordboxCheckView`, `can_undo`, `detail`). The batch version is `BatchCheckCards.svelte` (same words, plural).

**1. Information shown** (command today: `rekordbox checked` acts and `batch show` gives `rekordbox{entries,kept}` per track; none of the words below)

| Shown | Source | Command |
|---|---|---|
| Warn card "In rekordbox" (summary "same track, cues kept" or "a new track") with numbered steps, by `reason`: `swapped` (not moved): [Reload Tag only when `reload_tag`], "Analyse it again, so the waveform shows the full sound (lock the beatgrid first if you set it by hand)", hint "Kept your own title and artist in rekordbox" or "Shows as missing? Auto Relocate finds it by its name, cues and all."; `swapped` + `moved`: "The track shows as missing: Auto Relocate finds it by its name, cues and all", Reload Tag, analyse; `repointed`: Reload Tag?, analyse, USB step; `converted` (in rekordbox): lead = the check's `text`, then only the USB step; `added_as_new`: "Right-click your old track > Relocate > choose the new file" + "Analyse it again · your cues fit exactly / fit / fit to within N ms" or "Analyse it again and set the cues again · a different edit / it couldn't be compared" | `decisionModel:checkCard`, `RELOCATE_NEW`, `USB_STEP`, `keptLine`; `check.reason/moved/reload_tag/match/aligned/offset_ms/rekordbox` | none (the engine's one-sentence `check.text` = `report.check_text`, also in the sync report; the steps are separate in the UI) |
| USB step: "On a USB stick? The stick still plays the old file. Rebuild the stick in rekordbox before your next gig" | `decisionModel:USB_STEP` | none |
| No steps (`renamed`, or a Convert/repoint rekordbox doesn't hold, or `wrong_song`): a note card with the engine's whole `check.text` (`item.detail` as fallback); info tone for own checks (`converted`/`renamed`), warn for others | `check.text`, `item.detail`; `decisionModel:isOwnCheck` | none |
| Card "Replaced with lossless" / "Replaced with the better version" / "Converted to AIFF" / "Given its clean name", with the day ("today" / "31 Oct"), two rows saying where each file is now (new file: "in {folder}"; old file: "in {Superseded folder}" or "its name before"), and while undo is possible one hint ("Undo puts your old audio back in the file." / "Undo points rekordbox back at your old file." / "Undo puts your old file back as it was." / "Undo gives it its old name and points rekordbox back at it." / "Undo puts both back as they were.") | `decisionModel:replacedCard`, `sinceText`; `check.since/old_path/old_name`, `item.path`, `item.quality`, `item.can_undo` | `batch show`: `results[].path`; the rest none |

**2. Decisions the file takes itself** (all in `decisionModel.ts`; same as `BatchCheckCards`): `inRekordbox`, `isOwnCheck`, `checkCard` (which steps and which texts), `replacedCard` (titles and which rows by `reason`), `keptLine`, the sentence for "kept" fields. Engine has only the raw record (`views.check_view`) and `check.text`.

**3. Actions:** none here (read only). The foot is `CheckFoot`.

### hub-ui/src/lib/decisions/CheckFoot.svelte

Foot of the single rekordbox check. Callers: `pages/library/TrackDetails.svelte`, `pages/todo/Details.svelte`. Flow: `UpgradeFlow`.

**1. Information shown** (command today: none for the words)

| Shown | Source | Command |
|---|---|---|
| Filled button "Done, checked in rekordbox" or "Done" (a Convert / clean name of a file rekordbox doesn't hold) | `decisionModel:doneLabel` | none |
| Undo button only while `item.can_undo`: "Undo the replace" / "Undo the conversion" / "Undo the clean name"; tooltip "Puts your old file back; the new version waits again" / "Puts your old file back" / "Puts your old name back" | `decisionModel:undoLabel`, `undoAsk`, `undoTitle`; `item.can_undo` | none (`upgrade undo`'s `results[].message` carries its own words) |
| Warn note with the undo's refusal text | `flow.undoProblem` (= job message of `undo_upgrade`) | `upgrade undo` prints `results[].message`; exit 4 with rekordbox open |

**2. Decisions:** which of the three Undo wordings; `can_undo` is the engine's (`views.todo`). The confirm dialog that precedes an Undo (`undoAsk`: title, body, confirm label by kind and whether in rekordbox) is UI only (a command never asks).

**3. Actions**

- Done -> `rekordbox_checked([track_id])` (command: `rekordbox checked <track>`).
- Undo -> `undo_upgrade([track_id])` after the confirm (command: `upgrade undo <track>`).

### hub-ui/src/lib/decisions/AiffCard.svelte

What Convert to AIFF or Give it its clean name would do for one file (card + notes). Callers: `pages/library/TrackDetails.svelte`, `pages/todo/Details.svelte` (CDJ item).
Data: `track().aiff: TrackAiff {action, why_not, kind, from, to, name_now, new_name, bytes, lossy, cdj}` (engine `views.track`, from `aiff_plan`/`eligible.aiff_action`), and `rekordbox_status()`.

**1. Information shown** (command today: `convert <track> --dry-run --json` / `rename <track> --dry-run --json` give the plan `{items[{track,name,action,kind,from,path,new_path,superseded,bytes,cdj}], skipped[{track,reason,message}], waiting, kinds, lossy, space[{drive,needed,free,enough}], superseded_bytes, rekordbox{state,running,needs_closed}}`; `rekordbox preview <track>` gives `eligible{convert,rename,...}`)

| Shown | Source | Command |
|---|---|---|
| Warn note with the last press's problem ("rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only while rekordbox is closed." or the engine's message) | `flow.problem` (`aiffModel:aiffProblem`) | `convert`/`rename` JSON `results[].message`, exit 4 |
| Warn note with what the CDJs refuse (the engine's words) above the card | `aiff.cdj.words` | `convert --dry-run`: `plan.items[].cdj{short,words}` (only for items that would run) |
| Card "AIFF", rows: Now ("FLAC · 24-bit · 96 kHz"), Becomes ("AIFF · 16-bit · 44.1 kHz"), Name (old name; the new name under it with an arrow, once when equal), Space ("+31.4 MB; your original goes to Superseded/"); a Rename shows the Name row only; a file with no step shows Now only | `aiff.from/to/name_now/new_name/bytes`; `aiffModel:aiffRows`, `format:sizeWords`, `formatWords` | `convert --dry-run`: `items[].from`, `path`, `new_path`, `bytes`, `superseded`; `plan.space` (the words differ) |
| Outcome rows (only with a rekordbox Discjockey can open and a Convert that can run): "Your track keeps its cues, playlists and history", "Becomes an AIFF file", and while rekordbox runs "Quit rekordbox before you start" | `aiffModel:aiffOutcomes`, `rekordbox_status().state/running` | `rekordbox status`, `convert --dry-run`'s `rekordbox{state,running,needs_closed}` (no outcome sentences) |
| Info note for a lossy file: "An AIFF made from this sounds the same and takes 5-10 times the space." | `aiffModel:LOSSY_NOTE`; `aiff.lossy` | `convert --dry-run`: `plan.lossy` count (no sentence per file) |

**2. Decisions the file takes itself** (`aiffModel.ts`; engine: `aiff_plan`, `eligible`)

- `aiffShown(aiff, decision, away)`: card shows only if the engine has an answer, no to-do decision stands for the track (upgrade, check, duplicate) and the file is there; and either there is an action or `why_not` is one of `rekordbox_unreadable`, `cloud`, `rename_blocked`. Engine: `aiff.action/why_not`; "no decision stands" is UI (it knows the to-do items).
- `aiffAction`/`aiffLabel`: rename vs convert from `aiff.action`. Engine.
- `aiffVariant`: filled for lossless, CDJ-refused or rename; outline for other lossy files. UI only (a command has no "recommended").
- `aiffBlocked`: why the button is off, in short words: `rekordbox_unreadable`, `cloud`, `rename_blocked` ("Every name this file could take is in use, so it keeps its name for now."), or a Rename while rekordbox runs or can't be read. Engine: `eligible` reasons; the sentences are UI.
- `aiffRows`, `aiffNotes`: see above. UI words over the engine's fields.

**3. Actions:** none here. The foot is `AiffFoot`; the card asks `rekordbox_status()` (on show and on window focus) via `AiffFlow.attach`.

### hub-ui/src/lib/decisions/AiffFoot.svelte

Foot of the AIFF card (the Library's; To-do's CDJ item brings its own). Caller: `pages/library/TrackDetails.svelte`, `pages/todo/Details.svelte`. Flow: `AiffFlow`.

**1. Information shown** (command today: none for the words)

| Shown | Source | Command |
|---|---|---|
| Button "Convert to AIFF" or "Give it its clean name", filled (lossless, CDJ-refused, rename) or secondary (other lossy), busy while the job runs, off when blocked | `aiffModel:aiffLabel`, `aiffVariant`, `aiffBlocked` | `convert <track>` / `rename <track>` run it (no filled/outline) |
| Hint under the button with the reason it is off (centred) | `aiffModel:aiffBlocked` | `rekordbox preview <track>`: `eligible.convert/rename` (reason keys; sentence none), `convert --dry-run`: `skipped[].reason/message` |

**2. Decisions:** the choice of action by `aiff.action`. Engine already decides it.

**3. Actions**

- Convert to AIFF -> `convert([track_id], 'library'|'todo')` (job; command: `convert <track>`).
- Give it its clean name -> `rename([track_id])` (job; command: `rename <track>`).
- Result/problem handling: `aiffModel:aiffProblem` (the job's refusal message, else the track's own skipped/failed message) is shown on the card; then `rekordbox_status()` again.

### hub-ui/src/lib/components/TrackRow.svelte

Generic: shows its caller's data (one track line: cover, "Artist - Title" over "folder · detail", quality badge with an upgrade arrow, optional FREE tag, trailing).
Callers: **only `hub-ui/src/lib/dev/Gallery.svelte`** (the dev gallery); no page of the window uses it (Library, To-do and the others use `ListRow` / `LibraryTable`). So it
adds nothing the window shows. If it were used: fields `TrackRow{artist,title,folder,quality,quality_label,upgrade_ready,cover_url}`, tooltip "The artist gives it away for free" on FREE, and "Upgrade ready" on the arrow (`QualityBadge`). No decision, no action of its own.

### hub-ui/src/lib/components/QualityBar.svelte

Generic: draws a share bar (+ optional legend) for the counts its caller passes. Callers: `lib/components/SummaryStrip.svelte`, `pages/playlists/Row.svelte`, `pages/dashboard/Page.svelte`,
`pages/sync/plan/UpToDatePanel.svelte`, `pages/sync/EndScreen.svelte`.

**1. Information shown** (command today: **none** for any library count; `sync --dry-run --json` has only plan counts)

| Shown | Source | Command |
|---|---|---|
| Segments in this order: lossless, good lossy, weak, fake, missing (muted), then a dashed "waiting" segment, each as a share of the total | `by_quality` (from `library.summary.by_quality`, `dashboard`, playlist rows) + `waiting` (the playlist's songs with no file); `qualityBarModel:barParts` | none |
| Tooltip / screen-reader text "9 lossless · 2 weak · 5 waiting" | `qualityBarModel:barTitle`, `QUALITY_NAMES` | none |
| Legend (when asked): a coloured dot and "{n} {name}" per quality that has songs ("lossless", "good lossy", "weak", "fake", "missing"); the waiting count is not in the legend (the caller's caption says it) | `by_quality`; `QUALITY_NAMES` | none |
| Shimmer while counts are unknown (`by_quality` null) | UI state | n/a |

**2. Decisions the file takes itself:** `barParts` = percentage of each part of the total (counts incl. waiting), only non-zero parts; rounding of `waiting`; empty bar when the total is 0. Engine has the counts (`views.summary`, `by_quality`); the percentages are UI only (trivial).
**3. Actions:** none.

### hub-ui/src/lib/components/ImportCard.svelte

The import of the user's own music as one card. Callers: `pages/settings/FoldersPanel.svelte`, `pages/setup/StepExisting.svelte` (and `lib/dev/Gallery`). Data: `view` = `watchedFoldersModel:importView(job, folders)`,
from the `import` job's last `ImportProgress` event, `job.finished`, and `watched_folders().stopped/waiting`.

**1. Information shown** (command today: **none**; no command runs or reports an import)

| Shown | Source | Command |
|---|---|---|
| Card "Import"; tone green when done, red when failed | `view.kind` | none |
| Running: the phase line "Looking for music files" / "Reading what your files are · 340 of 1,500" / "Reading tags · 340 of 1,500" / "Checking the sound · 340 of 1,500" / "Linking to your playlists", a live bar (share = done/total of the phase; none for scan and link) | `ImportProgress{phase,done,total}`; `watchedFoldersModel:phaseLine`, `phaseShare` | none (a convert/rename run prints its own "Reading what your files are: n of m" on stderr) |
| Stopped: "Import stopped with 12 files to go. It carries on where it stopped." (warn mark) | `watched_folders.stopped && waiting > 0`; `stoppedLine` | none |
| Done: "Imported 1,240 files." (green) or the job's own message | `job.finished.result.files`; `doneLine` | none |
| Failed: the job's message (red) | `job.finished.message` | none |
| Stop button (with "Stopping" busy) while running; "Continue import" while stopped (Setup only; Settings has it in its foot) | `view.stopping`, `oncontinue` | none |

**2. Decisions the file takes itself** (`watchedFoldersModel:importView`, `canContinue`): which of running / stopped / done / failed shows (running beats stopped beats finished of this session; a "stopped" finish shows nothing of its own), the phase share, and "Continue is offered when files wait and no import runs". Engine: the job, `ImportProgress`, `ImportResult{files, own_songs, sound_checked, unreadable, left, stopped, link_note}` and `watched_folders.waiting/stopped`. A command needs the same states.
**3. Actions:** Stop -> `onstop` -> `stop()` (the running job); Continue import -> `oncontinue` -> `start_import()` (job).

### hub-ui/src/lib/components/DropZone.svelte

The drop target for a bought file in To-do's details (a picture of where to drop). Caller: `pages/todo/BoughtFile.svelte` (and `lib/dev/Gallery`). Data: `track` (`TrackDetail.bought_name`, artist, title) and the caller's state.

**1. Information shown** (command today: **none**)

| Shown | Source | Command |
|---|---|---|
| Idle: "Drag the file here"; "WAV, AIFF, FLAC or MP3 · renamed and filed automatically"; "-> Library/Hard_Bounce/Armin Hermann – Get Naughty" (where it will be filed, without extension, " - " shown as " – ") | `track.bought_name` (engine `views.track`); `todoModel:filedAs` | none |
| Dragging: "Drop it to add it to {Artist – Title}" | `stores/drag` | n/a |
| Busy: spinner, "Adding…", the dropped file's name (middle-cut) | job state, `FileDropped.name` | none |
| Error line under the zone (macOS refusal, e.g. unreadable, or the job's message); red dashed border | `FileDropped{readable,message}` (`api.py:1398-1412`), `add_bought_file` job message | none |
| "Add {file} again" button after a refused add (busy library) | `BoughtFile` | none |

**2. Decisions** (in `BoughtFile.svelte` / `todoModel:dropDecision`): a drop is for this track only when `FileDropped.track_id` matches; unreadable -> message; nothing selected -> toast by the shell. The engine remembers the dropped file (`HubApi._dropped`, one per track) and `add_bought_file(track_id)` takes **no path**: the file travels as the window's drop, not as an argument. A command needs the path as an argument (the engine's `ops.add_bought_file(paths, state, track_id, path, ...)` already takes one).
**3. Actions:** drop -> `add_bought_file(track_id)` (job); "Add again" -> same call.

### hub-ui/src/lib/components/QualityBadge.svelte

Generic: shows its caller's data (a track's quality). Callers: `lib/decisions/DuplicateChoice.svelte`, `lib/components/TrackRow.svelte`, `pages/playlists/ChangePanel.svelte`,
`pages/library/TrackDetails.svelte`, `pages/library/LibraryTable.svelte`, `pages/todo/{Details,QuestionDetails}.svelte`, `pages/sync/SyncCard.svelte`.

**1. Information shown** (command today: **none** for the track's quality; `rekordbox preview` gives codec/rate/bits, not the quality verdict; `upgrade list` `now`/`new` carry a quality text for parked upgrades)

| Shown | Source | Command |
|---|---|---|
| Coloured badge with the engine's label: "LOSSLESS", "FAKE · 16.0 kHz" (or "FAKE"), "16.0 kHz" for a lossy file (where its highs end; "LOSSY" when unknown), "NOT FOUND" (missing) | `quality`, `quality_label`, `cutoff_hz`; engine `views.quality_class`, `quality_label`, `khz` (threshold `WEAK_HZ`: lossy at or under it is `weak`, over it `good_lossy`) | none |
| Small "↑" accent badge, tooltip "Upgrade ready" (when the caller passes `upgrade`) | `upgrade_ready` | `upgrade list` (parked upgrades) |
| Muted "Not checked" badge, tooltip "The sound hasn't been checked yet" (an imported file whose sound isn't judged: no colour, no kHz) | `sound_checked === false` (engine `views.sound_checked`: `import_state == "identified"`) | none |

**2. Decisions:** none in the UI (colour class and label are the engine's). `checked` false hides the quality entirely; every count of qualities leaves such files out in the engine (`views.quality_counts`).
**3. Actions:** none (the table wraps it in a button; see `LibraryTable.svelte`).

### hub-ui/src/lib/components/AwayTag.svelte

Generic: shows its caller's data. Callers: `pages/library/LibraryTable.svelte`, `pages/todo/Page.svelte` (and `lib/dev/Gallery`). Shows a warn mark and the short word "Offline" / "Folder not found" / "File not found" for a list row whose file is not there to play;
tooltip = the whole line "Offline: connect the drive" / "Folder not found" / "This file isn't there any more." (`format:FILE_STATE_TAG`, `FILE_STATE_WORDS`). Source: `file_state` (engine `views.file_state`: `offline` = drive not connected,
`folder_missing` = watched folder not found, `file_missing` = path gone). Command today: **none** for a library file's state (`rekordbox preview` refuses with reason `away` / `file_missing` for the file it is given; `convert --dry-run` lists `waiting` reasons `away`, `file_missing`).
No decision, no action.

### hub-ui/src/lib/components/ListLine.svelte

Generic: one quiet line among a list's rows (an inline empty line, e.g. "This playlist is empty." above "Also in this folder" in the Library table). Callers: `pages/library/LibraryTable.svelte` (`data-test="library-main-empty"`), `lib/dev/Gallery`.
Shows the text its caller passes (`libraryModel:pageEmpty.line`). No data of its own, no decision, no action.

## Coverage

Every listed path, with its status:

| Path | Status |
|---|---|
| hub-ui/src/pages/library/LibraryTable.svelte | done |
| hub-ui/src/pages/library/TrackDetails.svelte | done |
| hub-ui/src/lib/components/ListRow.svelte | generic: shows its caller's data (callers: lib/decisions/AiffBatchPanel, BatchCheckCards, UpgradeSelection, lib/components/UnreadableList, WatchedFolderList, pages/settings/Page, pages/playlists/{ChangePanel,TidyList,Row,MovesPanel}, pages/setup/StepPlaylists, pages/limits/Page, pages/todo/Page, pages/dashboard/{Page,RunRow}, pages/sync/plan/{PlanRows,PlanFolds,UpToDatePanel,RunPanel}, pages/sync/{RunList,EndScreen}) |
| hub-ui/src/lib/decisions/BatchCheckCards.svelte | done |
| hub-ui/src/lib/components/WatchedFolderList.svelte | done (generic list of `WatchedFolderRow`s; callers: pages/settings/FoldersPanel, pages/setup/StepExisting) |
| hub-ui/src/lib/decisions/UpgradeCards.svelte | done |
| hub-ui/src/lib/components/TrackHead.svelte | generic: shows its caller's data (callers: pages/library/TrackDetails, pages/todo/Details, pages/todo/DuplicateDetails) |
| hub-ui/src/lib/components/ComparePlayer.svelte | done |
| hub-ui/src/lib/shell/NowPlayingRow.svelte | done |
| hub-ui/src/lib/components/MiniPlayer.svelte | done |
| hub-ui/src/lib/decisions/DuplicateChoice.svelte | done |
| hub-ui/src/lib/decisions/CheckCards.svelte | done |
| hub-ui/src/lib/decisions/AiffCard.svelte | done |
| hub-ui/src/lib/components/TrackRow.svelte | generic: shows its caller's data (callers: only lib/dev/Gallery.svelte; not used by any page of the window) |
| hub-ui/src/lib/components/QualityBar.svelte | generic: shows its caller's data (callers: lib/components/SummaryStrip, pages/playlists/Row, pages/dashboard/Page, pages/sync/plan/UpToDatePanel, pages/sync/EndScreen) |
| hub-ui/src/lib/decisions/BatchCheckFoot.svelte | done |
| hub-ui/src/lib/components/ImportCard.svelte | done (callers: pages/settings/FoldersPanel, pages/setup/StepExisting) |
| hub-ui/src/lib/components/DropZone.svelte | done (caller: pages/todo/BoughtFile) |
| hub-ui/src/lib/components/PlayButton.svelte | generic: shows its caller's data (callers: lib/shell/NowPlayingRow, lib/shell/Foot, lib/decisions/FilePlay, lib/components/ComparePlayer, lib/components/MiniPlayer) |
| hub-ui/src/lib/decisions/CheckFoot.svelte | done |
| hub-ui/src/pages/todo/DuplicateDetails.svelte | done |
| hub-ui/src/lib/decisions/FilePlay.svelte | done |
| hub-ui/src/lib/shell/RowLead.svelte | generic: shows its caller's data (callers: lib/shell/BrowserColumn, lib/shell/Sidebar) |
| hub-ui/src/lib/decisions/AiffFoot.svelte | done |
| hub-ui/src/lib/components/QualityBadge.svelte | generic: shows its caller's data (callers: lib/decisions/DuplicateChoice, lib/components/TrackRow, pages/playlists/ChangePanel, pages/library/TrackDetails, pages/library/LibraryTable, pages/todo/{Details,QuestionDetails}, pages/sync/SyncCard) |
| hub-ui/src/lib/components/AwayTag.svelte | generic: shows its caller's data (callers: pages/library/LibraryTable, pages/todo/Page) |
| hub-ui/src/lib/decisions/DuplicateFoot.svelte | done |
| hub-ui/src/lib/components/ListLine.svelte | generic: shows its caller's data (callers: pages/library/LibraryTable) |

## Findings worth the designer's eye

1. **The decision words live in the UI.** The check steps (Reload Tag, Auto Relocate, Analyse again, USB), the "In rekordbox" outcome lines, "Same track can't run" sentences, the AIFF card rows and notes, and the keep-button naming are built in `lib/decisions/{decisionModel,aiffModel}.ts`, not by the engine. The engine gives keys and one sentence per check (`check.text` = `report.check_text`), so a command that wants the same words needs them moved into Python (or the agent gets keys only).
2. **Keep one of a duplicate group is a UI loop**: `DuplicateFlow.keep` calls `supersede_duplicate` once per leaving file and recomputes the group id (`"dup:" + sorted file ids`) after each step. A command must do the sequence itself (one job).
3. **`add_bought_file(track_id)` takes no path**: the engine holds the file from the window's drop (`HubApi._dropped`). A command needs the path as an argument.
4. **Two copies of "is this on the to-do list"**: `libraryModel:inTodo`/`rowInTodo` versus `views.todo`; the Library audit notes they diverge (D6). A command should use the engine's.
5. **`TrackRow.svelte` is dev-gallery only** (nothing in the window uses it).
6. **Audio-only pieces** (`ComparePlayer`, `MiniPlayer`, `NowPlayingRow`, `FilePlay`, `PlayButton`) show window audio state: nothing for a command except the file paths (`upgrade list` gives `file` and `parked`; no command gives a library file's playable path or `audio_url`).
7. **Import has no command at all** (`start_import`, stop, the phase lines, "Couldn't read" list, stopped/waiting state): nothing reports or runs it from the Terminal.
