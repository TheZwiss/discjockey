<script lang="ts">
  // A state as colour plus shape (design language §2): ✓ in green, ! in yellow, ▪ in red, a 16 px mark in front of
  // the words that name it ("All good", "Search failed"). `quiet` draws a fine ✓ as an outline, for a check that
  // passed among ones that didn't (Download limits' warning signs). `none` is the neutral "nothing here yet": an empty
  // dashed circle of the same size (the source ladder's account not set up). Decorative: the words beside it carry
  // the state.
  let { tone, quiet = false }: { tone: 'good' | 'warn' | 'problem' | 'none'; quiet?: boolean } = $props();
  const GLYPH = { good: '✓', warn: '!', problem: '▪', none: '' } as const;
</script>

<span class="mark {tone}" class:quiet aria-hidden="true">{GLYPH[tone]}</span>

<style>
  .mark { display: inline-grid; place-items: center; flex: none; width: 16px; height: 16px; border-radius: 50%;
    font-size: var(--fs-label); font-weight: var(--fw-bold); line-height: 1; color: var(--text-on-accent); }
  .good { background: var(--risk-safe); }
  .warn { background: var(--risk-notice); }
  .problem { background: var(--risk-high); }
  .none { border: var(--bw) dashed var(--line-control-hover); }
  .quiet { background: none; color: var(--risk-safe); box-shadow: inset 0 0 0 var(--bw-accent) var(--risk-safe-line); }
</style>
