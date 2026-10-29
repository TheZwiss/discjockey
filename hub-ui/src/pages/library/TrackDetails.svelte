<script lang="ts">
  // The selected track in the panel (design system mockup design-system/library.html), as a Panel with the same
  // cards in the same order as To-do's: the track card (cover, name, "Artist · length · place", quality and its
  // words), then the upgrade box when one is ready (its Now spectrum and compare player stand in for the file's
  // own), else the cutoff as a number over the spectrum, then Current file (the player, Format, Source, Added, File)
  // with Show in Finder as its link (not for a file that isn't there: the pictures say why). The foot holds the one filled button: Swap the files when the upgrade matches;
  // Open in to-do (outline) for any other track on the to-do list; nothing for a lossless one. The head's place line is
  // the file's folder (or "Not in a playlist"); the playlists it is in are the Playlists row, by name.
  import type { ComponentProps } from 'svelte';
  import {
    Button, EmptyState, ExternalLink, KeyValue, MiddleText, MiniPlayer, ProblemCard, QualityBadge, Skeleton, Spectrum, StatCard,
    Surface, TrackHead, UpgradeCard, WriteButton, envelope,
  } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { artistTitle, cutoffStat, dateShort, fileAwayWords, qualityWords } from '$lib/format';
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
  // every playlist the song is in, by name, whole (the head only says where the file sits); nothing when it is in none
  // or the playlists weren't read yet
  const playlists = $derived(t?.in_playlists && t.playlists?.length ? t.playlists.join(', ') : null);
  const hasFile = $derived(!!t && t.status !== 'missing');
  // the file isn't there (drive away, folder or file not found): the picture says why, the player stays off, there is
  // nothing to show in Finder
  const away = $derived(t ? fileAwayWords(t) : null);
</script>

{#snippet waiting()}<Skeleton lines={6} height={18} gap={10} />{/snippet}
{#snippet isGone()}<div data-test="track-gone"><EmptyState title="This track isn't here any more." /></div>{/snippet}
{#snippet failed()}{#if error}<ProblemCard kind={error.kind} message={error.message} compact {onretry} />{/if}{/snippet}

{#snippet head()}
  {#if t}
    <div class="details" class:fading={loading} data-test="track-details" data-track={t.track_id}>
      <Surface kind="card">
        <TrackHead track={t} place={placeLine(t.folder, t.in_playlists)}>
          <span class="state" class:stack={!t.sound_checked}>
            <QualityBadge quality={t.quality} label={t.quality_label} upgrade={t.upgrade_ready}
              checked={t.sound_checked} />
            <span class="words">{qualityWords(t.quality, t.quality_label, t.sound_checked)}</span>
          </span>
        </TrackHead>
      </Surface>

      {#if t.upgrade}
        <UpgradeCard upgrade={t.upgrade} currentUrl={t.audio_url} current={spectrum} next={upgradeSpectrum}
          loading={spectrumLoading} swap={action === 'swap'} />
      {:else if cutoff}
        <StatCard value={cutoff.value} unit={cutoff.value ? 'kHz' : undefined} label={cutoff.label} wrap data-test="cutoff">
          <Spectrum {spectrum} height={64} loading={spectrumLoading && !spectrum} error={spectrumError}
            noFile={!t.audio_url} {away} cutoffLabel={false} />
        </StatCard>
      {/if}

      {#if hasFile}
        <Surface kind="card" label="Current file" data-test="current-file">
          {#snippet header()}
            {#if !away}<Button variant="link" size="sm" onclick={onfinder} data-test="details-finder">Show in Finder</Button>{/if}
          {/snippet}
          {#if !cutoff && !t.upgrade}
            <div data-test="spectrum"><Spectrum {spectrum} height={64} loading={spectrumLoading && !spectrum}
              error={spectrumError} noFile={!t.audio_url} {away} /></div>
          {/if}
          {#if !t.upgrade}
            <MiniPlayer url={t.audio_url} title={artistTitle(t.artist, t.title)} track_id={t.track_id}
              envelope={envelope(spectrum)} length_s={t.duration_s} start={onlisten} />
          {/if}
          <div class="facts">
            {#if t.format_line}<KeyValue keyWidth={76} k="Format" v={t.format_line} />{/if}
            <KeyValue keyWidth={76} k="Source">
              {#if t.source_url}<ExternalLink href={t.source_url} label={t.source_full ?? shortUrl(t.source_url)} />
              {:else}{t.source_full ?? t.source_name ?? '–'}{/if}
            </KeyValue>
            {#if playlists}<KeyValue keyWidth={76} k="Playlists" v={playlists} />{/if}
            <KeyValue keyWidth={76} k="Added" v={dateShort(t.added) || '–'} />
            <KeyValue keyWidth={76} k="File">{#if fileName(t.path)}<MiddleText text={fileName(t.path)} />{:else}–{/if}</KeyValue>
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
  /* the badge and its words ("fake lossless"; no "from …": the Source row in Current file says it, with its link).
     When both don't fit in the column, the words go under the badge whole, never cut: the badge is up to 130 px wide */
  .state { display: flex; flex-wrap: wrap; align-items: center; gap: var(--s-1) var(--s-2); min-width: 0; }
  .state.stack .words { flex-basis: 100%; }
  .words { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; color: var(--text-muted);
    font-size: var(--fs-small); }
  .facts { display: flex; flex-direction: column; }
</style>
