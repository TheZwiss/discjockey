<script lang="ts">
  import type { Toast } from '../stores/toasts';
  import { link } from '../router';
  let { toast, onclose }: { toast: Toast; onclose: () => void } = $props();
</script>

<div class="toast {toast.tone}" role={toast.tone === 'problem' ? 'alert' : 'status'}>
  <span class="mark" aria-hidden="true">{toast.tone === 'success' ? '✓' : toast.tone === 'problem' ? '!' : 'i'}</span>
  <div class="text">
    <p class="title">{toast.title}</p>
    {#if toast.body}<p class="body">{toast.body}</p>{/if}
    {#if toast.action}
      {#if toast.action.href}<a href={toast.action.href} use:link class="act" onclick={onclose}>{toast.action.label}</a>
      {:else}<button type="button" class="act" onclick={() => { toast.action?.onclick?.(); onclose(); }}>{toast.action.label}</button>{/if}
    {/if}
  </div>
  <button type="button" class="close" aria-label="Close" onclick={onclose}>×</button>
</div>

<style>
  .toast { width: 340px; display: flex; gap: var(--s-3); align-items: flex-start; padding: var(--s-3) var(--s-3) var(--s-3) var(--s-4);
    background: var(--bg); border: var(--bw) solid var(--line-control); border-radius: var(--r-surface); box-shadow: var(--shadow); }
  .success { border-color: var(--q-lossless-line); }
  .problem { border-color: var(--q-weak-line); }
  .mark { width: 16px; text-align: center; font-weight: var(--fw-bold); color: var(--text-muted); flex-shrink: 0; }
  .success .mark { color: var(--q-lossless); }
  .problem .mark { color: var(--q-weak); }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .title { color: var(--text-strong); }
  .body { color: var(--text-muted); font-size: var(--fs-small); user-select: text; -webkit-user-select: text; overflow-wrap: anywhere; }
  .act { align-self: flex-start; margin-top: 4px; color: var(--accent-text); font-weight: var(--fw-semi); background: none;
    border: 0; padding: 0; font-size: var(--fs-small); }
  .close { border: 0; background: none; color: var(--text-label); font-size: var(--fs-title); line-height: 1; padding: 0 2px; }
  .close:hover { color: var(--text); }
</style>
