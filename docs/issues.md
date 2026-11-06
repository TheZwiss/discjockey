# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 37. Sync: folders switch in and out of the sync like playlists (user, 2026-11-06)

On Sync the browser column gives only playlists a switch; a Folders row (a watched folder such as "Techno", or a
Library folder no playlist uses) has none, and a click on it opens Library. Its lossy files still get the weekly
upgrade check (planner rule 4), so the user can't leave a folder out of the sync. Wanted (user):
- Every playlist AND folder in the Sync column has a switch; no row there sends the user to Library.
- Switched off means the collection is completely left out of the sync: nothing at all is done with its files (no
  download, no check, no move, no replacement), now and for anything the sync does with files later.
- A song belongs to the sync while ANY playlist or folder it is in is switched on; it is left out only when every
  collection it is in is off (a user who turns a playlist on must never find one of its tracks missing because
  another collection is off).

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
