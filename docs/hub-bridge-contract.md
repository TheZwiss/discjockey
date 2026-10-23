# Discjockey hub — bridge contract (Part B → Part C)

Source of truth: `discjockey/hub/api.py` (methods), `discjockey/hub/views.py` (shapes), `discjockey/hub/jobs.py` (events).
Pinned by tests: `tests/test_hub_api*.py` (the page sees exactly these methods: `test_the_whole_contract_is_there`),
`tests/test_hub_views.py`, `tests/test_hub_fixture.py` (event schema). Examples below are real outputs from the test
library (lists cut to 2 items, `data` cut).

## Calling

- `await window.pywebview.api.<method>(arg1, arg2, ...)` — **positional** arguments in the order listed. Every method
  resolves (never rejects) to `{"ok": true, ...fields}` or `{"ok": false, "kind": <problem>, "message": <plain English>}`.
- Write methods return `{"ok": true, "job_id": <int>}` at once; the outcome arrives as a `JobFinished` event with the
  same `job_id` (see Jobs). At most one write job runs; others are refused with kind `busy` (hub) or `console`
  (a terminal run holds the lock).
- After a write job finishes, re-fetch the screens you show (`track`, `todo`, `sidebar`, ...). After a playlists save,
  `spotify.stale` is true: offer ↻ (`refresh()`). After a sync (finished, stopped or crashed) `sync_preview` is the
  plan worked out again from the sync's own Spotify read and the library as the run left it (`read_at` = that read,
  `stale` false), so what the run did is not offered again; only when state.json or settings.json can't be read then
  does the old plan stay, with `stale` true.
- Disable write buttons while `job_status().job.running` or `console_running`. ↻ is refused during the hub's own sync.

### Problem kinds (`kind` on ok:false, `problem` on JobFinished)

| kind | meaning / UI |
|---|---|
| `busy` | another hub job runs (or a refresh already runs) |
| `console` | a Discjockey run in the terminal holds the lock → read-only banner |
| `sync_running` | network read refused while any sync runs (searches, previews, playlist reads) |
| `not_set_up` | Spotify/Qobuz/playlists.txt not set up → wizard |
| `login_expired` | Spotify login expired → wizard Spotify step |
| `offline` | no connection / Spotify not answering → "No internet connection. Try again when you're online." + Retry |
| `playlist_unreadable` | a playlist can't be read → "make your own copy" hint |
| `config_invalid` | playlists.txt / settings.json / state.json needs fixing → show message |
| `qobuz_login_failed` | Qobuz login failed at sync start → wizard Qobuz step |
| `login_failed` | Spotify login in the wizard failed (port busy, timeout, refused) |
| `changed` | the track changed since it was shown → re-fetch, show message |
| `refused` | not possible (bad input, rule) → show message |
| `failed` | a download / login / tool step failed → show message |
| `stopped` | ended by Stop (nothing half done) |
| `protected` | the version is DRM-protected (yt-dlp refuses it; Discjockey never works around DRM) → the plain message; "Wrong song?" takes the version off its list, and later searches leave it out (`.cache/protected_sources.json`) |
| `no_library` | no music folder is bound (not chosen yet, or the chosen one isn't there) → Setup's music step or the missing-folder screen; every method in `LIBRARY_METHODS` answers it while unbound |
| `crashed` | unexpected error → "Something went wrong" + message (a sync: "The sync stopped unexpectedly. Everything done up to then is saved, and the next sync carries on from there."; any other bridge call: "Something unexpected went wrong. Try again, and if it keeps happening, restart Discjockey."); for a sync: + Open report. A crashed sync is filed like any run: its report (`reports/<run_id>.md`, exit code 1) starts with a plain crash note (when, the step it was on, that what was done is saved; no error type in it; the error and traceback only at the very end), its .json has `crashed` (that note); `RunFinished` (exit code 1, that report) comes first, and the `JobFinished` carries the same `result` as a finished sync. A crash in another job files nothing (`result` null) |

Use the kind for the card/headline; always show `message` as the detail.

## Shared shapes

**TrackRow** (library rows, to-do items, change moves; to-do items add `group`, `detail`; moves add `from`, `to`, `to_not_lossless`):
```json
{
 "track_id": "t2",
 "artist": "Armin Hermann",
 "title": "Get Naughty",
 "folder": "Hard_Bounce",
 "duration_s": 268.0,
 "status": "not_lossless",
 "quality": "weak",
 "quality_label": "16.0 kHz",
 "cutoff_hz": 16000,
 "source": "youtube",
 "source_name": "YouTube",
 "in_playlists": true,
 "hidden": false,
 "upgrade_ready": true,
 "path": "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff",
 "added": "2026-10-13T22:15:00",
 "cover_url": "https://i.scdn.co/image/t2"
}
```
- `status`: `lossless|not_lossless|fake_lossless|missing`. `quality` (colour): `lossless` green · `good_lossy` yellow ·
  `weak` red (cutoff ≤ 17 kHz) · `fake` purple · `missing` red. `quality_label`: `LOSSLESS`, `20.0 kHz`, `LOSSY`,
  `FAKE · 16.0 kHz`, `NOT FOUND`. `source`: `qobuz|youtube_music|soundcloud|youtube|manual|null`; `source_name` short
  (`Qobuz`, `YT Music`, `SoundCloud`, `YouTube`, `bought`). `cover_url`: media URL of the embedded cover, else the
  Spotify image URL (https), else null (show placeholder). `duration_s` float.
- **SpotifyStatus** (`spotify` field): `read_at` ISO|null, `minutes_ago` int|null, `problem` kind|null, `message`,
  `stale` bool, `reading` bool, `offline` bool (show last data with an "offline" badge), `auto_read` bool (the hub's
  one automatic read of this session has started, whatever its outcome; kept in Python, so also true after a window
  reload: the Sync page then never reads by itself).
- **Budget** (`qobuz_today`, `today`): `used, allowance, limit, carry_over, extra, remaining` (ints). "37 of 80 · 60 + 20 carried over".
- **RunSummary**: `run_id` (`YYYY-MM-DD_HHMMSS`), `started`, `finished`, `duration_s`, `exit_code` (0 ok, 1 some failed,
  130 stopped), `counts {lossless, lossy, problems, moved}`, `stopped_after` int|null ("stopped by you after N tracks").
- **Result** (report line; in `ActionFinished.result`, run sections, op results): `section, folder, artist, title,
  track_id|null, note, status|null, source|null, cutoff_hz|null, path|null, error_kind` (`network|qobuz|other|not_found|null`),
  `found_status|null` (`upgrade_ready`: the found file's status — a SoundCloud original can be lossless; `status` stays
  the current file's; null elsewhere. Missing in runs saved before it: then a Qobuz find counts as lossless, any other as lossy).
  Sections: see `discjockey/report.py SECTIONS` (new_lossless, new_not_lossless, fake, upgrade_ready, swapped, added_new,
  discarded, checked, bought, replaced, rejected, hidden, unhidden, moved, adopted, redownloaded, dropped, missing,
  queued, ambiguous, conflicts, skipped, recovered, errors).
- **rekordbox_check** (state.json entry field): null or `{reason: "wrong_song"|"added_as_new", since: "YYYY-MM-DD"}`.
  `wrong_song`: set by `use_candidate`/`use_link` when the old file was moved away to Superseded/, and by
  `reject_current` ("None of these"). `added_as_new`: set by `upgrade(id, "add_new")`. The next sync keeps it; only
  `rekordbox_checked(track_id)` clears it. The page sees it through `todo()`'s `rekordbox_check` group (the item's
  `detail` is the text to show) and the report section `rekordbox_check`; `track()` does not return it.
- `empty` fields: null or a first-run/empty state: `no_playlists`, `not_set_up`, `empty_library`, `no_preview`,
  `up_to_date`, `no_match`, `all_lossless`, `all_hidden`, `nothing_here`.

## Methods

### Read, any time

`dashboard()`
```json
{
 "ok": true,
 "greeting": "Good evening",
 "spotify": {
  "read_at": "2026-10-20T21:47:00",
  "minutes_ago": 0,
  "problem": null,
  "message": "",
  "stale": false,
  "reading": false,
  "offline": false,
  "auto_read": true
 },
 "tiles": {
  "lossless": {
   "share": 0.3333,
   "lossless": 1,
   "total": 3,
   "by_quality": {
    "lossless": 1,
    "good_lossy": 0,
    "weak": 1,
    "fake": 0,
    "missing": 1
   }
  },
  "qobuz_today": {
   "used": 0,
   "allowance": 80,
   "limit": 60,
   "carry_over": 20,
   "extra": 0,
   "remaining": 80
  },
  "still_to_load": {
   "count": 2,
   "days": 1,
   "fits_today": true
  },
  "account_today": {
   "service": "youtube",
   "name": "YouTube Premium",
   "set_up": true,
   "used": 3,
   "allowance": 30,
   "warnings": 0,
   "new_warnings": 0,
   "paused": false
  }
 },
 "ready": {
  "counts": {
   "new": 2,
   "retries": 0,
   "redownloads": 0,
   "moves": 0,
   "adopts": 0,
   "bought": 0,
   "weekly_checks": 0
  },
  "actions": 2,
  "duration_min": 5,
  "qobuz_limit": 60,
  "qobuz_needed": 2,
  "qobuz_left": 80,
  "qobuz_uses": 2,
  "accounts": [],
  "left": 80,
  "limit": 60
 },
 "needs_you": {
  "upgrades": 1,
  "swappable": 1,
  "not_found": 1,
  "weak": 1
 },
 "folders": [
  {
   "folder": "Hard_Bounce",
   "tracks": 3,
   "lossless_share": 0.3333,
   "by_quality": {
    "lossless": 1,
    "good_lossy": 0,
    "weak": 1,
    "fake": 0,
    "missing": 1
   }
  },
  {
   "folder": "Powertrance",
   "tracks": 0,
   "lossless_share": null,
   "by_quality": {
    "lossless": 0,
    "good_lossy": 0,
    "weak": 0,
    "fake": 0,
    "missing": 0
   }
  }
 ],
 "last_runs": [
  {
   "run_id": "2026-10-19_214700",
   "started": "2026-10-19T21:47:00",
   "finished": "2026-10-19T22:11:00",
   "duration_s": 1440,
   "exit_code": 0,
   "counts": {
    "lossless": 1,
    "lossy": 0,
    "problems": 0,
    "moved": 0
   },
   "stopped_after": null
  }
 ],
 "has_more_runs": false,
 "next_checks": 0,
 "empty": "not_set_up"
}
```
`ready` is null until Spotify was read; `next_checks` = weekly checks in the preview; `empty` as above. `ready` carries
the same `estimate` fields as `sync_preview`. `tiles.account_today`: the first set-up card of `limits()` (Qobuz first,
then YouTube Premium, then SoundCloud Go+), null when no service is set up.

`sidebar()` — counts for the sidebar (to-do badge, folders with file counts, Not in a playlist).
```json
{
 "ok": true,
 "todo": 2,
 "all_tracks": 2,
 "folders": [
  {
   "folder": "Hard_Bounce",
   "tracks": 2,
   "in_playlists_txt": true
  },
  {
   "folder": "Powertrance",
   "tracks": 0,
   "in_playlists_txt": true
  }
 ],
 "not_in_playlist": 0,
 "limits_warning": false
}
```
`limits_warning`: true when a set-up service has a warning sign the user hasn't marked as seen ("Got it",
`mark_warnings_seen`), or is paused today (the dot on "Download limits").

