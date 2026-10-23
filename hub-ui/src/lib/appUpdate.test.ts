import { describe, expect, it } from 'vitest';
import { aboutLine, shortVersion, updateLink } from './appUpdate';
import type { AppUpdate } from './bridge/types';

const URL_ = 'https://github.com/TheZwiss/discjockey/releases/tag/v1.1.0';
const available: AppUpdate = { state: 'available', current: '1.0.0', latest: '1.1.0', url: URL_ };
const upToDate: AppUpdate = { state: 'up_to_date', current: '1.0.0', latest: null, url: null };
const unknown: AppUpdate = { state: 'unknown', current: '1.0.0', latest: null, url: null };

describe('appUpdate', () => {
  it('shortens x.y.0 to x.y and keeps a patch number', () => {
    expect(shortVersion('1.1.0')).toBe('1.1');
    expect(shortVersion('2.0.0')).toBe('2.0');
    expect(shortVersion('1.1.2')).toBe('1.1.2');
    expect(shortVersion('1.10.0')).toBe('1.10');
    expect(shortVersion('odd')).toBe('odd');
  });
  it('offers the link only for a newer version with its page', () => {
    expect(updateLink(available)).toEqual({ text: 'Discjockey 1.1 is available', url: URL_ });
    expect(updateLink(upToDate)).toBeNull();
    expect(updateLink(unknown)).toBeNull();
    expect(updateLink(null)).toBeNull();
    expect(updateLink({ ...available, url: null })).toBeNull();
    expect(updateLink({ ...available, latest: null })).toBeNull();
  });
  it("says the About row's state: up to date, the newer version, or nothing without an answer", () => {
    expect(aboutLine(upToDate)).toBe('up to date');
    expect(aboutLine(available)).toBe('1.1 is available');
    expect(aboutLine(unknown)).toBeNull();
    expect(aboutLine(null)).toBeNull();
  });
});
