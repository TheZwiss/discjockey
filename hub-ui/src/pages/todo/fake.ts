// Fake scenarios of the To-do page (fake mode only). Open them with ?scenario=todo:<name>.
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakeState } from '$lib/bridge/fake/data';
import { dateOnly, makeUpgrade, pathOf, qualityOf, type FakeMatch, type FakeTrack } from '$lib/bridge/fake/data';
import { markRefused, markWaiting, seedUpgrades } from '$lib/bridge/fake/auto';
import { sameAudio, sameSong } from '$lib/bridge/fake/folders';
import { aiffSet, seedBatch } from '$lib/bridge/fake/aiffScenes';
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
function replaced(s: FakeState, reason: 'swapped' | 'added_as_new', match: FakeMatch, undo = true, aligned = false) {
  const t = s.tracks.find((x) => x.track_id === 't2');
  if (!t) return;
  const old = pathOf(t)!.split('/').pop()!;
  const before: Partial<FakeTrack> = { status: t.status, cutoff_hz: t.cutoff_hz, source: t.source, codec: t.codec,
    upgrade: makeUpgrade(t, match, dateOnly(s.now)), rekordbox_check: null };
  Object.assign(t, { status: 'lossless', cutoff_hz: null, source: 'qobuz', codec: 'flac', upgrade: null });
  t.rekordbox_check = { reason, since: dateOnly(s.now), match, offset_ms: match === 'shifted' ? 12 : 0,
    ...(reason === 'swapped' ? { moved: false } : { aligned }), ...(undo ? { undo: before } : {}),
    old_path: `Superseded/${t.folder}/${reason === 'swapped' ? old.replace(/\.[^.]+$/, ' (lossy)$&') : old}` };
}

/** `n` more tracks in the playlists wait with a lossless version of the same edit (Upgrade ready grows for the
 *  multi-select states, plan stage B §6.5): every other one in a file that isn't an AIFF, so Same track converts it. */
function moreUpgrades(s: FakeState, n: number): FakeTrack[] {
  const more = s.tracks.filter((t) => t.in_playlists && !t.upgrade && !t.hidden && !t.rekordbox_check && !t.away
    && qualityOf(t) !== 'missing').slice(0, n);
  more.forEach((t, i) => {
    if (i % 2) Object.assign(t, { codec: 'mp3', kbps: 320 });
    t.upgrade = makeUpgrade(t, 'exact', dateOnly(s.now), i % 2 === 0);
  });
  return more;
}

/** A user's own file names, as their files come (a title alone, a downloader's underscores, a track number): the
 *  batch rows' second line is the file's name, which is not always "Artist - Title". The old and the new file share
 *  the stem (a Same track swap keeps the name, a convert keeps the stem). */
function userStem(t: FakeTrack, i: number): string {
  const n = String(3 + i * 4).padStart(2, '0');
  return [t.title, `${t.artist}_-_${t.title}_(Original_Mix)`.replace(/ /g, '_'), `${t.artist} - ${t.title}`,
    `${n} ${t.artist} - ${t.title}`][i % 4];
}

/** What a Same track batch leaves (as the fake's upgrade() does, plan stage B §6.4): `n` tracks of the playlists
 *  upgraded in batch 7, each with its check and undo record; every other one was an MP3 (a new AIFF, `repointed`),
 *  the rest AIFFs swapped in place. Each file sits in its playlist's folder (the row's folder, the card's "in
 *  Library/…" and "Superseded/…" agree) under a name of the user's own. Every batch shot has four tracks, so the
 *  to-do totals agree between them. `tune` changes a track's check after (kept fields, Reload Tag, not in rekordbox). */
