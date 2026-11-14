import { describe, expect, it } from 'vitest';
import type {
  DuplicateItem, FileSide, QuestionItem, QuestionPair, Todo, TodoGroupKey, TodoItem, TrackDetail, Upgrade,
} from '$lib/bridge/types';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import {
  dropDecision,
  FILTER_ORDER, actionsFor, segOptions, filterFrom, flatten, headerSub, itemKey, keepSelection, moveSelection, rowDim, rowOff,
  cutoffStat, freeHint, qobuzText, selectAfterHide, selectFromTrack,
  NO_VALUE, compareLines, fileFolder, filePlace, fileName, fileQueue, fileState, keepLabel, linkService, queueRows, rowBadge,
  checkCard, editLine, fileFormat, fileWords, groupIdOf, keepWords, lastFolder, localDay, replaceLabel, replacedCard,
  sinceText, upgradeWays, findHeld, ghostOf, holdApplies, openCount, withHeldItem, type TodoHold,
  batchListStep, checksPanelShows, coalesce, keepPinned, upgradeAllKeys, wholeUpgradeGroup,
  MULTI_GROUPS, cdjAllKeys, cdjGroup, multiCdj, wholeCdjGroup,
} from './todoModel';
import type { RekordboxCheckView } from '$lib/bridge/types';
import { stepChoice } from '$lib/components/choiceModel';
import { cueTone, rowAway } from '$lib/format';

function item(id: string, group: TodoGroupKey, extra: Partial<TodoItem> = {}): TodoItem {
  return { track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'not_lossless',
    quality: 'weak', quality_label: '16.0 kHz', cutoff_hz: 16000, source: 'youtube', source_name: 'YouTube',
    in_playlists: true, own: false, hidden: false, upgrade_ready: false, path: 'Library/Hard_Bounce/A - x.aiff', added: null,
    cover_url: null, group, detail: '', free: false, file_state: 'here', ...extra };
}
function todo(groups: [TodoGroupKey, string[]][]): Todo {
  const chips = { all: 0, rekordbox_check: 0, same_song: 0, duplicate: 0, cdj: 0, upgrade_ready: 0, not_found: 0, weak: 0, good_lossy: 0, fake: 0, other: 0 };
  return { chips, check_tracks: 0, hidden_count: 0, show_hidden: false, empty: null,
    groups: groups.map(([key, ids]) => ({ key, label: key, hint: '', items: ids.map((id) => item(id, key)) })) };
}
function upgrade(extra: Partial<Upgrade> = {}): Upgrade {
  return { file: 'Upgrades ready/Hard_Bounce/A - x.aiff', source: 'qobuz', source_name: 'Qobuz', source_id: 'q1',
    found: '2026-10-16', what: 'lossless version', quality_line: 'Qobuz FLAC · verified lossless', format_line: 'FLAC · lossless',
    alignment: { drift_ms: 0, offset_ms: 0, offset_samples: 0, result: 'exact', text: 'matches exactly' },
    cue_text: 'matches exactly, cues stay', swap_safe: true, swap_possible: true, why_not: null, swap_how: 'in_place',
    rekordbox: { state: 'ready', running: false }, auto_refused: null, auto_waits: false, audio_url: 'u2', ...extra };
}
function detail(extra: Partial<TrackDetail> = {}): TrackDetail {
  return { ...item('t2', 'weak'), file_state: 'here' as const, isrc: null, playlists: ['Hard_Bounce'], in_playlist_count: 1,
    quality_line: 'YouTube OPUS · cutoff 16.0 kHz', source_url: null, track_link: null, next_qobuz_check: null,
    rejected_sources: [], buy_links: { beatport: 'https://b', bandcamp: 'https://c' }, free_downloads: [],
    bought_name: 'Library/Hard_Bounce/A - t2.wav', audio_url: 'u1', upgrade: null, ...extra } as TrackDetail;
}

describe('flatten', () => {
  it('keeps the spec group order and every item, a track in two groups twice', () => {
    const t = todo([['rekordbox_check', ['t5']], ['upgrade_ready', ['t2']], ['not_found', ['t3', 't5']]]);
    expect(flatten(t).map((i) => itemKey(i))).toEqual(['rekordbox_check/t5', 'upgrade_ready/t2', 'not_found/t3',
      'not_found/t5']);
  });

  it('flattens the big fake library in the contract order', async () => {
    const fake = createFakeBridge('big');
    const r = await fake.todo('all', false);
    if (!r.ok) throw new Error('todo failed');
    const flat = flatten(r);
    const order = r.groups.map((g) => g.key);
    expect(order).toEqual(FILTER_ORDER.filter((k) => k !== 'all' && order.includes(k as TodoGroupKey)));
    expect(flat.length).toBe(r.groups.reduce((n, g) => n + g.items.length, 0));
    expect(flat.length).toBeGreaterThan(50);
    const seen = flat.map((i) => i.group);
    expect(seen).toEqual([...seen].sort((a, b) => order.indexOf(a) - order.indexOf(b)));
  });
});

describe('keepSelection after a re-fetch', () => {
  const before = flatten(todo([['upgrade_ready', ['t2']], ['weak', ['t4', 't5', 't6']]]));
  it('keeps the same item', () => {
    const after = flatten(todo([['weak', ['t4', 't5', 't6']]]));
    expect(keepSelection('weak/t5', before, after)).toBe('weak/t5');
  });
  it('follows the same track into another group', () => {
    const after = flatten(todo([['upgrade_ready', ['t2']], ['good_lossy', ['t5']], ['weak', ['t4', 't6']]]));
    expect(keepSelection('weak/t5', before, after)).toBe('good_lossy/t5');
  });
  it('takes the item now at the same position when the track is gone', () => {
    const after = flatten(todo([['upgrade_ready', ['t2']], ['weak', ['t4', 't6']]]));
    expect(keepSelection('weak/t5', before, after)).toBe('weak/t6');
  });
  it('takes the previous one when the gone track was the last', () => {
    const after = flatten(todo([['upgrade_ready', ['t2']], ['weak', ['t4', 't5']]]));
    expect(keepSelection('weak/t6', before, after)).toBe('weak/t5');
  });
  it('is null on an empty list and the first item without a selection', () => {
    expect(keepSelection('weak/t5', before, [])).toBeNull();
    expect(keepSelection(null, [], before)).toBe('upgrade_ready/t2');
  });
});

describe('selection helpers', () => {
  const flat = flatten(todo([['rekordbox_check', ['t5']], ['weak', ['t4', 't5']]]));
  it('moves with ↑/↓ and stops at the ends', () => {
    expect(moveSelection(flat, 'rekordbox_check/t5', 1)).toBe('weak/t4');
    expect(moveSelection(flat, 'weak/t5', 1)).toBe('weak/t5');
    expect(moveSelection(flat, 'rekordbox_check/t5', -1)).toBe('rekordbox_check/t5');
    expect(moveSelection(flat, null, 1)).toBe('rekordbox_check/t5');
  });
  it('selects from ?track= (first item of that track)', () => {
    expect(selectFromTrack(flat, 't5')).toBe('rekordbox_check/t5');
    expect(selectFromTrack(flat, 'nope')).toBeNull();
  });
  it('selects the next item after hiding (the previous one at the end)', () => {
    expect(selectAfterHide(flat, 'weak/t4')).toBe('weak/t5');
    expect(selectAfterHide(flat, 'weak/t5')).toBe('weak/t4');
  });
});

describe('filter strip', () => {
  const chips = { all: 9, rekordbox_check: 0, same_song: 0, duplicate: 0, cdj: 0, upgrade_ready: 2, not_found: 3, weak: 0, good_lossy: 4, fake: 0, other: 0 };
  it('come in spec order with zero ones hidden (All always shown)', () => {
    expect(segOptions(chips, 'all').map((o) => o.key)).toEqual(['all', 'upgrade_ready', 'not_found', 'good_lossy']);
    expect(segOptions({ ...chips, all: 0, upgrade_ready: 0, not_found: 0, good_lossy: 0 }, 'all').map((o) => o.key))
      .toEqual(['all']);
  });
  it('keep the chosen chip even at zero', () => {
    expect(segOptions(chips, 'weak').map((o) => o.key)).toContain('weak');
  });
  it('have labels and counts', () => {
    const o = segOptions(chips, 'all');
    expect(o[0]).toMatchObject({ label: 'All', count: 9, dot: null });
    expect(o.find((x) => x.key === 'not_found')).toMatchObject({ label: 'Not found', count: 3, dot: 'missing' });
    expect(o.find((x) => x.key === 'upgrade_ready')).toMatchObject({ label: 'Upgrades', dot: 'lossless' });
  });
  it('filter comes from ?filter= first, then the saved one', () => {
    expect(filterFrom('not_found', 'weak')).toBe('not_found');
    expect(filterFrom(null, 'weak')).toBe('weak');
    expect(filterFrom('nonsense', 'nonsense')).toBe('all');
  });
});

describe('freeHint', () => {
  const f = { url: 'https://hypeddit.com/x', host: 'hypeddit.com', direct: false, title: 'T', uploader: 'U' };
  it('says what a gate asks for and what it usually gives', () => {
    expect(freeHint([f])).toBe('For a follow, a like or an e-mail · usually WAV or 320 kbps MP3');
    expect(freeHint([{ ...f, direct: true }])).toBe('The artist\'s own file · usually WAV or 320 kbps MP3');
  });
});

