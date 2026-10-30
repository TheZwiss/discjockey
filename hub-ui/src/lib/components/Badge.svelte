<script lang="ts">
  // A short state or value in a quality colour, or `muted` (neutral: a name the user gave, kept as spelled, e.g. a
  // playlist in Library's Playlist column). `more` (a list's first name, e.g. the playlists holding a song): how many
  // others there are besides `text`, as "+n" after it in the label grey (none at 0), in the medium weight of a name;
  // such a badge fits its cell: the text gives way with "…", the "+n" never.
  // `quiet`: a state that has no badge yet, as words in the badge's place (Library's "Waiting" / "Switched off" for a
  // playlist song without a file): no outline, the muted grey at the small size and weight of a row's second words,
  // as the user would say it (no capitals), so it reads as "nothing to judge yet", quieter than any state badge.
  // `tip`: the house Tip on the badge itself (what the word means, or every name behind "+n"); `test`: its data-test.
  import type { Quality } from '../bridge/types';
  import { tip as tipAction, type TipParams } from './tip';
  let { tone = 'muted', text, more, tip = null, test }: { tone?: Quality | 'accent' | 'muted' | 'other' | 'quiet'; text: string;
    more?: number; tip?: TipParams; test?: string } = $props();
</script>

{#if more !== undefined}
  <span class="badge {tone} parts" use:tipAction={tip} data-test={test}><span class="text">{text}</span>{#if more > 0}<span
    class="more">+{more}</span>{/if}</span>
{:else}
  <span class="badge {tone}" use:tipAction={tip} data-test={test}>{text}</span>
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
  .quiet { padding: 0; border: 0; color: var(--text-muted); font-size: var(--fs-small); font-weight: normal; letter-spacing: 0; }
  /* a name, not a state: the medium weight and no tracking, so it reads as the user's own words and stays quieter than
     the quality badge beside it (at the states' bold it competed with it) */
  .parts { display: inline-flex; gap: var(--s-1); max-width: 100%; min-width: 0; vertical-align: middle;
    font-weight: var(--fw-medium); letter-spacing: 0; }
  .text { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .more { flex: none; color: var(--text-label); }
</style>
