<script lang="ts">
  // "Upgrade ready" box (spec §6.6), the same in the Library and To-do details: a good-tone Surface card named
  // "Upgrade ready" with when it was found beside the name; what the parked version is; current and new spectra side
  // by side; the compare player; the cue-point line with its dot (does rekordbox keep the cues?). The page passes its
  // `actions` (To-do: the minor ones as links, the main one sits in its panel foot; Library: Swap or Open in to-do).
  import type { Snippet } from 'svelte';
  import type { Spectrum as Spec, TrackDetail } from '../bridge/types';
  import { cueTone, foundText, upgradeLabel } from '../format';
  import ComparePlayer from './ComparePlayer.svelte';
  import Spectrum from './Spectrum.svelte';
  import Surface from './Surface.svelte';

  let { upgrade, currentUrl, current = null, next = null, loading = false, swap, actions, children }: {
    upgrade: NonNullable<TrackDetail['upgrade']>; currentUrl: string | null; current?: Spec | null;
    next?: Spec | null; loading?: boolean; swap?: boolean; actions?: Snippet; children?: Snippet;
  } = $props();
  const found = $derived(foundText(upgrade.found));
</script>

<Surface kind="card" tone="good" label={upgradeLabel(upgrade.what)} summary={found || undefined}>
  <div class="up" data-test="upgrade-box" data-swap={swap}>
    <p class="what">{upgrade.quality_line}</p>
    <div class="specs">
      <div><span class="caps">Now</span><Spectrum spectrum={current} height={40} loading={loading && !current}
          cutoffLabel={false} /></div>
      <div><span class="caps">New</span><Spectrum spectrum={next} height={40} loading={loading && !next}
          cutoffLabel={false} /></div>
    </div>
    {#if currentUrl && upgrade.audio_url}
      <ComparePlayer a={{ url: currentUrl, label: 'Now' }} b={{ url: upgrade.audio_url, label: 'New' }} />
    {/if}
    <p class="cue"><span class="dot {cueTone(upgrade.alignment?.result)}" aria-hidden="true"></span>{upgrade.cue_text}</p>
    {#if actions}<div class="actions">{@render actions()}</div>{/if}
    {@render children?.()}
  </div>
</Surface>

<style>
  .up { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .what { margin: 0; color: var(--text); }
  .specs { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-2); }
  .specs > div { display: flex; flex-direction: column; gap: var(--s-1); min-width: 0; }
  /* the verdict closes the comparison, ruled off from it like a list's last row */
  .cue { margin: 0; display: flex; align-items: center; gap: var(--s-2); padding-top: var(--s-3);
    border-top: var(--bw) solid var(--line-soft); color: var(--text); font-size: var(--fs-small); }
  .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }
  .dot.lossless { background: var(--q-lossless); }
  .dot.good_lossy { background: var(--q-good); }
  .actions { display: flex; gap: var(--s-4); flex-wrap: wrap; align-items: center; }
</style>
