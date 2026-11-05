<script lang="ts">
  // Where to find a playlist's link in each service's app, and what such a link looks like (sources round I4, notes
  // problem 2): AddRow's logos say which services, this says what to copy. A `Surface list`, one row per service in
  // the user's order (linkGuideModel): logo · name · where to click · an example link. Rows say, they do nothing: no
  // hover, no press. The columns come with the guide's own width (container query, design language §1):
  //   under 400 px (a panel)  name over where, two lines
  //   from 400 px             name | where
  //   from 560 px             name | where | example link
  // `folded` (Setup once a playlist is in): only the head, a disclosure with the four logos at its end; a click opens
  // it (`open`, bindable) and the logos give way to the rows. The example link is in the body font, muted: a link's
  // shape to recognise, not code to type (the design language has no code face; FolderField's mono is a path's well).
  import { PLAYLIST_SERVICE_NAMES } from '../copy';
  import { GUIDE_HEAD, GUIDE_SERVICES, guideRows } from './linkGuideModel';
  import ServiceMark from './ServiceMark.svelte';
  import { logoOf } from './serviceLogos';
  import Surface from './Surface.svelte';
  import { tip } from './tip';

  let { folded = false, open = $bindable(false), 'data-test': test = 'link-guide' }: {
    folded?: boolean; open?: boolean; 'data-test'?: string;
  } = $props();
  const rows = guideRows();
</script>

{#snippet logos()}
  {#if folded && !open}
    <span class="logos" data-test="{test}-logos">
      {#each GUIDE_SERVICES as s (s)}<ServiceMark service={logoOf(s)} label={PLAYLIST_SERVICE_NAMES[s]} />{/each}
    </span>
  {/if}
{/snippet}

<Surface kind="list" label={GUIDE_HEAD} foldable={folded} bind:open header={folded ? logos : undefined}
  data-test={test}>
  {#each rows as r (r.service)}
    <div class="row" data-test="{test}-{r.service}">
      <ServiceMark service={logoOf(r.service)} label={PLAYLIST_SERVICE_NAMES[r.service]} />
      <span class="name">{PLAYLIST_SERVICE_NAMES[r.service]}</span>
      <span class="where">{r.where}</span>
      <span class="example" use:tip={{ text: r.example, cut: true }}>{r.example}</span>
    </div>
  {/each}
</Surface>

<style>
  .logos { display: inline-flex; align-items: center; gap: 6px; }
  /* the rows' width decides the columns (Surface's rows are the `list` container), wherever the guide stands (Setup's
     column, the Playlists panel). Under 400 px: logo | name over where, a tall row */
  .row { display: grid; grid-template-columns: 14px minmax(0, 1fr); grid-template-areas: 'mark name' '. where';
    column-gap: var(--s-3); row-gap: 2px; align-items: center; min-height: var(--h-list-row-tall);
    padding: var(--s-2) var(--s-4); min-width: 0; }
  .row > :global([data-service-mark]) { grid-area: mark; }
  .name { grid-area: name; min-width: 0; color: var(--text); white-space: nowrap; overflow: hidden;
    text-overflow: ellipsis; }
  .where { grid-area: where; min-width: 0; font-size: var(--fs-small); color: var(--text-muted); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  .example { display: none; min-width: 0; font-size: var(--fs-small); color: var(--text-label); white-space: nowrap;
    overflow: hidden; text-overflow: ellipsis; }
  /* from 400 px: one line, name | where */
  @container list (min-width: 400px) {
    .row { grid-template-columns: 14px 112px minmax(0, 1fr); grid-template-areas: 'mark name where';
      min-height: var(--h-list-row); padding-block: 0; }
  }
  /* from 560 px: the example link as a third column */
  @container list (min-width: 560px) {
    .row { grid-template-columns: 14px 112px 200px minmax(0, 1fr); grid-template-areas: 'mark name where example'; }
    .example { display: block; grid-area: example; }
  }
</style>
