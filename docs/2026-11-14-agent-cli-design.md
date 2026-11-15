# Discjockey's command line for agents and people (issue 39, design)

Status: design, 2026-11-14. Input: the six audit files `docs/2026-11-14-cli-audit-{library,todo,app,supplement-a,
supplement-b,supplement-c}.md` (cited as **L**, **T**, **A**, **SA**, **SB**, **SC** with their row ids, e.g. L D15,
T §5.4), today's commands (`CONTRIBUTING.md` › "Commands for scripts and agents"), `docs/issues.md` › 39, `CLAUDE.md`
› "Agent-ready". A later Opus agent turns this into a build plan for Sonnet groups; this file fixes the decisions,
the interfaces and the behaviours tests pin, not the code.

---

## 1. What this design must achieve

### 1.1 The user's hard rules, as this design states them

| # | Rule | How this design meets it (section) |
|---|---|---|
| H1 | **Everything the window shows, and more.** Every text, number, sentence, badge, colour or dimming that means something, tooltip, count, ordering, and the data behind every picture is reachable by a command; where the window leaves things out, the command gives them anyway. Nothing is reachable only in the window. Guaranteed by construction. | The window and the command line read the **same view objects** (`views.py` + one new layer, `discjockey/present/`), and every word the window shows is produced by the engine, not by Svelte (§8). The CLI prints the view object whole; text mode renders it field by field from one schema (§4). Tests compare the bridge payloads and the command payloads key for key (§13). |
| H2 | **For people too.** Readable text by default with the same facts; a machine shape for agents; pictures as data plus a way to see them. | Text is the default; `--json` prints the versioned envelope (§4). Pictures: `--json` gives the numbers; `--png <file>` writes the picture a person or a vision agent opens; text mode prints the verdict line and a small text sketch (§4.5). |
| H3 | **Everything the user can do in the window, an agent can do**, under the same invariants. An agent's command counts as the user starting it. | The full catalogue maps every bridge method to a command or to "window only" with a view-state reason (§5). Writes keep the lock, Qobuz protection, never-delete, batches the user started, and a dry run where the hub has one (§7). |
| H4 | **Coverage from what the app is FOR.** | §11 lists the user's goals and questions and the commands that answer each. |
| H5 | **Today's commands are evidence, not a template.** Nothing is kept for compatibility. | §12: every convention judged keep / change / drop with its reason. |

### 1.2 Principles (how the decisions below were made)

1. **One engine answer, two renderers.** A fact the window shows comes from the engine; Svelte and the console both
   render it. When the window decides something itself today (≈115 audit rows), the decision moves into the engine
   (§9). The window keeps only how things are laid out and what the person is looking at (pure view state).
2. **Read commands are free, write commands are deliberate.** Reads take no lock, never write, never touch the
   network unless they say so, and work while the window runs. Every write is an explicit verb with `--dry-run` where
   anything moves or changes, and a `--yes` where the window asks a question first.
3. **Nouns first, then verbs** (`gh`, `kubectl`): `discjockey <noun> <verb> [ids] [flags]`. One noun per concept the
   user knows (track, playlist, folder, todo, run, batch, rekordbox, settings, login, limits). An agent that knows the
   nouns can guess the commands; `discjockey help --json` lists them all.
4. **Porcelain = plumbing.** Unlike git, there is one layer: the same command serves a person (text) and an agent
   (`--json`). The JSON is the contract (versioned, documented per command); the text may change freely.
5. **Long work is a job with an id**, detachable and followable from any process (§6). A command never needs to stay
   attached for hours.
6. **Ids are stable and typed** (`track:…`, `file:…`, `batch:…`, `moves:…`, `run:…`), never bare integers that mean
   different things in different tables (§3).
7. **Every outcome has one shape and one exit code table** across all commands (§4.3).
8. **A command never prompts.** What the window asks a person (confirm Discard, Undo, Remove folder) is a `--yes`
   flag; what only a person can do (log in in a browser, quit rekordbox, listen) is a `needs_person` outcome with the
   exact words the agent tells the user (§10).
9. **Safe to rehearse.** `--sandbox` (or `DISCJOCKEY_SANDBOX=<dir>`) runs any command against a copy, never the real
   library or rekordbox (§10.3).

### 1.3 What is borrowed, and from where

| From | Taken | Why it fits Discjockey |
|---|---|---|
| `gh` | noun-verb grammar; `--json` on every command; `help` that names the next command; secrets only through stdin (`--with-token` → our `--password-stdin`) | A DJ's concepts are nouns (track, playlist, batch); one flag for machine output is easy to teach an agent |
| `kubectl` | `--dry-run` on every write; typed ids (`kind/name` → our `aiff:12`); `wait` and `--watch`-style follow; a version field on every object | Writes that move files need a preview; long work needs waiting without a held connection |
| Terraform | a dry run returns a **plan id**; the apply can be bound to it and refuses what changed in between | The window already binds a sync to the plan the person reviewed (`run.select_actions`); one mechanism for every write |
| git porcelain/plumbing | the idea that scripts need a stable layer | Rejected as two layers: one layer whose JSON is stable is simpler for a one-maintainer app |
| systemd / launchd jobs | a job runs in its own process, outlives the client, is listed, followed and stopped by id | A sync takes hours; an agent's tool call times out after minutes |
| HTTP ETags | `rev` of a record; a write may say `--if-rev` | Replaces the window's in-memory `_shown` with an explicit, stateless token (L finding 5, T §0.2b) |
| Unix | text to stdout, progress to stderr, `-` reads ids from stdin, exit codes that mean one thing | Pipes: `discjockey todo list --group weak --json | jq … | discjockey track hide -` |

---

## 2. Entry, grammar and discovery

### 2.1 The program

- **One program, two homes.** In a checkout: `bin/discjockey`. In the installed app:
  `/Applications/Discjockey.app/Contents/MacOS/Discjockey`. Both run `cli.main`.
- **Routing in the app (change).** `app_main` opens the window only when there is **no argument** (or the single word
  `app open`); `--self-test` and `--check-tools` keep their places; **anything else goes to `cli.main`**. Today only
  `CLI_COMMANDS` words reach the CLI and `Discjockey --yes --json` opens the window (L finding 7, T §0.7). The list
  `CLI_COMMANDS` and its test are dropped: the parser is the one list. macOS may pass a `-psn_…` argument when the app
  is opened from the Finder: that one argument still opens the window (test pins it).
- **A short name for people.** `discjockey app install-command [--dir ~/.local/bin] [--dry-run]` writes a two-line
  shell script `discjockey` that execs the app's binary; it refuses to overwrite a file that is not its own. Agents
  never need it: `where` prints the absolute command path.
- **Long jobs keep the Mac awake** inside the job worker (`caffeinate -i -w <worker pid>`), no longer only through
  `bin/discjockey` (A §5.1: the .app had none).

### 2.2 Grammar

```
discjockey <noun> <verb> [ids…] [flags]          ids: typed (§3); "-" reads ids from stdin
discjockey <noun>                                 = the noun's read verb (list or show)
global flags (anywhere on the line): --json | --jsonl   --sandbox <dir>   --wait <s> | --detach
                                     --wait-busy <s>     --verbose        --no-color
write flags (each write that has them): --dry-run   --plan <plan id>   --yes   --if-rev <rev>
selection flags (bulk writes, §7.3):  <ids…> | --all | --rows   with --in <collection> | --todo <group>,
                                      --search <words>, --quality <q>
```

- Global flags are parsed **once, wherever they stand** (today `discjockey --json upgrade list` silently drops
  `--json`, T §5.4). A flag a command doesn't take is a usage error (`bad_args`), never ignored.
- Every noun has `help`: `discjockey <noun> --help`, `discjockey help <noun> <verb> [--json]`.
- Words on the command line are the window's words, hyphenated: `same-track`, `new-track`, `read-liked-music`.
  In JSON the same values are snake_case (`same_track`). The parser accepts both spellings.

### 2.3 Discovery: how an agent with no prior knowledge finds its way in

