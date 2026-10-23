<script lang="ts">
  // A bar for a share or for live progress. The fill is the full width and slides in from the left (a transform, so
  // a live update repaints nothing). How a new value moves is `pace`, one of spec §6's three value motions:
  // - `value` (default): a share that changes on its own (a tile after a refresh), --t-value with --ease;
  // - `reply`: a value the user just changed (the run estimate after a click), --t-reply with --ease;
  // - `live`: progress during a job, linear over --t-live, a bit longer than the engine's update pace, so it moves on
  //   smoothly instead of stair-stepping.
  let { value, tone = 'accent', height = 4, label = 'Progress', pace = 'value' }: {
    value: number | null; tone?: 'accent' | 'lossless' | 'muted'; height?: number; label?: string;
    pace?: 'value' | 'reply' | 'live';
  } = $props();
  const pct = $derived(value === null ? null : Math.max(0, Math.min(1, value)) * 100);
</script>

<div class="pb" style:height="{height}px" role="progressbar" aria-label={label} aria-valuemin={0} aria-valuemax={100}
  aria-valuenow={pct === null ? undefined : Math.round(pct)}>
  {#if pct === null}<span class="ind live-anim {tone}"></span>{:else}<span class="fill {tone} {pace}"
    style:transform="translateX({pct - 100}%)"></span>{/if}
</div>

<style>
  .pb { width: 100%; background: var(--bg-inset); border-radius: var(--r-pill); overflow: hidden; position: relative; }
  span { display: block; height: 100%; border-radius: var(--r-pill); }
  .fill { width: 100%; transition: transform var(--t-value) var(--ease); }
  .fill.reply { transition: transform var(--t-reply) var(--ease); }
  .fill.live { transition: transform var(--t-live) linear; }
  .accent { background: var(--accent); }
  .lossless { background: var(--q-lossless-bar); }
  .muted { background: var(--text-label); }
  /* the indeterminate sweep moves by transform, not `left` (a layout property every frame; review-animations #7).
     translateX % is of the 30 % sweep's own width: -100 % starts it just off the left end, 333.34 % (100 / 30) just
     past the right one. It is .live-anim, so it keeps running under reduced motion (base.css: live state). */
  .ind { width: 30%; position: absolute; left: 0; top: 0; animation: slide 1.4s ease-in-out infinite; }
  @keyframes slide { from { transform: translateX(-100%); } to { transform: translateX(333.34%); } }
</style>
