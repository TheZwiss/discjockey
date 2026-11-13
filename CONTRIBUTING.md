# Contributing to Discjockey

Notes for running Discjockey from its source code, changing it and releasing it. [README.md](README.md) is the
user's manual: read it for how a feature behaves from the user's side. The binding project rules (invariants,
layout, commands, how docs and plans are kept) are in [CLAUDE.md](CLAUDE.md); this file doesn't repeat them.

## Getting started

You need a Mac with Apple Silicon, [uv](https://docs.astral.sh/uv/) and, for the window's interface, Node.js.

```
git clone https://github.com/TheZwiss/discjockey.git
cd discjockey
uv sync
cd hub-ui && npm ci
```

`bin/discjockey` is the launcher: it runs `uv sync`, then the engine (`python -m discjockey`). `bin/discjockey hub`
opens the window; `DISCJOCKEY_HUB_DEBUG=1 bin/discjockey hub` keeps its log in the terminal.

Your own library and logins live in the support folder `~/Library/Application Support/Discjockey/`. To try things
without touching them, point Discjockey at a scratch folder: `DISCJOCKEY_SUPPORT=/tmp/dj bin/discjockey hub` (Setup
then asks for a music folder). Without the app, ffmpeg, ffprobe and deno come from your `PATH`
(`brew install ffmpeg deno`).

## The Terminal version

The engine also runs in Terminal. `bin/discjockey setup` asks Setup's questions there, the music folder first (it
needs a real Terminal window), and at the end prints a line that lets you type just `discjockey`:

```
discjockey --dry-run      shows what would happen, changes nothing
discjockey                shows the plan, asks "Proceed?", then does it
discjockey --limit 10     only the first 10 downloads
discjockey --extra 20     allows 20 more Qobuz downloads today only
discjockey upgrades       goes through the waiting lossless versions
discjockey update         gets the newest yt-dlp
discjockey --yes --json   runs a sync without a question and prints one JSON object (below)
discjockey settings auto-upgrade off    turns Auto-upgrade off (below)
```

- The Mac stays awake while a run goes (`caffeinate`). Ctrl-C once stops safely after the current track; Ctrl-C
  again stops at once. Both are safe, and the next run continues where this one stopped.
- `discjockey upgrades` offers the To-do page's choices as letters: **s** swap, **a** add as a new file, **d**
  discard, **f** show in Finder, **l** later (or Enter), **q** quit. A swap that has started is finished first, even
  on Ctrl-C. It writes a report of what you decided.
- While a Terminal run is busy, the window's buttons that change something are switched off.

### Commands for scripts and agents

Every command runs without prompts and ends with an exit code. Where it has `--json`, it prints one JSON object:
`{"ok": true, …}`, or `{"ok": false, "kind": "refused" | "failed", "message": "…"}` (a refusal also has a `reason`).
Issue 39 gathers these into the agent docs; the entries below are the ones issue 33's stages A, B and C added.

Someone who installed the app has no `discjockey` command, but the app's program takes the same ones: in the
Terminal, `/Applications/Discjockey.app/Contents/MacOS/Discjockey rekordbox backups` (any of the commands, in place of
`discjockey`; the README's restore advice uses it). `app_main.py` hands an argument list that starts with one of
`CLI_COMMANDS` to `cli.main`, and anything else opens the window.

**`discjockey rekordbox status [--json]`** says whether rekordbox's library can be read. Read only: it takes no
library lock and needs no music folder. JSON: `{"ok", "state", "running", "version", "library", "problem",
"db_version"}`. `state` is `ready`, `none` (no rekordbox library on this Mac) or `unreadable` (Discjockey can't open
this rekordbox version's library yet). `problem` is `null`, `unclean` (rekordbox didn't close normally: it left
`-wal` or `-shm` files behind; reading still works), `busy` (rekordbox is open and holds its library), `key`,
`db_version` or `schema` (why it is unreadable). Exit 0 whenever it answered, 1 on an unexpected error.

**`discjockey rekordbox preview (<track> | --path <file>) [--json]`** says what Same track, Convert to AIFF and Give
it its clean name would do for one file, and why not. Read only, no lock, nothing written, but it decodes the file
(1 to 3 seconds). `<track>` is the song's key; `--path` takes any file (a file the library doesn't know still gets the
rekordbox part, and every action says `not_in_library`). JSON:

