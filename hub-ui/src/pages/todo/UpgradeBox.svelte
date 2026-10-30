<script lang="ts">
  // To-do's links on the shared "Upgrade ready" box (spec §6.6): the minor choices, Add as new file (when Swap is the
  // main one) and Discard; the main one (Swap, or Add as new file when the version doesn't match) is the panel foot's
  // filled button (Details). The box says itself whether rekordbox keeps the cues (its cue line).
  import type { Spectrum as Spec, TrackDetail } from '$lib/bridge/types';
  import { Hint, UpgradeCard, WriteButton } from '$lib/components';
  import { actionsFor } from './todoModel';

  type Mode = 'swap' | 'add_new' | 'discard';
  let { track, current, upgrade, loading, busy, onrun }: {
    track: TrackDetail; current: Spec | null; upgrade: Spec | null; loading: boolean;
    /** the upgrade job running now, if any */
    busy: string | null; onrun: (mode: Mode) => void;
  } = $props();

  const a = $derived(actionsFor(track).upgrade!);
  // without Swap the new file goes in beside the old one; every measured cue line says so itself, only an
  // unmeasured one ("could not compare") leaves it to the hint
</script>

<UpgradeCard upgrade={track.upgrade!} currentUrl={track.audio_url} {current} next={upgrade} {loading} swap={a.swap}>
  {#snippet actions()}
    {#if a.primary === 'swap'}
      <WriteButton variant="link" size="sm" busy={busy === 'add_new'} onclick={() => onrun('add_new')}
        data-test="upgrade-add-new">Add as new file</WriteButton>
    {/if}
    <WriteButton variant="link" muted size="sm" busy={busy === 'discard'} onclick={() => onrun('discard')}
      data-test="upgrade-discard">Discard</WriteButton>
  {/snippet}
  {#if !a.swap && track.upgrade!.alignment.result === 'unknown'}<Hint text="Add as new file makes a new rekordbox entry" />{/if}
</UpgradeCard>
