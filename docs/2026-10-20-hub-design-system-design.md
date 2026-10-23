# Hub design system — design spec

Date: 2026-10-20 · Status: discussed with the user section by section and approved in conversation; awaiting the
user's review of this written version. Nothing is implemented.

Approved mockups: `docs/hub-mockups/design-system/` — `space-rule.html` (where extra width goes, option B),
`sync-look2.html` (look 2 and the Sync page at 1280 × 800), `sync-panel-many.html` (the "This run" panel with many
playlists at the default and the minimum window height). Where this text and a mockup disagree, this text wins.

## 1. Purpose

The user likes the hub's look but keeps meeting the same three faults, and fixes don't stick:

1. **Pages don't know what to do with space.** `SplitView` fixes the list at `--main-w: 660px` and gives the panel all
   remaining width ("free width never stretches rows", spec "hub" §4 — the user's wish back then). In a big window the
   panel and its full-width button grow huge while the content stays small.
2. **No shared visual language.** Download limits and Playlists show information (rings, bars, chart, cards, colour);
   the Sync panel, the dashboard's runs and the To-do detail tell it in sentences on the bare background; To-do's
   filter chips wrap onto a second line.
3. **The rules live nowhere the next agent reads.** The bridge stays consistent because `docs/hub-bridge-contract.md`
   is living and pinned by tests. The design has only archived specs. Each agent builds its page cold and invents its
   own layout; a fix lands in one page, never in the system.

Goal: **a design system that holds when several subagents redesign pages in parallel** — written rules, a look, a
quality bar, building blocks that contain the rules, and checks that fail the build when a rule is broken. The Sync
page is the reference that proves the system and shows agents what "done right" looks like.

Success:
- Every page looks calm and in proportion at 1100 × 700, 1280 × 800 and 2560 × 1440.
- A user understands a panel before reading its words (numbers, bars, rings, colour + shape).
- A subagent given only the page brief (§9), the design-language doc and the gallery produces a page that matches the
  reference page's quality without inventing new patterns.
- A rule break fails `npm run verify`.

## 2. Scope

**Phase 1 (this spec's plan), done by the main agent itself:** the design-language doc, look 2 in the tokens, the
building blocks, the gallery as catalogue, the rule checker and three-size screenshots, the Sync page rebuilt in every
state as the reference, `SplitView` re-based on the new frame so every page stops stretching at once, `CLAUDE.md` and
the page brief.

**Phase 2 (its own plan, written after phase 1):** the rollout to Dashboard, To-do, Library, Playlists, Download
limits, Settings, Setup and the dialogs, by subagents in pairs (§9).

Not in scope: new features or behaviour changes, bridge or engine changes, a light theme, pixel-diff regression tests
(worth adding once the redesign has settled; noted in `docs/issues.md` at the end of phase 2).

## 3. Rules — space

- **Window sizes.** Designed for the default 1280 × 800 (`discjockey/hub/app.py` `SIZE`); must work from the minimum
  1100 × 700 (`MIN_SIZE`) up to 2560 × 1440. **More space shows more, never bigger:** type, controls, cards and
  buttons have fixed sizes. Extra width reveals optional columns; extra height shows more rows.
- **Exactly two page frames.** Every page uses one:
  - **List + panel** (`ListPanelFrame`): sidebar 168 px · list area · panel docked at the right edge, **360 px**, or
    **320 px** while the window is narrower than 1240 px (one fixed step, never fluid). The list area takes the rest;
    its content grows to **900 px** (`wide` variant for the Library table: **1200 px**), then centres in the list area.
    The panel never takes free width.
  - **Single column** (`ColumnFrame`): content up to **900 px**, centred. For the running sync, the end screen,
    Settings and Setup.
- **Panels** (`Panel`): fixed `head`, one `fill` area that grows and scrolls, fixed `foot`. The `fill` area holds the
  list of unknown length (playlists, tracks); everything else keeps its natural height and never shrinks. The page's
  main action sits in `foot` and never scrolls away. If even the `fill` area's minimum (3 rows) doesn't fit, the whole
  panel body scrolls while `foot` stays.
- **Optional columns** appear through container queries on the list (`@container`), never through window media
  queries, so a column depends on the list's own width.
- **No horizontal scrolling, ever.** Long text ends in "…" and shows in full in a tooltip (`title`).

## 4. Rules — visual grammar ("show before tell")

- **Every quantity is a number plus a visual:** bar, ring, day bar or a count column.
- **Every state is colour plus shape:** badge, dot or icon. Never colour alone, never text alone.
- **Everything sits in a container:** a card, a grouped list or a table shell (`Surface`). On the bare background
  only: the page title and its status line, section labels, and one-line hints directly under the control they
  explain.
- **Each kind of choice has exactly one form:**

  | Choice | Form |
  |---|---|
  | on/off, several items | `ToggleGroup` of `ToggleRow`s: switch · cover/icon · name · count, header "N of M on" with All · None, search from 7 rows |
  | one of up to 6 | `Segmented`, with counts where useful |
  | one of many | a selectable list |
  | filters over a list | `Segmented` on one line, never wrapping; what doesn't fit goes into its "More" menu |
  | a single on/off setting | a switch in a row of a grouped list |

- **Rows sit on a column grid:** counts right-aligned in a fixed column with tabular digits; covers the same size
  within one list; badges in their own column.
- **Button hierarchy:** one filled orange button per screen (per dialog in a dialog); secondary actions outlined; minor
  ones text links.
- **Colour has fixed jobs:** orange = action and selection; the quality colours (green, yellow, red, purple, grey) =
  quality only; red also = a problem; yellow also = waiting or limited (a warning: `NoteCard` `warn`, the Download
  limits dot in the sidebar). No other colours.

## 5. Rules — look ("look 2": OLED with depth)

- Background pure black `#000`. Text colours stay as today (no pure white; static chrome dimmed), except that no text
  falls below 4.5:1 on its surface: labels and counts `#7a7a80` (`--text-label`), sidebar items `#7c7c84`
  (`--text-nav`). Both stay clearly dimmer than secondary text `#9a9aa0`, so static chrome is still dimmed.
- **Surfaces** are very slightly raised: fill `linear-gradient(#0f0f12, #0a0a0c)`, 1 px border
  `rgba(255,255,255,.07)`, inner top highlight `inset 0 1px 0 rgba(255,255,255,.04)`, radius 12. Lists:
  `linear-gradient(#0c0c0e, #08080a)`, row dividers `rgba(255,255,255,.045)`.
- **Sidebar:** 168 px, fill `linear-gradient(#0b0b0d, #070708)`; the selected page is a rounded pill
  `rgba(255,255,255,.07)` (radius 7), replacing the orange side bar. Panel background `#040405`.
- **Controls:** border `rgba(255,255,255,.09)`, fill `rgba(255,255,255,.03)`, radius 8; hover
  `rgba(255,255,255,.035)`.
- **Primary button:** `linear-gradient(#ff6a30, #f2521a)`, inner highlight `inset 0 1px 0 rgba(255,255,255,.25)`,
  glow `0 4px 14px rgba(255,90,31,.22)`, radius 10. Only one per screen.
- **Type scale** (px): 11 labels (uppercase, tracking .7) · 12 small · 13 body · 17 title · 22 page title
  (−0.02 em) · 30 stat numbers (−0.03 em, tabular) · 44 the countdown only. No other sizes.
- One accent `#ff5a1f` (text on black `#ff8a5a`); quality colours as today.

## 5a. The page header (`PageHeader`, Task 10A)

Every page starts with one `PageHeader`; a page never builds its own title row. The one exception is the Setup
wizard, whose steps carry their own 17 px headings (phase 2, `docs/issues.md`).

```
[Title · status line] .............................. [page actions] [Spotify read 2 min ago  ↻ Read Spotify]
```

- **Anatomy, left to right:** the title (22 px, `--fs-h1`), then on the same baseline an optional status line (12 px,
  `--text-label`: "18 tracks are not lossless yet", "10 tracks · 60 % lossless"); at the right the page's own
  actions (`actions` snippet: Library's search, the end screen's Full report), then the **Spotify slot** (`spotify`),
  always last, so its right edge is the content's right edge. Title and status line end in "…" (the status line gives
  way first); the right side never shrinks. The header aligns on the title's baseline: the status line, the slot's
  line and the controls' labels sit on it (centred, the slot's 12 px line sat 3.8 px above it).
