<script lang="ts" generics="K extends string | number">
  // One of a few, each with a consequence (design language "each kind of choice has exactly one form", decision log
  // 2026-10-31; To-do's "In rekordbox" and "Which file stays?"): radio rows in a list Surface under its label. A row is
  // a ring · its name (+ "Recommended" in accent caps) · one line: the outcomes while it is picked (OutcomeList), its
  // summary while another is, its reason when it can't be picked (dimmed, --dim-locked). `content` replaces a row's
  // middle (Duplicates' file rows), `trail` sits at its end outside the radio (a ▶ of its own), `foot` is a ruled last
  // section (what happens either way). Arrow keys move the pick (roving tabindex, as a radio group); nothing is picked
  // until the caller says so (`value` null), so a group without a clear winner asks first.
  import type { Snippet } from 'svelte';
  import Hint from './Hint.svelte';
  import OutcomeList from './OutcomeList.svelte';
  import Surface from './Surface.svelte';
  import { stepChoice, type ChoiceOption } from './choiceModel';

  let { label, summary, hint, options, value, onchange, content, trail, foot, disabled = false, test }: {
    label: string; summary?: string;
    /** one line under the head, about the whole choice ("Same quality and format. …") */
    hint?: string;
    options: ChoiceOption<K>[]; value: K | null; onchange: (key: K) => void;
    content?: Snippet<[ChoiceOption<K>, boolean]>; trail?: Snippet<[ChoiceOption<K>]>; foot?: Snippet;
    /** the whole group is off (a job is running) */
    disabled?: boolean; test?: string;
  } = $props();

  let rows = $state<HTMLElement | null>(null);
  const first = $derived(options.find((o) => !o.disabled)?.key ?? null);
  // the one row Tab reaches: the picked one, else the first that can be picked
  const stop = $derived(value !== null && options.some((o) => o.key === value && !o.disabled) ? value : first);

  function key(e: KeyboardEvent, o: ChoiceOption<K>) {
    const step = e.key === 'ArrowDown' || e.key === 'ArrowRight' ? 1 : e.key === 'ArrowUp' || e.key === 'ArrowLeft' ? -1 : 0;
    if (!step) return;
    e.preventDefault();
    const next = stepChoice(options, o.key, step);
    if (next === null || next === o.key) return;
    onchange(next);
    const i = options.findIndex((x) => x.key === next);
    rows?.querySelectorAll<HTMLButtonElement>('[role=radio]')[i]?.focus();
  }
</script>

<Surface kind="list" {label} {summary} data-test={test}>
  {#if hint}<div class="hint"><Hint text={hint} wrap /></div>{/if}
  <div class="rows" role="radiogroup" aria-label={label} bind:this={rows}>
    {#each options as o (o.key)}
      {@const on = o.key === value}
      <div class="row" class:on class:off={o.disabled} class:ruled={o.ruled} data-test={o.test} data-key={o.key}
        data-on={on || undefined}>
        <button type="button" role="radio" class="hit" aria-checked={on} tabindex={o.key === stop ? 0 : -1}
          disabled={disabled || o.disabled} title={o.disabled ? o.reason : undefined}
          onclick={() => { if (!on) onchange(o.key); }} onkeydown={(e) => key(e, o)}>
          <span class="rb" aria-hidden="true"></span>
          <span class="cx">
            {#if content}{@render content(o, on)}
            {:else}
              <span class="nm"><span class="n">{o.name}</span>{#if o.recommended}<span class="rec">Recommended</span>{/if}</span>
              {#if o.disabled && o.reason}<span class="why lock">{o.reason}</span>
              {:else if on && o.outcomes?.length}<OutcomeList items={o.outcomes} />
              {:else if o.summary}<span class="why">{o.summary}</span>{/if}
            {/if}
          </span>
        </button>
        {#if trail}<span class="trail">{@render trail(o)}</span>{/if}
      </div>
    {/each}
  </div>
  {#if foot}<div class="foot">{@render foot()}</div>{/if}
</Surface>

<style>
  .hint { padding: 0 var(--s-4) var(--s-3); margin-top: calc(-1 * var(--s-1)); }
  .rows { display: flex; flex-direction: column; }
  .row { display: flex; align-items: center; gap: var(--s-2); border-top: var(--bw) solid var(--line-soft);
    padding-right: var(--s-4); transition: background var(--t-hover) var(--ease); }
  .row.ruled { border-top-color: var(--surface-line); }
  .row.on { background: var(--accent-wash); }
  .hit { flex: 1; min-width: 0; display: flex; align-items: flex-start; gap: 10px; padding: 11px 0 11px var(--s-4);
    border: 0; background: none; color: inherit; font: inherit; text-align: left; cursor: pointer; }
  .hit:disabled { cursor: default; }
  @media (hover: hover) and (pointer: fine) {
    .row:not(.on):not(.off):hover { background: var(--ctl-hover); }
  }
  .row:not(.on):not(.off):active { background: var(--ctl-press); }
  .hit:focus-visible { outline: none; }
  .row:has(.hit:focus-visible) { box-shadow: inset 0 0 0 var(--bw-accent, 1.5px) var(--accent-line); }
  .rb { width: 16px; height: 16px; border-radius: var(--r-pill); border: 1.5px solid var(--line-control);
    flex-shrink: 0; margin-top: 1px; position: relative; transition: border-color var(--t-hover) var(--ease); }
  .rb::after { content: ''; position: absolute; inset: 3px; border-radius: var(--r-pill); background: var(--accent);
    transform: scale(0.6); opacity: 0; transition: transform var(--t-hover) var(--ease), opacity var(--t-hover) var(--ease); }
  .on .rb { border-color: var(--accent); }
  .on .rb::after { transform: scale(1); opacity: 1; }
  .off .rb, .off .nm { opacity: var(--dim-locked); }
  .cx { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .cx > :global(.outcomes) { margin-top: 3px; }
  .nm { display: flex; align-items: baseline; gap: var(--s-2); min-width: 0; color: var(--text); font-weight: var(--fw-medium); }
  .n { min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .rec { margin-left: auto; font-size: var(--fs-label); text-transform: uppercase; letter-spacing: 0.7px;
    color: var(--accent-text); font-weight: var(--fw-semi); white-space: nowrap; }
  .why { font-size: var(--fs-small); color: var(--text-muted); }
  .why.lock { color: var(--text-label); }
  .trail { flex-shrink: 0; display: flex; align-items: center; }
  .foot { padding: 10px var(--s-4) var(--s-3); border-top: var(--bw) solid var(--line-soft); display: flex;
    flex-direction: column; gap: var(--s-2); }
  @media (prefers-reduced-motion: reduce) { .row, .rb, .rb::after { transition: none; } }
</style>
