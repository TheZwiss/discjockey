# Library stage 3 "Qobuz playlists" — plan

Spec: `docs/2026-10-23-library-and-sources-design.md` §9.1–9.3 (the spec), with §2 (song, source), §3.2, §5.2
(`song_ids`), §5.5 (code boundaries), §12 ("a source can't read a playlist") and §13 ("Sources"). Orchestration:
`docs/2026-10-23-library-and-sources-orchestration.md`. Builds on stages 1–2 (merged into `main` 43552ed). Stage
branch: `feat/library-3-qobuz`, off `main`.

**Goal:** a Qobuz playlist link works in `playlists.txt` and on the Playlists page; its tracks download exactly, by
Qobuz id; Spotify is one source among others behind one interface; every track link is the track's own service's.

**Architecture.** A new package `discjockey/sources/` holds one module per playlist service (`spotify.py` moves
there, `qobuz.py` is new) and a small registry (`sources/__init__.py`) that turns a link into (service, playlist id)
and reads a list of playlist lines with the right reader. Songs and playlists are named by a **token** (I2): a bare
id for Spotify (as today, so nothing stored changes), `service:id` for every other service. The planner links a
fetched track to a song by token, then ISRC, then name and length (§9.2), and tells the acquirer the Qobuz id to
try first. `discjockey/qobuz.py` stays where it is: it is the download client (login, search, download) that
`acquire.py`, `run.open_qobuz` and Setup use; the new `sources/qobuz.py` reads playlists through it.

**No schema step.** `SCHEMA_VERSION` stays 2. `song_ids` already has `(service, id)` and `songs.key` is free text;
only the code that reads and writes `song_ids` learns tokens (I3). *Why:* no released version reads `library.db`
yet (v1.1.0 still uses `state.json`; stages 1–3 ship together), so there is no older reader to fence off with a
version bump, and a step with no SQL would be noise.

---

## Global constraints

