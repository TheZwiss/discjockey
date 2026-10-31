<script lang="ts">
  // What a choice does, one short line each (design language "colour has fixed jobs", decision log 2026-10-31): a
  // glyph and its colour say the kind of consequence, so the line reads at a glance and never needs a tooltip. kept:
  // green ✓ (stays as it was, or fits), step: yellow ⓘ (needs a step from you), lost: red ✕ (something is lost),
  // file: a grey folder (where a file goes; the text in muted grey). Spans throughout, so it may sit inside a
  // ChoiceGroup row's button.
  import type { Outcome } from './choiceModel';
  let { items, test }: { items: Outcome[]; test?: string } = $props();
</script>

<span class="outcomes" role="list" data-test={test}>
  {#each items as o, i (i)}
    <span class="o {o.tone}" role="listitem" data-tone={o.tone}>
      <svg viewBox="0 0 12 12" aria-hidden="true" fill="none" stroke="currentColor" stroke-linecap="round"
        stroke-linejoin="round">
        {#if o.tone === 'kept'}<path d="M2.5 6.3l2.2 2.2 4.8-5" stroke-width="1.6" />
        {:else if o.tone === 'step'}<circle cx="6" cy="6" r="4.6" stroke-width="1.5" /><path d="M6 3.6v2.8M6 8.3v.1" stroke-width="1.5" />
        {:else if o.tone === 'lost'}<path d="M3.3 3.3l5.4 5.4M8.7 3.3l-5.4 5.4" stroke-width="1.6" />
        {:else}<path d="M1.5 3.5h3l1 1h5v5h-9z" stroke-width="1.4" />{/if}
      </svg>
      <span class="t">{o.text}</span>
    </span>
  {/each}
</span>

<style>
  .outcomes { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .o { display: grid; grid-template-columns: 14px minmax(0, 1fr); gap: 6px; align-items: start; font-size: var(--fs-small);
    line-height: 16px; color: var(--text); }
  .o svg { width: 12px; height: 12px; margin-top: 2px; }
  .o.kept svg { color: var(--q-lossless); }
  .o.step svg { color: var(--q-good); }
  .o.lost svg { color: var(--q-weak); }
  .o.file svg { color: var(--text-label); }
  .o.file { color: var(--text-muted); }
  .t { min-width: 0; overflow-wrap: break-word; }
</style>
