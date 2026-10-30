<script lang="ts">
  // The chrome (plan library stage 5, A4; notes N1, N2, N7, N11; design language "the frame is an L"): the app's
  // sidebar in one of its two forms, full (168 px) or rail (50 px), and in Library the browser column beside it. The
  // rail is the full sidebar with its labels folded away: the fold button, every page's icon and every row keep their
  // place, so no icon moves. The frame's material (--sidebar-bg) is painted by App behind the chrome and the foot, so
  // the L they form has no seam.
  //
  // Motion (notes "Motion"; design language §5): the page lays out once, the chrome moves over it. The page takes the
  // chrome's width at once (`.space`, `--sidebar-w`); the chrome itself (`.chrome`) lies over the body's left edge and
  // follows with a CSS transition of its own width, its right border being the page's edge line. So a shrinking chrome
  // uncovers a page that is already laid out, and a growing one covers room already empty. `foot`: the foot is there,
  // so the chrome also covers the foot's first two pixel rows (its line, the played part) up to its own edge, and
  // `.floor` draws the line from the chrome's edge to the page's while the chrome is narrower: the L stays joined
  // mid-glide. Which timings
  // apply comes from the move that led to the layout (`data-move`, chromeMotion): fold, into or out of Library, the
  // step-back and its return, the edge's reset; `none` is at once. All CSS transitions, so a second ⌃⌘S turns a fold
  // round from where it is. The browser column stays mounted outside Library (`away`: hidden, inert, its scroll kept),
  // so its arrival and leaving are transitions too.
  import { get } from 'svelte/store';
  import { hub, hubSyncRunning } from '../stores/hub';
  import { route, link } from '../router';
  import { updateLink } from '../appUpdate';
  import { ExternalLink, NavIcon, Ring, tip } from '../components';
  import { player } from '../stores/player';
  import { run } from '../stores/run';
  import {
    BROWSER_DEFAULT, BROWSER_MAX, BROWSER_MIN, bringBrowserBack, chromeMotion, edgeCursor, edgeKeyWidth, fold,
    lastLibrary, setBrowserWidth,
  } from '../stores/chrome';
  import { EDGE_TIP } from './browserModel';
  import { activityProgress } from './activity';
  import { FOLD_KEYS, NAV, SETTINGS, type NavPage } from './keys';
  import { navCount, navTip, railPill, type NavSignals } from './sidebarModel';
  import NowPlayingRow from './NowPlayingRow.svelte';
  import BrowserColumn from './BrowserColumn.svelte';

  let { foot = false }: { foot?: boolean } = $props();

  // what the chrome shows: the layout and the move that led to it. Into Library the page's first frame is a long one
  // (the table mounts), and a glide started with it would be mostly over before anything is drawn, so the chrome waits
  // until that frame has painted (two animation frames) and then glides the whole way, over room the page has
  // already left empty. Any other change, or a second one meanwhile, applies at once; so does everything under
  // reduced motion, where nothing glides and a held frame would only leave the browser's room empty.
  const reduced = () => typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;
  let motion = $state(get(chromeMotion));
  let pending = 0;
  $effect.pre(() => {
    const m = $chromeMotion;
    cancelAnimationFrame(pending);
    pending = 0;
    if (m.move !== 'into' || reduced()) { motion = m; return; }
    pending = requestAnimationFrame(() => { pending = requestAnimationFrame(() => { pending = 0; motion = m; }); });
  });
  $effect(() => () => cancelAnimationFrame(pending));
  // the foot's first rows under the chrome: they come with the foot at once, and go only once the foot has gone (its
  // slowest way out, Hide's fold, takes 240 ms; Foot.svelte's motion), so the chrome's edge strip never retracts
  // while the foot's line is still there
  const FOOT_LEAVES_MS = 240;
  let footHeld = $state(false);
  $effect(() => {
    if (foot) { footHeld = true; return; }
    const t = setTimeout(() => (footHeld = false), FOOT_LEAVES_MS);
    return () => clearTimeout(t);
  });
  const L = $derived(motion.layout);
  const rail = $derived(L.form === 'rail');
  const side = $derived($hub.sidebar);
  const update = $derived(updateLink($hub.app_update));
  const r = $derived($route);
  const syncing = $derived($hubSyncRunning && ['preparing', 'running', 'stopping'].includes($run.phase));
  const sig: NavSignals = $derived({
    todo: side?.todo ?? 0,
    sync: syncing ? { index: $run.index, total: $run.total, frac: activityProgress($run) } : null,
    limitsWarning: !!side?.limits_warning,
  });
  const pill = $derived(railPill(sig.todo));
  const isOn = (n: NavPage) => r.name === n.key || (n.also ?? []).includes(r.name);
  // Library goes back to the collection it was left at; on Library itself it stays where it is
  const here = $derived(`#${r.path}${r.query.toString() ? `?${r.query}` : ''}`);
  const hrefOf = (n: NavPage) => (n.key !== 'library' ? n.href : r.name === 'library' ? here : $lastLibrary);
  const foldTip = $derived({ text: rail ? 'Show sidebar' : 'Hide sidebar', keys: FOLD_KEYS, side: 'right' as const });
  const navTipOf = (n: NavPage) => (rail ? { text: navTip(n.key, n.label, sig), keys: n.keys, side: 'right' as const } : null);
  // the browser's edge (notes N4): a 9 px grip on the page's edge line, outside the chrome (whose overflow would cut
  // its outer half). Dragged 1:1 with no easing (pointer capture, the width at once, the table reflows live), held to
  // 200–360; while dragging the line is orange and the resize cursor stays wherever the pointer goes. A double-click
  // goes back to 240 in the fold's glide. It is a focusable separator too: ← → (⇧ larger steps), Home, End.
  let drag = $state<{ x0: number; w0: number; id: number } | null>(null);
  function edgeDown(e: PointerEvent) {
    if (e.button !== 0 || drag) return;   // one pointer at a time: a second touch doesn't take over
    e.preventDefault();
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    drag = { x0: e.clientX, w0: L.browserWidth, id: e.pointerId };
  }
  function edgeMove(e: PointerEvent) {
    if (drag && e.pointerId === drag.id) setBrowserWidth(drag.w0 + e.clientX - drag.x0);
  }
  function edgeUp(e: PointerEvent) {
    if (drag && e.pointerId === drag.id) drag = null;
  }
  function edgeKey(e: KeyboardEvent) {
    const w = edgeKeyWidth(e.key, L.browserWidth, e.shiftKey);
    if (w === null) return;
    e.preventDefault();
    setBrowserWidth(w);
  }
  $effect(() => {
    if (!drag) return;
    const root = document.documentElement;
    root.classList.add('edge-drag');
    return () => root.classList.remove('edge-drag');
  });
  // ♫ while the browser waits behind the rail (below 1240 with details open): the details close, the browser returns
  function libraryClick() {
    if (r.name === 'library') bringBrowserBack();
  }
