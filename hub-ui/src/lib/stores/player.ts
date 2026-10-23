// One sound at a time (plan 64.5): one hidden <audio> in App.svelte. Starting any sound stops the previous one,
// including a ComparePlayer (which registers itself through claimSound).
import { writable, type Readable } from 'svelte/store';

export type PlayerState = { url: string | null; title: string; track_id: string | null; playing: boolean;
  loading: boolean; position_s: number; duration_s: number | null; error: string | null };
const EMPTY: PlayerState = { url: null, title: '', track_id: null, playing: false, loading: false, position_s: 0,
  duration_s: null, error: null };
export const CANT_PLAY = "Can't play this file.";

const state = writable<PlayerState>({ ...EMPTY });
let audio: HTMLAudioElement | null = null;
let stopAfter: number | null = null;
let owner: { id: symbol; stop: () => void } | null = null;
const ME = Symbol('player');

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

/** App.svelte hands its hidden <audio> element over once. */
export function attachAudio(el: HTMLAudioElement): () => void {
  audio = el;
  const set = (p: Partial<PlayerState>) => state.update((s) => ({ ...s, ...p }));
  const on: Record<string, () => void> = {
    loadstart: () => set({ loading: true, error: null }),
    canplay: () => set({ loading: false }),
    playing: () => set({ playing: true, loading: false }),
    pause: () => set({ playing: false }),
    ended: () => set({ playing: false, position_s: 0 }),
    durationchange: () => set({ duration_s: Number.isFinite(el.duration) ? el.duration : null }),
    timeupdate: () => {
      set({ position_s: el.currentTime });
      if (stopAfter !== null && el.currentTime >= stopAfter) { el.pause(); stopAfter = null; }
    },
    error: () => set({ playing: false, loading: false, error: CANT_PLAY }),
  };
  for (const [k, fn] of Object.entries(on)) el.addEventListener(k, fn);
  return () => {
    for (const [k, fn] of Object.entries(on)) el.removeEventListener(k, fn);
    if (audio === el) audio = null;
  };
}

function play(o: { url: string; title: string; track_id?: string | null; stop_after_s?: number }): void {
  if (!audio) return;
  claimSound(ME, () => stop());
  stopAfter = o.stop_after_s ?? null;
  if (audio.src !== o.url) {
    audio.src = o.url;
    state.set({ ...EMPTY, url: o.url, title: o.title, track_id: o.track_id ?? null, loading: true });
  }
  audio.play().catch(() => state.update((s) => ({ ...s, playing: false, loading: false, error: CANT_PLAY })));
}
function pause(): void { audio?.pause(); }
function toggle(): void {
  if (!audio) return;
  if (audio.paused) {
    claimSound(ME, () => stop());
    audio.play().catch(() => state.update((s) => ({ ...s, error: CANT_PLAY })));
  } else audio.pause();
}
function seek(s: number): void {
  if (!audio || !Number.isFinite(s)) return;
  audio.currentTime = Math.max(0, s);
  state.update((p) => ({ ...p, position_s: Math.max(0, s) }));   // the bar moves now, not at the next timeupdate
}
function stop(): void {
  releaseSound(ME);
  if (audio) {
    audio.pause();
    audio.removeAttribute('src');
    audio.load();
  }
  stopAfter = null;
  state.set({ ...EMPTY });
}

export const player: Readable<PlayerState> & { play: typeof play; pause: typeof pause; toggle: typeof toggle;
  seek: typeof seek; stop: typeof stop } = { subscribe: state.subscribe, play, pause, toggle, seek, stop };
