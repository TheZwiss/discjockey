# Library stage 5 "Library layout" — plan

Spec: `docs/2026-10-23-library-and-sources-design.md` §11, with §2 (terms), §3 item 4, §6.4 (offline), §13 ("UI").
Design (approved by the user): `docs/hub-mockups/design-system/library-layout.html` and its notes
`library-layout-notes.md` (cited below as **N** with the decision's number, e.g. N5). Crate rules from the earlier round:
`library-browser.html`'s "Decisions" (cited as **B**) as far as the notes don't replace them. Leftovers: `docs/issues.md`
#26 (first bullet). Orchestration: `docs/2026-10-23-library-and-sources-orchestration.md`.

The stage ships in **two steps**, each on its own branch from `main`, each reviewed, merged, pushed and live-checked
on its own:

- **Step A "Layout"** (`feat/library-5a-layout`): the rail and the two sidebar forms with their memory, the browser
  column (today's collections, the filter and its hand-off, the drag), the details inspector, the summary strip, the
  motion, the shortcuts. It reads only what the engine knows today plus three small fields.
- **Step B "Folders and records"** (`feat/library-5b-folders`): read records, crates, Favourites, hiding, the playlist
  and folder views, Settings' crate switches.

**Why this cut.** The layout needs nothing that read records or the crate scan produce: today's sidebar already has the
playlists in order with a count, the Library folders and the views, and the Library page already has every column the
new table shows (Length included). Three facts are missing, all cheap and all from data the engine has: each playlist's
service and on/off (from `playlists.txt`), the not-lossless count for the strip, and the header's subtitle parts. Step B
then changes data under a finished layout: records, crates and Favourites all need the new schema step, and Favourites
of crates need crates. The one thing step A loses for a while: other pages show only the pages (Favourites come with
step B), so a playlist is ⌘K or two clicks away from To-do. **No release between A and B** (the orchestrator holds it).

---

## Global constraints

- **The player bar (`shell/Foot.svelte`, `SyncPart`, `PlayButton`, the Now playing row) stays exactly as it is.** The
  only change: its line starts at the page's edge, which in Library is the chrome's whole width (N12: the line follows
  `--sidebar-w`, which becomes the chrome's width). The hidden player gets a rail form (N11): the same 22 px
  `PlayButton`, ⌃ Show player and the row's 2 px position line, stacked. Any other change to the foot is out of scope.
- **Nothing here moves, renames or writes a music file.** The stage's only writes are the read records, Favourites
  and crate visibility (D1, D15), all in `library.db`.
- **`views.py` and `planner.py` stay pure; only `db.py` writes SQL.** The new tables never enter the snapshot and
  never bump `generation` (stage 4 I2).
- **Every visual signal has exactly one meaning** — the notes' signal table (N, "What each signal means") is binding,
  plus D6's row signals. Reviews check each shot against both.
- **Seamless chrome:** the rail, the full sidebar and the browser column are one material with the foot (N3); nothing
  floats or reserves a strip. Structured controls only.
- **The user's settled wishes, unchanged:** the services' original coloured logos (D7); drag ordering only inside
  Favourites, Playlists in priority order with an A–Z option (N13); the name "Playlists"; the track list fully usable
  at 1280 × 800 and 1100 × 700 (N6, N7); a click on a track opens its details unless the user hid them by hand, which
  sticks and shows on the toggle (the user's wish at the step A live check, replacing N5's "a click only selects"); the
  "Search tracks for …" row
  (N3).
- **Contract rule** and **design rule** as CLAUDE.md. **Tests offline**, made-up names. `scripts/check_public.sh` before
  every commit.

## Decisions (with reasons)

- **D1. Read records in `library.db`.** After each successful read of a playlist, its tracks (order, token, artist,
  title, length) and the read's time replace that playlist's record; records of playlists no longer in `playlists.txt`
  (on or off) are dropped. *Why:* counts and a playlist's view must be there when the window opens, offline, and for
  switched-off playlists. Recorded wherever the fetch result first exists with the database at hand (check first:
  `run.prepare` or its caller; the console's sync and dry run and the hub's read all pass through it). A dry run
  records too (check first that its connection is writable; if not, skip it there and say so in the report). Outside
  the library lock, best-effort: a failing write is logged, the read still succeeds.
- **D2. A record keeps the fetched token plus display facts**, resolved to songs at view time (keys and `aliases`).
  *Why:* a song not downloaded yet still shows ("Waiting"); a later relink still resolves.
- **D3. Names and keys.** A playlist is named by its folder name, keyed by its line's ref (a folder rename keeps the
  record and the favourite). A folder is keyed by its **snapshot path** (`Library/Old_Hardstyle`, or the absolute path
  in an import folder), also its route key. Favourite keys: `playlist:<ref>`, `folder:<path>`.
- **D4. The browser column's content (replaces the old sidebar group, N2, N3).** Top, no head: All tracks, Not in a
  playlist. Then the sections **Favourites** (step B), **Playlists** (`playlists.txt` order, switched-off ones in place
  and dimmed; an A–Z toggle), **Folders** (step A: the `Library/` folders no playlist line uses; step B: each watched
  import folder with its crates, then those Library folders). Every row one line (N4). Section heads fold, stick to the
  list's edges, solid and square (N10, N15). The full sidebar on other pages lists the pages, Library (♫, after
  Download limits) and, from step B, Favourites without counts.
- **D5. Counts.** Playlist: step A the files in its folder (today's number); step B the songs its view lists (distinct
  songs of its record; never read → no number). Watched folder, crate, Library folder: files at or below it. Views:
  files. An offline folder keeps its count.
- **D6. Row signals in the table (binding with the notes' table):** lead dimmed = a downloaded song that left every
  playlist (own files never); dimmed + `AwayTag` = the file is away; dimmed + "Waiting" (muted words) or the red
  `NOT FOUND` badge + dashed empty cover = a playlist song with no file; "in Techno 2019" after the title in
  `--text-label` = the file sits outside the playlist's own folder; neutral `Badge` with a playlist's name (+n) = the
  playlists holding the song; "–" = nothing there.
- **D7. `ServiceMark`: the services' original logos in their own colours, 14 px, unchanged** (the user's wish). The SVGs
  are the mockup's `SVC` table in `library-layout.html` (Qobuz's black tile with its faint edge), copied into
  `hub-ui/src/lib/components/serviceLogos.ts` with a comment naming their source (Simple Icons shapes, CC0; Qobuz's
  from static.qobuz.com). All five services now. A dimmed row dims its logo. The colour rule gets its one exception (D16).
