import { afterEach, describe, expect, it } from 'vitest';
import { get } from 'svelte/store';
import { getPref, persisted, setPref } from './prefs';

const mem = () => {
  const m = new Map<string, string>();
  return { getItem: (k: string) => m.get(k) ?? null, setItem: (k: string, v: string) => void m.set(k, v), m };
};
afterEach(() => { delete (globalThis as any).localStorage; });

describe('prefs', () => {
  it('saves with the discjockey. prefix and reads back', () => {
    const s = mem();
    (globalThis as any).localStorage = s;
    setPref('todo.filter', 'weak');
    expect(s.m.get('discjockey.todo.filter')).toBe('"weak"');
    expect(getPref('todo.filter', 'all')).toBe('weak');
  });
  it('a throwing storage gives the default and never throws', () => {
    (globalThis as any).localStorage = { getItem() { throw new Error('blocked'); }, setItem() { throw new Error('full'); } };
    expect(getPref('x', 3)).toBe(3);
    expect(() => setPref('x', 4)).not.toThrow();
    const p = persisted('x', 'a');
    p.set('b');
    expect(get(p)).toBe('b');
  });
  it('no storage at all, broken JSON or a wrong type give the default', () => {
    expect(getPref('x', true)).toBe(true);
    const s = mem();
    (globalThis as any).localStorage = s;
    s.m.set('discjockey.a', '{broken');
    s.m.set('discjockey.b', '"text"');
    expect(getPref('a', 1)).toBe(1);
    expect(getPref('b', 1)).toBe(1);
  });
});
