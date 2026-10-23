#!/usr/bin/env node
// Every visible string per page of the fake-mode app, for the wording review (Task 72). Needs `npm run dev`.
// For each page it opens the shots of src/pages/<page>/shots.json (or just #/<page> when there are none), runs
// their steps, and collects the visible text plus aria-label / placeholder / title attributes. Strings outside
// <main> (sidebar, banners, toasts) go to "shell". Writes screenshots/strings.json and prints a count per page.
//
//   node scripts/strings.mjs --port 5170 [--page todo]
import { webkit } from 'playwright';
import { existsSync, mkdirSync, readFileSync, readdirSync, writeFileSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { runSteps } from './shot-lib.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const out = join(root, 'screenshots');
const argv = process.argv.slice(2);
const opt = (k, d) => (argv.includes(k) ? argv[argv.indexOf(k) + 1] : d);
const port = Number(opt('--port', 5170));
const only = opt('--page', null);

const pages = readdirSync(join(root, 'src/pages'), { withFileTypes: true }).filter((d) => d.isDirectory())
  .map((d) => d.name).filter((p) => !only || p === only);
function visits(page) {
  const f = join(root, 'src/pages', page, 'shots.json');
  const shots = existsSync(f) ? JSON.parse(readFileSync(f, 'utf8')) : [];
  return shots.length ? shots : [{ name: page, route: `#/${page === 'dashboard' ? '' : page}`, scenario: 'normal' }];
}

// Runs in the page: visible text nodes and labelling attributes, split into inside/outside <main>.
function collect() {
  const res = { main: [], shell: [] };
  const visible = (el) => {
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    }
    return true;
  };
  const add = (el, text) => {
    const t = text.replace(/\s+/g, ' ').trim();
    if (!t || /^[\d\s.,:%×·–—/+-]*$/.test(t)) return;   // skip pure numbers and separators
    (el.closest('main') ? res.main : res.shell).push(t);
  };
  const walk = document.createTreeWalker(document.body, NodeFilter.SHOW_TEXT);
  for (let n = walk.nextNode(); n; n = walk.nextNode()) {
    const p = n.parentElement;
    if (p && !['SCRIPT', 'STYLE'].includes(p.tagName) && !p.closest('[data-test=fake-toolbar]') && visible(p)) add(p, n.textContent);
  }
  for (const el of document.querySelectorAll('[aria-label],[placeholder],[title]')) {
    if (!visible(el) || el.closest('[data-test=fake-toolbar]')) continue;
    for (const a of ['aria-label', 'placeholder', 'title']) if (el.getAttribute(a)) add(el, el.getAttribute(a));
  }
  return res;
}

const browser = await webkit.launch();
const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
const result = {};
const shell = new Set();
let failed = 0;
for (const p of pages) {
  const set = new Set();
  for (const v of visits(p)) {
    const page = await ctx.newPage();
    const q = new URLSearchParams({ scenario: v.scenario ?? 'normal', ...(v.query ?? {}) });
    try {
      await page.goto(`http://localhost:${port}/?${q}${v.route ?? '#/'}`);
      await page.waitForSelector('[data-page-ready]', { timeout: 15000 });
      await runSteps(page, v.steps);
      await page.waitForTimeout(v.settle ?? 250);
      const r = await page.evaluate(collect);
      r.main.forEach((s) => set.add(s));
      r.shell.forEach((s) => shell.add(s));
    } catch (e) {
      failed++;
      console.log(`FAIL ${p} ${v.name}: ${e.message.split('\n')[0]}`);
    }
    await page.close();
  }
  result[p] = [...set].sort();
  console.log(`${p}: ${result[p].length} strings`);
}
result.shell = [...shell].sort();
console.log(`shell: ${result.shell.length} strings`);
await browser.close();
mkdirSync(out, { recursive: true });
writeFileSync(join(out, 'strings.json'), JSON.stringify(result, null, 1));
console.log(`wrote screenshots/strings.json${failed ? ` (${failed} visits failed)` : ''}`);
process.exit(failed ? 1 : 0);
