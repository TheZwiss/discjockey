# Open issues

Bugs, wishes and open checks that are noted but not done yet. The newest go at the top. Remove an entry once its fix is
committed. Moved here from `docs/archive/pre-public/2026-10-16-hub-plan.md` when that plan was archived (2026-10-20).

## 47. A download whose cover art is not a JPEG gets no cover at all (found in the covers fix, 2026-11-24)

`audio.fetch_cover` returns the picture only when it starts with the JPEG marker; a PNG (or WebP) from a source's
`image_url` is dropped without a word, so `acquire` writes the download with
no cover, and every later step keeps that (Same track and the AIFF swap copy the download's tags). Fix: return any
picture `audio.cdj_cover` can make safe (it already converts PNG and the like through ffmpeg), None only when that
fails; test with a PNG served for the url.

## 46. The Playlists change panel words the rekordbox and undo notes itself (issue 39 phase 3 fix round, 2026-11-22)

`ChangePanel.svelte` (the save question's warning card) joins the window's own constants `R1`, `R2`, `U1` from
`tidyModel.ts`; the Moves panel shows the engine's `TidyPreview.rekordbox` and `undo_note`. Same sentences, two sources
(a window-computed sentence: design §9.1). Fix: `ChangePreviewTidy` (`preview_playlist_change`) carries the two notes from
`views.REKORDBOX_NOTES` / `views.UNDO_NOTE`, the panel shows them, `R1`/`R2`/`U1` go; shape, fake, contract and the
vitest data of `ChangePreviewTidy` change in one commit. Until then `U1` holds the engine's current word.

## 42. The sync's own login-file saves take the support lock inside the library lock (V1.14 review, 2026-11-16)

Lock order is support, library, `rekordbox.lock` (CLAUDE.md). Every settings write follows it now (`_settings_job`,
`_update_settings`, `set_music_folder`; pinned by `test_cli_locks`). Not yet: the saves a sync or download job makes
while it holds the library lock for the whole run: Qobuz's `config.toml` (`qobuz._write_config`, `_save_login`,
`_save_secrets`) and Spotify's token (`sources/spotify._save_token`). They take the support lock inside the library
lock. No deadlock is possible (the support lock is a leaf, waited for 2 s, then `busy`), but the order is the other
way. Fix: take the support lock before the library lock for a run that logs in, or move the saves out of the run.
The in-run saves wait up to 60 s (phase 1 review S-7), so a tools install no longer loses a refreshed token.

## 41. To-do multi-select for the other groups' actions (Hide, Find a version, …) (2026-11-08)

Issue 33's stage B gives To-do a selection model and a selection panel for the Upgrade ready group (Replace, Discard)
and the check group ("Done, checked in rekordbox"). The other groups still act on one track at a time: Hide, Find a
version, Mark as bought and the like. Every action should take one track, a selection or all eligible ones (the rule
for file actions). Reuse the stage B model (`lib/decisions`); each action needs its console command too (issue 39).

## 40. rekordbox follows Discjockey's own moves; what Discjockey does with moves made by hand (user, 2026-11-07)

**Follow Discjockey's own moves** (issue 33's stage E, after its stage B live test). When Discjockey moves a file (a
tidy-up and its undo, a folder rename on disk, a swap out of `not_lossless/`, a duplicate to `Superseded/`, any move
batch), it points rekordbox's track at the new path itself, so the user never needs Relocate for them. The same engine
and safety as issue 33's design (`docs/2026-11-07-rekordbox-repoint-design.md` §5: rekordbox closed, backup per
batch, journal, undo per field, refusals). A move never waits for rekordbox: the repoint of a batch made while
rekordbox runs is queued and done once it is closed, and Relocate still works meanwhile because a move keeps the name.
Needs its own short design round (where the queue shows, what an undo of the move does to the repoint).

**Not for moves the user makes by hand** in Finder: those stay with rekordbox's own (Auto) Relocate. Instead, an
audit of what Discjockey itself does, written down and pinned by tests, then said in plain words in the manual (docs/manual.md): a file
moved or renamed inside one watched folder, between watched folders, to another drive, out of every watched folder
(waits as missing in To-do, never downloaded by itself: issue 43, manual "Missing files"), copied instead of moved (a duplicate), and a whole watched
folder moved or renamed (today it waits as "Folder not found"). Today's behaviour: inside `Library/` and the watched
folders a file is found again by its content key, with no new download or import (manual, `scanner.py`).