describe('actionsFor', () => {
  it('offers Swap only when the swap is safe and possible', () => {
    expect(actionsFor(detail({ upgrade: upgrade() })).upgrade).toEqual({ swap: true, primary: 'swap' });
    expect(actionsFor(detail({ upgrade: upgrade({ swap_safe: false }) })).upgrade).toEqual({ swap: false, primary: 'add_new' });
    expect(actionsFor(detail({ upgrade: upgrade({ swap_possible: false }) })).upgrade).toEqual({ swap: false, primary: 'add_new' });
    expect(actionsFor(detail()).upgrade).toBeNull();
  });
  it('picks the primary action from the match and the file format together', () => {
    // [swap_safe, swap_possible] -> what leads: only an AIFF file that lines up swaps; an MP3 is added as a new file
    // however well it matches
    const cases: [boolean, boolean, 'swap' | 'add_new'][] = [
      [true, true, 'swap'], [true, false, 'add_new'], [false, true, 'add_new'], [false, false, 'add_new'],
    ];
    for (const [swap_safe, swap_possible, primary] of cases) {
      const d = detail({ upgrade: upgrade({ swap_safe, swap_possible }) });
      expect(actionsFor(d).upgrade).toEqual({ swap: primary === 'swap', primary });
      expect(actionsFor(d, 'upgrade_ready').main).toBe(primary);
    }
  });
  it('offers Find a version for missing tracks, Wrong song? otherwise; None of these not for missing', () => {
    const missing = actionsFor(detail({ status: 'missing', quality: 'missing', audio_url: null, path: null }));
    expect(missing.versions).toBe('find');
    expect(missing.noneOfThese).toBe(false);
    expect(missing.listen).toBe(false);
    const lossy = actionsFor(detail());
    expect(lossy.versions).toBe('wrong_song');
    expect(lossy.noneOfThese).toBe(true);
    expect(lossy.listen).toBe(true);
  });
  it('shows the drop zone and buy links only for missing, not lossless and fake lossless', () => {
    for (const status of ['missing', 'not_lossless', 'fake_lossless'] as const) {
      expect(actionsFor(detail({ status })).dropZone).toBe(true);
      expect(actionsFor(detail({ status })).buy).toBe(true);
    }
    expect(actionsFor(detail({ status: 'lossless', quality: 'lossless' })).dropZone).toBe(false);
  });
  it('offers no buy links or drop zone under a lossless version that is ready, but does under a better lossy one', () => {
    const ready = actionsFor(detail({ upgrade: upgrade({ what: 'lossless version' }) }));
    expect([ready.buy, ready.dropZone]).toEqual([false, false]);
    const better = actionsFor(detail({ upgrade: upgrade({ what: 'better version' }) }));
    expect([better.buy, better.dropZone]).toEqual([true, true]);
  });
  it('hides or unhides', () => {
    expect(actionsFor(detail()).hide).toBe('hide');
    expect(actionsFor(detail({ hidden: true })).hide).toBe('unhide');
  });
  it('puts the to-do\'s own action in the panel foot, none for a lossy file', () => {
    expect(actionsFor(detail({ upgrade: upgrade() }), 'upgrade_ready').main).toBe('swap');
    expect(actionsFor(detail({ upgrade: upgrade({ swap_safe: false }) }), 'upgrade_ready').main).toBe('add_new');
    expect(actionsFor(detail(), 'rekordbox_check').main).toBe('rekordbox');
    expect(actionsFor(detail({ status: 'missing', quality: 'missing', audio_url: null, path: null }), 'not_found').main)
      .toBe('find');
    expect(actionsFor(detail({ status: 'lossless', quality: 'lossless' }), 'other').main).toBe('finder');
    expect(actionsFor(detail({ status: 'lossless', quality: 'lossless', file_state: 'offline' }), 'other').listen).toBe(true);   // switched off, no address
    expect(actionsFor(detail({ audio_url: null, file_state: 'file_missing' }), 'weak').listen).toBe(true);
    expect(actionsFor(detail({ audio_url: null }), 'weak').listen).toBe(false);
    expect(actionsFor(detail({ status: 'lossless', quality: 'lossless', file_state: 'folder_missing' }), 'other').main).toBeNull();   // the file isn't there: nothing to show
    expect(actionsFor(detail(), 'weak').main).toBeNull();
    expect(actionsFor(detail({ status: 'fake_lossless' }), 'fake').main).toBeNull();
  });
  it('Other items get Show in Finder, Check in rekordbox items get Done', () => {
    const lossless = detail({ status: 'lossless', quality: 'lossless' });
    expect(actionsFor(lossless, 'other')).toMatchObject({ showInFinder: true, hide: 'hide', rekordboxDone: false });
    expect(actionsFor(lossless, 'rekordbox_check')).toMatchObject({ showInFinder: false, hide: null, rekordboxDone: true });
  });
});

describe('texts', () => {
  it('says when Qobuz checks again', () => {
    expect(qobuzText('2026-10-20')).toBe('not there yet · looks again on 20\u00A0Oct');
    expect(qobuzText('next_sync')).toBe('not there yet · looks again at the next sync');
    expect(qobuzText(null)).toBeNull();
  });
  it('gives the cutoff of a lossy file as a number with what it means', () => {
    expect(cutoffStat({ status: 'not_lossless', cutoff_hz: 20100 }))
      .toEqual({ value: '20.1', label: 'where the highs end · lossless reaches about 22 kHz' });
    expect(cutoffStat({ status: 'not_lossless', cutoff_hz: null })).toEqual({ value: null, label: 'no clear edge in the highs' });
    expect(cutoffStat({ status: 'fake_lossless', cutoff_hz: 16000, path: 'Library/A/x.flac' }))
      .toEqual({ value: '16.0', label: 'where the highs end · a lossy file inside the FLAC' });
    expect(cutoffStat({ status: 'lossless', cutoff_hz: null })).toBeNull();
    expect(cutoffStat({ status: 'missing', cutoff_hz: null })).toBeNull();
  });
  it('header line tells the tracks, the questions about the user\'s own files and the checks in rekordbox', () => {
    const none = { all: 0, rekordbox_check: 0, same_song: 0, duplicate: 0, cdj: 0, upgrade_ready: 0, not_found: 0, weak: 0,
      good_lossy: 0, fake: 0, other: 0 };
    const sub = (chips: Partial<typeof none>, check_tracks = 0) => headerSub({ chips: { ...none, ...chips }, check_tracks });
    // not lossless yet: every group of tracks below lossless, summed (Upgrade ready included)
    expect(sub({ weak: 4, good_lossy: 6, fake: 3, not_found: 3, upgrade_ready: 2, other: 1 })).toEqual(['19 tracks are not lossless yet']);
    expect(sub({ fake: 1 })).toEqual(['1 track is not lossless yet']);
    // the questions' part
    expect(sub({ weak: 16, same_song: 1, duplicate: 1 })).toEqual(['16 tracks are not lossless yet', '2 questions about your files']);
    expect(sub({ weak: 1, same_song: 1 })).toEqual(['1 track is not lossless yet', '1 question about your files']);
    expect(sub({ same_song: 2, duplicate: 1 })).toEqual(['3 questions about your files']);
    // checks only: a batch of 4 and one single check are 5 tracks, not 2 items (chips.rekordbox_check) and never "lossy"
    expect(sub({ all: 2, rekordbox_check: 2 }, 5)).toEqual(['5 tracks to check in rekordbox']);
    expect(sub({ all: 1, rekordbox_check: 1 }, 1)).toEqual(['1 track to check in rekordbox']);
    // a track that is a check and also Weak is one lossy track and one check; chips.all counts it once and is not used
    expect(sub({ all: 1, rekordbox_check: 1, weak: 1 }, 1)).toEqual(['1 track is not lossless yet', '1 track to check in rekordbox']);
    // all three, in order of importance
    expect(sub({ all: 20, rekordbox_check: 2, weak: 14, upgrade_ready: 2, same_song: 1, duplicate: 1 }, 5))
      .toEqual(['16 tracks are not lossless yet', '2 questions about your files', '5 tracks to check in rekordbox']);
    expect(sub({ weak: 3 }, 4)).toEqual(['3 tracks are not lossless yet', '4 tracks to check in rekordbox']);
    expect(sub({ duplicate: 1 }, 1)).toEqual(['1 question about your files', '1 track to check in rekordbox']);
    // nothing left
    expect(sub({})).toEqual(['Nothing to do']);
  });
});

describe('FileDropped decision', () => {
  const ev = (more: Partial<{ track_id: string | null; readable: boolean; message: string }>) =>
    ({ track_id: 't17', name: 'Armin Hermann - Get Naughty.wav', readable: true, message: '', ...more });
  it('adds a readable file dropped on the selected track', () => {
    expect(dropDecision(ev({}), 't17')).toEqual({ do: 'add' });
  });
  it('shows the message in the drop zone when macOS blocked the file', () => {
    expect(dropDecision(ev({ readable: false, message: "macOS didn't let Discjockey read this file." }), 't17'))
      .toEqual({ do: 'message', text: "macOS didn't let Discjockey read this file." });
  });
  it('leaves a drop with nothing selected to the toast', () => {
    expect(dropDecision(ev({ track_id: null, message: 'Select the track this file belongs to, then drop it again.' }),
      null)).toEqual({ do: 'toast' });
  });
  it('ignores a drop meant for another track', () => {
    expect(dropDecision(ev({ track_id: 't2' }), 't17')).toEqual({ do: 'ignore' });
  });
});

