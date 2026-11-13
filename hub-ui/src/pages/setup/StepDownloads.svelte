<script lang="ts">
  // Step 3, Downloads (spec settings-setup §8, mockup "Setup · Downloads step"): the source ladder beside the three
  // download logins as compact account cards (Qobuz, YouTube Premium, SoundCloud Go+), so the ladder lights rung by
  // rung as the user signs in. The same blocks and the same flows as Settings (AccountPanel + AccountFlow): a sign-in
  // here is a sign-in there. Required: Qobuz signed in, or "I don't have Qobuz" (inside Qobuz's card); the other two
  // are optional. While Qobuz is required its card's main action is the screen's one filled button (filledCard);
  // afterwards Continue is. A click on a rung's name or chip brings its card into view and puts the focus in it.
  // Under the account cards sits one more card, "Upgrades" (issue 33 stage C plan §6.2): the switch "Upgrade
  // automatically when I sync", starting on, saved at once (set_auto_upgrade). It shows once Qobuz is decided (signed
  // in or left out), still before Continue; it is never the filled button and never blocks Continue.
  import { untrack } from 'svelte';
  import { api, runJob } from '$lib/bridge/client';
  import type { DownloadsView, ProblemKind, SetupStatus } from '$lib/bridge/types';
  import { AccountFlow, AccountPanel, NoteCard, ProblemCard, SourceLadder, Surface, ToggleRow, accountBlocked } from '$lib/components';
  import { AUTO_UPGRADE_LABEL, AUTO_UPGRADE_SETUP_SUB, autoUpgradeOn, shownAutoUpgrade } from '$lib/autoUpgrade';
  import { bumpData, dataVersion, hub, writeBlockedReason } from '$lib/stores/hub';
  import { filledCard } from './setupModel';

  // `busy`: one of the cards' flows runs (a sign-in waiting for the browser, a check): the page holds Back, Continue
  // and the step strip, so leaving never drops a card's Cancel while its wait goes on
  let { status, busy = $bindable(false) }: { status: SetupStatus; busy?: boolean } = $props();

  type Service = 'qobuz' | 'youtube' | 'soundcloud';
  const SERVICES: Service[] = ['qobuz', 'youtube', 'soundcloud'];

  let downloads = $state<DownloadsView | null>(null);
  let loadError = $state<{ kind: ProblemKind; message: string } | null>(null);
  let retry = $state(0);
  let turn = 0;
  function load() {
    const t = ++turn;
    void api.downloads_view().then((r) => {
      if (t !== turn) return;
      if (r.ok) { downloads = r.downloads; loadError = null; } else loadError = { kind: r.kind, message: r.message };
    });
  }
  $effect(() => {
    void $dataVersion;
    void retry;
    untrack(load);
  });

  // a finished sign-in, check or sign-out (and "I don't have Qobuz") bumps dataVersion: the cards, the ladder and
  // the step's state (the page's setup_status) read again
  const flows: Record<Service, AccountFlow> = {
    qobuz: new AccountFlow('qobuz', bumpData), youtube: new AccountFlow('youtube', bumpData),
    soundcloud: new AccountFlow('soundcloud', bumpData),
  };
  // every card shows at once, so each flow looks for its logins and follows its sign-in while the step is open
  $effect(() => untrack(() => {
    const stops = SERVICES.map((s) => flows[s].mount());
    return () => stops.forEach((stop) => stop());
  }));

  $effect(() => { busy = SERVICES.some((s) => flows[s].busy); });

  const filled = $derived(filledCard(status));
  const blocked = $derived(accountBlocked($hub));

  // the Upgrades switch: the choice being saved shows at once, until the read-again status says the same
  let pending = $state<boolean | null>(null);
  let upgradeError = $state<string | null>(null);
  $effect(() => { if (pending !== null && autoUpgradeOn(status.auto_upgrade) === pending) pending = null; });
  async function setAuto(on: boolean) {
    if ($writeBlockedReason || pending !== null) return;
    upgradeError = null;
    pending = on;
    const r = await runJob(api.set_auto_upgrade(on), { quiet: true, success: false });
    if (!r.ok) { pending = null; if (r.kind !== 'stopped') upgradeError = r.message; }
    bumpData();
  }

  let cards = $state<Partial<Record<Service, HTMLElement>>>({});
  function pick(service: Service) {
    const el = cards[service];
    if (!el) return;
    const still = matchMedia('(prefers-reduced-motion: reduce)').matches;
    el.scrollIntoView({ block: 'nearest', behavior: still ? 'auto' : 'smooth' });
    el.querySelector<HTMLElement>('input, button:not([aria-disabled="true"])')?.focus({ preventScroll: true });
  }
</script>

<div class="two" data-test="setup-downloads">
  <div class="ladder">
    {#if loadError && !downloads}
      <ProblemCard kind={loadError.kind} message={loadError.message} onretry={() => retry++} />
    {:else}
      <SourceLadder {downloads} compact onpick={pick} test="setup-ladder" />
    {/if}
  </div>
  <div class="cards">
    {#each SERVICES as service (service)}
      {@const flow = flows[service]}
      <div bind:this={cards[service]} class="card" data-test="setup-card-{service}">
        <AccountPanel {service} {downloads} compact filled={filled === service} phase={flow.phase(downloads)}
          actions={flow} logins={flow.logins} busy={flow.busy} disabledWhy={blocked} />
      </div>
    {/each}
    <!-- once Qobuz is decided (signed in or left out): before that the card sat below the fold, under three cards the
         user has to deal with first, and an unseen switch is no choice (stage review B10); still before Continue -->
    {#if filled === null}
      <Surface kind="list" label="Upgrades" data-test="setup-card-upgrades">
        <ToggleRow item={{ key: 'auto_upgrade', label: AUTO_UPGRADE_LABEL, on: shownAutoUpgrade(status.auto_upgrade, pending) }}
          sub={AUTO_UPGRADE_SETUP_SUB} disabled={!!$writeBlockedReason} title={$writeBlockedReason ?? undefined}
          onchange={(_k, on) => void setAuto(on)} test="auto-upgrade-switch" />
      </Surface>
    {/if}
    {#if upgradeError}<NoteCard tone="problem" data-test="auto-upgrade-error">{upgradeError}</NoteCard>{/if}
  </div>
</div>

<style>
  /* the ladder at its compact width (the 372 px it is drawn for) beside the cards, which take the rest; it stays in
     view while the cards scroll past it, so a sign-in lights its rung where the user can see it */
  .two { display: grid; grid-template-columns: 372px minmax(0, 1fr); gap: var(--s-3); align-items: start; }
  .ladder { position: sticky; top: 0; min-width: 0; }
  .cards { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .card { scroll-margin-block: var(--s-4); }
</style>
