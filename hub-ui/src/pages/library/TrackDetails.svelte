<script lang="ts">
  // The selected track in the panel (design system mockup design-system/library.html), as a Panel with the same
  // cards in the same order as To-do's: the track card (cover, name, "Artist · length · place", quality and its
  // words), then the upgrade box when one is ready (its Now spectrum and compare player stand in for the file's
  // own), else the cutoff as a number over the spectrum, then Current file (the player, Format, Source, Added, File)
  // with Show in Finder as its link. The foot holds the one filled button: Swap the files when the upgrade matches;
  // Open in to-do (outline) for any other track on the to-do list; nothing for a lossless one.
  import type { ComponentProps } from 'svelte';
  import {
    Button, EmptyState, ExternalLink, KeyValue, MiniPlayer, ProblemCard, QualityBadge, Skeleton, Spectrum, StatCard,
    Surface, TrackHead, UpgradeCard, WriteButton, envelope,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { artistTitle, cutoffStat, dateShort, qualityWords } from '$lib/format';
  import type { Fail, TrackDetail } from '$lib/bridge/types';
  import { fileName, footAction, placeLine, shortUrl } from './libraryModel';

  type Spec = ComponentProps<typeof Spectrum>['spectrum'];
  let { detail, loading = false, gone = false, error = null, spectrum = null, spectrumLoading = false,
    spectrumError = null, upgradeSpectrum = null, swapping = false, onretry, onfinder, ontodo, onswap, onlisten }: {
    detail: TrackDetail | null; loading?: boolean; gone?: boolean; error?: Fail | null; spectrum?: Spec;
    spectrumLoading?: boolean; spectrumError?: string | null; upgradeSpectrum?: Spec; swapping?: boolean;
    onretry: () => void; onfinder: () => void; ontodo: () => void; onswap: () => void;
    /** ▶ in the player: start the folder from this track (the page's queue) */
    onlisten?: () => void;
  } = $props();

  const t = $derived(detail);
  const cutoff = $derived(t && !t.upgrade ? cutoffStat(t) : null);
  const action = $derived(t ? footAction(t) : null);
  const hasFile = $derived(!!t && t.status !== 'missing');
</script>

{#snippet waiting()}<Skeleton lines={6} height={18} gap={10} />{/snippet}
{#snippet isGone()}<div data-test="track-gone"><EmptyState title="This track isn't here any more." /></div>{/snippet}
{#snippet failed()}{#if error}<ProblemCard kind={error.kind} message={error.message} compact {onretry} />{/if}{/snippet}

{#snippet head()}
  {#if t}
    <div class="details" class:fading={loading} data-test="track-details" data-track={t.track_id}>
      <Surface kind="card">
        <TrackHead track={t} place={placeLine(t.folder, t.in_playlist_count, t.in_playlists)}>
          <span class="state" class:stack={!t.sound_checked}>
            <QualityBadge quality={t.quality} label={t.quality_label} upgrade={t.upgrade_ready}
              checked={t.sound_checked} />
            <span class="words">{qualityWords(t.quality, t.quality_label, t.sound_checked)}{t.sound_checked && t.source_full ? ` · from ${t.source_full}` : ''}</span>
          </span>
        </TrackHead>
      </Surface>

      {#if t.upgrade}
        <UpgradeCard upgrade={t.upgrade} currentUrl={t.audio_url} current={spectrum} next={upgradeSpectrum}
          loading={spectrumLoading} swap={action === 'swap'} />
      {:else if cutoff}
        <StatCard value={cutoff.value} unit={cutoff.value ? 'kHz' : undefined} label={cutoff.label} data-test="cutoff">
          <Spectrum {spectrum} height={64} loading={spectrumLoading && !spectrum} error={spectrumError}
            noFile={!t.audio_url} cutoffLabel={false} />
        </StatCard>
      {/if}

      {#if hasFile}
        <Surface kind="card" label="Current file" data-test="current-file">
          {#snippet header()}
            <Button variant="link" size="sm" onclick={onfinder} data-test="details-finder">Show in Finder</Button>
          {/snippet}
          {#if !cutoff && !t.upgrade}
            <div data-test="spectrum"><Spectrum {spectrum} height={64} loading={spectrumLoading && !spectrum}
              error={spectrumError} noFile={!t.audio_url} /></div>
          {/if}
          {#if !t.upgrade}
            <MiniPlayer url={t.audio_url} title={artistTitle(t.artist, t.title)} track_id={t.track_id}
              envelope={envelope(spectrum)} length_s={t.duration_s} start={onlisten} />
          {/if}
          <div class="facts">
            {#if t.format_line}<KeyValue keyWidth={64} k="Format" v={t.format_line} />{/if}
            <KeyValue keyWidth={64} k="Source">
              {#if t.source_url}<ExternalLink href={t.source_url} label={t.source_full ?? shortUrl(t.source_url)} />
              {:else}{t.source_full ?? t.source_name ?? '–'}{/if}
            </KeyValue>
            <KeyValue keyWidth={64} k="Added" v={dateShort(t.added) || '–'} />
            <KeyValue keyWidth={64} k="File"><span class="file" title={t.path ?? undefined}>{fileName(t.path) || '–'}</span></KeyValue>
          </div>
        </Surface>
      {/if}
    </div>
  {/if}
{/snippet}

{#snippet foot()}
  {#if action === 'swap'}
    <WriteButton variant="filled" wide busy={swapping} onclick={onswap} data-test="swap">Swap the files</WriteButton>
  {:else if action === 'todo'}
    <Button wide onclick={ontodo} data-test="details-todo">Open in to-do</Button>
  {/if}
{/snippet}

{#if gone}
  <Panel head={isGone} />
{:else if error && !t}
  <Panel head={failed} />
{:else if !t}
  <Panel head={waiting} />
{:else}
  <Panel {head} foot={action ? foot : undefined} />
{/if}

<style>
  .details { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; transition: opacity var(--t-state) var(--ease); }
  .fading { opacity: .7; }
  .state { display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
  /* "Not checked" and its words ("sound not checked yet", no "from …": the Source row says it) don't fit in one line: the words go
     under the badge, whole */
  .state.stack { flex-wrap: wrap; row-gap: var(--s-1); }
  .state.stack .words { flex-basis: 100%; }
  .words { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted);
    font-size: var(--fs-small); }
  .facts { display: flex; flex-direction: column; }
  .file { display: block; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
    user-select: text; -webkit-user-select: text; }
</style>
