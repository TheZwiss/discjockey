// Fake mode: the songs behind the Convert / Rename / Make all AIFF scenarios of the Library and To-do pages (issue 33
// stage D, D7b). Data only: `aiffSet` turns the 24 songs of the plain scenarios' Music folder into the files a DJ's own
// folder holds (FLAC, ALAC, AIFFs with tags that are or aren't right, lossy files, files CDJs refuse); the helpers
// below leave a finished Convert or Rename behind (the file's new facts, its check, the batch record). Nothing here
// runs a job: the fake bridge's `aiff_batch` does that when the page asks.
import type { SeedBatch, FakeAudio, FakeState, FakeTrack } from './data';
import { pathOf } from './data';
import { applyItem, planOf } from './convert';

/** The folder of the plain scenarios' own songs (folders.ts seedImport), the page `#/library/folder/<MUSIC_ROUTE>`. */
export const MUSIC_DIR = '/Volumes/Example Drive/Music';
export const MUSIC_ROUTE = `#/library/folder/${encodeURIComponent(MUSIC_DIR)}`;
/** The batch scope string of a Make all over the Music folder (`library:<view>:<key>`). */
export const MUSIC_SCOPE = `library:folder:${MUSIC_DIR}`;

const AIFF16 = (tagsClean: boolean): FakeAudio => ({ codec: 'pcm_s16be', rate: 44100, bits: 16, kbps: null, ext: 'aiff', tagsClean });
const flac = (rate: number, bits: number): FakeAudio => ({ codec: 'flac', rate, bits, kbps: null, ext: 'flac' });
const lossy = (codec: string, kbps: number, rate: number, ext: string): FakeAudio => ({ codec, rate, bits: null, kbps, ext });

/** Which of the 24 songs becomes which file (`own:<n>`): its stored facts, a file name that is not "Artist - Title" (a
 *  downloader's, a track number) where the song needs its clean name, and the quality a lossy file measured. */
type Spec = { audio?: FakeAudio; messy?: 'underscores' | 'track' | 'free'; cutoff?: number; cloud?: boolean; inRekordbox?: false };
export const SET: Record<number, Spec> = {
  // FLAC → AIFF (a 24-bit 96 kHz, a CD rip), ALAC, an AIFF above 16-bit / 44.1 kHz, an AIFF with the wrong tags
  1: { audio: flac(96000, 24) },
  2: { audio: flac(44100, 16) },
  4: { audio: { codec: 'alac', rate: 44100, bits: 16, kbps: null, ext: 'm4a' } },
  5: { audio: { codec: 'pcm_s24be', rate: 96000, bits: 24, kbps: null, ext: 'aiff' } },
  6: { audio: AIFF16(false) },
  // clean AIFFs: two with a messy name (Clean name only), one with its clean name already (nothing to do)
  7: { audio: AIFF16(true), messy: 'underscores' },
  8: { audio: AIFF16(true) },
  9: { audio: AIFF16(true), messy: 'track' },
  // lossy files: an AIFF made from them sounds the same and takes 5-10 times the space
  10: { audio: lossy('mp3', 256, 44100, 'mp3'), cutoff: 19000 },
  11: { audio: lossy('aac', 256, 44100, 'm4a'), cutoff: 20000 },
  12: { audio: lossy('mp3', 320, 44100, 'mp3'), cutoff: 20000 },
  // CDJs refuse or stutter on these (To-do's group): rate, bit depth, format; one sits in Cloud Library Sync
  13: { audio: flac(192000, 24) },
  14: { audio: { codec: 'pcm_f32le', rate: 44100, bits: 32, kbps: null, ext: 'wav' } },
  15: { audio: lossy('opus', 128, 48000, 'opus'), cutoff: 16000 },
  16: { audio: flac(176400, 24), cloud: true },
  17: { audio: { codec: 'pcm_s24be', rate: 192000, bits: 24, kbps: null, ext: 'aiff' } },
  18: { audio: lossy('vorbis', 192, 44100, 'ogg'), cutoff: 19000 },
  // a FLAC rekordbox has no track for
  20: { audio: flac(44100, 16), inRekordbox: false },
};
/** The CDJ group of `SET`: what To-do lists under "Won't play well on CDJs" (own:16 waits: Cloud Library Sync). */
export const CDJ_IDS = [13, 14, 15, 16, 17, 18].map((n) => `own:${n}`);