// ---------- the import's groups (plan library stage 4, 7.1–7.3) ----------
function side(file_id: number, extra: Partial<FileSide> = {}): FileSide {
  return { file_id, song_key: `local:${file_id}`, path: `/Volumes/Example Drive/Music/A - x${file_id}.aiff`, artist: 'A',
    title: 'x', duration_s: 200, quality: 'lossless', quality_label: 'LOSSLESS', online: true,
    audio_url: `u${file_id}`, in_playlist: false, ...extra };
}
function question(song_key: string, own: number, extra: Partial<QuestionPair> = {}): QuestionItem {
  const pair: QuestionPair = { song_key, own_key: `local:${own}`, why: 'artist', delta_s: null,
    track: { artist: 'Neon Riot', title: 'Hands Up', duration_s: 194, folder: 'Hard_Bounce', link: null },
    file: side(own, { artist: 'Neonriot', title: 'Hands Up', duration_s: 194, quality: 'weak', quality_label: '16.0 kHz' }),
    ...extra };
  return { ...item(song_key, 'same_song'), group: 'same_song', status: 'missing', quality: 'missing',
    quality_label: 'NOT FOUND', pair };
}
function dupe(ids: number[]): DuplicateItem {
  const group_id = `dup:${ids.join('-')}`;
  return { ...item(group_id, 'duplicate'), group: 'duplicate', pair: { group_id, why: 'same_audio', files: ids.map((id) => side(id)), recommended: null, recommended_why: null } };
}
const flatOf = (...items: TodoItem[]) => items;

describe('the import groups on the strip and in navigation', () => {
  it('come right after rekordbox, in the order the sections do', () => {
    expect(FILTER_ORDER.slice(0, 5)).toEqual(['all', 'rekordbox_check', 'same_song', 'duplicate', 'upgrade_ready']);
    const chips = { all: 12, rekordbox_check: 1, same_song: 2, duplicate: 3, cdj: 0, upgrade_ready: 1, not_found: 4, weak: 1,
      good_lossy: 0, fake: 0, other: 0 };
    const o = segOptions(chips, 'all');
    expect(o.map((x) => x.key)).toEqual(['all', 'rekordbox_check', 'same_song', 'duplicate', 'upgrade_ready',
      'not_found', 'weak']);
    expect(o.find((x) => x.key === 'same_song')).toMatchObject({ label: 'Same song?', count: 2, dot: null });
    expect(o.find((x) => x.key === 'duplicate')).toMatchObject({ label: 'Duplicates', count: 3 });
    expect(filterFrom('same_song', 'all')).toBe('same_song');
    expect(filterFrom(null, 'duplicate')).toBe('duplicate');
  });
  it('name a question by its song and file, a duplicate group by its id', () => {
    expect(itemKey(question('q1', 101))).toBe('same_song/q1/local:101');
    expect(itemKey(dupe([201, 202]))).toBe('duplicate/dup:201-202');
    // one song asked about two files: two items
    expect(itemKey(question('q1', 102))).not.toBe(itemKey(question('q1', 101)));
  });
  it('go on to the next question after an answer, never after the song into another group', () => {
    const before = flatOf(question('q1', 101), question('q2', 102), item('t9', 'weak'));
    const after = flatOf(question('q2', 102), item('q1', 'weak'), item('t9', 'weak'));
    expect(keepSelection('same_song/q1/local:101', before, after)).toBe('same_song/q2/local:102');
  });
  it('keep a duplicate group selected when it lost a file to Superseded/ (its id changes)', () => {
    const before = flatOf(dupe([201, 202, 203]), dupe([301, 302]));
    const after = flatOf(dupe([301, 302]), dupe([201, 203]));
    expect(keepSelection('duplicate/dup:201-202-203', before, after)).toBe('duplicate/dup:201-203');
  });
  it('stay on a duplicate when Keep all makes the group vanish, even with a question in its place', () => {
    const before = flatOf(question('q1', 101), dupe([201, 202, 203]), item('t9', 'weak'), dupe([301, 302]));
    const after = flatOf(question('q1', 101), item('t9', 'weak'), dupe([301, 302]));
    expect(keepSelection('duplicate/dup:201-202-203', before, after)).toBe('duplicate/dup:301-302');
    // the last of its kind: the one before it; none left: the item in its place
    expect(keepSelection('duplicate/dup:301-302', flatOf(dupe([201, 202]), dupe([301, 302])), flatOf(dupe([201, 202]))))
      .toBe('duplicate/dup:201-202');
    expect(keepSelection('duplicate/dup:201-202', flatOf(question('q1', 101), dupe([201, 202]), item('t9', 'weak')),
      flatOf(question('q1', 101), item('t9', 'weak')))).toBe('weak/t9');
  });
  it('keep a question on a question after an answer', () => {
    const before = flatOf(item('t1', 'weak'), question('q1', 101), question('q2', 102));
    const after = flatOf(item('t1', 'weak'), question('q2', 102));
    expect(keepSelection('same_song/q2/local:102', before, flatOf(item('t1', 'weak'), question('q3', 103))))
      .toBe('same_song/q3/local:103');
    expect(keepSelection('same_song/q1/local:101', before, after)).toBe('same_song/q2/local:102');
  });
  it('go on to the item in its place when a duplicate group is done', () => {
    const before = flatOf(dupe([201, 202]), dupe([301, 302]), item('t9', 'weak'));
    const after = flatOf(dupe([301, 302]), item('t9', 'weak'));
    expect(keepSelection('duplicate/dup:201-202', before, after)).toBe('duplicate/dup:301-302');
  });
  it('select the item of a file playing in the foot (file:<id>), and a question by its song', () => {
    const flat = flatOf(question('q1', 101), dupe([201, 202]));
    expect(selectFromTrack(flat, 'file:202')).toBe('duplicate/dup:201-202');
    expect(selectFromTrack(flat, 'file:101')).toBe('same_song/q1/local:101');
    expect(selectFromTrack(flat, 'file:999')).toBeNull();
    expect(selectFromTrack(flat, 'q1')).toBe('same_song/q1/local:101');
  });
  it('leave the import items out of the to-do queue', () => {
    const flat = flatOf(question('q1', 101), dupe([201, 202]), item('t9', 'weak'));
    expect(queueRows(flat).map((i) => i.track_id)).toEqual(['t9']);
  });
  it('show a question row with its file\'s quality, every other row with its own', () => {
    expect(rowBadge(question('q1', 101))).toEqual({ quality: 'weak', label: '16.0 kHz' });
    expect(rowBadge(item('t9', 'weak'))).toEqual({ quality: 'weak', label: '16.0 kHz' });
    expect(rowBadge(dupe([1, 2]))).toEqual({ quality: 'weak', label: '16.0 kHz' });
  });
});

describe('the import details', () => {
  it('line the playlist song up with the file, the why\'s line marked', () => {
    const lines = compareLines(question('q1', 101).pair);
    expect(lines.map((l) => [l.key, l.song, l.file, l.differs])).toEqual([
      ['title', 'Hands Up', 'Hands Up', false], ['artist', 'Neon Riot', 'Neonriot', true],
      ['length', '3:14', '3:14', false], ['where', 'Hard_Bounce', 'Example Drive\u00A0› Music', false]]);
    expect(lines[3].fileTitle).toBe('/Volumes/Example Drive/Music/A - x101.aiff');
  });
  it('mark the length for a length why and say "—" for what isn\'t there', () => {
    const q = question('q1', 101, { why: 'no_length' }).pair;
    const len = compareLines({ ...q, file: { ...q.file, duration_s: 0 } }).find((l) => l.key === 'length')!;
    expect(len).toMatchObject({ song: '3:14', file: NO_VALUE, differs: true });
    const noArtist = question('q2', 102, { why: 'no_artist' }).pair;
    const a = compareLines({ ...noArtist, file: { ...noArtist.file, artist: '' } }).find((l) => l.key === 'artist')!;
    expect(a).toMatchObject({ file: NO_VALUE, differs: true });
    const t = compareLines({ ...noArtist, file: { ...noArtist.file, title: '' } })[0];
    expect(t.file).toBe('A - x102.aiff');   // a file with no title tag: its name
  });
  it('give the folder a file is in, home as ~', () => {
    expect(fileFolder('/Users/you/Music/Crates/A - x.aiff')).toBe('~/Music/Crates');
    expect(fileFolder('Library/Hard_Bounce/A - x.aiff')).toBe('Library/Hard_Bounce');
    expect(fileFolder('/x.aiff')).toBe('/');
  });
  it('names a file\'s place as the watched folders do', () => {
    expect(filePlace('/Volumes/Example Drive/Music/Old/A - x.aiff')).toBe('Example Drive\u00A0› Music/Old');
    expect(filePlace('/Volumes/Example Drive/A - x.aiff')).toBe('Example Drive');
    expect(filePlace('/Users/you/Music/Crates/A - x.aiff')).toBe('~/Music/Crates');
    expect(filePlace('Library/Hard_Bounce/A - x.aiff')).toBe('Library/Hard_Bounce');
    expect(fileName('/Volumes/Example Drive/Music/A - x.aiff')).toBe('A - x.aiff');
  });
  it('say Keep both for two files, Keep all for more', () => {
    expect(keepLabel(2)).toBe('Keep both');
    expect(keepLabel(3)).toBe('Keep all');
  });
  it('name the service of a song\'s link', () => {
    expect(linkService('https://open.spotify.com/track/abc')).toBe('Spotify');
    expect(linkService('https://open.qobuz.com/track/1')).toBe('Qobuz');
    expect(linkService('https://example.com/x')).toBeNull();
    expect(linkService(null)).toBeNull();
  });
  it('queue the playable files from the one pressed', () => {
    const files = [side(1), side(2, { online: false }), side(3), side(4, { audio_url: null })];
    const q = fileQueue(files, 3, 'c')!;
    expect(q.items.map((i) => i.track_id)).toEqual(['file:1', 'file:3']);
    expect(q.start).toBe(1);
    expect(q.items[0]).toMatchObject({ artist: 'A', title: 'x', cover_url: 'c', duration_s: 200 });
    expect(q.urls.get('file:3')).toBe('u3');
    expect(fileQueue(files, 2)).toBeNull();
    expect(fileQueue(files, 4)).toBeNull();
  });
  it('read a file\'s ▶ state from the player', () => {
    const p = { track_id: 'file:1', playing: true, loading: false };
    expect(fileState(p, { file_id: 1 })).toBe('playing');
    expect(fileState({ ...p, playing: false, loading: true }, { file_id: 1 })).toBe('loading');
    expect(fileState({ ...p, playing: false }, { file_id: 1 })).toBe('paused');
    expect(fileState(p, { file_id: 2 })).toBe('paused');
  });
  it('get both groups from the fake, every item with its pair and its own key', async () => {
    for (const scenario of ['todo_same_song', 'todo_duplicates_three']) {
      const r = await createFakeBridge(scenario).todo('all', false);
      if (!r.ok) throw new Error('todo failed');
      const flat = flatten(r);
      const imp = flat.filter((i) => i.group === 'same_song' || i.group === 'duplicate');
      expect(imp.length).toBeGreaterThan(1);
      expect(imp.every((i) => !!i.pair)).toBe(true);
      expect(new Set(flat.map(itemKey)).size).toBe(flat.length);
    }
  });
});

