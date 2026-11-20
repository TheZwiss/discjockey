# Discjockey hub — bridge contract (Part B → Part C)

## Shapes

Every payload shape is a `TypedDict` in `discjockey/hub/shapes/` with each field's meaning beside it; this document keeps
the rules only. `uv run python -m discjockey.hub.shapes --export` writes `hub-ui/src/lib/bridge/types.gen.ts` and
`schemas.gen.json` (which shape answers which method and job kind); `discjockey help <command> --json` prints a
command's schema (`data_schema`, and `dry_run_schema` for its `--dry-run`; where the command line adds keys to the
answer, `CLI_DATA` in `shapes/cli.py` maps the method to the shape of the `data` it prints). A pytest fails when the generated files are
stale, every test checks what the engine answers and what a job finishes with, and the `data` the command line prints,
against the shapes (test mode,
`DISCJOCKEY_CHECK_SHAPES=1`), and `hub-ui/src/lib/bridge/fake/schemas.test.ts` checks the fake's. A shape changes in
its TypedDict and is regenerated; never in the generated files.

Source of truth: `discjockey/hub/api.py` (methods), `discjockey/hub/shapes/` (payloads), `discjockey/hub/views.py` (how
they are built), `discjockey/hub/jobs.py` (events).
Pinned by tests: `tests/test_hub_api*.py` (the page sees exactly these methods: `test_the_whole_contract_is_there`),
`tests/test_hub_shapes.py` (shapes, completeness), `tests/test_hub_views.py`, `tests/test_hub_fixture.py` (event schema).

## Calling

- `await window.pywebview.api.<method>(arg1, arg2, ...)` — **positional** arguments in the order listed. Every method
  resolves (never rejects) to `{"ok": true, ...fields}` or `{"ok": false, "kind": <problem>, "message": <plain English>}`.
  A problem with a playlist service (a `SourceError`: Spotify, Qobuz, SoundCloud or YouTube Music) also carries `"service": "spotify" | "qobuz" | "soundcloud" | "youtube_music"`;
  for every other problem the key is absent. The page names that service in its card.
