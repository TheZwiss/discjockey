<script lang="ts">
  // Fake mode only: a small "FAKE ▾" pill (the scenario in its tooltip and menu), to switch scenario and poke the fake
  // backend. It sits in the page's top left corner, just inside the page's edge (`--sidebar-w`, so it follows the
  // chrome), above the page header's title: there it covers nothing the shots show, in either sidebar form (the
  // rail has no room beside a brand, and the window's bottom holds the foot).
  import { SCENARIOS, pageScenarios } from '../bridge/fake';
  import { toasts } from '../stores/toasts';

  const fake = window.__fake;
  const current = fake?.scenario ?? 'normal';
  const all = [...SCENARIOS, ...Object.keys(pageScenarios())];
  let open = $state(false);
  let consoleOn = $state(fake?.ctx.s.console_running ?? false);

  function reload(p: Record<string, string>) {
    const u = new URL(location.href);
    for (const [k, v] of Object.entries(p)) u.searchParams.set(k, v);
    location.href = u.toString();
  }
  function act(fn: () => void) { fn(); open = false; }
</script>

<div class="fake chrome" data-test="fake-toolbar" data-dev>
  {#if open}
    <div class="menu" role="menu">
      <label>Scenario
        <select value={current} onchange={(e) => reload({ scenario: (e.currentTarget as HTMLSelectElement).value })}>
          {#each all as s (s)}<option value={s}>{s}</option>{/each}
        </select>
      </label>
      <label>Speed
        <select value={String(fake?.speed ?? 1)} onchange={(e) => reload({ speed: (e.currentTarget as HTMLSelectElement).value })}>
          {#each ['0.5', '1', '2', '5', '20'] as v (v)}<option value={v}>{v}×</option>{/each}
        </select>
      </label>
      <button type="button" onclick={() => act(() => fake?.dropFile(true))}>Drop a readable file</button>
      <button type="button" onclick={() => act(() => fake?.dropFile(false))}>Drop a blocked file</button>
      <button type="button" onclick={() => act(() => { consoleOn = !consoleOn; fake?.consoleBusy(consoleOn); })}>
        {consoleOn ? 'Console ends' : 'Console starts'}</button>
      <button type="button" onclick={() => act(() => fake?.readPlaylists())}>Read playlists</button>
      <div class="row">
        <button type="button" onclick={() => toasts.show({ tone: 'info', title: 'Info toast', body: 'Hides after 5 s.' })}>Info</button>
        <button type="button" onclick={() => toasts.show({ tone: 'success', title: 'Hidden from the to-do list.' })}>Success</button>
        <button type="button" onclick={() => toasts.show({ tone: 'problem', title: "That didn't work.", body: 'Stays until closed.' })}>Problem</button>
      </div>
      <a href="#/dev/gallery">Component gallery</a>
    </div>
  {/if}
  <button type="button" class="pill" aria-expanded={open} onclick={() => (open = !open)}
    title="Fake mode · {current}">FAKE ▾</button>
</div>

<style>
  .fake { position: fixed; left: calc(var(--sidebar-w) + 6px); top: 2px; z-index: 50; display: flex; flex-direction: column-reverse; align-items: flex-start; gap: 6px; }
  .pill { border: var(--bw) dashed var(--line-control-hover); border-radius: var(--r-pill); background: var(--bg); color: var(--text-label);
    font-size: var(--fs-label); line-height: 1.2; padding: 1px 9px; letter-spacing: .3px; }
  .menu { background: var(--bg); border: var(--bw) solid var(--line-control); border-radius: var(--r-card); padding: var(--s-2);
    display: flex; flex-direction: column; gap: 4px; min-width: 210px; box-shadow: var(--shadow); font-size: var(--fs-small); }
  .menu button, .menu a { text-align: left; border: var(--bw) solid var(--line-control); background: transparent; color: var(--text);
    border-radius: var(--r-input); padding: 3px 8px; font-size: var(--fs-small); }
  .menu label { display: flex; justify-content: space-between; align-items: center; gap: var(--s-2); color: var(--text-muted); }
  select { background: var(--bg); color: var(--text); border: var(--bw) solid var(--line-control); border-radius: var(--r-input); }
  .row { display: flex; gap: 4px; }
</style>
