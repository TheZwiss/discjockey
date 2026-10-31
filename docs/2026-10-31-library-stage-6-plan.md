# Library stage 6 "SoundCloud and YouTube Music playlists" — plan

Spec: `docs/2026-10-23-library-and-sources-design.md` §3 item 5, §4 row 6, §9 (all; this stage is §9.4 and §9.5),
§12 ("a source can't read a playlist"), §13 ("Sources"). Orchestration: `docs/2026-10-23-library-and-sources-orchestration.md`.
Builds on stage 3 (`docs/2026-10-24-library-stage-3-plan.md`: the source interface, tokens, linking, the exact
Qobuz id). Stage branch: `feat/library-6-sources`, off `main`.

**Goal:** SoundCloud sets and likes and YouTube Music playlists work in `playlists.txt` and on the Playlists page;
their titles are split into artist and title; each track is looked for on Qobuz by name first, then the playlist's
own upload (SoundCloud: its free download first), then the other fallbacks.

## Questions for the user

1. **YouTube Music "Liked music".** Reading it needs the user's YouTube login (the browser cookies the Premium
   downloads use), and logged-in reads of a whole list are the kind of traffic that brings YouTube's bot checks onto
   that account. The plan leaves it out: an `LM` link is recognised and answered with W17 ("add the songs to a
   playlist"). If the user wants it, it becomes a follow-up (issue), not part of this stage.

Nothing else is open; every other choice is decided below with its reason.

## UI changes needing a mockup

None. Every visible change puts the new services into existing patterns: two more service logos (already drawn
by stage 5's `ServiceMark`, coloured, unchanged), the words of the add field, empty state, errors and Setup's
playlist step, "Open in SoundCloud" / "Open in YouTube Music" on a track. No block, layout or flow changes.

## Groups that can run without the user

All of them. Groups 1–5 are engine and bridge; group 6 (UI build + shots) changes only words, type unions and the
logo mapping, so it waits for no mockup. The user is needed only for the live check at the end.

---

## Global constraints

- **Reads are not downloads.** Reading a SoundCloud or YouTube Music playlist uses no `Pacer`, no `Budget`, no usage
  row and never counts toward an auto-stop or an account's daily limit (as Qobuz reads, spec §9.3). Requests are
  sequential, one reader per service per read, so a read is a handful of requests (SoundCloud: 1 + ⌈n/50⌉ per set,
  1 + ⌈n/200⌉ per likes list; YouTube: one page per 100 entries).
- **Reads are anonymous.** No browser cookies for any read, with one exception: a `you/likes` link (D4) with the
  SoundCloud login set up. YouTube Music reads never use the YouTube login (protects the Premium account; Q1).
- **yt-dlp is imported lazily** in the new source modules (inside `open` / the reader), never at module level:
  `sources` is imported by `config` and `playlists_file`, which must stay cheap and must not import yt-dlp before
  `tools.activate()` (CLAUDE.md, `__main__.py`). A test pins that `import discjockey.sources` and `recognise` leave
  `yt_dlp` out of `sys.modules` (*check first:* how `conftest.py` stubs yt-dlp, and write the test so it holds).
- **The download protection is untouched:** every download the new step makes goes through `Acquirer._try` and the
  existing account rules (pacing between account requests, the format listing as a logged-in request, the daily
  limits, `MISSES_PER_TRACK`, the waits of spec sources-and-limits §4).
- **`planner.py` and `hub/views.py` stay pure; only `db.py` writes SQL.** No schema step: tokens and `song_ids`
  already take any service (stage 3 I3); `playlist_reads.service` is free text.
- **Tests are offline:** recorded SoundCloud API answers and yt-dlp info dicts as JSON fixtures, trimmed to the
  fields used, with made-up ids and names (`Example Artist`, `example-label`, SoundCloud ids like `900000101`,
  YouTube ids like `EXAMPLEid01`). **Public repo:** `scripts/check_public.sh` before every commit.

## Decided here (with reasons)

- **D1. Service keys** `soundcloud` and `youtube_music`, the keys the download side already uses (`SOURCE_NAMES`,
  `Candidate.source`). So a track token `soundcloud:900000101` is the same string as that upload's candidate key,
  and a "Wrong song?" rejection of the upload also skips it as the exact upload (D7). Playlist tokens use the
  service's playlist id (D3, D5); they never meet candidate keys.
- **D2. One title splitter for both services** (`discjockey/titles.py`, pure, I2). It is applied when a source parses
  an entry, so everything downstream (linking, Qobuz search, file names `Artist - Title`) sees clean names.
- **D3. SoundCloud playlist ids are the link's path**, lowercased: `user/sets/slug`, `user/sets/slug/s-token` (a
  private set's share link), `user/likes`, `you/likes`. *Why:* `recognise` is local (no network), and the numeric
  set id isn't in the link. Canonical link `https://soundcloud.com/{id}`. A `/` in a ref is safe: refs reach routes
  only through `encodeURIComponent` (`hub-ui/src/lib/router.ts`).
- **D4. Likes.** `soundcloud.com/<user>/likes` is public: read anonymously. `soundcloud.com/you/likes` (what the
  SoundCloud site shows for one's own likes) needs to know who "you" is: when pasted on the Playlists page,
  `expand` (I4) resolves it once through the SoundCloud browser login (Settings' SoundCloud Go+ account) to
  `<permalink>/likes` and stores that, so later reads need no login. A `you/likes` line typed into `playlists.txt` is
  read through the login each time; without a login it answers W8. *Why:* this is the spec's "likes when logged in
  through the browser, as the fallback is", with cookies used once instead of on every sync.
- **D5. YouTube Music playlist ids are the `list=` id**, case kept. Accepted: `music.youtube.com/playlist?list=ID`,
  `music.youtube.com/browse/VL<ID>`, and `www.`/`m.`/bare `youtube.com/playlist?list=ID` and `…/watch?v=…&list=ID`
  (any other query keys, like `si=`, ignored). Canonical link `https://music.youtube.com/playlist?list={id}`. *Why
  accept youtube.com links:* the same list, the same reader; a DJ who copies it from the YouTube site gets the same
  result. Ids `LM`, `LL`, `WL` and mixes (`RD…` except the curated `RDCLAK5uy_…`) are recognised but refused at
  read time without a request (W17, W18): they are personal or change on every play.
- **D6. YouTube Music reads are flat** (`extract_flat="in_playlist"`, one yt-dlp call, no request per track).
  Researched against yt-dlp 2026.10.21 (the project's): yt-dlp reads `music.youtube.com` playlists through the
  `www.youtube.com` playlist page ("YouTube Music is not directly supported. Redirecting…"), and a flat entry carries
  `id`, `title`, `duration` (whole seconds), `channel`/`uploader`, `url`, `thumbnails` — no artist, album or "song"
  flag. A song entry (an album playlist `OLAK5uy_…`, or a song added from YTM) has the bare song title and the
  artist as `channel` ("One More Time", channel "Daft Punk"); a video entry has "Artist - Title (Official Video)" and
  the uploader. So the splitter's own rule tells them apart: no dash → the channel is the artist (the spec's "song
  carries artist and title"); a dash → split (the spec's "video is split like a SoundCloud title"). Album stays empty
  (D10 fills tags from the Qobuz match). *Why not a full read per entry:* one watch-page request per track, hundreds
  per playlist on every sync, anonymous: slow and the surest way into YouTube's bot check.
- **D7. The playlist's own upload** (spec §9.4/§9.5 "then the track itself"). The planner carries the first fetched
  SoundCloud / YouTube Music track that resolved to a song (`_Wanted.upload`, like stage 3's `_Wanted.qobuz`) to the
  action (`Action.upload`), and the acquirer tries it right after Qobuz and before the fallback search (I6). *Why
  before the search, even when a name match elsewhere would rank higher (spec sources-and-limits §2):* it is
  certainly the right version (edits, bootlegs and premieres are often only there), the spec orders it so, and the
  existing upgrade check (`_better_stream`, `lossless_only`) later replaces a stream below ~256 kbps when an account
  or Qobuz has better.
- **D8. Track links.** `TRACK_LINKS["youtube_music"] = "https://music.youtube.com/watch?v={id}"`;
  `TRACK_LINKS["soundcloud"] = "https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/{id}"` (the
  SoundCloud player page, derivable from the id). A fetched SoundCloud track passes its `permalink_url` as `link`, so
  within a read (stage 3 D5) "Open in SoundCloud" opens the real page; the player link covers views without a read.
  *Why not store permalinks:* it needs a schema step for a link the player page already gives. Closes issue 26's
  first point.
- **D9. SoundCloud's own metadata wins where it exists.** A track's `publisher_metadata` (label-distributed uploads)
  gives `artist`, `isrc` and `album_title`; then the ISRC links the song (§9.2 step 2) and the Qobuz ISRC search
  runs. `policy` `BLOCK` (not playable here) → `streamable=False` (no exact try); `SNIP` (Go+ only: 30 s for
  others) → `account_only=True` (I1): the exact try only through the SoundCloud account, never free, because a free
  try downloads a 30 s preview that `make_ready` rejects and `_try` records the upload as rejected for good. Length:
  `full_duration`, else `duration` (a SNIP's `duration` is the preview's).
- **D10. Album fallback in tags:** `make_ready` writes `track.album or cand.album`. YouTube Music tracks have no
  album (D6), SoundCloud ones mostly none; a Qobuz match knows it.
- **D11. Service-neutral words come from the registry:** `sources.service_list()` → "Spotify, Qobuz, SoundCloud or
  YouTube Music" (registry order), used by W1, W2 and the API's line check, so a later service changes no sentence.

## Review focus (per-group review and the stage review)

1. No read touches a pacer, budget, usage row or auto-stop; no read except `you/likes` uses cookies.
2. The exact upload is tried once, after Qobuz, before the fallback search, through `_try` and the account rules;
   a SNIP upload is never tried free; a failure falls through to the usual chain without retrying that upload.
3. The splitter's pinned cases (I2) and that both sources use it.
4. Spotify and Qobuz read, plan and save exactly as before (stage 3's tests untouched).
5. `import discjockey.sources` doesn't import yt-dlp; bridge methods never reject; every error names its service.

---

## Interfaces (fixed here; groups build against them)

### I1. Records — `models.py` (group 1)

- `SERVICE_NAMES` gains `"soundcloud": "SoundCloud"`, `"youtube_music": "YouTube Music"` (registry order:
  spotify, qobuz, soundcloud, youtube_music). `TRACK_LINKS` gains D8's two patterns.
- `SourceTrack` gains, last, `account_only: bool = False` (D9). Field order otherwise unchanged.
- `Action` gains `upload: SourceTrack | None = None` (I5).

Tests pin: the two new links; a SoundCloud track with an explicit `link` keeps it.

### I2. The title splitter — `discjockey/titles.py` (group 1, new, pure)

```python
def split_title(title: str, uploader: str, artist: str | None = None) -> tuple[tuple[str, ...], str]
def clean_uploader(name: str) -> str
```

Returns (artists, title). `artist`: a known artist (SoundCloud `publisher_metadata.artist`); `uploader`: the
SoundCloud user's name or the YouTube channel. Rules, in order:

1. **Clean:** NFKC; drop emoji and other pictographs (Unicode `So`/`Sk` symbols and variation selectors), keep
   letters, digits and punctuation of any script; collapse spaces. If nothing is left, the original title stays.
2. **Leading tags dropped:** `PREMIERE:`, `Premiere -`, `[Premiere]`, `(Premiere)`, `Premiere |`, any case; also
   `FREE DL:` / `[FREE DL]` at the start.
3. **Tags dropped anywhere** as a whole bracket (`()`, `[]`, any case): `free dl`, `free download`, `free`, `premiere`,
   `out now`, `official video`, `official audio`, `official music video`, `official visualizer`, `visualizer`,
   `lyrics`, `lyric video`, `audio`, `hq`, `hd`, `4k`, and a bracket equal to the uploader's name (a label's own tag:
   "[Example Records]"). Remix, edit, mix, bootleg, VIP, version and feat. brackets **stay** ("Title (Example Remix)").
4. **Pipe tail:** from the first ` | ` on, everything is dropped when text remains before it ("Title | Genre | Label").
5. **Split** at the first spaced dash (` - `, ` – `, ` — `; never an unspaced one: "Jay-Z", "AC-DC"). With two or more
   spaced dashes and the first part equal (normalised) to the uploader, the first part is dropped first
   ("Example Records - Artist - Title"). Left = artists, right = title.
6. **No dash:** the artist is `artist` when given, else `clean_uploader(uploader)`; the title is the whole cleaned
   title. With `artist` given and the title starting with `"{artist} - "`, that prefix is dropped (rule 5 covers it).
7. **Artists:** the artist part is split at `feat.`, `ft.`, `featuring` (with or without brackets) and at `, ` and a
   lowercase ` x `; ` & `, ` and `, ` vs ` stay inside one artist ("Chase & Status", "Above & Beyond" are bands).
   A `feat.` part inside the title moves to the artists. Empty artists → `()`.
8. `clean_uploader`: strips a trailing ` - Topic` and a trailing `VEVO`, and spaces.

Pinned cases (`tests/test_titles.py`, each a row of a parametrised table): no dash (uploader is the artist); several
dashes ("Artist - Title - Extended Mix" → title "Title - Extended Mix"; the label-prefix case of rule 5); a label
uploader "Example Records" with "Artist - Title" (the artist from the title, not the label) and without a dash (the
label stays the artist: a known limit); `[FREE DL]`, `(Free Download)`, `(Premiere)`, `PREMIERE: Artist - Title`,
`Premiere | Artist - Title`; emoji before, inside and after, and a title of emoji only; "Artist - Title (Example
Remix)" keeps the remix; "Artist feat. Other - Title" and "Artist - Title (feat. Other)" → `("Artist", "Other")`;
"Chase & Status - Title" one artist; "Artist x Other - Title" two; "Lil Nas X - Title" one; "Jay-Z - Title"; en and
em dashes; the NCS pipe tail ("Artist - Title | Genre | NCS - Copyright Free Music"); `" - Topic"` and `VEVO`
uploaders; a non-Latin title; a given `artist` with and without the prefix in the title.

### I3. The source modules (group 2: `sources/soundcloud.py`; group 3: `sources/youtube_music.py`)

Both implement stage 3's interface exactly (`sources/__init__.py` docstring): `SERVICE`, `recognise`,
`canonical_link`, `login_state`, `open` → a reader with `want_info`, `fetch(line)`, `info(playlist_id)`, `close`; and
`UNREADABLE_HINT` (`hub/api.add_playlist` reads it). `login_state` returns `LoginState("not_needed")` (I4): neither
service needs a login to read. `fetch` fills `FetchedPlaylist.info` from its first answer when `want_info` is set
(as Qobuz does), so the hub needs no second request.

### I4. Registry and base — `sources/base.py`, `sources/__init__.py` (group 1)

- `LoginState.state`: `"ok" | "missing" | "not_needed"`. `sources.read` and the two callers in `hub/api.py`
  (`_logins`, `add_playlist`) treat anything but `"missing"` as connected. Tests: a `not_needed` service never raises
  `not_set_up`; `_logins` lists it `connected: true`.
- `SOURCES` gains `soundcloud` and `youtube_music` (one line each, added by groups 2 and 3).
- `service_list() -> str` (D11): the registry's `SERVICE_NAMES`, "A, B, C or D".
- `expand(link, paths, token) -> str`: a source module may define `expand(link, paths, token) -> str` (network
  allowed; raises `SourceError`); it returns the link unchanged when the link is not its own. `sources.expand` does
  not go through `recognise` (a short link has no id): it asks every source that defines `expand`, in registry order,
  and the first that changes the link wins; none → the link unchanged. Only `hub/api.add_playlist` calls it, before
  `clean_link` (`link = clean_link(expand(url.strip()))`). `recognise` stays strict, so a short link written into
  `playlists.txt` is still refused (W2). SoundCloud uses it (D4 and short links, group 2); nothing else does.
- Words W1, W2 and `hub/api.py`'s line check (`This is not a … playlist link`) use `service_list()`.

### I5. The upload on actions — `planner.py`, `models.Action` (group 4)

`_Wanted.upload: SourceTrack | None` — the first fetched track (playlist order) of service `soundcloud` or
`youtube_music` that resolved to the song and is `streamable`. `plan`'s `act` sets `upload=w.upload` for `acquire`
and `upgrade` (not `adopt_bought`), beside `qobuz_id`. Same reason as stage 3 I5: only this read says the upload is
there now. Linking (§9.2) needs no change: tracks without ISRC already link by normalised artist, title and length
±3 s (`_resolve`, `_song_name`); the tests below pin it for the new services.

Tests pin (`tests/test_planner.py`): a SoundCloud track "Example Artist - Example Title [FREE DL]" (split by the
source) and the Spotify track of the same song and length ±2 s → one song, the second token in `aliases`; at 3.1 s
two songs; a SoundCloud track with a publisher ISRC links by ISRC; a YouTube Music song entry links to a Qobuz track
by name; `upload` is the first streamable SoundCloud/YTM track, a `BLOCK` one gives none, a Spotify-first song with a
later SoundCloud track still gets that upload; Spotify/Qobuz-only input plans exactly as before.

### I6. The exact-upload step — `acquire.py`, `execute.py` (group 4)

`Acquirer.acquire(..., upload: SourceTrack | None = None)`. With `upload` set, after the Qobuz steps (which keep
their own `exact` id and name/ISRC search) and before `_fallback`, when `self.fallback` is set:

1. The candidate: `Candidate(upload.service, upload.id, upload.title, " ".join(upload.artists),
   upload.duration_ms / 1000, url=upload.link or stream_url(...))`. Skipped when its key is in `skip`. It is not run
   through `fallback_match` (it is the song's own upload) but `make_ready`'s length check still applies.
2. **SoundCloud, free download first:** `fallback.free_downloads([c])`; a `direct` offer is tried first
   (`replace(c, direct=True)`, `how="upload"`); every offer (gate links too) lands in `res.free_downloads` as the
   fallback step records them today.
3. **The stream:** through the account when its service is in `_usable()` and the premium check passes (the same
   pacing and `premium()` listing `_fallback` uses for an account candidate); a usable account that is used up or
   paused today makes the track wait (`queued`, the account's `why_exhausted()`), as §4 does for a match that needs
   it; else the free stream — **except** an `account_only` upload, which is skipped without the account. `how="upload"`.
4. Ready → done. A failed try adds `c.key` to `skip` (no second download in the search that follows), and `_try`
   records rejections exactly as for a searched candidate. Then `_fallback` as today.
5. **Upgrade checks** (`lossless_only`): the upload's direct free download joins the originals step (SoundCloud
   only), and `_better_stream` considers the upload as an account candidate first. *Check first:* how `found`
   ("cands", "downloads") feeds `_better_stream`, and add the upload there rather than searching again.

`how="upload"` is a new `SourceChosen.how` (events) — *check first* where `how` is worded (`views.py`, hub-ui
`cardState.ts`); group 4 emits it, groups 5/6 word it (W20). `execute.py`'s two `acquire` calls pass
`upload=a.upload`. D10's album fallback is in `make_ready`.

Tests pin (`tests/test_acquire.py`, fakes): Qobuz first, then the upload, no fallback search when it succeeds; a
direct free download before the stream; a gate offer recorded and the stream taken; SoundCloud account usable →
account listing with its pause, used up → `queued`; an `account_only` upload without the account → no download
of it, the search follows; a failed upload → the search runs and doesn't download it again; a rejected upload key
→ not tried; `upload=None` → today's behaviour (existing tests unchanged); D10's album from the candidate.

### I7. Bridge changes (group 5)

All in `docs/hub-bridge-contract.md`, `types.ts`, `contract.ts`, the fake backend, same commit:

- `PlaylistService` (types.ts) and every service field (`service`, `problem_service`, `services[].service`, the
  error envelope's `service`): `'spotify' | 'qobuz' | 'soundcloud' | 'youtube_music'`.
- `add_playlist`: `sources.expand` first (I4); an `expand` failure answers `ok: false` with its kind and `service`.
- `read_status.services`: SoundCloud and YouTube Music are listed `connected: true` (not_needed).
- `SourceChosen.how` may be `"upload"` (W20).
- Fake backend: a SoundCloud set row (`https://soundcloud.com/example-label/sets/example-set`, owner "Example
  Label"), a SoundCloud likes row ("Example DJ's likes"), a YouTube Music row (`…playlist?list=PLEXAMPLE0001`,
  owner "Example Channel"); a track of each with "Open in SoundCloud" / "Open in YouTube Music"; scenarios
  `soundcloud_unreadable` (add answers W5) and `youtube_mix_refused` (add answers W18). The fake's own refused
  message becomes W2.

### I8. Binding words

| Id | Where | Words |
|----|-------|-------|
| W1 | `config.parse_playlists` | `playlists.txt line {n}: this is not a playlist link Discjockey can read ({service_list}): {ref}` |
| W2 | `playlists_file.clean_link` | `That isn't a playlist link Discjockey can read. Open the playlist in {service_list}, choose Share, then Copy link, and paste it here.` |
| W3 | SoundCloud `UNREADABLE_HINT` | `Make it public in SoundCloud, or use its private share link.` |
| W4 | SoundCloud `fetch`, unreadable | `playlists.txt line {n} ({folder}): SoundCloud doesn't show this playlist. It may be private or removed; for a private set, use its private share link. Check the link, or put # in front of the line.` |
| W5 | SoundCloud `info`, unreadable | `SoundCloud doesn't show this playlist. It may be private or removed; for a private set, use its private share link.` |
| W6 | SoundCloud not answering | `SoundCloud is not responding ({problem}). Try again later.` (kind `offline`) |
| W7 | SoundCloud too many requests | `SoundCloud asked Discjockey to slow down. Try again in an hour.` (kind `offline`) |
| W8 | `you/likes` without a SoundCloud login | `To read your own likes, use your profile's likes link: on SoundCloud, open your profile, click Likes and copy the address (soundcloud.com/your-name/likes).` (kind `playlist_unreadable`) |
| W9 | `you/likes`, login not accepted | `SoundCloud didn't accept the login from {browser}. Log in to SoundCloud there, or use your profile's likes link (soundcloud.com/your-name/likes).` (kind `login_expired`, service `soundcloud`) |
| W10 | likes playlist name | `{username}'s likes` |
| W11 | skipped SoundCloud entry | `A track SoundCloud no longer shows (ID {id})` |
| W12 | YouTube Music `UNREADABLE_HINT` | `Set it to public or unlisted in YouTube Music.` |
| W13 | YouTube Music `fetch`, unreadable | `playlists.txt line {n} ({folder}): YouTube Music doesn't show this playlist. It must be public or unlisted. Check the link, or put # in front of the line.` |
| W14 | YouTube Music `info`, unreadable | `YouTube Music doesn't show this playlist. It must be public or unlisted. Check the link.` |
| W15 | YouTube Music not answering | `YouTube Music is not responding ({problem}). Try again later.` (kind `offline`) |
| W16 | YouTube bot check / too many requests | `YouTube Music asked Discjockey to slow down. Try again in an hour.` (kind `offline`) |
| W17 | `LM`, `LL`, `WL` ids | `Discjockey can't read your liked songs or Watch later. Add the songs to a playlist, set it to public or unlisted, and paste that link.` (kind `playlist_unreadable`) |
| W18 | a mix (`RD…`) | `This is a YouTube mix, which changes every time it plays. Save its songs to a playlist and paste that link.` (kind `playlist_unreadable`) |
| W19 | skipped YouTube entry | `{title} (removed from YouTube)` (a `[Deleted video]` / `[Private video]` entry or one without an id or length) |
| W20 | how a source was chosen | `the playlist's own upload` (next to "exact Qobuz track", "ISRC", "name") |
| W21 | AddRow placeholder | `Paste a Spotify, Qobuz, SoundCloud or YouTube Music link…`; if it is cut at 1100 px: `Paste a playlist link…` (group 6b decides by the shot) |
| W22 | Playlists empty state body | `Paste a playlist link from Spotify, Qobuz, SoundCloud or YouTube Music above.` |
| W23 | Setup playlists card label | `Add a playlist` (the step's example links name all four services) |

The `{problem}` in W6/W15 is our own words or the error's type name, never a library's text (it may hold a link;
as `sources/qobuz._problem`). Console and hub use the same engine words; the hub's cards pick their title by `kind`
and `service` (`copy.ts`).

---

## Task groups

| Group | Model | Area | Size (changed lines) | Estimate (tokens) | Depends on |
|-------|-------|------|----------------------|-------------------|------------|
| 1 Splitter and registry | Sonnet | `titles.py` new, `models.py`, `sources/base.py`, `sources/__init__.py`, `config.py`, `playlists_file.py`, `hub/api.py` (words, not_needed) | ~450 | 150–200k | — |
| 2 SoundCloud source | Sonnet | `sources/soundcloud.py` new, fixtures, tests | ~600 | 200–280k | 1 |
| 3 YouTube Music source | Sonnet | `sources/youtube_music.py` new, fixtures, tests | ~450 | 160–220k | 1 |
| 4 Upload step | Opus | `planner.py`, `models.Action`, `acquire.py`, `execute.py` | ~400 | 220–300k | 1 (tests use 2's parse output shape only through `SourceTrack`) |
| 5 Bridge and docs | Sonnet | `hub/api.py`, `hub/views.py`, `events.py`, contract, `types.ts`, `contract.ts`, fake; README, CLAUDE.md, `setup_cmd.py`, `docs/issues.md` | ~500 | 180–250k | 2, 3, 4 |
| 6a UI build | Sonnet | `hub-ui/src` words, unions, logo mapping (no shots) | ~200 | 120–160k | 5 |
| 6b UI shots | Opus | shots of the touched pages, fixes only what they show | small | 120–180k | 6a |

Plus a Sonnet review per group (110–140k each) and one Opus stage review (~150k). Order: 1 → 2 → 3 → 4 → 5 → 6a →
6b (2, 3 and 4 share no file and may run side by side if two agents are allowed). Every brief carries the ~80
tool-call hard stop; 6a takes no screenshots (orchestration §5).

---

## Group 1 — Splitter and registry (Sonnet)

**Read list:** this plan's Global constraints, D1, D2, D8, D11, I1, I2, I4, I8 (W1, W2); `discjockey/models.py`
lines 1–125; `discjockey/sources/__init__.py`, `sources/base.py` (whole, ~140 lines); `discjockey/config.py`
around line 54; `discjockey/playlists_file.py` lines 55–70; `discjockey/hub/api.py` lines 387–400, 1105–1128 and
`grep -n "not a Spotify" discjockey/hub/api.py`; `discjockey/matching.py` (outline, `normalize`, `_DASH`); `tests/`
`grep -ln "LoginState\|recognise" tests` and their `def test_` lines.

Tasks:
1. **1.1 Records** (`models.py`): I1 (not `Action.upload`: group 4). Tests: `tests/test_models.py`.
2. **1.2 The splitter** (`titles.py`): I2 with its pinned table (`tests/test_titles.py`). Reuse `matching.normalize`
   for the "equal to the uploader" comparisons; do not change `matching.py`.
3. **1.3 Registry** (`base.py`, `__init__.py`): `not_needed`, `service_list`, `expand` (I4); the yt-dlp-free import
   test (Global constraints). Tests: `tests/test_sources.py` (or the registry's existing test file).
4. **1.4 Words** (`config.py`, `playlists_file.py`, `hub/api.py`): W1, W2, the line check; `_logins` and
   `add_playlist` take `not_needed` as connected and call `sources.expand`. Tests: `tests/test_config.py`,
   `tests/test_playlists_file.py`, `tests/test_hub_api_playlists.py` (Spotify/Qobuz answers unchanged but the words).

Checks: those files while working; the full suite at the end (`uv run pytest -q | tail -3`).

## Group 2 — SoundCloud source (Sonnet)

**Read list:** Global constraints, D1, D3, D4, D8, D9, I2, I3, I4, I8 (W3–W11); `discjockey/sources/qobuz.py`
(whole: the model to follow); `discjockey/fallback.py` lines 1–60 and `_soundcloud_track`, `_browser_cookies`;
`discjockey/accounts.py` (`LOGIN_COOKIES`, `ytdlp_login`, `signal_of`, `check_message`'s cookie words);
`discjockey/settings.py` (`grep -n "def load\|accounts"`); in the project's yt-dlp
(`.venv/lib/python3.12/site-packages/yt_dlp/extractor/soundcloud.py`): `SoundcloudBaseIE` lines 82–230 (client id,
`_call_api`, the OAuth header from the `oauth_token` cookie), `_extract_set` 820–870, `SoundcloudSetIE`,
`SoundcloudPagedPlaylistBaseIE._entries` 982–1060 (paging, `next_href`, impersonation), `SoundcloudUserIE`.

Researched (yt-dlp 2026.10.21, one public set and one public likes list): a flat set read gives entries with only
`id` and `url` (no title, length or user), and SoundCloud's playlist answer holds full track objects for the first
few tracks and stubs (`id` only) for the rest. So the reader asks SoundCloud's API itself through yt-dlp's
SoundCloud extractor, as `fallback._soundcloud_track` already does (`ydl.get_info_extractor("Soundcloud")`,
`initialize()`, `_call_api(..., headers=ie._HEADERS)`), which keeps the client id current. The first likes page
loads without impersonation (yt-dlp warns that none is available: curl_cffi isn't installed).

Tasks:
1. **2.1 Recognise** (`recognise`, `canonical_link`): `https://(www.|m.)soundcloud.com/<user>/sets/<slug>[/<s-token>]`,
   `…/<user>/likes`, `…/you/likes`, with any `?…`/`#…`, case-insensitive, stored lowercase except the secret token
   (*check first:* yt-dlp's `SoundcloudSetIE._VALID_URL`: slugs may contain `:`, discover sets
   `soundcloud.com/discover/sets/…` are refused — they change daily). A track link, a user page, `on.soundcloud.com`
   short links → None (`recognise` stays strict; `expand` handles short links, 2.2). Tests: each form; tracks, albums (`/<user>/albums`),
   reposts, Spotify and Qobuz links → None.
2. **2.2 expand** (I4, D4): SoundCloud's `expand` itself claims `on.soundcloud.com/<code>` links (it is asked
   before `recognise`) and returns every other link unchanged: it follows the redirect once (10 s timeout, stdlib
   `urllib.request`, our own User-Agent), then `recognise`s the target; `you/likes` → with the SoundCloud account in
   settings, `me` through the login (`accounts.ytdlp_login("soundcloud", browser, profile)` options) → its
   `permalink` → `<permalink>/likes`; without the account W8; cookie or 401 trouble W9 (`accounts.signal_of`
   decides "cookies unreadable"). Everything else unchanged (the link comes back as it is).
3. **2.3 Reader** (`open`, `fetch`, `info`): one `YoutubeDL` + initialised SoundCloud extractor per reader, no
   cookies (except `you/likes`: a second, logged-in extractor opened on first need). Sets: `resolve?url=<canonical>`
   → the playlist object; stub ids fetched with `tracks?ids=` in batches of 50, `playlistId` and (secret sets)
   `playlistSecretToken` passed as yt-dlp does; order kept by the set's order; an id the batch doesn't return →
   W11 in `skipped`. Likes: resolve the user, then `users/{id}/track_likes` with `limit=200`,
   `linked_partitioning=1`, following `next_href`, passing `impersonate=ie._browser_impersonate_target` as yt-dlp does
   (*check first:* that the call works without curl_cffi; if a later page is refused with 403 in the recorded
   shape, stop and report — curl_cffi would be a new dependency, an orchestrator decision). `token.check()` before
   every request. Errors: HTTP 404/401/403 on the resolve → `playlist_unreadable` (W4 from fetch, W5 from info);
   429 → W7; network/other → W6. No pacer, budget or usage (pass none; a test pins it).
4. **2.4 Parsing** (`parse_track(obj) -> SourceTrack | str`): `id` (text), title and artists through
   `titles.split_title(title, user.username, publisher_metadata.artist)`, `album` = `publisher_metadata.album_title`
   or "", `image_url` = `artwork_url` (else `user.avatar_url`) with `-large` → `-t500x500`, `duration_ms` per D9,
   `isrc` = `publisher_metadata.isrc` or None, `link` = `permalink_url`, `streamable` / `account_only` per D9,
   `service="soundcloud"`. `info`: name = the set's `title` (likes: W10), owner = `user.id` / `user.username`,
   `collaborative=False`, cover = the set's `artwork_url` (else its first track's) at t500x500, `track_count`,
   `yours=False`, `readable=True`; `UNREADABLE_HINT` W3.
5. **2.5 Register** in `SOURCES`. Tests (`tests/test_sources_soundcloud.py`, fixtures in
   `tests/fixtures/soundcloud/`: `set_resolve.json` with 3 full tracks and 60 stubs, `tracks_batch1.json`,
   `tracks_batch2.json`, `likes_page1.json` + `likes_page2.json` with `next_href`, `me.json`, a SNIP, a BLOCK and a
   publisher-metadata track): a fake extractor whose `_call_api` serves them by URL; pins batching and order, paging,
   every parse field, D9's three policies, W3–W11 by cause, Stop between requests, the anonymous reader never sets
   cookies, `expand` for both cases, and no budget/pacer touched.

Checks: that test file and `tests/test_sources.py` while working; the full suite at the end.

## Group 3 — YouTube Music source (Sonnet)

**Read list:** Global constraints, D1, D5, D6, D8, I2, I3, I4, I8 (W12–W19); `discjockey/sources/qobuz.py` (whole);
`discjockey/sources/soundcloud.py` as group 2 left it (outline: follow its shape); `discjockey/fallback.py`
(`_Logger`, `_extract`, `short_error`); `discjockey/accounts.py` (`signal_of`); in the project's yt-dlp:
`extractor/youtube/_tab.py` lines 34–60 (the music redirect), 2285–2330 (`YoutubeTabIE._real_extract`), the
`_extract_video` keys (lines 76–140) — the fields a flat entry carries.

Tasks:
1. **3.1 Recognise** per D5 (list ids `[A-Za-z0-9_-]+`; `VL` stripped from a browse id). Tests: every accepted form,
   `si=` and other keys ignored, a plain video link (`watch?v=` without `list`), a channel, `youtu.be` → None; `LM`,
   `LL`, `WL`, `RD…` recognised.
2. **3.2 Reader**: `open` makes one `YoutubeDL` with `FallbackSource`'s quiet options and logger,
   `extract_flat="in_playlist"`, `skip_download`, `socket_timeout=30`, no cookies, no `extractor_args`. `fetch`/`info`
   refuse `LM`/`LL`/`WL` (W17) and mixes (W18) before any request. Otherwise `extract_info(canonical_link,
   download=False, process=False)` and iterate `entries` lazily, `token.check()` per entry, so Stop reaches it between
   pages (*check first:* that `process=False` gives a lazy generator for `youtube:tab`, and that entries are already
   the flat dicts; if not, use `process=True` with the flat option and check Stop before and after). Errors by
   yt-dlp's message (*check first:* the texts of a private and a removed playlist in this yt-dlp: "This playlist does
   not exist", "private", "unavailable"): → `playlist_unreadable` (W13 / W14); `accounts.signal_of` `bot_check` or
   `rate_limited` → W16; anything else → W15 with `short_error`-free words (`{problem}` = error type name).
3. **3.3 Parsing** (`parse_entry(entry) -> SourceTrack | str`): no `id`, `duration` None, or a title `[Deleted video]`
   / `[Private video]` → W19; artists and title through `titles.split_title(title, channel or uploader)`;
   `album=""`; `image_url` = the largest of `thumbnails` (else `https://i.ytimg.com/vi/{id}/hqdefault.jpg`);
   `duration_ms = duration * 1000`; `isrc=None`; `service="youtube_music"`; link from TRACK_LINKS. `info`: name = the
   playlist `title` (a leading `Album - ` dropped: yt-dlp names album playlists so), owner = `channel_id`/`channel`
   (or `uploader`), `track_count` = `playlist_count`, cover = the largest playlist thumbnail, `yours=False`,
   `collaborative=False`, `readable=True`; `UNREADABLE_HINT` W12. `info` reads only the first page (stop iterating
   after the playlist fields are known; *check first:* they are on the outer dict before `entries` is consumed).
4. **3.4 Register** in `SOURCES`. Tests (`tests/test_sources_youtube_music.py`, fixtures in
   `tests/fixtures/youtube_music/`: `album_playlist.json` (song entries, `Album - ` title), `video_playlist.json`
   (dashed titles, a pipe tail, a deleted entry), error message strings): a fake `YoutubeDL` returning them; pins
   every parse field, song vs video splitting, W12–W19, Stop between entries, no cookies, no budget/pacer.

Checks: that file and `tests/test_sources.py`; the full suite at the end.

## Group 4 — Upload step (Opus)

**Read list:** Global constraints, D7, D9, D10, I1, I5, I6, I8 W20; `discjockey/planner.py` lines 175–200, 310–380,
425–440; `discjockey/acquire.py` (whole, ~480 lines: the account rules are the risk); `discjockey/fallback.py`
(`free_downloads`, `stream_url`, `download`); `discjockey/accounts.py` (`stream_rank`, `ACCOUNT_OF`); `grep -n
"acquire(" discjockey/execute.py` and both call sites; `tests/test_acquire.py` and `tests/test_planner.py`
(`grep -n "def test_"`, the fake Qobuz/fallback helpers).

Tasks:
1. **4.1 Upload on actions** (`planner.py`, `models.Action.upload`): I5 with its tests.
2. **4.2 The step** (`acquire.py`): I6 1–4 as a helper beside `_fallback` (`_upload(...)`), reusing `_fallback`'s
   account branch rather than copying it — refactor that branch into one function both call if needed (CLAUDE.md
   "refactor when necessary").
3. **4.3 Upgrade checks** (`acquire.py`): I6 5.
4. **4.4 Wiring** (`execute.py`): `upload=a.upload` in both calls; D10 in `make_ready`. Tests: I6's list;
   one in `tests/test_execute.py` (an action with an upload reaches the acquirer).

Touched tests: `uv run pytest -q tests/test_acquire.py tests/test_planner.py tests/test_execute.py tests/test_run.py`
while working; the full suite at the end.

## Group 5 — Bridge and docs (Sonnet)

**Read list:** Global constraints, D4, D8, I4, I7, I8 (W3, W12, W20); `docs/hub-bridge-contract.md` (`grep -n
"service\|PlaylistService\|how"` and those lines); `discjockey/hub/api.py` lines 1105–1160; `discjockey/hub/views.py`
`grep -n "PLAYLIST_SERVICES\|how\b\|\"how\""`; `discjockey/events.py` (`SourceChosen`);
`hub-ui/src/lib/bridge/types.ts`, `contract.ts`, `fake/bridge.ts`, `fake/data.ts` (`grep -n "PlaylistService\|qobuz:\|
SERVICE_NAME\|Spotify or Qobuz"`); `README.md` (`grep -n "playlists.txt\|Qobuz playlist\|Links:"` and that section,
lines 180–205); `CLAUDE.md` (the `discjockey/sources/` row); `discjockey/setup_cmd.py` lines 10–20, 90–100;
`docs/issues.md` issue 26.

Tasks:
1. **5.1 Bridge** (`api.py`, `views.py`): I7's engine side; W20 wherever views word `how`. Tests:
   `tests/test_hub_api_playlists.py` (a SoundCloud and a YouTube Music link add with service and ref; `you/likes`
   expands; W5, W8, W18 as `ok: false` with `service`), `tests/test_hub_views.py` (`how` upload, read status lists
   the new services connected).
2. **5.2 Contract, types, fake** in the same commits (I7). `npx vitest run src/lib/bridge` and `npm run check` in
   `hub-ui`.
3. **5.3 README:** `playlists.txt` takes all four services; the accepted SoundCloud forms (sets, private share links,
   `<name>/likes`, `you/likes` with the SoundCloud login, short links pasted in the window) and YouTube Music forms
   (playlists and albums, youtube.com playlist links too; not Liked music, Watch later or mixes); a SoundCloud or
   YouTube Music playlist needs no login and its read counts against no limit; titles are split into artist and
   title and tags like `[FREE DL]` dropped; the search order (Qobuz by name, then the playlist's own upload, its free
   download first, then the other fallbacks). Plain words, README's tone.
4. **5.4 The rest:** CLAUDE.md's sources row names the four services, `titles.py` gets a row; `setup_cmd.py`'s
   template comment and the Spotify-skipped line name the four services; `docs/issues.md`: remove issue 26's
   first point (D8), add Q1's answer if it is "later". `scripts/check_public.sh --require-denylist`.

Checks: the files above; the full suite at the end.

## Group 6a — UI build (Sonnet, no screenshots)

**Mandatory:** read `docs/hub-design-language.md` (§2 the colour rule's logo exception, the blocks). Strict scope:
words, unions and mappings only; no layout, block or token change (anything else is reported, not done).

**Read list:** I7, I8 (W2, W20–W23); `hub-ui/src/lib/components/serviceLogos.ts`, `ServiceMark.svelte`,
`lib/shell/RowLead.svelte`, `lib/shell/browserModel.ts` (around line 92), `lib/copy.ts` lines 1–80,
`lib/components/AddRow.svelte`, `lib/components/addRowModel.ts`, `pages/playlists/Page.svelte` (around line 192),
`pages/setup/StepPlaylists.svelte`, `pages/sync/cardState.ts` (`how` words); `grep -rn "PlaylistService\|'qobuz'"
hub-ui/src --include='*.ts' --include='*.svelte'` for every switch over services.

Tasks:
1. **6a.1 One name map:** `copy.ts`'s `PLAYLIST_SERVICE_NAMES` gains the two services and becomes the only map
   (`browserModel.ts`'s and the fake's copies import it). `SERVICE_SETTINGS`: `soundcloud` → `#/settings/soundcloud`,
   `youtube_music` → none (it never answers `not_set_up`; type it so).
2. **6a.2 Logos:** `serviceLogos.ts` gets `logoOf(service: PlaylistService): LogoKey` (`youtube_music` →
   `youtubemusic`); `RowLead` and every `ServiceMark` caller pass through it; the stale "stage 6 adds the others"
   comment goes. The logos stay exactly as they are (coloured, 14 px).
3. **6a.3 Words:** W21 (first form), W22, W23, W20 in `cardState.ts`; `copy.ts` picks problem titles for the new
   services by `kind` + `service` (`offline` → "SoundCloud isn't answering." through the existing rule).
4. **6a.4 Tests and fake:** `*.test.ts` for `logoOf`, the name map and `serviceProblem` with the new services;
   `shots.json` entries for the three fake rows, `soundcloud_unreadable`, `youtube_mix_refused`, and a track detail
   of each new service.

Checks: `npx vitest run` on the changed tests, `npm run check`, `npm run build` (its `build(hub): static` commit
last). Never `npm run verify`.

## Group 6b — UI shots (Opus)

**Mandatory:** load `apple-design` and `emil-design-eng`; read `docs/hub-design-language.md`. Review the whole
screen in every shot (each grey, colour, word and count for meaning), empty and first-open states included, logos at
real size.

**Scope.** Build from: nothing new (no mockup). Must not change: every page, block, token and the foot outside what
6a touched. Look for: the placeholder cut at 1100 (then W21's second form), the two new logos beside Spotify/Qobuz
rows in the browser column and on the Playlists page at 1100 and 2560, the error cards' words, the track detail
link. Anything beyond words goes in the report as "beyond scope" with before/after shots.

Shots (fake mode): `--page playlists` (the three rows, both scenarios, empty state), `--page library` (browser column
with all four logos; a SoundCloud track's details), `--page setup` (playlists step), `--page sync` (a card chosen by
`how=upload`). `npm run rules -- --page <p> --only <shots>` for the touched shots.

---

## Stage checks

- **Python:** each group's files while working; the full suite once per group (`uv run pytest -q | tail -3`); CI on
  the stage branch push before the merge.
- **Specific pins the stage review looks for:** the splitter table (review focus 3); the reader-touches-no-budget
  tests in both source files (1); the anonymous-reader test (1); the upload order and the SNIP rule (2); the
  yt-dlp-free import test (5); stage 3's test files unchanged except words; `grep -rn "Spotify or Qobuz" discjockey
  hub-ui/src README.md` empty.
- **UI:** `npm run verify` once, by the orchestrator, in the background, before the merge. Screenshots as group 6b
  lists; the orchestrator looks at them itself.
- **Live check by the user — about 5 minutes, read-only.** SoundCloud's API answers and YouTube's flat entries can't
  be checked offline beyond the recorded shapes (the fixtures were trimmed from real answers of public examples, but
  a user's lists bring the real mix of policies, deleted tracks and odd titles). Nothing downloads. In the new
  build, on the Playlists page: (1) paste a SoundCloud set and check name, owner, track count; (2) paste
  `soundcloud.com/you/likes` (with the SoundCloud login set up) and check it becomes the profile's likes link and
  reads past 200 tracks if the list is that long; (3) paste a YouTube Music playlist that mixes songs and videos;
  (4) save them, press "↻ Read playlists" on Sync, and look through the plan's artists and titles for splits that
  read wrong (each one becomes a splitter case). Optional, the user's call: sync one SoundCloud-only track to see the
  upload step (counts against the SoundCloud limit only). If the user prefers, the orchestrator does (1)–(4) itself
  with the user's go, in a scratch support folder.
