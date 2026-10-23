<script lang="ts">
  // Credentials typed here stay in this input until they are sent; never put them in a store.
  import type { Snippet } from 'svelte';
  let { value = $bindable(''), placeholder = '', type = 'text', invalid = false, hint, okHint, autofocus = false,
    onenter, label, name, disabled = false, mono = false, trailing }:
    { value?: string; placeholder?: string; type?: 'text' | 'password' | 'email' | 'url' | 'number'; invalid?: boolean;
      hint?: string; okHint?: string; autofocus?: boolean; onenter?: () => void; label?: string; name?: string;
      disabled?: boolean; mono?: boolean; trailing?: Snippet } = $props();
  let el: HTMLInputElement | undefined = $state();
  $effect(() => { if (autofocus) el?.focus(); });
  function key(e: KeyboardEvent) { if (e.key === 'Enter' && onenter) { e.preventDefault(); onenter(); } }
</script>

<div class="tf">
  <div class="box" class:invalid class:ok={!!okHint && !invalid} class:disabled>
    <input bind:this={el} bind:value {type} {placeholder} {name} {disabled} class:mono aria-label={label ?? placeholder}
      aria-invalid={invalid || undefined} autocomplete={type === 'password' ? 'current-password' : 'off'}
      spellcheck="false" onkeydown={key} />
    {#if trailing}<span class="trailing">{@render trailing()}</span>{/if}
  </div>
  {#if invalid && hint}<div class="hint bad">{hint}</div>
  {:else if okHint}<div class="hint good">✓ {okHint}</div>
  {:else if hint}<div class="hint">{hint}</div>{/if}
</div>

<style>
  .tf { display: flex; flex-direction: column; gap: 4px; min-width: 0; }
  .box { display: flex; align-items: center; gap: var(--s-2); border: var(--bw) solid var(--line-control);
    border-radius: var(--r-ctl); padding: 0 var(--s-3); min-height: var(--h-btn); transition: border-color var(--t-press); }
  .box:hover { border-color: var(--line-control-hover); }
  .box:focus-within { border-color: var(--accent-line); }
  .invalid, .invalid:hover, .invalid:focus-within { border-color: var(--q-weak-line); }
  .ok { border-color: var(--q-lossless-line); }
  .disabled { opacity: .6; }
  input { flex: 1; min-width: 0; border: 0; background: transparent; color: var(--text); padding: 7px 0;
    font-size: var(--fs-body); outline: none; user-select: text; -webkit-user-select: text; }
  input::placeholder { color: var(--text-label); }
  .mono { font-family: ui-monospace, "SF Mono", Menlo, monospace; font-size: var(--fs-small); }
  .hint { font-size: var(--fs-small); color: var(--text-label); }
  .bad { color: var(--q-weak); }
  .good { color: var(--q-lossless); }
  .trailing { display: inline-flex; }
</style>
