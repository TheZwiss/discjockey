<script lang="ts">
  // A folder chosen with the Mac's own dialog, never typed (design language §6, decision log 2026-10-23): the path in
  // a recessed well (mono, `~` for the home folder; when narrow the middle ends in "…" so the folder's own name stays,
  // the full path in `title`), `Choose…` beside it, and one line under it from `checkLine`: a StatusMark (✓ usable,
  // ! other files, ▪ refused) and the Hint. A refusal or a warning may take up to three lines: a refusal says what to choose instead.
  // `disabledWhy` turns the button off and is the one line instead (it wraps, as a check line does); `disabled` turns
  // it off with no line (the page already says why). `label`: the button's words (Choose…, Choose where…, Change…).
  // When the field itself is narrow (under 300 px) the button sits under the path, so the path takes the full width. Without `onchoose` it only shows where the folder is
  // (the missing screen). It never calls the bridge: the page goes through musicFolderFlow.
  import type { FolderCheck } from '../bridge/types';
  import { checkLine, shortPath } from '../musicFolder';
  import Button from './Button.svelte';
  import Hint from './Hint.svelte';
  import StatusMark from './StatusMark.svelte';

  let { path, check = null, onchoose, label = 'Choose…', filled = false, busy = false, disabledWhy = null,
    disabled = false, test = 'folder' }: {
    path: string | null; check?: FolderCheck | null; onchoose?: () => void; label?: string; filled?: boolean;
    busy?: boolean; disabledWhy?: string | null; disabled?: boolean; test?: string;
  } = $props();

  const shown = $derived(path ? shortPath(path) : '');
  // head shrinks first ("~/Music/Long…"), the last part ("/DJ Sets") keeps its place
  const cut = $derived(shown.lastIndexOf('/') > 0 ? shown.lastIndexOf('/') : 0);
  const line = $derived(checkLine(check));
</script>

<div class="field" data-test={test}>
  <div class="row">
    <div class="well" class:none={!path} title={path ?? undefined} data-test="{test}-path">
      <svg class="icon" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M1.5 4.5v-1a1 1 0 0 1 1-1h3.6l1.5 1.5h5.9a1 1 0 0 1 1 1v7.5a1 1 0 0 1-1 1h-11a1 1 0 0 1-1-1z" />
      </svg>
      {#if path}
        <span class="path"><span class="head">{shown.slice(0, cut)}</span><span class="tail">{shown.slice(cut)}</span></span>
      {:else}
        <span class="empty">No folder chosen</span>
      {/if}
    </div>
    {#if onchoose}
      <Button variant={filled ? 'filled' : 'secondary'} {busy} disabled={disabled || !!disabledWhy} title={disabledWhy ?? undefined}
        onclick={onchoose} data-test="{test}-choose">{label}</Button>
    {/if}
  </div>
  {#if disabledWhy}
    <Hint text={disabledWhy} wrap data-test="{test}-why" />
  {:else if line.text}
    <div class="line" data-test="{test}-check" data-tone={line.tone}>
      {#if line.tone}<StatusMark tone={line.tone} />{/if}
      <Hint text={line.text} tone={line.tone === 'problem' ? 'problem' : 'muted'} wrap />
    </div>
  {/if}
</div>

<style>
  .field { container-type: inline-size; display: flex; flex-direction: column; gap: var(--s-2); min-width: 0; }
  .row { display: flex; align-items: center; gap: var(--s-2); min-width: 0; }
  @container (max-width: 300px) { .row { flex-direction: column; align-items: flex-start; } .well { align-self: stretch; flex: none; } }
  /* a recessed well, not an input: nothing here is typed (the box of TextField would invite it) */
  .well { flex: 1; min-width: 0; display: flex; align-items: center; gap: var(--s-2); min-height: var(--h-btn);
    padding: 0 var(--s-3); border-radius: var(--r-ctl); background: var(--bg-inset); }
  .icon { flex: none; width: 16px; height: 16px; fill: none; stroke: var(--text-label); stroke-width: 1.2;
    stroke-linejoin: round; }
  .path { flex: 1; display: flex; min-width: 0; font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: var(--fs-small);
    color: var(--text); white-space: nowrap; user-select: text; -webkit-user-select: text; }
  /* the parents give way first; the folder's own name ("/DJ Sets") keeps its place and is cut only when it alone is
     wider than the well, leaving "~…" in front of it */
  .head { flex: 0 1 auto; min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .tail { flex: none; max-width: calc(100% - 2ch); overflow: hidden; text-overflow: ellipsis; }
  .empty { font-size: var(--fs-body); color: var(--text-label); }
  .line { display: flex; align-items: flex-start; gap: var(--s-2); min-width: 0; }
</style>
