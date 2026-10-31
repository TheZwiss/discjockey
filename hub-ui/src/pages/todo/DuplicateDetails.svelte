<script lang="ts">
  // Duplicates in the panel (plan library stage 4, 7.3, W8; mockup todo-decisions "Which file stays?"): the same
  // audio, or the same song, in two or more files. The head names the song (the track card, the why under it), then
  // the shared choice of the file that stays (lib/decisions DuplicateChoice, the Library's details show the same); the
  // foot is its button (DuplicateFoot). Errors: runJob's toast, words as sent; the re-fetch keeps the group selected
  // while files are left in it.
  import type { DuplicateItem } from '$lib/bridge/types';
  import { Surface, TrackHead } from '$lib/components';
  import { DuplicateChoice, DuplicateFlow, DuplicateFoot } from '$lib/decisions';
  import { Panel } from '$lib/frames';

  let { item, onacted }: {
    item: DuplicateItem;
    /** a Keep starts here: `keep` are the paths of the files that stay (the page follows the song that has one) */
    onacted?: (keep: string[]) => void;
  } = $props();

  // the app's pick until the user picks (the component is keyed by the group, so a new group starts over)
  const flow = new DuplicateFlow({ onact: (keep) => onacted?.(keep) });
  const pick = $derived(flow.pick(item.pair));
</script>

{#snippet head()}
  <div class="details" data-test="duplicates" data-group={item.pair.group_id} data-files={item.pair.files.length}
    data-pick={pick ?? undefined}>
    <Surface kind="card">
      <TrackHead track={item} place={item.folder}><span class="why">{item.detail}</span></TrackHead>
    </Surface>
    <DuplicateChoice {item} {flow} />
  </div>
{/snippet}

{#snippet foot()}<DuplicateFoot {item} {flow} />{/snippet}

<Panel {head} {foot} />

<style>
  .details { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .why { font-size: var(--fs-small); color: var(--text-muted); }
</style>
