<script lang="ts">
  // The one button (design system §4–§7). `filled` is the screen's primary action: look 2 fill, `data-primary`
  // (the rule checker allows one per screen / dialog). `secondary` is the outlined control, `primary` the
  // orange outline, `danger` the red one. `link` is accent text without border or padding for every in-text action
  // ("+ Add a playlist", "Fix →", "Full report ↗"; the arrow stays in the label). With `href` the button is an
  // `<a>`: `#/` targets go through the router (leave guard), anything else opens in the system browser. Buttons keep
  // their natural width; `wide` (`data-stretch`) is allowed only in a panel foot. `muted` turns a `link` grey (hover:
  // text colour) for quiet list controls next to orange switches and ticks ("All · None", "Tick all · None").
  // `icon` is an icon-only action in a row (⊘): a small square with no box at rest, its child a 16 px SVG drawn in
  // the text colour (glyphs like ⊘ or ▸ render as faint rings or dots at 11–13 px); the caller gives `aria-label`.
  // `destructive` turns it red on hover, for an action that hides or removes something.
  // Press: buttons scale (.98, small and icon .97); a link dims instead, so text inside a sentence or row doesn't shrink.
  // OUTDATED: `ghost` is an alias of `secondary` since look 2; phase 2 maps each use to `secondary` or `link`.
  import type { Snippet } from 'svelte';
  import type { HTMLButtonAttributes } from 'svelte/elements';
  import Spinner from './Spinner.svelte';
  import { api } from '../bridge/client';
  import { link } from '../router';

  type Props = Omit<HTMLButtonAttributes, 'disabled' | 'onclick' | 'type' | 'title'> & {
    variant?: 'primary' | 'filled' | 'secondary' | 'ghost' | 'danger' | 'link' | 'icon'; size?: 'md' | 'sm';
    disabled?: boolean; busy?: boolean; busyLabel?: string; title?: string;
    onclick?: (e: MouseEvent) => void; type?: 'button' | 'submit'; wide?: boolean; href?: string;
    children?: Snippet; icon?: Snippet; muted?: boolean; destructive?: boolean;
  };
  let { variant = 'secondary', size = 'md', disabled = false, busy = false, busyLabel, title, onclick,
    type = 'button', wide = false, href, children, icon, muted = false, destructive = false, ...rest }: Props = $props();
  const off = $derived(disabled || busy);
  // aria-disabled instead of disabled, so the tooltip (the reason) still shows on hover
  function click(e: MouseEvent) {
    if (off) { e.preventDefault(); e.stopPropagation(); return; }
    // in-app targets are handled by use:link; a website never opens inside the window
    if (href && !href.startsWith('#')) { e.preventDefault(); void api.open_external(href); }
    onclick?.(e);
  }
</script>