`sync_preview()` — the check before Start. Each action's `key` is sent back ticked to `start_sync`.
Group `key`s/labels in order: `acquire:new` Download (new), `acquire:retry` Try again, `acquire:redownload` Download
again, `move` Move to another folder, `adopt` Pick up a file you moved by hand, `adopt_bought` Add a bought file,
`upgrade` Look for a better version (weekly check). `key` is `[kind, track_id, to_dir]` (3 strings; example cut).
Every action row also has `run`: its index in the order the sync works through them (moves and adopts first, then
downloads, then weekly checks; inside each, playlists.txt order). Downloads of tracks in the "never download" list
are not in `groups` but in `never` (same rows, without `run`); marking or unmarking a track moves it at once, without
reading Spotify again. `folders` is the playlists.txt order, `in_playlists` the number of unique Spotify tracks read
(null before the first read). `estimate.duration_min` counts only the downloads that fit into today's Qobuz
allowance (`min(qobuz_needed, qobuz_left)` × 70 s, rounded to 5 min): the rest is queued at once and waits for the
next sync. `estimate.qobuz_limit` is the daily limit setting. `estimate.accounts` says which service the downloads
are expected to use, one entry per set-up service in quality order: `{service, name, uses, left, limit, about}`
(`uses` null for an account behind Qobuz, which only gets the tracks Qobuz lacks; `about` true for every service but
Qobuz: an estimate). `estimate.left` is today's remaining allowance (null = no limit) and `estimate.limit` the daily
limit; the `qobuz_*` fields are kept for one release. `estimate.minutes_by_downloads[n]` (sync_preview only, not
the dashboard's) is the time for `n` downloads, for `n = 0 … qobuz_uses` (the most any ticked subset can run today):
the page looks up the count of the actions the user ticked, so the formula (70 s a download, rounded to 5 minutes) is
in the engine only (`views.minutes_by_downloads`) and ticking needs no bridge call. In the same way, each entry of
`estimate.accounts` in `sync_preview` also has `uses_by_downloads[n]`: that service's `uses` for `n` downloads
(`n = 0 … qobuz_uses`, the engine's `views.split(n, …)`), or null for an account behind Qobuz. The page looks up the
ticked count (a larger count takes the last entry) for the service rows and never repeats the split.
```json
{
 "ok": true,
 "spotify": {
  "read_at": "2026-10-20T21:47:00",
  "minutes_ago": 0,
  "problem": null,
  "message": "",
  "stale": false,
  "reading": false,
  "offline": false,
  "auto_read": true
 },
 "counts": {
  "new": 2,
  "retries": 0,
  "redownloads": 0,
  "moves": 0,
  "adopts": 0,
  "bought": 0,
  "weekly_checks": 0
 },
 "groups": [
  {
   "key": "acquire:new",
   "label": "Download (new)",
   "actions": [
    {
     "key": [
      "acquire",
      "t4"
     ],
     "kind": "acquire",
     "reason": "new",
     "track_id": "t4",
     "artist": "Pegassi",
     "title": "AEIOU",
     "folder": "Hard_Bounce",
     "from_folder": null,
     "to_dir": "Library/Hard_Bounce",
     "to_not_lossless": false,
     "src": null,
     "cover_url": "https://i.scdn.co/image/t4",
     "run": 0
    },
    {
     "key": [
      "acquire",
      "t5"
     ],
     "kind": "acquire",
     "reason": "new",
     "track_id": "t5",
     "artist": "torbentorben",
     "title": "non stop",
     "folder": "Powertrance",
     "from_folder": null,
     "to_dir": "Library/Powertrance",
     "to_not_lossless": false,
     "src": null,
     "cover_url": "https://i.scdn.co/image/t5",
     "run": 1
    }
   ]
  }
 ],
 "estimate": {
  "duration_min": 5,
  "qobuz_limit": 60,
  "qobuz_needed": 2,
  "qobuz_left": 80,
  "qobuz_uses": 2,
  "accounts": [
   {
    "service": "qobuz",
    "name": "Qobuz",
    "uses": 2,
    "left": 80,
    "limit": 60,
    "about": false,
    "uses_by_downloads": [0, 1, 2]
   }
  ],
  "left": 80,
  "limit": 60,
  "minutes_by_downloads": [0, 5, 5]
 },
 "never": [],
 "folders": [
  "Hard_Bounce",
  "Powertrance"
 ],
 "in_playlists": 2,
 "ambiguous": [],
 "dropped": [],
 "notes": [],
 "empty": null
}
```

`refresh(auto=false)` → `{"job_id"}` — read-only Spotify read: "↻ Read Spotify", and by itself whenever
playlists.txt changes on disk (mtime or size, checked every 2 s; retried until no hub sync blocks it). `auto=true`: the
session's one automatic read (the hub when it opens; the Sync page when it opens and `spotify.auto_read` is still
false, e.g. the hub's own read could not start). It sets `spotify.auto_read` when it starts; later `auto=true` calls are
refused (`refused`), so a stopped or failed automatic read is never redone by itself. Each playlist read emits
`ReadingPlaylist`. Outcome: `JobFinished` kind `refresh`, `result {"actions": n}`; on problems (`offline`, ...) the
last preview stays with `spotify.problem` set.
`stop_refresh()` → `{"stopped": bool}`. The read's `JobFinished` (`stopped`) comes at once, also while one slow
Spotify request is still under way; that request's late answer is dropped (the last preview stays).

`job_status()` — snapshot after a reload. `sign_in`: null or the browser sign-in's snapshot, same shape as `job` (see
Settings). `job`: null or `{id, kind, track_id, started, running, stopping, last:
{<EventType>: <last event of that type>}, usage: [<AccountUsage>], results: [<ActionFinished events>], finished: <JobFinished>|null, actions:
[{kind, track_id, title, artist, image_url}]}`. `usage`: the newest `AccountUsage` event of each service, in the order the
services first reported (`last` keeps only the newest one overall) — the "Qobuz 42 of 80 today" lines after a reload; `[]` until
a download counted. `actions`: the run's planned actions in the order the run does them (copied from
`RunStarted.actions`; `[]` until a run started, and for jobs without a run) — "Up next" and the time left after a
reload.
```json
{
 "ok": true,
 "job": null,
 "refresh_running": false,
 "console_running": false,
 "spotify": {
  "read_at": "2026-10-20T21:47:00",
  "minutes_ago": 0,
  "problem": null,
  "message": "",
  "stale": false,
  "reading": false,
  "offline": false,
  "auto_read": true
 }
}
```

