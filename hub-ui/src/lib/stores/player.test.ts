import { get } from 'svelte/store';
import { afterEach, describe, expect, it } from 'vitest';
import { attachAudio, claimSound, player } from './player';
import type { QueueItem } from './queueModel';

/** Enough of an <audio> for the player: events, src, play/pause. `finish()` plays it to its end. */
class FakeAudio extends EventTarget {
  src = '';
  currentTime = 0;
  duration = 200;
  paused = true;
  play() { this.paused = false; this.dispatchEvent(new Event('playing')); return Promise.resolve(); }
  pause() { this.paused = true; this.dispatchEvent(new Event('pause')); }
  load() {}
  removeAttribute(name: string) { if (name === 'src') this.src = ''; }
  finish() { this.paused = true; this.dispatchEvent(new Event('ended')); }
}

const item = (n: number): QueueItem => ({ track_id: `t${n}`, title: `Title ${n}`, artist: 'Artist', cover_url: null,
  duration_s: 200 });
const items = (n: number) => Array.from({ length: n }, (_, i) => item(i));
const source = { label: 'All tracks', href: '#/library' };
const tick = () => new Promise((r) => setTimeout(r, 0));

/** A resolve whose answers the test hands out, so it can finish them in any order. */
function slowResolve() {
  const waiting = new Map<string, (url: string | null) => void>();
  const resolve = (id: string) => new Promise<string | null>((r) => waiting.set(id, r));
  const answer = (id: string) => waiting.get(id)!(`/audio/${id}`);
  return { resolve, answer };
}

let detach: (() => void) | null = null;
function setup() {
  const el = new FakeAudio();
  detach = attachAudio(el as unknown as HTMLAudioElement);
  return el;
}
afterEach(() => { player.stop(); detach?.(); detach = null; });

describe('player queue', () => {
  it('the latest of two quick next() calls wins', async () => {
    const el = setup();
    const r = slowResolve();
    player.playQueue({ items: items(4), start: 0, source, resolve: r.resolve });
    r.answer('t0'); await tick();
    player.next();
    player.next();
    r.answer('t2'); await tick();
    r.answer('t1'); await tick();   // the older request finishes last and is dropped
    expect(el.src).toBe('/audio/t2');
    expect(get(player).track_id).toBe('t2');
  });

  it('stops at the end of the list with ended set, and ▶ starts it again from the top', async () => {
    const el = setup();
    const resolve = async (id: string) => `/audio/${id}`;
    player.playQueue({ items: items(2), start: 1, source, resolve });
    await tick();
    el.finish(); await tick();
    expect(get(player)).toMatchObject({ ended: true, playing: false, track_id: 't1' });
    player.toggle(); await tick();
    expect(get(player)).toMatchObject({ ended: false, track_id: 't0', playing: true });
  });

  it('a clip pauses the queue and keeps it; stop clears the queue and hidden', async () => {
    const el = setup();
    player.playQueue({ items: items(3), start: 1, source, resolve: async (id) => `/audio/${id}` });
    await tick();
    player.hide();
    claimSound(Symbol('clip'), () => {});
    expect(el.paused).toBe(true);
    expect(get(player)).toMatchObject({ hidden: true, track_id: 't1', url: '/audio/t1' });
    expect(get(player).queue).not.toBeNull();
    player.stop();
    expect(get(player)).toMatchObject({ queue: null, hidden: false, url: null, playing: false });
  });

  it("a track that can't be resolved shows the error and does not skip", async () => {
    setup();
    player.playQueue({ items: items(3), start: 0, source, resolve: async () => null });
    await tick();
    expect(get(player)).toMatchObject({ error: "Can't play this file.", track_id: 't0', playing: false });
  });
});
