<script lang="ts">
  // Duplicates in the panel (plan library stage 4, 7.3, W8; mockup todo-decisions "Which file stays?"): the same
  // audio, or the same song, in two or more files. The head names the song (the track card, the why under it); then
  // one ChoiceGroup of the files: line 1 the quality and format, line 2 the folder's last part (+ "in your
  // playlists"), ▶ at the row's end, the full path its tooltip; the app's pick (pair.recommended) is picked and says
  // why, every file that won't stay says "Goes to Superseded/" while another is picked, and Keep both / Keep all is
  // the list's last, ruled row. With no clear winner nothing is picked and the head says so. The foot's one filled
  // button names the result ("Keep the AIFF"; off with "Choose the file that stays" until a pick), the line under it
  // where the others go (nothing is deleted).
  // Keeping a file is "supersede" write jobs (D10: journaled, no undo), one per file that goes; after each, the
  // group is the one of the files left (groupIdOf), so a group of three takes two jobs. Keep both is one "answer"
  // job. Errors: runJob's toast, words as sent; the re-fetch keeps the group selected while files are left in it.
  import type { DuplicateItem, FileSide, Result } from '$lib/bridge/types';
  import { api, runJob } from '$lib/bridge/client';
  import { toasts } from '$lib/stores/toasts';
  import { ChoiceGroup, Hint, QualityBadge, Surface, TrackHead, WriteButton } from '$lib/components';
  import type { ChoiceOption } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { fileFormat, fileName, groupIdOf, keepLabel, keepWords, lastFolder, type DuplicatePick } from './todoModel';
  import FilePlay from './FilePlay.svelte';

  let { item }: { item: DuplicateItem } = $props();

  const g = $derived(item.pair);
  // the app's pick until the user picks (the component is keyed by the group, so a new group starts over)
  let chosen = $state<DuplicatePick | undefined>(undefined);
  const pick = $derived<DuplicatePick>(chosen !== undefined ? chosen : g.recommended ?? null);
  const words = $derived(keepWords(g.files, pick));
  let busy = $state(false);

  const ALL = 'all' as const;
  type Key = number | typeof ALL;
  const options = $derived<ChoiceOption<Key>[]>([
    ...g.files.map((f): ChoiceOption<Key> => ({ key: f.file_id, test: 'duplicate-file' })),
    { key: ALL, name: keepLabel(g.files.length), summary: `${g.files.length > 2 ? 'All' : 'Both'} stay; this to-do goes away`,
      ruled: true, test: 'duplicates-keep-all' }]);
  const byId = $derived(new Map(g.files.map((f) => [f.file_id, f])));

  async function keepAll() {
    busy = true;
    await runJob(api.keep_duplicates(g.group_id, g.files.map((f) => f.path)));
    busy = false;
  }
  async function keepOne(keep: number) {
    busy = true;
    let left = [...g.files];
    let last: Result | null = null;
    for (const f of g.files.filter((x) => x.file_id !== keep)) {
      const r = await runJob<{ result: Result }>(api.supersede_duplicate(groupIdOf(left.map((x) => x.file_id)), f.file_id,
        left.map((x) => x.path)), { success: false });
      if (!r.ok) break;
      last = r.result?.result ?? null;
      left = left.filter((x) => x !== f);
    }
    busy = false;
    const moved = g.files.length - left.length;
    if (moved === 1 && last?.note) toasts.show({ tone: 'success', title: last.note });
    else if (moved > 1) toasts.show({ tone: 'success', title: `Moved ${moved} files to Superseded/.` });
  }
  function go() {
    if (pick === ALL) void keepAll();
    else if (typeof pick === 'number') void keepOne(pick);
  }
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
    <FilePlay files={g.files} file={byId.get(o.key) as FileSide} cover={item.cover_url} test="duplicate-play" />
  {/if}
{/snippet}

{#snippet head()}
  <div class="details" data-test="duplicates" data-group={g.group_id} data-files={g.files.length}
    data-pick={pick ?? undefined}>
    <Surface kind="card">
      <TrackHead track={item} place={item.folder}><span class="why">{item.detail}</span></TrackHead>
    </Surface>
    <ChoiceGroup label="Which file stays?" summary={g.recommended === null ? 'no clear winner' : undefined}
      hint={g.recommended === null ? 'Same quality and format. Keep the one in the folder rekordbox uses.' : undefined}
      {options} value={pick} onchange={(k) => (chosen = k)} content={fileRow} trail={play} disabled={busy}
      test="duplicate-files" />
  </div>
{/snippet}

{#snippet foot()}
  <WriteButton variant="filled" wide busy={busy} disabled={!words.ready} onclick={go} data-test="duplicates-keep">
    {words.label}</WriteButton>
  {#if words.hint}<div class="centered"><Hint text={words.hint} wrap data-test="duplicates-hint" /></div>{/if}
{/snippet}

<Panel {head} {foot} />

<style>
  .details { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .why { font-size: var(--fs-small); color: var(--text-muted); }
  .nm { color: var(--text); font-weight: var(--fw-medium); }
  .fmt { display: flex; align-items: center; gap: 6px; min-width: 0; }
  .f { color: var(--text); font-weight: var(--fw-medium); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .line { font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .reason { font-size: var(--fs-small); color: var(--accent-text); }
  /* yellow: it needs nothing from the user, but it is a change they should see before they press */
  .gone { font-size: var(--fs-small); color: var(--q-good); display: flex; gap: 5px; align-items: center; }
  .gone svg { width: 12px; height: 12px; flex-shrink: 0; }
  .centered :global(.hint) { text-align: center; }
</style>
