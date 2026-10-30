<script lang="ts">
  // The ⓘ behind which longer explanation waits (design system §6). The small round button opens a popover on
  // hover (after a short wait, openTiming), on keyboard focus and on click; a click pins it open until the next click, a click elsewhere, Escape or a
  // scroll. It opens in the top layer (popover API), so no list or panel that clips its content cuts it off, and it
  // sits under the ⓘ (above when there's no room below), shifted to stay inside the window. `label` names the button
  // for VoiceOver ("About the daily limit"); `children` is the text, which also describes the button. Text only: a `role=tooltip` may hold no link or
  // button (WAI-ARIA tooltip pattern), so the ⓘ has no expanded state and controls nothing (final review M10). When it opens
  // and closes is infoTipModel.ts. `data-infotip` marks it for the rule checker.
  // Other attributes (`data-test`) go onto the root; the button is `<data-test>-button`, the popover `<data-test>-tip`.
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import { openTiming, TIP_CLOSED, tipStep, type TipEvent, type TipState, type TipStep } from './infoTipModel';
  // the other tips on the page, InfoTips and Tips alike (tipRegistry.ts): one open at a time, the next one warm
  import { tipClosed, tipGone, tipOpened, tipWarmth } from './tipRegistry';

  type Props = Omit<HTMLAttributes<HTMLSpanElement>, 'children'> & { label: string; children: Snippet };
  let { label, children, class: className, ...rest }: Props = $props();
  const id = $props.id();
  const test = $derived(rest['data-test'] as string | undefined);
  const EDGE = 8;        // keep this far from the window's edges
  const GAP = 6;         // between the ⓘ and the popover
  const LEAVE_MS = 150;  // time to move the pointer from the ⓘ onto the popover

  let root: HTMLSpanElement | undefined = $state();
  let trigger: HTMLButtonElement | undefined = $state();
  let tip: HTMLDivElement | undefined = $state();
  let tipState = $state<TipState>(TIP_CLOSED);
  const open = $derived(tipState.open);
  let leaveTimer: ReturnType<typeof setTimeout> | undefined;
  let hoverTimer: ReturnType<typeof setTimeout> | undefined;
  let pos = $state({ left: 0, top: 0, origin: '50% 0' });   // origin: the ⓘ's spot, so the tip grows out of it
  let fade = $state(true);   // this opening fades in (not from the keyboard, not while or right after another tip is open)
  const closeNow = () => send({ type: 'dismiss' });
  const warmth = () => tipWarmth(closeNow);

  /** Feeds one event to the model (infoTipModel.ts) and applies what it says. `fadeIn`: how a closed tip opens. */
  function send(e: TipEvent, fadeIn = true): TipStep {
    clearTimeout(leaveTimer);
    clearTimeout(hoverTimer);
    const was = tipState.open;
    const r = tipStep(tipState, e);
    tipState = r.state;
    if (!was && r.state.open) {
      fade = fadeIn;
      tipOpened(closeNow);   // the tip the user just left goes as this one comes
    }
    if (was && !r.state.open) tipClosed(closeNow);
    if (r.refocus) trigger?.focus();
    return r;
  }
  function enter() {
    if (tipState.open) { send({ type: 'hover' }); return; }   // back over an open tip: it stays
    clearTimeout(hoverTimer);
    const t = openTiming('hover', performance.now(), warmth());
    if (t.delay === 0) send({ type: 'hover' }, t.fade);
    else hoverTimer = setTimeout(() => send({ type: 'hover' }, t.fade), t.delay);
  }
  function opened(how: 'click' | 'keyboard') { return openTiming(how, performance.now(), warmth()).fade; }
  function place() {
    if (!trigger || !tip) return;
    const t = trigger.getBoundingClientRect();
    const w = tip.offsetWidth, h = tip.offsetHeight;
    const below = t.bottom + GAP;
    const top = below + h <= window.innerHeight - EDGE ? below : Math.max(EDGE, t.top - GAP - h);
    const left = Math.max(EDGE, Math.min(t.left + t.width / 2 - w / 2, window.innerWidth - EDGE - w));
    pos = { left, top, origin: `${t.left + t.width / 2 - left}px ${top === below ? 0 : h}px` };
  }
  // popover in the top layer once open; measured after it is laid out
  $effect(() => {
    if (!tip) return;
    const shown = tip.matches(':popover-open');
    if (open) {
      if (!shown) tip.showPopover();
      place();
    } else if (shown) tip.hidePopover();
  });
  // while open: Escape, a press outside, a scroll anywhere or a resize close it
  $effect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => {
      if (e.key !== 'Escape') return;
      // preventDefault too: a modal <dialog>'s cancel is this key's default action, one Escape closes one layer
      if (send({ type: 'escape', focusInTip: !!tip?.contains(document.activeElement) }).handled) {
        e.preventDefault(); e.stopPropagation();
      }
    };
    const press = (e: PointerEvent) => { if (!root?.contains(e.target as Node)) send({ type: 'dismiss' }); };
    const dismiss = () => send({ type: 'dismiss' });
    window.addEventListener('keydown', key, true);
    window.addEventListener('pointerdown', press, true);
    window.addEventListener('scroll', dismiss, true);
    window.addEventListener('resize', dismiss);
    return () => {
      window.removeEventListener('keydown', key, true);
      window.removeEventListener('pointerdown', press, true);
      window.removeEventListener('scroll', dismiss, true);
      window.removeEventListener('resize', dismiss);
    };
  });
  $effect(() => () => {
    clearTimeout(leaveTimer); clearTimeout(hoverTimer);
    tipGone(closeNow);   // removed while open (its page went away)
  });

  function leave() {
    clearTimeout(hoverTimer);   // left before the wait was over: it doesn't open
    clearTimeout(leaveTimer);
    leaveTimer = setTimeout(() => send({ type: 'leave' }), LEAVE_MS);
  }
  function focusOut(e: FocusEvent) {
    if (!root?.contains(e.relatedTarget as Node | null)) send({ type: 'blur' });
  }
