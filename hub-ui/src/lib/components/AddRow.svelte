<script lang="ts">
  // Paste a Spotify or Qobuz playlist link → add_playlist (a network read) → the playlist it found as a card between
  // the field and the list (design system mockup design-system/playlists.html) → "Add to the list" appends the row.
  // The field and Add share one line (--h-btn); a note or a problem sits under it as a Hint or a compact ProblemCard
  // (a login the service needs: "Qobuz isn't connected." with Connect Qobuz →, unless the shell's banner says it already).
  // A block (Playlists' list head, Setup's first playlist): `draft` is the list it adds to (for the duplicate and
  // folder checks), `onadd` takes the found playlist and its folder name; the page decides what adding means
  // (Playlists: a row in the draft; Setup: saved at once). It answers whether the playlist went in: only then the
  // field and the found card clear, so a refused save keeps them for another try.
  import Button from './Button.svelte';
  import Cover from './Cover.svelte';
  import Hint from './Hint.svelte';
  import ProblemCard from './ProblemCard.svelte';
  import Surface from './Surface.svelte';
  import TextField from './TextField.svelte';
  import { api } from '../bridge/client';
  import type { AddedPlaylist, PlaylistService, ProblemKind } from '../bridge/types';
  import { networkReadsAllowed, readBlock } from '../stores/hub';
  import { bannersSaidInBody } from '../stores/shell';
  import { NOT_WHILE_SYNC } from '../copy';
  import { plural } from '../format';
  import { bannerSaysIt, folderProblem, hasLink, ownerText, type PlaylistRef } from './addRowModel';

  let { draft, onadd, filled = false }: {
    draft: PlaylistRef[]; onadd: (a: AddedPlaylist, folder: string) => boolean | Promise<boolean>;
    /** "Add to the list" is the screen's one filled button (Setup's first playlist, where adding is the step) */
    filled?: boolean;
  } = $props();

  const DUPLICATE = 'This playlist is already in your list.';
  /** answers whose message is the whole point (W2 "That isn't a Spotify or Qobuz playlist link…", W4 "Qobuz doesn't
   *  show this playlist…"): no headline of ours says more than the engine's sentence */
  const SAID_BY_MESSAGE = new Set<ProblemKind>(['refused', 'playlist_unreadable']);
  let url = $state('');
  let busy = $state(false);
  /** onadd runs (Setup saves at once): Add to the list waits */
  let adding = $state(false);
  let result = $state<AddedPlaylist | null>(null);
  let error = $state<{ kind: ProblemKind; message: string; service: PlaylistService | null } | null>(null);
  let note = $state<string | null>(null);
  let folder = $state('');
  const folderHint = $derived(result ? folderProblem(folder, draft) : null);

  async function add() {
    const u = url.trim();
    if (!u || busy) return;
    error = null; note = null; result = null;
    if (!$networkReadsAllowed) { note = NOT_WHILE_SYNC; return; }
    if (hasLink(draft, u)) { note = DUPLICATE; return; }
    busy = true;
    const r = await api.add_playlist(u);
    busy = false;
    if (!r.ok) {
      if (r.kind === 'sync_running') note = NOT_WHILE_SYNC;
      else error = { kind: r.kind, message: r.message, service: r.service ?? null };
      return;
    }
    if (hasLink(draft, r.link)) { note = DUPLICATE; return; }
    result = r;
    folder = r.suggested_folder;
  }
  async function keep() {
    if (!result || !result.readable || folderHint || adding) return;
    const kept = result;
    adding = true;
    const ok = await onadd(kept, folder);
    adding = false;
    // only the playlist that was added clears (a Cancel or a new check while it saved keeps what is there now)
    if (ok && result === kept) { result = null; url = ''; folder = ''; }
  }
  /** "Qobuz · Example Curator · 18 tracks": the service first, as in the list's rows; a part that isn't known is left
   *  out. */
  function foundLine(r: AddedPlaylist): string {
    const n = r.info?.track_count ?? r.tracks;
    return [r.service_name, r.info ? ownerText(r.info) : '', n == null ? '' : plural(n, 'track')].filter(Boolean)
      .join(' · ');
  }
  function cancel() { result = null; folder = ''; }
</script>

<div class="add" data-test="add-row">
  <div class="field">
    <TextField bind:value={url} placeholder="Paste a Spotify or Qobuz playlist link…" onenter={add} name="playlist-link" />
  </div>
  <Button {busy} disabled={!$networkReadsAllowed || !url.trim()} title={$networkReadsAllowed ? undefined : NOT_WHILE_SYNC}
    onclick={add} data-test="add-button">Add</Button>
</div>

{#if note}<Hint text={note} data-test="add-note" />{/if}
{#if error}
  <div data-test="add-problem">
    {#if SAID_BY_MESSAGE.has(error.kind) || bannerSaysIt(error, $readBlock, $bannersSaidInBody)}
      <!-- the engine's words are the answer (not a playlist link, a playlist the service won't show), so they are
           the line itself, whole: a compact card shows only its headline. Likewise a login the shell's banner is
           already asking for ("Qobuz isn't connected." + Connect Qobuz →): the sentence alone, no second button -->
      <Hint tone="problem" wrap text={error.message} />
    {:else}
      <ProblemCard alert compact kind={error.kind} message={error.message} service={error.service} onretry={add} />
    {/if}
  </div>
{/if}

{#if result}
  <Surface kind="card" tone={result.readable ? 'default' : 'problem'} data-test="add-result">
    <div class="found">
      <Cover url={result.info?.image_url ?? null} seed={result.link} size={40} />
      <div class="what">
        <span class="name">{result.info?.name ?? 'Unknown playlist'}</span>
        {#if foundLine(result)}<span class="muted">{foundLine(result)}</span>{/if}
        {#if result.readable}
          <Hint text="Discjockey can read this playlist" />
        {:else}
          <!-- the service's own words (the engine's hint), whole: they say what to do in that service -->
          <Hint tone="problem" wrap text={result.hint ?? result.info?.hint ?? ''} data-test="add-hint" />
        {/if}
      </div>
      <Button variant="link" muted size="sm" disabled={adding} onclick={cancel} data-test="add-cancel">Cancel</Button>
    </div>
    {#if result.readable}
      <div class="keep">
        <span class="flabel">Folder name</span>
        <div class="field">
          <TextField bind:value={folder} label="Folder name" invalid={!!folderHint} hint={folderHint ?? undefined}
            onenter={keep} name="new-folder" />
        </div>
        <Button variant={filled ? 'filled' : 'primary'} disabled={!!folderHint} busy={adding} busyLabel="Adding"
          onclick={keep} data-test="add-keep">Add to the list</Button>
      </div>
    {/if}
  </Surface>
{/if}

<style>
  .add { display: flex; gap: var(--s-2); align-items: flex-start; }
  .field { flex: 1; min-width: 0; }
  .found { display: flex; gap: var(--s-3); align-items: center; min-width: 0; }
  .what { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .name { color: var(--text-strong); font-weight: var(--fw-semi); overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
  .muted { color: var(--text-muted); font-size: var(--fs-small); }
  .keep { display: flex; gap: var(--s-2); align-items: flex-start; margin-top: var(--s-3); max-width: 560px; }
  .flabel { flex: none; line-height: var(--h-btn); color: var(--text-muted); font-size: var(--fs-small); }
</style>
