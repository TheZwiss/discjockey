<script lang="ts">
  // OUTDATED (design system §7): use StatCard. Kept until phase 2 ends.
  import type { Snippet } from 'svelte';
  import Skeleton from './Skeleton.svelte';
  let { label, value, unit, sub, tone = 'default', loading = false, children }:
    { label: string; value: string | number | null | undefined; unit?: string; sub?: string;
      tone?: 'default' | 'accent' | 'problem'; loading?: boolean; children?: Snippet } = $props();
</script>

<div class="tile {tone}">
  <div class="caps">{label}</div>
  {#if loading}
    <div class="sk big"><Skeleton height={24} width="55%" /></div><div class="sk sub"><Skeleton height={10} width="80%" /></div>
  {:else}
    <div class="big num">{value === null || value === undefined || value === '' ? '—' : value}{#if unit}<span
        class="unit">{' '}{unit}</span>{/if}</div>
    {#if sub}<div class="sub">{sub}</div>{/if}
    {#if children}<div class="extra">{@render children()}</div>{/if}
  {/if}
</div>

<style>
  .tile { flex: 1; min-width: 0; border: var(--bw) solid var(--line-card); border-radius: var(--r-card);
    padding: var(--s-3) var(--s-4); display: flex; flex-direction: column; gap: 2px; }
  .accent { border-color: var(--accent-line); }
  .problem { border-color: var(--q-weak-line); }
  .big { font-size: var(--fs-big); font-weight: var(--fw-bold); color: var(--text-strong); line-height: 1.15; margin-top: 2px; }
  .unit { font-size: var(--fs-body); font-weight: 400; color: var(--text-muted); }
  .sub { color: var(--text-muted); font-size: var(--fs-small); }
  .extra { margin-top: var(--s-2); }
  /* loading keeps the loaded height (number + sub line), so the tile does not jump */
  .sk { display: flex; align-items: center; }
  .sk.big { height: calc(var(--fs-big) * 1.15); }
  .sk.sub { height: calc(var(--fs-small) * 1.45); }
  .sk > :global(.skeleton) { flex: none; }
</style>
