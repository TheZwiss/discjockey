<script lang="ts">
  // One drawn icon per kind of plan action (planModel KINDS), shared by the panel's What to do rows, the plan rows'
  // narrow mark (a list under 680 px, where the why column hides) and the Gallery, so a kind looks the same wherever
  // it shows. Drawn at stroke 1.6 like the chevron and ⊘ (NeverButton): text glyphs (↓ ↻) at 11–13 px rendered
  // thin and uneven, as ▸ and ⊘ did (spec §11). Colour comes from the text around it (currentColor). Only a known kind
  // has an icon (callers with a plain string check `isKindKey`); anything else draws nothing rather than a download's.
  import type { KindKey } from '../planModel';
  let { kind, size = 14 }: { kind: KindKey; size?: number } = $props();
  const PATHS: Record<KindKey, string> = {
    new: 'M8 2.5v9M4.5 8 8 11.5 11.5 8M3.5 13.5h9',                         // download: arrow onto a line
    retry: 'M12.5 8A4.5 4.5 0 1 1 11 4.6M12.5 2.5v2.75H9.75',                // try again: arrow round
    redownload: 'M4.5 2.5h4.5l2.5 2.5v8.5h-7zM2.5 13.5l11-11',                // file gone: a page struck through
    bought: 'M2.5 8.5V2.5h6l5 5-6 6zM5.5 5.5h.01',                           // bought: a price tag
    weekly: 'M3 4h10v9.5H3zM3 7h10M6 2.5v3M10 2.5v3',                         // weekly check: a calendar
  };
  const d = $derived(PATHS[kind] as string | undefined);
</script>

{#if d}<svg class="kind-icon" width={size} height={size} viewBox="0 0 16 16" aria-hidden="true"><path {d} /></svg>{/if}

<style>
  .kind-icon { flex: none; display: block; fill: none; stroke: currentColor; stroke-width: 1.6; stroke-linecap: round;
    stroke-linejoin: round; }
</style>
