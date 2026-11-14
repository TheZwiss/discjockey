# CLI audit, supplement B (issue 39, step 1b)

UI files no earlier audit (`docs/2026-11-14-cli-audit-{library,todo,app}.md`) names: Sync, Setup, Settings, Playlists,
Limits, Dashboard, shell and shared parts. 59 files, every one read in full. Nothing was run. Paths are relative to the
repo root. "Today's commands" = `CONTRIBUTING.md` › "Commands for scripts and agents": sync (`discjockey [--yes |
--dry-run] [--limit N] [--extra N] [--json]`), `setup` (prompts), `update` (yt-dlp), `upgrades` (prompts), `rekordbox
status|preview|checked|backups|restore`, `upgrade list|apply|discard|undo`, `batch list|resume|undo`, `convert`,
`rename`, `settings auto-upgrade`. None of them reads the Sync plan, playlists, usage/limits, runs, accounts or the
other settings. "none" below means: no command gives it today.

Shorthand: `DV` = `downloads_view()` payload (`views.downloads`, `api.py:1153`): `{qobuz:{state,last_check,tracks},
youtube|soundcloud:{state,browser,browser_name,profile,profile_name,last_check,tracks}, library:{lossless,account,free}}`.
`setup` = `discjockey setup` (`setup_cmd.py`: interactive prompts for the Spotify Client ID and the Qobuz login only; no
flags, no YouTube/SoundCloud login, no state output).

### hub-ui/src/lib/components/AccountPanel.svelte
Used by Settings (`RowPanel`, `YouTubeMusicPanel`, `Page`) and Setup (`StepDownloads`); it renders a phase from
`accountModel.ts` / `accountFlow.svelte.ts` (not on my list, read for the words).

1. **Information shown**
   - Service name and the login state line: "Signed in via Chrome (DJ)" + sub "256 kbps · checked today"; "Signed in,
     no Premium" (YouTube) / "Signed in · Go+ not confirmed" (SoundCloud); "Can't read the login in <browser>"; "Paused
     today"; "Today's downloads used up"; "Not signed in any more in <browser>"; "Not set up yet"; Qobuz: "Signed in",
     "Left out", "Qobuz didn't accept the login". Source: `DV.<service>.state/browser_name/profile_name/last_check`
     through `accountModel.ts:accountSaid/qobuzSaid/panelLine` (tone good/warn/problem/none = StatusMark colour). **none**
     (no command prints any account state or last check).
   - Compact (Setup) head line: the state, or "what it gives" for an unset account ("lossless for most songs" / "about
     256 kbps instead of 130") + "optional" tag on a not-yet-working YouTube/SoundCloud card. UI constants
     `accountModel.ts:WHAT_IT_GIVES`. **none**.
   - Gain card (Settings): YouTube/SoundCloud: "256 kbps" with caption "with Premium|Go+ · about 130 without", two bars
     (256 vs 130 as a percentage of 256), sentence "N of your tracks came from free streams at about 130 kbps." from
     `DV.library.free` (shown only when > 0). Qobuz: tracks count (`DV.qobuz.tracks`) with label "lossless from Qobuz ·
     of <total>" (`total = library.lossless + account + free`) and a share bar `min(1, tracks/total)`; sentence "N of
     your tracks came from Qobuz.". Computed `accountModel.ts:gainLine/qobuzShare`; counts from `views.downloads`
     (`live` = in a playlist, not hidden; `premium` = `source_kbps >= PREMIUM_MIN_KBPS`). **none**.
   - Risk note behind the (i) per service (`accountModel.ts:RISK_NOTE`, three fixed texts: against Qobuz's terms /
     YouTube blocks unusual traffic / SoundCloud skips protected Go+ tracks). Static; **none** (README has an "Account
     risk" section).
   - Phase sentences: "Looking for your login…"; "Found your YouTube login in Chrome (DJ)." + "Use it, and Discjockey
     checks one song for the 256 kbps."; "No <Site> login in Chrome or Firefox." + "Sign in opens <Site> in <browser>,
     your default browser. Discjockey notices the login by itself."; "No browser Discjockey can read is on this Mac." +
     "Install Chrome or Firefox, sign in there, then look again."; "macOS didn't let Discjockey read Safari's logins." +
     "Turn on Discjockey under Full Disk Access…"; "Waiting for your sign-in in <browser>…" + "Use the window that just
     opened … keeps watching for 10 minutes."; "Checking one song…" / "Checking the login with one search…"; the check's
     own message (`AccountCheck.message`, built by `api.py:check_message`); the Chromium keychain warning "macOS will
     ask about “Chrome Safe Storage” once. Click Always Allow." (only before that browser was ever checked,
     `checkedBefore` over `DV` last_checks). Words: `accountModel.ts` functions; data: `find_logins(service)` →
     `{browsers:[{id,name,default,readable,problem,profiles:[{id,name,signed_in}]}]}`. **none**.
   - "Another browser ▾" menu: one entry per installed browser x profile, default browser first then by name, labelled
     "<Browser> · <profile>" only when the browser has more than one profile, with note "signed in" / "needs Full Disk
     Access" / "default browser". `accountModel.ts:browserMenu` over `find_logins`. **none**.
   - Qobuz password steps (3 fixed sentences) and "Stored only on this Mac. Discjockey tests the login with one search."
     Static. **none**.
   - "Download limits →" link shown when the account is paused or used up (`ladderModel.ts:limitsHref`). Link only.
   - Disabled reason text (Hint): console run, "Wait until the sync has finished.", busy, "Another sign-in is waiting
     for the browser." (`accountModel.ts:accountBlocked` over `job_status` `{job, console_running, sign_in}`). **none**
     (a command gets `busy`/`console` refusals from the lock instead).
2. **Decisions the file takes itself**
   - `accountModel.ts:accountPhase/qobuzPhase/firstFound`: which login to offer first (default browser first, then by
     name; first profile with `signed_in`; browsers with `problem == no_access` never offered for Sign in; Safari
     unreadable -> Open System Settings). Engine: `find_logins` returns the raw scan only (`api.py:2441`); the pick is UI.
   - `accountModel.ts:isWorking` (on/paused/used_up count as set up), `mainAction` (which one filled button), `dismissable`.
   - `accountModel.ts:checkPhase`: failed check -> tone warn for `no_premium`, problem otherwise; Safari
     `cookies_unreadable` -> "unreadable". Engine has the same `problem` values (`api.py:setup_account`) but not the tone.
   - `accountModel.ts:gainLine/qobuzShare` arithmetic (above). Engine has the three counts in `DV.library`.
3. **Actions** (all through `accountFlow.svelte.ts`): Use this login -> `setup_account(service, browser, profile)`;
   Sign in -> `account_sign_in(service, browser, profile)` (waits up to 10 min; event `SignInPhase`); Cancel ->
   `stop_sign_in`; Check again -> `setup_account` (YouTube/SoundCloud) / `qobuz_check_login`; Sign out -> confirm dialog
   ("Sign out of <name>? Discjockey forgets which browser holds the login. Downloads use the free streams until you sign
   in again; your browser stays signed in.") then `setup_forget_account(service)`; Open System Settings ->
   `open_privacy_settings`; Look again / Try again -> `find_logins(service)`; Qobuz Sign in ->
   `setup_qobuz_login(email, password)`; "I don't have Qobuz" -> `setup_skip_qobuz`; "Use another account" -> UI only
   (opens the form); "Set a Qobuz password ↗" -> `open_external(QOBUZ_PASSWORD_URL)`; "Google, Apple or Facebook
   account?" / "Keep the current login" / OK / Back -> UI only. Today's commands: `setup` does the Qobuz login and the
   Spotify ID interactively (no YouTube/SoundCloud account, no check, no sign out, no skip).

### hub-ui/src/pages/settings/RowPanel.svelte
Settings' panels for the rows that are not download accounts: Spotify, Programs, About, Music folder, Reports (one
`Panel` per `row`). Data: `setup_status()` (`SetupStatus`), `setup_check_tools()` (`SetupTools`), the hub store's
`read_status` / `job` / `app_update`, and a reports count from the Settings page.

1. **Information shown**
   - Spotify: state line "Connected as <name>" / "Connected" / "Left out" / "Not connected" / "Not set up"
     (`settingsModel.ts:spotifyState` from `status.spotify_login/spotify_app/spotify_skipped/spotify_user` and
     `spotifyUsed(read_status.services)`); sentence "Discjockey reads your playlists from Spotify; it never changes
     them." or, when left out, "You chose I don't use Spotify in Setup. Connect it when a playlist of yours is on
     Spotify."; "Waiting for the Spotify login in your browser…" while connecting. **none** (no command reads Spotify
     login state; `setup` asks for the Client ID and logs in interactively).
   - Spotify app (Client ID) fold: only when `status.spotify_app`; text "Only when you made a new app in Spotify's
     developer dashboard." (the ID itself is never shown); otherwise the note "The Spotify app comes first". **none**.
   - Programs "On this Mac": ffmpeg / ffprobe / deno each with a good or problem mark and the purpose ("converts files
     to AIFF", "checks length and quality (comes with ffmpeg)", "helps with YouTube downloads", `setupModel.ts:TOOL_PURPOSE`),
     for a missing one the Terminal fix line (`brew install …`, `setupModel.ts:toolFixes` cuts `tools.hints[name]` to the
     `brew install \S+` part and shows it once per command) and "Paste the line into the Terminal app and press Return;
     then Check again." Source `setup_check_tools().tools/hints/missing`. Partly: `setup` calls `check_tools()` (prints
     missing programs, interactive); **no command prints the state as data**.
   - Download tools card: `yt-dlp <version> (built in|updated)` and `streamrip <version> (built in|updated)` or "not
     installed" (`settingsModel.ts:toolsCard` from `tools.download_tools[...].version/source`); "Go back to yt-dlp
     <previous>" link (hidden while a version waits for a reopen); the update result lines "streamrip 2.1.0 → 2.1.1" /
     "yt-dlp 2026.10.10 (already the newest)" (`updateLines` over `update_tools` `{before, after, restart}`); note "Open
     Discjockey again" (+ "Quit Discjockey and open it again to start using yt-dlp <waiting|the new yt-dlp|the earlier
     yt-dlp>"); fallback "Discjockey couldn't read the download tools' versions…" (`download_tools_problem`). Partly:
     `discjockey update` prints `tool_updates.update_line(before, after)` and "Start Discjockey again to use it."; the
     installed versions, source, `waiting` and `previous` are **none**.
   - About: "Version <status.version>", "Discjockey <short version> is available" link with "Drag the new Discjockey
     onto Applications: your music, logins and settings stay." or "Up to date" (`lib/appUpdate.ts:updateLink`, hub
     store `app_update` = `app_update()` bridge call, `{state, latest, url}`); licence sentence (static). **none**.
   - Music folder: path + ok state (`status.music.path/state`), static explanation. **none** (the folder is chosen
     interactively by `setup`; no command prints it).
   - Reports: "…" / "No reports yet" / "1 sync report" / "N sync reports" from the `reports` prop (count of `runs()`),
     static sentence. **none** (sync `--json` prints one report path).