```
{"ok": true, "track": "<key>" | null, "file": "<path>", "codec", "sample_rate", "bits",
 "new_file": "<path>" | null, "superseded": "<path>" | null,
 "rekordbox": {"state", "running", "problem"},
 "timing": {"result", "offset_samples": int | null},
 "entries": [{"id", "cues", "grid", "pwv3", "offset_ms", "expected_ms", "score", "cloud", "fields_kept": []}],
 "eligible": {"same_track": null | "<reason>", "convert": null | "<reason>", "rename": null | "<reason>"}}
```

`eligible` is `null` for an action that can run, else the reason key (`no_upgrade`, `needs_choice`, `file_missing`,
`away`, `rekordbox_unreadable`, `timing`, `not_analysed`, `cloud`, `downloaded`, `clean_aiff`, `named_already`,
`needs_convert`, `no_name`, `not_in_library`, `auto_refused`; the list is `rekordbox/eligible.py`'s `REASONS`).
`timing.result` is how rekordbox's timeline for the file was found: `no_rekordbox`, `not_in_rekordbox`, `format`,
`no_cues`, `measured` (then `offset_samples` is the exact shift, in 44.1 kHz samples), `not_analysed`, `timing` or
`unreadable` (the last three: unknown). `new_file` and `superseded` are the paths the first action that can run would
use (nothing is reserved); `fields_kept` names the text fields of the rekordbox track the user edited, which a later
repoint would leave alone. Exit 0 when it answered; 1 when it refused (`reason`: `unknown_track`, `file_missing`,
`away` for a file on a drive that isn't connected) or failed (a file ffmpeg can't read); 2 when a song key was given
and there is no music folder (`reason: "no_library"`). A usage error (a missing or conflicting argument) also exits 2,
but prints argparse's usage as text on stderr, not JSON: only a JSON answer with `reason: "no_library"` means the
music folder is missing.

When you run these two commands by hand on a Mac that has a real rekordbox, always set both overrides first:
`DISCJOCKEY_SUPPORT=<scratch folder> DISCJOCKEY_REKORDBOX=<a fixture folder or an empty folder> bin/discjockey rekordbox
status|preview …`. Without them they read the real rekordbox library and your real music folder. An empty
`DISCJOCKEY_REKORDBOX=` also means "no rekordbox library".

### Upgrade, batch and rekordbox commands (issue 33, stage B)

These change files, Discjockey's records and, for Same track, rekordbox's library, so each one that changes anything
takes the library lock the hub takes (and finishes interrupted steps first), and **an agent's command counts as the
user starting it**: never delete a file (replaced files move to `Superseded/`), Same track writes rekordbox only while
rekordbox is closed, takes a backup first and can be undone. Read commands take no lock. All of them find the music
folder like the hub and are meant to be run by hand only with both overrides set (above). Progress lines ("2 of 5:
Artist - Title") go to stderr; with `--json` stdout holds exactly one JSON object.

| Exit | Meaning |
|---|---|
| 0 | done for every track, or a dry run, or a read |
| 1 | refused or failed, or some tracks were skipped or failed (each result says why) |
| 2 | no music folder or no setup (`reason: "no_library"`); a usage error also exits 2 with argparse's text on stderr |
| 3 | busy: the library lock or `rekordbox.lock` is held by another window or Terminal |
| 4 | rekordbox is open: nothing was done, or the batch stopped there (quit rekordbox, then `batch resume <id>`) |
| 5 | stopped by Ctrl-C between tracks (`batch resume <id>`); the sync's own 130 stays for the sync |

Every command that changes something, when it finished an interrupted step first (`library.recover_pending`), also
prints `"recovered": [[message, ok], …]` (the messages in words); without such a step the key is absent.

**`ok` and the exit code.** `{"ok": true, …}` means the command ran to its end: a batch that finished with some tracks
skipped or failed is still `ok: true` (each track's `state` and `reason` are in `results`), and its exit code is 1.
`{"ok": false, "kind": "refused" | "failed" | "busy" | "rekordbox_open" | "stopped", "reason"?, "message", …}` is for a
problem: nothing could start, or the job did not end. A problem of a batch carries the batch's own fields too
(`batch`, `state`, `stop_reason`, `total`, `done`, `skipped`, `failed`, `results`, `backup`), so the id to resume is
always there. One result per track: `{"track", "action", "state": "planned" | "done" | "skipped" | "failed",
"reason", "message", "path", "rekordbox": null | {"entries": [rekordbox track ids], "kept": [fields the DJ edited]}}`;
`reason` is an `eligible.REASONS` key for a skip.

**Ctrl-C.** Once: stop between tracks (the track in work finishes or rolls back; exit 5). A second press, a second
later: stop at once; what is finished stays saved.

**`discjockey upgrade list [--json]`** lists the parked better versions as To-do shows them (a song in a playlist or
the user's own file, its sound judged, not hidden). Read only. JSON: `{"ok", "count", "upgrades": [{"track",
"artist", "title", "folder", "file", "parked", "now", "new", "alignment", "same_track": null | "<reason>",
"auto_refused": null | {"reason", "message", "at"}, "auto_waits": bool}]}`. `same_track` is `null` when Same track can
run for it (the quick answer: the run asks again and may still skip it), else the reason. `auto_refused` is the
refusal the sync's Auto-upgrade recorded on the track (`timing`, `not_analysed`, `cloud`, `space`, `needs_choice`),
`auto_waits` is `true` when the last sync met rekordbox open for it, Auto-upgrade is on and `same_track` is `null` (the hub's To-do shows the mark under the same condition). Song keys for the
commands below come from here.

**`discjockey upgrade apply (<track>… | --all) --way same-track|new-track [--dry-run] [--json]`**. `same-track` is
one AIFF batch (`aiff_batches` in `library.db`): a file that isn't an AIFF becomes a new AIFF and rekordbox's track
is pointed at it; an AIFF is swapped in place. `--all` is "Upgrade all" (every track Same track can run for;
`started_by` `upgrade_all`, else `user`). `new-track` runs the named tracks one after the other (no batch, no backup,
`batch: null` in the result). `--all` with `new-track` exits 1 (`kind: "refused"`, `reason: "all_needs_same_track"`).
JSON: `{"ok", "batch": <id> | null, "state": "done", "stop_reason", "total", "done", "skipped", "failed", "results",
"backup": <backup id> | null}`. When nothing could run the answer is a refusal (`ok: false`, `kind: "refused"`, the
one track's `reason`, or none for several). Exit 4 (rekordbox open) and exit 5 (Ctrl-C) leave the batch `stopped`
(`stop_reason` `rekordbox_open` / `stop`), and exit 3 with `rekordbox.lock` held by another window or Terminal leaves
it `stopped` (`busy`); those are resumable with `batch resume`. Exit 3 for the library lock records no batch at all.
A batch of one named track (not `--all`) that meets rekordbox open or `rekordbox.lock` busy before anything ran is
closed instead (its song is skipped with that reason and stays in Upgrade ready; there is nothing to resume), as the
window's single Replace does. Starting a batch for songs an earlier stopped batch still has `planned` closes those
items there (`skipped`, reason `later_batch`), so each song waits in one batch only.
`--dry-run` takes no lock, writes nothing and decodes nothing: per track `{"track", "action", "state": "planned" |
"skipped", "reason", "file", "new_file", "superseded"}`, plus `{"ok", "dry_run": true, "way", "total", "planned",
"skipped", "space": [{"drive", "needed", "free", "enough"}], "rekordbox": {"state", "running",
"needs_rekordbox_closed"}}`. It says the run checks each track again.

**`discjockey upgrade discard <track>… [--json]`** throws the better versions away (the current files stay).
**`discjockey upgrade undo <track>… [--json]`** puts each track's replace back (files, records and, for Same track,
rekordbox's text and path), one job. Both print the batch shape with `batch: null` (discard) or `{"ok", "batch":
null, "total", "undone", "refused", "failed", "results": [{"track", "state": "undone" | "refused" | "failed" |
"waiting", "reason", "message"}]}` (undo). Undo with rekordbox open and a rekordbox change to take back exits 4 and
undoes nothing (`waiting`). An undo that undid nothing at all ends `{"ok": false, "kind": "refused", "message", …}`
with the same fields (the one track's own message, else "None of these could be undone.") and exit 1, as the window's
job fails `refused`.

**`discjockey batch list [--json]`** (the newest batches: `{"ok", "count", "batches": [{"batch", "kind",
"started_by", "state": "running" | "stopped" | "done", "stop_reason", "started", "ended", "total", "done", "skipped",
"failed", "planned", "undone", "backup"}]}`), **`batch show <id> [--json]`** (that row plus `results`),
**`batch resume <id> [--json]`** (runs the `planned` tracks of a stopped batch again, each asked again; a batch that
isn't stopped exits 1 with `reason: "not_stopped"`) and **`batch undo <id> [--json]`** (undoes the batch's done
tracks, newest first; a track that can't be undone stays listed with its reason and the exit is 1). An unknown id
exits 1 (`reason: "unknown_batch"`).

**`discjockey rekordbox checked (<track>… | --batch <id>) [--json]`** is "Done, checked in rekordbox": the reminder
goes away and with it the undo. JSON: `{"ok", "checked": [keys], "not_checked": [keys]}`; a key with nothing to check
exits 1, a batch's tracks checked earlier are not an error.

**`discjockey rekordbox backups [--json]`** lists the copies of rekordbox's library Discjockey made before a batch
(`.discjockey/rekordbox/backups/`): `{"ok", "backups": [{"id", "created", "batches", "tracks", "size"}]}`.
**`discjockey rekordbox restore <backup> --yes [--json]`** puts rekordbox's whole library back as the backup holds it
and drops every change made in rekordbox since; without `--yes` it changes nothing and exits 1 (`reason:
"needs_yes"`). It refuses while rekordbox is open (exit 4), for an unknown, damaged or foreign backup, and with
`-wal`/`-shm` files beside the library (exit 1, `reason`: `not_found`, `damaged`, `other_library`, `unclean`,
`no_rekordbox`). It saves the current library first: `{"ok", "restored", "saved_current", "missing_after": [{"id",
"path", "was"}]}`. `missing_after` lists the rekordbox tracks that now point at files Discjockey has since moved to
`Superseded/`; undo those batches first (`batch undo`) or Relocate them in rekordbox.

### The sync's `--json` and `settings auto-upgrade` (issue 33, stage C)

**`discjockey [--yes | --dry-run] --json`** is the sync with one JSON object on stdout at the end; every human line
goes to stderr. A command never prompts, so `--json` without `--yes` and without `--dry-run` exits 1 and changes
nothing (`{"ok": false, "kind": "needs_yes", "message"}`). JSON:

```
{"ok": true, "exit_code": 0 | 1 | 130, "dry_run": bool, "report": "<path of the .md>" | null,
 "counts": {"<section>": n}, "auto_upgrade": <block> | null}
```

`ok` is `true` when the sync ran to its end: `exit_code` 1 is a run with errors (they are in the report's `errors`
section), 130 a run stopped with Ctrl-C (the first press stops after the current step, a second one, a second later,
at once; what is finished stays saved). `counts` are the report's sections with their number of results
(`report.SECTIONS` keys, such as `new_lossless`, `upgraded`, `upgrade_waits`, `errors`); a dry run has `report: null` and
counts the plan's actions (`acquire:new`, `acquire:retry`, `acquire:redownload`, `adopt_bought`, `upgrade`). Problems
are `{"ok": false, "kind", "message"}`: exit 2 for a setup problem (`kind` is the setup problem's own: `not_set_up`,
`login_expired`, `offline`, `playlist_unreadable`, `config_invalid`, `qobuz_login_failed`) or no music folder
(`kind: "refused"`, `reason: "no_library"`), exit 3 `busy` (another run holds the library lock), exit 1 `crashed` (the
sync stopped on an unexpected error; `report` names the crash note) or `failed`, 130 `stopped` (Ctrl-C before the run
started). The exit code 4 of the batch commands is not used: rekordbox being open is a normal end of a sync, and the
block says so.

`auto_upgrade` is the run's Auto-upgrade block, the same object the report's `.json` holds under `"auto_upgrade"`;
`null` when the switch is off (the sync then moves no file and looks at nothing of rekordbox):

```
{"batch": <id> | null, "backup": "<backup id>" | null, "done": n, "waiting": n, "refused": n, "failed": n,
 "stopped": bool, "dry_run": bool,
 "results": [{"track": "<key>", "name": "Artist – Title", "state": "done" | "would" | "waiting" | "refused" | "failed",
              "reason": null | "<key>", "message": "…" | null, "how": "in_place" | "new_aiff"}]}
```

`waiting` counts the tracks that wait for rekordbox to be closed (`reason: "rekordbox_open"`) or for the next sync
(`not_reached` after Stop, `busy`, and any skip nothing is recorded for, such as `changed` or `unclean`: its row keeps
that reason and its specific `message`); `refused` only the ones To-do says why about (`reason` one of `timing`,
`not_analysed`, `cloud`, `space`, `needs_choice`, its `message` the words To-do shows; a refusal still held from an
earlier sync is listed again, not tried, also while rekordbox is open); failures
are also in the report's `errors`. A dry run has `batch: null`, `done: 0` and `would` rows, and writes nothing.
`how` is `in_place` for an AIFF swapped in place and `new_aiff` for a new AIFF that rekordbox's track is pointed at.

**`discjockey settings auto-upgrade [on|off] [--json]`** is Settings › Upgrades from the Terminal ("Upgrade
automatically when I sync", on by default; a settings file without the key reads as on). Without a value it prints
the current one and takes no lock; with one it takes the library lock, saves, and prints "Upgrade automatically when
I sync: on|off". JSON `{"ok": true, "auto_upgrade": bool}`. Exit 0; 1 when the settings file can't be read
(`reason: "settings_invalid"`, nothing is written over it); 2 no music folder; 3 busy (the library lock is held;
nothing changed). `settings` is a group so the other settings can join it (issue 39).

Never start a real sync, upgrade swap or Qobuz download while working on the code unless you mean to: it changes
your library and counts against your Qobuz daily limit. `--dry-run` changes nothing.

## Tests

```
uv run pytest -q
```

Tests are offline: `tests/conftest.py` blocks the network and PyPI and stubs yt-dlp, and every test library lives in
a temporary folder. The audio tests need ffmpeg and ffprobe on your `PATH` and skip without them. The workflow
test also runs `actionlint` on both workflows when it is installed (`brew install actionlint`) and skips without it,
so CI, whose runner has none, never lints them: run the tests on a Mac with it before changing a workflow.

## The window's interface (`hub-ui/`)

Read [docs/hub-design-language.md](docs/hub-design-language.md) first: it holds the design rules, the blocks every
page is built from and the rule checker. From `hub-ui/`:

| What | Command |
|------|---------|
| Dev server with a fake backend (no engine, no network) | `npm run dev`, then pick a state with `?scenario=…` or the toolbar |
| Type check, unit tests, design rules, trial build | `npm run verify` |
| Build into `discjockey/hub/static/` (committed) | `npm run build` |
| Smoke test of the built page in WebKit | `npm run smoke` (after a build) |
| Screenshots of a page in fake mode | `node scripts/shots.mjs --port <dev port> --page <page>` → `hub-ui/screenshots/` |

The fake backend's catalogue of blocks is the gallery at `#/dev/gallery`. A change that touches the bridge between
the engine and the page updates [docs/hub-bridge-contract.md](docs/hub-bridge-contract.md) in the same commit.

**Dev switches of the fake backend.** In fake mode `window.__fake.ctx.s` is the fake's state; set a field in the
browser console and the next call sees it. `s.briefBusy = true` makes both brief saves (Favourites, crate switches)
answer `busy`; `s.unread` and `s.emptyRead` list the playlist folders the fake treats as never read, or read and empty. Two scenarios build on them:
`library:crates_busy` is `library:crates` with `briefBusy` on, and `library:first_look` shows its folders and crates with
no Favourites. The other scenarios are listed in the toolbar. Songs of the user's own come from `fake/own.ts` (a
deterministic generator): `normal` and the scenarios built on it have a watched Music folder with 24 of them, the
`folders_*` scenarios thousands, the crate scenarios their own folders, and one function (`listedCounts`) gives the sidebar, Settings and the folder's page the same count.

