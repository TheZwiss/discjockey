import { describe, expect, it } from 'vitest';
import { NAV } from './keys';
import { navCount, navTip, railPill, type NavSignals } from './sidebarModel';

describe('the sidebar\'s words and marks', () => {
  const quiet: NavSignals = { todo: 0, sync: null, limitsWarning: false };
  const busy: NavSignals = { todo: 5, sync: { index: 12, total: 40, frac: 0.3 }, limitsWarning: true };
  it('a quiet page\'s tooltip is its name', () => {
    expect(NAV.map((n) => navTip(n.key, n.label, quiet))).toEqual(NAV.map((n) => n.label));
  });
  it('To-do, a running sync and Download limits\' dot add their signal in words', () => {
    expect(navTip('todo', 'To-do', busy)).toBe('To-do · 5 to look at');
    expect(navTip('sync', 'Sync', busy)).toBe('Sync · syncing, 12 of 40');
    expect(navTip('sync', 'Sync', { ...busy, sync: { index: 0, total: null, frac: 0 } })).toBe('Sync · reading playlists');
    expect(navTip('limits', 'Download limits', busy)).toBe('Download limits · a warning sign to look at, or a service paused today');
    expect(navTip('library', 'Library', busy)).toBe('Library');
  });
  it('the full form\'s count column: To-do\'s count and the sync\'s "12/40"', () => {
    expect(navCount('todo', busy)).toBe('5');
    expect(navCount('sync', busy)).toBe('12/40');
    expect(navCount('todo', quiet)).toBeNull();
    expect(navCount('sync', { ...busy, sync: { index: 0, total: null, frac: 0 } })).toBeNull();
  });
  it('the rail\'s pill holds two digits', () => {
    expect([railPill(0), railPill(7), railPill(99), railPill(312)]).toEqual([null, '7', '99', '99+']);
  });
});
