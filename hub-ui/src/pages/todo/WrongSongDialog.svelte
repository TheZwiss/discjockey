<script lang="ts">
  // "Wrong song?" / "Find a version" dialog (Task 67 part B, spec §6.6): candidates with ▶ preview, Use this,
  // Use link, None of these; the download's progress while a use job runs (the dialog can't be closed then).
  import { onDestroy, untrack } from 'svelte';
  import { api, runJob, type JobOutcome } from '$lib/bridge/client';
  import type { Candidate, Candidates, Fail, TrackDetail } from '$lib/bridge/types';
  import { Button, Dialog, ProblemCard, ProgressBar, Spinner, TextField, WriteButton, confirm } from '$lib/components';
  import { problemCopy } from '$lib/copy';
  import { networkReadsAllowed } from '$lib/stores/hub';
  import { CANT_PLAY, claimSound, releaseSound } from '$lib/stores/player';
  import { run } from '$lib/stores/run';
  import {
    NONE_CONFIRM, NOTHING_FOUND, SEARCHING, SEARCH_BLOCKED, canUse, dialogTitle, lengthText, lengthTone, matchText,
    matchTone, previewOffer, progressText, progressValue, secondLine, subLine,
  } from './candidates';
  import { actionsFor } from './todoModel';

  let { track, onclose }: { track: TrackDetail; onclose: () => void } = $props();

  let open = $state(true);
  let res = $state<Candidates | null>(null);
  let problem = $state<Fail | null>(null);
  let searching = $state(false);
  let job = $state<'use' | 'link' | 'none' | null>(null);
  let usingKey = $state<string | null>(null);
  let message = $state<string | null>(null);
  let link = $state('');
  let previewKey = $state<string | null>(null);     // preview being fetched
  let gone = $state(new Set<string>());             // DRM-protected: taken off the list (the backend remembers them)
  const shown = $derived(res ? res.candidates.filter((c) => !gone.has(c.key)) : []);
  let playingKey = $state<string | null>(null);     // preview playing now

  const blocked = $derived(!$networkReadsAllowed || problem?.kind === 'sync_running');
  const noneOfThese = $derived(actionsFor(track).noneOfThese);
  const mine = $derived(job === 'use' || job === 'link'
    ? $run.job_track_id === track.track_id && ($run.job_kind === 'use_candidate' || $run.job_kind === 'use_link')
    : false);

  async function search() {
    searching = true; problem = null;
    const r = await api.search_candidates(track.track_id);
    searching = false;
    if (r.ok) res = r; else problem = r;
  }
  // search on open, and again when a sync that blocked the search has finished
  $effect(() => {
    const allowed = $networkReadsAllowed;
    untrack(() => { if (allowed && !res && !searching && (!problem || problem.kind === 'sync_running')) void search(); });
  });

  // The clips have their own element, not the player's: a clip pauses a queue (claimSound) and the queue's track
  // keeps its place, which swapping the shared element's src would lose.
  const CLIP = Symbol('clip');
  const CLIP_S = 20;
  let clip: HTMLAudioElement | null = null;
  function stopPreview() {
    if (clip) { clip.pause(); clip.removeAttribute('src'); clip.load(); }
    playingKey = null;
    releaseSound(CLIP);
  }
  function clipElement(): HTMLAudioElement {
    if (clip) return clip;
    const el = new Audio();
    el.addEventListener('timeupdate', () => { if (el.currentTime >= CLIP_S) stopPreview(); });
    el.addEventListener('ended', stopPreview);
    el.addEventListener('error', () => { if (playingKey) { message = CANT_PLAY; stopPreview(); } });
    return (clip = el);
  }
  onDestroy(stopPreview);

  async function preview(c: Candidate) {
    if (playingKey === c.key) { stopPreview(); return; }
    message = null; previewKey = c.key;
    const r = await api.preview(track.track_id, c);
    previewKey = null;
    if (!r.ok) {
      message = r.message;
      if (r.kind === 'protected') gone = new Set([...gone, c.key]);
      return;
    }
    claimSound(CLIP, stopPreview);
    const el = clipElement();
    playingKey = c.key;
    el.src = r.url;
    el.play().catch(() => { if (playingKey === c.key) { message = CANT_PLAY; stopPreview(); } });
  }

  function after(o: JobOutcome<unknown>) {
    if (!o.ok && o.kind === 'protected' && usingKey) gone = new Set([...gone, usingKey]);
    job = null; usingKey = null;
    if (o.ok) { open = false; onclose(); return; }   // the success toast comes from runJob; the page re-fetches
    message = o.message || problemCopy(o.kind).title;
  }
  async function use(c: Candidate) {
    stopPreview(); message = null; job = 'use'; usingKey = c.key;
    after(await runJob(api.use_candidate(track.track_id, c), { quiet: true }));
  }
  async function useLink() {
    if (!link.trim()) return;
    stopPreview(); message = null; job = 'link';
    after(await runJob(api.use_link(track.track_id, link.trim()), { quiet: true }));
  }
  async function none() {
    if (!(await confirm(NONE_CONFIRM))) return;
    stopPreview(); message = null; job = 'none';
    after(await runJob(api.reject_current(track.track_id), { quiet: true }));
  }
  function close() { stopPreview(); onclose(); }
</script>

