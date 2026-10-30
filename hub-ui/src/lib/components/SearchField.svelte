<script lang="ts">
  // A search or filter field. `shortcut` shows its key cap while the field is empty: `cmd+f` also binds ⌘F at the
  // window (the page's track search); `cmd+k` is the cap only (the browser column's filter), the key itself belongs
  // to the shell's window-level handler (plan library stage 5 D18). Esc or × clears.
  // `fill`: as wide as its container (the browser column's filter), not its own 180 px. `input` (bindable): the
  // field itself, for a caller that focuses it on a request (⌘K). `onkeydown` comes first: a caller that handles a
  // key (↑ ↓ Enter in the browser's filter, or an Esc that also leaves) prevents its default, and the field then
  // leaves that key alone.
  let { value = $bindable(''), placeholder = 'Search…', shortcut, test, fill = false, input = $bindable(), onkeydown }:
    { value?: string; placeholder?: string; shortcut?: 'cmd+f' | 'cmd+k'; test?: string; fill?: boolean;
      input?: HTMLInputElement; onkeydown?: (e: KeyboardEvent) => void } = $props();
  $effect(() => {
    if (shortcut !== 'cmd+f') return;
    const fn = (e: KeyboardEvent) => {
      if (e.metaKey && e.key.toLowerCase() === 'f') { e.preventDefault(); input?.focus(); input?.select(); }
    };
    window.addEventListener('keydown', fn);
    return () => window.removeEventListener('keydown', fn);
  });
  function key(e: KeyboardEvent) {
    onkeydown?.(e);
    if (e.defaultPrevented) return;
    if (e.key === 'Escape' && value) { e.preventDefault(); e.stopPropagation(); value = ''; }
  }
</script>

<label class="sf" class:filled={!!value} class:fill>
  <span class="glyph" aria-hidden="true">⌕</span>
  <input bind:this={input} bind:value type="search" {placeholder} aria-label={placeholder} spellcheck="false"
    aria-keyshortcuts={shortcut === "cmd+k" ? "Meta+K" : shortcut ? "Meta+F" : undefined}
    data-test={test} onkeydown={key} />
  {#if value}<button type="button" class="clear" aria-label="Clear the search" title="Clear (Esc)" onclick={() => { value = ''; input?.focus(); }}>×</button>
  {:else if shortcut}<span class="kbd" aria-hidden="true">{shortcut === 'cmd+k' ? '⌘K' : '⌘F'}</span>{/if}
</label>

<style>
  .sf { display: inline-flex; align-items: center; gap: 6px; border: var(--bw) solid var(--ctl-line); background: var(--ctl-bg);
    border-radius: var(--r-ctl); padding: 0 var(--s-2); height: var(--h-ctl); min-width: 180px; color: var(--text-label);
    transition: border-color var(--t-hover) var(--ease); }
  .sf:focus-within { border-color: var(--accent-line); }
  .fill { display: flex; width: 100%; min-width: 0; }
  .filled { color: var(--text); }
  input { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--text); font-size: var(--fs-small);
    outline: none; -webkit-appearance: none; appearance: none; user-select: text; -webkit-user-select: text; }
  input::-webkit-search-cancel-button { display: none; }
  input::placeholder { color: var(--text-label); }
  .glyph { font-size: var(--fs-body); }
  .kbd { font-size: var(--fs-label); color: var(--text-label); border: var(--bw) solid var(--line-control);
    border-radius: var(--r-badge); padding: 0 4px; }
  .clear { border: 0; background: transparent; color: var(--text-muted); font-size: var(--fs-title); line-height: 1;
    padding: 0 2px; }
  .clear:hover { color: var(--text); }
</style>