const MESSY = {
  underscores: (t: FakeTrack) => `${t.artist}_-_${t.title}_(Original_Mix)`.replace(/ /g, '_'),
  track: (t: FakeTrack) => `07 ${t.artist} - ${t.title}`,
  free: (t: FakeTrack) => `${t.artist} - ${t.title} [FREE DL]`,
};

/** The track `own:<n>` of the plain scenarios. */
export function ownTrack(s: FakeState, n: number | string): FakeTrack {
  const t = s.tracks.find((x) => x.track_id === `own:${n}`);
  if (!t) throw new Error(`own:${n} is not in this scenario`);
  return t;
}

/** The Music folder as a DJ's own folder is: see `SET`. The other songs stay the 24-bit WAVs the plain scenarios have. */
export function aiffSet(s: FakeState): void {
  for (const [n, spec] of Object.entries(SET)) {
    const t = ownTrack(s, n);
    if (spec.audio) {
      t.audio = spec.audio;
      const isLossy = spec.audio.kbps !== null && spec.audio.codec !== 'flac' && spec.audio.codec !== 'alac';
      if (isLossy) Object.assign(t, { status: 'not_lossless', cutoff_hz: spec.cutoff ?? 20000, kbps: spec.audio.kbps ?? undefined });
    }
    if (spec.messy) t.file = `${t.dir}/${MESSY[spec.messy](t)}.${t.audio?.ext ?? 'aiff'}`;
    if (spec.cloud) t.cloud = true;
    if (spec.inRekordbox === false) t.inRekordbox = false;
  }
}

/** The Music folder with nothing left to change: every file is a clean AIFF with its clean name or a lossy one (the Make
 *  all view's "Every lossless file here is a clean AIFF already."). */
export function aiffClean(s: FakeState): void {
  aiffSet(s);
  for (const t of s.tracks.filter((x) => x.track_id.startsWith('own:'))) {
    const a = t.audio ?? { codec: 'pcm_s24le', rate: 44100, bits: 24, kbps: null };
    if (a.kbps !== null && a.codec !== 'flac' && a.codec !== 'alac') continue;   // a lossy file stays as it is
    t.audio = AIFF16(true);
    t.file = `${t.dir}/${t.artist} - ${t.title}.aiff`;
    t.cloud = undefined;
  }
}

/** Leave a finished Convert (or Rename, for a clean AIFF) of `ids` behind, as batch `batch` made it: the files'
 *  new facts, their checks and undo records. Set the fake's rekordbox first: a file it holds gets a rekordbox part. */
export function finished(s: FakeState, ids: string[], batch: number): void {
  const r = planOf(s, { kind: 'tracks', tracks: ids });
  if ('refused' in r) throw new Error(r.refused);
  if (r.plan.items.length !== ids.length) throw new Error(`not every file can run: ${JSON.stringify(r.plan.skipped)}`);
  for (const item of r.plan.items) applyItem(s, ownTrack(s, item.track.slice(4)), item, batch);
}

/** The seed of a batch whose items are `done` (finished first, see `finished`) and `planned` (left for Resume). */
export function seedBatch(s: FakeState, scope: string, state: 'stopped' | 'done', done: string[], planned: string[],
  startedBy: SeedBatch['started_by'] = 'user'): void {
  const batch = (s.batches?.length ?? 0) + 1;
  const action = (id: string): 'convert' | 'rename' => {
    const t = s.tracks.find((x) => x.track_id === id)!;
    return t.audio?.tagsClean && pathOf(t) !== `${t.dir}/${t.artist} - ${t.title}.aiff` ? 'rename' : 'convert';
  };
  const items = [...done, ...planned].map((id): SeedBatch['items'][number] =>
    ({ track: id, action: action(id), state: done.includes(id) ? 'done' : 'planned' }));
  if (done.length) finished(s, done, batch);
  s.batches = [...(s.batches ?? []), { kind: 'convert', scope, state, started_by: startedBy, items }];
}
