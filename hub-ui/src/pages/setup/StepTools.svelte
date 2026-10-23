<script lang="ts">
  // Step 1, Programs (shown only when one is missing; Setup opens past it otherwise): the three free programs
  // Discjockey needs, each with its state; a missing one gets its Terminal line to copy. Check again is the screen's
  // filled button while something is missing (Continue waits for it), quiet once everything is there.
  import { Button, CopyCode, Hint, NoteCard, Skeleton, StatusMark, Surface } from '$lib/components';
  import type { SetupTools } from '$lib/bridge/types';
  import { TOOL_NAMES, TOOL_PURPOSE, toolFixes } from './setupModel';
  let { tools, error, checking, onrecheck }: {
    tools: SetupTools | null; error: string | null; checking: boolean; onrecheck: () => void;
  } = $props();

  const missing = $derived(!!tools && TOOL_NAMES.some((n) => !tools?.tools[n]));
  // one line per command: ffprobe comes with ffmpeg, so a missing pair shows `brew install ffmpeg` once
  const fixes = $derived(toolFixes(tools));
</script>

<Surface kind="card" label="Programs on this Mac" summary="Discjockey needs three free programs." data-test="tools-list">
  {#if !tools}
    <Skeleton lines={3} />
  {:else}
    <ul class="tools">
      {#each TOOL_NAMES as name (name)}
        {@const ok = tools.tools[name]}
        <li class:missing={!ok} data-test="tool-{name}">
          <StatusMark tone={ok ? 'good' : 'problem'} />
          <span class="name">{name}</span><span class="what">{ok ? TOOL_PURPOSE[name] : `missing · ${TOOL_PURPOSE[name]}`}</span>
          {#if fixes[name]}<div class="fix"><CopyCode text={fixes[name] ?? ''} test="tool-fix-{name}" /></div>{/if}
        </li>
      {/each}
    </ul>
  {/if}
  <div class="again">
    <Button variant={missing ? 'filled' : 'secondary'} onclick={onrecheck} busy={checking} data-test="check-again">Check
      again</Button>
    {#if missing}<Hint text="Paste the line into the Terminal app, press Return, then Check again." data-test="terminal-tip" />{/if}
  </div>
</Surface>
{#if error}<NoteCard tone="problem" title="The programs couldn't be checked." data-test="tools-error">{error}</NoteCard>{/if}

<style>
  .tools { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
  li { display: grid; grid-template-columns: 16px 64px minmax(0, 1fr); column-gap: var(--s-2); row-gap: var(--s-2);
    align-items: center; min-height: var(--h-list-row); padding: var(--s-2) 0; border-top: var(--bw) solid var(--line-soft); }
  li:first-child { border-top: 0; }
  .name { color: var(--text-strong); font-weight: var(--fw-semi); }
  .what { color: var(--text-muted); font-size: var(--fs-small); min-width: 0; overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
  .missing .what { color: var(--text); }
  .fix { grid-column: 2 / -1; }
  .again { display: flex; align-items: center; gap: var(--s-3); margin-top: var(--s-3); min-width: 0; }
</style>