- **Qobuz protection stays on** (CLAUDE.md invariant): every Qobuz *download*, the exact-id one included, goes
  through `Acquirer._try` (download pacing, the daily limit with carry-over, the auto-stop). Playlist **reads**
  touch none of them: no `Pacer` call, no `budget.count()`, no usage row, and a read error never counts toward the
  auto-stop (spec §9.3: reads don't count against the download limits; the auto-stop protects the download account).
- **No new path writes music files.** Stage 3 changes reading and choosing, not placing: option A, `run_op` and the
  move log are untouched.
- **`planner.py` and `hub/views.py` stay pure; only `db.py` writes SQL.** Linking (§9.2) lives in the planner; the
  aliases it adds reach the db through the existing `db.save` diff.
- **Nothing stored for Spotify changes:** a Spotify song's key, aliases, `never` rows, hub caches and report rows
  keep their bare ids. A test pins that a stage-2 database snapshot round-trips unchanged through the new code.
- **`SpotifyTrack` is gone, not aliased:** every use (engine, tests, docs) says `SourceTrack`. Same for
  `discjockey.spotify` → `discjockey.sources.spotify` (no shim module left behind).
- **Words** are binding as given in I8. **Tests offline** (recorded responses only, `conftest.py` blocks the
  network). **Public repo:** `scripts/check_public.sh` before every commit; fixtures use made-up ids and names
  (`Example Artist`, playlist `0DiscjockeyExample…`, Qobuz ids like `900000001`).

## Decided here (with reasons)

- **D1. Setup is unchanged.** Its Spotify step stays; a user with only Qobuz playlists still connects Spotify in
  Setup. At *read* time only the services `playlists.txt` uses must be logged in (I4 `login_state`). *Why:* making
  Spotify optional in Setup is a product change the spec doesn't make (open question Q1 for the user).
- **D2. The read-status wire names stay** (`spotify` field, `SpotifyStatus` type and component, `spotify_status` in
  views). Their *words* become service-neutral now (I8 W10). *Why:* the shell-wide status slot is rebuilt with the
  sidebar in stage 5; renaming its plumbing now would be done twice. Group 7 records the rename in
  `docs/issues.md`. The two per-track wire fields that would now lie (`spotify_url`, `spotify_duration_s`) are
  renamed in this stage (I7).
- **D3. One Qobuz login per read.** The Qobuz reader opens its own `qobuz.QobuzSource` and closes it when the read
  ends; `run.open_qobuz` still opens the download client for `execute`. *Why:* the hub reads in one job's thread and
  downloads in another, and streamrip's client is bound to its `asyncio.Runner`; one extra login per sync is cheap.
- **D4. ISRC linking keeps the 3-second length check** (`planner.ISRC_TOLERANCE_MS`). The spec says "the same ISRC";
  the existing rule is stricter and guards against wrong ISRCs on re-releases. Not a conflict: the spec doesn't
  forbid a tolerance.
- **D5. A track's link comes from where it was read.** A song's link (track detail, report) is the link of the first
  fetched track that resolves to it (playlist order), else the link derived from its key (`models.track_link`).
  *Why:* a song in a Qobuz playlist should open in Qobuz even if it was first known from Spotify.

## Review focus (per-group review and the stage review)

1. A stage-2 database and its Spotify songs read, plan and save exactly as before (keys, aliases, `never`).
2. The exact Qobuz id is tried first, once, through `_try`; on preview-only / unavailable the usual chain follows
   without retrying that id; no Qobuz request skips pacing, the limit or the auto-stop.
3. Reading a Qobuz playlist never counts as a download or a failure for the auto-stop.
4. Linking order is token → ISRC (±3 s) → name and length (only for a track without ISRC) → new song; a link by
   ISRC or name adds the track's token to the song.
5. Bridge methods never reject; every user-facing word for a service problem names that service.

---

## Interfaces (fixed here; groups build against them)

### I1. Records — `models.py` (group 1)

`SpotifyTrack` becomes `SourceTrack`; field order kept so the ~100 positional constructions in tests still read:

```python
@dataclass(frozen=True)
class SourceTrack:
    id: str                      # the service's own id (Spotify base62, Qobuz digits as text)
    title: str
    artists: tuple[str, ...]
    album: str
    image_url: str | None
    duration_ms: int
    isrc: str | None
    service: str = "spotify"     # a key of SERVICE_NAMES
    link: str | None = None      # the track's page; __post_init__ fills it from TRACK_LINKS when None
    streamable: bool = True      # False: the service lists it but won't deliver it now (Qobuz preview/region)
    # properties: first_artist (as today), key -> token(service, id). `url` is removed (callers use .link)

@dataclass(frozen=True)
class PlaylistLine:
    folder: str
    playlist_id: str             # the service's own id
    line_no: int
    service: str = "spotify"
    # property: ref -> token(service, playlist_id)

@dataclass(frozen=True)
class PlaylistInfo:              # moved from spotify.py, now shared
    service: str
    id: str
    name: str
    owner_id: str
    owner_name: str
    collaborative: bool
    image_url: str | None
    track_count: int | None
    yours: bool
    readable: bool               # set by the source: its own rule (Spotify: yours or collaborative)
```

Plus `SERVICE_NAMES = {"spotify": "Spotify", "qobuz": "Qobuz"}` (playlist services; `SOURCE_NAMES` stays the
download sources), `TRACK_LINKS = {"spotify": "https://open.spotify.com/track/{id}", "qobuz":
"https://open.qobuz.com/track/{id}"}`, and three pure helpers: `token(service, id) -> str`, `split_token(tok) ->
tuple[str, str]`, `track_link(tok) -> str | None` (None for a service without a TRACK_LINKS entry: stage 6 decides
SoundCloud's, whose links aren't derivable from an id). `FetchedPlaylist.tracks` is `list[SourceTrack]`.
`Action` gains `qobuz_id: str | None = None` (I5).

- *Why `link` defaults:* Spotify and Qobuz links follow from the id; stage 6 passes SoundCloud permalinks.
- *Why `streamable`:* a Qobuz playlist marks preview-only tracks; trying them would cost a request that counts
  toward the auto-stop (`_try` counts a preview-only answer as a failure).
- `PlaylistInfo.readable` becomes a field because the rule differs per service.

### I2. Tokens

`token("spotify", x) == x`; `token(s, x) == f"{s}:{x}"` for any other service. `split_token` of a string without
`:` is `("spotify", s)`, else split at the first `:`. A Spotify id never contains `:`; a token is used as a song
key, an alias, a `never` key, an `Action.track_id`, a hub `track_id` and the key of every playlist-keyed dict
(`tracks_by_id`, `infos`, `_extra_tracks`, `read_infos` ids). Candidate keys (`qobuz:<id>` in
`rejected_sources`) are a different namespace that happens to share the form; nothing compares the two.

Tests pin: round trips for both services; a Spotify id stays bare; `track_link` for both and None for `soundcloud:1`.

### I3. song_ids by token — `db.py` (group 2)

- `_insert_song(conn, key, entry)` inserts `(*split_token(key), song)` instead of `(SPOTIFY, key, song)`.
- `_write_aliases` keeps the key's own row (`NOT (service = ? AND id = ?)` with the split key) and inserts each alias
  split; insertion order is still the aliases' order.
- `_aliases` reads every service (drop `WHERE i.service = ?`), returns tokens, skips the row equal to the key.
- `SPOTIFY` goes once nothing uses it. *Check first:* `grep -n "SPOTIFY\|song_ids" discjockey/db.py` for any other
  reader (migration `create`, `apply_scan`) and keep its behaviour.

Tests pin (`tests/test_db.py`): a song keyed `qobuz:900000001` with a Spotify alias round-trips (`song_ids` holds
`("qobuz","900000001")` and `("spotify", "<id>")`); a Spotify song with Qobuz aliases likewise; the stage-2
round-trip test still passes untouched.

### I4. The source interface — `discjockey/sources/` (group 1 builds it with Spotify; group 3 adds Qobuz)

Each source module has:

```python
SERVICE: str                                            # "spotify" | "qobuz"
def recognise(link: str) -> str | None                  # the playlist id when the link is one of its playlists
def canonical_link(playlist_id: str) -> str             # what playlists.txt and the page store
def login_state(paths: SupportPaths) -> LoginState      # local check only, never a network call
def open(paths: SupportPaths, token: CancelToken) -> Reader   # logs in; raises SourceError
class Reader:                                           # a context manager; close() on exit
    def fetch(self, line: PlaylistLine) -> FetchedPlaylist
    def info(self, playlist_id: str) -> PlaylistInfo
```

The spec's `fetch(playlist)` and `info(playlist)` are the reader's methods because both need a logged-in session
that is opened once per read (Spotify's refresh lock, Qobuz's login, D3). `LoginState` (in `sources/__init__.py`):
`state: "ok" | "missing"` and `message` (W6 for Qobuz; Spotify's existing "not set up" text). "Not needed" from the
spec has no user in stage 3 (both services need a login); stage 6 adds it if yt-dlp reads need none.

`sources/__init__.py` exports:

- `class SourceError(Exception)` with `kind` (the existing kinds: `not_set_up | login_expired | offline |
  playlist_unreadable | login_failed`, plus `qobuz_login_failed`) and `service`. `sources.spotify.SpotifyError`
  becomes its subclass (service `"spotify"`), so every existing `except SpotifyError` keeps working and new code
  catches `SourceError`.
- `SOURCES: dict[str, module]` (`"spotify"`, then `"qobuz"` from group 3).
- `recognise(link) -> tuple[str, str] | None` — the first source that recognises the link → (service, playlist id).
- `read(paths, lines, *, emit, token) -> list[FetchedPlaylist]` — for each service the lines use (in first-line
  order): `login_state` first (a `missing` raises `SourceError(kind="not_set_up", service=…)` with its message,
  before any network call), then one `open(...)` reader per service, `ReadingPlaylist(i, total, folder)` per line in
  `playlists.txt` order, results in line order.
- `read_infos(paths, refs, infos, token)` — the hub's info read (today `jobs.read_infos`), per service, a failing
  playlist drops its entry (as today), a failing login leaves the others.

`config.playlist_id` is removed; `config.parse_playlists` uses `sources.recognise` and builds
`PlaylistLine(folder, id, line_no, service)`; the duplicate check compares `ref`. `playlists_file.Row` gets
`service` and `ref` properties (from `sources.recognise`), replacing `playlist_id`; every `tracks_by_id[...]` is
keyed by `ref`. *Check first:* `config.py` must not import `sources` at module level if that cycles
(`sources.spotify` imports `library`); import inside the function if it does.

### I5. Linking and the exact id — `planner.py` (group 2)

`_resolve` works on tokens and follows §9.2 exactly:

1. `index[t.key]` (song key or any alias token) → that song.
2. else the ISRC twin (`_isrc_twin`, ±3 s, D4) → that song.
3. else, **only for a track without ISRC**, a *name twin*: a song whose normalised artist and normalised title equal
   the track's (`first_artist`, `title`) and whose `duration_ms` is within `ISRC_TOLERANCE_MS` (rename it
   `SAME_LENGTH_MS`, one constant for both rules). *Check first:* which normaliser `matching.py` uses for
   `qobuz_match` and how an entry's `artist` is built from a track (`apply_outcome` / `make_ready`); compare like
   with like (entry `artist` against `first_artist` normalised the same way). Candidates for a name twin are the
   stored songs *and* the songs this run already resolved (as `by_isrc` does today).
4. else a new song keyed `t.key`.

A link by 2 or 3 appends `t.key` to the song's `aliases` (stored songs) or to `_Wanted.aliases` (new ones), and adds
a note: ISRC as today; name W11. `index[t.key]` is set either way, so a second playlist with the same track resolves
by step 1.

`_Wanted` gains `qobuz: SourceTrack | None` — the first fetched Qobuz track (playlist order) that resolved to the
song **and is streamable**. `plan` passes it on: `Action.qobuz_id = w.qobuz.id if w.qobuz else None` for `acquire`
and `upgrade` actions (not `adopt_bought`). *Why only fetched tracks, never a stored alias:* only this read says
whether Qobuz delivers the track now; a song with a stored Qobuz alias but no Qobuz playlist any more still finds it
through the ISRC search.

Tests pin (`tests/test_planner.py`): each step, in order, with a Spotify and a Qobuz playlist holding the same
song (ISRC) → one action, key = the first line's token, the other token in `aliases`; a no-ISRC track with same
name and length ±3 s links, at 3.1 s doesn't, with an ISRC it never links by name; a non-streamable Qobuz track
gives `qobuz_id None`, a streamable one later in the order gives its id; Spotify-only input plans exactly as before.

### I6. The exact-id step — `acquire.py`, `execute.py` (group 4)

`Acquirer.acquire(..., exact: str | None = None)`. When `exact` is set and Qobuz is open and wanted
(`self.qobuz is not None and qobuz`), before the search steps:

- the same `budget.exhausted()` → `queued` and `budget.stopped` → break guards as the search loop;
- no metadata request (the playlist read already has the facts): the candidate is built from the track:
  `Candidate("qobuz", exact, title, artist, duration_s, isrc=…, album=…, image_url=…)` with `artist` joined like
  `qobuz.parse_track` does, so `rank`/`isrc_match` treat it like a search result; skipped when `c.key in skip`
  (rejected before).
- `self._try(c, track, workdir, res, skip, lossless_only, tracker, qobuz=True, how="exact")`; ready → done.
- a failed try (preview-only, unavailable, a download error, a file that fails `make_ready`): `skip.add(c.key)` so
  the ISRC search that follows doesn't download the same id again this time; `_try` already records permanent
  rejections and counts failures toward the auto-stop exactly as for a searched candidate.
- then the usual chain (ISRC, name, fallbacks) unchanged; `qobuz_searched` still counts only the search steps.

`how="exact"` is a new value of `SourceChosen.how` (events) — *check first:* where `how` is worded
(`views.py` / hub-ui `cardState.ts`) and add "exact Qobuz track" next to "ISRC"/"name" (group 5 owns the words, I8
W12; group 4 only emits it). `execute.py` (*check first:* the call site of `acquirer.acquire`) passes
`exact=action.qobuz_id` for acquire and upgrade actions.

Tests pin (`tests/test_acquire.py`, fake Qobuz): exact id downloaded first without any search call; preview-only on
the exact id → ISRC search runs and the same id isn't downloaded again; exact failure counts once toward the
auto-stop (as a searched candidate's would); budget exhausted → `queued` before any request; `exact=None` → today's
behaviour byte for byte (existing tests unchanged).

### I7. Bridge changes (group 5)

All in `docs/hub-bridge-contract.md`, `types.ts`, `contract.ts`, fake backend, same commit:

- **Playlist rows** (`views.playlists`): `playlist_id` now carries the **ref** (token) — the page keys rows by it;
  new `service` (`"spotify" | "qobuz"`) and `service_name`; `info` (InfoDict) gains `hint: str | null` (the
  service's unreadable words, W5 / Spotify's `NOT_YOURS`) so the page stops hard-coding Spotify's.
- **`add_playlist(url)`**: recognises either service (`sources.recognise`), reads info and tracks through that
  service's reader; returns the same shape, `playlist_id` = ref, plus `service`, `service_name`. A Qobuz playlist
  Qobuz won't show → `{"ok": false, "kind": "playlist_unreadable", "service": "qobuz", "message": W4}`; Qobuz not
  logged in → `kind "not_set_up"`, `service "qobuz"`, W6 (hub form). `preview_playlist_change` reads unread rows per
  service the same way (a failing one is skipped, as today).
- **Error envelope:** `{"ok": false, "kind", "message"}` may carry `"service"` when a `SourceError` caused it
  (`bridge` in `api.py` maps `SourceError` like it maps `SpotifyError` today, *check first* how).
- **Read status** (`spotify` field, D2): gains `problem_service: "spotify" | "qobuz" | null` and `services:
  [{service, name, connected}]` — the services `playlists.txt` uses, `connected` from `login_state`. The page blocks
  reading only when one of them isn't connected. `views.spotify_status` gets the logins passed in (pure).
  `run.SetupProblem` gains `service` (from the `SourceError`); `PreviewStore.failed(kind, message, service)`.
- **Track detail:** `spotify_url` → `track_link: {url, label} | null` (label W9; D5: first fetched track's link,
  else `models.track_link(key)`).
- **Events:** `Checked.spotify_duration_s` → `track_duration_s`; `search_candidates` likewise
  (`spotify_duration_s` → `track_duration_s`); `tests/fixtures/hub_events.schema.json` follows. *Check first:*
  `Checked` is built positionally in `acquire.make_ready` (then acquire.py needs no edit).
- **Report** (`report.py:59`): the track link comes from `models.track_link(track_id)` (and from the track's
  `link` where the row is built from a `SourceTrack`), never a hard-coded Spotify URL.

Fake backend: one Qobuz playlist row (`https://open.qobuz.com/playlist/900000001`, owner "Example Curator"), a
Qobuz track whose detail shows "Open in Qobuz", a scenario `qobuz_unreadable` (add_playlist answers W4) and one
`qobuz_not_connected` (read status `services` has Qobuz `connected: false`).

### I8. Binding words

| Id | Where | Words |
|----|-------|-------|
| W1 | `config.parse_playlists` | `playlists.txt line {n}: this is not a Spotify or Qobuz playlist link: {ref}`; the format hint becomes `expected 'Folder = playlist link'` |
| W2 | `playlists_file.clean_link` | `That isn't a Spotify or Qobuz playlist link. Open the playlist in Spotify or Qobuz, choose Share, then Copy link, and paste it here.` |
| W3 | Qobuz `fetch`, a line it can't read | `playlists.txt line {n} ({folder}): Qobuz doesn't show this playlist. It must be public or one of yours. Check the link, or put # in front of the line.` (kind `playlist_unreadable`) |
| W4 | Qobuz `info`, a pasted link | `Qobuz doesn't show this playlist. It must be public or one of yours. Check the link.` |
| W5 | row hint, Qobuz unreadable | `Make it public in Qobuz, or use one of your own playlists.` |
| W6 | Qobuz `login_state` missing | console: `Your playlists include a Qobuz playlist, but Qobuz isn't set up yet. Run: discjockey setup`; hub card: title `Qobuz isn't connected.`, action `Connect Qobuz →` (*check first:* the hash route of the Qobuz login card in `settingsModel.ts`) |
| W7 | Qobuz login rejected while reading | `qobuz.login_problem(e)` as today, kind `qobuz_login_failed` |
| W8 | Qobuz not answering while reading | `Qobuz is not responding ({problem}). Try again later.` (kind `offline`) |
| W9 | track link label | `Open in {SERVICE_NAMES[service]}` ("Open in Spotify", "Open in Qobuz") |
| W10 | read status (UI) and console | `Reading your playlists...` (console, replaces "Reading your Spotify playlists..."); `↻ Read playlists`; `Playlists read {ago}`; `Playlists haven't been read yet`; `Reading playlists…`; `Connect {Name} first.`; `no_preview` body: `Read your playlists above to see what changed.` |
| W11 | planner note, name link | `{artist} - {title}: same song as one you already have (same artist, title and length), not downloaded again.` |
| W12 | how a source was chosen | `exact Qobuz track` (next to the existing ISRC / name wording) |
| W13 | length check (sync card) | `Length matches ({file} = playlist {track})` / `Length differs ({file}, playlist {track})` |
| W14 | AddRow placeholder | `Paste a Spotify or Qobuz playlist link…` |

Spotify's own words (its unreadable "Follow ≠ own", login expired, not connected) stay as they are.

---

## Task groups

| Group | Model | Area | Size (changed lines) | Depends on | Runs with |
|-------|-------|------|----------------------|------------|-----------|
| 1 Sources and the rename | Sonnet | `sources/` new, `spotify.py` moved, `models.py`, `config.py`, `playlists_file.py`, `run.py`, the rename everywhere | ~900 (mostly mechanical) | — | — |
| 2 Linking | Opus | `planner.py`, `db.py` | ~450 | 1 | 3 |
| 3 Qobuz source | Sonnet | `sources/qobuz.py` new, its fixtures and tests | ~550 | 1 | 2 |
| 4 Exact id | Sonnet | `acquire.py`, `execute.py` | ~250 | 2 | 7 |
| 5 Bridge | Sonnet | `hub/api.py`, `hub/jobs.py`, `hub/views.py`, `events.py`, `report.py`, contract, `types.ts`, `contract.ts`, fake | ~800 | 2, 3 | 7 |
| 6 Hub words and Playlists page | Opus | `hub-ui/src` (AddRow, playlists page, SpotifyStatus words, copy, sync card) | ~400 | 5 | — |
| 7 Docs | Sonnet | README, CLAUDE.md, `docs/issues.md` | ~120 | 3 | 4 or 5 |

Rounds: 1 → (2 ∥ 3) → (4 ∥ 7) → 5 → 6. Parallel groups share no file (group 3 registers itself in
`SOURCES` with one line in `sources/__init__.py`, which group 2 doesn't touch). Group 5 waits for 4 only because both
are big enough that one review at a time is cheaper; they share no file.

---

## Group 1 — Sources and the rename (Sonnet)

**Read list:** this plan's Global constraints, D1–D3, I1, I2, I4, I8 W1/W2/W10; `discjockey/models.py` lines 1–70;
`discjockey/spotify.py` (docstring, outline, lines 39–54, 300–389); `discjockey/config.py` (whole, ~90 lines);
`discjockey/playlists_file.py` lines 1–90, 142–222; `discjockey/run.py` lines 1–123; `discjockey/hub/jobs.py`
lines 560–592. For the rename: `grep -rn "SpotifyTrack\|discjockey.spotify\|from \.spotify\|from \.\. import
spotify\|import spotify\|playlist_id\|\.url\b" discjockey tests` and change each hit; no other reads.

Tasks:
1. **1.1 Records** (`models.py`): I1 and I2 exactly. `SourceTrack.__post_init__` fills `link` (frozen:
   `object.__setattr__`). Tests: `tests/test_models.py` (new or existing) pins I2's cases and the link defaults.
2. **1.2 The package** (`discjockey/sources/__init__.py`, `sources/spotify.py` by `git mv` so history follows):
   `SourceError`, `LoginState`, `SOURCES`, `recognise`, `read`, `read_infos` (I4). Spotify's module gets
   `SERVICE`, `recognise` (the two regexes now in `config.py`, moved), `canonical_link`, `login_state` (token file
   present → ok; else `missing` with today's not-set-up message), `open` → a `Reader` wrapping today's `Session`
   (`session.check, session.sleep = token.check, token.sleep`) with `fetch` (today's `fetch_playlist`) and `info`
   (today's `playlist_info`, `current_user` read once per reader, `readable = yours or collaborative`).
   `SpotifyError` subclasses `SourceError`. Keep `login`, `api_get`, `load_session`, `current_user` as module
   functions (Setup and the hub's login use them).
3. **1.3 Links in playlists.txt** (`config.py`, `playlists_file.py`): I4's last paragraph; W1, W2;
   `clean_link` returns `canonical_link` of the recognising source. Tests: `tests/test_config.py`,
   `tests/test_playlists_file.py` — Spotify lines behave as before; an unknown link gives W1; refs key the dicts.
4. **1.4 One read for all lines** (`run.prepare`, `hub/jobs.py`): `prepare` calls `sources.read(...)` instead of
   its Spotify loop and catches `SourceError` into `SetupProblem(str(e), e.kind, service=e.service)`
   (`SetupProblem` gains `service: str | None = None`); the console line is W10's. `jobs.read_infos` delegates to
   `sources.read_infos`; `jobs.py`'s `except spotify.SpotifyError` become `SourceError`. Tests: `tests/test_run.py`
   — a run with only Spotify lines reads exactly as before (same `ReadingPlaylist` events); a `missing` login
   stops before any network call with the service's message.
5. **1.5 The rename** in every other module and test (`acquire`, `ops`, `matching`, `fallback`, `candidates`,
   `report`, `setup_cmd`, `cli`, `hub/api.py`, `hub/views.py`, tests and `tests/hub_helpers.py`): `SpotifyTrack` →
   `SourceTrack`, `t.url` → `t.link`, `discjockey.spotify` → `discjockey.sources.spotify` (monkeypatch targets
   too), `config.playlist_id(...)` → `sources.recognise(...)`. Behaviour unchanged; `hub/api.py`'s
   `add_playlist` / `preview_playlist_change` keep calling Spotify directly until group 5.

Checks while working: `uv run pytest -q tests/test_models.py tests/test_config.py tests/test_playlists_file.py
tests/test_spotify.py tests/test_run.py`. At the end: the full suite (`| tail -3`); `grep -rn SpotifyTrack
discjockey tests docs/hub-bridge-contract.md` is empty.

## Group 2 — Linking (Opus)

**Read list:** Global constraints, D4, D5, I1 (`Action`), I2, I3, I5, I8 W11; `discjockey/planner.py` lines
1–20, 171–318; `discjockey/db.py` lines 225–258, 353–383, 462–476 and `grep -n "SPOTIFY\|song_ids"
discjockey/db.py`; `discjockey/matching.py` (docstring, outline, the normaliser `qobuz_match` uses);
`tests/test_planner.py` and `tests/test_db.py` (`grep -n "def test_"` and helper signatures).

Tasks:
1. **2.1 song_ids by token** (`db.py`): I3. Tests as listed there.
2. **2.2 §9.2 in `_resolve`** (`planner.py`): steps 1–4 of I5, the name twin, notes, `SAME_LENGTH_MS`.
   `desired_folders` follows (it calls `_resolve`), so the Playlists page's "what this change does" links the same
   way. Tests as listed in I5.
3. **2.3 The Qobuz id on actions** (`planner.py`, `models.Action`): `_Wanted.qobuz`, `Action.qobuz_id` (I5).
   `run.action_key` and `select_actions` are unaffected (they key by track id) — *check first* that nothing
   compares whole `Action`s, which a new field would change.

Touched tests (planner and db are used widely): `uv run pytest -q tests/test_planner.py tests/test_db.py
tests/test_playlists_file.py tests/test_tidy.py tests/test_run.py` while working; the full suite at the end.

## Group 3 — Qobuz source (Sonnet)

**Read list:** Global constraints, D3, I1, I2, I4, I8 W3–W8; `discjockey/sources/__init__.py` and
`sources/spotify.py` as group 1 left them (outline + `Reader`); `discjockey/qobuz.py` lines 1–60 (errors,
`login_problem`), 119–200 (`parse_track`, `QobuzSource._call`, `open`); streamrip's
`.venv/lib/python*/site-packages/streamrip/client/qobuz.py` lines 217–251 (`get_metadata`) and 342–395
(`_paginate`, `_api_request`), and `streamrip/metadata/playlist.py` `from_qobuz` (the response fields streamrip
relies on: `name`, `tracks.items`, each item's `album`).

Tasks:
1. **3.1 Recognise** (`sources/qobuz.py`): `SERVICE = "qobuz"`; `recognise` accepts
   `https://{open,play,listen}.qobuz.com/playlist/<digits>` (with any trailing path, `?…` or `#…`) and
   `https://www.qobuz.com/<xx-xx>/playlists/<slug>/<digits>`; `canonical_link(id) =
   "https://open.qobuz.com/playlist/{id}"`. Tests: each form, a Qobuz album/track link → None, a Spotify link → None.
2. **3.2 Login state** (`login_state`): `qobuz.config_file(paths)` exists and holds a login (*check first:* what
   `_save_login` writes, and test the same thing `QobuzSource.open` needs) → ok; else `missing`, W6 (console form).
3. **3.3 Reader** (`open`, `Reader.fetch`, `Reader.info`): `open` calls `qobuz.QobuzSource.open(paths)` and sets
   its `check = token.check`; `QobuzNotSetUp` → `SourceError(kind="not_set_up")` W6; `QobuzLoginRejected` / other
   login errors → `qobuz_login_failed` W7. `fetch` pages `playlist/get` itself (`extra=tracks`, `limit=500`,
   `offset` += 500 until `tracks.total`), each request through `QobuzSource._call(client._api_request(...))` so Stop
   and the 30-second timeout apply — *not* `get_metadata`, which stops at 500 tracks. *Check first:* whether
   `_api_request` adds `app_id` itself (`get_metadata` passes it explicitly; do the same if not). Status 200 → items;
   400/401/403/404 → `playlist_unreadable` W3 (W4 from `info`); a timeout, `QobuzError` or another status → `offline`
   W8. No `Pacer`, no budget, no usage (Global constraints).
4. **3.4 Parsing** (`parse_item(item) -> SourceTrack | str`): `id = str(item["id"])`; title with `version` in
   parentheses as `qobuz.parse_track` does; `artists = (performer.name,)` falling back to `album.artist.name`;
   `album.title`; `album.image.large`; `duration_ms = duration * 1000`; `isrc`; `streamable = item.get("streamable")
   is not False`; `service="qobuz"`; link from TRACK_LINKS. An item without `id` is skipped:
   `"{title} (no Qobuz ID)"`. `info`: `name`, `owner.id`/`owner.name`, `is_collaborative`, image (*check first:*
   `images300` / `image_rectangle` in streamrip's metadata, the largest present), `tracks_count`, `yours` = owner id
   equals the logged-in user's id when the client keeps it (*check first:* streamrip's `login` stores the user;
   else `yours=False`), `readable=True` (Qobuz answering is the test).
5. **3.5 Register** in `sources.SOURCES` and test the registry with both: a mixed `playlists.txt` reads both
   services through one `read` call, each logging in once, results in line order.

Tests (`tests/test_sources_qobuz.py`, new): recorded responses as JSON fixtures in `tests/fixtures/qobuz/`
(`playlist_page1.json`, `playlist_page2.json` for a 501-track playlist trimmed to the fields used, `private.json`
error body), a fake client whose `_api_request` returns them; pins pagination, every parse field, a preview-only
item (`streamable False`) kept in the list, every error kind and word, Stop during a page, and that no budget,
usage or pacer object is touched (pass none; the reader must not need one). Checks: that file, then the full suite.

## Group 4 — Exact id (Sonnet)

**Read list:** Global constraints, I5 (last paragraph), I6; `discjockey/acquire.py` lines 71–150, 409–469;
`grep -n "acquire(" discjockey/execute.py` and the call site's function; `tests/test_acquire.py` (`grep -n "def
test_"`, the fake Qobuz helper).

Tasks: **4.1** the exact step in `Acquirer.acquire` (I6); **4.2** `execute.py` passes `exact=action.qobuz_id`.
Tests as listed in I6, in `tests/test_acquire.py` and one in `tests/test_execute.py` (an acquire action with
`qobuz_id` reaches the acquirer). Checks: those two files, then the full suite.

## Group 5 — Bridge (Sonnet)

**Read list:** Global constraints, D2, D5, I4 (registry), I7, I8 (W4–W6, W9, W12, W13); `docs/hub-bridge-contract.md`
(`grep -n` for `spotify_url`, `spotify_duration_s`, `playlist_id`, `SpotifyStatus`, `add_playlist`, then those
sections); `discjockey/hub/api.py` lines 117–151 (`bridge`), 728–790; `discjockey/hub/views.py` lines 220–231,
574–603, 816–852, 1020–1046; `discjockey/hub/jobs.py` `grep -n "failed\|SetupProblem"`; `discjockey/report.py`
around line 59; `hub-ui/src/lib/bridge/types.ts` (`grep -n` the same names), `contract.ts`, `fake/bridge.ts`,
`fake/data.ts` (`grep -n "spotify_url\|playlist_id\|spotify"`).

Tasks:
1. **5.1 Playlists bridge** (`api.add_playlist`, `preview_playlist_change`, `views.playlists`, `views.info_dict`):
   I7's first two bullets. `_infos` / `_extra_tracks` keyed by ref. Tests: `tests/test_hub_api_playlists.py` — a
   Qobuz link adds with service and ref; W4 and W6 answers as `ok: false` with `service`; Spotify unchanged.
2. **5.2 Problems by service** (`api.bridge`, `run.SetupProblem` → `PreviewStore.failed`, `views.spotify_status`):
   the envelope's `service`, `problem_service`, `services` (I7). Tests: `tests/test_hub_views.py`,
   `tests/test_hub_sync.py` (a Qobuz login missing → `problem_service "qobuz"`, `services` lists it unconnected).
3. **5.3 Track link and renamed fields** (`views.track_detail`, `events.Checked`, `search_candidates`,
   `report.py`): I7's last three bullets, W9; `SourceChosen.how == "exact"` worded W12 wherever views word `how`.
   Tests: `tests/test_hub_views.py`, `tests/test_report.py`, `tests/test_hub_events.py` (schema fixture updated).
4. **5.4 Contract, types, fake** in the same commits as their Python changes: `docs/hub-bridge-contract.md`,
   `types.ts`, `contract.ts`, the fake backend and its scenarios (I7's last paragraph). Run `npx vitest run
   src/lib/bridge` and `npm run check` in `hub-ui`; never `npm run verify`.

Checks: the test files above while working; the full Python suite at the end.

## Group 6 — Hub words and Playlists page (Opus)

**Mandatory:** load the `apple-design` and `emil-design-eng` skills first; read `docs/hub-design-language.md`;
CLAUDE.md §12 applies (improve, don't preserve; consistency is absolute; pages use only the blocks; a missing pattern
is added centrally with gallery + design-language doc).

**Read list:** Global constraints, D1, D2, I7, I8 (W5, W6, W9, W10, W12–W14); `hub-ui/src/lib/components/AddRow.svelte`,
`SpotifyStatus.svelte`, `ProblemCard.svelte` (top comment + props), `hub-ui/src/lib/copy.ts`,
`hub-ui/src/pages/playlists/` (outline, `changeModel.ts` around line 112), `hub-ui/src/pages/sync/cardState.ts`
around line 42, `hub-ui/src/lib/stores/hub.ts` lines 40–60; `hub-ui/src/pages/settings/settingsModel.ts` (the
Qobuz card's route, for W6).

Tasks:
1. **6.1 Words**: W10 in `SpotifyStatus.svelte` and `copy.ts`; W13 in `cardState.ts`; W12 wherever `how` is shown;
   W14 in AddRow. The read is blocked only when a service in `services` isn't connected (`Connect {Name} first.`).
2. **6.2 Problems by service** (`copy.ts`, `ProblemCard`): `not_set_up` / `login_expired` / `playlist_unreadable`
   pick their copy by `service` (Qobuz: W6 card; unreadable hint from the engine's `info.hint`, never a
   hard-coded Spotify sentence — `AddRow`'s `UNREADABLE` and `changeModel.ts`'s constant go).
3. **6.3 The Playlists page shows which service a row is**: the row already shows the link; decide whether a
   service mark helps a DJ scanning a mixed list (stage 5 brings service icons to the sidebar — if a mark is added
   here, it is the block stage 5 will reuse, built centrally in `lib/components` with its gallery entry, sized
   for both). Critique the page at 1100 and 2560 with a Qobuz row in it. If anything visible changes beyond words,
   the report includes before/after screenshots (`shots.mjs --page playlists`).
4. **6.4 Fake scenarios and shots**: `shots.json` entries for the Qobuz row, `qobuz_unreadable`,
   `qobuz_not_connected`; model logic changed in `*.ts` gets its `*.test.ts`.

Checks: `npx vitest run` on the changed `*.test.ts`, `npm run check`, `npm run rules -- --page playlists --only …`
and `--page sync` for the touched shots, `npm run build` (its `build(hub): static` commit last). Never `npm run
verify` (the orchestrator runs it once).

## Group 7 — Docs (Sonnet)

**Read list:** Global constraints, D1, D2, I4, I8 (W1–W6); `README.md` (`grep -n "playlists.txt\|Spotify playlist\|
Qobuz"` and those sections); `CLAUDE.md` (the Layout table); `docs/issues.md` (top 40 lines).

Tasks: **7.1** README: `playlists.txt` takes Spotify and Qobuz playlist links (the accepted Qobuz forms, from
group 3's `recognise`), a Qobuz playlist must be public or yours, its tracks download by their exact Qobuz id,
reading a Qobuz playlist doesn't count against the daily limit, Qobuz must be logged in when `playlists.txt` has a
Qobuz line. **7.2** CLAUDE.md Layout: a `discjockey/sources/` row (one module per playlist service, the registry,
tokens) and the `discjockey/qobuz.py` row says it is the download client. **7.3** `docs/issues.md`: Q1 (Setup's
Spotify step for Qobuz-only users, waiting for the user), D2's rename of the read-status wire names (with stage 5),
stage 6's note that SoundCloud / YouTube Music track links aren't derivable from an id (`models.track_link` returns
None; store the link if a view needs it). Check: `scripts/check_public.sh`.

---

## Stage checks

- **Python:** each group's files while working; the full suite once per group (`uv run pytest -q | tail -3`); CI on
  the stage branch push before the merge.
- **Specific pins the stage review looks for:** the stage-2 round trip unchanged (review focus 1); the exact-id
  tests (2); the reader-touches-no-budget test (3); the four linking steps (4); `grep -rn "open.spotify.com/track"
  discjockey` only in `models.TRACK_LINKS`; `grep -rn SpotifyTrack` empty.
- **UI:** `npm run verify` once, by the orchestrator, in the background, before the merge (this stage changes
  `hub-ui`). Screenshots in fake mode: `node scripts/shots.mjs --port <p> --page playlists` (Qobuz row,
  `qobuz_unreadable`, `qobuz_not_connected`), `--page sync` (W10 read status, W13 length line, a `how=exact` card),
  `--page dashboard` (the header's read status words). The orchestrator looks at them itself.
- **Live check by the user — proposed, about 3 minutes, read-only:** Qobuz's `playlist/get` answer can't be checked
  offline (the fixtures are built from streamrip's parser, not from a real answer), and a wrong field name would
  make every Qobuz playlist look empty or unreadable. Nothing downloads and nothing counts against the limit. The
  user, in the new build: (1) on the Playlists page pastes the link of one of their own Qobuz playlists and checks
  that its name, owner and track count are right; (2) pastes a public Qobuz playlist of someone else, same check;
  (3) saves one of them and presses "↻ Read playlists" on Sync, then checks that its tracks appear in the plan
  with their right artists and titles (no sync started). If the user prefers, the orchestrator can do (1)–(3)
  itself with the user's go, in a scratch support folder that holds only a copy of the Qobuz login.

## Open question for the user

- **Q1.** Should Setup let a user skip Spotify when they only use Qobuz playlists? Today the Spotify step is
  required. Recommendation: not in stage 3 (D1); decide it with stage 5's sidebar work or when SoundCloud and
  YouTube Music arrive (stage 6), when more users have no Spotify at all.
