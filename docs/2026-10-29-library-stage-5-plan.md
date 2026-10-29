# Library stage 5 "Sidebar" — plan

Spec: `docs/2026-10-23-library-and-sources-design.md` §11, with §2 (terms), §3 item 4, §6.4 (offline), §13 ("UI").
Leftovers: `docs/issues.md` #26 (first bullet: the read-status wire). Orchestration:
`docs/2026-10-23-library-and-sources-orchestration.md`. Mockup: `docs/hub-mockups/design-system/library-sidebar.html`
(states `#sidebar`, `#playlist`, `#folder`; the user approves it before Groups 4 and 5 start). Builds on `main` 5e6d172;
branch `feat/library-5-sidebar`.

**Goal:** under "Library" the sidebar lists All tracks, the playlists (a service mark and a song count each), the
folders on disk as a tree (import folders and the `Library/` folders no playlist uses) and Not in a playlist. A
playlist opens its songs wherever their files are; a folder opens the files physically in it.

**Architecture.** Today the Library knows only a song's *placement* folder (`songs.folder`), and which songs a playlist
holds lives only in the hub's last read (`PreviewStore.prep`, session memory). Stage 5 needs both answers before and
without a read (a gig without Wi-Fi, a switched-off playlist that is never read), so each successful read of a playlist
is recorded in `library.db` (schema step 3 → 4, two tables outside the snapshot). Everything the sidebar and the views
show is computed in `views.py` (pure) from the snapshot, those records, `playlists.txt` and the watched folders: a
playlist view resolves its recorded tracks to songs; a folder view groups files by their **path**, not their song's
folder. The UI adds one block (`ServiceMark`), rebuilds the sidebar's Library group from a pure `sidebarModel.ts`, and
extends the Library page with two view kinds. The Spotify-named read-status wire is renamed first, on its own.

---

## Global constraints

- **Nothing here moves, renames or writes a music file.** The stage reads; its only writes are the read records (D1).
- **`views.py` and `planner.py` stay pure; only `db.py` writes SQL.** The read records never enter the snapshot and
  never bump `generation` (stage 4 I2): a read that lands while an import runs must not make the import's snapshot
  stale.
- **Every visual signal has exactly one meaning** (D6). No row, mark or grey may fall under another rule by accident
  (stage 4 fix G: own files were greyed as "not in a playlist"). Reviews check each signal against D6.
- **Seamless chrome:** the Library group is rows of the sidebar like Dashboard or Sync: the same height, glyph slot,
  pill and count column. Nothing floats, nothing reserves a strip. Structured controls only.
- **Names** in rows are the user's own (folder names, playlist names, "Artist - Title" files); never rewritten.
- **Contract rule:** an api/views shape change updates `docs/hub-bridge-contract.md`, `types.ts`, `contract.ts` and the
  fake backend in the same commit. **Design rule:** a new block updates `docs/hub-design-language.md` and the gallery in
  the same commit.
- **Tests offline**, `tmp_path` libraries, made-up names (`Example Artist`, `/Volumes/Example Drive/DJ Sets`,
  `/Users/you/Music/Old Sets`). **Public repo:** `scripts/check_public.sh` before every commit.

## Decided here (with reasons)

- **D1. Read records in `library.db`.** After each successful read of a playlist, its tracks (order, token, artist,
  title, length) and the read's time replace that playlist's earlier record; records of playlists no longer in
  `playlists.txt` (on or off) are dropped. *Why:* the sidebar's song counts and a playlist's view must be there when the
  window opens, offline, and for switched-off playlists, which the sync no longer reads; the hub's preview is gone after a
  restart. One place for both front ends: wherever the fetch result first exists with the database at hand (check first:
  `run.prepare` or its caller; the console's sync and dry run and the hub's read all pass through it). A dry run records
  too: it changes no music file and no library state (check first that its connection is writable; if it isn't, skip it
  there and say so in the report). Recording is outside the library lock (a read never takes it) and is best-effort: a
  locked or failing write is logged, the read still succeeds, the next read records again.
