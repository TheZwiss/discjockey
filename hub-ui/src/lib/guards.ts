// Source guards of the design system (spec §9), pure so their tests can feed them strings as fixtures.
// outdated.test.ts and guards.test.ts run them over the tree.
import { OUTDATED, OUTDATED_TOKENS } from './outdated';

/** The blocks a source file imports, by their file names: named imports from the components index
 *  (`import { Card } from '$lib/components'`, also `../components`, `./index`) and imports of a block's own file
 *  (`import Card from '$lib/components/Card.svelte'`, `./Card.svelte`), with either quote. An alias counts as the
 *  block it names (`{ Card as Box }` → Card). */
export function importedBlocks(src: string): string[] {
  const named = [...src.matchAll(/import\s*(?:type\s*)?\{([^}]*)\}\s*from\s*['"]([^'"]*)['"]/g)]
    .filter((m) => /(^|\/)components(\/index(\.ts)?)?$|^\.\/index(\.ts)?$/.test(m[2]))
    .flatMap((m) => m[1].split(',').map((s) => s.trim().replace(/^type\s+/, '').split(/\s+as\s+/)[0]).filter(Boolean));
  const files = [...src.matchAll(/import\s+[\w$]+\s+from\s*['"]([^'"]*\/)?([\w$]+)\.svelte['"]/g)].map((m) => m[2]);
  return [...named, ...files];
}

/** The outdated blocks among a file's imports. */
export const outdatedBlocksIn = (src: string): string[] =>
  importedBlocks(src).filter((n) => (OUTDATED as readonly string[]).includes(n));

/** The outdated tokens a file reads (`var(--r-card)`, also with a fallback: `var(--r-card, 10px)`). */
export const outdatedTokensIn = (src: string): string[] =>
  OUTDATED_TOKENS.filter((t) => new RegExp(`var\\(\\s*${t}\\s*[,)]`).test(src));

/** The outdated Button variant `ghost`, as an attribute or a prop value. */
export const usesGhost = (src: string): boolean => /variant\s*(=|:)\s*\{?\s*["']ghost["']/.test(src);

/** The markers the rule checker trusts: a block or a frame sets each one, a page never writes it by hand. A page that
 *  wrote `data-note` on a paragraph made its own shelter from the loose-text rule (final review I5: LiveView did). */
export const BLOCK_MARKERS = ['note', 'surface', 'infotip', 'dev', 'hint', 'row-hit', 'frame', 'frame-main',
  'frame-content', 'frame-foot', 'panel', 'panel-root', 'panel-head', 'panel-fill', 'panel-after', 'panel-foot',
  'page-header', 'max', 'stretch', 'primary', 'read-status'] as const;

/** The block markers written as attributes in a file's markup. A selector that names one (`'[data-panel]'`, a
 *  `querySelector` or a shot's `wait`) reads it and is fine. */
export function handWrittenMarkers(src: string): string[] {
  const names = [...BLOCK_MARKERS].sort((a, b) => b.length - a.length).join('|');
  return [...src.matchAll(new RegExp(`(?<![\\w-])data-(${names})(?=[\\s=>/{])`, 'g'))].map((m) => `data-${m[1]}`);
}
