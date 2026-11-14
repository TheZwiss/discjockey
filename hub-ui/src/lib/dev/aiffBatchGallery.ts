// Gallery only (#/dev/gallery, fake mode): AiffBatchPanel in each of its states, every one a stand-in AiffBatchFlow
// that holds a fixed plan or batch and never asks the bridge (its `load` does nothing; Make, Stop and Resume are the
// real flow's, so a press in the gallery would run against the fake bridge like any page).
import type { AiffPlan, AiffPlanItem, AiffScope } from '../bridge/types';
import { AiffBatchFlow, type AiffRunView } from '../decisions/flows.svelte';
import { scopeKey } from '../decisions/aiffBatchModel';
import type { BatchEnd, RunRow } from '../decisions/decisionModel';

/** A flow that keeps what the gallery gave it. */
class StillAiffFlow extends AiffBatchFlow {
  override async load(): Promise<void> {}
}

const NAMES = ['Armin Hermann - Get Naughty', 'Bounce Brigade - Never Stop Raving', 'Lio Sander - Get Lost',
  'Pegassi - AEIOU', 'DJ Tallboy - The Weekend', 'Neonfalter - Sonnenfinsternis', 'Kaltfront - Ruhrpott Nights',
  'Sefa - Partyraiser', 'Mira Vale - Afterhour', 'Tonwerk - Chrome Loop', 'Hallenbad - Sonntag', 'Volt Nine - Flux',
  'Eisregen - Warmup', 'Sternsucher - Selection 2026'];
const KIND: Record<string, { label: string; from: string; action: 'convert' | 'rename' }> = {
  flac: { label: 'FLAC → AIFF', from: 'FLAC · 24-bit · 96 kHz', action: 'convert' },
  wav: { label: 'WAV → AIFF', from: 'WAV · 24-bit · 44.1 kHz', action: 'convert' },
  alac: { label: 'ALAC → AIFF', from: 'ALAC · 16-bit · 44.1 kHz', action: 'convert' },
  aiff_hires: { label: 'AIFF 24-bit or above 44.1 kHz → 16-bit', from: 'AIFF · 24-bit · 96 kHz', action: 'convert' },
  tags: { label: 'New tags', from: 'AIFF · 16-bit · 44.1 kHz', action: 'convert' },
  name: { label: 'Clean name only', from: 'AIFF · 16-bit · 44.1 kHz', action: 'rename' },
  mp3: { label: 'MP3 → AIFF', from: 'MP3 · 256 kbps', action: 'convert' },
};
const DRIVE = '/Volumes/Example Drive';
const MB = 1_000_000;

function item(n: number, kind: string): AiffPlanItem {
  const k = KIND[kind];
  return { track: `own:${n}`, name: NAMES[n % NAMES.length], action: k.action, kind, from: k.from,
    path: `${DRIVE}/Music/${n}.flac`, new_path: `${DRIVE}/Music/${NAMES[n % NAMES.length]}.aiff`,
    superseded: k.action === 'convert' ? `Superseded/${n}.flac` : null, bytes: k.action === 'convert' ? 52 * MB : 0, cdj: null };
}
function plan(scope: AiffScope, label: string, kinds: [string, number][], o: Partial<AiffPlan> = {}): AiffPlan {
  let n = 1;
  const items = kinds.flatMap(([kind, count]) => Array.from({ length: count }, () => item(n++, kind)));
  const needed = items.reduce((a, i) => a + i.bytes, 0);
  return {
    scope: { ...scope, label } as AiffPlan['scope'], items, skipped: [], waiting: [],
    kinds: kinds.map(([kind, count]) => ({ kind, label: KIND[kind].label, n: count })),
    lossy: 0, total: items.length,
    space: needed ? [{ drive: `${DRIVE}/Music`, needed, free: 412_300 * MB, enough: true }] : [],
    superseded_bytes: Math.round(needed * 0.62), rekordbox: { state: 'ready', running: false, needs_closed: true }, ...o,
  };
}

const SELECTION: AiffScope = { kind: 'tracks', tracks: ['own:1', 'own:2', 'own:3', 'own:4', 'own:5', 'own:6'] };
const VIEW: AiffScope = { kind: 'lossless', view: 'folder', key: `${DRIVE}/Music` };
const LEFT = [
  { track: 'own:5', name: 'Kaltfront - Ruhrpott Nights', reason: 'named_already', message: 'A clean AIFF with its clean name already.' },
  { track: 'own:6', name: 'Neonfalter - Sonnenfinsternis', reason: 'cloud',
    message: "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet. Nothing was changed." },
];
const WAITING = [{ reason: 'away', message: "The file's drive isn't connected, so nothing was changed.", n: 2 },
  { reason: 'cloud', message: "This track is in rekordbox's Cloud Library Sync, which Discjockey doesn't change yet. Nothing was changed.", n: 1 }];

function ready(scope: AiffScope, p: AiffPlan): StillAiffFlow {
  const f = new StillAiffFlow();
  f.read = { key: scopeKey(scope), phase: 'ready', plan: p, message: '' };
  return f;
}
const row = (n: number, state: RunRow['state'], text: string | null = null): RunRow =>
  ({ track_id: `own:${n}`, name: NAMES[n % NAMES.length], sub: n % 3 ? 'FLAC → AIFF' : 'WAV → AIFF', cover_url: null, state, text });