`library(folder=null, query="", filter="all", sort="artist")` — folder: null (All tracks), `"__not_in_playlist__"`, or
a folder name. filter: `all|lossless|good_lossy|weak|fake|upgrade_ready`. sort:
`title|artist|length|source|quality|added|folder` (folder: tracks in no playlist last), prefix `-` for descending. Only
tracks with a file. `summary` is the folder at a glance and ignores the search and the filter: `by_quality` (as in
`dashboard`), `upgrades_ready`, and `to_do`, the tracks of the folder the to-do list shows (in a playlist, not hidden).
```json
{
 "ok": true,
 "title": "Hard_Bounce",
 "folder": "Hard_Bounce",
 "summary": {
  "tracks": 2,
  "lossless_share": 0.5,
  "by_quality": {
   "lossless": 1,
   "good_lossy": 0,
   "weak": 1,
   "fake": 0,
   "missing": 0
  },
  "upgrades_ready": 1,
  "to_do": 1
 },
 "chips": {
  "all": 2,
  "lossless": 1,
  "good_lossy": 0,
  "weak": 1,
  "fake": 0,
  "upgrade_ready": 1
 },
 "rows": [
  {
   "track_id": "t2",
   "artist": "Armin Hermann",
   "title": "Get Naughty",
   "folder": "Hard_Bounce",
   "duration_s": 268.0,
   "status": "not_lossless",
   "quality": "weak",
   "quality_label": "16.0 kHz",
   "cutoff_hz": 16000,
   "source": "youtube",
   "source_name": "YouTube",
   "in_playlists": true,
   "hidden": false,
   "upgrade_ready": true,
   "path": "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff",
   "added": "2026-10-13T22:15:00",
   "cover_url": "https://i.scdn.co/image/t2"
  },
  {
   "track_id": "t1",
   "artist": "Vatoz Locoz",
   "title": "Gimme Gimme",
   "folder": "Hard_Bounce",
   "duration_s": 156.0,
   "status": "lossless",
   "quality": "lossless",
   "quality_label": "LOSSLESS",
   "cutoff_hz": null,
   "source": "qobuz",
   "source_name": "Qobuz",
   "in_playlists": true,
   "hidden": false,
   "upgrade_ready": false,
   "path": "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff",
   "added": "2026-10-13T22:15:00",
   "cover_url": "https://i.scdn.co/image/t1"
  }
 ],
 "empty": null
}
```

`track(track_id)` — details panel (Library and To-do).
```json
{
 "ok": true,
 "track": {
  "track_id": "t2",
  "artist": "Armin Hermann",
  "title": "Get Naughty",
  "folder": "Hard_Bounce",
  "duration_s": 268.0,
  "status": "not_lossless",
  "quality": "weak",
  "quality_label": "16.0 kHz",
  "cutoff_hz": 16000,
  "source": "youtube",
  "source_name": "YouTube",
  "in_playlists": true,
  "hidden": false,
  "upgrade_ready": true,
  "path": "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff",
  "added": "2026-10-13T22:15:00",
  "cover_url": "https://i.scdn.co/image/t2",
  "isrc": null,
  "playlists": [
   "Hard_Bounce",
   "Powertrance"
  ],
  "in_playlist_count": 2,
  "quality_line": "YouTube OPUS · cutoff 16.0 kHz",
  "source_url": "https://www.youtube.com/watch?v=abcdefghijk",
  "spotify_url": "https://open.spotify.com/track/t2",
  "next_qobuz_check": null,
  "rejected_sources": [],
  "buy_links": {
   "beatport": "https://www.beatport.com/search?q=Armin+Hermann+Get+Naughty",
   "bandcamp": "https://bandcamp.com/search?q=Armin+Hermann+Get+Naughty"
  },
  "free_downloads": [],
  "bought_name": "Library/Hard_Bounce/Armin Hermann - Get Naughty.wav",
  "audio_url": "http://127.0.0.1:62534/YpzDYco76287ItHFL8xqv4xIFYLjaPBy/Library/Hard_Bounce/not_lossless/Armin%20Hermann%20-%20Get%20Naughty.aiff?v=11-1792150089412432418",
  "upgrade": {
   "file": "Upgrades ready/Hard_Bounce/Armin Hermann - Get Naughty.aiff",
   "source": "qobuz",
   "source_name": "Qobuz",
   "source_id": "q2",
   "found": "2026-10-18",
   "what": "lossless version",
   "quality_line": "Qobuz FLAC · verified lossless",
   "alignment": {
    "drift_ms": 0.0,
    "offset_ms": 0.0,
    "offset_samples": 0,
    "result": "exact",
    "text": "matches exactly"
   },
   "cue_text": "matches exactly, cues stay",
   "swap_safe": true,
   "swap_possible": true,
   "audio_url": "http://127.0.0.1:62534/YpzDYco76287ItHFL8xqv4xIFYLjaPBy/Upgrades%20ready/Hard_Bounce/Armin%20Hermann%20-%20Get%20Naughty.aiff?v=15-1792150089395813784"
  }
 }
}
```
`next_qobuz_check`: ISO date, `"next_sync"`, or null. `playlists`: null until Spotify was read.
`upgrade`: null or the parked version; `what` names it ("lossless version" or e.g. "256 kbps version"); Swap only
when `swap_safe && swap_possible`; `cue_text` is the line to show.

`track()`'s `free_downloads` (added 2026-10-18): the artists' free downloads found on SoundCloud while the track is
not lossless, each `{"url", "host", "direct", "title", "uploader"}`, e.g. `{"url": "https://hypeddit.com/djtallboy/x",
"host": "hypeddit.com", "direct": false, "title": "WHERE HAVE YOU BEEN", "uploader": "DJ TALLBOY"}`; `direct: true` is
SoundCloud's own download button (`url` is then the SoundCloud page). Empty when none is known. `quality_line` of a
lossy download carries the bitrate when known ("YouTube Music OPUS 135 kbps · cutoff 20.1 kHz"). A dropped bought
file may be WAV, AIFF, FLAC or MP3.