- **D2. A record keeps the fetched token plus display facts,** resolved to songs at view time (through each entry's
  key and `aliases`). *Why:* a song the sync hasn't downloaded yet has no song row, but its playlist still shows it
  ("Waiting"); a later relink adds an alias and the record still resolves.
- **D3. A playlist is named by its folder name** (the line's left side), as the sidebar and Playlists page do today;
  the record is keyed by the line's ref (the link's token), so a folder rename keeps the record. A folder is named by its
  **snapshot path** (`Library/Old_Hardstyle`, or the absolute path in an import folder), which is also its route key.
- **D4. The Library group, in this order:** All tracks · the playlists in `playlists.txt` order (switched-off ones in
  place, dimmed) · the folders (import folders' roots, by name, then the `Library/` folders no line uses, by name; each
  root followed by its open subfolders) · Not in a playlist. A 10 px pause (6 px + the row gaps) between the four
  parts; no extra captions. *Why:* icons and the pause already separate them; captions cost two rows of a sidebar that
  scrolls at 1100 × 700. The views (All tracks, Not in a playlist) keep no glyph and start at the row's inset as today:
  they come from no source, and "Not in a playlist" needs the width (measured in the mockup: with a blank glyph slot it
  read "Not in a pla…").
- **D5. Counts.** Playlist: the songs its view lists (distinct songs of its last record; `null` = never read → no
  number). Folder: files with a song at or below it. All tracks and Not in a playlist: files, as today. An offline
  folder keeps its count (its files are still in the library, §6.4).
