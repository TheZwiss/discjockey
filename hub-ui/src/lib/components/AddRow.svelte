<script lang="ts">
  // Paste a Spotify, Qobuz, SoundCloud or YouTube Music playlist link → add_playlist (a network read) → the playlist it found as a card between
  // the field and the list (design system mockup design-system/playlists.html) → "Add to the list" appends the row.
  // The field and Add share one line (--h-btn); a note or a problem sits under it as a Hint or a compact ProblemCard
  // (a login the service needs: "Qobuz isn't connected." with Connect Qobuz →, unless the shell's banner says it already).
  // A block (Playlists' list head, Setup's first playlist): `draft` is the list it adds to (for the duplicate and
  // folder checks), `onadd` takes the found playlist and its folder name; the page decides what adding means
  // (Playlists: a row in the draft; Setup: saved at once). It answers whether the playlist went in: only then the
  // field and the found card clear, so a refused save keeps them for another try.
  // The placeholder is "Paste a playlist link here" followed by the four services' logos in the user's order (sources
  // round problem 1), each with a Tip of its name; they are part of the placeholder, so they go once the field has
  // text, and the found card then shows the one service it recognised. The words sit where the input's own
  // placeholder would (the field's padding, its colour), and a click on them or a logo goes to the input.
  // A link the engine reads only once a Settings choice is on (`setting_off` with its `setting`: Liked music) gets
  // the "needs a setting" form: the playlist's fixed name, logo + "YouTube Music · yours", the yellow ! line, a Hint
  // and one primary action the caller names (`settingAction`: Playlists' "Turn on in Settings").
  // The normal found card leads its line with the service's logo (as the rows do) and says what reading it takes
  // (readLine: Liked music "Discjockey reads it through your YouTube login").
  // `check(link)` puts a link in the field and checks it, as a paste and Add would (the gallery's states).
  import Button from './Button.svelte';
  import Cover from './Cover.svelte';
  import Hint from './Hint.svelte';
  import ProblemCard from './ProblemCard.svelte';
  import ServiceMark from './ServiceMark.svelte';
  import StatusMark from './StatusMark.svelte';
  import Surface from './Surface.svelte';
  import TextField from './TextField.svelte';
  import { logoOf } from './serviceLogos';
  import { tip } from './tip';
  import { GUIDE_SERVICES } from './linkGuideModel';
  import { api } from '../bridge/client';
  import type { AddedPlaylist, PlaylistService, ProblemKind, SettingKey } from '../bridge/types';
  import { networkReadsAllowed, readBlock } from '../stores/hub';
  import { bannersSaidInBody } from '../stores/shell';
  import { NOT_WHILE_SYNC, PLAYLIST_SERVICE_NAMES } from '../copy';
  import { plural } from '../format';
  import { bannerSaysIt, folderProblem, hasLink, ownerText, readLine, settingForm, type PlaylistRef } from './addRowModel';

  let { draft, onadd, filled = false, settingAction }: {
    draft: PlaylistRef[]; onadd: (a: AddedPlaylist, folder: string) => boolean | Promise<boolean>;
    /** "Add to the list" is the screen's one filled button (Setup's first playlist, where adding is the step) */
    filled?: boolean;
    /** the "needs a setting" form's one action: its words and where it goes (Playlists: "Turn on in Settings");
     *  without one (Setup) the form's Hint says to turn it on in Settings after setup */
    settingAction?: { label: string; onclick: (setting: SettingKey) => void };
  } = $props();

  /** the field's name for VoiceOver, the four services in words (the logos say them to the eye) */
  const FIELD_LABEL = 'Paste a link from YouTube Music, SoundCloud, Spotify or Qobuz';
  const PLACEHOLDER = 'Paste a playlist link here';

  const DUPLICATE = 'This playlist is already in your list.';
  /** answers whose message is the whole point (W2 "That isn't a playlist link Discjockey can read…", W4 "SoundCloud
   *  doesn't show this playlist…"): no headline of ours says more than the engine's sentence */
  const SAID_BY_MESSAGE = new Set<ProblemKind>(['refused', 'playlist_unreadable']);
  let url = $state('');
  let busy = $state(false);
  /** onadd runs (Setup saves at once): Add to the list waits */
  let adding = $state(false);
  let result = $state<AddedPlaylist | null>(null);
  let error = $state<{ kind: ProblemKind; message: string; service: PlaylistService | null } | null>(null);
  let note = $state<string | null>(null);
  /** a link whose read needs a Settings choice that is off: the "needs a setting" form */
  let needs = $state<{ setting: SettingKey; link: string } | null>(null);
  const form = $derived(needs ? settingForm(needs.setting) : null);
  let fieldEl: HTMLElement | undefined = $state();
  function focusField() { fieldEl?.querySelector('input')?.focus(); }
  let folder = $state('');
  const folderHint = $derived(result ? folderProblem(folder, draft) : null);

  async function add() {
    const u = url.trim();
    if (!u || busy) return;
    error = null; note = null; result = null; needs = null;
    if (!$networkReadsAllowed) { note = NOT_WHILE_SYNC; return; }
    if (hasLink(draft, u)) { note = DUPLICATE; return; }
    busy = true;
    const r = await api.add_playlist(u);
    busy = false;
    if (!r.ok) {
      if (r.kind === 'sync_running') note = NOT_WHILE_SYNC;
      else if (r.kind === 'setting_off' && r.setting) needs = { setting: r.setting, link: u };
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
  function cancel() { result = null; folder = ''; needs = null; }
  /** a link in the field, checked at once (as a paste and Add) */
  export function check(link: string) { url = link; void add(); }
</script>

<div class="add" data-test="add-row">
  <div class="field" bind:this={fieldEl}>
    <TextField bind:value={url} label={FIELD_LABEL} onenter={add} name="playlist-link" />
    {#if !url}
      <!-- the placeholder: the words where the input's own would be, then the logos; the words let a click through
           to the input, a logo focuses it (its Tip names the service) -->
      <span class="ph" aria-hidden="true" data-test="add-placeholder">
        <span class="ph-words">{PLACEHOLDER}</span>
        <span class="ph-logos">
          {#each GUIDE_SERVICES as s (s)}
            <!-- svelte-ignore a11y_click_events_have_key_events, a11y_no_static_element_interactions -->
            <span class="ph-logo" use:tip={PLAYLIST_SERVICE_NAMES[s]} onclick={focusField}><ServiceMark
              service={logoOf(s)} label={PLAYLIST_SERVICE_NAMES[s]} /></span>
          {/each}
        </span>
      </span>
    {/if}
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

{#if needs && form}
  <Surface kind="card" data-test="add-needs-setting">
    <div class="found">
      <Cover url={null} seed={needs.link} size={40} />
      <div class="what">
        <span class="name">{form.name}</span>
        <span class="muted svc"><ServiceMark service={logoOf(form.service)} label={PLAYLIST_SERVICE_NAMES[form.service]} />{`${PLAYLIST_SERVICE_NAMES[form.service]} · ${form.owner}`}</span>
        <span class="off" data-test="add-needs-line"><StatusMark tone="warn" />{form.line}</span>
      </div>
      <Button variant="link" muted size="sm" onclick={cancel} data-test="add-cancel">Cancel</Button>
    </div>
    <div class="keep">
      <!-- no action (Setup has no way to Settings yet): the Hint says when and where instead, never a dead end -->
      <span class="why"><Hint text={settingAction ? form.hint : form.later} wrap data-test="add-needs-hint" /></span>
      {#if settingAction}
        <Button variant={filled ? 'filled' : 'primary'} onclick={() => needs && settingAction.onclick(needs.setting)}
          data-test="add-setting">{settingAction.label}</Button>
      {/if}
    </div>
  </Surface>
{/if}

{#if result}
  <Surface kind="card" tone={result.readable ? 'default' : 'problem'} data-test="add-result">
    <div class="found">
      <Cover url={result.info?.image_url ?? null} seed={result.link} size={40} />
      <div class="what">
        <span class="name">{result.info?.name ?? 'Unknown playlist'}</span>
        <span class="muted svc" data-test="add-found-line"><ServiceMark service={logoOf(result.service)}
          label={PLAYLIST_SERVICE_NAMES[result.service]} />{foundLine(result)}</span>
        {#if result.readable}
          <Hint text={readLine(result.link)} data-test="add-read-line" />
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
  .field { flex: 1; min-width: 0; position: relative; }
  /* over the input, in its padding (TextField's border + --s-3) and its placeholder colour, one line high */
  .ph { position: absolute; left: 0; top: 0; height: var(--h-btn); max-width: 100%; display: flex; align-items: center;
    gap: var(--s-2); padding: 0 calc(var(--s-3) + var(--bw)); pointer-events: none; white-space: nowrap;
    overflow: hidden; color: var(--text-label); font-size: var(--fs-body); }
  .ph-words { min-width: 0; overflow: hidden; text-overflow: ellipsis; }
  .ph-logos { flex: none; display: inline-flex; align-items: center; gap: 6px; }
  .ph-logo { display: inline-flex; pointer-events: auto; cursor: text; }
  .svc { display: inline-flex; align-items: center; gap: 6px; min-width: 0; }
  /* the 16 px ! mark, 4 px before its words: they start where the 14 px logo's line above starts (14 + 6) */
  .off { display: inline-flex; align-items: center; gap: 4px; font-size: var(--fs-small); color: var(--text-muted); }
  .why { flex: 1; min-width: 0; align-self: center; }
  .found { display: flex; gap: var(--s-3); align-items: center; min-width: 0; }
  .what { flex: 1; min-width: 0; display: flex; flex-direction: column; gap: 2px; }
  .name { color: var(--text-strong); font-weight: var(--fw-semi); overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; }
  .muted { color: var(--text-muted); font-size: var(--fs-small); }
  .keep { display: flex; gap: var(--s-2); align-items: flex-start; margin-top: var(--s-3); max-width: 560px; }
  .flabel { flex: none; line-height: var(--h-btn); color: var(--text-muted); font-size: var(--fs-small); }
</style>