{#snippet label()}
  {#if busy}
    <Spinner size={size === 'sm' ? 10 : 12} label={busyLabel ?? 'Working'} />
    {#if busyLabel}<span>{busyLabel}</span>{:else}{@render children?.()}{/if}
  {:else}
    {#if icon}<span class="glyph">{@render icon()}</span>{/if}
    {@render children?.()}
  {/if}
{/snippet}

{#if href !== undefined}
  <!-- no href while off: the router's link action and the browser both leave it alone; role and tabindex keep it
       focusable (like a disabled button) so the reason tooltip still shows -->
  <a {...rest as Record<string, unknown>} href={off ? undefined : href} role={off ? 'link' : undefined}
    tabindex={off ? 0 : undefined} use:link class="btn {variant} {size}" class:muted class:destructive
    class:off class:busy aria-disabled={off || undefined} aria-busy={busy || undefined} {title}
    data-primary={variant === 'filled' || undefined} data-stretch={wide || undefined} onclick={click}>{@render label()}</a>
{:else}
  <button {...rest} {type} class="btn {variant} {size}" class:muted class:destructive class:off class:busy aria-disabled={off || undefined}
    aria-busy={busy || undefined} {title} data-primary={variant === 'filled' || undefined}
    data-stretch={wide || undefined} onclick={click}>{@render label()}</button>
{/if}

<style>
  .btn {
    display: inline-flex; align-items: center; justify-content: center; gap: var(--s-2);
    padding: 7px var(--s-4); min-height: var(--h-btn); border-radius: var(--r-ctl);
    border: var(--bw) solid var(--ctl-line); background: var(--ctl-bg); color: var(--text-muted);
    font-size: var(--fs-body); font-weight: var(--fw-semi); white-space: nowrap; line-height: 1.2;
    text-decoration: none;
    --btn-motion: background var(--t-hover) var(--ease), border-color var(--t-hover) var(--ease),
      color var(--t-hover) var(--ease), filter var(--t-hover) var(--ease), transform var(--t-press) ease-out;
    transition: var(--btn-motion);
  }
  .sm { padding: 3px 10px; min-height: var(--h-ctl-sm); font-size: var(--fs-small); }
  .btn[data-stretch] { width: 100%; }
  /* press feedback on pointer-down (design system §6): big buttons .98, small ones .97. The transition is repeated
     so the global press rule in base.css doesn't cut the state transitions while pressed. */
  .btn:active:not(.off) { transform: scale(.98); transition: var(--btn-motion); }
  .sm:active:not(.off), .icon:active:not(.off) { transform: scale(.97); }
  .secondary:hover:not(.off), .ghost:hover:not(.off) { background: var(--ctl-hover); color: var(--text); }
  .primary { border-color: var(--accent); background: transparent; color: var(--accent-text); font-weight: var(--fw-bold); }
  .primary:hover:not(.off) { border-color: var(--accent-text); }
  /* the screen's one main action (Start sync) */
  .filled {
    background: var(--go-bg); box-shadow: var(--go-highlight), var(--go-glow); border-color: transparent;
    border-radius: var(--r-go); color: var(--text-on-accent); font-weight: var(--fw-bold);
  }
  .filled:hover:not(.off) { filter: brightness(1.06); }
  .danger { border-color: var(--q-weak-line); background: transparent; color: var(--q-weak); }
  .danger:hover:not(.off) { border-color: var(--q-weak); }
  /* in-text action: accent text, no box */
  .link {
    padding: 0; min-height: 0; border: 0; border-radius: 0; background: none; color: var(--accent-text);
  }
  .link:hover:not(.off) { text-decoration: underline; }
  /* a link held down dims instead of shrinking inside its sentence or row (rule 2: feedback on pointer-down) */
  .link { --btn-motion: color var(--t-hover) var(--ease), opacity var(--t-press) ease-out; }
  .link:active:not(.off) { transform: none; opacity: var(--link-press); }
  .link.muted:not(.off) { color: var(--text-muted); }
  .link.muted:hover:not(.off) { color: var(--text); text-decoration: none; }
  /* icon-only: quiet at rest (--text-label, an action is never the disabled grey), a wash on hover */
  .icon { min-width: var(--h-ctl-sm); min-height: var(--h-ctl-sm); padding: 0; border-color: transparent; background: none;
    color: var(--text-label); }
  .icon :global(svg) { width: 16px; height: 16px; fill: none; stroke: currentColor; stroke-width: 1.6;
    stroke-linecap: round; }
  .icon:hover:not(.off) { background: var(--ctl-hover); color: var(--text); }
  .icon.destructive:hover:not(.off) { background: none; border-color: var(--q-weak-line); color: var(--q-weak); }
  /* off keeps the control's box, so the user still sees where the action is and that it waits (a disabled Start sync
     doesn't turn into floating grey text); a filled one keeps its --r-go corners. A link stays a bare link. */
  .off { color: var(--text-disabled); box-shadow: none; filter: none; }
  .off:not(.link, .icon) { border-color: var(--ctl-line); background: var(--ctl-bg); }
  .off.busy { color: var(--text-muted); }
  .glyph { display: inline-flex; }
</style>
