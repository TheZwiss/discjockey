# Sources round: design notes

The notes behind `sources-round.html`. That page shows only the app window and the state switcher. Open it in a
browser and pick a state and a size (1100, 1280, 2560). The window is drawn at its real size and is scaled down
only when the browser is smaller. The hash `#<state>@<width>` opens a state directly. Every name, link and account
is made up.

The states: `playlists`, `empty`, `liked-off`, `liked-on`, `settings`, `settings-on`, `setup`, `setup-added`,
`library`, `library-upload`, `library-none`, `todo`, `sync`.

## Blocks

| Block | Reused / changed / new |
|---|---|
| `AddRow` | **Changed:** the placeholder is the words plus the four `ServiceMark`s, and the found card has a new "needs a setting" form (problem 3) |
| `ServiceMark` | Reused, unchanged (14 px, own colours); now also in Playlists and Setup rows, the Sync card and the details panel |
| **`LinkGuide`** | **New block:** a `Surface list` with one row per service (logo · name · where to click · what a link looks like). Columns come with the container's width: a two-line stack under 400 px (a panel), name + where from 400 px, plus the example link from 560 px. `folded` shows only the head with the four logos. Used by the empty Playlists panel and Setup |
| `TrackHead` | **Changed:** an optional `link` (`TrackLink`) adds a bottom row inside the head card: logo + "Open in {Service} ↗" (problem 5). At 320 px the meta line stays on one line and ends in "…" (full line in its tip), the badge's word shows whole or not at all (it wraps onto a hidden line; the badge's tip says it), and To-do's Hide sits beside the title only, so the other lines keep the full width |
| `KeyValue` | Reused; a value may take a quiet second line (Source's "how") |
| `SummaryStrip` | **Changed:** for a playlist the quality bar includes songs not downloaded yet as a dashed end segment, and the caption says "13 of 18 downloaded" (problem 8) |
| `PageHeader` | Reused, unchanged; Playlists no longer passes a `sub` (problem 10) |
| `ToggleGroup` head | Reused; Playlists' summary gains the track count, and the reorder hint moves into its ⓘ |
| `NumberedSteps`, `NoteCard warn`, `Switch` row, `ChoiceGroup`, `UpgradeCards` | Reused, unchanged |
| Sync card (`SyncCard.svelte`) | **Changed:** the source moves out of the kicker into its own line under the title, with the logo and the how |

## 1. Adding a playlist (states `playlists`, `empty`, `setup`)

- **Design:** the field's placeholder is "Paste a playlist link here", followed straight after the words by the four
  logos in the user's order (YouTube Music, SoundCloud, Spotify, Qobuz), 14 px, 6 px apart, in their own colours.
  Each logo has a Tip with the service's name. The logos are part of the placeholder: they go when the field has
  text, and the found card then shows the one service it recognised. It is the same field on Playlists and in Setup.
- **Why:** the logos say "these four" faster than a list of names, the line never gets cut at 1100 (W21's long
  form would), and the words stay plain.
- **Words:** `Paste a playlist link here`. This replaces W21 (both forms). The field's tooltip says the four names
  for VoiceOver and for anyone who doesn't know a logo.
- **Risk:** the Qobuz mark is the weakest logo at 14 px (white on black). It is the same as the Library sidebar's,
  so it stays.

## 2. Setup's example links (states `setup`, `setup-added`, `empty`)

- **Design:** 1 says which services, but not what to copy. `LinkGuide` under the Add card says where the link is in
  each app and what a link looks like. Once a playlist is added it folds into one line (head + logos) under "Your
  playlists", and a click opens it again. The empty Playlists page shows the same block in its panel, in the
  two-line form.
- **Words:** head `Where to find a playlist's link`. Rows: YouTube Music `Share › Copy` ·
  `music.youtube.com/playlist?list=…`; SoundCloud `Share › Copy link` · `soundcloud.com/name/sets/…`; Spotify
  `⋯ › Share › Copy link to playlist` · `open.spotify.com/playlist/…`; Qobuz `Share › Copy link` ·
  `open.qobuz.com/playlist/…`. W23's card label `Add a playlist` stays.
- **Check first:** the exact menu words in today's Qobuz and YouTube Music apps (web and Mac). The example shapes
  are the canonical links the readers write (`canonical_link`).

## 3. YouTube Music "Liked music" (states `settings`, `settings-on`, `liked-off`, `liked-on`)

- **Settings:** the "Spotify" group in Settings' list becomes **Reading playlists**, with two rows: Spotify (as today)
  and **YouTube Music** ("public playlists · Liked music off"). Its panel holds a card (YouTube Music: "Public and
  unlisted playlists need no login."), one switch row **Read my Liked music** ("uses your YouTube login"), off by
  default, and a `NoteCard warn` with the risk. The Downloads rows (Qobuz, YouTube Premium, SoundCloud Go+) take the
  same coloured `ServiceMark`s (YouTube's for Premium), so every service row has its logo. The warning shows in both states: before the choice it explains,
  after it reminds. When on and no Liked music line exists yet, the panel offers **Add Liked music to Playlists**
  (primary). It adds the `…list=LM` line, so the user never has to find a link that YouTube Music doesn't share.
- **Without a YouTube login** the switch is grey with the reason "Sign in to YouTube Premium first" (the
  `disabledReason` pattern) and a link to that row. This state is not drawn.
- **Warning words:** `Every read signs in with your YouTube account, the one your downloads use. Many reads can set
  off YouTube's bot check, which pauses downloads from YouTube for a while.`
- **Playlists, off:** a pasted `LM` link gives a found card, not an error. It shows "Liked music", the logo with
  "YouTube Music · yours", a yellow `!` with `Reading your Liked music is off`, the Hint `It reads through your
  YouTube login, so it's a choice in Settings.`, and the primary **Turn on in Settings** (it opens Settings at the
  YouTube Music row). Yellow is right here: a step from you, nothing broken. `LL`/`WL` (Watch later) and mixes keep
  W17/W18.
- **Playlists, on:** the normal found card ("YouTube Music · yours · 212 tracks", `Discjockey reads it through your
  YouTube login`, Folder name `Liked_music`, Add to the list).
- **Turned off while a Liked music line is listed:** that row reads like a switched-off row but says why
  (`[logo] Liked music is off in Settings`), and the sync skips it without a problem card. This state is not drawn.
- **Risk:** "pauses downloads for a while" must stay true to what the bot check really does. The engine side
  (cookies per read, how often) needs its own plan task.

## 4. Where a track came from (W20; states `sync`, `library-upload`, `library`)

- **Sync card:** the source leaves the uppercase kicker (`NOW · EXAMPLE_LABEL`) and gets its own line under the
  title: logo + `SoundCloud · the playlist's own upload`. The same line names the other ways: `Qobuz · exact Qobuz
  track`, `Qobuz · found by ISRC`, `YouTube Music · found by name`. The uppercase kicker would shout the long words, and a line of its
  own puts "from where" next to "what".
- **Details:** Source gets a quiet second line with the how (`the playlist's own upload`, `exact Qobuz track`,
  `found by ISRC`, `found by name`).
- **Engine:** today `how` exists only in the live `SourceChosen` event. The details need it stored with the file
  (`source_how` on the entry, written where `source` is). Files from before keep no second line.
- **Words:** W20 is kept exactly. The ISRC and name words become `found by ISRC` / `found by name` in the details,
  where a lone "ISRC" would mean nothing.

## 5. "Open in …" (states `library`, `library-upload`, `todo`)

- **Design:** `track_link` is a row at the foot of the head card in Library and To-do: logo + `Open in Spotify ↗`
  (the `ExternalLink` look). It sits with the song (the head card), not with the file (Current file), because the
  service's page belongs to the song, file or no file. A waiting song (dashed cover) shows it too. The row's
  right-click menu gains the same item.
- **No double link:** when the download's page is the same page (a SoundCloud playlist's own upload), Source shows
  the service without a link (`library-upload`). Otherwise Source keeps its own link to where the file came from
  (`Qobuz ↗`).

## 6. FORMAT vs the file (states `library`, `library-upload`, `todo`)

- **Design:** FORMAT is what the file is: `AIFF · 16-bit`. What it came from moves to Source: `Qobuz ↗ · FLAC`,
  `YouTube Music ↗ · Opus · 135 kbps`, `SoundCloud · WAV`. Read top to bottom, the panel says "the file is AIFF,
  made from a FLAC from Qobuz". The file name's `.aiff` and FORMAT now agree.
- **Upgrade card:** Now / New keep today's values (`Opus · 135 kbps` / `FLAC · lossless`). In a comparison of two
  versions what differs is what each was made from (both end up AIFF), and the values stay short for the 320 px
  panel. Now's tooltip says `Your AIFF was made from this`.
- **Contract:** `format_line` becomes the file's own format (container + bit depth when known). The download's
  format moves to `source_format_line` ("FLAC", "Opus · 135 kbps"), which Source and the upgrade card's Now read.
  The user's own files and bought files: FORMAT is their real format (`WAV · 24-bit`), Source `your own file` /
  `bought`.
- **Check first:** whether the file row knows the bit depth. If it doesn't, FORMAT is just `AIFF`.

## 7. Setup's playlist rows (state `setup-added`)

- **Design:** Setup's rows are the Playlists rows without the controls: cover, folder name, then
  `[logo] "Playlist name" · owner · N tracks`. The raw link is gone. "yours" for the user's own playlists, else the
  owner's name, as on Playlists.
- **Also on Playlists:** the service's name in words leaves the rows and the logo says it (as in the Library
  sidebar, Tip on hover). At 1100 the owner was being cut, and the logo is quicker to read. A problem line keeps
  its logo and its red words.

## 8. Library's count at 1280 with details open (states `library`, `library-none`, `library-upload`)

- **Design:** the count leaves the header and goes into the `SummaryStrip`, at every size. The quality bar spans
  every song of the playlist: the downloaded ones in their quality colours, the rest as a dashed end segment (the
  house shape for "waiting to be filled", as the dashed cover). The caption reads `9 of 13 checked · 13 of 18
  downloaded`.
- **Why:** a quantity is a number plus a visual. The strip is always there, so the count never drops, and it is
  said once. The header keeps only `{Service} playlist`, which always fits.
- **Risk:** the % stays "of checked tracks", while the bar now also spans the waiting songs. The dashed segment
  reads as "not there yet", but it should get one look in the live check.

## 9. The empty Playlists panel (state `empty`)

- **Design:** with no playlists the Segmented (both counts 0) and the "0 tracks" card leave. The panel shows how a
  playlist comes in (`NumberedSteps`: `Copy its link in the music app` · `Paste it above: it gets a folder` ·
  `Sync downloads its songs as AIFF`) and `LinkGuide` in its two-line form. The foot (Undo · Save) stays grey,
  because disabled controls are never removed. When the first playlist is added, the panel goes back to its usual
  content.
- **Main column:** the EmptyState's line is `Paste a link above to add your first one.` (replaces W22, whose list of
  names repeated the logos right above it). With no playlist the sidebar shows no To-do count and no Download limits dot.

