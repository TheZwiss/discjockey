<script lang="ts">
  import { link } from '../router';
  type Action = { label: string; href?: string; onclick?: () => void };
  let { tone = 'info', text, action }: { tone?: 'info' | 'warn'; text: string; action?: Action | null } = $props();
</script>

<div class="banner {tone}" role="status">
  <span class="dot" aria-hidden="true"></span>
  <span class="text">{text}</span>
  {#if action}
    {#if action.href}<a href={action.href} use:link class="act">{action.label}</a>
    {:else}<button type="button" class="act" onclick={action.onclick}>{action.label}</button>{/if}
  {/if}
</div>

<style>
  .banner { display: flex; align-items: center; gap: var(--s-3); min-height: var(--banner-h); padding: 0 var(--s-5);
    border-bottom: var(--bw) solid var(--line); color: var(--text); font-size: var(--fs-small); flex-shrink: 0; }
  .dot { width: 7px; height: 7px; border-radius: var(--r-pill); background: var(--text-muted); flex-shrink: 0; }
  .warn .dot { background: var(--q-good); }
  .info .dot { background: var(--accent); }
  .text { flex: 1; min-width: 0; }
  .act { color: var(--accent-text); font-weight: var(--fw-semi); background: none; border: 0; padding: 0; font-size: inherit;
    white-space: nowrap; }
</style>