Also in `track()` (2026-10-18, details redone as facts): `format_line` ("Opus · 135 kbps", "FLAC", "uncompressed PCM";
the bitrate only for a lossy download) and `source_full` ("YouTube Music", "bought"), both null without a file.
`todo()` items carry `free: bool` (a not found, weak, good lossy or fake track with a free download: the row's FREE
tag); the `detail` of lossy and fake rows is the source and bitrate ("YT Music · 131 kbps", "Qobuz"), as the badge
already says the kHz.

`todo(filter="all", show_hidden=false)` — filter: `all|rekordbox_check|upgrade_ready|not_found|weak|good_lossy|fake|other`.
Groups always in that order; `chips` counts exclude hidden; `hidden_count` for "Show hidden (N)". First group
`rekordbox_check` (label "Check in rekordbox", hint "the file changed; rekordbox needs a hand"): every track with a
`rekordbox_check`, also hidden tracks and tracks no longer in a playlist; `detail` is what to do in rekordbox ("This
track now plays the right song. In rekordbox: analyse it again and delete the old cues (they belong to the wrong
song)." / "This is a different edit. In rekordbox: analyse it again and set the cues again."); its button calls
`rekordbox_checked(track_id)`. A track can be in two groups (e.g. Check in rekordbox and Not found); `chips.all`
counts each track once, `chips.rekordbox_check` every check (hidden ones too).
```json
{
 "ok": true,
 "chips": {
  "all": 2,
  "rekordbox_check": 0,
  "upgrade_ready": 1,
  "not_found": 1,
  "weak": 0,
  "good_lossy": 0,
  "fake": 0,
  "other": 0
 },
 "hidden_count": 0,
 "show_hidden": false,
 "groups": [
  {
   "key": "upgrade_ready",
   "label": "Upgrade ready",
   "hint": "a better version is waiting for you",
   "items": [
    {
     "track_id": "t2",
     "artist": "Armin Hermann",
     "title": "Get Naughty",
     "folder": "Hard_Bounce",
     "duration_s": 268.0,
     "status": "not_lossless",
     "quality": "weak",
     "quality_label": "16.0 kHz",
     "cutoff_hz": 16000,
     "source": "youtube",
     "source_name": "YouTube",
     "in_playlists": true,
     "hidden": false,
     "upgrade_ready": true,
     "path": "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff",
     "added": "2026-10-13T22:15:00",
     "cover_url": "https://i.scdn.co/image/t2",
     "group": "upgrade_ready",
     "detail": "matches exactly, cues stay"
    }
   ]
  },
  {
   "key": "not_found",
   "label": "Not found",
   "hint": "nothing usable anywhere",
   "items": [
    {
     "track_id": "t3",
     "artist": "Some Artist",
     "title": "Gone Track",
     "folder": "Hard_Bounce",
     "duration_s": 180.0,
     "status": "missing",
     "quality": "missing",
     "quality_label": "NOT FOUND",
     "cutoff_hz": null,
     "source": null,
     "source_name": null,
     "in_playlists": true,
     "hidden": false,
     "upgrade_ready": false,
     "path": null,
     "added": "2026-10-13T22:15:00",
     "cover_url": "https://i.scdn.co/image/t3",
     "group": "not_found",
     "detail": "next try in 5 days"
    }
   ]
  }
 ],
 "empty": null
}
```

`playlists()` — rows top = highest priority. `info` null until read (refresh or add_playlist); `tracks` null when
neither the tracks nor the playlist's count were read (the row then shows no count). `version` must be sent to
`save_playlists`. `overlaps` for the panel when nothing is unsaved: each track that is in several switched-on
playlists, with `folders` (in list order) and `lands_in` (the first), its `cover_url`, `downloaded` (has a file yet),
`quality` and `quality_label` (null without a state entry), `never` (the user said "never download").
`problem`: what the sync would say about the file.
```json
{
 "ok": true,
 "version": "481d45b7d451c816dd949d1a86b559bf9083ef5d02f69831f870dafbccffc36b",
 "problem": null,
 "rows": [
  {
   "index": 0,
   "folder": "Hard_Bounce",
   "link": "https://open.spotify.com/playlist/0DiscjockeyExampleList",
   "playlist_id": "0DiscjockeyExampleList",
   "enabled": true,
   "info": {
    "name": "Name of 0Dis",
    "owner_name": "DJ One",
    "yours": true,
    "collaborative": false,
    "readable": true,
    "image_url": null,
    "track_count": 4
   },
   "tracks": 4,
   "quality": {
    "lossless": 1,
    "good_lossy": 0,
    "weak": 1,
    "fake": 0,
    "missing": 2
   }
  },
  {
   "index": 1,
   "folder": "Powertrance",
   "link": "https://open.spotify.com/playlist/3DiscjockeyExampleList",
   "playlist_id": "3DiscjockeyExampleList",
   "enabled": true,
   "info": {
    "name": "Name of 3Dis",
    "owner_name": "DJ One",
    "yours": true,
    "collaborative": false,
    "readable": true,
    "image_url": null,
    "track_count": 2
   },
   "tracks": 2,
   "quality": {
    "lossless": 0,
    "good_lossy": 0,
    "weak": 1,
    "fake": 0,
    "missing": 1
   }
  }
 ],
 "overlaps": [
  {
   "track_id": "t2",
   "artist": "Armin Hermann",
   "title": "Get Naughty",
   "cover_url": "https://i.scdn.co/image/t2",
   "downloaded": true,
   "quality": "weak",
   "quality_label": "16.0 kHz",
   "folders": [
    "Hard_Bounce",
    "Powertrance"
   ],
   "lands_in": "Hard_Bounce"
  }
 ],
 "empty": null
}
```

`limits(service="qobuz")` — the Download limits page. `service`: `qobuz|youtube|soundcloud` (else refused). `cards`: always
all three services in quality order `{service, name, set_up, used, allowance, warnings, new_warnings, paused}`
(`warnings` = signals of the last 14 days, `new_warnings` = those after the last "Got it", `paused` = an `auto_stop`
today; a service that is not set up has zeros). `usage` is null when
`service` is not set up, else the page of that service: `days`: 14 entries oldest first (cut here); `zones` (5 entries;
Qobuz and SoundCloud: careful 1–40, normal 41–60, faster 61–79, fast 80–100, risky 101–500; YouTube: careful 1–20, normal
21–30, faster 31–45, fast 46–60, risky 61–500); `recommended`: 60 Qobuz, 30 YouTube, 60 SoundCloud. `behind`: "Qobuz"
for an account while Qobuz is set up (it only gets the tracks Qobuz lacks; `still_to_load` is then all null and
`what_if.days_to_load` null), else null. `signals` of the last 14 days `{time, kind, message, new, clears_in}` (`new`:
after the time in settings.json `warnings_seen[service]`, or never marked; `clears_in`: days until it leaves the 14 days,
1 = tomorrow); `signal_summary` has a
count for every kind of the service: Qobuz `login_failed, search_failed, download_rejected, preview_only,
duration_mismatch, auto_stop`; YouTube `cookies_unreadable, bot_check, rate_limited, refused, premium_missing,
download_rejected, auto_stop`; SoundCloud the same without `bot_check`. `last_download`: ISO time of the last download
of that service that counted toward its limit (any day), null if none yet ("last download 21:47").
```json
{
 "ok": true,
 "service": "qobuz",
 "cards": [
  {
   "service": "qobuz",
   "name": "Qobuz",
   "set_up": true,
   "used": 0,
   "allowance": 80,
   "warnings": 0,
   "new_warnings": 0,
   "paused": false
  },
  {
   "service": "youtube",
   "name": "YouTube Premium",
   "set_up": false,
   "used": 0,
   "allowance": 0,
   "warnings": 0,
   "new_warnings": 0,
   "paused": false
  },
  {
   "service": "soundcloud",
   "name": "SoundCloud Go+",
   "set_up": false,
   "used": 0,
   "allowance": 0,
   "warnings": 0,
   "new_warnings": 0,
   "paused": false
  }
 ],
 "usage": {
  "service": "qobuz",
  "name": "Qobuz",
  "behind": null,
  "today": {
   "used": 0,
   "allowance": 80,
   "limit": 60,
   "carry_over": 20,
   "extra": 0,
   "remaining": 80
  },
  "days": [
   {
    "date": "2026-10-07",
    "used": 0
   },
   {
    "date": "2026-10-08",
    "used": 0
   }
  ],
  "still_to_load": {
   "count": 2,
   "days": 1,
   "fits_today": true
  },
  "setting": {
   "limit": 60,
   "extra_today": 0,
   "recommended": 60,
   "zones": [
    {
     "name": "careful",
     "from": 1,
     "to": 40
    },
    {
     "name": "normal",
     "from": 41,
     "to": 60
    }
   ],
   "min": 1,
   "max": 500,
   "extra_max": 200
  },
  "assessment": {
   "level": 2,
   "label": "normal"
  },
  "what_if": {
   "limit": 60,
   "extra_today": 0,
   "assessment": {
    "level": 2,
    "label": "normal"
   },
   "allowance_today": 80,
   "remaining_today": 80,
   "days_to_load": 1,
   "run_minutes": 5
  },
  "signals": [],
  "signal_summary": {
   "login_failed": 0,
   "search_failed": 0,
   "download_rejected": 0,
   "preview_only": 0,
   "duration_mismatch": 0,
   "auto_stop": 0
  },
  "last_download": null
 }
}
```

`limits_what_if(service, limit, extra_today=0)` — "What N per day means" while the slider moves (no write). The service
must be set up (else refused "Set up YouTube Premium first."); `limit` 1–500, `extra_today` 0–200. For an account behind
Qobuz `days_to_load` is null.
```json
{
 "ok": true,
 "limit": 90,
 "extra_today": 20,
 "assessment": {
  "level": 4,
  "label": "fast"
 },
 "allowance_today": 140,
 "remaining_today": 140,
 "days_to_load": 1,
 "run_minutes": 5
}
```

`runs()` → `{"runs": [RunSummary, newest first]}`. `run(run_id)` → the end screen:
```json
{
 "ok": true,
 "run": {
  "run_id": "2026-10-19_214700",
  "started": "2026-10-19T21:47:00",
  "finished": "2026-10-19T22:11:00",
  "duration_s": 1440,
  "exit_code": 0,
  "counts": {
   "lossless": 1,
   "lossy": 0,
   "problems": 0,
   "moved": 0
  },
  "stopped_after": null,
  "sections": {
   "new_lossless": [
    {
     "section": "new_lossless",
     "folder": "Hard_Bounce",
     "artist": "Vatoz Locoz",
     "title": "Gimme Gimme",
     "track_id": "t1",
     "note": "Qobuz FLAC · verified lossless",
     "status": "lossless",
     "source": "qobuz",
     "cutoff_hz": null,
     "path": "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff",
     "error_kind": null,
     "found_status": null,
     "cover_url": "https://i.scdn.co/image/t1"
    }
   ]
  },
  "needs_you": [],
  "for_rekordbox": {
   "new_files": 1,
   "folders": [
    "Library/Hard_Bounce"
   ]
  },
  "upgrades_ready": 1,
  "report_md": "reports/2026-10-19_214700.md",
  "queued": 0,
  "folder_order": ["Hard_Bounce", "Powertrance"]
 }
}
```
Every row with a `track_id` except `queued` carries `cover_url` (the file's own cover, else Spotify's, else null).
`queued`: how many tracks wait for the next sync (stopped before, left out, over the limit). `folder_order`: the
playlist folders in playlists.txt order, for grouping the rows.

`spectrum(track_id, which="current")` — which: `current|upgrade`. `data`: base64 of `cols*bands` bytes, row by row
in time, each row low→high frequency (band width `max_hz/bands`); byte v → dB = `floor_db * (1 - v/255)` (0 dB =
loudest cell). Draw the cutoff line at `cutoff_hz` (null = none). `waveform`: base64 of `cols` bytes, one per column
(the same columns as the matrix): the largest sample anywhere in that column's stretch of the track (1/`cols` of its
length), 0 = silence, 255 = the loudest column, linear. A kick's attack shows as its peak; the matrix's mean energy
would not show it. Files cached before the field existed are made again.
```json
{
 "ok": true,
 "spectrum": {
  "cols": 400,
  "bands": 128,
  "max_hz": 22050,
  "duration_s": 1.0,
  "floor_db": -100.0,
  "data": "////////////////////////////////////////...",
  "waveform": "//////////////////////////////////...",
  "which": "current",
  "cutoff_hz": 16000
 }
}
```

