# Library layout: design note

The notes behind `library-layout.html` (rail + browser column, library stage 5). The mockup page shows only the app
window and the state switcher. Everything that explains it is here.

## Trying the mockup

Open `library-layout.html` in a browser. The window is shown at its real size (1280 × 800 or 1100 × 700) and is
scaled down only when the browser window is smaller. Each state has a hash that is read on load (`#library`,
`#search`, …), and a state button's tooltip describes the state. These controls work:

| Try | What happens |
|-----|-----|
| The sidebar button (top left) or ⌃⌘S | Folds or unfolds the sidebar. Library remembers its form, and the other pages share one form. |
| ♫ and the Dashboard icon | Switch between the two pages that are built. The other icons have tooltips only. |
| ⌘K, then type | Filters the browser. ↑ ↓ move the one highlighted row, Enter opens it, Esc clears. ✕ clears. |
| A name that matches nothing (try "kaltf") | One row, "Search tracks for "kaltf"" ↵. Enter or a click opens All tracks searched for it. |
| A browser row | Opens that playlist, folder or crate. Right-click opens the menu (Open, Add to / Remove from favourites). |
| Section heads, a watched folder's chevron, the sort button | Fold the section or the folder, or switch Playlists between priority order and A–Z. |
| The browser's right edge | Drag it (200–360 px). Double-click it to go back to 240. |
| A table row | A click selects it, and a double-click (or Enter) plays it in the foot. ↑ ↓ move the selection. |
| A quality badge, the details toggle, or ⌘I | Opens the details inspector. It follows the selection. At 1100 it steps the browser back, and ⌘K or ♫ brings the browser back. |
| ⌘F, the filter segments, "Upgrade ready ›" | Search the open collection's tracks, or filter them by quality. |

The mockup changes size and layout instantly. The motion table below is how the app moves.

## States

| State (hash) | Shows |
|-----|-----|
| Library (`library`) | Library at 1280 × 800: the rail, the browser column at 240, Rekordbox Library open. The table keeps every column and gains Length. |
| Filter "bou" (`search`) | Filtering with ⌘K. Each match is listed once, in its own section. The watched folder appears as context. One highlighted row is the one Enter opens, and the hand-off to the track search comes last. A crate's tooltip gives its full path. |
| Filter, no match (`filter-none`) | A track name typed into the filter ("kaltf"). No playlist or folder matches, so the only row hands the text to the track search. |
| Favourites drag (`favourites`) | Peak Time is being dragged to the top of Favourites and the rows below make room. Hardtechno is open, with its pill on its topmost row. |
| Column wider (`wide`) | The browser column dragged to 320. The orange edge line follows the pointer, long names come out whole, and the table lets Length go. |
| Details open (`inspector`) | An upgrade-ready track (Eisenbahn, a 20 kHz MP3) in the details. The table drops to Track, Artist, Subfolder and Quality while the details are open. |
| Details 1100 (`inspector-1100`) | The same at 1100 × 700. The browser column steps back behind the rail. |
| Library 1100 (`library-1100`) | 1100 × 700 with a track playing and a sync running. The foot keeps working under the rail and the browser. |
| First look (`first-look`) | A new user's first look: Favourites empty with its landing row, Playlists folded, and the right-click menu on a crate. |
| Dashboard (`dashboard`) | Another page: the full sidebar with Favourites as shortcuts and the docked panel. Qobuz is at 15 of 40, so Download limits has no dot. |
| Dashboard, folded (`dashboard-rail`) | The sidebar folded by hand. Qobuz's limit is reached today (40 of 40), so Download limits has its yellow dot. The hidden player sits above Settings. |

## The layout in one line

In Library the app's sidebar folds into a 50 px **rail** of page icons, and the space goes to a **browser column**
(Favourites, playlists, folders, a filter field) that the user drags wider or narrower. The **right panel leaves
Library**: its summary card becomes a **strip** on the page, and the track's details become an **inspector** that opens
only when asked. Every other page keeps the full sidebar and its docked panel. The user can fold the sidebar on any page
with ⌃⌘S.

## Decisions