| Step | Command | What it gives |
|---|---|---|
| 1 | `Discjockey --help` (or no TTY and no args: still the window; any `help` word reaches the CLI) | First line: "AI agents: run `<path> help agents` first." Then the nouns with one line each |
| 2 | `discjockey help agents` | The agent guide (§14.2): what Discjockey is, the concepts, the safety rules, the workflow (look → dry run → ask the user → apply → follow → report the person's steps), ids, outcomes |
| 3 | `discjockey where --json` | `music` (path, state `ok`/`missing`/`not_chosen`), `support`, `rekordbox` (library path or null), `command` (absolute path of this program), `version`, `sandbox` (null or its dir), `window_open` (bool), `jobs_running` |
| 4 | `discjockey status --json` | The cross-screen overview (Dashboard + counts + running jobs + problems + what needs a person), §11 |
| 5 | `discjockey help --json` | The machine index: every command with its args, flags, whether it writes, its job kind, its outcome reasons, the name of its data schema; `help <cmd> --json` adds the schema (JSON Schema) |
| 6 | `discjockey help concepts` / `help glossary` | The model of the app (§14.2) and every badge, colour, tone and tooltip word with its meaning (the word catalogue's static part, §8) |

The folders are found the way the window finds them (`library.resolve_paths`: `config.json` in the support folder,
the support folder from `DISCJOCKEY_SUPPORT` or `~/Library/Application Support/Discjockey`); `where` prints the
answer so an agent can confirm it works on the intended library **before** any write. Every `--json` envelope also
carries `sandbox` (§4.1), so an agent can check after the fact too.

---

## 3. Identity: how things are named

Rules: (1) every id printed in JSON is a string that names its kind, except song keys, which already carry their
service; (2) an id never changes meaning between tables (today `batch undo 3` and `undo_moves(3)` are different
batches, L finding 3); (3) a command accepts the printed id; where a person thinks in names (a playlist's folder, a
file's path) the command accepts that too and prints the id it resolved to.

| Thing | Printed as (JSON) | Accepted on the command line | Stable? |
|---|---|---|---|
| Song (track) | `track_id`: the song key, unchanged: Spotify id bare, `qobuz:…`, `soundcloud:…`, `youtube_music:…`, `local:<n>` (own file) | the key; **a file path** (absolute, or relative to the music folder) resolves to the song that holds it; `-` | yes (service ids; `local:<n>` while the file is known) |
| File (index row) | `file_id`: `file:<n>` + `path` | `file:<n>` or a path | yes, per index row |
| Playlist | `playlist`: `playlist:<folder>` + `ref` (the link token, `models.token`) + `folder` | the folder name, `playlist:<folder>`, or its link | folder name is unique in `playlists.txt` (validated on save); `ref` survives a rename |
| Collection (a Library view) | `all`, `unlisted`, `playlist:<folder>`, `folder:<path>` | the same | yes |
| Watched folder | `folder:<path>` + `folder_id` (int, internal) | the path or `folder:<path>` | path |
| Crate | `folder:<path>` (a crate is a folder) | path | yes |
| AIFF batch | `aiff:<n>` | `aiff:<n>` (a bare number is `bad_args`: "say aiff:12 or moves:12") | yes |
| Move batch | `moves:<n>` | `moves:<n>` | yes |
| Run (sync report) | `run:<YYYY-MM-DD_HHMMSS>` | that, or `last` | yes |
| Job | `job:<8 hex>` | that, or `current` (the one running write job) | yes (registry, §6) |
| Duplicate group | `dup:<sorted file ids>` (`models.group_id`) | the same | changes when its files change, by design (asked again); a stale one is `refused`/`changed` with `next: duplicate list` |
| Same-song question | `same:<song key>~<own key>` | the same | yes while the question stands |
| rekordbox check | one per track: the `track_id` | `track_id`s, or `--batch aiff:<n>` | yes |
| Version candidate | `cand:<source>:<id>` | the same, valid while that track's last search is cached | until the next search |
| rekordbox backup | its `id` (today's) | the same | yes |
| Plan (any dry run) | `plan:<12 hex>` | the same | 24 h, kept in `.discjockey/plans/` |
| Sync action | `act:<kind>:<track_id>:<n>` (n = position of its `to_dir` in the plan's folder list) | the same | for that plan |
| Record revision | `rev`: 10 hex of `models.snapshot(entry)` | `--if-rev <rev>` | changes on every change of the record |
| Person step | `step:<name>` (§10.1) | n/a | yes |

- **Finding ids without knowing them:** `track find <words>` (artist/title, folded like the window's search) and
  `track find --path <file>` print `track_id`s; every list prints ids; every result names the ids it touched.
- **`rev` replaces `_shown`.** Today single-track writes (`hide`, `use_candidate`, `use_link`, `reject_current`,
  `add_bought_file`, one-track New track / Discard) are refused `changed` unless *this window process* showed the
  track (`ops.run_single`). New: every read of a record prints its `rev`; the bridge and the CLI take an optional
  `expect`/`--if-rev`; the window always sends it (same safety as today, no memory); a command without it acts on the
  record as it is now, and the engine's own per-item checks still hold.
- **Result objects carry names, not only keys** (T §5.5): every per-track result has `track_id`, `artist`, `title`.

---

## 4. Output, outcomes and exit codes

### 4.1 The machine shape: one envelope

With `--json` stdout holds **exactly one JSON object**, also for a usage error and a crash (today a usage error
prints argparse text even with `--json`, L §5). Shape:

```
{"v": 1,
 "command": "upgrade apply",            the noun and verb that ran
 "outcome": "ok" | "partial" | "refused" | "busy" | "needs_person" | "stopped" | "failed" | "bad_args" | "running",
 "reason": null | "<key>",              why, for every outcome but ok (keys in §4.3)
 "message": null | "<words>",           the window's sentence for this outcome (from the word catalogue, §8)
 "data": { … },                         the command's payload (its schema: help <cmd> --json); present for ok and
                                        partial, and for a problem when there is something to show (a batch's state)
 "next": [{"run": "<command line>", "why": "<words>"}],   what to do next, as commands (may be [])
 "person_steps": [{"id": "step:…", "say": "<words for the user>", "then": "<command>" | null}],   (§10.1)
 "recovered": [{"message": "<words>", "ok": bool}],       interrupted steps this command finished first (may be [])
 "job": null | "job:…",                 the job that did the work (writes, §6)
 "as_of": {"scanned_at": "<iso>" | null, "read_at": "<iso>" | null},   how fresh the index and the playlist read are
 "sandbox": null | "<dir>"}
```

- `--jsonl` (job verbs and `job follow` only): one line per event (the window's event objects, `events.py`
  serialised as for the bridge, plus `{"event": "Job", …}` for start/end), then the envelope as the last line.
- **Versioning.** `v` is the envelope and payload major version. Within `v: 1` changes are additive only (new keys,
  new enum values documented in `help --json`); removing or renaming a key bumps `v`. Nothing old is kept around
  (one user, rule H5): a bump changes the docs and tests in the same commit. Each payload has a JSON Schema generated
  from the present layer's typed shapes (§8.1); `help <cmd> --json` prints it; a test pins that every command's real
  output validates against its schema.
- **Window URLs become paths.** Payloads carry `cover_path`, `path`, `upgrade.path`; the hub adapter alone turns
  them into `cover_url` / `audio_url` (a declared transform list, pinned by a test). An agent reads files, a person
  opens them (§4.5).

### 4.2 The human shape: readable text with the same facts

- Default output. Rendered **from the same payload** by one renderer per schema (`discjockey/cli/render/`), using the
  words the payload carries (§8). The rule a test pins: every field of the payload whose schema says `shown: true` is
  printed in text mode (as its words where it has words, else its value). The window's dimming, colours and badges
  are printed as their words (`FAKE · 16.0 kHz`, "dimmed: not in any playlist any more"); with a colour terminal the
  quality words also get their colour (`--no-color`, `NO_COLOR`).
- Lists are tables with the window's columns and order, then a count line ("12 of 340 shown · --limit 0 for all").
  Long lists page by `--limit N` (default 200 rows, `0` = all) and `--offset`; JSON carries `total` and `next_offset`
  (`library()` has no paging today, SC `library-big`).
- Progress and notices go to **stderr**; results to **stdout**; a problem's message to stderr with the exit code.
- Text is not a contract: it may change with the window's words. Scripts use `--json`.

### 4.3 Outcomes, reasons and exit codes (one table for every command)

| Exit | `outcome` | Meaning | Typical `reason`s |
|---|---|---|---|
| 0 | `ok` | Done for everything asked; a read; a dry run; a job started with `--detach` | — |
| 1 | `failed` | Something broke: nothing or only part was done, the rest stays as it was (journal) | `crashed`, `offline`, `ffmpeg`, `service_error`, `qobuz_login_failed`, `config_invalid` |
| 2 | `bad_args` | The command line is wrong; nothing was looked at | `usage`, `unknown_id`, `bad_id_kind`, `conflicting_flags` |
| 3 | `busy` | Another writer holds what this needs; nothing done. `data.holder` names it (`job`, `via` window/terminal, `kind`) | `library_lock`, `rekordbox_lock`, `import_running`, `sync_running` |
| 4 | `needs_person` | Only a person can unblock it; `person_steps` says what to tell the user | `rekordbox_open`, `login_needed`, `login_expired`, `keychain`, `full_disk_access`, `drive_missing`, `browser_sign_in` |
| 5 | `stopped` | Stopped by Ctrl-C or `job stop`; finished steps stay; `next` says how to carry on | `stop`, `stop_now` |
| 6 | `partial` | Ran to its end; some items were skipped or failed, each with its reason | — (per item) |
| 7 | `refused` | The rules say no; nothing done | `no_library`, `not_set_up`, `needs_yes`, `nothing_to_do`, `changed`, `not_stopped`, `setting_off`, `exists`, `protected`, `sandbox_required`, `outside_sandbox`, the `eligible.REASONS` keys for one item |
| 8 | `running` | `--wait` (or `job wait --timeout`) ran out; the job goes on: `job` holds its id | `still_running` |

- Every bridge `ProblemKind` (`types.ts:3`) maps to one row: `busy`, `console`, `sync_running` → `busy`;
  `not_set_up`, `no_library`, `setting_off`, `exists`, `changed`, `refused`, `protected` → `refused`;
  `login_expired`, `rekordbox_open` → `needs_person`; `offline`, `playlist_unreadable`, `config_invalid`,
  `qobuz_login_failed`, `login_failed`, `failed`, `crashed` → `failed`; `stopped` → `stopped`. The map lives in one
  table in the engine (`present/outcomes.py`) that both the CLI and the bridge use; the bridge keeps answering
  `{ok, kind, message}` to the window (CLAUDE.md invariant) and adds `outcome` beside `kind`.
- **Why these changes:** today exit 1 means refused, failed, crashed *and* "some skipped" (with `ok: true`), exit 2
  means both "usage error" and "no music folder", Ctrl-C is 5 in batches and 130 in the sync, and rekordbox open (4)
  is the only person step with a code (T §5.6). An agent needs: did it all work (0), may I retry later (3, 8), must I
  ask the user (4), did the rules refuse (7), did it break (1), did I call it wrong (2), is it half done (5, 6).
- Every refusal and failure carries `next` (the commands that move on) and, for `needs_person`, `person_steps`.
- `needs_yes`: a write that the window confirms, run without `--yes`, does nothing and answers `refused`,
  `reason: "needs_yes"`, with the confirmation's words in `message` and the dry run's `data` (so an agent can show
  the user exactly what the window would ask, §7.2).

### 4.4 Per-item results

Every bulk write's `data` holds `results: [{"track_id" | "file_id" | "id", "artist", "title", "action", "state":
"done" | "skipped" | "failed" | "planned" | "waiting" | "undone", "reason", "message", "path", "rekordbox": null |
{"entries", "kept"}, "person_steps": […]}]` plus the counts `total`, `done`, `skipped`, `failed`. A finished batch
with skips is `partial` (exit 6), never `ok` with exit 1.

### 4.5 Pictures and sound

| Picture in the window | `--json` data | Text mode | For a person or a vision agent |
|---|---|---|---|
| Spectrum (track, Now/New, sync card) | `track spectrum <id> [--which current\|upgrade]`: `cols`, `bands`, `max_hz`, `floor_db`, `duration_s`, `matrix` (base64 8-bit dB, as today) or `--matrix list` (nested lists), `cutoff_hz`, `verdict` {quality, label, words} | the verdict line, the cutoff sentence, and a 12×64 character sketch (shade per dB step, the cutoff marked `│`) | `--png <file>` writes the picture as the window draws it (colour map, cutoff line, axis label); `--open` opens it in Preview |
| Waveform (mini player, compare player) | `waveform` (base64 peaks) in the same answer, or `--waveform list` | a one-line sparkline | in the `--png` |
| Covers | `cover_path` in every row and track | the path | `open file <path>` |
| Quality bar, share strips, day bar | the counts and labels (`by_quality`, `parts[]` with `n`, `share`, `label`) | "9 lossless · 2 weak · 5 waiting" | — |
| 14-day usage chart, risk scale | `days[]` (date, used, zone), `zones[]` (name, from, to, tone), `limit`, `draft` | a bar per day with its zone word | `limits show <svc> --png <file>` |
| Quality colour, dimming, StatusMark tone | `quality`, `tone` (`good`/`warn`/`problem`/`none`), `dim` + `dim_why` | the word, coloured on a colour terminal | — |
| Sound (players, 20-s clips, A/B compare) | `path` of each file; `version preview` writes the clip and gives its `path` | the paths | `open file <path>` plays it in the Mac's player; listening is a person step (§10.1) |

PNG writing uses the standard library (`zlib` + `struct`, no new dependency); the colour map is the one the
window's canvas uses, exported once from the engine (§8) so both draw the same picture.

---

## 5. The command catalogue

### 5.1 Nouns

| Noun | What it is to the user | Verbs |
|---|---|---|
| `help`, `where`, `status`, `doctor`, `history` | finding one's way; the whole picture; health; what changed | (§2.3, §11) |
| `library` | the Library page's collections and table | `list`, `collections`, `scan`, `favourites`, `superseded` |
| `track` | one song and its file | `show`, `find`, `spectrum`, `hide`, `unhide`, `undo` |
| `todo` | the To-do page | `list` |
| `upgrade` | parked better versions | `list`, `apply`, `discard` |
| `aiff` | Convert to AIFF / Give it its clean name / Make AIFF / Convert all | `convert`, `rename` |
| `check` | "Done, checked in rekordbox" reminders | `list`, `done` |
| `duplicate`, `question` | the import's answers | `list`, `keep` / `list`, `answer` |
| `version` | Find a version / Wrong song? / a bought file | `search`, `preview`, `use`, `reject`, `add-file` |
| `batch` | every undoable change the user started (AIFF and move batches) | `list`, `show`, `resume`, `undo` |
| `tidy` | Tidy up files | `run` |
| `sync` | read the playlists, the plan, the run | `read`, `plan`, `run`, `scope`, `never`, `again` |
| `run` | past syncs (reports) | `list`, `show` |
| `playlist` | playlists.txt | `list`, `check`, `add`, `remove`, `rename`, `move`, `enable`, `disable`, `add-liked` |
| `folder`, `import` | watched folders and the import | `list`, `check`, `add`, `remove`, `crates` / `status`, `run` |
| `limits` | Download limits | `show`, `set`, `seen` |
| `login` | download and playlist accounts | `list`, `find`, `use`, `sign-in`, `check`, `sign-out`, `skip`, `qobuz`, `spotify` |
| `settings` | the remaining switches | `show`, `set` |
| `setup` | the setup guide's state and the music folder | `status`, `music`, `skip-import` |
| `tools`, `app` | programs, versions | `status`, `update`, `rollback` / `info`, `open`, `install-command` |
| `rekordbox` | rekordbox's library | `status`, `preview`, `match`, `backups`, `restore` |
| `job` | long work in any process | `list`, `show`, `follow`, `wait`, `stop` |
| `open` | the window's "Show in Finder" and links, for a person | `file`, `folder`, `url`, `report`, `licences`, `privacy-settings` |
| `sandbox` | a safe copy to rehearse on | `create`, `info`, `remove` |

### 5.2 Every bridge method → its command

Kinds: **R** read (no lock, never writes), **J** write job (§6), **B** brief save (no lock, answers at once),
**W** window only. "New args" names bridge signature changes the design needs (contract changes, §16).

| Bridge method | Command | Kind | Notes |
|---|---|---|---|
| `library(view,key,query,filter,sort)` | `library list [--in C] [--search W] [--quality Q] [--sort S] [--limit N]` | R | rows incl. `also`, chips, summary, subtitle, songs, empty (six states, words), `as_of`; `file_state` incl. `file_missing` per row (§9 L-D, SC) |
| `track(id)` | `track show <track>` | R | the whole details payload + `decision`, `actions[]`, `why` (§11), `rev`; valid for a song still waiting (D21) |
| `todo(filter,show_hidden)` | `todo list [--group G…] [--hidden]` | R | all groups incl. checks, questions, duplicates, chips, `check_tracks`, `hidden_count`, `empty`, each item's `id`, `actions[]` |
| `sidebar()` | `library collections` | R | the collections list as the browser draws it (sections, order, counts, away marks), and the nav counts |
| `watched_folders()` | `folder list` | R | rows, unreadable files, `waiting`, import `state` (`stopped` now on disk, §9) |
| `removal_preview(id)` | `folder remove <folder> --dry-run` | R | |
| `check_import_folder(path)` | `folder check <path>` | R | |
| `aiff_plan(scope)` | `aiff convert … --dry-run`, `aiff rename … --dry-run` | R | the same `AiffPlan`; a dry run never writes (facts read in memory, §12) |
| `tidy_preview()` | `tidy run --dry-run` | R | |
| `move_batches()` | `batch list [--kind moves]` | R | one list for both batch kinds, typed ids |
| `undo_preview(batch)` | `batch undo moves:<n> --dry-run` | R | |
| `rekordbox_status()` | `rekordbox status` | R | the console's richer answer becomes the bridge's too (problem, version) |
| `job_status()` | `job list`, `job show <job>`, `status` | R | from the job registry: window and terminal jobs alike (§6) |
| `spectrum(id,which)` | `track spectrum <track> [--which current\|upgrade] [--png F]` | R | §4.5 |
| `media_url(id,which)` | — | dropped | no UI caller (L, T); paths are in the payloads |
| `dashboard()` | `status` | R | plus counts, jobs, problems, `--ready` (§11) |
| `runs()` | `run list [--since T] [--limit N]` | R | |
| `run(run_id)` | `run show <run\|last>` | R | the end screen's whole data, one engine definition of "what a run did" (§9 U14) |
| `open_report(run)` | `open report <run>` | R (person) | prints the `.md` path; opens it unless `--print` |
| `sync_preview()` | `sync plan [--search W]` | R | the stored plan (§9: persisted), with scope, presets, next-sync set, estimate, folds; `plan_id` |
| `refresh(auto)` | `sync read` | J | reads playlists (network), scans, stores the plan on disk |
| `stop_refresh()` | `job stop <job>` | J-control | |
| `start_sync(selected)` | `sync run [selection] [--plan P] [--limit N] [--auto-upgrade-only] [--dry-run]` | J | §7.3; `--auto-upgrade-only` runs only the last phase (T J11 C) |
| `stop()` | `job stop <job\|current> [--now]` | J-control | reaches a window job too (stop file, §6.3); new arg `job_id` |
| `never_download(id,never)` | `sync never <track…>`, `sync again <track…>` | J | |
| `setup_status()` | `setup status` | R | six steps incl. "Your existing music" (§9 U32) |
| `app_update()` | `app info` | R | |
| `rescan_library()` | `library scan` | J | |
| `quit()` | — | **W** | closes the window; a command has no window to close. When a change needs the window reopened, the command says so as a person step |
| `open_external(url)` | `open url <url>` | R (person) | prints the URL; opens it unless `--print` |
| `reveal(rel_path)` | `open folder <path\|collection>` | R (person) | same place check as today |
| `show_in_finder(id,which)` | `open file <track> [--upgrade]` | R (person) | |
| `select(id)` | — | dropped | only told the hub where a drop goes; the drop's path now travels in `FileDropped` and back in `add_bought_file` |
| `hide(id,hidden)` | `track hide <tracks>`, `track unhide <tracks>` | J | selection of several (issue 41), `--if-rev` |
| `limits(service)` | `limits show [<service>] [--png F]` | R | cards, usage, days, signals, zones, `suggestion` (§9 U21) |
| `limits_what_if(s,l,e)` | `limits set <service> <n> [--extra-today N] --dry-run` | R | what-if = the set's dry run |
| `save_limits(s,l,e)` | `limits set <service> <n> [--extra-today N]` | J | replaces the sync's `--extra N` (which wrote settings even in a dry run) |
| `mark_warnings_seen(s)` | `limits seen <service>` | J | |
| `playlists()` | `playlist list` | R | names/covers from the stored read (§9), overlaps, tidy waiting |
| `add_playlist(url)` | `playlist check <url>` | R (network) | the found card; `suggested_folder`; duplicates by `sources.recognise` |
| `preview_playlist_change(lines)` | `--dry-run` of every `playlist` write | R | new arg `op` (the engine applies the edit, §9 U25) |
| `save_playlists(lines,ver,files)` | `playlist add <url> [--folder F] [--at N]`, `remove`, `rename`, `move --to N`, `enable`, `disable`, `edit --file <playlists.txt>` | J | `--files move\|leave`, `--no-rename` answer the save question; `--if-version` |
| `set_read_liked_music(on)` | `settings set read-liked-music on\|off` | J | |
| `add_liked_music()` | `playlist add-liked` | J | |
| `tidy_up(moves)` | `tidy run [<file>… \| --all] [--with-yours] [--plan P]` | J | `--all` = the rows the engine ticks; `--with-yours` = "Put these in playlist order too" |
| `undo_moves(batch)` | `batch undo moves:<n> --yes` | J | |
| `downloads_view()` | `login list` | R | per source state, last check, ladder (rungs lit, sentence) (§9 SB ladder) |
| `find_logins(service)` | `login find <service>` | R | plus `offer`: the browser/profile the window would offer first |
| `setup_account(s,b,p)` | `login use <service> --browser B [--profile P]` | J | may raise a keychain prompt: `needs_person` step `step:keychain` |
| `account_sign_in(s,b,p)` | `login sign-in <service> [--browser B] [--profile P]` | J (person) | opens the browser, waits ≤ 10 min for the person |
| `stop_sign_in()` | `job stop <job>` | J-control | |
| `open_privacy_settings()` | `open privacy-settings` | R (person) | |
| `setup_check_account(s)` | `login check <service>` | J | unused by the window; the bridge method is dropped, `login check` re-runs `setup_account` with the saved browser |
| `setup_forget_account(s)` | `login sign-out <service> --yes` | J | |
| `qobuz_check_login()` | `login check qobuz` | J | |
| `setup_qobuz_login(e,p)` | `login qobuz --email E --password-stdin` | J | the password never on argv or in the environment |
| `setup_skip_qobuz()` | `login skip qobuz` | J | |
| `setup_save_client_id(id)` | `login spotify --client-id ID` | J | |
| `setup_spotify_login()` | `login sign-in spotify` | J (person) | |
| `spotify_sign_out()` | `login sign-out spotify --yes` | J | |
| `setup_skip_spotify()` | `login skip spotify` | J | |
| `set_auto_upgrade(on)` | `settings set auto-upgrade on\|off` | J | |
| `setup_check_tools()` | `tools status` | R | |
| `update_tools()` | `tools update` | J | touches only the support folder: no music folder, no library lock (A §5.3) |
| `rollback_tools()` | `tools rollback --yes` | J | |
| `open_licenses()` | `open licences` | R (person) | |
| `set_favourites(keys)` | `library favourites add\|remove <collection…>`, `library favourites move <collection> --to N` | B | the engine applies the edit (§9 D26) |
| `set_crate_shown(p,s)` / `set_crates_shown(ps,s)` | `folder crates show\|hide\|default <path…>` | B | the engine decides what override to store (§9 D24) |
| `pick_folder(start)` | — | **W** | the Mac's folder dialog; every command takes the path as an argument |
| `check_music_folder(p)` | `setup music <path> --dry-run` | R | |
| `set_music_folder(p)` | `setup music <path> [--yes]` | J | `--yes` where the window asks (`other_files`); an open window keeps its folder until reopened: person step |
| `retry_music_folder()` | `setup status` | R | a command resolves the folder fresh every time; nothing to retry |
| `setup_skip_import()` | `setup skip-import` | B | |
| `add_watched_folder(path)` | `folder add <path>` | J | imports in the same job |
| `start_import()` | `import run` | J | |
| `remove_watched_folder(id)` | `folder remove <folder> --yes` | J | |
| `answer_same_song(s,o,same)` | `question answer <same:…> yes\|no` | J | |
| `keep_duplicates(g,paths)` | `duplicate keep <dup:…> --all` | J | |
| `supersede_duplicate(g,f,paths)` | `duplicate keep <dup:…> <file>` | J | replaced by one engine op "keep this file" (moves every other file of the group, one job; §9 D10) |
| `convert(ids,origin)` | `aiff convert <tracks> \| --rows …` | J | |
| `rename(ids)` | `aiff rename <tracks> \| --all \| --rows …` | J | |
| `make_aiff(scope)` | `aiff convert --all [--in C \| --todo cdj]` | J | Make all lossless files AIFF / Convert all |
| `batch_resume(b)` | `batch resume aiff:<n>` | J | |
| `batch_undo(b)` | `batch undo aiff:<n> --yes` | J | the window's "Undo all" uses it too (today it sends track ids, T §1.2) |
| `undo_upgrade(ids)` | `track undo <tracks> --yes` | J | undoes the last file step of each track (replace, Same track, Convert, clean name) |
| `upgrade(ids,mode)` | `upgrade apply <tracks> --way same-track\|new-track`, `upgrade discard <tracks> --yes` | J | mode enum becomes `same_track\|new_track\|discard` |
| `upgrade_all()` | `upgrade apply --all` | J | refused while a stopped upgrade batch waits (`not_stopped` → `next: batch resume`), as the window hides it |
| `rekordbox_checked(ids)` | `check done <tracks> \| --batch aiff:<n> \| --all` | J | |
| `add_bought_file(id)` | `version add-file <track> <path>` | J | new arg `path` (T §1.3) |
| `search_candidates(id)` | `version search <track>` | R (network) | refused `busy`/`sync_running` while a sync runs (Qobuz pacing) |
| `preview(id,cand)` | `version preview <track> <cand:…>` | R (network) | writes the 20-s clip to the cache, prints its `path` |
| `use_candidate(id,cand)` | `version use <track> <cand:…>` | J | Qobuz limit counts as in the window |
| `use_link(id,url)` | `version use <track> --link <url>` | J | |
| `reject_current(id)` | `version reject <track> --yes` | J | "None of these" |

95 methods: **2 window only** (`pick_folder`, `quit`), **3 dropped** (`media_url`, `select`, `setup_check_account`),
90 with a command. A completeness test pins this table (§13).

### 5.3 Commands with no bridge method (new reads the window lacks)

| Command | Why |
|---|---|
| `help …`, `where` | discovery (§2.3) |
| `status [--ready]` | one cross-screen answer; `--ready` is the gig check (§11) |
| `doctor` | health: folder, tools, logins, rekordbox readable/unclean, a stale lock, lost jobs, pending journal steps, drives away, Qobuz paused, files out of place, `Superseded/` size, rekordbox tracks on missing or superseded files |
| `history [--since T]` | runs, batches and logged operations, newest first (§11) |
| `track find` | ids from words or a path |
| `library superseded` | what sits in `Superseded/`, its size, and which files rekordbox still points at (L J16) |
| `rekordbox match [--in C]` | rekordbox tracks whose file is missing, moved to `Superseded/`, or not in the library; library files rekordbox lacks |
| `sync scope …` | the Sync page's switches, now saved settings (§9 U1) |
| `import status` | the import card's state as data |
| `job …`, `sandbox …`, `app install-command` | §6, §10.3, §2.1 |

`rekordbox preview` gains `folder_path`, `content_file` and `updated_at` per entry (T J11 B 9b: no command showed
them).

---

## 6. Long runs, jobs and the open window

### 6.1 Every write is a job in a registry both front ends share

- **Registry:** `<music>/.discjockey/jobs/<job id>/` with `state.json` (id, kind, args, `via` window|terminal,
  `pid`, `status` queued|running|stopping|done|lost, `started`, `ended`, the reduced progress: index, total, current
  item, step, waiting, counts, the one-line `line` the window's foot shows), `events.jsonl` (every event, as the window
  receives it), `result.json` (the final envelope) and `log.txt` (warnings and tracebacks of that job: today there is
  no log file at all, A §5.6). Kept: the newest 100 jobs or 30 days.
- **The window's jobs register too** (`hub/jobs.py` `Jobs.start` writes the same files in-process). So `job list`
  shows window jobs, the window shows terminal jobs, and `status` answers "is something running, which, how far" for
  everyone (today a command can only learn that from an exit-3 refusal, L §1a `job_status`).
- **Terminal jobs run in a worker process, never in the client.** A write command validates its arguments, writes the
  job's `state.json` (`queued`), starts the worker (`Discjockey job _worker <id>`, a new session, its own `caffeinate`)
  and then **follows** it: progress to stderr, the final envelope to stdout. Killing or closing the client (an
  agent's tool call timing out, a closed Terminal tab) never kills the work. Ctrl-C in an attached client is
  forwarded: the first press stops after the current item, a second press at least a second later stops at once
  (today's semantics, `CTRL_C_REPEAT_S`).
- **The worker takes the library lock**, not the client. Busy → the worker writes the `busy` envelope and ends; the
  client prints it (exit 3) unless `--wait-busy <s>` lets the worker retry until then (rides out the window's opening
  scan and its 60 s rescan, L D28; today a command meets them with an immediate exit 3).
- **Brief saves** (favourites, crate switches, skip import) are not jobs: they answer at once, as in the window.

### 6.2 Waiting and following

| Want | Command | Answer |
|---|---|---|
| Start and get the id at once | `<write> --detach` | `outcome: ok`, `job: "job:…"`, `data.status: running`, exit 0 |
| Wait at most N seconds | `<write> --wait 120` | the job's own envelope if it ended, else `outcome: running` (exit 8) with `job` |
| Follow events | `job follow <job> [--jsonl]` | the events from the start (or `--from-end`), then the final envelope; text mode = the console's progress lines |
| Wait for the end | `job wait <job> [--timeout S]` | the job's envelope (its own outcome and exit code), or `running` (exit 8) |
| See it | `job show <job>` | `state.json` + the last events + `result` when done |
| Stop it (any process, also the window's) | `job stop <job\|current> [--now]` | `stopping`; the job ends `stopped` (exit 5 for whoever waits). `--now` = the second Ctrl-C; for a window job it is refused (`refused`, `reason: "window_job"`): the window offers only "Stop safely" |
| Everything running and recent | `job list [--all]` | running first, then newest |

Default without `--wait`/`--detach`: follow to the end (a person in the Terminal sees today's behaviour). The agent
guide tells agents to pass `--detach` or `--wait 120` on every long write, then `job wait --timeout 300` in a loop.
A job whose worker died (pid gone, status still running) shows `lost`; the next writer's `recover_pending` finishes
its journaled step as today, and `doctor` names it.

### 6.3 Stopping a run another process started

`job stop` writes `jobs/<id>/stop`. `CancelToken` gains a file check: `cancelled` is true when its event is set **or**
the job's stop file exists (stat at most every 0.5 s). Every place that checks the token today (between items, inside
steps, in pacing sleeps) therefore stops for a request from any process, the window's own jobs included. `--now` (a
terminal job only) sends SIGINT twice to the worker, as two Ctrl-Cs do. Test: a window job and a terminal job both end
`stopped` after a stop file appears, and nothing half done remains.

### 6.4 The window open at the same time

| Topic | Rule |
|---|---|
| Shared library | one music folder, one `library.db`, one lock (`.lock`); the window binds its folder at start, commands resolve it fresh each time; `where` says `window_open` |
| The lock | the arbiter stays the lock: one writer at a time. Window writes refused while a terminal job holds it answer `console` (bridge) as today; terminal writes answer `busy` with `holder` |
| Who sees whose runs | the registry: the window's "console running" banner reads the terminal job's `state.json` (kind and `line`: "Sync running in the Terminal · 4 of 60"), and the Sync page can show its live view from `events.jsonl`; `job list` and `status` show the window's jobs. The 3 s lock probe stays only as the fallback for a holder without a registry entry |
| Who sees whose batches | all batches in one table: `batch list` and the window list the same rows. The `console` scope is dropped: a batch records where it started (`via`) and its real scope (`library:<view>[:<key>]`, `todo:cdj`, `selection`), so the window's Resume links show stopped terminal batches too (T §0.5) |
| A command's changes in the window | the window re-reads on every `JobFinished` it sees; terminal jobs now produce one in the registry, so the window refreshes after a terminal write of any length (today a command shorter than the 3 s probe was never noticed, A §5.6) |
| The stored plan | the plan lives on disk (§9.2), so the window's Sync page and `sync plan` show the same plan, and a terminal sync re-plans it at its end like a window sync (`preview_after_run`); today a console run left the window's plan stale |
| The window's own automatic work | scan at open and after 60 s in the background, the first read, the automatic import once per session: they stay window behaviour (a person opened the window). Commands never start them by themselves; an agent runs `library scan`, `sync read`, `import run` |
| A music folder change | `setup music <path>` writes `config.json`; an open window keeps its folder until reopened: the answer carries `person_steps: [step:reopen_window]` when `window_open` |

---

## 7. Writes: dry runs, confirmation, undo, selection

### 7.1 Dry runs and the gap to the apply

- **Every write that moves, renames, converts or deletes a file, writes rekordbox, edits playlists.txt or changes what
  a sync will do has `--dry-run`.** A dry run takes no lock, writes nothing (no `settings.json`, no facts, no
  `library.db`) and answers exactly what the window shows before the person presses the button: the AIFF plan, the
  tidy rows, the undo preview, the removal preview, the playlist change's preview with its save question, the limit's
  what-if, the upgrade's ways and outcomes. Today `convert --dry-run` fills facts under the lock and `--extra N` writes
  settings in a dry run (L §5, A §1.4): both stop (the dry run reads missing facts in memory, `importer` facts code
  split into "read" and "store").
- **The plan id.** A dry run's answer carries `data.plan_id` (`plan:<12 hex>`) and stores the plan in
  `.discjockey/plans/` (24 h). `<write> --plan <id>` runs **only the items of that plan**: each item is asked again as
  it runs (the engine's per-item checks stay), an item whose answer changed is skipped with `reason: "changed"`, an
  item that is new since the plan is left out and listed under `data.new_since_plan`. This is the window's sync rule
  (`run.select_actions` with `new_since_preview`) made general. Without `--plan` a write plans fresh, as the window
  does when the person presses a button without a panel. The agent guide says: dry run → show the user → apply with
  `--plan`.
- Writes with a version instead of items keep their version check: `playlist … --if-version <v>` (the file's hash,
  `playlists_file.save`), single-record writes `--if-rev <rev>` (§3).

### 7.2 Confirmation without prompts

A command never prompts (the interactive `setup`, `upgrades` and the sync's "Proceed?" go, §12). `--yes` is required
exactly where the window asks a person first, and nowhere else:

| Needs `--yes` (the window confirms) | No `--yes` (the window doesn't ask) |
|---|---|
| `upgrade discard` (deletes Discjockey's own parked download), `track undo`, `batch undo`, `version reject` ("None of these"), `folder remove`, `login sign-out`, `tools rollback`, `rekordbox restore`, `setup music` onto a folder with other files, `sandbox remove` | `upgrade apply`, `aiff convert/rename`, `check done` (the window doesn't ask; the answer's `message` says the undo ends), `tidy run`, `duplicate keep`, `question answer`, `sync run`, everything else |

Without `--yes`: `refused`, `reason: "needs_yes"`, `message` = the window's question and body, `data` = the dry run.

### 7.3 Selection: one, several, all

Every bulk write takes exactly one of three forms (a usage error otherwise):

| Form | Means | Window equivalent |
|---|---|---|
| `<ids…>` or `-` | these items (ids, paths, or ids read from stdin: one per line or a JSON array, so `… list --json \| jq` pipes in) | click, ⌘-click, ⇧-click |
| `--all` | the verb's own "all" button where it is used: `upgrade apply --all` = Upgrade all; `aiff convert --all --in C` = Make all lossless files AIFF in that view; `aiff convert --all --todo cdj` = Convert all; `aiff rename --all [--in C]`; `check done --all`; `tidy run --all` = the rows the engine ticks | the group head's "… all" |
| `--rows` with `--in C` or `--todo G`, and `--search`, `--quality` | **every row that listing shows**, as `library list` / `todo list` with the same flags prints it: filter and search applied, a playlist's `also` rows included, rows without a file left out | ⌘A on the screen with that search and filter |

- One engine function answers "which ids does this listing select" (`present.select(listing)`), used by `--rows` and
  by the window's ⌘A, which sends the listing instead of the ids (bridge: every bulk write accepts
  `{"tracks": [...]} | {"listing": {view, key, query, filter} | {todo, show_hidden}}`). So the window's "all" and
  the command's "all" are the same answer by construction (L D15).
- Each item a selection names that the verb can't act on is a `skipped` result with its reason (today's engine rule);
  `--all` never includes them.

### 7.4 Undo

| Undo | Command | Dry run |
|---|---|---|
| A whole batch (AIFF or moves), newest step first | `batch undo <aiff:n\|moves:n> --yes` | `--dry-run`: per item whether it can be undone and why not (`upgrades.can_undo`, `undo_preview`) |
| The last file step of tracks (replace, Same track, Convert, clean name) | `track undo <tracks> --yes` | `--dry-run` |
| A setting, a never-download, a hide, a crate switch, a favourite | the opposite verb (`settings set`, `sync again`, `track unhide`, …) | n/a |
| rekordbox's whole library | `rekordbox restore <backup> --yes` (rekordbox closed) | `--dry-run`: `missing_after` |
| "Undo yesterday's work" | `history --since yesterday --json` lists the batches; undo each newest first | each `--dry-run` |

What can't be undone is said before: `check done` ends the undo of those tracks (its answer's `message`), `upgrade
discard` deletes a parked download for good, `duplicate keep` moves files to `Superseded/` without an undo (today's
D10 rule; the files stay there and the answer lists their paths).

---

## 8. "Everything the window shows" by construction (H1)

Three mechanisms together make a gap impossible rather than unlikely: one source of payloads, one source of words, and
checks that fail on anything the window shows from elsewhere.

### 8.1 One surface for both front ends

- New package **`discjockey/surface/`**: one function per bridge method, same name, same arguments, returning the
  payload (`surface.reads`, `surface.writes` (each write = a validated job spec), `surface.jobs` (runner + registry),
  `surface.select`, `surface.outcomes`). It gathers what it needs from disk (state, settings, the stored plan, the
  rekordbox status, file presence) and calls the pure `views.py` (which stays pure).
- `HubApi` becomes an adapter: the `bridge` decorator, the path→URL transform, events to the page, and the two window
  methods. The CLI is the other adapter: parsing, rendering, the job client. **Neither adapter may compute a fact**;
  a test (§13 T3) checks each `HubApi` read method body is a call to its `surface` twin plus the declared transform.
- `discjockey/surface/catalog.py` is the one table of §5.2 in code: method → command path, kind, `needs_yes`,
  `dry_run`, job kind, schema name, or `WINDOW_ONLY` with a reason from a closed set (`native_dialog`,
  `closes_window`). Parser, `help --json`, the agent reference and the tests are generated from it.
- Every payload is a `TypedDict` per schema in `surface/shapes.py`, the source of the JSON Schemas (§4.1), of
  `hub-ui/src/lib/bridge/types.ts` (generated, replacing the hand-kept copy) and of the text renderers' field lists.

### 8.2 One source of words: the word catalogue

- **`discjockey/surface/words.py`** holds every user-visible sentence, label and tooltip the window shows, keyed
  (`quality.fake.word` "fake lossless", `upgrade.why_not.not_analysed` "Same track needs the track analysed in
  rekordbox first. …", `check.step.reload_tag`, `ui.button.replace`), with named fields and plural forms. There is
  one copy of each (today: `REASON_WORDS` 24 keys in the engine vs `SAME_TRACK_WHY`/`WHY_NOT_LINE` in the UI, two
  size-word functions, T §0.4, L D36).
- **Words that carry data are filled in by the engine** and travel in the payload next to their facts:
  `next_try` + `next_try_text` ("next try in 3 days"), `quality` + `quality_word`, `dim` + `dim_why`, `actions[]`
  with `label`, `primary`, `blocked` + `blocked_text`, `steps[]` of a rekordbox check, `outcomes[]` with `tone` and
  `text`, `empty` + `empty_text`. The window renders them; the CLI prints them.
- **Words that carry no data** (headings, button labels, static explanations, the badge glossary) are exported from
  `words.py` into `hub-ui/src/lib/generated/words.json` by `python -m discjockey.surface.words --export` (committed,
  checked by CI like `hub/static`). The UI imports them; `help glossary` prints the same catalogue with each entry's
  meaning, so every tooltip is reachable from the Terminal.
- **The rule checker** (`npm run rules`, new check `words`) fails on a user-visible string literal in
  `hub-ui/src/{pages,lib}` that does not come from `words.json` or a payload: text nodes, `title=`, `aria-label=`,
  `placeholder=`, and string returns of `*Model.ts`, `copy.ts`, `format.ts`. Allowed: class names, ids, routes, test
  ids, numbers and dates formatted by one shared `format.ts` helper set listed in the checker. During the build a
  ratchet file `hub-ui/words-ratchet.json` (file → count) may only shrink; the last build group empties and deletes
  it. From then on the window **cannot** show a word the engine lacks.
- Dates and numbers: the engine sends ISO dates and raw numbers plus the text ("31 Oct", "today", "1.2 GB"); the
  window may format a number it receives (grouping, `m:ss`) only through the shared helpers, which mirror
  `surface/words.py` formatters and are pinned against them by a shared fixture test.

### 8.3 Shown information and screen states, checked

- Each fake scenario in `hub-ui` already has the real bridge's data. New: every `shots.json` entry declares
  `reads: ["track", "todo", …]` (the bridge reads behind it) or `view: "<reason>"` from a closed set (`layout`,
  `open_panel`, `selection`, `player`, `menu`, `scroll`, `loading`, `width`). A vitest fails on an entry with neither.
  A Python test runs, for every declared read of every scenario's library, the command twin and checks the payloads
  are equal (§13 T4). A new screen state therefore names its command, or argues why it is only a view.
- Supplement C's `file_missing` surprise is closed by the same rule: `file_state` is computed once in the surface
  (one stat per file, I/O outside `views.py`), so a row and the details agree.

---

## 9. State and logic move into the engine

### 9.1 The rule

A computation the window does today **moves into the surface/engine** when it does any of:
(a) decides which items an action applies to, what it will do, or whether it may run;
(b) produces a fact, count, order, state, colour/tone or dimming the person reads;
(c) produces a sentence that carries data.
It **stays in the window** only when it is: layout and geometry; which panel, menu, dialog or fold is open; focus,
selection, scroll, hover; audio playback; timers and animation; an unsent draft; per-window view preferences (the sort
and filter remembered per view, A–Z, widths, folded sections, details hidden). Where the window *uses* a moved answer,
it calls the bridge field instead of its own copy, and the copy is deleted in the same change.

### 9.2 State the window holds today, and where it lives now

| State today | Where it moves | Why |
|---|---|---|
| `PreviewStore.prep` (the last read's plan), `read_at`, read problem, `stale`; `_infos` (playlist names, covers) | `.discjockey/plan.json` (+ `plan_infos.json`), written by `sync read` and the window's read; re-planned without network when library state changes (today's `replanned_work`) | the Sync page, `library().rows[].track_link`, the questions and `dashboard.ready` exist only after a read in the same window (A §0) |
| "Is this the same song?" questions and same-song duplicate groups (inside `prep`) | derived from `plan.json` by `surface.reads.todo`; `question list` | an agent can neither list nor answer them today (L finding 4) |
| Sync scope switches (localStorage `sync.scope`), weekly checks on/off | `settings.json` `sync_scope` {`off`: [collections], `weekly_off`: [kinds]}; `sync scope show/on/off`; the window's switch becomes a brief save | the run's selection must be the same for the window and an agent (A U1) |
| Ticks and "how many" | stay a window draft; the presets and the default are engine answers (`sync plan` `presets`, `default_how_many`); `sync run` takes them as flags | a draft until Start is a view; what a choice means is not |
| `sync.lastSelection` (localStorage) | the job's `args` in the registry | the window's run list needs it after a reload; so does `job show` |
| `_shown` | `rev` tokens (§3) | stateless, works across processes |
| `_dropped`, `_selected` | the drop's `path` travels in `FileDropped` and back in `add_bought_file(track_id, path)` | a command passes a path (SA finding 3) |
| `_import_stopped`, `_import_auto_done` | `library.db` import state (`stopped_at`, `waiting`); the auto import stays a window behaviour keyed on it | "Import stopped, n to go" must survive the window and be readable (L D29) |
| `Jobs.current`, `refresh`, `sign_in` | the job registry (§6) | |
| `_qobuz_streak` | stays (protection counter, already reset per sync) | invariant, not view |
| `_cdj_cache` | stays a cache (keyed by records generation) | no meaning |
| Recent toasts | each job's `result.json` | |

### 9.3 The rule applied to the audit rows

Ids: **L D1–D37** (library audit §2), **U1–U39** (app audit §2), **T:`fn`** (todo audit §2, by function), **SA/SB:
`file:fn`** (supplements). "→ field" names where the answer lives after the move.

**Moves into the surface/engine (the window deletes its copy):**

| Rows | What moves | → where |
|---|---|---|
| L D1 | a route name is a playlist or a Library folder | `surface.resolve_collection(name)`; `--in` uses it |
| L D5, T:`decisionFor`, SA `TrackDetails` decision choice | which decision a track waits for (check > duplicate > upgrade) | `track().decision` {kind, item id} |
| L D6, SA `rowInTodo`/`inTodo` | "is it on the To-do list" (today it **diverges** from `views._group`/`todo_listed`) | row and track field `in_todo`, from the engine's one rule |
| L D7, D34, T:`actionsFor`/`IMPROVABLE`, SA `footAction`, `aiffShown`, `aiffVariant`, T `Details.aiff` | which actions an item/row offers, which one is the filled button, which menu items exist | `actions[]` {id, label, primary, blocked, blocked_text, command} on rows, tracks, to-do items |
| L D8, T:`canSwap`/`upgradeWays`/`defaultWay`/`UpgradeFlow.way`, `goes`/`NOWHERE`, `selectionWays`/`beforeLine`, SA `UpgradeCards` | the ways an upgrade offers, the default, the mode Replace sends with no choice, each way's outcomes, which selected items a way reaches, the n/m/k counts | `upgrade.ways[]` {way, recommended, outcomes[] {tone,text}, why_not_text}; `upgrade apply --dry-run` summary |
| L D9, T:`undoAsk`/`undoManyConfirm`, SB `ConfirmHost` callers | which actions confirm and their words | catalogue `needs_yes`; `confirm` {title, body, label} in the dry run |
| L D10, T:`groupIdOf` + `DuplicateFlow.#keepOne`, SA `DuplicateFoot` | "keep this file" as N−1 jobs with the group id recomputed in JS | one engine op `folders.keep_file(group, file_id, expect)` in one job; answer names the track holding the kept file (L D4 data part) |
| L D11, T:`keepWords`/`fileWords`/`fileFormat`/`lastFolder`/`keepLabel` | the duplicate's button and file words | `pair.files[].words`, `pair.keep_label` |
| L D12, D13, D14 (except `panelPhase`, `listShape` fold), T `aiffModel.*`, `aiffBatchModel.*`, SA `AiffCard`/`AiffFoot` | why Convert/Rename/Make is off (space, rekordbox open), button words, rows Now/Becomes/Name/Space, outcomes, notes, "Left as they are", drive names ("this Mac") | `aiff` card fields and `AiffPlan` gain `blocked`, `blocked_text`, `label`, `rows[]`, `outcomes[]`, `notes[]`, `left[]`, `space[].drive_name` |
| L D15, T:`cdjAllKeys`/`cdjReachable`/`wholeCdjGroup`/`upgradeAllKeys`/`wholeUpgradeGroup`/`multiScope`/`MULTI_GROUPS`, T `AiffBatchFlow.start` | what "all", ⌘A and a whole group select; which groups allow several | `surface.select(listing)` (§7.3); `groups[].multi`, `groups[].all` |
| L D19, D20, D21, D22, SA `noFileNote`, `waitWords`, `notFoundTip`, `cutoffStat`, `qualityWords`, `fileAwayWords`, `titleNote`, `placeLine`, SA `TrackHead` line | empty states (six), "next try in N days", the no-file note, quality and cutoff words, away words, place words | `empty` + `empty_text`; `next_try_text`; `why` (§11); `quality_word`, `cutoff_text`; `file_state_text`; `place_text` |
| L D23, D25, SA `RowLead` | the collections list as drawn: "Not in a playlist" only when > 0, one row per folder path, playlists in playlists.txt order, away marks, which can be shown in Finder | `library collections` sections; `reveal_path` per collection (A–Z order stays a view pref) |
| L D24, U34, SB `cratesModel`, `CrateSwitches` | a crate's default visibility and what override to store | `folder crates` takes the wanted state; the engine stores the override or `null` |
| L D26 | favourites add/remove/move | engine list ops |
| L D29, U33, SA `ImportCard`, `WatchedFolderList`, `watchedFoldersModel.*` | import card state, phase words, "Continue import" offered, folder state lines and marks | `import status` {state, phase, phase_text, can_continue, waiting}; folder rows `state_text`, `tone` |
| L D31, D32, D33, U27, SB `TidyList`, `tidyModel.*` | tidy ticks, the save question's payload, count line, result words, undo target | `tidy run` / `playlist … --files move\|leave --no-rename`; rows' `group` (main/yours/skipped), `count_text`, result `headline` |
| L D17 | which rows play (`file_state == here`) | row `playable` (the queue itself stays window) |
| L D36, U39, SB `ToastHost` | size words; problem and success sentences | `words.py` |
| T:`sameTrackWhy`/`WHY_NOT_LINE` vs `REASON_WORDS` | two word lists for one reason set | one list in `words.py` |
| T:`checkCard`/`batchCheckCard`/`USB_STEP`/`RELOCATE_NEW`/`BEATGRID`/`keptLine`/`inRekordbox`/`isOwnCheck`, SA `CheckCards`, `BatchCheckCards` | the numbered rekordbox steps after a replace or convert, per track and per batch | `check.steps[]` = `person_steps` (§10.1) + `check.summary`, `in_rekordbox` |
| T:`replacedCard`/`undoTitle`/`undoLabel`/`doneLabel`/`undoneToast`/`undoFoot`, SA `CheckFoot`, `BatchCheckFoot` | what was replaced where, Undo/Done words, which tracks Undo offers, "k can't be undone" | `check.replaced` {rows, since_text, undo_text}; `can_undo` per item; batch `undo` {tracks, label, cant} |
| T:`batchEnd`/`endRows`/`endNote`/`canTryAgain`/`endWords`/`progressRows`/`runLabel`, SA/SB batch panels | a running and ended batch's words, Resume vs Try again | batch result `headline`, `notes[]`, `next` |
| T:`checkTracks`/`batchRowName`/`batchRowSub`/`batchListTitle`, `headerSub`, `segOptions`/`FILTER_LABEL`/`FILTER_DOT`/`FILTER_ORDER`, `itemKey`, `rowOff`/`rowWaits`/`rowDim`/`rowBadge`, `compareLines`/`filePlace`/`linkService`, `qobuzText`/`freeHint`/`filedAs` | to-do row names and sub-lines, page sub-line, chip labels/order/tone, item ids, dimming and badges, the same-song comparison, Qobuz and free-download lines, the bought file's name | to-do payload fields `name`, `sub`, `chips[]` {group, label, n, tone}, `id`, `dim`/`dim_why`, `badge`, `pair.lines[]`, `qobuz_text`, `free_text`, `bought_name` (with the real extension, T §0.6) |
| T `Page.svelte:headResume`/`groupAction`, `Details` | "Upgrade all · n" vs "Resume · k left" | `groups[].head_action` |
| T `WrongSongDialog` `blocked`, `candidates.ts:lengthTone`/`matchTone`/`previewOffer`/`canUse` | candidate tones (UI thresholds ignore the engine's `length_ok`/`matches`) and offers | candidate `tone_length`, `tone_match`, `can_preview`, `can_use` from the engine |
| T `hub.ts:writeBlockedReason`/`networkReadsAllowed`, U9, SB `WriteButton`, `AccountPanel` blocked | why buttons are off | `status.blocked` {writes, network_reads} with words |
| U2, U3, U6, U7, U8, U10, U16-search-excluded, SB `KindStrip`, `RunPanel`, `PlanRows`, `PlanFolds`, `WhyMark`, `NextDot`, `WaitingAnswersNote`, `DayBar`/`dayBarModel` | plan kinds and counts per collection, presets, the next-sync set, today/later/days, per-account use, minutes left (two rules today), the start note, why tags, day-bar labels | `sync plan` fields `kinds[]`, `presets[]`, `next_sync[]`, `day_bar`, `accounts[]`, `minutes`, `start_note`, rows' `why`/`why_text` |
| U1 | the scope switches | settings (§9.2) and `sync scope` |
| U12, SB `SyncCard`, `StepBar`, `SyncPart`/`activity.ts`, `RunList`, `results.ts` | the live run state, from line, length check line, step list, pause text, foot activity line, result chips and badges | the job registry's reduced state (`job show`), events carry `text`; result `badge`. The window's TS reducer may stay for motion only; a test feeds recorded event logs to both and compares the facts |
| U13 | weak = cutoff ≤ 17 kHz (third copy) | `views.quality_class` only |
| U14, U15, U20, SB `EndScreen`/`endModel`, `UpToDatePanel`, `RunRow`, `RunsPage` | "what a run did" (two definitions of "added"), titles, notes, Auto-upgrade split, run status, totals | one `report.outcome(run)` used by `run show`, `run list`, Dashboard, end screen |
| U17, U18, U19, SB `SummaryStrip`/`summaryStripModel`, `QualityBar` words | next-sync panel state, limit gate, needs-you rows, strip words | `status` fields; `summary.words` |
| U21, U22, U23, U24, SB `UsageChart`, `RiskScale` | limit suggestion, warning rows and order, zone/level of a limit or a day, bounds and extra options | `limits show` fields `suggestion`, `signals_by_kind[]`, `zone` per day and draft, `bounds`, `extra_options` |
| U25, U26, SB `AddRow`/`addRowModel` | playlist edits, folder-name rules, "already listed" (a copy of `sources.recognise`) | `playlists_file.apply(lines, op)` + `validate`; `preview_playlist_change(lines, op)` returns the new lines |
| U28, SB `PlaylistLine`/`changeModel.infoLine/setupLine` | overlap cards, folder deltas, row lines | `playlist list` / preview fields with words |
| U29, U30, U31, SB `AccountPanel`/`accountModel`, `SourceLadder`/`ladderModel`, `RowPanel`, `YouTubeMusicPanel` | Settings row lines and attention, account phase and the browser offered first, Spotify state, tools card, Liked music panel, the ladder (re-derives `download_accounts`) | `login list` (states, `state_text`, `ladder`), `login find` `offer`, `setup status` rows, `tools status` |
| U32, SB `Step*`, `StepFooter` | setup's six steps (the engine counts five) and why Continue is off | `setup status` `steps[]` {id, done, reachable, why_not} |
| U36, SB `MusicMissing`, `StepMusic` | when to confirm a music folder, the gate | `setup music --dry-run` `needs_yes`; `where.music.state` |

**Stays in the window (view only):** L D2 (the saved sort; the default is the engine's), D3, D4 (holding the acted-on
row; its data part moved above), D16, D18 (columns), D27, D28 and U37 (when the window rescans; commands have
`library scan` and `as_of`), D35, D37 and U38 (refresh wiring), U4 (carrying ticks), U5 (sending the ticked keys),
U11, U16 (plan search: `sync plan --search` reuses the engine's fold), U35 (the "99+" cap), T:`keepSelection` and the
other selection/hold/deep-link helpers, T `flows` `adopt`, the panel phases, `FILTER_MAX` (five before "More"), SA
players (`ComparePlayer`, `MiniPlayer`, `NowPlayingRow`, `PlayButton`, `FilePlay`), `ListRow`, `ShareStrip`,
`ShareBar` geometry, `qualityBarModel` percentages (the words move), `Spinner`, `ErrorBoundary`, `NotFound`,
`LinkGuide` (static words move to the catalogue).

**Deleted:** `PageStub.svelte`, `SectionLabel.svelte`, `TrackRow.svelte` and its gallery entry (no page uses them).

---

## 10. Person-only steps, the sandbox, the app binary

### 10.1 Steps only a person can do

A step is a person's when it needs eyes, ears, hands on another app, a browser login, or the person's decision. The
engine names each one; a command never pretends to do it.

| `id` | When | What the answer says (`say`) | `then` |
|---|---|---|---|
| `step:quit_rekordbox` | a write needs rekordbox closed (`needs_person`, exit 4) | "Quit rekordbox, then tell me to carry on." | the same command, or `batch resume aiff:<n>` |
| `step:open_rekordbox` | live tests only | "Open rekordbox." | the next read |
| `step:reload_tag`, `step:analyse_again`, `step:auto_relocate`, `step:relocate_new`, `step:rebuild_usb` | after a replace, Same track, Convert (in `check.steps` and the result's `person_steps`) | the window's numbered words with the track names | `check done <tracks>` once the person did them |
| `step:listen` | an upgrade marked different or unsure; a fake verdict the user doubts | "Listen to both: <now path> and <new path>." | `upgrade apply …` or `upgrade discard …` |
| `step:sign_in` | `login sign-in`, `login_expired` | "Sign in to <service> in <browser>; the window that just opened. I'll notice it." | `job wait <job>` |
| `step:keychain` | first cookie read of a Chromium browser | "macOS will ask about “Chrome Safe Storage”. Click Always Allow." | `job wait` |
| `step:full_disk_access` | Safari cookies unreadable | "Turn on Discjockey in System Settings › Privacy & Security › Full Disk Access." | `login find <service>` |
| `step:spotify_app`, `step:qobuz_password` | setup | the window's numbered setup words | `login spotify --client-id …`, `login qobuz …` |
| `step:install_tools` | a program missing | "Paste `brew install ffmpeg` into the Terminal." (an agent may run it if the user agrees) | `tools status` |
| `step:connect_drive` | files or the music folder on a drive that isn't connected | "Connect the drive <name>." | the same command |
| `step:reopen_window` | music folder or tools changed while the window is open | "Quit Discjockey and open it again." | — |
| `step:delete_superseded` | the user wants space back | "Discjockey never deletes music. You can delete these files in the Finder." + the list | — |
| `step:decide` | a choice that is the user's (which file of a duplicate stays, Same vs New track when not recommended, a risky limit) | the options with their outcomes | the command for each option |

In JSON each step is `{"id", "say", "then"}`; in text mode they are printed as "Your turn:" lines. The agent guide's
rule: tell the user `say` word for word, wait for their answer, then run `then`.

### 10.2 The app binary is the command

Covered in §2.1: no argument opens the window, any argument is a command, `where` prints the path, `app
install-command` makes a short name. The self-test (`--self-test`) gains one CLI round trip (`help --json` and
`where --json` in a scratch support folder) so a built app proves its command works.

### 10.3 The sandbox: rehearsing without touching the real library or rekordbox

| Command | Does |
|---|---|
| `sandbox create <dir> [--from empty\|real] [--rekordbox none\|copy\|<fixture dir>] [--no-audio]` | makes `<dir>/music`, `<dir>/support`, `<dir>/rekordbox` and a marker `.discjockey-sandbox`. `--from real` clones the music folder (incl. `.discjockey/`) with APFS clones (`clonefile`, no extra space, instant); watched folders on the same volume are cloned too and their paths rewritten in the sandbox's `library.db`, others become `folder_missing`. Without a clone-capable volume it refuses unless `--no-audio` (copies `.discjockey/` and `playlists.txt` only; audio steps meet `file_missing`). `settings.json` is copied **without logins**; no login file is copied. `--rekordbox copy` clones rekordbox's library folder (rekordbox must be closed while copying) |
| `--sandbox <dir>` or `DISCJOCKEY_SANDBOX=<dir>` on any command | runs it against the sandbox (sets the three folders); every envelope says `sandbox`; text mode prints "Sandbox: <dir>" on stderr first |
| `sandbox info <dir>` | what it was made from, size, when |
| `sandbox remove <dir> --yes` | deletes a folder only if it holds the marker and is neither the real music folder, a watched folder, nor inside one |

Guarantees, pinned by tests:
- **No write escapes.** In a sandbox, the lowest write layer (`library.run_op`, `move_files`, `move_path`,
  `rekordbox.write.open_write`, the tools updater, settings and config writes) refuses any target outside the sandbox
  root (`refused`, `reason: "outside_sandbox"`). A test runs every write command of the catalogue in a sandbox with a
  real-looking library next to it and checks no byte outside the sandbox changed.
- **Qobuz protection holds trivially:** a sandbox has no Qobuz login, so nothing downloads from Qobuz; anonymous
  reads and free streams work and are paced as usual.
- `DISCJOCKEY_REQUIRE_SANDBOX=1` makes every command but `help` refuse (`sandbox_required`) unless a sandbox is set:
  for developer agents working on the code (CLAUDE.md tells them to export it).
- `DISCJOCKEY_SUPPORT` / `DISCJOCKEY_REKORDBOX` stay as the plumbing the sandbox and the tests use; the docs point
  agents to `--sandbox`.

---

## 11. What the app is for: goals and the questions an agent gets (H4)

From README "Why Discjockey" and "How it works": the user collects music in streaming playlists and plays sets from
files; Discjockey makes the library follow the playlists, gets the best version (Qobuz AIFF first, then the ladder),
checks every file's real quality, names and files it, keeps going weekly, never deletes, and keeps rekordbox's cues
when a file is replaced.

| Goal | Questions a user asks an agent | Commands that answer or do it |
|---|---|---|
| A library that follows the playlists | "Is everything from my playlists downloaded?" "Sync my new tracks." "Only sync Hard_Bounce today." | `status`; `library list --in playlist:X` (`songs`, `wait`); `sync read`, `sync plan`, `sync run --plan P [--in playlist:X] --detach`, `job wait` |
| The best version | "Why didn't X download?" "Why is X only 130 kbps?" | `track show X`: `why[]` (engine-composed reasons in order: playlist switched off / scope off / never-download / not found last time + `next_try_text` / Qobuz paused or used up / waiting for the limit / rejected sources / last run's result for it with its note) + `next` (e.g. `version search X`); `login list` (the ladder sentence) |
| Real quality | "Is my library lossless?" "Which files are fake?" "Is this upgrade real?" | `status` (lossless share); `todo list --group fake,weak`; `upgrade list`, `track show X` (`upgrade` block: alignment, both cutoffs, ways), `track spectrum X --which current\|upgrade --png …`, then `step:listen` |
| rekordbox keeps working | "Does rekordbox match my files?" "What do I still have to do in rekordbox?" | `rekordbox match`; `check list` (steps per track); `rekordbox status` |
| Ready for a gig | "Is my library ready for Saturday's gig?" | `status --ready`: open rekordbox checks (USB stick stale), CDJ problems (`todo` group cdj), rekordbox tracks with missing or superseded files, playlist songs without a file, stopped batches, drives away, upgrades waiting; each with `next` |
| Upgrades | "Swap in all the better versions that keep my cues." | `upgrade apply --all --dry-run` → user → `upgrade apply --all --plan P --detach`; `check list` → person steps → `check done --all` |
| Files that play everywhere | "Make my Hard_Bounce folder AIFF." "Which files won't play on CDJs?" | `aiff convert --all --in playlist:Hard_Bounce --dry-run` / apply; `todo list --group cdj`, `aiff convert --all --todo cdj` |
| Own music | "Add my old crates." "What couldn't be read?" "Answer the same-song questions." | `folder check/add`, `import status`, `folder list` (unreadable); `question list`, `duplicate list`, `question answer`, `duplicate keep` |
| Order | "Tidy my folders." "Rename the playlist and move its folder." | `tidy run --dry-run` / `--plan`; `playlist rename X Y --files move --dry-run` |
| Time | "What changed since yesterday?" "What's waiting and why?" "When does Qobuz look again?" | `history --since yesterday`; `sync plan` (`next_sync`, `why`), `todo list`, `job list`; `track show X` `next_qobuz_check`; `status` `next_checks` |
| History and recovery | "What did the last sync do?" "Undo yesterday's work." "Something broke." | `run show last`; `history --since yesterday` → `batch undo … --dry-run` → `--yes`; `doctor`, `job show <job> --log`, `rekordbox backups`, `rekordbox restore` |
| Limits and account risk | "Can I download more today?" "Is my account at risk?" | `limits show qobuz` (signals, zone, `suggestion`), `limits set qobuz 60 --extra-today 10 --dry-run` |
| Health | "Is everything set up?" | `setup status`, `doctor`, `tools status`, `login list` |

The model of the app's concepts an agent needs is part of the agent guide (§14.2) and `help concepts`.

---

## 12. Today's conventions: keep, change or drop (H5)

| Today | Verdict | Reason |
|---|---|---|
| `{"ok", "kind", "reason", "message"}` JSON | **change** → envelope `{v, command, outcome, reason, message, data, next, person_steps, recovered, job, as_of, sandbox}` | one shape for every command; `ok: true` with exit 1 for skips confused success and failure |
| `ok` field | **drop** | the exit code and `outcome` say it; two truths disagreed |
| `kind` vocabularies (batch: refused/failed/busy/rekordbox_open/stopped; sync: setup kinds; bridge: 20) | **change** → one `outcome` set + `reason` keys; the bridge keeps `kind` for the window and adds `outcome` | one map in the engine (§4.3) |
| exit codes 0–5, sync 130, settings 0–3, rekordbox 0–2 | **change** → 0–8 for all (§4.3) | usage error and "no music folder" both 2; Ctrl-C 5 vs 130; "partial" hidden in 1 |
| `reason` keys of `eligible.REASONS` | **keep** | precise and already shared with the window |
| `--json` per sub-command, position-sensitive | **change** → global, anywhere | `--json upgrade list` silently printed text |
| usage error as argparse text on stderr | **change** → `bad_args` envelope with `--json` | an agent parses one thing |
| progress lines on stderr | **keep**, plus `--jsonl` and `job follow` | text for people, events for agents |
| `--dry-run` with `default=SUPPRESS`, missing on undo/discard/checked | **change** → on every file/rekordbox/plan write, a plain flag, never writes | the hub's previews exist for those (undo preview, removal preview) |
| dry run that takes the lock / writes facts / writes `--extra` | **drop** | a dry run must be safe to run any time |
| `--yes` only on the sync and restore | **change** → exactly where the window confirms (§7.2) | same confirmations as the window |
| the sync's "Proceed? [y/N]" | **drop** | a command never prompts; Start isn't confirmed in the window either |
| interactive `setup`, `upgrades` | **drop** → `setup status`, `login …`, `upgrade …` | prompts can't be driven by an agent; the window is the guided form for a person |
| `update` | **change** → `tools update` (+ `tools rollback`, `--json`, no music folder, no library lock) | it only touches the support folder |
| `hub` | **change** → `app open` | noun grammar |
| bare `discjockey [--yes] [--dry-run] [--limit] [--extra] [--verbose]` sync | **change** → `sync run [selection] [--plan] [--limit] [--auto-upgrade-only]`, `sync read`, `sync plan`; `--extra` → `limits set --extra-today` | selection, plan binding, runs from the app binary |
| `--limit N` | **keep** on `sync run` | the "how many" chip in words |
| `CLI_COMMANDS` routing in `app_main` | **drop** | any argument is a command (§2.1) |
| song keys as ids | **keep**; paths accepted too | stable, already everywhere |
| `track` (console JSON) vs `track_id` (bridge) | **change** → `track_id` everywhere | one payload |
| bare integer batch ids in two tables | **change** → `aiff:<n>`, `moves:<n>` in one `batch` noun | the same number meant two batches |
| `--batch ID` flag vs positional `<id>` | **change** → positional typed ids | one style |
| `--way same-track\|new-track` vs bridge `swap\|add_new` | **keep** the CLI words; **change** the bridge enum to `same_track\|new_track` | the window's words win |
| `--all lossless\|cdj` vs `--all` flag | **change** → `--all` + `--in` / `--todo` (§7.3) | one selection grammar |
| `--in playlist:<name>\|folder:<path>\|unlisted` | **keep** the form, widen it to every listing; playlist named by its folder | readable and typed |
| `upgrade undo` (also undoes conversions) | **change** → `track undo` | it undoes any file step |
| `rekordbox checked` | **change** → `check done` | checks are a To-do group of their own |
| `rekordbox status`, `preview`, `backups`, `restore` | **keep** (status gains nothing, preview gains entry columns) | already the reference read commands |
| `upgrade list`, `batch list/show/resume/undo` | **keep** names; outputs move to the shared payloads | |
| `settings auto-upgrade [on\|off]` | **change** → `settings show`, `settings set auto-upgrade on\|off`; reads need no music folder | one group for all switches |
| batch scope `console` | **drop** → `via` + the real scope | the window's Resume never showed terminal batches |
| `recovered` key (absent when none) | **keep**, always present (`[]`) | an agent shouldn't test for a missing key |
| `DISCJOCKEY_SUPPORT`, `DISCJOCKEY_REKORDBOX` | **keep** as plumbing; agents use `--sandbox` | tests and the sandbox need them; two variables are easy to forget one of |
| Ctrl-C once/twice | **keep** semantics; forwarded to the worker; `job stop [--now]` from anywhere | |
| lock refusal at once (exit 3), no wait | **change** → `--wait-busy <s>` | the window's own scans would make agents fail at random |
| `batch list` newest 20 only | **change** → `--limit`, `--since`, `total` | |
| the cli.py/convert_cmd claim "keys as the library's JSON prints them" | **change** → true (`library list`, `track find`) | |
| CONTRIBUTING's hand-written command shapes | **drop** → generated reference + AGENTS.md (§14) | they drift |

---

## 13. Completeness tests (keeping it complete forever)

| Test | Fails when |
|---|---|
| T1 catalogue ↔ bridge | a `@bridge` method of `HubApi` is missing from `surface/catalog.py`, or an entry names no method; a `WINDOW_ONLY` reason is outside `{native_dialog, closes_window}` |
| T2 catalogue ↔ parser | an entry's command path doesn't parse, or a parser command has no entry (except the §5.3 list, which is its own table in the catalogue) |
| T3 adapters compute nothing | a `HubApi` read method does more than call its `surface` twin and the declared path→URL transform (AST check); a CLI handler builds data instead of passing the surface's payload |
| T4 screen states ↔ commands | a `shots.json` entry has neither `reads` nor a `view` reason; for every scenario library, a declared read's bridge payload ≠ its command's `--json` `data` (after the transform) |
| T5 words | the `words` rule finds a literal (ratchet may only shrink, then none); `words.json` is stale against `words.py`; two catalogue keys hold the same sentence |
| T6 schemas | a command's real output doesn't validate against its schema; `types.ts` is stale against `shapes.py` |
| T7 text shows everything | a field marked `shown` in a schema is absent from the text rendering of a sample payload |
| T8 outcomes | a command exits with a code not matching its `outcome`; a `ProblemKind` has no row in the outcome map; `--json` prints anything but one object (also for usage errors and crashes) |
| T9 safety | a dry run writes a byte (run every command's `--dry-run` on a fixture library, compare all files and `library.db`); a `needs_yes` command acts without `--yes`; a sandbox write escapes |
| T10 jobs | a stop file stops a window job and a terminal job between items; a killed client leaves the job running; `lost` is reported for a dead worker |
| T11 docs | `docs/agent-commands.md` differs from `discjockey help --markdown`; a catalogue entry has no example in it |
| T12 app binary | a built app with any argument but `-psn_…` doesn't reach the CLI (self-test round trip) |

The CLAUDE.md "Agent-ready" rule is rewritten to point at T1–T11: a new bridge method, payload field, word or screen
state can't land without its command, schema, text rendering and docs, because the tests fail.

---

## 14. Agent docs

### 14.1 Where they live and how they stay true

| Doc | Audience | Source |
|---|---|---|
| `AGENTS.md` (repo root; bundled into the app; printed by `help agents`) | any agent pointed at Discjockey | hand-written guide (§14.2), short; links the reference |
| `docs/agent-commands.md` | agents and maintainers | **generated** from the catalogue and schemas (`discjockey help --markdown`); every command with its flags, outcome reasons, data shape and one example; T11 keeps it equal |
| `help <cmd> [--json]`, `help concepts`, `help glossary` | an agent with only the app | the same catalogue and word catalogue |
| README "Let an AI agent run Discjockey" | the user | what to tell their agent ("run `/Applications/Discjockey.app/Contents/MacOS/Discjockey help agents`"), what it may do alone and what it will ask |
| CONTRIBUTING "Commands for scripts and agents" | developers | replaced by a pointer to the two docs above plus the sandbox rule for developer agents |

### 14.2 What the agent guide says (outline)

1. What Discjockey is (two paragraphs from the README).
2. Concepts: song (`track_id`) and file; playlist, folder, collection; quality verdicts (lossless, good lossy, weak,
   fake, missing) and the cutoff; the download ladder; the sync (read → plan → run) and the weekly checks; Upgrade
   ready, Same track vs New track; Convert and clean name; AIFF batches and move batches; rekordbox checks;
   `Superseded/`; To-do groups; watched folders, the import, own songs (`local:`), questions and duplicates; the lock,
   jobs; limits and account risk.
3. Safety rules (CLAUDE.md invariants as rules for the agent): never delete a music file (the app can't; don't do it
   by hand either); moves only in batches — every batch you start counts as the user's; run `--dry-run` first and show
   the user before any write that moves, converts, discards, undoes or touches rekordbox; Qobuz protection can't be
   switched off — never try to work around a limit or a pause; never touch rekordbox's library yourself; rehearse in a
   sandbox when unsure; never pass a password on the command line.
4. The workflow: `where` → `status` → read → dry run → ask → apply with `--plan` and `--detach`/`--wait` → `job wait`
   → tell the user every `person_steps` entry word for word → follow `next`.
5. Ids, selection, outcomes and exit codes (the tables of §3, §4.3, §7.3).
6. The questions of §11 with their commands.

---

## 15. The issue 33 live tests (todo audit J11) with the new commands

Every step marked **P** needs the user; everything else the agent runs. "Real" = against the user's library and
rekordbox with their go; the stage plans' rehearsal parts can run in `--sandbox` with `--rekordbox copy`.

**Stage A**

| Step | Who | Command |
|---|---|---|
| 1a rekordbox ready, the right library, closed | agent | `rekordbox status` |
| 1b open rekordbox | **P** | `step:open_rekordbox` |
| 1c "rekordbox is open" | agent | `rekordbox status` (`running: true`) |
| 2 offsets of an MP3, a 48 kHz M4A, an AIFF | agent | `rekordbox preview --path <file> --json` (`timing.offset_samples`, `entries[].offset_ms`) |
| 3a make a test track | agent | `scripts/make_upgrade_test.py --keep-lossy m4a` |
| 3b import, analyse, 3 hot cues, quit rekordbox | **P** | — |
| 3c Discjockey knows the file | agent | `folder add <scratch folder> --wait 600` |
| 3d New track | agent | `upgrade list`; `upgrade apply <track> --way new-track --dry-run`; apply `--plan P` |
| 3e Relocate the old track to the new `.aiff` | **P** | the answer's `person_steps` (`step:relocate_new` with the path) |
| 3f cues on the same beats, no click | **P** (looks, listens) | agent afterwards: `rekordbox preview --path <new>` |
| 3g remove the test files | agent | `folder remove <scratch> --yes`, then deletes the script's own files |

**Stage B**

| Step | Who | Command |
|---|---|---|
| 0a File › Library › Backup; a spare USB stick | **P** | — |
| 0b copy rekordbox's folder aside; four click tracks with parked upgrades; scratch folder | agent | file copy; script; `folder add <scratch> --wait 600` |
| 1 import, analyse, cues, playlists, edit a title, export to the stick, quit | **P** | — |
| 2a Upgrade all | agent | `upgrade apply --all --dry-run` → `--plan P --detach`; `job follow <job>` |
| 2b Stop midway | agent | `job stop <job>` → the job ends `stopped` (exit 5), `next: batch resume aiff:<n>` |
| 2c Resume | agent | `batch resume aiff:<n> --wait 600` |
| 3 AIFF/44.1/16, plays, cues and grid, names, sorting, history, playlists | **P** looks; agent reads | `batch show aiff:<n>` (paths, `rekordbox.entries/kept`), `rekordbox preview --path <new>` |
| 4–6 reopen, seek, re-analyse; Reload Tag; USB stick | **P** | `check list` gives the steps to read out |
| 7a rekordbox open, Undo all says quit | **P** opens; agent | `batch undo aiff:<n> --yes` → `needs_person` (exit 4), `step:quit_rekordbox`, nothing undone |
| 7b quit, undo again; old files with cues | **P** quits and looks; agent | `batch undo aiff:<n> --yes` |
| 8 relocate tries by hand | **P** | — |
| 9a leave rekordbox closed a minute | **P** | — |
| 9b master.db untouched meanwhile, `contentFile` accepted | agent; **P** for the prompt | `rekordbox status` (modified time), `rekordbox preview --path <new>` (`content_file`, `folder_path`, `updated_at`) |

**Stage C**

| Step | Who | Command |
|---|---|---|
| 0 click tracks with same-edit upgrades; rekordbox backup | agent / **P** | script, `folder add`; backup **P** |
| 1a rekordbox open; the Sync page's before-start line | **P** opens; agent | `sync plan` (`start_note`, `auto_upgrade`) |
| 1b sync: "… wait for rekordbox to be closed" | agent | `sync run --auto-upgrade-only --wait 600` (no downloads needed) → `auto_upgrade.waiting`, rows `rekordbox_open` |
| 1c To-do marks them; nothing changed | agent; **P** may look | `todo list --group upgrade_ready` (`sub`: "Waits for rekordbox to be closed") |
| 2a quit rekordbox | **P** | — |
| 2b sync again: upgraded, end screen lists | agent | `sync run --auto-upgrade-only --wait 600`; `run show last` |
| 2c AIFF with cues in rekordbox | **P** | agent: `rekordbox preview --path <new>` |
| 2d "Undo all from this sync" offered | agent | `check list` (batch `undo.label`) |
| 3 undo; back with cues | agent; **P** looks | `batch undo aiff:<n> --yes` |
| 4a switch off | agent | `settings set auto-upgrade off` |
| 4b nothing moves | agent | `sync run --auto-upgrade-only` → `auto_upgrade: null`; `upgrade list` still lists them |

**Stage D**

| Step | Who | Command |
|---|---|---|
| 0 backup; five click tracks analysed with cues in a playlist; rekordbox closed | **P** (+ agent script) | — |
| 1a the plan for the folder | agent | `aiff convert --all --in folder:<path> --dry-run` |
| 1b run it | agent | `aiff convert --all --in folder:<path> --plan P --wait 600` |
| 1c AIFF/44.1/16, cues, grid, playlist | **P** | agent: `rekordbox preview --path <new>` |
| 2a the AAC listed with its words | agent | `todo list --group cdj` / `aiff convert --all --todo cdj --dry-run` |
| 2b Convert all; plays with cues | agent; **P** plays | `aiff convert --all --todo cdj --plan P` |
| 3 the MP3 by hand | agent; **P** looks | `aiff convert <track> --dry-run`, apply |
| 4 Undo all on each check card | agent; **P** looks | `batch undo aiff:<n> --yes`, `track undo <track> --yes` |
| 5a open rekordbox | **P** | — |
| 5b Convert one file: "Quit rekordbox", nothing changed | agent | `aiff convert <track>` → `needs_person` (exit 4), the batch of one closed, no resume |
| 6 export to a stick, play on a CDJ | **P** | — |

---

## 16. Risks and how the build plan must split

| Risk | Why it is risky | What the plan must do |
|---|---|---|
| Extracting `surface/` out of `api.py` (~150 KB) | every window read and write moves; a slip changes what the window shows | move method groups one by one behind the unchanged bridge; T3 and the existing bridge tests green after each group; no behaviour change in the extraction groups |
| The words into the engine | hundreds of strings across ~60 UI files, rendered by Svelte; easy to change a word by accident | per page, Sonnet mechanical with the ratchet; screenshots compared to `main` per page (words must be identical unless a duplicate is merged); UI build/shots split from model work |
| Job registry and worker processes | concurrency, crash recovery, the window's in-process jobs writing the same files, stop files in hot loops | one Opus group owns `surface/jobs.py` + `CancelToken` change + window wiring; T10 before any write command uses it |
| Persisted plan (`plan.json`) and sync scope in settings | changes how the Sync page and the run choose actions (`select_actions`) | its own group with the sync's tests; the window's Sync page switched over in a UI group after it |
| Contract changes (`track_id`, mode enum, `add_bought_file(path)`, `keep_file`, `stop(job_id)`, listing selections, `expect`) | `types.ts`, `contract.ts`, the fake backend and `hub-bridge-contract.md` must move together | one contract group per change set, generated `types.ts` first |
| Sandbox escape guard | must sit in the lowest write layer or it is decoration | build it with T9 before `sandbox create`; review by Opus |
| App routing | a mistake opens the window for every command or a command for every Finder open | small group with the self-test round trip |
| New outcome scheme across today's commands | every existing command test changes | first group (framework) migrates today's commands; nothing else lands before it |

Suggested order of groups (the planner sizes them; one deliverable each, < 150k tokens):
1. CLI framework: grammar, global flags, envelope, outcomes and exit codes, ids, `help`/`where`, catalogue skeleton, app routing; today's commands migrated (Sonnet).
2. `surface` extraction, reads, by area (library/track/todo; sync/runs/status; playlists/limits/logins/setup/tools; rekordbox), each with its read commands, schemas and T1–T4/T6 parity (Sonnet ×4).
3. Jobs registry, worker, `job …`, stop files, window integration (Opus).
4. Persisted state: plan, scope, import state, questions, `rev`, drop path, `keep_file`, `select`/`media_url`/`setup_check_account` removal (Opus plan, Sonnet build; contract group).
5. Write commands by area, each with dry runs, `--plan`, `--yes`, selection (Sonnet ×4: sync+playlists; folders+import+tidy+batches; upgrades+aiff+checks+versions; logins+settings+limits+tools).
6. Decisions into the engine (§9.3 rows), window switched to the fields, no visible change (Sonnet model groups + Opus UI wiring).
7. Words catalogue, export, rule checker, ratchet emptied page by page (Sonnet per page, Opus final).
8. Pictures (spectrum text/PNG), `status --ready`, `doctor`, `history`, `rekordbox match`, `library superseded` (Sonnet).
9. Sandbox + T9 (Opus).
10. Docs (AGENTS.md, generated reference, README, CONTRIBUTING, CLAUDE.md rule), T11 (Sonnet), then an Opus whole-design review.
11. The A–D live tests of §15 with the user.

---

## 17. MCP: later, not now

**Decision: no MCP server in issue 39.** The agents the user names (Claude Code, Codex) have a shell; the CLI with
`--json`, `help --json` and jobs gives them everything an MCP server would, and long runs are solved by jobs either
way (an MCP tool call times out just like a shell call). An MCP server now would be a second surface to keep complete.
Because every command comes from `surface/catalog.py` with a JSON Schema per payload and per argument set, an MCP
server later is a thin generated adapter (one tool per catalogue entry, `needs_yes` as a required boolean, jobs as
`job_wait` polling). Build it when a user wants an agent without a shell (Claude Desktop); note it in `docs/issues.md`
then.
