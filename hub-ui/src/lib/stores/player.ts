// One sound at a time (plan 64.5): one hidden <audio> in App.svelte. Starting any sound stops the previous one,
// including a ComparePlayer and the wrong-song dialog's clips (they register themselves through claimSound).
// On top of the element sits the queue session (plan now-playing): the list a preview started from, its rules in
// queueModel.ts. A clip or a compare pauses the queue where it is; a single `play()` forgets it.
import { get, writable, type Readable } from 'svelte/store';
import { artistTitle } from '../format';
import { current, goTo, makeQueue, nextIndex, prevAction, setShuffle as shuffled, type Queue, type QueueItem,
  type QueueSource } from './queueModel';

export type PlayerState = { url: string | null; title: string; track_id: string | null; playing: boolean;
  loading: boolean; position_s: number; duration_s: number | null; error: string | null;
  queue: Queue | null; hidden: boolean; ended: boolean };   // ended: stopped after the last track of the queue
const EMPTY: PlayerState = { url: null, title: '', track_id: null, playing: false, loading: false, position_s: 0,
  duration_s: null, error: null, queue: null, hidden: false, ended: false };
export const CANT_PLAY = "Can't play this file.";

const state = writable<PlayerState>({ ...EMPTY });
let audio: HTMLAudioElement | null = null;
let owner: { id: symbol; stop: () => void } | null = null;
const ME = Symbol('player');
/** Turns a track id into its playable URL when that item plays; null when it can't be played. Kept with the queue. */
type Resolve = (track_id: string) => Promise<string | null>;
let resolver: Resolve | null = null;
let turn = 0;   // the latest request wins: a slow resolve that finished late sees a newer turn and gives up

/** Whoever starts a sound calls this; the previous owner is stopped. */
export function claimSound(id: symbol, stop: () => void): void {
  if (owner && owner.id !== id) {
    const prev = owner;
    owner = null;
    prev.stop();
  }
  owner = { id, stop };
}
export function releaseSound(id: symbol): void {
  if (owner?.id === id) owner = null;
}
/** What the player does when someone else takes the sound: a queue waits where it is, a single sound is dropped. */
const claim = () => claimSound(ME, () => (get(state).queue ? pauseForClip() : stop()));

/** App.svelte hands its hidden <audio> element over once. */
export function attachAudio(el: HTMLAudioElement): () => void {
  audio = el;
  const set = (p: Partial<PlayerState>) => state.update((s) => ({ ...s, ...p }));
  const on: Record<string, () => void> = {
    loadstart: () => set({ loading: true, error: null }),
    canplay: () => set({ loading: false }),
    playing: () => set({ playing: true, loading: false }),
    pause: () => set({ playing: false }),
    ended: () => {
      const q = get(state).queue;
      if (!q) { set({ playing: false, position_s: 0 }); return; }
      const n = nextIndex(q);
      if (n !== null) { void playAt(n); return; }
      set({ playing: false, ended: true, position_s: Number.isFinite(el.duration) ? el.duration : get(state).position_s });
    },
    durationchange: () => set({ duration_s: Number.isFinite(el.duration) ? el.duration : null }),
    timeupdate: () => { if (get(state).url) set({ position_s: el.currentTime }); },   // not the old track's, while the next resolves
    error: () => set({ playing: false, loading: false, error: CANT_PLAY }),
  };
  for (const [k, fn] of Object.entries(on)) el.addEventListener(k, fn);
  return () => {
    for (const [k, fn] of Object.entries(on)) el.removeEventListener(k, fn);
    if (audio === el) audio = null;
  };
}

const cantPlay = (): void => state.update((s) => ({ ...s, playing: false, loading: false, error: CANT_PLAY }));
const titleOf = (it: QueueItem): string => artistTitle(it.artist, it.title);

/** A single sound with no queue (the gallery); it ends any queue. */
function play(o: { url: string; title: string; track_id?: string | null }): void {
  if (!audio) return;
  turn++;
  resolver = null;
  claim();
  if (audio.src !== o.url) {
    audio.src = o.url;
    state.set({ ...EMPTY, url: o.url, title: o.title, track_id: o.track_id ?? null, loading: true });
  } else state.update((s) => ({ ...s, queue: null, hidden: false, ended: false }));
  audio.play().catch(cantPlay);
}

