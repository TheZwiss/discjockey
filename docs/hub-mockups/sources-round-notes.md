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
| `TrackHead` | **Changed:** an optional `link` (`TrackLink`) adds a bottom row inside the head card: logo + "Open in {Service} ↗" (problem 5) |
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
  default, and a `NoteCard warn` with the risk. The warning shows in both states: before the choice it explains,
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
- **Main column:** the EmptyState keeps W22.

## 10. The Playlists subtitle at 1100 (states `playlists` at 1100 and 1280)

- **Design:** the count leaves the header and joins the list's own head: `Your playlists  7 on · 1 off · 70 tracks`.
  The header holds only the title and its actions, so it can't wrap at any size. To make room in the head at 1100,
  the reorder hint keeps only `top = highest priority`, and "drag ⠿ or ⌥↑ ⌥↓" moves into its ⓘ (the ⠿ handles are on
  every row anyway).
- **Why:** the number counts the list, so it belongs with the list's other counts, and a state is said once.

## Seen, not part of this round

- Library's `All` segment: the app's fake showed `All 13` while the playlist lists 18 songs (5 waiting). The
  mockup uses 18. Check which count is meant.
- To-do's head card wraps "lossy, audible" and Library's "verified lossless" onto a second line in the 320 px panel
  at 1100. It is the same in the app today.
- Setup's step strip cuts "Your existing music" with no "…" at 1100 and 1280.
- The Sync results' lossy row: the segment's dot is yellow ("Lossy") while a 16 kHz row's badge is red (weak). The
  same split exists in the app today.
- The Settings rows' glyphs for Qobuz, YouTube Premium and SoundCloud Go+ are grey shapes (◆ ▶ ☁), while the new
  "Reading playlists" rows use the coloured logos. The Downloads rows could take the logos too (one rule for "a
  service's row").
