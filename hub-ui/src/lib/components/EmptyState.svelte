<script lang="ts">
  import type { Snippet } from 'svelte';
  import type { EmptyKind } from '../bridge/types';
  import { EMPTY } from '../copy';
  import { link } from '../router';
  import Button from './Button.svelte';

  type Action = { label: string; href?: string; onclick?: () => void };
  let { kind, title, body, action, children }:
    { kind?: EmptyKind | null; title?: string; body?: string; action?: Action | null; children?: Snippet } = $props();
  const base = $derived(kind ? EMPTY[kind] : null);
  const head = $derived(title ?? base?.title ?? 'Nothing here.');
  const text = $derived(body ?? base?.body);
  // Read Spotify is never an empty state's action: the header slot holds it, its one place (spec §11)
  const act = $derived<Action | null>(action !== undefined ? action
    : base?.action ? { label: base.action.label, href: base.action.href } : null);
</script>

<div class="empty">
  <p class="title">{head}</p>
  {#if text}<p class="body">{text}</p>{/if}
  {@render children?.()}
  {#if act}
    {#if act.href}<a class="act" href={act.href} use:link>{act.label}</a>
    {:else}<Button size="sm" onclick={act.onclick}>{act.label}</Button>{/if}
  {/if}
</div>

<style>
  .empty { display: flex; flex-direction: column; align-items: center; text-align: center; gap: var(--s-2);
    padding: var(--s-6) var(--s-4); color: var(--text-muted); }
  .title { color: var(--text-muted); font-size: var(--fs-body); text-wrap: balance; }
  .body { color: var(--text-label); font-size: var(--fs-small); max-width: 360px; }
  .act { color: var(--accent-text); font-weight: var(--fw-semi); }
</style>
