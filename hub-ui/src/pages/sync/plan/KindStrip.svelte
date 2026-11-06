<script lang="ts">
  // The plan at a glance (issue 36), on top of the plan: Library's health strip (ShareStrip) with the plan's words.
  // The count is what the sync would do in the playlists and weekly checks switched on; the bar shows the share of
  // each kind; the rows name the kinds with their counts, each led by its plan-row icon in the kind's colour (the
  // bar's colour), so the strip ties the bar to the rows below it. A weekly check switched off in the panel keeps its
  // row, dimmed, and says "off"; its part leaves the bar, which shows only what the sync would do; a kind's tooltip says what it is.
  import { ShareBar, ShareStrip, type ShareRow } from '$lib/components';
  import { count } from '$lib/format';
  import { isKindKey, type KindShare } from '../planModel';
  import KindIcon from './KindIcon.svelte';

  let { kinds, total, line }: { kinds: KindShare[]; total: number; line: string } = $props();
  // The bar shows what the sync would do: a kind switched off leaves it, and with nothing to sync (`total` 0: every
  // playlist off, nothing ticked, a limit of 0) it is the empty track, never a kind's colour (a kind colour in an
  // empty bar reads as a share of that kind). The rows keep their counts.
  const parts = $derived(kinds.map((k) => ({ key: k.key, n: total && !k.off ? k.n : 0, colour: k.colour, label: k.label.toLowerCase(), off: k.off })));
  const rows = $derived<ShareRow[]>(kinds.map((k) => ({
    key: k.key, words: k.label, quiet: k.off ? 'off' : null, count: count(k.n), test: 'strip-kind', tip: k.tip,
    off: k.off })));
  const colourOf = (key: string) => kinds.find((k) => k.key === key)?.colour ?? 'currentColor';
</script>

{#snippet bar()}<ShareBar {parts} />{/snippet}
{#snippet mark(r: ShareRow)}<span class="km" style:color={colourOf(r.key)} data-kind={r.key}>{#if isKindKey(r.key)}<KindIcon
  kind={r.key} size={13} />{/if}</span>{/snippet}

<ShareStrip value={count(total)} unit={total === 1 ? 'track' : 'tracks'} {line} {bar} {rows} {mark} stack test="sync-kinds-strip"
  valueTest="sync-strip-total" lineTest="sync-strip-line" />

<style>
  .km { display: grid; place-items: center; width: 14px; height: 14px; }
  .km :global(.kind-icon) { fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round; stroke-linejoin: round; }
</style>
