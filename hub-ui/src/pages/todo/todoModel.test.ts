import { describe, expect, it } from 'vitest';
import type { Todo, TodoGroupKey, TodoItem, TrackDetail, Upgrade } from '$lib/bridge/types';
import { createFakeBridge } from '$lib/bridge/fake/bridge';
import {
  dropDecision,
  FILTER_ORDER, actionsFor, segOptions, filterFrom, flatten, headerSub, itemKey, keepSelection, moveSelection,
  cutoffStat, freeHint, qobuzText, selectAfterHide, selectFromTrack,
} from './todoModel';

function item(id: string, group: TodoGroupKey, extra: Partial<TodoItem> = {}): TodoItem {
  return { track_id: id, artist: 'A', title: id, folder: 'Hard_Bounce', duration_s: 200, status: 'not_lossless',
    quality: 'weak', quality_label: '16.0 kHz', cutoff_hz: 16000, source: 'youtube', source_name: 'YouTube',
    in_playlists: true, hidden: false, upgrade_ready: false, path: 'Library/Hard_Bounce/A - x.aiff', added: null,
    cover_url: null, group, detail: '', free: false, ...extra };
}
function todo(groups: [TodoGroupKey, string[]][]): Todo {
  const chips = { all: 0, rekordbox_check: 0, upgrade_ready: 0, not_found: 0, weak: 0, good_lossy: 0, fake: 0, other: 0 };
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
  return { ...item('t2', 'weak'), isrc: null, playlists: ['Hard_Bounce'], in_playlist_count: 1,
    quality_line: 'YouTube OPUS · cutoff 16.0 kHz', source_url: null, spotify_url: null, next_qobuz_check: null,
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
  const chips = { all: 9, rekordbox_check: 0, upgrade_ready: 2, not_found: 3, weak: 0, good_lossy: 4, fake: 0, other: 0 };
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
    expect(cutoffStat({ status: 'fake_lossless', cutoff_hz: 16000 }))
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
