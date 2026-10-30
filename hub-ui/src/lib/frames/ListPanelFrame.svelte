<script lang="ts">
  // List + panel page frame (design system §3). The panel is docked at the right edge at --panel-w (--panel-w-narrow
  // below a 1240 px window, one fixed step) and never takes free width. The list area takes the rest and scrolls; its
  // content grows to --content-max (`wide`: --content-max-wide, the Library table), then centres. The vertical padding
  // sits on the scroller so the last row keeps space below it. `.content` grows to the scroller's height and never
  // shrinks below its content (a shrunk box would let the rows overflow past the padding); a list that scrolls inside
  // itself marks its root `data-scrolls-itself`, and then `.content` keeps exactly the scroller's height instead.
  // Optional columns query the list itself (Surface's rows are the `list` container), not this area.
  //
  // `panelMode="inspector"` (Library, plan library stage 5 A3.7, D16.3, house rule 3): the panel is there only while
  // `open`, the details when wanted (the page decides: Library opens them on a pick). Same widths, same `data-panel`, same Panel inside. The page lays out once and the
  // chrome moves over it (the notes' motion table): on open the list takes its final width at once and the inspector
  // slides in from the window's right edge over the space just freed (--t-slide-in, 240 ms, the drawer curve); on
  // close the list widens at once and the inspector slides out the way it came, over the rows (--t-slide-out, 200 ms:
  // exit faster than entry). A CSS transition, so a toggle mid-way turns it round from where it is. Reduced motion:
  // it fades in place. Closed, it is `inert` and, once out, hidden (no focus, no reader, nothing for the checker).
  // Keep passing `panel` while closed: its content stays during the slide out. `panelLabel` names the panel's
  // landmark (Library: "Track details"; an inspector without one is "Details"), so a screen reader's landmark list
  // says what the region holds.
  import type { Snippet } from 'svelte';
  import EmptyState from '../components/EmptyState.svelte';
  let { main, panel = null, emptyPanel = 'Pick a track to see its details.', wide = false, panelMode = 'docked',
    open = false, panelLabel }:
    { main: Snippet; panel?: Snippet | null; emptyPanel?: string; wide?: boolean;
      panelMode?: 'docked' | 'inspector'; open?: boolean; panelLabel?: string } = $props();

  const inspector = $derived(panelMode === 'inspector');
  const asideLabel = $derived(panelLabel ?? (inspector ? 'Details' : undefined));
  // out of view and hidden once the slide out has ended (transitionend, or at once when nothing moves)
  let gone = $state(true);
  let aside: HTMLElement | undefined = $state();
  $effect(() => {
    if (!inspector || open) { gone = false; return; }
    if (!aside) return;
    const moving = aside.getAnimations().length > 0;
    if (!moving) { gone = true; return; }
    const el = aside;
    const done = (e: TransitionEvent) => { if (e.target === el) gone = true; };
    // a cancel can be the slide in that this close interrupted (it may arrive after this listener is attached):
    // only hide when nothing on the panel is moving any more
    const cancelled = (e: TransitionEvent) => { if (e.target === el && el.getAnimations().length === 0) gone = true; };
    el.addEventListener('transitionend', done);
    el.addEventListener('transitioncancel', cancelled);
    return () => { el.removeEventListener('transitionend', done); el.removeEventListener('transitioncancel', cancelled); };
  });
</script>

<div class="frame" class:inspector class:open={inspector && open} data-frame="list-panel">
  <div class="main" data-frame-main>
    <div class="content" class:wide data-frame-content data-max={wide ? '--content-max-wide' : '--content-max'}>{@render main()}</div>
  </div>
  <aside bind:this={aside} class:gone={inspector && !open && gone} data-panel data-panel-mode={panelMode}
    data-open={inspector ? String(open) : undefined} inert={inspector && !open} aria-label={asideLabel}>
    {#if panel}{@render panel()}{:else}<div class="empty"><EmptyState title={emptyPanel} /></div>{/if}
  </aside>
</div>

<style>
  .frame { display: flex; height: 100%; min-height: 0; }
  /* a sticky Surface head sticks at the scroller's top edge, not below its padding */
  .main { flex: 1 1 auto; min-width: 0; overflow-y: auto; display: flex; flex-direction: column;
    padding-block: var(--s-4); --sticky-top: calc(-1 * var(--s-4)); }
  .content { flex: 1 0 auto; align-self: center; width: 100%; max-width: var(--content-max);
    padding: 0 var(--s-5); display: flex; flex-direction: column; gap: var(--s-3); }
  .content:has(:global([data-scrolls-itself])) { flex-shrink: 1; min-height: 0; }
  /* only that list gives way: everything above it keeps its height (a Segmented clips its overflow, so it could
     otherwise shrink to a sliver; To-do at 1100 with 299 to-dos) */
  .content:has(:global([data-scrolls-itself])) > :global(:not([data-scrolls-itself])) { flex-shrink: 0; }
  .content.wide { max-width: var(--content-max-wide); }
  aside { flex: none; width: var(--panel-w); background: var(--panel-bg); border-left: var(--bw) solid var(--surface-line);
    min-height: 0; display: flex; flex-direction: column; }
  @media (width < 1240px) { aside { width: var(--panel-w-narrow); } }

  /* the inspector: out of the flow, over the frame's right edge; the frame clips it while it is out (clip, not
     hidden: the frame doesn't become a scroller) */
  .inspector { position: relative; overflow: clip; }
  .inspector aside { position: absolute; top: 0; right: 0; bottom: 0; z-index: 2; transform: translateX(100%);
    transition: transform var(--t-slide-out) var(--ease-drawer); }
  .inspector.open aside { transform: none; transition-duration: var(--t-slide-in); }
  .inspector aside.gone { visibility: hidden; }
  /* the list makes room at once (no transition on purpose: a table reflowing per frame would stutter) */
  .inspector.open .main { margin-right: var(--panel-w); }
  @media (width < 1240px) { .inspector.open .main { margin-right: var(--panel-w-narrow); } }
  @media (prefers-reduced-motion: reduce) {
    .inspector aside { transform: none; opacity: 0; transition: opacity var(--t-fade) var(--ease); }
    .inspector.open aside { opacity: 1; }
  }
  .empty { margin: auto 0; padding: var(--s-4); }
</style>
