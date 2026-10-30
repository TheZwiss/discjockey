// Shared by shots.mjs (pictures) and rules.mjs (rule checker): which shots exist, how a shot is opened at a window
// size, and the steps that bring the page into the state to show.
//
// Shots come from src/pages/<page>/shots.json (base: src/lib/dev/shots.json):
//   [{ "name": "todo-weak-selected", "route": "#/todo?track=t2", "scenario": "normal", "query": { "speed": "5" },
//      "steps": [{ "click": "[data-test=wrong-song]" }, { "wait": "[data-test=candidates]" }, { "sleep": 300 },
//                { "press": "Escape" }, { "fill": ["input[type=search]", "gimme"] }, { "resize": [1100, 700] }],
//      "mockup": "todo.html", "mockupClip": null }]
// Steps also take { "rightclick": selector } (opens a right-click menu), { "hover": selector } and { "eval": "js" }.
// Optional shot keys: "prefs": { "shell.form.other": "rail" } (UI prefs seeded into localStorage, without the app's
// "discjockey." prefix, right after the per-shot clear: a shot can start with the folded sidebar, a wider browser column
// or an open inspector; a shot without it starts from the defaults: Library rail, other pages full),
// "mockupState": "dashboard-rail" (with "mockup": the state's hash, read by shots.mjs --compare: it loads
// <mockup>#<state>, waits for [data-win] and clips it) and "mockupScale": 1 (the mockup's size in the comparison; 1
// for library-layout.html, which is drawn at real size; 1.15 is the default for the older, smaller mockups),
// "each": "section" (also one PNG per matching element), "width"/"height" (a window of its own: with a
// width the shot is taken once, at that size; a height alone keeps the widths up to 1280, see sizesFor), "settle": ms (default 250), "fullPage": true,
// "reducedMotion": "reduce".
import { existsSync, readFileSync, readdirSync } from 'node:fs';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { availableParallelism } from 'node:os';

const here = dirname(fileURLToPath(import.meta.url));
export const root = resolve(here, '..');

// Window sizes the design system is checked at (spec §9): the minimum, the usual, a large display.
export const SIZES = { min: [1100, 700], default: [1280, 800], large: [2560, 1440] };

// "min,default" or "1280x800,1100x700" -> [{ w, h }]; no value means all three.
export function parseSizes(value) {
  const parts = value ? value.split(',').map((p) => p.trim()).filter(Boolean) : Object.keys(SIZES);
  return parts.map((p) => {
    if (SIZES[p]) return { w: SIZES[p][0], h: SIZES[p][1] };
    const m = /^(\d+)x(\d+)$/.exec(p);
    if (!m) throw new Error(`Unknown size "${p}": use ${Object.keys(SIZES).join(', ')} or <w>x<h>`);
    return { w: Number(m[1]), h: Number(m[2]) };
  });
}

// A shot with its own width is taken once, at that size. A shot with only a height (a tall page such as the gallery)
// keeps each chosen size's width up to 1280 at that height: 1100 is where samples reflow, and above 1280 a capped
// page shows nothing new on a far larger canvas. The others run at every chosen size.
export function sizesFor(shot, sizes) {
  if (shot.width) return [{ w: shot.width, h: shot.height ?? 800 }];
  if (!shot.height) return sizes;
  const narrow = sizes.filter((s) => s.w <= 1280).map((s) => ({ w: s.w, h: shot.height }));
  return narrow.length ? narrow : [{ w: 1280, h: shot.height }];
}

export function pageNames() {
  return ['base', ...readdirSync(join(root, 'src/pages'), { withFileTypes: true }).filter((d) => d.isDirectory()).map((d) => d.name)];
}
function shotFile(page) {
  return page === 'base' ? join(root, 'src/lib/dev/shots.json') : join(root, 'src/pages', page, 'shots.json');
}
// pages: names to read; only: one or several shot names (array) or null.
export function loadShots(pages, only = null) {
  const shots = [];
  for (const p of pages) {
    const f = shotFile(p);
    if (!existsSync(f)) continue;
    for (const s of JSON.parse(readFileSync(f, 'utf8'))) shots.push({ ...s, page: p });
  }
  return only ? shots.filter((s) => only.includes(s.name)) : shots;
}

