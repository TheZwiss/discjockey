<script lang="ts">
  // The selected to-do in the panel (spec §5.3, design system mockup design-system/todo.html), as a Panel: the head
  // holds the track card (cover, name, quality, Hide at the title's end for every kind), what this to-do needs (the
  // rekordbox check's cards, the Other note, the upgrade decision, or what is still being looked for), the cutoff as
  // a number over the spectrum, the current file (player, facts, Wrong song?; not for an upgrade decision, whose Now
  // column says it) and "Get a lossless file" (the artist's free download, buy links, the drop zone). The body scrolls
  // when it is long (Panel). The foot holds the to-do's own action as the screen's one filled button
  // (actionsFor().main): Replace with lossless (the "In rekordbox" pick: Same track = swap, New track = add_new),
  // Done, checked in rekordbox, Find a version, Show in Finder; a lossy file has none in the app (it is bought and
  // dropped), so its foot stays empty. Under Replace: Discard the new version and when a replace can be undone;
  // under Done, for a check a replace left that can still be undone (item.can_undo), "Undo the replace" (mockup
  // todo-decisions: full width, plain, the same width as Done).
  import { untrack } from 'svelte';
  import type { Spectrum as Spec, TodoItem, TrackDetail } from '$lib/bridge/types';
  import { api, runJob } from '$lib/bridge/client';
  import { networkReadsAllowed } from '$lib/stores/hub';
  import { onEvent } from '$lib/bridge/events';
  import { toasts } from '$lib/stores/toasts';
  import { NOT_WHILE_SYNC } from '$lib/copy';
  import { artistTitle, fileAway, fileAwayWords, qualityWords } from '$lib/format';
  import {
    Badge, Button, ExternalLink, Hint, KeyValue, MiniPlayer, NoteCard, QualityBadge, Spectrum, StatCard, Surface,
    TrackHead, WriteButton, confirm, envelope,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { actionsFor, cutoffStat, dropDecision, freeHint, qobuzText, replaceLabel, type Way } from './todoModel';
  import CheckCards from './CheckCards.svelte';
  import UpgradeBox from './UpgradeBox.svelte';
  import BoughtFile from './BoughtFile.svelte';

  let { track, item, onhidden, onversions, onlisten }: {
    track: TrackDetail; item: TodoItem | null;
    /** ▶ in the player: start the to-do list (its rows with a file, in the order shown) from this track */
    onlisten?: () => void;
    /** after "Hide" finished */
    onhidden: () => void;
    /** "Wrong song?" / "Find a version" (part B opens the dialog) */
    onversions: (track: TrackDetail) => void;
  } = $props();

  const act = $derived(actionsFor(track, item?.group ?? null));
  const qobuz = $derived(qobuzText(track.next_qobuz_check));
  const cutoff = $derived(track.upgrade ? null : cutoffStat(track));
  const hasFile = $derived(track.status !== 'missing');
  // the file isn't there (drive away, folder or file not found): no spectrum to ask for, the pictures say why, the
  // player stays off
  const driveAway = $derived(fileAway(track));
  const awayWords = $derived(fileAwayWords(track));

  // spectra: current (when there is a file) and upgrade; re-fetched when the file changes (audio_url carries ?v=)
  let current = $state<Spec | null>(null);
  let upSpec = $state<Spec | null>(null);
  let specError = $state<string | null>(null);
  let specLoading = $state(false);
  let seq = 0;
  $effect(() => {
    const key = `${track.track_id}|${track.audio_url}|${track.upgrade?.audio_url ?? ''}`;
    untrack(() => void loadSpectra(key));
  });
  let lastKey = '';
  async function loadSpectra(key: string) {
    if (key === lastKey) return;
    const sameTrack = lastKey.split('|')[0] === track.track_id;
    lastKey = key;
    const my = ++seq;
    if (!sameTrack) { current = null; upSpec = null; }
    specError = null;
    specLoading = true;
    const id = track.track_id;
    const [c, u] = await Promise.all([
      hasFile && !driveAway ? api.spectrum(id, 'current') : Promise.resolve(null),
      track.upgrade ? api.spectrum(id, 'upgrade') : Promise.resolve(null),
    ]);
    if (my !== seq) return;
    specLoading = false;
    if (c && c.ok) current = c.spectrum; else { current = null; if (c) specError = c.message; }
    upSpec = u && u.ok ? u.spectrum : null;
  }

  // the "In rekordbox" pick: Same track (swap) by default where both ways are possible; a new track starts over
  let picked = $state<Way | null>(null);
  let undoProblem = $state<string | null>(null);   // an undo's refusal, kept under its button until the next track
  let pickedFor = '';
  $effect(() => { if (track.track_id !== pickedFor) { pickedFor = track.track_id; picked = null; undoProblem = null; } });
  const way = $derived<Way>(act.upgrade?.swap ? (picked ?? 'swap') : 'add_new');

  let busy = $state<'hide' | 'rekordbox' | 'undo' | 'swap' | 'add_new' | 'discard' | null>(null);
  async function hide() {
    busy = 'hide';
    const r = await runJob(api.hide(track.track_id, !track.hidden));
    busy = null;
    if (r.ok && act.hide === 'hide') onhidden();
  }
  async function checked() {
    busy = 'rekordbox';
    await runJob(api.rekordbox_checked(track.track_id));
    busy = null;
  }
  async function undoUpgrade() {
    const swapped = item?.check?.reason === 'swapped';
    if (!(await confirm({ title: 'Undo the replace?',
      body: swapped ? 'Your old audio goes back in the file, and the new version waits in Upgrades ready again.'
        : 'Your old file goes back where it was, and the new version waits in Upgrades ready again.',
      confirmLabel: 'Undo the replace' }))) return;
    busy = 'undo';
    undoProblem = null;
    // a refusal (a file changed since, the step already done) shows as runJob's toast and stays under the button
    const r = await runJob(api.undo_upgrade(track.track_id));
    busy = null;
    if (!r.ok) undoProblem = r.message;
  }
  // Replace with lossless (swap / add_new, the "In rekordbox" pick) and Discard (spec §6.6). A replace needs no
  // confirm: it can be undone until Done (the hint under it says so); Discard deletes the new version, so it asks.
  async function upgrade(mode: 'swap' | 'add_new' | 'discard') {
    if (mode === 'discard' && !(await confirm({ title: 'Throw away the new version?',
      body: 'Your current file stays. This version is not offered again.', confirmLabel: 'Discard', tone: 'danger' }))) return;
    busy = mode;
    // "changed": runJob shows "This track changed in the meantime."; the finished job re-fetches the page
    await runJob(api.upgrade(track.track_id, mode));
    busy = null;
  }
  // A track without a drop zone (e.g. lossless): BoughtFile isn't there and the shell skips To-do, so an
  // unreadable drop on it would show nothing. Toast macOS's message like the shell does on other pages.
  $effect(() => onEvent((e) => {
    if (e.type !== 'FileDropped' || act.dropZone) return;
    const d = dropDecision(e, track.track_id);
    if (d.do === 'message') toasts.show({ tone: 'problem', title: "Can't read this file.", body: d.text });
  }));

  function finder() { void api.show_in_finder(track.track_id, 'current'); }
  const offline = $derived($networkReadsAllowed ? undefined : NOT_WHILE_SYNC);
</script>

{#snippet hideLink()}
  {#if act.hide}
    <WriteButton variant="link" muted size="sm" busy={busy === 'hide'} onclick={hide} data-test="hide">
      {act.hide === 'hide' ? 'Hide' : 'Unhide'}</WriteButton>
  {/if}
{/snippet}

{#snippet head()}
  <div class="details" data-test="details" data-track={track.track_id}>
    <Surface kind="card">
      <TrackHead {track} place={track.folder} action={act.hide ? hideLink : undefined}>
        <span class="state" data-test="details-state">
          <QualityBadge quality={track.quality} label={track.quality_label} upgrade={track.upgrade_ready} />
          <span class="words">{qualityWords(track.quality, track.quality_label)}</span>
        </span>
      </TrackHead>
    </Surface>

    {#if act.rekordboxDone && item}<CheckCards {item} />{/if}
    {#if item?.group === 'other'}
      <NoteCard data-test="other">{item.detail}</NoteCard>
    {/if}

    {#if track.upgrade}
      <UpgradeBox {track} {current} upgrade={upSpec} loading={specLoading} swap={!!act.upgrade?.swap} {way}
        onway={(w) => (picked = w)} busy={busy !== null} />
    {/if}

    {#if !hasFile}
      <Surface kind="card" label="Still looking" data-test="still-looking">
        <div class="facts">
          {#if qobuz}<KeyValue keyWidth={76} k="Qobuz" v={qobuz} />{/if}
          {#if item?.detail}<KeyValue keyWidth={76} k="Others" v={item.detail} />{/if}
        </div>
      </Surface>
    {/if}

    {#if cutoff}
      <StatCard value={cutoff.value} unit={cutoff.value ? 'kHz' : undefined} label={cutoff.label} wrap data-test="cutoff">
        <Spectrum spectrum={current} height={64} loading={specLoading && !current} error={specError} cutoffLabel={false}
          away={awayWords} />
      </StatCard>
    {/if}

    {#if hasFile && !track.upgrade}
      <Surface kind="card" label="Current file" data-test="current-file">
        {#snippet header()}
          <Button variant="link" size="sm" disabled={!!offline} title={offline} onclick={() => onversions(track)}
            data-test="wrong-song">Wrong song?</Button>
        {/snippet}
        {#if !cutoff}
          <Spectrum spectrum={current} height={64} loading={specLoading && !current} error={specError} away={awayWords} />
        {/if}
        {#if act.listen}
          <MiniPlayer url={track.audio_url} title={artistTitle(track.artist, track.title)} track_id={track.track_id}
            envelope={envelope(current)} length_s={track.duration_s} start={onlisten} />
        {/if}
        {#if track.format_line || track.source_full || track.source_url || qobuz}
          <div class="facts">
            {#if track.format_line}<KeyValue keyWidth={76} k="Format" v={track.format_line} />{/if}
            {#if track.source_full || track.source_url}
              <KeyValue keyWidth={76} k="Source">
                {#if track.source_url}<ExternalLink href={track.source_url} label={track.source_full ?? track.source_url} />
                {:else}{track.source_full}{/if}
              </KeyValue>
            {/if}
            {#if qobuz}<KeyValue keyWidth={76} k="Qobuz" v={qobuz} />{/if}
          </div>
        {/if}
      </Surface>
    {/if}

    {#if act.buy || act.dropZone}
      <Surface kind="card" label="Get a lossless file" data-test="get-better">
        {#if act.buy && track.free_downloads.length}
          <div class="frees" data-test="free-downloads">
            {#each track.free_downloads as f (f.url)}
              <div class="free">
                <div class="fline"><Badge tone="accent" text="FREE" /><ExternalLink href={f.url}
                    label={f.direct ? 'Download on SoundCloud' : f.host} /></div>
                <Hint text="{f.title}{f.uploader ? ` · from ${f.uploader}` : ''}" />
                <Hint text={freeHint([f])} />
              </div>
            {/each}
          </div>
        {/if}
        {#if act.buy}
          <div class="buy">
            <span class="label">{track.free_downloads.length ? 'or buy' : 'Buy'}</span>
            <ExternalLink href={track.buy_links.beatport} label="Beatport" />
            <ExternalLink href={track.buy_links.bandcamp} label="Bandcamp" />
          </div>
        {/if}
        {#if act.dropZone}<BoughtFile {track} />{/if}
      </Surface>
    {/if}
  </div>
{/snippet}

{#snippet foot()}
  {#if (act.main === 'swap' || act.main === 'add_new') && track.upgrade}
    <WriteButton variant="filled" wide busy={busy === way} disabled={busy !== null && busy !== way}
      onclick={() => upgrade(way)} data-test="upgrade-replace" data-mode={way}>{replaceLabel(track.upgrade)}</WriteButton>
    <WriteButton wide busy={busy === 'discard'} disabled={busy !== null && busy !== 'discard'}
      onclick={() => upgrade('discard')} title="Deletes the new version; it isn't offered again"
      data-test="upgrade-discard">Discard the new version</WriteButton>
    <div class="centered"><Hint text="You can undo a replace until you press Done" /></div>
  {:else if act.main === 'rekordbox'}
    <WriteButton variant="filled" wide busy={busy === 'rekordbox'} disabled={busy === 'undo'} onclick={checked}
      data-test="rekordbox-done">Done, checked in rekordbox</WriteButton>
    {#if item?.can_undo}
      <WriteButton wide busy={busy === 'undo'} disabled={busy === 'rekordbox'} onclick={undoUpgrade}
        title="Puts your old file back; the new version waits again" data-test="upgrade-undo">
        <svg class="undo" viewBox="0 0 14 14" aria-hidden="true" fill="none" stroke="currentColor" stroke-width="1.5"
          stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 3L2 5.5 4.5 8" /><path d="M2.3 5.5h6.2a3.2 3.2 0 010 6.4H6" /></svg>
        Undo the replace</WriteButton>
      {#if undoProblem}<Hint text={undoProblem} tone="problem" wrap data-test="undo-problem" />{/if}
    {/if}
  {:else if act.main === 'find'}
    <Button variant="filled" wide disabled={!!offline} title={offline} onclick={() => onversions(track)}
      data-test="wrong-song">Find a version</Button>
  {:else if act.main === 'finder'}
    <Button variant="filled" wide onclick={finder} data-test="show-in-finder">Show in Finder</Button>
  {/if}
{/snippet}

<Panel {head} foot={act.main ? foot : undefined} />

<style>
  .details { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  /* the badge and its words (no "from …": the Source row in Current file says it, with its link). When both don't fit
     in the column, the words go under the badge whole, never cut: the badge is up to 130 px wide */
  .state { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-1) var(--s-2); min-width: 0; }
  .words { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted);
    font-size: var(--fs-small); }
  .facts { display: flex; flex-direction: column; }
  .frees { display: flex; flex-direction: column; gap: var(--s-3); }
  .free { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .fline { display: flex; align-items: center; gap: var(--s-2); }
  .buy { display: flex; align-items: baseline; gap: var(--s-3); flex-wrap: wrap; font-size: var(--fs-small); }
  .label { color: var(--text-label); }
  .undo { width: 14px; height: 14px; flex-shrink: 0; }
  .centered :global(.hint) { text-align: center; }
</style>
