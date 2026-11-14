<script lang="ts">
  // Make all lossless files AIFF, a selection's Convert and the CDJ group's Convert all (issue 33 stage D, plan §6.0.2):
  // the stage's one decision panel for several files, one Panel in three phases built on UpgradeSelection's layout
  // (stage B's batch panel), so a batch reads the same wherever it runs:
  // - decide: the head card (what the panel is about and how many can change), the plan as the fill's one list ("What
  //   happens": each file with its kind under its name, or, for more than 8, the counts per kind with the files folded
  //   under "Files"; then "Left as they are" with each reason), then the "AIFF" card (the format sentence, the room per
  //   drive, the rekordbox and Superseded/ outcome rows) under the lossy note; the foot's one filled button, off with
  //   its reason as the Hint under it (a short drive, rekordbox open while it holds some of these files), and Cancel.
  //   The decide phase is one scrolling column (the panel's body): the plan's list has no scroller of its own, so
  //   "Left as they are", the "Files" fold, the note and every space row are reached by scrolling the one column. A
  //   shortage is said once, by the foot's Hint in the problem tone; the space rows stay neutral.
  //   While the plan is read the head keeps its height and the list waits as Skeleton rows; nothing to change is an
  //   EmptyState and no filled button;
  // - running: how many of how many with the file in work and its bar, the rows marked as they pass, Stop;
  // - ended (until Done): the number made AIFF, the note when it ended early (stopped, rekordbox opened, refused), the
  //   files left as they are with their reasons and those still to do; Done, or Resume · k left / Try again.
  // The plan and the batch are the window's AiffBatchFlow, so the progress survives a pick of another row. The page
  // hosts the panel and passes the scope (the Library's selection or view, To-do's selection or the CDJ group).
  import type { AiffPlan, AiffScope } from '$lib/bridge/types';
  import {
    Button, Cover, EmptyState, Hint, KeyValue, ListRow, ListSection, NoteCard, OutcomeList, ProgressBar, Skeleton, Spinner,
    StatCard, StatusMark, Surface, WriteButton,
  } from '$lib/components';
  import { untrack } from 'svelte';
  import { formatWords } from '$lib/format';
  import { Panel } from '$lib/frames';
  import { filesVersion, writeBlockedReason } from '$lib/stores/hub';
  import {
    FORMAT_SENTENCE, LEFT_TITLE, STILL_TO_DO, aiffEndNote, aiffRunLabel, blockReason, emptyWords, filesSummary, kindLabel,
    leftCount, leftRows, listShape, lossyNote, madeWords, panelHead, panelPhase, planOutcomes, runLabel, scopeKey, showsFormat,
    spaceRows, type AiffOrigin, type LeftRow,
  } from './aiffBatchModel';
  import { endGroups, endNoteSaysCount, panelFocus, resumeLabel, runUnit, type RunRow } from './decisionModel';
  import { refocus } from './focus';
  import { aiffBatch, type AiffBatchFlow } from './flows.svelte';

  let { scope, origin = 'library', label = null, known, oncancel, ondone, onact, flow = aiffBatch }: {
    /** what the panel is for: a selection (`tracks`), a Library view's lossless files (`lossless`) or To-do's CDJ group */
    scope: AiffScope;
    /** the page that opened it: the Convert job's origin, and To-do's words ("files for CDJs", "Convert k to AIFF") */
    origin?: AiffOrigin;
    /** the view's title the page shows (a `lossless` scope), so the head is whole while the plan is read */
    label?: string | null;
    /** the page's own name and cover of a track it lists (the Library's "Artist - Title"); the plan's name otherwise */
    known?: (track_id: string) => { name: string; cover_url: string | null } | null;
    /** Cancel: the page puts the panel away (the Library goes back to a track's details) */
    oncancel: () => void;
    /** Done at the end: the end is put away, then the page does what follows */
    ondone: () => void;
    /** a batch starts from this panel (Make, Resume, Try again): the page keeps the panel until the next pick */
    onact?: () => void;
    flow?: AiffBatchFlow;
  } = $props();

  const key = $derived(scopeKey(scope));
  // the plan is read for a new scope and again after any file change (a job finished, a drive came or went)
  $effect(() => {
    void key;
    void $filesVersion;
    untrack(() => void flow.load(scope));
  });
  // and when the window gets focus back while the plan shows: the user quit rekordbox or freed space, then returned
  $effect(() => {
    const onFocus = () => { if (!flow.covers(scope)) void flow.load(scope); };
    window.addEventListener('focus', onFocus);
    return () => window.removeEventListener('focus', onFocus);
  });

  const read = $derived(flow.read?.key === key ? flow.read : null);
  const plan = $derived(read?.plan ?? null);
  const run = $derived(flow.covers(scope) ? flow.view : null);
  const phase = $derived(panelPhase(read, run));
  const heading = $derived(panelHead(scope, plan, origin, label));
  const shape = $derived(plan ? listShape(plan) : 'files');
  const left = $derived(plan ? leftRows(plan) : []);
  const block = $derived(plan ? blockReason(plan) : null);
  const outcomes = $derived(plan ? planOutcomes(plan) : []);
  const space = $derived(plan ? spaceRows(plan) : []);
  const lossy = $derived(plan ? lossyNote(plan.lossy) : null);
  const renames = $derived(!!plan && plan.items.length > 0 && plan.items.every((i) => i.action === 'rename'));
  const blocked = $derived($writeBlockedReason);
  const why = $derived(block ?? (blocked ? { text: blocked, tone: 'muted' as const } : null));

  // "Files" (more than 8): folded until its head is pressed; a new scope folds it again
  let filesOpen = $state(false);
  $effect(() => { void key; filesOpen = false; });

  const ended = $derived(run?.phase === 'ended' ? endGroups(run.rows) : { notDone: [], left: [] });
  const endCount = $derived(ended.notDone.length + ended.left.length);
  const made = $derived(run?.end ? madeWords(run.done, run.renames) : null);
  const note = $derived(run?.end ? aiffEndNote(run.end) : null);
  /** the file in work, by the page's own name for it where it lists it */
  const nowName = $derived.by(() => {
    const r = run?.rows.find((x) => x.state === 'now');
    return r ? nameOf(r.track_id, r.name) : run?.now ?? null;
  });

  const nameOf = (id: string, fallback: string) => known?.(id)?.name ?? fallback;
  const coverOf = (id: string, fallback: string | null = null) => fallback ?? known?.(id)?.cover_url ?? null;
  /** the plan's files as the running list's rows */
  const runRows = (p: AiffPlan): RunRow[] => p.items.map((i) => ({ track_id: i.track, name: nameOf(i.track, i.name),
    sub: kindLabel(p, i.kind), cover_url: coverOf(i.track), state: 'waiting', text: null }));

  function make() {
    if (!plan || !plan.total) return;
    onact?.();
    void flow.start(scope, runRows(plan), renames, origin);
  }
  function resume(batch_id: number) { onact?.(); void flow.resume(batch_id); }
  function done() { flow.clear(); ondone(); }

  // Focus follows the foot (UpgradeSelection's rule): the pressed button is gone, so Stop takes it while the batch
  // runs, then the end's filled button. Only for a change seen here, never on opening on a batch already in a phase.
  let root = $state<HTMLElement>();
  let lastPhase = untrack(() => run?.phase);
  $effect(() => {
    const p = run?.phase;
    const target = panelFocus(run);
    untrack(() => {
      if (p === lastPhase) return;
      lastPhase = p;
      if (target) void refocus(() => root?.querySelector<HTMLElement>(`[data-test="${target}"]`));
    });
  });
