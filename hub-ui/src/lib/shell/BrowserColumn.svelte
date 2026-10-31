<script lang="ts">
  // The browser column (plan library stage 5 A5 and B5, D4, D8, I7; notes N2–N4, N9, N10, N13, N15): Library's
  // collections beside the rail, in the frame's material (Sidebar.svelte places it, moves it and sizes it). On top the
  // filter field ("Filter playlists, folders", the ⌘K cap), centred on the page header's row; under it one scroller:
  // All tracks and Not in a playlist without a head, then the sections whose heads fold and stick to the list's top and
  // foot, solid and square (`ListSection on="chrome" stick="both"`): Favourites (the user's own order; while empty one
  // dashed row says where a dragged row lands), Playlists (playlists.txt order, the download priority, or A–Z by the
  // head's toggle; a switched-off one in place at half strength; the service's own logo) and Folders (each watched
  // import folder with its crates, indented, and a chevron that folds them; the yellow "!" while its drive is away;
  // then the Library folders no playlist uses). Every row is one line; a name that doesn't fit ends in "…", and every
  // collection row has a Tip with its words (I7). The pill marks the collection on screen on its topmost row.
  //
  // The filter (browserModel.ts): typing lists only the names that match, each once, in its own section (folded ones
  // open, Favourites steps aside, hidden crates and every album found too, under their watched folder), the matching
  // letters bold; one row carries the orange wash, the one Enter opens (the first match; ↑ ↓ move it), and the last
  // row hands the text to the track search ("Search tracks for “…”" ↵: All tracks with the text in its search,
  // `#/library?q=`). No motion: the list is rebuilt on each key. Esc clears and leaves the field (an open Tip takes
  // the first Esc). ⌘K anywhere asks for the field (`filterFocus`); the column answers once it stands. Opening a
  // collection (a click, Enter, the route) scrolls its row into view, whole beside the stuck heads.
  //
  // Favourites by keyboard: ⌥↑ / ⌥↓ on a focused favourite moves it one place, saved like a drag (same put-back on a
  // refusal), without motion; focus stays on the row.
  //
  // Favourites by drag (notes "Motion"), only into and inside Favourites: a playlist or folder row pressed and moved
  // 4 px lifts (120 ms: raised, a shadow, 1.02, nudged towards the pointer) and follows the pointer 1:1 up and down;
  // over Favourites the rows part where it will land (200 ms ease-out transforms, `animate:flip`), and a drop settles
  // it there on a critically damped spring (response 0.3, no overshoot: a drop has no momentum). Dropped anywhere
  // else, a favourite included, or Esc, it goes back the same way. The order shows at once and is saved (a brief save, D15); a refused save
  // puts it back and says so in a toast. The list scrolls by itself while the pointer holds near its ends.
  //
  // The right-click menu (I7): Open · Play · Add to favourites / Remove from favourites · Hide from sidebar (a crate
  // under its watched folder; "Settings brings it back"; a hidden one the filter found offers Show in sidebar) · Show in
  // Finder (where the folder is inside the music folder). The row it acts on wears the orange ring while it is open.
  // Shift-F10 or the menu key opens it from the keyboard.
  //
  // For a screen reader the filter is a combobox over the rows: while filtering the list is a listbox, each row an
  // option with its own id (`bc-…`), and the field's `aria-activedescendant` names the highlighted one, so ↑ ↓ are
  // read out as they move. A switched-off playlist and an away folder say so in words, not only by their look.
  import { tick } from 'svelte';
  import { flip } from 'svelte/animate';
  import { cubicOut } from 'svelte/easing';
  import { get } from 'svelte/store';
  import { api } from '../bridge/client';
  import type { FolderState } from '../bridge/types';
  import { hub, saveCrateShown, saveFavourites } from '../stores/hub';
  import { route, link, go } from '../router';
  import { browserClosed, chrome, filterFocus, playlistsAz } from '../stores/chrome';
  import { toasts } from '../stores/toasts';
  import { problemCopy } from '../copy';
  import { listen } from '../listen';
  import { count as thousands } from '../format';
  import { getPref } from '../prefs';
  import { LEGACY_SORT_KEY, playQueue, sortKey, viewSort } from '../../pages/library/libraryModel';
  import { Button, ContextMenu, ListSection, SearchField, tip } from '../components';
  import type { MenuItem } from '../components/ContextMenu.svelte';
  import {
    HANDOFF, LANDING_TEXT, browserList, crateShownValue, currentTarget, dropIndex, dropSpring, favouritesIn, inDropZone,
    foldWatchedTip, highlightOf, menuFor, moveHighlight, moveKey, nameParts, playCall, revealPath, rowByKey, rowId,
    sortTip, toggleClosed, type BrowserRow, type CollectionRow, type MenuAction, type Match, type ViewRow,
  } from './browserModel';
  import RowLead from './RowLead.svelte';

  let query = $state('');
  /** the highlight the arrow keys moved to (null: the first match) */
  let moved = $state<string | null>(null);
  let input: HTMLInputElement | undefined = $state();
  let scroller: HTMLDivElement | undefined = $state();
  /** a Favourites order saved a moment ago and not read back yet (shown at once), and crate switches likewise */
  let pendingFavs = $state<string[] | null>(null);
  let pendingShown = $state<Record<string, boolean>>({});

  const side = $derived($hub.sidebar);
  const shownSide = $derived(side && pendingFavs ? { ...side, favourites: favouritesIn(side, pendingFavs) } : side);
  const current = $derived(currentTarget(side, $route.name === 'library' ? ($route.params.folder ?? null) : undefined));
  const list = $derived(browserList({ side: shownSide, query, az: $playlistsAz, closed: $browserClosed, current,
    shown: pendingShown }));
  const filtering = $derived(list.targets.length > 0);
  const hi = $derived(highlightOf(list.targets, moved));
  const at = $derived(list.on);
  const favKeys = $derived(shownSide?.favourites.map((f) => f.key) ?? []);
  const favSet = $derived(new Set(favKeys));

  // a new text starts the highlight over at the first match, and brings it into view
  let lastQuery = '';
  $effect.pre(() => {
    if (query === lastQuery) return;
    lastQuery = query;
    moved = null;
    void tick().then(() => reveal(hi));
  });

  // the column stays mounted outside Library: typed text must not wait for the next visit
  $effect(() => {
    if ($chrome.place !== 'library') clear();
  });

  function clear() {
    query = '';
    moved = null;
  }
  /** Opens a row (a click goes through its link; Enter through here). The filter clears; the field lets go, except
   *  for the hand-off, where the page's track search takes the focus. */
  function opened(r: BrowserRow) {
    clear();
    if (r.kind !== 'handoff') input?.blur();
  }
  function enter(r: BrowserRow) {
    opened(r);
    void go(r.href);
  }

  function keydown(e: KeyboardEvent) {
    // keys that compose a letter (an input method's ↑ ↓ Enter Esc) belong to the input method
    if (e.isComposing || e.metaKey || e.ctrlKey || e.altKey) return;
    if (e.key === 'ArrowDown' || e.key === 'ArrowUp') {
      if (!filtering) return;
      e.preventDefault();
      moved = moveHighlight(list.targets, hi, e.key === 'ArrowDown' ? 1 : -1);
      void tick().then(() => reveal(moved));
    } else if (e.key === 'Enter') {
      const r = hi ? rowByKey(list, hi) : null;
      if (!r) return;
      e.preventDefault();
      enter(r);
    } else if (e.key === 'Escape') {
      e.preventDefault();
      e.stopPropagation();
      clear();
      input?.blur();
    }
  }

  // ⌘K: each new request focuses the field and selects its text, once the column stands (into Library it is still
  // inert for a frame or two while the chrome waits for the page's first frame; Sidebar.svelte's motion)
  let seenFocus = get(filterFocus);
  $effect(() => {
    const n = $filterFocus;
    if (n === seenFocus) return;
    seenFocus = n;
    let frames = 0;
    let raf = 0;
    const tryFocus = () => {
      raf = 0;
      if (input && !input.closest('[inert]')) {
        input.focus();
        input.select();
        return;
      }
      if (++frames < 30) raf = requestAnimationFrame(tryFocus);
    };
    tryFocus();
    return () => cancelAnimationFrame(raf);
  });

  /** Scrolls a row whole into the list's view, beside the stuck heads (their height is each row's scroll margin), and
   *  only the list: the chrome around it never scrolls. */
  function reveal(key: string | null) {
    if (!key || !scroller) return;
    const el = scroller.querySelector<HTMLElement>(`[data-key="${CSS.escape(key)}"]`);
    if (!el) return;
    const r = el.getBoundingClientRect();
    const s = scroller.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const top = r.top - (parseFloat(cs.scrollMarginTop) || 0);
    const bottom = r.bottom + (parseFloat(cs.scrollMarginBottom) || 0);
    if (top < s.top) scroller.scrollTop += top - s.top;
    else if (bottom > s.bottom) scroller.scrollTop += bottom - s.bottom;
  }
  // the collection on screen: its row comes into view when it changes (a click, Enter, ♫, a link from another page),
  // when its folded section opens, and when the filter is cleared; not while filtering, where the highlight leads.
  // Nothing else moves the list: a refresh of the counts, another section folding or the A–Z order leave the user's
  // scroll where it is (`at` is the pill's row key, so a new list with the same row doesn't count as a change)
  $effect(() => {
    const k = at;
    if (!k || filtering) return;
    void tick().then(() => reveal(k));
  });

  // the A–Z toggle reorders the rows in place; WebKit moves the list's scroll while the rows are moved (measured: 400
  // → 176), so the list keeps the scroll it had
  function toggleAz() {
    const top = scroller?.scrollTop ?? 0;
    playlistsAz.update((v) => !v);
    void tick().then(() => { if (scroller) scroller.scrollTop = top; });
  }
  function fold(key: string) {
    browserClosed.update((c) => toggleClosed(c, key));
  }

  // ---------- saving: Favourites and crate switches (brief saves, D15), shown at once, put back on a refusal ----------
  let favSeq = 0;
  async function saveFavs(keys: string[]) {
    const mine = ++favSeq;
    pendingFavs = keys;
    const r = await saveFavourites(keys);
    if (mine !== favSeq) return;   // a later save is under way: it decides
    pendingFavs = null;            // the sidebar was read again: what is stored shows
    if (!r.ok) toasts.show({ tone: 'problem', title: 'Couldn’t save your favourites. Try again.' });
  }
  async function saveShown(path: string, tooMany: boolean, show: boolean) {
    pendingShown = { ...pendingShown, [path]: show };
    const r = await saveCrateShown(path, crateShownValue(tooMany, show));
    const { [path]: _, ...rest } = pendingShown;
    pendingShown = rest;
    if (!r.ok) toasts.show({ tone: 'problem', title: 'Couldn’t save that. Try again.' });
  }

  // ---------- the right-click menu ----------
  let menu = $state<{ row: ViewRow | CollectionRow; x: number; y: number; keys: boolean } | null>(null);
  function openMenu(e: MouseEvent, row: ViewRow | CollectionRow) {
    e.preventDefault();
    cancelDrag();
    menu = { row, x: e.clientX, y: e.clientY, keys: false };
  }
  /** ⌥↑ / ⌥↓ on a favourite: one place up or down, saved like a drag. The rows are moved in the DOM (focus is lost
   *  there), so focus goes back to the row; keyboard actions never animate (spec §6). */
  function moveFav(e: KeyboardEvent, row: CollectionRow): boolean {
    if (!e.altKey || e.metaKey || e.ctrlKey || e.shiftKey || filtering || row.place !== 'favourites') return false;
    if (e.key !== 'ArrowUp' && e.key !== 'ArrowDown') return false;
    e.preventDefault();
    const i = favKeys.indexOf(row.target);
    const to = i + (e.key === 'ArrowUp' ? -1 : 1);
    if (i < 0 || to < 0 || to >= favKeys.length || drag?.started) return true;
    flipMs = 0;
    void saveFavs(moveKey(favKeys, row.target, to));
    void tick().then(() => {
      scroller?.querySelector<HTMLElement>(`[data-key="${CSS.escape(row.key)}"]`)?.focus();
      reveal(row.key);
      flipMs = FLIP_MS;
    });
    return true;
  }
  function menuKey(e: KeyboardEvent, row: ViewRow | CollectionRow) {
    if (row.kind !== 'view' && moveFav(e, row)) return;
    if (!(e.key === 'ContextMenu' || (e.key === 'F10' && e.shiftKey))) return;
    e.preventDefault();
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    menu = { row, x: r.left + 24, y: r.bottom, keys: true };
  }
  const menuItems = $derived<MenuItem[]>(menu ? menuFor(menu.row, favSet).map((m) => ({
    label: m.label, note: m.note ?? null, test: `browser-menu-${m.action}`, onpick: () => pick(m.action) })) : []);
  /** Focus goes back to the row a keyboard-opened menu acted on (Esc, a pick), so the next key starts there. A click
   *  elsewhere (focus already on something else) is left alone. */
  async function returnFocus(m: NonNullable<typeof menu>) {
    if (!m.keys) return;
    const a = document.activeElement;
    if (a && a !== document.body && !a.closest('[role=menu]')) return;
    await tick();
    scroller?.querySelector<HTMLElement>(`[data-key="${CSS.escape(m.row.key)}"]`)?.focus();
  }
  function closeMenu() {
    const m = menu;
    menu = null;
    if (m) void returnFocus(m);
  }
  function pick(action: MenuAction) {
    const m = menu;
    const row = m?.row;
    menu = null;
    if (!m || !row) return;
    void returnFocus(m);
    if (action === 'open') enter(row);
    else if (action === 'play') void play(row);
    else if (row.kind === 'view') return;
    else if (action === 'fav-add') { showFavourites(); void saveFavs(moveKey(favKeys, row.target, favKeys.length)); }
    else if (action === 'fav-remove') void saveFavs(favKeys.filter((k) => k !== row.target));
    else if ((action === 'hide' || action === 'show') && row.kind === 'folder' && row.crate) {
      void saveShown(row.path, row.crate.tooMany, action === 'show');
    } else if (action === 'finder') void finder(row);
  }
  const AWAY: Record<Exclude<FolderState, 'here'>, string> = { offline: 'Offline: connect the drive', folder_missing: 'Folder not found' };
  /** Play: what ▶ on the collection's page queues (`playQueue`: the page's list in the page's sort, a playlist's songs
   *  then the other files of its folder, only files that are there), from the first. */
  async function play(row: ViewRow | CollectionRow) {
    const c = playCall(row);
    // the sort the page opens this view kind with, so the queue is the page's
    const sort = viewSort(c.view, getPref<string | null>(sortKey(c.view), null), getPref<string | null>(LEGACY_SORT_KEY, null));
    const r = await api.library(c.view, c.key, '', 'all', sort);
    if (!r.ok) {
      toasts.show({ tone: 'problem', title: problemCopy(r.kind).title, body: r.message || undefined });
      return;
    }
    const rows = playQueue(r);
    const away = row.kind === 'folder' && row.state !== 'here' ? AWAY[row.state] : undefined;
    if (!rows.length || !listen(rows, rows[0].track_id, { label: row.name, href: row.href })) {
      toasts.show({ tone: 'info', title: 'Nothing here can play right now.', body: away });
    }
  }
  async function finder(row: CollectionRow) {
    const path = revealPath(row);
    if (!path) return;
    const r = await api.reveal(path);
    if (!r.ok) toasts.show({ tone: 'problem', title: problemCopy(r.kind).title, body: r.message || undefined });
  }

  // ---------- Favourites by drag ----------
  const ROW_PITCH = 32;    // a row (--h-ctl, 30) and the list's 2 px gap: every row is one line
  const ROW_H = 30;
  const FLIP_MS = 200;
  const THRESHOLD = 4;     // px before a press becomes a drag (a click stays a click)
  type Drag = {
    row: CollectionRow; id: number; x0: number; y0: number; el: HTMLElement; started: boolean;
    grab: number; left: number; width: number; top: number; fromFav: boolean; over: boolean; at: number;
    settling: boolean;
  };
  let drag = $state<Drag | null>(null);
  let lifted: HTMLDivElement | undefined = $state();
  let favBox: HTMLDivElement | undefined = $state();
  let swallowClick = false;
  /** the rows' glide when the order changes: 0 for a keyboard move */
  let flipMs = $state(FLIP_MS);
  let autoRaf = 0;
  let lastY = 0;

  function rowDown(e: PointerEvent, row: CollectionRow) {
    if (e.button !== 0 || e.ctrlKey || e.metaKey || e.altKey || filtering) return;
    if (drag?.settling) finishSettle();
    if (drag) return;
    drag = { row, id: e.pointerId, x0: e.clientX, y0: e.clientY, el: e.currentTarget as HTMLElement, started: false,
      grab: 0, left: 0, width: 0, top: 0, fromFav: row.place === 'favourites', over: false, at: 0, settling: false };
  }
  /** The Favourites rows the drag lands among (the dragged one left out) and where their first one stands. */
  function favGeometry(d: Drag): { top: number; n: number; zone: [number, number] } | null {
    if (!favBox) return null;
    const box = favBox.getBoundingClientRect();
    const n = favKeys.filter((k) => !(d.fromFav && k === d.row.target)).length;
    const head = favBox.previousElementSibling?.getBoundingClientRect();
    return { top: box.top, n, zone: [(head?.top ?? box.top) - ROW_H / 2, box.top + Math.max(n, 1) * ROW_PITCH + ROW_H / 2] };
  }
  function place(d: Drag, y: number) {
    d.top = y - d.grab;
    const g = favGeometry(d);
    if (!g) return;
    const mid = d.top + ROW_H / 2;
    d.over = inDropZone(mid, g.zone);
    const mids = Array.from({ length: g.n }, (_, i) => g.top + i * ROW_PITCH + ROW_H / 2);
    d.at = d.over ? Math.min(g.n, dropIndex(mids, mid)) : d.at;
  }
  function winMove(e: PointerEvent) {
    const d = drag;
    if (!d || d.settling || e.pointerId !== d.id) return;
    lastY = e.clientY;
    if (!d.started) {
      if (Math.hypot(e.clientX - d.x0, e.clientY - d.y0) < THRESHOLD) return;
      const r = d.el.getBoundingClientRect();
      d.started = true;
      d.grab = d.y0 - r.top;
      d.left = r.left;
      d.width = r.width;
      try { scroller?.setPointerCapture(d.id); } catch { /* a pointer that isn't pressed (a synthetic one) */ }
      document.documentElement.classList.add('fav-drag');
    }
    place(d, e.clientY);
    autoScroll();
  }
  /** While the pointer holds near the list's top or bottom, the list scrolls towards it (Favourites is near the top,
   *  a playlist far down). */
  function autoScroll() {
    if (autoRaf || !scroller) return;
    const step = () => {
      autoRaf = 0;
      const d = drag;
      if (!d?.started || d.settling || !scroller) return;
      const s = scroller.getBoundingClientRect();
      const edge = 28;
      const v = lastY < s.top + edge ? -Math.ceil((s.top + edge - lastY) / 3)
        : lastY > s.bottom - edge ? Math.ceil((lastY - s.bottom + edge) / 3) : 0;
      if (!v) return;
      const before = scroller.scrollTop;
      scroller.scrollTop += v;
      if (scroller.scrollTop === before) return;
      place(d, lastY);
      autoRaf = requestAnimationFrame(step);
    };
    autoRaf = requestAnimationFrame(step);
  }
  async function winUp(e: PointerEvent) {
    const d = drag;
    if (!d || d.settling || e.pointerId !== d.id) return;
    if (!d.started) { drag = null; return; }
    swallowClick = true;
    setTimeout(() => (swallowClick = false), 0);
    await settle(d, d.over);
  }
  /** The lifted row settles where it lands (the slot), or goes back to its own row; then the order is committed. */
  async function settle(d: Drag, drop: boolean) {
    d.settling = true;
    // going back: nothing lands, so the gap closes as the row returns
    if (!drop) d.over = false;
    cancelAnimationFrame(autoRaf);
    autoRaf = 0;
    const from = d.top;
    let to = from;
    if (drop) {
      const slot = scroller?.querySelector<HTMLElement>('[data-fav-slot]');
      if (slot) to = slot.getBoundingClientRect().top;
    } else {
      // back to its own row (a favourite's comes back into its place, hidden until the lifted one is there)
      await tick();
      const src = scroller?.querySelector<HTMLElement>(`[data-key="${CSS.escape(d.row.key)}"]`);
      to = src ? src.getBoundingClientRect().top : from;
    }
    d.top = to;
    await tick();
    const reduced = typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
    const el = lifted;
    if (el && !reduced && typeof el.animate === 'function') {
      const { duration, easing } = dropSpring(to - from);
      const a = el.animate([{ transform: `translateY(${from - to}px) translateX(3px) scale(1.02)` },
        { transform: 'none' }], { duration, easing });
      settleAnim = a;
      try { await a.finished; } catch { /* cancelled by a new press: finishSettle committed already */ }
      if (settleAnim !== a) return;
    }
    finishSettle();
  }
  let settleAnim: Animation | null = null;
  function finishSettle() {
    const d = drag;
    settleAnim = null;
    document.documentElement.classList.remove('fav-drag');
    drag = null;
    if (d?.started && d.over) {
      const next = moveKey(favKeys, d.row.target, d.at);
      showFavourites();
      if (next.join('\n') !== favKeys.join('\n')) void saveFavs(next);
    }
  }
  /** Favourites open (they were folded): a row added by a drop or the menu lands where it shows. */
  function showFavourites() {
    if ($browserClosed.includes('favourites')) fold('favourites');
  }
  function cancelDrag() {
    const d = drag;
    if (!d) return;
    if (!d.started) { drag = null; return; }
    if (!d.settling) void settle(d, false);
  }
  function winKey(e: KeyboardEvent) {
    if (e.key === 'Escape' && drag?.started && !drag.settling) {
      e.preventDefault();
      e.stopPropagation();
      void settle(drag, false);
    }
  }
  // a click that ends a drag opens nothing (caught on the way down, before the row's link)
  function clickCapture(e: MouseEvent) {
    if (!swallowClick) return;
    e.preventDefault();
    e.stopPropagation();
  }
  $effect(() => () => {
    cancelAnimationFrame(autoRaf);
    document.documentElement.classList.remove('fav-drag');
  });

  const live = $derived(drag?.started ? drag : null);
  /** Favourites as drawn: the rows (the one dragged out of them left out) and, where it will land, the slot */
  type FavItem = { key: string; row: CollectionRow | null; ghost?: boolean };
  const favItems = $derived.by((): FavItem[] => {
    const s = list.sections.find((x) => x.key === 'favourites');
    if (!s) return [];
    // the dragged favourite is out of the list while in the air; going back, its place holds it, hidden under the
    // lifted row until that lands
    const back = !!live?.fromFav && live.settling && !live.over;
    // a row dragged in from Playlists or Folders that already is a favourite is not drawn twice: while it is over
    // Favourites the slot is where it is
    const out = (r: CollectionRow) => !!live && r.target === live.row.target && (live.fromFav || live.over);
    const rows: FavItem[] = s.rows.filter((r) => back || !out(r))
      .map((r) => ({ key: r.key, row: r, ghost: back && r.target === live?.row.target }));
    if (live?.over && (rows.length || live.fromFav)) rows.splice(Math.min(live.at, rows.length), 0, { key: '__slot', row: null });
    return rows;
  });
  // a drag from Playlists or Folders opens a folded Favourites for as long as it lasts: it is where the row goes
  const favOpen = (open: boolean) => open || (!!live && !live.fromFav);
  const leadState = (r: CollectionRow) => (r.kind === 'folder' && r.state !== 'here' ? AWAY[r.state] : null);
