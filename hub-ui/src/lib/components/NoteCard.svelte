<script lang="ts">
  // Explanation that needs more than a hint's one line (design system §6): a `Surface` card with an icon in the
  // tone's colour, an optional bold `title` and up to about three lines of text (`children`; a title alone when the
  // text would only repeat what's around it). `info` (ⓘ, grey) says
  // how something works, `warn` (⚠, yellow border) that something waits or is limited, `problem` (✕, red border)
  // that something failed. Longer text than that is a page of its own, not a note. `data-note` marks it for the rule
  // checker; other attributes (`data-test`) go onto the card.
  import type { Snippet } from 'svelte';
  import type { HTMLAttributes } from 'svelte/elements';
  import Surface from './Surface.svelte';

  type Tone = 'info' | 'warn' | 'problem';
  type Props = Omit<HTMLAttributes<HTMLElement>, 'children' | 'title'> & { tone?: Tone; title?: string; children?: Snippet };
  let { tone = 'info', title, children, class: className, ...rest }: Props = $props();
  const ICON: Record<Tone, string> = { info: 'ⓘ', warn: '⚠', problem: '✕' };
  const SURFACE_TONE = { info: 'default', warn: 'warn', problem: 'problem' } as const;
</script>

<Surface {...rest} tone={SURFACE_TONE[tone]} class="note-card {className ?? ''}" data-note={tone} role="note">
  <div class="body">
    <span class="icon {tone}" aria-hidden="true">{ICON[tone]}</span>
    <div class="text">
      {#if title}<b class="title">{title}</b>{/if}
      {#if children}<div class="message">{@render children()}</div>{/if}
    </div>
  </div>
</Surface>

<style>
  .body { display: grid; grid-template-columns: auto minmax(0, 1fr); column-gap: var(--s-3); align-items: start; }
  .icon { font-size: var(--fs-body); line-height: 1.45; font-weight: var(--fw-bold); }
  .icon.info { color: var(--text-muted); }
  .icon.warn { color: var(--q-good); }
  .icon.problem { color: var(--q-weak); }
  .text { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .title { font-size: var(--fs-body); font-weight: var(--fw-semi); color: var(--text-strong); line-height: 1.45; }
  .message { font-size: var(--fs-small); line-height: 1.45; color: var(--text-muted); overflow-wrap: anywhere; }
  .message :global(p) { margin: 0; }
</style>
