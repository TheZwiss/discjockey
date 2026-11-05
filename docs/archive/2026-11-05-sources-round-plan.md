# Sources round "where music comes from" — plan

Design: `docs/hub-mockups/sources-round.html` (13 states, opens at `#<state>@<width>`) and its notes
`docs/hub-mockups/sources-round-notes.md` (problems 1–10 and the **Drift list**). The user approved the ten problems
and answered: rows show the logo only; the Liked music warning words and the button stay; the dashed segment stays,
with the text count. Orchestration rules: `docs/2026-10-23-library-and-sources-orchestration.md` §4–§7. Branch:
`feat/sources-round`, off `main` after `design/sources-round` is merged; group worktrees
`.claude/worktrees/sr-<group>` on `feat/sources-round-<group>`.

**Goal:** the Add field and Setup show which services and where a link is; YouTube Music's Liked music becomes a
choice in Settings; the details say what the file is (FORMAT) and what it was made from and how it was found (SOURCE),
with "Open in …" on the head card; counts move where they never get cut (Library strip, Playlists list head).

**The mockup is a sketch drawn from memory.** It is the reference only for the elements in the scope table. For
everything else on a page, the real app is the reference, including every "mockup error" row of the Drift list.

## Global constraints

- **Engine shape changes carry their contract** in the same commit: `docs/hub-bridge-contract.md`,
  `hub-ui/src/lib/bridge/types.ts` + `contract.ts`, and the fake backend (CLAUDE.md "Docs and plans").
- **`planner.py` and `hub/views.py` stay pure; only `db.py` writes SQL.** One schema step (v4 → v5).
- **Reads are not downloads** (no Pacer, Budget or usage row) and **reads are anonymous**, with one new exception:
  the `LM` (Liked music) read with the user's YouTube login, only while `read_liked_music` is on (D5). Its cookies
  live on the one `YoutubeDL` the read creates and closes; nothing reaches the download path.
- **The download protection is untouched** (pacing, limits, pauses, I6 waits). The LM read respects them: it never
  runs while the YouTube account is in a protection pause (D6).
- **New patterns go into blocks** (block + gallery + `docs/hub-design-language.md`), never built in a page.
- **Tests are offline**; made-up ids and names only. **Public repo:** `scripts/check_public.sh --require-denylist`
  before every commit; never `--no-verify`.
- **No `npm run verify`** inside a group; it runs once before the merge (CLAUDE.md "Critical rules").

## Decided here (with reasons)

**D1. FORMAT is the file; SOURCE is the download.** `format_line` becomes the file's own format. Every file
Discjockey downloads is converted by `audio.convert_to_aiff` (`-c:a pcm_s16be`), so its FORMAT is `AIFF · 16-bit`
without a new column. A file the user owns (import) or bought: the container from its file extension (`AIFF`,
`WAV`, `FLAC`, `MP3`, `AAC` for `.m4a` with an AAC codec, `ALAC` for `.m4a` with ALAC) plus the bit depth when its
stored `source_format` is a PCM codec name (`pcm_s24le` → `24-bit`); otherwise the container alone (`FLAC`).
*Reason:* the notes' "check first" (does the row know the bit depth) is answered by the conversion and the PCM codec
names; no schema change is needed for it. *Check first:* what `source_format` holds for an imported FLAC and WAV
(`importer.py`, `db.py` line ~1201) and for a bought file (`db.set_quality`).

**D2. `source_format_line` is today's `format_line`, renamed.** The function stays exactly as it is
(`"FLAC"`, `"Opus · 135 kbps"`, `"uncompressed PCM"`); it moves to the new field. *Reason:* the upgrade card's Now
keeps its values (notes §6), and SOURCE gets the same words, so one function serves both and no value changes.

**D3. `source_how` is stored with the file.** A new nullable `files.source_how TEXT` (schema v5; NULL for every
existing row and for own and bought files). Values: the `SourceChosen.query_kind` union
`exact | isrc | name | fallback | chosen | upload`. It flows the way `source_format` does: `acquire.Ready` →
`models.Placed` → `planner._placed_fields` / `MERGED_FIELDS` / `ENTRY_KEYS` → `db.FILE_FIELDS`; `ops.py`'s "Use this"
path writes `chosen`; `execute.py`'s parked upgrade dict carries `how` and a swap (`upgrades.py`, `UNDO_FIELDS`)
moves it into the entry with the other source fields; `db.set_quality` (bought) and the import set it NULL.
*Reason:* today `how` lives only in the live event (`acquire.py:577`), so the details can't say it after the run.

