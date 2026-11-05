// The sources round's block models (I4): LinkGuide's rows, TrackHead's line, link service and hidden word, and the
// quality bar's dashed end segment.
import { describe, expect, it } from 'vitest';
import { GUIDE_HEAD, GUIDE_SERVICES, guideRows } from './linkGuideModel';
import { barParts, barTitle } from './qualityBarModel';
import { headLine, linkService, wordHidden } from './trackHeadModel';
import { settingForm } from './addRowModel';

const q = (o: Partial<Record<'lossless' | 'good_lossy' | 'weak' | 'fake' | 'missing', number>> = {}) =>
  ({ lossless: 0, good_lossy: 0, weak: 0, fake: 0, missing: 0, ...o });

describe('linkGuide', () => {
  it("lists the four services in the user's order with the binding words", () => {
    expect(GUIDE_SERVICES).toEqual(['youtube_music', 'soundcloud', 'spotify', 'qobuz']);
    expect(GUIDE_HEAD).toBe("Where to find a playlist's link");
    expect(guideRows()).toEqual([
      { service: 'youtube_music', where: 'Share › Copy', example: 'music.youtube.com/playlist?list=…' },
      { service: 'soundcloud', where: 'Share › Copy link', example: 'soundcloud.com/name/sets/…' },
      { service: 'spotify', where: '⋯ › Share › Copy link to playlist', example: 'open.spotify.com/playlist/…' },
      { service: 'qobuz', where: 'Share › Copy link', example: 'open.qobuz.com/playlist/…' },
    ]);
  });
});

describe('trackHead', () => {
  it('joins the known parts of the meta line', () => {
    expect(headLine('Lio Sander', 268, 'Hard_Bounce')).toBe('Lio Sander · 4:28 · Hard_Bounce');
    expect(headLine('Lio Sander', null, 'Hard_Bounce')).toBe('Lio Sander · Hard_Bounce');
    expect(headLine('', 268, '')).toBe('4:28');
  });
  it("finds the service from the engine's label, else none", () => {
    expect(linkService({ url: 'https://open.spotify.com/track/x', label: 'Open in Spotify' })).toBe('spotify');
    expect(linkService({ url: 'https://open.qobuz.com/track/1', label: 'Open in Qobuz' })).toBe('qobuz');
    expect(linkService({ url: 'https://soundcloud.com/a/b', label: 'Open in SoundCloud' })).toBe('soundcloud');
    expect(linkService({ url: 'https://music.youtube.com/watch?v=x', label: 'Open in YouTube Music' }))
      .toBe('youtube_music');
    expect(linkService({ url: 'https://example.com', label: 'Open elsewhere' })).toBeNull();
  });
  it('hides the word only when it went a line lower', () => {
    expect(wordHidden(0, 0)).toBe(false);
    expect(wordHidden(0, 1)).toBe(false);
    expect(wordHidden(0, 20)).toBe(true);
  });
});

describe('qualityBar', () => {
  it('ends with the waiting songs, each part sized by its share of all of them', () => {
    const p = barParts(q({ lossless: 9, good_lossy: 1, weak: 2, fake: 1 }), 5);
    expect(p.map((x) => x.key)).toEqual(['lossless', 'good_lossy', 'weak', 'fake', 'waiting']);
    expect(p.at(-1)).toEqual({ key: 'waiting', n: 5, pct: (5 / 18) * 100 });
    expect(p.reduce((a, x) => a + x.pct, 0)).toBeCloseTo(100);
  });
  it('without waiting songs is the bar as before', () => {
    const p = barParts(q({ lossless: 3, weak: 1 }));
    expect(p).toEqual([{ key: 'lossless', n: 3, pct: 75 }, { key: 'weak', n: 1, pct: 25 }]);
  });
  it('is all dashed when nothing has a file yet, and empty with nothing at all', () => {
    expect(barParts(q(), 4)).toEqual([{ key: 'waiting', n: 4, pct: 100 }]);
    expect(barParts(q(), 0)).toEqual([]);
    expect(barParts(q({ lossless: 2 }), -3)).toEqual([{ key: 'lossless', n: 2, pct: 100 }]);
    expect(barParts(q({ lossless: 2 }), Number.NaN)).toEqual([{ key: 'lossless', n: 2, pct: 100 }]);
  });
  it('names the waiting songs in its title', () => {
    expect(barTitle(barParts(q({ lossless: 9, weak: 2 }), 5))).toBe('9 lossless · 2 weak · 5 waiting');
    expect(barTitle([])).toBe('');
  });
});

describe('addRow needs-setting form', () => {
  it("says Liked music's facts and words", () => {
    expect(settingForm('read_liked_music')).toEqual({
      name: 'Liked music', service: 'youtube_music', owner: 'yours',
      line: 'Reading your Liked music is off',
      hint: "It reads through your YouTube login, so it's a choice in Settings.",
      later: "It reads through your YouTube login, so it's a choice in Settings. Turn it on there after setup; add another playlist for now.",
    });
  });
});
