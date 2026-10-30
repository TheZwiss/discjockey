<script lang="ts">
  // A short state or value in a quality colour, or `muted` (neutral: a name the user gave, kept as spelled, e.g. a
  // playlist in Library's Playlist column). `more` (a list's first name, e.g. the playlists holding a song): how many
  // others there are besides `text`, as "+n" after it in the label grey (none at 0), in the medium weight of a name;
  // such a badge fits its cell: the text gives way with "…", the "+n" never.
  import type { Quality } from '../bridge/types';
  let { tone = 'muted', text, more }: { tone?: Quality | 'accent' | 'muted' | 'other'; text: string; more?: number } = $props();
</script>

{#if more !== undefined}
  <span class="badge {tone} parts"><span class="text">{text}</span>{#if more > 0}<span class="more">+{more}</span>{/if}</span>
{:else}
  <span class="badge {tone}">{text}</span>
{/if}

<style>
  .badge {
    display: inline-block; font-size: var(--fs-label); font-weight: var(--fw-bold); line-height: 1.35;
    padding: 1px 6px; border-radius: var(--r-badge); border: var(--bw) solid var(--q-other-line);
    color: var(--q-other); white-space: nowrap; letter-spacing: .2px; font-variant-numeric: tabular-nums;
    user-select: none; -webkit-user-select: none;
  }
  .lossless { color: var(--q-lossless); border-color: var(--q-lossless-line); }
  .good_lossy { color: var(--q-good); border-color: var(--q-good-line); }
  .weak, .missing { color: var(--q-weak); border-color: var(--q-weak-line); }
  .fake { color: var(--q-fake); border-color: var(--q-fake-line); }
  .accent { color: var(--accent-text); border-color: var(--accent-line); }
  .muted { color: var(--text-muted); border-color: var(--line-control); }
  /* a name, not a state: the medium weight and no tracking, so it reads as the user's own words and stays quieter than
     the quality badge beside it (at the states' bold it competed with it) */
  .parts { display: inline-flex; gap: var(--s-1); max-width: 100%; min-width: 0; vertical-align: middle;
    font-weight: var(--fw-medium); letter-spacing: 0; }
  .text { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .more { flex: none; color: var(--text-label); }
</style>