- Write methods return `{"ok": true, "job_id": "job:<8 hex>"}` at once (every job id is this string, the window's jobs
  and the terminal's alike: `JobStarted.job_id`, `JobFinished.job_id`, `job_status().job.id` and `.sign_in.id`); the outcome arrives as a `JobFinished` event with the
  same `job_id` (see Jobs). At most one write job runs; others are refused with kind `busy` (hub) or `console`
  (a terminal run holds the lock). **The exception: brief saves** (`set_favourites`, `set_crate_shown`,
  `set_crates_shown`, plus `setup_skip_import`) answer their result at once (`{favourites}` / `{path, shown}` /
  `{paths, shown}`) and start no job and send no
  `JobFinished`. The two new ones also take no engine lock: they write the Favourites and the crate switches, which
  are records beside the library, not library state (`library.db` tables `favourites` and `crate_shown`, never in the
  snapshot, no `generation` bump). So pinning a playlist or switching a crate works during a sync, an import or a
  terminal run, where every job is refused. SQLite's busy timeout (1.5 s) orders them against a running job's
  transactions; a save that still can't be made answers `busy` (nothing was changed) and the page puts its list back
  and says so. They do not use localStorage because the window's saved settings start over when its port changes
  (`hub/window_port.py`), which is fine for a width but not for a curated list.
- After a write job finishes, re-fetch the screens you show (`track`, `todo`, `sidebar`, ...). After a playlists save,
  `read_status.lines_changed` is true until the next read: offer ↻ (`refresh()`; "playlists.txt changed since this read:
  the plan below is from the old lines"). After a sync (finished, stopped or crashed) `sync_preview` is the plan
  derived from the sync's own stored read and the library as the run left it, so what the run did is not offered again;
  after any other write too: nothing re-plans, the plan is derived on every ask (see `sync_preview`).
- A song's `rekordbox_check` (in `state.json`) is kept by every sync; only `rekordbox_checked(track_id)` clears it. The
  page sees it through `todo()`'s `rekordbox_check` group and the report section of the same name; `track()` does not
  return it. The panel builds its numbered steps from `reason`, `match`, `offset_ms`, `moved` and `aligned`: an added file's first step is a manual Relocate, never Auto Relocate, while `relocate` is true; with `relocate` false the one step is `report.NO_RELOCATE`'s words. It keeps `text` for any other reason.
- An own file (the import's) is in no playlist by nature: the Library table dims a row only when `!in_playlists && !own`.
- Disable write buttons while `job_status().job.running` or `console_running`. ↻ is refused during the hub's own sync.

### Problem kinds (`kind` on ok:false, `problem` on JobFinished)

| kind | meaning / UI |
|---|---|
| `busy` | another hub job runs (or a refresh already runs) |
| `console` | another process's job (a terminal run) holds the library lock → read-only banner. `data.holder` `{job, via, kind, line}` names it when the registry knows it (none for a holder with no registry entry, an older Discjockey); the message stays the same |
| `sync_running` | network read refused while any sync runs (searches, previews, playlist reads) |
| `not_set_up` | Spotify/Qobuz/playlists.txt not set up (SoundCloud and YouTube Music playlists need no login, so they never are) → wizard (`service` names the playlist service that isn't, when it is one). `message` is the inline wording ("Connect Qobuz first." for a pasted link, a read or a sync alike; `JobFinished.service` names the service for a read or sync too); a card's title and route ("Qobuz isn't connected.", "Connect Qobuz →") are the UI's, built from `kind` + `service` |
| `login_expired` | Spotify login expired → wizard Spotify step. With `service` `soundcloud`: a `soundcloud.com/you/likes` line (or a pasted one) is read through the SoundCloud login of Settings and SoundCloud didn't accept it ("SoundCloud didn't accept the login from {browser}. Log in to SoundCloud there, or use your profile's likes link (soundcloud.com/your-name/likes)."); it blocks reading like any login problem (`read_status.problem` + `problem_service`, the banner's "Connect SoundCloud →" goes to Settings' SoundCloud row) until a login is saved there |
| `offline` | no connection / a playlist service not answering (`service` says which, for Qobuz: "Qobuz is not responding (…). Try again later."; SoundCloud and YouTube Music say the same with their names, or "{name} asked Discjockey to slow down. Try again in an hour." for too many requests or a bot check) → "No internet connection. Try again when you're online." + Retry |
| `playlist_unreadable` | a playlist can't be read → the hint of its service (`service` on the answer; `info.hint`). Also a link the service refuses to read at all: YouTube Music's liked videos, Watch later and mixes ("Discjockey can't read your liked videos or Watch later. …", "This is a YouTube mix, …"), and `soundcloud.com/you/likes` without a SoundCloud login ("To read your own likes, use your profile's likes link: …"). YouTube Music's Liked music (`list=LM`) is not among them since the sources round: it answers `setting_off` (a choice in Settings); liked videos (`LL`) and Watch later (`WL`) stay refused |
| `config_invalid` | playlists.txt / settings.json / state.json needs fixing → show message |
| `qobuz_login_failed` | Qobuz login failed at sync start, or when reading a Qobuz playlist (`add_playlist`, a read; `service` `qobuz`) → wizard Qobuz step |
| `login_failed` | Spotify login in the wizard failed (port busy, timeout, refused). With `service` `youtube_music`: the YouTube login couldn't be read for the Liked music read ("Discjockey couldn't read your YouTube login to read your Liked music. Check it in Settings, YouTube Premium.") |
| `setting_off` | the playlist needs a choice in Settings that is off (sources round, Liked music): `add_playlist` for `music.youtube.com/playlist?list=LM`, `add_liked_music`, and a direct read; `message` "Reading your Liked music is off. Turn it on in Settings." On `add_playlist`'s answer `service` is `youtube_music` and `setting` names the choice (`read_liked_music`, its key in settings.json); the page shows its "needs a setting" form with a button to that Settings row. It is also what a Liked music line reads as while the choice is off (a `needs_setting` row, no problem card) |
| `exists` | `add_liked_music`: a Liked music line is in playlists.txt already, switched on or off ("Liked music is in your playlists already.") |
| `changed` | the track changed since it was read (an `expect` that is not the record's `rev` now; reason `rev_changed`, `data.rev` the current one) → re-fetch, show message |
| `refused` | not possible (bad input, rule) → show message |
| `failed` | a download / login / tool step failed → show message |
| `stopped` | ended by Stop (nothing half done) |
| `protected` | the version is DRM-protected (yt-dlp refuses it; Discjockey never works around DRM) → the plain message; "Wrong song?" takes the version off its list, and later searches leave it out (`.cache/protected_sources.json`) |
| `no_library` | no music folder is bound (not chosen yet, or the chosen one isn't there) → Setup's music step or the missing-folder screen; every method in `LIBRARY_METHODS` answers it while unbound |
| `crashed` | unexpected error → "Something went wrong" + message (a sync: "The sync stopped unexpectedly. Everything done up to then is saved, and the next sync carries on from there."; any other bridge call: "Something unexpected went wrong. Try again, and if it keeps happening, restart Discjockey."); for a sync: + Open report. A crashed sync is filed like any run: its report (`reports/<run_id>.md`, exit code 1) starts with a plain crash note (when, the step it was on, that what was done is saved; no error type in it; the error and traceback only at the very end), its .json has `crashed` (that note); `RunFinished` (exit code 1, that report) comes first, and the `JobFinished` carries the same `result` as a finished sync. A crash in another job files nothing (`result` null) |
| `bad_args` | the command line's: a typed id or word that names nothing (`resolve`, a `plan_id`, a batch id; `todo` with a filter that is no group). The window never sends one; the page shows it as `crashed` |

Use the kind for the card/headline; always show `message` as the detail.

Beside `ok`, `kind`, `message` (and `service`, `setting`) every ok:false answer also carries what the command line
reads (issue 39; additive, the page ignores it; the `Fail` shape has every field; a failure with kind `bad_args` is the `CliFail` shape, which the window never gets): `outcome` is the row of `kind` in
`discjockey/hub/outcomes.py` `KIND_OUTCOME` (`busy`, `console`, `sync_running` are `busy`; `not_set_up`, `no_library`,
`setting_off`, `exists`, `changed`, `refused`, `protected` are `refused`; `login_expired`, `rekordbox_open` are
`needs_person`; `stopped` is `stopped`; the rest are `failed`), `reason` is a key of `REASONS` in the same module (the
engine's own where the raiser named one, else the kind's), `person_steps` are what only a person can do (`rekordbox_open`
carries `step:quit_rekordbox`). An ok:true answer is unchanged.

The command line also calls methods the window does not have (the catalogue's `cli_first` entries, marked
`@cli_first` and kept on `CliApi(HubApi)`, because pywebview hands the page every public name of its object: the same
answers, but not in `contract.ts`, `types.ts` or the fake). `resolve(kind, values)` (group 1.2)
turns what a person typed into the method's argument: `{"kind", "resolved": [..]}`, one resolved argument per value in
the same order; kind `track` takes a song key (kept as it is) or the path of a library file (absolute, or relative to
the music folder) and answers the song key. Kind `folder` takes a watched import folder's path (absolute, `~` or relative to where the command runs; `folder:<path>` too) and
answers its folder id; the Library, a folder nobody watches and a path of no folder are `unknown_id`, no music folder is `no_library`. The command line's `settings_view()` (`@cli_first`; works without a music folder) answers what Settings holds, in the
page's words (the `SettingsView` shape); a settings file that cannot be read is `config_invalid`. A text no id can be made of answers `{ok: false, kind: "bad_args",
outcome: "bad_args", reason: "unknown_id" | "bad_id_kind"}`; a kind nobody resolves yet is `failed`. A single-track write checks the record only when it is given `expect` (see "Write jobs").

## Methods

### Read, any time

`dashboard()` — the start page: greeting, the read status, the tiles, the plan that is ready, what needs the user, one bar
per playlist folder and the newest runs.
Shape: `Dashboard` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
`ready` is null until the playlists were read; it carries the estimate fields of `sync_preview` (without its two
tables) and the plan's counts. `tiles.account_today` is the first set-up card of `limits()` (Qobuz first, then YouTube
Premium, then SoundCloud Go+), null when no service is set up.

`sidebar()` — counts and lists for the sidebar (to-do badge, Favourites, one entry per `playlists.txt` line, the watched import folders with their crates, the Library folders no line uses, Not in a playlist).
Shape: `Sidebar` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
`playlists` has every line of `playlists.txt` in file order, switched-off ones too (`#off#` lines). Its `songs` are the
distinct songs of the playlist's read record (the last successful read of it, kept per playlist in `library.db`; a token
resolves through a song's key or alias); a read that found no song is a record of 0 songs, not `null`, which is a playlist
never read. `library_folders` are the `Library/` folders with files that no line uses (case and accents ignored, as the
disk does). A file belongs to the folder it sits in, not to its song's folder: a file outside its song's folder counts
where it is, and a folder holding only the user's own files has its row. So every `files` (a Library folder's, a watched
folder's, a crate's) is the length of the `rows` of the view it opens, as are `all_tracks`, `not_in_playlist` and a
playlist's `songs`.
`watched` has the watched import folders (not the Library) ordered by name; `place` writes the path in words (the home
folder as `~`, a folder on another drive with the drive's name first and a no-break blank before the `›`), `state` is
checked live. `crates` are the folders below it that hold a file themselves (wrapper folders get no row; files directly
in the watched folder belong to no crate; a file under two watched folders belongs to the deeper one), all of them in
label order (numbers read as numbers, case ignored), hidden ones too. A crate is `hidden` by the user's switch
(`set_crate_shown`) or, without one, by the default: shown, but hidden when the watched folder has more than 25 crates
(`too_many`; the folder is then one row, and Settings switches single crates on). A label never depends on what is hidden.
`favourites` are the keys of `set_favourites` in their stored order, resolved; a key whose playlist or folder is gone is
left out of the answer, and stays stored.
`set_crate_shown(path, shown)` refuses a path that is no crate of a watched folder; `set_crates_shown(paths, shown)` is the same
for several crates in one write (all or none, a path given twice counts once). Both and `set_favourites` are brief saves
that start no job: they answer `FavouritesSaved`, `CrateSaved` and `CratesSaved` (generated, as above). `reveal(path)` also
opens an absolute path inside a watched import folder (the folder, a crate); any other absolute path is refused.
`limits_warning` is true when a set-up service has a warning sign the user hasn't marked as seen ("Got it",
`mark_warnings_seen`), or is paused today (the dot on "Download limits").
The page reads `sidebar()` again after `JobFinished` of kind `refresh`, `sync` or `import` (each changes what it counts
and lists), after `DrivesChanged` (a folder's `state`), and after its own `set_favourites` / `set_crate_shown`; no
event was added for it. The hub store reads it after every `JobFinished`, which includes those.

`sync_preview()` — the check before Start. Each action's `key` is sent back ticked to `start_sync`.
Shape: `SyncPreview` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
Before the first read the counts are 0, `counts` and `estimate` are null and `collections` is empty. `waiting_answers`
are held back until the user answers "Is this the same song?" (the plan's `questions`) and are not downloaded meanwhile.
`auto_upgrade` (stage C) is null when the switch is off and no placement is coming, settings.json can't be read, or
there is no preview yet — see "Auto-upgrade" below. `read_id` names the stored read the plan is derived from
(`read:<n>`; null before the first read). The plan is derived, never stored: every process that asks (the window, the
command line, a second window) gets the plan for the stored read and the library as they are now, and asking writes
nothing (so a dry run is this answer). A plan that can't be derived (a settings.json the planner refuses) is the error
of `sync_preview`, `start_sync` and `never_download` (`config_invalid`, its words); every other page that shows the plan
(the dashboard, Library, To-do, Playlists, Limits, the sidebar, `tidy_preview`) shows what it has without one, and
`read_status` then says `problem: config_invalid` with the words. `job_status` derives no plan: its `read_status` is the
stored read's head (and names a refused settings.json), and `lines_changed` also holds when every line was switched
off or removed.
Group `key`s/labels in order: `acquire:new` Download (new), `acquire:retry` Try again, `acquire:redownload` Download
again (its file is missing; planned only for a song whose Download again the user asked for, issue 43: a missing file alone plans nothing), `adopt_bought` Add a bought file, `upgrade` Look for a better version (weekly check). There are no `move` or
`adopt` groups, no `counts.moves` / `counts.adopts` (in `sync_preview` and in the dashboard's `ready.counts`) and no
`from_folder` on a row any more (library stage 1): a sync moves no files, and files moved by hand are found by the
scan (`rescan_library`). An action's `key` is `[kind, track_id, to_dir]` (3 strings).
A row's `in` names the collections of the browser column its song belongs to (issue 37), by their sidebar keys: every
playlist line whose read holds it (`playlist:<ref>`, playlists.txt order; a line not read this time by its last stored
read, else by the songs' folder), then the folders its file sits in, outer to inner (`folder:<path>`: the watched import
folder, each crate of it shown in the sidebar that holds the file, or a Library folder no playlist uses; a file in a
playlist's own Library folder is in no folder). Sync leaves a row out only when every collection in it is switched off
(a folder by its own switch and those of the folders around it); a row with an empty `in` has nothing that can switch it
off. The preview's `collections` names each of them. `api.sync_preview` passes `views.song_places` (watched folders,
crate visibility).
A row's `run` is its index in the order the sync works through them (bought files, then downloads, then weekly checks;
inside each, playlists.txt order). Downloads of tracks in the "never download" list are not in `groups` but in `never`
(same rows, without `run`); marking or unmarking a track moves it at once, without reading Spotify again.
`estimate.duration_min` counts only the downloads that fit into today's Qobuz allowance (`min(qobuz_needed, qobuz_left)`
× 70 s, rounded to 5 min): the rest is queued at once and waits for the next sync. `estimate.accounts` says which service
the downloads are expected to use, one entry per set-up service in quality order (`uses` null for an account behind
Qobuz, which only gets the tracks Qobuz lacks; `about` true for every service but Qobuz: an estimate); the `qobuz_*`
fields are kept for one release. `estimate.minutes_by_downloads[n]` (the preview only, not the dashboard's) is the time
for `n` downloads, `n = 0 … qobuz_uses` (the most any ticked subset can run today), and each account's
`uses_by_downloads[n]` its `uses` for `n` downloads (the engine's `views.split(n, …)`): the page looks up the count of the
actions the user ticked (a larger count takes the last entry), so the formula (70 s a download, rounded to 5 minutes)
and the split are in the engine only (`views.minutes_by_downloads`) and ticking needs no bridge call.

`refresh(auto=false)` → `{"job_id"}` — read-only playlists read: "↻ Read playlists", and by itself whenever
playlists.txt changes on disk (mtime or size, checked every 2 s; retried until no hub sync blocks it). `auto=true`: the
session's one automatic read (the hub when it opens; the Sync page when it opens and `read_status.auto_read` is still
false, e.g. the hub's own read could not start). It sets `read_status.auto_read` when it starts; later `auto=true` calls are
refused (`refused`), so a stopped or failed automatic read is never redone by itself. Each playlist read emits
`ReadingPlaylist`. Outcome: `JobFinished` kind `refresh`, result `RefreshResult` (`{actions, read_id}`; a read that could not be stored, e.g. the library was busy, ends `failed` since the plan is derived from the stored read); on problems (`offline`, ...) the
last preview stays with `read_status.problem` set.
`stop_refresh()` → `Stopped` (`{"stopped": bool}`; `stop()` and `stop_sign_in()` answer it too). The read's `JobFinished` (`stopped`) comes at once, also while one slow
Spotify request is still under way; that request's late answer is dropped (the last preview stays).

`job_status()` — snapshot after a reload. `sign_in` is null or the browser sign-in's snapshot, the same shape as `job` (see
Settings). `job` is null or a `JobSnap`: the events are not shapes (`tests/fixtures/hub_events.schema.json` pins them), so
`last`, `results` and `finished` hold them as events.ts `HubEvent`s.
Shape: `JobStatus` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
`batch_kind` is set for an AIFF batch job (kinds `upgrade_batch`, `aiff_batch`, `batch_resume`, and the
one-after-the-other `upgrade_add_new` / `upgrade_discard`): `"upgrade"` for Same track (`upgrade`, `upgrade_all`, add as
new, discard), `"convert"` for what Convert, Give it its clean name, Make all and the CDJ group's Convert all start, and,
for `batch_resume`, the stopped batch's own kind (`upgrade` / `convert` / `mixed`), so a reloaded window can tell a
resumed Convert batch from Same track's. The `JobStarted` event carries the same `batch_kind`, so a snapshot built from
the live event says what `job_status` says after a reload. `usage` has the newest `AccountUsage` event of each service, in
the order the services first reported (`last` keeps only the newest one overall) — the "Qobuz 42 of 80 today" lines after
a reload. `actions` are the run's planned actions in the order the run does them (copied from `RunStarted.actions`) —
"Up next" and the time left after a reload.

`library(view="all", key=null, query="", filter="all", sort=null)` — one view of the library. `view`: `all` (All
tracks), `unlisted` (Not in a playlist), `playlist` (`key` = the playlist's folder name, any case) or `folder` (`key` = a
folder's snapshot path: `Library/<name>` for a Library folder, the absolute path for a watched folder or a crate). A
playlist or folder view without its `key`, an unknown view or filter is `refused` ("view must be one of …"). A playlist or
folder that is not there (any more) is no error: the answer has `empty: "gone"`, `rows: []`, `subtitle: []`. filter:
`all|lossless|good_lossy|weak|fake|upgrade_ready`. sort:
`title|artist|length|source|quality|added|folder|order` (folder: tracks in no playlist last; `order`: the playlist's own
order, its read record's; outside a playlist it means `artist`), prefix `-` for descending; `null` = the view's own
order (`order` in a playlist, else `artist`).

*What the views list.* All tracks, Not in a playlist and the folder views list files. A folder view lists the files at
or below its path (a path match with a `/` boundary, NFC: `Old Sets 2` is not in `Old Sets`). A watched folder is a view
even when it holds no file yet; any other folder without a file, and a path that is none of the kinds, is `gone`.
`not_lossless/` directly under a Library folder is never a crate or a subfolder. A **playlist** view lists the songs of the
playlist's read record in the record's order, each once; the record is what the last successful read found, so the view
shows what the playlist holds now, not where the files are. A song of the record without a file is a row too:
`file_state` `no_file`, `path` `null`, `wait` `waiting` (the sync has yet to get it) or `not_found` (the sync found
nothing usable: the song is in To-do's Not found group). A not-found song the user hid in To-do keeps `not_found` and
carries `hidden: true`: the page doesn't offer "Open in to-do" for it, as To-do doesn't show it. `also` holds the files in the playlist's own Library folder
whose song the playlist does not hold (null in every other view), by artist, then title. The search narrows `rows` and `also` (artist and title, case and accents ignored: `names.search_fold`, as the command line's `track find`); the quality
filter, the quality `chips` and `summary` count only the rows with a file; `chips.all` counts every row the table lists
under All (a read playlist's songs without a file too, never `also`), so the All segment says 18 beside 18 rows. A
playlist's `subtitle` and `summary.tracks` count its songs with a file, the table also shows the waiting ones, and the
sidebar's `songs` counts them all (so the page's strip names both, "13 of 18 downloaded", from `songs`, and the header
leaves out the subtitle's count, rather than let the numbers seem to disagree). An empty folder, and a playlist that was
read and holds nothing, both come with `empty: "no_match"` even without search text; the page tells them apart by
`view`, `folder_kind` and `read_at`.

*Rows.* Shape: `Library` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
A row with `sound_checked: false` (an imported file whose sound isn't judged yet, `import_state` `identified`) is left out of
the quality chips (Lossless, Good lossy, Weak, Fake), of `summary.by_quality` and `summary.lossless_share` (a share of the
checked files), and it sorts after every checked file by quality; it still counts under All and in `summary.tracks`.
`file_state` is read now exactly as `track()`'s (below: the live away set of the import folders, a stored `online = 0`
stays `offline`), but per watched folder only: a row whose file waits as missing (issue 43, "Missing files" below) says
`file_missing` from its stored mark, no disk check, after the offline checks (a drive that is away says `offline`). A row
that isn't `here` doesn't play (Enter, double-click and its cover do nothing). The same holds for `dashboard`'s
`lossless_share` tile and folder bars (`by_quality`, `lossless_share`; `tracks` stays the whole count), and the to-do
list holds no such file (but the Missing files group: its items say `file_missing`). The user's own songs (the import)
are in no folder: their rows have `folder: ""` and `in_playlists: false`, they show in All tracks, Not in a playlist and
the folder views, never under a playlist folder. `also` rows carry the same fields.
`key` is echoed as the request had it (the playlist's folder name as `playlists.txt` spells it, or the folder's path);
`folder` keeps the old meaning (`null`, `"__not_in_playlist__"`, the playlist's folder name or the folder's key).

*Subtitle.* `subtitle` is the header's second line as parts in order of importance (the page drops the last parts first
when it is too long; `1 track` for one): All tracks `["{n} tracks", "every folder"]`; Not in a playlist
`["{n} tracks", "in no playlist"]`; a playlist `["{Service} playlist", "{n} tracks", ("switched off",) "Library ›
{folder}"]`, or `["{Service} playlist", "not read yet"]` while it was never read (the service leads both: it is the
one part the view says nowhere else in words, so it is the last to drop; the header keeps the first part whole); a Library folder no line uses
`["{n} tracks", "no playlist uses it", "Library › {name}"]`; a watched folder `["{n} tracks", ("Offline: connect the
drive" | "Folder not found",) "{k} folders with music", "{place}"]` (the folders part is left out at none; `{place}` as
the sidebar's `place`); a crate `["{n} tracks", ("Offline: …" | "Folder not found",) "{tip}"]`. An away folder (the
innermost watched folder holding it is offline or not found) puts its words second.

`track(track_id)` — details panel (Library and To-do). The answer is `{track: TrackDetail}`.
Shape: `TrackAnswer` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`track_link`: `url` is the track's page on the service it was read from: the link of the first fetched track (playlist order) that is this song, else the link its key gives (all four services; null for a key with none: SoundCloud's is its player page `https://w.soundcloud.com/player/?url=…/tracks/{id}`, YouTube Music's `https://music.youtube.com/watch?v={id}`; a fetched SoundCloud track carries its real `permalink_url`). The hub shows the service's logo beside "Open in …" from `service`, never from the label's words.
`playlists` matches a song by its key and aliases (tokens), so a Qobuz song lists its folders too.
`upgrade`: Swap only when `swap_safe && swap_possible`. `cue_text` combines the measurement with `swap_possible`: exact/shifted on a file that can be swapped says the cues stay; on one that can't (MP3, WAV: "Add as new file" is the only way in, which rekordbox sees as a new entry) it says it is the same edit but a new rekordbox entry, and that relocating the old entry to the new file keeps its cues; a mismatch or unknown keeps its own line (the Library's card shows it). `format_line` of the upgrade is the parked version's quality in the words of the current file's `source_format_line` ("FLAC · lossless", "AAC · 256 kbps"): the To-do panel's New beside Now. The To-do row's `detail` for `upgrade_ready` is a short line (`views.upgrade_status`): "Lossless ready · cues can stay" (swap possible), "· new rekordbox track" (same edit, no swap), "· different edit", "· not compared" ("256 kbps ready · …" for a better lossy stream); the To-do panel words the rest from `alignment` and `swap_possible` (todoModel.upgradeWays).

The media server (`audio_url`) answers `Access-Control-Allow-Origin: http://127.0.0.1:<window port>` to requests from the
page's own origin, and nothing (never `*`) to any other: the compare player `fetch()`es both files to decode them, and
the page and the server run on different ports. A CORS preflight (`OPTIONS`) is answered the same way.

`track()`'s words: `free_downloads` are the artists' free downloads found on SoundCloud while the track is not lossless; `quality_line` of a lossy download carries the bitrate when known ("YouTube Music OPUS 135 kbps · cutoff 20.1 kHz"); `cutoff_text` of a fake lossless file names the format of the file's extension ("16.0 kHz · where the highs end · a lossy file inside the WAV", else "a lossless file"). A dropped bought file may be WAV, AIFF, FLAC or MP3. `format_line` is the file itself: a download is always `"AIFF · 16-bit"` (every download is converted), an own or bought file names its container by its extension (`AIFF`, `WAV`, `FLAC`, `MP3`, `AAC`, `ALAC`) plus the bit depth when its stored codec is a PCM one (`"WAV · 24-bit"`; a FLAC or MP3 stays `"FLAC"`, `"MP3"`); `source_format_line` is what a download was made from (the bitrate only for a lossy download). `source_how` is stored in `library.db` as `files.source_how` (schema 5) and travels with the file: a parked upgrade carries it as `how`, a Swap or Add as new file moves it into the entry and an undo puts the old one back; the UI words it in `copy.ts`. For a file with `sound_checked: false`, `quality_line` ends "sound not checked yet" instead of "verified lossless" ("Your own file (PCM) · sound not checked yet"; a lossy codec: "Your own file (MP3) · lossy, sound not checked yet").
`track()` also carries `file_state` (2026-10-29, replaces the boolean `online`): `here`, `offline` (the file's drive is
not connected), `folder_missing` (its watched folder is not found: moved, renamed or deleted while the drive is there)
or `file_missing` (the folder is there, the file's path is not: it went since the last scan, or its row waits as
missing: the stored mark of issue 43). Away is read now, not
from the last scan: an import folder is away when the scanner's rule says so (`scanner.away_reason`: `unmounted` when
its `/Volumes/<drive>` is not mounted, else `missing` when the path is not a folder; checked live once per request, like
`watched_folders()`'s states), so an unplugged drive counts before any scan has seen it; the innermost watched folder
holding the file decides. A file row that says `online = 0` and lies in no away folder stays `offline`. `file_missing`
is checked for this one track (`Path.exists()`) in the api, and also holds for a row marked missing (after the offline
checks). A track without a file is `here`. For every state but
`here` `audio_url` is null too: the panel says the words where the picture would be ("Offline: connect the drive" ·
"Folder not found" · "This file isn't there any more."), keeps the player off, requests no spectrum and offers no Show in
Finder. `todo()` question and duplicate sides (`FileSide.online`) mean `here` by the folder rule only (and carry no
`audio_url` when false). The `detail` of lossy and fake rows is the source and bitrate ("YT Music · 131 kbps", "Qobuz"), as the badge already says the kHz.

`todo(filter="all", show_hidden=false)` — filter: `all|rekordbox_check|missing_file|same_song|duplicate|upgrade_ready|cdj|not_found|weak|good_lossy|fake|other` (any other word is `bad_args` / `usage`).
Groups always in that order; `chips` counts exclude hidden; `hidden_count` for "Show hidden (N)". The import adds two
groups after the first (see "Watched folders and the import" below): `same_song` and `duplicate`, whose items also carry
a `pair`; the user's own songs (`local:<n>`, in no playlist) are on To-do only under `upgrade_ready`, `missing_file`
(issue 43), in a question and in a duplicate group (their quality is for the Library to show). First group
`rekordbox_check` (label "Check in rekordbox", hint "the file changed; rekordbox needs a hand"): every track with a
`rekordbox_check`, also hidden tracks and tracks no longer in a playlist; `detail` is what to do in rekordbox ("This
track now plays the right song. In rekordbox: analyse it again and delete the old cues (they belong to the wrong
song)." / "This is a different edit. In rekordbox: analyse it again and set the cues again." for a real mismatch, no
measurement or an old record; "This is the same edit. In rekordbox: relocate the old entry to the new file, its cues
fit." when the two files were measured as the same edit; the two `swapped` texts after a swap); its button calls
`rekordbox_checked(track_id)`. Its items also carry `can_undo` (bool): the check belongs to a swap or an added file
that `undo_upgrade(track_id)` can still put back (the track still has that file and no newer version waits; whether
the files changed is checked when it runs). False for every other check and for upgrades from before undo existed. A track can be in two groups (e.g. Check in rekordbox and Not found); `chips.all`
counts each track once, `chips.rekordbox_check` every check item (hidden ones too; a batch is one item). `check_tracks`
counts the same checks as **tracks**: a batch counts its `size`, hidden tracks too, whatever the filter. The page header
says "{n} tracks to check in rekordbox" from it, and "{n} tracks are not lossless yet" from the sum of the chips of the
groups below lossless (`upgrade_ready`, `not_found`, `weak`, `good_lossy`, `fake`, `other`), never from `chips.all`.
`sub` (`string[]`, amended at FC) is that header line itself, worded by the engine (`views.todo_sub`) as parts in order
of importance: "{n} tracks are not lossless yet", "{n} questions about your files" (`same_song` + `duplicate`), "{n}
tracks to check in rekordbox" (`check_tracks`), "{n} files won't play well on CDJs" (`chips.cdj`), "{n} songs are
missing their file" (`chips.missing_file`), each with its own singular ("1 track is not lossless yet", "1 question about
your files", "1 track to check in rekordbox", "1 file won't play well on CDJs", "1 song is missing its file") and only
when its number is above 0; `["Nothing to do"]` when none. The page shows the parts and drops whole ones where they don't
fit; the command line prints them joined by " · " on a "Summary" row of `todo list`.
`empty_text` is `empty`'s words for the command line (`all_lossless` "Everything is lossless.", `all_hidden` "Only hidden
tracks are left.", `nothing_here` "Nothing here."), null when `empty` is null; the window keeps its own copy until phase 6.
Shape: `Todo` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`playlists()` — rows top = highest priority.
Shape: `Playlists` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
`playlist_id` is the playlist's **ref** (a Spotify id stays bare, every other service's is `<service>:<id>`: `qobuz:<id>`,
`soundcloud:<user>/sets/<slug>` or `soundcloud:<user>/likes` (the link's path, lower case), `youtube_music:<list id>`); the page keys rows by it. `service` is one of `spotify|qobuz|soundcloud|youtube_music`, `service_name` is "Spotify",
"Qobuz", "SoundCloud" or "YouTube Music". `info.hint` words, always set once `info` is, what the row's service says for a playlist it won't show (Spotify:
"Follow ≠ own: make your own copy in Spotify."; Qobuz: "Make it public in Qobuz, or use one of your own playlists."; SoundCloud: "Make it public in SoundCloud, or use its private share link."; YouTube Music: "Set it to public or unlisted in YouTube Music."). `info.owner_name` is `""` when the name already says it (a SoundCloud likes list is named "{username}'s likes"), so the page names the owner once.
`needs_setting` (sources round) is `"read_liked_music"` for a listed YouTube Music Liked music line (`youtube_music:LM`, on or off in the file) while Settings' choice is off or no YouTube login is set up (the row reads "Liked music is off in Settings", it is not read and raises no problem), else `null`.
`info` is null until read (refresh or add_playlist); `tracks` is null when neither the tracks nor the playlist's count were read
(the row then shows no count). `quality` is always the five counts, all 0 while the playlist's tracks were not read (a
switched-off playlist is never read), never null: the row reads it when it is switched on. `version` must be sent to
`save_playlists`. `overlaps` is for the panel when nothing is unsaved: each track that is in several switched-on
playlists, with `folders` (in list order) and `lands_in` (the first). `problem` is what the sync would say about the file.
`tidy.waiting` counts what a tidy-up would tick by default (`planner.out_of_place`: files the playlist order puts
elsewhere, not placed by the user); the page's "Tidy up files" badge.

`limits(service="qobuz")` — the Download limits page. `service`: `qobuz|youtube|soundcloud` (else refused).
Shape: `Limits` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
`cards` are always all three services in quality order; a service that is not set up has zeros. `usage` is null when
`service` is not set up, else the page of that service: `days` are 14 entries oldest first; `zones` are 5 entries (Qobuz
and SoundCloud: careful 1–40, normal 41–60, faster 61–79, fast 80–100, risky 101–500; YouTube: careful 1–20, normal
21–30, faster 31–45, fast 46–60, risky 61–500); `recommended` is 60 Qobuz, 30 YouTube, 60 SoundCloud. `behind` is "Qobuz"
for an account while Qobuz is set up (it only gets the tracks Qobuz lacks; `still_to_load` is then all null and
`what_if.days_to_load` null), else null. `signals` are those of the last 14 days (`new`: after the time in settings.json
`warnings_seen[service]`, or never marked; `clears_in`: days until it leaves the 14 days, 1 = tomorrow);
`signal_summary` has a count for every kind of the service: Qobuz `login_failed, search_failed, download_rejected,
preview_only, duration_mismatch, auto_stop`; YouTube `cookies_unreadable, bot_check, rate_limited, refused,
premium_missing, download_rejected, auto_stop`; SoundCloud the same without `bot_check`. A card's `paused` is an
`auto_stop` today; `warnings` counts the signals of the last 14 days, `new_warnings` those after the last "Got it".

`limits_what_if(service, limit, extra_today=0)` — "What N per day means" while the slider moves (no write). The service
must be set up (else refused "Set up YouTube Premium first."); `limit` 1–500, `extra_today` 0–200. For an account behind
Qobuz `days_to_load` is null.
Shape: `WhatIf` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`runs()` → `Runs` (`{"runs": [RunSummary, newest first]}`). `run(run_id)` (the command line also says `report:<id>` or `last`, the newest report) → `RunAnswer` (`{"run": RunDetail}`), the end screen.
Shape: `RunAnswer` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
Every row with a `track_id` except `queued` carries `cover_url` (the file's own cover, else Spotify's, else null).
`section_labels` are the report's own title of every section (`report.SECTIONS`; the end screen's part of the placements
reads `placed_missing`) and `part_labels` the titles of the Auto-upgrade parts that hold rows of more than one section
(`report.PART_LABELS`: `upgraded`, `waiting`, `refused`); the window prints them as they are.

`spectrum(track_id, which="current")` — which: `current|upgrade`; answers `SpectrumAnswer` (`{"spectrum": Spectrum}`).
Shape: `SpectrumAnswer` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
`data` is base64 of `cols*bands` bytes, row by row in time, each row low→high frequency (band width `max_hz/bands`); byte v → dB
= `floor_db * (1 - v/255)` (0 dB = loudest cell). Draw the cutoff line at `cutoff_hz` (null = none). `waveform` is base64
of `cols` bytes, one per column (the same columns as the matrix): the largest sample anywhere in that column's stretch
of the track (1/`cols` of its length), 0 = silence, 255 = the loudest column, linear. A kick's attack shows as its peak;
the matrix's mean energy would not show it. Files cached before the field existed are made again.

(`media_url` is gone, issue 39 V2.5b: no page called it; a row's `audio_url` is the playable address. Its command-line
row answers the `dropped` refusal.)

`setup_status()` — what is set up; open the wizard when `complete` is false. Unbound (no music folder yet) `playlists`
and `complete` are false. `downloads` is Setup's Downloads step (Qobuz and the other download logins): done when Qobuz is
signed in or left out (`qobuz_skipped`; `qobuz` itself stays false). Setup's "Your existing music" step (after `music`)
is not among the required steps: `existing` (an import folder is watched, or `import_skipped`, set by
`setup_skip_import`) never changes `next_step` or `complete` and never blocks Continue. `auto_upgrade` is false too when
settings.json can't be read, because a sync can't start from it. A skipped Spotify (`spotify_skipped`) counts the
`spotify` step as done and is no problem in the read status unless `playlists.txt` has a Spotify line (`services` lists
only the services the lines use); connecting Spotify (`setup_spotify_login`) clears it. `youtube_music.liked_music` only
counts with a YouTube account: forgetting that login turns it off for good; `set_read_liked_music` changes it,
`add_liked_music` lists it. It never carries a secret, only whether it is there.
Shape: `SetupStatus` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

### Tidy-up and the move log (read, any time; in `LIBRARY_METHODS`)

`tidy_preview()` — every file the playlist order puts somewhere else ("Tidy up files"). Each row is a track row (as
`library()` rows) with where it is and where it goes; a `skip` (`offline` "Offline, skipped", `not_found` "Not where
Discjockey last saw it", `name_taken` "A file with this name is already in {to}") means the row cannot be ticked; `ticked`
rows move by default (no `skip`, placed by the app). `empty` is the text shown instead of the list: "Every file is where
the playlist order puts it." with no rows, or "{n} files are where you put them, not where the playlist order puts
them." when only `yours` rows are left (the button then stays usable). `yours` is the "You put these here" group of the
list with its one control "Put these in playlist order too" (ticks every movable row of the group).
Shape: `TidyPreview` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`move_batches()` — the 20 newest move batches, newest first, and how many there are in all (`total`); empty while
nothing was ever moved. `title`: "Tidy-up", "Saved playlists", "Renamed {old} to {new}", "Undo of: {title}"; `moved` counts
the files moved (a folder rename counts the files it carried); `undoable` is how many moves an undo could still make
today (0: the Undo button reads "Nothing left to undo"); `summary` "{n} files moved" / "1 file moved", plus " · {k} not
moved".
Shape: `MoveBatches` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`undo_preview(batch_id)` — what undoing a batch would do, move by move (a batch the log does not know: `refused`,
"Discjockey has no record of that tidy-up."). A row's `skip` is as above, plus `moved_on` "Moved or changed since" / "The
folder {new} isn't there any more", `place_taken` "Another file is in its old place now" / "A folder called {old} is in
your Library again." / "Another playlist is called {old} now.", `playlist_renamed` "The playlist isn't called {new} any
more". For a folder row `files` is how many files are in the folder now, else the count the rename carried; for a file
row it is null. `warning` holds the lines for the confirmation (rekordbox; for a folder rename also that the folder and
the playlist get their old name back); `nothing_left` true: the page then offers no Undo.
Shape: `UndoPreview` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

### Read with network (refused with `sync_running` while any sync runs)

`search_candidates(track_id)` — the versions the sources offer for a song. The current version is first (`current: true`,
"you marked it as wrong" when `rejected`); colour `length_diff_s` green within ±3 s. Send a Candidate back unchanged to
`preview` / `use_candidate`.
Shape: `Candidates` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`preview(track_id, candidate)` — 30 s AIFF for youtube_music/soundcloud/youtube only (`can_preview`); qobuz → refused
"Qobuz versions have no preview." Plays 20 s of it in the UI.
Shape: `PreviewAnswer` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`add_playlist(url)` — pasted link, a playlist of Spotify, Qobuz, SoundCloud or YouTube Music (`sources.recognise`); its info and tracks are read
through that service's reader. The link is first run through `sources.expand`: a short SoundCloud link (`on.soundcloud.com/…`) becomes the set's or likes list's link, and `soundcloud.com/you/likes` becomes `<your permalink>/likes` through the SoundCloud login of Settings (the stored line then needs no login; this may ask macOS for the browser's Keychain access). A failure there (or in the read) is an ordinary `ok: false` answer with its `kind` and `service`, never a rejection.
Shape: `AddedPlaylist` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
Add the row with `link` and `suggested_folder` (editable). `hint` (when not readable) is the service's words, the same as
`info.hint`. The answers that are not ok carry the service:
`{"ok": false, "kind": "playlist_unreadable", "service": "qobuz", "message": "Qobuz doesn't show this playlist. It
must be public or one of yours. Check the link."}` (a Qobuz playlist Qobuz won't show), and
`{"ok": false, "kind": "not_set_up", "service": "qobuz"|"spotify", "message": "Connect Qobuz first."}` (that service
isn't connected: nothing is read; SoundCloud and YouTube Music need no login), and, with the words of the engine,
`{"ok": false, "kind": "playlist_unreadable", "service": "soundcloud", "message": "SoundCloud doesn't show this playlist. It may be private or removed; for a private set, use its private share link."}`,
`{"ok": false, "kind": "playlist_unreadable", "service": "youtube_music", "message": "This is a YouTube mix, which changes every time it plays. Save its songs to a playlist and paste that link."}` (a mix, or liked videos / Watch later: the YouTube Music reader refuses them before any request),
`{"ok": false, "kind": "setting_off", "setting": "read_liked_music", "service": "youtube_music", "message": "Reading your Liked music is off. Turn it on in Settings."}` (a `list=LM` link while the choice is off, or on without a YouTube login: nothing is read, there are no other facts; the page shows its "needs a setting" form named `Liked music`, owner `yours`). While it is on, the link is read through the YouTube login like any playlist and answers the normal found card (name, owner, count); while the YouTube account is paused today (a bot check or too many requests recorded for it) the answer is `{"ok": false, "kind": "offline", "service": "youtube_music", …}` before any request, and a bot check met by this read is recorded as that account's warning sign,
`{"ok": false, "kind": "login_expired", "service": "soundcloud", …}` and `{"ok": false, "kind": "offline", "service": "soundcloud"|"youtube_music", …}`. A link that is no service's is `refused` without `service`: "That isn't a playlist link Discjockey can read. Open the playlist in Spotify, Qobuz, SoundCloud or YouTube Music, choose Share, then Copy link, and paste it here."

`preview_playlist_change(lines)` — `lines`: `[{"folder", "link", "enabled"}]` in the new order (top first).
A switched-on line whose playlist was not read yet is read once, through its own service's reader; a service that
isn't connected, or a playlist its service won't show, is skipped without an error (that line then counts as unread). A Liked music line while the choice is off or the YouTube account is paused is not read either.
`headline` is ready to show (for `moves` and `rename` it is "{n} files would sit in a different folder" / "1 file would
sit in a different folder"); `checklist` is 3-4 lines (for `moves` and `rename`: the downloads line, "Nothing is deleted",
"Files move only if you choose to", "Moves can be undone on this page"; for the other kinds "Happens at the next sync, not
right away").
`switch_off`: a playlist is switched off by this edit and nothing else changes (also when none of its songs was read:
`stopped` 0); its `headline` is "Left out of the sync, its files stay" (as Sync's switch: nothing is downloaded for it, no
file is deleted or moved). `folders` lists a switched-off playlist's folder with `after` 0, because the counts are made of
the playlists that are on; the page does not show it as a folder whose files change.
`tidy` has the files with a place this change would put elsewhere (each a row of `tidy_preview()`; `by_rename` names the
old folder whose rename on disk would put the file at its target, else null). `renames` has one offer per playlist whose
folder name changes other than in case and whose old folder is in `Library/`: `offered` false means the page shows
`why_not` ("A folder called {new} is already in your Library." / "{old} is still the folder of another playlist.")
instead of the choice; `option` "Rename the folder on disk too", `detail` "One folder move instead of {n} file moves.".
`reroute`: only tracks without a file yet change folder ("24 tracks will go to 03_06_2026 instead of Powertrance"), no
file moves; `problem`: what is wrong with the lines (Save would be refused), else null. The old `moves` list is gone.
Shape: `ChangePreview` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

### Write jobs (→ `{"job_id"}`; outcome in `JobFinished.result`)

Every write method answers `{"job_id"}` at once and the job ends with exactly one `JobFinished`: `ok` true with its
`result`, or a `problem` kind (the table above) with a `message`, and for some kinds a `result` that still carries what was
done (`stopped`, `rekordbox_open`, `busy`, `refused`). A job's success can carry words in `JobFinished.message`, empty
otherwise (the import's "Imported 3 files."). A job that crashed has `result` null, except a crashed sync (see below).
Stop (`stop()` → `{"stopped": bool}`, not a job) stops the current write job safely: what was done is saved, the job ends
`stopped` and still carries its result so far. The result of each job kind is its shape: `RESULTS` in
`discjockey/hub/shapes/` maps the kind to it (`schemas.gen.json` `results`), and the method's own entry in `ANSWERS` names the
same shape. Rules per method:

**`rev` and `expect`.** Every `TrackRow` (so every read of a song) carries `rev`, 10 hex characters of the record's `models.snapshot` (status, path, the source and source id of the file that stands, and the parked file with its source, source id and found date; null for a row with no record, a duplicate group or a batch). The single-track writes (`hide`, `add_bought_file`, `use_candidate`, `use_link`, `reject_current`, and `upgrade` for one song) take an optional last parameter `expect`, the command line's `--if-rev`: when given and different from the record's `rev` now, the write is refused `changed` with reason `rev_changed`, `data.rev` the current rev, and nothing is done; without it the write acts on the record as it is (a song that is gone is `changed` either way). The window sends the `rev` of the row it acted on; the hub keeps no memory of what a page showed.

(The import's jobs — `add_watched_folder`, `start_import`, `remove_watched_folder`, `answer_same_song`,
`keep_duplicates`, `keep_file` — are in "Watched folders and the import"; `setup_skip_import`, `set_favourites` and
`set_crate_shown` are brief saves.)

| method (positional args) | job kind | rules of its outcome |
|---|---|---|
| `start_sync(selected)` — list of ticked `key`s from `sync_preview` | `sync` | with the switch on, the run's last phase is Auto-upgrade: it sends `BatchProgress` events and the report's `.json` carries `auto_upgrade`, see below; with the switch off the phase still runs for the placements of missing songs (issue 43), alone, see "Auto-upgrade"; a `crashed` sync still carries its result (`exit_code` 1, `report` its crash note, `actions` 0 when it crashed before the plan) |
| `save_playlists(lines, loaded_version, files = null)` — `files` answers the save question when the change retargets files: `null` (nothing to ask) or `{choice: "leave"\|"move", renames: [[old, new]], moves: [[file_id, from_path]]}` (`from_path` as `preview_playlist_change`'s rows send it). `leave` makes the files this save would have moved the user's own placement (a later tidy-up lists them apart); `move` renames the chosen folders on disk (one batch each), then moves the chosen files (one batch). A malformed `files` is `refused` before a job starts | `save_playlists` | problem `changed` = "playlists.txt was changed elsewhere…". A Stop after the save ends with problem `stopped` and the same result |
| `tidy_up(moves)` — `moves`: `[[file_id, from_path]]` from `tidy_preview` rows (not empty, else `refused`); each file moves only if it still looks as shown | `tidy` | a Stop ends with problem `stopped` and the batch so far as `result` |
| `undo_moves(batch_id)` — undoes a batch as a batch of its own | `undo_moves` | an undo with nothing left to move has `batch_id` null; a Stop as for `tidy` |
| `save_limits(service, limit, extra_today)` — the service must be set up (else refused); 1–500, 0–200 (0 clears the extra) | `save_limits` | |
| `mark_warnings_seen(service)` — "Got it" on Download limits; the service must be set up (else refused). Saves settings.json `warnings_seen[service]` = now: its signals up to now are no longer `new` | `mark_warnings_seen` | |
| `hide(track_id, hidden, expect?)` | `hide` / `unhide` | |
| `never_download(track_id, never)` — the track must be in the current preview (else `changed`) | `never_download` | |
| `add_bought_file(track_id, path, expect?)` — `path` is an absolute path of a file this process can read (the `path` of a `FileDropped` with `readable: true`, or any file a command names); refused (`refused`, before a job starts) when there is no file at it or macOS doesn't let Discjockey read it; nothing is remembered between the drop and the call, so "Add" can be tried again with the same path | `add_bought_file` | |
| `use_candidate(track_id, candidate, expect?)` | `use_candidate` | |
| `use_link(track_id, url, expect?)` — Qobuz track / YouTube / YT Music / SoundCloud link | `use_link` | |
| `reject_current(track_id, expect?)` — "None of these"; sets `rekordbox_check` (`wrong_song`) | `reject_current` | |
| `rekordbox_checked(track_ids, batch_id?)` — "Done, checked in rekordbox" for a list (a batch card sends its done tracks): clears `rekordbox_check` and with it the undo. `batch_id` (the command line's `--batch aiff:<n>`; `track_ids` is then `[]`, both is `refused`, an unknown batch `refused`): the tracks that AIFF batch did; the window sends none | `rekordbox_checked` | `changed` when none of the named tracks had a check (the result still lists them as `not_checked`); the command line's own api finishes that job `ok` instead, `check done` answers `ok` with total 0 and the tracks as `skipped` rows |
| `upgrade(track_ids, mode, plan_id?, expect?)` — `same_track\|new_track\|discard`, a list (one track is a list of one; a string, an empty list or an unknown mode, `swap` and `add_new` included, is `refused`). `same_track` is **Same track for any format** and runs one AIFF batch; `new_track` / `discard` run the list one after the other | `upgrade_batch` (same_track) / `upgrade_add_new` / `upgrade_discard` | One song with `expect` is checked first (`changed`, reason `rev_changed`); more than one song with `expect` is `bad_args` (`usage`, "--if-rev takes one song."). One-track `new_track`/`discard` also refuse a song that is gone, and a failure ends the job with its own words. A batch ends as a problem that still carries the batch in `JobFinished.result`: `stopped` ("Stopped after {done} of {total}."), `rekordbox_open`, `busy` (another window or the Terminal holds `rekordbox.lock`), `refused` (nothing in it could be done; each reason in `results`). A batch of one track that meets rekordbox open or `busy` before anything ran is closed (`state` done, the item skipped `rekordbox_open`/`busy`), so no Resume is offered; a bigger batch stays `stopped`. `plan_id` (the command line's `--plan`, `same_track` / `new_track` only; `discard` refuses it): only the songs of that plan that still stand run, the others are `skipped` with reason `changed`, and `new_since_plan` lists the songs the plan did not have; an unknown plan is `bad_args`, an old one `refused`, a plan with nothing standing `refused` (`changed`). |
| `upgrade_all(plan_id?)` — Same track for every parked upgrade the To-do group counts as possible (`all.n`); `refused` ("None of these can be upgraded right now.") when none. The command line's `upgrade_all` also refuses (`refused`, reason `not_stopped`, `next: batch resume aiff:<n>`) while a stopped upgrade batch waits; the window's does not (it hides the button) | `upgrade_batch` (started by `upgrade_all`) | |
| `batch_resume(batch_id)` — the planned tracks of a stopped batch, eligibility asked again; `refused` for an unknown batch or one that is not stopped | `batch_resume` | |
| `batch_undo(batch_id)` — every track the batch did, newest first. For the command line (`batch undo aiff:<n> --yes`); the hub's batch card and its "Undo all {n}" send `undo_upgrade` over the card's own undoable tracks (`batch_undo` would also try tracks already marked Done and list them as refused) | `batch_undo` | `rekordbox_open` (nothing undone, every track `waiting`) or `stopped` carry the result; `refused` when nothing could be undone |
| `undo_upgrade(track_ids)` — "Undo" on `can_undo` items, a list, newest first (the order of the steps in operations.log, then batch/row id: timestamps are only seconds), one job: puts a swap, an added file or a Same track back (the upgrade waits again). Needs rekordbox closed where a step wrote it. Gone once `rekordbox_checked` ran | `undo_upgrade` | the job is `refused` (with the one track's own words, or "None of these could be undone.") when nothing was undone, `rekordbox_open` when rekordbox runs |

`rescan_library` answers like every write method: `console` ("A sync is running in the terminal. Wait until it has
finished.") while a terminal run holds the lock, `busy` ("Discjockey is still busy with the last change. Wait until it
has finished.") while another write job runs. While a scan runs (the `scan` job, or the scan that `sync_preview` runs
first) every write method answers `busy` with "Discjockey is checking your Library. Try again in a moment.". `scan` is the
job kind for `JobStarted` / `JobFinished`; it has no `track_id`. `library scan --json` prints the job's result. Issue 43:
nothing a song has is decided by one scan; a song whose file the scan does not see waits as missing and To-do lists it.

`use_candidate` / `use_link` are refused (problem `refused`) before any request to Qobuz (no login, no link lookup,
nothing counted) with the messages of `ops.refusal`: "This is the version you have now." (the candidate is the
current file); "Your current file is not where Discjockey expects it. Run a sync first, so it can find the file again."
(the file was moved in Finder); for Qobuz versions while Qobuz is paused "Not downloaded: Qobuz is paused, because
several Qobuz requests in a row failed (a warning sign for the account). Discjockey sends Qobuz nothing more until the
next sync starts. A YouTube Music or SoundCloud version still works."; and when the daily limit is used up "Not
downloaded: daily Qobuz limit reached. Try again tomorrow, or allow a few extra downloads on the Qobuz page." When the
old file was moved away to Superseded/, the entry gets `rekordbox_check` (`wrong_song`).

`upgrade(track_id, "new_track")`: the current file moves to `Superseded/<Folder>/` and the new lossless file gets the
correct name `Library/<Folder>/<Artist - Title>.aiff` (no "(lossless)"; an ID suffix only if another file has that
name); the entry gets `rekordbox_check` (`added_as_new`, with the measurement of the two files: `match`,
`offset_ms`, `aligned`), because rekordbox sees a new file as a new entry; an old AIFF entry can be relocated to it (by
hand: right-click › Relocate; rekordbox offers only files of the same type, so any other old file gets the new one as
a new track) and keeps its cues when the two are the same edit. When Discjockey knows rekordbox's
timeline of the old file, the new file is rendered lined up with it (`aligned: true`) and the cues fit to the sample;
otherwise the download is only renamed and the cues fit to within the measured offset.

The single operations (`hide`, `add_bought_file`, `use_candidate`, `use_link`, `reject_current`) check that the track
still looks as the page last showed it (via `track`, `todo` or `library`); call one of those before. Interrupted steps
are finished first and shown (`recovered`).

Download jobs (`use_candidate`, `use_link`, `sync`) send the engine events (SourceChosen, Progress, ...) too.

Report section `rekordbox_check` ("Check in rekordbox", in `run(run_id).sections` and the .md report): every track
that still has a `rekordbox_check` when the run's report is written, `note` = the same text as the to-do `detail`.

### Other

`show_in_finder(track_id, which="current")`, `reveal(rel_path)` (inside the music folder only, e.g.
`"Library/Hard_Bounce"`, `".discjockey/reports"`; `"."` is the music folder itself), `open_report(run_id)`, `open_licenses()` (the licences folder, `Contents/Resources/licenses` in the app, in Finder; refused
when it is missing: "The licences folder is missing from this copy of Discjockey."), `open_external(url)` (https only,
system browser) → `{}`.

`app_update()` (immediate, also without a music folder: not a library method) — the last answer of the update check (spec
public-release §8); it never touches the network itself. `unknown` means no answer yet (offline, rate limit, or a version
that isn't plain), and then the page shows nothing. `latest` and `url` are set only for `available`, and the page opens
`url` with `open_external`. Read it at boot; the `AppUpdate` event brings later changes.
Shape: `AppUpdate` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

`quit()` (immediate) — closes the hub window (after `update_tools` or `rollback_tools` with `restart`: the page says
"Open Discjockey again" first, then calls it). Refused with `busy` ("Discjockey is still busy with a change. Wait until
it has finished, then quit.") while a write job runs; otherwise `{}` and the window closes about 0.3 s later.

### Setup wizard

`setup_check_tools()` (immediate) — which programs are found, and the download tools of Settings → This Mac
(`download_tools`: `version` is what this window runs, `waiting` the version the next start uses when it differs (an
update or a step back waits for a reopen), `previous` the version **Go back** would use; streamrip is always `built_in`
with null `waiting`/`previous`). If reading them fails unexpectedly, `download_tools` is null and `download_tools_problem`
holds a plain sentence (the logged detail stays out of it); the rest of the check still answers.
Shape: `SetupTools` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).

| method | job kind | result |
|---|---|---|
| `setup_save_client_id(client_id)` (32 hex; bad format refused at once) | `setup_save_client_id` | Shape: `Empty` |
| `setup_spotify_login()` — opens the system browser; ends by itself, after 5 min (`login_failed`), or with `stop()` (`stopped`) → show Retry | `setup_spotify_login` | Shape: `SpotifyLogin` |
| `setup_qobuz_login(email, password)` — also stores `qobuz_last_check` (ok, or `login_failed` when Qobuz refuses the login; being offline or a Qobuz hiccup records nothing); a failed login puts the previous streamrip config back. An account made with Google, Apple or Facebook first sets a Qobuz password at `https://www.qobuz.com/signin/forget-password` (the page opens it with `open_external`) | `setup_qobuz_login` | Shape: `Empty` (`failed` + message) |
| `setup_skip_qobuz()` — "I don't have Qobuz": the Qobuz step counts as done | `setup_skip_qobuz` | Shape: `Empty` |
| `setup_skip_spotify()` — "I don't use Spotify": the Spotify step counts as done and sets `spotify_skipped` (playlists then come from the links of the other services); a later `setup_spotify_login` clears it | `setup_skip_spotify` | Shape: `Empty` |
| `set_read_liked_music(on)` — Settings' "Read my Liked music" (sources round): whether YouTube Music's Liked music line is read, through the YouTube login (a `YoutubeDL` of the read's own, never the download path's). Off by default; `on` must be a bool (`refused`); turning it on without a YouTube account fails `not_set_up` ("Sign in to YouTube first: Discjockey reads your Liked music through that login."). Turning it off never touches playlists.txt. While it is off a listed Liked music line is left out of every read like a switched-off line (no request, no problem, its files stay; its tracks are marked as not in a playlist like any switched-off line's); the same while the YouTube account is paused today (an `auto_stop`, `bot_check` or `rate_limited` sign recorded today), and a bot check or "too many requests" met by the Liked music read itself is recorded as the YouTube account's warning sign (Settings shows it, the account is then paused for the next Liked music reads) and ends only that line | `set_read_liked_music` | Shape: `Empty` |
| `set_auto_upgrade(on)` — "Upgrade automatically when I sync" (Settings › Upgrades, Setup's Downloads step; stage C): whether a sync ends with Same track for every upgrade that needs no decision, while rekordbox is closed. On by default; `on` must be a bool (`refused`: "on must be true or false."). A settings job like every settings write: it holds no library lock for its run; its save takes the support lock (`busy` / `support_lock` after 2 s) and the library lock for the moment of the save (`busy` / `console`). Turning it off touches nothing that waits | `set_auto_upgrade` | Shape: `AutoUpgradeSet` (the window ignores it, the command line says it) |
| `sync_scope()` — the Sync scope (issue 39 V2.5b; settings.json `sync_scope`): the playlists and folders left out of a sync (`off`: `{target, name}`; `target` is `playlist:<ref>` or `folder:<path>`, `name` the playlists.txt line's folder name or the path's last part, the target itself when no line or folder has it any more) and the weekly kinds switched off (`weekly_off`: `{kind: retry\|weekly, label}`, "Not found last time" / "Weekly checks"). Nothing listed: everything on. Works without a music folder; a settings.json that can't be read answers the defaults | `sync_scope` | Shape: `SyncScope` (the window's `syncScope` store reads it at start and when a job ends; the command line's `sync scope show`) |
| `set_sync_scope(on, off)` — switches collections (`playlist:<ref>`, `folder:<path>`) and weekly kinds (`kind:retry`, `kind:weekly`) back in (`on`) or out (`off`) of the sync: a settings job (`set_sync_scope`, no library lock for its run, as `set_auto_upgrade`). `off` adds, `on` removes, the order is kept, none twice. A switch states the wanted value, so there is no `expect`: the last write wins. `refused` before a job starts for anything else or an item in both lists (the words name the item). The window sends one job at a time and merges the flips made meanwhile; the engine applies the scope to a run's selection only in the command line's `sync run` (phase 4), the window keeps working it out from the store | `set_sync_scope` | Shape: `SyncScope` (the scope as saved; `sync scope on|off`) |
| `add_liked_music()` — "Add Liked music to Playlists" (a `LIBRARY_METHODS` member): appends `Liked_music = https://music.youtube.com/playlist?list=LM` to the end of playlists.txt through the writer `save_playlists` uses (YouTube Music shares no link for it; a folder `Liked_music` taken by another playlist becomes `Liked_music_2`, …). Fails `setting_off` while the choice is off and `exists` when a Liked music line is listed already (on or off). A Playlists page with an unsaved draft meets it through its "changed elsewhere" answer (`playlists().version` changes) | `add_liked_music` | Shape: `LikedMusicAdded` |
| `setup_account(service, browser, profile?)` — `service` `youtube|soundcloud`, `browser` `safari|chrome|firefox|brave|edge`, `profile` that browser's profile folder (null: the default); checks the login in that profile (only cookie names are read), then saves the browser, the profile and the check (`last_check`). A login without Premium or Go+ is saved too (`saved: true`, its check recorded): SoundCloud's is used for downloads, YouTube's only to read Liked music and never for a download (`Settings.download_accounts`: no cookies, no limit card, no usage row, no `premium_missing`). A later check that finds Premium makes it the download account. A failed check of the saved login itself (same browser and profile) is recorded on it | `setup_account` | Shape: `AccountSaved` |
| `setup_forget_account(service)` — removes the saved browser of that account (forgetting the YouTube login also turns Liked music off: signing in again does not turn it back on) | `setup_forget_account` | Shape: `AccountForgotten` |
| `update_tools()` — the newest yt-dlp (+ the yt-dlp-ejs it pins) from PyPI into the support folder, tested in its own process before use; streamrip only changes with Discjockey releases. `failed` + a plain sentence (never a traceback or an OS error text) when: offline ("Couldn't reach the download server..."), the server answers with an error status ("The download server has a problem right now..."), its answer is not understood, there is no wheel for this Mac, the download was damaged, the disk refuses (the sentence names the reason in plain words: full, not allowed, refused), or the new version failed its test. The tools in use always stay. `busy` while a write job of this support folder runs (this window's, a terminal job found in the registry, or a terminal run holding the library): it takes no library lock itself, only the support lock (`.support.lock`) for its whole run, and answers `busy` / `support_lock` when another process holds that for 2 s. `stopped` when Stop is pressed (the test process ends too) | `update_tools` | Shape: `ToolsChange`: `restart` true when the version the next start uses isn't the one this window runs → ask to reopen, then `quit()`; already the newest: `before == after` (`restart` still true when an earlier update waits for a reopen) |
| `rollback_tools()` — back to the yt-dlp used before the last update (the folder stepped back from is deleted unless this window runs it); `refused` "There is no earlier version to go back to."; `busy` and disk problems as `update_tools` | `rollback_tools` | Shape: `ToolsChange` as `update_tools` |

The shapes are generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`.

(`setup_check_account` is gone, issue 39 V2.5b: the page re-checks a login with `setup_account`. Its command-line row
answers the `dropped` refusal.)

### Settings

Signing in through the browser (spec settings-setup §5, §7, §13). Only cookie *names* are read, from copies; macOS
never asks for a password while Discjockey looks. A sign-in runs in its own slot beside the write jobs (no library lock:
waiting changes nothing), one at a time; `job_status().sign_in` is its snapshot (`last.SignInPhase` = where it is).
A sync may start while it waits; the check then doesn't run. Every settings write takes the support lock (waited for 2 s, then `busy` / `support_lock`) and, inside it, the library lock for the moment of the save, answered `busy` / `console` instead of waiting: a settings job holds no library lock for its run, a sign-in holds none at all (one writer at a time; lock order support, library, rekordbox.lock).

| method | kind | result / notes |
|---|---|---|
| `find_logins(service)` — `youtube\|soundcloud` | immediate | The installed browsers, the default one first, and which profiles hold a login. `problem` `no_access` (Safari without Full Disk Access) \| `locked` \| null; `profiles[].id` null = Safari's only profile. Shape: `FindLogins` |
| `account_sign_in(service, browser, profile?)` — refused with `sync_running` during any sync, `busy` while another sign-in waits, `refused` for a browser that isn't installed | job `account_sign_in` (sign-in slot) | Opens the sign-in page in that browser (that Chrome/Brave/Edge profile in its own window; Firefox and Safari open their default profile), then looks every 3 s: for Chrome/Brave/Edge with a profile only that profile's login counts, otherwise a login in any profile of the browser (the chosen one first). `SignInPhase` `waiting` → `checking`; then like `setup_account` (Shape: `AccountSaved`), `profile` the one whose login was found. Ends `failed` after 10 minutes ("Didn't see a login in 10 minutes. Sign in again.") or at once when macOS refuses the browser's files (the Full Disk Access message); `stopped` by `stop_sign_in()`; `sync_running` ("… Check again after the sync.") when a sync started while it waited (no check runs); `busy` / `console` when the login was checked but a write job or a terminal run held the lock at the save (nothing saved) |
| `stop_sign_in()` | immediate | `{stopped}` — Cancel on a waiting sign-in; `stop()` never ends it, and it never ends a sync |
| `open_privacy_settings()` | immediate | `{}` — System Settings at Full Disk Access |
| `qobuz_check_login()` — refused with `sync_running` during any sync | job `qobuz_check_login` | `{}`: logs in with the saved login and searches once; stores `qobuz_last_check`: `login_failed` only when Qobuz refuses the login, `search_failed` when logged in but the search finds nothing (then `failed` + message). Offline, a Qobuz error or a failed search store nothing (the last check stays) and end `failed` with a plain message |
| `spotify_sign_out()` | job `spotify_sign_out` | `{}`: forgets the Spotify login; the Client ID stays |

`setup_account(service, browser, profile?)` saves the profile and the check (`last_check`) with the login; its result
carries `profile`. A failed check of the saved login (same browser and profile) is recorded on it, so Settings shows
"not signed in" instead of a stale ✓.

`downloads_view()` (immediate; answers `{downloads}`) — the source ladder and the account panels of Settings and Setup
(spec settings-setup §4, §6.4): each download source's state and the library counted by rung. A login without Premium
(YouTube) is used only to read Liked music, never for a download. Without a music folder the library counts are zero.
Shape: `DownloadsViewAnswer` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).


### The music folder

Where the library lives (spec public-release §4). The hub opens without one: Setup's first step chooses it, and
`setup_status().music` says where things stand. These four methods work without a bound folder.

| method | kind | result / notes |
|---|---|---|
| `pick_folder(start?)` | immediate | `{path}`: the Mac's folder dialog, opened at `start`, else `~/Music` (the nearest folder that exists). `path` null when the user cancelled. `refused` when no window dialog exists |
| `check_music_folder(path)` | immediate | Changes nothing. `path` is the resolved folder. `usable` false: `problem` names why and `message` says it in plain words. `kind` is set for usable folders (`other_files`: the page asks before using it). Shape: `FolderCheck` |
| `set_music_folder(path)` | immediate | Uses the folder (made when new). Without a bound library (none chosen, or the chosen one missing) it is bound at once, `restart` false. A bound library is never swapped while the window is open: the choice is saved and `restart` is true, then the page calls `quit()`. The folder already in use again changes nothing (`restart` false). Refused: `refused` with the check's message, `busy` while a change runs, `console` while a terminal run holds the library. Shape: `MusicFolderSet` |
| `retry_music_folder()` | immediate | The missing-folder screen's Try again; binds the library when the folder is back; `music.state` becomes `not_chosen` when `config.json` no longer names a folder. With a library bound already (see "bound but missing" below) there is nothing to bind: it answers the status, `ok` once the folder is back. Shape: `MusicFolderAnswer` |

While no music folder is bound, every method in `LIBRARY_METHODS` answers `no_library` before anything runs, with
"Choose your music folder first: it is the first step of Setup." (not chosen) or "Your music folder isn't there:
{path}. Connect the drive it is on, or choose another folder." (missing). `LIBRARY_METHODS` (api.py, `contract.ts`;
a test compares them): `dashboard`, `sidebar`, `sync_preview`, `refresh`, `library`, `track`, `todo`, `playlists`,
`limits`, `limits_what_if`, `save_limits`, `mark_warnings_seen`, `runs`, `run`, `spectrum`,
`search_candidates`, `preview`, `add_playlist`, `preview_playlist_change`, `start_sync`, `save_playlists`, `hide`,
`never_download`, `add_bought_file`, `use_candidate`, `use_link`, `reject_current`, `rekordbox_checked`, `upgrade`, `upgrade_all`,
`undo_upgrade`, `batch_resume`, `batch_undo`, `rescan_library`, `show_in_finder`, `reveal`, `open_report`, `tidy_preview`, `move_batches`, `undo_preview`, `tidy_up`,
`undo_moves`, `watched_folders`, `set_favourites`, `set_crate_shown`, `check_import_folder`, `removal_preview`, `add_watched_folder`,
`remove_watched_folder`, `start_import`, `answer_same_song`, `keep_duplicates`, `keep_file`, `add_liked_music`,
`missing_files_preview`, `missing_files`. Everything else works without a music folder, `open_licenses` included (Setup and Settings before one
is chosen); `downloads_view()` then counts zero tracks.

**Bound but missing.** A folder that vanishes while the hub runs (an unplugged drive) behaves as an unbound one: every
`LIBRARY_METHODS` method answers `no_library` with "Your music folder isn't there any more. Connect the drive it is on,
then try again. Nothing was changed." (`library.MUSIC_GONE`), and `setup_status().music` is `{state: "missing", path}`
with the bound folder's path. It is never shown as an empty library. The bridge client calls the hub store's
`refreshOnNoLibrary` on any `no_library` answer, so the shell reads `setup_status` again and shows the missing screen
whichever page asked. Nothing is rebound while the window lives: `retry_music_folder` answers `ok` when the folder is
back, and "Choose another…" saves the other folder and returns `restart: true` (the page calls `quit()`).

### Watched folders and the import (read: `LIBRARY_METHODS`; writes are jobs, except the brief saves)

The user's own music (spec library-and-sources §10; plan library stage 4): folders Discjockey indexes where they are.
Every word below is the engine's (`folders.py`, `importer.py`, `jobs.py`, `views.py`) and is shown as given. The shapes are generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`.

| method | kind | result / notes |
|---|---|---|
| `watched_folders()` | read | The Library first (always `online`, or `scanning` while an import looks for files; `name` "Library"; its `waiting` and `unreadable` count like an import folder's: files that came into Library/ before an import finished them), then the import folders by id. `offline`: the folder's drive is not connected (path under `/Volumes/<drive>`, that mount absent). `missing`: any other folder that is not a folder now (moved, renamed or deleted; the page says "Folder not found: moved, renamed or deleted? Put it back or remove it here." and the row keeps its ×). Both: checked live, rows kept, nothing downloads. `files` is the sidebar's number for the same folder (`views.listed_counts`: one definition for both; the Library row counts `Library/...`; a file the import has not read yet or could not read is no track yet and is in `waiting` or `unreadable` instead). `crates` are the user's switches applied (`Crate` as in `sidebar()`); the Library row has none. Top level: `unreadable` lists the files it couldn't read (in the Library and every import folder), each with the id of its folder and the reason in words; `stopped` is true after the user stopped an import, in any window or process (library.db `import_state.stopped_at`, schema 13: it outlives the window; the page offers Continue import). The live phase and counts come from the `ImportProgress` event, not from here. Shape: `WatchedFolders` |
| `check_import_folder(path)` | read | Changes nothing. `usable` false: `problem` says why and `message` says it: "This is inside your music folder, which Discjockey watches already." · "This folder holds your music folder. Choose a folder inside it instead." · "This is inside {name}, which Discjockey watches already." · "Discjockey watches this folder already." · "That folder isn't there. If it is on a drive, connect the drive first." · "macOS doesn't let Discjockey read that folder." (and the music folder check's words for the first four). Usable: `kind` `import`; `merges` the folders inside it that it would take over (their files and links are kept). Shape: `ImportFolderCheck` |
| `removal_preview(folder_id)` | read | The folder's file count, and the playlist songs whose only file is there (they download again at the next sync). `refused` for the Library or a number that is no watched folder ("That folder isn't one of the watched folders."). Shape: `RemovalPreview` |
| `add_watched_folder(path)` | write → job `import` | Checks the folder as above (`refused` with its message when it can't be watched), watches it, then imports in the same job. `JobFinished.result`: `ImportResult` (below) |
| `start_import()` | write → job `import` | "Continue import": the import again where it stopped. Clears `import_state.stopped_at`, which lets the import start by itself again (a Stop holds that for every window and process; a start that fails puts the stop back) |
| `remove_watched_folder(folder_id)` | write → job `folders` | The result is `RemovalPreview` as `removal_preview` said (`name` is for the command line's words). The files stay where they are; own songs left with no file go; playlist songs left with no file download again. The preview is planned again at once. `refused` for the Library or an unknown number |
| `answer_same_song(song_key, own_key, same)` | write → job `answer` | "Is this the same song?" answered (`same`: bool): the preview is planned again (Yes: the next plan links the file to the playlist song; No: the song downloads at the next sync, and is never asked again). `result` is `Empty`. `changed` when `song_key` isn't a playlist song any more |
| `keep_duplicates(group_id, paths)` | write → job `answer` | "Keep both" / "Keep all": the group isn't asked again; it applies to every file of the group (a group can hold more than two). `paths`: the group's files' `path`s as the card showed them (list of strings, any order); `changed` when they are not the group's files now (a file id can be given out again to another file). `result` is `Empty` |
| `keep_file(group_id, file_id, paths)` | write → job `supersede` | "Keep this file" of a duplicate group (the panel's "Keep the …"): every other file of the group goes to Superseded/ in one job (`folders.keep_file`: one move after the other, each checked against the group as it is then); nothing is deleted. `file_id` is the file that stays. `paths`: as for `keep_duplicates`; `file_id` not in the group, or a group that isn't as the page showed it (a file gone, offline or a different group), is `changed` before anything moves. `result` is `KeepFileResult`: `results` one report line per moved file in the order they moved (`section` `replaced`, `path` where the file went, relative to the music folder, `track_id` the song it was linked to), `recovered` `[]`, `kept_track` the song the kept file belongs to afterwards (a playlist song takes it over from an own song when its own file moved; null when linked to no song). `JobFinished.message`: "Moved to {path}." for one file, "Moved {n} files to Superseded/." for more. A move that is refused stops the job (`failed`, "Nothing was moved: …"): the files moved before stay moved, listed in the failed job's `result` (`kept_track` null) |
| `set_favourites(keys)` | brief save | `{favourites: string[]}`: replaces the Favourites with `keys` (`playlist:<ref>` / `folder:<path>`, in the order given; a key given twice keeps its first place) and answers the list as stored. Not a job and no engine lock: it works during a sync, an import and a terminal run (see "Calling"). `refused` for anything but a list of such keys; `busy` ("Discjockey couldn't save that just now. Try again in a moment.") when a running job's write holds `library.db` past the 1.5 s wait, nothing changed; `refused` with "Discjockey has no records of your library yet, so it can't save that. Quit and open Discjockey again." while there is no `library.db`. A stored key that is not in `keys` and whose playlist or folder is gone right now (`sidebar()` leaves it out) stays stored, right after the nearest stored key before it that is in the new list (first if none): the UI never saw it, so a save from the UI cannot have meant to remove it (a playlist taken out of playlists.txt for a while, a folder on an unplugged drive, a briefly empty sidebar). A key in `keys` is the user's, wherever it points. The answer is the list as stored, those kept keys among them |
| `set_crate_shown(path, shown)` | brief save | `{path, shown}`: shows (`true`) or hides (`false`) the crate at snapshot path `path` in the sidebar, or goes back to the default (`null`: shown, hidden under a folder with more than 25 crates). Settings' switch. Same rules, answers and refusals as `set_favourites` (`refused` for an empty path or a `shown` that is neither bool nor null); the path is not checked against the crates |
| `setup_skip_import()` | brief save | Sets `import_skipped` in settings.json (Setup's "Your existing music" step counts as done). Not a job; `busy` while a job writes, `console` while a terminal run does. Answers `Empty` |

**Jobs.** `import` runs the import: `ImportProgress` events (phase `scan` · `facts` · `tags` · `sound` · `link`, `done` of `total`
files of that phase, `unreadable` so far), then ends. `JobFinished.result` is `ImportResult` (`link_note` is null or the
words of a link that didn't happen: "Your playlists couldn't be read, so the imported files are linked to them at the next
sync."). `JobFinished.message`
is the end line: "Imported {files} files." (singular: "Imported 1 file."). `stop()` ends an import between two files:
`JobFinished` with problem `stopped`, `result` the import as far as it went (`stopped` true) and `message` "Import
stopped with {left} files to go. It carries on where it stopped." ("1 file" when 1). What was done is written; the
rest waits. The import starts by itself after Add folder (the same job) and when the window opens with files waiting
(after the first read's scan, once, when nothing else writes); after a Stop (kept in library.db) only with `start_import`; the window's one automatic start per session stays a flag of the window. While it runs
every other write answers `busy` (and `lock_briefly` saves such as `setup_skip_import`) with: "Discjockey is importing
your music. Stop the import in Settings → Watched folders to do this now; it carries on later where it stopped."
`folders`, `answer` and `supersede` are ordinary short write jobs (`busy` / `console` as every write); each ends with
the preview planned again from the last read.

**To-do items of the import.** `todo()` items of the groups `same_song` ("Is this the same song?", "a file of yours
might be a playlist song") and `duplicate` ("Duplicates", "the same song more than once") are TodoItems plus `pair`:
- `same_song`: `track_id` is the playlist song's key (its track token while it isn't stored yet); the item is that
  song, which waits for the answer (not listed as Not found meanwhile). `pair = {song_key, own_key, why, delta_s,
  track: {artist, title, duration_s, folder, link}, file: FileSide}`; `why` `artist` · `no_artist` · `length` ·
  `no_length`, `delta_s` the file's length minus the song's in whole seconds (null with `no_length`). `detail` is the
  why in words: "Same title, different artist" · "Same title, no artist in your file" · "Same artist and title, {s} s
  longer" / "{s} s shorter" · "Same artist and title, the length couldn't be read".
- `duplicate`: `track_id` is the `group_id`. `pair = {group_id, why: same_audio\|same_song, files: FileSide[],
  recommended, recommended_why}`, files by file id; a group can hold more than two files, and "Keep both"
  (`keep_duplicates`) applies to all of them. `recommended`: the file id the panel picks to keep (`views.recommend`:
  the better sound, lossless before lossy then the higher cutoff, then AIFF before any other format; being in a
  playlist or in `Library/` breaks no tie), null when there is no clear winner; `recommended_why` its line
  ("Recommended: best quality" / "Recommended: AIFF keeps tags"), null with it. Keeping one file of a group is one
  `keep_file` job. `detail`:
  "The same audio in {n} files" · "{n} files of the same song". A group found both by the plan and by the records
  shows once, as `same_audio`. Groups with a file offline now, held or gone are left out: "offline now" is the same live away set as the panels' (a group on a just-ejected drive or a renamed folder is neither listed nor counted in `chips`, the filter or the sidebar, even before a scan).
- `FileSide = {file_id, song_key, path, artist, title, duration_s, quality, quality_label, online, audio_url,
  in_playlist}`: `path` is absolute for an import folder's file; `audio_url` is a media address
  like any other; a file outside the music folder (an import folder's) plays through `file/<file_id>`, which the
  media server serves only for a known file row that is online in a watched folder and whose real path, links
  resolved, stays inside that folder's root. It is null for a file that is offline, gone, or leads out of its folder.

## Events

The window must define `window.dj = { onEvent(event) {...} }`; the hub calls it with one object per event. Every
event has `type` (class name) plus the fields below. Exact JSON schema: `tests/fixtures/hub_events.schema.json`
(regenerated by `scripts/record_hub_events.py`; `test_the_schema_is_up_to_date` fails on any rename). Recorded
streams to replay: `tests/fixtures/hub_events_sync.jsonl` (refresh + full sync: move, Qobuz lossless, not found,
YouTube Music lossy, network error, weekly check parking an upgrade) and `hub_events_stopped.jsonl` (Stop during
the third action).

Events are dataclasses (`discjockey/hub/jobs.py`), not shapes: `tests/fixtures/hub_events.schema.json` pins them on both
sides, and `hub-ui/src/lib/bridge/events.ts` (type and `EVENT_FIELDS`) follows it.

| type | fields |
|---|---|
| `JobStarted` | `job_id` str (`job:<8 hex>`), `kind` str, `track_id` str\|null, `batch_kind` `"upgrade"\|"convert"\|"mixed"`\|null (an AIFF batch job's kind as the snapshot's; null for any other job) |
| `JobFinished` | `job_id`, `kind`, `ok` bool, `problem` kind\|null, `message` str, `result` object\|null, `service` `spotify\|qobuz\|soundcloud\|youtube_music`\|null (the playlist service a failed job's problem is about — a sync or read that stops at a missing login, a rejected login, an unreadable playlist, a service not answering; null for everything else and for success) |
| `ConsoleBusy` | `running` bool, `job`, `kind`, `line` (each a string or null: another process's job holds the library lock or has ended → banner, read-only). `job`, `kind` (a job kind, as `state.json`'s) and `line` (its progress line, "4 of 60") come from the registry; all null when `running` is false and for a holder with no registry entry (an older Discjockey: the lock probe). Sent when that set of four changes, so a changed `line` is a new event; the registry is looked at once a second, the first look sends only when something runs. A foreign job's end, any kind, is a `JobFinished` of the same shape the window sends for its own (rebuilt from the job's `result.json`; `worker_lost` words when it left none), so the pages re-read; a foreign `refresh` ending while the window's own refresh runs sends none. The banner's words do not change |
| `FileDropped` | `name` str, `path` str\|null (the full path the window gave, also for a file that can't be read; null when it gave none), `readable` bool, `message` str ("" when readable; else why not: "macOS didn't let Discjockey read this file…", or "…Drag it from a Finder window." when there is no path). The engine remembers no drop and no selection: the window knows which to-do item a drop belongs to and passes the `path` back in `add_bought_file` |
| `SignInPhase` | `service` (`youtube\|soundcloud`), `phase` `waiting\|checking`, `browser`, `browser_name` — a sign-in through the browser (Settings, Setup) |
| `AppUpdate` | `state`, `current`, `latest`, `url` as `app_update()` — sent when the update check's answer changes (at start, then at most daily) |
| `DrivesChanged` | `away` int (how many watched folders are away now) — sent once when the set of import folders that are away (and why: `unmounted` or `missing`, `scanner.away_reason`) differs from the last look: a drive plugged in or ejected, a watched folder renamed or put back while the window is open. The hub's drives watch looks every 2 s, read only (no scan, no write); its first look is the baseline and sends nothing, and a look that can't read `library.db` sends nothing and keeps the last answer. The page re-reads what shows a file's or a watched folder's state (`library()` and the open `track()`, `todo()` and its panel, `watched_folders()`, `sidebar()`), not every page. A new event rather than `JobFinished` (no job ran) or `ConsoleBusy` (it means the window goes read-only) |
| `RunStarted` | `total` int, `actions` [{`kind`, `track_id`, `title`, `artist`, `image_url` str\|null}] — every action of the run in the order the run does them ("Up next", time left; `image_url`: Spotify's cover for the rows) |
| `ActionStarted` | `index` (1-based), `total`, `action` {kind, track_id, folder, track {id, title, artists[], album, image_url, duration_ms, isrc, service, link\|null, streamable, account_only}, order [int,int], src, dest_dir, aliases[], reason, qobuz_id\|null, upload SourceTrack\|null} (`track.service` `spotify\|qobuz\|soundcloud\|youtube_music`: the service the track was read from; `id` is that service's own id, and `link` its page; `track.account_only`: only the SoundCloud Go+ account plays the whole track; `upload`: the playlist's own SoundCloud or YouTube Music upload of the song, tried after Qobuz and before the search (null: none), a `SourceTrack` with the same fields as `track`) |
| `StepChanged` | `track_id`, `step`: `search|download|check|convert|analyse|compare` |
| `Progress` | `track_id`, `step`, `done` number, `total` number\|null, `unit` `bytes` (download) \| `seconds` (conversion) |
| `Waiting` | `kind` `search|between|break|fallback`, `label`, `remaining` s, `total` s, `service` (`qobuz`, `youtube`, `soundcloud`; empty for free sources) — pause card only for `between`/`break` |
| `SourceChosen` | `track_id`, `source`, `query_kind` `exact|isrc|name|fallback|chosen|upload` (`exact`: the Qobuz id the playlist track carries, "exact Qobuz track"; `upload`: the playlist's own upload, "the playlist's own upload" (W20), whether its free download, the account's stream or the free stream is the one tried), `title`, `duration_s`\|null ("Qobuz by ISRC") — sent before the protection pause (`Waiting` `between`/`break`) that precedes a Qobuz download, so the pause card can name the next source |
| `Checked` | `track_id`, `file_duration_s`, `track_duration_s` (the playlist track's length, whichever service; was `spotify_duration_s`), `codec`, `ok` ("Length matches (3:12 = playlist 3:12)", "Length differs (3:12, playlist 3:20)") |
| `AccountUsage` | `service`, `used`, `allowance` ("Qobuz 42 of 80 today") |
| `ActionFinished` | `action` (as above), `result` Result — Problems = sections missing/errors/conflicts/ambiguous; `error_kind: network` → "NO INTERNET" |
| `RunFinished` | `exit_code` (0, 1, 130), `report_path` (.md) — then `run(run_id)` with the report's stem for the end screen; also sent for a crashed sync (1, its crash note), before its `JobFinished` |
| `Message` | `level` `info|warning|debug`, `text` (hide debug) |
| `ReadingPlaylist` | `index`, `total`, `folder` — before each playlist is read (a refresh, or a sync's start) |
| `MovesProgress` | `batch_id`, `done`, `total` — after each move of a move batch, during `tidy`, `undo_moves` and a moving `save_playlists` (a folder rename counts as one move) |
| `BatchProgress` | `batch_id`, `done`, `total`, `track_id`, `name`, `lead`, `count` — `lead` / `count` the phase's words, printed as they are (`batches.progress_words`): only Same track items "Upgrading" / "{done} of {total} upgraded", only placements of missing songs "Putting in better versions" / "{done} of {total} put in", any other mix "Upgrading" / "{done} of {total} done"; both "" for `upgrade_add_new` / `upgrade_discard` lists and an undo — before each track of an AIFF batch and after the last (`track_id`/`name` null then), during `upgrade_batch`, `batch_resume`, `batch_undo`, a `sync` (its Auto-upgrade phase, stage C: one batch, `batch_id` its real id) and, with `batch_id` 0 (no batch record), `upgrade_add_new` / `upgrade_discard` lists. `done` counts tracks handled, earlier runs of a resumed batch included |
| `ImportProgress` | `phase` `scan|facts|tags|sound|link`, `done`, `total` (0 of 0 for scan and link), `unreadable` (files this import couldn't read so far) — during an import (importer.run_import), at each phase's start and end and at most every 25 files or 0.5 s between |

Pause card: the pause runs inside the next action after its `ActionStarted` and search, so "next up" is the current
action and "after that N more" = `total - index`. Progress and Waiting may be coalesced when the page lags (only the
latest is sent). The pause card's source is the latest `SourceChosen` of the current action.


## Upgrades and batches (issue 33 stage B)

- **Problem kind `rekordbox_open`**: a batch or an undo needs rekordbox closed ("rekordbox is open. Quit rekordbox, then try again. Discjockey changes your rekordbox tracks only while rekordbox is closed."; stopped mid-way: "rekordbox was opened, so Discjockey stopped after {done} of {total}. Quit rekordbox and press Resume."). `JobFinished.result` is the stopped `AiffBatchResult` (or the `UndoResult`) when items ran.
- **`upgrade` block** (`track().upgrade`): `swap_possible` means "Same track can run now" (the quick answer: a parked upgrade, the file there, a stored alignment `exact`/`shifted`, and for a file that isn't AIFF a rekordbox library Discjockey can open or none); `why_not` is the eligibility reason key when it can't; `rekordbox` is the cached state (see below); `auto_refused` is the Auto-upgrade phase's record (stage C, see "Auto-upgrade" below). `upgrade_status` says "cues can stay" whenever Same track is possible.
- **`check_view`** (`check`): gains `person_steps` (issue 39, the command line's): `[{id, say, then}]`, the steps only the person can do in rekordbox. An added file (New track) is `step:relocate_new`, its `say` the check's text ending with the new file's absolute path; a `placed_missing` check is `step:look`, except a different edit placed under a new name (not repointed, not the same edit), which is `step:relocate_new` with the file's path (a placement's row has no `path`: the song's file now is it); a swap, Same track or Convert is `step:reload_tag` while rekordbox's text is still to be reloaded (`reload_tag` true, or a record without it), and `step:look` ("In rekordbox, have a look at {tracks}.") when Discjockey wrote rekordbox's text itself (`reload_tag` false, which every Same track repoint, Convert and clean-name check stores, whether or not rekordbox has the track, and an AIFF swap stores once its write committed: a Reload Tag would replace names the person changed), its `say` the check's text either way (with the USB step for a repointed or converted file rekordbox has tracks of); a batch result's `person_steps` holds one `reload_tag` step and one `look` step at most, each listing its tracks and ending `check done --batch aiff:N`; `then` is `check done <track_id>` (a step with no command of its own, such as quitting rekordbox, has `then: null`: run the same command again); a clean name and a wrong song have none (`words.person_steps`). The window words its own numbered steps and ignores it. Reasons include `repointed` and `placed_missing` (a better version put in for a missing file, see "Auto-upgrade"); a record without `reload_tag` still asks for Reload Tag (`true`). Shape of a check: `RekordboxCheckView`.
- **`todo()`**: every `upgrade_ready` item carries `same_track` (null, or the reason key); the group's `all` counts Same track can run (`n`) / the edit needs a choice (`m`) / waits for something else (`k`), hidden tracks left out, and its `stopped` is the newest stopped batch with tracks left. The open checks of one batch with two or more tracks are one item, `BatchCheckItem` (`key` = `track_id` = `batch:<id>`, `group: "rekordbox_check"`, the first track's row fields, `batch`: the `BatchCheck`; `aiff_id` is `aiff:<id>`, the id the command line takes, the window ignores it), counted once in `chips`; one open check stays a plain item.
- **Shapes of the batches**: results of `upgrade`, `upgrade_all` and the batch jobs: `AiffBatchResult`; of `undo_upgrade`: `UndoResult`; of `rekordbox_checked`: `CheckedResult`; of `hide`, `add_bought_file`, `use_candidate`, `use_link` and `reject_current`: `OpResult`; of `never_download`: `NeverDownloadResult`; the dry runs `upgrade_preview` and `undo_upgrade_preview`: `UpgradePreviewAnswer` and `UndoUpgradePreviewAnswer`.
  Shape: `AiffBatchResult` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
- **Cached rekordbox state**: `HubApi._rekordbox_status()` keyed on master.db's modified time and size plus whether rekordbox runs; one read open per change. A reader takes `rekordbox.lock` shared and without waiting (`rekordbox.lock.reader_lock`); while a writer of any Discjockey process (a batch's session, a restore, a recovery of analysis files) holds it, master.db is never opened and the answer is the last value (`writing`, see `rekordbox_status()`). The same goes for the plan behind To-do's CDJ group and the `aiff_plan` read: with a writer holding the lock they plan on rekordbox's cached state and no lookup. A write job that holds no rekordbox session does not stop the read. Services `rekordbox_running` and `rekordbox_place` are injected (tests and the fake never touch a real library).


## Auto-upgrade (issue 33 stage C)

The sync's last phase (`discjockey/auto_upgrade.py`): with Settings' switch on (the default), a sync ends with one AIFF
batch that does Same track for exactly the set Upgrade all would do, while rekordbox is closed. rekordbox open means
nothing is upgraded that run and the upgrades are marked as waiting. The hub changes nothing about how a sync starts
or stops: `sync_work` passes the job's Stop token and the hub's rekordbox services (`rekordbox_running`,
`rekordbox_place`, `compare`, `now`) to both ways a sync ends, so Stop reaches the phase even when the plan had no
action.

- **`set_auto_upgrade(on)`** (write job `set_auto_upgrade`, result `{auto_upgrade}`: the value saved, for the command line's words): see Settings. **`setup_status().auto_upgrade`**
  is the switch. `SettingKey` is unchanged (no read needs the switch).
- **`rekordbox_status()`** (read, any time; works without a music folder, not a `LIBRARY_METHODS` member): issue 39's
  command line gets a richer answer than the window, which reads `state` and `running` only (`library` is the path of
  master.db, `modified_at` its local modified time to the second and `size` its size, so "master.db untouched meanwhile"
  can be checked). `state` is the cached `_rekordbox_status()` (one read open per change of master.db; with a writer
  holding `rekordbox.lock` it answers its last value, with `writing: true` and `as_of`), `running` is asked on every
  call. The Sync page reads it when it opens and when the window gets focus again (no timer); `none`: no rekordbox
  library on this Mac, `unreadable`: one Discjockey cannot open. Shape: `RekordboxStatusAnswer` (generated:
  `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
- **`sync_preview().auto_upgrade`** → `{on: bool, ready: n, places: p, place_notes: {closed, open} | null} | null`. `on` is the Auto-upgrade switch. `n` = the phase's upgrade set now: To-do's Upgrade ready
  list (hidden left out, songs waiting for an answer to "Is this the same song?" left out) filtered by the quick Same
  track answer (the cached rekordbox state; nothing of rekordbox's library is opened), minus the tracks a recorded
  refusal still holds (`auto_refused`): a refusal that only a read of rekordbox's analysis files could tell counts as
  holding, one of `space` or `needs_choice` is checked. It counts the upgrades that would wait for rekordbox too (rekordbox
  running does not change `n`); the placements are not in `n`. `p` = the missing songs whose parked better version the phase would put in (Download again was asked, the file is missing; with the switch off too: `on: false`), those that would wait for rekordbox counted; `place_notes` is `{closed, open}`, the sentence for them (`words.place_plan_line`, rekordbox closed / open: "2 missing songs get their better version at the end of the sync." / "... at the end of the sync, once rekordbox is closed."; with one song the sentence names it: "Artist – Title gets its better version at the end of the sync."), null when `p` is 0. A placement whose rekordbox library can't be read waits too (`rekordbox_unreadable`, no `auto_waits`) and is counted. null: the switch is off and `p` is 0, settings.json can't be read, or `empty` is `no_preview`.
  The Sync page's before-start Hint ("rekordbox is open: quit it before the sync ends, so the sync can put {n} upgrades in
  place.", "1 upgrade" for one) shows when `ready >= 1` and `rekordbox_status().running`.
- **`upgrade` block** (`track().upgrade`): `auto_refused` is the refusal the phase recorded on the parked upgrade (`AutoRefused`, or null): `reason` one of `timing`, `not_analysed`, `cloud`, `space`, `needs_choice`; shown whatever the switch says. `auto_waits`: the phase met rekordbox open for this upgrade; true only while the switch is on and Same track could run now (`swap_possible`).
- **`todo()`**: an `upgrade_ready` item's `detail` is, in this order: "Waits for rekordbox to be closed" (`auto_waits`
  as above), "{Short} · not upgraded at your sync" (the reason first, so the end of the row can be cut; a recorded refusal that still applies: `short`, capitalised, is `timing`
  "couldn't line it up", `not_analysed` "not analysed in rekordbox", `cloud` "in Cloud Library Sync", `space` "not
  enough free space", `needs_choice` "couldn't compare it"; a `needs_choice` record is dropped once a measurement says
  "a different edit"), else `upgrade_status`. A batch's `started_by` (`aiff_batches.started_by`: `user`, `upgrade_all`, `auto_upgrade`, `download_again`, …; null when
  unknown) says who made it; for `auto_upgrade` and `download_again` (the same phase with the switch off, which runs the
  placements alone: issue 43) the
  item's `detail` is "{date} · Upgraded during your sync" (in place of "{date} · Same track"). The batch also has
  `from_sync: bool` (`views.SYNC_STARTERS`: true for `auto_upgrade` and `download_again`): the page names the card and its
  foot from it ("Undo all from this sync"), so it keeps no list of starters. The engine words the batch, the window prints
  them as they are: `batch.row_name` ("{n} tracks upgraded"; Convert and mixed batches "{n} tracks"; every check a
  placement `placed_missing` "{n} better versions put in"; a mix of placements and others "{n} tracks changed"),
  `batch.row_sub` ("{day} · {how}", the day "today", "yesterday" or "12 Nov"; `how` as the item's `detail` says it, and
  "Better versions put in during your sync" when every check is a placement), `batch.list_title` ("Upgraded", "Made AIFF",
  "Clean names", "Better versions put in", "Changed" for a mix) and `batch.card_summary` (the summary of the batch's "In
  rekordbox" card, every batch has one: "same track, cues kept" / "same tracks, cues kept" by how many of its checks that
  are no placement have steps to do in rekordbox (a track rekordbox has, no clean name); else "better versions in" when
  placements are there; null when the card has no steps) and `batch.placed_summary` ("better versions in" when the batch
  holds a placement, else null: a panel held after an undo that left only placements shows it).
  The card's steps for a placement are its `check.text`, one step per distinct text. The foot words ("Undo all from this
  sync") are the window's.
- **`run(run_id)` / `runs()`** (`RunSummary.auto_upgrade`): the report's `.json` key `auto_upgrade` plus `line`
  (`report.auto_upgrade_line`: "Upgraded 2 tracks; your cues stayed. 1 waits for rekordbox to be closed." …; null when
  nothing happened), or null. The block is an `AutoUpgradeBlock` (`action` and `how: "placed"`: issue 43, below; a report from before it has no `action`: read it as `same_track`); `waiting` counts `rekordbox_open`, `busy` and `not_reached` results and every skip nothing is recorded for
  (`changed`, `unclean`, `other_library`, `rekordbox_unreadable`, …: a waiting row then carries that skip's `reason` and
  its specific `message`, and counts for "your next sync"); `refused` (state and count) only the reasons the phase
  records and To-do shows (`timing`, `not_analysed`, `cloud`, `space`, `needs_choice`).
  `sections` carry `upgraded` (done; counted in `counts.lossless` / `lossy` by `status` like `swapped`, and not a new
  file for rekordbox), `placed_missing` (a done placement, below; counted in `counts.lossless` the same way) and
  `upgrade_waits` (waiting, refused, not reached; never an error: a failed item is in `errors`).
- **Placements for missing songs (issue 43 E4b).** The phase also puts in the parked better version of a song whose file
  is missing and whose Download again the user asked for (`missing.place_keys`; hidden songs included, a song found in
  two places or on an away drive left out): a row with `action: "place"` and `how: "placed"`, listed before the upgrades
  in the one batch. A placement counts in the block's `done` / `waiting` / `refused` / `failed` like any row. It runs with
  the switch off too, because Download again is its go: the phase then holds the placements alone, and the batch's
  `started_by` is `download_again` (with the switch on: `auto_upgrade`; no Resume is offered for either). **With the
  switch off the block, `auto_upgrade_preview()`'s `auto_upgrade` and the report's `auto_upgrade` key are present only
  when a placement is coming or was done, otherwise null** (nothing is read or written then). rekordbox open: the
  placement waits (`rekordbox_open`) whether or not rekordbox holds the song, the song stays missing with its mark; its
  waiting rows say "…its better version goes in at your next sync" in place of "…it is upgraded at your next sync". A
  refusal the phase records (`space`, `cloud`) goes on the parked upgrade as for an upgrade; the song keeps its mark. A done
  row's `message` is "Its better version is in, at {name}; rekordbox's track plays it with its cues." (`; check its cues in
  rekordbox.` when the missing file's timeline was unknown or another edit has its name; no clause when rekordbox's track was
  left alone) and its result is in section `placed_missing` ("Better versions put in (their files were missing)"). The block's
  `line` counts placements apart, after the upgrades' clauses: "1 missing song got its better version." / "… waits for its
  better version until your next sync." / "… couldn't get its better version yet." The dry run's rows say `would`;
  `auto_upgrade_preview().start_note` adds "{n} missing songs get their better version at the end of the sync[, once rekordbox is
  closed]." (one song is named: "Artist – Title gets its better version at the end of the sync[, once rekordbox is
  closed]."; after the upgrades' line; with the switch off it is the only line). `sync_preview().auto_upgrade` still counts
  upgrades only (`ready`; null with the switch off): a placement is visible in the dry run's block, not in that count.
- **The check of a placement** (`rekordbox_check.reason: "placed_missing"`, `check_view.reason`; the batch item's `batch` and
  `started_by` as above): the record holds `match`, `offset_ms`, `aligned` (the new file was rendered lined up with
  rekordbox's timeline of the missing file; false when that timeline was unknown, or another edit took the missing file's
  name) and `repointed` (rekordbox's track of the missing file was pointed at the new file), and `reload_tag` false
  (rekordbox's text columns are never written). `check_view` sends `match`, `offset_ms`, `aligned` and `text`, not
  `repointed`: the window reads the case from `text` and the row's `detail`.
  The row's short line (`views.check_status`) and the card's `text` (`report.placed_check_text`), five cases: repointed and
  aligned "better version in place: play it once"; repointed, not aligned "better version in place: check cues and grid";
  not repointed, the same edit "better version in place, not in rekordbox"; not repointed, another edit as a new file "add as a
  new track, set the cues"; not repointed, another edit under the missing file's name "check cues and grid". Its undo puts
  the song back in Missing files (Download again is asked again).
- **`auto_upgrade_preview()`** answers `{auto_upgrade, start_note}`: the phase's block (`dry_run: true`) or null, and the Sync page's before-start line.
  Shape: `AutoUpgradePreviewAnswer` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
- **Events:** a sync job sends `BatchProgress` during its phase, after a `Message` "Upgrading {n} tracks at the end of
  the sync…" (and, for placements, "Putting in the better version of {n} missing song(s) at the end of the sync…"; when
  rekordbox is open, "{n} upgrade(s) wait for rekordbox to be closed." and "{n} missing song(s) wait for rekordbox to be closed
  to get their better version.") (`done` of `total` handled; `track_id` / `name` the track in work). The phase starts only when the run
  reached its end: never after Stop or a crash. A Stop during the phase ends the batch (the rest are
  `skipped` / `not_reached`, no Resume is offered for it) and the sync's `exit_code` is 130.
- **Fake scenarios:** `missing_files` (the end of its sync holds a done `place` row, `rekordbox` open makes it wait; with the switch off a batch `download_again`), `sync:auto-done`, `sync:auto-rekordbox-open`, `sync:auto-running`, `todo:auto-waits`,
  `todo:auto-refused`, `todo:auto-batch`, `settings:upgrades-on`, `settings:upgrades-off`, `setup:downloads-auto`; the
  dev toolbar's "rekordbox open" toggle sets `rekordbox_status().running`.


## Convert and clean names (issue 33 stage D)

Convert to AIFF, Give it its clean name, Make all lossless files AIFF and To-do's "Won't play well on CDJs" group (design
`docs/2026-11-07-rekordbox-repoint-design.md` §2, plan `docs/2026-11-13-rekordbox-stage-d-plan.md`). The shapes below
are generated (`hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`: `AiffPlan`, `AiffScope`, `AiffBatchResult`, `TrackAiff`, `CdjWhy`, `CdjWords`); the new methods are in `contract.ts` and, as `LIBRARY_METHODS` members,
answer `no_library` without a music folder.

- **`aiff_plan(scope, only?)`** (read, any time) → `{plan: AiffPlan}` (`aiff_plan.AiffPlan.to_dict`). Shape: `AiffPlanAnswer`.
  `only` is the command line's (`aiff rename --dry-run`; the window sends none): `"rename"` plans Rename's answer alone, as
  `rename` runs it (a file that needs a Convert is left out, in a `tracks` scope `skipped` as `needs_convert`); any other
  value is `refused`. `scope` is a selection (`tracks`, each song once), a view's own files (`lossless`: as `library()`
  lists them without filter or search, whose stored codec is lossless; `key` is null for `all` / `unlisted`) or `cdj`
  (To-do's group). Anything else is `refused` ("That isn't a set of files Discjockey can make AIFF."; an empty or malformed
  `tracks`: "No tracks were chosen."). The plan's `scope` is the scope plus a `label` ("Selection", "Won't play well on
  CDJs", else the view's title).
  - `items` are the files the run would change, in order; a Convert whose AIFF takes the name the old file held ends at the
    old path. `kinds` lists the kinds with files, in the panel's order ("FLAC → AIFF", "WAV → AIFF", "ALAC → AIFF", "AIFF
    24-bit or above 44.1 kHz → 16-bit", "New tags", "Clean name only", then "{format} → AIFF"). `skipped` is for a `tracks`
    scope only: the songs left as they are, `reason` an eligibility key (`eligible.REASONS`: `named_already`,
    `downloaded`, `needs_convert`, `away`, …) with its words.
  - `waiting` has the files that can't run now but may later, each file once and never an item, in every scope, in this
    order: `away`, `file_missing`, `no_name`, `rekordbox_unreadable`, `cloud`, `rename_blocked`, `upgrade_waits`.
    `rename_blocked` is only ever the no-free-name case here, and its words (in `waiting` and `skipped`) are "Every name
    this file could take is in use, so it keeps its name for now. Nothing was changed.", not about rekordbox.
  - `rekordbox.needs_closed` is true when an item's file is in rekordbox's library; `writing: true` (only then present) says
    a writer of any Discjockey process held `rekordbox.lock`, so master.db was not opened and the plan took rekordbox's
    cached state with no lookup of its tracks (as `rekordbox_status` answers `writing`).
  - A plan only reads: stored file facts, tags of the own AIFFs whose tags decide, no decoding. Own files without stored facts are read in memory (ffprobe) and never stored
    (`aiff_plan.with_facts`), for the window and the command line alike, for the files the scope looks at that `library
    facts` would store: at most 50, read again at every call, so the panel shows what the run (which fills the facts
    first) will do. With more, the command line's answer is `refused` (`kind` `refused`, `reason` `facts_missing`,
    `data` `{missing, most: 50}`, `next: library facts`) and nothing is planned; the window's plans on the stored facts
    alone (own files without facts left out) and never refuses for this. To-do's CDJ group counts on the stored facts
    only, so while files lack them its panel can list more than its count. A file ffprobe found no sound in (marked) is not counted and is not read.
    The command line's empty answers: `--rows` and `rename --all` with no song, and a plan of a clean library, are `ok`
    with `total` 0; `aiff convert --all` on a clean library is `refused`.
- **`track().aiff`** (`aiff_plan.file_answer`): `null` (no file, a download (also while its drive is away), a better version waiting: the upgrade decision
  stands) or `{action: "convert"\|"rename"\|null, why_not: reason\|null, kind, from, to, name_now, new_name, bytes, lossy,
  cdj: {short, words}\|null}`. `kind`, `to` ("AIFF · 16-bit · 44.1 kHz" for a Convert, null for a rename), `new_name`
  (equal to `name_now` for a Convert whose AIFF ends where the old file was) and `bytes` say what the step would do.
  **An action with a `why_not` is blocked**: `why_not` set is the reason it can't run now (`eligible.REASONS`), and for the
  three reasons that wait on something else, `rekordbox_unreadable`, `cloud` and `rename_blocked`, the answer still
  carries the `action` and its `kind` / `to` / `new_name` / `bytes`, judged as if rekordbox were not in the way (an
  unreadable library as rekordbox `none`), so the card can show Becomes, Name and Space and say why it waits. No free file
  name is a Rename with `new_name` null and `bytes` 0. For every other reason (`named_already`, `away`, `needs_convert`,
  `no_name`, …) `action` is null, `kind` / `to` / `new_name` null and `bytes` 0. `from`, `lossy` and `cdj` always say what
  the file is. rekordbox is read from the cached state. The same meaning holds for a plan's `skipped` (a reason is a
  blocked or empty answer, never an item); views, api, the fake and the command line's `aiff convert --dry-run` read the one
  `aiff_plan` and add nothing of their own.
- **Write jobs** `convert(track_ids, origin = "library" \| "todo", plan_id?)`, `rename(track_ids, plan_id?)` and `make_aiff(scope, plan_id?)` (scope
  `lossless` or `cdj`; any other is `refused`) → `{job_id}`; job kind `aiff_batch`, progress `BatchProgress`, result
  `AiffBatchResult` (items' `action` is `convert` or `rename`). One selected id is a batch
  "alone" (its job carries the `track_id`).
  - `plan_id` (the command line's `--plan`; the window sends none): only the items of that plan that still stand run
    (each item's answer as `aiff_plan` gives it now equals the one the dry run saw, keyed by song), as one batch; the
    others are `skipped` with reason `changed` (a named-songs run lists only the songs it was given), and
    `new_since_plan: [track ids]` (only when there are some) lists the songs that have an item now and had none in the
    plan. A plan none of whose songs stands (also one whose songs the run does not name) is `changed` (as for `upgrade`); a plan that had no items (a clean
    library) ends the job done with `batch` null and `total` 0 (the command line says "Nothing to change: these are clean
    AIFFs already." unless `new_since_plan` lists songs); an unknown plan is `bad_args`, an old one `refused`
    (`plan_expired`), as for `upgrade`.
  - `convert` does each file's own answer (`eligible.aiff_action`: Convert, or only the name for a clean AIFF); `rename` is
    Rename's answer alone (a file that needs a Convert is left out as `needs_convert`); `make_aiff` plans again at its start.
  - The batch's `started_by` / `scope`: `convert` → `user` / `library:selection` or `todo:selection`; `rename` → `user` /
    `library:selection`; `make_aiff` lossless → `make_aiff` / `library:<view>[:<key>]`; cdj → `cdj_all` / `todo:cdj`. A batch a
    command starts (the command line's `CliApi`) says `via` `terminal` (the window's `window`) and its selection's scope `selection`; the
    `console` scope is gone (older console batches were migrated to `via` `terminal`, scope null). The
    batch's `kind` (`aiff_batches.kind`) is `convert` (`mixed` with a Same track item).
  - A selection's results also list the songs the plan left out, as `skipped` items (counted in `total` and `skipped`).
  - Refusals end the job `refused` with `batch` null, `state` "done" and the skipped items in the result: a selection says
    the one song's own words, else "None of these can be changed right now."; `make_aiff` with nothing to do says
    "Nothing to change: these are clean AIFFs already." `rekordbox_open`, `stopped` and `busy` carry the batch as for
    Same track; one song alone that meets an open rekordbox closes its batch (no Resume), otherwise it is `stopped` and
    resumable. An item whose answer changed meanwhile is skipped with the new reason, never switched to the other action.
  - `batch_resume`, `batch_undo`, `undo_upgrade` and `rekordbox_checked` are unchanged; their `UndoResult` gains `words` on
    success only (`views.undone_words`: "Conversion undone. Your old file is back.", "Clean name undone. Your old name is
    back.", "Upgrade undone. Your old file is back."; several: "Undone. Your old files are back." / "…old names are
    back." / "…old files and names are back.").
  - A job's facts fill emits `ImportProgress` (`phase` `facts`, "Reading what your files are") through the job's events; a page may show import-style progress.
- **`library()`**: the answer gains `aiff_stopped: {batch_id, left} \| null`, the newest stopped `library:*` batch with
  items left (the header's Resume). Rows are unchanged.
- **`todo()`**: `TodoFilter` and the group list gain `cdj` after `upgrade_ready` (label "Won't play well on CDJs", hint "CDJs
  refuse or stutter on these files"; `chips.cdj`). An item is a row (`TodoItem`) with `group: "cdj"`, `detail` = its `cdj.short`,
  `free` false, `cdj: {reason: format\|bitrate\|bits\|rate_high\|rate_low, short, words}` and `aiff: reason\|null` (null:
  Convert can run now; the reason is the one the head's `all.k` counts: a file the `cdj` plan holds back says its reason there, a
  Cloud Library Sync file's `cloud` among them, so the group's not-hidden rows with `aiff` null are exactly `all.n`). The group lists an own file with stored facts the rule flags (CDJ-3000 and CDJ-2000NXS2: MP3 / AAC up
  to 320 kbps and 48 kHz, WAV / AIFF / FLAC / ALAC 16- or 24-bit at 44.1-96 kHz; anything else), no parked upgrade (that song
  is Upgrade ready's), hidden as any item, and not a song whose own file an open "Is this the same song?" question or a
  listed duplicate group asks about (that decision comes first: the question's `own_key`, the songs of the group's files; a
  group with a file away is not listed, so its songs stay here); a song listed there is listed nowhere else, and the `cdj`
  plan (head, Convert all) leaves the same songs out. The group carries `all: {n, k}`
  (what Convert all can do now / what waits, from the `cdj` plan: `total` and the sum of `waiting[].n`; no `m`) and
  `stopped: {batch_id, left} \| null` (the newest stopped `todo:*` batch). Upgrade ready's `stopped` counts only
  Same track batches. The `cdj` plan behind `all` and the rows' `aiff` is remembered on the records' generation, rekordbox's
  cache key (master.db's change, whether it runs), the folders away and the decided songs: a To-do read that changed none of
  them opens no library of rekordbox's.
- **Check items**: `check.reason` adds `converted` and `renamed`; `check_status` says "an AIFF now: nothing to redo" (or "an
  AIFF now, not in rekordbox") and "clean name now". `check_view` gains `old_name` (a `renamed` check: the file's old base
  name; else null); a `converted` check's `old_path` is where the old file is now (`Superseded/`), a `renamed` one has none.
  A `BatchCheckItem`'s `batch` gains `kind` (`upgrade`\|`convert`\|`mixed`\|null) and its `detail` is "{day} · Made AIFF" for a
  Convert batch ("{day} · Clean name" when every check is a clean name).
- **Fake backend** (`bridge/fake/convert.ts`, ports of `cdj.py` and `aiff_plan.py`): a scenario sets data only. Per track:
  `audio` (the stored facts: `codec`, `rate`, `bits`, `kbps`, `ext`, `tagsClean`; unset: what the extension suggests, a WAV is
  24-bit PCM at 44.1 kHz), `file` (the path, to give a file another name), `cloud`, `inRekordbox` (default true), `away`,
  `upgrade`, `hidden`. On the state: `rekordbox_state`, `rekordbox_running`, `freeBytes` (per drive; default 400 GB),
  `batchSkip` (a run-time skip reason per track), `batchStep`, and `batches` (batches that exist from the start: `kind`,
  `scope`, `state` `stopped`\|`done`, `started_by`, `items [{track, action, state: done\|planned}]`).

## Missing files (issue 43)

A file that one scan doesn't see is never decided: its song waits as missing (`files.missing_since`) with everything it
has, links back when the file shows up in any watched folder, and To-do lists it. Only the user's word removes an own
song or downloads a playlist song again. This section is the read side (E3a) and the two actions (`missing_files_preview`,
`missing_files`, E3b); the Auto-upgrade block's placement rows (E4b) are in "Auto-upgrade" above.

- **`todo()`**: `TodoFilter` and `TodoGroupKey` gain `missing_file`; the group is second, after `rekordbox_check` (label
  "Missing files", hint "not where they were; put a file back and it links again"; `chips.missing_file`). It lists every
  song whose file waits as missing, an own song or a song no playlist lists any more included, hidden ones as any item
  (a hidden song only with `show_hidden`, counted in `hidden_count`). It wins over every group but Check in rekordbox
  (a song with an open check is in both; `chips.all` counts it once): Upgrade ready, Won't play well on CDJs, Not found,
  Weak, Good lossy, Fake, Other and the CDJ group never hold a missing song, and `upgrade_ready_keys` (Upgrade all,
  `upgrade list`, Auto-upgrade's set) leaves it out; its parked upgrade stays. A song for which Download again was asked
  (`file_gone` set) is in no group: the sync downloads it (or puts its parked version in), unless the sync's phase
  refused that placement for a held reason (`space`, `cloud`; `auto_refused` on the parked upgrade): then the song stays in
  Missing files, `why_not` is `place_refused` with the record's own message as `words`, and `next_qobuz_check` is null
  (amended at FB). A song with no file row and
  `file_gone` (after `folder remove`) is no Not found either; its Library row says `wait: "waiting"`.
- **A missing item** is a `TodoItem` (`group: "missing_file"`, `free` false, `file_state` `file_missing`, or `offline` / `folder_missing` when its drive or folder is away) whose `detail` is "Missing since 12 Nov · was in Techno 2019" (in several places: "In 2 places now · keep one and it links again") and whose `missing` is a `MissingView`. The song decides the action, never a choice: `download_again` for a song in a playlist (an own key linked to one included), `remove` for any other. The single song's button is "Download again" (tone `filled`) or "Remove from library…" (tone `danger`: the dots because Remove asks first). `why_not` is the first reason that applies (below). `foot_note` is `words`, null when `why_not` is null or the note above says them already, which is the case for `found_twice` and `away`: `hint` is those very words. `will` is what the action does for this song: "Downloads again at your next sync", "Gets the better version already waiting for it at your next sync; nothing is downloaded" (Download again with a parked upgrade: the parked version goes in) or "Removed from your library". `in_missing_files` is true unless Download again was asked and no held refusal keeps the song in the group (one rule, `missing.in_group`, for the group, this field and the Library's). The window shows these words and decides nothing.
  Shape: `MissingView` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
- **The group carries `all: {download_again: n, remove: m, label}`**: `n` and `m` count the items not hidden whose
  `missing.why_not` is null, by action: what the commands' `--all` act on. `label` is the head link's words,
  "Select all · {k}", where `k` counts what Select all selects: every item of the group that is not hidden (a song that
  can't act now too; the selection panel says why); null when `k` is under 2 (with one, the row's own button does it).
  The window shows it as it is.
- **`track()`** gains `missing` (`MissingDetail`: the item's `MissingView` plus `line`, `hint` and `hint_library`; null
  when the song's file isn't marked missing). `line` is "Missing since 12 Nov. It was in Techno 2019." (in several
  places "Found in 2 places: Techno 2019 and Old crates."). `hint` is what can be done, by
  action; with `upgrade_waiting` the placement's or Remove's variant; amended at FC: by `why_not` first, so it never
  advises what the disabled button under it refuses: `never`, `check_open` and `place_refused` say the first sentence
  only ("Put the file back in any watched folder and it links again with everything it had."), `away` says its reason's
  words ("Its drive isn't connected; plug it in to decide."), `asked` the first sentence and "You asked for it already:
  it happens at your next sync."; in several places "Delete or move away the copies
  you don't want; the one left links again.") and `hint_library` (the same first sentence, for the Library, whose foot
  has no such buttons and only opens To-do: "... Or open it in To-do to download it again." / with `upgrade_waiting`
  "... Or open it in To-do to download it again: the better version already waiting for it goes in, and nothing is
  downloaded." / "... Or open it in To-do to remove it from your library." (Remove's parked-version sentence follows
  as in `hint`); the several-places hint is the same in both; amended at FC: for a song already asked for (`asked`, which
  To-do doesn't list) it is the same as `hint`, the first sentence and "You asked for it already: it happens at your next
  sync.", never "open it in To-do"). A file gone since the last scan shows `file_state: "file_missing"` from the
  live check, without `missing`. `next_qobuz_check` is `"next_sync"` for a song whose Download again was asked.
- **`library()`**: a row's `file_state` may be `file_missing` (the stored mark; `LibraryRow.file_state` is `FileState |
  "no_file"`); every row carries `in_missing_files` (amended at FC: true only for a row whose file waits as missing and
  that To-do's Missing files group lists, by `missing.in_group`: false for every other row and for a song whose Download
  again was asked; the window decides nothing about whether To-do lists a song); `summary.to_do` counts a missing song (own ones too). A `not_found` row's `next_try` is `"next_sync"` after
  Download again, and a song with no file row and `file_gone` is `waiting`, not `not_found`.
- **Reasons**: the eight `why_not` keys are `refused` reasons in `hub/outcomes.py` (the command line's result rows use
  them; `away` keeps the row the rekordbox flows have). Offline wins: a missing song whose drive isn't connected is
  skipped by both actions (its drive isn't there to tell), checked right after `not_missing`.
  Words (`wrong_action` names the action the song gets instead): `not_missing` "Its file is back."; `away` "Its drive
  isn't connected; plug it in to decide."; `wrong_action` "This
  song gets {Download again | Remove from library} instead."; `found_twice` "Delete or move away the copies you don't
  want; the one left links again." (the same sentence as the details' hint; refused for both actions, amended at FB: a song
  whose file is in several places isn't removed, both copies are there); `never` "You chose Never download for it."; `check_open` "Its rekordbox check is still open:
  finish it first."; `place_refused` "The sync couldn't put its better version in; it tries again when that changes." (the fallback;
  the item says the refusal record's own message instead, e.g. "Not enough free space on that drive."); `asked` "You asked for it already: it happens at your next sync."
- **Fake backend**: scenario `missing_files` (`hub-ui/src/lib/bridge/fake/missingFiles.ts`): the plain scenario with eleven
  songs whose file waits as missing (a playlist song, one with a parked better version, one found in two places, one
  marked Never download, a hidden one, one whose Download again was asked, one whose Download again was asked and whose
  better version is parked (the sync's last phase places it: a done `place` row), and four own songs: plain, with a parked
  version, with an open rekordbox check, on a drive that is away). `todo()`, `track()` and `library()` answer from them as
  the engine does (the group, `missing`, `all`, `file_state`, `next_qobuz_check`); the engine's words are pinned against
  `discjockey/missing.py` by `missingFiles.test.ts`. `missing_files_preview` and `missing_files` answer from the same
  state with the engine's rules and words (`previewMissing`, `runMissing`, `summary`; the summary line's sentences are
  pinned against `tests/test_missing_actions.py`): Download again sets `fileGone` (the song leaves To-do, its parked
  version stays), Remove deletes an own song and its parked version, a song the action does not fit is a `skipped` row
  with its reason, and every song skipped ends the job `changed` with the result kept. An unknown action is `bad_args` in
  the fake as in the engine (`outcome` and `kind` `bad_args`, `reason` `usage`; the window sends only the two words). The
  fake's Sync plan lists the download that Download again asks for (group `acquire:redownload` "Download again", rows
  `acquire` / `redownload`) for a missing playlist song with no parked version and not marked Never download; a song with a
  parked version plans none, the sync's last phase places it (the fake's `planPhase`: `place` rows first, `placed_missing`
  section, the batch's `started_by` by the switch).

### The two actions (read: `missing_files_preview`; write job: `missing_files`; both in `LIBRARY_METHODS`)

The action follows the song (`missing.action_for`), never a choice: `download_again` for a song in a playlist, `remove`
for any other. Both methods take `track_ids` (a non-empty list of song keys, each once; a lone string or an empty list is
`refused`) and `action` (`download_again` | `remove`; any other word is `bad_args`, "action must be one of
download_again, remove."). A song the action does not fit is not switched to the other action: it is skipped with its
reason.

- **`missing_files_preview(track_ids, action)`** (read, the dry run of both commands): one item per song, in the order
  asked. `will` says the action runs for it now; `words` is the action's `will` sentence when `will`, else the
  reason's sentence. A key that is no song is an item with `reason: "not_missing"`. `words` of the preview is the one
  line ("2 songs download again at your next sync; 1 is skipped." / "Removes 1 song from your library." / with
  parked versions among them: "1 song downloads again and 1 gets the better version already waiting for it, at
  your next sync."). `button` is the selection panel's button over the `n` that run ("Download again · {n}" /
  "Remove from library · {n}…"; null when `n` is 0) and `confirm` Remove's question for them: "Remove from your
  library?" for one, "Remove {n} songs from your library?" for several, body "Their files aren't in your watched
  folders. …" (for one song, singular: "Its file isn't in your watched folders. Discjockey forgets this song, your
  answers about it and any better version waiting for it. If the file comes back later, it is added as a new
  song."), `confirm_label` "Remove", `tone` "danger"; null for Download again and for `n` 0. The window sends the
  ids whose item has `will` and shows these words as they are. Reads only: no lock beyond the hub's read, nothing
  is stored.
  Shape: `MissingPreview` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
- **`missing_files(track_ids, action)`** (write job, kind `missing_files`; answers `busy`, `console` and `sync_running`
  as every write method): each song is asked again when the job runs under the library lock, so a song that changed
  since the click (its file came back, the other action became its own, Never download, an open rekordbox check, Download
  again asked already) is `skipped` with its reason. `JobFinished.result` is a `MissingResult`:
  one row per song with its words (a done song's `will` sentence, a skipped song's reason sentence, `wrong_action`
  naming the action the song gets instead) and the one line of the preview's grammar in the past for Remove
  ("Removed 2 songs from your library; 1 is skipped."). **Every song skipped** ends
  the job `changed` (`message` = `words`) with the same `MissingResult` kept in `JobFinished.result`. The sync's plan
  is made again when the job ends, so the Sync page shows the planned download at once (a song with a parked version
  plans none: the sync's last phase places it).
  Shape: `MissingResult` (generated: `hub-ui/src/lib/bridge/types.gen.ts`, `discjockey help <command> --json`).
  - **Download again** sets `file_gone` and changes nothing else: the file row, the parked upgrade and its file, every
    answer. The next sync downloads the song, or puts its parked version in.
  - **Remove from library** is final (no undo; the window asks first): it deletes the song's records (its missing file
    row, the song, its aliases, the answers naming it) and the parked download in `Upgrades ready/` its song had. It
    deletes no music file: the song's own file is not there, and a parked record that names a path outside `Upgrades
    ready/` leaves that file alone. Nothing is removed by a scan, a sync or the preview, only by this call.
- **Problem kinds**: `bad_args` (unknown action), `refused` (no songs), `changed` (every song skipped), and the write
  methods' `busy` / `console` / `sync_running` / `no_library`.
- **Command line** (`discjockey missing list | download | remove`): `missing list [--hidden]` is `todo` with the filter
  `missing_file`; `missing download` and `missing remove` take songs (a song key, or the path of a missing row's old
  file) or `--all`, which is this group's `all` split by action (the songs the window's "Select all · n" selects; with
  none left the command answers `ok`, "No song whose file is missing waits for …", and starts no job; its `--dry-run` answers `ok` too, with
  the preview's own shape: `items` empty, `n` and `skipped` 0). `--dry-run` is
  `missing_files_preview`; `missing remove` needs `--yes`. A run with a skipped song ends `partial` (exit 6), a run in
  which every song was skipped `refused` (exit 7); `data` is the method's answer, its rows are `MissingItemResult`s.