describe('a file that is away', () => {
  it('says so in place of the quality badge, as Library does, and dims the row', () => {
    expect(rowAway(item('t1', 'weak', { file_state: 'offline' }))).toBe('offline');
    expect(rowAway(item('t1', 'weak', { file_state: 'folder_missing' }))).toBe('folder_missing');
    expect(rowAway(item('t1', 'weak'))).toBeNull();
    expect(rowAway(item('t1', 'not_found', { file_state: 'no_file' }))).toBeNull();
    expect(rowDim(item('t1', 'weak', { file_state: 'offline' }))).toBe(true);
    expect(rowDim({ ...question('q1', 101), file_state: 'offline' })).toBe(true);
    expect(rowDim(item('t1', 'weak'))).toBe(false);
    expect(rowDim(item('t1', 'weak', { in_playlists: false }))).toBe(true);
  });
});

describe('which rows are dimmed', () => {
  it('only the older kinds dim a track that no playlist holds; questions and duplicate groups never do', () => {
    expect(rowOff(item('t1', 'weak', { in_playlists: false }))).toBe(true);
    expect(rowOff(item('t1', 'weak'))).toBe(false);
    expect(rowOff({ ...question('q1', 101), in_playlists: false })).toBe(false);
    expect(rowOff({ ...dupe([201, 202]), in_playlists: false })).toBe(false);
  });
});


describe('upgrade decision', () => {
  const align = (result: string, offset_ms = 0) => ({ drift_ms: 0, offset_ms, offset_samples: 0, result, text: '' });
  it('offers a choice only where both ways are possible, Same track first', () => {
    const w = upgradeWays(upgrade(), true);
    expect(w.choice).toBe(true);
    expect(w.options.map((o) => [o.key, o.name])).toEqual([['swap', 'Same track'], ['add_new', 'New track']]);
    expect(w.options[0].outcomes).toEqual([{ tone: 'kept', text: 'Your track keeps its cues' }]);
    expect(w.options[1].summary).toBe('Relocate your old track to keep cues');
    expect(w.reason).toBeNull();
  });
  it('says a shifted match moves the audio onto the cues', () => {
    const w = upgradeWays(upgrade({ alignment: align('shifted', -12.4) }), true);
    expect(w.options[0].outcomes.map((o) => o.text)).toEqual(['Your track keeps its cues',
      'Moved 12 ms to sit on your cues']);
  });
  it('without a swap says what happens and why Same track is off', () => {
    const mp3 = upgradeWays(upgrade({ swap_possible: false }), false);
    expect([mp3.choice, mp3.reason]).toEqual([false, 'Same track needs an AIFF file']);
    expect(mp3.fixed.map((o) => [o.tone, o.text])).toEqual([['step', 'rekordbox lists it as a new track'],
      ['kept', 'Relocate your old track: cues fit']]);
    const diff = upgradeWays(upgrade({ alignment: align('different'), swap_safe: false }), false);
    expect(diff.reason).toBe('Same track needs the same edit');
    expect(diff.fixed[1]).toEqual({ tone: 'step', text: 'A different edit: set the cues again' });
    const unk = upgradeWays(upgrade({ alignment: align('unknown'), swap_safe: false, swap_possible: false }), false);
    expect(unk.reason).toBe('Same track needs a measured match');
    expect(unk.fixed[1].text).toBe('Unsure if your cues fit: listen first');
  });
  it('words the edit as a fact about the audio', () => {
    expect(editLine(align('exact'))).toEqual({ tone: 'lossless', text: 'The same edit as yours' });
    expect(editLine(align('shifted', 12))).toEqual({ tone: 'lossless', text: 'The same edit, 12 ms apart' });
    expect(editLine(align('different')).tone).toBe('good_lossy');
    expect(editLine(null)).toEqual({ tone: 'other', text: "Couldn't compare them" });
  });
  it('shows a shifted match green (the engine says shifted, not aligned)', () => {
    expect(cueTone('shifted')).toBe('lossless');
    expect(cueTone('different')).toBe('good_lossy');
  });
  it('names the main button by the result', () => {
    expect(replaceLabel(upgrade())).toBe('Replace with lossless');
    expect(replaceLabel(upgrade({ what: '256 kbps version' }))).toBe('Replace with the better version');
  });
});

describe('rekordbox check after a replace', () => {
  const check = (extra: Partial<RekordboxCheckView>): RekordboxCheckView => ({ reason: 'swapped', since: '2026-10-31',
    match: 'exact', offset_ms: 0, moved: false, aligned: false, text: 'long', old_path: 'Superseded/Hard_Bounce/A - x (lossy).aiff',
    reload_tag: true, batch: null, rekordbox: null, old_name: null, ...extra });
  const words = (c: RekordboxCheckView) => checkCard(c)!.steps.map((s) => s.parts.map((p) => p.text).join('') + (s.note ? ` ${s.note}` : ''));
  it('a swap: Reload Tag, analyse; the hint about Auto Relocate', () => {
    const c = checkCard(check({}))!;
    expect(c.summary).toBe('same track, cues kept');
    expect(words(check({}))).toEqual(['Right-click the track › Reload Tag',
      'Analyse it again, so the waveform shows the full sound (lock the beatgrid first if you set it by hand)']);
    expect(c.hint).toMatch(/Auto Relocate/);
    expect(c.steps[0].parts[1]).toEqual({ text: 'Reload Tag', strong: true });
  });
  it('a swap that moved up out of not_lossless/: relocate first', () => {
    expect(words(check({ moved: true }))[0]).toBe('The track shows as missing: Auto Relocate finds it by its name, cues and all');
    expect(checkCard(check({ moved: true }))!.hint).toBeNull();
  });
  it('an added file: relocate, then analyse; the cues by what was measured', () => {
    const add = (match: string | null, offset_ms = 0) => words(check({ reason: 'added_as_new', match, offset_ms }))[1];
    expect(words(check({ reason: 'added_as_new' }))[0]).toBe('Right-click your old track › Relocate › choose the new file');
    expect(add('exact')).toBe('Analyse it again · your cues fit');
    expect(add('shifted', 9)).toBe('Analyse it again · your cues fit to within 9\u00a0ms');
    expect(add('different')).toBe('Analyse it again and set the cues again · a different edit');
    expect(add(null)).toBe("Analyse it again and set the cues again · it couldn't be compared");
  });
  it('an added file lined up with rekordbox: the cues fit exactly', () => {
    const lined = (match: string | null) => words(check({ reason: 'added_as_new', match, offset_ms: 9, aligned: true }));
    expect(lined('exact')).toEqual(['Right-click your old track › Relocate › choose the new file', 'Analyse it again · your cues fit exactly']);
    expect(lined('shifted')[1]).toBe('Analyse it again · your cues fit exactly');
    // the first step is the same however the file was made; only the note after "Analyse it again" depends on it
    expect(checkCard(check({ reason: 'added_as_new', aligned: true }))!.steps[0].parts[1]).toEqual({ text: 'Relocate', strong: true });
    // aligned never speaks for a different edit or an unmeasured one
    expect(lined('different')[1]).toBe('Analyse it again and set the cues again · a different edit');
    expect(lined(null)[1]).toBe("Analyse it again and set the cues again · it couldn't be compared");
    // an old record (aligned false) keeps its words
    expect(words(check({ reason: 'added_as_new', match: 'shifted', offset_ms: 9 }))[1]).toBe('Analyse it again · your cues fit to within 9\u00a0ms');
  });
  it('a swap never says Auto Relocate for an added file, and aligned is ignored on a swap', () => {
    expect(words(check({ aligned: true }))).toEqual(words(check({})));
  });
  it('a wrong song keeps its note', () => {
    expect(checkCard(check({ reason: 'wrong_song' }))).toBeNull();
    expect(checkCard(undefined)).toBeNull();
    expect(replacedCard(check({ reason: 'wrong_song' }), { path: 'x', quality: 'lossless' })).toBeNull();
  });
  it('says where each file is now and what Undo puts back', () => {
    const it2 = { path: 'Library/Hard_Bounce/A - x.aiff', quality: 'lossless' as const };
    expect(replacedCard(check({}), it2)).toEqual({ title: 'Replaced with lossless', undo: 'Undo puts your old audio back in the file.',
      rows: [{ icon: 'file', name: 'Your file, now lossless', where: 'in Library/Hard_Bounce' },
        { icon: 'folder', name: 'A copy of the old audio', where: 'in Superseded/Hard_Bounce' }] });
    const added = replacedCard(check({ reason: 'added_as_new', old_path: null }), it2)!;
    expect(added.rows.map((r) => r.name)).toEqual(['New file, lossless', 'Your old file']);
    expect(added.rows[1].where).toBe('in Superseded/');
    expect(added.undo).toBe('Undo puts both back as they were.');
  });
  it('words the day', () => {
    expect(sinceText('2026-10-31', '2026-10-31')).toBe('today');
    expect(sinceText('2026-10-18', '2026-10-31')).toBe('18\u00a0Oct');
    expect(sinceText(null, '2026-10-31')).toBe('');
    expect(localDay(new Date(2026, 0, 5))).toBe('2026-01-05');
  });
});