**D4. Source's link is dropped when it is the song's own page.** `track_detail.source_url` is null when it equals
`track_link.url` (a YouTube Music playlist's own upload). SoundCloud ids give no `source_url` already. *Reason:*
notes §5 "no double link".

**D5. Liked music is a setting.** `Settings.read_liked_music: bool = False` in `settings.json`. While off,
`youtube_music` answers an `LM` id with `SourceError(<the setting_off message, Binding words>, "setting_off", "youtube_music")`; `LL` and `WL` keep
W17, mixes W18. While on, `LM` is read through yt-dlp's tab extractor with the YouTube account's login
(`accounts.ytdlp_login("youtube", browser, profile)` from `settings.accounts["youtube"]`) on the read's own
`YoutubeDL`. With no YouTube account set up, the setting can't be turned on (`set_read_liked_music` refuses with
kind `not_set_up`) and a listed LM line reads as off. *Reason:* the user's choice; the login is the only way to
read it, and the warning words say the risk.

**D6. The LM read obeys the YouTube account's waits.** While the account is paused (bot check, rate limit, the
waits of spec sources-and-limits §4 / I6), the LM line is not read this time: the planner gets no fresh read for it
and treats it like a line whose read failed (its files stay; no drop). A bot check met by the LM read itself records
the same account signal a download would (*check first:* where `pacing`/`accounts` record `bot_check` for
`youtube`, and reuse that call, never a copy). *Reason:* the rules decide it (download hierarchy, I6 waits): a read
must not set off or prolong the pause that protects the downloads.

**D7. An LM line while the setting is off is a switched-off line, not a problem.** `sources.read` leaves it out
before any request (as `#off#` lines are left out); the run never raises for it, no problem card, its files stay.
*Check first:* how `run.prepare` and the planner treat lines that are not read (off lines) so its tracks are not
dropped; reuse that path. The Playlists row says `Liked music is off in Settings`.

**D8. "Add Liked music to Playlists" is a bridge write.** `add_liked_music()` (write job) appends
`Liked_music = https://music.youtube.com/playlist?list=LM` to `playlists.txt` through the same writer
`save_playlists` uses (`playlists_file`), at the end of the list; answers `{folder}`; refuses with kind
`setting_off` when the setting is off and `exists` when an LM line is listed (on or off). A Playlists page with an
unsaved draft meets it through its existing "changed elsewhere" flow. *Reason:* YouTube Music doesn't share an LM
link, so the user must never have to find one.

**D9. Pasting LM while off answers a "needs a setting" form.** `add_playlist(url)` for an `LM` link while off:
`{ok: false, kind: "setting_off", setting: "read_liked_music", service: "youtube_music", message}`. `AddRow` maps
`kind: "setting_off"` to its new form with the fixed name `Liked music` and owner `yours` (no read happens, so there
are no other facts). While on: the normal found card (the read gives name, owner, count).

**D10. Library counts.** The header loses its count; the strip's caption reads
`{checked} of {files} checked · {with_file} of {listed} downloaded` from the existing `summary` and `songs`
(`views.py` ~line 846: `songs = {listed, with_file}`); no engine change. The quality bar gets a dashed end segment
of `listed − with_file`. Views that are not a read playlist (`songs` null) keep today's caption and no dashed end.
The `%` stays "of checked tracks" (user answer).

**D11. The "how" words** (binding, one map in `hub-ui/src/lib/copy.ts`, used by the Sync card and the details):
`upload` → `the playlist's own upload` (W20), `exact` → `exact Qobuz track`, `isrc` → `found by ISRC`,
`name` → `found by name`, `fallback` → `found by name` (the fallback search is a name search), `chosen` →
`picked by you` (open question 1). A file without `source_how` shows no second line.

**D12. Hard_Techno's problem line reads whole.** At 1100 the app hides the quality column and the line already
reads whole; at 1280 it fits. The logo-only subline (problem 7) only shortens it. The shots check pins it at 1100
and 1280 (`playlists` state): the full `Follow ≠ own: make your own copy in Spotify.` with no "…".

## Interfaces (fixed here)

### I1. Schema and records (group E1)

- `db.SCHEMA_VERSION = 5`; `SCHEMA_V5_STEP = ("ALTER TABLE files ADD COLUMN source_how TEXT",)` registered in
  `UPGRADES[4]`. `FILE_FIELDS` gains `source_how`; every `source=None` reset (`db.py:335`, `ops.py:226`,
  `planner.py:620`) also clears it.
- `acquire.Ready.how: str`, `models.Placed.how: str | None`; the entry dict key is `source_how`.
- The parked upgrade dict gains `how`; a swap copies it to `source_how`; undo restores the old one (`UNDO_FIELDS`).

### I2. Track detail (group E1)

`track()` / `TrackDetail` (Library and To-do):