function batchChecks(s: FakeState, n: number, tune: (c: NonNullable<FakeTrack['rekordbox_check']>, i: number) => void = () => {}):
  FakeTrack[] {
  const some = s.tracks.filter((t) => t.in_playlists && !t.upgrade && !t.hidden && !t.rekordbox_check && !t.away
    && qualityOf(t) !== 'missing' && qualityOf(t) !== 'lossless').slice(0, n);
  some.forEach((t, i) => {
    const mp3 = i % 2 === 1;
    const stem = userStem(t, i);
    const old = `${stem}.${mp3 ? 'mp3' : 'aiff'}`;
    const before: Partial<FakeTrack> = { status: t.status, cutoff_hz: t.cutoff_hz, source: t.source, codec: t.codec,
      upgrade: makeUpgrade(t, 'exact', dateOnly(s.now), !mp3), rekordbox_check: null };
    Object.assign(t, { status: 'lossless', cutoff_hz: null, source: 'qobuz', codec: 'flac', upgrade: null,
      file: `Library/${t.folder}/${stem}.aiff` });
    delete t.at;
    t.rekordbox_check = { reason: mp3 ? 'repointed' : 'swapped', since: dateOnly(s.now), match: 'exact', offset_ms: 0,
      ...(mp3 ? { aligned: true } : { moved: false }), reload_tag: false, rekordbox: { entries: 1, kept: [] }, batch: 7,
      undo: before, old_path: `Superseded/${t.folder}/${mp3 ? old : old.replace(/\.aiff$/, ' (lossy).aiff')}` };
    tune(t.rekordbox_check, i);
  });
  return some;
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
    // Same track for an MP3 when rekordbox's library can't be opened: no choice, a new track, and why.
    'upgrade-unreadable'(s) { upgradeOf(s, 'exact', false); s.rekordbox_state = 'unreadable'; },
    // ... and with no rekordbox on this Mac: "a new track", the clean AIFF (Replace runs Same track's convert).
    'upgrade-no-rekordbox'(s) { upgradeOf(s, 'exact', false); s.rekordbox_state = 'none'; },
    // Several upgrades (open with #/todo?filter=upgrade_ready): three more of the same edit, the last on a drive that
    // isn't connected, so the group mixes all three kinds (Same track, a different edit, waits for something else).
    'upgrade-group'(s) { const m = moreUpgrades(s, 3); if (m[2]) m[2].away = 'offline'; },
    // The same group, each track of a batch taking 2.5 s: long enough to see it run and to stop it.
    'upgrade-slow'(s) { moreUpgrades(s, 3); s.batchStep = 2500; },
    // A batch whose full check skips one track (timing): the end lists it with its reason.
    'upgrade-skips'(s) { const m = moreUpgrades(s, 3); s.batchStep = 400; if (m[1]) s.batchSkip = { [m[1].track_id]: 'timing' }; },
    // A batch where every track is skipped (changed meanwhile): refused, every reason listed.
    'upgrade-refused'(s) {
      const m = moreUpgrades(s, 2);
      s.batchStep = 300;
      s.batchSkip = Object.fromEntries(['t2', ...m.map((t) => t.track_id)].map((id) => [id, 'changed']));
    },
    // After the replace: the rekordbox check with its steps, "Replaced with lossless", Done and Undo the replace.
    // Open each with #/todo?track=t2.
    'after-swap'(s) { replaced(s, 'swapped', 'exact'); },
    // New track rendered lined up with rekordbox's timeline of the old file: the cues fit to the sample.
    'after-add-same'(s) { replaced(s, 'added_as_new', 'exact', true, true); },
    // A record from before the lined-up render (or one whose timing was unknown): the download was only renamed.
    'after-add-shifted-old'(s) { replaced(s, 'added_as_new', 'shifted', true, false); },
    'after-add-different'(s) { replaced(s, 'added_as_new', 'different'); },
    // A swap whose undo is gone (no copy kept): Done only, no Undo, no "Undo puts …" line.
    'after-no-undo'(s) { replaced(s, 'swapped', 'exact', false); },
    // The rekordbox checks of a Same track batch (plan stage B §6.4), one row "3 tracks upgraded" in Check in
    // rekordbox (open with #/todo?filter=rekordbox_check): its card with the steps, a row per track, Done and Undo all.
    'check-batch'(s) { batchChecks(s, 4); },
    // ... with what the write kept as the user edited it, a track whose text Discjockey couldn't write (Reload Tag for
    // it, by name) and a file rekordbox doesn't have.
    'check-batch-kept'(s) {
      batchChecks(s, 4, (c, i) => {
        if (i === 0) c.rekordbox = { entries: 1, kept: ['title'] };
        if (i === 1) c.rekordbox = { entries: 1, kept: ['artist', 'comment'] };
        if (i === 2) c.reload_tag = true;
        if (i === 3) c.rekordbox = { entries: 0, kept: [] };
      });
    },
    // ... where Undo all can't put one back (relocated in rekordbox since): its row says why, the foot how many.
    'check-batch-undo-refused'(s) {
      const b = batchChecks(s, 4);
      if (b[1]) s.undoRefuse = { [b[1].track_id]: "This track was moved or removed in rekordbox since the replace, so Discjockey can't put it back safely. Nothing was changed." };
    },
    // ... with rekordbox open: Undo all puts nothing back and says to quit rekordbox (design §8).
    'check-batch-rekordbox-open'(s) { batchChecks(s, 4); s.rekordbox_running = true; },
    // Single Same track checks (batches of one): t12 an AIFF swapped in place, t15 an MP3 that became a new AIFF
    // (`repointed`), each its own single card. Open with #/todo?track=t15.
    'check-repointed'(s) { batchChecks(s, 2, (c, i) => { c.batch = 8 + i; }); },
    // Auto-upgrade (issue 33 stage C). Upgrade ready (#/todo?filter=upgrade_ready) with Get Naughty and four more of the same
    // edit; the first three were met by a sync with rekordbox open: "Waits for rekordbox to be closed" (open one with
    // #/todo?track=t15, then t17 and t22; t24 and Get Naughty are plain).
    'auto-waits'(s) { seedUpgrades(s, 4).slice(0, 3).forEach(markWaiting); },
    // ... five parked upgrades the sync's last phase refused, one per reason (timing, not analysed, Cloud Library Sync, space,
    // couldn't compare): "{Reason} · not upgraded at your sync" in their rows, the reason's sentence in their panel.
    'auto-refused'(s) {
      const reasons = ['timing', 'not_analysed', 'cloud', 'space', 'needs_choice'] as const;
      seedUpgrades(s, reasons.length).forEach((t, i) => markRefused(s, t, reasons[i]));
    },
    // A Same track batch of the sync's last phase (open with #/todo?filter=rekordbox_check): its card is named from the
    // sync ("4 tracks upgraded", "Upgraded during your sync", "Undo all from this sync").
    'auto-batch'(s) { batchChecks(s, 4); s.batchStartedBy = { 7: 'auto_upgrade' }; },
    // Duplicates (open with #/todo?filter=duplicate): a clear winner (the lossless AIFF in a playlist against a
    // 16 kHz copy) is picked; a tie (two lossless AIFFs) picks nothing; both together.
    'duplicates-pick'(s) { s.imp.duplicates = [sameSong(s)]; },
    'duplicates-tie'(s) { s.imp.duplicates = [sameAudio(2)]; },
    'duplicates'(s) { s.imp.duplicates = [sameAudio(2), sameSong(s)]; },
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
    // ---- Won't play well on CDJs and the checks of Convert and Rename (issue 33 stage D, plan §6.4 S2) ----
    // The Music folder of aiffScenes.aiffSet: To-do's CDJ group holds own:13 FLAC 24-bit 192 kHz, own:14 WAV 32-bit float,
    // own:15 Opus, own:16 FLAC 176.4 kHz (in Cloud Library Sync: it waits), own:17 AIFF 24-bit 192 kHz, own:18 Ogg Vorbis.
    // The group (#/todo?filter=cdj): six rows with their short reasons, "Convert all · 5".
    cdj(s) { aiffSet(s); },
    // One item's panel (#/todo?filter=cdj&track=own%3A13): the warn note, the AIFF card, "Convert to AIFF".
    'cdj-item'(s) { aiffSet(s); },
    // Several rows picked (open the group, select own:13, own:14, own:15): the batch panel "3 files for CDJs", "Make 3 files AIFF".
    'cdj-multi'(s) { aiffSet(s); },
    // The whole group selected (click "Convert all · 5"): "6 files for CDJs", "Convert 5 to AIFF", one waits.
    'cdj-all'(s) { aiffSet(s); },
    // A Convert all that was stopped after own:13 and own:14: the group head says "Resume · 4 left".
    'cdj-resume'(s) {
      aiffSet(s);
      seedBatch(s, 'todo:cdj', 'stopped', ['own:13', 'own:14'], ['own:15', 'own:17', 'own:18'], 'cdj_all');
    },
    // The check of a Convert (#/todo?filter=rekordbox_check&track=own%3A13): "Converted to AIFF", the USB step, Done and Undo.
    'check-converted'(s) { aiffSet(s); seedBatch(s, 'todo:selection', 'done', ['own:13'], []); },
    // ... for a file rekordbox has no track for (own:20 FLAC): the text's first sentence and the "not in your rekordbox collection" line.
    'check-converted-no-rekordbox'(s) { aiffSet(s); seedBatch(s, 'todo:selection', 'done', ['own:20'], []); },
    // The check of a clean name (#/todo?filter=rekordbox_check&track=own%3A7): the text, no steps.
    'check-renamed'(s) { aiffSet(s); seedBatch(s, 'todo:selection', 'done', ['own:7'], []); },
    // A Convert all of three files (#/todo?filter=rekordbox_check): "3 tracks", "{day} · Made AIFF", the card lists each with its new name.
    'check-convert-batch'(s) { aiffSet(s); seedBatch(s, 'todo:cdj', 'done', ['own:13', 'own:14', 'own:17'], [], 'cdj_all'); },
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