- **D8. Crates (B "Decisions", N4, N13).** Under a watched import folder W, a **crate** is any folder below W that holds
  at least one indexed file itself; wrapper folders get no row; W itself is the watched-folder row. Pure, in `views.py`:
  - **Label (one line, also the Subfolder column's words):** a crate inside another crate reads
    `"{nearest crate ancestor} › {name}"` ("Hardtechno › 2019"); a crate whose name another crate also has (any watched
    folder, fold-equal, single-name labels only) reads `"{name} · {its parent folder's name}"` ("Bounce · Old Sets");
    otherwise its name. *Changed from the mockup:* the mockup compared only shown crates, so hiding one would rename
    another; here every crate counts, so a label never changes with visibility.
  - **Order:** by label, natural numbers, case-folded. **Count:** files at or below it. **Tooltip:** the full path from
    W's name, " › " between levels.
  - **Too many:** more than 25 crates under W → W is one row without a chevron; its crates are hidden unless switched
    on (Settings, D15). The filter still finds every crate.
  - Files directly in W belong to no crate (Subfolder "–").
- **D9. A playlist's view:** its songs in playlist order (`#` column, default sort `order`), a song listed twice shown
  once (first place); a file outside the playlist's own folder carries the note "in {place}" after its title (it gives
  way first); below, the `ListSection` **Also in this folder**: files physically in `Library/<folder>/` (incl.
  `not_lossless/`) whose song the playlist doesn't hold. One table, one column grid.
- **D10. Table columns follow the table's own width (N6, the mockup's `columns()`).** Always Track, Artist, Quality
  and the upgrade slot; then, as width allows: **Subfolder** (or **Folder** in All tracks and Not in a playlist),
  **Playlist**, **Length**; they go in the reverse order (Length first, Subfolder last). Per view: All tracks: Folder,
  Playlist, Length; Not in a playlist: Folder, Length; a playlist: Length (its order and notes carry the rest); a
  Library folder: Length; a watched folder: Subfolder (if it has crates), Playlist, Length; a crate: Subfolder (only
  if it has crates inside, relative path with " › "), Playlist, Length. **Source and Added leave the table** (the
  approved widths have none; the inspector shows both). Container queries as today, thresholds from the mockup: Track
  + Artist 380, + Subfolder 140, + Playlist 180, + Length 200. Default sort Artist ↑ (as the mockup), a playlist `order`.
- **D11. The inspector's head says where the file sits.** `track()` gains `place` (the physical folder, the same words
  as the Subfolder/Folder column); `TrackHead`'s place line shows it ("in Hardtechno › 2019", N6).
- **D12. All tracks' and Not in a playlist's Folder column says where the file sits** (`place`): a playlist's folder
  name, a Library folder's name, or for an import file its watched folder and crate ("Rekordbox Library › Hardtechno
  › 2019", crate labels, no wrappers). A place too wide gives way in the middle, whole folders first (`MiddleText` gains
  `sep`), then characters; tooltip the full place. Being in no playlist stays told by the dim and `rowTitleTip`.
- **D13. The read-status wire is renamed** (issue #26): `spotify` → `read_status`, `views.spotify_status` →
  `views.read_status`, `SpotifyStatus` → `ReadStatus` (type and component), the `PageHeader` slot's docs word, the rule
  checker's `spotify-status` rule and its fixture. Real Spotify things keep their names. A pure rename.
- **D14. Not in this stage:** issue #27's To-do `AwayTag`.
- **D15. Favourites and crate visibility live in `library.db`, written outside the job system.** Two small tables
  (I1) beside the read records, never in the snapshot, no generation bump. *Why not localStorage (the sidebar forms'
  home):* the window's saved settings start over whenever its port changes (`hub/window_port.py`), which is fine for a
  width but not for a user's curated list. *Why not a write job:* jobs are refused while a sync runs, and pinning a
  playlist during a long sync must work. So `set_favourites` and `set_crate_shown` are **brief writes** (the
  `setup_skip_import` precedent, "a brief save, not a job"), but they don't take the engine lock either: the tables
  aren't library state, and SQLite's busy timeout orders them against a running job's transactions. A write that still
  fails answers `{"ok": false, "kind": "busy"}`; the UI then puts the list back and toasts. The contract records the
  exception with this reason.
- **D16. House rules for `docs/hub-design-language.md`** (written in step A's G3, Favourites' part in step B's G5): the
  notes' house-rule changes 1–6 and 8–10 (7 is "no change"), each with its reason and a decision-log entry:
  1. the L frame: two sidebar forms (168 / 50); in Library the frame holds the browser column; `--sidebar-w` is the
     chrome's whole width and the foot's line follows it; 2. one more chrome line: the sidebar's right edge while the
     browser stands beside it; 3. `ListPanelFrame`: Library's panel becomes an on-demand inspector (same widths, same
     `Panel`), its summary the `SummaryStrip` block; other pages keep the docked panel; 4. the sidebar's Library group
     retires (Favourites without counts on pages without the browser; the two-line crate rows and balanced wrap
     retire); 5. motion: "the chrome moves, the page lays out once", with the notes' timings; 6. the nav's text glyphs
     become drawn icons (`NavIcon`, 14 px, 1.3 px stroke); 8. `PageHeader`: the subtitle is a list of parts that drop
     whole, last first; 9. dim is reserved: in lists of collections half strength means switched off, a name's
     secondary part keeps the name's colour, only its separator is quiet; 10. stuck heads are opaque, square and get a
     hairline (`ListSection`).
  Plus **the colour rule's exception**: a service's logo keeps its own colours; it is an image naming a service, not a
  signal. If `rules-page.js`'s colour check flags it, exempt only `[data-service-mark]`, with that reason in a comment.
- **D17. Sidebar memory and the step-back (N7, N8).** UI prefs (localStorage, `persisted`): `shell.form.library`
  ('rail'), `shell.form.other` ('full'), `shell.browser.width` (240, clamped 200–360), `shell.browser.closed` (folded
  sections and watched folders), `shell.playlists.az` (false), `library.inspector` (false), `library.details.hidden` (false: details hidden by hand,
  see A6.2). Below `--panel-narrow-below`
  (1240 px window) an open inspector steps the browser back behind the rail; ⌘K or ♫ brings it back and closes the
  inspector.
- **D18. Shortcuts (N "Keyboard"), checked against the app.** Today: Space, ⌘← ⌘→ (player, `footModel.playerKey`,
  never in fields, buttons or dialogs); ⌘F (`SearchField`, window-level); ↑ ↓ Enter Esc inside lists, menus and To-do;
  the native menu (pywebview cocoa): ⌘H, ⌥⌘H, ⌘Q, ⌃⌘F (full screen), ⌘X ⌘C ⌘V ⌘A. The new keys ⌘1–6, ⌘,, ⌘K, ⌘I,
  ⌃⌘S **clash with none of them**. Rules that keep it so: one window-level handler (`lib/shell/keys.ts`, pure +
  tested) owns the new keys, works also while a text field has focus (they all carry ⌘), never while a dialog is open;
  ⌘F stays `SearchField`'s; ↑ ↓ Enter Esc belong to whatever has focus (the filter field, the table). ⌘1–6 match
  `e.code` `Digit1…6` so keyboard layouts don't matter. In the fake-mode dev browser ⌘1–6 and ⌘K may be taken by the
  browser itself; that is dev only. The notes' "also in the View menu" item: check first whether pywebview's menu API
  can add an item to its default View menu; if it can't without a second View menu, skip the menu item and keep the
  key (report it).
- **D19. Screenshots with the rail.** Every page's chrome changes, so every shot changes; there are no stored
  baselines (shots are looked at, rules are checked), so nothing is re-blessed. What changes: `shot-lib.mjs` gains a
  shot key `prefs` (seeded into localStorage right after its per-shot clear), so a shot can show the folded sidebar,
  a wider column or an open inspector; every shot still starts from the defaults (Library rail, other pages full).
  `shots.mjs --compare` gains `mockupState` (loads `<mockup>#<state>`, waits for `[data-win]`, clips it) and
  `mockupScale` (1 for `library-layout.html`, which is drawn at real size; 1.15 stays the default). `rules-page.js`
  gains a `chrome-edge` rule: the page frame's left edge equals `--sidebar-w` (the foot's line and the page's edge can't
  drift apart), with a good and a bad fixture; its `spotify-status` rule becomes `read-status` (D13). The smoke test
  keeps finding `[data-test=nav-library]` (the Library nav item keeps that id). `npm run verify` runs once per step,
  by the orchestrator.