</script>

<div class="space" aria-hidden="true"></div>
<span class="floor" class:foot={footHeld} aria-hidden="true"></span>
{#if L.browserShown}
  <!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_noninteractive_element_interactions -->
  <div class="edge" class:drag={!!drag} role="separator" aria-orientation="vertical" aria-label="Width of the list"
    aria-valuemin={BROWSER_MIN} aria-valuemax={BROWSER_MAX} aria-valuenow={L.browserWidth} tabindex="0"
    style:cursor={drag ? null : edgeCursor(L.browserWidth)} use:tip={drag ? null : EDGE_TIP}
    onpointerdown={edgeDown} onpointermove={edgeMove} onpointerup={edgeUp} onpointercancel={edgeUp}
    ondblclick={() => setBrowserWidth(BROWSER_DEFAULT, true)} onkeydown={edgeKey} data-test="browser-edge"></div>
{/if}
<div class="chrome" class:foot={footHeld} data-chrome data-form={L.form} data-browser={L.browserShown || undefined}
  data-move={motion.move} style:--chrome-w="{L.sidebarW}px">
  <nav class="side chrome-part" class:rail class:beside={L.browserShown} aria-label="Main" data-test="sidebar"
    style:--form-w={rail ? 'var(--rail-w)' : 'var(--sidebar-full-w)'}>
    <div class="head">
      <button type="button" class="tog" aria-label={foldTip.text} aria-expanded={!rail} use:tip={foldTip} onclick={fold}
        data-test="sidebar-fold">
        <svg viewBox="0 0 16 13" aria-hidden="true"><rect x=".75" y=".75" width="14.5" height="11.5" rx="2.6" /><path
          d="M5.6 1v11" /><path class="ln" d="M2.4 3.4h1.6M2.4 5.4h1.6M2.4 7.4h1.6" /></svg>
      </button>
      <span class="brand lab">Discjockey</span>
    </div>
    <!-- a newer version is out (spec public-release §8): one quiet line that belongs to the brand and folds with it; it
         keeps its height in the rail, so no row below moves -->
    {#if update}<div class="update lab" data-test="update-line"><ExternalLink href={update.url}>{update.text}</ExternalLink></div>{/if}

    {#each NAV as n (n.key)}
      {@const on = isOn(n)}
      {@const count = navCount(n.key, sig)}
      <a class="nav" class:on href={hrefOf(n)} use:link use:tip={navTipOf(n)} aria-current={on ? 'page' : undefined}
        aria-label={rail ? navTip(n.key, n.label, sig) : undefined} onclick={n.key === 'library' ? libraryClick : undefined}
        data-test="nav-{n.key}">
        <span class="g" aria-hidden="true">
          <NavIcon name={n.icon} />
          {#if n.key === 'limits' && sig.limitsWarning}<span class="warn" data-test="limits-dot"></span>{/if}
          {#if n.key === 'sync' && sig.sync}<span class="ring ro" data-test="sync-ring"><Ring mark size={26} value={sig.sync.frac}
            max={1} tone="muted" /></span>{/if}
          {#if n.key === 'todo' && pill}<span class="pill ro num" class:wide={pill.length > 2}
            data-test="todo-pill">{pill}</span>{/if}
        </span>
        <span class="t lab">{n.label}</span>
        {#if count}<span class="n num lab">{count}</span>{/if}
      </a>
    {/each}

    <div class="spacer"></div>
    <!-- the hidden player bar, folded into the sidebar's foot (plan now-playing; in the rail its stacked form) -->
    <NowPlayingRow p={$player} {rail} />

    <a class="nav settings" class:on={r.name === 'settings'} href={SETTINGS.href} use:link use:tip={navTipOf(SETTINGS)}
      aria-current={r.name === 'settings' ? 'page' : undefined} aria-label={rail ? SETTINGS.label : undefined}
      data-test="nav-settings">
      <span class="g" aria-hidden="true"><NavIcon name="settings" /></span><span class="t lab">{SETTINGS.label}</span>
    </a>
  </nav>

  <div class="browser chrome-part" class:away={!L.browserShown} style:width="{L.browserWidth}px" inert={!L.browserShown}
    aria-hidden={!L.browserShown || undefined} data-test="browser-column">
    <BrowserColumn />
  </div>
</div>

<style>
  /* the page's room for the chrome: --sidebar-w, at once (the page lays out once) */
  .space { width: var(--sidebar-w); flex: none; }
  /* the chrome: over the body's left edge, as wide as --sidebar-w, its right border the page's edge line. Opaque in the
     frame's material (fixed to the window, so it is the very gradient App paints behind it) */
  .chrome { position: absolute; left: 0; top: 0; bottom: 0; z-index: 4; width: var(--chrome-w); display: flex;
    overflow: hidden; border-right: var(--bw) solid var(--surface-line); background: var(--sidebar-bg) fixed; }
  /* with the foot there the chrome also covers the foot's first two rows (its line and the played part's 2 px) up to
     the chrome's edge; .floor draws the line from the chrome's edge to the page's while the chrome is narrower than
     the page's room. At rest both lie under the chrome, where the foot shows only its material anyway */
  .chrome.foot { bottom: calc(-1 * var(--foot-edge-h)); }
  .floor { position: absolute; left: 0; bottom: calc(-1 * var(--bw)); z-index: 3; width: var(--sidebar-w);
    height: var(--bw); background: var(--surface-line); display: none; }
  .floor.foot { display: block; }

  /* the browser's edge: a 9 px grip centred on the page's edge line (the chrome's right border, its last pixel), over
     the chrome and the page's first pixels. Hovered for a moment the line lights up a step (a neutral line: orange
     means the width is being set); while dragging it is the accent, 2 px, and follows the pointer at once */
  .edge { position: absolute; top: 0; bottom: 0; left: calc(var(--sidebar-w) - 5px); width: 9px; z-index: 5;
    touch-action: none; outline: none; }
  .edge::after { content: ''; position: absolute; top: 0; bottom: 0; left: 4px; width: var(--bw);
    background: transparent; transition: background-color var(--t-hover) var(--ease); }
  .edge:hover::after { background: var(--line-control-hover); transition-delay: 300ms; }
  .edge:focus-visible::after { background: var(--accent-line); width: 2px; }
  .edge.drag::after { width: 2px; background: var(--accent); transition: none; }
  :global(html.edge-drag), :global(html.edge-drag *) { cursor: col-resize !important; user-select: none !important;
    -webkit-user-select: none !important; }

  .side { position: relative; width: var(--form-w); flex: none; padding: var(--s-4) 10px;
    display: flex; flex-direction: column; gap: 2px; min-height: 0; overflow: hidden; }
  /* the second chrome line: the sidebar's right edge while the browser stands beside it (pages | collections) */
  .side::after { content: ''; position: absolute; top: 0; right: 0; bottom: 0; width: var(--bw);
    background: var(--surface-line); opacity: 0; }
  .side.beside::after { opacity: 1; }
  /* it ends where the foot begins: the foot's first row is the page's lower edge, not the chrome's */
  .chrome.foot .side::after { bottom: var(--foot-edge-h); }

  .head { display: flex; align-items: center; height: 22px; margin-bottom: var(--s-2); flex: none; }
  /* the fold button sits on the glyph column (18–32 px) in both forms, so it never moves */
  .tog { width: 30px; min-width: 30px; height: 22px; flex: none; display: grid; place-items: center; padding: 0; border: 0;
    border-radius: var(--r-icon); background: transparent; color: var(--text-label); }
  .tog:hover { background-color: var(--ctl-hover); color: var(--text); transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  .tog:active { background-color: var(--ctl-press); transition: none; }
  .tog svg { width: 16px; height: 13px; fill: none; stroke: currentColor; stroke-width: 1.3; }
  .tog svg .ln { stroke-width: 1; stroke-linecap: round; }
  .brand { padding-left: 1px; color: var(--text-dim); font-weight: var(--fw-bold); white-space: nowrap; }
  /* the update line (spec public-release §8: "Discjockey 1.1 is available"): label size, the brand's left edge, the full
     sentence wrapped in balance into two even lines; the nav moves down by it only while it shows, at most once per
     session */
  .update { margin: calc(-1 * var(--s-1)) 0 var(--s-2) 31px; font-size: var(--fs-label); line-height: 1.4;
    text-wrap: balance; flex: none; }

  .nav { display: flex; align-items: center; gap: 9px; height: var(--h-ctl); flex-shrink: 0; padding: 0 var(--s-2);
    color: var(--text-nav); border-radius: var(--r-nav); text-decoration: none; white-space: nowrap; min-width: 0; }
  .nav:hover { color: var(--text); background-color: var(--ctl-hover); text-decoration: none; }
  /* hover fades in its fill and its text together (spec §6, --t-hover) and goes at once (exit faster than enter).
     The transition lives only on the hovered, unselected item, so selection never animates: the item that becomes
     selected and the one that stops being selected both change at once */
  .nav:not(.on):hover { transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  /* the selected pill is a background image, which never transitions: it moves with the page at once. In the rail it
     is the 30 × 30 square on the same spot */
  .nav.on { color: var(--text-strong); background-color: transparent;
    background-image: linear-gradient(var(--nav-on-bg), var(--nav-on-bg)); }
  /* held down: lit at once, no shrinking (it is a list item). The selected item is lit already */
  .nav:active:not(.on) { background-color: var(--ctl-press); transition: none; }
  /* the page's drawn icon on the glyph column, a little quieter than the name; full strength when selected */
  .g { position: relative; width: 14px; height: 14px; flex: none; display: grid; place-items: center; }
  .g :global(.nav-icon) { opacity: .8; }
  .on .g :global(.nav-icon) { opacity: 1; }
  .warn { position: absolute; top: -1px; right: -4px; width: 6px; height: 6px; border-radius: var(--r-pill);
    background: var(--q-good); }  /* yellow = a warning sign or a pause (spec §4) */
  /* the rail's marks: a running sync's neutral ring round ⟳ (its arc the share done), To-do's count as a neutral pill
     on the glyph's top-right corner, growing rightwards (the mockup's place), ringed in the frame's colour */
  .ring { position: absolute; left: 50%; top: 50%; transform: translate(-50%, -50%); pointer-events: none; }
  .pill { position: absolute; left: 11px; top: -9px; min-width: 18px; height: 14px; padding: 0 4px;
    border-radius: var(--r-pill); background: var(--rail-pill-bg); box-shadow: 0 0 0 2px var(--sidebar-solid);
    color: var(--text); font-size: var(--fs-label); font-weight: var(--fw-semi); line-height: 14px; text-align: center; }
  /* "99+" would cross the rail's edge from there: it alone ends 2 px inside the rail, a little tighter, and grows
     leftwards, so it covers only the glyph's top-right corner as a two-digit count does */
  .pill.wide { left: auto; right: -16px; padding: 0 3px; letter-spacing: -.2px; }
  .t { flex: 1 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .n { margin-left: auto; color: var(--text-label); font-size: var(--fs-label); padding-left: var(--s-1); }
  .on .n { color: var(--text-muted); }
  /* each form shows its own: the labels and the count column in the full form, the marks in the rail. Hidden ones keep
     their place (visibility), so nothing moves when the form changes */
  .rail .lab { opacity: 0; visibility: hidden; }
  .side:not(.rail) .ro { opacity: 0; visibility: hidden; }
  .spacer { flex: 1; min-height: 0; }
  .settings { margin-top: var(--s-2); }

  /* the browser's filter field on the page header's row: level with the page's own search field (30 px, which the
     header's baseline puts 4 px below the page's 16 px padding) */
  .browser { position: relative; flex: none; display: flex; flex-direction: column; min-height: 0;
    padding-top: calc(var(--s-4) + 4px); --away-x: -8px; }
  .browser.away { opacity: 0; visibility: hidden; transform: translateX(var(--away-x)); }

  /* ---------- motion (the notes' motion table) ---------- */
  /* the edge: the chrome and the sidebar's form glide together on the drawer curve, no bounce */
  .chrome { --edge-dur: 0ms; --edge-delay: 0ms; --lab-delay: calc(var(--t-fold) - var(--t-fold-fade-in)); }
  .chrome[data-move='fold'], .chrome[data-move='into'], .chrome[data-move='reset'] { --edge-dur: var(--t-fold); }
  /* out of Library quicker: the browser's rows fade in 90 ms, then the edge glides back (done at 200 ms, entry 220) */
  .chrome[data-move='out'] { --edge-dur: var(--t-fold-exit); --edge-delay: var(--t-fold-exit-delay);
    --lab-delay: calc(var(--t-fold-exit-delay) + var(--t-fold-exit) - var(--t-fold-fade-in)); }
  .chrome[data-move='step-back'] { --edge-dur: var(--t-slide-out); }
  .chrome[data-move='step-in'] { --edge-dur: var(--t-slide-in); }
  .chrome, .side { transition: width var(--edge-dur) var(--ease-drawer) var(--edge-delay); }
  /* the labels: out in the first 90 ms, in during the last 120 ms; the rail's marks the other way round. Hidden ones
     turn invisible only once faded */
  .lab, .ro { transition: opacity var(--t-fold-fade-in) var(--ease) var(--lab-delay), visibility 0s linear 0s; }
  .rail .lab, .side:not(.rail) .ro { transition: opacity var(--t-fold-fade-out) var(--ease),
    visibility 0s linear var(--t-fold-fade-out); }
  /* the browser and its hairline: into Library its rows fade in over the last 150 ms from 8 px to the left; out of it
     they fade in 90 ms; the step-back moves it 24 px behind the rail and back (200 ms out, 240 ms in, drawer curve) */
  .browser, .side::after { transition: none; }
  [data-move='into'] .browser, [data-move='into'] .side::after {
    --rows-delay: calc(var(--t-fold) - var(--t-fold-rows-in));
    transition: opacity var(--t-fold-rows-in) var(--ease) var(--rows-delay),
      transform var(--t-fold-rows-in) var(--ease) var(--rows-delay); }
  [data-move='out'] .browser, [data-move='out'] .side::after {
    transition: opacity var(--t-fold-fade-out) var(--ease), transform var(--t-fold-fade-out) var(--ease),
      visibility 0s linear var(--t-fold-fade-out); }
  [data-move='step-back'] .browser, [data-move='step-in'] .browser { --away-x: -24px; }
  [data-move='step-back'] .browser, [data-move='step-back'] .side::after { transition: opacity var(--t-slide-out)
    var(--ease-drawer), transform var(--t-slide-out) var(--ease-drawer), visibility 0s linear var(--t-slide-out); }
  [data-move='step-in'] .browser, [data-move='step-in'] .side::after { transition: opacity var(--t-slide-in)
    var(--ease-drawer), transform var(--t-slide-in) var(--ease-drawer); }
  /* reduced motion: no glides, widths change at once; the chrome's contents cross-fade */
  @media (prefers-reduced-motion: reduce) {
    .chrome, .side { transition: none; }
    .lab, .ro, .rail .lab, .side:not(.rail) .ro { transition: opacity var(--t-fade) linear, visibility 0s linear 0s; }
    .rail .lab, .side:not(.rail) .ro { transition: opacity var(--t-fade) linear, visibility 0s linear var(--t-fade); }
    .browser.away { transform: none; }
    .chrome:not([data-move='none']) .browser, .chrome:not([data-move='none']) .side::after {
      transition: opacity var(--t-fade) linear, visibility 0s linear 0s; }
    .chrome:not([data-move='none']) .browser.away { transition: opacity var(--t-fade) linear, visibility 0s linear var(--t-fade); }
  }
</style>