describe('which duplicate stays', () => {
  const f = (id: number, path: string, quality: FileSide['quality'] = 'lossless', label = 'LOSSLESS'): FileSide =>
    ({ ...side(id), path, quality, quality_label: label });
  const aiff = f(1, '/Volumes/X/Music/A - x.aiff');
  const mp3 = f(2, '/Volumes/X/Music/Old/A - x.mp3', 'good_lossy', '20.0 kHz');
  it('reads the format and folder from the path', () => {
    expect([fileFormat(aiff.path), fileFormat('x.aif'), fileFormat('/a/b.WAV'), fileFormat('noext')]).toEqual(['AIFF', 'AIFF', 'WAV', '']);
    expect(lastFolder(mp3.path)).toBe('Old');
  });
  it('names the button by the result; the line under it says the others are kept, not deleted', () => {
    expect(keepWords([aiff, mp3], 1)).toEqual({ label: 'Keep the AIFF', hint: 'Not deleted: kept in Superseded/', ready: true });
    expect(keepWords([aiff, mp3], 2).label).toBe('Keep the MP3');
  });
  it('same format: tells them apart by quality, then by folder, else plainly', () => {
    const weak = f(3, '/Volumes/X/Music/Old/A - x.aiff', 'weak', '16.0 kHz');
    expect(keepWords([aiff, weak], 1)).toEqual({ label: 'Keep the lossless file',
      hint: 'Not deleted: kept in Superseded/', ready: true });
    const twin = f(4, '/Volumes/X/Music/Old/A - x.aiff');
    expect(keepWords([aiff, twin], 4)).toEqual({ label: 'Keep the one in Old', hint: 'Not deleted: kept in Superseded/', ready: true });
    const long = f(5, '/Volumes/X/Peak Hour Rarities and More/A - x.aiff');
    expect(fileWords(long, [aiff, long])).toBeNull();
    expect(keepWords([aiff, long], 5).label).toBe('Keep this file');
  });
  it('asks for a pick, keeps both, and counts the others', () => {
    expect(keepWords([aiff, mp3], null)).toEqual({ label: 'Choose the file that stays', hint: null, ready: false });
    expect(keepWords([aiff, mp3], 'all')).toEqual({ label: 'Keep both', hint: null, ready: true });
    const wav = f(6, '/Volumes/X/Crates/A - x.wav');
    expect(keepWords([aiff, mp3, wav], 1).hint).toBe('Not deleted: kept in Superseded/');
    expect(keepWords([aiff, mp3, wav], 'all').label).toBe('Keep all');
  });
  it('a group id from its files, sorted', () => {
    expect(groupIdOf([12, 3, 7])).toBe('dup:3-7-12');
  });
  it('arrow keys skip rows that cannot be picked and wrap', () => {
    const opts = [{ key: 'a' }, { key: 'b', disabled: true }, { key: 'c' }];
    expect(stepChoice(opts, 'a', 1)).toBe('c');
    expect(stepChoice(opts, 'c', 1)).toBe('a');
    expect(stepChoice(opts, null, -1)).toBe('c');
    expect(stepChoice([{ key: 'x', disabled: true }], null, 1)).toBeNull();
  });
});

describe('the fake backend follows the engine', () => {
  it('rows say the short status; the check carries the steps\' data', async () => {
    const b = createFakeBridge('todo:after-swap');
    const t = await b.todo('all', false);
    if (!t.ok) throw new Error('todo failed');
    const check = t.groups.find((g) => g.key === 'rekordbox_check')!.items.find((i) => i.track_id === 't2')!;
    expect(check.detail).toBe('Reload Tag, analyse again');
    expect(check.check?.reason).toBe('swapped');
    expect(check.can_undo).toBe(true);
    const up = (await createFakeBridge('normal').todo('upgrade_ready', false));
    if (!up.ok) throw new Error('todo failed');
    expect(up.groups[0].items.find((i) => i.track_id === 't2')!.detail).toBe('Lossless ready · cues can stay');
  });
  it('a duplicate group with a clear winner is picked, a tie is not', async () => {
    const t = await createFakeBridge('todo:duplicates').todo('duplicate', false);
    if (!t.ok) throw new Error('todo failed');
    const pairs = t.groups[0].items.map((i) => (i as DuplicateItem).pair);
    expect(pairs.map((p) => p.recommended === null)).toContain(true);
    expect(pairs.some((p) => p.recommended !== null && p.recommended_why === 'Recommended: best quality')).toBe(true);
  });
});

describe('the item just acted on (the hold)', () => {
  const hold = (extra: Partial<TodoHold> = {}): TodoHold => ({ key: 'upgrade_ready/t2', id: 't2', keep: null,
    filter: 'upgrade_ready', showHidden: false, put: false, ghost: false, ...extra });

  it('holds only for the selected item, in the filter and Show hidden it was made in', () => {
    expect(holdApplies(hold(), 'upgrade_ready/t2', 'upgrade_ready', false)).toBe(true);
    expect(holdApplies(hold(), 'upgrade_ready/t3', 'upgrade_ready', false)).toBe(false);
    expect(holdApplies(hold(), 'upgrade_ready/t2', 'all', false)).toBe(false);
    expect(holdApplies(hold(), 'upgrade_ready/t2', 'upgrade_ready', true)).toBe(false);
    expect(holdApplies(null, 'upgrade_ready/t2', 'upgrade_ready', false)).toBe(false);
  });

  it('finds the item itself, else the same track in another group, else the song with a kept file', () => {
    const items = flatten(todo([['rekordbox_check', ['t2']], ['weak', ['t5']]]));
    expect(findHeld(items, hold())?.group).toBe('rekordbox_check');
    expect(findHeld(items, hold({ key: 'weak/t5', id: 't5' }))?.track_id).toBe('t5');
    expect(findHeld(items, hold({ key: 'upgrade_ready/t9', id: 't9' }))).toBeNull();
    const kept = [item('t5', 'weak', { path: '/Volumes/M/kept.aiff' })];
    expect(findHeld(kept, hold({ key: 'duplicate/1-2', id: 'local:5', keep: ['/Volumes/M/kept.aiff'] }))?.track_id).toBe('t5');
    expect(findHeld(kept, hold({ key: 'duplicate/1-2', id: 'local:5', keep: ['/elsewhere.aiff'] }))).toBeNull();
  });

  it('an import item is never taken for the same track', () => {
    const dup = item('dup1', 'duplicate', { path: '/Volumes/M/kept.aiff',
      pair: { group_id: '1-2', why: 'same_audio', files: [], recommended: null, recommended_why: null } });
    expect(findHeld([dup], hold({ key: 'duplicate/9-9', id: 'other', keep: ['/Volumes/M/kept.aiff'] }))).toBeNull();
  });

  it('puts a replaced item back into the section it stood in, at its place', () => {
    const before = todo([['upgrade_ready', ['t1', 't2', 't3']]]);
    const after = todo([['upgrade_ready', ['t1', 't3']]]);
    const moved = item('t2', 'rekordbox_check');
    const out = withHeldItem(after, moved, before, 'upgrade_ready/t2');
    expect(out.groups).toHaveLength(1);
    expect(out.groups[0].key).toBe('upgrade_ready');
    expect(flatten(out).map((i) => itemKey(i))).toEqual(['upgrade_ready/t1', 'rekordbox_check/t2', 'upgrade_ready/t3']);
  });

  it('makes the section again when the answer has none left, in the contract order, and clears empty', () => {
    const before = { ...todo([['upgrade_ready', ['t2']]]) };
    before.groups[0] = { ...before.groups[0], label: 'Upgrade ready', hint: 'a better version is waiting' };
    const after: Todo = { ...todo([]), empty: 'nothing_here' };
    const out = withHeldItem(after, item('t2', 'rekordbox_check'), before, 'upgrade_ready/t2');
    expect(out.empty).toBeNull();
    expect(out.groups.map((g) => [g.key, g.label, g.hint, g.items.length])).toEqual([['upgrade_ready', 'Upgrade ready', 'a better version is waiting', 1]]);
    const two = todo([['upgrade_ready', ['t4']], ['weak', ['t5']]]);
    const gone = todo([['weak', ['t5']]]);
    expect(withHeldItem(gone, item('t4', 'rekordbox_check'), two, 'upgrade_ready/t4').groups.map((g) => g.key))
      .toEqual(['upgrade_ready', 'weak']);
  });

  it('leaves an answer that lists the item as it is', () => {
    const view = todo([['upgrade_ready', ['t2']]]);
    expect(withHeldItem(view, item('t2', 'upgrade_ready'), view, 'upgrade_ready/t2')).toBe(view);
  });

  it('the item put back is in view but not an open to-do: the section counts without it, as the chips do', () => {
    const before = todo([['upgrade_ready', ['t1', 't2', 't3']]]);
    const out = withHeldItem(todo([['upgrade_ready', ['t1', 't3']]]), item('t2', 'rekordbox_check'), before, 'upgrade_ready/t2');
    const g = out.groups[0].items;
    expect(g).toHaveLength(3);
    expect(openCount(g, 'rekordbox_check/t2')).toBe(2);
    expect(openCount(g, null)).toBe(3);
    // a section made again for the item alone has no open item
    const only = withHeldItem({ ...todo([]), empty: 'nothing_here' }, item('t2', 'rekordbox_check'), todo([['upgrade_ready', ['t2']]]), 'upgrade_ready/t2');
    expect(openCount(only.groups[0].items, 'rekordbox_check/t2')).toBe(0);
    // the same row listed by the answer itself (no extra) counts
    expect(openCount(g, 'weak/zzz')).toBe(3);
  });

  it('the arrow keys go on from the held row to its neighbours', () => {
    const out = withHeldItem(todo([['upgrade_ready', ['t1', 't3']]]), item('t2', 'rekordbox_check'),
      todo([['upgrade_ready', ['t1', 't2', 't3']]]), 'upgrade_ready/t2');
    const flat = flatten(out);
    expect(moveSelection(flat, 'rekordbox_check/t2', 1)).toBe('upgrade_ready/t3');
    expect(moveSelection(flat, 'rekordbox_check/t2', -1)).toBe('upgrade_ready/t1');
  });

  it('a ghost is the row as it was, without what only a to-do has', () => {
    const old = item('t2', 'rekordbox_check', { upgrade_ready: true, can_undo: true, detail: 'Reload Tag',
      check: { reason: 'swapped', since: null, match: null, offset_ms: null, moved: false, aligned: false, text: 't', old_path: null,
        reload_tag: true, batch: null, rekordbox: null, old_name: null } });
    const g = ghostOf(old);
    expect(itemKey(g)).toBe(itemKey(old));
    expect(g).toMatchObject({ upgrade_ready: false, can_undo: false, check: undefined, detail: '', title: old.title });
  });

  it('under the Upgrades filter a replace in the fake keeps the item, with its steps and Undo', async () => {
    const b = createFakeBridge('todo:upgrade-aiff-same', { speed: 200 });
    const up = await b.todo('upgrade_ready', false);
    if (!up.ok) throw new Error('todo failed');
    const h = hold();
    expect(findHeld(flatten(up), h)?.group).toBe('upgrade_ready');
    const job = await b.upgrade(['t2'], 'swap');
    if (!job.ok) throw new Error('upgrade failed');
    await new Promise((r) => setTimeout(r, 300));
    const view = await b.todo('upgrade_ready', false);
    const all = await b.todo('all', false);
    if (!view.ok || !all.ok) throw new Error('todo failed');
    expect(findHeld(flatten(view), h)).toBeNull();
    const held = findHeld(flatten(all), h)!;
    expect(held).toMatchObject({ group: 'rekordbox_check', can_undo: true });
    const out = withHeldItem(view, held, up, h.key);
    expect(flatten(out).some((i) => itemKey(i) === 'rekordbox_check/t2' && i.check?.reason === 'swapped')).toBe(true);
  });
});

