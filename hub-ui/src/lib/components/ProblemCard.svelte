<script lang="ts">
  // One look per problem kind (spec §8). The backend's message is always the detail line, shown verbatim.
  // The card is a `Surface` card with the problem tone (design system §4: everything sits in a container; §5 look),
  // and `data-note` marks it as explanation for the rule checker, like NoteCard: its hint and message lines may be
  // long. `compact` is the one-line form that sits inside another control or row (SpotifyStatus in the page header,
  // a playlist row, a dialog's search): no box of its own, since a box inside a row would be a container in a
  // container (§4), but still marked `data-note`.
  // `actions`: the caller's own recovery control for this problem (Sync's crashed card: Show reports folder), set
  // beside the card's own action inside the card, so it sits with the problem it answers instead of loose on the
  // background below it (§4, grouping by proximity; spec §11, Task 10B).
  import type { Snippet } from 'svelte';
  import type { ProblemKind } from '../bridge/types';
  import { detailLine, problemCopy } from '../copy';
  import { api } from '../bridge/client';
  import Button from './Button.svelte';
  import Surface from './Surface.svelte';

  // `spotify`: the problem is Spotify's login (its "not set up" reads "Spotify isn't connected.", like the banner)
  let { kind, message, onretry, report, compact = false, sync = false, spotify = false, actions,
    alert = false }:
    { kind: ProblemKind; message: string; onretry?: () => void; report?: { run_id: string } | null; compact?: boolean;
    /** a problem the user's own action just caused (a start, a search): announced at once (`role=alert`); a card
     *  drawn with its page has no role, so VoiceOver doesn't interrupt on load (final review M11) */
    alert?: boolean;
      sync?: boolean; spotify?: boolean; actions?: Snippet } = $props();
  const c = $derived(problemCopy(kind, { sync, spotify }));
  // the headline's own button only when this card can carry it out (no report → fall back to Try again)
  const action = $derived(
    c.action && (c.action.href || (c.action.retry && onretry) || (c.action.report && report)) ? c.action : undefined,
  );
  // the detail line minus a repeat of the headline, and minus a lone "Try again." next to a Try again button
  const button = $derived(action?.label ?? (onretry && !compact ? 'Try again' : ''));
  const detail = $derived.by(() => {
    const d = detailLine(message, c.title);
    const norm = (x: string) => x.trim().replace(/[.…]+$/, '').toLowerCase();
    return button && norm(d) === norm(button) ? '' : d;
  });
</script>

{#snippet body()}
  <div class="text">
    <p class="title">{c.title}</p>
    {#if c.hint}<p class="hint">{c.hint}</p>{/if}
    {#if detail}<p class="message">{detail}</p>{/if}
  </div>
  {#if action || (onretry && !compact) || actions}
    <div class="actions">
      {#if action}
        {#if action.href}<Button size="sm" href={action.href}>{action.label}</Button>
        {:else if action.retry && onretry}<Button size="sm" onclick={onretry}>{action.label}</Button>
        {:else if action.report && report}<Button size="sm" onclick={() => api.open_report(report.run_id)}>{action.label}</Button>{/if}
      {:else if onretry && !compact}<Button size="sm" onclick={onretry}>Try again</Button>{/if}
      {@render actions?.()}
    </div>
  {/if}
{/snippet}

{#if compact}
  <div class="problem compact" role={alert ? 'alert' : undefined} data-kind={kind} data-note="problem">{@render body()}</div>
{:else}
  <Surface kind="card" tone="problem" role={alert ? 'alert' : undefined} data-kind={kind} data-note="problem">
    <div class="problem">{@render body()}</div>
  </Surface>
{/if}

<style>
  .problem { display: flex; gap: var(--s-3); align-items: flex-start; min-width: 0; }
  .compact { align-items: center; }
  .text { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 3px; }
  .title { color: var(--q-weak); font-weight: var(--fw-semi); }
  .compact .title { font-size: var(--fs-small); }
  .hint { color: var(--text); }
  .message { color: var(--text-muted); font-size: var(--fs-small); user-select: text; -webkit-user-select: text; }
  .compact .message { display: none; }
  .actions { display: flex; gap: var(--s-2); flex-shrink: 0; }
</style>
