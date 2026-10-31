<script lang="ts">
  // The live card: one card, its state from cardState() (preparing, working, downloading, converting, analysed,
  // pause, stopping, finished, failed). It is a `Surface` card (design system §8 Running); a failed card is the
  // ProblemCard alone, itself a problem-tone card (a card inside a card is a container in a container, §4).
  import { Badge, Cover, ExternalLink, ProblemCard, ProgressBar, QualityBadge, Ring, Spectrum, Spinner, Surface }
    from '$lib/components';
  import { api } from '$lib/bridge/client';
  import type { Action } from '$lib/bridge/events';
  import type { Spectrum as SpectrumData } from '$lib/bridge/types';
  import { artistTitle, duration, noteParts } from '$lib/format';
  import { sourceName, stepIndex, stepsFor, verdict, type Card } from './cardState';
  import { stripCover } from './results';
  import StepBar from './StepBar.svelte';

  // `covers`: cover links by track id (the plan's, file artwork included), for a track whose service gave no picture
  let { card, covers = new Map() }: { card: Card; covers?: Map<string, string> } = $props();

  const who = (a: Action) => artistTitle(a.track.artists.join(', '), a.track.title);
  const kicker = (a: Action, source: string | null) => ['Now', a.folder, sourceName(source)].filter(Boolean).join(' · ');

  // one spectrum fetch per finished track that has a file
  let spec = $state<{ track_id: string; data: SpectrumData | null; error: string | null } | null>(null);
  $effect(() => {
    if (card.kind !== 'analysed') return;
    const id = card.result.track_id;
    if (!id || !verdict(card.result).hasFile || spec?.track_id === id) return;
    spec = { track_id: id, data: null, error: null };
    void api.spectrum(id, 'current').then((r) => {
      if (spec?.track_id !== id) return;
      spec = r.ok ? { track_id: id, data: r.spectrum, error: null } : { track_id: id, data: null, error: r.message };
    });
  });
  const v = $derived(card.kind === 'analysed' ? verdict(card.result) : null);
  const dlTail = $derived(card.kind !== 'downloading' ? '' : [card.percent !== null ? `${card.percent} %` : null,
    card.secondsLeft !== null && card.totalMB !== null ? `${card.secondsLeft} s left` : null]
    .filter(Boolean).map((x) => ` · ${x}`).join(''));
  const convText = $derived(card.kind !== 'converting' ? '' : `converting to AIFF · ${duration(card.done_s)}${
    card.total_s !== null ? ` of ${duration(card.total_s)}` : ''}`);
  const fill = $derived(card.kind === 'downloading' ? (card.percent ?? 0) / 100
    : card.kind === 'converting' && card.total_s ? Math.min(1, card.done_s / card.total_s) : null);
</script>

