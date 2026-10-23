<script lang="ts">
  // Where the music comes from, best first (spec settings-setup §4): four rungs on a vertical chain, each lit in its
  // quality colour when the download uses it, greyed with an outlined node when it doesn't; the chain passes an
  // unlit rung dashed (the download skips it). Rungs: Qobuz · the artist's own file · Premium streams (one chip per
  // account, either lights it) · free streams. Under the chain one Hint says what the setup means (`ladderLine`).
  // Settings shows it full width; Setup `compact` in its 372 px column, with the short sub-lines. The line may take
  // two lines where the column is narrow (the four sentences don't fit one at 372 px). `downloads={null}` is
  // loading: every rung greyed, the unknown lines and the summary as Skeletons, nothing clickable.
  // `onpick(row)`: Qobuz's name and each account chip select that row (Settings) or scroll to its card (Setup);
  // without it the names and chips are plain text. A chip that is paused or used up for today goes to Download
  // limits instead (`limitsHref`, on every page: that is where the pause is explained and lifted, plan R26). Every state is in words: the sub-lines, and each chip's
  // "YouTube Premium: signed in" (read out, and its tooltip). State changes fade (`--t-state`, colours only, so
  // reduced motion keeps them); sizes are fixed, more width only gives the sub-lines room.
  import type { DownloadsView } from '../bridge/types';
  import Badge from './Badge.svelte';
  import Hint from './Hint.svelte';
  import Skeleton from './Skeleton.svelte';
  import StatusMark from './StatusMark.svelte';
  import Surface from './Surface.svelte';
  import { link } from '../router';
  import {
    chipLabel, chipTone, ladderLine, ladderState, limitsHref, premiumWords, qobuzLit, qobuzWords, type AccountService,
  } from './ladderModel';

  type Row = 'qobuz' | 'youtube' | 'soundcloud';
  let { downloads, onpick, compact = false, test }: {
    downloads: DownloadsView | null; onpick?: (row: Row) => void; compact?: boolean; test?: string;
  } = $props();

  type Tone = 'lossless' | 'good_lossy' | 'weak';
  type Rung = { key: 'qobuz' | 'own' | 'premium' | 'free'; name: string; words: string | null; badge: string; tone: Tone; lit: boolean };

  const ladder = $derived(downloads ? ladderState(downloads) : null);
  const rungs = $derived.by((): Rung[] => {
    const l = ladder;
    return [
      { key: 'qobuz', name: 'Qobuz', words: l ? qobuzWords(l.qobuz, compact) : null, badge: 'LOSSLESS', tone: 'lossless',
        lit: !!l && qobuzLit(l.qobuz) },
      { key: 'own', name: "The artist's own file", words: compact ? 'no login needed' : 'SoundCloud download button · no login needed',
        badge: 'OFTEN LOSSLESS', tone: 'lossless', lit: !!l },
      { key: 'premium', name: 'Premium streams', words: l ? premiumWords(l, compact) : null, badge: '~256 KBPS', tone: 'good_lossy',
        lit: !!l && l.accounts },
      { key: 'free', name: 'Free streams', words: compact ? 'the last resort' : 'YouTube Music, SoundCloud, YouTube · the last resort',
        badge: '~130 KBPS', tone: 'weak', lit: !!l },
    ];
  });
  const COLOUR: Record<Tone, string> = { lossless: '--q-lossless', good_lossy: '--q-good', weak: '--q-weak' };
  const CHIPS: { service: AccountService; name: string }[] = [{ service: 'youtube', name: 'YouTube' }, { service: 'soundcloud', name: 'SoundCloud' }];
  const pickable = $derived(!!onpick && !!ladder);
</script>

