#!/usr/bin/env node
// Screenshots of the fake-mode app in Playwright WebKit at three window sizes (1100 × 700, 1280 × 800, 2560 × 1440;
// scale 2), optionally side by side with the mockup. Fails on any console.error or uncaught page error.
//
//   node scripts/shots.mjs --port 5173 --page todo [--only <name>] [--sizes min,default,large | 1280x800] [--compare]
//   node scripts/shots.mjs --port 5170 --page base --compare      (the base's shell and gallery shots)
//   node scripts/shots.mjs --port 5178 --all
//   --jobs <n>: shots taken at once (default: half the cores, at most 6; 1 = one after another)
//
// Files are named <shot>@<width>.png (sync-before@1280.png). Shot format and steps: see shot-lib.mjs.
import { webkit } from 'playwright';
import { mkdirSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { pathToFileURL } from 'node:url';
import { WORKERS, loadShots, openShot, pageNames, parseSizes, pool, root, sizesFor } from './shot-lib.mjs';

const out = join(root, 'screenshots');
const mockups = resolve(root, '../docs/hub-mockups');

function args(argv) {
  const a = { port: 5170, page: null, only: null, sizes: null, compare: false, all: false, jobs: WORKERS };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--port') a.port = Number(argv[++i]);
    else if (k === '--page') a.page = argv[++i];
    else if (k === '--only') a.only = argv[++i];
    else if (k === '--sizes') a.sizes = argv[++i];
    else if (k === '--compare') a.compare = true;
    else if (k === '--all') a.all = true;
    else if (k === '--jobs') a.jobs = Math.max(1, Number(argv[++i]) || 1);
  }
  if (!a.page && !a.all) throw new Error('Give --page <page> or --all');
  return a;
}

// Left: the built screen at its real size. Right: the mockup at 1.15x (mockups are drawn small, plan 64.2).
async function compose(ctx, leftPng, rightPng, file, name) {
  const page = await ctx.newPage();
  const src = (b) => `data:image/png;base64,${b.toString('base64')}`;
  await page.setContent(`<!doctype html><html><body style="margin:0;background:#111;color:#999;font:12px -apple-system">
    <div style="display:flex;gap:16px;padding:12px;align-items:flex-start">
      <figure style="margin:0"><figcaption>built · ${name}</figcaption><img id="l" src="${src(leftPng)}" style="display:block"></figure>
      <figure style="margin:0"><figcaption>mockup × 1.15</figcaption><img id="r" src="${src(rightPng)}" style="display:block"></figure>
    </div></body></html>`);
  await page.waitForLoadState('load');
  await page.evaluate(() => {
    const l = document.getElementById('l'), r = document.getElementById('r');
    l.style.width = `${l.naturalWidth / 2}px`;
    r.style.width = `${(r.naturalWidth / 2) * 1.15}px`;
  });
  await page.screenshot({ path: file, fullPage: true });
  await page.close();
}

const a = args(process.argv.slice(2));
const sizes = parseSizes(a.sizes);
const shots = loadShots(a.all ? pageNames() : [a.page], a.only ? [a.only] : null);
if (!shots.length) { console.log('No shots.'); process.exit(0); }
mkdirSync(out, { recursive: true });
const browser = await webkit.launch();
const failures = [];
const taken = [];
const jobs = shots.flatMap((s) => sizesFor(s, sizes).map((size) => ({ s, size })));
await pool(browser, jobs, a.jobs, async (ctx, { s, size }) => {
  const label = `${s.name}@${size.w}`;
  const { page, errors, ok } = await openShot(ctx, a.port, s, size);
  try {
    if (ok) {
      const png = await page.screenshot({ path: join(out, `${label}.png`), fullPage: !!s.fullPage });
      if (s.each) {
        // one picture per matching element as well (e.g. every gallery section)
        const parts = await page.locator(s.each).all();
        for (let i = 0; i < parts.length; i++) await parts[i].screenshot({ path: join(out, `${s.name}-${String(i + 1).padStart(2, '0')}@${size.w}.png`) });
      }
      if (a.compare && s.mockup) {
        const m = await ctx.newPage();
        await m.goto(pathToFileURL(join(mockups, s.mockup)).href);
        const mp = s.mockupClip ? await m.locator(s.mockupClip).first().screenshot() : await m.screenshot({ fullPage: true });
        await m.close();
        await compose(ctx, png, mp, join(out, `${label}.compare.png`), label);
      }
    }
  } catch (e) {
    errors.push(`shot failed: ${e.message.split('\n')[0]}`);
  }
  taken.push(label);
  if (errors.length) failures.push({ name: label, errors });
  console.log(`${errors.length ? 'FAIL' : 'ok  '} ${String(taken.length).padStart(3)}/${jobs.length} ${label}${errors.length ? `  ${errors[0].slice(0, 160)}` : ''}`);
  await page.close();
});
await browser.close();
writeFileSync(join(out, 'last-run.json'), JSON.stringify({ shots: taken, failures }, null, 1));
if (failures.length) { console.log(`${failures.length} of ${taken.length} shots failed`); process.exit(1); }
console.log(`${taken.length} shots ok`);