</script>

{#snippet headCard()}
  <!-- the inspector's subject, as TrackHead is a track's: the title at the title size, the count line under it; while the
       plan is read, a line not known yet waits as a Skeleton of that line's own height, so nothing moves when it comes -->
  <Surface kind="card" data-test="aiff-batch-head">
    <div class="hd">
      <h2 class="title">{#if heading.title}<span data-test="aiff-batch-title">{heading.title}</span>{:else if phase === 'loading'}<span class="wait"
          ><Skeleton height={14} width="60%" /></span>{/if}</h2>
      <p class="sub">{#if heading.sub}<span data-test="aiff-batch-sub">{heading.sub}</span>{:else if phase === 'loading'}<span class="wait"
          ><Skeleton height={10} width="40%" /></span>{/if}</p>
    </div>
  </Surface>
{/snippet}

{#snippet mark(r: RunRow)}
  <span class="mark" data-mark>
    {#if r.state === 'now'}<Spinner size={12} label="Working on it" />
    {:else if r.state === 'handled'}<StatusMark tone="good" quiet />
    {:else if r.state === 'done'}<StatusMark tone="good" />
    {:else if r.state === 'skipped'}<StatusMark tone="warn" />
    {:else if r.state === 'failed'}<StatusMark tone="problem" />
    {:else if r.state === 'waiting'}<StatusMark tone="none" />{/if}
  </span>
{/snippet}

{#snippet runRowsOf(rows: RunRow[])}
  {#each rows as r (r.track_id)}
    <ListRow wrap wrapName title={nameOf(r.track_id, r.name)} test="run-row" data-track={r.track_id} data-state={r.state}>
      {#snippet lead()}<span class="lead">{@render mark(r)}<Cover url={coverOf(r.track_id, r.cover_url)} seed={r.track_id} size={28} /></span>{/snippet}
      {#snippet name()}{nameOf(r.track_id, r.name)}{/snippet}
      {#snippet sub()}{#if r.text}<span class={r.state === 'failed' ? 'bad' : 'warn'}>{r.text}</span>{:else}{r.sub}{/if}{/snippet}
    </ListRow>
  {/each}
{/snippet}
{#snippet runList(rows: RunRow[], title: string, summary: string | undefined, test: string, more?: { label: string; rows: RunRow[] })}
  <Surface kind="list" label={title} {summary} style="--row-cols: 52px minmax(0, 1fr)"
    grow={{ rows: rows.length + (more ? more.rows.length + 1 : 0), tall: true }} data-test={test}>
    {@render runRowsOf(rows)}
    {#if more}
      <ListSection label={more.label} summary={String(more.rows.length)} test="batch-left" />
      {@render runRowsOf(more.rows)}
    {/if}
  </Surface>
{/snippet}

{#snippet fileRow(i: AiffPlan['items'][number], p: AiffPlan)}
  <ListRow wrap title={nameOf(i.track, i.name)} test="aiff-file" data-track={i.track} data-action={i.action} style="--row-cols: 28px minmax(0, 1fr)">
    {#snippet lead()}<Cover url={coverOf(i.track)} seed={i.track} size={28} />{/snippet}
    {#snippet name()}{nameOf(i.track, i.name)}{/snippet}
    {#snippet sub()}{kindLabel(p, i.kind)}{/snippet}
  </ListRow>
{/snippet}
{#snippet leftRow(r: LeftRow)}
  {#if r.track}
    {@const track = r.track}
    <ListRow wrap title={nameOf(track, r.name)} test="aiff-left" data-track={track} style="--row-cols: 28px minmax(0, 1fr)">
      {#snippet lead()}<Cover url={coverOf(track)} seed={track} size={28} />{/snippet}
      {#snippet name()}{nameOf(track, r.name)}{/snippet}
      {#snippet sub()}{r.text}{/snippet}
    </ListRow>
  {:else}
    <!-- a view's waiting files: the engine counts them by reason and names none -->
    <ListRow wrap title={r.text} test="aiff-left" data-reason={r.key} style="--row-cols: minmax(0, 1fr)">
      {#snippet name()}{r.name}{/snippet}
      {#snippet sub()}{r.text}{/snippet}
    </ListRow>
  {/if}
{/snippet}

{#snippet head()}
  {#if phase === 'running' && run}
    <StatCard value={run.done} unit={runUnit(run.total || run.rows.length)} label={aiffRunLabel(nowName, run.renames)}
      valueTest="batch-done" data-test="batch-progress">
      <ProgressBar value={run.total ? run.done / run.total : 0} label={aiffRunLabel(null, run.renames)} />
    </StatCard>
  {:else if phase === 'ended' && run?.end && made}
    <!-- the number only where the note doesn't already say it ("Stopped after 2 of 4."), and not "0 files" over a note
         that says why nothing was made -->
    {#if (run.done || run.end.kind === 'done') && !endNoteSaysCount(run.end)}
      <StatCard value={run.done} unit={made.unit} label={made.label} valueTest="batch-result" data-test="batch-result" />
    {/if}
    {#if note}<NoteCard tone={note.tone} data-test="batch-note" data-kind={run.end.kind}>{note.text}</NoteCard>{/if}
  {:else}
    {@render headCard()}
  {/if}
{/snippet}

{#snippet fill()}
  {#if phase === 'running' && run}
    {@render runList(run.rows, filesSummary(run.rows.length), undefined, 'batch-rows')}
  {:else if phase === 'ended'}
    {#if ended.notDone.length}
      {@render runList(ended.notDone, LEFT_TITLE, String(ended.notDone.length), 'batch-not-done',
        ended.left.length ? { label: STILL_TO_DO, rows: ended.left } : undefined)}
    {:else if ended.left.length}
      {@render runList(ended.left, STILL_TO_DO, String(ended.left.length), 'batch-not-done')}
    {/if}
  {:else if phase === 'loading'}
    <!-- the plan's list waiting in its own rows: no "Counting…", nothing to read until the numbers are there -->
    <Surface kind="list" label="What happens" grow={{ rows: 3 }} data-test="aiff-batch-plan" data-loading="true">
      {#each [62, 48, 70] as w (w)}
        <ListRow style="--row-cols: minmax(0, 1fr) auto">
          {#snippet name()}<span class="wait"><Skeleton height={10} width="{w}%" /></span>{/snippet}
          {#snippet trailing()}<span class="wait n"><Skeleton height={10} width="16px" /></span>{/snippet}
        </ListRow>
      {/each}
    </Surface>
  {:else if phase === 'error'}
    <NoteCard tone="problem" data-test="aiff-batch-error">{read?.message}</NoteCard>
  {:else if phase === 'empty'}
    <Surface kind="list" label="What happens" data-test="aiff-batch-plan" data-empty="true">
      <EmptyState title={emptyWords(scope)} />
    </Surface>
  {:else if plan}
    {@const p = plan}
    <Surface kind="list" label={p.items.length ? 'What happens' : LEFT_TITLE}
      summary={String(p.items.length ? p.total : leftCount(left))} data-test="aiff-batch-plan" data-shape={shape}>
      {#if p.items.length}
        {#if shape === 'files'}
          {#each p.items as i (i.track)}{@render fileRow(i, p)}{/each}
        {:else}
          {#each p.kinds as k (k.kind)}
            <ListRow wrapName title={k.label} test="aiff-kind" data-kind={k.kind} style="--row-cols: minmax(0, 1fr) auto">
              {#snippet name()}{formatWords(k.label)}{/snippet}
              {#snippet trailing()}<span class="count">{k.n}</span>{/snippet}
            </ListRow>
          {/each}
          <ListSection label="Files" summary={String(p.items.length)} test="aiff-files"
            fold={{ open: filesOpen, toggle: () => (filesOpen = !filesOpen) }} />
          {#if filesOpen}{#each p.items as i (i.track)}{@render fileRow(i, p)}{/each}{/if}
        {/if}
        {#if left.length}<ListSection label={LEFT_TITLE} summary={String(leftCount(left))} test="aiff-left-head" />{/if}
      {/if}
      {#each left as r (r.key)}{@render leftRow(r)}{/each}
    </Surface>
  {/if}
{/snippet}

{#snippet after()}
  {#if lossy && plan?.items.length}<NoteCard tone="info" data-test="aiff-lossy">{lossy}</NoteCard>{/if}
  {#if plan && plan.items.length && (showsFormat(plan) || space.length || outcomes.length)}
    <!-- the same "AIFF" card as one file's (AiffCard): what every file becomes, the room it takes, what stays -->
    <Surface kind="card" label="AIFF" data-test="aiff-batch-card">
      <div class="col">
        {#if showsFormat(plan)}<p class="fmt" data-test="aiff-format">{formatWords(FORMAT_SENTENCE)}</p>{/if}
        {#if space.length}
          <div class="rows">
            {#each space as r, n (r.drive)}
              <KeyValue keyWidth={76} k={n === 0 ? 'Space' : ''}>
                <span class="space" data-test="aiff-space" data-enough={r.enough}>
                  <span>{r.needs}</span><span class="free">{r.free}</span>
                </span>
              </KeyValue>
            {/each}
          </div>
        {/if}
        {#if outcomes.length}<OutcomeList items={outcomes} test="aiff-batch-outcomes" />{/if}
      </div>
    </Surface>
  {/if}
{/snippet}

{#snippet foot()}
  {#if phase === 'running' && run}
    <Button wide busy={run.stopping} busyLabel="Stopping" onclick={() => flow.stop()} data-test="batch-stop">Stop</Button>
  {:else if phase === 'ended' && run?.end}
    {@const end = run.end}
    {#if end.resume || run.again}
      <div class="row">
        <Button onclick={done} data-test="batch-done-plain">Done</Button>
        {#if end.resume}
          {@const r = end.resume}
          <WriteButton variant="filled" wide onclick={() => resume(r.batch_id)} data-test="batch-resume">{resumeLabel(r.left)}</WriteButton>
        {:else}
          <WriteButton variant="filled" wide onclick={() => { onact?.(); run?.again?.(); }} data-test="batch-again">Try again</WriteButton>
        {/if}
      </div>
    {:else}
      <Button variant="filled" wide onclick={done} data-test="batch-close">Done</Button>
    {/if}
  {:else}
    {#if phase === 'loading' || (phase === 'decide' && plan?.items.length)}
      <WriteButton variant="filled" wide disabled={phase === 'loading' || !!block} onclick={make}
        data-test="aiff-batch-run">{runLabel(scope, phase === 'loading' ? null : plan, origin)}</WriteButton>
      {#if phase === 'decide' && why}
        <div class="centered"><Hint text={why.text} tone={why.tone} wrap data-test="aiff-batch-why" /></div>
      {/if}
    {:else if phase === 'error'}
      <Button wide onclick={() => void flow.load(scope)} data-test="aiff-batch-retry">Try again</Button>
    {/if}
    <div class="centered"><Button variant="link" onclick={oncancel} data-test="aiff-batch-cancel">Cancel</Button></div>
  {/if}
{/snippet}

<div class="batch" bind:this={root} data-test="aiff-batch" data-phase={phase} data-end={run?.end?.kind}>
  <Panel {head} fill={phase !== 'ended' || endCount ? fill : undefined} after={phase === 'decide' ? after : undefined} {foot} />
</div>

<style>
  .batch { display: contents; }
  .hd { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  /* each line has its own height, so a Skeleton waiting in it takes exactly the room its words will */
  .title { margin: 0; min-height: 22px; font-size: var(--fs-title); line-height: 22px; font-weight: var(--fw-semi);
    color: var(--text-strong); text-wrap: balance; overflow-wrap: anywhere; }
  .sub { margin: 0; min-height: 18px; font-size: var(--fs-body); line-height: 18px; color: var(--text-muted);
    overflow-wrap: anywhere; }
  .wait { display: flex; align-items: center; height: 100%; min-height: inherit; width: 100%; }
  .wait.n { width: 16px; justify-content: flex-end; }
  .count { color: var(--text-muted); font-variant-numeric: tabular-nums; }
  .col { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .rows { display: flex; flex-direction: column; }
  .fmt { margin: 0; font-size: var(--fs-small); line-height: 1.45; color: var(--text); }
  /* "Needs 1.4 GB on Example Drive" over "412.3 GB free", as KeyValue's quiet second line, both lines wrapping. Neutral
     whatever the drive: a shortage is said once, by the foot's Hint in the problem tone */
  .space { display: flex; flex-direction: column; min-width: 0; overflow-wrap: anywhere; }
  .free { margin-top: 2px; font-size: var(--fs-small); color: var(--text-muted); }
  /* mark · cover on a fixed grid, so the covers stay in one column whatever the mark (none, ✓, spinner) */
  .lead { display: grid; grid-template-columns: 16px 28px; column-gap: var(--s-2); align-items: center; }
  .mark { display: grid; place-items: center; width: 16px; height: 16px; }
  .row { display: flex; gap: var(--s-2); }
  .centered { display: flex; justify-content: center; }
  .centered :global(.hint) { text-align: center; }
  /* a reason's words in the colours of its mark, as the moves panel's (MovesPanel) */
  .warn { color: var(--risk-notice); }
  .bad { color: var(--q-weak); }
</style>