- **D20. Issue #28 (widen the sidebar by dragging) is covered** by the browser column's drag (N4): long names come out
  whole in Library. The full sidebar on other pages lists only pages and short favourites; a long favourite ends in
  "…" with its tooltip, as every row does. The entry is removed in this plan's commit.

## Review focus

1. Each signal in the shots means exactly the notes' table and D6; no dim, grey or colour has a second meaning.
2. The foot is today's foot (compare `base-gallery-foot` before/after); only its line's start follows the chrome.
3. Read records, Favourites and crate visibility never bump `generation`, never enter `snapshot`; a failed record never
   fails a read.
4. `views.py` pure; no SQL outside `db.py`; counts in the browser equal the rows of the view they open.
5. Seamless chrome and alignment at 1100, 1280 and 2560; no icon moves when the sidebar folds (N1).
6. Old routes (`#/library/folder/Hard_Bounce`) still open the playlist.

---

## Interfaces

**I1. Schema step 3 → 4 (step B)** (`SCHEMA_VERSION = 4`, through `db._upgrade`):

```sql
CREATE TABLE playlist_reads (playlist TEXT PRIMARY KEY, service TEXT NOT NULL, read_at TEXT NOT NULL);
CREATE TABLE playlist_tracks (playlist TEXT NOT NULL REFERENCES playlist_reads (playlist) ON DELETE CASCADE,
  position INTEGER NOT NULL, token TEXT NOT NULL, artist TEXT NOT NULL, title TEXT NOT NULL, duration_ms INTEGER,
  PRIMARY KEY (playlist, position));
CREATE TABLE favourites (position INTEGER PRIMARY KEY, key TEXT NOT NULL UNIQUE);
CREATE TABLE crate_shown (path TEXT PRIMARY KEY, shown INTEGER NOT NULL);
```

`playlist` is the line's ref (check first: that a `FetchedPlaylist` carries the same token as `playlists_file.Row.ref`).
`crate_shown` holds only the user's overrides; no row = the default (shown, or hidden under a too-many folder).

**I2. `db.py` (step B):** `record_reads(conn, reads, now, keep)` (one transaction; replaces each read that has tracks;
an unreadable playlist keeps its record; deletes refs not in `keep`); `playlist_records(conn) -> dict[str,
PlaylistRecord]` (`PlaylistRecord(service, read_at, tracks)`, `RecordedTrack(position, token, artist, title,
duration_ms)`, NamedTuples beside `ImportCounts`); `favourites(conn) -> list[str]`; `set_favourites(conn, keys)`
(replaces the list, drops duplicates keeping the first); `crate_overrides(conn) -> dict[str, bool]`;
`set_crate_shown(conn, path, shown: bool | None)` (None removes the override). None bumps `generation`. Pins: v3 → v4
keeps every row; a v4 library refuses a stage-4 build (`NEWER`); the record rules; a second connection holding a write
transaction makes these wait (check first: `connect`'s busy timeout), then fail cleanly.

**I3. Step A shapes** (views, contract, types, fake; each a small addition):

```ts
export type Sidebar = {
  todo: number; all_tracks: number; not_in_playlist: number; limits_warning: boolean;
  playlists: { name: string; ref: string; service: PlaylistService | null; enabled: boolean; tracks: number }[];
  library_folders: { folder: string; tracks: number }[];   // Library/ folders no playlist line uses, by name
};
// Library gains: subtitle: string[] (parts in order of importance, I7), summary.not_lossless: number
// (checked files of the counted rows that aren't lossless: good lossy + weak + fake; beside summary.to_do)
```

`limits_warning` keeps today's meaning (a warning sign not yet seen, or a service paused today). See the concerns in
the report: the notes describe the dot as "a limit reached or a service waiting"; that is a product change this stage
doesn't make.

**I4. Step B shapes:**

```ts
export type Sidebar = {
  todo: number; all_tracks: number; not_in_playlist: number; limits_warning: boolean;
  favourites: Favourite[];   // stored order; keys whose target is gone are left out
  playlists: { name: string; ref: string; service: PlaylistService | null; enabled: boolean; songs: number | null }[];
  watched: WatchedEntry[];   // import folders by name
  library_folders: { path: string; name: string; files: number }[];
};
export type Favourite = { key: string; kind: 'playlist' | 'folder'; name: string; service: PlaylistService | null;
  enabled: boolean; count: number | null; path: string | null; state: FolderState };
export type FolderState = 'here' | 'offline' | 'folder_missing';
export type WatchedEntry = { path: string; name: string; place: string; files: number; state: FolderState;
  too_many: boolean; crate_count: number; crates: Crate[] };   // crates: all of them, label order
export type Crate = { path: string; label: string; name: string; tip: string; files: number; hidden: boolean;
  has_crates: boolean };
export type LibraryView = 'all' | 'unlisted' | 'playlist' | 'folder';
export type LibraryRow = TrackRow & {
  sound_checked: boolean; file_state: FileState | 'no_file';
  wait: 'waiting' | 'not_found' | null; position: number | null;
  place: string | null;      // where the file sits (D11/D12); playlist view: null inside the playlist's own folder
  subfolder: string | null;  // folder views: crate label (watched folder) or relative path (crate); '' = itself
  playlists: string[];       // the playlists holding the song, playlists.txt order
};
// Library gains: view, key, folder_kind: 'watched' | 'crate' | 'library' | null, also: LibraryRow[] | null,
// read_at, enabled, service, empty adds 'gone'. Bridge: library(view="all", key=None, query="", filter="all",
// sort=None); set_favourites(keys) -> {favourites}; set_crate_shown(path, shown) -> {path, shown};
// watched_folders() rows gain crates: Crate[] and too_many (Settings' switches).
```

Rules the views pin: `place` as D11/D12; `wait` is `not_found` when the song is in To-do's not-found group (check
first: `_group(e) == "not_found"`), else `waiting`; a playlist view's `summary` and `chips` count its main rows with a
file; search filters main and `also` rows; folder rows by path prefix with a `/` boundary, NFC (`Old Sets 2` isn't in
`Old Sets`); `not_lossless/` directly under a Library folder is never a crate or a subfolder.

