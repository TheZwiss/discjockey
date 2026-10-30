# Library and sources: watched folders, import, tidy-up, more playlist services — design

Status: draft for review (2026-10-23).

## 1. Goal

Today Discjockey thinks in Spotify tracks: every track is keyed by its Spotify id, every playlist is a Spotify
playlist, and the sync decides where each file lives. This design turns it into a library manager:

- **Playlists from several services:** Spotify, Qobuz, SoundCloud and YouTube Music. The link in `playlists.txt`
  says which service it is.
- **Your existing music:** you choose folders Discjockey watches (like rekordbox's search folders). Every file there
  is indexed, its quality analysed, identified where possible, and offered upgrades, as if Discjockey had
  downloaded it.
- **Files are found again** when you move or rename them inside the watched folders.
- **Library's browser column** lists playlists and folders side by side, each with an icon for where it comes from.

Decided with the user:

- **Import manages files in place.** Nothing is copied, moved or renamed on import. rekordbox keeps working.
- **The user owns where files live (option A).** The sync picks a folder only when it downloads something new. It
  never moves a file afterwards on its own.
- **Moving files to match the playlist order is an explicit, logged, undoable action** ("Tidy up", §8). It is
  offered when the playlist order or a playlist's folder name changes, and as a button on the Playlists page.
  Files the user placed by hand are unticked by default; the user sees the list and the rekordbox consequences
  before anything moves.
- **A playlist entry shows the playlist's songs wherever their files are; a folder entry shows only the files
  physically in it** (§11).
- **An unplugged drive is offline, not deleted.** Nothing is downloaded again because of it.
- **Imported files are linked to playlist songs on their own only when that is certain;** otherwise the To-do page
  asks "Is this the same song?".
- **A lossy imported file that is in a playlist counts as that playlist's copy** and gets the usual weekly upgrade
  checks. No second copy is downloaded next to it.
- **Tracks only on SoundCloud or YouTube Music** come in as not lossless from that service (its free download when
  one is offered), like any track Qobuz doesn't have.
- The user left the technical choices to Claude; they are made below with their reasons.

Never changes: Discjockey never deletes a music file. Files it replaces go to `Superseded/`.

Out of scope: identifying files by their sound (AcoustID; a later, opt-in addition), live file-system watching
(scans run at fixed moments, §6.4), importing rekordbox's own playlists, Apple Music / Tidal / Deezer / Beatport,
syncing anything back to a service.

## 2. Terms

| Term | Meaning |
|------|---------|
| **Song** | One recording. Has a title, artists, a length, and every id it is known by (ISRC, Spotify, Qobuz, SoundCloud, YouTube Music). |
| **File** | One audio file on disk, in a watched folder. Belongs to at most one song. |
| **Source** | A service Discjockey reads playlists from. A source turns a link into an ordered list of songs. |
| **Playlist** | A line in `playlists.txt`: a folder name and a link. Says which songs the user wants; the order of lines is the priority. |
| **Watched folder** | A folder Discjockey indexes, with everything below it. `Library/` in the music folder is always one. |
| **Placement** | Where a new download lands: `Library/<Folder>/` of the first playlist that has the song (`not_lossless/` below it for lossy files), as today. |
| **Placed by** | Who put a file where it is now: `app` (downloaded or moved there by Discjockey), `user` (moved there by hand), `import` (found there by a scan). |
| **Content key** | A fingerprint of a file's audio bytes that survives renames, moves and tag edits (§6.2). |

## 3. What the user experiences

1. **After the update (stages 1–2):** nothing visible changes in the library. The sync stops moving files when the
   playlist order changes; the Playlists page instead asks whether to move them (§8). Files moved by hand inside
   `Library/` are no longer downloaded again: they are found where they are.
2. **Qobuz playlists (stage 3):** a Qobuz playlist link works in `playlists.txt` and on the Playlists page. Its
   tracks download exactly, by Qobuz id.
3. **Import (stage 4):** Setup gets an optional step "Your existing music", and Settings a "Watched folders"
   section. Adding a folder starts a background scan with progress: it indexes every file, analyses quality, and
   links files to playlist songs. The To-do page then shows upgrades, "Is this the same song?" questions and
   duplicates.
4. **Library layout (stage 5):** in Library the sidebar folds into a rail and a browser column lists the
   playlists (each with its service's icon) and the watched folders' crates (folder icon); Favourites are shortcuts
   on every page.
5. **SoundCloud and YouTube Music playlists (stage 6):** links of those services work too.

## 4. Stages

Each stage gets its own plan, ends with the app working, and updates `README.md` and `docs/hub-bridge-contract.md`.
Stages 1 and 2 ship in the same release, because stage 1 alone would stop moving files without offering the
tidy-up.

| Stage | Delivers | Sections |
|-------|----------|----------|
| 1 Foundation | `library.db`, songs/files/watched folders, migration, scanner, content keys, option-A placement | §5, §6, §7 |
| 2 Tidy-up | Tidy-up preview, the playlist-save question, folder rename on disk, move batches with undo | §8 |
| 3 Qobuz playlists | The source interface, Spotify behind it, the Qobuz source | §9 |
| 4 Import | Watched folders in Setup/Settings, the import job, identification, duplicates, upgrades for imported files | §10 |
| 5 Library layout | The rail and browser column, Favourites, crates, playlist and folder views (two steps) | §11 |
| 6 SoundCloud, YouTube Music | Two more sources, title splitting | §9.4, §9.5 |

## 5. The library database (stage 1)

### 5.1 Why SQLite

`state.json` holds 366 tracks in 250 KB and is rewritten whole after every step. An imported library of 10,000
files would make it about 7 MB per write, and indexing needs lookups by path, content key, ISRC and service id. The
state moves into `.discjockey/library.db`, using Python's built-in `sqlite3` (no new dependency), in WAL mode with
`synchronous=FULL`.

### 5.2 What it holds

- **songs:** id, artist, title, artists, album, duration, ISRC, image link, `in_playlists`, `added`, and the
  acquisition bookkeeping that today sits on a state entry and belongs to the song: `last_attempt`,
  `last_upgrade_check`, `upgrade` (the parked version), `rejected_sources`, `declined_streams`, `free_downloads`,
  `originals_searched`, `qobuz_searched`.
- **song_ids:** (service, id) → song, unique per (service, id). A Spotify relink alias is one more `spotify` row.
- **files:** id, song (nullable), watched folder, path relative to it, size, mtime, content key, placed by, online,
  first seen, last seen, and the quality fields that today sit on an entry and belong to the file: `status`
  (lossless, not_lossless, fake_lossless), `source`, `source_id`, `source_format`, `cutoff_hz`, `source_kbps`.
- **watched_folders:** id, absolute path, kind (`library` for the music folder's `Library/`, `import` for the
  user's own), added, last scan.
- **never, qobuz_usage:** as today.
- **pending:** the crash-safe operations journal (§5.4).
- **move_batches, moves:** the tidy-up log (§8.4).
- **meta:** schema version.

A song's `status` "missing" today means "no file": in the new model that is a song with no file row. A song is
*satisfied* when it has a file that is online, or offline (§6.4).

`playlists.txt` stays the source of truth for the playlist list, so the console keeps working and the user can still
edit it by hand.

### 5.3 Migration

On the first run of the new version against a music folder with `state.json` and no `library.db`:

1. Build `library.db` from `state.json`: one song per entry (the Spotify id and its aliases as `song_ids`), one
   file per entry that has a path (placed by `app`), `Library/` as the first watched folder.
2. Compute the content keys of the migrated files.
3. Rename `state.json` to `state.v1.json` (the backup) and write a new `state.json` holding only
   `{"version": 2, "moved_to": "library.db"}`. An older Discjockey reads it, sees version 2, and stops with its
   existing message ("this Discjockey only knows version 1. Nothing was changed.") instead of treating the library
   as empty and downloading everything again.

The migration runs under the lock, is all-or-nothing (the database is written to a temporary name and renamed into
place last), and a failed migration leaves `state.json` untouched. Pending operations in `state.json` are recovered
(the existing `recover_pending`) before migrating.

### 5.4 Crash safety

The rule stays the same as today: record the step as pending, do the file operations, apply the result, clear the
pending record. Each of those is one committed transaction, and `recover_pending` reads the `pending` table. The
`run_op` interface keeps its shape, so callers change little.

### 5.5 Code boundaries

- A new module `discjockey/db.py` owns the schema, the migration and every query. Nothing else writes SQL.
- `planner.py` stays pure. It gets a plain snapshot (songs, files, watched folders online/offline, the fetched
  playlists, today) and returns a plan; it never touches the database.
- `hub/views.py` stays pure and reads the same snapshots.
- `library.py` keeps the paths, the lock and `run_op`, now backed by `db.py`.

## 6. Watched folders and the scanner (stage 1)

### 6.1 What a scan looks at

Every watched folder and everything below it, skipping hidden folders, the music folder's `Superseded/`,
`Upgrades ready/` and `.discjockey/`, and anything that isn't audio. Audio is: `.aiff .aif .wav .flac .mp3 .m4a
.ogg .opus`. Watched folders that sit inside each other are scanned once, as the outer one.

### 6.2 Content key

A fingerprint of the audio bytes only, so tag edits (by the user, rekordbox or Discjockey) don't change it:

- Find the audio payload: the `SSND` chunk (AIFF), `data` chunk (WAV), the frames after the metadata blocks (FLAC),
  the frames between ID3v2 and ID3v1/APE (MP3), `mdat` (M4A), the pages after the header packets (Ogg/Opus).
- Key = payload length + SHA-256 of three 256 KB windows (start, middle, end). Reading 768 KB per file keeps the
  first scan of a large library to minutes, not hours.
- A file whose payload can't be found gets the same windows over the whole file.

Changes Discjockey makes itself (a swap, a re-tag) update the stored key in the same operation.

### 6.3 Reconciling

A file is known by (watched folder, path, size, mtime). A scan sorts every file into one of:

- **Unchanged:** same path, size and mtime. No reading.
- **Changed in place:** same path, other size or mtime. Re-key. Same key → only the tags changed (keep everything).
  Other key → the audio was replaced outside Discjockey: keep the song link, analyse the quality again.
- **Moved:** a known path is gone and a new path has its content key. Update the path and set placed by `user`.
  If more than one new file has that key, nothing is decided: the To-do page asks which one it is (the existing
  "ambiguous" flow).
- **New:** a path with an unknown key. In `Library/`: indexed, not linked to a song (it shows under "Also in this
  folder", §11). In an import folder: handled by the import job (§10). A bought file under the expected name is
  still adopted as today (§7).
- **Gone:** a known path is gone and nothing has its key. The file row is removed and its song has no file; for a
  playlist song the sync downloads it again, as today.
- **Copy:** a new path has the key of a file that is still there. Indexed as its own file and reported as a
  duplicate (§10.4).

### 6.4 Offline

A watched folder is offline when its path doesn't exist or, for a path under `/Volumes/<name>`, that volume isn't
mounted. A scan never touches an offline folder's files: they keep their rows, marked offline, and their songs stay
satisfied. Views show them as offline. Nothing is downloaded and nothing is reported as gone.

A scan runs at the start of every sync and dry run, when the window opens, and when the window comes back to the
front after more than a minute. A scan with nothing changed takes one `stat` per file.

## 7. Placement under option A (stage 1)

The planner rules change:

- **New song (rule 1):** download into the placement folder, as today.
- **No file (rule 2):** download again when due, as today; adopt a bought file under the expected name in the
  placement folder, as today.
- **File gone (rule 3):** the by-name search in `Library/` is replaced by the scanner's content key (§6.3).
- **Different folder (rule 4):** removed. A file in another folder than its placement folder stays there; the
  tidy-up (§8) is where it moves.
- **Lossy (rule 5):** unchanged: weekly upgrade checks, bought-file adoption. A bought file is looked for in the
  placement folder and next to the song's current file.

Upgrades work on the file where it is. Swap writes into the existing file; "Add as new file" puts the new file in
the current file's folder under the correct "Artist - Title" name and moves the old one to `Superseded/`. The
`not_lossless/` → folder move after a swap happens only for a file in a playlist folder's `not_lossless/`.
`Superseded/` and `Upgrades ready/` mirror the file's folder: `<Folder>` for a playlist folder, `<watched folder
name>/<subfolders>` for an import folder.

## 8. Tidy-up (stage 2)

### 8.1 The target of a file

For a file linked to a playlist song: the placement folder of that song (first playlist by priority, `not_lossless/`
below it when lossy), under its current file name. Files without a playlist song have no target and are never
moved. Offline files are listed as "offline, skipped".

### 8.2 Where it is offered

- **Saving the Playlists page:** when the new order or a renamed folder would give files another target, the save
  preview says "N files would sit in a different folder" and offers **Save and move the files** or **Save, leave
  files where they are**. The second means only new downloads follow the new order.
- **Renaming a playlist's folder:** the preview also offers **Rename the folder on disk too**: one folder move
  instead of a move per file. Not offered when the new name is taken.
- **A "Tidy up files" button** on the Playlists page, at any time.
- The console never moves files. After a sync it prints "N files are not where the playlist order puts them; tidy up
  in the window."

### 8.3 The preview

One list, a row per file: from → to, with a checkbox. Ticked by default when placed by `app`; unticked and marked
"you put this here" when placed by `user` or `import`. Rows that can't move (offline, a file with that name already
at the target) are shown without a checkbox, with the reason. A tidy-up never renames a file, not even one moving
from an import folder into `Library/`: rekordbox's Relocate finds files by name. The "Artist - Title" naming rule
for `Library/` (CLAUDE.md's invariants) applies to files Discjockey downloads or adds; stage 2 amends its wording.

Above the button, the warning says in plain words: how many files move and between which folders; that rekordbox
may show moved tracks as missing and that Relocate finds them by file name; and that the tidy-up can be undone from
this page. The warning's rekordbox sentences are checked against the real rekordbox in the stage's live check
before release.

### 8.4 The log and undo

Each tidy-up (and each folder rename on disk) is one **move batch**: when, what started it, and each file's from and
to. The moves run through `run_op`, so a stopped tidy-up is finished or rolled back the next time. The moved files
become placed by `app`.

The Playlists page lists recent batches with an **Undo** button. Undo moves each file back, in reverse order, only
when the file is still where the batch put it (same content key) and its old place is free; every skipped file is
listed with its reason. An undo is a batch of its own. Batches don't expire; one whose files have all moved on since
shows "nothing left to undo".

## 9. Sources (stages 3 and 6)

### 9.1 The interface

A source is a module with:

- `recognise(link) → playlist id | None`: whether the link is one of its playlists.
- `fetch(playlist) → FetchedPlaylist`: the playlist's songs in order, each a `SourceTrack` (service, id, title,
  artists, album, duration, ISRC or none, link, image) or a reason it can't be read.
- `login_state()`: logged in, not needed, or what to do; `info(playlist)`: name, owner, track count, for the
  Playlists page.

`SpotifyTrack` becomes `SourceTrack`. Every track link ("Open in Spotify") becomes the track's own service link.
The sources live in `discjockey/sources/` (`spotify.py` moves there).

### 9.2 Linking a fetched track to a song

In this order: an existing song with the same (service, id); the same ISRC; for a track without ISRC, a song with
the same normalised artist and title and a length within 3 seconds. Otherwise a new song. A link found by ISRC or
name adds the track's (service, id) to the song.

### 9.3 Qobuz

Read through streamrip's client with the existing login: public playlists and the user's own. Every track has a
Qobuz id and an ISRC, so the first try is a download of exactly that id; the usual chain (Qobuz search, then the
fallbacks) follows only when that track is preview-only or unavailable. Qobuz playlist reads don't count against the
download limits.

### 9.4 SoundCloud

Read with yt-dlp (sets, and the user's likes when logged in through the browser, as the SoundCloud fallback already
is). Titles are split: "Artist - Title" when there is a dash, otherwise the uploader is the artist; tags like
`[FREE DL]`, `(Premiere)` and a leading `PREMIERE:` are dropped. The search order is: Qobuz (by name), then the
SoundCloud track itself (its free download first, when offered), then the other fallbacks.

### 9.5 YouTube Music

Read with yt-dlp. A "song" entry carries artist, title and album; a video entry is split like a SoundCloud title.
The search order is: Qobuz (by name), then the entry itself, then the other fallbacks.

## 10. Import (stage 4)

### 10.1 Choosing folders

- **Setup:** an optional step "Your existing music" after the music folder: add one or more folders, or skip.
- **Settings → Watched folders:** the list with each folder's state (online, offline, scanning), file count, and
  Add / Remove.
- **Removing a folder** removes its files from the index (the files on disk are untouched). When playlist songs had
  their only file there, the confirmation says how many will be downloaded again on the next sync.

### 10.2 The import job

A background job like the sync (one at a time, under the lock, can be stopped, shows progress), resumable: each
file's progress is stored, so a stopped import continues where it stopped. Per new file:

1. Probe and read tags.
2. Analyse quality with the existing verdict rules (`quality.py`). The spectrum is drawn on demand, as today.
3. Identify (§10.3).
4. Done: the file shows in the library.

### 10.3 Identifying

- **Certain:** the file's ISRC tag matches a song, or its tags/name give an artist and title that match a playlist
  song exactly (normalised) with a length within 2 seconds → linked.
- **Plausible:** a playlist song matches on title with a different or missing artist, or the length is off by
  2–10 seconds → linked only after the user answers "Is this the same song?" on the To-do page.
- **Otherwise:** a song of its own, not in any playlist. Artist and title come from the tags, else from a file name
  "Artist - Title", else the file name is the title.

Imported songs not in a playlist are searched on Qobuz (ISRC first, then name) only to find upgrades for lossy
files (§10.5); lossless files aren't searched.

### 10.4 Duplicates

Two files with the same content key, or two files linked to the same song, show on the To-do page as a duplicate:
both files with path, quality and a player. Choices: **Keep both**, or **Move one to Superseded** (never a delete).

### 10.5 Upgrades for imported files

Lossy and fake-lossless imported files get the weekly upgrade check like any lossy file, within the download limits
of the Download limits page; a large import spreads its first checks over several runs instead of using up a day's
Qobuz allowance. Parked versions, swap and "Add as new file" work as in §7.

## 11. Library layout and views (stage 5)

### 11.1 The browser column

The agreed design is `docs/hub-mockups/design-system/library-layout.html` with its notes `library-layout-notes.md`;
the plan is `docs/2026-10-29-library-stage-5-plan.md`. In short:

1. In Library the app's sidebar folds into a 50 px **rail** of page icons, and a **browser column** (200–360 px, dragged
   by its edge) lists, top to bottom: **All tracks** and **Not in a playlist**; **Favourites** (the user's own order, by
   drag); **Playlists** in priority order (or A–Z), each with its service's icon and its song count, switched-off ones
   dimmed; **Folders**: each watched import folder with its **crates** (the folders that hold music themselves; wrapper
   folders get no row), then the folders in `Library/` that belong to no playlist. A playlist's own folder is not
   listed again. A filter field (⌘K) filters the names and hands a text that matches nothing on to the track search.
2. Other pages keep the full sidebar, which lists the pages, Library and the Favourites. The user can fold it on any
   page.
3. Library's right panel leaves the page: the summary becomes a strip and a track's details an inspector that opens
   on demand.

The icons are the services' original logos in their own colours (the user's wish, 2026-10-29), used unchanged and only
to name the service. The column follows the seamless-chrome rules of `docs/hub-design-language.md`.

### 11.2 A playlist's view

- The playlist's songs, wherever their files are. A file outside the playlist's folder has a quiet location note
  ("in Techno 2019"). An offline file shows as offline; a song without a file shows as today (waiting, not found).
- Below them, **Also in this folder**: files physically in the playlist's folder that aren't in the playlist.

### 11.3 A folder's view

The files physically in the folder and its subfolders, with the crate they sit in as a column. A file that belongs to
a playlist carries that playlist's name as a badge.

## 12. Error handling

- **Database can't be opened or is from a newer version:** the run stops with a plain message; nothing is changed.
- **Migration fails:** `state.json` is untouched; the message says so and the next run tries again.
- **A watched folder disappears mid-scan:** it becomes offline; the scan goes on with the others.
- **A file can't be read during import** (damaged, permission): it is listed under "Couldn't read" in the import's
  report and tried again on the next scan.
- **A move fails mid-tidy-up:** that file stays where it was, the batch records it as skipped, the rest go on.
- **A source can't read a playlist:** the existing playlist error card, worded for that service.

## 13. Testing

Tests never touch a real library (`conftest.py` already blocks the network and points the support folder at a temp
folder).

- **db / migration:** state.json fixtures (with aliases, pending operations, missing files, parked upgrades) migrate
  to the expected rows; a crash at each migration step leaves state.json usable; an older version refuses the
  version-2 stub.
- **Content key:** each format's payload is found; editing tags keeps the key; changing audio changes it.
- **Scanner:** every case of §6.3 with temp folders; an offline folder (missing path, unmounted `/Volumes` path)
  keeps its files satisfied and triggers no download.
- **Planner:** option A: a moved file is not moved back and not downloaded again; new downloads follow the order.
- **Tidy-up:** targets, default ticks by placed-by, skipped rows, a crash mid-batch, undo with each skip reason.
- **Sources:** recorded API and yt-dlp responses per service; title splitting cases; linking by id, ISRC and name.
- **Import:** resumable after a stop; certain vs plausible vs own song; duplicates.
- **UI:** the existing fake backend gets scenarios for each new view; screenshots against approved mockups.

Live checks for the user, at the end of the stages that need them: rekordbox after a tidy-up and after an undo
(stage 2), and importing their own library (stage 4).