/**
 * Starts a queue from a snapshot of a list. `resolve` runs for each item when it is about to play. Starting one
 * while another is up keeps the bar hidden if it was hidden; shuffle starts off. ▶ after the last track
 * starts the list again from its top (same source, resolve and shuffle).
 */
function playQueue(o: { items: QueueItem[]; start: number; source: QueueSource; resolve: Resolve }): void {
  if (!audio || o.items.length === 0) return;
  resolver = o.resolve;
  begin(o.items, o.start, o.source, false);
}

/** Plays the item at position `at` of the queue's order. A resolve that fails sets the error and stays put. */
async function playAt(at: number): Promise<void> {
  const q0 = get(state).queue;
  const el = audio;
  const resolve = resolver;
  if (!q0 || !el || !resolve) return;
  const q = goTo(q0, at);
  const item = current(q);
  const mine = ++turn;
  claim();
  el.pause();
  state.update((s) => ({ ...s, queue: q, ended: false, url: null, title: titleOf(item), track_id: item.track_id,
    playing: false, loading: true, position_s: 0, duration_s: item.duration_s, error: null }));
  let url: string | null = null;
  try { url = await resolve(item.track_id); } catch { url = null; }
  if (mine !== turn) return;
  if (!url) { cantPlay(); return; }
  el.src = url;
  state.update((s) => ({ ...s, url }));
  if (owner?.id !== ME) return;   // a clip took the sound while we resolved: stay loaded, paused at the start
  el.play().catch(() => { if (mine === turn) cantPlay(); });
}

function pause(): void { audio?.pause(); }
function toggle(): void {
  if (!audio) return;
  const s = get(state);
  if (s.queue) {
    if (s.ended) { begin(s.queue.items, 0, s.queue.source, s.queue.shuffle); return; }
    if (s.error || !s.url) return;   // can't play (the button is grey) or the next item is still resolving
  }
  if (audio.paused) {
    claim();
    audio.play().catch(() => state.update((p) => ({ ...p, error: CANT_PLAY })));
  } else audio.pause();
}
/** A fresh queue from `start`, keeping a hidden bar hidden (`hidden` is only ever true while a queue is up). */
function begin(items: QueueItem[], start: number, source: QueueSource, shuffle: boolean): void {
  const hidden = get(state).hidden;
  state.set({ ...EMPTY, queue: shuffled(makeQueue(items, start, source), shuffle), hidden });
  void playAt(get(state).queue!.at);
}
function seek(s: number): void {
  if (!audio || !Number.isFinite(s) || (get(state).queue && !get(state).url)) return;   // nothing loaded yet
  audio.currentTime = Math.max(0, s);
  state.update((p) => ({ ...p, position_s: Math.max(0, s) }));   // the bar moves now, not at the next timeupdate
}
function next(): void {
  const q = get(state).queue;
  const n = q ? nextIndex(q) : null;
  if (n !== null) void playAt(n);
}
function prev(): void {
  const s = get(state);
  if (!s.queue) return;
  const a = prevAction(s.queue, s.position_s);
  if (a.kind === 'go') { void playAt(a.at); return; }
  if (!audio || s.error || !s.url) { void playAt(s.queue.at); return; }   // nothing loaded to rewind: load it again
  seek(0);
  state.update((p) => ({ ...p, ended: false }));
  claim();
  audio.play().catch(cantPlay);
}
function setShuffle(on: boolean): void {
  state.update((s) => (s.queue ? { ...s, queue: shuffled(s.queue, on) } : s));
}
function hide(): void { state.update((s) => (s.queue ? { ...s, hidden: true } : s)); }
function show(): void { state.update((s) => ({ ...s, hidden: false })); }
/** A clip or a compare took the sound: the queue stays, paused where it is, and ▶ resumes it from there. */
function pauseForClip(): void { audio?.pause(); }
/** Stops the sound and forgets the queue (and a hidden bar). */
function stop(): void {
  turn++;
  resolver = null;
  releaseSound(ME);
  if (audio) {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
  }
  state.set({ ...EMPTY });
}

export const player: Readable<PlayerState> & { play: typeof play; playQueue: typeof playQueue; pause: typeof pause;
  toggle: typeof toggle; seek: typeof seek; next: typeof next; prev: typeof prev; setShuffle: typeof setShuffle;
  hide: typeof hide; show: typeof show; pauseForClip: typeof pauseForClip; stop: typeof stop } =
  { subscribe: state.subscribe, play, playQueue, pause, toggle, seek, next, prev, setShuffle, hide, show,
    pauseForClip, stop };