// ---------- multi-select (issue 33 stage B §6.1) and the U1 states in fake mode (§6.5) ----------
import { multiScope, upgradeGroup } from './todoModel';
import { click, keep, selectScope, single } from '$lib/components/selectionModel';
import type { AiffBatchResult } from '$lib/bridge/types';
import type { HubEvent } from '$lib/bridge/events';

describe('multi-select in To-do', () => {
  const list = [item('t1', 'rekordbox_check'), item('t2', 'upgrade_ready'), item('t3', 'upgrade_ready'),
    item('t4', 'weak'), item('t5', 'upgrade_ready')];
  const order = list.map(itemKey);
  const scopeOf = multiScope(list);
  it('only Upgrade ready and the rekordbox checks take several; other groups stay one item', () => {
    expect(scopeOf('upgrade_ready/t2')).toBe('upgrade_ready');
    expect(scopeOf('weak/t4')).toBeNull();
    expect(scopeOf('rekordbox_check/t1')).toBe('rekordbox_check');
    expect(click(single('weak/t4'), 'weak/t4', { meta: true }, order, scopeOf)).toEqual(single('weak/t4'));
    expect(click(single('upgrade_ready/t2'), 'upgrade_ready/t5', { shift: true }, order, scopeOf).keys)
      .toEqual(['upgrade_ready/t2', 'upgrade_ready/t3', 'upgrade_ready/t5']);
  });
  it('"Upgrade all" selects the group, its first item the anchor', () => {
    expect(selectScope('upgrade_ready', order, scopeOf)).toEqual({
      keys: ['upgrade_ready/t2', 'upgrade_ready/t3', 'upgrade_ready/t5'], anchor: 'upgrade_ready/t2' });
  });
  it('a replace that took two items away keeps the rest selected, and one left is a single selection', () => {
    const sel = selectScope('upgrade_ready', order, scopeOf);
    const after = order.filter((k) => k !== 'upgrade_ready/t2' && k !== 'upgrade_ready/t3');
    expect(keep(sel, order, after)).toEqual(single('upgrade_ready/t5'));
  });
  it('finds the Upgrade ready group of an answer', () => {
    const t = { groups: [{ key: 'weak', label: '', hint: '', items: [] }, { key: 'upgrade_ready', label: 'U', hint: '',
      items: [], all: { n: 1, m: 0, k: 0 }, stopped: null }] } as unknown as Todo;
    expect(upgradeGroup(t)?.all).toEqual({ n: 1, m: 0, k: 0 });
    expect(upgradeGroup(null)).toBeNull();
  });
  it('a single upgrade with no rekordbox on this Mac runs Same track from its foot', () => {
    const up = upgrade({ swap_how: 'new_aiff', rekordbox: { state: 'none', running: false } });
    const t = { ...item('t2', 'upgrade_ready'), upgrade: up } as unknown as TrackDetail;
    expect(actionsFor(t, 'upgrade_ready').upgrade).toEqual({ swap: true, primary: 'swap' });
  });
});

describe('the U1 states in fake mode', () => {
  function setup(scenario: string) {
    const evs: HubEvent[] = [];
    const f = createFakeBridge(scenario, { speed: 400, emit: (e) => evs.push(e) });
    const finished = async (id: number) => {
      for (let i = 0; i < 400; i++) {
        const e = evs.find((x) => x.type === 'JobFinished' && x.job_id === id);
        if (e) return e as Extract<HubEvent, { type: 'JobFinished' }>;
        await new Promise((r) => setTimeout(r, 5));
      }
      throw new Error('the job did not finish');
    };
    const group = async () => upgradeGroup((await f.todo('upgrade_ready', false)) as Todo);
    return { evs, f, finished, group };
  }
  it('todo-upgrade-multi / todo-upgrade-all: a mixed group (Same track, a choice, something else)', async () => {
    const { group } = setup('todo:upgrade-group');
    const g = await group();
    expect(g!.all!.n).toBeGreaterThan(1);
    expect(g!.all!.m).toBeGreaterThan(0);
    expect(g!.all!.k).toBeGreaterThan(0);
    expect(g!.items.some((i) => i.same_track === 'away')).toBe(true);
  });
  it('todo-upgrade-running / -stopped / todo-resume-link: a slow batch runs, stops, and the group offers Resume', async () => {
    const { f, evs, finished, group } = setup('todo:upgrade-slow');
    const start = await f.upgrade_all();
    expect(start.ok).toBe(true);
    for (let i = 0; i < 200 && !evs.some((e) => e.type === 'BatchProgress' && e.done === 1); i++) {
      await new Promise((r) => setTimeout(r, 5));
    }
    expect(evs.some((e) => e.type === 'BatchProgress' && e.track_id !== null)).toBe(true);
    await f.stop();
    const fin = await finished((start as { job_id: number }).job_id);
    expect(fin.problem).toBe('stopped');
    const r = fin.result as AiffBatchResult;
    expect(r.state).toBe('stopped');
    expect((await group())!.stopped).toEqual({ batch_id: r.batch, left: r.results.filter((x) => x.state === 'planned').length });
  });
  it('todo-upgrade-rekordbox-open: the batch stops before it starts and carries its tracks', async () => {
    const { f, finished } = setup('upgrade-rekordbox-open');
    const start = await f.upgrade_all();
    const fin = await finished((start as { job_id: number }).job_id);
    expect(fin.problem).toBe('rekordbox_open');
    expect((fin.result as AiffBatchResult).state).toBe('stopped');
  });
  it('todo-upgrade-done: a finished batch lists the track its check skipped, with the reason', async () => {
    const { f, finished } = setup('todo:upgrade-skips');
    const fin = await finished(((await f.upgrade_all()) as { job_id: number }).job_id);
    expect(fin.ok).toBe(true);
    const r = fin.result as AiffBatchResult;
    expect(r.results.filter((x) => x.state === 'skipped').map((x) => x.reason)).toEqual(['timing']);
    expect(r.results.find((x) => x.state === 'skipped')!.message).toBeTruthy();
  });
  it('todo-upgrade-refused: every track skipped, refused, the batch still in the result', async () => {
    const { f, finished } = setup('todo:upgrade-refused');
    const fin = await finished(((await f.upgrade_all()) as { job_id: number }).job_id);
    expect(fin.problem).toBe('refused');
    expect((fin.result as AiffBatchResult).results.every((x) => x.state === 'skipped')).toBe(true);
  });
  it('todo-upgrade-mp3-same / -unreadable / -no-rekordbox: the single track\'s upgrade block', async () => {
    const block = async (sc: string) => {
      const r = await createFakeBridge(sc).track('t2');
      return (r as { track: TrackDetail }).track.upgrade!;
    };
    expect(await block('todo:upgrade-mp3-same')).toMatchObject({ swap_possible: true, swap_how: 'new_aiff' });
    expect(await block('todo:upgrade-unreadable')).toMatchObject({ swap_possible: false, why_not: 'rekordbox_unreadable' });
    expect((await block('todo:upgrade-no-rekordbox')).rekordbox.state).toBe('none');
  });
});

