<script lang="ts">
  // One playlist on the list's grid (design system mockup design-system/playlists.html): ⋮⋮ (pointer drag, never
  // HTML5 drag-and-drop: the window's file-drop handler covers the document) · priority · cover · the folder over
  // "Spotify name · owner" (led by what the unsaved change does to it: "gets 27 more") · quality (only while the list
  // is at least 680 px wide) · tracks · switch · ⋯ (Rename, Remove; right-click opens the same menu). ⌥↑ / ⌥↓ move a
  // focused row; renaming edits the name in place (Enter keeps it, Esc cancels).
  import { Badge, Button, ContextMenu, Cover, ListRow, QualityBar, Switch, TextField } from '$lib/components';
  import { plural } from '$lib/format';
  import { folderProblem } from '$lib/components/addRowModel';
  import { changeText, infoLine, losslessText, type DraftRow } from './changeModel';

  let { row, prio, draft, delta = null, offset = 0, dragging = false, onhandledown, onmove, onrename, ontoggle,
    onremove }: {
    row: DraftRow; prio: string; draft: DraftRow[];
    /** what the unsaved change does to this folder's file count (null: nothing) */
    delta?: number | null;
    offset?: number; dragging?: boolean;
    onhandledown: (e: PointerEvent) => void; onmove: (delta: number) => void; onrename: (folder: string) => void;
    ontoggle: () => void; onremove: () => void;
  } = $props();

  let editing = $state(false);
  let edit = $state('');
  let menu = $state<{ x: number; y: number; keyboard: boolean } | null>(null);
  const problem = $derived(editing ? folderProblem(edit, draft, row.key) : null);
  const line = $derived(infoLine(row));
  const lossless = $derived(losslessText(row.quality));
  const unreadable = $derived(row.enabled && line.tone === 'bad');

  function startEdit() { edit = row.folder; editing = true; }
  function commit() {
    if (problem) return;
    if (edit.trim() !== row.folder) onrename(edit);
    editing = false;
  }
  function key(e: KeyboardEvent) {
    const inInput = (e.target as HTMLElement).tagName === 'INPUT';
    if (e.key === 'Escape' && editing) { e.preventDefault(); editing = false; return; }
    if (inInput || !e.altKey) return;
    if (e.key === 'ArrowUp') { e.preventDefault(); onmove(-1); }
    if (e.key === 'ArrowDown') { e.preventDefault(); onmove(1); }
  }
  let opener: HTMLElement | null = null;
  function openMenu(e: MouseEvent) {
    e.preventDefault();
    e.stopPropagation();   // the menu closes on any window click, this one included
    if (e.type === 'contextmenu') { opener = null; menu = { x: e.clientX, y: e.clientY, keyboard: false }; return; }
    if (menu) { menu = null; return; }
    opener = e.currentTarget as HTMLElement;
    const r = opener.getBoundingClientRect();
    menu = { x: r.right - 180, y: r.bottom + 4, keyboard: e.detail === 0 };   // detail 0: Enter or Space
  }
  // Esc or a click elsewhere from inside the menu gives focus back to ⋯, so keyboard users aren't dropped
  function closeMenu() {
    const inside = !!(document.activeElement as HTMLElement | null)?.closest('[role=menu]');
    menu = null;
    if (inside) opener?.focus();
  }
  const pick = (fn: () => void) => () => { menu = null; fn(); };
  const items = $derived([
    { label: 'Rename the folder…', onpick: pick(startEdit), test: `rename-${row.folder}` },
    { label: 'Remove from the list…', onpick: pick(onremove), test: `remove-${row.folder}` },
  ]);
</script>

