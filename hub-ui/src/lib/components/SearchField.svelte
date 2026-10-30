<script lang="ts">
  // A search or filter field. `shortcut` shows its key cap while the field is empty: `cmd+f` also binds ⌘F at the
  // window (the page's track search); `cmd+k` is the cap only (the browser column's filter), the key itself belongs
  // to the shell's window-level handler (plan library stage 5 D18). Esc or × clears.
  let { value = $bindable(''), placeholder = 'Search…', shortcut, test }:
    { value?: string; placeholder?: string; shortcut?: 'cmd+f' | 'cmd+k'; test?: string } = $props();
  let el: HTMLInputElement | undefined = $state();
  $effect(() => {
    if (shortcut !== 'cmd+f') return;
    const fn = (e: KeyboardEvent) => {
      if (e.metaKey && e.key.toLowerCase() === 'f') { e.preventDefault(); el?.focus(); el?.select(); }
    };
    window.addEventListener('keydown', fn);
    return () => window.removeEventListener('keydown', fn);
  });
  function key(e: KeyboardEvent) { if (e.key === 'Escape' && value) { e.preventDefault(); e.stopPropagation(); value = ''; } }
</script>

<label class="sf" class:filled={!!value}>
  <span class="glyph" aria-hidden="true">⌕</span>
  <input bind:this={el} bind:value type="search" {placeholder} aria-label={placeholder} spellcheck="false"
    aria-keyshortcuts={shortcut === "cmd+k" ? "Meta+K" : shortcut ? "Meta+F" : undefined}
    data-test={test} onkeydown={key} />
  {#if value}<button type="button" class="clear" aria-label="Clear the search" title="Clear (Esc)" onclick={() => { value = ''; el?.focus(); }}>×</button>
  {:else if shortcut}<span class="kbd" aria-hidden="true">{shortcut === 'cmd+k' ? '⌘K' : '⌘F'}</span>{/if}
</label>

<style>
  .sf { display: inline-flex; align-items: center; gap: 6px; border: var(--bw) solid var(--ctl-line); background: var(--ctl-bg);
    border-radius: var(--r-ctl); padding: 0 var(--s-2); height: var(--h-ctl); min-width: 180px; color: var(--text-label);
    transition: border-color var(--t-hover) var(--ease); }
  .sf:focus-within { border-color: var(--accent-line); }
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