| Field | Before | After |
|---|---|---|
| `format_line` | the download's format (`"FLAC"`) | the file's format: `"AIFF · 16-bit"`, `"WAV · 24-bit"`, `"FLAC"`; null without a file |
| `source_format_line` | — | today's `format_line` value (`"FLAC"`, `"Opus · 135 kbps"`); null without a file and for own/bought files |
| `source_how` | — | the stored union value or null |
| `source_url` | as today | null when equal to `track_link.url` (D4) |
| `track_link` | as today | unchanged (already `{url, label}`) |

The upgrade block's `format_line` is unchanged. `UpgradeCards`' Now label reads `track.source_format_line ??
track.quality_label` (moved in E1, so Now never shows the AIFF) with the tooltip `Your AIFF was made from this`
(group U3).

### I3. Liked music bridge (group E2)

- `settings()` view gains `youtube_music: {liked_music: bool, can_turn_on: bool, listed: bool}` (`can_turn_on`:
  the YouTube account is set up; `listed`: an LM line exists, on or off).
- `set_read_liked_music(on: bool)` → write job (through `_update_settings`, like `setup_skip_spotify`); refuses
  `not_set_up` when turning on without a YouTube account. Turning it off never touches `playlists.txt`.
- `add_liked_music()` → write job (D8). `add_playlist` LM answer (D9).
- `playlists()` rows: a row gains `needs_setting: "read_liked_music" | null` (set for a listed LM line while off).
- Error kind `setting_off` joins the kinds in the contract and `types.ts`.

### I4. Blocks (group U1)

- **`LinkGuide`** (new): props `folded?: boolean`, `open?: boolean` (bindable). A `Surface list` with head
  `Where to find a playlist's link` and one row per service in the user's order (YouTube Music, SoundCloud,
  Spotify, Qobuz): `ServiceMark` · name · where to click · example link. Columns by the container's width (container
  query): under 400 px a two-line stack (name over where); from 400 px name + where in two columns; from 560 px the
  example link as a third column. `folded`: only the head row with a chevron and the four logos at its end; a click
  opens it. Example link in the design language's numeric/code style if one exists, else the body font (no new
  face; the mockup's monospace is a sketch).
- **`AddRow`**: the placeholder is `Paste a playlist link here` followed by the four `ServiceMark`s (14 px, 6 px
  apart, each with a Tip of its name); the field's `title`/aria words name the four services; the logos go once the
  field has text. New found-card form `needs-setting`: name, `ServiceMark` + `YouTube Music · yours`, a yellow `!`
  line, a `Hint`, and one primary action (label and target given by the caller).
