import { describe, expect, it } from 'vitest';
import { OFFLINE_WORDS, ago, artistTitle, clock, cutoffStat, dateShort, dayMonth, duration, estimate, estimateText, fileFormat, fitMiddle, foldText, khz, megabytes, minutesLong, noteParts, percent, plural,
  qualityWords, runIdFromReport, runWhen, upgradeLabel } from './format';

describe('format', () => {
  it('estimate: one time format for every estimate (spec §11)', () => {
    expect(estimate(5)).toEqual({ value: '~5', unit: 'min' });
    expect(estimate(75)).toEqual({ value: '~75', unit: 'min' });
    expect(estimate(119.4)).toEqual({ value: '~119', unit: 'min' });
    expect(estimate(120)).toEqual({ value: '~2', unit: 'h' });
    expect(estimate(140)).toEqual({ value: '~2.5', unit: 'h' });   // to the half hour
    expect(estimate(-3)).toEqual({ value: '~0', unit: 'min' });
    expect(estimate(null)).toEqual({ value: '—', unit: '' });
    expect(estimateText(75)).toBe('~75 min');
    expect(estimateText(200)).toBe('~3.5 h');
    expect(estimateText(undefined)).toBe('—');
  });
  it('duration', () => {
    expect(duration(192)).toBe('3:12');
    expect(duration(156.4)).toBe('2:36');
    expect(duration(5)).toBe('0:05');
    expect(duration(3725)).toBe('1:02:05');
    expect(duration(null)).toBe('—');
  });
  it('minutesLong', () => {
    expect(minutesLong(25)).toBe('25 min');
    expect(minutesLong(92)).toBe('1 h 32 min');
    expect(minutesLong(120)).toBe('2 h');
  });
  it('megabytes, percent, khz', () => {
    expect(megabytes(19_800_000)).toBe('19.8');
    expect(percent(0.7412)).toBe('74 %');
    expect(percent(null)).toBe('—');
    expect(percent(1)).toBe('100 %');
    expect(khz(16000)).toBe('16.0 kHz');
    expect(khz(20500)).toBe('20.5 kHz');
  });
  it('ago', () => {
    expect(ago(0)).toBe('just now');
    expect(ago(2)).toBe('2 min ago');
    expect(ago(185)).toBe('3 h ago');
    expect(ago(60 * 30)).toBe('yesterday');
    expect(ago(60 * 24 * 4)).toBe('4 days ago');
    expect(ago(null)).toBe('never');
  });
  it('runWhen, dateShort, clock', () => {
    const now = new Date('2026-10-16T22:00:00');
    expect(runWhen('2026-10-16T21:47:00', now)).toBe('Today 21:47');
    expect(runWhen('2026-10-15T21:47:00', now)).toBe('Yesterday 21:47');
    expect(runWhen('2026-10-13T21:47:00', now)).toBe('Tue 13 Oct');
    expect(dateShort('2026-10-13T21:47:00')).toBe('13 Oct 2026');
    expect(dateShort('2026-10-13')).toBe('13 Oct 2026');
    expect(dayMonth('2026-10-03T21:47:00')).toBe('3 Oct');
    expect(dayMonth(null)).toBe('');
    expect(clock('2026-10-13T09:05:00')).toBe('09:05');
  });
  it('plural, artistTitle, runIdFromReport', () => {
    expect(plural(1, 'track')).toBe('1 track');
    expect(plural(3, 'track')).toBe('3 tracks');
    expect(plural(2, 'match', 'matches')).toBe('2 matches');
    expect(artistTitle('Pegassi', 'AEIOU')).toBe('Pegassi – AEIOU');
    expect(artistTitle('', 'AEIOU')).toBe('AEIOU');
    expect(runIdFromReport('/Users/you/Music/Discjockey/.discjockey/reports/2026-10-16_132430.md'))
      .toBe('2026-10-16_132430');
    expect(runIdFromReport(null)).toBeNull();
  });
  it('noteParts turns Markdown links into links, never raw Markdown', () => {
    expect(noteParts('not found · [Beatport](https://www.beatport.com/search?q=a+b) · [Bandcamp](https://bandcamp.com/search?q=a)'))
      .toEqual([{ text: 'not found · ' }, { label: 'Beatport', href: 'https://www.beatport.com/search?q=a+b' },
        { text: ' · ' }, { label: 'Bandcamp', href: 'https://bandcamp.com/search?q=a' }]);
    expect(noteParts('plain')).toEqual([{ text: 'plain' }]);
    expect(noteParts('[x](http://insecure)')).toEqual([{ text: '[x](http://insecure)' }]);
  });
});

