<script lang="ts">
  import type { Quality } from '../bridge/types';
  let { tone = 'muted', text }: { tone?: Quality | 'accent' | 'muted' | 'other'; text: string } = $props();
</script>

<span class="badge {tone}">{text}</span>

<style>
  .badge {
    display: inline-block; font-size: var(--fs-label); font-weight: var(--fw-bold); line-height: 1.35;
    padding: 1px 6px; border-radius: var(--r-badge); border: var(--bw) solid var(--q-other-line);
    color: var(--q-other); white-space: nowrap; letter-spacing: .2px; font-variant-numeric: tabular-nums;
    user-select: none; -webkit-user-select: none;
  }
  .lossless { color: var(--q-lossless); border-color: var(--q-lossless-line); }
  .good_lossy { color: var(--q-good); border-color: var(--q-good-line); }
  .weak, .missing { color: var(--q-weak); border-color: var(--q-weak-line); }
  .fake { color: var(--q-fake); border-color: var(--q-fake-line); }
  .accent { color: var(--accent-text); border-color: var(--accent-line); }
  .muted { color: var(--text-muted); border-color: var(--line-control); }
</style>
