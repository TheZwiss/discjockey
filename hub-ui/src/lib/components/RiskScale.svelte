<script lang="ts">
  // A number picked on a scale of risk steps (Download limits' daily limit): five equal steps, careful · normal ·
  // faster · fast · risky, in the risk colours (green, green, yellow, yellow, red; design language §2). Equal steps,
  // not a linear 1–max track: "faster 61–79" would otherwise be a sliver next to "risky 101–150", and the steps are
  // what the user decides between; the value moves evenly inside each step. The handle follows the pointer 1:1 (no
  // transition, Apple's direct manipulation), the step under it lights up and names itself in its colour; `saved`
  // stays as a tick so the way back is visible (which step is the recommended one, the caller's verdict says). The
  // last step ends at `max` on the track (higher values: the caller's number field). Keys on the handle: ← / → one,
  // Page Up / Down ten, Home / End the ends.
  type Zone = { name: string; from: number; to: number };
  let { zones, value, saved = null, max, onchange, label, test }: {
    zones: Zone[]; value: number; saved?: number | null; max: number;
    onchange: (v: number) => void; label: string; test?: string;
  } = $props();

  const TONE = ['safe', 'safe', 'notice', 'notice', 'high'];
  const steps = $derived(zones.map((z) => ({ ...z, to: Math.min(z.to, max) })));
  const n = $derived(steps.length);
  const stepOf = (v: number) => {
    const i = steps.findIndex((z) => v >= z.from && v <= z.to);
    return i < 0 ? (v < steps[0].from ? 0 : n - 1) : i;
  };
  /** where a value sits on the track, 0–100 */
  function pos(v: number): number {
    const i = stepOf(v), z = steps[i];
    const inside = (Math.min(Math.max(v, z.from), z.to) - z.from + 0.5) / (z.to - z.from + 1);
    return ((i + inside) / n) * 100;
  }
  function valueAt(frac: number): number {
    const f = Math.min(0.9999, Math.max(0, frac)) * n, i = Math.floor(f), z = steps[i];
    return Math.round(z.from + (f - i) * (z.to - z.from));
  }
  const here = $derived(stepOf(value));
  const range = (z: Zone, i: number) => (i === 0 ? `≤ ${z.to}` : i === n - 1 ? `> ${z.from - 1}` : `${z.from}–${z.to}`);

  let track: HTMLDivElement | undefined = $state();
  let dragging = $state(false);
  function at(e: PointerEvent) {
    const r = track!.getBoundingClientRect();
    const v = valueAt((e.clientX - r.left) / r.width);
    if (v !== value) onchange(v);
  }
  function down(e: PointerEvent) {
    if (e.button !== 0) return;
    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    dragging = true;
    at(e);
    track?.querySelector<HTMLElement>('[role=slider]')?.focus();
  }
  function key(e: KeyboardEvent) {
    const step = { ArrowRight: 1, ArrowUp: 1, ArrowLeft: -1, ArrowDown: -1, PageUp: 10, PageDown: -10 }[e.key];
    let v: number | null = step ? value + step : e.key === 'Home' ? 1 : e.key === 'End' ? max : null;
    if (v === null) return;
    e.preventDefault();
    v = Math.min(max, Math.max(1, v));
    if (v !== value) onchange(v);
  }
</script>

<div class="scale" data-test={test}>
  <div class="track" class:dragging bind:this={track} role="presentation" onpointerdown={down}
    onpointermove={(e) => dragging && at(e)} onpointerup={() => (dragging = false)}
    onpointercancel={() => (dragging = false)}>
    <div class="steps" aria-hidden="true">
      {#each steps as z, i (z.name)}<span class="{TONE[i]}" class:here={i === here}></span>{/each}
    </div>
    {#if saved !== null && saved !== value}<span class="saved" style:left="{pos(saved)}%" aria-hidden="true"></span>{/if}
    <span class="thumb" style:left="{pos(value)}%" role="slider" tabindex="0" aria-label={label}
      aria-valuemin={1} aria-valuemax={max} aria-valuenow={value} aria-valuetext="{value}, {steps[here].name}"
      onkeydown={key} data-test={test ? `${test}-thumb` : undefined}></span>
  </div>
  <div class="names" aria-hidden="true">
    {#each steps as z, i (z.name)}
      <span class="{TONE[i]}" class:here={i === here}><b>{z.name}</b>{range(zones[i], i)}</span>
    {/each}
  </div>
</div>

<style>
  .scale { display: flex; flex-direction: column; gap: var(--s-2); }
  .track { position: relative; height: 20px; cursor: grab; touch-action: none; user-select: none; }
  .track.dragging { cursor: grabbing; }
  .steps { position: absolute; left: 0; right: 0; top: 6px; height: 8px; display: flex; gap: 3px; }
  .steps span { flex: 1; border-radius: var(--r-pill); opacity: .35; transition: opacity var(--t-state) var(--ease); }
  .steps span.here { opacity: 1; }
  .safe { --c: var(--risk-safe); }
  .notice { --c: var(--risk-notice); }
  .high { --c: var(--risk-high); }
  .steps span { background: var(--c); }
  .saved { position: absolute; top: 0; width: 2px; height: 20px; margin-left: -1px; border-radius: 1px;
    background: var(--text-muted); }
  .thumb { position: absolute; top: 1px; width: 18px; height: 18px; margin-left: -9px; border-radius: 50%;
    background: var(--text-strong); box-shadow: 0 0 0 3px var(--panel-bg), var(--knob-shadow);
    transition: transform var(--t-press) var(--ease); }
  .dragging .thumb { transform: scale(1.12); }
  .thumb:focus-visible { outline: var(--bw-accent) solid var(--accent-line); outline-offset: 3px; }
  .names { display: flex; gap: 3px; }
  .names span { flex: 1; min-width: 0; text-align: center; font-size: var(--fs-label); color: var(--text-label);
    line-height: 1.35; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .names b { display: block; font-weight: var(--fw-semi); color: var(--text-muted); }
  .names span.here { color: var(--text); }
  .names span.here b { color: var(--c); }
</style>