- **`TrackHead`**: optional `link?: TrackLink` adds a bottom row inside the head card: `ServiceMark` +
  `ExternalLink` "Open in {Service} ↗". Truncation rule at 320 px: the meta line stays on one line and ends in "…"
  (full line in its Tip); the badge's word shows whole or not at all (it wraps onto a hidden line; the badge's Tip
  says it); an `action` (To-do's Hide) sits beside the title only.
- **`KeyValue`**: a value may take a quiet second line (`sub?: string`). *Check first:* whether it already can.
- **`SummaryStrip` / `QualityBar`**: `waiting?: number` adds a dashed end segment (the dashed-cover look: border
  token, no fill) sized by its share of `listed`.

## Scope table (what this round builds)

| # | State(s) | Element | Problem | Group |
|---|---|---|---|---|
| 1 | `playlists`, `empty`, `setup` | AddRow placeholder `Paste a playlist link here` + four logos | 1 | U1 (block), U2 |
| 2 | `setup` | LinkGuide open under the Add card | 2 | U2 |
| 3 | `setup-added` | LinkGuide folded under "Your playlists", opens on click | 2 | U2 |
| 4 | `empty` | Panel: NumberedSteps (3 steps) + LinkGuide two-line form; no Segmented, no StatCard; foot stays grey | 2, 9 | U2 |
| 5 | `empty` | EmptyState body `Paste a link above to add your first one.` | 9 | U2 |
| 6 | `settings` | Group `Spotify` → `Reading playlists` with rows Spotify and YouTube Music | 3 | U2 |
| 7 | `settings` | YouTube Music row subline `public playlists · Liked music off/on` | 3 | U2 |
| 8 | `settings` | YouTube Music panel: card (head + `Public and unlisted playlists need no login.`), switch row `Read my Liked music` / `uses your YouTube login`, NoteCard warn | 3 | U2 |
| 9 | `settings` (not drawn) | Switch disabled without a YouTube login: reason `Sign in to YouTube Premium first` + link to that row | 3 | U2 |
| 10 | `settings-on` | Primary `Add Liked music to Playlists` while on and not listed | 3 | U2 |
| 11 | `settings` | Downloads rows (Qobuz, YouTube Premium, SoundCloud Go+) and the Spotify row get their coloured `ServiceMark` | 3 | U2 |
| 12 | `liked-off` | AddRow needs-setting form: `Liked music`, logo + `YouTube Music · yours`, `!` line, Hint, primary `Turn on in Settings` (opens Settings at the YouTube Music row) | 3 | U1, U2 |
| 13 | `liked-on` | Normal found card with `Discjockey reads it through your YouTube login`, Folder `Liked_music` | 3 | U2 |
| 14 | Playlists (not drawn) | Listed LM row while off: logo + `Liked music is off in Settings`, reads like a switched-off row | 3 | U2 |
| 15 | `sync` | Sync card: source leaves the kicker (`NOW · <FOLDER>`); new line under the title: logo + `{Service} · {how words}` | 4 | U3 |
| 16 | `library`, `library-upload`, `todo` | SOURCE value: link or name + ` · {source_format_line}`; quiet second line with the how words | 4, 6 | U3 |
| 17 | `library`, `library-upload`, `todo` | TrackHead `Open in {Service} ↗` row; also on a waiting song | 5 | U1, U3 |
| 18 | Library rows | Context menu item `Open in {Service}` | 5 | U3 |
| 19 | `library-upload` | SOURCE without a link when it is the song's own page | 5 | E1, U3 |
| 20 | `library`, `todo` | FORMAT = the file (`AIFF · 16-bit`) | 6 | E1, U3 |
| 21 | `todo` | Upgrade card Now/New values unchanged; Now's Tip `Your AIFF was made from this` | 6 | E1, U3 |
| 22 | `setup-added` | Setup rows = Playlists rows without controls: cover, folder, logo `"Name" · owner · N tracks`; no raw link | 7 | U2 |
| 23 | `playlists` | Row subline: the service's name in words leaves; the logo (Tip) says it; a problem line keeps logo + red words | 7 | U2 |
| 24 | `library`, `library-none`, `library-upload` | Header count leaves (breadcrumb stays when it fits); strip caption `… checked · W of L downloaded` | 8 | U3 |
| 25 | same | Quality bar dashed end segment for waiting songs | 8 | U1, U3 |
| 26 | `playlists` | PageHeader without `sub`; list head `Your playlists  N on · N off · N tracks` | 10 | U2 |
| 27 | `playlists` | Reorder hint `top = highest priority`; `drag ⠿ or ⌥↑ ⌥↓` moves into its ⓘ | 10 | U2 |
| 28 | `todo`, `library` | TrackHead truncation rule at 320 px (meta "…", badge word whole or hidden, Hide beside the title) | 5 (TrackHead change) | U1 |

**Must not change** (on every touched page; the real app is the reference):

- **Shell:** the sidebar and its icons (Settings is the **gear**, never a sun), counts (To-do count, Sync's `3/5`
  while syncing), the Download limits dot, the rail, the foot and Now playing.
- **Every list card ends after its last row** (Playlists, Settings, To-do, Sync results, Library table); none
  stretches to the window's foot.
- **Type, greys, badges, row heights and spacing** stay the tokens' (secondary text size and grey, QualityBadge
  letter-spacing and columns, Library's 38 px rows); titles keep the en dash `Artist – Title`.
- **Playlists:** the responsive columns (the quality column hides at 1100), the number/cover/toggle/⋯ columns, the
  panel's Segmented, "Where they land" rows (`1  lands in …`), Tidy up files, Read playlists, Undo/Save.
- **Settings:** the "Where your music comes from" `SourceLadder` exactly as it is: the connecting line, the hollow
  unavailable Premium step with `needs YouTube Premium or SoundCloud Go+` and the dashed `YouTube` / `SoundCloud`
  chips, the badges, the footer note `Songs Qobuz doesn't have come from free YouTube at about 130 kbps.`; the
  Downloads rows' sublines and status marks (dashed mark when not set up); the ListSection head style; the whole
  "This Mac" group (Music folder, Watched folders and every row below); the other panels.
- **Setup:** the column width (860 px at 1280), the step strip and its labels (`Your existing…` stays: not this
  round), the ✓ on the last step once a playlist is added, the foot (`Add a playlist first.` + disabled Finish before
  the first playlist).
- **Library:** the browser column (Favourites drop zone, Playlists head with sort and fold, nested folders with
  chevrons, offline marks, text sizes); the strip's right rows (`Not lossless yet · all in To-do`); the Segmented
  with its Fake segment and every dot; the table (sort arrow, `in <playlist>` hint, LENGTH, UPGRADE column, ⓘ, row
  height); "Also in this folder"; the spectrum with its kHz label; FILE's middle truncation; the header breadcrumb.
- **To-do:** the Segmented (Weak and More), `Show hidden · n`, every section, the `↑` upgrade chip on the head card,
  the upgrade card's spectra and `EDIT` row, the In rekordbox card (right-aligned `RECOMMENDED`, the Superseded/ line
  and the Tip), the panel foot and `You can undo a replace until you press Done`.
