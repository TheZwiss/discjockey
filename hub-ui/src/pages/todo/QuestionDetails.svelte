<script lang="ts">
  // "Is this the same song?" in the panel (plan library stage 4, 7.2, W8): a file of the user's own might be a playlist
  // song. The head is one card, labelled with the why ("Same title, different artist"): the playlist song and the
  // file side by side, line for line (title, artist, length, where), so the eye reads across; the line the why is
  // about is the one in full white. The file's column ends in its quality and ▶, the song's in its link to the
  // playlist service (the song has no file yet, it waits: D4). Under it the W8 note, yellow because the song waits.
  // The foot holds the two answers, Yes as the screen's one filled button. An answer is a write job ("answer"); the
  // finished job re-fetches the page, which goes on to the next question (keepSelection). A refusal ("changed": the
  // song isn't in a playlist any more) shows the backend's words in runJob's toast, and the re-fetch drops it.
  import type { QuestionItem } from '$lib/bridge/types';
  import { api, runJob } from '$lib/bridge/client';
  import { ExternalLink, NoteCard, PathText, QualityBadge, Surface, WriteButton } from '$lib/components';
  import { Panel } from '$lib/frames';
  import { compareLines, linkService } from './todoModel';
  import FilePlay from './FilePlay.svelte';

  let { item }: { item: QuestionItem } = $props();

  const p = $derived(item.pair);
  const lines = $derived(compareLines(p));
  const service = $derived(linkService(p.track.link));
  let busy = $state<'yes' | 'no' | null>(null);

  async function answer(same: boolean) {
    busy = same ? 'yes' : 'no';
    await runJob(api.answer_same_song(p.song_key, p.own_key, same));
    busy = null;
  }
</script>

{#snippet head()}
  <div class="details" data-test="question" data-key="{p.song_key}/{p.own_key}" data-why={p.why}>
    <Surface kind="card" data-test="question-compare">
      <!-- the why as the card's title, wrapping: a Surface label ends in "…" and this line must be read whole -->
      <h3 class="why">{item.detail}</h3>
      <div class="compare" role="table" aria-label="The playlist song beside your file">
        <div class="line caps" role="row">
          <span role="columnheader">Playlist song</span><span role="columnheader">Your file</span>
        </div>
        {#each lines as l (l.key)}
          <div class="line {l.key}" class:differs={l.differs} role="row" data-line={l.key}>
            <span class="v" role="cell" title={l.song}>{l.song}</span>
            <!-- a place breaks after a "/" only -->
            <span class="v" role="cell" title={l.fileTitle ?? l.file}><PathText path={l.file} /></span>
          </div>
        {/each}
        <div class="line ends" role="row">
          <span class="v" role="cell">{#if service && p.track.link}<ExternalLink href={p.track.link}
            label="Open in {service}" />{/if}</span>
          <span class="v file" role="cell"><QualityBadge quality={p.file.quality} label={p.file.quality_label} />
            <FilePlay files={[p.file]} file={p.file} test="question-play" /></span>
        </div>
      </div>
    </Surface>
    <NoteCard tone="warn" data-test="question-note">Until you answer, Discjockey doesn't download this song.</NoteCard>
  </div>
{/snippet}

{#snippet foot()}
  <div class="answers">
    <WriteButton variant="filled" wide busy={busy === 'yes'} disabled={busy === 'no'} onclick={() => answer(true)}
      data-test="question-yes">Yes, it's the same song</WriteButton>
    <WriteButton variant="secondary" wide busy={busy === 'no'} disabled={busy === 'yes'} onclick={() => answer(false)}
      data-test="question-no">No, keep them apart</WriteButton>
  </div>
{/snippet}

<Panel {head} {foot} />

<style>
  .details { display: flex; flex-direction: column; gap: var(--s-3); min-width: 0; }
  .why { margin: 0 0 var(--s-3); font-size: var(--fs-body); font-weight: var(--fw-semi); color: var(--text-strong); }
  /* two equal columns, one row per line, so the song's value and the file's sit on one baseline even when one wraps */
  .compare { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); column-gap: var(--s-4);
    row-gap: var(--s-1); min-width: 0; }
  .line { display: contents; }
  .caps span { font-size: var(--fs-label); text-transform: uppercase; letter-spacing: .7px; color: var(--text-label);
    padding-bottom: var(--s-1); }
  .v { min-width: 0; font-size: var(--fs-small); color: var(--text-muted); overflow-wrap: break-word;
    word-break: normal; }
  /* names and places are read whole, up to two lines (a place's end is what tells folders apart); the full value is
     the tooltip */
  .title .v, .artist .v, .where .v { display: -webkit-box; -webkit-box-orient: vertical; -webkit-line-clamp: 2;
    line-clamp: 2; overflow: hidden; }
  .title .v, .artist .v { font-size: var(--fs-body); color: var(--text); }
  .length .v { font-variant-numeric: tabular-nums; }
  /* the line the why is about is the only one at full strength, so the difference is what the eye lands on */
  .differs .v { color: var(--text-strong); font-weight: var(--fw-semi); }
  .ends .v { display: flex; align-items: center; gap: var(--s-2); min-height: var(--h-ctl-sm); margin-top: var(--s-2); }
  .ends .file { justify-content: space-between; }
  .answers { display: flex; flex-direction: column; gap: var(--s-2); }
</style>
