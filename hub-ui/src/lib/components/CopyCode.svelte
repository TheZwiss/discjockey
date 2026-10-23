<script lang="ts">
  // A code line with a Copy button. Without clipboard access it selects the text and says "Press ⌘C".
  // The code wraps inside its own column, so Copy stays on the first line's end however long the code is.
  import { onDestroy } from 'svelte';
  import Button from './Button.svelte';
  import { copyText } from './clipboard';
  let { text, copy, test }: { text: string; copy?: string; test?: string } = $props();
  let codeEl = $state<HTMLElement>();
  let said = $state<string | null>(null);
  let timer: ReturnType<typeof setTimeout> | undefined;
  onDestroy(() => clearTimeout(timer));
  async function doCopy() {
    const done = await copyText(copy ?? text);
    if (!done && codeEl) {
      const range = document.createRange();
      range.selectNodeContents(codeEl);
      const sel = window.getSelection();
      sel?.removeAllRanges();
      sel?.addRange(range);
    }
    said = done ? 'Copied' : 'Press ⌘C';
    clearTimeout(timer);
    timer = setTimeout(() => (said = null), 2500);
  }
</script>

<span class="cc" data-test={test}>
  <code bind:this={codeEl}>{text}</code>
  <Button variant="link" size="sm" onclick={doCopy}>{said ?? 'Copy'}</Button>
</span>

<style>
  /* justify-content: start keeps Copy beside the code when a parent stretches the block (a flex column, a grid
     cell): otherwise both auto tracks share the free width and Copy drifts away from its box */
  .cc { display: inline-grid; grid-template-columns: minmax(0, auto) auto; justify-content: start;
    align-items: baseline; gap: var(--s-2); max-width: 100%; min-width: 0; }
  code { background: var(--bg-inset); border: var(--bw) solid var(--line-card); border-radius: var(--r-badge);
    padding: 1px 6px; color: var(--text-strong); font-family: ui-monospace, "SF Mono", Menlo, monospace;
    font-size: var(--fs-small); overflow-wrap: anywhere; user-select: text; -webkit-user-select: text; }
</style>