- **Sync:** the running page layout: `Sync running`, the `Track n of m` progress card (time left, Qobuz count), the
  five-step bar with its done state, the progress words (`0.2 of 0.4 MB · 50 %`), the Problems / Done / Up next
  sections, the Segmented with its Problems dot, the foot `Stopping is safe at any time` + `Stop safely`, the 860 px
  column.
- **Not this round** (notes "Seen"): Library's `All` count (open question 2), Setup's step label, the Sync results'
  lossy dot.

## Binding words

| Where | Words |
|---|---|
| AddRow placeholder (replaces W21, both forms) | `Paste a playlist link here` (field title/aria: `Paste a link from YouTube Music, SoundCloud, Spotify or Qobuz`) |
| Logo Tips | `YouTube Music`, `SoundCloud`, `Spotify`, `Qobuz` |
| LinkGuide head | `Where to find a playlist's link` |
| LinkGuide rows | YouTube Music `Share › Copy` · `music.youtube.com/playlist?list=…`; SoundCloud `Share › Copy link` · `soundcloud.com/name/sets/…`; Spotify `⋯ › Share › Copy link to playlist` · `open.spotify.com/playlist/…`; Qobuz `Share › Copy link` · `open.qobuz.com/playlist/…` |
| Empty Playlists panel head / steps | `How a playlist comes in`: `Copy its link in the music app` · `Paste it above: it gets a folder` · `Sync downloads its songs as AIFF` |
| Empty Playlists main (replaces W22) | `No playlists yet.` / `Paste a link above to add your first one.` |
| Setup card (W23 stays) | `Add a playlist` · `Discjockey keeps each playlist's tracks in a folder of its own.` |
| Settings group | `Reading playlists` |
| Settings YouTube Music row | `YouTube Music` · `public playlists · Liked music off` / `… on` |
| YouTube Music panel | head `YouTube Music`; `Public and unlisted playlists need no login.`; switch `Read my Liked music` · `uses your YouTube login`; disabled reason `Sign in to YouTube Premium first` |
| Warning (user: stays) | `Every read signs in with your YouTube account, the one your downloads use. Many reads can set off YouTube's bot check, which pauses downloads from YouTube for a while.` |
| Button (user: stays) | `Add Liked music to Playlists` |
| Found card, off | `Liked music` · `YouTube Music · yours` · `Reading your Liked music is off` · Hint `It reads through your YouTube login, so it's a choice in Settings.` · `Turn on in Settings` |
| Found card, on | `Discjockey reads it through your YouTube login`; Folder `Liked_music` |
| Listed LM row while off | `Liked music is off in Settings` |
| `setting_off` message (engine, console) | `Reading your Liked music is off. Turn it on in Settings.` |
| Playlists list head | `{n} on · {n} off · {n} tracks`; hint `top = highest priority`; ⓘ `Drag ⠿ or press ⌥↑ ⌥↓ to change the order.` |
| How words | D11 |
| SOURCE values | `Qobuz ↗ · FLAC`, `YouTube Music ↗ · Opus · 135 kbps`, `SoundCloud · WAV`; own `your own file`; bought `bought` |
| FORMAT values | `AIFF · 16-bit`, `WAV · 24-bit`, `FLAC` (D1) |
| Upgrade Now Tip | `Your AIFF was made from this` |
| Open in | `Open in {Service} ↗` (the existing `track_link.label` + ↗) |
| Library strip caption | `{a} of {b} checked · {c} of {d} downloaded` |

## Task groups

Build order (one agent at a time): **E1 → E2 → U1 → U2 → S2 → U3 → S3 → final review**. Sizes from the record
(Sonnet group 150–310k, Opus UI build 300–360k); these are aimed smaller by keeping each group to one area.

| Group | Model | What | Estimate |
|---|---|---|---|
| E1 | Sonnet | Where a file came from: schema v5, `source_how`, FORMAT/SOURCE lines, contract | 150–200k |
| E2 | Sonnet | Liked music: setting, read with login, bridge, contract, fake | 180–240k |
| U1 | Opus | Blocks: LinkGuide, AddRow, TrackHead, KeyValue, SummaryStrip/QualityBar + gallery + doc | 200–260k |
| U2 | Opus | Pages: Playlists, Setup, Settings | 220–280k |
| S2 | Opus | Shots check of U1's gallery entries + U2's pages | 110–150k |
| U3 | Opus | Pages: Library, To-do, Sync card | 180–240k |
| S3 | Opus | Shots check of U3's pages | 100–140k |
| Review | Opus | Final review of the round | 130–160k |

