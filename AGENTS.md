# Discjockey for AI agents

You are an AI agent (Claude Code, Codex, a ChatGPT agent or similar) and a person has pointed you at Discjockey on
their Mac. This file is everything you need to use it well without reading its source code. It is written for version
1.4.0; the program tells you its own version (`where --json`, `data.version`).

Start here:

1. Find the program (below) and run `discjockey help --json`: every command, with its flags, usage and an example.
2. Run `discjockey status --ready --json` or `discjockey doctor --json` to see where the library stands.
3. Read [Safety rules](#safety-rules) before you change anything. The short version: look first, show the person the
   plan, change things only when they said yes, and never start a sync or a download on your own.

## What Discjockey is

Discjockey keeps a DJ's lossless music library in step with their playlists on Spotify, Qobuz, SoundCloud and YouTube
Music. Each playlist is a folder in the library; a track that sits in several playlists is downloaded once. It looks for
the best version of every song (Qobuz as 16-bit AIFF first, then the artist's own file, a premium stream, a free
stream), measures each file's spectrum to tell real lossless from lossy and "fake lossless", names files
`Artist - Title`, and swaps in better versions later without losing the cue points the person set in rekordbox. It
**never deletes a music file**: a file it replaces moves to `Superseded/`.

The things you will meet:

- **The music folder** (suggested `~/Music/Discjockey`, the person chose it in Setup, it may be on an external
  drive): `playlists.txt` (one playlist per line, `Name = link`, the line further up wins when a song is in several, `#`
  switches a line off), `Library/<Folder>/` (verified lossless files and files the person bought),
  `Library/<Folder>/not_lossless/` (the best version found when Qobuz had none), `Superseded/<Folder>/` (replaced
  files), `Upgrades ready/<Folder>/` (better versions found for lossy files, parked until decided), and the hidden
  `.discjockey/` with `library.db` (Discjockey's records), `reports/`, `not_lossless.md` and
  `rekordbox/backups/`.
- **The support folder** `~/Library/Application Support/Discjockey/`: logins, `settings.json`, `config.json` (names
  the music folder), the programs Discjockey downloaded. Per Mac, not per library.
- **rekordbox's library** (`master.db`, encrypted, plus the analysis files that hold beat grids): the person's DJ
  software. Discjockey writes it only in three steps (Same track, Convert to AIFF, Give it its clean name), only
  while rekordbox is closed, always after a backup.
- **Songs and files.** A *song* is a library entry with a key (a bare Spotify id, `qobuz:…`, `soundcloud:…`,
  `youtube_music:…`, or `local:<n>` for the person's own music). Most commands take a song key or the path of its file.
- **Collections.** A view of the library: `all`, `unlisted` (songs in no playlist), `playlist:<folder>` or
  `folder:<path>` (a watched folder). Every `--in` flag takes one.
- **Quality verdicts:** lossless, good lossy, weak ("audibly weak"), fake ("fake lossless"), and not found.
- **To-do groups** (the keys of `todo list`): `rekordbox_check`, `missing_file`, `same_song`, `duplicate`,
  `upgrade_ready`, `cdj`, `not_found`, `weak`, `good_lossy`, `fake`, `other`.
- **Upgrades.** Same track keeps the rekordbox track, its cues, loops, beat grid, playlists and history, and needs
  rekordbox closed. New track puts the better file in as a new entry (the old file moves to `Superseded/`).
  `upgrade apply --all` is Same track only; name songs to add them as new tracks.
- **Batches.** Changes to files come in logged batches that can be undone: `aiff:<n>` (Same track, Convert, clean
  names; one rekordbox backup each) and `moves:<n>` (a tidy-up or a folder rename).
- **Checks in rekordbox.** After a file changed, the person has to look at it in rekordbox (reload tags, relocate,
  rebuild a USB stick). `check list` lists them; `check done` clears them once the person did it.

## Finding and running the program

One program, two homes. Both are the same engine:

- **Installed app:** `/Applications/Discjockey.app/Contents/MacOS/Discjockey`. Any argument you give it goes to the
  command line, except `--check-tools`, `--self-test`, `app open` and a Finder start. With no argument from a shell it
  prints the short help and exits (a window never opens on a probe).
- **A checkout of the code:** `bin/discjockey` (it runs `uv sync` first).

`discjockey` in the rest of this file stands for the full path of whichever you use (`where --json` prints it as
`data.command`, and every `next[].run` and `person_steps[].then` the program prints begins with it). `where --json` also
says which folders this process works on: `data.music.path`, `data.support`, `data.rekordbox`, `data.not_lossless`
(the buy list, or null), `data.jobs_running`, `data.windows_open`. Run `where --json` before anything else.

`help --json` is the index. `help <noun> [<verb>] --json` describes one command and adds its `data_schema` (the shape
of `data`, with a meaning for each field) and its `dry_run_schema`. `<noun> --help` is the same as `help <noun>`.
`discjockey app open` opens the window on the person's screen; do it only when the person wants the window.

## The contract

Every command follows the same rules, so you can drive all of them the same way.

- **Grammar:** `discjockey <noun> <verb> [ids] [flags]`. `--json`, `--jsonl`, `--verbose`, `--no-color`, `--wait`,
  `--detach` and `--wait-busy` stand anywhere on the line. A flag a command does not take is a usage error, never
  ignored. A command never prompts: confirmations are flags. Always add `--json`.
- **`--dry-run`** shows what a command that changes things would do (`help` lists it in `flags`, and `dry_run` is
  true). `--yes` is the window's confirmation, taken only by the commands whose `needs_yes` is true
  (`upgrade discard`, `track undo`, `batch undo`, `folder remove`, `missing remove`, `rekordbox restore`): without it
  they answer `refused` / `needs_yes` with what they would do, and any other command answers `bad_args` to the flag.
- **`discjockey call <method> [--args <json|->]`** sends a bridge method the window's own payload, through the same
  refusals as the noun-verb command. `help --json` lists the methods in `data.call_methods`. Prefer the noun-verb
  commands; `call` is for a method that has none.
- **Choosing songs.** A command that acts on songs takes `TRACK…` (keys or file paths), `-` (keys on standard input),
  `--all` (the command's own "all" list), `--rows` (every song of the list the flags describe) or, for `check done`,
  `--batch aiff:N`. `--rows` is read from `--in COLLECTION` (`all`, `unlisted`, `playlist:<folder>`, `folder:<path>`),
  `--todo GROUP`, `--search WORDS` and `--quality QUALITY` (Library: `all`, `lossless`, `good_lossy`, `weak`, `fake`,
  `upgrade_ready`). A flag a list does not take is `bad_args`. `library list` also takes `--sort` (`artist`, `title`,
  `length`, `source`, `quality`, `added`, `order`, `folder`; a `-` in front reverses it).
- **Typed ids** keep a number from meaning two things: `aiff:3` and `moves:3` are different batches; `job:<8 hex>` or
  `current`; `report:<YYYY-MM-DD_HHMMSS>` or `last`; `plan:<12 hex>`; `folder:<path>`; `playlist:<folder>`;
  `file:<n>`. A bare path where a song is meant is looked up for you.
- **The answer.** With `--json`, stdout holds exactly one object, for a usage error and a crash too. Without it the
  answer is a text page, and notices and problems go to stderr. The keys, in this order:
  - `v` (1), `command`, `outcome`, `reason`, `message` (words for the person);
  - `data`: the answer of the command's bridge method minus `ok`, plus what the command line adds (a dry run's
    `plan_id`, a batch's `batch_id`, the counts of `check done`; `shapes.CLI_DATA`). `help <command> --json` prints its
    `data_schema` (and `dry_run_schema`), which fits the `data` printed;
  - `page`: `null`, or for a long list `{list, offset, limit, total, next_offset}`. `--limit N` (default 200, `0` =
    all) and `--offset N` cut the one list `help --json` names as the command's `pages` (`batch list`, `history`,
    `library list`, `library superseded`, `rekordbox match`, `report list`); other commands are never paged. Read until
    `next_offset` is null;
  - `next`: commands to run next (`{run, why}`);
  - `person_steps`: what only the person can do, `{id, say, then}`. `then` is the command to run afterwards, or `null`
    for the same command again. Every `next[].run` and every `then` starts with this program's path;
  - `recovered` (always a list: what a recovery of an earlier crash put right), `job`, `as_of` (`{scanned_at,
    read_at}`: when the index was last scanned and the playlists last read, from the stored records; both `null`
    without a music folder; an answer is only as fresh as these), `sandbox` (always `null` in this version).
- **Outcome and exit code:** 0 `ok`, 1 `failed`, 2 `bad_args`, 3 `busy`, 4 `needs_person`, 5 `stopped`, 6 `partial`,
  7 `refused`, 8 `running`. `reason` is one word of a closed list (`discjockey/hub/outcomes.py`, in a checkout; each
  command's `reasons` in `help --json` says which it answers with). Read `reason` and `message`, not just the exit
  code. `partial` is not `ok`: some songs were done and others skipped or failed; the rows are in `data.results`.
- **Jobs.** Commands that change the library, and reads that can take minutes (`playlist check`), run in a worker
  process that outlives the command. The first stderr line is `Job job:… started (follow: <path> job follow job:…)`,
  so a killed call still has the id. How a command that starts a job waits: `--detach` answers `ok` (exit 0, `job`
  set) once the job runs, or the job's own answer when it already ended (a `busy` too); `--wait S` answers the job's
  own envelope, or `running` (exit 8, with the progress and any `person_steps`) after S seconds while the job goes on;
  with no flag a terminal follows to the end and anything else waits 90 s. `job list [--all]`, `job show <job|current>
  [--log]`, `job follow <job|current> [--jsonl] [--from-end]`, `job wait <job|current> [--wait S]` and `job stop
  <job|current> [--now]` work on any job from any process (`current` is the one running write job of this music
  folder). Ctrl-C in the command that started a job stops it safely, a second press a second later stops it at once. A
  `--jsonl` answer is one event per line, then the envelope.
- **Dry runs.** A rebuilt command's `--dry-run` changes no byte of the music folder, the rekordbox folder,
  `settings.json` or `library.db`; it stores its plan (`<support>/plans/`), caches (`cache/`) and, when it is a read
  job (`aiff … --dry-run`), the job's own record (`jobs/`). Its answer has a `plan_id`. Then run the same line with
  `--plan <id>` instead of `--dry-run` (the songs are named again): the run does the plan, and refuses with `changed`
  when things moved since, or `plan_expired` when the plan is more than a day old. On the aiff commands: `--rows` and
  `rename --all` with no song, and a plan of a clean library, are `ok` with `total` 0; `aiff convert --all` on a clean
  library is `refused`; a dry run with more than 50 own files whose facts are unread is `refused` (`facts_missing`,
  next `library facts`; up to 50 are read in memory and never stored, in the window too; past 50 the window plans on
  the stored facts and never refuses). `upgrade apply` and `upgrade discard` also take `--if-rev EXPECT` (refuse with
  `rev_changed` when the song changed since you read it).
- **Locks and `busy`.** One writer at a time: a write command takes the library lock like the window does. Another
  Discjockey job, a window's job or a terminal run holding it answers `busy` (exit 3, reasons `library_lock`,
  `console`, `sync_running`, `import_running`, `rekordbox_lock`, `support_lock`). Wait and try again, or add
  `--wait-busy S` to wait up to S seconds for it. Never remove a lock file.
- **Reading is safe.** Reads (`writes: false`) take no library lock and change nothing. Some read the stored records
  only; `track show` and `track spectrum` and `rekordbox preview` read one file (a few seconds).

`help --json` layout: `data` is `{command, version, global_flags: [{flag, says}], commands: [...], call_methods:
[...]}`. Each command has: `command` (`rekordbox status`), `kind` (`R` read, `RJ` read that may run as a job, `J`
write job, `J-control` stops a job, `B` brief save, `words` for `help`, `where`, `app open`, `call` and the `job`
words, rows that also carry `says`, one line on what the word does), `writes`, `job` (runs as a job), `args`
(`{name, word, positional, many, required, type, id}`: what the person types; `word` is the form of a positional
(`aiff:N`, `on|off`, `FOLDER`) or the flag, `id` the id kind a value is read as, else `null`; a command that selects
songs has `track_ids` not required: `songs` lists the ways), `songs` (`["TRACK...", "-", "--all", "--rows",
"--batch"]`, each only where the command has it; empty for a command that selects none), `flags` (the ones beside the
arguments: the selection words `--all`, `--rows`, `--in`, `--todo`, `--search`, `--quality` on a command that takes
songs, `--auto-upgrade-only`, `--dry-run`, `--yes`, `--limit`, `--offset`), `flag_values` (the word of the value of
each flag that takes one: `{"--in": "COLLECTION", "--way": "same-track|new-track"}`), `required_flags` (flags the
command cannot run without), `needs_yes`, `dry_run`, `locks`, `methods` (the bridge methods it runs, `call`'s
names), `dry_run_method`, `reasons` (the `reason`s the command line and the catalogue know the command answers
with; an engine rule may still answer `refused` or `failed` with a reason of its own, `facts_missing` or an
eligibility reason, always one word of the closed list), `example` and `usage` (`(TRACK... | - | --all | --rows)` is
the songs, `[--in COLLECTION]` a flag with its value, a flag without brackets one the command cannot run without).
`locks` tells you what a command takes: `library`, `support`, `rekordbox_w` (it writes rekordbox's library: rekordbox
must be closed), `rekordbox_r`. A command that is not built yet is not listed.

## Safety rules

An agent's command counts as the person starting it, so everything Discjockey promises the person holds for you too:
it never deletes a file (a replaced file moves to `Superseded/`), writes rekordbox's library only while rekordbox is
closed, takes a backup first, can be undone, and takes the library lock like the window. On top of that, you:

1. **Look, show, then change.** For every command with `writes: true` that has `dry_run: true`, run `--dry-run`
   first, tell the person in plain words what it would do (counts, the songs, what goes to `Superseded/`, whether
   rekordbox must be closed), and run it only when they said yes to that. Then run the same line with `--plan <id>`.
   A command that changes things and has no dry run (`check done`, `library scan`, `settings set auto-upgrade`,
   `sync scope on|off`, `batch resume`) is for a request that names it.
2. **Never start a sync or a download on your own.** The sync downloads from Qobuz, which has a daily limit that
   Discjockey paces on purpose (60 tracks a day by default, a third of yesterday's unused amount carries over, a pause
   after 3 failed requests in a row), and Qobuz's terms do not allow downloading with streamrip, so the person carries
   the account risk. Only the person decides to spend that. `sync plan`, `sync scope show`, `limits show` and
   `missing download --dry-run` are free to run; a real sync, `--extra` (more Qobuz downloads today) and any loop
   that retries a failing login or download are not yours to start. `missing download` itself only queues the song for
   the person's next sync.
3. **rekordbox must be closed** for a step that writes its library (`locks` has `rekordbox_w`: `aiff convert`,
   `aiff rename`, `upgrade apply`, `track undo`, `batch undo`, `batch resume`, `rekordbox restore`, `sync run`).
   When it is open the answer is `needs_person` with the reason `rekordbox_open` and a person step "Quit rekordbox,
   then tell me to carry on". Relay it, wait for the person, run the same command again. **Never quit or kill
   rekordbox yourself**: it may hold unsaved work or a track on a deck. If rekordbox is opened while a step runs,
   Discjockey rolls the track in work back and stops the batch.
4. **Never touch music files by hand.** No deleting, moving, renaming or re-tagging in the music folder
   (`Library/`, `Superseded/`, `Upgrades ready/`) or in a watched folder, whatever the file looks like: Discjockey's
   records know where every file is, and rekordbox finds files by name. Every file change goes through a command
   (convert, rename, upgrade, tidy-up) so it is logged and undoable. Files in `Superseded/` are the person's to
   delete, once rekordbox no longer points at them (`library superseded` and `rekordbox match` say which); you only
   report them. The one command that deletes a file is `upgrade discard` (the parked better version in `Upgrades
   ready/`, which the person chose to throw away) and it needs `--yes` from them.
5. **Never edit Discjockey's or rekordbox's records by hand:** not `.discjockey/library.db` (its layout changes between
   versions and a job may hold it), not `settings.json`, `config.json` or the logins in the support folder, not
   rekordbox's `master.db` or its analysis files (`USBANLZ`). Use the commands. rekordbox deletes the analysis files
   of tracks removed from its collection: never advise "remove from collection" to fix a missing track; Discjockey's
   `rekordbox backups` (copies of master.db and the analysis files of tracks a batch changed) exist for that.
   The one hand-editable file is `playlists.txt` (see below).
6. **`person_steps` are for the person.** Say them in your words, wait until the person says they did them, then run
   `then` (or the same command again when it is `null`). Run `check done` only after the person has looked in
   rekordbox; it clears their to-do, it is not a way to make the list shorter.
7. **One writer at a time.** If a command answers `busy`, `job list` shows what holds the library; wait for it or use
   `--wait-busy S`. Do not start a second write command next to a running job. A job the window runs holds the library lock too.
8. **No secrets through you.** Passwords, API keys and the macOS keychain are the person's. Logins are set up in the
   window; a `needs_person` with `keychain`, `folder_access`, `full_disk_access` or `browser_sign_in` is a question
   only they can answer. `call` refuses secret arguments.
9. **Undo and backups.** Every batch can be undone (`history` and `batch list` name the undo; run its `--dry-run`
   first). `rekordbox restore <backup>` puts the whole rekordbox library back as one of the backups holds it and drops
   every change the person made in rekordbox since: only with their go, after `--dry-run`, and say so. Discjockey
   saves the current library first and prints its name. Undo replaces made after that backup first (`batch undo`),
   or those tracks point at files in `Superseded/`.
10. **Report outcomes as they are.** `partial`, `refused`, `running` and `needs_person` are not success. Say what was
    done, what was skipped and why (`data.results[].state` and `reason`), and what is left.

**`playlists.txt`** is the one file the README tells the person to edit by hand, and in this version no command edits
it (see the last section). If the person asks you to change it: not while a job runs (`job list`), keep a copy of the
file first, change only the lines asked for, keep the format `Name = link` (a `#` in front switches a line off), and
show the person the difference. Know what a change does: the name on the left is the folder in `Library/` (files
already there stay, new downloads go to the new name), the order is the priority (only new downloads follow a new
order; moving existing files is a tidy-up the window does), and a link must be one `playlist check <link>` can read.
Run `playlist check <link>` before you add a link.

## Task map

Each row gives the command (see `help <command> --json` for its flags, `data_schema` and example). **W** marks a
command that writes (needs the person's go, dry run first where the command has one). Everything else only reads.

### Get the library gig-ready

| To do | Run |
|---|---|
| One sentence: ready for a gig or not, and the problems a gig depends on, each with what to do | `status --ready` |
| Everything that is wrong, with the next step for each (setup, programs, logins, folder access, rekordbox, locks, lost jobs, records, drives that are not connected, downloads paused today, files out of place, `Superseded/`, rekordbox tracks on missing files, stopped batches, open rekordbox checks, files CDJs won't play well, songs without a file, better versions waiting) | `doctor` |
| The to-do list (what the window's To-do page shows); narrow with `--group fake,weak`, add `--hidden` | `todo list [--group G[,G…]] [--hidden]` |
| Better versions waiting | `upgrade list` |
| **W** Put better versions in (Same track for the same edit, or `--way new-track` for a different edit) | `upgrade apply (TRACK… \| --all \| --rows) [--way same-track\|new-track] --dry-run`, then with `--plan plan:ID` |
| **W** Throw a waiting better version away (deletes the parked file; needs `--yes`) | `upgrade discard (TRACK… \| --rows) --dry-run`, then `--yes` |
| Files CDJs refuse or stutter on (MP3/AAC above 320 kbps or 48 kHz, Opus, Vorbis, WMA, AC-3, WavPack, APE, TTA, lossless that is not 16 or 24 bit or is above 96 kHz or below 44.1 kHz) | `todo list --group cdj` |
| **W** Make files AIFF (16-bit/44.1 kHz, tags and cover kept, original to `Superseded/`); `--all` takes every lossless file of `--in COLLECTION`, `--todo cdj` the CDJ group; a lossy file only joins when named or through the CDJ group | `aiff convert (TRACK… \| --all \| --rows) [--in C] [--todo G] --dry-run`, then `--plan plan:ID` |
| **W** Give a clean AIFF that is named wrongly its clean name (`Artist - Title.aiff`; only the name changes) | `aiff rename (TRACK… \| --all \| --rows) --dry-run`, then `--plan plan:ID` |
| What the person still has to check in rekordbox | `check list [--hidden]` |
| **W** Mark those checks done (only after the person did them) | `check done (TRACK… \| --all \| --batch aiff:N)` |
| Songs whose file is missing, with the day it went missing and where it was | `missing list [--hidden]` |
| **W** Ask Download again for them (the next sync downloads them, or puts a waiting better version in) | `missing download (TRACK… \| --all) --dry-run`, then without |
| **W** Remove them from the library (final, no undo; deletes no music file, only the better version waiting in `Upgrades ready/`; needs `--yes`) | `missing remove (TRACK… \| --all) --dry-run`, then `--yes` |
| rekordbox on this Mac: state, version, whether its library can be opened | `rekordbox status` |
| Does rekordbox match the files? (tracks on missing files, in `Superseded/`, on a drive that is not connected; files rekordbox lacks) | `rekordbox match [--in C]` |
| What Same track, Convert and Rename would do for one file, and what rekordbox holds for it | `rekordbox preview TRACK` (or `--path PATH`) |
| The backups of rekordbox's library | `rekordbox backups` |
| **W** Put a backup back | `rekordbox restore BACKUP --dry-run`, then `--yes` |

A song is a key or the old path of its missing file. The action of `missing` follows the song: a song in a playlist
downloads again, any other is removed, and one it does not fit is skipped with its reason; the run ends `partial` (exit
6), or `refused` (exit 7) when every song was skipped. `--all` is the To-do group's list for that action.

Before a gig, USB sticks the person exported before a replace still play the old file: tell them to rebuild the stick in
rekordbox (Discjockey says so after a batch and never writes to sticks).

### See the library

| To do | Run |
|---|---|
| The collections (all, unlisted, playlists, folders) with their counts | `library collections` |
| Songs of a collection with quality, filter and sort | `library list [--in C] [--search Q] [--quality F] [--sort S]` |
| Find a song by artist and title words, or by file path | `track find WORDS…` / `track find --path PATH` |
| Everything about one song (the detail view the window shows) | `track show TRACK` |
| A file's spectrum (the measurement behind the quality verdict); `--which current\|upgrade` | `track spectrum TRACK` |
| What sits in `Superseded/`, with its size and whether rekordbox still points at it | `library superseded` |
| Read the library's files again (after files moved outside Discjockey) | **W** `library scan` |
| Read the facts of the person's own files (needed before big AIFF plans) | **W** `library facts [--dry-run]` |
| What changed, newest first, and the command that undoes each | `history [--since today\|yesterday\|3d\|12h\|2026-11-20]` |
| Past syncs: list, show one | `report list [--since …]`, `report show report:STAMP\|last` |
| Batches: list, show, carry on a stopped one, undo one | `batch list [--kind K]`, `batch show aiff:N\|moves:N`, **W** `batch resume aiff:N`, **W** `batch undo aiff:N\|moves:N --dry-run`, then `--yes` |
| **W** Undo what the last step did to a song | `track undo TRACK… --dry-run`, then `--yes` |
| Where a file, folder or report is: `--print` prints the path instead of opening Finder; use it | `open file TRACK --print`, `open folder all\|playlist:NAME\|folder:PATH --print`, `open report last\|not-lossless --print` |

`open url URL`, `open licences` and `open privacy-settings` also open things on the person's screen: add `--print` and
tell them instead.

### Sync

The sync reads the playlists, plans downloads and runs them; the person decides it, in the window. What an agent can do
today:

| To do | Run |
|---|---|
| The plan the Sync page shows (new, try again, download again, bought files, better versions to look for), narrowed with `--search WORDS`. It is read from the playlists as last read (`as_of.read_at`) | `sync plan` |
| What the sync leaves out (`playlist:<ref>`, `folder:<path>`, `kind:retry`, `kind:weekly`) | `sync scope show` |
| **W** Leave something out, or take it back | `sync scope off ITEM…` / `sync scope on ITEM…` |
| **W** Only the sync's upgrade phase: Same track for the upgrades that need no decision. Reads no playlists, downloads nothing, but moves files and writes rekordbox | `sync run --auto-upgrade-only --dry-run`, then `--plan plan:ID` |
| What is used today and the daily limits; what another limit would do | `limits show [SERVICE]`, `limits set SERVICE N [--extra-today N] --dry-run` |

The full sync (read playlists, download, check, convert) is still the old command line: the program with no word
(`discjockey --dry-run`, `--yes`, `--limit N`, `--extra N`, `--verbose`, `--json`). Do **not** run it without the
person's explicit go for that run. `--dry-run` moves and downloads nothing and writes no report, but it reads the
playlists from the services and stores what it read in `library.db`. A sync started that way shows in the window
"In the Terminal", and Stop safely there stops it. `--json` needs `--yes` or `--dry-run` and prints one object
`{"ok", "exit_code", "dry_run", "report", "counts", "auto_upgrade"}` (or `{"ok": false, "kind", "message"}` for a
problem, every human line on stderr). Exit codes of that old command line: 0 done, 1 errors in the run, a crash or `--json`
without `--yes`/`--dry-run`, 2 setup problem or no music folder, 3 another run holds the library or the support lock,
130 stopped (Ctrl-C once stops after the current step, twice at once; for `update`, exit 3 also means a tools update
already runs). `update` gets the newest yt-dlp; `discjockey setup --help` and `discjockey update --help` print their
flags. Each of these words leaves the old command line when its replacement is built.

### Folders, settings, setup

| To do | Run |
|---|---|
| The folders Discjockey watches for the person's own music | `folder list` |
| What watching a folder would find, before adding it | `folder check PATH` |
| **W** Watch a folder (nothing is copied, moved, renamed or re-tagged) / stop watching one (needs `--yes`) | `folder add PATH --dry-run` / `folder remove folder:PATH --dry-run`, then `--yes` |
| The person's playlists | `playlist list` |
| Whether a playlist link can be read, and what is in it, without adding it | `playlist check LINK` |
| What Settings holds; the Auto-upgrade switch | `settings show`; **W** `settings set auto-upgrade on\|off` |
| Download sources: state of each login, browsers that hold one | `login list`, `login find SERVICE` |
| The programs Discjockey needs (ffmpeg, ffprobe, deno, yt-dlp) | `tools status` |
| What Setup still needs; whether a folder can be the music folder | `setup status`, `setup music PATH --dry-run` |
| This app's version, and whether a newer one is out (`--check` asks the internet) | `app info [--check]` |
| What a tidy-up would move (files out of playlist order) | `tidy run --dry-run` |

`settings set auto-upgrade` changes whether every sync also moves files and writes rekordbox at its end: it is the
person's choice, never yours to flip for convenience.

### Jobs

`job list [--all]` (running first), `job show job:ID|current [--log]`, `job follow job:ID|current`, `job wait
job:ID|current [--wait S]`, `job stop job:ID|current [--now]` (a safe stop after the current step; `--now` at once).

## Worked examples

**1. "Which of my tracks will give trouble on the CDJs, and fix them."**

```
discjockey where --json                                   # which library is this? data.music.path
discjockey todo list --group cdj --json                   # the files, each with why ("AAC 420 kbps · CDJs stop at 320")
discjockey aiff convert --all --todo cdj --dry-run --json # data.plan, data.plan_id = "plan:…"
```

Tell the person what the plan says: how many files, which become AIFF, how much room it needs, that every original
goes to `Superseded/`, and that rekordbox must be closed for tracks that are in it. When they agree:

```
discjockey aiff convert --all --todo cdj --plan plan:0123456789ab --detach --json
discjockey job wait current --wait 120 --json             # exit 8 `running` while it goes on: wait again
```

The end answer lists `data.results` (one row per track) and `data.batch_id` (`aiff:12`). If rekordbox was open the
answer is `needs_person` (exit 4), `reason` `rekordbox_open`, person step `step:quit_rekordbox`: say it, wait for the
person, run the same line again. Afterwards tell them about the USB stick, and that `batch undo aiff:12 --dry-run` is
how it goes back.

**2. "Put in the better versions that are waiting."**

```
discjockey upgrade list --json                            # what is waiting, same edit or not
discjockey upgrade apply --all --dry-run --json           # Same track only; data.items, data.space, data.rekordbox, data.plan_id
discjockey upgrade apply --all --plan plan:0123456789ab --detach --json
discjockey job follow current                             # progress lines, then the answer
```

A different edit is never in `--all`: ask the person which songs to add as new tracks (`--way new-track` with the
songs named). The answer may have `person_steps` such as `step:reload_tag` ("In rekordbox, reload the tags of …") with
`then` `check done <tracks>`: tell the person, and run `then` only after they say they did it.

**3. "Is everything ready for Saturday?"**

```
discjockey status --ready --json    # data.ready_text: one sentence; data.ready[]: problems a gig depends on
discjockey doctor --json            # data.problems[] each with text, next[], person_steps[]
```

Report the sentence and the problems in your words. For each problem run its read-only `next` commands (for example
`rekordbox match`, `check list`, `missing list`), propose the fix, and do the fixes the person approves with the
dry-run flow above. Steps that are the person's (connect a drive, allow a folder in macOS, open rekordbox and have a
look) you hand over.

## What still needs the window (version 1.4.0)

These are in the window and have no command yet. Say so and offer `discjockey app open`; do not work around them by
touching files or records. More commands arrive in later releases, so check `help --json` again after an update.

- **Reading the playlists again and running the full sync** (Start sync, choosing what and how many). Only the old
  command line above runs it, and that is the person's call.
- **Changing the playlists:** add, remove, rename, move, switch on or off, edit, add Liked music (see the
  `playlists.txt` note above).
- **Moving files:** the tidy-up that moves files to where the playlist order puts them, undoing a tidy-up, and the
  question "Save and move the files" after a playlist change. `tidy run --dry-run` and `batch undo moves:N --dry-run`
  only show what they would do. "Continue import" (the import of watched folders again after a Stop) is the window's
  too; `folder add` starts the first import.
- **Questions and duplicates** about the person's own songs (is this the same song, which copy to keep).
- **Per-song decisions:** Never download, Hide, Show again, adding a bought file, searching for another version,
  previewing or using a candidate or a link, rejecting the current version.
- **Logins and setup:** signing in or out of Qobuz, Spotify, SoundCloud and YouTube, choosing or changing the music
  folder, skipping the import. `login list` and `setup status` only read.
- **Limits and tools:** saving a daily limit (`limits set` only shows what it would do), marking a limit warning as
  seen, the Liked-music switch, updating or rolling back the download tools (`update` in the old command line does
  update yt-dlp).
- **Library organisation:** favourites and the crates shown in the browser.
- **Playing a track** in the window's player.
- **Setup in the Terminal** is the old command line `discjockey setup`: it asks Setup's questions in the Terminal, the
  music folder first (it needs a real Terminal window), and ends with the line that lets you type just `discjockey`.
  It is not for agents.

The old words are gone and answer `bad_args` with what to say instead: `upgrades` (say `upgrade …`), `upgrade undo`
(say `track undo`), `rekordbox checked` (say `check done`), `convert` and `rename` (say `aiff convert …` and
`aiff rename …`), `settings auto-upgrade` (say `settings set auto-upgrade on|off`; `settings show` reads).

## If you work on Discjockey's code

A command run by hand always sets `DISCJOCKEY_SUPPORT=<scratch folder>` and `DISCJOCKEY_REKORDBOX=<fixture folder or an
empty folder>`: without them it reads, and a job writes, the real library and the real rekordbox library. `where`
prints what a process resolved. A set but empty `DISCJOCKEY_REKORDBOX=` means "no rekordbox library". Never run a real
sync, upgrade or download while working on the code: it changes the library and counts against the Qobuz daily
limit. The binding rules for code changes are in [CLAUDE.md](CLAUDE.md), the developer notes in
[CONTRIBUTING.md](CONTRIBUTING.md). The shapes of every answer, with each field's meaning, are in
`discjockey/hub/shapes/` (`cli.py` holds the command line's own methods, `cli_first` included).

## Where to read more

- [docs/manual.md](docs/manual.md): the full user manual. Read it for how a feature behaves from the person's side
  (upgrades, AIFF, rekordbox, watched folders, limits).
- `help <command> --json` → `data_schema`: what each field of an answer means.
- [README.md](README.md): what Discjockey is, install, and what to tell your agent.