`media_url(track_id, which="current")` → `{"url"}` playable by `<audio>` / `fetch` (range requests work). The URL
changes when the file changes (`?v=size-mtime`).

`setup_status()` — `next_step`: `music|tools|spotify|downloads|playlists|null`; open the wizard when `complete` is false. `music` = MusicStatus `{state: ok|not_chosen|missing, path, suggested}`: `ok` the music folder is bound, `not_chosen` Setup's first step, `missing` config.json names a folder that isn't there (an unplugged drive); `path` the bound or missing folder, `suggested` the default to offer (`~/Music/Discjockey`). Unbound, `playlists` is false and `complete` false. `downloads` is Setup's Downloads step (Qobuz and the other download logins): done when Qobuz is signed in or left out.
`version`: `discjockey.__version__` (Settings → About shows it).
`qobuz_skipped`: "I don't have Qobuz" was chosen, the `downloads` step then counts as done (`qobuz` itself stays false).
`accounts`: `youtube` and `soundcloud`, each null or `{browser, browser_name, daily_limit, profile, profile_name,
last_check}` (`browser`: `safari|chrome|firefox|brave|edge`; `profile` the browser profile's folder, null = the
default or Safari's only one; `last_check` LastCheck|null, see Settings).
```json
{
 "ok": true,
 "music": {"state": "ok", "path": "/Users/dj/Music/Discjockey", "suggested": "/Users/dj/Music/Discjockey"},
 "tools": {
  "ffmpeg": true,
  "ffprobe": true,
  "deno": true
 },
 "spotify_app": false,
 "spotify_login": false,
 "qobuz": false,
 "playlists": true,
 "complete": false,
 "next_step": "spotify",
 "version": "1.0.0",
 "qobuz_skipped": false,
 "accounts": {
  "youtube": null,
  "soundcloud": {
   "browser": "chrome",
   "browser_name": "Chrome",
   "daily_limit": 60
  }
 }
}
```

`select(track_id|null)` → `{}` — call whenever the to-do selection changes (drops go to this track).

### Read with network (refused with `sync_running` while any sync runs)

`search_candidates(track_id)` → `{track_id, spotify_duration_s, current_quality_label, candidates: [Candidate],
notes: [str]}`. Candidate: `source, id, title, artist, duration_s|null, url|null, isrc, album, label, image_url, key,
source_name, length_diff_s|null, can_preview, score (0–100|null), matches, length_ok, current, rejected`. The current
version is first (`current: true`, "you marked it as wrong"); colour `length_diff_s` green within ±3 s. Send a
Candidate back unchanged to `preview` / `use_candidate`.

`preview(track_id, candidate)` → `{"url"}` — 30 s AIFF for youtube_music/soundcloud/youtube only (`can_preview`);
qobuz → refused "Qobuz versions have no preview." Plays 20 s of it in the UI.

`add_playlist(url)` — pasted link.
```json
{
 "ok": true,
 "playlist_id": "37i9dQZF1DXcBWIGoYBM5M",
 "link": "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",
 "info": {
  "name": "Name of 37i9",
  "owner_name": "DJ One",
  "yours": true,
  "collaborative": false,
  "readable": true,
  "image_url": null,
  "track_count": 0
 },
 "tracks": 0,
 "readable": true,
 "suggested_folder": "Name_of_37i9",
 "hint": null
}
```
`hint` (when not readable): "Follow ≠ own: … make your own copy …". Add the row with `link`
and `suggested_folder` (editable).

`preview_playlist_change(lines)` — `lines`: `[{"folder", "link", "enabled"}]` in the new order (top first).
`kind`: `moves|rename|reroute|add|switch_off|unknown|none`; `headline` ready to show; `checklist` 4 lines (cut here);
`moves`: tracks with a file that move; `reroutes`: tracks without a file yet that will land in another folder
(`track_id`, `artist`, `title`, `cover_url`, `downloaded`, `quality`, `quality_label`, `never`, `from`, `to`). `reroute`: only
such tracks change ("24 tracks will go to 03_06_2026 instead of Powertrance"), no file moves;
`problem`: what is wrong with the lines (Save would be refused), else null.
```json
{
 "ok": true,
 "kind": "moves",
 "headline": "1 track change folder",
 "folders": [
  {
   "folder": "Powertrance",
   "before": 1,
   "after": 2
  },
  {
   "folder": "Hard_Bounce",
   "before": 4,
   "after": 3
  }
 ],
 "moves": [
  {
   "track_id": "t2",
   "artist": "Armin Hermann",
   "title": "Get Naughty",
   "folder": "Hard_Bounce",
   "duration_s": 268.0,
   "status": "not_lossless",
   "quality": "weak",
   "quality_label": "16.0 kHz",
   "cutoff_hz": 16000,
   "source": "youtube",
   "source_name": "YouTube",
   "in_playlists": true,
   "hidden": false,
   "upgrade_ready": true,
   "path": "Library/Hard_Bounce/not_lossless/Armin Hermann - Get Naughty.aiff",
   "added": "2026-10-13T22:15:00",
   "cover_url": "https://i.scdn.co/image/t2",
   "from": "Hard_Bounce",
   "to": "Powertrance",
   "to_not_lossless": true
  }
 ],
 "reroutes": [],
 "new_downloads": 0,
 "days": 0,
 "stopped": 0,
 "unknown": [],
 "checklist": [
  "No downloads, no Qobuz quota used",
  "Nothing is deleted"
 ],
 "problem": null
}
```

### Write jobs (→ `{"job_id"}`; outcome in `JobFinished.result`)

| method (positional args) | job kind | JobFinished.result |
|---|---|---|
| `start_sync(selected)` — list of ticked `key`s from `sync_preview` | `sync` | `{exit_code, report, actions, new_since_preview}` (`report`: absolute .md path); also on a `crashed` sync (`exit_code` 1, `report` its crash note; `actions` 0 when it crashed before the plan) |
| `stop()` → `{"stopped": bool}` (not a job) — Stop safely: current write job (sync, download, Spotify login) | | |
| `save_playlists(lines, loaded_version)` | `save_playlists` | `{version}`; problem `changed` = "playlists.txt was changed elsewhere…" |
| `save_limits(service, limit, extra_today)` — the service must be set up (else refused); 1–500, 0–200 (0 clears the extra) | `save_limits` | `{service, limit, extra_today}` |
| `mark_warnings_seen(service)` — "Got it" on Download limits; the service must be set up (else refused). Saves settings.json `warnings_seen[service]` = now: its signals up to now are no longer `new` | `mark_warnings_seen` | `{service, seen_until}` |
| `hide(track_id, hidden)` | `hide` / `unhide` | OpResult |
| `never_download(track_id, never)` — the track must be in the current preview (else `changed`) | `never_download` | `{track_id, never}`; saves `state.never` and rewrites not_lossless.md |
| `add_bought_file(track_id)` — after a `FileDropped` with `readable: true` for this track; when the call is refused (e.g. `busy`) the dropped file is kept, so "Add" can be tried again without a new drop | `add_bought_file` | OpResult |
| `use_candidate(track_id, candidate)` | `use_candidate` | OpResult |
| `use_link(track_id, url)` — Qobuz track / YouTube / YT Music / SoundCloud link | `use_link` | OpResult |
| `reject_current(track_id)` — "None of these"; sets `rekordbox_check` (`wrong_song`) | `reject_current` | OpResult |
| `rekordbox_checked(track_id)` — "Done" on a "Check in rekordbox" item: clears `rekordbox_check` | `rekordbox_checked` | OpResult (`result.section` `rekordbox_checked`, note "checked in rekordbox") |
| `upgrade(track_id, mode)` — `swap|add_new|discard` | `upgrade_swap` / `upgrade_add_new` / `upgrade_discard` | OpResult |

`use_candidate` / `use_link` are refused (problem `refused`) before any request to Qobuz (no login, no link lookup,
nothing counted) with the messages of `ops.refusal`: "This is the version you have now." (the candidate is the
current file); "Your current file is not where Discjockey expects it. Run a sync first, so it can find the file again."
(the file was moved in Finder); for Qobuz versions while Qobuz is paused "Not downloaded: Qobuz is paused, because
several Qobuz requests in a row failed (a warning sign for the account). Discjockey sends Qobuz nothing more until the
next sync starts. A YouTube Music or SoundCloud version still works."; and when the daily limit is used up "Not
downloaded: daily Qobuz limit reached. Try again tomorrow, or allow a few extra downloads on the Qobuz page." When the
old file was moved away to Superseded/, the entry gets `rekordbox_check` (`wrong_song`).

`upgrade(track_id, "add_new")`: the current file moves to `Superseded/<Folder>/` and the new lossless file gets the
correct name `Library/<Folder>/<Artist - Title>.aiff` (no "(lossless)"; an ID suffix only if another file has that
name); the entry gets `rekordbox_check` (`added_as_new`), because rekordbox relinks the old entry by name but its cues
fit the old edit.

OpResult = `{"track_id", "result": Result, "recovered": [[message, ok], ...]}` (interrupted steps finished first; show
them). The single operations check that the track still looks as the page last showed it (via `track`, `todo` or
`library`); call one of those before. Example:
```json
{
 "type": "JobFinished",
 "job_id": 2,
 "kind": "hide",
 "ok": true,
 "problem": null,
 "message": "",
 "result": {
  "track_id": "t2",
  "result": {
   "section": "hidden",
   "folder": "Hard_Bounce",
   "artist": "Armin Hermann",
   "title": "Get Naughty",
   "track_id": "t2",
   "note": "hidden from the to-do list",
   "status": null,
   "source": null,
   "cutoff_hz": null,
   "path": null,
   "error_kind": null,
   "found_status": null
  },
  "recovered": []
 }
}
```

Download jobs (`use_candidate`, `use_link`, `sync`) send the engine events (SourceChosen, Progress, ...) too.

Report section `rekordbox_check` ("Check in rekordbox", in `run(run_id).sections` and the .md report): every track
that still has a `rekordbox_check` when the run's report is written, `note` = the same text as the to-do `detail`.

### Other

`show_in_finder(track_id, which="current")`, `reveal(rel_path)` (inside the music folder only, e.g.
`"Library/Hard_Bounce"`, `".discjockey/reports"`; `"."` is the music folder itself), `open_report(run_id)`, `open_licenses()` (the licences folder, `Contents/Resources/licenses` in the app, in Finder; refused
when it is missing: "The licences folder is missing from this copy of Discjockey."), `open_external(url)` (https only,
system browser) → `{}`.

`app_update()` (immediate, also without a music folder: not a library method) →
`{"state": "available" | "up_to_date" | "unknown", "current": "1.0.0", "latest": "1.1.0" | null,
"url": "https://github.com/TheZwiss/discjockey/releases/tag/v1.1.0" | null}`. It is the last answer of the update
check (spec public-release §8) and never touches the network itself. `unknown` means no answer yet (offline, rate
limit, or a version that isn't plain), and then the page shows nothing. `latest` and `url` are set only for
`available`, and the page opens `url` with `open_external`. Read it at boot; the `AppUpdate` event brings later
changes.

`quit()` (immediate) — closes the hub window (after `update_tools` or `rollback_tools` with `restart`: the page says
"Open Discjockey again" first, then calls it). Refused with `busy` ("Discjockey is still busy with a change. Wait until
it has finished, then quit.") while a write job runs; otherwise `{}` and the window closes about 0.3 s later.

### Setup wizard

`setup_check_tools()` (immediate):
```json
{
 "ok": true,
 "tools": {
  "ffmpeg": true,
  "ffprobe": true,
  "deno": true
 },
 "missing": [],
 "hints": {},
 "redirect_uri": "http://127.0.0.1:8888/callback",
 "download_tools": {
  "yt-dlp": {"version": "2026.10.21", "source": "updated", "waiting": null, "previous": "2026.10.14"},
  "streamrip": {"version": "2.1.0", "source": "built_in", "waiting": null, "previous": null}
 },
 "download_tools_problem": null
}
```

`download_tools` (Settings → This Mac): per tool the `version` this window runs, `source` `built_in` (came with
Discjockey) or `updated` (Update download tools), `waiting` the version the next start uses when it differs (an update
or a step back waits for a reopen), `previous` the version **Go back** would use (null: nothing to go back to).
streamrip is always `built_in` with null `waiting`/`previous`. If reading them fails unexpectedly, `download_tools` is
null and `download_tools_problem` holds a plain sentence (the logged detail stays out of it); the rest of the check
still answers. Otherwise `download_tools_problem` is null.

| method | job kind | result |
|---|---|---|
| `setup_save_client_id(client_id)` (32 hex; bad format refused at once) | `setup_save_client_id` | `{}` |
| `setup_spotify_login()` — opens the system browser; ends by itself, after 5 min (`login_failed`), or with `stop()` (`stopped`) → show Retry | `setup_spotify_login` | `{user}` |
| `setup_qobuz_login(email, password)` — also stores `qobuz_last_check` (ok, or `login_failed` when Qobuz refuses the login; being offline or a Qobuz hiccup records nothing); a failed login puts the previous streamrip config back. An account made with Google, Apple or Facebook first sets a Qobuz password at `https://www.qobuz.com/signin/forget-password` (the page opens it with `open_external`) | `setup_qobuz_login` | `{}` (`failed` + message) |
| `setup_skip_qobuz()` — "I don't have Qobuz": the Qobuz step counts as done | `setup_skip_qobuz` | `{}` |
| `setup_account(service, browser, profile?)` — `service` `youtube|soundcloud`, `browser` `safari|chrome|firefox|brave|edge`, `profile` that browser's profile folder (null: the default); checks the login in that profile (only cookie names are read), then saves the browser, the profile and the check (`last_check`). A YouTube login without Premium is not saved; a SoundCloud one is. A failed check of the saved login itself (same browser and profile) is recorded on it | `setup_account` | `{service, browser, profile, saved, check}` (`check` = AccountCheck) |
| `setup_forget_account(service)` — removes the saved browser of that account | `setup_forget_account` | `{service}` |
| `update_tools()` — the newest yt-dlp (+ the yt-dlp-ejs it pins) from PyPI into the support folder, tested in its own process before use; streamrip only changes with Discjockey releases. `failed` + a plain sentence (never a traceback or an OS error text) when: offline ("Couldn't reach the download server..."), the server answers with an error status ("The download server has a problem right now..."), its answer is not understood, there is no wheel for this Mac, the download was damaged, the disk refuses (the sentence names the reason in plain words: full, not allowed, refused), or the new version failed its test. The tools in use always stay. `stopped` when Stop is pressed (the test process ends too) | `update_tools` | `{before: {"yt-dlp": v}, after: {"yt-dlp": v}, restart}` — `before`/`after` the version the next start uses before/after; `restart` true when that isn't the version this window runs → ask to reopen, then `quit()`; already the newest: `before == after` (`restart` still true when an earlier update waits for a reopen) |
| `rollback_tools()` — back to the yt-dlp used before the last update (the folder stepped back from is deleted unless this window runs it); `refused` "There is no earlier version to go back to."; disk problems as `update_tools` | `rollback_tools` | `{before, after, restart}` as `update_tools` |

`setup_check_account(service)` (immediate; refused with `sync_running` during any sync, and with `refused` when the account is
not set up) — the saved login checked again → `{"service", "check"}`. AccountCheck = `{ok, problem, kbps, message}`:
`problem` `cookies_unreadable|not_logged_in|no_premium|failed|null`, `kbps` the stream quality found (int|null),
`message` the sentence to show.
```json
{
 "ok": true,
 "service": "youtube",
 "check": {
  "ok": true,
  "problem": null,
  "kbps": 256,
  "message": "..."
 }
}
```


### Settings

Signing in through the browser (spec settings-setup §5, §7, §13). Only cookie *names* are read, from copies; macOS
never asks for a password while Discjockey looks. A sign-in runs in its own slot beside the write jobs (no library lock:
waiting changes nothing), one at a time; `job_status().sign_in` is its snapshot (`last.SignInPhase` = where it is).
A sync may start while it waits; the check then doesn't run. Every settings write takes the library lock: a write job
holds it already, a sign-in or `setup_check_account` takes it for the moment of the save and is answered `busy` /
`console` instead of waiting (one writer at a time).

| method | kind | result / notes |
|---|---|---|
| `find_logins(service)` — `youtube\|soundcloud` | immediate | `{browsers: [{id, name, default, readable, problem, profiles: [{id, name, signed_in}]}]}`: the installed browsers, the default one first. `problem` `no_access` (Safari without Full Disk Access) \| `locked` \| null; `profiles[].id` null = Safari's only profile |
| `account_sign_in(service, browser, profile?)` — refused with `sync_running` during any sync, `busy` while another sign-in waits, `refused` for a browser that isn't installed | job `account_sign_in` (sign-in slot) | Opens the sign-in page in that browser (that Chrome/Brave/Edge profile in its own window; Firefox and Safari open their default profile), then looks every 3 s: for Chrome/Brave/Edge with a profile only that profile's login counts, otherwise a login in any profile of the browser (the chosen one first). `SignInPhase` `waiting` → `checking`; then like `setup_account`: `{service, browser, profile, saved, check}`, `profile` the one whose login was found. Ends `failed` after 10 minutes ("Didn't see a login in 10 minutes. Sign in again.") or at once when macOS refuses the browser's files (the Full Disk Access message); `stopped` by `stop_sign_in()`; `sync_running` ("… Check again after the sync.") when a sync started while it waited (no check runs); `busy` / `console` when the login was checked but a write job or a terminal run held the lock at the save (nothing saved) |
| `stop_sign_in()` | immediate | `{stopped}` — Cancel on a waiting sign-in; `stop()` never ends it, and it never ends a sync |
| `open_privacy_settings()` | immediate | `{}` — System Settings at Full Disk Access |
| `qobuz_check_login()` — refused with `sync_running` during any sync | job `qobuz_check_login` | `{}`: logs in with the saved login and searches once; stores `qobuz_last_check`: `login_failed` only when Qobuz refuses the login, `search_failed` when logged in but the search finds nothing (then `failed` + message). Offline, a Qobuz error or a failed search store nothing (the last check stays) and end `failed` with a plain message |
| `spotify_sign_out()` | job `spotify_sign_out` | `{}`: forgets the Spotify login; the Client ID stays |

`setup_account(service, browser, profile?)` saves the profile and the check (`last_check`) with the login; its result
carries `profile`. A failed check of the saved login (same browser and profile) is recorded on it, so Settings shows
"not signed in" instead of a stale ✓. `setup_check_account` records its check the same way (answered `busy` / `console` when a write job or a terminal run
holds the lock at the save).

`setup_status()` also carries `qobuz_last_check` (LastCheck\|null), `spotify_user` (the display name saved at the
Spotify login, null when not connected) and, per account, `profile`, `profile_name`, `last_check`.

`downloads_view()` (immediate) — the source ladder and the account panels of Settings and Setup (spec
settings-setup §4, §6.4): each download source's state and the library counted by rung.
- `qobuz.state`: `on` · `off` (not signed in, or its last login check failed) · `skipped` ("I don't have Qobuz") ·
  `paused` (stopped itself today) · `used_up` (today's allowance used).
- An account's `state`: `on` · `off` (not set up, or its last check found no login / failed) · `no_premium` ·
  `unreadable` (macOS didn't let Discjockey read the browser's login) · `paused` · `used_up`.
- `last_check` = LastCheck `{ok, problem, kbps, at}` (null: never checked since it was saved). `profile` is the
  browser profile's folder (null: the default one); `profile_name` its display name (null when it can't be read).
- `tracks`: Qobuz — live tracks from Qobuz; an account — live lossy tracks from its source at about 256 kbps.
- `library`: live tracks (in a playlist, not hidden): `lossless`; `account` = lossy stream downloads at ≥ 200 kbps;
  `free` = the lower or unknown ones (an artist's lossless original counts as lossless).
```json
{
 "ok": true,
 "downloads": {
  "qobuz": {"state": "on", "last_check": {"ok": true, "problem": null, "kbps": null, "at": "2026-10-22T09:15:00"}, "tracks": 412},
  "youtube": {"state": "off", "browser": null, "browser_name": null, "profile": null, "profile_name": null,
              "last_check": null, "tracks": 0},
  "soundcloud": {"state": "no_premium", "browser": "chrome", "browser_name": "Chrome", "profile": "Profile 2",
                 "profile_name": "DJ", "last_check": {"ok": false, "problem": "no_premium", "kbps": 128, "at": "2026-10-22T10:00:00"},
                 "tracks": 0},
  "library": {"lossless": 412, "account": 0, "free": 31}
 }
}
```

### The music folder

Where the library lives (spec public-release §4). The hub opens without one: Setup's first step chooses it, and
`setup_status().music` says where things stand. These four methods work without a bound folder.

| method | kind | result / notes |
|---|---|---|
| `pick_folder(start?)` | immediate | `{path}`: the Mac's folder dialog, opened at `start`, else `~/Music` (the nearest folder that exists). `path` null when the user cancelled. `refused` when no window dialog exists |
| `check_music_folder(path)` | immediate | FolderCheck `{path, exists, usable, problem, kind, message}`; changes nothing. `path` is the resolved folder. `usable` false: `problem` names why and `message` says it in plain words. `kind` (usable folders): `new` (not there yet, made on the user's choice) · `empty` · `discjockey_library` (a Discjockey library already) · `other_files` (the page asks before using it). `problem`: `not_absolute` · `not_a_folder` · `system_folder` · `inside_app` · `is_support_dir` · `not_writable` |
| `set_music_folder(path)` | immediate | `{music: MusicStatus, restart}`: uses the folder (made when new). Without a bound library (none chosen, or the chosen one missing) it is bound at once, `restart` false. A bound library is never swapped while the window is open: the choice is saved and `restart` is true, then the page calls `quit()`. The folder already in use again changes nothing (`restart` false). Refused: `refused` with the check's message, `busy` while a change runs, `console` while a terminal run holds the library |
| `retry_music_folder()` | immediate | `{music}`: the missing-folder screen's Try again; binds the library when the folder is back; `music.state` becomes `not_chosen` when `config.json` no longer names a folder. With a library bound already (see "bound but missing" below) there is nothing to bind: it answers the status, `ok` once the folder is back |

While no music folder is bound, every method in `LIBRARY_METHODS` answers `no_library` before anything runs, with
"Choose your music folder first: it is the first step of Setup." (not chosen) or "Your music folder isn't there:
{path}. Connect the drive it is on, or choose another folder." (missing). `LIBRARY_METHODS` (api.py, `contract.ts`;
a test compares them): `dashboard`, `sidebar`, `sync_preview`, `refresh`, `library`, `track`, `todo`, `playlists`,
`limits`, `limits_what_if`, `save_limits`, `mark_warnings_seen`, `runs`, `run`, `spectrum`, `media_url`,
`search_candidates`, `preview`, `add_playlist`, `preview_playlist_change`, `start_sync`, `save_playlists`, `hide`,
`never_download`, `add_bought_file`, `use_candidate`, `use_link`, `reject_current`, `rekordbox_checked`, `upgrade`,
`show_in_finder`, `reveal`, `open_report`. Everything else works without a music folder, `open_licenses` included (Setup and Settings before one
is chosen); `downloads_view()` then counts zero tracks.

**Bound but missing.** A folder that vanishes while the hub runs (an unplugged drive) behaves as an unbound one: every
`LIBRARY_METHODS` method answers `no_library` with "Your music folder isn't there any more. Connect the drive it is on,
then try again. Nothing was changed." (`library.MUSIC_GONE`), and `setup_status().music` is `{state: "missing", path}`
with the bound folder's path. It is never shown as an empty library. The bridge client calls the hub store's
`refreshOnNoLibrary` on any `no_library` answer, so the shell reads `setup_status` again and shows the missing screen
whichever page asked. Nothing is rebound while the window lives: `retry_music_folder` answers `ok` when the folder is
back, and "Choose another…" saves the other folder and returns `restart: true` (the page calls `quit()`).

## Events

The window must define `window.dj = { onEvent(event) {...} }`; the hub calls it with one object per event. Every
event has `type` (class name) plus the fields below. Exact JSON schema: `tests/fixtures/hub_events.schema.json`
(regenerated by `scripts/record_hub_events.py`; `test_the_schema_is_up_to_date` fails on any rename). Recorded
streams to replay: `tests/fixtures/hub_events_sync.jsonl` (refresh + full sync: move, Qobuz lossless, not found,
YouTube Music lossy, network error, weekly check parking an upgrade) and `hub_events_stopped.jsonl` (Stop during
the third action).

| type | fields |
|---|---|
| `JobStarted` | `job_id` int, `kind` str, `track_id` str\|null |
| `JobFinished` | `job_id`, `kind`, `ok` bool, `problem` kind\|null, `message` str, `result` object\|null |
| `ConsoleBusy` | `running` bool (terminal run started/ended → banner, read-only) |
| `FileDropped` | `track_id` str\|null, `name` str, `readable` bool, `message` str ("macOS didn't let Discjockey read this file…" / "Select the track…") |
| `SignInPhase` | `service` (`youtube\|soundcloud`), `phase` `waiting\|checking`, `browser`, `browser_name` — a sign-in through the browser (Settings, Setup) |
| `AppUpdate` | `state`, `current`, `latest`, `url` as `app_update()` — sent when the update check's answer changes (at start, then at most daily) |
| `RunStarted` | `total` int, `actions` [{`kind`, `track_id`, `title`, `artist`, `image_url` str\|null}] — every action of the run in the order the run does them ("Up next", time left; `image_url`: Spotify's cover for the rows) |
| `ActionStarted` | `index` (1-based), `total`, `action` {kind, track_id, folder, track {id, title, artists[], album, image_url, duration_ms, isrc}, order [int,int], src, dest_dir, aliases[], reason} |
| `StepChanged` | `track_id`, `step`: `search|download|check|convert|analyse|compare` |
| `Progress` | `track_id`, `step`, `done` number, `total` number\|null, `unit` `bytes` (download) \| `seconds` (conversion) |
| `Waiting` | `kind` `search|between|break|fallback`, `label`, `remaining` s, `total` s, `service` (`qobuz`, `youtube`, `soundcloud`; empty for free sources) — pause card only for `between`/`break` |
| `SourceChosen` | `track_id`, `source`, `query_kind` `isrc|name|fallback|chosen`, `title`, `duration_s`\|null ("Qobuz by ISRC") — sent before the protection pause (`Waiting` `between`/`break`) that precedes a Qobuz download, so the pause card can name the next source |
| `Checked` | `track_id`, `file_duration_s`, `spotify_duration_s`, `codec`, `ok` ("Length matches (3:12 = Spotify 3:12)") |
| `AccountUsage` | `service`, `used`, `allowance` ("Qobuz 42 of 80 today") |
| `ActionFinished` | `action` (as above), `result` Result — Problems = sections missing/errors/conflicts/ambiguous; `error_kind: network` → "NO INTERNET" |
| `RunFinished` | `exit_code` (0, 1, 130), `report_path` (.md) — then `run(run_id)` with the report's stem for the end screen; also sent for a crashed sync (1, its crash note), before its `JobFinished` |
| `Message` | `level` `info|warning|debug`, `text` (hide debug) |
| `ReadingPlaylist` | `index`, `total`, `folder` — before each playlist is read (a refresh, or a sync's start) |

Pause card: the pause runs inside the next action after its `ActionStarted` and search, so "next up" is the current
action and "after that N more" = `total - index`. Progress and Waiting may be coalesced when the page lags (only the
latest is sent). The pause card's source is the latest `SourceChosen` of the current action.
