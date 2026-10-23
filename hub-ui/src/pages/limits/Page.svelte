<script lang="ts">
  // Download limits (design system mockup design-system/limits.html). The page answers three questions in order.
  // Are my accounts okay? The services as SelectCards that carry their state: today's usage (an accent bar) and a
  // status, colour plus shape. How far am I? Today (what's left, the bar, where it comes from) beside the backlog
  // and when it's done, then the last 14 days coloured by pace. Is something wrong? The warning signs, new ones
  // marked NEW until "Got it", each with when it clears, and a slower limit to try when they say "too fast"; on a
  // quiet fortnight they are one line. The panel is the decision: the daily limit on the RiskScale, its verdict in
  // the step's colour, what it does to the backlog and a run, the extra for today, and Back · Save (the one filled
  // button) in the foot. Everything on the scale follows the pointer 1:1; the engine's numbers (days, run) follow
  // limits_what_if, throttled, dimmed while they catch up.
  import { untrack } from 'svelte';
  import {
    Badge, Button, EmptyState, Hint, InfoTip, ListRow, NoteCard, PageHeader, ProblemCard, ProgressBar, RiskScale, Segmented,
    SelectCard, Skeleton, StatCard, StatusMark, Surface, TextField, WriteButton,
  } from '$lib/components';
  import { ListPanelFrame, Panel } from '$lib/frames';
  import { api, runJob } from '$lib/bridge/client';
  import type { LimitCard, ProblemKind, Service, ServiceUsage, WhatIf } from '$lib/bridge/types';
  import { go } from '$lib/router';
  import { dataVersion } from '$lib/stores/hub';
  import { problemCopy } from '$lib/copy';
  import { markReady } from '$lib/ready';
  import UsageChart from './UsageChart.svelte';
  import {
    HONEST_NOTE, RISK_TONE, SLIDER_MAX, SUGGESTION_WHY, WHAT_IF_THROTTLE_MS, backlog, clampLimit, clearsText,
    compareDays, compareRun, defaultService, extraOptions, footerLabels, isChanged, isService, pageTitle, riskOf,
    lastDownload, serviceStatus, suggestion, todayLine, verdict, warningRows, type Draft,
  } from './limitsModel';

  let { params }: { params: Record<string, string>; query: URLSearchParams } = $props();

  const service = $derived<Service>(isService(params.service) ? params.service : 'qobuz');
  let cards = $state<LimitCard[]>([]);
  let usage = $state<ServiceUsage | null>(null);
  let shownFor = $state<Service | null>(null);
  let loaded = $state(false);
  let loadError = $state<{ kind: ProblemKind; message: string } | null>(null);
  let draft = $state<Draft>({ limit: 60, extra: 0 });
  let whatIf = $state<WhatIf | null>(null);
  let saving = $state(false);
  let saveError = $state<{ title: string | null; message: string } | null>(null);
  let seeing = $state(false);     // "Got it" pressed: the warnings dim at once, before the job confirms
  let retry = $state(0);
  let ready = false;
  let justSaved = false;

  let turn = 0;
  function load() {
    const t = ++turn;
    const want = service;
    void api.limits(want).then((r) => {
      if (t !== turn) return;
      if (r.ok) {
        cards = r.cards;
        if (!isService(params.service)) {  // #/limits or #/qobuz: open the first service that is set up
          void go(`/limits/${defaultService(r.cards)}`, { replace: true });
          return;
        }
        const keepDraft = usage && shownFor === want && !justSaved && isChanged(draft, usage.setting);
        if (shownFor !== want) { whatIf = null; saveError = null; }
        usage = r.usage;
        shownFor = want;
        loaded = true;
        loadError = null;
        seeing = false;
        if (r.usage && !keepDraft) draft = { limit: r.usage.setting.limit, extra: r.usage.setting.extra_today };
        justSaved = false;
      } else {
        loadError = { kind: r.kind, message: r.message };
      }
      if (!ready) { ready = true; markReady('limits'); }
    });
  }
  $effect(() => {
    void $dataVersion;
    void retry;
    void params.service;  // a click on a card loads that service; #/limits loads again once it became #/limits/<service>
    untrack(load);
  });

  // what the draft means: throttled while dragging, only the latest answer counts
  let reqId = 0;
  let lastSent = 0;
  let timer: ReturnType<typeof setTimeout> | undefined;
  $effect(() => {
    const d = { limit: draft.limit, extra: draft.extra };
    const u = usage;
    if (!u) return;
    untrack(() => {
      if (!isChanged(d, u.setting)) { reqId++; whatIf = u.what_if; return; }
      const wait = Math.max(0, WHAT_IF_THROTTLE_MS - (Date.now() - lastSent));
      timer = setTimeout(() => {
        lastSent = Date.now();
        const id = ++reqId;
        void api.limits_what_if(service, d.limit, d.extra).then((r) => { if (id === reqId && r.ok) whatIf = r; });
      }, wait);
    });
    return () => clearTimeout(timer);
  });

  // the number field and the scale edit the same draft
  let limitText = $state('60');
  $effect(() => { const v = draft.limit; untrack(() => { if (Number(limitText) !== v) limitText = String(v); }); });
  $effect(() => {
    const v = Number(limitText);
    untrack(() => { if (usage && Number.isFinite(v) && v >= 1 && v !== draft.limit) draft.limit = clampLimit(v, usage.setting.max); });
  });

  async function save() {
    if (!usage) return;
    saving = true;
    saveError = null;
    const r = await runJob(api.save_limits(service, draft.limit, draft.extra), { quiet: true });
    saving = false;
    if (!r.ok) {
      saveError = { title: r.kind === 'refused' ? null : problemCopy(r.kind).title, message: r.message };
      return;
    }
    justSaved = true;
    load();
  }
  function back() {
    if (!usage) return;
    draft = { limit: usage.setting.limit, extra: usage.setting.extra_today };
    saveError = null;
  }
  async function gotIt() {
    seeing = true;
    const r = await runJob(api.mark_warnings_seen(service), { success: false });
    if (!r.ok) seeing = false;   // the toast says why; the warnings stay new
  }

  const shown = $derived(whatIf ?? usage?.what_if ?? null);
  const current = $derived(cards.find((c) => c.service === service) ?? null);
  const changed = $derived(!!usage && isChanged(draft, usage.setting));
  const labels = $derived(usage ? footerLabels(draft, usage.setting) : null);
  const zones = $derived(usage?.setting.zones ?? []);
  const risk = $derived(riskOf(draft.limit, zones));
  const level = $derived(zones.length ? Math.min(5, zones.findIndex((z) => draft.limit >= z.from && draft.limit <= z.to) + 1 || 5) : 2);
  const say = $derived(verdict(level));
  // the engine's numbers lag the scale while the answer for the current draft is on its way
  const catching = $derived(!!usage && changed && (shown?.limit !== draft.limit || shown?.extra_today !== draft.extra));
  const days = $derived(usage && shown && shown.days_to_load !== null && usage.what_if.days_to_load !== null
    ? compareDays(shown.days_to_load, usage.what_if.days_to_load) : null);
  const run = $derived(usage && shown ? compareRun(shown.run_minutes, usage.what_if.run_minutes) : null);
  const bl = $derived(usage ? backlog(usage) : null);
  const rows = $derived(usage ? warningRows(service, usage.signals) : []);
  const bad = $derived(rows.filter((r) => !r.ok).length);
  const anyNew = $derived(!seeing && rows.some((r) => !r.ok && r.isNew));
  const paused = $derived(!!current?.paused);
  const tip = $derived(usage && !seeing ? suggestion(usage, Math.min(draft.limit, usage.setting.limit)) : null);
  const total = $derived(usage ? usage.days.reduce((n, d) => n + d.used, 0) : 0);
  const setupHref = (s: Service) => `#/settings/${s}`;
  const pick = (s: Service) => { if (s !== service) void go(`/limits/${s}`); };
