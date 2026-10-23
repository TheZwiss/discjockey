# Now playing — plan (issue 21)

Global controls for track previews. A preview started in Library or To-do keeps playing on every page, and the
window gets a **foot**: a 44 px bar along the bottom in the sidebar's material. Together with the sidebar it forms
one L-shaped frame around the page. The bar can be hidden into a **Now playing** row at the sidebar's foot and shown
again from there.

**The visual spec is the approved mockup `docs/hub-mockups/now-playing.html`** (approved by the user 2026-10-23
after two rejected rounds). Open it and screenshot it before building. Where this plan and the mockup disagree, the
mockup wins on look and this plan wins on behaviour. Builders may improve details for a named reason (spec §12 of
`docs/2026-10-20-hub-design-system-design.md`), but the concept is fixed:

- an L-shaped frame;
- the page's lower edge shows the position;
- the bar holds the sync status too;
- hide folds the bar into the sidebar row.

The user rejected two other forms:

- **A floating pill with a reserved strip under the page:** it takes space and still looks detached.
- **A player crammed into the sidebar:** too tight.

Do not drift back towards either.

## Decisions (with the user, binding)

- **Controls:** ⏮ ⏯ ⏭, shuffle ⤮, Stop ×, Hide ⌄; Show ⌃ on the sidebar row.
- **The queue is a snapshot** of the list the preview started from, taken when play is pressed. In Library it is the
  folder's rows as shown: filter, search and sort applied, only rows with a file (`path !== null`). In To-do it is
  the to-do rows with a file, in the order shown. Later filter changes don't change the queue.
- **When a track ends, the next one plays** (in shuffle order when shuffle is on). After the last track the player
  stops at "End of <list>", and ▶ plays the list again from the top.
- **⏮:** after the first 3 s of a track it restarts that track; within the first 3 s it goes to the previous one.
  On the first track it always restarts.
- **Shuffle on** shuffles the rest of the queue after the current track. Shuffle off goes back to the list's order,
  continuing from the current track.
- **A queue of one:** ⤮ ⏮ ⏭ are grey (disabled, never removed). At the end of the list ⏭ is grey too.
- **Can't play:** "Can't play this file." appears in red under the title and ▶ turns grey. It does **not** skip by
  itself; ⏭ and ⏮ still work.
- **The wrong-song dialog's 20 s candidate clips and the upgrade ComparePlayer** are checks inside one track. They
  **pause** the queue (it stays, ❚❚ turns ▶) and never appear in the bar.
- **Hide** folds the bar into a sidebar row (above Settings) that holds ⏯, the title and a thin position line. Show
  (⌃ or a click on the title) unfolds it again. A new preview while hidden keeps it hidden; the row just changes
  title. Hidden lasts until Show or Stop. It isn't saved across app restarts, because the queue isn't either.
- **Stop** (×, only on the bar) stops the sound and forgets the queue. The bar goes away, or shrinks back to only the
  sync status while a sync runs.
- **Keys:** Space plays/pauses, ⌘→ goes to next, ⌘← to previous. None of them fire while focus is in a text field,
  textarea, select, contenteditable, a focused button or slider, or an open dialog. Media keys are out of scope.
- **One truth:** the Library row's ❚❚, the details MiniPlayer, the bar and the row all read the same store.

## Architecture

```
lib/stores/queueModel.ts (pure)  ← next/prev/shuffle/end rules, unit-tested
lib/stores/player.ts             ← the one <audio> (unchanged ownership) + the queue session on top
lib/shell/Foot.svelte            ← the bar: player part and/or sync part (replaces ActivityBar's slot)
lib/shell/NowPlayingRow.svelte   ← the sidebar row while hidden
lib/shell/activity.ts            ← unchanged texts, plus a short form for the bar's right end
App.svelte                       ← renders Foot; global keys
pages/library, pages/todo        ← start a queue instead of a single play
pages/todo/WrongSongDialog       ← clips on their own channel (no track_id, no bar)
```

