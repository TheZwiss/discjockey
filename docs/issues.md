# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 29. Library stage 5b leftovers (folders)

Noted while building and reviewing `docs/2026-10-29-library-stage-5-plan.md`, step B (folders), task group B2.

- **Same label for two crates:** two crates under different wrapper folders can get the same label ("Hard › 2019"),
  so the UI tells them apart only by the tooltip (the full path). This is the plan's D8 rule.
- **Count differences:** the sidebar's count for a watched folder leaves out the files an import still has to work
  through, while Settings' row counts them.
- **For B4 (the UI):** the events the page re-reads the sidebar on are `JobFinished` with `kind` `refresh`, `sync` or
  `import`, and `DrivesChanged`; no event was added. The UI's `shortPath` / `filePlace` duplicate `views.place`, so B4
  drops the UI copy. The contract must record `set_favourites` and `set_crate_shown` as the exception to "write
  methods return a `job_id`": they are brief saves that answer `{favourites}` / `{path, shown}` or `busy`.
- **From B4 (for B5–B7):** the contract, types, fake and store match the engine; the UI still draws today's screens.
  Stand-ins to remove: `libraryCalls` / `asToday` in `pages/library/libraryModel.ts` (the Library page asks by the old
  route param; for a playlist it asks for the whole view, then merges `also` (the leftover files, still dimmed) into
  the rows, summary, chips and subtitle, leaves out the rows without a file, and applies search, filter and sort
  itself, so a never-read playlist still lists its folder and no leftover vanishes; B6 draws the waiting rows and the
  `also` section from the engine's counts and removes `asToday`). `shortPath` (`musicFolder.ts`) and `filePlace`
  (`todoModel.ts`) stay: they word arbitrary paths (the music folder, a To-do file, Settings' rows, fitted to a width)
  that carry no engine `place`; only `track()`'s and the rows' `place` (and the sidebar's `watched[].place`) come from
  the engine. The store has `saveFavourites(keys)` / `saveCrateShown(path, shown)`: they read the sidebar again after
  every answer, `busy` too, and hand the answer back; the toast and the optimistic list are B5's. In the fake, `ctx.s.briefBusy = true`
  (`window.__fake.ctx.s`) makes both brief saves answer `busy`; `s.unread` / `s.emptyRead` make a playlist never read /
  read and empty. `library:crates_busy` is `library:crates` with `briefBusy` already on (B5 shoots the busy state with it). `library:first_look` is `library:crates`' folders and crates with no Favourites (the normal state has none
  either, but also no crates). `empty: 'gone'` shows the generic line in `copy.ts` EMPTY until B6 words it by `view`.
- **For B6 (from the B3 review):** an empty folder and a read-but-empty playlist both come with `empty` `no_match`
  even without search text; B6 picks I7's words ("No music in this folder." / "This playlist is empty.") from `view`,
  `folder_kind`, `read_at` and the empty query, and pins it. A playlist's subtitle and `summary.tracks` count rows
  with a file (9) while the table shows the waiting ones too (12) and the sidebar says "12 songs": B6 words the
  waiting rows so the numbers don't seem to disagree (e.g. "3 waiting").
- **From B5 (the browser column):** *Show in Finder* is offered only where `api.reveal` can open the folder (a
  playlist's folder, a Library folder): it refuses any path outside the music folder, so an import folder and its
  crates have no Show in Finder until the engine gets a reveal for watched folders (no Python change in B5). A
  favourite can be reordered only by drag (the menu adds at the end and removes); a keyboard way (⌥↑ / ⌥↓ on a
  favourite) would make it reachable without a pointer. The UI saves the Favourites it is shown, so a stored key whose
  playlist or folder is gone right now (left out of `sidebar()`) is dropped by the next save from the UI. The browser
  links an import folder and a crate by its path (`#/library/folder/<path encoded>`; `libraryCalls` asks a path as a
  folder view); the rest of I5's routes (`/library/playlist/:name`, `libraryTarget`) are still open. Folder rows count
  "tracks" (the word of the page they open), playlists "songs".
- **Later cleanup:** `views.library` is about 140 lines; `_playlist_rows` / `_folder_rows` would split it. `track()`
  recomputes `views.sites` over every file on each pick (linear, fast enough today).

## 28. Library stage 5a leftovers (layout)

Noted while building and reviewing `docs/2026-10-29-library-stage-5-plan.md`, step A (the layout).

- **Rail tooltips:** the shortcut shows as a grey key cap per the mockup, not the plan's I7 text "{Page} (⌘n)". The
  plan's I7 could be updated to match.
- **"Hide/Show Sidebar" can't go in the View menu:** pywebview 6.2.1 adds custom menus only as new top-level menus, and
  its items take no shortcut, so ⌃⌘S is key-only.
- **The rail's "99+" To-do pill** covers most of the To-do icon (the 30 px rail column has no room); the tooltip gives
  the exact count.
- **ARIA nit:** while filtering, the browser column's section heads sit inside the listbox (needed so they stick),
  which ARIA doesn't strictly allow.
- **No Playlist column in the track table** until step B, because rows don't carry their playlists yet. Your own files
  in "Not in a playlist" show "–" under Folder until step B.
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

Noted while building and reviewing `docs/2026-10-25-library-stage-4-plan.md`.

- **To-do's list rows don't say a file is away** (fix K did the Library's): an Upgrade ready or Weak item whose file
  is on an ejected drive looks like any other row; only its panel says "Offline: connect the drive". `views.todo`
  could send each item's `file_state` as `library()` does (per folder) and the row show the `AwayTag`. Its rows have
  no quality column, so the tag's place needs a look of its own (the badge slot, or the detail line).
- **Sync's Up-to-date view shows no hint when every remaining song waits for an answer;** only the To-do count points
  at them. Show the "{n} songs wait for your answer" note there too.
- **A downloaded file's Format row names the download, not the file.** `views.format_line` prints `source_format`, the
  codec of what was downloaded (`acquire.make_ready` probes the file before it converts to AIFF), so every Qobuz file
  reads "Format FLAC" and a YouTube one "Opus · 135 kbps" while the file on disk is a 16-bit `.aiff`, and the cutoff
  sentence beside it says "a lossy file inside the AIFF". The fake data matches the real wording (it sends "FLAC" for
  a Qobuz file), so it is not wrong; the engine is. Decide: print the file's own format ("AIFF", `source_format`
  stays for the quality line), or label the row "Downloaded as"; then change `format_line`, its tests, the contract
  text and the fake in one commit.
- **The library view's `in_playlists` for a duplicate group comes from its first file** (`hub/views.py`). The UI no
  longer depends on it, but it is misleading; derive it from the group or drop it.
- **The removal count (W4) misses rare cases:** a playlist track matched only at plan time (no stored song) isn't
  counted, and a Yes answer for a track that left every playlist still is. A song re-keyed after the removal keeps
  its file's tag name until the planner updates stored names.
- **Files judged before the floor rule (fix round E1) keep their old verdict.** Nothing judges a library file again
  when the detector improves; in the user's library three House_Banger files would now be fake. Two more just miss
  the rule (a 28–29.7 dB fall into a flat floor, the rule needs 30); lowering it would take in looser shapes.

## 26. Library stage 3 leftovers (Qobuz playlists) — for stages 5 and 6

Noted while building and reviewing `docs/2026-10-24-library-stage-3-plan.md`.

- **SoundCloud and YouTube Music track links can't be derived from an id:** `models.track_link` returns None for
  them. When stage 6 adds those sources and a view needs the link, store it with the track.
- **A file downloaded by its exact Qobuz id gets no record-label tag.** `make_ready` writes `cand.label`, and the
  exact candidate is built from the playlist track, which has no label (`SourceTrack` has none). Fix: carry the label
  from the Qobuz playlist read into the track, or fetch it.
- **An upgrade check with Qobuz recently searched doesn't try a new Qobuz id.** With `searched_since_check` set it
  passes `qobuz=False`, so a Qobuz id that newly appeared in a playlist waits for the next weekly check. Deliberate
  for now (it keeps the weekly wait); revisit if users expect an immediate upgrade.

## 25. Library stage 1 leftovers (engine on library.db) — for later stages

Noted while moving the engine onto `library.db` (`docs/2026-10-23-library-stage-1-plan.md`, group 3).

- **The sync's file steps still work on the entry view of the database** (the stage 1 seam: `db.snapshot` /
  `db.save`): the `run_op` callers `execute.py`, `ops.py` and `upgrades.py`, and the folder moves of `tidy.py`. The
  import, the folders and the file journal (`move_files`) write songs and files explicitly. Move the rest the same
  way when a stage touches them.
- **Content keys of long Ogg/Opus files** read every Ogg page header, one small read per page; fine for DJ tracks,
  slow for hour-long mixes.
- **RF64 WAV, streamed WAV and Ogg-FLAC** get the whole-file key, so a tag edit changes it and a scan reports such a
  file as changed (judged again) instead of retagged.
- **Interrupted steps finished during the migration** are shown as messages but don't reach that run's report
  (`library.open_state` recovers them before the run log exists).
- **Report and console still label the never-used moved/adopted/conflicts sections;** drop them once old run reports
  no longer need to render.
- **A replaced file the quality check can never read** is judged again, with a warning, on every sync.

## 24. Identify files by their sound (AcoustID) — agreed design, a stage after stage 6

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