Every brief follows orchestration §4 (≤ 60 lines, read list, read budget 6, don'ts, checks, 15-line report,
the three scope lists) and has a **hard stop at ~80 tool calls** (commit what is done, report what remains).

### Group E1 — Where a file came from (Sonnet)

**Read list:** D1–D4, D11, I1, I2; `discjockey/db.py` (docstring, `SCHEMA_V4_STEP`, `_upgrade`, `FILE_FIELDS`,
`set_quality`); `grep -n "how" discjockey/acquire.py`; `acquire.Ready`; `models.Placed`; `planner.py` around
`ENTRY_KEYS`, `MERGED_FIELDS`, `_placed_fields`; `execute.py:180–200`; `ops.py:220–335`; `upgrades.py`
`UNDO_FIELDS` and the swap; `hub/views.py:540–720`; contract `grep -n "format_line\|source_full\|track_link"`.

**Files:** `db.py`, `acquire.py`, `models.py`, `planner.py`, `execute.py`, `ops.py`, `upgrades.py`,
`hub/views.py`, `docs/hub-bridge-contract.md`, `hub-ui/src/lib/bridge/types.ts`, `contract.ts`, the fake's track
details (`bridge/fake`), `lib/decisions/UpgradeCards.svelte` (Now label only), tests.

**Tasks:** schema v5 + migration; `how` from `_try` to the entry; `chosen` in `ops.py`; upgrade `how` and swap/undo;
`file_format_line` (D1) and `source_format_line` (D2); `source_how`; D4; contract + types + fake (every fake track
detail gets `source_format_line` and `source_how`; one fake SoundCloud track with `how: "upload"`, one YouTube Music
own upload where `source_url` equals `track_link.url`).

**Behaviours to test:** a v4 `library.db` opens as v5 with `source_how` NULL on every row and nothing else changed;
a Qobuz download stores `exact`/`isrc`/`name`, a SoundCloud own upload `upload`, a fallback `fallback`, "Use this"
`chosen`; bought and imported files NULL; a swap moves the parked `how` and an undo restores the old one; a reset
to missing clears it; `format_line` = `AIFF · 16-bit` for a download, `WAV · 24-bit` for an own `pcm_s24le` WAV,
`FLAC` for an own FLAC; `source_format_line` equals the old `format_line` for the same entry (table test over the
old cases); `source_url` null when equal to `track_link.url`; the upgrade card's Now label in vitest reads
`source_format_line`. Checks: the touched test files, `npx vitest run` on the touched UI tests, `npm run check`,
then `uv run pytest -q | tail -3` once.

### Group E2 — Liked music (Sonnet)

**Read list:** D5–D9, I3; `discjockey/sources/youtube_music.py` (docstring, `PERSONAL_IDS`, `_refusal`, the reader's
`YoutubeDL` options); `sources/__init__.py` (`read`, `expand`); `settings.py` (`Settings`, load/save);
`accounts.py` (`ytdlp_login`, `signal_of`); `grep -n "bot_check" discjockey/pacing.py discjockey/accounts.py`;
`run.py:95–125`; `playlists_file.py` (docstring, `_row`, `_line`, the writer `save_playlists` uses);
`hub/api.py` (`add_playlist`, `setup_skip_spotify`, `_update_settings`, `playlists`, `settings`); contract
`grep -n "playlist_unreadable\|add_playlist\|settings()"`; the fake's `add_playlist` and settings scenarios.

**Files:** `settings.py`, `sources/youtube_music.py`, `sources/__init__.py`, `run.py` (only if D7's check needs
it), `hub/api.py`, `hub/views.py`, contract, `types.ts`, `contract.ts`, `bridge/fake/*`, tests. No UI pages.

**Tasks:** the setting; the split refusal; the logged-in LM read (own `YoutubeDL`, closed after the read; the
class-level-state test of the module extended to the logged-in read); D6 (skip while paused; a bot check during
the read records the account signal through the existing call); D7 (`sources.read` leaves an off LM line out; no
`SetupProblem`); bridge `set_read_liked_music`, `add_liked_music`, `add_playlist`'s `setting_off`, `settings()`'s
`youtube_music` block, `playlists()` rows' `needs_setting`; fake scenarios `settings:liked-off`,
`settings:liked-on`, `settings:liked-no-login`, `playlists:liked-listed-off`, and the fake's `add_playlist`
answering LM by the setting (today it reads LM as a normal playlist: a fake bug, fix it).