describe('qualityWords', () => {
  it('says what the badge means without repeating it', () => {
    expect(qualityWords('good_lossy', '20.1 kHz')).toBe('lossy, hard to hear');
    expect(qualityWords('good_lossy', 'LOSSY')).toBe('hard to hear');
    expect(qualityWords('lossless', 'LOSSLESS')).toBe('verified lossless');
  });
  it('says the sound is not checked yet, whatever the codec guessed', () => {
    expect(qualityWords('lossless', 'LOSSLESS', false)).toBe('sound not checked yet');
    expect(qualityWords('good_lossy', 'LOSSY', false)).toBe('sound not checked yet');
  });
  it('cutoffStat shows nothing for a file whose sound is not checked yet', () => {
    expect(cutoffStat({ status: 'not_lossless', cutoff_hz: null, sound_checked: false })).toBeNull();
    expect(cutoffStat({ status: 'not_lossless', cutoff_hz: null, sound_checked: true })).not.toBeNull();
  });
  it('cutoffStat names the format a fake lossless file really is, from its path', () => {
    const fake = (path: string | null) => cutoffStat({ status: 'fake_lossless', cutoff_hz: 16000, path })!.label;
    expect(fake('/Volumes/Example/x.wav')).toBe('where the highs end · a lossy file inside the WAV');
    expect(fake('Library/A/x.FLAC')).toBe('where the highs end · a lossy file inside the FLAC');
    expect(fake('/m/x.aiff')).toBe('where the highs end · a lossy file inside the AIFF');
    expect(fake('/m/x.aif')).toContain('the AIFF');
    expect(fake('/m/no-extension')).toBe('where the highs end · a lossy file inside a lossless file');
    expect(fake(null)).toBe('where the highs end · a lossy file inside a lossless file');
    expect(fileFormat('/m/x.mp3')).toBeNull();
  });
  it('OFFLINE_WORDS are the folder state line\'s words', () => expect(OFFLINE_WORDS).toBe('Offline: connect the drive'));
  it('upgradeLabel: "Upgrade ready", plus what it is when it is not lossless', () => {
    expect(upgradeLabel('lossless version')).toBe('Upgrade ready');
    expect(upgradeLabel(undefined)).toBe('Upgrade ready');
    expect(upgradeLabel('256 kbps version')).toBe('Upgrade ready · 256 kbps version');
  });
});

describe('foldText', () => {
  it('drops case and accents', () => expect(foldText('Kölsch MIX É')).toBe('kolsch mix e'));
});

describe('fitMiddle', () => {
  const upTo = (n: number) => (s: string) => s.length <= n;   // a width measured in characters
  const a = 'Example Artist - Some Long Title (REMIX x GUEST EDIT).wav';
  const b = 'Example Artist - Some Long Title (REMIX x GUEST EDIT)(1).wav';
  it('leaves a text that fits whole', () => {
    expect(fitMiddle(a, upTo(a.length))).toBe(a);
    expect(fitMiddle('ab', upTo(1))).toBe('ab');
  });
  it('gives up the middle, both ends stay, so two names with the same start differ at the end', () => {
    const x = fitMiddle(a, upTo(30)), y = fitMiddle(b, upTo(30));
    expect(x.length).toBeLessThanOrEqual(30);
    expect(x).toMatch(/^Example.*….*EDIT\)\.wav$/);
    expect(y).toMatch(/^Example.*….*EDIT\)\(1\)\.wav$/);
    expect(x).not.toBe(y);
  });
  it('uses the room it has: one more character shows at least as much', () => {
    expect(fitMiddle(a, upTo(31)).length).toBeGreaterThanOrEqual(fitMiddle(a, upTo(30)).length);
    expect(fitMiddle(a, upTo(a.length - 1)).length).toBeGreaterThanOrEqual(a.length - 3);   // a blank beside the … is dropped
  });
  it('keeps a character of each end when nothing fits', () => {
    expect(fitMiddle(a, upTo(0))).toBe('E…v');
  });
  it('leaves no blank beside the ellipsis', () => {
    expect(fitMiddle('Artist - Title', upTo(9))).not.toMatch(/ …|… /);
  });
});
