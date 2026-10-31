<script lang="ts">
  // The selected track in the panel (design system mockup design-system/library.html), as a Panel with the same
  // cards in the same order as To-do's: the track card (cover, name, "Artist · length · place", quality and its
  // words), then the decision the track waits for (`decision`, decisionFor), the very panel To-do shows and decided
  // here the same way (lib/decisions, mockup todo-decisions): the rekordbox check a replace left (its steps, what was
  // replaced; Done and Undo the replace in the foot), "Which file stays?" for a duplicate group one of its files is in
  // (Keep … in the foot), or the upgrade (Now/New and the compare player stand in for the file's own spectrum and
  // player, "In rekordbox"; Replace with lossless and Discard in the foot). Without an upgrade the cutoff follows as a
  // number over the spectrum, then Current file (the player, Format, Source, Added, File) with Show in Finder as its
  // link (not for a file that isn't there: the pictures say why). The foot holds the decision's buttons (its one
  // filled button), else Open in to-do (outline) for any other track on the to-do list, else nothing. The head's place line
  // says where the file sits, in the Folder and Subfolder columns' words ("in Hardtechno › 2019", plan library stage 5
  // D11); the playlists it is in are the Playlists row, by name ("–" for none).
  // A playlist song without a file (`pending`, the selected row: a song only just read isn't a track `track()` knows)
  // has no file to show: its head (the dashed cover, "Artist · length · not downloaded yet", Waiting or NOT FOUND as in
  // its row) and one NoteCard that says what happens next; a song not found also has Open in to-do, where the ways to
  // get it are (`next`: when Qobuz looks again, from its details when the engine has them).
  import type { ComponentProps } from 'svelte';
  import {
    Badge, Button, EmptyState, ExternalLink, KeyValue, MiddleText, MiniPlayer, NoteCard, ProblemCard, QualityBadge, Skeleton,
    Spectrum, StatCard, Surface, TrackHead, envelope,
  } from '$lib/components';
  import {
    CheckCards, CheckFoot, DuplicateChoice, DuplicateFlow, DuplicateFoot, UpgradeCards, UpgradeFlow, UpgradeFoot, canSwap,
    type Decision,
  } from '$lib/decisions';
  import { Panel } from '$lib/frames';
  import { artistTitle, cutoffStat, dateShort, fileAwayWords, qualityWords } from '$lib/format';
  import type { Fail, LibraryRow, TrackDetail } from '$lib/bridge/types';
  import {
    NOT_FOUND_WORD, NO_FILE_PLACE, fileName, waitWords, noFileNote, footAction, placeLine, playlistsLine, shortUrl,
  } from './libraryModel';

  type Spec = ComponentProps<typeof Spectrum>['spectrum'];
  let { detail, decision = null, playSource, pending = null, loading = false, gone = false, error = null, spectrum = null,
    spectrumLoading = false, spectrumError = null, upgradeSpectrum = null, onretry, onfinder, ontodo, onlisten, onacted }: {
    detail: TrackDetail | null;
    /** what `detail` waits for (decisionFor over the to-do list, fetched with it) */
    decision?: Decision;
    /** the foot's link back while a duplicate's file plays: this track in this view */
    playSource?: { label: string; href: string };
    /** the selected row when it is a playlist song without a file; `next`: its details' `next_qobuz_check` (not found) */
    pending?: { row: LibraryRow; next: string | null; off: boolean } | null;
    loading?: boolean; gone?: boolean; error?: Fail | null; spectrum?: Spec;
    spectrumLoading?: boolean; spectrumError?: string | null; upgradeSpectrum?: Spec;
    onretry: () => void; onfinder: () => void; ontodo: () => void;
    /** ▶ in the player: start the folder from this track (the page's queue) */
    onlisten?: () => void;
    /** a decision's job starts here: the page keeps this track on its table and selected (its Hold); `keep`: a
     *  duplicate's Keep, the paths of the files that stay */
    onacted?: (keep: string[] | null) => void;
  } = $props();

  const t = $derived(detail);
  // the upgrade decision's Now/New and compare player stand in for the cutoff and the file's own spectrum and player
  const upgrading = $derived(decision?.kind === 'upgrade' && !!t?.upgrade);
  const cutoff = $derived(t && !upgrading ? cutoffStat(t) : null);
  const action = $derived(t ? footAction(t, decision) : null);
  // the decisions' state (the "In rekordbox" pick, the file that stays, the running job), as in To-do's panel
  const upFlow = new UpgradeFlow({ onact: () => onacted?.(null) });
  const dupFlow = new DuplicateFlow({ onact: (keep) => onacted?.(keep) });
  $effect(() => { if (t) upFlow.follow(t.track_id); });
  const swap = $derived(canSwap(t?.upgrade));
  const way = $derived(upFlow.way(swap));
  const check = $derived(decision?.kind === 'check' ? decision.item : null);
  const dup = $derived(decision?.kind === 'duplicate' ? decision.item : null);
  // every playlist the song is in, by name, whole (the head only says where the file sits); nothing when it is in none
  // or the playlists weren't read yet
  const playlists = $derived(t ? playlistsLine(t) : null);
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
        <TrackHead track={t} place={placeLine(t.place)}>
          <span class="state" class:stack={!t.sound_checked}>
            <QualityBadge quality={t.quality} label={t.quality_label} upgrade={t.upgrade_ready}
              checked={t.sound_checked} />
            <span class="words">{qualityWords(t.quality, t.quality_label, t.sound_checked)}</span>
          </span>
        </TrackHead>
      </Surface>

      {#if check}<CheckCards item={check} />{/if}
      {#if dup}<DuplicateChoice item={dup} flow={dupFlow} source={playSource} />{/if}

      {#if upgrading && t.upgrade}
        <UpgradeCards track={t} current={spectrum ?? null} upgrade={upgradeSpectrum ?? null} loading={spectrumLoading} {swap}
          {way} onway={(w) => (upFlow.picked = w)} busy={upFlow.busy !== null} />
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
          {#if !cutoff && !upgrading}
            <div data-test="spectrum"><Spectrum {spectrum} height={64} loading={spectrumLoading && !spectrum}
              error={spectrumError} noFile={!t.audio_url} {away} /></div>
          {/if}
          {#if !upgrading}
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

{#snippet noFile()}
  {#if pending}
    {@const r = pending.row}
    <div class="details" data-test="track-details" data-track={r.track_id} data-wait={r.wait}>
      <Surface kind="card">
        <TrackHead track={r} place={NO_FILE_PLACE} empty>
          {#if r.wait === 'not_found'}<Badge tone="missing" text={NOT_FOUND_WORD} />
          {:else}<Badge tone="quiet" text={waitWords(pending.off).word} />{/if}
        </TrackHead>
      </Surface>
      <NoteCard data-test="no-file-note">{noFileNote(r.wait, pending.next, pending.off, r.hidden)}</NoteCard>
    </div>
  {/if}
{/snippet}
{#snippet noFileFoot()}<Button wide onclick={ontodo} data-test="details-todo">Open in to-do</Button>{/snippet}

{#snippet foot()}
  {#if action === 'upgrade' && t?.upgrade}
    <UpgradeFoot track_id={t.track_id} upgrade={t.upgrade} {way} flow={upFlow} />
  {:else if action === 'check' && check}
    <CheckFoot item={check} flow={upFlow} />
  {:else if action === 'duplicate' && dup}
    <DuplicateFoot item={dup} flow={dupFlow} />
  {:else if action === 'todo'}
    <Button wide onclick={ontodo} data-test="details-todo">Open in to-do</Button>
  {/if}
{/snippet}

{#if pending}
  <Panel head={noFile} foot={pending.row.wait === 'not_found' && !pending.row.hidden ? noFileFoot : undefined} />
{:else if gone}
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