2. **Decisions the file takes itself**
   - `settingsModel.ts:spotifyState`: left out is only "left out" while no Spotify line is listed in playlists.txt
     (`read_status.services` has Spotify); else not connected/not set up. Engine: `setup_status` has the pieces, not the answer.
   - `setupModel.ts:toolFixes`: which missing program shows which install line (one per command). Engine: `hints` per tool.
   - `settingsModel.ts:needsReopen/reopenNote`: when a restart is needed (`waiting !== null` or the last change's
     `restart`) and which version it names. Engine: `tool_updates.update` returns `restart`; `waiting`/`previous` come from `setup_check_tools`.
   - `settingsModel.ts:updateOutcome/updateLines`: before/after wording "already the newest" when equal.
   - Report count: `runs().length` (computed on the Settings page).
3. **Actions**: Connect Spotify / Connect again -> `setup_spotify_login` (Cancel -> `stop`); Sign out of Spotify (confirm
   "Sign out of Spotify? Discjockey stops reading your playlists until you connect again.") -> `spotify_sign_out`; Save the
   Client ID -> `setup_save_client_id` (check "A Client ID has 32 letters and digits." in the UI,
   `setupModel.ts:checkClientId`); Open setup -> route `/setup/spotify`; Check again (programs) -> `setup_check_tools`;
   Update download tools -> `update_tools`; Go back to yt-dlp <v> (confirm) -> `rollback_tools`; Quit Discjockey ->
   `quit`; Show licences -> `open_licenses`; Change… music folder -> folder picker then `useFolder` (`musicFolderFlow`,
   setup_save music folder; closes the app); Show in Finder -> `reveal('.')`; Open the reports folder ->
   `reveal('.discjockey/reports')`; See all runs -> route `/runs`. Commands: `update` (update only; no rollback),
   `setup` (Spotify ID + Qobuz, music folder). None for sign-out, rollback, licences, reveal.

### hub-ui/src/lib/components/AddRow.svelte
"Paste a playlist link" block of Playlists (draft list) and Setup's first playlist (saved at once). Data: `add_playlist(url)`
answer `AddedPlaylist {playlist_id, service, service_name, link, info:{name, owner_name, yours, collaborative, readable,
image_url, track_count, hint}|null, tracks, readable, suggested_folder, hint}` (`api.py:1429`).