- **D6. The signals (binding; the mockup's table is the same):**

  | Where | Signal | Means only |
  |---|---|---|
  | Sidebar | whole row at `.5` (today's `.dimmed`) | a switched-off playlist. The sidebar's only dim. |
  | Sidebar | `StatusMark warn` "!" in a folder's glyph slot, name and count at full strength | the folder's drive isn't connected or the folder isn't found (the same "!" as Settings → Watched folders and `AwayTag`) |
  | Sidebar | `ServiceMark` (letter in a ring) | which service the playlist is read from |
  | Sidebar | folder outline | a folder on disk (a root; subfolders have no glyph) |
  | Rows | lead dimmed (`rowOff`) | a downloaded song that left every playlist (unchanged; own files never) |
  | Rows | lead dimmed + `AwayTag` in the quality column | the file is away (unchanged) |
  | Rows | lead dimmed + "Waiting" (muted words) or the red `NOT FOUND` badge in the quality column, dashed empty cover | a playlist song with no file |
  | Rows | "in Techno 2019" after the title, `--text-label` | the file sits outside the playlist's own folder |
  | Rows | neutral `Badge` with a playlist's name (+n) | the playlists that hold the song (folder view) |

  "Waiting" gets no colour: yellow in the quality column reads as good lossy, and nothing is wrong.
- **D7. `ServiceMark`: a capital letter in a 14 px ring, monochrome, the glyphs' grey** (S Spotify, Q Qobuz). *Why:* the
  spec asks for marks that name the service without brand art; a letter needs no learning and breaks no colour job.
  Stage 6 adds SoundCloud and YouTube Music in the same form with letters that don't collide (its plan picks them).
- **D8. The tree.** Children are subfolders holding at least one file with a song at or below them. Directly under a
  `Library/` folder, `not_lossless/` is never a node (Discjockey's own place for lossy files; its files count to the
  folder and show "not_lossless" in the Subfolder column). A subfolder row has no glyph: its name starts under its
  parent's name, 12 px further per extra level. A folder with subfolders has a chevron in a 10 px column right before
  the count; the folders' count column is as wide as their widest count (tabular digits), so the chevrons stand in one
  column and no width is reserved on rows without one. Choosing a folder opens it as well; the chevron toggles without
  navigating; the folder of the current route and its ancestors are always open. Open folders are remembered per path
  (`getPref`/`setPref`, key `sidebar.open`). *Why:* aligned icons, counts and chevrons at 168 px (the mockup's first
  try with a chevron after the name and glyphs on subfolders cut "Techno 2019" to "Techn…"); clicking a folder is
  enough to discover what is inside.
- **D9. A playlist's view:** its songs in playlist order (a `#` column, the view's default sort `order`), a song listed
  twice in the playlist shown once (first place), then the section **Also in this folder**: files physically in
  `Library/<its folder>/` (including `not_lossless/`) whose song the playlist doesn't hold. One table, the section as a
  `ListSection`. The location note gives way before the title (it shrinks to nothing first). *Why:* a DJ reads a
  playlist in its order; one table keeps one column grid.
- **D10. A folder's view:** the files whose path is in the folder or below; optional columns Subfolder (first, the
  default sort, `MiddleText`: the end of a path tells two apart), then Playlist, then Source, Added. Both Subfolder and
  Playlist show at 1280 × 800; Subfolder at 1100 × 700. The folder view's Length column is optional too and is the
  first to go: it is hidden at 1280 × 800, so titles and subfolder paths fit (orchestrator's mockup check).
- **D11. The panel head says where the file sits.** `track()` gains `place` (the physical folder, as the location note
  words it) and `TrackHead`'s place line shows it. *Why:* under option A a file can sit outside its song's folder; the
  row would say "in Techno 2019" and the head "Hard_Bounce". Fix I's intent ("the head says only where the file
  sits") is kept, now true; record it in the decision log.
- **D12. All tracks' and Not in a playlist's Folder column says where the file sits** (as `place`, D11): the
  playlist folder's name, or the import folder's path with " › " between levels ("Old Sets › Warmups"). It no longer
  names the song's folder, and own files no longer read "Not in a playlist" there. *Why:* after this stage a folder
  view shows the file in Old Sets › Warmups, so a Folder column saying "Bouncy" for the same file would be false, and
  "Not in a playlist" isn't a folder. Being in no playlist stays told by the dim and its tooltip (`rowTitleTip`), as
  before. The column's end gets cut (title tooltip = the full place). Found in the orchestrator's mockup check.
- **D13. The read-status wire is renamed** (issue #26): field `spotify` → `read_status`, `views.spotify_status` →
  `views.read_status`, type `SpotifyStatus` → `ReadStatus`, component `SpotifyStatus.svelte` → `ReadStatus.svelte`, the
  `PageHeader` slot's prop and docs words "Spotify slot" → "read-status slot". Real Spotify things (its login, Setup's
  Spotify step, `service: "spotify"`) keep their names. A pure rename: no behaviour or words change.
- **D14. Not in this stage:** issue #27's To-do `AwayTag` (To-do rows have no quality column, so it needs its own look,
  and this stage doesn't touch To-do; it stays in #27).

## Review focus (per group and the stage review)

1. Each signal in the shots means exactly D6's row; no dim, grey or colour has a second meaning.
2. Read records never bump `generation`, never enter `snapshot`, and a failed record never fails a read.
3. `views.py` pure; no SQL outside `db.py`; counts in the sidebar equal the rows of the view they open.
4. Seamless chrome and alignment at 1100, 1280 and 2560: icons, names, chevrons and counts in their columns.
5. Old routes (`#/library/folder/Hard_Bounce`) still open the playlist (I4).

---

## Interfaces (fixed here; groups build against them)

**I1. Schema step 3 → 4** (`SCHEMA_VERSION = 4`, through `db._upgrade` like stage 4's step):

```sql
CREATE TABLE playlist_reads (playlist TEXT PRIMARY KEY, service TEXT NOT NULL, read_at TEXT NOT NULL);
CREATE TABLE playlist_tracks (playlist TEXT NOT NULL REFERENCES playlist_reads (playlist) ON DELETE CASCADE,
  position INTEGER NOT NULL, token TEXT NOT NULL, artist TEXT NOT NULL, title TEXT NOT NULL, duration_ms INTEGER,
  PRIMARY KEY (playlist, position));
```

`playlist` is the line's ref (check first: that a `FetchedPlaylist` carries the same token as `playlists_file.Row.ref`).

**I2. `db.py`:**
- `record_reads(conn, reads: Sequence[FetchedPlaylist], now: datetime, keep: Collection[str]) -> None`: one
  transaction; replaces the rows of each read that has tracks (an unreadable playlist keeps its old record); deletes
  playlists not in `keep` (every ref in `playlists.txt`, on or off). No generation bump.
- `playlist_records(conn) -> dict[str, PlaylistRecord]`; `PlaylistRecord(service, read_at, tracks: list[RecordedTrack])`,
  `RecordedTrack(position, token, artist, title, duration_ms)` (NamedTuples beside `ImportCounts`).
- Pins: v3 → v4 keeps every row; a v4 library refuses a stage-4 build (`NEWER`); `record_reads` replaces, keeps an
  unreadable one, prunes, and leaves `generation` unchanged; a second connection holding a write transaction makes it
  wait (check first: `connect`'s busy timeout), then the caller's best-effort catch.

**I3. Views (pure) and the bridge.** `views.sidebar(state, lines, records, watched, away, todo_count, warnings)`
(`lines`: every `playlists.txt` row as `(name, ref, service, enabled)`; `watched`: `(path, kind)` per watched folder;
`away`: as `library()` gets it). `views.library(state, view, key, query, filt, sort, records, lines, cover, away)`.
`api.library(view="all", key=None, query="", filter="all", sort=None)`; `sort=None` is the view's default
(`order` / `subfolder` / `artist`). New sort keys `order` and `subfolder`; rows without a file sort after every
other row by quality. `track()` gains `place` (D11).

```ts
export type Sidebar = {
  todo: number; all_tracks: number; not_in_playlist: number; limits_warning: boolean;
  playlists: { name: string; service: PlaylistService | null; enabled: boolean; songs: number | null }[];
  folders: SidebarFolder[];   // display order: each parent before its children
};
export type SidebarFolder = { path: string; name: string; kind: 'import' | 'library'; depth: number;
  parent: string | null; has_children: boolean; files: number; state: 'here' | 'offline' | 'folder_missing' };
export type LibraryView = 'all' | 'playlist' | 'folder' | 'unlisted';
export type LibraryRow = TrackRow & {
  sound_checked: boolean;
  file_state: FileState | 'no_file';   // no_file: a playlist song without a file (playlist view only)
  wait: 'waiting' | 'not_found' | null; // with no_file; track_id is then the song's key, else the recorded token
  position: number | null;              // playlist view, main rows: 1-based place
  place: string | null;                 // playlist view: the file's folder when it isn't the playlist's own
  subfolder: string | null;             // folder view: the path below the folder, '' = the folder itself
  playlists: string[];                  // names of the playlists holding the song, playlists.txt order
};
// Library gains: view, key, also: LibraryRow[] | null (playlist view), read_at: string | null (playlist view),
// enabled: boolean | null (playlist view), service: PlaylistService | null, empty adds 'gone' (an unknown name or path)
```

Rules the views pin: `place` is the file's first folder under `Library/` (Library files) or its parent folder's name
(import files), `null` inside the playlist's own folder or its `not_lossless/` (fold-equal names, as `sidebar` folds
today); `wait` is `not_found` when the song is in To-do's not-found group (check first: `_group(e) == "not_found"`),
else `waiting` (also for a song held by a pending "Is this the same song?"); `summary` and `chips` of a playlist view
count its main rows with a file, `summary.songs` all its main rows; search filters main and `also` rows alike; a
folder's `subfolder` is relative to the viewed folder, with `/` between parts.

**I4. Routes** (`router.ts`): `#/library` (all), `#/library/playlist/:name`, `#/library/folder/:path` (the path
encoded whole, `/` as `%2F`), `#/library/not-in-playlist`. `libraryTarget(params) → { view, key }`: a `folder` param
that is no path (doesn't start with `Library/` or `/`) is a playlist name (old links and the player's queue hrefs).
`libraryHref(target)` takes `{ view: 'all' } | { view: 'playlist', name } | { view: 'folder', path } | { view:
'unlisted' }`. Pins: a path with spaces, `%`, `/`, `›` and NFD/NFC round-trips through `buildHash`/`parseHash`.

**I5. Words (binding).**
- Sidebar tooltips: playlist `{name}` ⏎ `{Service} playlist · {n} songs` (never read: `· not read yet`); switched off
  adds ⏎ `Switched off: its files stay, nothing new downloads`. Folder: its place (`~/Music/Old Sets`, `Example Drive ›
  DJ Sets`, through the watched-folder list's existing formatter; check first its name in `watchedFoldersModel.ts`);
  `Library/{name} · in no playlist` for a Library folder; away adds ⏎ `Offline: connect the drive` / `Folder not
  found`. Chevron `aria-label`: `Show the subfolders of {name}` / `Hide the subfolders of {name}`. Mark: `{Service}
  playlist`.
- Header line: playlist `{Service} playlist · {n} songs` (+ ` · switched off`; never read: `{Service} playlist · not
  read yet`); folder `{n} tracks · {place}`; away folder `{n} tracks · Offline: connect the drive` / `… · Folder not
  found`.
- Rows: `Waiting` (tooltip `Downloads at the next sync`); `NOT FOUND` with To-do's next-try line as tooltip (reuse its
  words); note `in {place}`; section `Also in this folder` with hint `files in {folder} that aren't in this playlist`;
  Subfolder `–` for the folder itself; badge `+{n}` with tooltip `In {a}, {b}, {c}`.
- Empty states: `This playlist hasn't been read yet.` (action `Read playlists`, the existing read); `This playlist is
  empty.`; `No music in this folder.`; `gone`: `This playlist isn't in your list any more.` / `This folder isn't in your
  library any more.` (action `All tracks`).
- Panel for a no-file row (built from the row; `track()` isn't called): `TrackHead` with `Artist · length · not
  downloaded yet`, then a `NoteCard` (`Downloads at the next sync.` / To-do's not-found words), foot `Open in to-do`
  for not found.

---

## Group 1 — Rename the read-status wire (Sonnet)

**Read list:** D13; `docs/issues.md` #26 first bullet; `grep -rn "spotify_status\|SpotifyStatus\|\"spotify\"\|\.spotify\b"
discjockey tests hub-ui/src docs/hub-bridge-contract.md docs/hub-design-language.md` (outline first, then each hit's
lines); `hub-ui/src/lib/components/SpotifyStatus.svelte`, `PageHeader.svelte` (props only).

Tasks:
1. **1.1 Engine:** `views.read_status`, the `read_status` field in `api.job_status`, `views.dashboard`,
   `views.sync_preview` and anywhere else the field is built; tests renamed with them.
2. **1.2 UI:** `ReadStatus` type and component (`git mv`), its users, `copy.ts`, stores, fakes, the gallery and every
   `shots.json`/test that names the field or component. Real Spotify uses stay (D13).
3. **1.3 Docs:** contract (the shape's name and every example's key), design-language doc (block table, "Spotify slot"),
   remove #26's first bullet.

Checks: `uv run pytest -q tests/test_hub_views.py tests/test_hub_api.py tests/test_hub_sync.py tests/test_hub_api_setup.py
tests/test_hub_api_playlists.py`; `cd hub-ui && npm run check && npx vitest run src/lib`; a final grep shows no
`spotify_status`/`SpotifyStatus` left. At the end: the full Python suite. ≈ 450 lines.

## Group 2 — Read records (Opus)

**Read list:** D1, D2, I1, I2; `discjockey/db.py` (docstring, `SCHEMA_V3_STEP`, `_upgrade`, `check`, `connect`,
`transaction`, `snapshot` lines 533–570, `import_counts`); `discjockey/run.py` (`grep -n "^def "`, then `prepare` and
where it fetches); `discjockey/sources/__init__.py` (`read`); `discjockey/models.py` (`FetchedPlaylist`,
`SourceTrack`); `discjockey/playlists_file.py` (`Row`, `load`); `discjockey/hub/jobs.py` 571–640 (`PreviewStore`);
`tests/test_db*.py` (`grep -n "def test_"`).

Tasks:
1. **2.1 Schema step** (I1) and its pins.
2. **2.2 `record_reads`, `playlist_records`** (I2) with their pins.
3. **2.3 Record after a read** (D1): one call where every read passes; best-effort catch with a log line; tests in
   `tests/test_run.py` (a read records; an unreadable playlist keeps its old record; a failing record doesn't fail the
   read; a dry run's behaviour as D1 decides) and one hub test that a preview read records.

Checks: `uv run pytest -q tests/test_db.py tests/test_db_migrate.py tests/test_run.py tests/test_hub_jobs.py` (check
first: the exact db test file names). At the end: the full Python suite. ≈ 600 lines.

## Group 3 — Views, bridge, contract and fake (Sonnet)

**Read list:** D3–D12, I3–I5; `discjockey/hub/views.py` lines 500–741 (`track_row`, `file_state`, `track_detail`,
`SORTS`, `library`, `sidebar`) and `_group`; `discjockey/hub/api.py` (`sidebar`, `library`, `track`, `_folders`,
`_away_roots`, `_images`); `docs/hub-bridge-contract.md` (`sidebar()`, `library()`, `track()`); `hub-ui/src/lib/bridge/
types.ts` (Sidebar, TrackRow, Library), `contract.ts`; `hub-ui/src/lib/bridge/fake/` (`bridge.ts` sidebar/library/
track, `data.ts` FakeTrack/FakeState/FakePlaylist, `folders.ts` outline); `hub-ui/src/pages/library/fake.ts`.

Tasks:
1. **3.1 `views.sidebar`** (I3): playlists from `lines` + `records` (songs = distinct resolved songs, `null` unread),
   folders as D4/D8 (roots, the tree, `not_lossless/` folded in, `state` from `away` per root, inherited by children).
   Tests `tests/test_hub_views.py`: order; switched-off kept in place; a playlist's own folder not listed (fold-equal);
   an offline root and its children; counts per D5; a `Library/` file directly in `Library/` belongs to no folder row.
2. **3.2 `views.library` playlist view** (D9, I3): resolution through keys and aliases, duplicates once, `wait`,
   `place`, `also`, `read_at`, `enabled`, chips and summary as I3, sort `order`. Tests: each rule of I3's list.
3. **3.3 Folder view** (D10): rows by path prefix (a `/` boundary, NFC), `subfolder`, `playlists` (from `records`, in
   `lines` order), sort `subfolder`. Tests: a nested subfolder; `not_lossless`; a sibling folder whose name starts the
   same (`Old Sets 2`) isn't inside `Old Sets`.
4. **3.4 `track()` `place`** (D11) and `api.library`'s new signature; `gone` for an unknown name or path. The
   All tracks / Not in a playlist rows' folder field becomes the same `place` (D12; the fake too). Tests
   `tests/test_hub_api.py`, `tests/test_hub_views.py` (a file outside its song's folder; an own file).
5. **3.5 Sidebar refresh:** check first when the shell's store re-fetches `sidebar()` (`stores/hub.ts`); it must also
   follow a finished read, `DrivesChanged` and a finished import. Add what is missing in the store (no new event if an
   existing one already says it).
6. **3.6 Contract, `types.ts`, `contract.ts`** (I3, with an example of each view).
7. **3.7 Fake backend:** read records per fake playlist, files with paths (Library and import), the methods above.
   Scenarios (prefix `library:`): `tree` (the mockup's data: six playlists incl. two Qobuz, one switched off, one long
   name; `Old Sets` with `Techno 2019/Peak` and `Warmups`; `DJ Sets` on an ejected `Example Drive`; `Library/
   Old_Hardstyle` in no playlist; in Hard_Bounce: a file in `Techno 2019`, one in `Powertrance`, one offline, one
   waiting, one not found, two files also in the folder, one of them a leftover), `never_read` (a playlist added since
   the last read), `many_playlists` (14 playlists and two deep trees, for the sidebar's scroll at 1100 × 700).

Checks: `uv run pytest -q tests/test_hub_views.py tests/test_hub_api.py`; `cd hub-ui && npm run check && npx vitest run
src/lib/bridge`. At the end: the full Python suite. ≈ 1,300 lines; past 1,500 stop and report.

## Group 4 — The sidebar's Library group (Opus, UI)

**Load the `apple-design` and `emil-design-eng` skills first**, then `docs/hub-design-language.md` (§1 the L frame, the
block table, the decision log's sidebar entries). The approved mockup is the target; improve what the shots show
(§12), and show the orchestrator before/after shots for any change to the approved design.

**Read list:** D4–D8, I3–I5; the mockup `#sidebar`; `hub-ui/src/lib/shell/Sidebar.svelte`, `NowPlayingRow.svelte`
(outline); `hub-ui/src/lib/router.ts`; `hub-ui/src/lib/components/StatusMark.svelte` (props), `index.ts`;
`hub-ui/src/lib/dev/Gallery.svelte` (one section's pattern); `hub-ui/src/lib/prefs*` (`getPref`/`setPref`).

Tasks:
1. **4.1 `ServiceMark` block** (D7): `service`, 14 px, `currentColor` at the glyphs' opacity, `aria-label` per I5; a
   gallery section `gallery-servicemark` (both marks, normal, selected row, dimmed row) and the block table row plus a
   decision-log entry (the mark's form and why, D7).
2. **4.2 `sidebarModel.ts` + test:** the visible rows from `Sidebar.folders` and the open set (a closed parent hides
   its subtree; the route's folder and its ancestors forced open), the folders' count width (widest count in `ch`),
   tooltips (I5), which row is current for a route (I4).
3. **4.3 The group** (`Sidebar.svelte`): rows per D4/D8 and the mockup; the whole row navigates, the chevron is a
   sibling `<button>` (no interactive element inside the `<a>`), `aria-expanded`; on a focused folder row → opens,
   ← closes (or moves to its parent); choosing a folder opens it. Selection is instant; the chevron turns in 160 ms
   (`--ease`), none under reduced motion. The Now playing row still pushes the list up (the list scrolls inside, as
   today).
4. **4.4 Router** (I4) and every `libraryHref` caller (the player's queue href, Dashboard's folder bars). Tests in
   `router.test.ts`.
5. **4.5 Shots** (`hub-ui/src/lib/shell` or the library page's `shots.json`, wherever the shell's shots live): 
   `library-sidebar-tree` (`#/library`, `library:tree`, `Old Sets` opened by a click on its chevron),
   `library-sidebar-many` (`library:many_playlists`, at 1100 × 700 scrolled to the end), `base-gallery-servicemark`.

Checks: `npm run check`, the touched `*.test.ts`, `npm run rules -- --page library --only library-sidebar-tree,
library-sidebar-many` and `--page gallery` for the new section. At the end: `npm run build`. ≈ 800 lines.

## Group 5 — The playlist and folder views (Opus, UI)

**Load the skills first**, then the design-language doc (`ListRow`, `ListSection`, `AwayTag`, `MiddleText`, `Badge`,
`TrackHead`, the Library entries of the decision log).

**Read list:** D6, D9–D12, I3–I5; the mockup `#playlist` and `#folder`; `hub-ui/src/pages/library/` (Page,
LibraryTable, TrackDetails, FolderOverview, libraryModel + test, shots.json).

Tasks:
1. **5.1 `libraryModel.ts` + test:** `LibraryView` per I3; `optionalColumns(view)` (D10; playlist: Source, Added);
   default sorts and a saved sort per view kind (`library.sort.<view>`); `playable` false for `no_file`; `rowOff`
   unchanged; `rowDim` = `rowOff || away || no_file`; the badge text (`first +n`) and tooltip; the location note.
2. **5.2 Table** (`LibraryTable.svelte`): the `#` column (playlist view, right-aligned, label colour); the note after
   the title (D9: gives way first); the quality column's `Waiting` / `NOT FOUND` and the dashed empty cover for
   `no_file`; Subfolder as `MiddleText`; the Playlist badge (neutral `Badge`; if `Badge` has no neutral tone that keeps
   the user's case, stop and report: it is added centrally); the `Also in this folder` `ListSection`.
3. **5.3 Page and panel:** header lines (I5), the empty states (I5), the overview over the main rows, the panel of a
   no-file row (I5), `TrackHead`'s place from `track().place` (D11, decision-log entry).
4. **5.4 Shots** (`pages/library/shots.json`, scenario `library:tree` unless named): `library-playlist`
   (`#/library/playlist/Hard_Bounce`), `library-playlist-away-selected` (the offline row), `library-playlist-waiting-
   selected`, `library-playlist-off` (`03_06_2026`), `library-playlist-never-read` (`library:never_read`),
   `library-folder` (Old Sets), `library-folder-subfolder` (`Old Sets/Techno 2019`), `library-folder-offline` (DJ
   Sets), `library-folder-library` (`Library/Old_Hardstyle`). Existing `library-*` shots keep working through I4's old
   route (switch them to the new routes where it reads clearer).

Checks: as Group 4, `--page library` on the new shots. At the end: `npm run build`. ≈ 1,000 lines.

## Group 6 — Docs (Sonnet)

**Read list:** this plan's D1–D14 and I5; `README.md` (its Library section); `docs/issues.md` #26, #27; `CLAUDE.md`
Layout (the `db.py` row).

Tasks: **6.1 README:** the sidebar's Library group (service marks, counts, the tree, offline "!", switched-off dim), a
playlist's view (the note, Waiting/Not found, Also in this folder), a folder's view. **6.2 `docs/issues.md`:** add any
leftover the groups reported; #27's To-do item stays. **6.3 `CLAUDE.md`:** the `db.py` row names the read records.

Checks: `uv run pytest -q tests/test_docs_citations.py tests/test_docs_links.py`; `scripts/check_public.sh`. ≈ 150 lines.

---

## Order and sizes

1 → 2 → 3 → (user approves the mockup) → 4 → 5 → 6, one at a time. Group 1 touches the shell's status slot that Group 4
rebuilds beside, so it goes first; 3 needs 2's records; 4 and 5 need 3's contract and fake. Expected changed lines with
tests: G1 ≈ 450, G2 ≈ 600, G3 ≈ 1,300, G4 ≈ 800, G5 ≈ 1,000, G6 ≈ 150.

## Stage checks

- **Python:** each group's files while working; the full suite once per group (`uv run pytest -q | tail -3`); CI on
  the branch push. Pins the stage review looks for: generation unchanged by `record_reads` (focus 2); the I3 rules;
  D5's counts against the views' rows (focus 3).
- **UI:** `npm run verify` once, by the orchestrator, in the background, before the merge (the sidebar is on every
  page, so every page's shots change). Screenshots looked at by the orchestrator, at the three sizes: Group 4's and 5's
  shots above, plus `library-all`, `library-not-in-playlist`, `library-ejected` (unchanged views keep their look) and
  one shot of each other page (the sidebar in place). `--compare` against `docs/hub-mockups/design-system/
  library-sidebar.html` (check first how `shots.mjs --compare` maps a shot to a mockup state).
- **Before the user's check, by the orchestrator:** a scratch run (`DISCJOCKEY_SUPPORT=<scratch> bin/discjockey hub`)
  with a scratch music folder, one import folder of generated tones with two subfolders, and a `playlists.txt` whose
  read is faked by the test fixtures' recorded responses: no Spotify or Qobuz call. Open, quit, open again: the
  playlists' counts are there before any read.
- **Live check by the user — the sidebar on their own library, about 10 minutes.** Nothing downloads.
  1. Open the new build and wait for the playlists to be read. *They see* under Library every playlist with an S or Q
     mark and its song count, a switched-off one dimmed, their import folders with folder icons, and Not in a playlist.
     *They judge* whether the marks read as Spotify and Qobuz and whether the group feels like part of the sidebar.
  2. Click an import folder that has subfolders. *They see* it open, its files with a Subfolder column and the playlist
     badges; the chevron closes it again.
  3. Open a playlist whose songs they keep in other folders. *They see* "in …" notes on those songs, and below, Also in
     this folder.
  4. Eject the drive of an import folder (if they have one). *They see* the "!" on its folder and "Offline" on its songs
     in the playlist.
  5. Quit, turn off Wi-Fi, open again. *They see* the same playlists and counts without a read.
  They report anything that looks wrong or reads unclearly, and how the tree feels to use.