## 10. The Playlists subtitle at 1100 (states `playlists` at 1100 and 1280)

- **Design:** the count leaves the header and joins the list's own head: `Your playlists  7 on · 1 off · 70 tracks`.
  The header holds only the title and its actions, so it can't wrap at any size. To make room in the head at 1100,
  the reorder hint keeps only `top = highest priority`, and "drag ⠿ or ⌥↑ ⌥↓" moves into its ⓘ (the ⠿ handles are on
  every row anyway).
- **Why:** the number counts the list, so it belongs with the list's other counts, and a state is said once.

## Seen, not part of this round

- Library's `All` segment: the app's fake showed `All 13` while the playlist lists 18 songs (5 waiting). The
  mockup uses 18. Check which count is meant.
- Setup's step strip: the second step is called `Existing music` (was `Your existing music`, cut without "…" at
  every size); a label that still doesn't fit ends in "…".
- The Sync results' lossy row: the segment's dot is yellow ("Lossy") while a 16 kHz row's badge is red (weak). The
  same split exists in the app today.
- Playlists at 1100: the owner still ends in "…" on three rows, and Hard_Techno's problem line reads `Follow ≠ own:
  make your o…`, which cuts the instruction.

## Drift list

The mockup was drawn from memory, so it differs from the real app in places outside its ten problems. Compared
2026-11-05: each state shot from the fake app (`normal`, `playlists:empty`, `setup:playlists`, `library:playlist`,
`syncing` scenarios; the nearest real state where the mockup's state doesn't exist yet) and from the mockup, at 1100,
1280 and 2560, region by region. **The real app is the reference** for every row marked "mockup error: keep the app".
Differences that come only from the fake's data (track names, covers, counts, which accounts are set up) are not
listed. "All" means the row holds in every state that shows the element.

| State | Element | Mockup vs app | Verdict |
|---|---|---|---|
| All | Sidebar Settings icon | sun vs the app's gear | mockup error: keep the app |
| All | Sidebar Sync row while syncing | no count vs the app's `3/5` | mockup error: keep the app |
| All | List cards (Playlists, Settings, To-do, Sync results, Library table) | stretch to the window's foot vs the app's cards that end after their last row | mockup error: keep the app |
| All | Row title separator | hyphen `Artist - Title` vs the app's en dash `Artist – Title` (Playlists panel, To-do, Sync rows) | mockup error: keep the app |
| All | Type sizes and greys of secondary text (row sublines, `6 of 15 lossless`, counts, KeyValue labels, panel row) | a little larger and brighter vs the app's tokens | mockup error: keep the app |
| All | Badges (QualityBadge) | wider letter-spacing, other column positions vs the app's | mockup error: keep the app |
| `playlists` | Paste field placeholder with four logos | W21 words vs words + logos | in scope (problem 1) |
| `playlists` | Header sub `48 tracks in your playlists` | gone vs shown (wraps to two lines at 1100) | in scope (problem 10) |
| `playlists` | List head `7 on · 1 off · 70 tracks` | count joins the head vs `9 on · 1 off` | in scope (problem 10) |
| `playlists` | Reorder hint | `top = highest priority` + ⓘ vs `top = highest priority · drag ⠿ or ⌥↑ ⌥↓` + ⓘ | in scope (problem 10) |
| `playlists` | Row subline service | logo only vs the service's name in words | in scope (problem 7) |
| `playlists` @1100 | Quality column | shown, so owner and Hard_Techno's problem line end in "…" vs the app, which hides the column at 1100 and reads both whole | mockup error: keep the app (the line must read whole) |
| `playlists` | Row number / cover x-position | number at 241 px vs 236 px, cover a few px right | mockup error: keep the app |
| `playlists` | Panel "Where they land" row | `1 · lands in Hard_Bounce` vs `1  lands in Hard_Bounce`; taller track row | mockup error: keep the app |
| `playlists` | Quality bar segment colours | purple last segment vs the app's colours from data | mockup error: keep the app |
| `empty` | Main EmptyState body | `Paste a link above to add your first one.` vs W22 | in scope (problem 9) |
| `empty` | Panel | NumberedSteps + LinkGuide (two-line form), no Segmented and no `0 tracks` card vs the app's Segmented + StatCard | in scope (problems 2, 9) |
| `empty` | EmptyState card height | one line shorter | in scope (follows the shorter body) |
| `liked-off` | Found card | `Liked music`, logo + `YouTube Music · yours`, yellow `!` line, Hint + `Turn on in Settings` vs W17 refusal (the fake today even reads `LM` as a normal playlist) | in scope (problem 3) |
| `liked-off` | Found card cover | dashed empty cover vs the app's filled cover | keep the app's cover rule for a playlist without a cover (check `AddRow`'s found card) |
| `liked-on` | Found card | normal found card with `Discjockey reads it through your YouTube login`, Folder `Liked_music` | in scope (problem 3) |
| `settings` | "Where your music comes from" ladder | plain dots with no connecting line, Premium as a yellow live step, `through YouTube Premium and SoundCloud Go+`, no chips, no footer vs the app's `SourceLadder`: connected line, hollow unavailable Premium step, `needs YouTube Premium or SoundCloud Go+`, dashed `YouTube` / `SoundCloud` chips, muted badge, footer note `Songs Qobuz doesn't have come from free YouTube at about 130 kbps.` | mockup error: keep the app |
| `settings` | Ladder row spacing and title size | tighter rows, larger title | mockup error: keep the app |
| `settings` | Downloads rows' icons | coloured ServiceMarks (Qobuz, YouTube, SoundCloud) vs grey glyphs (◆ ▶ cloud) | in scope (problem 3, notes §3) |
| `settings` | Downloads rows' sublines and status marks | `signed in · checked today`, all ✓ vs the app's words and its dashed "not set up" mark | mockup error: keep the app |
| `settings` | Group `Spotify` | renamed `Reading playlists` with Spotify + YouTube Music rows | in scope (problem 3) |
| `settings` | Spotify row icon | Spotify's ServiceMark vs a ♫ glyph | in scope (problem 3: every service row has its logo) |
| `settings` | Group label weight | bold white `Downloads` / `Reading playlists` vs the app's ListSection head | mockup error: keep the app |
| `settings` | "This Mac" group | Music folder only vs the app's Music folder, Watched folders and the rows below | mockup error: keep the app |
| `settings` | YouTube Music panel | head card, `Read my Liked music` switch row, warn NoteCard | in scope (problem 3) |
| `settings-on` | `Add Liked music to Playlists` | primary button under the warning | in scope (problem 3) |
| `setup` | Column width | 900 px vs the app's 860 px | mockup error: keep the app |
| `setup` | Foot before a playlist is added | filled `Finish`, no hint vs the app's `Add a playlist first.` + disabled Finish | mockup error: keep the app |
| `setup` | LinkGuide under the Add card | new | in scope (problem 2) |
| `setup` | LinkGuide example link | monospace | in scope (problem 2), font from the design language's tokens, not a new face |
| `setup`, `setup-added` | Step strip label | `Existing music` vs `Your existing…` | not this round (notes "Seen"): keep the app |
| `setup-added` | Last step mark | `6` vs the app's ✓ once a playlist is added | mockup error: keep the app |
| `setup-added` | Rows | cover + folder + logo `"Name" · owner · N tracks` vs folder + `Spotify · <raw link>` | in scope (problem 7) |
| `setup-added` | Folded LinkGuide | new | in scope (problem 2) |
| `library` | Browser column | no Favourites section, Playlists head without sort and fold controls, flat folders with ▱ glyphs vs the app's Favourites drop zone, sort + chevron, nested folders with chevrons, the offline mark | mockup error: keep the app |
| `library` | Browser row text | larger and brighter | mockup error: keep the app |
| `library` | Header count | gone vs `13 of 18 downloaded` (1100, closed panel) | in scope (problem 8) |
| `library-none` | Header breadcrumb `Library › Hard_Bounce` | gone vs shown when it fits | keep the app (only the count leaves) |
| `library` | Strip caption | `9 of 13 checked · 13 of 18 downloaded` vs `9 of 13 checked tracks` | in scope (problem 8) |
| `library` | Strip quality bar | dashed end segment for waiting songs | in scope (problem 8) |
| `library` | Strip right row `Not lossless yet` | no `· all in To-do` vs the app's | mockup error: keep the app |
| `library` | Segmented | no `Fake` segment, a dot only on Lossless vs the app's Fake segment and a dot on every quality segment | mockup error: keep the app |
| `library` | `All` count | 18 vs 13 (the app lists 18 rows) | not a mockup problem: the app's own inconsistency, see the plan |
| `library` | Table | no sort arrow, no `in <playlist>` hint, no LENGTH column (2560, closed panel), no UPGRADE column, no ⓘ, 46 px rows vs the app's 38 px rows with all of them | mockup error: keep the app |
| `library` @2560 | "Also in this folder" section | missing vs shown | mockup error: keep the app |
| `library` | Head card `Open in Spotify ↗` row | new | in scope (problem 5) |
| `library`, `todo` | Head card meta line and badge word at 320 px | one line with "…", word whole or hidden vs the app's wrapping lines | in scope (TrackHead change) |
| `library` | Spectrum | gradient placeholder vs the app's spectrum with its `22.1 kHz` label | mockup error: keep the app |
| `library` | FORMAT / SOURCE values | `AIFF · 16-bit` / `Qobuz ↗ · FLAC` + `exact Qobuz track` vs `FLAC` / `Qobuz ↗` | in scope (problems 4, 6) |
| `library` | FILE value | cut at the end vs the app's middle truncation | mockup error: keep the app |
| `library-upload` | SOURCE without a link | `SoundCloud · WAV` + `the playlist's own upload` | in scope (problems 4, 5) |
| `todo` | Segmented | no `Weak` segment vs the app's | mockup error: keep the app |
| `todo` | List head | no `Show hidden · 1` vs the app's | mockup error: keep the app |
| `todo` | Sections | only Upgrade ready + Not found vs the app's rekordbox check and Weak sections | data; keep the app |
| `todo` | Head card badges | no `↑` upgrade chip vs the app's | mockup error: keep the app |
| `todo` | Upgrade card | gradient placeholders, no `EDIT · The same edit as yours` row vs the app's spectra and edit row | mockup error: keep the app |
| `todo` | Upgrade card Now tooltip | `Your AIFF was made from this` | in scope (problem 6) |
| `todo` | In rekordbox card | `RECOMMENDED` inline, no Superseded/ line and no Tip vs the app's right-aligned `RECOMMENDED`, `Your old file is kept in Superseded/`, `Tip: quit rekordbox before you replace` | mockup error: keep the app |
| `todo` | Panel foot | no `You can undo a replace until you press Done` vs the app's | mockup error: keep the app |
| `sync` | Page head | `Syncing 4 of 12 · ~6 min left` + `Stop` in the header vs the app's `Sync running`, the `Track 3 of 5` progress card (time left, Qobuz count) and the foot `Stopping is safe at any time` + `Stop safely` | mockup error: keep the app |
| `sync` | Column width | 900 px vs 860 px | mockup error: keep the app |
| `sync` | Card kicker | `NOW · EXAMPLE_LABEL` vs `NOW · POWERTRANCE · YT MUSIC` | in scope (problem 4: the source leaves the kicker) |
| `sync` | Card `from` line | logo + `SoundCloud · the playlist's own upload` | in scope (problem 4) |
| `sync` | Step bar | four steps, no ✓ / green done step vs the app's five (`Search ✓`, Download, Check, Convert, Analyse) | mockup error: keep the app |
| `sync` | Progress line | `41 of 96 MB · ~6 s left` vs `0.2 of 0.4 MB · 50 %` | mockup error: keep the app |
| `sync` | Results | Done only, with playlist sublines vs the app's Problems / Done / Up next sections | mockup error: keep the app |
| `sync` | Segmented `Problems` | no dot vs the app's red dot when there are problems | mockup error: keep the app |
