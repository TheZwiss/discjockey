import { describe, expect, it } from 'vitest';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { FULL_W, NARROW_BELOW, RAIL_W } from './stores/chrome';
import { handWrittenMarkers, importedBlocks, outdatedBlocksIn, outdatedTokensIn, usesGhost } from './guards';

const files = (dir: string): string[] => readdirSync(dir).flatMap((f) => {
  const p = join(dir, f);
  return statSync(p).isDirectory() ? files(p) : /\.(svelte|ts)$/.test(f) && !f.endsWith('.test.ts') ? [p] : [];
});

describe('the guards on source fixtures', () => {
  it('importedBlocks: named, aliased, type, index and direct-path imports, either quote', () => {
    expect(importedBlocks(`import { Button, Card as Box, type Bulk } from '$lib/components';`)).toEqual(['Button', 'Card', 'Bulk']);
    expect(importedBlocks(`import Card from "$lib/components/Card.svelte";`)).toEqual(['Card']);
    expect(importedBlocks(`import Chip from './Chip.svelte';\nimport { Tile } from "../components";`)).toEqual(['Tile', 'Chip']);
    expect(importedBlocks(`import { api } from '$lib/bridge/client';\nimport { Card } from './cards';`)).toEqual([]);
  });
  it('outdatedBlocksIn fails an outdated block, passes a current one', () => {
    expect(outdatedBlocksIn(`import Card from '$lib/components/Card.svelte';`)).toEqual(['Card']);
    expect(outdatedBlocksIn(`import { Surface } from '$lib/components';`)).toEqual([]);
  });
  it('outdatedTokensIn fails an outdated token (also with a fallback), passes a current one', () => {
    expect(outdatedTokensIn(`.a { border-radius: var(--r-card); transition: opacity var(--t-fast, 120ms); }`)).toEqual(['--t-fast', '--r-card']);
    expect(outdatedTokensIn(`.a { border-radius: var(--r-surface); font-size: var(--fs-bigger); }`)).toEqual([]);
  });
  it('usesGhost fails the ghost variant, passes the others', () => {
    expect(usesGhost(`<Button variant="ghost">Cancel</Button>`)).toBe(true);
    expect(usesGhost(`const b = { variant: 'ghost' };`)).toBe(true);
    expect(usesGhost(`<Button variant="secondary">Cancel</Button> <!-- not a ghost -->`)).toBe(false);
  });
  it('handWrittenMarkers fails a marker written in markup, passes one read in a selector', () => {
    expect(handWrittenMarkers(`<p class="err" data-note="problem">x</p><div data-surface={k} data-panel-foot>`))
      .toEqual(['data-note', 'data-surface', 'data-panel-foot']);
    expect(handWrittenMarkers(`el.closest('[data-panel-foot]'); <div data-test="x" data-notes="y" data-scrolls-itself>`)).toEqual([]);
  });
});

describe('pages never write a block marker by hand (final review I5)', () => {
  it('src/pages', () => {
    const pages = join(__dirname, '../pages');
    const bad = files(pages).flatMap((f) => handWrittenMarkers(readFileSync(f, 'utf8')).map((m) => `${relative(pages, f)}: ${m}`));
    expect(bad).toEqual([]);
  });
});

describe('the panel breakpoint has one value', () => {
  it("tokens.css --panel-narrow-below is ListPanelFrame's media query", () => {
    const token = /--panel-narrow-below:\s*(\d+)px/.exec(readFileSync(join(__dirname, 'styles/tokens.css'), 'utf8'));
    const query = /@media \(width < (\d+)px\)/.exec(readFileSync(join(__dirname, 'frames/ListPanelFrame.svelte'), 'utf8'));
    expect(token?.[1]).toBeDefined();
    expect(query?.[1]).toBe(token?.[1]);
  });
});

describe('the chrome widths have one value', () => {
  const css = readFileSync(join(__dirname, 'styles/tokens.css'), 'utf8');
  const token = (name: string) => Number(new RegExp(`${name}:\\s*(\\d+)px`).exec(css)?.[1]);
  it("chrome.ts FULL_W, RAIL_W and NARROW_BELOW are tokens.css's --sidebar-full-w, --rail-w and --panel-narrow-below", () => {
    expect(token('--sidebar-full-w')).toBe(FULL_W);
    expect(token('--rail-w')).toBe(RAIL_W);
    expect(token('--panel-narrow-below')).toBe(NARROW_BELOW);
  });
});