</script>

{#snippet main()}
  <PageHeader title={pageTitle} sub="your own safety limits, not official quotas" />
  {#if cards.length}
    <div class="cards" role="tablist" aria-label="Services">
      {#each cards as c (c.service)}
        {@const st = serviceStatus(c)}
        <SelectCard title={c.name} selected={c.service === service} off={!c.set_up} onclick={() => pick(c.service)}
          test="service-card-{c.service}">
          {#if st}
            <span class="use"><b>{c.used}</b> of {c.allowance} today</span>
            <ProgressBar value={c.used / Math.max(1, c.allowance)} height={6} label="{c.name} today" />
            <span class="status" data-test="status-{c.service}"><StatusMark tone={st.tone} />{st.text}</span>
          {:else}
            <span class="use muted">not set up</span>
          {/if}
        </SelectCard>
      {/each}
    </div>
  {/if}

  {#if loadError && !usage}
    <ProblemCard kind={loadError.kind} message={loadError.message} onretry={() => retry++} />
  {:else if loaded && !usage && current}
    <Surface kind="card" data-test="limits-not-set-up">
      {#if cards.some((c) => c.set_up)}
        <EmptyState title="{current.name} is not set up"
          body="It finds better files for tracks Qobuz doesn't have, with its own daily limit."
          action={{ label: `Set up ${current.name}`, href: setupHref(service) }} />
      {:else}
        <EmptyState title="No daily limits to set" body="Only the free sources are in use, so downloads have no daily limit."
          action={{ label: 'Set up Qobuz', href: setupHref('qobuz') }} />
      {/if}
    </Surface>
  {:else if !usage || !bl}
    <div class="pair" data-test="limits-loading">
      <StatCard value={null} label="today" /><StatCard value={null} label="Backlog" />
    </div>
    <Surface kind="card"><Skeleton height={90} /></Surface>
  {:else}
    <div class="pair">
      <StatCard value={paused ? 0 : usage.today.remaining} unit="left of {usage.today.allowance}" label="{usage.name} today"
        data-test="today-card">
        <div class="under">
          <ProgressBar value={usage.today.used / Math.max(1, usage.today.allowance)} height={8} label="Used today" />
          {#if paused}<Hint tone="problem" text="Paused until midnight" />{:else}<span class="line"><Hint text={todayLine(usage)} /><InfoTip label="When it resets">Resets at midnight{lastDownload(usage) ? ` · ${lastDownload(usage)}` : ''}.</InfoTip></span>{/if}
        </div>
      </StatCard>
      <StatCard value={bl.value} unit={bl.unit} label="Backlog" data-test="still-to-load">
        {#if bl.done}<span class="done"><StatusMark tone="good" />{bl.line}</span>{:else}<Hint text={bl.line} />{/if}
      </StatCard>
    </div>

    <Surface kind="card" label="Last 14 days" summary="{total} {total === 1 ? 'download' : 'downloads'}" data-test="usage">
      {#snippet header()}
        <span class="legend" aria-hidden="true"><i class="safe"></i>normal<i class="notice"></i>faster<i class="high"></i>risky</span>
      {/snippet}
      <UsageChart days={usage.days} limit={usage.setting.limit} draft={draft.limit} {zones} height={84} />
    </Surface>

    {#if !bad}
      <Surface kind="card" data-test="warnings-ok">
        <div class="ok"><StatusMark tone="good" /><b>No warning signs</b><Hint text="in the last 14 days" />
          <InfoTip label="What Discjockey watches">{rows.map((r) => r.title).join(' · ')}.</InfoTip></div>
      </Surface>
    {:else}
      <Surface kind="list" label="Warning signs" summary="{bad} in 14 days{anyNew ? '' : ' · seen'}"
        tone={paused ? 'problem' : anyNew ? 'warn' : 'default'} grow={{ rows: rows.length + (tip ? 1 : 0), tall: true }}
        style="--row-cols: 16px minmax(0, 1fr) auto"
        data-test="signals">
        {#snippet header()}
          {#if anyNew}<Button size="sm" onclick={gotIt} data-test="got-it">Got it</Button>{/if}
        {/snippet}
        {#if tip}
          <ListRow height={52} test="suggestion">
            {#snippet lead()}<StatusMark tone={paused ? 'problem' : 'warn'} />{/snippet}
            {#snippet name()}{tip.text}{/snippet}
            {#snippet sub()}{SUGGESTION_WHY}{/snippet}
            {#snippet trailing()}
              <Button variant="primary" size="sm" onclick={() => (draft.limit = tip.limit)} data-test="try-limit">Try {tip.limit} a day</Button>
            {/snippet}
          </ListRow>
        {/if}
        {#each rows as r (r.kind)}
          {#if r.ok}
            <ListRow height={40} test="signal-{r.kind}">
              {#snippet lead()}<StatusMark tone="good" quiet />{/snippet}
              {#snippet name()}<span class="quiet">{r.title}</span>{/snippet}
            </ListRow>
          {:else}
            <ListRow height={52} class={r.isNew && !seeing ? '' : 'seen'} test="signal-{r.kind}">
              {#snippet lead()}<StatusMark tone={r.kind === 'auto_stop' && paused ? 'problem' : 'warn'} />{/snippet}
              {#snippet name()}<b>{r.title}</b>{#if r.isNew && !seeing}<span class="new"><Badge tone="accent" text="NEW" /></span>{/if}{/snippet}
              {#snippet sub()}{r.latest}{/snippet}
              {#snippet trailing()}
                <span class="clears">{clearsText(r.clearsIn)}</span><span class="count">{r.count}×</span>
              {/snippet}
            </ListRow>
          {/if}
        {/each}
      </Surface>
    {/if}
  {/if}
{/snippet}

{#snippet head()}
  {#if usage && shown}
    <Surface kind="card" label="Daily limit" data-test="limit">
      {#snippet header()}<span class="field"><TextField bind:value={limitText} type="number" name="limit" label="Daily limit" /></span>{/snippet}
      <div class="value"><span class="v" data-test="limit-value">{draft.limit}</span>
        <span class="per">a day{draft.limit !== usage.setting.limit ? ` · saved ${usage.setting.limit}` : ''}</span></div>
      <RiskScale {zones} value={Math.min(draft.limit, SLIDER_MAX)} saved={usage.setting.limit} max={SLIDER_MAX}
        label="Daily limit" test="limit-scale"
        onchange={(v) => (draft.limit = v)} />
    </Surface>
    <Surface kind="card" tone={RISK_TONE[risk]} data-test="verdict">
      <div class="verdict"><StatusMark tone={RISK_TONE[risk]} />
        <span class="vt"><b class:risky={risk === 'high'}>{say.title}</b><span>{say.sub}</span></span>
        <InfoTip label="How sure is this?">{HONEST_NOTE[service]}</InfoTip></div>
    </Surface>
    <div class="pair" class:catching>
      <StatCard value={days?.value ?? null} unit={days?.unit} label="Backlog done in" data-test="days">
        {#if !days}<Hint text={usage.behind ? `set by ${usage.behind}` : 'nothing to load'} />
        {:else if days.was}<span class="was" class:better={days.better}>{days.was}</span>{/if}
      </StatCard>
      <StatCard value={run?.value ?? null} unit={run?.unit} label="One run takes" data-test="run">
        {#if run?.was}<span class="was" class:better={run.better}>{run.was}</span>{/if}
      </StatCard>
    </div>
    <Surface kind="card" label="Extra just for today" data-test="extra">
      {#snippet header()}<Hint text="ends at midnight" />{/snippet}
      <Segmented label="Extra just for today" value={String(draft.extra)} test="extra"
        options={extraOptions(usage.setting.extra_today, usage.setting.extra_max).map((o) => ({ key: o.key, label: o.label }))}
        onchange={(k) => (draft.extra = Number(k))} />
    </Surface>
  {:else if loaded && !usage}
    <EmptyState title={cards.some((c) => c.set_up) ? `Set up ${current?.name ?? 'this service'} to give it a daily limit.`
      : 'Each paid service you set up gets its own daily limit.'} />
  {:else}
    <Surface kind="card"><Skeleton lines={4} /></Surface>
  {/if}
{/snippet}

{#snippet foot()}
  {#if saveError}
    <NoteCard tone="problem" title={saveError.title ?? undefined} data-test="save-error">{saveError.message}</NoteCard>
  {/if}
  {#if usage && labels}
    <div class="footer" data-test="footer">
      <Button wide data-test="back" onclick={back} disabled={!changed || saving}>{labels.back}</Button>
      <WriteButton wide variant="filled" data-test="save" busy={saving} disabled={!changed} onclick={save}>{labels.save}</WriteButton>
    </div>
  {/if}
{/snippet}

{#snippet side()}<Panel {head} {foot} />{/snippet}

<div class="page" data-test="limits-page"><ListPanelFrame {main} panel={side} /></div>

<style>
  .page { height: 100%; min-height: 0; }
  .cards { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: var(--s-3); }
  .use { color: var(--text-muted); font-size: var(--fs-small); font-variant-numeric: tabular-nums; }
  .use b { color: var(--text-strong); font-size: var(--fs-title); font-weight: var(--fw-bold); margin-right: 2px; }
  .muted { color: var(--text-label); }
  .status { display: inline-flex; align-items: center; gap: var(--s-1); font-size: var(--fs-label);
    font-weight: var(--fw-semi); color: var(--text); white-space: nowrap; }
  .pair { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: var(--s-3); }
  .under { display: flex; flex-direction: column; gap: var(--s-2); }
  .line { display: flex; align-items: center; gap: var(--s-1); min-width: 0; }
  .line > :global(:first-child) { min-width: 0; }
  .done { display: inline-flex; align-items: center; gap: var(--s-2); color: var(--risk-safe); font-weight: var(--fw-semi); }
  .legend { display: inline-flex; align-items: center; gap: var(--s-1); font-size: var(--fs-label); color: var(--text-muted); }
  .legend i { width: 8px; height: 8px; border-radius: 2px; margin-left: var(--s-2); }
  .legend i.safe { background: var(--risk-safe); }
  .legend i.notice { background: var(--risk-notice); }
  .legend i.high { background: var(--risk-high); }
  .ok { display: flex; align-items: center; gap: var(--s-2); }
  .ok b { color: var(--text-strong); font-weight: var(--fw-semi); }
  .quiet { color: var(--text-muted); }
  .new { margin-left: var(--s-2); }
  .clears { color: var(--text-label); font-size: var(--fs-label); white-space: nowrap; }
  .count { min-width: 28px; text-align: right; font-weight: var(--fw-semi); font-variant-numeric: tabular-nums; }
  :global([data-test='signals'] .seen) { opacity: .55; transition: opacity var(--t-state) var(--ease); }
  .field { width: 76px; }
  .value { display: flex; align-items: baseline; gap: var(--s-2); }
  .v { font-size: var(--fs-stat); font-weight: var(--fw-bold); color: var(--text-strong); line-height: 1;
    letter-spacing: var(--ls-stat); font-variant-numeric: tabular-nums; }
  .per { color: var(--text-muted); }
  .verdict { display: flex; align-items: flex-start; gap: var(--s-2); }
  .vt { display: flex; flex-direction: column; gap: 2px; flex: 1; min-width: 0; }
  .vt b { color: var(--text-strong); font-weight: var(--fw-semi); }
  .vt b.risky { color: var(--risk-high); }
  .vt span { color: var(--text-muted); font-size: var(--fs-small); }
  .catching :global(.stat-card .num) { opacity: .55; transition: opacity var(--t-press) var(--ease); }
  .was { color: var(--text-muted); font-size: var(--fs-small); }
  .was.better { color: var(--risk-safe); }
  .footer { display: flex; gap: var(--s-2); }
  .footer > :global(*) { flex: 1; }
</style>
