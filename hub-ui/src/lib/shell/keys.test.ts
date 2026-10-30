import { describe, expect, it } from 'vitest';
import { chromeKey, NAV, type KeyLike } from './keys';
import { playerKey } from './footModel';

const k = (o: Partial<KeyLike>): KeyLike => ({ key: '', code: '', metaKey: true, ctrlKey: false, altKey: false,
  shiftKey: false, repeat: false, ...o });
const ctx = { dialogOpen: false, onLibrary: false };

describe('chromeKey', () => {
  it('⌘1–⌘6 open the pages in the rail\'s order, by the key\'s place (code), whatever the layout prints', () => {
    const pages = ['1', '2', '3', '4', '5', '6'].map((d) => chromeKey(k({ code: `Digit${d}`, key: '&' }), ctx));
    expect(pages).toEqual(NAV.map((n) => ({ kind: 'page', page: n.key })));
  });
  it('⌘, opens Settings, ⌘K the filter, ⌃⌘S folds', () => {
    expect(chromeKey(k({ key: ',', code: 'Comma' }), ctx)).toEqual({ kind: 'page', page: 'settings' });
    expect(chromeKey(k({ key: 'k', code: 'KeyK' }), ctx)).toEqual({ kind: 'filter' });
    expect(chromeKey(k({ key: 's', code: 'KeyS', ctrlKey: true }), ctx)).toEqual({ kind: 'fold' });
    expect(chromeKey(k({ key: 'S', code: 'KeyS', ctrlKey: true }), ctx)).toEqual({ kind: 'fold' });
  });
  it('⌘I only on Library', () => {
    expect(chromeKey(k({ key: 'i', code: 'KeyI' }), ctx)).toBeNull();
    expect(chromeKey(k({ key: 'i', code: 'KeyI' }), { ...ctx, onLibrary: true })).toEqual({ kind: 'inspector' });
  });
  it('none while a dialog is open, none held down, none without ⌘ or with other modifiers', () => {
    const one = { code: 'Digit1', key: '1' };
    expect(chromeKey(k(one), { ...ctx, dialogOpen: true })).toBeNull();
    expect(chromeKey(k({ ...one, repeat: true }), ctx)).toBeNull();
    expect(chromeKey(k({ ...one, metaKey: false }), ctx)).toBeNull();
    expect(chromeKey(k({ ...one, shiftKey: true }), ctx)).toBeNull();
    expect(chromeKey(k({ ...one, altKey: true }), ctx)).toBeNull();
    expect(chromeKey(k({ ...one, ctrlKey: true }), ctx)).toBeNull();
    expect(chromeKey(k({ key: 'k', ctrlKey: false, metaKey: false }), ctx)).toBeNull();
  });
  it('leaves today\'s keys alone: ⌘F, ⌘C, ⌘A, ⌘Q, ⌃⌘F, ⌘← ⌘→, Space', () => {
    for (const key of ['f', 'c', 'v', 'x', 'a', 'q', 'h', 'ArrowLeft', 'ArrowRight']) {
      expect(chromeKey(k({ key }), { ...ctx, onLibrary: true })).toBeNull();
    }
    expect(chromeKey(k({ key: 'f', ctrlKey: true }), ctx)).toBeNull();
    expect(chromeKey(k({ key: ' ', metaKey: false }), ctx)).toBeNull();
  });
  it('and the player\'s keys never take the chrome\'s', () => {
    for (const e of [k({ code: 'Digit3', key: '3' }), k({ key: 'k' }), k({ key: 'i' }), k({ key: 's', ctrlKey: true }), k({ key: ',' })]) {
      expect(playerKey(e, null, false)).toBeNull();
    }
  });
});
