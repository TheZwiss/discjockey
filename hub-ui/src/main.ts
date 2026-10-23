// Boot (plan 64.6).
import './lib/styles/tokens.css';
import './lib/styles/base.css';
import { mount } from 'svelte';
import App from './App.svelte';
import { installEventSink } from '$lib/bridge/events';
import { api, bridgeReady } from '$lib/bridge/client';
import { hubNow, markBooted, refreshHub } from '$lib/stores/hub';
import { seedRun } from '$lib/stores/run';
import { catchDrops } from '$lib/stores/drag';
import { go, onRouteChange } from '$lib/router';

const WIZARD_SHOWN = 'discjockey.wizardShown';
function onceThisSession(): boolean {
  try {
    if (sessionStorage.getItem(WIZARD_SHOWN)) return false;
    sessionStorage.setItem(WIZARD_SHOWN, '1');
  } catch { /* no storage: ask every start */ }
  return true;
}

async function boot(): Promise<void> {
  const fake = import.meta.env.VITE_FAKE === '1';
  if (import.meta.env.VITE_FAKE === '1') {
    const { installFake } = await import('$lib/bridge/fake');
    installFake(new URLSearchParams(location.search).get('scenario') ?? 'normal');
  }
  installEventSink();
  // Safety net: no website ever opens inside the window.
  document.addEventListener('click', (e) => {
    if (e.defaultPrevented) return;
    const a = (e.target as Element | null)?.closest?.('a[href^="http"]');
    if (!a) return;
    e.preventDefault();
    void api.open_external(a.getAttribute('href') ?? '');
  });
  // A dropped file never lands on a track the user doesn't see: only To-do selects.
  onRouteChange((r) => { if (r.name !== 'todo') void api.select(null); });
  const catcher = document.getElementById('drop-catcher');
  if (catcher) catchDrops(document, catcher);

  mount(App, { target: document.getElementById('app')! });

  await bridgeReady();
  await refreshHub();
  markBooted(fake);
  const { job, setup } = hubNow();
  if (job?.running) seedRun(job);
  // No music folder yet: its Setup step on every start (the shell keeps every other page closed until it is chosen).
  // A missing folder shows the shell's own screen; Setup waits until the folder is back.
  const music = setup?.music.state;
  if (music === 'not_chosen') {
    if (location.hash !== '#/setup/music') void go('/setup/music', { replace: true });
  } else if (music !== 'missing' && setup && setup.complete === false && !location.hash.startsWith('#/setup')
    && onceThisSession()) {
    void go(`/setup/${setup.next_step ?? ''}`.replace(/\/$/, ''), { replace: true });
  }
}

void boot();
