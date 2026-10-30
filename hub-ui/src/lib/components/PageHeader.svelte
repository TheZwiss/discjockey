<script lang="ts">
  // The page header (design system §5a): one block for every page, so the title, its status line, the page's actions
  // and the playlists' read status sit in the same place with the same look everywhere (§12: a shared element is placed by its
  // block, never by the page).
  //   [title · sub] ............................ [actions] [Playlists read 2 min ago · ↻ Read playlists]
  // - It spans its frame's content box and adds no padding of its own: the list area's content in ListPanelFrame (never
  //   the panel, which has its own head), the 900 px column in ColumnFrame, the page's padding box on a plain page.
  //   So the title starts where the rows start and the last control ends where the rows end, at every window size.
  // - Title and sub share one baseline (a 22 px title and a 12 px line centred on each other sat 4 px off it). The
  //   title ends in "…" when it is longer than the header (a folder name); the sub never does: when it doesn't fit
  //   beside the title it wraps under it, so no word is lost.
  // - `readStatus`: the fixed slot at the right edge (the playlists' read status), used by
  //   the pages whose content comes from the last read (Dashboard, Sync, To-do, Playlists). `readStatusInBody`: the page
  //   shows the read in progress and its problems as cards in its body (Sync before the start), so the slot keeps
  //   only its control and the state is said once.
  // - `actions`: the page's own controls (search, Full report), left of the read-status slot.
  // - `readStatusState`: the gallery only, shows a given read state instead of the live one.
  // - `sub` as a list of parts (Library, plan library stage 5 N14, house rule 8): the parts in order of importance
  //   ("472 tracks", "8 folders with music", "~/Music/Rekordbox Library"), on the title's line only. When they don't
  //   all fit, whole parts drop, the last (least important) first, down to none; a part is never cut mid-word and the
  //   whole subtitle is the tooltip. CSS only, so it follows the width live with no measuring: the parts are flex
  //   items that wrap onto a second line, which is clipped, behind an empty first item one line tall (a zero-width
  //   strut, which also gives the row its baseline), so even the first part wraps away rather than be cut. The
  //   parts take no width of their own (flex-basis 0), so the title keeps its whole width and ends in "…" only when
  //   even the title alone doesn't fit.
  import type { Snippet } from 'svelte';
  import ReadStatus from './ReadStatus.svelte';
  import type { ReadStatus as ReadState } from '../bridge/types';
  let { title, sub, actions, readStatus = false, readStatusInBody = false, readStatusState }:
    { title: string; sub?: string | string[]; actions?: Snippet; readStatus?: boolean; readStatusInBody?: boolean;
      readStatusState?: ReadState | null } = $props();
  const parts = $derived(Array.isArray(sub) ? sub.filter(Boolean) : null);
  // a line breaks after the "·", never before it: the separator stays with the words it follows (no line starts "· 5 …")
  const subText = $derived(typeof sub === 'string' ? sub.replaceAll(' · ', '\u00a0· ') : '');
</script>

<header class="ph" data-page-header>
  <div class="lead" class:has-parts={!!parts}>
    <h1 {title}>{title}</h1>
    {#if parts}
      {#if parts.length}<span class="parts" title={parts.join(' · ')} data-test="page-sub"><span class="strut"
        aria-hidden="true">{'\u200b'}</span>{#each parts as p, i (i)}<span class="part">{i ? ` · ${p}` : p}</span>{/each}</span>{/if}
    {:else if subText}<span class="sub" title={sub as string} data-test="page-sub">{subText}</span>{/if}
  </div>
  {#if actions || readStatus}
    <div class="trail">
      {#if actions}<div class="actions">{@render actions()}</div>{/if}
      {#if readStatus}<ReadStatus inBody={readStatusInBody} status={readStatusState} />{/if}
    </div>
  {/if}
</header>

<style>
  /* min-height = --h-btn, room for a control or the 22 px title's line box, so the header keeps its height
     whether or not it holds controls, and content below starts at the same y on every page */
  /* baseline: the slot's 12 px line and the controls' labels sit on the title's baseline (centred, they sat 3.8 px
     above it; Apple typography: one line, one baseline) */
  .ph { display: flex; align-items: baseline; gap: var(--s-4); min-height: var(--h-btn); min-width: 0; flex: none; }
  /* the lead wraps: a status line that doesn't fit beside the title goes under it, whole, instead of ending in "…"
     (To-do at 1100: "18 tracks are not lossless yet · 5 quest…"). The first line keeps the title's baseline, so the
     controls on the right still sit on it; only the header grows, by one line, and only where the words need it. */
  .lead { display: flex; flex-wrap: wrap; align-items: baseline; column-gap: var(--s-3); row-gap: 0; min-width: 0;
    flex: 1 1 auto; }
  /* the title keeps its whole width: it never shrinks; a title longer than the lead (a long folder name) is capped
     by max-width and ends in "…" (only a name, never the status words, is cut) */
  h1 { font-size: var(--fs-h1); white-space: nowrap; min-width: 0; max-width: 100%;
    overflow: hidden; text-overflow: ellipsis; flex: 0 0 auto; }
  /* the status line breaks between words, balanced so no word is left alone on the second line; beside the title
     while it fits, under it otherwise */
  .sub { color: var(--text-label); font-size: var(--fs-small); min-width: 0; flex: 0 1 auto; text-wrap: balance; }
  /* parts: one line beside the title, never under it; the title gives way only to the gap when it fills the lead */
  .lead.has-parts { flex-wrap: nowrap; }
  .has-parts h1 { flex: 0 1 auto; }
  .parts { flex: 1 1 0; min-width: 0; display: flex; flex-wrap: wrap; height: 16px; line-height: 16px; overflow: hidden;
    color: var(--text-label); font-size: var(--fs-small); }
  .strut { width: 0; flex: none; }
  .part { white-space: pre; }
  .trail { flex: none; display: flex; align-items: center; gap: var(--s-4); }
  .actions { display: flex; align-items: center; gap: var(--s-2); }
</style>
