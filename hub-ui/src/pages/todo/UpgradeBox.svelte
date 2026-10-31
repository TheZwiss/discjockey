<script lang="ts">
  // To-do's upgrade decision (mockup todo-decisions, spec §6.6): two cards. "Upgrade ready" holds the comparison: the
  // spectra with what each version is under them (Now and New both as a quality, "MP3 · 320 kbps" / "FLAC ·
  // lossless"), the compare player, and the "Edit" row (a fact about the audio, not a promise about rekordbox).
  // "In rekordbox" is the only place where the two ways differ, so it is the only choice: with an AIFF file and the
  // same edit, Same track (recommended, = Swap) or New track (= Add as new file), the picked row listing what happens;
  // otherwise no choice, it says what will happen and why Same track isn't possible. Its last section says where the
  // old file goes and the README's tip to quit rekordbox first. The action itself ("Replace with lossless") is the
  // panel foot's filled button (Details); the Library keeps the shared UpgradeCard.
  import type { Spectrum as Spec, TrackDetail } from '$lib/bridge/types';
  import { ChoiceGroup, ComparePlayer, Hint, KeyValue, OutcomeList, Spectrum, Surface } from '$lib/components';
  import type { ChoiceOption } from '$lib/components';
  import { foundText, upgradeLabel } from '$lib/format';
  import { KEPT_FILE, QUIT_REKORDBOX, editLine, upgradeWays, type Way } from './todoModel';

  let { track, current, upgrade, loading, swap, way, onway, busy = false }: {
    track: TrackDetail; current: Spec | null; upgrade: Spec | null; loading: boolean;
    /** both ways are possible (actionsFor().upgrade.swap) */
    swap: boolean;
    /** the picked way, and where a new pick goes */
    way: Way; onway: (w: Way) => void;
    /** an upgrade job is running: the choice waits */
    busy?: boolean;
  } = $props();

  const up = $derived(track.upgrade!);
  const ways = $derived(upgradeWays(up, swap));
  const edit = $derived(editLine(up.alignment));
  const options = $derived(ways.options.map((o): ChoiceOption<Way> => ({ key: o.key, name: o.name, summary: o.summary,
    outcomes: o.outcomes, recommended: o.key === 'swap', test: `way-${o.key}` })));
  const nowLabel = $derived(track.format_line ?? track.quality_label);
</script>

<Surface kind="card" tone="good" label={upgradeLabel(up.what)} summary={foundText(up.found) || undefined}>
  <div class="up" data-test="upgrade-box" data-swap={swap}>
    <div class="specs">
      <div>
        <Spectrum spectrum={current} height={28} loading={loading && !current} cutoffLabel={false} />
        <span class="fmt"><span class="caps">Now</span><span class="q" title={nowLabel}>{nowLabel}</span></span>
      </div>
      <div>
        <Spectrum spectrum={upgrade} height={28} loading={loading && !upgrade} cutoffLabel={false} />
        <span class="fmt"><span class="caps">New</span><span class="q" title={up.format_line}>{up.format_line}</span></span>
      </div>
    </div>
    {#if track.audio_url && up.audio_url}
      <ComparePlayer ready total={track.duration_s} a={{ url: track.audio_url, label: 'Now' }}
        b={{ url: up.audio_url, label: 'New' }} />
    {/if}
    <KeyValue k="Edit" keyWidth={44}>
      <span class="edit" data-test="upgrade-edit" data-tone={edit.tone}><span class="dot {edit.tone}" aria-hidden="true"></span>{edit.text}</span>
    </KeyValue>
  </div>
</Surface>

{#snippet after()}
  <OutcomeList items={[KEPT_FILE]} />
  <Hint text={QUIT_REKORDBOX} />
{/snippet}

{#if ways.choice}
  <ChoiceGroup label="In rekordbox" {options} value={way} onchange={onway} foot={after} disabled={busy}
    test="upgrade-ways" />
{:else}
  <Surface kind="card" label="In rekordbox" summary="a new track" data-test="upgrade-ways" data-choice="false">
    <div class="fixed">
      <OutcomeList items={[...ways.fixed, KEPT_FILE]} />
      {#if ways.reason}<Hint text={ways.reason} class="reason" data-test="upgrade-why" />{/if}
      <Hint text={QUIT_REKORDBOX} />
    </div>
  </Surface>
{/if}

<style>
  .up { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .specs { display: grid; grid-template-columns: 1fr 1fr; gap: var(--s-2); }
  .specs > div { display: flex; flex-direction: column; gap: var(--s-1); min-width: 0; }
  /* NOW over "MP3 · 320 kbps": the version's name in caps, its quality whole on the line under it (side by side they
     didn't fit a column at 1100: "Opus · 135 k…"); cut with … only in a very narrow column */
  .fmt { display: flex; flex-direction: column; gap: 1px; min-width: 0; font-size: var(--fs-small); color: var(--text-muted); }
  .q { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .caps { font-size: var(--fs-label); text-transform: uppercase; letter-spacing: 0.7px; color: var(--text-label); }
  .edit { display: inline-flex; align-items: baseline; gap: 6px; min-width: 0; }
  .dot { width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; align-self: flex-start; margin-top: 0.45em; }
  .dot.lossless { background: var(--q-lossless); }
  .dot.good_lossy { background: var(--q-good); }
  .dot.other { background: var(--q-other); }
  .fixed { display: flex; flex-direction: column; gap: var(--s-2); }
  .fixed :global(.reason) { color: var(--text-label); }
</style>
