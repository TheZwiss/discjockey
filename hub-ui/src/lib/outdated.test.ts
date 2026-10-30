import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { basename, join, relative } from 'node:path';
import { REDESIGNED } from '../pages/designSystem';
import { OUTDATED, OUTDATED_TOKENS } from './outdated';
import { importedBlocks, outdatedBlocksIn, outdatedTokensIn, usesGhost } from './guards';

const files = (dir: string): string[] => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? files(p) : /\.(svelte|ts)$/.test(f) && !f.endsWith('.test.ts') ? [p] : [];
});
const name = (f: string) => relative(__dirname, f);

// What a redesigned page renders: its own folder, and the blocks and frames (final review I3: the guard read only
// page folders, so Skeleton's --r-card and ReadStatus's ghost reached Sync unseen). The outdated blocks themselves
// are skipped; tokens.css defines the outdated tokens and isn't scanned.
const pageFiles = (page: string) => files(join(__dirname, '../pages', page));
const blockFiles = ['components', 'frames'].flatMap((d) => files(join(__dirname, d)))
  .filter((f) => !(OUTDATED as readonly string[]).includes(basename(f).replace(/\.svelte$/, '')));

/** An outdated use a block may keep, with why. Each is checked below to be rendered by no redesigned page. Empty
 *  since To-do's pass moved UpgradeCard onto Surface; kept for the next block that needs a stay. */
const ALLOWED: Record<string, { block: string; why: string }> = {};

function problems(list: string[]): string[] {
  return list.filter((f) => !ALLOWED[name(f)]).flatMap((f) => {
    const src = readFileSync(f, 'utf8');
    return [...outdatedBlocksIn(src), ...outdatedTokensIn(src), ...(usesGhost(src) ? ['variant="ghost"'] : [])]
      .map((x) => `${name(f)}: ${x}`);
  });
}

describe('redesigned pages use only current blocks, tokens and variants', () => {
  for (const page of REDESIGNED) it(page, () => expect(problems(pageFiles(page))).toEqual([]));
  it('and so do the blocks and frames they render', () => expect(problems(blockFiles)).toEqual([]));
  it('no redesigned page imports a block that keeps an allowed outdated use', () => {
    const allowed = Object.values(ALLOWED).map((a) => a.block);
    const bad = REDESIGNED.flatMap((p) => pageFiles(p).flatMap((f) =>
      importedBlocks(readFileSync(f, 'utf8')).filter((b) => allowed.includes(b)).map((b) => `${name(f)}: ${b}`)));
    expect(bad).toEqual([]);
  });
  it('has at least the list to check', () => expect(OUTDATED.length).toBeGreaterThan(0));
  it('lists only tokens that tokens.css still defines and marks OUTDATED', () => {
    const css = readFileSync(join(__dirname, 'styles/tokens.css'), 'utf8');
    for (const t of OUTDATED_TOKENS) {
      const line = css.split('\n').find((l) => l.includes(`${t}:`));
      expect(line, t).toBeDefined();
      expect(line, t).toMatch(/OUTDATED/);
    }
  });
});