function ran(view: Omit<AiffRunView, 'scope' | 'stopping' | 'renames' | 'again'>, again = false): StillAiffFlow {
  const f = new StillAiffFlow();
  f.view = { ...view, scope: null, stopping: false, renames: false, again: again ? () => {} : null };
  return f;
}
const end = (o: Partial<BatchEnd>): BatchEnd => ({ mode: 'swap', kind: 'done', done: 0, total: 0, message: '', resume: null, ...o });

export type GalleryAiff = { key: string; cap: string; scope: AiffScope; flow: AiffBatchFlow; origin?: 'library' | 'todo'; label?: string };
export function galleryAiffPanels(): GalleryAiff[] {
  const loading = new StillAiffFlow();
  loading.read = { key: scopeKey(SELECTION), phase: 'loading', plan: null, message: '' };
  const cdj: AiffScope = { kind: 'cdj' };
  return [
    { key: 'selection', cap: 'Six selected, up to 8 files: each file with its kind, then the ones left as they are', scope: SELECTION,
      flow: ready(SELECTION, plan(SELECTION, 'Selection', [['flac', 2], ['aiff_hires', 1], ['name', 1]], { skipped: LEFT })) },
    { key: 'view', cap: 'Make all, more than 8 files: the counts per kind lead, the files fold under Files, the waiting ones by reason', scope: VIEW,
      flow: ready(VIEW, plan(VIEW, 'Music', [['flac', 6], ['wav', 4], ['alac', 1], ['aiff_hires', 2], ['tags', 1], ['name', 3]],
        { waiting: WAITING })) },
    { key: 'loading', cap: 'Reading the plan: the head keeps its height, the list waits in Skeleton rows, the button off', scope: SELECTION, flow: loading },
    { key: 'empty', cap: 'Nothing to change in the view: an EmptyState, no filled button', scope: VIEW,
      flow: ready(VIEW, plan(VIEW, 'Music', [])) },
    { key: 'space', cap: 'A drive short of room: its row and the Hint in the problem tone, the button off', scope: VIEW,
      flow: ready(VIEW, { ...plan(VIEW, 'Music', [['flac', 3], ['wav', 2]]),
        space: [{ drive: `${DRIVE}/Music`, needed: 1_240 * MB, free: 180 * MB, enough: false }] }) },
    { key: 'rekordbox', cap: 'rekordbox open while it holds some of these files: the button off, the reason under it', scope: SELECTION,
      flow: ready(SELECTION, plan(SELECTION, 'Selection', [['flac', 2], ['wav', 2]],
        { rekordbox: { state: 'ready', running: true, needs_closed: true } })) },
    { key: 'lossy', cap: 'Lossy files among them: the info note under the card', scope: SELECTION,
      flow: ready(SELECTION, plan(SELECTION, 'Selection', [['flac', 1], ['mp3', 3]], { lossy: 3 })) },
    { key: 'cdj', cap: 'To-do\'s CDJ group, Convert all: "files for CDJs", "Convert k to AIFF"', scope: cdj, origin: 'todo',
      flow: ready(cdj, plan(cdj, "Won't play well on CDJs", [['flac', 2], ['wav', 1]], { waiting: WAITING.slice(1) })) },
    { key: 'running', cap: 'Running: the number and its bar, the file in work, the rows marked as they pass, Stop', scope: VIEW,
      flow: ran({ phase: 'running', rows: [row(1, 'handled'), row(2, 'handled'), row(3, 'now'), row(4, 'waiting'), row(7, 'waiting')],
        done: 2, total: 5, now: NAMES[3], end: null }) },
    { key: 'ended', cap: 'Ended: the number made AIFF, the ones left as they are with their reasons, Done', scope: VIEW,
      flow: ran({ phase: 'ended', rows: [row(1, 'done'), row(2, 'done'), row(3, 'skipped',
        "Discjockey couldn't line the new file up with your rekordbox track exactly, so nothing was changed. Analyse the track again in rekordbox and try again."), row(4, 'done')],
        done: 3, total: 4, now: null, end: end({ done: 3, total: 4 }) }) },
    { key: 'stopped', cap: 'Stopped by hand: the note counts, the files still to do, Resume · k left', scope: VIEW,
      flow: ran({ phase: 'ended', rows: [row(1, 'done'), row(2, 'done'), row(4, 'waiting'), row(7, 'waiting'), row(8, 'waiting')],
        done: 2, total: 5, now: null, end: end({ kind: 'stopped', done: 2, total: 5, resume: { batch_id: 3, left: 3 } }) }) },
    { key: 'rekordbox-opened', cap: 'rekordbox opened mid-way: design §8\'s words, Resume · k left', scope: VIEW,
      flow: ran({ phase: 'ended', rows: [row(1, 'done'), row(2, 'waiting'), row(4, 'waiting')],
        done: 1, total: 3, now: null, end: end({ kind: 'rekordbox_open', done: 1, total: 3, resume: { batch_id: 4, left: 2 } }) }) },
  ];
}
