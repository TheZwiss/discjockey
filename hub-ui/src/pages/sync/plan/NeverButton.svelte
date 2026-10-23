<script lang="ts">
  // ⊘ "Never download this track": Button's `icon` form with a drawn "no" mark, red on hover (it hides the track from
  // every later sync). `blocked` is why it can't be used right now (another change runs); it is the tooltip then.
  import { Button } from '$lib/components';
  let { name, blocked = null, onclick }: { name: string; blocked?: string | null; onclick: () => void } = $props();
</script>

<Button variant="icon" destructive aria-label="Never download {name}" title={blocked ?? 'Never download this track'}
  disabled={!!blocked} {onclick} data-test="sync-never">
  <svg viewBox="0 0 16 16" aria-hidden="true"><circle cx="8" cy="8" r="5.5" /><path d="M4.1 11.9l7.8-7.8" /></svg>
</Button>
