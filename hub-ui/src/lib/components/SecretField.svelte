<script lang="ts">
  // An input whose text stays in the element (credentials). The page reads it with takeSecret() when it sends.
  // `oninput` gets the text only to derive a boolean or a check result; nothing may keep it.
  let { el = $bindable(), multiline = false, type = 'password', placeholder = '', label, test, mono = false,
    tone = null, oninput, onenter }: {
    el?: HTMLInputElement | HTMLTextAreaElement; multiline?: boolean; type?: 'password' | 'text'; placeholder?: string;
    label?: string; test?: string; mono?: boolean; tone?: 'ok' | 'bad' | null; oninput?: (text: string) => void;
    onenter?: () => void;
  } = $props();
  function key(e: KeyboardEvent) {
    if (e.key === 'Enter' && onenter) { e.preventDefault(); onenter(); }
  }
  function changed(e: Event) { oninput?.((e.currentTarget as HTMLInputElement | HTMLTextAreaElement).value); }
</script>

<div class="box" class:ok={tone === 'ok'} class:bad={tone === 'bad'} class:multi={multiline}>
  {#if multiline}
    <textarea bind:this={el} {placeholder} aria-label={label ?? placeholder} autocomplete="off" spellcheck="false"
      rows="3" class="mono" data-test={test} oninput={changed}></textarea>
  {:else}
    <input bind:this={el} {type} {placeholder} aria-label={label ?? placeholder} autocomplete="off" spellcheck="false"
      class:mono data-test={test} oninput={changed} onkeydown={key} />
  {/if}
</div>

<style>
  /* the same box as TextField (one look per element) */
  .box { display: flex; border: var(--bw) solid var(--line-control); border-radius: var(--r-ctl);
    padding: 0 var(--s-3); min-height: var(--h-btn); transition: border-color var(--t-press); }
  .box:hover { border-color: var(--line-control-hover); }
  .box:focus-within { border-color: var(--accent-line); }
  .ok, .ok:hover { border-color: var(--q-lossless-line); }
  .bad, .bad:hover, .bad:focus-within { border-color: var(--q-weak-line); }
  .multi { padding: var(--s-2) var(--s-3); }
  input, textarea { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--text); padding: 7px 0;
    font-size: var(--fs-body); font-family: inherit; outline: none; user-select: text; -webkit-user-select: text; }
  textarea { resize: vertical; padding: 0; }
  input::placeholder, textarea::placeholder { color: var(--text-label); }
  .mono { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: var(--fs-small); }
  /* the hint text reads like the other fields; only what is pasted is monospace */
  .mono::placeholder { font-family: var(--font); font-size: var(--fs-body); }
</style>