- **The Spotify slot** shows Spotify's status and its control: "Spotify read 2 min ago · ↻ Read Spotify", while
  reading "Reading · 3 of 7 · Stop reading", a Spotify problem as the compact problem line. While Spotify can't be
  read (no login, not set up, login expired: the shared `spotifyMissing` store) the shell's banner says so with its
  Set up link, so the slot shows only the last read, if any, with Read Spotify off ("Connect Spotify first."). It is on the pages whose content
  comes from the last Spotify read: Dashboard, Sync (before the start) and To-do. `SpotifyStatus` is placed only by
  this slot (rules checker rule 7).
- **A state said once:** a page that shows the read in progress and Spotify problems as cards in its body
  (`spotifyInBody`: Sync before the start, with its reading card and offline card) keeps only the control in the slot:
  "Stop reading" while reading, otherwise the last read and Read Spotify without the OFFLINE badge. The control never
  leaves its place; the state isn't repeated.
- **Edges:** the header has no padding of its own and spans its frame's content box. In `ListPanelFrame` it spans the
  list area's content (900 px, 1200 px `wide`, centred), never the panel, which has its own head; in `ColumnFrame` the
  900 px column; on a plain page (phase 2 pages not yet on a frame: All runs, Settings) the page's padding box, with
  the frames' padding (`--s-4` top, `--s-5` sides). So the title starts where the rows start and the Spotify slot ends
  where they end, at 1100, 1280 and 2560.