**I5. Routes.** Step A keeps today's routes. Step B (`router.ts`): `#/library` (all), `#/library/playlist/:name`,
`#/library/folder/:path` (the path encoded whole), `#/library/not-in-playlist`. `libraryTarget(params)`: a `folder`
param that is no path (doesn't start with `Library/` or `/`) is a playlist name (old links, the player's queue hrefs).
`libraryHref(target)`. Pins: spaces, `%`, `/`, `›`, NFD/NFC round-trip.

**I6. The shell's shared state** (`lib/stores/chrome.ts`, step A): `form` ('full' | 'rail', for the current page),
`browserShown`, `browserWidth`, `inspectorOpen`, `filterFocus` (a request the browser answers). The page sets
`inspectorOpen`; the shell derives `--sidebar-w` = form width + (browser shown ? 1 + width : 0) and sets it on the app
root, so the frame, the foot's line and the rule checker read one value.

**I7. Words (binding).**
- Rail and nav tooltips: `{Page} (⌘n)`; To-do adds ` · {n} to look at`; Sync while running ` · syncing, {i} of {n}`;
  Download limits with its dot names the reason (today's words). Fold button: `Hide sidebar (⌃⌘S)` / `Show sidebar
  (⌃⌘S)`. Rail hidden player: `{Artist} - {Title} · {list} · Show player` (the row's tooltip).
- Filter: placeholder `Filter playlists, folders`, the `⌘K` key cap, clear `Clear (Esc)`; hand-off row `Search tracks for
  "{text}"` with ↵, tooltip `Search every track's title and artist for "{text}" (All tracks)`. Track search unchanged
  (`Search title, artist…`, ⌘F). Sort toggle: `Order: download priority (change it on the Playlists page) · click for
  A–Z` / `Order: A–Z · click for download priority`. Column edge: `Drag to resize · double-click to reset`.
- Subtitles: All tracks `{n} tracks · every folder`; Not in a playlist `{n} tracks · in no playlist`; a playlist `{n}
  tracks · {Service} playlist[ · switched off] · Library › {folder}` (never read: `{Service} playlist · not read
  yet`); a Library folder `{n} tracks · no playlist uses it · Library › {name}`; a watched folder `{n} tracks · {k}
  folders with music · {place}`; a crate `{n} tracks · {tip}`; an away folder puts `Offline: connect the drive` /
  `Folder not found` second. `{place}` uses the watched-folder list's form (check first where Settings' rows get
  "~/…" / "Drive › …": engine or `watchedFoldersModel.ts`; the subtitle uses the same, from the same side).
- Strip (N5): `{p} % lossless`, `{l} of {c} checked tracks`; rows `Upgrade ready {n} ›`, `Not lossless yet · {all in
  To-do | {m} in To-do | none in To-do} {n} ›` (no link and no › at none; tooltip when fewer: `{m} of them in To-do:
  files of your own in no playlist aren't`). Inspector toggle `Show details (⌘I)` / `Hide details (⌘I)`; hidden by hand: the toggle's words `Show details`, tip
  `Hidden by you: selecting a track won't open them`; empty
  inspector `Select a track to see its details.`; a quality badge's tooltip `Show details`.
- Step B: playlist rows `{name}` ⏎ `{Service} playlist · {n} songs` (never read `· not read yet`; off adds ⏎
  `Switched off: its files stay, nothing new downloads`); folder rows their tip, away adds ⏎ `Offline: connect the
  drive` / `Folder not found`; Favourites' landing row `Drag a playlist or folder here`; the menu `Open · Play · Add to
  favourites / Remove from favourites · Hide from sidebar · Show in Finder` with the note `Settings brings it back`
  under Hide; the too-many row's link `Show some in the sidebar…`; Settings: `{n} folders with music, too many for the
  sidebar: switch on the ones you want to see`; table: `Waiting` (tooltip `Downloads at the next sync`), `NOT FOUND`
  (To-do's next-try line as tooltip), `in {place}`, section `Also in this folder` with hint `files in {folder} that
  aren't in this playlist`, badge `+{n}` tooltip `In {a}, {b}, {c}`; empty states `This playlist hasn't been read
  yet.` (action `Read playlists`), `This playlist is empty.`, `No music in this folder.`, gone `This playlist isn't in
  your list any more.` / `This folder isn't in your library any more.` (action `All tracks`); save failure toast
  `Couldn't save your favourites. Try again.` / `Couldn't save that. Try again.`

---

# Step A — Layout (`feat/library-5a-layout`)

Order: A1 → A2 → A3 → A4 → A5 → A6 → A7, one at a time. A1 first because it renames the shell's status slot that A4
rebuilds beside; A2's shapes feed A5 and A6; A3's blocks are used by A4–A6.

## A1 — Rename the read-status wire (Sonnet, ≈ 450 lines)