## 39. Discjockey fully usable by an AI agent: audit, agent docs, commands (user, 2026-11-07)

The user's wish: any AI agent they point at Discjockey (Claude Code, Codex, …) can run it fully and safely: sync,
upgrades, the To-do answers, Library and folder actions, Settings, and reading every screen's state. The development
rule is in `CLAUDE.md` ("Agent-ready"). Phase 1 of plan v2 (`docs/2026-11-15-agent-cli-plan-v2.md`) built the command
line's frame (`discjockey/cli/`, `discjockey help --json`) and the rekordbox, upgrade, AIFF, batch, check, folder,
settings, library, report, to-do and track commands; the other phases follow. Background: on 2026-10-31 an agent
repointed 38 rekordbox entries for the user with throwaway scripts of its own rather than through Discjockey.
- **Audit:** list every hub bridge method (`hub/api.py`) and screen (`hub/views.py`). For each, say whether an agent
  can reach it today and how (command, flags, output, exit code), and where it can't.
- **Design the agent surface:** console commands that run without prompts, `--json` output, exit codes for ok, busy
  and failed, and progress an agent can follow. Weigh whether an MCP server (tool calls) should be added on top, and
  how an agent finds the user's music folder and support folder.
- **Agent docs:** what Discjockey is, the safety rules an agent must keep (the invariants: lock, Qobuz protection,
  never delete, never move outside a batch the user started, dry run first), and every command with an example. Put
  them where agents look (e.g. `AGENTS.md` at the repo root, plus a README section for users who point their agent
  at the app). Hand-written `AGENTS.md` for v1.4.0 done 2026-11-24 (Commands for scripts and agents moved out of
  CONTRIBUTING.md into it); V8.1 generates the rest (`help agents`, `help concepts`, `help --markdown`, T11) and keeps
  AGENTS.md current.
- **Pin it:** a test that fails when a bridge method has no command or no agent-docs entry.
- The 33 work (rekordbox repoint) has its commands under the rule (phase 1): `rekordbox status | preview | backups |
  restore`, `upgrade list | apply | discard`, `track undo`, `batch list | show | resume | undo`, `check list | done`,
  `aiff convert | rename`, `settings show | set auto-upgrade`, `sync run --auto-upgrade-only`. The sync's own `--json`
  (`discjockey --yes --json`) stays the old command line's until V4.1.

## 33. Lossless AIFF for imported files, with rekordbox pointed at them (user, 2026-10-31) — stage E open (issue 40)

Design: `docs/2026-11-07-rekordbox-repoint-design.md` (the user's answers and wishes A–C built in; stage E is issue 40).

**Stage A** is merged into main (43e6797: the read side, New track lined up, `rekordbox status` / `preview`); its live
check is pending (`docs/2026-11-07-rekordbox-stage-a-plan.md` §8). **Stage B** is merged into main
(0c2261b, verify 1081 shots green): the rekordbox write side, backups and restore,
Same track for any format as one AIFF batch with undo, Upgrade all, To-do multi-select, the batch check card and the
console commands (`upgrade …`, `batch …`, `rekordbox checked | backups | restore`); its live test is plan stage B §9.

**Stage C** is merged into main (de95052, verify 1129 shots green): Auto-upgrade on sync (Setup and Settings switch,
on by default; the sync's last phase as one AIFF batch with its backup and undo; `auto_refused` / `auto_waits`; the
end screen's Upgraded / Still waiting / Couldn't go in; `settings auto-upgrade`, the run's `--json` block); its live
test is plan stage C §9, before any release.

**Stage D** is merged into main (verify 1216 shots green): Convert to AIFF, Give it its clean name, To-do's **Won't play well on CDJs** group
with Convert all, and **Make all lossless files AIFF** (Library's **Make AIFF…**, wish C), each as one AIFF batch with
its backup, undo and check card; console `convert` (`--all <view>`, `--all cdj`) and `rename` (CONTRIBUTING); rehearsal on a copy
216 checks passed. Its live test is plan stage D §9, before any release.

**Still open:** stage E is issue 40. The live tests of stages A–D (each plan's last section) wait for the user.

**Facts the later stages build on:** cues and beatgrid live at rekordbox's track, not in the file; Relocate matches on
file name only; rekordbox keeps following files it finds anywhere in a watched folder; every write to the user's
rekordbox library happens with rekordbox closed, after a backup, with an undo.

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
