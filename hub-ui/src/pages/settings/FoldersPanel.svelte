<script lang="ts">
  // Settings → Watched folders (plan library stage 4, group 6): the folders Discjockey indexes where they are. The
  // head is the import while it runs, stopped or just ended (ImportCard, Stop at its end); the fill the folders as
  // one growing list (the Library first, always watched; each import folder with its state, its files and × Remove);
  // after it the files that couldn't be read and the line Add folder… left (a refusal, or what the new folder took
  // over). An import folder with crates is a row to pick (the route's folder, else the first one): its crates' switches
  // follow the list and take the growing part, the list then keeping its rows' height (one grow group per Panel). The
  // foot holds the panel's one filled button: Continue import while files wait and nothing imports, else
  // Add folder…, and under the buttons why they are off while another change runs. The page owns the flow, so the row's line follows the import while another row is open.
  import { Hint, ImportCard, ProblemCard, UnreadableList, WatchedFolderList, WriteButton, canContinue, importView,
    type WatchedFoldersFlow } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { go, settingsFolderHref } from '$lib/router';
  import { hub, writeBlockedReason } from '$lib/stores/hub';
  import CrateSwitches from './CrateSwitches.svelte';
  import { pickedFolder } from './cratesModel';

  let { flow, folder }: { flow: WatchedFoldersFlow; /** the route's folder path (`#/settings/folders/<path>`) */ folder?: string } = $props();

  const picked = $derived(pickedFolder(flow.data?.folders, folder));

  const view = $derived(importView($hub.job, flow.data));
  const offerContinue = $derived(canContinue($hub.job, flow.data));
  const blocked = $derived($writeBlockedReason);
</script>

{#snippet head()}
  <!-- a failed read shows whenever it is the newest answer, over the rows it leaves standing; the next good read clears it -->
  {#if flow.error}
    <ProblemCard kind={flow.error.kind} message={flow.error.message} onretry={() => void flow.load()} />
  {/if}
  {#if view}
    <ImportCard {view} onstop={() => void flow.stop()} test="folders-import" />
  {/if}
{/snippet}

{#snippet fill()}
  <WatchedFolderList folders={flow.data?.folders ?? null} grow={!picked} onremove={(f) => void flow.remove(f)}
    removeOff={blocked} removing={flow.removing} picked={picked?.id ?? null} cap={picked ? 4 : undefined}
    onpick={(f) => { if (f.id !== picked?.id) void go(settingsFolderHref(f.path)); }} test="folders-list" />
  {#if picked}{#key picked.id}<CrateSwitches folder={picked} reload={flow.load} />{/key}{/if}
{/snippet}

{#snippet after()}
  <UnreadableList files={flow.data?.unreadable ?? []} folders={flow.data?.folders ?? []} test="folders-unreadable" />
  {#if flow.note}
    <div class="note" data-test="folders-note" data-tone={flow.note.tone}>
      {#each flow.note.lines as line (line)}<Hint text={line} tone={flow.note.tone === 'problem' ? 'problem' : 'muted'} wrap />{/each}
    </div>
  {/if}
{/snippet}

{#snippet foot()}
  {#if offerContinue}
    <WriteButton wide busy={flow.adding} onclick={() => void flow.add()} data-test="folders-add">Add folder…</WriteButton>
    <WriteButton variant="filled" wide busy={flow.starting} onclick={() => void flow.continueImport()}
      data-test="folders-continue">Continue import</WriteButton>
  {:else}
    <WriteButton variant="filled" wide busy={flow.adding} onclick={() => void flow.add()} data-test="folders-add">Add
      folder…</WriteButton>
  {/if}
  <!-- why the buttons are off, right under them (Setup's step puts the same Hint beside its button); not while this
       panel's own add is under way, which is what blocks -->
  {#if blocked && !flow.adding}<Hint text={blocked} data-test="folders-why" />{/if}
{/snippet}

<Panel head={flow.error || view ? head : undefined} {fill}
  after={flow.data?.unreadable.length || flow.note ? after : undefined} {foot} />

<style>
  .note { display: flex; flex-direction: column; gap: var(--s-1); min-width: 0; }
</style>