**Read list:** D13; `docs/issues.md` #26 first bullet; `grep -rn "spotify_status\|SpotifyStatus\|spotify-status\|\"spotify\"\|\.spotify\b" discjockey tests hub-ui/src hub-ui/scripts docs/hub-bridge-contract.md docs/hub-design-language.md`
(outline first, then each hit's lines); `SpotifyStatus.svelte`, `PageHeader.svelte` (props only).

Tasks: **A1.1** engine (`views.read_status`, the field in `api.job_status`, `views.dashboard`, `views.sync_preview`,
wherever built) and its tests; **A1.2** UI (`ReadStatus` type and component by `git mv`, users, `copy.ts`, stores,
fakes, gallery, `shots.json`, tests; `rules-page.js` rule 7 and `rules-fixtures/bad-spotify-status.html` →
`read-status`; `stores/shell.ts`' `SaidInBody.spotify` key); **A1.3** docs (contract, design-language doc, remove #26's
first bullet). Real Spotify uses stay.

Checks: `uv run pytest -q tests/test_hub_views.py tests/test_hub_api.py tests/test_hub_sync.py
tests/test_hub_api_setup.py tests/test_hub_api_playlists.py`; `cd hub-ui && npm run check && npx vitest run src/lib &&
npm run rules -- --self-test`; a final grep finds no old name. End: the full Python suite.

## A2 — Data for the layout (Sonnet, ≈ 350 lines)

**Read list:** I3, I7 (subtitles); `discjockey/hub/views.py` `sidebar`, `library` (summary part); `discjockey/hub/api.py`
`sidebar`, `library`, `_folders`; `playlists_file.Row`; `docs/hub-bridge-contract.md` (`sidebar()`, `library()`);
`hub-ui/src/lib/bridge/types.ts` (Sidebar, Library), `contract.ts`; the fake's `sidebar`/`library` (`bridge/fake/`);
the hub store's sidebar fetch.

Tasks: **A2.1** `views.sidebar` → I3 (playlists from every `playlists.txt` line with ref, service, on/off and today's
file count; `library_folders` for the rest); `api.sidebar` passes the lines. **A2.2** `views.library`: `subtitle`
(I7, step A's four views) and `summary.not_lossless`. **A2.3** contract, `types.ts`, `contract.ts`, fake (+ scenario
`library:browser`: 35 playlists over all five services, two switched off, one long name, two Library folders);
`Sidebar.svelte` keeps working on the new shape until A4 replaces it (adapt its reads only).

Checks: `uv run pytest -q tests/test_hub_views.py tests/test_hub_api.py`; `npm run check && npx vitest run
src/lib/bridge src/lib/stores`. End: the full Python suite.

## A3 — Blocks and house rules (Opus, ≈ 900 lines)

**Load `apple-design` and `emil-design-eng` first**, then `docs/hub-design-language.md` (§1, §2 colour, §5 motion, §6
block table, the decision log's sidebar and foot entries), the notes (N1–N15, the motion and signal tables).

**Read list:** D7, D16, I7; `lib/components/` `index.ts`, `PageHeader.svelte`, `ListSection.svelte`,
`SearchField.svelte`, `Button.svelte` (icon, pressed), `InfoTip.svelte` + `infoTipModel.ts` (its delay logic);
`lib/frames/ListPanelFrame.svelte`, `Panel.svelte`; `lib/styles/tokens.css`; `lib/dev/Gallery.svelte` (one section's
pattern); `pages/library/FolderOverview.svelte` (what the strip replaces).

Tasks (each block: gallery section, block-table row, decision-log entry):
1. **A3.1 `NavIcon`** (the mockup's `NAVI` paths: dashboard, sync, todo, playlists, limits, library, settings; 14 px,
   1.3 px stroke).
2. **A3.2 `ServiceMark`** + `serviceLogos.ts` (D7), `data-service-mark`, `aria-label` `{Service} playlist`.
3. **A3.3 `Tip`** (a hover tooltip action for icon-only and cut rows): fades and grows from scale(.97) at the trigger,
   `--t-pop`; the first waits 500 ms, the next open at once (share `infoTipModel`'s logic if it has it; check first).
4. **A3.4 `SummaryStrip`** (N5: share · bar · two link rows, 72 px; no legend) replacing `FolderOverview`'s card.
5. **A3.5 `PageHeader` subtitle parts** (N14: parts drop whole, path first, CSS only, whole subtitle as tooltip; the
   title ends in "…" only alone).
6. **A3.6 `ListSection`**: stuck heads opaque, square, hairline on the open edge (N15); scrolled-to rows stop whole
   below them.
7. **A3.7 `ListPanelFrame` inspector mode** (D16.3): `panel: 'docked' | 'inspector'`, `open`; inspector slides from the
   window's right edge (240 ms in, 200 ms out, drawer curve; reduced motion: fade); the list takes its final width at
   once; same widths and `data-panel` as the docked panel. `SearchField` gains `shortcut: 'cmd+k'` (key cap only; the
   key itself is D18's handler).
8. **A3.8 Tokens and the doc:** chrome widths (`--rail-w: 50px`, `--browser-w-min/-default/-max`), the rail's count
   pill colour as a token; D16's rule changes and the colour exception in `docs/hub-design-language.md`.

Improve what the shots show (§12) and show the orchestrator before/after shots for any change to the approved design.
Checks: `npm run check`, touched `*.test.ts`, `npm run rules -- --page base --only base-gallery`. End: `npm run build`.

## A4 — The chrome: two forms, memory, motion, keys (Opus, ≈ 800 lines)

**Load the skills first**, then the notes N1, N2, N7, N8, N9, N11, N12, motion and keyboard tables; D17, D18, I6.

**Read list:** `App.svelte` (frame, keys), `lib/shell/Sidebar.svelte`, `NowPlayingRow.svelte`, `Foot.svelte` (the
`--sidebar-w` uses only), `footModel.ts` (`playerKey`, `keyTarget`); `lib/router.ts`; `lib/prefs.ts`;
`lib/stores/hub.ts` (sidebar), `shell.ts`; pywebview's menu API (D18's check).

Tasks:
1. **A4.1 `stores/chrome.ts` + test** (I6, D17): forms per place, the step-back below 1240, the width clamp, `--sidebar-w`.
2. **A4.2 `keys.ts` + test** (D18): ⌘1–6, ⌘, (Settings), ⌘K (Library + filter focus; at < 1240 closes the inspector),
   ⌘I (only on Library), ⌃⌘S (fold the current place's form); none in a dialog; `playerKey` untouched.
3. **A4.3 The sidebar's two forms** (`Sidebar.svelte`): the fold button and brand head (N1: no icon moves; the update
   line folds with the brand), `NavIcon`s, Library as a nav item (♫, `data-test="nav-library"`), Settings; the rail's
   signals (N11: To-do count pill, Download limits' dot as today's `limits_warning`, the sync ring with `Ring`);
   rail tooltips (`Tip`); the hairline beside the browser (D16.2). The old Library group goes.
4. **A4.4 The hidden player's rail form** (`NowPlayingRow` `rail`): ⌃ Show player (`Button icon xs`), `PlayButton`
   22, the 2 px position line under it; the full form unchanged (part 1's mockup is the target).
5. **A4.5 Motion** (N motion table): fold 220 ms drawer curve, labels fade out 90 ms / in 120 ms after 100 ms; into
   Library 220 ms with the browser's rows fading in over the last 150 ms from 8 px; out quicker; the page lays out at
   once (`--sidebar-w` changes at once, only the chrome's edge glides over it); interruptible CSS transitions; reduced
   motion cross-fades. Page switches never animate the chrome except into or out of Library.

Checks: `npm run check`, `npx vitest run src/lib/stores src/lib/shell`, `npm run rules -- --page base`. End: `npm run build`.

## A5 — The browser column (Opus, ≈ 900 lines)

**Load the skills first**, then N2–N4, N9, N10, N13, N15, D4, I7.

**Read list:** A4's `stores/chrome.ts` and `Sidebar.svelte` (where the column mounts); `lib/stores/hub.ts`;
`lib/router.ts` (`libraryHref`, current route); A3's `ServiceMark`, `Tip`, `ListSection`, `SearchField`;
`lib/components/StatusMark.svelte` (props).

Tasks:
1. **A5.1 `browserModel.ts` + test** (pure): the rows from `Sidebar` (views, Playlists in order or A–Z, Folders), the
   filter (case-folded substring on names; folded sections open; each match once; the one highlighted row = the first
   match; ↑ ↓ moving down to the hand-off row; the hand-off row whenever there's text, alone with the highlight when
   nothing matches), the current row for a route, tooltips (I7).
2. **A5.2 `BrowserColumn.svelte`** in the shell: the filter field at the top (centred on the page header's row), the
   rows (one line, the count column, `ServiceMark`, switched-off dim), section heads that fold and stick (A3.6), the
   Playlists head's count and A–Z toggle (`Button icon xs pressed`); Enter opens, Esc clears and leaves; the hand-off
   opens All tracks with the text in its track search (check first how the Library page takes a search from the
   route: add a `q` query if it has none). Opening a collection scrolls its row into view (whole, below a stuck head).
3. **A5.3 The drag edge** (N4): the page's edge line as a 9 px grip, resize cursor, orange 2 px line while dragging,
   1:1 with no easing (pointer capture), 200–360, double-click → 240 (220 ms drawer curve), remembered.

Shots (fake `library:browser`): `library-browser` (`#/library`), `library-filter` (fill "bou"), `library-filter-none`
(fill "kaltf"), `library-browser-wide` (`prefs` width 320), `library-browser-1100`.
Checks: `npm run check`, the model test, `npm run rules -- --page library --only <the shots>`. End: `npm run build`.

## A6 — The Library page: inspector, strip, header, columns (Opus, ≈ 800 lines)

**Load the skills first**, then N5–N7, N14, the widths table, D10 (step A part: today's views), I7.

**Read list:** `pages/library/` (Page, LibraryTable, TrackDetails, FolderOverview, libraryModel + test, shots.json);
A3's `SummaryStrip`, `PageHeader`, `ListPanelFrame` inspector mode; `stores/chrome.ts`.

Tasks:
1. **A6.1 `libraryModel.ts` + test:** column sets per view kind and their thresholds (D10, today's three views; a
   playlist folder counts as "a playlist"); the strip's numbers from `summary`; subtitle parts from `Library.subtitle`.
2. **A6.2 Page:** `ListPanelFrame` in inspector mode; the details toggle (`Button icon pressed`, I7 words) and ⌘I;
   the inspector follows the selection, empty words without one; double-click or Enter plays (unchanged); the strip
   between header and filter segments, its rows linking to the Upgrade ready segment and To-do. **When the details
   show (changed after the step A live check, the user's wish):** picking a track (a click, ↑ ↓) opens them, unless
   the user hid them by hand; hiding by hand is the toggle or ⌘I while they show, and it sticks (`library.details.hidden`,
   remembered across pages and restarts) until the user opens them by hand (the toggle, ⌘I, a quality badge, the
   menu's Show details), after which picks open them again. ⌘K / ♫ below 1240 px close them for the browser without a
   hide by hand. Arriving with `?track=` (♫, ⌘6, the foot's link) is no pick and keeps the remembered state; a
   right-click selects without opening (the menu is what it asks for). Hidden by hand, the toggle says so: `Button
   switchedOff` (words `Show details` before the glyph, which keeps its place; a dashed outline, the house shape for
   switched off; the glyph struck through), neutral because red means weak quality or a problem and orange means on.
   The rules are pure (`detailsAfter` in `stores/chrome.ts`, tested).
3. **A6.3 Table:** the columns by container width (D10), Length added, Source and Added gone, the "–" cells; the
   filter segments keep whole labels in every state.

Shots: `library-inspector` (an upgrade-ready row selected, inspector open), `library-inspector-1100` (the browser
stepped back), `library-playing-sync` (1100, a track playing, `syncing` scenario: the foot's line starts at the page's
edge), existing `library-*` shots updated where a panel step became a toggle; `library-pick-opens`,
`library-details-hidden`, `library-details-hidden-1100` (the hidden-by-hand toggle).
Checks: as A5 on these shots. End: `npm run build`.

## A7 — Shots, checker, docs (Sonnet, ≈ 350 lines)

**Read list:** D19, D20; `hub-ui/scripts/shot-lib.mjs`, `shots.mjs` (compare), `rules-page.js`, `rules.mjs`
(self-test), `rules-fixtures/` (names); every `shots.json` (`grep -n "sidebar\|nav-\|side-"`); `README.md` (Library
section, keys).

Tasks: **A7.1** `prefs` and `mockupState`/`mockupScale` shot keys (D19), documented in `shot-lib.mjs`' header;
`mockup`/`mockupState` on the A5/A6 shots that have a mockup state. **A7.2** the `chrome-edge` rule + fixtures
(`good--rail.html`, `bad-chrome-edge.html`). **A7.3** shots: `base-shell-folded` (Dashboard, `prefs` other form rail,
a hidden player), any shot whose steps clicked the old Library group switched to the browser. **A7.4** README: the
layout, the forms, the keys; `docs/issues.md`: add what the groups reported (#28 was removed with this plan, D20).

Checks: `npm run rules -- --self-test`; `node scripts/shots.mjs --page library --only library-browser --compare`.

## Step A checks

- **Python:** the full suite once per group; CI on the branch push.
- **UI:** `npm run verify` once, by the orchestrator, in the background, before the merge. Shots looked at by the
  orchestrator at the three sizes: every A5/A6 shot, `base-gallery-*` of the new blocks, `base-gallery-foot` (the foot
  unchanged), `base-shell-folded`, and one shot of every other page (full sidebar, drawn icons, nothing moved). Library
  at 1280 shows Track, Artist, Folder/Subfolder, Playlist, Length, Quality; at 1100 today's 1280 set; with the
  inspector never less than Track, Artist, Subfolder, Quality (N6).
- **Opus stage-step review** of the branch against N1–N15, D4, D10, D16–D19.
- **Live check by the user, about 10 minutes, nothing downloads.** 1. Open Library. *They see* the rail, the column with
  their playlists and logos, the table with Length. *They judge* the fold (⌃⌘S, the button) and the slide into and out
  of Library: smooth, nothing jumping. 2. Drag the column's edge wider and back; double-click it. 3. ⌘K, type part of
  a playlist name, Enter; then type a track name and take the "Search tracks for …" row. 4. Click a track (its
  details open), ⌘I to hide them: the button reads "Show details"; click other tracks (they only select; still
  hidden after leaving Library and coming back); click a quality badge or ⌘I (details back, clicks open them again). 5. Make the window as small as it goes: the list stays
  usable; open details: the column steps back; ⌘K brings it back. 6. Play a track, hide the player: the rail's play
  button. *They report* anything that feels slow, cramped or unclear.

---

# Step B — Folders and records (`feat/library-5b-folders`)

Order: B1 → B2 → B3 → B4 → B5 → B6 → B7 → B8. B2 and B3 need B1's tables; B4 copies B2/B3's shapes; B5–B7 need B4.

## B1 — Records, Favourites and crate tables (Opus, ≈ 750 lines)

**Read list:** D1, D2, D15, I1, I2; `discjockey/db.py` (docstring, `SCHEMA_V3_STEP`, `_upgrade`, `check`, `connect`,
`transaction`, `snapshot`, `import_counts`); `discjockey/run.py` (`grep -n "^def "`, then `prepare` and where it
fetches); `discjockey/sources/__init__.py` (`read`); `models.py` (`FetchedPlaylist`, `SourceTrack`);
`playlists_file.py` (`Row`, `load`); `hub/jobs.py` (`PreviewStore`); `tests/test_db*.py` (`grep -n "def test_"`).

Tasks: **B1.1** the schema step and its pins; **B1.2** `record_reads`, `playlist_records` and their pins; **B1.3**
`favourites`, `set_favourites`, `crate_overrides`, `set_crate_shown` and their pins (no generation bump; a held write
transaction makes them wait, then fail cleanly); **B1.4** record after a read (D1) with tests in `tests/test_run.py`
(records; unreadable keeps; a failing record doesn't fail the read; the dry run as D1) and one hub test that a preview
read records.

Checks: `uv run pytest -q tests/test_db.py tests/test_db_migrate.py tests/test_run.py tests/test_hub_jobs.py` (check
first: the exact file names). End: the full Python suite.

## B2 — Views: the sidebar, crates, the two brief writes (Sonnet, ≈ 650 lines)

**Read list:** D3, D5, D8, D15, I4 (Sidebar, Crate, WatchedEntry, Favourite), I7; `hub/views.py` `sidebar`,
`watched_folders`, `fold`; `hub/api.py` `sidebar`, `watched_folders`, `_away_folders`, `setup_skip_import` (the brief
write's pattern), `_move_log`; `tests/test_hub_views.py`, `tests/test_hub_api.py` (`grep -n "def test_"`).

Tasks: **B2.1** `views.crates(files, watched, overrides)` (pure, D8) with tests: wrappers skipped; a crate in a crate;
same-name crates in two folders and in one; labels unchanged by hiding; >25 → too many, all hidden unless switched on;
files in the root belong to no crate; counts at or below. **B2.2** `views.sidebar` → I4 (playlists' songs from records,
unread `null`; favourites resolved, gone keys left out; library folders by path). **B2.3** `api.set_favourites`,
`api.set_crate_shown` (D15: brief, no job, no engine lock; busy answer) and `watched_folders()`'s crates. **B2.4**
check which events the hub sends after a finished read, a drive change and a finished import; add one only where none
says it, and name them for B4.

Checks: `uv run pytest -q tests/test_hub_views.py tests/test_hub_api.py tests/test_hub_jobs.py`. End: the full suite.
Past 800 lines stop and report.

## B3 — Views: the playlist and folder views (Sonnet, ≈ 650 lines)

**Read list:** D3, D6, D9–D12, I4 (LibraryRow, Library), I7; `hub/views.py` lines of `track_row`, `file_state`,
`track_detail`, `SORTS`, `library`, `_group`; `hub/api.py` `library`, `track`; B2's `crates`.

Tasks: **B3.1** the playlist view (D9: resolution through keys and aliases, duplicates once, `wait`, `place`, `also`,
`read_at`, `enabled`, chips and summary, sort `order`). **B3.2** folder views (`folder_kind`, rows by path prefix,
`subfolder` per D8/I4, `playlists` in `lines` order; a deeper route still has its view). **B3.3** `track().place`,
All tracks' / Not in a playlist's `place` (D12, crate labels); `api.library`'s new signature, `gone`; `subtitle` for
the new views (I7). Tests for each rule of I4's list, plus: a file outside its song's folder; an own file; a folder of
own files in no playlist (`not_lossless` 2, To-do 0).

Checks: as B2. End: the full suite. Past 800 lines stop and report.

## B4 — Contract, types and the fake (Sonnet, ≈ 700 lines)

**Read list:** I4, I5, I7; B2/B3's commits (`git show --stat`, then the views' docstrings); the contract's
`sidebar()`, `library()`, `track()`, `watched_folders()`; `types.ts`, `contract.ts`; `bridge/fake/` (`bridge.ts`,
`data.ts`, `folders.ts` outline); `pages/library/fake.ts`; `stores/hub.ts`.

Tasks: **B4.1** contract (with D15's exception and its reason), `types.ts`, `contract.ts`. **B4.2** the fake: records,
crates, favourites and overrides with the same rules; scenarios `library:crates` (the mockup's data: Rekordbox Library
with Bounce twice, Hardtechno › 2019, Edits hidden; Albums with 312 album folders; Vinyl Rips offline; Old_Hardstyle;
four favourites in the mockup's order Hard_Bounce, Hardtechno, Peak Time, Bounce · Old Sets), `library:first_look`
(no favourites), `library:never_read`; the fake's `set_favourites` can be told to answer busy. **B4.3** the store
re-fetches `sidebar()` after the events B2.4 named, and after its own brief writes.

Checks: `npm run check && npx vitest run src/lib/bridge src/lib/stores`.

## B5 — Browser: Favourites, crates, the menu (Opus, ≈ 900 lines)

**Load the skills first**, then N2, N9, N10, N13, B "Decisions" (crates, hiding, favourites), D4, D8, D15, I7.

**Read list:** A5's `browserModel.ts` + `BrowserColumn.svelte`, A4's `Sidebar.svelte`; `lib/stores/drag.ts`;
`lib/components/ContextMenu.svelte` (props); `StatusMark` (props); the player store's queue entry point (check first
how Library builds a queue, for the menu's Play); `api.reveal` (check first whether it takes an import folder's path).

Tasks:
1. **B5.1 Model:** Favourites (the section; while filtering it steps aside, N9), watched folders with crates (hidden and
   too-many rules, chevrons fold a watched folder, offline "!"), the filter finding hidden crates and every album with
   their watched folder as context (never the highlighted row), the current row (a favourite's pill on its topmost row).
2. **B5.2 Favourites UI:** the drag (lift 120 ms, rows part 200 ms ease-out, drop spring damping 1 / response 0.3),
   only inside Favourites; dragging a row from Playlists or Folders into it adds it; the empty section's dashed landing
   row; optimistic order, put back with the toast on a busy answer. The full sidebar on other pages lists Favourites
   (no counts; a click opens Library at it).
3. **B5.3 The menu:** right-click on a row (I7 items; Hide only on crates; Show in Finder only where a folder exists);
   the row it acts on gets the orange ring.

Shots: `library-favourites`, `library-first-look` (rightclick a crate), `library-crates` (Rekordbox Library open),
`library-filter-crates` ("bou"), `base-shell-favourites` (Dashboard).
Checks: `npm run check`, the model test, `npm run rules` on these shots. End: `npm run build`.

## B6 — The playlist and folder views (Opus, ≈ 900 lines)

**Load the skills first**, then the design-language doc (`ListRow`, `ListSection`, `AwayTag`, `MiddleText`, `Badge`,
`TrackHead`), D6, D9–D12, I4, I7.

**Read list:** `pages/library/` (Page, LibraryTable, TrackDetails, libraryModel + test, shots.json);
`MiddleText.svelte`, `fitPathAction.ts`, `format.ts` (`fitMiddle`) and its test.

Tasks: **B6.1** `libraryModel.ts` + test: the view kinds, column sets (D10), default sorts and a saved sort per view
kind, `playable` false for `no_file`, `rowDim`, the badge text and tooltip, the location note. **B6.2** table: `#`,
the note, `Waiting` / `NOT FOUND` and the dashed cover, `MiddleText` `sep` (whole folders first; block table row,
decision log), the Playlist badge (if `Badge` has no neutral tone that keeps the user's case, stop and report), the
`Also in this folder` section. **B6.3** page and inspector: subtitles, empty states, the no-file row's inspector
(`TrackHead` with `Artist · length · not downloaded yet`, a `NoteCard`, `Open in to-do` for not found), `TrackHead`'s
place (D11); the too-many watched folder's page carries the link `Show some in the sidebar…` (to Settings' folder).

Shots: `library-playlist`, `library-playlist-away-selected`, `library-playlist-waiting-selected`,
`library-playlist-off`, `library-playlist-never-read`, `library-folder-crate` (Hardtechno: Subfolder "2019"),
`library-folder-too-many` (Albums), `library-folder-offline` (Vinyl Rips), `library-folder-library` (Old_Hardstyle).
Checks: as B5. End: `npm run build`.

## B7 — Settings: crate switches (Opus, ≈ 400 lines)

**Load the skills first**, then `library-browser.html` states `#settings` and `#settings-many`, D8, D15.

**Read list:** `pages/settings/` (the Watched folders section), `WatchedFolderList.svelte`, `watchedFoldersModel.ts`,
`Switch.svelte`/`ToggleRow.svelte` (props).

Tasks: each watched folder's crates as switch rows (label, count), the too-many message, a switch writes
`set_crate_shown` (optimistic, put back on busy); the route the `Show some in the sidebar…` link opens lands on that
folder. Shots `settings-folders-crates`, `settings-folders-too-many`.

## B8 — Docs (Sonnet, ≈ 150 lines)

README: Favourites, crates and hiding, a playlist's view (the note, Waiting/Not found, Also in this folder), a folder's
view; the trademarks line (Spotify, Qobuz, SoundCloud and YouTube names and logos are trademarks of their owners, used
only to show where a playlist comes from; Discjockey isn't affiliated with them); `CLAUDE.md`'s `db.py` row names the
read records, Favourites and crate visibility; the design-language doc's Favourites part (D16.4); `docs/issues.md`:
leftovers the groups reported. Checks: `uv run pytest -q tests/test_docs_citations.py tests/test_docs_links.py`;
`scripts/check_public.sh`.

## Step B checks

- **Python:** the full suite once per group; CI on the branch push. Pins the review looks for: no generation bump from
  the new tables; the I4 rules; counts in the browser against the views' rows.
- **UI:** `npm run verify` once before the merge; shots looked at: every B5/B6/B7 shot, `library-all`,
  `library-not-in-playlist`, `library-ejected` (Folder column and middle cut), one shot of every other page (Favourites
  in the full sidebar). `--compare` against `library-layout.html` states `favourites`, `first-look`, `dashboard`.
- **Before the user's check, by the orchestrator:** a scratch run (`DISCJOCKEY_SUPPORT=<scratch> bin/discjockey hub`)
  with a scratch music folder, an import folder of generated tones with a wrapper level and two crates (one inside the
  other), and a `playlists.txt` whose read comes from the test fixtures' recorded responses (no Spotify or Qobuz call).
  Open, pin two favourites, quit, open again: counts and favourites are there before any read.
- **Opus stage review** of the whole stage against the spec's §11 and this plan.
- **Live check by the user, about 10 minutes, nothing downloads.** 1. Open Library on their own library. *They see*
  their watched folders with the folders that hold music (no wrapper levels), names they recognise. 2. Right-click a
  crate → Add to favourites; drag it to the top of Favourites; go to To-do: it's in the sidebar there. 3. Hide a crate,
  bring it back in Settings. 4. Open a playlist whose songs sit in other folders: "in …" notes, Also in this folder.
  5. Quit, turn off Wi-Fi, open again: the same playlists, counts and favourites. *They report* anything that reads
  unclearly, and whether the folder names match how they think of their crates.

## Sizes

Step A: A1 ≈ 450 (Sonnet), A2 ≈ 350 (Sonnet), A3 ≈ 900 (Opus), A4 ≈ 800 (Opus), A5 ≈ 900 (Opus), A6 ≈ 800 (Opus),
A7 ≈ 350 (Sonnet). Step B: B1 ≈ 750 (Opus), B2 ≈ 650 (Sonnet), B3 ≈ 650 (Sonnet), B4 ≈ 700 (Sonnet), B5 ≈ 900 (Opus),
B6 ≈ 900 (Opus), B7 ≈ 400 (Opus), B8 ≈ 150 (Sonnet). Changed lines with tests. Agent budgets as the orchestration
rules §4 (an Opus UI group up to about 150k tokens, a Sonnet group 40–100k).
