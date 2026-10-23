#!/usr/bin/env node
// Design-system rule checker (spec §9): runs every shot of every redesigned page at the three window sizes and
// reports what breaks the rules (rules-page.js says which). Without --port it starts the fake-mode dev server on a
// free port and stops it at the end.
//
//   node scripts/rules.mjs                       every page listed in REDESIGNED (src/pages/designSystem.ts)
//   node scripts/rules.mjs --page sync --force   one page, even if it isn't flagged yet (while it is being built)
//   node scripts/rules.mjs --only a,b            only the named shots
//   node scripts/rules.mjs --port 5173           use a dev server that is already running
//   node scripts/rules.mjs --jobs 1              shots checked at once (default: half the cores, at most 6)
//   node scripts/rules.mjs --self-test           check the checker against scripts/rules-fixtures/ (good*.html pass,
//                                                bad-<rule>[--<case>].html break exactly <rule>)
import { webkit } from 'playwright';
import { spawn } from 'node:child_process';
import { readFileSync, readdirSync } from 'node:fs';
import { createServer } from 'node:net';
import { dirname, join } from 'node:path';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { WORKERS, loadShots, openShot, pageNames, parseSizes, pool, root, sizesFor } from './shot-lib.mjs';

const here = dirname(fileURLToPath(import.meta.url));
const fixtures = join(here, 'rules-fixtures');
const rulesPage = join(here, 'rules-page.js');

function fail(message) {
  console.error(`rules: ${message}`);
  process.exit(1);
}

function args(argv) {
  const a = { port: null, page: null, only: null, force: false, selfTest: false, jobs: WORKERS };
  for (let i = 0; i < argv.length; i++) {
    const k = argv[i];
    if (k === '--port') a.port = Number(argv[++i]);
    else if (k === '--page') a.page = argv[++i];
    else if (k === '--only') a.only = argv[++i].split(',');
    else if (k === '--force') a.force = true;
    else if (k === '--self-test') a.selfTest = true;
    else if (k === '--jobs') a.jobs = Math.max(1, Number(argv[++i]) || 1);
    else fail(`unknown argument ${k}`);
  }
  return a;
}

// REDESIGNED is a plain list in a .ts file so vitest can read it too; read the quoted names out of it here.
function redesigned() {
  const src = readFileSync(join(root, 'src/pages/designSystem.ts'), 'utf8');
  const m = /REDESIGNED\s*:\s*string\[\]\s*=\s*\[([^\]]*)\]/.exec(src);
  if (!m) throw new Error('src/pages/designSystem.ts: REDESIGNED list not found');
  return [...m[1].matchAll(/'([^']+)'|"([^"]+)"/g)].map((x) => x[1] ?? x[2]);
}

function freePort() {
  return new Promise((resolve, reject) => {
    const srv = createServer();
    srv.once('error', reject);
    srv.listen(0, '127.0.0.1', () => { const { port } = srv.address(); srv.close(() => resolve(port)); });
  });
}

async function startServer() {
  const port = await freePort();
  const proc = spawn(join(root, 'node_modules/.bin/vite'), ['--mode', 'fake', '--strictPort', '--port', String(port)], { cwd: root, stdio: 'ignore' });
  let exited = false;
  proc.once('exit', () => { exited = true; });
  process.on('exit', () => proc.kill('SIGTERM'));   // also when the checker itself dies half-way
  for (const [sig, code] of [['SIGINT', 130], ['SIGTERM', 143]]) process.on(sig, () => { proc.kill('SIGTERM'); process.exit(code); });
  for (let i = 0; i < 150; i++) {
    if (exited) throw new Error('The fake dev server stopped on start');
    try { if ((await fetch(`http://localhost:${port}/`)).ok) return { port, stop: () => proc.kill('SIGTERM') }; } catch { /* not up yet */ }
    await new Promise((r) => setTimeout(r, 200));
  }
  proc.kill('SIGTERM');
  throw new Error('The fake dev server did not start within 30 s');
}

