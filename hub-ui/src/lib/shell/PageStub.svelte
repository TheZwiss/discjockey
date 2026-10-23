<script lang="ts">
  // Placeholder until the page's own task builds it.
  import { onMount } from 'svelte';
  import { markReady } from '../ready';
  import PageHeader from '../components/PageHeader.svelte';
  import EmptyState from '../components/EmptyState.svelte';
  import SplitView from '../components/SplitView.svelte';
  let { page, title }: { page: string; title: string } = $props();
  onMount(() => markReady(page));
</script>

<SplitView>
  {#snippet main()}
    <PageHeader {title} />
    <EmptyState title="This screen comes next." />
  {/snippet}
</SplitView>
