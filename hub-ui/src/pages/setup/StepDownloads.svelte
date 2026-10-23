<script lang="ts">
  // Step 3, Downloads (spec settings-setup §8, mockup "Setup · Downloads step"): the source ladder beside the three
  // download logins as compact account cards (Qobuz, YouTube Premium, SoundCloud Go+), so the ladder lights rung by
  // rung as the user signs in. The same blocks and the same flows as Settings (AccountPanel + AccountFlow): a sign-in
  // here is a sign-in there. Required: Qobuz signed in, or "I don't have Qobuz" (inside Qobuz's card); the other two
  // are optional. While Qobuz is required its card's main action is the screen's one filled button (filledCard);
  // afterwards Continue is. A click on a rung's name or chip brings its card into view and puts the focus in it.
  import { untrack } from 'svelte';
  import { api } from '$lib/bridge/client';
  import type { DownloadsView, ProblemKind, SetupStatus } from '$lib/bridge/types';
  import { AccountFlow, AccountPanel, ProblemCard, SourceLadder, accountBlocked } from '$lib/components';
  import { bumpData, dataVersion, hub } from '$lib/stores/hub';
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