## Building the app

```
scripts/build_app.sh
```

It takes 5 to 10 minutes and makes `dist/app/Discjockey.app` and `dist/Discjockey-<version>.dmg`: it downloads
deno and FFmpeg's source release (both pinned by hash in `packaging/tools.json`), builds ffmpeg and ffprobe from that
source with `packaging/build_ffmpeg.sh` (only the Xcode command line tools, no external libraries; a few more minutes
the first time, then cached in `dist/cache/`), builds the app with PyInstaller, signs it, runs its self-test and makes
the `.dmg`. Check a built app with
`DISCJOCKEY_SUPPORT=$(mktemp -d) dist/app/Discjockey.app/Contents/MacOS/Discjockey --self-test`.

**Signing.** Every build is signed with a self-signed identity called "Discjockey Release", so macOS remembers the
user's keychain and Full Disk Access grants from one version to the next. The maintainer makes it once with
`scripts/make_signing_identity.sh` (it goes to `~/.discjockey-signing/`, in a keychain of its own, with a `.p12`
copy for safekeeping). Without it, a local build is signed ad hoc, which is fine for testing. CI rebuilds the
identity from the `.p12` with `scripts/import_signing_identity.sh <file.p12>` (`SIGNING_P12_PASSWORD` and
`DISCJOCKEY_SIGNING_DIR` in the environment).