Playback stays in one hidden `<audio>` in `App.svelte` (`attachAudio`). The queue is a layer in `player.ts`.
`player.play({url,…})` remains for a **single sound** with no queue (used by nothing that shows in the bar after this
change; keep it for the gallery and for clips).

---

## Task 1 — the queue (logic, Sonnet)

Files: `hub-ui/src/lib/stores/queueModel.ts` + `queueModel.test.ts` (new), `lib/stores/player.ts`,
`pages/todo/WrongSongDialog.svelte`, `lib/components/ComparePlayer.svelte` (only if its `claimSound` use needs it).

### Interfaces (exact)

```ts
// queueModel.ts — pure, no DOM, no timers
export type QueueItem = { track_id: string; title: string; artist: string; cover_url: string | null;
  duration_s: number | null };
export type QueueSource = { label: string; href: string };   // "All tracks", "#/library?track=…" style link
export type Queue = { items: QueueItem[]; order: number[]; at: number; shuffle: boolean; source: QueueSource };
// order: indices into items in play order; at: position in order
export function makeQueue(items: QueueItem[], start: number, source: QueueSource): Queue;
export function nextIndex(q: Queue): number | null;          // null at the end
export function prevAction(q: Queue, position_s: number): { kind: 'restart' } | { kind: 'go'; at: number };
export function setShuffle(q: Queue, on: boolean, rand?: () => number): Queue;   // rand injectable for tests
export function current(q: Queue): QueueItem;
export function single(q: Queue): boolean;                    // items.length === 1
```

```ts
// player.ts additions (store state extends PlayerState)
type PlayerState = /* existing fields */ & {
  queue: Queue | null; hidden: boolean; ended: boolean;   // ended: stopped after the last track
};
player.playQueue(o: { items: QueueItem[]; start: number; source: QueueSource;
  resolve: (track_id: string) => Promise<string | null> }): void;
player.next(): void; player.prev(): void; player.setShuffle(on: boolean): void;
player.hide(): void; player.show(): void;
player.stop(): void;          // existing: now also clears queue + hidden + ended
player.pauseForClip(): void;  // what claimSound's stop callback calls when a queue is active: pause, keep queue
```

- `resolve` turns a `track_id` into a playable URL **at the moment that item plays**. Pages pass
  `async id => (await api.track(id)).ok ? r.track.audio_url : null`. A `null` result, or an `<audio>` error, sets the
  existing `error: CANT_PLAY` for that item; no auto-skip. Keep the resolve function with the queue.
- `ended` event with a queue → `nextIndex`; `null` → state `ended: true`, `playing: false`, position at the end. A
  toggle/▶ in that state calls `playQueue` again from index 0 with the same items, source and shuffle.
