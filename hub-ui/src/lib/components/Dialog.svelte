<script lang="ts">
  // Esc and the backdrop close it (unless busy); focus goes to the first field; the body scrolls inside.
  import type { Snippet } from 'svelte';
  let { open = $bindable(false), title, width = 560, onclose, busy = false, children, footer }:
    { open?: boolean; title: string; width?: 560 | 760; onclose?: () => void; busy?: boolean; children?: Snippet;
      footer?: Snippet } = $props();
  let el: HTMLDialogElement | undefined = $state();

  $effect(() => {
    if (!el) return;
    if (open && !el.open) {
      el.showModal();
      const first = el.querySelector<HTMLElement>('input, textarea, select, [data-autofocus]')
        ?? el.querySelector<HTMLElement>('.foot button:not([aria-disabled="true"])');
      first?.focus();
    } else if (!open && el.open) el.close();
  });
  function close() {
    if (busy) return;
    open = false;
    onclose?.();
  }
  function cancel(e: Event) { e.preventDefault(); close(); }
  function backdrop(e: MouseEvent) { if (e.target === el) close(); }
</script>

<dialog bind:this={el} class="dialog" style:width="{width}px" aria-label={title} oncancel={cancel} onclick={backdrop}>
  {#if open}
    <div class="inner">
      <header><h2>{title}</h2><button type="button" class="x" aria-label="Close" disabled={busy} onclick={close}>×</button></header>
      <div class="body">{@render children?.()}</div>
      {#if footer}<footer class="foot">{@render footer()}</footer>{/if}
    </div>
  {/if}
</dialog>

<style>
  .dialog { padding: 0; border: var(--bw) solid var(--line-control); border-radius: var(--r-surface); background: var(--bg);
    color: var(--text); max-width: calc(100vw - 64px); max-height: calc(100vh - 96px); box-shadow: var(--shadow); }
  .dialog::backdrop { background: var(--backdrop); }
  .inner { display: flex; flex-direction: column; max-height: calc(100vh - 98px); }
  header { display: flex; align-items: center; gap: var(--s-3); padding: var(--s-4) var(--s-5) var(--s-2); }
  h2 { flex: 1; font-size: var(--fs-title); }
  .x { border: 0; background: none; color: var(--text-label); font-size: var(--fs-h1); line-height: 1; }
  .x:hover:not(:disabled) { color: var(--text); }
  .body { padding: var(--s-2) var(--s-5) var(--s-4); overflow-y: auto; min-height: 0; display: flex; flex-direction: column;
    gap: var(--s-3); }
  .foot { display: flex; justify-content: flex-end; gap: var(--s-2); padding: var(--s-3) var(--s-5) var(--s-4);
    border-top: var(--bw) solid var(--line); }
</style>