</script>

<!-- no role: the span only groups the ⓘ with its popover for pointer and focus events -->
<span {...rest} bind:this={root} class="infotip {className ?? ''}" data-infotip
  onpointerenter={enter} onpointerleave={leave} onfocusout={focusOut}>
  <button type="button" bind:this={trigger} class="trigger" class:open aria-label={label} aria-describedby={id} data-test={test ? `${test}-button` : undefined}
    onfocus={() => send({ type: 'focus', keyboard: !!trigger?.matches(':focus-visible') }, opened('keyboard'))}
    onclick={(e) => send({ type: 'activate', keyboard: e.detail === 0 }, opened(e.detail === 0 ? 'keyboard' : 'click'))}>ⓘ</button>
  <div {id} bind:this={tip} popover="manual" role="tooltip" class="tip" class:instant={!fade} style:left="{pos.left}px"
    style:top="{pos.top}px" style:transform-origin={pos.origin} data-test={test ? `${test}-tip` : undefined}>{@render children()}</div>
</span>

<style>
  .infotip { display: inline-flex; vertical-align: middle; }
  /* 22 px to hit, drawn as before: the negative margin keeps the line it sits in from growing */
  .trigger {
    min-width: 22px; min-height: 22px; margin: -2px; padding: 0; display: inline-grid; place-items: center;
    border-radius: var(--r-pill); color: var(--text-muted); font-size: var(--fs-body); line-height: 1;
    transition: color var(--t-hover) var(--ease), background var(--t-hover) var(--ease), transform var(--t-press) ease-out;
  }
  .trigger:hover, .trigger.open { color: var(--text); background: var(--ctl-hover); }
  /* the popover API shows and hides it; its own placement (centred, inset 0) is replaced by ours. Popover material
     (the lightest layer); fades in and grows from .97 out of the ⓘ on open (not from the keyboard, nor while or right
     after another tip is open: .instant), and goes at once on close */
  .tip {
    position: fixed; inset: auto; margin: 0; z-index: 30;
    width: max-content; max-width: 280px; padding: var(--s-2) var(--s-3);
    background: var(--popover-bg); color: var(--text); border: var(--bw) solid var(--popover-line);
    border-radius: var(--r-surface); box-shadow: var(--surface-highlight), var(--shadow);
    font-size: var(--fs-small); line-height: 1.45; white-space: normal; text-align: left;
    transition: opacity var(--t-pop) var(--ease), transform var(--t-pop) var(--ease);
  }
  @starting-style { .tip:popover-open { opacity: 0; transform: scale(.97); } }
  .tip.instant { transition: none; }
  .tip :global(p) { margin: 0; }
  .tip :global(p + p) { margin-top: var(--s-1); }
</style>