- **Height:** at least 34 px whether or not it holds controls, and the content below starts `--s-3` under it (the
  frames' gap; Settings and Limits use it too), so the content starts at the same y on every page.

## 6. Rules — motion and text

Motion:
- **Press feedback** instantly on pointer-down: `scale(.97)` (big buttons `.98`), 100 ms ease-out.
- **State changes that confirm a decision** (switch knob, on/off colour): 200–260 ms, `cubic-bezier(.22, 1, .36, 1)`.
- **Hover:** 120 ms (`--t-hover`), same curve. **Selection that follows navigation or a keyboard arrow** (sidebar,
  `Segmented`): instant, no animation.
- **Value changes** that happen on their own (a bar, ring or quality bar after a refresh): ~420 ms, same curve. A
  value shown for the first time is drawn at once; bars don't fill on load (entrance limit below; seen many times a day).
  A value change the user just caused (the day bar after an amount click): 280 ms (`--t-reply`).
- **Live progress** during a sync moves linearly and smoothly; nothing bounces.
- **Never blocking:** CSS transitions only (interruptible), no input waits for an animation; no entrance animations
  beyond a ≤ 150 ms fade. Popovers and menus (InfoTip, "More", context menus) fade and grow from `scale(.97)` out of
  what opened them (`transform-origin` at the trigger), 140 ms (`--t-pop`); they close at once. Modals stay centred
  and only fade.
- **Reduce motion** (`prefers-reduced-motion`): fades only.

Text (adds to `CLAUDE.md`'s plain-English rule):
- Panels use labels and numbers, not sentences.
- A hint (`Hint`) is at most one line, directly under its control.
- Anything longer goes behind an ⓘ (`InfoTip`) or into a `NoteCard` (icon + up to about three lines, like Download
  limits' "Honest note"). Never loose on the background.

## 7. Building blocks

All in `hub-ui/src/lib/components` (frames in `hub-ui/src/lib/frames`), exported from the index, each in the gallery
in every state.

| Block | What it does |
|---|---|
| `ListPanelFrame`, `ColumnFrame` | The two page frames of §3. Snippets `main`/`panel` and `content`; `wide` for the Library table. |
| `Panel` | `head` / `fill` / `foot` snippets with the §3 behaviour. |
| `Surface` | The raised container: `card` (padded), `list` (grouped rows, optional header), `table` (shell). Sets `data-surface` for the checker. |
| `ToggleGroup`, `ToggleRow` | §4 on/off rows; header with "N of M on" and All · None; search field from 7 rows; used inside `Panel`'s `fill` when long. |
| `Segmented` | One choice of up to 6, optional counts and colour dots, "More" menu for the rest; never wraps. Replaces filter `Chip`s. |
| `StatCard` | Big number (30 px) + unit + label; optional bar or ring under it. |
| `DayBar` | Today vs later split (solid vs striped), 280 ms value motion (it answers the user); variants: no daily limit (one segment), limit reached (today = moves only). |
| `Hint`, `InfoTip`, `NoteCard` | The only three ways to put explanation text on screen. |
| `ListRow` | The row grid every list uses: fixed lead columns (tick, cover), a flexible name, fixed trailing columns (badge, count, action); optional columns declared per list and shown by container query. Sync uses it in phase 1; `TrackRow` is re-based on it in phase 2 with To-do and Library, so those pages don't change before their turn. |
| `PageHeader` | §5a: title · status line, page actions, the Spotify slot; spans the frame's content. The only place for `SpotifyStatus`. |
| `Button` (reworked) | `filled` (look 2 fill, `data-primary`: the one main action of a screen, or of a dialog inside it), `primary` (orange outline: a forward step that isn't the main one), `secondary`, `danger`, `link`, `icon` (an icon-only row action); natural width, `wide` only in a panel foot. |

- The **gallery** (`hub-ui/src/lib/dev/Gallery.svelte`) becomes the catalogue: every block in every state, with the
  rule it carries in one line. A page agent reads it before designing.
- **Old blocks** — `SplitView`, `Chip`/`ChipGroup`, `Card` (→ `Surface`), `Tile` (→ `StatCard`), `SectionLabel`
  (→ `Surface` label), `--main-w`, `--panel-min` — are marked outdated in their
  file headers and listed in one place (`hub-ui/src/lib/outdated.ts`); a vitest test fails when a page flagged as
  redesigned imports one. In phase 1 `SplitView` is re-based on `ListPanelFrame`, so every page stops stretching at
  once; it and the other outdated blocks are deleted when phase 2 ends.
- A page that needs a pattern no block covers **must not build it locally**: the agent stops and flags it; the
  pattern is added centrally (block + gallery + doc) and then used.

## 8. The Sync page (reference)

Frame per state; everything not mentioned keeps today's behaviour (`hub-ui/src/pages/sync`, spec "hub" 5.2).

| State | Design |
|---|---|
| **Before the start** | `ListPanelFrame`. List: one `Surface list` per playlist section (header: name · "N of M ticked" · Tick all · None, foldable); rows `ListRow` (tick · cover · Artist – Title · tag column · ⊘). Optional column at ≥ 680 px list width: why the track is in the run (new / not found last time / from <folder> / moved by hand / bought / weekly check) and "next sync" for ticked rows beyond today (muted words led by a 6 px yellow dot; when every ticked row of a section waits, the head says "· N next sync" once and the rows drop it). A section gets the column only if it can fill it (a tag, or a download that may wait). The folds below share the plan's grid (cover under the fold's label, names under the plan's names). Panel (`Panel`): head = `StatCard` count + `StatCard` "run time" ("~20 min", "~2.5 h", "0 min" with nothing to run; both count what runs today, as Start does), then a card with `DayBar`, the amount `Segmented` (presets, ✦ on "fits today") and one line "✦ fits today · 60 a day" with Download limits → at its right; a `Hint` "N ticked wait for the next sync" only when that differs from the DayBar's Later; fill = Playlists `ToggleGroup` (up to its rows' height); then What to do `ToggleGroup` (natural height, drawn kind icons, no search); foot = Start sync. Below 680 px list width a row's why becomes a mark before ⊘ (kind icon, yellow dot). Mockups: `sync-look2.html`, `sync-panel-many.html`. |
| several services (no Qobuz, or fallbacks with limits) | Under the day card, a small `Surface list` of its own (not nested in the card): one row per service, name · mini bar · "U of L" ("~4 of 30" for an estimate); a backup behind Qobuz gets no bar but a muted "backup" and "30 left"; the full sentence in the row's tooltip. |
| no daily limit (free sources only) | `DayBar` one segment "Today N", `Hint` "No daily limit" under it; no Later. |
| limit reached | `DayBar` "Today: moves only" + Later N; a `NoteCard` (yellow), title only, "Downloads start tomorrow"; Start reads "Start sync · N moves". |
| more ticked than fit today | `DayBar` shows the overflow in Later; ticked rows beyond today show "next sync" in the list. |
| **Reading Spotify** | `ReadingCard` as a neutral `Surface card`: spinner · "Reading your Spotify playlists" · "3 of 7 · <folder>" at the right edge, the bar under them; above the dimmed old plan (or the up-to-date card) with the `Hint` "What's below is from the last read · it updates when this is done", or alone without it. |
| **Up to date** | Main: a `Surface card` (good tone) with a drawn green check, "Up to date", one line "5 playlists · 49 tracks", + Add a playlist (link) under the text (Read Spotify lives only in the page header, §5a); Never download as a foldable `Surface list`. Panel (`Panel`): the last sync counted as its end screen counts it: a full-width `StatCard` "added in the last sync" with the quality bar and legend, then its time and See what came in → on one line; "moved" and "need you" as two half `StatCard`s; `after` = Could be better as a `Surface list` of `ListRow`s (icon · label · count ›, the whole row opens To-do). While the last sync loads, the same StatCards wait (`value={null}`, `QualityBar by_quality={null}`). |
| offline, console running | Offline (or another Spotify problem): `ProblemCard` as a problem-tone `Surface card` above the plan, never the bare compact line. Console: with a plan, Start off with the `Hint` "A sync is running in the terminal" (the full sentence in its tooltip), and the view takes the shell's console banner over (`sayInBody`); without a plan (up to date, empty, preview error) the banner says it. |
| **Running** | `ColumnFrame`. Header status becomes a run progress bar "4 of 6" with the time left and Qobuz usage as small stats; the now card (cover, 5-step bar, bytes/seconds) as a `Surface card`; the filters become a `Segmented` (All · Lossless · Lossy · Problems, with colour dots and counts); Problems / Done / Up next as `Surface list`s with a badge column; foot: Stop safely (secondary) + one-line `Hint`, or the reason a stop failed as `Hint tone="problem"`. Pause/break: countdown ring as today, inside the now card. |
| **End** | `ColumnFrame`. Summary card: `StatCard`s (added · moved · need you) + quality bar with legend; Needs you, Added to your library (one `Surface list` per folder with Show in Finder) and Other changes as `Surface list`s; Done is the one primary button; Full report a link. |
| failed, crashed | A `ProblemCard` (problem-tone `Surface card`; crashed carries Show reports folder in its `actions`) + the end screen's structure. |

Every existing Sync fake scenario and `shots.json` entry keeps working; each state gets shots at all three sizes.

## 9. Checks and the rollout playbook

**Three sizes.** `hub-ui/scripts/shots.mjs` gets `--sizes` (default: all three) and runs every shot at 1100 × 700,
1280 × 800 and 2560 × 1440; file names gain the size (`sync-before@1280.png`).

**Rule checker** (`hub-ui/scripts/rules.mjs`, Playwright WebKit, against the fake-mode dev server it starts itself),
run on every shot of every page flagged as redesigned (listed in `REDESIGNED` in `hub-ui/src/pages/designSystem.ts`,
a plain list so vitest can read it; other pages are skipped and counted in the summary line, `--force` checks one
anyway while it is being built). It fails on:
1. horizontal overflow of the document or any scroll container;
2. a frame's content wider than its maximum (900 / 1200 / column 900), or the panel wider than 360;
3. a button wider than its natural size (its content + padding), or more than one `[data-primary]` visible per screen
   or dialog;
4. at 1100 × 700: an interactive element outside the viewport and not inside a scrolling area; a `Panel` foot not
   fully visible;
5. a text block longer than 90 characters not inside `[data-surface]`, `NoteCard` or `InfoTip`;
6. a computed `font-size` outside the type scale, or a computed text, background or border colour that isn't a token
   value (tokens read from `:root` at run time; transparent allowed);
7. a Spotify status (`[data-spotify-status]`) outside the page header (`[data-page-header]`), §5a.

The fake-mode dev toolbar and anything else marked `data-dev` is ignored. `npm run verify` runs the checker (it starts
and stops the fake dev server). The outdated-block test (§7) runs in
vitest.

**The page brief** (`docs/hub-page-brief.md`, the playbook a page agent gets), always in this order:
1. Read `docs/hub-design-language.md`, the gallery and the Sync reference; screenshot the page's current states at
   three sizes.
2. List every rule the page breaks (an audit, in the agent's report).
3. Make an HTML mockup in `docs/hub-mockups/design-system/<page>.html` using only existing blocks — or stop and flag a
   missing pattern.
4. Main agent reviews the mockup against the rules; the user approves (mockups of a pair are shown together).
5. Build the page, flag it `designSystem: true`, keep every fake scenario, add shots for new states.
6. Done when `npm run verify`, `npm run build`, `npm run smoke` and the rule checker are green at all three sizes and
   the main agent has looked at the screenshots.

**Rollout order (phase 2).** Pairs, at most two subagents at a time, complex design work on the strongest model:
1. To-do + Dashboard (the user's sharpest complaints) · 2. Library + Playlists · 3. Download limits + Settings ·
4. Setup + dialogs (Wrong song, confirm). Blocks needed by both pages of a pair are built by the main agent before the
pair starts.

## 10. Documents

- **`docs/hub-design-language.md`** (new, living): §3–§7 as rules, each with a do and a don't, screenshots from the
  Sync reference, and the list of blocks. Updated in the same commit as any change to tokens or blocks.
- **`CLAUDE.md`:** layout table gains the design-language doc, the page brief and `lib/frames`; a rule "UI work reads
  `docs/hub-design-language.md` first; pages only use the blocks; a missing pattern is added centrally"; the
  screenshot command mentions the three sizes and `rules.mjs`.
- **`hub-ui/src/lib/styles/tokens.css`:** look 2, the type scale, motion tokens; `--main-w` and `--panel-min` removed
  when phase 2 ends.
- The phase 1 plan moves to `docs/archive/` (now `docs/archive/pre-public/`) when phase 1 is done; this spec stays in `docs/` for phase 2 and moves
  with the phase 2 plan.

## 11. Decisions and reasons

- **Option B for space** (panel docked, list grows to a limit, then centres) over centring the whole page: a big
  screen should show more (columns, rows), like Apple Music or Finder; the original "never stretched rows" wish is
  kept because rows only widen when they gain columns.
- **Look 2** over keeping the outline-only look or going macOS grey: structure becomes visible without lines
  everywhere, while keeping the pure black (OLED care) and the app's own character.
- **Panel steps 360 → 320 below 1240 px:** at 1100 px a 360 px panel would leave To-do's rows about 530 px.
- **Note cards allowed:** Download limits' "Honest note" works because it's short and on its own card.
- **Rules in blocks plus a checker** over a doc alone: a doc depends on every agent reading and applying it, which is
  how the current state came about; pixel diffs deferred because a redesign trips them constantly.
- **Agents may not invent patterns:** parallel agents would otherwise produce one dialect per page.
- **An "off" row stays readable (Task 6):** in `ToggleRow` and `ListRow` an off row's name is `--text-muted` (its
  count `--text-label`) and its lead dims to `--dim-cover`; the switch or tick carries the state. The design audit's text rule is narrowed:
  `--text-disabled` is for things the user can't act on (`disabled`/locked), not for an off item they read to decide
  whether to turn it on (about 2:1 contrast was too low).
- **Focus rings inside a list follow its corner:** `border-radius: calc(var(--r-surface) - var(--bw))` with the inset
  ring, so the first and last rows' rings are concentric with the Surface instead of clipped square (nested
  corners are concentric, design audit).
- **Surface head hierarchy (Task 9):** the label is a title, sentence case, 13 px semibold `--text`; the summary
  follows it at 12 px `--text-muted`; header actions sit alone at the right edge. Before, an 11 px grey uppercase
  caption sat beside an 11 px grey count and grey links, so nothing read first and the count read as part of the
  links (grouping by proximity). Uppercase also rewrote the user's folder names ("HARD_BOUNCE" beside "Hard_Bounce"
  in the sidebar and panel, a consistency break) and widened long names. Like macOS System Settings' group titles,
  a group is named in sentence case; uppercase captions stay for values (StatCard) and panel captions.
- **Foldable and sticky Surface heads (Task 9):** `foldable` makes the label the disclosure button (chevron in a
  16 px box, the tick's width, so the label starts at the rows' covers in Sync); `sticky` keeps a long list's name and
  Tick all · None in view while its rows scroll. A list Surface clips with `overflow: clip` instead of `hidden`, which
  isn't a scroller, so its head can stick to the frame's scroller (`--sticky-top`, set by ListPanelFrame). The
  hairline under a head sits on the head, so it stays with it when stuck. Sync's old `Fold` is gone.
- **ListRow's optional column from 680 px list width, not 760 (Task 9):** measured: at the default window (1280) the
  Sync list is 713 px wide (1280 − 168 sidebar − 360 panel − 2 × 20 padding), so with 760 the "why" column never
  showed at the default size. At 680 it shows at 1280 with a 328 px name column (about 45 characters), and stays
  hidden at 1100 (573 px list, where it would leave the name 221 px).
- **An off row keeps its tick at full strength (Task 9):** ListRow dims an off row's cover or icon, not a lead item
  marked `data-mark` (the tick): a dimmed empty tick box all but vanished, and the tick carries the state (as the
  switch does in ToggleRow).
- **ToggleRow's column gap is `--s-3` (12 px)**, ListRow's gap, instead of a raw 10 px (Task 9).
- **"next sync" is a yellow dot plus muted words (Task 9 fix 1):** with today's limit used up, 118 rows each
  carried a saturated yellow "next sync"; the repeated word outshouted the track names and the list read as one
  warning (hierarchy: the most important thing most obvious). The dot keeps §4's yellow for waiting and the words
  stay secondary; it also separates the tag from it, so no "·" is needed. When every ticked row of a section waits,
  the head's count says "· N next sync" once and the rows drop the label (the same fact on every row is noise). The
  row's tooltip and description still say it. Shared as `Why` (Sync and the Gallery).
- **One grid for the plan and its folds (Task 9 fix 1):** fold rows keep the plan's 52 px lead with an empty
  16 px tick slot, so their covers sit under the fold's label and their names under the plan's names; dropped and
  ambiguous rows get a cover too. Before, fold labels started at the plan's cover column while their rows' covers
  sat at the tick column (measured x≈358 vs 320 at 1280), aligned with neither.
- **Button `icon` (Task 9 fix 1):** an icon-only row action (⊘) is a Button variant, not a local button: a
  26 px square, no box at rest, `--text-label`, a drawn 16 px SVG (stroke 1.6, the chevron's); `destructive` turns
  it red on hover. The ⊘ glyph at 11–13 px rendered as a faint ring (as ▸ did), and Sync and the Gallery had two
  spellings of the control. Press .97 like small buttons; off keeps no box.
- **Surface `bulk` (Task 9 fix 1):** "All · None" (or "Tick all · None") in a list head is a Surface prop, so
  ToggleGroup and Sync share one spelling; the separator matches the small links (`--fs-small`). They had been
  written twice with different separator sizes.
- **The why column only where it can be filled (Task 9 fix 1):** a section gets `--row-cols-wide` only if a row has
  a tag or is a download that may wait (the plan holds more downloads than today's limit leaves). A section of plain
  new tracks gave its names' last 200 px to a blank column. The test doesn't depend on ticks, so columns never jump;
  a section that may wait keeps the column blank until a row waits (accepted).
- **A DayBar segment is never narrower than its label (Task 9B):** with "All 195" picked under a 10-a-day limit,
  "Today 10" got a 12 px sliver beside "Later 185" and dropped its label, so the number the user had just picked
  vanished (measured on `sync-long-plan-all`). Each present segment's label is measured (a hidden twin) and its
  flex-basis is that width plus padding, in px; its share grows on top; a missing segment's basis is 0. Fix round 1:
  the first form, `min-width: min-content`, can't be interpolated and switched with `gone`, so the floor snapped in
  and out while the share slid (§6: a split that gains or loses a side slides); flex-basis is transitioned.
- **ToggleGroup `search={false}` for app-defined sets (Task 9B):** the search from 7 rows is for the user's own
  lists (playlists). What to do's kinds are a fixed set of at most 7 the app defines; with all 7 present the search
  cost 44 px in a panel that already scrolls at 1100 × 700 and pushed Playlists below its 3-row minimum (`sync-many`).
- **Panel `fill` is a slot; the list owns its 3-row minimum (Task 9B fix round 1):** a guessed 194 px on `fill` and
  150 px on ToggleGroup `grow` disagreed with each other and with the real 205 px, so Playlists showed 2 rows and a
  sliver (`sync-many@1100`). `fill` is `display: contents`, so the list is the body's flex item and its own minimum
  holds: ToggleGroup `grow` = head `--h-list-row` + rule + [search `--h-ctl` + 2 × `--s-2`] + 3 × `--h-row` + 2 row
  rules + 2 borders = 159 px, 205 px with a search (measured 159 / 205 in WebKit, rows 38 px). A `min-content`
  minimum on `fill` would be the list's full height, so it could never shrink.
- **One scroll edge fade, shorter and not to transparent (Task 9B fix round 1):** the `edgeFade` action marks the
  ends of a scroller with content beyond them; base.css fades a marked end over `--edge-fade` (16 px) to
  `--edge-fade-to` (35 %). ToggleGroup's rows and Panel's body use it. The old 24 px fade to transparent sat on the
  third Playlists row, so its on-switch read grey (`sync-many@1100`); and the Panel body cut What to do with a hard
  edge above the foot at 1100 (`sync-long-plan-all`, `sync-limit-reached`), with no sign of more below.
- **Panel `fill` grows to its list's height, not past it (Task 9B):** at 2560 a 5-row Playlists group stretched into
  a 570 px empty box with What to do pinned under it (`sync-before@2560`, space left over, §12). `fill` and the
  ToggleGroup `grow` are `flex: 0 1 auto`: they take spare height up to their rows, shrink to the 3-row minimum and
  scroll inside; the spare height sits above the foot, by Start (the mockup's `margin-top: auto` button).
- **Sync kinds have drawn icons (Task 9B):** `KindIcon` (one SVG per kind, stroke 1.6) replaces the ↓ ↻ ⇄ glyphs and
  covers all 7 kinds, shared by What to do, the plan rows' narrow mark and the Gallery; text glyphs at 11–13 px
  rendered thin and uneven, as ▸ and ⊘ did.
- **The why column's narrow form (Task 9B, I2):** below 680 px list width a row keeps its why as a mark before ⊘: the
  kind's icon (tagged rows) and the yellow "next sync" dot, in a fixed 26 px slot so marks line up down the list
  (trailing column 60 px in sections that have a why column). Words stay in the tooltip and description.
- **A run's count is what runs today (Task 9B, fix round 1):** the count card, the run time and Start count the ticked
  actions minus the ticked downloads that wait for the next sync (`runCount`); when that is only the moves it says
  moves ("1 move this run", "Start sync · 1 move"). "196 tracks this run" sat beside "10 min", "Today 10" and
  "185 wait" (`sync-long-plan-all`); the approved mockup counts today. Nothing runs today: "Start sync", "0 min".
- **Run time reads "~20 min" (Task 9B fix round 1):** the label "about" under "—" or "1–2 min" said nothing. The card
  is "run time", the estimate is marked by "~" as the service rows' "~4 of 30"; below 2 h in minutes ("~75 min";
  "~1 h 15 min" was cut off at 1280, `sync-no-qobuz`), then hours to the half ("~2.5 h"); nothing to run: "0 min",
  so the card keeps its place instead of the head reflowing.
- **One time format for every estimate (Task 9B fix round 2):** `estimate` / `estimateText` in `lib/format.ts`:
  "~75 min" below 2 h, then hours to the half ("~2.5 h"). Sync's run time card, Dashboard's ready line, Download
  limits' run length and the live "~12 min left" all use it; Dashboard said "approx. 1 h 15 min" for Sync's "~75 min".
  The compact form wins because the card has the least room ("~1 h 15 min" was cut off at 1280) and a minute-exact
  "1 h 15 min" claims more than an estimate knows; "~" is the service rows' estimate mark. Measured times (a run
  that took "1 h 2 min") stay `minutesLong`: they are facts, not estimates.
- **Start is off when nothing runs today (Task 9B ruling, fix round 2):** ticked, but only downloads that wait for
  the next sync (`runsNothingToday`): a run would only re-read Spotify, log in to Qobuz, queue nothing and add an
  empty Last runs entry. The label stays "Start sync" (the main action keeps its name and place; a disabled button
  whose text changes reads as a different control) and the reason is a Hint under it, "Nothing to run today ·
  downloads start tomorrow", where the terminal-sync reason already sits. It stays beside Start even when the
  limit NoteCard has scrolled away at 1100. Raising today's limit turns Start back on by itself.
- **A grow group's minimum fits the group (Task 9B fix round 2):** up to 3 whole rows, fewer when it has fewer (2
  playlists no longer leave an empty box under the last row), counted on all rows, not the search result, so the
  box doesn't jump while searching; with more than 3 rows a peek of the next row sits under the end fade
  (the iOS peek: a cut exactly on a row edge read as the whole list); half a row since issue 10 (below).
- **Panel's fill slot stays box-less; edgeFade looks through it (Task 9B fix round 2):** `display: contents` is kept
  because it makes the list's own minimum the one that holds. edgeFade watches the children of a box-less child
  in its place (sizes) and the slot itself (rows coming and going), so the body's fade follows the group.
- **Service rows are a list of their own under the day card (Task 9B, review M1):** §8 first put them inside the
  DayBar card; a list nested in a card is a container in a container (§4), and as a separate `Surface list` the
  rows line up on a fixed number column. A backup behind Qobuz gets no bar (an empty bar read as unused or
  broken) but a muted "backup", with "30 left" in the number column.
- **Less repeated text at 1100 (Task 9B fix round 1):** the limit NoteCard is title-only ("Downloads start
  tomorrow"; "Moves still run" repeated "Today: 1 move" and Start); the overflow Hint shows only when the ticked
  downloads that wait differ from the DayBar's Later. NoteCard's text is optional for this.
- **Shots start from defaults (Task 9B):** the shot harness shares one browser context, so a shot that changed a pref
  (Sync's playlists or amount) carried it into every later shot and size (`sync-many-all-off` left the next sizes
  with no rows). `openShot` clears localStorage on each page's first load.
- **ProblemCard is a Surface card (Task 9C):** the full card is a `Surface card` with the problem tone and
  `data-note="problem"` (its hint and message may be long, as in a NoteCard); `compact`, the one-line form inside a
  header, row or dialog, keeps no box (a box there would be a container in a container, §4) but keeps `data-note`.
  Its link action is a `Button` with `href` instead of a local outlined link (one spelling per control). Sync shows
  its Spotify problem as the full card even above a plan: the compact form left a red sentence loose on the
  background (§4).
- **The reading card is neutral (Task 9C):** the old card had an orange border and wash; orange is action and
  selection (§4) and a read in progress is status. The bar keeps the accent (the job that runs); "3 of 7 · <folder>"
  moved to the card's right edge, where counts sit. The first read has no hint: "What to download shows up here"
  repeated the panel's own "The plan shows here when Spotify is read". The old "The plan below is from the last
  read" also showed over the up-to-date card, which is not a plan; the hint now says "What's below".
- **Up to date says one line of numbers (Task 9C):** "Nothing new to download in your 5 playlists (49 tracks)." plus
  "Add tracks to these playlists in Spotify…" became "5 playlists · 49 tracks" (§6: labels and numbers); the ✓ glyph
  became a drawn check (as KindIcon, ⊘); the actions start under the text, so the card has one left edge.
- **The last sync counts as its end screen does (Task 9C):** `lastSyncStats(run)` (endModel, also used by the end
  screen) reads the run's details: a `RunSummary`'s `lossy` can't be split by quality, so a quality bar built from it
  would call a weak file "good lossy". Added gets a full-width StatCard with the bar and legend as its visual (§4);
  three cards in a row would be 85 px wide at 1100 (53 px inside), and a 3-digit count at 30 px needs about 56 px.
  The panel waits for those details (`lastSyncView`): the cards themselves hold their place, with "—" and a
  waiting QualityBar (final review fix A, I4, below), so nothing moves and no number corrects itself when they draw; a reply for an older run is
  dropped (checked by run id); only if the details fail do the summary's counts show, without a bar. The newest run
  comes from the dashboard's `last_runs[0]` (no separate `runs()` call), and a finished run's details load once.
  Up to date with no sync ever and nothing in Could be better shows the frame's empty panel, "Your last sync shows
  here." (fix round 1).
- **Skeleton has a card shape (Task 9C fix round 1):** `shape="card"` gives the placeholder the card radius it stands
  in for; text placeholders keep the badge radius. A placeholder should have its content's shape and height, or the
  page jumps when the content draws (§6 motion: no layout shift).
- **EmptyState titles are balanced (Task 9C fix round 1):** `text-wrap: balance` on the block's title. At 1100 the
  panel's "The plan shows here when Spotify is read." left "read." alone on its line; a short centred message wraps
  into even lines everywhere it is used.
- **Service rows use the short service name (Task 9C fix round 1):** "YouTube", not "YouTube Premium" (shared
  `serviceName` in `format.ts`). A row answers "which service, how much"; the plan ("Premium", "Go+") is account
  detail that Download limits and the row's tooltip show with the full name. At 1100 the full names were cut with
  "…" in the 110 px name column; short names fit without narrowing 9B's 132 px bar and number column.
- **The console Hint is one short line (Task 9C):** "A sync is running in the terminal. Its progress shows there."
  ended in "…" at 1280 (a 320 px foot); the Hint is "A sync is running in the terminal", the full sentence stays in
  Start's tooltip and the app's banner.
- **The page header is a block with a Spotify slot (Task 10A):** it was never designed. Dashboard set the Spotify
  status beside its greeting on the left (its own `.head`), Sync and To-do at the right edge through PageHeader's
  `right`; Settings sat 12 px further right and 8 px lower than every other title (its own `--s-6`/`--s-8` padding).
  §12 makes consistency absolute and Apple's familiarity rule says the same element lives in the same place, so the
  slot is part of the block (`spotify`), always last at the right edge, and pages only say whether they show it. The
  right edge, not beside the title: on Sync and To-do the slot meets the hard edge the search field and the rows set
  (§12 edges on purpose); beside a short greeting it floated mid-row and moved with the greeting's length. The header
  spans the list, not list + panel: the panel has its own head (Sync's count cards, To-do's track), and at 2560 a
  header across both would put Read Spotify over 900 px from the content it refreshes (grouping by proximity). Title
  and status line now share a baseline (they were centred on each other, so the 12 px line sat off the title's
  baseline; Apple typography: a pair of sizes reads as one line on a shared baseline).
- **Spotify's state is said once on Sync (Task 10A, from the 9C review):** while reading, the header said "Reading ·
  3 of 7" beside the reading card's "3 of 7 · <folder>" and bar; offline, an OFFLINE badge beside the red offline
  card. The cards stay: they are where the user looks (the top of the plan they came to review), they carry the bar
  (§4: a number plus a visual) and the hint that the plan below is old. The slot keeps the control in its place
  (`spotifyInBody`: "Stop reading", or Read Spotify without the badge). The offline card has no Retry (fix round 1,
  10A review I1): the slot's Read Spotify sits about 40 px above it and does the same read, so the card explains and
  the slot recovers (one action per intent).
- **Read Spotify has one place (Task 10A):** the up-to-date card no longer repeats it; the header slot right above it
  is its one place on every page (§12: a shared element is placed by its block). The card keeps + Add a playlist,
  the other way to get more to sync. Fix round 1 applied it on every page: Sync's offline card lost Retry,
  Dashboard's ready card lost "↻ Read now", and the `no_preview` empty state lost its button. Unread, both say
  "Nothing to review yet." and point up ("Read Spotify above to see what changed in your playlists.") instead of
  repeating "Spotify hasn't been read yet", which the slot says. While Spotify can't be read the ready card doesn't
  point (the button is off; the banner or the setup card says why).
- **The shell's banners stay off on Sync's before-start view (Task 10A, fix rounds 1–2; superseded by "A page takes a
  banner over through one shell store", final review fix A):** the console banner and the
  Hint under Start both said "A sync is running in the terminal". The Hint wins: it sits directly under the control
  it explains (§6), where the user looks when Start doesn't respond, and Start's tooltip holds the full sentence. The
  same holds for the Spotify banner: the before-start view's Spotify card says a missing or expired login above the
  plan, where it bites, and it reads the same `spotifyMissingKind` store as the banner, so it also says a login that
  is missing before any read failed (round 2: the card had read only the last read's problem, so that state went
  unsaid). The live and end views keep both banners until Task 10B gives them their own place for it. Every other
  page keeps both banners, the only place they say it.
- **A state said once, one action per intent (fix round 1, system rule):** a state is said in one place, where the
  user looks for it, and each intent has one control. Spotify can't be read (no login, not set up, expired) is one
  derived store, `spotifyMissing` (the banner reads its `spotifyMissingKind` sibling), read by the header slot: the banner says it with Set up, the slot
  only turns Read Spotify off, so the slot no longer adds "Discjockey isn't set up yet. Open setup →" (which also
  misnamed a Spotify state). On the first-run Dashboard the setup card says "Discjockey isn't set up yet" with Finish
  setup (the whole wizard) and the banner says Spotify isn't connected with Set up (the Spotify step): two facts, two
  intents; the ready card no longer adds a third line. When a duplicate turns up, remove it on every page, not just the one
  in front of you. One state also has one wording and one link everywhere (round 2): the banner and Sync's card take
  their words from the same copy (`problemCopy(kind, { spotify: true })`): "Your Spotify login has expired." or
  "Spotify isn't connected.", both with "Open setup →" to the Spotify step. The empty state's "Read Spotify above"
  is left out while that button is off.
- **The running sync's numbers have their own card (Task 10B):** "4 of 6 · ~4 min left · Qobuz 1 of 80 today" was
  the header's status line, a quantity without a visual (§4) in 12 px grey. It is now a `Surface card` under the title:
  "4 of 6" at 17 px leads, the time left and Qobuz usage follow as small numbers at the card's right edge, the
  run's `ProgressBar` (finished actions of all, `live` pace) under them, and the engine's last message as the card's
  third line (it was a loose line on the background). Before the count is known it says "Counting tracks…" over the
  indeterminate bar, so the card keeps its place. Fix round 1: the count reads "Track 4 of 6" (a bare "4 of 6" over a
  bar of finished tracks at 3/6 read as a count of finished ones); the run's bar is the `muted` tone, because the
  live card's step and download bars carry the accent and three orange bars in 250 px competed with the track's own
  progress; the card owns today's usage, so the pause card no longer repeats it (`pauseUsage` is gone); while
  stopping, the time left goes (it no longer holds).
- **A stop says "Stopping…" once (Task 10B fix round 1):** it was the title, the card's title and the busy button. The
  title keeps it; the card is the kicker "Current track" over "Finished or cleanly discarded, then the sync stops.";
  the button is busy only for the click's round trip and is off once stopping (fix round 2: a second spinner beside
  the card's said the state again); the foot's hint goes while stopping.
- **The indeterminate ProgressBar moves by transform (Task 10B fix round 1):** the sweep animated `left`, a layout
  property, every frame. It now sits at `left: 0` and slides `translateX(-100%)` → `translateX(333.34%)` (percent of
  its own 30 % width); it stays `.live-anim`, so it runs under reduced motion like the other live state.
- **A foot's hint sits beside its button (Task 10B):** "Stopping is safe at any time" sat at the foot's left edge,
  up to 700 px from Stop safely (grouping by proximity). Hint and button are one group at the foot's right edge; the
  hint is one short line and the full sentence is the button's tooltip. In a `Panel` foot the hint stays under its
  button (§8 before the start), where the foot is narrow. A failed stop replaces the hint with its reason in red,
  one line with an ellipsis and the full text as the tooltip, `role="alert"` (fix round 1): a failed stop is an error,
  not grey help text (apple-design §16, error feedback). `ProblemCard compact` would hide the reason behind the
  kind's generic title, so the line is the page's own.
- **The end screen counts in stat cards, the rest in a notes list (Task 10B):** the headline "2 tracks added" at
  22 px plus "1 moved · 2 need you" in 12 px said three counts in two sizes. Three `StatCard`s count as the
  up-to-date panel counts the last sync (`lastSyncStats`, so the two never disagree) and in its composition (fix
  round 1): added across with the quality bar and legend, then moved · need you as a pair. A row of 2 : 1 : 1 stretched
  moved and need you to the added card's height, about 90 px of empty card under one digit each. The cards stand on
  the background, not inside a summary card (a card in a card is a container in a container, §4). What the
  cards can't count (stopped by you, upgrades to review with Review →, new since the check, checked, waiting for the
  next sync) is one `Surface list` of plain rows under them (`endModel` `notes`), instead of loose lines on the
  background and inside the headline card.
- **Badges line up beside an optional action (Task 10B):** in a list where some rows have Fix → or Review → and
  others don't, the action has a slot of fixed width in the trailing column, so the badges' right edges line up down
  the list (§4: badges in their own column). Fix round 1: every list of the view keeps the slot, also the ones with
  no action (Done, Up next, the folder lists), and both views use one width (64 px, Review →): a stacked column reads
  as one right edge, and list-by-list slots left NOT FOUND 40–64 px short of the badges under it (§12 edges).
- **The new files' lists are titled by their folder (Task 10B):** one `Surface list` per folder, label = the folder,
  summary "N new tracks", Show in Finder ↗ as the head's link (↗: it leaves the app, like Full report ↗). The old
  bare section caption "Added to your library · add the new files in rekordbox" had no container to sit in (Surface
  labels replaced SectionLabel, §7); the added card above already says what they are. The rekordbox step is a `Hint`
  directly above the folder lists, "Add the new files in rekordbox: Show in Finder opens each folder." (fix round 1:
  as a tooltip only, the DJ's main next step was hidden from anyone who doesn't hover); the tooltip stays.
- **A failed sync is its ProblemCard in the end screen's frame (Task 10B):** the brief asked for a `NoteCard tone=
  "problem"` around the ProblemCard; since Task 9C the full ProblemCard is a problem-tone `Surface card` marked
  `data-note="problem"`, so a NoteCard around it would be a card in a card (§4). The title names the outcome, "Sync
  didn't finish", like every other end title ("Sync stopped", "Sync finished"); "Sync" said nothing. Back to the plan
  (secondary) and Done (filled) sit in the foot.
- **ProblemCard `actions` (Task 10B):** a caller's own recovery control is a snippet the card sets beside its own
  action, so it sits with the problem it answers (§4, grouping by proximity). Sync no longer uses it (fix round 1): a
  crash writes nothing into `reports/`, so Show reports folder opened older runs only; Back to the plan is the way on,
  and the engine's crash note is in `docs/issues.md`. A crash under "Sync didn't finish" says "Something went wrong"
  (the sync wording "The sync stopped unexpectedly" said the title twice).
- **ColumnFrame's foot rule spans the content (Task 10B):** the hairline over the foot was the foot's border, so it
  ran `--s-5` past the rows and the buttons on both sides (measured 20 px at 1280, §12 edges). It is drawn inset by
  the foot's padding, so it ends where they end.
- **Banners stay on the running and end views (Task 10B):** they have no Start, no Spotify slot and no Spotify card,
  so the shell's console and Spotify banners are the one place those views say it (a view never loses the warning).
  Only the before-start view hides them (Task 10A).
- **The running view's filter is a `Segmented` (Task 10B):** the loose ChipGroup pills stopped short of the right
  edge the rows set (§12 edges, §4 filters); `segOptions` gives All · Lossless · Lossy · Problems their counts and the
  green, yellow and red dots of what each shows. An empty filter says "Nothing here yet" as a `Hint` directly under it.
  The strip appears with the first result (before it, a control of four zeros filtered nothing). `Segmented`'s
  segments are equal (`flex: 1 1 0`, fix round 1: "All 3" was 20 % narrower than "Problems 1" on a full-width strip);
  a label longer than its equal share keeps its width (`min-width: auto`; RunPanel's "All 195" read "All …" at 1100
  with equal shares alone). Fix round 2: a strip is `tight` when its full labels need more than its width
  (`isTight`, measured from the labels with a ResizeObserver, so shortening never flips it back); only then the
  unchosen segments may shorten to "…" (`min-width: 0`) while the chosen one keeps its label up to half the strip.
  Without it, round 1 made every segment unshrinkable and a narrow strip pushed the chosen one out of view; the
  `base-gallery` shot now checks the 260/200/160 px strip for overflow and for the chosen segment's right edge.
- **Sync's last outdated motion tokens are mapped (Task 10B):** the tick's on/off colour (`--t-fast` 120 ms) confirms
  a decision, so it takes `--t-state` with `--ease` (§6, 200–260 ms, as the switch does); the plan's dimming while
  Spotify is read (`--t-med`) is a state change and takes the same.
- **Improve, don't preserve (user, 2026-10-20):** agents had screenshotted and reworked pages without flagging
  visible flaws (loose filter pills stopping short of the right edge; a page header nobody ever designed; Spotify
  status left on Dashboard, right on Sync and To-do). The existing look was treated as a given. §12 makes the
  critique an obligation and adds the safeguards that stop it turning into endless churn.
- **The gallery is the catalogue (Task 7):** one section per block, headed by its name and the one-line rule it carries
  (from §7 and this log), the design-system blocks first, then the shared components §7 doesn't rework yet, then one
  Outdated section that lists `outdated.ts` (blocks and tokens) and `ghost` with their samples. Before, outdated blocks
  sat between live ones at the same rank, `ghost` was shown as a live variant (also in the samples' own footers), and
  the frames, Panel, the ProgressBar paces and Skeleton's card shape had no sample, so a page agent couldn't tell
  what to use (§7: a page agent reads the gallery before designing). The gallery itself uses no outdated token.
- **The why's narrow mark is a shared component, `WhyMark` (Task 7):** the kind icon and "next sync" dot before ⊘
  (Task 9B, I2) were markup and CSS inside `PlanRows`; the gallery's ListRow sample needs the same mark, and a second
  copy would be a second spelling. Shared like `Why` (Sync and the Gallery); Sync's rows look the same.
- **Panel's body fades its cut over a row's height (Task 7 fix round 1):** when even fill's minimum doesn't fit, the
  whole body scrolls and its cut falls wherever the window ends. With the lists' 16 px fade a cut a few px under a
  row's rule faded only that row's padding: the panel read as a complete list (the gallery's 380 px Panel showed 2
  Playlists rows and no sign of more), the same misreading the grow group's peek rules out. Moving the cut onto a row
  would need the panel to measure its rows and leave a gap above the foot; instead the body's fade runs over
  `--h-row`, more than the gap between two rows' content, so at any cut some row content dims toward the foot.
  `--fade-len` is set on each scroller, so the lists inside the body keep their 16 px fade (fix round 1 of 9B).
- **The gallery's main actions are `filled` (Task 7 fix round 1):** the frames' foot, the ColumnFrame's Done and both
  dialogs' main buttons used `primary` (orange outline), so the samples a page agent copies first broke §4's one
  filled button per screen. The Button rule line now says what each variant is for.
- **A cut grow group ends half a row into the next row (issue 10):** above its minimum the Playlists group ended
  wherever the spare height ended; at 1100 × 700 that was 5 px under the 4th row's rule (`sync-before`), a sliver of
  the 5th switch that read as a glitch, and the 16 px fade covered only padding. The group now rounds its rows' area
  down to whole rows plus the peek (`growSpare` in `toggleModel.ts`, tested) and hands the rest (less than a row) to
  Panel (`GROW_SPARE` context), which holds it in a spacer at the body's end, above the foot, where a fitting list's
  spare height already sits; a margin on the group would have opened the gap to What to do instead. The group
  measures the space it is given (its box plus what the spacer holds; the spacer barely shrinks until the group is at
  its minimum, then gives way), never its own result, so applying the spare changes nothing and nothing oscillates.
  The peek is half a row (`--h-row` / 2, 19 px with the rule), at the minimum too: the `--s-3` peek showed only 1 px
  of the next row's switch, the same sliver; half a row shows the top of the switch and the name under the fade,
  and the 16 px fade still ends above the last whole row (9B). Minimums: 178 px, 224 px with a search. Outside a
  Panel a grow group ends where its space ends.

- **A page takes a banner over through one shell store (final review fix A, I1 + I2):** the shell's Banners imported
  Sync's view logic (`whichView`, `dismissedJob`) to hide its banners on the whole before-start view, so the up-to-date
  and empty views, which have no Start and no Hint, said nothing while a terminal sync ran (probe 1; a view never
  loses the warning). `lib/stores/shell.ts` holds `bannersSaidInBody` (`{ console?, spotify? }`): the view that says a
  state in its body sets it while it shows it (`sayInBody` in an effect, cleared on teardown), and Banners reads only
  that store. Sync's before-start view sets `console: hasPlan` (Start and its Hint show) and `spotify` while the card
  above the plan can show (a preview, no load problem). Shot `sync-before-up-to-date-console` guards it. The shell
  depends on no page; a phase 2 page that says a state itself uses the same store.
- **Placeholders are the real blocks waiting (final review fix A, I4):** the up-to-date panel and the end screen
  pasted measured heights (167, 84, 118 px) into Skeletons, true for one data set and one set of tokens. They now
  draw their StatCards with `value={null}` ("—", the block's own "nothing known yet") and `QualityBar by_quality={null}`:
  the bar's track shimmers and its legend holds one waiting line of its own line height. Height and radius match by
  construction (measured: the waiting and drawn panel cards line up to 1 px at 1280). Only the rare fallback without a
  quality split (details failed) draws shorter, without a bar; accepted (re-review N4), since the view can't know the
  fallback before the details arrive. `Skeleton shape="card"` stays for a card whose blocks
  can't wait, and takes `--r-surface`.
- **Outdated tokens and variants out of the blocks Sync renders (final review fix A, I3):** Skeleton's card radius
  `--r-card` → `--r-surface` (10 px placeholders under 12 px Surfaces), Cover's image fade `--t-med` →
  `--t-state` with `--ease` (§6: a state change), SpotifyStatus's Stop reading `ghost` → `secondary`.
- **The grow group's peek comes from its min-height (final review fix A, M3):** `growSpare` measured the peek as half
  the first row while the CSS min-height computes `--h-row / 2`; they rounded 2 px apart, so at its minimum the group
  handed 2 px to Panel's spacer (probe 2, 700–856 px). It now takes `floor`, the box's computed min-height, and the
  peek is what that holds beyond the whole rows, so a group at its minimum hands nothing and every cut above it
  repeats the min-height's own peek.
- **ToggleGroup (final review fix A, M4, M5):** a group that drops below `SEARCH_FROM` clears its query, so an old
  filter can't come back unseen when it grows again. `disabledReason` says why a disabled group is off: each row's
  tooltip and a one-line Hint under the group, as a disabled Button carries its `title`.
- **One grow group per Panel (final review fix A, M6):** Panel's spacer holds one group's spare; a second group would
  overwrite it. `GrowSpareHost.join` registers a group and dev mode warns about a second.
- **Segmented caps the chosen label only when tight (final review fix A, M7):** `max-width: 50%` applied to every
  strip, so with few options a chosen label wider than half the strip was cut although everything fit.
- **Sizes as tokens (final review fix A, M8):** `--w-row-action` (64 px, a row's trailing slot: EndScreen's and
  RunList's action slot, RunPanel's number column, Could be better's count) and `--gap-split` (3 px, DayBar's parts);
  PageHeader's min-height is `--h-btn`, DayBar's bar `--h-ctl-sm`, and the Switch's and the reading plan's dim
  `--dim-locked` (.45 → .5: one dim for a thing that can't be used right now).
- **"Download limits →" is a Button link (final review fix A, M9):** the reference page's last raw `<a use:link>`;
  `Button variant="link"` brings the press dim and the off state, and phase 2 copies the reference page.
- **InfoTip is text only (final review fix A, M10):** a `role=tooltip` may hold no link or button, and the ⓘ had
  `aria-expanded`/`aria-controls` as if it opened a disclosure. The ⓘ is described by its tip (`aria-describedby`),
  nothing more; a tip that needs a link is a different block.
- **ProblemCard announces only what the user just caused (final review fix A, M11):** `role="alert"` on every card
  made VoiceOver interrupt on page load and read stacked cards together. `alert` is a prop, set where the user's own
  action failed (Sync's start, adding a playlist, a playlist change, the wrong-song search); a card drawn with its page
  has no role.
- **Out-of-order replies are dropped (final review fix A, M12):** `latestOnly()` (`lib/latest.ts`, tested) numbers
  requests; Sync's `sync_preview` and up-to-date `dashboard` loads apply only the newest reply, so a slow older one
  can't set the last run back (and `keepDetail` then drop the newer run's details).
- **edgeFade handles children one by one (final review fix A, M13):** it re-walked the whole slot tree with a
  `getComputedStyle` per child on every child change (each search keystroke in a long ToggleGroup); it now observes
  the children added and unobserves the removed ones. Limit, noted in the action: a child that switches to or from
  `display: contents` after it arrived is not noticed (none does).
- **The guards read the blocks too (final review fix B, I3):** `outdated.test.ts` scanned page folders only, so an
  outdated token inside a block a redesigned page renders stayed green. It now also scans `lib/components` and
  `lib/frames` (the outdated blocks themselves skipped), checks `variant="ghost"`, and counts direct-path, aliased and
  double-quoted imports (`lib/guards.ts`, each matcher with a failing and a passing string). The wider scan found
  Toast, Dialog and DropZone on `--r-card` (now `--r-surface`, 10 → 12 px, one card radius), TextField on `--r-input`
  and a literal 34 px (now `--r-ctl`, 7 → 8 px, and `--h-btn`), DropZone and TextField on `--t-fast` (now `--t-press`:
  a focus or drag-over answers the pointer, `--t-state`'s 240 ms would feel late), Ring on `--fs-big` (`--fs-stat`,
  same value) and ConfirmHost's Cancel on `ghost` (now `secondary`). `UpgradeCard` keeps `Card` as the one allowed
  exception (To-do's, reworked with To-do), and the test fails if a redesigned page imports it.
- **Checker markers are block-owned (final review fix B, I5):** `data-note` and `data-surface` were plain attributes,
  and LiveView wrote `data-note` on a bare `<p>` to shelter its stop error. `lib/guards.test.ts` now fails any page
  that writes a checker marker (`data-note`, `-surface`, `-infotip`, `-dev`, `-hint`, `-row-hit`, `-frame*`,
  `-panel*`, `-page-header`, `-max`, `-stretch`, `-primary`, `-spotify-status`). The stop error is `Hint
  tone="problem"`, a new tone: red, `role=alert`, the backend's message cut to one line; the block marks it
  `data-note` because its length is the backend's. Gallery: a third Hint sample.
- **The button rule checks list surfaces (final review fix B, I5):** it skipped every button in any list surface, so
  a stretched button in a list's head or a row's trailing cell passed. Only the hit areas that fill by design are
  allowed now: segments, switch rows, menu items, and `data-row-hit` (ListRow's `.main`, Surface's fold). The
  stricter rule found Sync's ⊘ (`Button variant="icon"`): its 26 px square was a `width`, so it read as stretched
  beyond its 18 px content. `.icon` now holds the square as `min-width`, the block's natural size; nothing moved.
- **One frame, measured against tokens (final review fix B, I5):** a new `frame` rule wants exactly one `[data-frame]`
  and at most one `[data-page-header]` per shot (a page without a frame had nothing to measure). `data-max` names its
  token (`--content-max`, `--content-max-wide`) instead of repeating 900 / 1200. The panel limit follows the window:
  `--panel-w`, or `--panel-w-narrow` below the new `--panel-narrow-below` (1240 px), which ListPanelFrame's media query
  repeats (a media query can't read a var; `guards.test.ts` keeps the two equal). Fixtures: `bad-frame`,
  `bad-frame--two`, `bad-frame--headers`, `bad-button--list`, `bad-max-width--panel` (340 px at 1100),
  `bad-max-width--token`, `good--wide-panel` (360 px at 1280), and good.html gained a list head button, row hit areas
  and a 320 px panel at 1100.
- **A locked ToggleGroup says why in its head (final review fix B):** the `disabledReason` Hint sat under the
  Surface at the column's gap, as far from its group as from the next caption (gallery). It now takes the place of
  the All · None links it locks, at the head's right edge where a group's actions sit, and gives way with the label
  (Surface `.extra` shrinks when it holds a Hint). No height changes, so a grow group's sizes stay true.
- **The waiting legend is a cap-height line (final review fix B):** the waiting QualityBar's legend line filled its
  whole 62 % × line-height box, a slab heavier than the 6 px bar above it and than the small muted text it stands
  for. It keeps the line's height (so nothing jumps) but draws a `.7em` pill at 48 %.

## 12. Rules — improve what you touch, converge on decisions

**The existing look is evidence, not law.** No page, block or header is "how it is" just because it exists. Every
agent that designs, builds or reviews UI does a written critique of what its task touches before building (and the
reviewer again on the result), with `apple-design` and `emil-design-eng` loaded, at all three sizes:

- **Edges and alignment:** does every line of content start and end on purpose? Which edges are hard (search field,
  buttons, row ends), and does everything that should meet them meet them?
- **Grouping:** do related things read as one object, unrelated ones as separate?
- **Space:** is empty space chosen, or left over? What happens to it at 1100 and at 2560?
- **Hierarchy:** what does the eye land on first, and is that the most important thing?
- **Consistency:** does the same element look, sit and behave the same on every other page?
- **Intent:** was this element designed, or carried over? Minimal is good only when it's a choice that serves the
  content. If it's just what was left, design it.

Every flaw the agent can fix inside this design system, it must fix. Flaws it can't (system level, or outside its
task) go in its report. A critique that finds nothing lists what it checked. A flaw visible in the task's screenshots
that nobody flagged is a review miss, not a matter of taste.

**Consistency is absolute.** One element has one place, one look and one behaviour on every page. A shared element
(the page header, Spotify status with Read Spotify, the start button, filters) is placed by its block, never by the
page. Where the checker can see it, it fails a page that places a shared element itself.

**Edges on purpose.** A line of content either spans its column or is one contained object (a `Segmented`, a
`Surface`). A loose row of separate items stopping short of a hard edge that the rows around it set is a flaw.
Spreading the gaps to fill the width is not a fix: the gaps grow with the window. Single-choice filters are a
`Segmented`; overflow goes into its More menu.

**Safeguards against drift:**

1. **A reason, not a taste.** Every change names its reason: a skill rule, a section of this spec, or a measured
   problem (contrast, alignment, hit size, consistency, clipping). "Looks better to me" doesn't count.
2. **System changes are made once, centrally.** Tokens, frames, blocks, the header and shared elements change in
   the block, never as a page-local variant. A page agent who finds a system flaw reports it. The controller applies
   it to the block, or rules against it with a reason.
3. **Decisions are recorded and stick.** Every system-level change goes into the decision log of
   `docs/hub-design-language.md` (§11 here until that doc exists), with its reason. It is reopened only for a reason
   the record didn't weigh (new evidence, a new requirement), never by restating a preference. A thing changed back
   a second time goes to the user.
4. **Taste goes to the user.** The user decides a new look, what a colour means, and the layout direction of a whole
   page type. Agents decide everything else and record it.
5. **Scope.** An agent fixes what its task touches. Flaws elsewhere go into its report and then `docs/issues.md`, so
   parallel agents never edit each other's ground.
6. **Done is finite.** A task is done when every flaw its critique found is fixed or recorded. Nothing is polished
   past that, and nothing is reopened without a reason under rule 3.