1. **One sidebar, two forms: full (168 px) and rail (50 px).** The rail is the full sidebar with its labels folded
   away. The glyph column (18–32 px from the window's edge) and each row's height (30 px, 2 px apart) are the same in
   both forms, so **no icon moves** when the sidebar folds. The selected pill becomes a 30 × 30 square on the same
   spot. The fold button sits on that glyph column too, at the top of both forms (the macOS sidebar symbol, "Hide
   sidebar ⌃⌘S" / "Show sidebar ⌃⌘S"), so it never moves either, and the word "Discjockey" folds away beside it.
   *Why:* navigation stays obvious when a DJ's eye finds To-do at the same place in either form. Opening a collection
   scrolls its row into view in the browser. Every rail icon has a tooltip with its name and shortcut. The first one
   waits 500 ms and the next ones open at once (the InfoTip rule).
2. **Library gets a nav item of its own (♫, after Download limits), and its collections leave the app sidebar.** The
   full sidebar holds only the pages, plus **Favourites** as shortcuts (no counts) on pages where the browser column
   isn't shown. A favourite opens Library at that playlist or folder. *Why:* the A variant's "everything in the
   sidebar" was what made names cut and the sidebar long. Favourites are short, the user picks them, and they stay one
   click away from To-do or Sync, which was A's real advantage. Without counts, 168 px fits "Bounce · Old Sets".
3. **The browser column is chrome, not page.** It uses the frame's material beside the rail, so the L frame just grows
   wider in Library (50 + 240 px). The page keeps its single edge line. A quiet hairline (the same 6 % white)
   separates the sidebar from the browser in either form and marks the two levels, pages | collections. The filter
   field sits at the top and stays visible ("Filter playlists, folders ⌘K", centred on the page header's row). The
   track search stays top right on the page ("Search title, artist… ⌘F"). The two fields use different words, sit in
   different materials and have different shortcuts. **The filter hands off to the track search** (new in this round):
   while filtering, its last row is "Search tracks for "…"". When no playlist or folder matches, that is the only
   row, and it carries the highlight and ↵. Enter or a click opens All tracks with the text in its search field.
   *Why:* a user who types a track name into the left field would otherwise get nothing. The row is there whenever
   there's text, not only on no match, so the user learns it before they need it, and a text that matches a playlist
   name ("bou") can still reach the tracks with ↓ … Enter. *Why All tracks:* the filter works across the whole library,
   so the hand-off does too. Searching only the open collection could miss the track again. *Why visible, not behind a
   magnifier:* the column has the room, and a new user should see that they can filter.
4. **Resizable by drag, 200–360 px, 240 by default.** The grip is the page's edge line (9 px wide). On hover the
   pointer turns into the resize cursor, and while dragging the line turns orange (the action) and follows the pointer
   1:1, with no animation. Double-clicking the line returns to 240. The width is remembered. Every row is **one
   line**: "Rekordbox Library", "Bounce · Old Sets" and "Hardtechno › 2019" (the same words as the page's Subfolder
   column) all fit at 240 px. The two-line crate rows and the balanced wrap for watched folders are gone. A playlist
   name that's still too long ("Afterhour_Sonntag_Warmup_…") ends in "…" with a tooltip, and comes out whole when the
   column is dragged wider. **A crate's place in its name keeps the row's colour.** Only the separator (› or ·) is
   quiet. *Why (changed in this round):* the parent or qualifier in label grey read as a dimmed row ("Hardtechno ›
   2019", "Bounce · Old Sets"), and dimmed means a switched-off playlist (see the signals table).
5. **The right panel leaves Library, because the width doesn't add up.** With the rail, the browser and a docked 360 px
   panel, the 1280 table would be 586 px, less than today's 708. So **the summary card becomes a 72 px strip** between
   the header and the filter segments. It keeps the share, the bar, Upgrade ready and Not lossless yet · n in To-do,
   each with its count and link. The bar's legend is dropped, because the segments right below it carry the same dots
   and counts. **The track details become an inspector** (the same card content, 360 / 320 px). It opens from the
   header's details toggle, ⌘I, the right-click menu's "Show details", or a click on a row's quality badge ("Why is
   this weak?"). It then follows the selection and stays open until closed. Its state is remembered, and it starts
   closed. A click selects and a double-click or Enter plays, as today. With nothing selected it says "Select a track
   to see its details." *Why the badge:* the quality question is what makes a DJ want the details, and the badge is
   where they ask it.
6. **The list stays fully usable at 1280 × 800 and at 1100 × 700, and its columns follow its own width** (the container
   rule, nothing scrolls sideways). The drop order is Length first, then Playlist, then Subfolder (D10). With details
   closed, which is the normal state, Library at 1280 shows **more** than today (+ Length), and at 1100 it shows what
   1280 shows today. With details open, the list never goes below today's 1100 set (Track, Artist, Subfolder,
   Quality, about 586 px), and the facts of the columns it drops are in the inspector for the selected track:
   Playlists in its file card, the place in its head ("in Hardtechno › 2019"). A column that would say the same on
   every row isn't shown: a playlist has no Playlist column, and a crate without crates inside has no Subfolder
   column. All tracks and Not in a playlist name the **Folder** instead. The filter segments keep their whole labels in
   every state. Variant B's failure (a list too narrow to be useful, single-letter filters) can't happen.
7. **Below 1240 px the window holds the browser or the details beside the list, not both.** At 1100, opening details
   steps the browser column back behind the rail. The rail stays, with Library's pill, and ⌘K or a click on ♫ brings
   the browser back and closes the details. Closing details brings the browser back at its own width. *Why:* rail +
   browser + a 320 px inspector leave 446 px at 1100, which is variant B's narrowness. Choosing a collection and
   reading one track's details are different moments, so on a small screen they take turns. At 1280 and up both fit.
8. **Sidebar memory: two places, not per page.** Library remembers its form (rail by default) and all other pages share
   one form (full by default). *Changed from the brief ("remembered per page"):* per page, folding the sidebar on
   Dashboard and then opening Sync would unfold it again, which feels like the app ignoring you, and every page switch
   could animate the chrome. With two places the chrome changes only on the way into or out of Library, and that
   change is expected because Library has its own browser.
9. **⌘K works on every page.** It opens Library with the filter focused, so from any page any collection is ⌘K, a few
   letters and Enter. The filter filters names, keeps sections and the watched folder as context, opens folded
   sections, and finds hidden crates and the 312 albums. **While filtering, each match appears once, in its own
   section: Favourites steps aside** (new in this round). Exactly one row carries the keyboard highlight, the first
   match, and Enter opens that row. *Why:* a favourite is a shortcut to a row that is also in Playlists or Folders.
   Listing both put two highlighted Hard_Bounce rows on screen and left it unclear which one Enter opens. A watched
   folder shown only as context (its name doesn't match) is never the highlighted row.
10. **Discoverable without being told:** the fold button with its tooltip; visible chevrons on every section head and
    watched folder; section heads that stick to the list's edges, so "Folders ⌄" sits at the foot from the first look;
    an **empty Favourites section that shows one dashed row "Drag a playlist or folder here"** until the first pin (it
    folds and stays folded if the user wants); the right-click menu (Open · Play · Add to favourites · Hide from
    sidebar · Show in Finder) with the note "Settings brings it back"; the resize cursor plus the line lighting up on
    the column's edge; and the filter's hand-off row.
11. **The rail carries the sidebar's signals, in the same colours:** the To-do count as a neutral pill on the glyph's
    corner; Download limits' yellow dot where it is today, **only while a limit is reached or a service is waiting**;
    a running sync as a neutral ring round ⟳ (the arc is the share done; in the full form, "12/40" in the count
    column). The hidden player becomes ⌃ Show player above a play button whose orange ring is the position, the same
    orange as the foot's line.
12. **The foot doesn't change.** It stays full window width under the rail and the browser, with the transport centred
    on the window. Its line (the page's lower edge and the position) starts at the page's edge, so in Library it starts
    at 291 px: the line follows `--sidebar-w`, which becomes the chrome's whole width.
13. **Folder logic as decided:** only crates are listed (wrappers skipped, full path in the tooltip), a crate can be
    hidden (right-click, Settings → Watched folders), and above 25 crates the watched folder is one row with Settings'
    message and the page link "Show some in the sidebar…" ("sidebar" here means the Library list, which is what the
    browser column is). The offline "!", the dimmed switched-off playlist, Favourites by drag, and Playlists in
    priority order or A–Z are all unchanged.
14. **The page header's subtitle drops whole parts, the least important first** (new in this round). Its parts are in
    order of importance: the count, then the kind or the number of folders, then the path ("472 tracks · 8 folders
    with music · ~/Music/Rekordbox Library"). When the header is narrow (details open, 1100, a long title), the path
    goes first, then the next part, and finally the count. A part is never cut mid-word, and the whole subtitle is the
    tooltip. *How:* the parts are flex items that wrap onto a clipped second line, behind an empty first item one line
    tall, so even the first part can wrap away. This is CSS only, so there's no measuring and it follows the width
    live. The title itself ends in "…" only when even the title alone doesn't fit.
15. **Section heads are solid and square** (new in this round). A stuck section head ("Playlists 35" at the top,
    "Folders" at the foot) is opaque in the column's own colour, has no rounded corners and no soft fade, and gets a
    hairline on its open edge while rows pass beneath it. A row the app scrolls to (opening a collection, a state, the
    keyboard highlight) stops whole below the stuck head, never half under it. *Why:* the old fade let a row show
    through and round the head's corners, which looked like a glitch. The rule is the design language's `ListSection`
    rule ("the stuck head is the edge").

## Widths (the table's own width decides its columns)

| Window · state | Chrome · panel | Table | Columns |
|-----|-----|-----|-----|
| Today 1280 · today 1100 | 168 · 360 / 320 | 708 · 568 | Track, Artist, Subfolder, Playlist, Quality · without Playlist |
| 1280 · Library (rail) | 50 + 240 · none | 946 | Track, Artist, Subfolder, Playlist, **Length**, Quality |
| 1280 · column dragged to 320 | 50 + 320 · none | 866 | Length goes (first to go) |
| 1280 · details open | 50 + 240 · 360 | 586 | Track, Artist, Subfolder, Quality (today's 1100 set) |
| 1100 · Library (rail) | 50 + 240 · none | 766 | Track, Artist, Subfolder, Playlist, Quality (today's 1280 set) |
| 1100 · details open | 50 (browser steps back) · 320 | 685 | Track, Artist, Subfolder, Quality (rail + browser + details would leave 446: variant B's narrowness, so they take turns) |

## What each signal means

| Signal | Means exactly this, nowhere else |
|-----|-----|
| Row at half strength | A switched-off playlist. It is the only dim in the sidebar and the browser. No part of a name is ever greyed: a crate's parent ("Hardtechno ›") or qualifier ("· Old Sets") keeps the row's colour, and only the separator is quiet. |
| Yellow ! in the icon slot | The watched folder's drive isn't connected (or the folder isn't found). The name and count stay at full strength. |
| Yellow dot on ◔ | Download limits: a limit is reached or a service is waiting, in both forms. Its tooltip says which. In the mockup it shows exactly when Qobuz is at 40 of 40 (Dashboard, folded), and is absent at 15 of 40. |
| Service logo, own colours | Which service the playlist is read from. Qobuz's black tile has a faint edge so it doesn't vanish on the black frame. |
| Folder outline | A folder on disk standing on its own: a watched folder, a pinned crate, a Library folder no playlist uses. A crate under its watched folder has none and is indented instead. |
| Grey pill on the page's row / the rail's square | The page or collection on screen. |
| Neutral pill with a number on ✓ | Rail only: the To-do count (the full form shows it in the count column). |
| Grey ring round ⟳ | A sync is running, and its arc is the share done. It is neutral because it's status. |
| Orange ring round the rail's ▶ | The hidden player's position (the same as the foot's orange line). |
| Orange line on the browser's edge | Only while dragging it: the width being set. |
| Orange details toggle with a dot | The inspector is open (the pressed state of an icon button). |
| Orange wash on a browser row | Only while filtering, and on one row only: the row Enter opens. On the hand-off row it comes with ↵. |
| Bold white letters in a name | While filtering: the letters that match. |
| Orange wash on a table row | The selected track (what the inspector shows when it's open). |
| Orange ring round a row | The row the open context menu acts on. |
| Dashed row in Favourites | Favourites is empty, and this is where a dragged row lands. |
| Hairline under / over a section head | The head is stuck and rows pass beneath it. |
| "–" in a cell | Nothing there (no playlist, or the track sits in the collection itself rather than a crate inside it). |
| Muted "· 41 in To-do" in the strip | How many of the not-lossless tracks are on the to-do list. It is secondary text, readable, not a dim. |

## Motion: the page lays out once, the chrome moves over it

Reflowing a 500-row table on every frame would stutter, and it would make the columns flicker. So the page takes its
final width **at once**, and only the chrome moves: when the chrome shrinks it uncovers the page, and when it grows it
covers space that is already empty. This is the foot's rule ("the page makes room at once, only the contents move"),
applied to the sidebar and the inspector. Only transform, opacity and the chrome's own width move. Every transition is
a CSS transition, so a second ⌃⌘S mid-way turns it round from where it is. (The mockup switches instantly.)

| What | How |
|-----|-----|
| Fold / unfold (⌃⌘S, the button) | The edge glides 168 ↔ 50 in **220 ms, cubic-bezier(.32,.72,0,1)** (the drawer curve, no bounce). Labels fade out in the first 90 ms (ease-out) and fade in during the last 120 ms (100 ms delay). Icons don't move. |
| Into Library / out of it | The page switches at once (selection after navigation is instant). The chrome's edge glides 168 → 291 in 220 ms on the same curve while the labels fade out, and the browser's rows fade in over the last 150 ms, 8 px from the left. On the way out it's quicker: the rows fade out in 90 ms, then the edge glides back. Exit is faster than entry. |
| Drag the column's edge | 1:1 with the pointer, with no easing (direct manipulation), and the table reflows live because the user is steering it. Double-click to reset: 220 ms, drawer curve. |
| Details below 1240 px | The browser column steps back behind the rail (translateX -24 px and fading, 200 ms, the drawer curve) while the inspector slides in. On close it comes back the same way (240 ms). The page lays out once. |
| Details inspector | Open: the table narrows at once and the inspector slides in from the window's right edge (translateX 100 % → 0), **240 ms**, drawer curve. Close: the table widens at once and the inspector slides out the same way, **200 ms**, so it leaves the way it came. A selection change inside it is instant. |
| Filtering | No motion: the list is rebuilt on each key (a keyboard action, used many times a day). The highlight moves instantly. |
| Tooltips (rail, rows) | Fade and grow from scale(.97) at the trigger, 140 ms (`--t-pop`). The first waits 500 ms, the next open at once. |
| Favourites drag | Lift: 120 ms (raised, shadow, scale 1.02). The other rows part with a 200 ms ease-out transform. Drop: a spring with damping 1 and response 0.3, with no overshoot (a drop has no momentum). |
| Sync ring, player ring | Their arcs move linearly with progress, and nothing turns or pulses. |
| Reduced motion | No glides: widths change at once and the chrome's contents cross-fade in 150 ms. The inspector fades in place. |

## Keyboard

| Keys | Does |
|-----|-----|
| ⌃⌘S | Fold or unfold the sidebar (macOS's standard key, also in the View menu as Hide / Show Sidebar) |
| ⌘1 … ⌘6, ⌘, | Dashboard, Sync, To-do, Playlists, Download limits, Library; Settings (the order of the rail) |
| ⌘K | From any page: Library with the filter field focused. At 1100 it also closes the details so the browser can come back. In the filter: ↑ ↓ move the one highlight (down to the hand-off row), Enter opens it, Esc clears and leaves |
| ⌘F | The page's own track search (unchanged). Esc clears it |
| ⌘I | Show or hide the details inspector (macOS's Get Info key) |
| ↑ ↓ · Enter · double-click | In the table: select · play · play (unchanged) |

## House-rule changes (for docs/hub-design-language.md, not edited now)

1. **The L frame: the sidebar has two forms, and in Library the frame holds the browser column.** `--sidebar-w`
   becomes the chrome's whole width (168, 50, or the sidebar + 1 + the browser's width), and the foot's line and seek
   area follow it. *Why:* the frame stays one seamless material and only changes width.
2. **One more line inside the chrome: the sidebar's right edge** while the browser stands next to it, the same hairline
   as the page's edge. "Only the page's edge has a line" becomes "the page's edge, and the sidebar's edge when the
   browser stands next to it". *Why:* without it, the icon column and the browser read as one ragged list.
3. **ListPanelFrame: Library drops the docked panel.** Library gets a details inspector instead (on demand, the same
   widths, the same Panel inside), and its summary becomes a strip block (`SummaryStrip`: share · bar · two link rows,
   72 px). The other pages keep the docked panel. *Why:* the widths table above.
4. **The sidebar's Library group retires.** The sidebar shows Favourites (no counts) on pages without the browser. The
   two-line crate rows and the watched folders' balanced wrap retire with it, because the browser's rows are one line.
5. **Motion: the "chrome moves, page lays out once" rule** joins the motion table, together with the timings above.
6. **The nav's text glyphs (◉ ⟳ ✓ ≡ ◔ ⚙) become drawn icons** (14 px, 1.3 px stroke, one family), the same in both
   forms. *Why:* in the rail the icon is the only label, and at 12 px ⟳ and ◉ render as dots and rings that can't be
   told apart. Library gets the note.
7. **Segmented: no change.** With 946 / 766 px the Library strip is never tight, and "Upgrade ready" and "Lossless 290"
   stay whole.
8. **PageHeader: the subtitle is a list of parts that drop whole, last first** (decision 14), never an ellipsis in the
   middle of a word.
9. **Dim is reserved.** In lists of collections, half strength means switched off and nothing else. A name's secondary
   part keeps the name's colour, and only its separator is quiet. This tightens the existing "one meaning per signal"
   rule for the sidebar and the browser.
10. **Stuck heads are opaque, square and get a hairline** (decision 15). No soft fade over rows.

## Considered and not built

**Details under the table (a 200 px shelf), so the table never loses a column.** The spectra would get width, but the
table would keep 10 rows at 1280 × 800 and only 6–8 at 1100 × 700 with the foot, which is too few to browse a crate.
**Page icons as a row at the top of one wide Library sidebar** (Xcode's navigator bar) would save the rail's 50 px, but
every icon would jump from the column to the row, against the spatial rule. **The panel docked as today** leaves 586 px
at 1280 (see the widths table). **A narrower inspector in place of stepping the browser back at 1100** would cut the
upgrade's spectra to about 220 px, too small to see a cutoff. **One field for both** (a single search that lists
collections and tracks together, Spotlight style) would end the two-field confusion at the root. But it puts tracks of
every collection into the browser column, which is too narrow for track rows, and it loses the clean split between
"go to a collection" and "find in this list". The hand-off row keeps both fields and removes the dead end. **The
hand-off only on no match** (the first agreed form) was built as the no-match case, but the row now shows whenever
there's text (decision 3). **A tree for nested crates** ("2019" indented under "Hardtechno") would show the nesting
without the parent in the name, but a favourite or a filter result then reads "2019" alone, and the page's Subfolder
column would no longer use the same words.

## The made-up data

The mockup's numbers agree with each other, and the page checks this on load (errors go to the browser's console).

- Every collection's files are made once for the whole library, so a playlist, a crate, Rekordbox Library, All tracks
  and Not in a playlist list the same files, and every filter and search agrees. Each collection has, per quality, as
  many files as its counts say (up to a screenful), and its upgrades exactly.
- Rekordbox Library (472 = 460 checked + 12 not checked yet) is the sum of its 8 crates (Hardtechno's 180 includes
  2019's 38). All tracks matches the Dashboard (5,318; 3,776 of 5,306 checked tracks lossless, 71 %).
- The 9 upgrades ready (Dashboard, To-do) are 6 in Rekordbox Library (2019: 2, Hardtechno: 1, 2016 Closing,
  Warmup, Bounce · DJ) and 3 in Library folders (Peak Time and Powertrance share one, Acid Wednesdays, Neo Rave). An
  upgrade is only ever on a file that isn't lossless.
- Qobuz today: 15 of 40 on Dashboard (today's runs: 13 new and 2 upgrades), 40 of 40 on Dashboard, folded (34 new and
  6 upgrades). The yellow dot follows that.
- The table sorts by Artist ↑ (the app's default). Rekordbox Library's made-up files sort after its named sample, so
  its first screen is the sample.

## This fix round (2026-10-30)

| Problem | Fix |
|-----|-----|
| Header subtitle cut mid-word ("8 f…", "~/Music/Reko…") | Parts drop whole, the path first (decision 14). |
| Greys that lie ("Hardtechno › 2019", "Bounce · Old Sets" looked dimmed) | A name's parent or qualifier keeps the row's colour, and only the separator is quiet. Also the strip's "· n in To-do" is muted rather than label grey, and Qobuz's tile has an edge. |
| Yellow dot on Download limits with Qobuz at 15 of 40 | The dot shows exactly when a limit is reached or waiting: absent at 15 of 40, and present in Dashboard, folded at 40 of 40, where the panel says "40 of 40 · limit reached" in the same yellow. |
| Two highlighted Hard_Bounce rows while filtering | Favourites steps aside while filtering, so there's one row per match and one highlight (decision 9). |
| Eisenbahn LOSSLESS with UPGRADE | Eisenbahn is a 20 kHz MP3 with an upgrade ready. Every collection's counts were rebuilt to add up (see the made-up data). |
| Sticky "Playlists 35" head with a row showing through | Opaque, square heads with a hairline when stuck. Scrolled-to rows stop whole below them (decision 15). |
| Two search fields | The filter's hand-off row "Search tracks for "…"" ↵ (decision 3), and the new state Filter, no match. |
| The wall of text on the mockup page | Moved here. The page is the window and the state switcher, sized to fit, and its controls work. |
