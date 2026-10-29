<script lang="ts">
  // Step 2, Your existing music (plan library stage 4, W1): folders of music the user already has, indexed where
  // they are. Not a required step: Continue is always on (with no folder it skips the step, the page calls
  // setup_skip_import). The card says what the step does and holds Add folder…, the step's filled button until a
  // folder is watched (or the step was skipped); then Continue is. Under it the import once it runs (it starts by
  // itself after the add, D14) and the watched folders, the Library first: the same blocks and flow as Settings →
  // Watched folders, so the two can't drift.
  import { untrack } from 'svelte';
  import type { SetupStatus } from '$lib/bridge/types';
  import { Hint, ImportCard, ProblemCard, Surface, UnreadableList, WatchedFolderList, WriteButton, importView,
    type WatchedFoldersFlow } from '$lib/components';
  import { hub, writeBlockedReason } from '$lib/stores/hub';

  /** the page owns the flow: Continue reads its folders to decide whether it skips the step */
  let { status, flow }: { status: SetupStatus; flow: WatchedFoldersFlow } = $props();

  $effect(() => untrack(() => flow.mount()));

  const view = $derived(importView($hub.job, flow.data));
  const watched = $derived(!!flow.data?.folders.some((f) => f.kind === 'import'));
  const blocked = $derived($writeBlockedReason);
</script>

<Surface kind="card" label="Your existing music" tone={watched ? 'good' : 'default'} data-test="existing-card">
  <Hint text="Add folders with music you already have. Discjockey indexes it where it is: nothing is copied, moved or renamed."
    wrap data-test="existing-hint" />
  <div class="actions">
    <WriteButton variant={status.existing || watched ? 'secondary' : 'filled'} busy={flow.adding}
      onclick={() => void flow.add()} data-test="existing-add">Add folder…</WriteButton>
    {#if blocked && !flow.adding}<Hint text={blocked} data-test="existing-why" />{/if}
  </div>
  {#if flow.note}
    <div class="note" data-test="existing-note" data-tone={flow.note.tone}>
      {#each flow.note.lines as line (line)}<Hint text={line} tone={flow.note.tone === 'problem' ? 'problem' : 'muted'} wrap />{/each}
    </div>
  {/if}
</Surface>
{#if view}
  <ImportCard {view} onstop={() => void flow.stop()} oncontinue={() => void flow.continueImport()}
    starting={flow.starting} test="existing-import" />
{/if}
{#if flow.error}
  <ProblemCard kind={flow.error.kind} message={flow.error.message} onretry={() => void flow.load()} />
{/if}
{#if flow.data || !flow.error}
  <WatchedFolderList folders={flow.data?.folders ?? null} onremove={(f) => void flow.remove(f)} removeOff={blocked}
    removing={flow.removing} test="existing-list" />
{/if}
<UnreadableList files={flow.data?.unreadable ?? []} folders={flow.data?.folders ?? []} test="existing-unreadable" />

<style>
  .actions { display: flex; align-items: center; gap: var(--s-3); min-width: 0; }
  .note { display: flex; flex-direction: column; gap: var(--s-1); min-width: 0; }
</style>