- A racing resolve (the user presses ⏭ twice fast) must never play a stale item: the latest request wins (turn
  counter, like Library's `trackTurn`).
- `claimSound` callback: with a queue active, the previous owner's stop becomes `pauseForClip()`. Without a queue
  it stays `stop()`, so single sounds keep today's behaviour.
- **Clips channel:** check first whether `WrongSongDialog` can play its 20 s clip through the same
  `<audio>` without polluting the bar. The bar reads `queue`, so a single `player.play({…})` with
  `track_id: null` already stays out of it. But a clip must also not *replace* the queue's audio for good: when the
  clip ends or the dialog closes, the queue stays paused at its position and resumes from there on ▶. If sharing the
  element makes that brittle (the src swap loses the queue's position), give clips their own `Audio()` that
  registers through `claimSound`, as ComparePlayer does with Web Audio. Decide and note why in the commit.

### Behaviours the tests must pin (queueModel.test.ts)

1. `makeQueue` with start k: `current` is items[k], `order` is identity, shuffle off.
2. `nextIndex` walks the order and returns `null` after the last.
3. `prevAction`: position > 3 → restart; ≤ 3 and not first → go to previous; first → restart.
4. `setShuffle(true)`: current item stays current; every item still appears exactly once; items before the current
   one are not replayed. Deterministic with an injected `rand`.
5. `setShuffle(false)` after shuffling: order is identity again and `at` points at the same current item.
6. `single` for one item; shuffle of one item is a no-op.
7. Player-level (a small test with a fake `<audio>` element, or keep the logic in the model so it is testable): the
   latest of two quick `next()` calls wins; `ended` at the last item sets `ended: true`; Stop clears queue and hidden.

Done: `npm run verify` green (it runs the tests, the type check, the rule checker and the trial build). No UI changes
are visible in this task; existing Library/To-do play keeps working via `play()` until Task 2 moves them over.

---

## Task 2 — the foot and the row (UI, Opus)

**Mandatory first:** load the `apple-design`, `emil-design-eng` and `animate` skills, read
`docs/hub-design-language.md`, open the mockup. Write a short critique of what you touch before building (spec §12).
You may improve on the mockup for a named reason; record each change and its reason in the report.

Files: `lib/shell/Foot.svelte` (new; takes over `ActivityBar.svelte`'s place; fold ActivityBar into it or keep it as
the sync part, whichever leaves one clear block), `lib/shell/NowPlayingRow.svelte` (new), `lib/shell/Sidebar.svelte`,
`App.svelte`, `lib/shell/activity.ts` (short form), `pages/library/Page.svelte` (+ `TrackDetails.svelte`),
`pages/todo/Page.svelte` / `Details.svelte`, `lib/components/MiniPlayer.svelte`, the gallery
(`lib/dev/Gallery.svelte`), `docs/hub-design-language.md` (+ decision log), fake scenarios + `shots.json` entries,
`README.md` (user manual: a short "Listening through a list" part), `docs/issues.md` (remove issue 21).

### The foot (binding values)

- **Shape:** height `--activity-h` (44 px), full window width under sidebar and page, background `--sidebar-bg`.
  There is **no line** where it meets the sidebar. Only the page's edge has a line: a 1 px `--surface-line` from
  `--sidebar-w` to the right edge, continuing the sidebar's right border into an L.
- **Position on the page's lower edge:** the played part is 2 px of `--accent` from the left end of that line. With
  the pointer on it, it thickens to 4 px, shows a knob at the position and the time under the pointer in a small
  label; click or drag seeks. It follows the pointer 1:1 with no transition while dragged (use the existing `scrub`
  action). The hit area is at least 8 px tall, centred on the line. While loading, no fill.
- **Grid** `minmax(0,1fr) auto minmax(0,1fr)`:
  - **Left** starts at the sidebar items' inset: a 28 px cover (`Cover` block), the title (strong, 13 px), and under
    it "Artist · <source label>" (muted, 12 px). In the error state the second line is "Can't play this file." in
    `--q-weak`; at the end it is "End of <source label>". Title and source are a link to `source.href`, which
    selects the playing track. The full name goes in the tooltip.
  - **Middle**, centred on the window: the time played, ⏮, ⏯ (the MiniPlayer's round accent button, 30 px), ⏭, the
    length. The times are 11 px, tabular, and hug the buttons.
  - **Right:** [sync part while a sync runs and the page isn't Sync] · ⤮ · separator · ⌄ Hide player · × Stop.
- **Sync part inside the bar:** pulsing dot, "Sync 4 of 6" (short form from `activity.ts`), a 90 px progress bar. It
  is a link to `#/sync`.
- **Sync only** (no queue, or hidden): today's ActivityBar content in the same foot (same material, same L line).
- **Shuffle on:** `--accent-text` on `--accent-wash-strong` plus a dot. That's colour plus shape (design language §2).
- **Buttons:** the 28 px icon buttons from the mockup. Disabled is grey (`--text-disabled`), never removed. Press
  scale .97 on pointer-down.
- **Words the user sees:** "Hide player", "Show player", "Stop", "Shuffle", "Previous", "Next", "Play", "Pause",
  "Can't play this file.", "End of <list>", "Now playing". All are aria-labels/tooltips too.

### The row (hidden)

In the sidebar above Settings: the group label "Now playing" (the "Library" label's style), then a 32 px row with a
22 px ⏯, the title (13 px, cut with …) and a 22 px ⌃ "Show player". A 2 px position line runs under the title.
Clicking the title shows the bar too. The row exists only while hidden with a queue. The folder list above gives
way (it already scrolls).

### Motion (binding intent; values may be tuned for a named reason)

- **Appear** (first preview): the foot slides up from the window's bottom edge, 220 ms, strong ease-out. The page
  makes room at once (no animated layout height). **Stop:** slides down, 180 ms.
- **Hide:** the bar's contents move left towards the sidebar corner and fade (240 ms, ease-in-out), then the foot
  goes away and the row fades in. **Show:** the reverse path (280 ms).
- **Instant:** track change, play/pause, shuffle, keys (emil: never animate keyboard actions; tens of times a day).
- **Reduced motion:** cross-fades only. Only transform/opacity animate. No looping animation except the existing sync
  dot pulse.

### Wiring the pages

- **Library:**
  - The cover ▶ in a row and the details MiniPlayer start `playQueue` with the snapshot defined above. Check first:
    whether `lib.rows` is already in display order or `LibraryTable` sorts them. The snapshot must match what is on
    screen.
  - Source: the page title ("All tracks", the folder name, "Not in a playlist"), plus " · “<search>”" when a search
    is active.
  - href: the folder's library link with `?track=<id>`. Clicking it while the queue moves on selects the track that
    is playing **then** (build the href from the current item, not the start).
  - The row ❚❚ follows `$player.track_id` as today.
- **To-do:** the details MiniPlayer starts a queue of the to-do rows with a file, in the order shown, with source
  "To-do".
- **MiniPlayer:** gets an optional `start?: () => void` used when it isn't the active sound (instead of
  `player.play`). Without it, it behaves as today (the gallery, any single sound).
- **Toasts** stay in the page area's bottom left. The page area ends above the foot, so they rise with it.

### Gallery, doc, fake

- **Gallery:** a "Foot" section with the states of the mockup's strip: playing, the pointer on the edge, paused,
  loading, can't play, end, a list of one, shuffle on, long names, with sync. Plus the row (playing, paused, the
  pointer on ⌃).
- **Design language:** the L frame (sidebar + foot, one material, the line only along the page) as a shell rule; the
  foot block; the decision log entry "2026-10-23 · Now playing lives in the frame's foot; hide folds it into the
  sidebar". The reasons: covers nothing, costs the 44 px the sync bar already cost, one bar instead of two,
  spatially consistent hide/show; a floating pill and a sidebar card were rejected by the user.
- **Fake mode:** scenarios to reach each state (the toolbar or `?scenario=`), plus `shots.json` entries for Library
  with the foot, Dashboard with foot + sync, hidden with the row, and the 2560 size. The fake library's tracks need
  playable `audio_url`s (the gallery's tone data URLs) so the states are real.

### Done (Task 2)

- `npm run verify`, `npm run build`, `npm run smoke` and `uv run pytest -q` are all green.
- You looked at the screenshots at 1100, 1280 and 2560 of:
  - Library playing;
  - Dashboard during a sync;
  - hidden;
  - every gallery state.
- The rebuilt `discjockey/hub/static/` goes in its own `build(hub): static` commit.
- The report (≤ 40 lines) covers:
  - what changed from the mockup and why;
  - what couldn't be shown in fake mode (for the live check);
  - flaws found outside the task (into `docs/issues.md`).

---

## Out of scope

Media keys / `navigator.mediaSession`, saving the queue across restarts, a queue list view, repeat, volume.

## Live check (the user, after merge)

Feel of the hide/show path and the edge scrub in the real window; Space/⌘←/⌘→ in the real window; one listen through
a few tracks of a folder with shuffle.
