import { describe, expect, it } from 'vitest';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { CONTRACT_METHODS, LIBRARY_METHODS } from './contract';
import { createFakeBridge } from './fake/bridge';

const apiPy = readFileSync(fileURLToPath(new URL('../../../../discjockey/hub/api.py', import.meta.url)), 'utf8');

describe('contract', () => {
  it('CONTRACT_METHODS are exactly the @bridge methods of api.py, in order', () => {
    const found = [...apiPy.matchAll(/@bridge\s+def (\w+)/g)].map((m) => m[1]);
    expect(found.length).toBeGreaterThan(40);
    expect([...CONTRACT_METHODS].sort()).toEqual([...found].sort());
    expect(new Set(CONTRACT_METHODS).size).toBe(CONTRACT_METHODS.length);
  });
  it('LIBRARY_METHODS are exactly api.py LIBRARY_METHODS', () => {
    const block = /LIBRARY_METHODS = frozenset\(\(([\s\S]*?)\)\)/.exec(apiPy);
    expect(block).not.toBeNull();
    const names = [...block![1].matchAll(/"(\w+)"/g)].map((m) => m[1]);
    expect([...LIBRARY_METHODS].sort()).toEqual(names.sort());
  });
  it('the fake bridge has every method and nothing else', () => {
    const fake = createFakeBridge('normal');
    expect(Object.keys(fake).sort()).toEqual([...CONTRACT_METHODS].sort());
  });
});
