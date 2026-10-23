// Fake mode only (VITE_FAKE=1): the whole backend in the browser, so every screen and state can be built and
// screenshot-checked without Python. Reached only through `if (import.meta.env.VITE_FAKE === '1')` in main.ts.
import { installBridge } from '../client';
import { CONTRACT_METHODS } from '../contract';
import type { HubEvent } from '../events';
import { DROP_BLOCKED } from '../../copy';
import { SCENARIOS, createFakeBridge, pageScenarios, type FakeContext } from './bridge';

export { SCENARIOS, pageScenarios };
export type FakeCall = { method: string; args: unknown };
const HIDDEN_ARGS = new Set(['setup_qobuz_login', 'setup_save_client_id']);

export type FakeControl = {
  scenario: string; speed: number; ctx: FakeContext;
  dropFile(readable: boolean): void; consoleBusy(running: boolean): void; spotifyRead(): void;
};
declare global {
  interface Window { __fakeCalls?: FakeCall[]; __fake?: FakeControl }
}

const clone = <T>(v: T): T => (v === undefined ? v : JSON.parse(JSON.stringify(v)));

export function installFake(scenario: string): FakeControl {
  const params = new URLSearchParams(location.search);
  const speed = Number(params.get('speed')) || 1;
  const freeze = Number(params.get('freeze')) || null;
  const emit = (e: HubEvent) => window.dj?.onEvent(clone(e));
  const fake = createFakeBridge(scenario, { speed, freeze, emit });
  const calls: FakeCall[] = (window.__fakeCalls = []);
  const api: Record<string, (...a: unknown[]) => Promise<unknown>> = {};
  for (const m of CONTRACT_METHODS) {
    api[m] = async (...args: unknown[]) => {
      // credentials never reach the call log
      calls.push({ method: m, args: HIDDEN_ARGS.has(m) ? '[hidden]' : clone(args) });
      // JSON in, JSON out, as through pywebview (the page can't change the fake's state by reference)
      return clone(await (fake[m] as (...a: unknown[]) => Promise<unknown>)(...clone(args)));
    };
  }
  installBridge(api);
  const ctx = fake._ctx;
  const control: FakeControl = {
    scenario, speed, ctx,
    dropFile(readable: boolean) {
      const t = ctx.s.tracks.find((x) => x.track_id === ctx.s.selected);
      const name = t ? `${t.artist} - ${t.title}.wav` : 'Some Artist - Some Track.wav';
      if (!readable) {
        emit({ type: 'FileDropped', track_id: ctx.s.selected, name, readable: false, message: DROP_BLOCKED });
        return;
      }
      if (!t) {
        emit({ type: 'FileDropped', track_id: null, name, readable: true,
          message: 'Select the track this file belongs to, then drop it again.' });
        return;
      }
      ctx.s.dropped = { track_id: t.track_id, name };
      emit({ type: 'FileDropped', track_id: t.track_id, name, readable: true, message: '' });
    },
    consoleBusy(running: boolean) {
      ctx.s.console_running = running;
      emit({ type: 'ConsoleBusy', running });
    },
    spotifyRead() { void api.refresh(); },
  };
  window.__fake = control;
  return control;
}