</script>

<svelte:window onpointermove={winMove} onpointerup={winUp} onpointercancel={(e) => { if (drag && e.pointerId === drag.id) cancelDrag(); }}
  onkeydown={winKey} />

{#snippet name(text: string, m: Match)}
  <span class="t">{#each nameParts(text, m) as p, i (i)}{#if p.hl}<b class="hl" class:sep={p.sep}>{p.text}</b>{:else if p.sep}<span
    class="sep">{p.text}</span>{:else}{p.text}{/if}{/each}</span>
{/snippet}


{#snippet inner(r: CollectionRow, count: boolean)}
  {#if !r.indent}<RowLead row={r} />{/if}
  {@render name(r.name, r.match)}
  {#if r.kind === 'playlist' && !r.enabled}<span class="sr-only">, switched off</span>{/if}
  {#if leadState(r)}<span class="sr-only">, {leadState(r)}</span>{/if}
  {#if r.kind === 'folder' && r.fold}<span class="chev-room" aria-hidden="true"></span>{/if}
  {#if count}<span class="n num" class:cw={r.kind === 'folder' && r.folder === 'watched'}>{r.count === null ? '' : thousands(r.count)}</span>{/if}
{/snippet}

{#snippet row(r: CollectionRow)}
  <a class="row" class:on={at === r.key} class:kb={hi === r.key} class:off={r.kind === 'playlist' && !r.enabled}
    class:indent={r.indent} class:menu-on={menu?.row.key === r.key}
    href={r.href} use:link use:tip={r.tip} draggable="false" onclick={() => opened(r)} data-key={r.key} id={rowId(r.key)}
    role={filtering ? 'option' : undefined} aria-selected={filtering ? hi === r.key : undefined}
    aria-current={at === r.key ? 'page' : undefined} onpointerdown={(e) => rowDown(e, r)}
    oncontextmenu={(e) => openMenu(e, r)} onkeydown={(e) => menuKey(e, r)}
    data-test={r.place === 'favourites' ? 'browser-fav' : r.kind === 'folder' && r.indent ? 'browser-crate' : 'browser-row'}>
    {@render inner(r, true)}
  </a>
  {#if r.kind === 'folder' && r.fold}
    {@const f = r.fold}
    <button type="button" class="chev" class:open={f.open} aria-expanded={f.open}
      aria-label={foldWatchedTip(f.open, r.name)} use:tip={foldWatchedTip(f.open, r.name)}
      onclick={() => fold(f.key)} data-test="browser-fold-watched"><svg viewBox="0 0 8 8" aria-hidden="true"><path
        d="M2.6 1.2 5.6 4l-3 2.8" /></svg></button>
  {/if}
{/snippet}

<div class="col" data-test="browser">
  <div class="find">
    <SearchField bind:value={query} bind:input placeholder="Filter playlists, folders" shortcut="cmd+k" fill
      onkeydown={keydown} test="browser-filter" role="combobox" aria-controls="bc-list" aria-expanded={filtering}
      aria-autocomplete="list" aria-activedescendant={filtering && hi ? rowId(hi) : undefined} />
  </div>

  <div class="list" id="bc-list" bind:this={scroller} role={filtering ? 'listbox' : undefined}
    aria-label={filtering ? 'Matches' : undefined} onclickcapture={clickCapture} data-test="browser-list"
    style:--count-w="{list.countCh}ch">
    {#each list.views as v (v.key)}
      <a class="row" class:on={at === v.key} class:menu-on={menu?.row.key === v.key} href={v.href} use:link
        draggable="false" onclick={() => opened(v)} oncontextmenu={(e) => openMenu(e, v)} onkeydown={(e) => menuKey(e, v)}
        data-key={v.key} id={rowId(v.key)} aria-current={at === v.key ? 'page' : undefined}
        data-test={v.key === 'view:all' ? 'browser-all' : 'browser-unlisted'}>
        <span class="t">{v.name}</span><span class="n num">{thousands(v.count)}</span>
      </a>
    {/each}

    {#each list.sections as s (s.key)}
      {@const open = s.key === 'favourites' ? favOpen(s.open) : s.open}
      <ListSection label={s.label} summary={s.count === null ? undefined : thousands(s.count)} on="chrome" stick="both"
        fold={{ open, toggle: () => fold(s.key), disabled: !s.foldable }} test="browser-section-{s.key}">
        {#if s.key === 'playlists'}
          <span class="sort" use:tip={sortTip($playlistsAz)}>
            <Button variant="icon" size="xs" pressed={$playlistsAz} aria-label="Order A to Z"
              onclick={toggleAz} data-test="browser-az">
              <svg viewBox="0 0 12 12" aria-hidden="true"><path d="M1.5 3h9M1.5 6h6.5M1.5 9h4" /></svg>
            </Button>
          </span>
        {/if}
      </ListSection>
      {#if s.key === 'favourites'}
        {#if open}
          <div class="favs" bind:this={favBox} data-test="browser-favourites">
            {#each favItems as it (it.key)}
              <div class="fi" class:ghost={it.ghost} animate:flip={{ duration: flipMs, easing: cubicOut }}>
                {#if it.row}{@render row(it.row)}{:else}<div class="slot" data-fav-slot aria-hidden="true"></div>{/if}
              </div>
            {:else}
              <div class="landing" class:over={live?.over} data-fav-slot data-test="browser-landing">{LANDING_TEXT}</div>
            {/each}
          </div>
        {/if}
      {:else if s.open}
        {#each s.rows as r (r.key)}
          <div class="ri" class:context={r.kind === 'folder' && r.context}>{@render row(r)}</div>
        {/each}
      {/if}
    {/each}

    {#if list.handoff}
      {@const h = list.handoff}
      <a class="row handoff" class:kb={hi === HANDOFF} class:alone={!list.sections.length} href={h.href} use:link
        use:tip={h.tip} onclick={() => opened(h)} data-key={HANDOFF} id={rowId(HANDOFF)} role="option"
        aria-selected={hi === HANDOFF} draggable="false" data-test="browser-handoff">
        <span class="lead"><svg class="mag" viewBox="0 0 12 12" aria-hidden="true"><circle cx="5.2" cy="5.2" r="3.9" /><path
          d="M8.1 8.1 11 11" /></svg></span>
        <span class="t">Search tracks for “{h.text}”</span>
        <span class="n ret" aria-hidden="true">↵</span>
      </a>
    {/if}
  </div>
</div>

{#if live}
  <div class="row lift" class:off={live.row.kind === 'playlist' && !live.row.enabled} bind:this={lifted}
    style:left="{live.left}px" style:top="{live.top}px" style:width="{live.width}px" aria-hidden="true"
    data-test="browser-lifted">
    {#if live.row.indent}<RowLead row={live.row} lead="folder" />{/if}
    {@render inner(live.row, true)}
  </div>
{/if}

{#if menu}
  <ContextMenu x={menu.x} y={menu.y} items={menuItems} onclose={closeMenu} focusFirst={menu.keys} test="browser-menu" />
{/if}

<style>
  /* the room under the list belongs to the column, not the scroller: a head stuck at the list's foot is its last
     pixel, and no row shows below it */
  .col { flex: 1; min-height: 0; display: flex; flex-direction: column; padding-bottom: var(--s-3); }
  .find { flex: none; padding: 0 var(--s-2) var(--s-2); }
  /* one scroller for the rows and their heads; no scrollbar of its own (the column is chrome, the stuck heads and the
     rows passing under them say there is more) */
  .list { position: relative; flex: 1; min-height: 0; display: flex; flex-direction: column; gap: 2px;
    overflow-y: auto; padding: 0 var(--s-2); scrollbar-width: none; }
  .list::-webkit-scrollbar { display: none; }
  /* a section's head stands a little apart from the rows above it */
  .list > :global([data-list-section]) { margin-top: var(--s-3); }
  /* a row's box in a section (with its chevron, if any); Favourites' rows in their own column, so they part as one */
  .ri, .fi { position: relative; flex: none; display: flex; flex-direction: column; }
  .favs { display: flex; flex-direction: column; gap: 2px; flex: none; }
  .fi.ghost { visibility: hidden; }

  .row { display: flex; align-items: center; gap: var(--gap-nav); height: var(--h-ctl); flex-shrink: 0; padding: 0 var(--s-2);
    color: var(--text-nav); border-radius: var(--r-nav); text-decoration: none; white-space: nowrap; min-width: 0;
    user-select: none; -webkit-user-select: none; }
  .row:hover { color: var(--text); background-color: var(--ctl-hover); text-decoration: none; }
  .row:not(.on):hover { transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  /* the collection on screen: the sidebar's pill, at once (a background image never transitions) */
  .row.on { color: var(--text-strong); background-image: linear-gradient(var(--nav-on-bg), var(--nav-on-bg)); }
  .row:active:not(.on) { background-color: var(--ctl-press); transition: none; }
  /* while filtering, the one row Enter opens: the orange wash (on the hand-off with ↵) */
  .row.kb { color: var(--text-strong); background-color: var(--accent-wash-strong); }
  /* the row the open right-click menu acts on: the orange ring (orange = action) */
  .row.menu-on { color: var(--text); box-shadow: inset 0 0 0 var(--bw) var(--accent-line); }
  /* a switched-off playlist: the one dim in the column, the whole row with its logo */
  .row.off { opacity: var(--dim-locked); }
  /* a crate under its watched folder: no lead, its name on the names' edge (8 + 14 + 9 px) */
  .row.indent { padding-left: calc(var(--s-2) + 14px + var(--gap-nav)); }
  .lead { width: 14px; height: 14px; flex: none; display: grid; place-items: center; }
  .t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  /* a crate's place in its name keeps the row's colour; only the separator is quiet (dim is reserved) */
  .sep { color: var(--text-label); }
  .hl { color: var(--text-strong); font-weight: var(--fw-semi); }
  .hl.sep { font-weight: normal; }
  .n { flex: none; min-width: 14px; margin-left: var(--s-1); text-align: right; color: var(--text-label);
    font-size: var(--fs-label); }
  /* a watched folder's count takes the widest one's room, so the chevrons before them line up */
  .n.cw { min-width: var(--count-w); }
  .on .n, .kb .n { color: var(--text-muted); }

  /* a watched folder's chevron: its own button over the row, just before the count (the row is a link; a button
     can't sit inside one); turns open (pointing down) like the section heads' */
  .chev-room { width: 4px; flex: none; }
  /* its glyph ends 6 px before the count; label size, so the count's width in ch reads the same here */
  .chev { position: absolute; top: 4px; right: calc(var(--s-2) + var(--count-w) + 2px); min-width: 16px; height: 22px;
    font-size: var(--fs-label);
    display: grid; place-items: center; padding: 0; border: 0; border-radius: var(--r-icon); background: transparent;
    color: var(--text-label); }
  .chev:hover { background-color: var(--ctl-hover); color: var(--text); transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  .chev:active { background-color: var(--ctl-press); transition: none; }
  .chev svg { width: 8px; height: 8px; fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round;
    stroke-linejoin: round; transition: transform var(--t-state) var(--ease); }
  .chev.open svg { transform: rotate(90deg); }

  /* Favourites, empty: the one dashed row, where a dragged row lands; lit while a row is over it (the drop zone's
     wash) */
  .landing { height: var(--h-ctl); flex: none; display: flex; align-items: center; padding: 0 var(--s-2);
    border: var(--bw) dashed var(--line-control-hover); border-radius: var(--r-nav); color: var(--text-label);
    font-size: var(--fs-small); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .landing.over { border-color: var(--accent-line); background-color: var(--accent-wash); color: var(--text); }
  /* where the dragged row will land: room only, the lifted row hovers over it */
  .slot { height: var(--h-ctl); flex: none; }
  /* the row in the air: the popover material, raised, 1.02 and nudged towards the pointer (lift 120 ms); it follows
     the pointer 1:1 (top, no transition) */
  .lift { position: fixed; z-index: 12; margin: 0; pointer-events: none; color: var(--text-strong);
    background: var(--popover-bg); box-shadow: 0 0 0 var(--bw) var(--popover-line), var(--shadow);
    transform: translateX(3px) scale(1.02); transition: transform 120ms var(--ease), box-shadow 120ms var(--ease); }
  @starting-style { .lift { transform: none; box-shadow: none; } }
  :global(html.fav-drag), :global(html.fav-drag *) { cursor: grabbing !important; user-select: none !important;
    -webkit-user-select: none !important; }
  @media (prefers-reduced-motion: reduce) {
    .lift { transform: none; transition: none; }
  }

  .handoff { margin-top: var(--s-1); }
  .handoff.alone { margin-top: 0; }
  .mag { width: 12px; height: 12px; fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round;
    color: var(--text-muted); }
  .ret { font-size: var(--fs-small); visibility: hidden; }
  .handoff.kb .ret { visibility: visible; }

  .sort { display: inline-flex; }
  .sort :global(svg) { fill: none; stroke: currentColor; stroke-width: 1.3; stroke-linecap: round; }
</style>