1. **Information shown**
   - Found card: cover (`info.image_url`), name (`info.name`, else "Unknown playlist"), service logo + line "<service> ·
     <owner: yours | collaborative | owner_name> · N tracks" (`foundLine`, `addRowModel.ts:ownerText`; N =
     `info.track_count ?? tracks`; omitted when unknown), then "Discjockey can read this playlist" or, for Liked music
     (`youtube_music:LM`), "Discjockey reads it through your YouTube login" (`addRowModel.ts:readLine`); an unreadable
     playlist shows `result.hint ?? info.hint` (the service's own words) in problem tone. Source: bridge. **none**
     (no command reads a playlist's name/owner/count; `playlists.txt` is edited by hand).
   - Suggested folder name (`suggested_folder`, editable). **none**.
   - "Needs a setting" card for Liked music while `read_liked_music` is off (`add_playlist` -> `{ok:false, kind:
     'setting_off', setting}`): name "Liked music", "YouTube Music · yours", "Reading your Liked music is off", hint "It
     reads through your YouTube login, so it's a choice in Settings." (+ "Turn it on there after setup; add another
     playlist for now." in Setup). Static words `addRowModel.ts:SETTING_FORMS`. **none**.
   - Problems: the engine's message whole for `refused`/`playlist_unreadable`; "This playlist is already in your list."
     (UI duplicate check); "Not while a sync runs. Try again when it's finished." (`NOT_WHILE_SYNC`, also from
     `sync_running`); a ProblemCard for other kinds (`not_set_up`, `login_expired`, `offline`...) unless the shell
     banner says the same login problem. The four service names in the placeholder/tooltips
     (`copy.ts:PLAYLIST_SERVICE_NAMES`). Folder-name errors: "A folder name is needed.", "A folder name can't contain
     "/".", "Pick another folder name.", "Another playlist already uses the folder X." (`folderProblem`). **none**.
2. **Decisions the file takes itself**
   - `addRowModel.ts:playlistKey/hasLink`: which pasted link is the same playlist as a listed one (Qobuz id, SoundCloud
     `soundcloud:<user>/sets/<id>`, YouTube Music `youtube_music:<list id>`, Spotify bare id). A re-implementation of the
     engine's `sources.recognise` (`sources/soundcloud.py`, `sources/youtube_music.py`), `playlists_file.clean_link`; the
     engine answer is the same key, so a command can use `sources.recognise`.
   - `addRowModel.ts:folderProblem`: folder name rules (not empty, no "/", not "."/"..", not used by another row, case
     insensitive). Engine: `playlists_file` validates on save (grep needed by the CLI designer; the UI check is the
     early copy).
   - `addRowModel.ts:bannerSaysIt`: whether a login problem is already said by the shell banner. UI-only.
   - Add disabled while a sync runs (`networkReadsAllowed` store).
3. **Actions**: Add -> `add_playlist(url)`; Add to the list -> caller's `onadd(found, folder)` (Playlists: a draft row,
   saved later by `save_playlists`; Setup: `save_playlists` at once); Cancel -> UI only; Turn on in Settings -> caller's
   `settingAction` (navigation). Commands: none.

### hub-ui/src/pages/sync/EndScreen.svelte
The screen after a sync, and a past run opened from the Dashboard. Data: `run(run_id)` -> `RunDetail` (the run's `.json`
report: `run_id, started, finished, duration_s, exit_code, counts, stopped_after, auto_upgrade{...,line}, sections{<section>:
Result[]}, needs_you, for_rekordbox, upgrades_ready, report_md, queued, folder_order`), the run store (`job_finished`
of the sync, `new_since_preview`). Model: `pages/sync/endModel.ts` (not on my list; read for the decisions), `results.ts`,
`cardState.ts:verdict`.

1. **Information shown**
   - Title: "Sync finished" / "Sync finished with some problems" (exit 1) / "Sync stopped" (130) / "Sync didn't finish" (a failed
     job); sub "<when> · took <under a minute | N minutes>" (`endModel.ts:endTitle`, `format.ts:runWhen/minutesLong`
     over `started/finished/duration_s`). Sync `--json` gives `exit_code` and `report`; the words and the duration:
     **none**.
   - Stat cards: added (count of new-file results, with the quality bar split lossless / good lossy / weak / fake / missing
     and legend), moved (sections `moved` + `adopted`), "need you" / "needs you" (`needs_you` length).
     `endModel.ts:lastSyncStats`. Partly: `--json` `counts` has section counts (`new_lossless`, ...), but not the bar, not
     "need you" as the window counts it. **none** for the composed numbers.
   - Notes (one line each, in this order): "Stopped by you after N tracks. Nothing is half done; N tracks wait for the next
     sync." / "...the next sync continues."; the Auto-upgrade line (`run.auto_upgrade.line`, from `report.auto_upgrade_line`);
     "N upgrades ready to review" (+ Review ->); "N new since the check, it waits / they wait for the next sync" (only a
     run just finished in this window: `job_finished.result.new_since_preview`); "N tracks checked, nothing better yet";
     "N tracks wait for the next sync" (`run.queued`). Words: `endModel.ts:endModel`. Partly: `--json` `auto_upgrade` block
     has the counts, not the line; the rest **none**.
   - "Needs you" list: one row per problem result (`needs_you.filter(isProblem)`): cover, "Artist – Title", the playlist
     folder, a badge (NOT FOUND / PROBLEM / QOBUZ PROBLEM / "NO INTERNET · retried next run", `results.ts:rowBadge`,
     `cardState.ts:verdict` from `section/error_kind`), plus shop links parsed out of the note (`format.ts:noteParts`),
     and Fix -> (`#/todo?track=<id>`). **none** (`--json` lists `errors` count only; the report `.md` has the text).
   - "Added" lists, one per playlist folder, in playlists.txt order then by name (`folder_order`, `groupByFolder`), each
     sorted by "artist - title", title "<folder>", summary "N new track(s)", rows with cover, name, the note as second
     line, a quality badge (e.g. "LOSSLESS", "16.0 kHz", "FAKE · 16.0 kHz", with " · <source>" for a lossy file) and a
     Show in Finder link. Hint "Add the new files in rekordbox: Show in Finder opens each folder." Sections counted as
     new files: `new_lossless, new_not_lossless, fake, redownloaded, bought, replaced, added_new`
     (`endModel.ts:NEW_FILE_SECTIONS`, as `views.py:NEW_FILE_SECTIONS`). **none** for the rows and badges.
   - Auto-upgrade list in up to three parts: "Upgraded" (second line: the engine's note extras "Kept your own ... in
     rekordbox" / "This file isn't in your rekordbox collection, so there was nothing to keep there", else "Now an AIFF
     file; rekordbox follows it" (`how: new_aiff`) / "Same AIFF, lossless audio" (`in_place`)), "Still waiting" ("Waits
     for rekordbox to be closed" when the block's reason is `rekordbox_open`, else "Waits for your next sync"; Review ->),
     "Couldn't go in" (short reason `decisionModel.ts:AUTO_REFUSED_SHORT[reason]` or "Couldn't go in"; the row's note as
     tooltip; Fix ->). Source: `run.sections.upgraded` + `upgrade_waits` joined to `run.auto_upgrade.results` by track.
     The sync `--json` `auto_upgrade.results[]` has `state/reason/message/how` per track: the data exists; the sentences
     and the split rule are **UI-only**.
   - "Other changes" list: sections `upgrade_ready, swapped, moved, adopted, rekordbox_check, discarded, rejected, hidden,
     unhidden, dropped`; second line `otherDetail`: "from <folder>" (moved, parsed from the note "from Library/<f>/"),
     "found again after you moved it" (adopted), "no longer in a playlist; the file stays" (dropped), else the verdict's
     line ("a better version waits for you", "lossy, hard to hear", "audibly lossy"...), else the note. Review -> on an
     `upgrade_ready` row. **none**.
   - Failed sync: a ProblemCard with the job's `problem` kind and message (+ service, + Open report for a crash).
     `--json` problem objects carry `kind/message`.
2. **Decisions the file takes itself** (via `endModel.ts`)
   - `lastSyncStats`: "added" = results in `NEW_FILE_SECTIONS` that have a `track_id`; quality split per result via
     `cardState.ts:verdict(r).quality` (lossy: cutoff <= 17 kHz = weak, else good lossy; unknown quality counts as good
     lossy); "moved" = `moved` + `adopted` with a track. Engine: `views.py` has `NEW_FILE_SECTIONS` for the Dashboard's
     counts, not this split.
   - `isProblem` (`results.ts`) decides which `needs_you` rows are problems.
   - `autoRows`: splits upgraded / waiting / refused by the block's per-track state (no block entry = waits).
   - `endModel.syncRest`: "Sync the rest ->" appears when the run was stopped (exit 130) and `queued > 0`.
   - `groupByFolder`: ordering described above. `endTitle`: exit code -> title.
   - The 500 ms retry of `run(run_id)` right after a finish (the run is filed just after its JobFinished).
3. **Actions**: Full report -> `open_report(run_id)`; Show in Finder -> `reveal('Library/<folder>')`; Fix -> route to To-do
   with `track`; Review -> route To-do `filter=upgrade_ready`; Done -> route `/`, Back to the plan / Sync the rest -> route
   `/sync` (both dismiss the finished job in the run store). Commands: `discjockey --json` prints the end of a CLI sync;
   nothing reads a past run.

### hub-ui/src/lib/components/SourceLadder.svelte
"Where your music comes from": four rungs, best first, in Settings (full) and Setup (compact). Data: `DV`
(`downloads_view`) through `ladderModel.ts`.

1. **Information shown**
   - Four rungs with fixed names and badges: Qobuz (LOSSLESS), "The artist's own file" (OFTEN LOSSLESS; "SoundCloud
     download button · no login needed"), "Premium streams" (~256 KBPS), "Free streams" (~130 KBPS; "YouTube Music,
     SoundCloud, YouTube · the last resort"). Static. Whether a rung is lit: Qobuz lit when `DV.qobuz.state` is on, paused
     or used_up; Premium lit when YouTube is `on` (a YouTube login without Premium counts as off) or SoundCloud is `on` or
     `no_premium`; the artist's own file and Free streams always lit (`ladderModel.ts:ladderState/qobuzLit/working/
     downloadState`). Lit/unlit and the dashed chain are the meaning; **none** for the ladder as one answer.
   - Qobuz sub-line: "signed in" / "signed in · paused today" / "signed in · used up today" (compact: "paused today",
     "used up today") / "not used" (skipped) / "not signed in" (`qobuzWords`).
   - Premium sub-line: "through YouTube Premium" / "through SoundCloud Go+" / "through YouTube Premium and SoundCloud Go+"
     (compact "through Premium and Go+") / "through SoundCloud · Go+ not confirmed" / "<Service> paused today|used up today" /
     "can't read the <Service> login" / "needs YouTube Premium or SoundCloud Go+" (`premiumWords`).
   - Chips YouTube / SoundCloud with tone: signed in (good), `no_premium`/paused/used_up (warn "!"), else dashed; tooltip and
     screen-reader text "YouTube Premium: signed in" / "Go+ not confirmed" / "paused today, see Download limits" / "used up
     today, see Download limits" / "the login can't be read" / "not set up" (`chipLabel`).
   - The summary sentence under the ladder, exactly one of four: "Songs Qobuz doesn't have come in at about 256 kbps through
     <YouTube Premium|SoundCloud Go+>." / "Songs Qobuz doesn't have come from free YouTube at about 130 kbps." / "Without Qobuz
     nothing comes in lossless, except the artists' own files." / "Without Qobuz or an account, most songs come in at about
     130 kbps." (`ladderLine`).
   All **none** as a command (the state is in `DV`, which only the bridge's `downloads_view` returns).
2. **Decisions the file takes itself** (`ladderModel.ts`): which account counts as a working download account
   (`working`: on, or SoundCloud `no_premium`; a YouTube login without Premium never downloads); `qobuzLit`; `ladderLine`'s
   case choice and which account name it uses (YouTube if YouTube is `on`, else SoundCloud). Engine: `Settings.download_accounts`
   (`settings.py`) and `views.downloads` decide the real use; the ladder re-derives it from the states, so the two must agree.
   `limitsHref`: paused or used up -> `#/limits/<service>`.
3. **Actions**: click Qobuz's name or a chip -> `onpick(row)` (Settings selects the row, Setup scrolls to the card); a paused or
   used-up chip links to Download limits (route). No bridge call. Commands: none.

Cross-references: "App U<n>" = row n of the "Logic the window does itself" tables in `docs/2026-11-14-cli-audit-app.md`
(U1-U16 Sync, U17-U20 Dashboard...). "Console lines" = what `discjockey` (the sync) prints to the terminal
(`console.py`: `[i/n] Downloading [folder] artist - title`, then `searching.../downloading 12.3 MB of 40 MB/checking length/
converting 31 s of 240 s/analysing...`, `<label>: N s` for waits, `-> lossless|not lossless|fake lossless|better version
found, waiting for you|no better version yet|bought file added|downloaded again|not found|waiting for the next run|error
(note)`, `Upgrading i of n: name`, warnings as `  ! text`; `--verbose` adds searches). Human text on stderr, not data.

### hub-ui/src/pages/sync/SyncCard.svelte
The live card of a running sync (built by `cardState.ts:cardState` from the run store `stores/run.ts` = events
`ActionStarted/StepChanged/Progress/Waiting/SourceChosen/Checked/AccountUsage/ActionFinished/RunFinished`, or from
`job_status().job` after a reload).

1. **Information shown**
   - Preparing: spinner, "Getting ready" and the latest `Message(level=info)` text, else "Getting ready…". Console: those
     info lines are printed.
   - Working / downloading / converting: cover (plan cover or `track.image_url`), kicker "Now · <folder>", "Artist – Title"
     (all artists joined by ", "), the **from line** "<logo> <Service> · <how>" with how in words `copy.ts:SOURCE_HOW_WORDS`:
     "exact Qobuz track", "found by ISRC", "found by name", "picked by you", "the playlist's own upload" (from `SourceChosen
     {source, query_kind}`; empty until chosen); a step bar (see StepBar); a detail line: "Searching…/Checking…/Analysing…"
     (`copy.ts:STEP_LABEL`) or the wait label with seconds ("<label> · 12 s", from `Waiting`), or "Length matches (3:42 =
     playlist 3:42)" / "Length differs (3:42, playlist 3:40)" (`Checked {file_duration_s, track_duration_s, ok}`), or
     "Downloading · 12.3 of 40.1 MB · 31 % · 8 s left" (`Progress` bytes: percent = done/total, seconds left = ceil((total-done)
     /rate)), or "<length line> · converting to AIFF · 0:31 of 3:42" (`Progress` seconds); a progress bar with the same fraction;
     for an own or bought file "Adding the bought file…" / "Picking up the file in <folder>…" with no step bar. Console: shows
     `[i/n]` header, step name, bytes/seconds progress, wait label with seconds; **none** for the source and how, the length
     check sentence, percent, "s left".
   - Analysed (4 s after a track, `ANALYSED_MS = 4000`, or until the next work step begins): "Done · <folder>", name, the spectrum
     picture (`spectrum(track_id, 'current')`: the data behind the picture), the verdict badge and line (App U13:
     "LOSSLESS · full spectrum up to 22 kHz", "16.0 kHz · audibly lossy" / "lossy, hard to hear", "FAKE · 16.0 kHz · not really
     lossless", "UPGRADE READY · a better version waits for you", "MOVED -> <folder>", "NOT FOUND", "NO INTERNET · tried again next
     run", "QOBUZ PROBLEM", "PROBLEM"), or for a result without a file the note with shop links (`format.ts:noteParts`). Console:
     `-> lossless` etc. plus the note for some sections; **none** for the kHz cutoff, the badge, the spectrum.
   - Pause: the cover dimmed with a countdown ring (`Waiting {remaining, total, kind}` minus the elapsed time), kicker "Protection
     pause · next up" or "Longer break · next up", the next track's name, "<folder> · from <Service> · after that N more" or "...·
     last one" (N = `total - index`). Console: the wait label with seconds only; **none** for next-up and "after that N more".
   - Stopping: "Current track" / "Finished or cleanly discarded, then the sync stops." Finished: "Sync stopped" / "Sync finished".
   - Failed: a ProblemCard (problem kind, message, service). `--json`: `kind`, `message`.
   - Auto-upgrade phase (`kind: 'upgrading'`) is shown by the caller (`upgradeProgress`: "3 of 8 upgraded", "Upgrading · Artist - Title").
2. **Decisions the file takes itself**: none of its own except the derived strings above; `cardState.ts` decides which card
   shows and when (App U12), `verdict` (App U13), `fromLine`, `lengthLine`, the 4 s analysed window (UI timing only),
   source display names (`SOURCE_NAME` "YT Music", `SOURCE_FULL`). The spectrum is fetched once per finished track that has a file.
3. **Actions**: only `spectrum(track_id, 'current')` (a read); links to shop pages via `open_external`. No controls (Stop is the page's).

### hub-ui/src/pages/sync/StepBar.svelte
Generic: shows the steps its caller passes. Callers: `SyncCard.svelte` (`steps` from `cardState.stepsFor`). Words:
Search / Download / Check / Convert / Analyse (+ Compare for an upgrade action), done steps with a check mark, the current one
accented with a fill (the download or conversion fraction). The step list rule is `cardState.ts:stepsFor` (`upgrade` adds
Compare; `adopt_bought` has none); the current step comes from `StepChanged`. Console: step names in lower case ("searching",
"downloading", "checking length", "converting", "analysing", "comparing with your file") as the current line only; the list of
steps and what is done: **none**. No actions.

### hub-ui/src/pages/sync/plan/NextDot.svelte
Generic: the yellow 6 px "next sync" dot. Callers: `WhyMark.svelte` and the plan rows (`PlanRows.svelte`). Its meaning
(a download that waits for the next sync because today's limit is reached) is decided elsewhere (App U6 `planModel.ts:nextSyncSet`).
No information of its own, no actions.

### hub-ui/src/pages/sync/plan/WhyMark.svelte
Generic: a plan row's kind icon (+ the next dot below 680 px list width). Callers: `PlanRows.svelte`, the Gallery. Shows the row's
kind (`planModel.ts:kindOf`: acquire/retry -> "Not found last time", acquire/redownload -> "File gone", adopt_bought -> "Bought
files", upgrade -> "Weekly checks", other acquire -> "New"; App U2) as an icon only (tooltip text `planModel.ts:WHY`: "not
downloaded yet", "not found last time", "file gone", "bought file", "weekly check"). The `kind` and `reason` of each plan action
are in `sync_preview.groups[].actions[]`; no command gives them (`--dry-run` text lists rows). No actions.

### hub-ui/src/pages/sync/plan/NeverButton.svelte
Generic button: "Never download this track" (tooltip; `blocked` text instead while another change runs), aria-label "Never download
<name>". Callers: `PlanRows.svelte`. Ends in the caller's `never_download(track_id, true)` (App table: only `acquire` rows,
`planModel.ts:canNever`). Command: none to mark, unmark or list the never list.

### hub-ui/src/pages/sync/plan/WaitingAnswersNote.svelte
Warn note "1 song waits for your answer on the To-do page." / "N songs wait for your answer on the To-do page." (`planModel.ts:
waitingAnswersLine`; nothing at 0) with a "To-do ->" link to `#/todo?filter=same_song`. Source: `sync_preview.waiting_answers`. Used by the
plan's run panel and the Up-to-date view. Console: `console.py:QUESTIONS_WAITING` prints "N songs wait for your answer in the
window (Is this the same song?)." at the end of a console sync (`waiting_lines`), as text; the count as data: **none**
(`--json` does not carry it). No bridge call.

### hub-ui/src/pages/sync/plan/KindStrip.svelte
The plan at a glance, from the Sync page's `kinds: KindShare[]`, `total`, `line`. Words: the total ("66 tracks"/"1 track"), the line
("to sync in 4 playlists and 1 folder" / "every playlist and folder switched off" / "everything switched off",
`planModel.ts:stripLine`), a bar split by kind, and one row per kind present in the plan with its count: "New downloads"
("Songs in your playlists with no file yet"), "Files gone" ("Downloaded before, but the file isn't there any more: downloaded
again"), "Missing songs" ("Not found last time: looked for again once a week"), "Lossy files" ("Files that aren't lossless:
checked once a week for a lossless copy"), "Bought files" ("Files you bought, put in their playlists: nothing to download");
a weekly kind switched off in the panel keeps its row, dimmed, with the word "off" and leaves the bar (`KIND_SHARE`,
`kindShares`, App U2). The counts by kind exist in `--json counts` (`acquire:new`, `acquire:retry`, `acquire:redownload`,
`adopt_bought`, `upgrade` for a dry run) but without the scope switches (App U1); the words and tips are **UI-only**. Decisions:
which kinds are listed (any in the plan), `off`, `total` counts only collections and kinds switched on (App U1/U2). No actions.

### hub-ui/src/pages/sync/plan/ReadingCard.svelte
While the playlists are read: spinner, "Reading your playlists", "<index> of <total> · <folder>" (from `ReadingPlaylist(index, total,
folder)`, hub store `read_progress`), a bar at `max(4 %, (index - 0.5) / total)`, and when a plan from the last read stays
below the Hint "What's below is from the last read · it updates when this is done". `--dry-run` re-reads the playlists but prints no
per-playlist progress (the console ignores `ReadingPlaylist`). Decisions: the bar fraction (UI). Actions: none (Stop is the page's:
`stop_refresh()`).

### hub-ui/src/lib/components/ShareStrip.svelte
Generic: a share at a glance (big number + unit, a line under it, a bar snippet, a column of rows with words / quiet part /
count / tip / dimmed "off"). Shows only what its callers pass in. Callers: `pages/sync/plan/KindStrip.svelte` (the plan's
kinds), `lib/components/SummaryStrip.svelte` (Library's lossless share). Row link (›) -> the caller's `onclick`.

### hub-ui/src/pages/setup/StepSpotify.svelte
Setup step 2, Spotify. Data: `SetupStatus` (`spotify_app, spotify_login, spotify_skipped, spotify_user`), `SetupTools.redirect_uri`.

1. **Information shown**: card "Spotify" with "Discjockey only reads your playlists; it never changes them."; the state line:
   "Your browser opened. Log in to Spotify there; Discjockey goes on by itself." (waiting) / "Left out. Connect it here or in
   Settings when a playlist of yours is on Spotify." / "Connected as <name>" or "Connected" / "Your Spotify app is ready. Connect to log
   in." / "Not set up. It needs a free Spotify app, once (about 2 minutes)."; five numbered instructions (open the developer dashboard,
   Create app, add this Redirect URI = `redirect_uri` from `setup_check_tools` default `http://127.0.0.1:8888/callback` with a copy
   button, tick Web API and Save, copy the Client ID and paste it) with hint "New Spotify apps need a Premium account (yours)."; field
   checks "Paste the Client ID first." / "A Client ID has 32 letters and digits." (`setupModel.ts:checkClientId`); failure card "The
   Spotify login didn't work." (kind `login_failed`) or `problemCopy(kind).title` + `detailLine(message)`; "Stops waiting after 5
   minutes.", "Cancelled.", "Your browser opens to log in to Spotify, then Discjockey comes back here.". **none** as commands
   (`setup` asks for the Client ID and logs in interactively, prints no state).
2. **Decisions**: `setupModel.ts:stepsDone().spotify` = `(spotify_app && spotify_login) || spotify_skipped`; the Client ID is asked
   when no Spotify app is saved or "Use another Client ID" was clicked; Connect is the filled button until the step is done. Engine
   has `setup_status.next_step/complete` (`api.py:266`) for the same steps.
3. **Actions**: Connect / Try again / Connect again -> `setup_save_client_id(id)` (when asked) then `setup_spotify_login()`; Cancel ->
   `stop()`; "I don't use Spotify" -> `setup_skip_spotify()`; "Use another Client ID", "Open the dashboard" (`open_external`
   https://developer.spotify.com/dashboard), copy buttons -> UI only. Commands: `setup` (interactive Client ID + login only; no skip).

### hub-ui/src/pages/setup/StepDownloads.svelte
Setup step 3, Downloads: the compact SourceLadder + three compact AccountPanels (Qobuz, YouTube Premium, SoundCloud Go+) +, once Qobuz
is decided, an "Upgrades" card. Data: `downloads_view()` (`DV`), `SetupStatus` (`qobuz`, `qobuz_skipped`, `auto_upgrade`).
1. **Information shown**: everything of SourceLadder and AccountPanel (see those sections); the "Upgrades" list card with the switch
   "Upgrade automatically when I sync" (`lib/autoUpgrade.ts:AUTO_UPGRADE_LABEL`) and its sub (`AUTO_UPGRADE_SETUP_SUB`); the saved
   value (`status.auto_upgrade`, on when the key is missing) shown at once while saving; problem note with the save's message.
   Commands: `discjockey settings auto-upgrade [on|off] [--json]` gives the switch (the words are the same); the ladder and accounts: **none**.
2. **Decisions**: `setupModel.ts:filledCard(status)` (which card's button is the screen's one filled button: Qobuz while neither
   signed in nor skipped, else none), the "Upgrades" card appears only when that is null (Qobuz decided); required = Qobuz signed in or
   skipped (`stepsDone().downloads = qobuz || qobuz_skipped`); the step blocks Back/Continue while any account flow runs (`busy`).
   `accountBlocked` (console run, sync, another change, another sign-in).
3. **Actions**: the account flows (see AccountPanel); the switch -> `set_auto_upgrade(on)`; click a rung/chip -> scroll to the card.

### hub-ui/src/pages/setup/StepMusic.svelte
Setup step 1, Music folder (the only step shown until a folder is bound). Data: `SetupStatus.music {path, state, suggested}`,
`check_folder(path)` -> `FolderCheck {usable, problem, ...}`.
1. **Information shown**: "Music folder · Your music, its playlist folders and the sync reports live here."; once bound: the path, a
   check and "Change it later in Settings → Music folder."; before: a choice "A new folder" (default `~/Music/Discjockey`, or
   "Discjockey" inside a chosen parent, `musicFolder.ts:newFolderPath`) / "A folder I already have", the folder field with what is in
   the folder (`FolderCheck`: usable, what it holds, a problem sentence), error text. The folder check words come from the engine
   (`check_folder`). **none** (`setup` asks for the folder interactively in `setup_cmd.ask_music_folder` with `MUSIC_FOLDER_INTRO`;
   no command prints the current folder or checks a path).
2. **Decisions**: `usable = check.usable && !check.problem`; the suggested path; `bound = music.state === 'ok'`; which button is filled.
3. **Actions**: Choose… / Choose where… -> native folder picker (`chooseFolder`); Use this folder -> `useFolder(path, {bound:false})`
   (`lib/musicFolderFlow.ts`: saves the folder, hub reads again). Commands: `setup` (interactive, writes `config.json`).

### hub-ui/src/pages/setup/StepExisting.svelte
Setup step 2 (shown between Music and Programs), "Your existing music": folders of music the user already has, indexed where they are.
Optional. Data: the page-owned `WatchedFoldersFlow` (`watched_folders()`), the hub store's job (an import in progress).
1. **Information shown**: hint "Add folders with music you already have. Discjockey indexes it where it is: nothing is copied, moved
   or renamed."; the flow's note lines (e.g. merge hints from `check_import_folder`), the import card while an import runs (phase, counts
   via `ImportProgress`), the watched-folder list, and the "Couldn't read (n)" list (UnreadableList). Details of the folder list and
   the import card belong to Library/Settings (`FoldersPanel`, `watchedFoldersModel.ts`); **none** as commands.
2. **Decisions**: `setupModel.ts:skipsExisting(status, folders)`: Continue skips the step (and calls `setup_skip_import`) only when
   no folder of kind `import` is watched; `status.existing` marks the step done; Add folder… is the filled button until one folder is
   watched.
3. **Actions**: Add folder… -> native picker, `check_import_folder`, `add_watched_folder` (job, imports at once); Stop/Continue import ->
   `stop` / `start_import`; remove a folder -> `removal_preview` + `remove_watched_folder`; skip -> `setup_skip_import`.

### hub-ui/src/pages/setup/StepPlaylists.svelte
Setup step 5, First playlist. Data: `playlists()`, `add_playlist` (via AddRow), `save_playlists`.
1. **Information shown**: card "Add a playlist · Discjockey keeps each playlist's tracks in a folder of its own." (AddRow); the saved
   problem (ProblemCard of the save's kind/message); list "Your playlists · N playlist(s)" with, per row: cover, folder name, service
   logo + line (`changeModel.ts:setupLine`: `"<name>" · <owner> · N tracks`; "switched off · files stay"; "Liked music is off in
   Settings"; "not read yet"; the service's own hint in red for an unreadable playlist); LinkGuide (open until the first playlist is in,
   then folded); Hint "Add more and change their order later in Playlists." Source: `playlists().rows` (`info`, `tracks`, `enabled`).
   **none** as commands (`playlists.txt` is plain text; `discjockey --dry-run` reads playlists but prints only the plan).
2. **Decisions**: adding saves at once: `save_playlists(lines(addRow(draft, found, folder)), loaded.version)`; on `changed` it re-reads
   and retries once (optimistic version = hash of the file, `playlists_file.py`); `draft`/`lines`/`addRow` build the new file's lines
   in `changeModel.ts` (the new row goes at the bottom, lowest priority). Required: one playlist (`stepsDone().playlists`).
3. **Actions**: Add -> `add_playlist`; Add to the list -> `save_playlists`; the guide's fold -> UI only.

### hub-ui/src/pages/setup/StepTools.svelte
Setup step "Programs" (shown only when one is missing). Data: `setup_check_tools()` (`tools {ffmpeg, ffprobe, deno}`, `hints`).
1. **Information shown**: "Programs on this Mac · Discjockey needs three free programs."; per program ffmpeg / ffprobe / deno a good or
   problem mark, "converts files to AIFF" / "checks length and quality (comes with ffmpeg)" / "helps with YouTube downloads" and
   "missing · …" when missing, with the Terminal line to copy (`setupModel.ts:toolFixes`: `brew install …`, once per command);
   "Paste the line into the Terminal app, press Return, then Check again."; error "The programs couldn't be checked." Same data as
   Settings → Programs (see `RowPanel.svelte`). **none** as data (`setup_cmd.check_tools()` is used by `setup` to print the missing
   ones).
2. **Decisions**: `missing = TOOL_NAMES.some(not installed)`; Check again is the filled button while any is missing;
   `stepsDone().tools = ffmpeg && ffprobe && deno`.
3. **Actions**: Check again -> `setup_check_tools()`; copy the line -> UI only.

### hub-ui/src/pages/setup/StepFooter.svelte
Generic: Setup's foot (Back, a reason Continue is off, Continue / Finish). Shows what the page passes in. Caller: `pages/setup/Page.svelte`
(it decides `allowed` and `why` per step from `setupModel.ts`).

### hub-ui/src/pages/playlists/PlaylistLine.svelte
Generic: the service logo (tooltip: the service's name from `copy.ts:PLAYLIST_SERVICE_NAMES`) + the line text its caller passes (red when
tone `bad`). Callers: `StepPlaylists.svelte` and the Playlists rows/list (`pages/playlists`, text from `changeModel.ts:infoLine/setupLine`).
Words behind it: see StepPlaylists. No actions.

### hub-ui/src/lib/components/LinkGuide.svelte
Static help: "Where to find a playlist's link": per service in the order YouTube Music, SoundCloud, Spotify, Qobuz: where to click ("Share
› Copy", "Share › Copy link", "⋯ › Share › Copy link to playlist", "Share › Copy link") and an example link shape
(`music.youtube.com/playlist?list=…`, `soundcloud.com/name/sets/…`, `open.spotify.com/playlist/…`, `open.qobuz.com/playlist/…`),
from `linkGuideModel.ts:ROWS` (also the order `GUIDE_SERVICES` used by AddRow's logos). Callers: `StepPlaylists.svelte`, Playlists page.
README documents the same; **none** as a command (and not data an agent needs beyond the four link forms the engine's
`sources.recognise` accepts). No actions (the fold only).

### hub-ui/src/lib/components/linkGuideModel.ts
Pure words for LinkGuide: `GUIDE_HEAD`, `GUIDE_SERVICES`, `guideRows()` (see above). Caller: `LinkGuide.svelte`, `AddRow.svelte`
(service order). Nothing computed beyond the static table.

### hub-ui/src/lib/components/UnreadableList.svelte
Generic: the files an import could not read. Shows its caller's `files: UnreadableFile {folder_id, path, reason}[]` and `folders`: a
fold "Couldn't read (n)" (open up to 5 rows), per file its name (middle-ellipsised), "<folder relative to its watched folder, or the
watched folder's name at its root> · <reason>" (`watchedFoldersModel.ts:unreadableWhere/unreadableSub`), the hint "Tried again at the
next import." Data: `watched_folders().unreadable`. Callers: `pages/settings/FoldersPanel.svelte`, `pages/setup/StepExisting.svelte`.
**none** as a command (the unreadable files are in `watched_folders()` only). No actions.

### hub-ui/src/pages/sync/plan/RunPanel.svelte
"This run" panel of the Sync plan (before start). Presentational: the page (`pages/sync/BeforeStart.svelte`, with `planModel.ts`) passes
`summary: RunTotals`, `left`, `limit`, `accounts` (`SyncPreview.estimate.accounts`), `presets`, `howMany`, the weekly switches,
`waitingAnswers`, `deferredChecks`, and the Start button as a snippet. Data: `sync_preview()` (`estimate {limit, left, accounts[].uses_by_downloads,
minutes_by_downloads}`, `waiting_answers`, `deferred_checks`). Most decisions are App U3, U6, U7, U10 (not repeated).

1. **Information shown**
   - Two stat cards: "N tracks this run" (`planModel.ts:runCount` = ticked rows - ticked downloads that exceed today's limit) and "run time"
     ("~75 min" form via `planModel.ts:runTime`: "0 min" for none, "1-2 min" under a minute, else `estimate(minutes)`), from the
     minutes table `estimate.minutes_by_downloads[uses]`. Console: `--dry-run` prints count/time/budget lines as text (`run.budget_text`);
     **none** as data.
   - The waiting-answers note and the deferred-checks note ("N first upgrade checks of your imported music wait for later runs, so today's
     Qobuz allowance isn't used up." / singular; `planModel.ts:deferredChecksLine`, `SyncPreview.deferred_checks`). Console prints the
     waiting-answers sentence (see WaitingAnswersNote); the deferred checks: **none**.
   - Day card: the DayBar (see DayBar), the hint "N ticked wait for the next sync" (only when `left > 0`, some ticked downloads exceed
     today's limit, and the count differs from the bar's Later), the amount control "How many downloads" with chips 5 / 10 / 25 / 50 (only
     below the total), "<left> ✦" (fits today) and "All N" (`planModel.ts:presets`, `howManyOptions`), the line "✦ fits today · 60 a day"
     (limit of the first limited service) and a link "Download limits ->". **none**.
   - Per-service usage list when more than one account has a limit: name, a mini bar (or "backup" for an account behind Qobuz), and "10 of
     10" / "~4 of 30" / "30 left" (`planModel.ts:serviceRows`, from `uses_by_downloads[min(downloads, len-1)]`); tooltip "<name>: uses N
     of M left" / "<name>: M left today · for tracks Qobuz doesn't have". **none**.
   - Warn note "Downloads start tomorrow" when `left === 0` and downloads are ticked.
   - Weekly checks: two switches "Missing songs" and "Lossy files" with counts and kind icons (`planModel.ts:weeklyItems`), All / None.
     Switch state is window-only (localStorage `sync.scope`, App section 0). **none**.
   - Start sync + its note (App U10).
2. **Decisions**: `limitReached = left === 0 && downloads > 0`; `overflow` rule above; `services` shown only when `accounts.length > 1`;
   the day-bar numbers (`planModel.ts:runTotals`, `dayBarInput`, App U6); which presets exist (App U3). Engine: `estimate` tables only.
3. **Actions**: how-many chip -> window-only state (re-ticks the first N downloads in scope); weekly switch / All / None -> window-only scope;
   Download limits -> route `#/limits`; To-do -> route; Start sync -> `start_sync(selected)` (the caller). Command: `discjockey --limit N`
   is the nearest (downloads at most N, ignores the window's scope and ticks).

### hub-ui/src/lib/components/DayBar.svelte
Draws `dayBarModel.ts:dayBar(input)`: segments "Today N" (or "This sync N" in day mode), "Tomorrow N" or "Later N · ~D days", in day mode
also "Used N" (earlier runs today) and "N left"; caption "No daily limit" when unlimited; when empty the caller's words ("Nothing ticked",
"Everything switched off", "No downloads") (`planModel.ts:dayBarEmpty`); a text alternative = the segment labels joined by " · ". Callers:
`RunPanel.svelte`, the Dashboard's next-sync card (`dashboardModel.ts:dayInput`, App U17-U18), the Download limits page. Decisions: none
beyond `dayBarModel.ts`. No actions. The numbers come from the plan and the limits (`estimate`, `limits().usage`); **none** as a command.

### hub-ui/src/lib/components/dayBarModel.ts
Pure: `dayBar(i)` turns `{today, later, limited, laterDays, day?:{used, allowance}}` into segments. Rules: "Used N" only in day mode with
`used > 0`; "Today N"/"This sync N" when `today > 0`; "Tomorrow N" when `laterDays <= 1`, else "Later N · ~D days"; later only when limited;
"N left" = `allowance - used - today` in day mode when nothing waits; caption "No daily limit" when not limited. Engine
equivalents: `views.py` `days_to_load`, `run_minutes`, `limit_cards` give the numbers, not these labels. Callers: `DayBar.svelte`.

### hub-ui/src/pages/sync/plan/UpToDatePanel.svelte
The right panel of the Sync page when nothing is to do. Data: `runs()` summary of the last run + (on demand) `run(last.run_id)` for
the split (`endModel.ts:lastSyncStats/lastSyncView`), and the page's counts `todo` (To-do items) and `upgrades` (upgrades ready).

1. **Information shown**: "N added in the last sync" with the quality bar and legend (lossless / good lossy / weak / fake / missing), "<when>"
   ("today at ..." style from `format.ts:runWhen`, lower-cased Today/Yesterday) and "See what came in ->" (`#/sync/run/<id>`); "N moved";
   "N needs you" / "N need you"; list "Could be better": "Upgrades ready N" (-> To-do `filter=upgrade_ready`) and "In To-do N" (-> To-do).
   The cards show "-" while the run's details load; if the details fail the summary's counts are used without a bar (`lastSyncView`: added =
   `counts.lossless + counts.lossy`, moved = `counts.moved`, needs = `counts.problems`). **none** as commands (App U14; the sync
   `--json` has section counts of its own run only).
2. **Decisions**: `endModel.ts:lastSyncView/keepDetail/needsDetail` (a reply for an older run is dropped; details are loaded once per run);
   which "Could be better" rows exist (non-zero only).
3. **Actions**: links only (route changes), no bridge call of its own (the page calls `run(run_id)`).

### hub-ui/src/pages/sync/plan/UpToDate.svelte
"Up to date" card: a check mark, "Up to date", "<N playlists> · <M tracks>" (tracks omitted while null) and "+ Add a playlist" (-> `#/playlists`),
then WaitingAnswersNote (see above). Data: the plan's `playlists` count and `tracks` (`SyncPreview`; the page decides when the plan is
empty and no read is running). **none** as a command (`--dry-run` prints "nothing to do" text). No bridge call.

### hub-ui/src/pages/sync/plan/PlanRows.svelte
The plan rows, one list per folder section. Data: `SyncPreview.groups[].actions[]` `{key [kind, track_id, to_dir], kind, reason, folder, artist,
title, track_id, cover_url, in[], run}` shaped by `planModel.ts:sections/sectionOf` (App U1, U2, U6) into `Section {folder, rows, total, ticked,
waiting, downloads}`.

1. **Information shown**: per section the name (`planModel.ts:folderLabel`: the folder, or "Your own music" when blank; a row stands under its
   own folder while that collection is switched on, else under the first collection that is on), summary "N of M ticked" + " · W next sync",
   "Tick all" / "None"; per row: tick, cover, "Artist – Title", the why tag (not for a plain new track): "not found last time", "file gone",
   "bought file", "weekly check" (`planModel.ts:tagOf/WHY`), "next sync" with a yellow dot (a ticked download that exceeds today's limit,
   `planModel.ts:nextSyncSet`; tooltip "Ticked, but today's downloads are used up before it. It waits for the next sync."; dropped from the rows
   and said once in the head when every ticked download of the section waits, `waitsWhole`), the kind icon (WhyMark), the Never button (only for
   `acquire` rows); row tooltip "<name> · <why> · next sync". The order is playlists.txt order then run order. `--dry-run` prints the rows as
   text (`rep.render_plan`); **none** as data, none for ticks and the next-sync flag.
2. **Decisions**: `whyColumn(rows, mayWait)` (a column only for sections that can fill it; `mayWait` = more downloads in the plan than today's
   limit leaves and some left, `mayWaitToday`), `sectionSummary`, `waitsWhole`, `canNever`; keys `keyId` (`selection.ts`) make tick sets.
3. **Actions**: row click or the tick -> `ontoggle` (window-only ticks); "Tick all"/"None" per folder -> `onfolder`; Never -> `never_download(track_id,
   true)` through the page; the section fold -> UI only. Commands: none (the nearest, `--limit`).

### hub-ui/src/pages/sync/plan/PlanFolds.svelte
Four folds below the plan from `SyncPreview`:
1. **Information shown**: "Never download" ("N tracks · your choice, the sync skips them"; rows: cover, "Artist – Title", the playlist name, "Download
   again" button), "Left your playlists" ("N tracks · their files stay"; rows with the folder), "More than one file" ("N tracks · the sync leaves it|them
   alone"), "Notes" ("N notes", the planner's own sentences `preview.notes[]`). Fields: `never[]`, `dropped[]`, `ambiguous[]`, `notes[]`
   (each `{track_id, artist, title, folder, cover_url}`). Console: `--dry-run` prints the plan's notes as text (`rep.render_plan`); the three lists as
   data: **none** (the library audit may cover "never"); no command lists them.
2. **Decisions**: a fold only appears with rows; "Download again" is disabled while another change runs (`blocked`); the pluralised words
   (`format.ts:plural`).
3. **Actions**: Download again -> `never_download(track_id, false)` (the page's `onagain`); no commands.

### hub-ui/src/pages/dashboard/RunsPage.svelte
"All runs" (`#/runs`). Data: `runs()` -> `{runs: RunSummary[]}` newest first (`views.run_summary`: `run_id, started, finished, duration_s,
exit_code, counts{lossless, lossy, problems, moved}, stopped_after, auto_upgrade`), re-read on every data change.

1. **Information shown**: title "All runs" with sub "N run(s)"; empty state "No runs yet. Your first sync shows up here." with "Go to Sync ->";
   one list per month ("October 2026", "N runs") once there are more than 10 runs (`dashboardModel.ts:groupByMonth`, `GROUP_FROM = 10`;
   "Earlier" for an unreadable date), else one list; the right panel totals "N run(s)", "N tracks added" (= sum of `counts.lossless +
   counts.lossy`), "N moved", "N problem(s)" (`dashboardModel.ts:runTotals`). Each row: see RunRow. A failed read shows a ProblemCard with
   retry. **none** as commands (`batch list` lists AIFF batches, not sync runs; the sync's `--json` returns `report` of its own run only).
2. **Decisions**: month grouping rule above; totals are sums over the list (App U20). Engine has the per-run counts, not the totals.
3. **Actions**: open a run -> route `#/sync/run/<id>` (the end screen, which calls `run(run_id)`); retry -> `runs()`.

### hub-ui/src/pages/dashboard/RunRow.svelte
One run in the Dashboard's "Last runs" and in All runs. Data: `RunSummary`; words from `dashboardModel.ts:runLine`.
1. **Information shown**: mark (check = exit 0, "!" = exit 1 "some failed", square = stopped by you); title "<when> · <duration>" (`format.ts:runWhen`
   e.g. "Yesterday 21:47", `minutesLong(duration_s / 60)`, omitted when the duration is null); parts in quality colours: "N lossless"
   (ok), "N lossy" (warn), "N problem(s)" (bad), "N moved", or "nothing changed"; note "stopped by you after N tracks" (from
   `stopped_after`) or "stopped by you" (exit 130 without a count); tooltip = title + parts + note. Counts: engine `views.run_summary`
   (`LOSSLESS_SECTIONS`/`LOSSY_SECTIONS`/`PROBLEM_SECTIONS`/`MOVED_SECTIONS`); `stopped_after` is computed in the engine (tracks done
   before a stop, `section != queued`). The sync `--json` prints `exit_code` and `counts` per report section, not these four numbers;
   **none** for the run list.
2. **Decisions**: `runLine` status: `stopped` when `stopped_after !== null` or exit 130, `ok` when exit 0, else `failed`; part order
   and tone; "nothing changed" when all four counts are 0. All in the UI; the engine gives the numbers only.
3. **Actions**: click -> `go('/sync/run/<id>')` (route). No bridge call.

### hub-ui/src/lib/components/RiskScale.svelte
Generic slider: a number on five equal steps named by the caller's `zones` (`[{name, from, to}]`), with the handle, a "saved" tick and the step
under the handle named in its colour; step ranges are written "<= to" / "from-to" / "> from-1". Caller: `pages/limits/Page.svelte` (the daily
limit). The five names (careful, normal, faster, fast, risky) and their ranges come from the engine: `accounts.py:zones(service)` ->
`limits(service).usage.setting.zones` (with `recommended`, `min`, `max`); colours by step index (green, green, yellow, yellow, red) are
UI. A command gets the number through none today (the limit is only set in the window: `save_limits(service, limit, extra_today)`;
the sync has `--limit N` and `--extra N` for one run). Actions: drag / arrow keys / Page / Home / End -> `onchange(v)` (the page keeps a
draft until it saves with `save_limits`). Keys clamp to 1..max.

### hub-ui/src/lib/components/SummaryStrip.svelte
Library's collection-at-a-glance strip (a `ShareStrip`). Data: `library()`'s `summary {tracks, lossless_share, by_quality, not_lossless, upgrades_ready,
to_do}` and, for a read playlist, `songs {listed, with_file}` (the strip ignores the search and the filter). Model: `summaryStripModel.ts:stripView`.
Callers: `pages/library/Page.svelte`. (Library audit may cover the same data; listed here because no audit names this file.)
1. **Information shown**: the share "63 % lossless" (`round(lossless_share * 100)`, "-" when none checked or no tracks), the line "290 of 460 checked
   tracks" (checked = sum of `by_quality`) / "lossless · no tracks yet" / "lossless · none checked yet" / for a playlist "9 of 13 checked · 13 of 18
   downloaded"; the quality bar (lossless / good lossy / weak / fake / missing, + a dashed "waiting" part = `songs.listed - songs.with_file`); row
   "Upgrade ready N" (a link while N > 0); row "Not lossless yet · all in To-do | N in To-do | none in To-do   N" (the "· ..." part omitted at 0), a link while
   some are in To-do, mark = good lossy / weak / fake colours in proportion; tooltip "N of them in To-do: files of your own in no playlist and
   hidden tracks aren't" (None instead of 0) when fewer are in To-do than not lossless. Commands: **none** for the summary (`upgrade list` gives
   the parked upgrades; the library audit covers a library read).
2. **Decisions** (`stripView`): share rounding; `m = min(to_do, not_lossless)`; row links only when the count is > 0; wording of "in To-do".
   Engine has `summary.*` (`views.library`), not the words or the 63 % rounding.
3. **Actions**: "Upgrade ready" -> shows the Upgrade ready segment; "Not lossless yet" -> opens To-do (routes). No bridge call.

### hub-ui/src/lib/components/summaryStripModel.ts
Pure words for SummaryStrip: `stripView(summary, songs)` (see above; the exact sentences: "lossless", "lossless · no tracks yet", "lossless ·
none checked yet", "N of M checked tracks", "all in To-do", "none in To-do", "N in To-do", the tooltip). Caller: `SummaryStrip.svelte`.

### hub-ui/src/lib/components/qualityBarModel.ts
Pure: `barParts(byQuality, waiting)` -> segments in the order lossless, good lossy, weak, fake, missing, waiting, each with its share in percent of
everything the bar spans (only parts > 0; none: an empty track); `barTitle(parts)` -> the tooltip / VoiceOver text "9 lossless · 2 weak · 5 waiting"
(`QUALITY_NAMES`: lossless, good lossy, weak, fake, missing). Callers: `QualityBar.svelte` (used by `SummaryStrip`, `KindStrip`-like strips, the
end screen, the up-to-date panel, the Playlists rows). The by-quality counts come from the engine (`views.py` quality classes, weak = cutoff <=
17 kHz, App U13); the words and percentages are UI. **none** as a command beyond `convert --dry-run`'s own kinds.

### hub-ui/src/pages/settings/YouTubeMusicPanel.svelte
Settings' YouTube Music panel. Data: `setup_status().youtube_music {liked_music, can_turn_on, listed}` (`liked_music` = the saved choice
`settings.read_liked_music`; `can_turn_on` = a YouTube login exists; `listed` = a Liked music line is in playlists.txt).
1. **Information shown**: card "YouTube Music · Public and unlisted playlists need no login."; switch "Read my Liked music" with its second line
   "uses your YouTube login" or, when locked, "Sign in to YouTube first" (+ a "Go to YouTube sign-in" link); warn note (`settingsModel.ts:LIKED_WARNING`)
   "Reading your Liked music signs in with your YouTube account. Many reads can set off YouTube's bot check, which pauses those reads, and YouTube
   Premium downloads if you have them, for a while."; problem note with a failed save's message; the one filled button "Add Liked music to
   Playlists" only while the choice is on, saved, and no Liked music line is listed. **none** as a command (`settings` has only `auto-upgrade`).
2. **Decisions** (`settingsModel.ts:likedPanel`): `locked = !can_turn_on` (the switch shows off while locked: the engine counts the choice only with
   a login); `canAdd = !locked && liked_music && !listed`; the switch shows the pending choice at once until the status agrees.
3. **Actions**: switch -> `set_read_liked_music(on)`; "Add Liked music to Playlists" -> `add_liked_music()` (adds the Liked music line to
   playlists.txt, success toast "Liked music is in your playlists."); "Go to YouTube sign-in" -> route `/settings/youtube`. Commands: none.

### hub-ui/src/pages/settings/FoldersPanel.svelte
Settings -> Watched folders. Presentational over the page-owned `WatchedFoldersFlow` (`watched_folders()` -> `WatchedFolders {folders[{id, path, name,
kind library|import, state online|offline|missing|scanning|importing, files, waiting, unreadable, crates[], too_many}], unreadable[], waiting, stopped}`) and the
hub store's running job (`importView`). The library audit lists `watched_folders` and the import jobs (rows 65, 82, 83 and the import actions); this file
adds nothing new in data.
1. **Information shown**: the import card while an import runs / was stopped / just ended (ImportCard: phase, counts from `ImportProgress`), the
   watched-folder list (the Library first, always watched; each import folder with its state, its files count and "Remove"), the picked import folder's
   crate switches (CrateSwitches), the "Couldn't read (n)" list (UnreadableList), the note lines of the last Add folder... (a refusal's words from
   `check_import_folder`, or what the new folder took over: `merge_hints`), why the buttons are off (`writeBlockedReason`). **none** as commands.
2. **Decisions**: `cratesModel.ts:pickedFolder` (the route's folder path, matched as NFC path without trailing slash, else the first import folder with
   crates); `importView/canContinue` (when "Continue import" is offered: files wait and nothing imports); which button is filled (Continue import when
   offered, else Add folder...). Engine has the data (`waiting`, `stopped` = window memory `_import_stopped`).
3. **Actions**: Add folder... -> picker, `check_import_folder`, `add_watched_folder`; Continue import -> `start_import`; Stop -> `stop`; Remove ->
   `removal_preview` then `remove_watched_folder`; pick a row -> route `#/settings/folders/<path>`. Commands: none.

### hub-ui/src/pages/settings/CrateSwitches.svelte
The picked import folder's crates as switches ("In the sidebar", search "Search folders in <folder name>..."). Data: `WatchedFolderRow.crates[] {path, label, files,
hidden, tip}` and `too_many`.
1. **Information shown**: one switch per crate: label, file count, on = shown in the sidebar (`!hidden`, a pending save wins), tooltip = the full way from the
   watched folder (`tip`, parts joined by " › "), searchable also by the folders a crate sits in; a Hint under the group when `too_many` (more than 25 crates, all
   hidden until switched on: `cratesModel.ts:tooManyText`); "All" is only offered for a search that narrows a too-many folder to <= 25 (`ALL_MAX = 25`), "None" always.
   Failure toast "Couldn't save that. Try again." **none** (`sidebar()`/`watched_folders()` give the data; no command).
2. **Decisions** (`cratesModel.ts:crateChanges/crateShownValue/crateItems`): only crates whose state changes are saved; the value stored is `null` where the folder's
   default (shown unless `too_many`) already gives it, else `true`/`false`; saves go one after another, a refused one is put back.
3. **Actions**: switch / All / None -> `set_crates_shown(paths, shown)` (via `saveCratesShown` in the hub store; `set_crate_shown` for one). Commands: none.

### hub-ui/src/lib/shell/MusicMissing.svelte
Full-screen gate in place of every page while the chosen music folder can't be found. Data: `SetupStatus.music {path, state, suggested}`; reads via
`retry_music_folder()` -> `{music}`.
1. **Information shown**: "Your music folder isn't there", the path of the missing folder, "If it is on an external drive, connect the drive.",
   after Try again "Still not there." (the folder still missing) or the bridge's message. Commands: every command that needs the library answers
   `{"ok": false, "kind": "refused", "reason": "no_library"}` with exit 2 (sync `--json`, `rekordbox preview <track>`, batch commands); the folder path
   itself is not printed anywhere (**none**); the Terminal has no "choose another folder" except the interactive `setup`.
2. **Decisions**: the shell shows this screen when `music.state` is not `ok` (shell gate in `App.svelte`/`stores/hub`; engine `library.write_music_folder`,
   `_need_library`, App section 1 S1).
3. **Actions**: Try again -> `retry_music_folder()` (when `music.state === 'ok'` the data is read again); Choose another... -> folder picker then
   `useFolder(path, {bound:false})` (`musicFolderFlow.ts`; saves the folder, may close the app: `SAVED_MESSAGE`).

### hub-ui/src/lib/shell/SyncPart.svelte
The sync's part of the frame's foot while the window's own sync runs (every screen except Sync). A link to `#/sync`. Data: the run store (events).
1. **Information shown** (`lib/shell/activity.ts`): long form "Sync running · 4 of 6 · Downloading <Artist – Title>" / "Sync running · 4 of 6 · Protection
   pause 0:42 · next <Artist – Title>" / "Reading playlists…" / "Stopping…" / "Upgrading · <name> · 3 of 8 upgraded"; the Qobuz count "Qobuz 12 of 60 today"
   (from `AccountUsage`, or the dashboard's tile before the first usage event); short form "Sync 4 of 6" / "3 of 8 upgraded"; a thin progress bar at
   `(index - 1 + step fraction) / total` where a download step counts for 0.8 of the track and conversion for all of it; pulsing dot. Console: the `[i/n]`
   header, step and wait lines (`console.py`) give index/total, step and pause seconds; the Qobuz count line and the fraction: **none**.
2. **Decisions**: `activity.ts:activityText/activityShort/activityProgress/pauseLeft` (the 0.8 weight and the verbs `STEP_LABEL`); the 250 ms clock for the
   pause countdown.
3. **Actions**: link -> route `/sync`. No bridge call.

### hub-ui/src/pages/limits/UsageChart.svelte
Last 14 days of downloads of one service. Data: `limits(service).usage.days[]` `{date, used}` (14 entries, oldest first, today last: `views.limits` `last14`), the
saved limit, the draft limit being dragged (window-only), the zones (`accounts.zones`).
1. **Information shown**: one bar per day coloured by the risk of that day's count (green for careful/normal, yellow for faster/fast, red for risky:
   `limitsModel.ts:RISK`, `riskOf`, `zoneIndex`), today's ringed; day labels (the day of the month, "today" for the last); a dashed line "limit N" (the saved
   limit) and, while the draft differs, a solid line "new limit N"; tooltip "<d Mon> · N download(s) · <zone name>" (`limitsModel.ts:barTooltip`; the zone is omitted at 0).
   The scale grows to `max(1, limit*1.25, draft*1.12, max used)`. The numbers per day exist in the engine (`limits().usage.days`) and in `settings`/library.db
   (`state[<service>_usage].days`); **none** as a command. The zone names and ranges: `accounts.py:zones` (careful <= 40, normal <= 60, faster <= 79, fast <= 100, risky
   for Qobuz and SoundCloud; YouTube 20/30/45/60).
2. **Decisions**: the zone of a day's count (`zoneIndex`: the step whose range holds the count, below the first -> 0, above the last -> last); the colour map
   is UI; the engine also has `assessment(service, limit)` (`accounts.py`, slightly different tops 40/60/80/100) used for the verdict on the page.
3. **Actions**: none (display only).

### hub-ui/src/pages/sync/RunList.svelte
The result lists below the live card while a sync runs. Data: the run store: `results` (each `ActionFinished` result), `planned` (the run's planned actions from
`RunStarted`), `current`, `total`, `index`; the last started selection from localStorage (`sync.lastSelection`, App section 0) when the plan is unknown.
1. **Information shown**: filter segments "All N · Lossless N · Lossy N · Problems N" (shown once there is a result; counts from `results.ts:chipCounts`);
   lists "Problems N" (rows: cover, "Artist – Title", a badge such as "NOT FOUND" / "PROBLEM" / "QOBUZ PROBLEM" / "NO INTERNET · retried next run", Fix ->), "Done N"
   (cover, name, quality badge "LOSSLESS" / "16.0 kHz" / "FAKE · 16.0 kHz" / "UPGRADE READY", with " · <source>" for a lossy file: `results.ts:rowBadge`, source names
   Qobuz / YT Music / SoundCloud / YouTube / bought), "Up next N" (the planned tracks not yet done and not the current one, with their playlist folder at the
   right) or "N more" when only the total is known; "Nothing here yet" for an empty filter. Console: one line per finished track (`-> lossless` etc., with the
   note for problems), `[i/n]` headers; the lists, the counts, the badge words and the up-next list: **none**.
2. **Decisions** (`results.ts`): `isProblem` = section in {missing, errors, conflicts, ambiguous}; `isLossless` / `isLossy` (an `upgrade_ready` result counts by
   the *found* file's quality, `foundLossless`: `found_status`, else Qobuz = lossless); lists = problems first, then done, both in run order; `selection.ts:upNext`;
   "N more" = `total - index` when no plan is known (App U12, U15).
3. **Actions**: segments -> UI filter; Fix -> route `#/todo?track=<id>`. No bridge call.

### hub-ui/src/lib/components/OutcomeList.svelte
Generic: one short line per consequence of a choice, each with a glyph by kind (green check = stays as it was or fits, yellow info = needs a
step from you, red cross = something is lost, grey folder = where a file goes). Shows the `Outcome {tone, text}` items its callers pass in. Callers:
`ChoiceGroup.svelte`, `lib/decisions/{AiffCard,AiffBatchPanel,UpgradeSelection,UpgradeCards}.svelte` (the Library / To-do audits cover the sentences).
Colour meaning (tone) is information a command must also carry, as a word, if it prints these lines (`convert --dry-run` / `upgrade apply --dry-run`
already print their own). No actions.

### hub-ui/src/lib/components/StatusMark.svelte
Generic: a 16 px state mark, colour plus shape: check (good), "!" (warn), square (problem), dashed circle (none: nothing yet), return arrow (back: a move
that will be undone), quiet = outline check. The tone it is given is chosen by the caller; used in `AccountPanel`, `AddRow`, `UnreadableList`,
`RowPanel`, `SourceLadder`, `RowLead`, `AiffBatchPanel`, `UpgradeSelection`. Meaning of the tones across the app: good = working / done, warn = waiting,
paused, limited, or "needs a step", problem = failed or needs fixing, none = not set up / left out. A command's JSON should expose that state as a word
(e.g. the account states in `DV`), not as this mark. No actions.

### hub-ui/src/lib/components/ShareBar.svelte
Generic: a 6 px bar of parts (`{key, n, colour, label, off}`), each as wide as its share of the sum, dimmed when `off` (switched off), the empty track for
nothing; text alternative "N label · N label" or "Nothing" (also the tooltip). Caller: `KindStrip.svelte` (plan kinds: part labels are the lower-cased kind
labels, "new downloads", "files gone", "missing songs", "lossy files", "bought files"; a weekly check switched off leaves the bar: its `n` is 0). Words come
from the caller; **none** as data beyond `--json counts`. No actions.

### hub-ui/src/lib/components/ServiceMark.svelte
Generic: the service's own logo (Spotify, Qobuz, SoundCloud, YouTube Music, YouTube) 14 px, text alternative "<Service> playlist" or the caller's label;
`dim` for a service beside something switched off. Callers: `AddRow`, `LinkGuide`, `PlaylistLine`, `SourceLadder`-like rows, `RowLead` (sidebar),
`TrackHead`, `pages/settings/Page.svelte`. The logo is the information "which service is this playlist or file from" (the `service` / `source` fields of
playlist rows and tracks); no command prints it as a picture, the field is `service` (`spotify|qobuz|soundcloud|youtube_music`) in `playlists()`.
No actions.

### hub-ui/src/lib/components/ExternalLink.svelte
Generic link: any web address opens in the system browser through `open_external(href)`; shows the caller's text (or the address) with a trailing arrow.
Callers: `RowPanel` (app update link), `StepSpotify` (Spotify dashboard), `EndScreen` (shop links parsed from a result's note via `format.ts:noteParts`),
`TrackHead`, `TrackDetails`, `QuestionDetails`, `Sidebar`. In a terminal the address itself is the information (print it); there is no command that opens a link.

### hub-ui/src/lib/components/ConfirmHost.svelte
Generic host (mounted once in `App.svelte`) of `confirm({title, body, confirmLabel, cancelLabel, tone})`: a dialog with the caller's title and body and two
buttons (Cancel / the confirm label, red when `tone` is `danger`). Every confirm sentence belongs to the caller that asks (for example "Sign out of
Spotify?", "Sign out of YouTube Premium?", "Go back to yt-dlp <v>?", the watched-folder removal, the Library tidy-up). Information for a CLI: the dialog is
the place where the window states a consequence before a destructive step (`removal_preview`, `tidy_preview`, `undo_preview`); commands have no prompts, so
`--yes`/`--dry-run` stand in (see CONTRIBUTING). No bridge call.

### hub-ui/src/lib/shell/ErrorBoundary.svelte
Generic: wraps the page; on an unexpected exception shows "Something went wrong on this screen." and a Reload button (the error goes to the developer
console only in a dev build). No information for the user beyond that; no command equivalent (a command never shows a traceback: `{ok: false, kind:
"crashed"|"failed", message}`, exit 1).

### hub-ui/src/lib/components/SectionLabel.svelte
Outdated generic (marked in its comment "OUTDATED: use a Surface label"): an upper-case label with an optional count and "· hint". Shows what the caller passes;
no current caller in a page (only `lib/outdated.ts` and the base stylesheet name it). No data, no actions.

### hub-ui/src/lib/components/WriteButton.svelte
Generic Button wrapper for every action that changes files: disabled while a change runs in the window or a terminal sync holds the library, with the reason as
its tooltip: "Wait until the current change is finished." (a window job runs) or "A sync is running in the terminal." (`copy.ts:WRITE_BLOCKED`,
`stores/hub.ts:writeBusy/writeBlockedReason`; `job_status().job.running`, `console_running`). A command meets the same rule as the exit codes 3 (library
lock busy) / the `busy` and `console` refusals. Callers: Setup, Settings and the decisions' foots (`UpgradeFoot`, `AiffFoot`, `DuplicateFoot`, `BatchCheckCards`...).
Its own busy state shows a spinner.

### hub-ui/src/lib/shell/PageStub.svelte
Generic placeholder: a page header with the given title and "This screen comes next." Not referenced by any page today (no importer found); nothing to
audit. No data, no actions.

### hub-ui/src/lib/shell/ToastHost.svelte
Generic host (in `App.svelte`): shows the toasts the toast store holds (`stores/toasts.ts`), each with a tone, title and optional body, auto-dismissed, announced
politely to screen readers. Toasts are made by job layer success/failure copy (`lib/copy.ts:successCopy/problemCopy`, App U39), the recovered-steps message of
`library.recover_pending` (App S2) and ad-hoc calls such as `CrateSwitches` ("Couldn't save that. Try again."). A command prints the same facts as its
`message` / `recovered` fields. No actions beyond dismiss (UI).

### hub-ui/src/lib/components/Spinner.svelte
Generic: a small spinner with a text alternative (default "Loading"; callers pass "Waiting", "Checking", "Looking", "Reading playlists", "Working",
"Waiting for Spotify"). Meaning: something is in progress. In a terminal that is a progress line (stderr). No data, no actions.

### hub-ui/src/pages/NotFound.svelte
The empty state for an unknown address: "Nothing here." with "Go to the Dashboard ->" (`#/`). Registered as the fallback in `pages/registry.ts`. No data; a command
with a wrong argument prints argparse usage (exit 2). No actions.

### hub-ui/src/pages/playlists/TidyList.svelte
The files a tidy-up or a playlists save could move, as one list in three groups. Presentational: the callers `ChangePanel.svelte` (the save question) and
`MovesPanel.svelte` (Tidy up files) pass `rows: TidyRow[]` (`tidy_preview().rows` / `preview_playlist_change().tidy.rows`: `{file_id, track_id, artist,
title, cover_url, from, to, from_path, placed_by app|user|import, ticked, yours, skip {reason offline|not_found|name_taken, text}|null, by_rename}`), the ticks
(window-only `Set<file_id>`) and, in the save question, folders renamed on disk as one row each (`FolderRow {from, to, files}`).
1. **Information shown**: list label and summary from the caller; per movable file: tick, cover, "Artist – Title", "<from folder> -> <to folder>" (a folder
   name of "" is shown as "Library"; long paths break after "/"); a folder rename row "<from>, the whole folder" with "-> <to> · N files"; group "You put these
   here N" with the control "Put these in playlist order too" (tick = all, dash = some) for files the user or an import placed (`yours`); group "Can't move N"
   with a yellow "!" and the reason (`skip.text`, e.g. the file's drive is offline, the file isn't there, the name is taken in the target folder). Engine: the
   row fields above; the reason words come from the engine (`skip.text`); the group names are UI (`tidyModel.ts:YOURS_HEADER/YOURS_CONTROL/CANT_MOVE`).
   Console: the sync prints only "N files are not where the playlist order puts them; tidy up in the window" (`planner.out_of_place`); no list: **none**.
2. **Decisions** (`tidyModel.ts`): `groups(rows)` = main (no skip, not yours), yours (not skipped, `yours`), skipped; `initialTicks` = the engine's `ticked`
   (skipped rows never); `groupState`/`toggleGroup` for the "yours" control (skipped rows are never ticked). The default ticks are the engine's; whether to
   include the user's own placements is the user's choice, off by default.
3. **Actions**: tick a row -> `ontick` (window-only); the yours control -> `ongroup`; moving is the caller's `tidy_up(moves [[file_id, from_path]])` (job) or the
   save question's `save_playlists(lines, version, files)`; undo is `undo_moves(batch_id)`. Commands: none (the console never moves files).

### Notes for the CLI designer (found while reading these files)
- **The window's Sync plan is window memory.** Everything on the plan side (`PlanRows`, `PlanFolds`, `KindStrip`, `RunPanel`, `UpToDate*`, `ReadingCard`) reads
  `sync_preview()`, which exists only after a "Read playlists" in the same window session; the switches, ticks and the "how many" chip are localStorage (App
  section 0). No command reads a plan as data; `--dry-run` re-reads the playlists and prints text.
- **Account and Settings state have no command at all.** `AccountPanel`, `SourceLadder`, `StepDownloads`, `YouTubeMusicPanel`, `RowPanel` show login state, last
  check, kbps, browser/profile, ladder, Liked music choice, download-tool versions: all from `downloads_view()` / `setup_status()` / `setup_check_tools()`. Only `settings
  auto-upgrade`, `update` (yt-dlp, without rollback) and the interactive `setup` (Qobuz + Spotify ID only) exist.
- **Words built in the UI from fields**: account state lines (`accountModel.ts`), the ladder's four summary sentences and rung words (`ladderModel.ts`), the end
  screen's notes and Auto-upgrade sub-lines (`endModel.ts`), the live card's from line / detail / pause text (`cardState.ts`), the foot's activity text
  (`activity.ts`), plan why words and kind tips (`planModel.ts`), run line and month groups (`dashboardModel.ts`), Library strip words (`summaryStripModel.ts`).
- **Duplicated engine rules in the UI**: `addRowModel.ts:playlistKey` re-implements `sources.recognise` for the duplicate check; `ladderModel.ts` re-derives which
  accounts download (`Settings.download_accounts`); `cardState.ts:verdict` re-implements the weak threshold (17 kHz); the Dashboard/All runs "added" = lossless + lossy
  counts (`views.run_summary`) are defined by `LOSSLESS_SECTIONS`/`LOSSY_SECTIONS`, while the end screen's "added" uses the new-file sections with a track: inferred, the two numbers can differ for one run.
- **The run's `.json` report already holds the End screen's whole data** (`run(run_id)` is a read of it plus covers); a `runs`/`run` command would need no engine work.
- Surprise: `pages/playlists/TidyList.svelte` and `StepFooter.svelte` are generic; `PageStub.svelte` has no importer; `SectionLabel.svelte` is marked outdated with no page using it.

## Coverage

All 59 listed files, one line each (`done` = a section with the file's own information, decisions and actions above).

- hub-ui/src/lib/components/AccountPanel.svelte: done
- hub-ui/src/pages/settings/RowPanel.svelte: done
- hub-ui/src/lib/components/AddRow.svelte: done
- hub-ui/src/pages/sync/EndScreen.svelte: done
- hub-ui/src/lib/components/SourceLadder.svelte: done
- hub-ui/src/pages/sync/SyncCard.svelte: done
- hub-ui/src/lib/components/ShareStrip.svelte: generic: shows its caller's data (callers: KindStrip, SummaryStrip)
- hub-ui/src/pages/setup/StepSpotify.svelte: done
- hub-ui/src/pages/sync/plan/RunPanel.svelte: done
- hub-ui/src/lib/components/DayBar.svelte: generic: shows its caller's data (callers: RunPanel, Dashboard next-sync card, Download limits)
- hub-ui/src/pages/setup/StepDownloads.svelte: done
- hub-ui/src/lib/components/RiskScale.svelte: generic: shows its caller's data (callers: pages/limits/Page.svelte)
- hub-ui/src/pages/playlists/TidyList.svelte: done
- hub-ui/src/pages/sync/RunList.svelte: done
- hub-ui/src/pages/sync/plan/UpToDatePanel.svelte: done
- hub-ui/src/pages/sync/plan/PlanRows.svelte: done
- hub-ui/src/pages/setup/StepMusic.svelte: done
- hub-ui/src/pages/sync/plan/PlanFolds.svelte: done
- hub-ui/src/lib/components/SummaryStrip.svelte: done
- hub-ui/src/pages/setup/StepPlaylists.svelte: done
- hub-ui/src/pages/settings/YouTubeMusicPanel.svelte: done
- hub-ui/src/lib/components/LinkGuide.svelte: done
- hub-ui/src/pages/settings/FoldersPanel.svelte: done
- hub-ui/src/pages/dashboard/RunsPage.svelte: done
- hub-ui/src/lib/components/summaryStripModel.ts: done
- hub-ui/src/lib/shell/MusicMissing.svelte: done
- hub-ui/src/pages/limits/UsageChart.svelte: done
- hub-ui/src/pages/setup/StepExisting.svelte: done
- hub-ui/src/lib/shell/SyncPart.svelte: done
- hub-ui/src/pages/setup/StepTools.svelte: done
- hub-ui/src/pages/sync/plan/UpToDate.svelte: done
- hub-ui/src/pages/settings/CrateSwitches.svelte: done
- hub-ui/src/lib/components/UnreadableList.svelte: generic: shows its caller's data (callers: FoldersPanel, StepExisting)
- hub-ui/src/pages/sync/plan/KindStrip.svelte: done
- hub-ui/src/pages/sync/plan/ReadingCard.svelte: done
- hub-ui/src/pages/dashboard/RunRow.svelte: done
- hub-ui/src/lib/components/OutcomeList.svelte: generic: shows its caller's data (callers: ChoiceGroup, AiffCard, AiffBatchPanel, UpgradeSelection, UpgradeCards)
- hub-ui/src/lib/components/dayBarModel.ts: generic: shows its caller's data (callers: DayBar)
- hub-ui/src/lib/components/linkGuideModel.ts: generic: shows its caller's data (callers: LinkGuide, AddRow)
- hub-ui/src/lib/components/qualityBarModel.ts: generic: shows its caller's data (callers: QualityBar)
- hub-ui/src/lib/components/StatusMark.svelte: generic: shows its caller's data (callers: AccountPanel, AddRow, UnreadableList, RowPanel, RowLead, AiffBatchPanel, UpgradeSelection)
- hub-ui/src/lib/components/ShareBar.svelte: generic: shows its caller's data (callers: KindStrip, ShareStrip)
- hub-ui/src/pages/sync/StepBar.svelte: generic: shows its caller's data (callers: SyncCard)
- hub-ui/src/pages/setup/StepFooter.svelte: generic: shows its caller's data (callers: pages/setup/Page.svelte)
- hub-ui/src/pages/sync/plan/WhyMark.svelte: generic: shows its caller's data (callers: PlanRows)
- hub-ui/src/pages/playlists/PlaylistLine.svelte: generic: shows its caller's data (callers: StepPlaylists, Playlists rows)
- hub-ui/src/lib/components/ServiceMark.svelte: generic: shows its caller's data (callers: AddRow, LinkGuide, PlaylistLine, RowLead, TrackHead, settings/Page)
- hub-ui/src/pages/sync/plan/WaitingAnswersNote.svelte: done
- hub-ui/src/lib/components/ExternalLink.svelte: generic: shows its caller's data (callers: RowPanel, StepSpotify, EndScreen, TrackHead, TrackDetails, QuestionDetails, Sidebar)
- hub-ui/src/lib/components/ConfirmHost.svelte: generic: shows its caller's data (callers: App.svelte (every confirm() caller))
- hub-ui/src/lib/shell/ErrorBoundary.svelte: generic: shows its caller's data (callers: App.svelte)
- hub-ui/src/pages/sync/plan/NeverButton.svelte: generic: shows its caller's data (callers: PlanRows)
- hub-ui/src/lib/components/SectionLabel.svelte: generic: shows its caller's data (callers: none (outdated))
- hub-ui/src/lib/components/WriteButton.svelte: generic: shows its caller's data (callers: Setup, Settings and the decisions foots)
- hub-ui/src/pages/sync/plan/NextDot.svelte: generic: shows its caller's data (callers: WhyMark, Why)
- hub-ui/src/lib/shell/PageStub.svelte: generic: shows its caller's data (callers: none)
- hub-ui/src/lib/shell/ToastHost.svelte: generic: shows its caller's data (callers: App.svelte)
- hub-ui/src/lib/components/Spinner.svelte: generic: shows its caller's data (callers: AccountPanel, AiffBatchPanel, UpgradeSelection, ReadStatus, ReadingCard and others)
- hub-ui/src/pages/NotFound.svelte: generic: shows its caller's data (callers: pages/registry.ts)