// ---------- the rekordbox checks: a batch's row and several checks selected (stage B §6.4), the U2 states (§6.5) ----------
import { isBatch, type BatchCheckItem, type UndoResult } from '$lib/bridge/types';
import { escape, selectAll } from '$lib/components/selectionModel';
import { heldChecks, multiChecks, queueRows as queueOf, rowBadge as badgeOf, rowDim as dimOf, selectFromTrack as fromTrack } from './todoModel';

describe('multi-select of the rekordbox checks', () => {
  const check = (id: string, extra: Partial<TodoItem> = {}) => item(id, 'rekordbox_check', { can_undo: true, quality: 'lossless',
    quality_label: 'LOSSLESS', ...extra });
  const batch: BatchCheckItem = { ...check('batch:7', { key: 'batch:7' }), group: 'rekordbox_check', key: 'batch:7',
    batch: { id: 7, size: 2, started: '2026-11-08', started_by: 'user', kind: 'upgrade', tracks: [check('b1'), check('b2')] } };
  const list = [batch, check('c1'), check('c2'), check('c3'), item('u1', 'upgrade_ready'), item('w1', 'weak')];
  const order = list.map(itemKey);
  const scopeOf = multiScope(list);
  const keys = (...ids: string[]) => ids.map((id) => `rekordbox_check/${id}`);
  const of = (sel: { keys: string[] }) => list.filter((i) => sel.keys.includes(itemKey(i)));

  it('none: nothing selected is no checks panel', () => {
    expect(multiChecks([])).toBe(false);
  });
  it('one: a plain click is one check (the batch row too), never the checks panel', () => {
    const one = click(single(null), keys('batch:7')[0], {}, order, scopeOf);
    expect(one).toEqual(single('rekordbox_check/batch:7'));
    expect(multiChecks(of(one))).toBe(false);
  });
  it('several: ⌘-click toggles within the checks, a batch row among single checks', () => {
    let sel = single(keys('batch:7')[0]);
    sel = click(sel, keys('c2')[0], { meta: true }, order, scopeOf);
    expect(sel.keys).toEqual(keys('batch:7', 'c2'));
    expect(multiChecks(of(sel))).toBe(true);
    sel = click(sel, keys('c2')[0], { meta: true }, order, scopeOf);
    expect(sel.keys).toEqual(keys('batch:7'));
    // ⌘-click in another group starts over there
    expect(click(single(keys('c1')[0]), 'upgrade_ready/u1', { meta: true }, order, scopeOf)).toEqual(single('upgrade_ready/u1'));
    expect(multiChecks([check('c1'), item('u1', 'upgrade_ready')])).toBe(false);
  });
  it('range: ⇧-click selects anchor…key in list order, inside the checks only', () => {
    const sel = click(single(keys('c1')[0]), keys('c3')[0], { shift: true }, order, scopeOf);
    expect(sel.keys).toEqual(keys('c1', 'c2', 'c3'));
    expect(sel.anchor).toBe(keys('c1')[0]);
    expect(click(single(keys('c3')[0]), 'weak/w1', { shift: true }, order, scopeOf)).toEqual(single('weak/w1'));
  });
  it('all: ⌘A selects every check, Esc goes back to the anchor', () => {
    const all = selectAll(single(keys('c2')[0]), order, scopeOf);
    expect(all.keys).toEqual(keys('batch:7', 'c1', 'c2', 'c3'));
    expect(escape(all)).toEqual(single(keys('c2')[0]));
  });
  it('kept or pruned when checks leave: Done on two keeps the rest, one left is a single selection', () => {
    const all = selectAll(single(keys('c1')[0]), order, scopeOf);
    const after = order.filter((k) => k !== keys('c1')[0] && k !== keys('batch:7')[0]);
    expect(keep(all, order, after)).toEqual({ keys: keys('c2', 'c3'), anchor: keys('c2')[0] });
    const later = after.filter((k) => k !== keys('c2')[0]);
    expect(keep({ keys: keys('c2', 'c3'), anchor: keys('c2')[0] }, after, later)).toEqual(single(keys('c3')[0]));
  });
  it('the checks the panel acted on stay held: a batch left with one track is that single check, none left ends it', () => {
    const h = { ids: ['b1', 'b2', 'c1'], batch: null };
    expect(heldChecks(list, h)).toEqual({ keys: keys('batch:7', 'c1'), tracks: [batch.batch.tracks[0], batch.batch.tracks[1], list[1]] });
    // an undo put b1 and c1 back: the batch is now the single check b2
    const after = [check('b2'), check('c2')];
    expect(heldChecks(after, h)).toEqual({ keys: keys('b2'), tracks: [after[0]] });
    expect(heldChecks([check('c2')], h)).toBeNull();
  });
  it('a batch row: its tracks play in the queue, ?track= of one of them selects it, never dimmed, its quality', () => {
    expect(queueOf(list).map((i) => i.track_id).slice(0, 3)).toEqual(['b1', 'b2', 'c1']);
    expect(fromTrack(list, 'b2')).toBe('rekordbox_check/batch:7');
    expect(dimOf({ ...batch, in_playlists: false })).toBe(false);
    expect(badgeOf(batch)).toEqual({ quality: 'lossless', label: 'LOSSLESS' });
    const mixed = { ...batch, batch: { ...batch.batch, tracks: [check('b1'), check('b2', { quality: 'good_lossy', quality_label: '20.0 kHz' })] } };
    expect(badgeOf(mixed)).toEqual({ quality: 'muted', label: 'MIXED' });
  });
});

describe('the U2 states in fake mode', () => {
  function setup(scenario: string) {
    const evs: HubEvent[] = [];
    const f = createFakeBridge(scenario, { speed: 400, emit: (e) => evs.push(e) });
    const finished = async (id: number) => {
      for (let i = 0; i < 400; i++) {
        const e = evs.find((x) => x.type === 'JobFinished' && x.job_id === id);
        if (e) return e as Extract<HubEvent, { type: 'JobFinished' }>;
        await new Promise((r) => setTimeout(r, 5));
      }
      throw new Error('the job did not finish');
    };
    const checks = async () => ((await f.todo('rekordbox_check', false)) as Todo).groups[0]?.items ?? [];
    const theBatch = async () => (await checks()).find(isBatch)!;
    return { f, finished, checks, theBatch };
  }
  it('todo-check-batch: one row for the batch, its tracks with their checks and undo, counted once', async () => {
    const { f, theBatch } = setup('todo:check-batch');
    const b = await theBatch();
    expect(b.key).toBe('batch:7');
    expect(b.batch.size).toBe(4);
    expect(b.batch.tracks.map((t) => t.check?.reason)).toEqual(['swapped', 'repointed', 'swapped', 'repointed']);
    // the files are the user's own names, in the folder the row names: not always "Artist - Title"
    const names = b.batch.tracks.map((t) => t.path!.split('/').pop()!);
    expect(names.filter((n, i) => n === `${b.batch.tracks[i].artist} - ${b.batch.tracks[i].title}.aiff`).length).toBeLessThan(2);
    expect(b.batch.tracks.every((t) => t.path!.split('/').at(-2) === t.folder)).toBe(true);
    expect(b.batch.tracks.every((t) => t.can_undo && t.check?.reload_tag === false)).toBe(true);
    const t = (await f.todo('all', false)) as Todo;
    expect(t.chips.rekordbox_check).toBe(t.groups.find((g) => g.key === 'rekordbox_check')!.items.length);
  });
  it('todo-check-batch-kept: kept fields, one track for Reload Tag, one rekordbox doesn\'t have', async () => {
    const b = await setup('todo:check-batch-kept').theBatch();
    expect(b.batch.tracks.map((t) => t.check?.rekordbox?.kept)).toEqual([['title'], ['artist', 'comment'], [], []]);
    expect(b.batch.tracks.map((t) => t.check?.reload_tag)).toEqual([false, false, true, false]);
    expect(b.batch.tracks[3].check?.rekordbox?.entries).toBe(0);
  });
  it('todo-check-batch-undo-refused: Undo all puts two back and lists the one it refused', async () => {
    const { f, finished, theBatch, checks } = setup('todo:check-batch-undo-refused');
    const ids = (await theBatch()).batch.tracks.map((t) => t.track_id);
    const fin = await finished(((await f.undo_upgrade(ids)) as { job_id: number }).job_id);
    expect(fin.ok).toBe(true);
    const r = fin.result as UndoResult;
    expect(r.results.filter((x) => x.state === 'refused').map((x) => x.track)).toEqual([ids[1]]);
    expect((await checks()).map((i) => i.track_id)).toContain(ids[1]);
  });
  it('todo-check-batch-rekordbox-open: Undo all undoes nothing while rekordbox is open', async () => {
    const { f, finished, theBatch } = setup('todo:check-batch-rekordbox-open');
    const ids = (await theBatch()).batch.tracks.map((t) => t.track_id);
    const fin = await finished(((await f.undo_upgrade(ids)) as { job_id: number }).job_id);
    expect(fin.problem).toBe('rekordbox_open');
    expect((fin.result as UndoResult).results.every((x) => x.state === 'waiting')).toBe(true);
  });
  it('todo-check-multi: Done for a batch and a single check clears all their checks in one job', async () => {
    const { f, finished, checks } = setup('todo:check-batch');
    const before = await checks();
    expect(before.length).toBeGreaterThan(1);
    const fin = await finished(((await f.rekordbox_checked(
      [...(before.find(isBatch)!).batch.tracks.map((t) => t.track_id), before.find((i) => !isBatch(i))!.track_id])) as { job_id: number }).job_id);
    expect(fin.ok).toBe(true);
    expect((await checks()).length).toBe(before.length - 2);
  });
  it('todo-check-repointed: a Same track batch of one is a plain check of its own', async () => {
    const items = await setup('todo:check-repointed').checks();
    const one = items.find((i) => i.check?.reason === 'repointed');
    expect(one && isBatch(one)).toBe(false);
    expect(one!.check).toMatchObject({ batch: { size: 1 }, reload_tag: false, rekordbox: { entries: 1, kept: [] } });
  });
});

