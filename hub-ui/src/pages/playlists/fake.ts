// Playlists fake scenarios (fake mode only). Open them with ?scenario=playlists:<name>.
import type { PageFake } from '$lib/bridge/fake/bridge';
import { pathOf, type FakeMove, type FakeState, type FakeTrack } from '$lib/bridge/fake/data';
import { hasFile, outOfPlace } from '$lib/bridge/fake/tidy';
import type { UndoPreview } from '$lib/bridge/types';

// playlists.txt gets changed in a text editor after the page loaded it (the next save is refused with `changed`)
const changedElsewhere = new WeakSet<FakeState>();
// every preview names a problem (Save is refused), e.g. a folder name the backend rejects
const previewProblem = new WeakSet<FakeState>();
// previews take 2.5 s (to see the dimmed "loading" panel)
const slowPreview = new WeakSet<FakeState>();
// the undo of the tidy-up (batch 1) lists one row for each reason an undo can't move something back
const undoSkips = new WeakSet<FakeState>();
const PROBLEM = 'Line 2: "Powertrance" and "Hard_Bounce" can\'t share a folder. Give each playlist its own folder name.';


// ---------- tidy-up helpers ----------
/** Files a scenario may put out of place: in a playlist folder, nothing else going on with them. */
function movable(s: FakeState): FakeTrack[] {
  return s.tracks.filter((t) => hasFile(t) && t.in_playlists && !t.other && !t.rekordbox_check && !t.hidden
    && !t.upgrade && s.playlists.some((p) => p.folder === t.folder));
}
/** Every file back where the playlist order puts it, nobody's own placement, nothing skipped. */
function tidyAll(s: FakeState): void {
  for (const t of s.tracks) delete t.at;
  s.tidy.placed = {};
  s.tidy.skips = {};
}
const ago = (s: FakeState, ms: number) => new Date(s.now.getTime() - ms).toISOString().slice(0, 19);
const folderOf = (path: string) => path.replace(/^Library\//, '').split('/').slice(0, -1).join('/').replace(/\/not_lossless$/, '');

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
    // Tidy up files (plan library stage 2, 6.5). The base seed already holds the mixed case: files the app placed
    // elsewhere (ticked), two the user put in Elsewhere, one whose name is taken, one offline.
    'tidy-mixed': () => {},
    // about 40 files out of place across the four other playlist folders
    'tidy-many': (s) => {
      tidyAll(s);
      const folders = s.playlists.map((p) => p.folder);
      movable(s).slice(0, 40).forEach((t, i) => {
        const others = folders.filter((f) => f !== t.folder);
        t.at = others[i % others.length];
      });
    },
    // every file is where the playlist order puts it
    'tidy-empty': (s) => { s.tidy.noRows = true; },
    // only the user's own placements are left: the button still opens the list, which says so
    'tidy-only-yours': (s) => {
      for (const t of s.tracks) if (outOfPlace(t) && !s.tidy.placed[t.track_id]) delete t.at;
      s.tidy.skips = {};
    },
    // the second move fails (the drive is full) and Stop comes after the third: the result lists both
    'move-fails': (s) => { s.tidy.failMove = 1; s.tidy.stopAfter = 3; },
    // renaming Powertrance offers the folder rename on disk (the base seed as it is: rename it in the list)
    'rename-offered': () => {},
    // ... and here Library already has a Powertrance_2026 folder, so the rename isn't offered
    'rename-taken': (s) => { s.extraFolders.push({ folder: 'Powertrance_2026', in_playlists_txt: false }); },
    // the move log: an undo (undoable), the save it undid part of, the tidy-up, and an old folder rename with
    // nothing left to undo
    batches: (s) => {
      const save = s.tidy.batches.find((b) => b.startedBy === 'save');
      const back = save?.moves.find((m) => m.state === 'done' && m.track_id);
      const t = back && s.tracks.find((x) => x.track_id === back.track_id);
      if (!save || !back || !t) return;
      // the undo moved one of the save's files back where it was
      t.at = folderOf(back.src);
      const undoMove: FakeMove = { ...back, src: back.dst, dst: pathOf(t) ?? back.src, placedBefore: 'app' };
      s.tidy.batches.push({ id: s.tidy.nextBatch, at: ago(s, 20 * 60e3), startedBy: 'undo', about: null,
        undoes: save.id, moves: [undoMove] });
      s.tidy.batches.unshift({ id: s.tidy.nextBatch + 1, at: ago(s, 4 * 86400e3), startedBy: 'rename',
        about: { from: 'Old_Sets', to: 'Sets_2025' }, undoes: null,
        moves: [{ kind: 'folder', track_id: null, label: 'Old_Sets', src: 'Library/Old_Sets', dst: 'Library/Sets_2025',
          state: 'done', reason: null, text: null, placedBefore: 'app' }] });
      s.tidy.nextBatch += 2;
    },
    'undo-skips': (s) => { undoSkips.add(s); },
  },
  overrides: {
    // undo-skips: the tidy-up's undo with every reason a move can't go back (I6 words)
    undo_preview: (ctx, base) => async (batch_id) => {
      const r = await base(batch_id);
      if (!r.ok || !undoSkips.has(ctx.s) || batch_id !== 1) return r;
      const name = (i: number) => { const t = ctx.s.tracks[i]; return `${t.artist} - ${t.title}`; };
      const skips: UndoPreview['rows'] = [
        { label: name(3), from: 'Hard_Bounce', to: 'Bouncy', skip: { reason: 'moved_on', text: 'Moved or changed since' } },
        { label: name(5), from: 'Bouncy', to: 'Powertrance',
          skip: { reason: 'place_taken', text: 'Another file is in its old place now' } },
        { label: name(7), from: 'Powertrance', to: '03_06_2026/not_lossless', skip: { reason: 'offline', text: 'Offline, skipped' } },
        { label: 'Sets_2025', from: 'Sets_2025', to: 'Old_Sets',
          skip: { reason: 'moved_on', text: "The folder Sets_2025 isn't there any more" } },
        { label: 'Old_Sets', from: 'Sets_2025', to: 'Old_Sets',
          skip: { reason: 'place_taken', text: 'A folder called Old_Sets is in your Library again.' } },
        { label: 'Old_Sets', from: 'Sets_2025', to: 'Old_Sets',
          skip: { reason: 'place_taken', text: 'Another playlist is called Old_Sets now.' } },
        { label: 'Sets_2025', from: 'Sets_2025', to: 'Old_Sets',
          skip: { reason: 'playlist_renamed', text: "The playlist isn't called Sets_2025 any more" } },
      ];
      return { ...r, rows: [...r.rows.filter((x) => !x.skip), ...skips] };
    },
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