<Dialog bind:open title={dialogTitle(track)} width={760} busy={job !== null} onclose={close}>
  <div class="body" data-test="wrong-song-dialog" data-track={track.track_id}>
    <p class="sub">{subLine(res?.track_duration_s ?? track.duration_s)}</p>

    {#if blocked && !res}
      <p class="note" data-test="search-blocked">{SEARCH_BLOCKED}</p>
    {:else if searching}
      <p class="loading" data-test="searching"><Spinner size={14} /> {SEARCHING}</p>
    {:else if problem}
      <div data-test="search-problem"><ProblemCard alert kind={problem.kind} message={problem.message} onretry={search} compact /></div>
    {:else if res}
      {#if blocked}<p class="note" data-test="search-blocked">{SEARCH_BLOCKED}</p>{/if}
      {#if res.candidates.length === 0}
        <p class="empty" data-test="no-candidates">{NOTHING_FOUND}</p>
      {:else}
        <div class="table" data-test="candidates" role="table" aria-label="Versions">
          <div class="row head" role="row">
            <span></span><span>Candidate</span><span>Source</span><span>Length</span><span>Match</span><span></span>
          </div>
          {#each shown as c (c.key)}
            {@const pv = previewOffer(c)}
            <div class="row" class:cur={c.current} class:rejected={c.rejected} role="row" data-test="candidate"
              data-key={c.key}>
              <span class="play">
                {#if pv.show}
                  <button type="button" class="pbtn" aria-label="Play a 20-second preview of {c.title}"
                    disabled={blocked || job !== null} onclick={() => preview(c)} data-test="preview">
                    {#if previewKey === c.key}<Spinner size={10} />{:else if playingKey === c.key}❚❚{:else}▶{/if}
                  </button>
                {:else if pv.title}
                  <span class="pbtn off" title={pv.title} aria-label={pv.title}>▶</span>
                {/if}
              </span>
              <span class="cand">
                <span class="title">{c.title}</span>
                <span class="second">{secondLine(c)}</span>
              </span>
              <span class="src">{c.source_name}</span>
              <span class="tone-{lengthTone(c)}">{lengthText(c)}</span>
              <span class="tone-{matchTone(c)}">{matchText(c)}</span>
              <span class="use">
                {#if canUse(c)}
                  <WriteButton size="sm" busy={usingKey === c.key} disabled={blocked || (job !== null && usingKey !== c.key)}
                    onclick={() => use(c)} data-test="use-candidate">Use this</WriteButton>
                {/if}
              </span>
            </div>
          {/each}
        </div>
      {/if}
      {#each res.notes as n}<p class="muted">{n}</p>{/each}
    {/if}

    {#if mine}
      <div class="progress" data-test="use-progress">
        <ProgressBar value={progressValue($run)} pace="live" label="Download progress" />
        <p class="muted">{progressText($run)}</p>
      </div>
    {/if}
    {#if message}<p class="msg" role="alert" data-test="use-message">{message}</p>{/if}

    <div class="link">
      <span class="muted">Or paste a link (YouTube / SoundCloud / Qobuz):</span>
      <div class="linkrow">
        <TextField bind:value={link} placeholder="https://…" type="url" mono disabled={job !== null}
          onenter={useLink} label="Link to another version" />
        <WriteButton size="sm" busy={job === 'link'} disabled={!link.trim() || (job !== null && job !== 'link')}
          onclick={useLink} data-test="use-link">Use link</WriteButton>
        {#if noneOfThese}
          <WriteButton size="sm" variant="secondary" busy={job === 'none'} disabled={job !== null && job !== 'none'}
            onclick={none} data-test="none-of-these">None of these</WriteButton>
        {/if}
      </div>
    </div>
  </div>
  {#snippet footer()}
    <Button onclick={() => { open = false; close(); }} disabled={job !== null}>Close</Button>
  {/snippet}
</Dialog>

<style>
  .body { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .sub, .muted { color: var(--text-muted); font-size: var(--fs-small); margin: 0; }
  .loading, .note, .empty { display: flex; align-items: center; gap: var(--s-2); color: var(--text-muted); margin: 0; }
  .table { display: flex; flex-direction: column; max-height: 360px; overflow-y: auto; }
  .row { display: grid; grid-template-columns: 24px minmax(0, 1fr) 82px 64px 56px 84px; gap: var(--s-2);
    align-items: center; padding: var(--s-2) var(--s-1); border-bottom: var(--bw) solid var(--line-row); }
  .row.head { color: var(--text-label); font-size: var(--fs-label); text-transform: uppercase; }
  .row.cur { background: var(--bg-inset); }
  .row.rejected .title, .row.rejected .second, .row.rejected .src, .row.rejected [class^='tone-'] {
    color: var(--text-dim); }
  .cand { display: flex; flex-direction: column; min-width: 0; }
  .title { color: var(--text-strong); overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .second { color: var(--text-muted); font-size: var(--fs-small); overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
  .src { color: var(--text-muted); }
  .tone-ok { color: var(--q-lossless); } .tone-warn { color: var(--q-good); } .tone-none { color: var(--text-muted); }
  .pbtn { width: 20px; min-width: 20px; height: 20px; border-radius: 50%; border: var(--bw) solid var(--line-control);
    background: none; color: var(--text-muted); font-size: var(--fs-label); display: flex; align-items: center;
    justify-content: center; padding: 0; cursor: pointer; }
  .pbtn:hover:not(:disabled) { border-color: var(--line-control-hover); color: var(--text); }
  .pbtn:disabled, .pbtn.off { color: var(--text-disabled); cursor: default; }
  .use { display: flex; justify-content: flex-end; }
  .progress { display: flex; flex-direction: column; gap: var(--s-1); }
  .msg { color: var(--q-weak); margin: 0; }
  .link { display: flex; flex-direction: column; gap: var(--s-2); padding-top: var(--s-2); }
  .linkrow { display: flex; gap: var(--s-2); align-items: center; }
  .linkrow :global(:first-child) { flex: 1; min-width: 0; }
</style>
