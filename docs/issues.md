# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 33. Lossless AIFF for imported files, with rekordbox pointed at them — needs a design round (user, 2026-10-31)

Audit 2026-11-05: parked, nothing of it is built (no AIFF conversion of imported files, no rekordbox repoint; the New
track choice still keeps the download as it is).

The user's wish: files of their own (imported, MP3 or other lossy) end up as the library format (16-bit AIFF), with
rekordbox's entry pointing at the new file automatically. Then every later upgrade is an in-place audio swap inside the
same file ("Same track"), and cues and beatgrid stay exact. Two shapes to weigh in the design round:
- **All at once:** at import, convert the whole library to AIFF and repoint rekordbox for every file.
- **One by one (likely better):** nothing is converted up front. When an upgrade is ready, the lossless AIFF goes in
  and rekordbox's entry is repointed to it at that moment.

**Bundle with it:** today the "New track" choice keeps the downloaded file as it is. Its cues therefore fit only
"to within N ms" (`report.SHIFTED_EDIT_CHECK`), while "Same track" shifts the audio sample-exactly
(`upgrades.build_staged`). If the new file is also shifted, cues fit exactly with either choice.

**Facts to design around** (reference: the rekordbox notes):
- rekordbox's `master.db` is SQLCipher-encrypted, so "auto point rekordbox" needs a safe route, such as the XML
  export/import or a relocate rekordbox does itself.
- Cues and beatgrid live at the rekordbox entry, not in the file.
- Relocate matches on file name only.
- rekordbox keeps following files it finds anywhere in the watched folder.

Any write to the user's rekordbox data needs a backup and an undo, and the user's go.

## 32. Library stage 6 leftovers (SoundCloud and YouTube Music playlists)

Noted while reviewing `docs/2026-10-31-library-stage-6-plan.md`. What is left are live checks, which need the real
services.

