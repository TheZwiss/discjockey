<script lang="ts">
  // Every website opens in the system browser through the bridge, never inside the window.
  import type { Snippet } from 'svelte';
  import { api } from '../bridge/client';

  let { href, label, children }: { href: string; label?: string; children?: Snippet } = $props();
  function open(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();
    void api.open_external(href);
  }
</script>

<a {href} class="ext" onclick={open} rel="noopener noreferrer">{#if children}{@render children()}{:else}{label ?? href}{/if}<span
    class="arrow" aria-hidden="true">{' ↗'}</span></a>

<style>
  .ext { color: var(--accent-text); text-decoration: none; }
  .ext:hover { text-decoration: underline; }
  .ext:active { opacity: var(--link-press); }   /* a text link dims while held, like Button link */
  .arrow { color: var(--text-label); }
</style>
