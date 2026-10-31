// Fake scenarios of the To-do page (fake mode only). Open them with ?scenario=todo:<name>.
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakeState } from '$lib/bridge/fake/data';
import { dateOnly, makeUpgrade, pathOf, type FakeMatch, type FakeTrack } from '$lib/bridge/fake/data';
import { sameAudio, sameSong } from '$lib/bridge/fake/folders';
import type { Candidate } from '$lib/bridge/types';

// Wrong song? search variants per fake state (scenarios run once per state; the override reads the mode back).
type SearchMode = 'long' | 'slow' | 'none';
const searchMode = new WeakMap<FakeState, SearchMode>();

const LONG = ['Extended Club Mix – Remastered 2024 Edition', 'Official Music Video (HD) [Full Length Version]',
  'Radio Edit · Recorded Live at Ruhr in Love Festival', 'Original Mix', 'Bootleg Remix by Someone With A Long Name',
  'Instrumental', 'VIP Mix'];

function longList(base: Candidate[]): Candidate[] {
  const extra = base.filter((c) => !c.current && !c.rejected && !c.id.startsWith('drm'));
  const more = LONG.map((suffix, i): Candidate => {
    const c = extra[i % extra.length];
    const diff = i % 2 ? 2 : 25 + i * 7;
    return { ...c, id: `long${i}`, key: `${c.source}:long${i}`, title: `${c.title} (${suffix})`,
      artist: `${c.artist} feat. A Very Long Featured Artist Name`, score: Math.max(20, 85 - i * 8),
      duration_s: c.duration_s === null ? null : c.duration_s + diff, length_diff_s: diff };
  });
  return [...base, ...more];   // 6 + 7 = 13
}

/** t2 (Armin Hermann – Get Naughty, Hard_Bounce) with an upgrade measured as `match`; `aiff` false: its file is an
 *  MP3 at 320 kbps, so it can't be swapped. */
function upgradeOf(s: FakeState, match: FakeMatch, aiff: boolean) {
  const t = s.tracks.find((x) => x.track_id === 't2');
  if (!t) return;
  if (!aiff) Object.assign(t, { codec: 'mp3', kbps: 320 });
  t.upgrade = makeUpgrade(t, match, dateOnly(s.now), aiff);
}
/** t2 after "Replace with lossless" (as the fake upgrade() leaves it): the rekordbox check, its undo while `undo`. */
function replaced(s: FakeState, reason: 'swapped' | 'added_as_new', match: FakeMatch, undo = true) {
  const t = s.tracks.find((x) => x.track_id === 't2');
  if (!t) return;
  const old = pathOf(t)!.split('/').pop()!;
  const before: Partial<FakeTrack> = { status: t.status, cutoff_hz: t.cutoff_hz, source: t.source, codec: t.codec,
    upgrade: makeUpgrade(t, match, dateOnly(s.now)), rekordbox_check: null };
  Object.assign(t, { status: 'lossless', cutoff_hz: null, source: 'qobuz', codec: 'flac', upgrade: null });
  t.rekordbox_check = { reason, since: dateOnly(s.now), match, offset_ms: match === 'shifted' ? 12 : 0,
    ...(reason === 'swapped' ? { moved: false } : {}), ...(undo ? { undo: before } : {}),
    old_path: `Superseded/${t.folder}/${reason === 'swapped' ? old.replace(/\.[^.]+$/, ' (lossy)$&') : old}` };
}

