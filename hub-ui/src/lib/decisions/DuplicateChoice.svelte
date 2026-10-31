<script lang="ts">
  // "Which file stays?" (plan library stage 4, 7.3, W8; mockup todo-decisions), the same in To-do's and the Library's
  // details: one ChoiceGroup of the group's files: line 1 the quality and format, line 2 the folder's last part
  // (+ "in your playlists"), ▶ at the row's end, the full path its tooltip; the app's pick (pair.recommended) is picked
  // and says why, every file that won't stay says "Goes to Superseded/" while another is picked, and Keep both / Keep
  // all is the list's last, ruled row. With no clear winner nothing is picked and the head says so. The pick lives in
  // the flow DuplicateFoot reads.
  import type { DuplicateItem, FileSide } from '$lib/bridge/types';
  import { ChoiceGroup, QualityBadge } from '$lib/components';
  import type { ChoiceOption } from '$lib/components';
  import { fileFormat, fileName, keepLabel, lastFolder } from './decisionModel';
  import type { DuplicateFlow } from './flows.svelte';
  import FilePlay from './FilePlay.svelte';

  let { item, flow, source }: {
    item: DuplicateItem; flow: DuplicateFlow;
    /** the foot's link back while a file plays (FilePlay; To-do's by default) */
    source?: { label: string; href: string };
  } = $props();

  const g = $derived(item.pair);
  $effect(() => flow.follow(g.group_id));
  const pick = $derived(flow.pick(g));

  const ALL = 'all' as const;
  type Key = number | typeof ALL;
  const options = $derived<ChoiceOption<Key>[]>([
    ...g.files.map((f): ChoiceOption<Key> => ({ key: f.file_id, test: 'duplicate-file' })),
    { key: ALL, name: keepLabel(g.files.length), summary: `${g.files.length > 2 ? 'All' : 'Both'} stay; this to-do goes away`,
      ruled: true, test: 'duplicates-keep-all' }]);
  const byId = $derived(new Map(g.files.map((f) => [f.file_id, f])));
</script>

{#snippet fileRow(o: ChoiceOption<Key>, on: boolean)}
  {#if o.key === ALL}
    <span class="nm">{o.name}</span><span class="line">{o.summary}</span>
  {:else}
    {@const f = byId.get(o.key) as FileSide}
    <span class="fmt"><QualityBadge quality={f.quality} label={f.quality_label} /><span class="f">{fileFormat(f.path)}</span></span>
    <span class="line" title={f.path}>{lastFolder(f.path) || fileName(f.path)}{f.in_playlist ? ' · in your playlists' : ''}</span>
    {#if f.file_id === g.recommended && g.recommended_why}<span class="reason" data-test="duplicate-why">{g.recommended_why}</span>{/if}
    {#if typeof pick === 'number' && !on}
      <span class="gone" data-test="duplicate-goes"><svg viewBox="0 0 12 12" aria-hidden="true" fill="none"
        stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path
        d="M2 6h7.5M6.8 3.2L9.6 6 6.8 8.8" /></svg>Goes to Superseded/</span>
    {/if}
  {/if}
{/snippet}

{#snippet play(o: ChoiceOption<Key>)}
  {#if o.key !== ALL}
    <FilePlay files={g.files} file={byId.get(o.key) as FileSide} cover={item.cover_url} {source} test="duplicate-play" />
  {/if}
{/snippet}

<ChoiceGroup label="Which file stays?" summary={g.recommended === null ? 'no clear winner' : undefined}
  hint={g.recommended === null ? 'Same quality and format. Keep the one in the folder rekordbox uses.' : undefined}
  {options} value={pick} onchange={(k) => (flow.chosen = k)} content={fileRow} trail={play} disabled={flow.busy}
  test="duplicate-files" />

<style>
  .nm { color: var(--text); font-weight: var(--fw-medium); }
  .fmt { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .f { color: var(--text); font-weight: var(--fw-medium); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .line { font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .reason { font-size: var(--fs-small); color: var(--accent-text); }
  /* yellow: it needs nothing from the user, but it is a change they should see before they press */
  .gone { font-size: var(--fs-small); color: var(--q-good); display: flex; gap: 5px; align-items: center; }
  .gone svg { width: 12px; height: 12px; flex-shrink: 0; }
</style>