## The public check

Everything in this repository is public. `scripts/check_public.sh` scans the tracked files for personal data: a real
person's `/Users/` path (made-up ones like `/Users/you` are fine), e-mail addresses outside `example.com` and
GitHub's no-reply domain, links to other repositories of the account, and the words in a denylist that lives
outside the repository: `~/.discjockey-public-denylist` (one word per line, for example your name and your other
e-mail addresses), or the file named in `DISCJOCKEY_PUBLIC_DENYLIST`. Run it before every commit:

```
scripts/check_public.sh
```

Without a denylist it warns and checks the generic rules only. The maintainer, who has the denylist, runs it as
`scripts/check_public.sh --require-denylist`, which exits 2 when the file is missing, unreadable or has no entries.

CI runs it on every push with the denylist from a secret. The maintainer's history from before the repository went
public lives in `docs/archive/pre-public/`, which is gitignored and only on the maintainer's disk.

## Releasing

1. Set the new version in `discjockey/__init__.py` (`__version__`) and in `pyproject.toml` (a test fails when they
   differ). Commit.
2. Run the checks locally (CI runs only the public check, the Python tests and the hub/static comparison; the release
   job runs no tests): `uv run pytest -q` and `cd hub-ui && npm run verify` must pass.
3. Tag the commit `v<version>` (for example `git tag v1.0.1`) and push that tag by name:
   `git push origin v1.0.1`. Never `--tags`, `--all` or `--mirror`, and never an `archive/*` branch or tag (the
   maintainer's local copy of the private history from before the repository went public; a local pre-push hook,
   `scripts/public_push_guard.sh`, refuses such a push, and `--no-verify` must not be used). The workflow refuses a tag that
   doesn't match `__version__`.
4. The `release` workflow runs the public check, builds ffmpeg, builds and signs the app, runs its self-test and
   attaches `Discjockey-<version>.dmg` to a **draft** release.
5. Look at the draft: download the `.dmg`, install it, open it. Then publish the draft by hand on GitHub. Nothing is
   published by the workflow itself, and a published release is never replaced.

The workflows read three repository secrets:

| Secret | What it holds |
|--------|---------------|
| `SIGNING_P12_BASE64` | The signing identity's `.p12` (`~/.discjockey-signing/discjockey-release.p12`), base64-encoded |
| `SIGNING_P12_PASSWORD` | That `.p12`'s password (`~/.discjockey-signing/p12.pass`) |
| `PUBLIC_CHECK_DENYLIST` | The denylist for the public check: the contents of `~/.discjockey-public-denylist` |