const fake: PageFake = {
  scenarios: {
    // The upgrade decision (mockup todo-decisions). Open each with #/todo?track=t2.
    // An AIFF file and the same edit: "In rekordbox" is a choice, Same track picked (Swap).
    'upgrade-aiff-same'(s) { upgradeOf(s, 'exact', true); },
    // As above, the new version 12 ms apart: Same track also says it moves the audio onto the cues.
    'upgrade-aiff-shifted'(s) { upgradeOf(s, 'shifted', true); },
    // An MP3 and the same edit: no choice, a new rekordbox track ("Same track needs an AIFF file").
    'upgrade-mp3-same'(s) { upgradeOf(s, 'exact', false); },
    // An AIFF file, a different edit: no choice ("Same track needs the same edit").
    'upgrade-different'(s) { upgradeOf(s, 'different', true); },
    // An MP3 the measurement couldn't compare: no choice ("Same track needs a measured match").
    'upgrade-unknown'(s) { upgradeOf(s, 'unknown', false); },
    // After the replace: the rekordbox check with its steps, "Replaced with lossless", Done and Undo the replace.
    // Open each with #/todo?track=t2.
    'after-swap'(s) { replaced(s, 'swapped', 'exact'); },
    'after-add-same'(s) { replaced(s, 'added_as_new', 'exact'); },
    'after-add-different'(s) { replaced(s, 'added_as_new', 'different'); },
    // A swap whose undo is gone (no copy kept): Done only, no Undo, no "Undo puts …" line.
    'after-no-undo'(s) { replaced(s, 'swapped', 'exact', false); },
    // Duplicates (open with #/todo?filter=duplicate): a clear winner (the lossless AIFF in a playlist against a
    // 16 kHz copy) is picked; a tie (two lossless AIFFs) picks nothing; both together.
    'duplicates-pick'(s) { s.imp.duplicates = [sameSong()]; },
    'duplicates-tie'(s) { s.imp.duplicates = [sameAudio(2)]; },
    'duplicates'(s) { s.imp.duplicates = [sameAudio(2), sameSong()]; },
    'duplicates-three'(s) { s.imp.duplicates = [sameAudio(3)]; },
    // t2 (Armin Hermann – Get Naughty) has an upgrade that doesn't match: no Swap, "Add as new file" is primary.
    // Open with #/todo?track=t2.
    'upgrade-mismatch'(s) {
      const t = s.tracks.find((x) => x.track_id === 't2');
      if (t) t.upgrade = makeUpgrade(t, 'different', dateOnly(s.now));
    },
    // Nothing left to do: every track's to-do is hidden ("Only hidden tracks are left." with Show hidden).
    'all-hidden'(s) { for (const t of s.tracks) { t.rekordbox_check = null; t.hidden = true; } },
    // Nothing to do at all ("Everything is lossless."): no track lands in a group.
    'all-lossless'(s) { for (const t of s.tracks) { t.rekordbox_check = null; t.in_playlists = false; } },
    // The weak files left every playlist, so Weak has nothing: opened with #/todo?filter=weak, the strip keeps the
    // chosen "Weak 0" (no dot: a 0 signals nothing) beside the groups that still have to-dos.
    'no-weak'(s) {
      for (const t of s.tracks) if (t.status === 'not_lossless' && (t.cutoff_hz ?? 22000) <= 17000) t.in_playlists = false;
    },
    // t17 (a weak file) sits on a drive that is away: the panel says "Offline: connect the drive" where its spectrum would
    // be and keeps the player off. Open with #/todo?track=t17.
    offline(s) {
      const t = s.tracks.find((x) => x.track_id === 't17');
      if (t) t.away = 'offline';
    },
    // Wrong song?: 12 candidates with long titles.
    'long-candidates'(s) { searchMode.set(s, 'long'); },
    // Wrong song?: the search takes 6 s.
    'search-slow'(s) { searchMode.set(s, 'slow'); },
    // Wrong song?: nothing found.
    'no-candidates'(s) { searchMode.set(s, 'none'); },
  },
  overrides: {
    search_candidates: (ctx, base) => async (track_id: string) => {
      const mode = searchMode.get(ctx.s);
      if (mode === 'slow') await ctx.later(5100, () => null);   // + the base's 0.9 s
      const r = await base(track_id);
      if (!mode || mode === 'slow' || !r.ok) return r;
      if (mode === 'none') return { ...r, candidates: [], notes: [] };
      return { ...r, candidates: longList(r.candidates) };
    },
  },
};
export const { scenarios, overrides } = fake;
export default fake;
