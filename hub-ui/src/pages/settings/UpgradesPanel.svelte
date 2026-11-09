<script lang="ts">
  // Settings' Upgrades panel (issue 33 stage C plan §6.1): the one choice, whether the sync upgrades by itself.
  // One list card with one switch row "Upgrade automatically when I sync", its second line the design's Hint, an ⓘ in
  // the card's head with the longer explanation; it saves at once (set_auto_upgrade, a quiet job) like YouTube
  // Music's Liked music switch, the switch showing the value being saved until the job ends, and an error as a
  // problem NoteCard under it. No filled button: nothing here is a step. The state comes from setup_status's
  // `auto_upgrade` (the hub store), read again after the job.
  import { api, runJob } from '$lib/bridge/client';
  import type { SetupStatus } from '$lib/bridge/types';
  import { InfoTip, NoteCard, Skeleton, Surface, ToggleRow } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { AUTO_UPGRADE_LABEL, AUTO_UPGRADE_SUB, AUTO_UPGRADE_TIP, autoUpgradeOn, shownAutoUpgrade } from '$lib/autoUpgrade';

  let { status, disabledWhy = null, onchanged }: {
    status: SetupStatus | null; disabledWhy?: string | null; onchanged: () => void;
  } = $props();

  /** the choice being saved: the switch shows it at once, until the read-again status says the same */
  let pending = $state<boolean | null>(null);
  let error = $state<string | null>(null);
  const off = $derived(!!disabledWhy);
  $effect(() => { if (status && pending !== null && autoUpgradeOn(status.auto_upgrade) === pending) pending = null; });

  async function set(on: boolean) {
    if (!status || off || pending !== null) return;
    error = null;
    pending = on;
    const r = await runJob(api.set_auto_upgrade(on), { quiet: true, success: false });
    if (!r.ok) { pending = null; if (r.kind !== 'stopped') error = r.message; }
    onchanged();
  }
</script>

{#snippet tipHeader()}
  <InfoTip label="About automatic upgrades" data-test="auto-upgrade-info">{AUTO_UPGRADE_TIP}</InfoTip>
{/snippet}

{#snippet head()}
  <div class="col" data-test="settings-upgrades">
    {#if !status}
      <Skeleton lines={3} />
    {:else}
      <Surface kind="list" label="Upgrades" header={tipHeader} data-test="auto-upgrade">
        <ToggleRow item={{ key: 'auto_upgrade', label: AUTO_UPGRADE_LABEL, on: shownAutoUpgrade(status.auto_upgrade, pending) }}
          sub={AUTO_UPGRADE_SUB} disabled={off} title={disabledWhy ?? undefined} onchange={(_k, on) => void set(on)}
          test="auto-upgrade-switch" />
      </Surface>
      {#if error}<NoteCard tone="problem" data-test="auto-upgrade-error">{error}</NoteCard>{/if}
    {/if}
  </div>
{/snippet}

<Panel {head} />

<style>
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
</style>