<ListRow off={!row.enabled} class="pl{dragging ? ' drag' : ''}" role="option" aria-selected="false" tabindex={0}
  data-key={row.key} test="row-{row.folder}" style={offset ? `transform: translateY(${offset}px)` : undefined}
  onkeydown={key} oncontextmenu={openMenu} height={52}>
  {#snippet lead()}
    <span class="handle" role="presentation" onpointerdown={onhandledown} data-test="handle-{row.folder}">⋮⋮</span>
    <span class="prio">{prio}</span>
    <Cover url={row.info?.image_url ?? null} seed={row.link} size={28} />
  {/snippet}
  {#snippet name()}
    {#if editing}
      <TextField bind:value={edit} autofocus onenter={commit} invalid={!!problem} name="folder"
        hint={problem ?? 'Enter keeps the new name, Esc cancels.'} />
    {:else}
      <span class="fname">{row.folder}</span>{#if row.isNew}<span class="new"><Badge tone="accent" text="NEW" /></span>{/if}
    {/if}
  {/snippet}
  {#snippet sub()}
    {#if !editing}
      {#if delta}<span class="delta" class:gain={delta > 0} data-test="delta-{row.folder}">{changeText(delta)}</span>{' · '}{/if}<span
        class:bad={line.tone === 'bad'}>{line.text}</span>
    {/if}
  {/snippet}
  {#snippet optional()}
    {#if unreadable}
      <Badge tone="weak" text="CAN'T READ" />
    {:else if row.enabled}
      <span class="q"><QualityBar by_quality={row.quality} height={4} /><span class="ql">{lossless ?? 'nothing yet'}</span></span>
    {/if}
  {/snippet}
  {#snippet trailing()}
    <span class="count" title={row.tracks == null ? undefined : plural(row.tracks, 'track')}>{unreadable || row.tracks == null ? '—' : row.tracks}</span>
    <button type="button" class="tog" role="switch" aria-checked={row.enabled} aria-label="Sync {row.folder}"
      onclick={ontoggle} data-test="toggle-{row.folder}"><Switch on={row.enabled} label={row.folder} /></button>
    <Button variant="icon" size="sm" aria-label="More for {row.folder}" aria-haspopup="menu" onclick={openMenu}
      data-test="more-{row.folder}">⋯</Button>
  {/snippet}
</ListRow>
{#if menu}
  <ContextMenu x={menu.x} y={menu.y} {items} focusFirst={menu.keyboard} onclose={closeMenu}
    test="menu-{row.folder}" />
{/if}

<style>
  .handle { color: var(--text-label); cursor: grab; touch-action: none; user-select: none; letter-spacing: -2px;
    width: 14px; font-size: var(--fs-small); }
  :global(.pl.drag) .handle { cursor: grabbing; color: var(--accent-text); }
  .prio { width: 18px; text-align: center; color: var(--text-muted); font-weight: var(--fw-semi);
    font-variant-numeric: tabular-nums; }
  .fname { color: var(--text-strong); font-weight: var(--fw-semi); }
  .new { margin-left: var(--s-2); }
  .delta { color: var(--text-muted); }
  .delta.gain { color: var(--accent-text); }
  .bad { color: var(--q-weak); }
  .q { display: flex; flex-direction: column; gap: var(--s-1); width: 100%; }
  .ql { color: var(--text-label); font-size: var(--fs-label); font-variant-numeric: tabular-nums; }
  .count { min-width: 32px; text-align: right; }
  .tog { display: inline-flex; align-items: center; min-width: 30px; padding: 0; border: 0; background: none;
    cursor: pointer; }
  .tog:focus-visible { outline: var(--bw-accent) solid var(--accent-line); outline-offset: 2px; border-radius: var(--r-pill); }
  /* the lifted row while it is dragged: above the others, with the accent edge */
  :global(.pl.drag) { position: relative; z-index: 2; background: var(--bg-selected); box-shadow: var(--shadow),
    inset 0 0 0 var(--bw) var(--accent-line); }
  :global(.pl:focus-visible) { outline: var(--bw-accent) solid var(--accent-line); outline-offset: -2px; }
</style>
