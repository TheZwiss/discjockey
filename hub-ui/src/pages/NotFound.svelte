<script lang="ts">
  import { onMount } from 'svelte';
  import { markReady } from '$lib/ready';
  import { EmptyState } from '$lib/components';
  onMount(() => markReady('unknown'));
</script>

<EmptyState title="Nothing here." action={{ label: 'Go to the Dashboard →', href: '#/' }} />
