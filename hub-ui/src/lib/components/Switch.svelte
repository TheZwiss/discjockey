<script lang="ts">
  // The on/off knob (design system §4). Presentational only: the row around it is the button (`role="switch"`,
  // `aria-checked`, see ToggleRow), so the switch is hidden from assistive tech and `label` only names it for tests
  // and the gallery (`data-label`). Knob slides with the state curve (a transform, so a whole group switching at
  // once lays out nothing); pressing the row stretches it towards where it will go (§6 press).
  let { on, label, disabled = false }: { on: boolean; label: string; disabled?: boolean } = $props();
</script>

<span class="sw" class:on class:disabled aria-hidden="true" data-label={label}></span>

<style>
  .sw { width: 30px; height: 18px; border-radius: var(--r-pill); background: var(--ctl-line); position: relative;
    transition: background var(--t-state) var(--ease), opacity var(--t-state) var(--ease); flex: none; }
  .sw::after { content: ''; position: absolute; top: 2px; left: 2px; width: 14px; height: 14px; border-radius: var(--r-pill);
    background: var(--text-muted); box-shadow: var(--knob-shadow);
    transition: transform var(--t-state) var(--ease), width var(--t-press) ease-out; }
  .on { background: var(--accent); } .on::after { transform: translateX(12px); background: var(--text-strong); }
  /* pressed: the knob stretches towards where it will go (an "on" knob grows to the left, so it moves 3 px back) */
  :global(button:active:not([aria-disabled])) > .sw::after { width: 17px;
    transition: transform var(--t-press) ease-out, width var(--t-press) ease-out; }
  :global(button:active:not([aria-disabled])) > .on::after { transform: translateX(9px); }
  .disabled { opacity: var(--dim-locked); }
</style>