- **Live check (a Go+-only SNIP track, stage 6 D9):** that a Go+-only upload seen through an account without Go+ really
  lists the 30 s preview (`…_preview`) and not a full stream, and that a Go+ account lists a full ~128 kbps one for such
  an upload (read from yt-dlp's code, not seen live). Two more yt-dlp assumptions, also unseen: for a Go+ track whose
  `hq` transcoding is DRM-protected, yt-dlp still picks a named, unprotected full format (`http_mp3_128` or an HLS mp3
  id) for `info["format_id"]` and never a `ctr-`/`cbc-` protocol one, so `stream_kbps` can tell it from "only
  protected" (then no format is named, or it ends in `_preview`); and `abr`/`tbr` of that format is its own ~128, not
  the protected stream's. If either is wrong the typical Go+ track's 128 stream is rejected as DRM again (nothing else
  breaks).
- **Live check:** the short-link redirect follows one hop. Confirm that `on.soundcloud.com` goes straight to
  `soundcloud.com/...`.

## 30. To-do decision panels leftovers

Audit 2026-11-05: both points are still open (the subtitle in `todoModel.headerSub` and the grey step numbers in
`NumberedSteps.svelte` are unchanged); nothing else is missing.

Noted in the screenshot review of the To-do panels (2026-10-31).

- **The To-do header's subtitle wraps to two lines at 1100×700 when there are questions** ("… not lossless yet · 1 question
  about your files"), so the header's height changes between the filters. It existed before stage 5.
- **The step numbers in the "In rekordbox" card stay grey** where the mockup drew them yellow. They come from a shared
  numbered-list block, so changing the colour there changes every numbered list; decide it centrally, not in To-do.

## 29. Library stage 5b leftovers (folders)

Audit 2026-11-05 (updated by leftovers round C2): the engine points are done: run reports name an own song's folder
(`run.select_actions` / `Executor` take `where`, `jobs.folder_names`), `SORTS["length"]` puts songs without a length
last either way and the playlist's length stands in (`views.sort_rows`), `api.reveal` opens an absolute path inside a
watched import folder (symlinks followed, nothing else), `set_crates_shown(paths, shown)` saves several crates in one
write, `set_favourites` no longer builds the sidebar (`views.sidebar_targets`), `set_crate_shown` refuses a path that is
no crate of a watched folder. Left for the UI round: `libraryTarget` and `/library/playlist/:name`, the row's next-try
date (also needs the engine to put the date on `LibraryRow`), Show in Finder for watched folders and crates, Settings'
All / None using `set_crates_shown`, and the points below that are not engine ones.

Noted while building and reviewing `docs/archive/2026-10-29-library-stage-5-plan.md`, step B (folders), task groups B2 to B7.

- **Same label for two crates:** two crates under different wrapper folders can get the same label ("Hard › 2019"),
  so the UI tells them apart only by the tooltip (the full path). This is the plan's D8 rule.
- **Count differences:** the sidebar's count for a watched folder leaves out the files an import still has to work
  through, while Settings' row counts them.
- **Routes (I5) still open:** `libraryCalls` in `pages/library/libraryModel.ts` asks by the old route param (a name is
  a playlist when the sidebar lists one, else a Library folder, and a path as a folder view). `/library/playlist/:name`
  and `libraryTarget` are not built yet.
- **Paths worded by the UI:** `shortPath` (`musicFolder.ts`) and `filePlace` (`todoModel.ts`) stay: they word
  arbitrary paths (the music folder, a To-do file, Settings' rows, fitted to a width) that carry no engine `place`.
  Only `track()`'s and the rows' `place` and the sidebar's `watched[].place` come from the engine.
- **Dev fake:** `ctx.s.briefBusy = true` (`window.__fake.ctx.s`) makes both brief saves answer `busy`; `s.unread` and
  `s.emptyRead` make a playlist never read / read and empty. `library:crates_busy` is `library:crates` with
  `briefBusy` on; `library:first_look` is its folders and crates with no Favourites.
- **NOT FOUND tooltip (UI + engine date):** it can't give To-do's next-try line ("next try in 5 days", I7): `LibraryRow` carries no
  date, only `track()` does. It reads "Nothing usable found yet: To-do has other ways to get it" until the engine adds the
  date to the row (additive field) and the tooltip shows it.
- **Show in Finder for watched folders (UI):** `api.reveal` now opens an import folder and its crates (absolute path inside a
  watched folder). The sidebar's and Library's menus still offer it only where it used to work; offer it for these too.
- **Settings' crate switches (UI):** `#/settings/folders/<path encoded>` (`settingsFolderHref`) picks an import folder in
  Watched folders; Library's "Show some in the sidebar…" opens it. All · None still save one crate after another
  (`saveCratesShown`); switch it to `set_crates_shown(paths, shown)` (one write, one sidebar read). Under a folder with too
  many crates, All needs a search that leaves at most 25 rows.
- **Favourites save and `refreshHub`:** a full `refreshHub` landing during a Favourites save can briefly show the old order.
- **`set_crate_shown` stores any path:** it does not check that the path is a crate.
- **Later cleanup:** `views.library` is about 140 lines; `_playlist_rows` / `_folder_rows` would split it. `track()`
  recomputes `views.sites` over every file on each pick (linear, fast enough today).

## 28. Library stage 5a leftovers (layout)

Audit 2026-11-05: the point "No Playlist column in the track table" is closed (`LibraryTable` has the Playlist column and
Not in a playlist names the Folder). The rest is unchanged: pywebview is still `>=6.2.1,<7`, the selected row is still
grey, the rule check and the other points were not re-run.

Noted while building and reviewing `docs/archive/2026-10-29-library-stage-5-plan.md`, step A (the layout).

- **Rail tooltips:** the shortcut shows as a grey key cap per the mockup, not the plan's I7 text "{Page} (⌘n)". The
  plan's I7 could be updated to match.
- **"Hide/Show Sidebar" can't go in the View menu:** pywebview 6.2.1 adds custom menus only as new top-level menus, and
  its items take no shortcut, so ⌃⌘S is key-only.
- **The rail's "99+" To-do pill** covers most of the To-do icon (the 30 px rail column has no room); the tooltip gives
  the exact count.
- **ARIA nit:** while filtering, the browser column's section heads sit inside the listbox (needed so they stick),
  which ARIA doesn't strictly allow.
- **The selected table row stays grey,** like To-do's, instead of the mockup's orange wash. Changing it would be one
  change for both pages.
- **The base page's rule check has old failures,** the same before and after this step:
  `npm run rules -- --page base --force` reports 1,808 FAIL lines in 40 shots, base-gallery 99, mostly the gallery's
  long section descriptions. Worth a cleanup group.
- **The dev-only FAKE pill** now sits at the page's top-left corner and touches the page title's top in fake mode.
- **"Not lossless yet" in the summary strip** has a small pill split into the good-lossy, weak and fake colours instead
  of the mockup's red dot, because the row counts all three. Settled.
- **The Playlists A–Z toggle turns orange when pressed** (the plan's `Button icon xs pressed`), where the mockup has it
  grey. Settled.
- **The browser's drag edge turns a lighter grey after 300 ms of hover,** so orange still means only "dragging". Settled.

## 27. Library stage 4 leftovers (import)

Audit 2026-11-05 (updated by leftovers round C2): the Format-row point is closed (sources round). Engine done in C2:
every To-do item carries `file_state` (as a Library row's: `here` / `offline` / `folder_missing` / `no_file`; a same-song
item is about the user's own file) and the duplicate item's `in_playlists` is now explicitly "any side of the group is in
a playlist" (it was already that value, from the side that names the group). Left for the UI round: the `AwayTag` on
To-do rows, the "waits for your answer" note in `UpToDate.svelte`; the other two points are unchanged.

Noted while building and reviewing `docs/archive/2026-10-25-library-stage-4-plan.md`.

- **To-do's list rows don't say a file is away (UI):** the items now carry `file_state`; the row still shows no `AwayTag`. Its
  rows have no quality column, so the tag's place needs a look of its own (the badge slot, or the detail line).
- **Sync's Up-to-date view shows no hint when every remaining song waits for an answer;** only the To-do count points
  at them. Show the "{n} songs wait for your answer" note there too.
- **The removal count (W4) misses rare cases:** a playlist track matched only at plan time (no stored song) isn't
  counted, and a Yes answer for a track that left every playlist still is. A song re-keyed after the removal keeps
  its file's tag name until the planner updates stored names.
- **Files judged before the floor rule (fix round E1) keep their old verdict.** Nothing judges a library file again
  when the detector improves; in the user's library three House_Banger files would now be fake. Two more just miss
  the rule (a 28–29.7 dB fall into a flat floor, the rule needs 30); lowering it would take in looser shapes.

## 25. Library stage 1 leftovers (engine on library.db) — for later stages

Audit 2026-11-05 (updated by leftovers round C2): the Ogg page-header reads, the moved/adopted/conflicts labels, the
migration's recovered steps in the run report, and the RF64 / streamed WAV / Ogg-FLAC keys are done (a tag edit no longer
changes their key; a file already keyed whole keeps that key until its bytes change). Still open: `execute.py`, `ops.py`,
`upgrades.py` and `tidy.py` call `run_op` on the entry view (its own stage), and the unreadable replaced file (a design
choice, below).

Noted while moving the engine onto `library.db` (`docs/archive/2026-10-23-library-stage-1-plan.md`, group 3).

- **The sync's file steps still work on the entry view of the database** (the stage 1 seam: `db.snapshot` /
  `db.save`): the `run_op` callers `execute.py`, `ops.py` and `upgrades.py`, and the folder moves of `tidy.py`. The
  import, the folders and the file journal (`move_files`) write songs and files explicitly. Move the rest the same
  way when a stage touches them.
- **A replaced file the quality check can never read** is judged again, with a warning, on every sync. That is on purpose
  (a check that fails once, say with ffmpeg missing, must be tried again), so a fix needs a record of the failed key (a
  schema change) or moving the retry to the import's sound check (`import_state` `unreadable`); not decided.


## 24. Identify files by their sound (AcoustID) — agreed design, a stage after stage 6

Audit 2026-11-05: parked, nothing of it is built (no AcoustID, `fpcalc` or Chromaprint code or licence file, no Settings
switch). The "check first" of layer 1 is answered: `identify.compare` already uses the lengths (`SAME_LENGTH_MS`,
`CERTAIN_MS`, `PLAUSIBLE_MS`), so only layers 2 and 3 are new.

Follow-up of `docs/2026-10-23-library-and-sources-design.md` (§1 out of scope, §10.3). Today files are identified
only from tags and file names. Design agreed with the user on 2026-10-29 (limits checked on acoustid.org/webservice,
acoustid.biz and the MusicBrainz rate-limiting page that day):

- **Off by default.** One switch in Settings, with one plain sentence saying what it sends.
- **Layer 1, local, nothing sent.** Tags and file name as today. New: compare the file's length with the matched
  playlist track's length (Spotify and Qobuz give it). A large difference means wrong tags or another version (radio
  edit vs extended mix). Check first whether `identify.py` already uses the length.
- **Layer 2: a fingerprint is sent only for** (a) files nothing identifies, (b) unsure matches that would become a
  question, (c) confident matches whose length doesn't fit. A file whose tags match and whose length agrees sends
  nothing.
- **Layer 3: the answer is evidence, never a re-tag.** If the sound agrees with a playlist track, link it without
  asking. If it disagrees with the tags, the question shows both ("Tags say X · the sound says Y"). If AcoustID doesn't
  know the track, behave as today. **An answer the user already gave always wins.** Never rename or re-tag a file.
- **What is sent:** the Chromaprint fingerprint, the duration and the app key. No names, paths, tags or email.
  The MusicBrainz User-Agent gives the GitHub repo URL as its contact, never an email.
- **Limits.** AcoustID is free for non-commercial and open-source apps, at most 3 requests per second, one request
  per file (no batch lookup), and needs a registered app key. It asks to be told in advance of significant traffic.
  MusicBrainz allows 1 request per second per IP and answers 503 above it. Its User-Agent must name the app and a
  contact. Pace AcoustID at 1 per second at most. Call MusicBrainz (for the ISRC) only when a file needs it for an
  upgrade search. Store every answer keyed by the file's content key, so a file is never sent twice. Expected volume:
  about 10 % of a library, once, then only new files.
- **Service unavailable** (offline, down, slow, 503 or 429): nothing waits for it. Import and sync finish as today.
  Local checks still run. Files wait in a queue that is tried again on the next sync, with a growing pause between
  tries and no fast retries. Late answers settle their questions automatically. No banners: one quiet line under the
  switch ("AcoustID unreachable (last tried 14:02) · 12 files waiting"). A missing or failing `fpcalc` is handled the
  same way.
- **Needs:** a registered AcoustID app key; `fpcalc` bundled, with its licence in `packaging/licenses/`.
- **Before the release:** write to AcoustID. Ask whether the 3 per second is counted per app key (shared by every
  user) or per IP, and give the expected traffic. This is outward-facing: only with the user's go and wording.
- **Later wish, nothing sent:** compare fingerprints locally to find the same song in different formats (MP3 vs FLAC).
  Today only same-file duplicates are found.