export async function runSteps(page, steps = []) {
  for (const st of steps) {
    if (st.click) await page.click(st.click);
    else if (st.press) await page.keyboard.press(st.press);
    else if (st.fill) await page.fill(st.fill[0], st.fill[1]);
    else if (st.wait) await page.waitForSelector(st.wait, { timeout: 10000 });
    else if (st.sleep) await page.waitForTimeout(st.sleep);
    else if (st.hover) await page.hover(st.hover);
    else if (st.rightclick) await page.click(st.rightclick, { button: 'right' });
    else if (st.resize) await page.setViewportSize({ width: st.resize[0], height: st.resize[1] });
    else if (st.eval) await page.evaluate(st.eval);
  }
}

// After the steps: pointer out of the way (no hover left over), every running finite animation and transition
// finished (looping and paused ones skipped), then the shot's own settle time. Without it the colour rule sees
// hover and state transitions half-way. The wait for animations gives up after 3 s so a stuck one can't hang a run.
export async function settle(page, ms = 250) {
  await page.mouse.move(0, 0);
  await Promise.race([
    page.evaluate(() => Promise.all(document.getAnimations()
      .filter((a) => a.playState === 'running' && a.effect?.getComputedTiming().iterations !== Infinity)
      .map((a) => a.finished.catch(() => undefined)))),
    new Promise((resolve) => setTimeout(resolve, 3000)),
  ]);
  await page.waitForTimeout(ms);
}

// Opens the shot in a new page at `size`, runs its steps and settles. Console errors and uncaught page errors are
// collected in `errors`; `ok` is false when the page, a step or the settle itself failed (then `errors` says why).
export async function openShot(ctx, port, shot, size) {
  const page = await ctx.newPage();
  // every shot starts from the app's defaults: the context is shared across shots and sizes, and a shot that changes a
  // pref (Sync's playlists or amount) would otherwise carry it into the next one. Cleared once per page (its first
  // load), so a shot that reloads keeps what it set.
  // The shot's `prefs` are seeded right after that clear, in the same first load.
  await page.addInitScript((prefs) => {
    try {
      if (sessionStorage.getItem('shot-fresh')) return;
      localStorage.clear();
      sessionStorage.setItem('shot-fresh', '1');
      for (const [k, v] of Object.entries(prefs)) localStorage.setItem(`discjockey.${k}`, JSON.stringify(v));
    } catch { /* storage off */ }
  }, shot.prefs ?? {});
  const errors = [];
  page.on('console', (m) => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', (e) => errors.push(String(e)));
  const q = new URLSearchParams({ scenario: shot.scenario ?? 'normal', ...(shot.query ?? {}) });
  const url = `http://localhost:${port}/?${q}${shot.route ?? '#/'}`;
  let ok = true;
  try {
    await page.setViewportSize({ width: size.w, height: size.h });
    if (shot.reducedMotion) await page.emulateMedia({ reducedMotion: shot.reducedMotion });
    await page.goto(url);
    await page.waitForSelector('[data-page-ready]', { timeout: 15000 });
    await runSteps(page, shot.steps);
    await settle(page, shot.settle);
  } catch (e) {
    ok = false;
    errors.push(`shot failed: ${e.message.split('\n')[0]}`);
  }
  return { page, errors, ok };
}

// How many shots run at once: half the cores, at most 6 (each is a WebKit page; more starve the dev server).
export const WORKERS = Math.min(6, Math.max(1, Math.floor(availableParallelism() / 2)));

// Runs `fn(ctx, job)` for every job, `workers` at a time. Each worker has its own browser context, so a shot that
// changes local storage (a pref) can't leak into a shot running beside it; inside a worker the jobs run one by one
// and share its context, as they did when everything ran in one.
export async function pool(browser, jobs, workers, fn) {
  let next = 0;
  const worker = async () => {
    const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 }, deviceScaleFactor: 2 });
    try { while (next < jobs.length) await fn(ctx, jobs[next++]); } finally { await ctx.close(); }
  };
  await Promise.all(Array.from({ length: Math.min(workers, jobs.length) }, worker));
}
