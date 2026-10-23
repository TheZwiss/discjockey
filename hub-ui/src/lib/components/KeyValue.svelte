<script lang="ts">
  import type { Snippet } from 'svelte';
  // `plain`: the key is a name, not a label (a program: "yt-dlp", "streamrip"), so it keeps its own spelling: normal
  // case, muted, body size, instead of the uppercase caption look. `keyWidth` (px) is the key column's width where
  // the default 96 px is too wide or too narrow for the keys of one list; every key of a list gets the same width.
  let { k, v, children, plain = false, keyWidth }: {
    k: string; v?: string | number | null; children?: Snippet; plain?: boolean; keyWidth?: number;
  } = $props();
</script>

<div class="kv" style:--kv-key="{keyWidth ?? 96}px">
  <span class={plain ? 'name' : 'caps'}>{k}</span>
  <span class="v selectable">{#if children}{@render children()}{:else}{v ?? '—'}{/if}</span>
</div>

<style>
  .kv { display: grid; grid-template-columns: var(--kv-key) 1fr; gap: var(--s-2); align-items: baseline; padding: 3px 0; }
  .caps { padding-top: 1px; }
  .name { color: var(--text-muted); min-width: 0; overflow-wrap: anywhere; }
  .v { color: var(--text); min-width: 0; overflow-wrap: anywhere; }
</style>