**Behaviours to test:** LM off → `setting_off`, no request (the yt-dlp stub sees no call); LL/WL → W17; LM on →
one read whose `YoutubeDL` options carry `cookiesfrombrowser` and no other read carries it; the download path's
options are unchanged after an LM read (snapshot of the class attributes and of a following download's options);
LM on while the YouTube account is paused → not read, its files stay, no drop; a run with an off LM line finishes
without a problem and keeps the line's files; `set_read_liked_music(True)` without a YouTube account → `not_set_up`;
`add_liked_music` appends exactly one line, refuses `exists` and `setting_off`; `settings()` and `playlists()` shapes
pinned in the contract tests. Checks as in E1.

### Group U1 — Blocks (Opus, build only, no shots)

**Mandatory:** load `apple-design` and `emil-design-eng`; read `docs/hub-design-language.md` (the colour rule's logo
exception, the blocks, the decision log).

**Read list:** I4; notes "Blocks" table and problems 1, 2, 5, 8; `lib/components/AddRow.svelte` +
`addRowModel.ts`; `TrackHead.svelte`; `KeyValue.svelte`; `SummaryStrip.svelte` + `summaryStripModel.ts`;
`QualityBar.svelte`; `ServiceMark.svelte` + `serviceLogos.ts`; `Surface.svelte`; `ExternalLink.svelte`; the
gallery's section for each (`lib/dev/Gallery.svelte`, by search); the mockup's `.openin`, `.qbar .wait`, LinkGuide
markup (by search, never the whole file).

**Scope.** Build from the mockup: rows 1, 12 (form only), 17 (the row only), 25 (the segment only), 28, and
`LinkGuide` (I4). Must not change: every other block, every token, every page (pages are U2/U3), the gallery's other
sections. Mockup errors to check at real size: the monospace example link, the logo spacing at 14 px, the Qobuz mark
(white on black) beside the placeholder.

**Tasks:** the five block changes + `LinkGuide`; a pure model with tests where there is logic (LinkGuide columns by
width, TrackHead truncation decision, dashed segment share); a gallery entry per new state (LinkGuide open / folded
/ narrow; AddRow placeholder and needs-setting form; TrackHead with link, long meta at 320 px, badge word hidden;
strip with a dashed end; KeyValue with a second line); `docs/hub-design-language.md` blocks + decision log
("dashed = waiting to be filled" now also on the quality bar). Checks: `npx vitest run` on the touched models,
`npm run check`, `npm run build` (static in its own commit).

### Group U2 — Playlists, Setup, Settings (Opus, build only, no shots)

**Mandatory:** as U1.

**Read list:** scope rows 1–14, 22, 23, 26, 27 and their binding words; Drift list rows for these pages;
`pages/playlists/Page.svelte` (header, list head, panel, empty state), `lib/shell/RowLead.svelte`,
`pages/setup/StepPlaylists.svelte`, `pages/settings/Page.svelte` + `settingsModel.ts` + `RowPanel.svelte`,
`lib/copy.ts` lines 1–80; contract I3.

**Scope.** Build from the mockup: rows 1–14, 22, 23, 26, 27. Must not change: everything in "Must not change" for
Playlists, Setup, Settings and the shell. Mockup errors: the Drift list's rows for `playlists`, `empty`,
`liked-*`, `settings*`, `setup*` (sun, ladder, column width, Setup foot, step strip, list cards to the foot).

**Tasks:** wire the blocks; Settings' new group, row, panel and actions (the switch saves at once through
`set_read_liked_music`; the panel's button calls `add_liked_music` and the page refreshes `settings()`; the
disabled reason's link selects the YouTube Premium row); Playlists' `needs_setting` row; `Turn on in Settings`
navigates to `#/settings/youtube_music`; Setup's rows from the same row data as Playlists (*check first:* what the
setup step reads after an add; reuse `playlists()` rows rather than a second shape); `shots.json` entries:
`playlists-liked-off`, `playlists-liked-on`, `playlists-liked-listed-off`, `settings-youtube-music`,
`settings-youtube-music-on`, `settings-youtube-music-no-login`, `setup-playlists-guide`, updated
`playlists-first-run` and `setup-playlists-done`; tests for the models touched (settings rows, add-row kinds,
list-head words). Checks as U1.

### Group S2 — Shots check of U1 + U2 (Opus)

**Mandatory:** load `apple-design` and `emil-design-eng`; review the whole screen in every shot (each grey, colour,
word and count for meaning), empty, first-open and no-selection states, logos at real size.

