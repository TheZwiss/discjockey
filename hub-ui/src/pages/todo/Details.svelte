<script lang="ts">
  // The selected to-do in the panel (spec §5.3, design system mockup design-system/todo.html), as a Panel: the head
  // holds the track card (cover, name, quality, Hide at the title's end for every kind), what this to-do needs (the
  // rekordbox check's cards, the Other note, the upgrade decision, or what is still being looked for), the cutoff as
  // a number over the spectrum, the current file (player, facts, Wrong song?; not for an upgrade decision, whose Now
  // column says it) and "Get a lossless file" (the artist's free download, buy links, the drop zone). The body scrolls
  // when it is long (Panel). The foot holds the to-do's own action as the screen's one filled button
  // (actionsFor().main): Replace with lossless (the "In rekordbox" pick: Same track = swap, New track = add_new),
  // Done, checked in rekordbox, Find a version, Show in Finder; a lossy file has none in the app (it is bought and
  // dropped), so its foot stays empty. The upgrade decision and the rekordbox check are the shared ones
  // (lib/decisions: UpgradeCards + UpgradeFoot, CheckCards + CheckFoot, one UpgradeFlow), as in the Library's details.
  import { untrack } from 'svelte';
  import type { Spectrum as Spec, TodoItem, TrackDetail } from '$lib/bridge/types';
  import { api, runJob } from '$lib/bridge/client';
  import { networkReadsAllowed } from '$lib/stores/hub';
  import { onEvent } from '$lib/bridge/events';
  import { toasts } from '$lib/stores/toasts';
  import { NOT_WHILE_SYNC, sourceHowWords } from '$lib/copy';
  import { artistTitle, fileAway, fileAwayWords, qualityWords } from '$lib/format';
  import {
    Badge, Button, ExternalLink, Hint, KeyValue, MiniPlayer, NoteCard, QualityBadge, Spectrum, StatCard, Surface,
    TrackHead, WriteButton, envelope,
  } from '$lib/components';
  import { CheckCards, CheckFoot, UpgradeCards, UpgradeFlow, UpgradeFoot } from '$lib/decisions';
  import { Panel } from '$lib/frames';
  import { actionsFor, cutoffStat, dropDecision, freeHint, qobuzText } from './todoModel';
  import BoughtFile from './BoughtFile.svelte';

  let { track, item, onhidden, onversions, onlisten, onacted }: {
    track: TrackDetail; item: TodoItem | null;
    /** ▶ in the player: start the to-do list (its rows with a file, in the order shown) from this track */
    onlisten?: () => void;
    /** a decision's job starts here (Replace, Discard, Done, Undo): the page keeps this item in the list and selected */
    onacted?: () => void;
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

  // the "In rekordbox" pick, the running action and an undo's refusal; a new track starts over
  const flow = new UpgradeFlow({ onact: () => onacted?.() });
  $effect(() => flow.follow(track.track_id));
  const way = $derived(flow.way(!!act.upgrade?.swap));

  async function hide() {
    flow.busy = 'hide';
    const r = await runJob(api.hide(track.track_id, !track.hidden));
    flow.busy = null;
    if (r.ok && act.hide === 'hide') onhidden();
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
    <WriteButton variant="link" muted size="sm" busy={flow.busy === 'hide'} onclick={hide} data-test="hide">
      {act.hide === 'hide' ? 'Hide' : 'Unhide'}</WriteButton>
  {/if}
{/snippet}

{#snippet head()}
  <div class="details" data-test="details" data-track={track.track_id}>
    <Surface kind="card">
      <TrackHead {track} place={track.folder} action={act.hide ? hideLink : undefined} link={track.track_link}
        word={qualityWords(track.quality, track.quality_label)}>
        {#snippet badge()}<span data-test="details-state"><QualityBadge quality={track.quality} label={track.quality_label}
          upgrade={track.upgrade_ready} titled={false} /></span>{/snippet}
      </TrackHead>
    </Surface>

    {#if act.rekordboxDone && item}<CheckCards {item} />{/if}
    {#if item?.group === 'other'}
      <NoteCard data-test="other">{item.detail}</NoteCard>
    {/if}

    {#if track.upgrade}
      <UpgradeCards {track} {current} upgrade={upSpec} loading={specLoading} swap={!!act.upgrade?.swap} {way}
        onway={(w) => (flow.picked = w)} busy={flow.busy !== null} />
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
              <!-- what the file was made from, and how it was found under it (sources round problems 4, 6), as in Library -->
              <KeyValue keyWidth={76} k="Source" sub={sourceHowWords(track.source_how)}>
                {#if track.source_url}<ExternalLink href={track.source_url} label={track.source_full ?? track.source_url} />
                {:else}{track.source_full}{/if}{#if track.source_format_line}{` · ${track.source_format_line}`}{/if}
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
    <UpgradeFoot track_id={track.track_id} upgrade={track.upgrade} {way} {flow} />
  {:else if act.main === 'rekordbox' && item}
    <CheckFoot {item} {flow} />
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
  .facts { display: flex; flex-direction: column; }
  .frees { display: flex; flex-direction: column; gap: var(--s-3); }
  .free { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
  .fline { display: flex; align-items: center; gap: var(--s-2); }
  .buy { display: flex; align-items: baseline; gap: var(--s-3); flex-wrap: wrap; font-size: var(--fs-small); }
  .label { color: var(--text-label); }
</style>
