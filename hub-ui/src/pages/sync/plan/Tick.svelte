<script lang="ts">
  // The checkbox look (the button around it is the control).
  let { on, mixed = false }: { on: boolean; mixed?: boolean } = $props();
</script>

<span class="tick" class:on class:mixed aria-hidden="true" data-mark>{on ? '✓' : mixed ? '–' : ''}</span>

<style>
  .tick { width: 16px; height: 16px; flex: none; display: inline-grid; place-items: center; border-radius: var(--r-badge);
    border: var(--bw) solid var(--line-control-hover); color: var(--text-on-accent); font-size: var(--fs-label);
    font-weight: var(--fw-bold); line-height: 1; transition: background var(--t-state) var(--ease), border-color var(--t-state) var(--ease); }
  .on { background: var(--accent); border-color: var(--accent); }
  .mixed { border-color: var(--accent-line); color: var(--accent-text); }
</style>