describe('Upgrade all and the batch panel (issue 33 stage B)', () => {
  const group = { items: [item('a', 'upgrade_ready'), item('h', 'upgrade_ready', { hidden: true }), item('b', 'upgrade_ready')] };
  it('Upgrade all leaves a hidden item out, also with Show hidden on', () => {
    expect(upgradeAllKeys(group)).toEqual(['upgrade_ready/a', 'upgrade_ready/b']);
    expect(upgradeAllKeys(null)).toEqual([]);
  });
  it('the whole group is every reachable item with no hidden one; else the selection goes as a list', () => {
    const [a, h, b] = group.items;
    expect(wholeUpgradeGroup(group, [a, b])).toBe(true);
    expect(wholeUpgradeGroup(group, [a, h, b])).toBe(false);
    expect(wholeUpgradeGroup(group, [a])).toBe(false);
    expect(wholeUpgradeGroup(null, [a])).toBe(false);
  });
  it('a pinned batch keeps only the rows still listed selected and never moves to a neighbour', () => {
    const sel = { keys: ['a', 'b', 'c'], anchor: 'a' };
    expect(keepPinned(sel, ['a', 'b', 'c', 'x'], ['b', 'c', 'x', 'batch:1'])).toEqual({ keys: ['b', 'c'], anchor: 'b' });
    expect(keepPinned(sel, ['a', 'b', 'c', 'x'], ['x', 'batch:1'])).toEqual({ keys: [], anchor: null });
  });
  it('the checks panel gives way to a pinned batch', () => {
    expect([checksPanelShows(true, true), checksPanelShows(false, true), checksPanelShows(false, false)]).toEqual([false, true, false]);
  });
  it('the list asks again once per track done while a batch runs, never at its start or when it is over', () => {
    expect(batchListStep(-1, null)).toEqual({ reload: false, seen: -1 });
    expect(batchListStep(-1, { phase: 'running', done: 0 })).toEqual({ reload: false, seen: 0 });
    expect(batchListStep(0, { phase: 'running', done: 1 })).toEqual({ reload: true, seen: 1 });
    expect(batchListStep(1, { phase: 'running', done: 1 })).toEqual({ reload: false, seen: 1 });
    expect(batchListStep(1, { phase: 'ended', done: 3 })).toEqual({ reload: false, seen: -1 });
  });
  it('a burst of asks is one run and one more after it', async () => {
    let runs = 0;
    let release: () => void = () => {};
    const gate = () => new Promise<void>((r) => { release = r; });
    const go = coalesce(async () => { runs++; await gate(); });
    go(); go(); go();
    expect(runs).toBe(1);
    release();
    await new Promise((r) => setTimeout(r, 0));
    expect(runs).toBe(2);
    release();
    await new Promise((r) => setTimeout(r, 0));
    expect(runs).toBe(2);
    go();
    expect(runs).toBe(3);
    release();
  });
});

describe('the CDJ group (issue 33 stage D §6.3)', () => {
  const group = { items: [item('a', 'cdj'), item('h', 'cdj', { hidden: true }), item('b', 'cdj'), item('c', 'cdj')] };
  it('its items select several at once, within the group only', () => {
    expect(MULTI_GROUPS).toContain('cdj');
    const a = item('a', 'cdj');
    const b = item('b', 'cdj');
    const u = item('u', 'upgrade_ready');
    const scope = multiScope([a, b, u]);
    expect([scope(itemKey(a)), scope(itemKey(b)), scope(itemKey(u))]).toEqual(['cdj', 'cdj', 'upgrade_ready']);
    expect([multiCdj([a, b]), multiCdj([a]), multiCdj([a, u]), multiCdj([])]).toEqual([true, false, false, false]);
  });
  it('Convert all reaches every item but a hidden one, also with Show hidden on', () => {
    expect(cdjAllKeys(group)).toEqual(['cdj/a', 'cdj/b', 'cdj/c']);
    expect(cdjAllKeys(null)).toEqual([]);
  });
  it('the whole group is every reachable item with no hidden one; else the selection goes as a list of tracks', () => {
    const [a, h, b, c] = group.items;
    expect(wholeCdjGroup(group, [a, b, c])).toBe(true);
    expect(wholeCdjGroup(group, [a, h, b, c])).toBe(false);
    expect(wholeCdjGroup(group, [a, b])).toBe(false);
    expect(wholeCdjGroup(null, [a])).toBe(false);
  });
  it('the group is found in the answer by its key, null without one', () => {
    const t = todo([['upgrade_ready', ['x']], ['cdj', ['a', 'b']]]);
    expect(cdjGroup(t)?.items.map((i) => i.track_id)).toEqual(['a', 'b']);
    expect(cdjGroup(todo([['upgrade_ready', ['x']]]))).toBeNull();
    expect(cdjGroup(null)).toBeNull();
  });
  it('the head\'s two states: "Convert all · n" from two files, "Resume · k left" while a batch is stopped', async () => {
    const { convertAllLabel, resumeLabel, upgradeAllShown } = await import('$lib/decisions/decisionModel');
    expect([convertAllLabel(5), upgradeAllShown(5), upgradeAllShown(1)]).toEqual(['Convert all · 5', true, false]);
    const f = createFakeBridge('todo:cdj-resume', { speed: 1000 });
    const g = cdjGroup((await f.todo('cdj', true)) as unknown as Todo)!;
    expect(g.stopped).toEqual({ batch_id: 1, left: 3 });
    expect(resumeLabel(g.stopped!.left)).toBe('Resume · 3 left');
    const fresh = cdjGroup((await createFakeBridge('todo:cdj', { speed: 1000 }).todo('cdj', true)) as unknown as Todo)!;
    expect([fresh.all, fresh.stopped]).toEqual([{ n: 5, k: 1 }, null]);
  });
  it('the strip says CDJs, the section its whole name, and the page header counts the files', () => {
    expect(segOptions({ all: 6, rekordbox_check: 0, same_song: 0, duplicate: 0, cdj: 6, upgrade_ready: 0, not_found: 0, weak: 0,
      good_lossy: 0, fake: 0, other: 0 }, 'all').find((o) => o.key === 'cdj')).toMatchObject({ label: 'CDJs', count: 6 });
    const none = { all: 0, rekordbox_check: 0, same_song: 0, duplicate: 0, cdj: 0, upgrade_ready: 0, not_found: 0, weak: 0,
      good_lossy: 0, fake: 0, other: 0 };
    expect(headerSub({ chips: { ...none, cdj: 6 }, check_tracks: 0 })).toEqual(["6 files won't play well on CDJs"]);
    expect(headerSub({ chips: { ...none, cdj: 1, weak: 2 }, check_tracks: 0 })).toEqual(['2 tracks are not lossless yet',
      "1 file won't play well on CDJs"]);
  });
  it('a CDJ item can be hidden (a lossless file the user wants no to-do for)', () => {
    expect(actionsFor(detail({ status: 'lossless' }), 'cdj')).toMatchObject({ hide: 'hide', main: null });
    expect(actionsFor(detail({ status: 'lossless', hidden: true }), 'cdj').hide).toBe('unhide');
    expect(actionsFor(detail({ status: 'lossless' }), null).hide).toBeNull();
  });
  it('a Convert batch is one row: "{n} tracks" over "{day} · Made AIFF"', async () => {
    const { batchRowName, batchRowSub } = await import('$lib/decisions/decisionModel');
    expect([batchRowName(3, 'convert'), batchRowName(3, 'upgrade'), batchRowName(3)]).toEqual(['3 tracks', '3 tracks upgraded', '3 tracks upgraded']);
    expect([batchRowSub('2026-11-14', '2026-11-14', 'cdj_all', 'convert'), batchRowSub('2026-11-14', '2026-11-14', 'user', 'convert', true),
      batchRowSub('2026-11-14', '2026-11-14', 'user', 'upgrade')]).toEqual(['today · Made AIFF', 'today · Clean name', 'today · Same track']);
  });
});