async function selfTest() {
  const browser = await webkit.launch();
  const page = await browser.newPage({ viewport: { width: 1100, height: 700 } });
  const problems = [];
  const names = readdirSync(fixtures).filter((f) => f.endsWith('.html')).sort();
  for (const f of names) {
    // a fixture may ask for its window size (`<html data-viewport="1280x800">`), e.g. for the panel's breakpoint
    const vp = /data-viewport="(\d+)x(\d+)"/.exec(readFileSync(join(fixtures, f), 'utf8'));
    await page.setViewportSize(vp ? { width: Number(vp[1]), height: Number(vp[2]) } : { width: 1100, height: 700 });
    await page.goto(pathToFileURL(join(fixtures, f)).href);
    let found;
    try { found = await page.evaluate(() => window.__rules()); } catch (e) { problems.push(`${f}: window.__rules failed (${e.message.split('\n')[0]})`); continue; }
    const kinds = [...new Set(found.map((v) => v.rule))];
    // good*.html pass every rule; bad-<rule>[--<case>].html break exactly <rule>
    if (f.startsWith('good')) { if (found.length) problems.push(`${f}: expected no violations, got ${JSON.stringify(found)}`); continue; }
    const want = f.replace(/^bad-/, '').replace(/(--[\w-]+)?\.html$/, '');
    if (!kinds.includes(want)) problems.push(`${f}: expected a "${want}" violation, got [${kinds.join(', ')}]`);
    else if (kinds.length > 1) problems.push(`${f}: expected only "${want}", got [${kinds.join(', ')}] ${JSON.stringify(found)}`);
  }
  await browser.close();
  if (problems.length) { for (const p of problems) console.log(`FAIL ${p}`); process.exit(1); }
  console.log(`${names.length} fixtures ok`);
}

async function check(a) {
  const flagged = redesigned();
  const known = pageNames();
  if (a.page && !known.includes(a.page)) fail(`no page "${a.page}" (pages: ${known.join(', ')})`);
  if (a.force && !a.page) fail('--force needs --page <page>');
  if (a.page && !flagged.includes(a.page) && !a.force) fail(`"${a.page}" is not in REDESIGNED (src/pages/designSystem.ts); add --force to check it anyway`);
  const candidates = a.page ? [a.page] : known;
  const run = candidates.filter((p) => flagged.includes(p) || (a.force && p === a.page));
  const skipped = known.filter((p) => !run.includes(p) && loadShots([p]).length).length;
  const shots = loadShots(run, a.only);
  if (a.only) {
    const missing = a.only.filter((n) => !shots.some((x) => x.name === n));
    if (missing.length) fail(`no shot named ${missing.join(', ')} in ${run.length ? run.join(', ') : 'any redesigned page'}`);
  }
  if (a.page && !shots.length) fail(`page "${a.page}" has no shots`);
  const sizes = parseSizes(null);
  const total = shots.reduce((n, s) => n + sizesFor(s, sizes).length, 0);
  if (!shots.length) { console.log(`${run.length} redesigned pages · ${skipped} skipped`); return; }

  const server = a.port ? null : await startServer();
  const port = a.port ?? server.port;
  let failed = 0;
  let browser;
  try {
    browser = await webkit.launch();
    const jobs = shots.flatMap((s) => sizesFor(s, sizes).map((size) => ({ s, size })));
    let done = 0;
    await pool(browser, jobs, a.jobs, async (ctx, { s, size }) => {
      const label = `${s.name}@${size.w}`;
      const { page, errors, ok } = await openShot(ctx, port, s, size);
      const lines = errors.map((e) => `FAIL ${label} error: ${e.slice(0, 200)}`);
      if (ok) {
        await page.addScriptTag({ path: rulesPage });
        for (const v of await page.evaluate(() => window.__rules())) lines.push(`FAIL ${label} ${v.rule}: ${v.where}: ${v.detail}`);
      }
      for (const l of lines) console.log(l);
      if (lines.length) failed++;
      await page.close();
      // a progress line every 25 shots, so a long run is never silent
      if (++done % 25 === 0 && done < jobs.length) console.log(`… ${done}/${jobs.length} shots checked`);
    });
  } finally {
    await browser?.close();
    server?.stop();
  }
  console.log(`${run.length} redesigned pages · ${skipped} skipped · ${total} shots checked, ${failed} with problems`);
  if (failed) process.exit(1);
}

const a = args(process.argv.slice(2));
if (a.selfTest) await selfTest();
else await check(a);
