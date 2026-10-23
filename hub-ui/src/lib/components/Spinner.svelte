<script lang="ts">
  let { size = 12, label = 'Loading' }: { size?: number; label?: string } = $props();
</script>

<span class="spinner live-anim" style:width="{size}px" style:height="{size}px" role="status" aria-label={label}></span>

<style>
  .spinner {
    display: inline-block; flex-shrink: 0; border-radius: var(--r-pill);
    border: var(--bw-accent) solid currentColor; border-right-color: transparent;
    animation: dj-spin 0.8s linear infinite; opacity: .8;
  }
</style>
