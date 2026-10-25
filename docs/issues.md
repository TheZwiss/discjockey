# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 26. Library stage 3 leftovers (Qobuz playlists) — for stages 5 and 6

Noted while building and reviewing `docs/2026-10-24-library-stage-3-plan.md`.

- **The read-status wire names still say Spotify** (`spotify` field, `SpotifyStatus` type and component,
  `spotify_status` in `hub/views.py`), though the words are service-neutral since stage 3 (plan D2). Rename them when
  stage 5 rebuilds the shell-wide status slot with the sidebar, not before.
- **SoundCloud and YouTube Music track links can't be derived from an id:** `models.track_link` returns None for
  them. When stage 6 adds those sources and a view needs the link, store it with the track.
- **A file downloaded by its exact Qobuz id gets no record-label tag.** `make_ready` writes `cand.label`, and the
  exact candidate is built from the playlist track, which has no label (`SourceTrack` has none). Fix: carry the label
  from the Qobuz playlist read into the track, or fetch it.
- **An upgrade check with Qobuz recently searched doesn't try a new Qobuz id.** With `searched_since_check` set it
  passes `qobuz=False`, so a Qobuz id that newly appeared in a playlist waits for the next weekly check. Deliberate
  for now (it keeps the weekly wait); revisit if users expect an immediate upgrade.

## 25. Library stage 1 leftovers (engine on library.db) — for stages 2–4

Noted while moving the engine onto `library.db` (`docs/2026-10-23-library-stage-1-plan.md`, group 3).

- **The engine still works on the entry view of the database** (the stage 1 seam: `db.snapshot` / `db.save`). Move
  callers to explicit song/file writes as stages 3–4 touch them.
- **Import folders on another drive:** `run_op` renames across drives aren't atomic. Stage 4 must stage a file in the
  target drive before renaming it into place.
- **Content keys of long Ogg/Opus files** read every Ogg page header, one small read per page; fine for DJ tracks,
  slow for hour-long mixes.
- **RF64 WAV, streamed WAV and Ogg-FLAC** get the whole-file key, so a tag edit changes it and a scan reports such a
  file as changed (judged again) instead of retagged.
- **Two new files with the same unknown key on a first scan** are both "new", neither is reported as a copy. Stage 4's
  import should treat them as duplicates of each other.
- **A file moved inside an inner watched folder** is recorded under the outer folder's id (the scanner walks the outer
  one). An inner folder that goes offline still marks those rows offline (`db.apply_scan` matches them by path), but
  views grouping by watched folder will see them under the outer one.
- **Interrupted steps finished during the migration** are shown as messages but don't reach that run's report
  (`library.open_state` recovers them before the run log exists).
- **Report and console still label the never-used moved/adopted/conflicts sections;** drop them once old run reports
  no longer need to render.
- **A replaced file the quality check can never read** is judged again, with a warning, on every sync.
- **Tidy-up covers only files in `Library/`;** stage 4 extends `tidy_rows` and the runner to import folders, staging
  across drives.

## 24. Identify imported files by their sound (AcoustID) — wish, after stage 4

Follow-up of `docs/2026-10-23-library-and-sources-design.md` (§1 out of scope, §10.3). Files with missing or wrong tags
are identified today only from tags and file names. An opt-in setting would send Chromaprint fingerprints to AcoustID
(free service; needs an application key and the `fpcalc` program bundled, with its licence in `packaging/licenses/`)
and use the returned recording's ISRC and names. Ask the user before building: it sends data about their files to an
outside service.
