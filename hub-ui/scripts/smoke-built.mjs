#!/usr/bin/env node
// Smoke test of the BUILT app (../discjockey/hub/static) in Playwright WebKit with a stub bridge (plan 64.11).
// Every contract method answers { ok:false, kind:'offline' }; setup_status answers "complete". Checks that the
// inline early script ran (window.dj), the shell renders, every route opens, and nothing logs a console error.
//
//   node scripts/smoke-built.mjs [--port 5199]
import { webkit } from 'playwright';
import { createServer } from 'node:http';
import { existsSync, readFileSync, statSync } from 'node:fs';
import { dirname, extname, join, normalize, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const root = resolve(here, '..');
const staticDir = resolve(root, '../discjockey/hub/static');
const portArg = process.argv.indexOf('--port');
const port = portArg > 0 ? Number(process.argv[portArg + 1]) : 5199;

if (!existsSync(join(staticDir, 'index.html'))) {
  console.error(`No built app at ${staticDir}. Run npm run build first.`);
  process.exit(1);
}

// The method names come from contract.ts, so the stub has exactly the methods pywebview would expose.
const contract = readFileSync(join(root, 'src/lib/bridge/contract.ts'), 'utf8');
const listSrc = contract.slice(contract.indexOf('['), contract.indexOf('] as const'));
const methods = [...listSrc.matchAll(/'([a-z_]+)'/g)].map((m) => m[1]);
if (methods.length < 40) { console.error(`Could not read CONTRACT_METHODS (${methods.length} names)`); process.exit(1); }

const TYPES = { '.html': 'text/html', '.js': 'text/javascript', '.css': 'text/css', '.svg': 'image/svg+xml',
  '.png': 'image/png', '.woff2': 'font/woff2', '.json': 'application/json', '.ico': 'image/x-icon' };
const server = createServer((req, res) => {
  const path = decodeURIComponent(new URL(req.url, 'http://x').pathname);
  const file = normalize(join(staticDir, path === '/' ? 'index.html' : path));
  if (!file.startsWith(staticDir) || !existsSync(file) || !statSync(file).isFile()) {
    res.writeHead(404); res.end('not found'); return;
  }
  res.writeHead(200, { 'content-type': TYPES[extname(file)] ?? 'application/octet-stream' });
  res.end(readFileSync(file));
});
await new Promise((ok) => server.listen(port, '127.0.0.1', ok));

const ROUTES = ['#/', '#/runs', '#/sync', '#/todo', '#/library', '#/playlists', '#/qobuz', '#/settings', '#/settings/about',
  '#/setup', '#/nope'];
// What a route must show beyond opening: the About card reads the version from setup_status, so a stub (or a contract
// change) that loses the field leaves the card blank.
const CHECKS = {
  '#/settings/about': async (page, errors) => {
    try {
      await page.waitForFunction(() => document.querySelector('[data-test=about-version]')?.textContent?.includes('1.0.0'),
        null, { timeout: 5000 });
    } catch { errors.push('About card does not show the version from setup_status'); }
  },
};
const failures = [];
const browser = await webkit.launch();
try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } });
  await ctx.addInitScript((names) => {
    const offline = { ok: false, kind: 'offline', message: 'Smoke test: no backend.' };
    const api = {};
    for (const n of names) api[n] = async () => offline;
    api.setup_status = async () => ({ ok: true,
      music: { state: 'ok', path: '/Users/you/Music/Discjockey', suggested: '/Users/you/Music/Discjockey' },
      tools: { ffmpeg: true, ffprobe: true, deno: true }, spotify_app: true, spotify_login: true, qobuz: true,
      playlists: true, complete: true, next_step: null, version: '1.0.0' });
    window.pywebview = { api };
    window.addEventListener('DOMContentLoaded', () => window.dispatchEvent(new Event('pywebviewready')));
  }, methods);

  for (const route of ROUTES) {
    const page = await ctx.newPage();
    const errors = [];
    page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
    page.on('pageerror', (e) => errors.push(String(e)));
    try {
      await page.goto(`http://127.0.0.1:${port}/${route}`);
      const dj = await page.evaluate(() => typeof window.dj?.onEvent === 'function');
      if (!dj) errors.push('window.dj.onEvent missing (inline script did not run)');
      await page.waitForSelector('main[data-page]', { timeout: 10000 });
      if (route !== '#/setup' && !(await page.$('[data-test=nav-library]'))) errors.push('sidebar missing');
      await CHECKS[route]?.(page, errors);
      await page.waitForTimeout(400);   // let the page's first (offline) calls settle
    } catch (e) {
      errors.push(`load failed: ${e.message.split('\n')[0]}`);
    }
    if (errors.length) failures.push({ route, errors });
    console.log(`${errors.length ? 'FAIL' : 'ok  '} ${route}${errors.length ? `  ${errors[0].slice(0, 160)}` : ''}`);
    await page.close();
  }
} finally {
  await browser.close();
  server.close();
}
if (failures.length) { console.log(`${failures.length} of ${ROUTES.length} routes failed`); process.exit(1); }
console.log(`smoke ok: ${ROUTES.length} routes, ${methods.length} stub methods`);
