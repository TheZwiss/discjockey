# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 39. Discjockey fully usable by an AI agent: audit, agent docs, commands (user, 2026-11-07)

The user's wish: any AI agent they point at Discjockey (Claude Code, Codex, …) can run it fully and safely: sync,
upgrades, the To-do answers, Library and folder actions, Settings, and reading every screen's state. The development
rule is in `CLAUDE.md` ("Agent-ready"). Today the console covers little more than a sync run (`cli.py`: `--yes`,
`--dry-run`, `--limit`, …). Background: on 2026-10-31 an agent repointed 38 rekordbox entries for the user with
throwaway scripts of its own rather than through Discjockey.
- **Audit:** list every hub bridge method (`hub/api.py`) and screen (`hub/views.py`). For each, say whether an agent
  can reach it today and how (command, flags, output, exit code), and where it can't.
- **Design the agent surface:** console commands that run without prompts, `--json` output, exit codes for ok, busy
  and failed, and progress an agent can follow. Weigh whether an MCP server (tool calls) should be added on top, and
  how an agent finds the user's music folder and support folder.
- **Agent docs:** what Discjockey is, the safety rules an agent must keep (the invariants: lock, Qobuz protection,
  never delete, never move outside a batch the user started, dry run first), and every command with an example. Put
  them where agents look (e.g. `AGENTS.md` at the repo root, plus a README section for users who point their agent
  at the app).
- **Pin it:** a test that fails when a bridge method has no command or no agent-docs entry.
- The 33 work (rekordbox repoint) gets its command under the rule from the start.

## 38. Playlists: switching a playlist off says its songs get removed; switching it back on crashes the page (user, 2026-11-07, live in 1.2.1)

Found live by the user on the Playlists page:
- **Wrong words.** When a playlist is switched off, the right panel (`ChangePanel`, the `switch_off` view) reads as
  if the playlist's songs get removed. They most likely don't: nothing is ever deleted, and the row itself says
  "switched off · files stay". Check what the panel says and what really happens to the files and the songs' records
  when the switch is saved. Then make the words say exactly that, in the same terms as Sync's switch (issue 37: off
  means the playlist is left out of the sync, its files stay where they are).
- **Crash.** Switching the same playlist back on shows the page's error screen: "Something went wrong on this
  screen." with a Reload button. Find the root cause (engine or UI), fix it there, and add a test that pins it.
  Check the other switch paths on the page too: on → off → on before saving, after saving, and with several rows.

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