**How:** two dev servers: the group's branch and its base (`git worktree add` of the commit before U1 into the
scratch folder, `hub-ui/node_modules` symlinked). Shoot the same states on both at 1100, 1280, 2560 (`shots.mjs
--page playlists|setup|settings`, the base for the states that exist there) plus the gallery sections U1 touched.
**Every difference between base and branch that is not a scope row is a defect** (fix it in the block or page, or
report it as "beyond scope" with both shots). Compare the scope rows against the mockup states `playlists`, `empty`,
`liked-off`, `liked-on`, `settings`, `settings-on`, `setup`, `setup-added` (`--compare` with `mockupState`).
Pin D12: Hard_Techno's line whole at 1100 and 1280. Run `npm run rules -- --page <p> --only <shots>` for the
touched shots. Fixes go in the same branch; report with the shot names.

### Group U3 — Library, To-do, Sync card (Opus, build only, no shots)

**Mandatory:** as U1.

**Read list:** scope rows 15–21, 24, 25, 28; D10, D11; Drift list rows for `library*`, `todo`, `sync`;
`pages/library/TrackDetails.svelte`, the Library header and strip use (by search), the row context menu (by
search for `ContextMenu` in `pages/library`), `pages/todo/Details.svelte`, `lib/decisions/UpgradeCards.svelte`,
`pages/sync/SyncCard.svelte` + `cardState.ts` (how the card gets `source` from `SourceChosen`).

**Scope.** Build from the mockup: rows 15–21, 24, 25, 28. Must not change: everything in "Must not change" for
Library, To-do, Sync and the shell (the Sync page's layout above all: only the card's kicker and the new line).
Mockup errors: the Drift list's rows for these states.

**Tasks:** the Sync card carries `query_kind` from `SourceChosen` into its state and words it with D11 (a pure
function in `cardState.ts`, tested); SOURCE and FORMAT rows in both detail panels (`KeyValue` with `sub`); the
TrackHead link in Library and To-do; the context menu item; the strip caption and dashed end from `songs`; the
header without its count; `shots.json` entries `library-source-how`, `library-own-upload`, `todo-open-in`,
`sync-downloading-upload` (fake: a running card with `how: upload`). Checks as U1.

### Group S3 — Shots check of U3 (Opus)

As S2, for `--page library|todo|sync`, compared with the mockup states `library`, `library-upload`,
`library-none`, `todo`, `sync`. Look hardest at: the head card at 1100 (meta "…", badge word, Hide), the strip
caption at 1100 with the panel open, the dashed segment's width and colour, SOURCE's second line under a link, the
Sync card's kicker and new line at 1100 and 2560, and that nothing else on the Sync page moved.

## Review focus (final review)

1. **Cookies never leak:** the logged-in LM read's options exist only on its own `YoutubeDL`; no class attribute
   changes; the download path and every other read stay anonymous (tests prove it, not comments).
2. **The waits:** the LM read never runs while the YouTube account is paused, and a bot check it meets pauses the
   downloads through the existing record (D6).
3. **No dropped files:** an off or unread LM line never drops tracks or moves files (D7).
4. **Migration:** v4 → v5 in one transaction, NULL for old rows, a newer-version database still refused.
5. **`how` everywhere a file's source is written or reset** (download, "Use this", swap, undo, bought, import,
   reset to missing): grep `source_format` writes and check each has its `source_how` twin.
6. **FORMAT/SOURCE words:** FORMAT never shows a download's codec; the upgrade card's Now/New unchanged.
7. **Drift:** every touched page against main's shots: nothing outside the scope table changed (sun, ladder, list
   cards, Sync layout, To-do panel, browser column).
8. **Contract:** every shape change in contract + `types.ts` + `contract.ts` + fake; the fake's LM answer by setting.
9. Hard_Techno's problem line whole at 1100 and 1280; the AddRow placeholder never cut at 1100.

## Stage checks

Before the merge: `uv run pytest -q`, `npm run verify` once (background, status line), `npm run build` +
`npm run smoke`, CI green on push. README: Liked music (the setting, its risk), the details' FORMAT/SOURCE.
`docs/issues.md`: re-check and close what this round fixes; move the plan to `docs/archive/` when the last group is
done.

## Open questions for the user

1. **Words for two more ways a source is found.** The notes word four (`the playlist's own upload`, `exact Qobuz
   track`, `found by ISRC`, `found by name`). Two more exist: a fallback search (planned as `found by name`, it is
   one) and a version the user picked in To-do with "Use this" (planned as `picked by you`). Keep `picked by you`?
2. **Library's `All` count.** It counts files (13) while the table lists every song of the playlist (18, five
   waiting); the strip will now say `13 of 18 downloaded`. Stage 5 chose "files only" for the chips on purpose.
   Should `All` count the rows it lists (18), with the other chips staying file counts? Not built in this round.
