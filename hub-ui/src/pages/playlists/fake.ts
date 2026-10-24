// Playlists fake scenarios (fake mode only). Open them with ?scenario=playlists:<name>.
import type { PageFake } from '$lib/bridge/fake/bridge';
import type { FakeState } from '$lib/bridge/fake/data';

// playlists.txt gets changed in a text editor after the page loaded it (the next save is refused with `changed`)
const changedElsewhere = new WeakSet<FakeState>();
// every preview names a problem (Save is refused), e.g. a folder name the backend rejects
const previewProblem = new WeakSet<FakeState>();
// previews take 2.5 s (to see the dimmed "loading" panel)
const slowPreview = new WeakSet<FakeState>();
const PROBLEM = 'Line 2: "Powertrance" and "Hard_Bounce" can\'t share a folder. Give each playlist its own folder name.';

const fake: PageFake = {
  scenarios: {
    // set up, but no playlists yet (first_run would open the wizard)
    empty: (s) => { s.playlists = []; },
    'changed-elsewhere': (s) => { changedElsewhere.add(s); },
    'preview-problem': (s) => { previewProblem.add(s); },
    'slow-preview': (s) => { slowPreview.add(s); },
    // many tracks in several playlists: moving 03_06_2026 to the top moves tracks out of three folders (the panel's
    // move view at scale). Only tracks whose current folder stays the highest of their playlists get a second one.
    'many-overlaps': (s) => {
      s.tracks.forEach((t, i) => {
        if (!t.in_playlists || !['Hard_Bounce', 'Powertrance', 'Bouncy'].includes(t.folder)) return;
        if (i % 3 !== 2) t.playlists = [...new Set([...t.playlists, '03_06_2026'])];
        if (i % 4 === 0 && t.folder !== 'Bouncy') t.playlists = [...new Set([...t.playlists, 'Bouncy'])];
      });
    },
  },
  overrides: {
    // with no playlists there is nothing to overlap (the base fake derives overlaps from its tracks)
    playlists: (ctx, base) => async () => {
      const r = await base();
      return r.ok && !ctx.s.playlists.length ? { ...r, overlaps: [] } : r;
    },
    preview_playlist_change: (ctx, base) => async (lines) => {
      const r = await base(lines);
      const out = r.ok && previewProblem.has(ctx.s) ? { ...r, problem: PROBLEM } : r;
      return slowPreview.has(ctx.s) ? ctx.later(2200, () => out) : out;
    },
    save_playlists: (ctx, base) => async (lines, loaded_version, files) => {
      if (changedElsewhere.has(ctx.s)) { changedElsewhere.delete(ctx.s); ctx.s.version++; }
      return base(lines, loaded_version, files);
    },
  },
};
export const { scenarios, overrides } = fake;
export default fake;
