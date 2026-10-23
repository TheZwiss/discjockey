<script module lang="ts">
  /** One step of a StepStrip. `state`: `done` (✓, can be opened again), `current` (on screen), `open` (the next one
   *  you can open), `locked` (waits for an earlier step; not clickable). `done` also marks the current step ✓. */
  export type StripStep<K extends string = string> = {
    key: K; label: string; state: 'done' | 'current' | 'open' | 'locked'; done?: boolean;
  };
</script>

<script lang="ts" generics="K extends string">
  // Where you are in a short guide (Setup, spec settings-setup §8): one row of equal steps, each a number (✓ when
  // done) and its label. Unlike Segmented, a step can be not reachable yet: it stays readable but is no button, its
  // number dashed. The current step carries the accent (the one selection on screen) and `aria-current="step"`; done
  // and open steps are buttons that open their step. Fixed height (--h-btn), equal widths; where the labels don't
  // fit, the other steps end in "…" (full label in `title`) and the current one keeps its label, as in Segmented. Selection moves at once (spec §6: selection after a click is
  // instant); a ✓ appearing fades its colour in (--t-state).
  let { steps, onpick, label, test }:
    { steps: StripStep<K>[]; onpick: (key: K) => void; label: string; test?: string } = $props();
  const sub = (key: string) => (test ? `${test}-${key}` : undefined);
</script>

<ol class="strip" aria-label={label} data-test={test}>
  {#each steps as s, i (s.key)}
    {@const mark = s.done || s.state === 'done' ? '✓' : String(i + 1)}
    <li class:now={s.state === 'current'}>
      {#if s.state === 'done' || s.state === 'open'}
        <button type="button" class="step {s.state}" data-step-hit onclick={() => onpick(s.key)} title={s.label} data-test={sub(s.key)}
          data-state={s.state}>
          <span class="n" aria-hidden="true">{mark}</span><span class="label">{s.label}</span>
          {#if s.state === 'done'}<span class="sr">(done)</span>{/if}
        </button>
      {:else}
        <span class="step {s.state}" class:checked={s.done} title={s.label} data-test={sub(s.key)} data-state={s.state}
          aria-current={s.state === 'current' ? 'step' : undefined}>
          <span class="n" aria-hidden="true">{mark}</span><span class="label">{s.label}</span>
          {#if s.state === 'locked'}<span class="sr">(after the steps before it)</span>{/if}
        </span>
      {/if}
    </li>
  {/each}
</ol>

<style>
  .strip { list-style: none; margin: 0; padding: 0; display: flex; gap: var(--s-2); min-width: 0; }
  /* equal steps; in a narrow strip the others shorten to "…" first, the one on screen keeps its whole label */
  li { flex: 1 1 0; min-width: 0; display: flex; }
  li.now { min-width: max-content; }
  .step { flex: 1; min-width: 0; height: var(--h-btn); display: flex; align-items: center; gap: var(--s-2);
    padding: 0 var(--s-3); border: var(--bw) solid var(--ctl-line); border-radius: var(--r-ctl); background: var(--ctl-bg);
    font: inherit; font-size: var(--fs-small); color: var(--text-label); text-align: left; white-space: nowrap; }
  .label { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .n { flex: none; width: 18px; height: 18px; border-radius: var(--r-pill); border: var(--bw-accent) solid var(--line-control-hover);
    display: grid; place-items: center; font-size: var(--fs-label); font-weight: var(--fw-bold);
    font-variant-numeric: tabular-nums; transition: color var(--t-state) var(--ease), border-color var(--t-state) var(--ease); }
  .sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip-path: inset(50%); white-space: nowrap; }

  /* done: quiet, its ✓ in the done green; it opens its step again */
  .done { color: var(--text-muted); }
  .done .n, .checked .n { border-color: var(--q-lossless); color: var(--q-lossless); }
  /* open: the next step you can go to, as readable as a done one, its number still neutral */
  .open { color: var(--text-muted); }
  /* the step on screen: the one selection, in the accent */
  .current { color: var(--text-strong); border-color: var(--accent-line); background: var(--accent-wash); }
  .current .n { border-color: var(--accent); color: var(--accent-text); }
  /* not reachable yet: readable as a label, no fill, its number dashed (it waits) */
  .locked { background: none; }
  .locked .n { border-style: dashed; }

  button.step { cursor: pointer; }
  /* rows and joined controls highlight on press instead of shrinking (spec §6) */
  button.step:active { transform: none; background: var(--ctl-press); transition: none; }
  @media (hover: hover) {
    button.step:hover { background: var(--ctl-hover); color: var(--text);
      transition: background-color var(--t-hover) var(--ease), color var(--t-hover) var(--ease); }
  }
  button.step:focus-visible { outline-offset: -2px; }
</style>