<Surface kind="card" label="Where your music comes from" data-test={test}>
  {#snippet header()}<Hint text="best first" />{/snippet}
  <ol class="lad" class:compact aria-busy={!ladder}>
    {#each rungs as r, i (r.key)}
      <li class="rung" class:lit={r.lit} class:before-off={r.lit && !rungs[i + 1]?.lit}
        style="--c: var({COLOUR[r.tone]}); --c-line: var({COLOUR[r.tone]}-line)" data-rung={r.key} data-lit={r.lit}>
        <span class="node" aria-hidden="true"></span>
        {#if r.key === 'qobuz' && pickable}
          <button type="button" class="name pick" onclick={() => onpick?.('qobuz')} data-test={test && `${test}-qobuz`}>{r.name}</button>
        {:else}<span class="name">{r.name}</span>{/if}
        <span class="q"><Badge tone={r.lit ? r.tone : 'muted'} text={r.badge} /></span>
        {#if r.words !== null}<span class="words" title={r.words}>{r.words}</span>
        {:else}<span class="words wait"><Skeleton height={12} width="120px" /></span>{/if}
        {#if r.key === 'premium'}
          <span class="chips">
            {#each CHIPS as c (c.service)}
              {@const s = ladder?.[c.service] ?? 'off'}
              {@const label = ladder ? chipLabel(c.service, s) : `${c.name}: checking`}
              {@const limits = ladder ? limitsHref(c.service, s) : null}
              {#if limits}
                <a class="chip tone-{chipTone(s)}" href={limits} use:link title={label}
                  data-test={test && `${test}-${c.service}`}><StatusMark tone={chipTone(s)} /><span aria-hidden="true">{c.name}</span><span
                    class="sr-only">{label}</span></a>
              {:else if pickable}
                <button type="button" class="chip tone-{chipTone(s)}" title={label} onclick={() => onpick?.(c.service)}
                  data-test={test && `${test}-${c.service}`}><StatusMark tone={chipTone(s)} /><span aria-hidden="true">{c.name}</span><span
                    class="sr-only">{label}</span></button>
              {:else}
                <span class="chip tone-{chipTone(s)}" title={label}><StatusMark tone={chipTone(s)} /><span aria-hidden="true">{c.name}</span><span
                    class="sr-only">{label}</span></span>
              {/if}
            {/each}
          </span>
        {/if}
      </li>
    {/each}
  </ol>
  <div class="line">
    {#if ladder}<Hint text={ladderLine(ladder)} data-test={test && `${test}-line`} />
    {:else}<span class="wait-line"><Skeleton height={12} width="60%" /></span>{/if}
  </div>
</Surface>

<style>
  .lad { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  /* fixed rung height (the Premium rung grows by its chips' row only); node · words · quality badge */
  .rung { position: relative; display: grid; grid-template-columns: 20px minmax(0, 1fr) auto; column-gap: var(--s-3);
    align-items: start; min-height: 44px; padding: var(--s-1) 0; }
  .lad.compact .rung { min-height: var(--h-list-row); }
  /* the node sits on the name's first line (centre 12 px from the rung's top): lit = filled in the rung's colour
     with a faint halo, off = an outlined hole */
  .node { position: relative; justify-self: center; margin-top: 2px; width: 12px; height: 12px; border-radius: 50%;
    background: var(--c); border: var(--bw-accent) solid var(--c); z-index: 1;
    transition: background-color var(--t-state) var(--ease), border-color var(--t-state) var(--ease); }
  .node::before { content: ''; position: absolute; inset: -3px; border-radius: 50%; background: var(--c); opacity: .18;
    transition: opacity var(--t-state) var(--ease); }
  .rung:not(.lit) .node { background: var(--bg); border-color: var(--line-control-hover); }
  .rung:not(.lit) .node::before { opacity: 0; }
  /* the chain to the next rung, from under this node to just above the next: solid in the rung's colour, dashed
     grey into and out of an unlit rung */
  .rung:not(:last-child)::after { content: ''; position: absolute; left: 9px; top: 23px; bottom: -1px;
    border-left: 2px solid var(--c-line); transition: border-color var(--t-state) var(--ease); }
  .rung:not(.lit)::after, .rung.before-off::after { border-left-style: dashed; border-left-color: var(--line-control-hover); }

  /* the badge sits beside the name only, so the sub-line and the chips take the rung's full width under both */
  .node { grid-area: 1 / 1 / span 3; }
  .name { grid-area: 1 / 2; justify-self: start; }
  .q { grid-area: 1 / 3; }
  .words { grid-area: 2 / 2 / auto / span 2; justify-self: start; margin-top: 1px; }
  .chips { grid-area: 3 / 2 / auto / span 2; }
  .name, .words { max-width: 100%; white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
    transition: color var(--t-state) var(--ease); }
  .name { font-size: var(--fs-body); line-height: 16px; font-weight: var(--fw-semi); color: var(--text-strong); }
  .words { font-size: var(--fs-small); line-height: 16px; color: var(--text-muted); }
  /* off: greyed but readable (4.5:1, design language §3), the words still say why */
  .rung:not(.lit) .name { color: var(--text-muted); font-weight: var(--fw-medium); }
  .rung:not(.lit) .words { color: var(--text-label); }
  .words.wait { display: flex; align-items: center; height: 16px; width: 120px; }
  /* Qobuz's name picks its row: a text link (it dims when held, never shrinks) */
  .pick { padding: 0; text-align: left; cursor: pointer; }
  .pick:hover { color: var(--accent-text); }
  .pick:active { transform: none; opacity: var(--link-press); }
  .q { display: flex; height: 16px; align-items: center; }
  .q :global(.badge) { transition: color var(--t-state) var(--ease), border-color var(--t-state) var(--ease); }

  .chips { display: flex; gap: var(--s-2); margin: var(--s-1) 0 var(--s-1); max-width: 100%; }
  .chip { display: inline-flex; align-items: center; gap: 6px; height: var(--h-ctl-sm); padding: 0 var(--s-2) 0 5px;
    border-radius: var(--r-ctl); border: var(--bw) solid var(--ctl-line); background: var(--ctl-bg); color: var(--text);
    font-size: var(--fs-small); font-weight: var(--fw-medium); white-space: nowrap; flex: none;
    transition: color var(--t-state) var(--ease), border-color var(--t-state) var(--ease), background-color var(--t-hover) var(--ease),
      transform var(--t-press) ease-out; }
  .chip.tone-none { color: var(--text-label); border-style: dashed; background: none; }
  button.chip, a.chip { cursor: pointer; text-decoration: none; }
  /* the link chip presses like the button chips (base.css scales buttons only) */
  a.chip:active { transform: scale(.97); }
  button.chip:hover, a.chip:hover { background: var(--ctl-hover); border-color: var(--line-control-hover); }

  .line { border-top: var(--bw) solid var(--line-soft); padding-top: var(--s-3); min-width: 0; }
  /* the sentence is the ladder's conclusion, so it is never cut short: at Setup's 372 px (and a narrow Settings
     column) it takes a second line, never a third */
  .line :global([data-hint]) { white-space: normal; display: -webkit-box; -webkit-box-orient: vertical;
    -webkit-line-clamp: 2; line-clamp: 2; }
  .wait-line { display: flex; align-items: center; height: calc(var(--fs-small) * 1.4); }
</style>