{#if card.kind === 'failed'}
  <div data-test="sync-card" data-state={card.kind}><ProblemCard kind={card.problem} message={card.message} service={card.service} sync /></div>
{:else}
<Surface kind="card" data-test="sync-card" data-state={card.kind}>
  {#if card.kind === 'preparing'}
    <div class="row">
      <Spinner />
      <div class="text">
        <div class="kicker">Getting ready</div>
        <div class="detail">{card.text}</div>
      </div>
    </div>
  {:else if card.kind === 'working' || card.kind === 'downloading' || card.kind === 'converting'}
    <div class="row">
      <Cover url={stripCover(card.action.track.image_url, card.action.track_id, covers)} seed={card.action.track_id} size={120} />
      <div class="text">
        <div class="kicker">{kicker(card.action, card.source)}</div>
        <div class="title">{who(card.action)}</div>
        {#if card.steps.length}<StepBar steps={card.steps} current={stepIndex(card)} {fill} />{/if}
        <div class="detail" data-test="card-detail">
          {#if card.kind === 'downloading'}
            Downloading · <b>{card.totalMB !== null ? `${card.doneMB} of ${card.totalMB} MB` : `${card.doneMB} MB`}</b>{dlTail}
          {:else if card.kind === 'converting'}
            {#if card.lengthLine}<span class:differs={card.lengthOk === false}>{card.lengthLine}</span>{' · '}{/if}{convText}
          {:else}
            {card.detail}
          {/if}
        </div>
        {#if card.kind === 'downloading' || card.kind === 'converting'}
          <div class="progress"><ProgressBar value={fill} pace="live" label={card.kind === 'downloading' ? 'Download' : 'Conversion'} /></div>
        {/if}
      </div>
    </div>
  {:else if card.kind === 'analysed' && v}
    <div class="row">
      <Cover url={stripCover(card.action.track.image_url, card.action.track_id, covers)} seed={card.action.track_id} size={120} />
      <div class="text">
        <div class="kicker">Done · {card.result.folder}</div>
        <div class="title">{artistTitle(card.result.artist, card.result.title)}</div>
        {#if v.hasFile && stepsFor(card.action).length}<StepBar steps={stepsFor(card.action)} current={-1} />{/if}
        {#if v.hasFile}
          <div class="spec">
            <Spectrum spectrum={spec?.data ?? null} height={56} loading={!spec?.data && !spec?.error}
              error={spec?.error ?? null} cutoffLabel={false} />
          </div>
        {/if}
        <div class="verdict" data-test="card-verdict">
          {#if v.quality}<QualityBadge quality={v.quality} label={v.label} upgrade={card.result.section === 'upgrade_ready'} />
          {:else}<Badge tone={v.tone} text={v.label} />{/if}
          {#if v.line}<span class="detail">{v.line}</span>{/if}
        </div>
        {#if !v.hasFile && card.result.note && card.result.section !== 'moved'}
          <div class="note">
            {#each noteParts(card.result.note) as part, i (i)}
              {#if 'href' in part}<ExternalLink href={part.href}>{part.label}</ExternalLink>{:else}{part.text}{/if}
            {/each}
          </div>
        {/if}
      </div>
    </div>
  {:else if card.kind === 'pause'}
    <div class="row">
      <!-- the cover stays where it was while downloading, darkened, with the countdown on it -->
      <div class="paused" data-test="pause-cover">
        <Cover url={stripCover(card.nextUp.track.image_url, card.nextUp.track_id, covers)} seed={card.nextUp.track_id} size={120} />
        <div class="over"><Ring value={card.remaining_s} max={card.total_s} size={88} countdown /></div>
      </div>
      <div class="text">
        <div class="kicker">{card.waiting === 'break' ? 'Longer break' : 'Protection pause'} · next up</div>
        <div class="title">{who(card.nextUp)}</div>
        <div class="detail muted" data-test="card-detail">
          {[card.nextUp.folder, card.source ? `from ${sourceName(card.source)}` : null,
            card.afterThat ? `after that ${card.afterThat} more` : 'last one'].filter(Boolean).join(' · ')}
        </div>
      </div>
    </div>
  {:else if card.kind === 'stopping'}
    <div class="row">
      <Spinner />
      <!-- the page title says "Stopping…" (§11: a state is said once); the card says what happens to the track -->
      <div class="text"><div class="kicker">Current track</div>
        <div class="detail">Finished or cleanly discarded, then the sync stops.</div></div>
    </div>
  {:else if card.kind === 'finished'}
    <div class="row"><div class="text"><div class="title">{card.exit_code === 130 ? 'Sync stopped' : 'Sync finished'}</div></div></div>
  {/if}
</Surface>
{/if}

<style>
  .row { display: flex; gap: var(--s-4); align-items: center; }
  .text { flex: 1; min-width: 0; }
  .kicker { font-size: var(--fs-label); color: var(--text-label); text-transform: uppercase;
    letter-spacing: var(--ls-label); }
  .title { font-size: var(--fs-title); font-weight: var(--fw-bold); color: var(--text-strong); margin-top: 2px;
    overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .detail { margin-top: var(--s-2); color: var(--text-muted); font-size: var(--fs-body); }
  .detail b { color: var(--text-strong); font-weight: var(--fw-semi); }
  .detail.muted { color: var(--text-dim); }
  .differs { color: var(--q-good); }
  .progress { margin-top: var(--s-2); }
  .spec { margin-top: var(--s-2); }
  .verdict { display: flex; align-items: center; gap: var(--s-2); margin-top: var(--s-2); }
  .verdict .detail { margin-top: 0; }
  .note { margin-top: var(--s-2); color: var(--text-dim); font-size: var(--fs-small); }
  .paused { position: relative; flex-shrink: 0; line-height: 0; }
  .paused :global(.cover) { filter: brightness(var(--dim-cover)); }
  .paused :global(.cover img) { filter: blur(2px); transform: scale(1.04); }   /* scaled: no soft edge from the blur */
  .over { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; }
  .over :global(.track) { stroke: var(--ring-on-cover); }
</style>
