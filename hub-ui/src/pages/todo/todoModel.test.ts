import { describe, expect, it } from 'vitest';
import type {
  DuplicateItem, FileSide, QuestionItem, QuestionPair, Todo, TodoGroupKey, TodoItem, TrackDetail, Upgrade,
} from '$lib/bridge/types';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import {
  dropDecision,
  FILTER_ORDER, actionsFor, segOptions, filterFrom, flatten, headerSub, itemKey, keepSelection, moveSelection, rowOff,
  cutoffStat, freeHint, qobuzText, selectAfterHide, selectFromTrack,
  NO_VALUE, compareLines, fileFolder, fileName, fileQueue, fileState, keepLabel, linkService, queueRows, rowBadge,
} from './todoModel';

function item(id: string, group: TodoGroupKey, extra: Partial<TodoItem> = {}): TodoItem {
  return { track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'not_lossless',
    quality: 'weak', quality_label: '16.0 kHz', cutoff_hz: 16000, source: 'youtube', source_name: 'YouTube',
    in_playlists: true, own: false, hidden: false, upgrade_ready: false, path: 'Library/Hard_Bounce/A - x.aiff', added: null,
    cover_url: null, group, detail: '', free: false, ...extra };
}
function todo(groups: [TodoGroupKey, string[]][]): Todo {
  const chips = { all: 0, rekordbox_check: 0, same_song: 0, duplicate: 0, upgrade_ready: 0, not_found: 0, weak: 0, good_lossy: 0, fake: 0, other: 0 };
  return { chips, hidden_count: 0, show_hidden: false, empty: null,
    groups: groups.map(([key, ids]) => ({ key, label: key, hint: '', items: ids.map((id) => item(id, key)) })) };
}
function upgrade(extra: Partial<Upgrade> = {}): Upgrade {
  return { file: 'Upgrades ready/Hard_Bounce/A - x.aiff', source: 'qobuz', source_name: 'Qobuz', source_id: 'q1',
    found: '2026-10-16', what: 'lossless version', quality_line: 'Qobuz FLAC · verified lossless',
    alignment: { drift_ms: 0, offset_ms: 0, offset_samples: 0, result: 'exact', text: 'matches exactly' },
    cue_text: 'matches exactly, cues stay', swap_safe: true, swap_possible: true, audio_url: 'u2', ...extra };
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
  const chips = { all: 9, rekordbox_check: 0, same_song: 0, duplicate: 0, upgrade_ready: 2, not_found: 3, weak: 0, good_lossy: 4, fake: 0, other: 0 };
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
    expect(qobuzText('2026-10-20')).toBe('not there yet · looks again on 20 Oct');
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
  it('header line', () => {
    expect(headerSub(16)).toBe('16 tracks are not lossless yet');
    expect(headerSub(1)).toBe('1 track is not lossless yet');
    expect(headerSub(0)).toBe('Nothing to do');
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
  return { ...item(group_id, 'duplicate'), group: 'duplicate', pair: { group_id, why: 'same_audio', files: ids.map((id) => side(id)) } };
}
const flatOf = (...items: TodoItem[]) => items;

describe('the import groups on the strip and in navigation', () => {
  it('come right after rekordbox, in the order the sections do', () => {
    expect(FILTER_ORDER.slice(0, 5)).toEqual(['all', 'rekordbox_check', 'same_song', 'duplicate', 'upgrade_ready']);
    const chips = { all: 12, rekordbox_check: 1, same_song: 2, duplicate: 3, upgrade_ready: 1, not_found: 4, weak: 1,
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
      ['length', '3:14', '3:14', false], ['where', 'Hard_Bounce', '/Volumes/Example Drive/Music', false]]);
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

describe('which rows are dimmed', () => {
  it('only the older kinds dim a track that no playlist holds; questions and duplicate groups never do', () => {
    expect(rowOff(item('t1', 'weak', { in_playlists: false }))).toBe(true);
    expect(rowOff(item('t1', 'weak'))).toBe(false);
    expect(rowOff({ ...question('q1', 101), in_playlists: false })).toBe(false);
    expect(rowOff({ ...dupe([201, 202]), in_playlists: false })).toBe(false);
  });
});
