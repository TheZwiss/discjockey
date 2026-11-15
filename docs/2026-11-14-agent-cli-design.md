# Discjockey's command line for agents and people (issue 39, design)

Status: design, 2026-11-14; revised 2026-11-15 after the adversarial and coverage reviews (step 4a: §6, §7.1, §7.5,
§8, §9.2, §10.3, §13, §15 and §16 redesigned; the "Fix status" table at the end of
`docs/2026-11-14-agent-cli-design-review.md` says which findings are done and which a later fix round applies).
Input: the six audit files `docs/2026-11-14-cli-audit-{library,todo,app,supplement-a,supplement-b,supplement-c}.md` (cited as **L**, **T**, **A**, **SA**, **SB**, **SC** with their row ids, e.g. L D15,
T §5.4), today's commands (`CONTRIBUTING.md` › "Commands for scripts and agents"), `docs/issues.md` › 39, `CLAUDE.md`
› "Agent-ready". A later Opus agent turns this into a build plan for Sonnet groups; this file fixes the decisions,
the interfaces and the behaviours tests pin, not the code.

---

## 1. What this design must achieve

### 1.1 The user's hard rules, as this design states them

| # | Rule | How this design meets it (section) |
|---|---|---|
| H1 | **Everything the window shows, and more.** Every text, number, sentence, badge, colour or dimming that means something, tooltip, count, ordering, and the data behind every picture is reachable by a command; where the window leaves things out, the command gives them anyway. Nothing is reachable only in the window. Guaranteed by construction. | The command line runs on the **same object the window talks to**: a headless `HubApi` (§8.1), so a command's payload *is* the bridge's payload. Every word that carries data or depends on data comes from the engine; the window's fixed words are extracted from its source at build time into a catalogue the CLI prints (§8.2). The CLI prints the payload whole; text mode renders it from one schema (§4). Checks that fail when the window computes, words, colours, orders or offers anything the payloads lack (§8.3, §13). |
| H2 | **For people too.** Readable text by default with the same facts; a machine shape for agents; pictures as data plus a way to see them. | Text is the default; `--json` prints the versioned envelope (§4). Pictures: `--json` gives the numbers; `--png <file>` writes the picture a person or a vision agent opens; text mode prints the verdict line and a small text sketch (§4.5). |
| H3 | **Everything the user can do in the window, an agent can do**, under the same invariants. An agent's command counts as the user starting it. | The full catalogue maps every bridge method to a command or to "window only" with a view-state reason (§5). Writes keep the lock, Qobuz protection, never-delete, batches the user started, and a dry run where the hub has one (§7). |
| H4 | **Coverage from what the app is FOR.** | §11 lists the user's goals and questions and the commands that answer each. |
| H5 | **Today's commands are evidence, not a template.** Nothing is kept for compatibility. | §12: every convention judged keep / change / drop with its reason. |

### 1.2 Principles (how the decisions below were made)

1. **One engine answer, two renderers.** A fact the window shows comes from the engine (`HubApi` and the pure
   `views.py`); Svelte and the console both render it. When the window decides something itself today (≈115 audit
   rows), the decision moves into the engine (§9). The window keeps only how things are laid out, what the person is
   looking at (pure view state) and its fixed words, which the CLI gets from the build's word catalogue (§8.3).
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
| 3 | `discjockey where --json` | `music` (path, state `ok`/`missing`/`not_chosen`), `support`, `rekordbox` (library path or null), `command` (absolute path of this program), `version`, `sandbox` (null or its dir), `windows_open` (count of live windows on this music folder, from the window files of §6.4; never by probing the window's lock), `jobs_running` |
| 4 | `discjockey status --json` | The cross-screen overview (Dashboard + counts + running jobs + problems + what needs a person), §11 |
| 5 | `discjockey help --json` | The machine index: every command with its args, flags, whether it writes, its job kind, its outcome reasons, the name of its data schema; `help <cmd> --json` adds the schema (JSON Schema) |
| 6 | `discjockey help concepts` / `help glossary` | The model of the app (§14.2) and every badge, colour, tone and tooltip word with its meaning (the extracted word catalogue `words.json`, §8.3) |

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
| Job | `job:<8 hex>`, for window jobs too (a contract change: today the window's ids are integers) | that, or `current` (the one running write job on this music folder) | yes (registry, §6) |
| Duplicate group | `dup:<sorted file ids>` (`models.group_id`) | the same | changes when its files change, by design (asked again); a stale one is `refused`/`changed` with `next: duplicate list` |
| Same-song question | `same:<song key>~<own key>` | the same | yes while the question stands |
| rekordbox check | one per track: the `track_id` | `track_id`s, or `--batch aiff:<n>` | yes |
| Version candidate | `cand:<source>:<id>` | the same, valid while that track's last search is cached | until the next search |
| rekordbox backup | its `id` (today's) | the same | yes |
| Plan (any dry run) | `plan:<12 hex>` | the same | 24 h, kept in `<support>/plans/` (§7.1); older: `refused`, `plan_expired` |
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
 "message": null | "<words>",           the window's sentence for this outcome (from `words.py`, §8.3)
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
  from the typed shapes of `hub/shapes.py` (§8.2); `help <cmd> --json` prints it; a test pins that every command's real
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
| 8 | `running` | `--wait` (also on `job wait`) ran out; the job goes on: `job` holds its id | `still_running` |

- Every bridge `ProblemKind` (`types.ts:3`) maps to one row: `busy`, `console`, `sync_running` → `busy`;
  `not_set_up`, `no_library`, `setting_off`, `exists`, `changed`, `refused`, `protected` → `refused`;
  `login_expired`, `rekordbox_open` → `needs_person`; `offline`, `playlist_unreadable`, `config_invalid`,
  `qobuz_login_failed`, `login_failed`, `failed`, `crashed` → `failed`; `stopped` → `stopped`. The map lives in one
  table in the engine (`discjockey/hub/outcomes.py`) that the `bridge` decorator applies, so the CLI reads it off the
  same answer: the bridge keeps answering `{ok, kind, message}` to the window (CLAUDE.md invariant) and adds
  `outcome`, `reason`, `next`, `person_steps` and `data` beside them (additive; the engine's `OpProblem` carries
  them).
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
| `library` | the Library page's collections and table | `list`, `collections`, `scan`, `facts`, `favourites`, `superseded` |
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

Kinds: **R** read (no lock, never writes), **RJ** a read that can take minutes and runs as a read job (§6.1: no
lock, same `--wait` rules as a write), **J** write job (§6), **B** brief save (no library lock, answers at once),
**W** window only. Which locks each J takes is the catalogue's `locks` column (§6.1). "New args" names bridge
signature changes the design needs (contract changes, §16).

| Bridge method | Command | Kind | Notes |
|---|---|---|---|
| `library(view,key,query,filter,sort)` | `library list [--in C] [--search W] [--quality Q] [--sort S] [--limit N]` | R | rows incl. `also`, chips, summary, subtitle, songs, empty (six states, words), `as_of`; `file_state` incl. `file_missing` per row (§9 L-D, SC) |
| `track(id)` | `track show <track>` | R | the whole details payload + `decision`, `actions[]`, `why` (§11), `rev`; valid for a song still waiting (D21) |
| `todo(filter,show_hidden)` | `todo list [--group G…] [--hidden]` | R | all groups incl. checks, questions, duplicates, chips, `check_tracks`, `hidden_count`, `empty`, each item's `id`, `actions[]` |
| `sidebar()` | `library collections` | R | the collections list as the browser draws it (sections, order, counts, away marks), and the nav counts |
| `watched_folders()` | `folder list` | R | rows, unreadable files, `waiting`, import `state` (`stopped` now on disk, §9) |
| `removal_preview(id)` | `folder remove <folder> --dry-run` | R | |
| `check_import_folder(path)` | `folder check <path>` | R | |
| `aiff_plan(scope)` | `aiff convert … --dry-run`, `aiff rename … --dry-run` | RJ | the same `AiffPlan`; a dry run never writes: up to 50 files without facts are read in memory, more answer `refused`, `facts_missing`, `next: library facts` (§7.1) |
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
| `sync_preview()` | `sync plan [--search W]` | R | the plan derived from the stored read (§9.2), with scope, presets, next-sync set, estimate, folds; `plan_id` |
| `refresh(auto)` | `sync read` | J | reads playlists (network) without a lock, scans when the library lock is free, stores the read in library.db (§9.2) |
| `stop_refresh()` | `job stop <job>` | J-control | |
| `start_sync(selected)` | `sync run [selection] [--plan P] [--limit N] [--auto-upgrade-only] [--dry-run]` | J | §7.3; `--auto-upgrade-only` runs only the last phase without reading the playlists (T J11 C; its dry run gives the phase's before-start line); new arg `plan_id`: the window's Start binds to the plan it showed like `--plan` (§9.2) |
| `stop()` | `job stop <job\|current> [--now]` | J-control | reaches a window job too (stop file, §6.4); new arg `job_id` (a string) |
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
| `add_playlist(url)` | `playlist check <url>` | RJ (network) | the found card; `suggested_folder`; duplicates by `sources.recognise` |
| `preview_playlist_change(lines)` | `--dry-run` of every `playlist` write | R | new arg `op` (the engine applies the edit, §9 U25) |
| `save_playlists(lines,ver,files)` | `playlist add <url> [--folder F] [--at N]`, `remove`, `rename`, `move --to N`, `enable`, `disable`, `edit --file <playlists.txt>` | J | `--files move\|leave`, `--no-rename` answer the save question; `--if-version` |
| `set_read_liked_music(on)` | `settings set read-liked-music on\|off` | J | |
| `add_liked_music()` | `playlist add-liked` | J | |
| `tidy_up(moves)` | `tidy run [<file>… \| --all] [--with-yours] [--plan P]` | J | `--all` = the rows the engine ticks; `--with-yours` = "Put these in playlist order too" |
| `undo_moves(batch)` | `batch undo moves:<n> --yes` | J | |
| `downloads_view()` | `login list` | R | per source state, last check, ladder (rungs lit, sentence) (§9 SB ladder) |
| `find_logins(service)` | `login find <service>` | R | plus `offer`: the browser/profile the window would offer first |
| `setup_account(s,b,p)` | `login use <service> --browser B [--profile P]` | J | may raise a keychain prompt: `needs_person` step `step:keychain` |
| `account_sign_in(s,b,p)` | `login sign-in <service> [--browser B] [--profile P]` | J (person) | opens the browser, waits ≤ 10 min for the person; `step:sign_in` shows as live `person_steps` while it waits (§6.5) |
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
| `search_candidates(id)` | `version search <track>` | RJ (network) | refused `busy`/`sync_running` while a sync of any process runs (the registry, §6); Qobuz searches go through the shared pacer and skip a paused Qobuz (§7.5) |
| `preview(id,cand)` | `version preview <track> <cand:…>` | RJ (network) | writes the 20-s clip to the cache, prints its `path` |
| `use_candidate(id,cand)` | `version use <track> <cand:…>` | J | the daily limit, the shared pacing and the shared failure streak of §7.5, for the window and every command alike |
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
| `library facts [--dry-run]` | a write job (library lock) that reads and stores missing file facts (today's `importer.fill_facts`), so dry runs stay read-only and fast (§7.1) |
| `job …`, `sandbox …`, `app install-command` | §6, §10.3, §2.1 |

`rekordbox preview` gains `folder_path`, `content_file` and `updated_at` per entry (T J11 B 9b: no command showed
them).

---

## 6. Long runs, jobs and the open window

Redesigned after the review (R4–R7, R17–R19, R21, R22, R27). One registry per support folder holds every long piece
of work from any process; a job is alive while its process holds a lock, never judged by its pid; each job kind
declares the locks it takes.

### 6.1 Job kinds and the locks they take

| Kind (catalogue) | Library lock (`<music>/.discjockey/.lock`) | Support lock (`<support>/.support.lock`, new) | `rekordbox.lock` | Commands |
|---|---|---|---|---|
| **write job** (J) | the whole job; held → `busy`, or retried under `--wait-busy` | only around a settings, config or login save inside it | exclusive, as today, only inside a rekordbox session (AIFF batch, undo, restore) | `sync run`, `upgrade …`, `aiff …`, `track hide/undo`, `tidy run`, `folder add/remove`, `import run`, `duplicate keep`, `question answer`, `version use/reject/add-file`, `check done`, `batch resume/undo`, `library scan`, `library facts`, `sync never/again`, `playlist` writes |
| **playlist read** | only for its scan, and only when free (today's `scan_lock`); otherwise it plans on the last scan | — | — | `sync read` |
| **read job** (RJ) | — | — | shared, non-blocking (below) | the RJ rows of §5.2, `rekordbox match`, `status --ready`, `doctor`, `track spectrum` |
| **person job** | — | at its save only | — | `login sign-in`, `login use` (it may wait for the Keychain question) |
| **settings write** | briefly while a music folder is bound (today's `lock_briefly`: a running library job never sees its settings change under it) | around the read-change-write | — | `settings set`, `limits set/seen`, `login qobuz/skip/sign-out/spotify`, `setup music`, `sync scope` |
| **support-only job** | — | the whole job; refused `busy` while a write job of this support folder runs (a sync imports yt-dlp lazily) | — | `tools update`, `tools rollback` |
| **brief save** (B) | — (library.db waits ≤ 1.5 s, today's rule) | for `setup skip-import` (it writes settings) | — | `library favourites …`, `folder crates …`, `setup skip-import` |

- The **support lock** is an `flock` on `<support>/.support.lock`, waited for ≤ 2 s, then `busy`
  (`reason: "support_lock"`). It guards `settings.json`, `config.json`, `tools/` and the login files against a
  read-change-write from two processes (two windows, a window before Setup has a music folder, a terminal). The
  window's in-process `_settings_mutex` stays in front of it.
- **rekordbox readers** (status, preview, match, the rekordbox parts of todo, track, check and status) try
  `rekordbox.lock` with `LOCK_SH | LOCK_NB`. While a writer holds it they never open master.db and answer their
  rekordbox part as `writing` (the process's last cached answer when it has one, with its `as_of`). `writer_lock`
  retries for up to 2 s, so a reader's brief shared hold never makes a writer `Busy`. This replaces the hub's
  in-process rule (`_rekordbox_status` skips master.db while its own write job runs), which no other process sees
  (R4).
- The catalogue's `locks` column states this per entry; T10 pins it.

### 6.2 The registry

- **Where:** `<support>/jobs/<job id>/`, per Mac and support folder, never in the music folder: jobs exist without a
  music folder (Setup, `tools update`), the registry must not vanish with an unplugged drive, and a sandbox clone must
  not inherit running jobs. Each job records its roots (`music` or null, `support`, `rekordbox`, `sandbox`); `job
  list` shows the jobs of the current music folder and those with none, unless `--all`.
- **Files of a job:**
  - `state.json`: id, kind, catalogue command, args, `via` (`window` | `terminal`), `roots`, `pid` and `pid_started`
    (the process's start time), `status` (`queued` | `running` | `stopping` | `done` | `lost`), `started`, `ended`, the
    reduced progress (index, total, current item, step, waiting, counts, the one-line `line` the window's foot shows),
    live `person_steps` (§6.5). Written with `write_json_atomic` at every status change and at most once a second
    otherwise.
  - `alive`: an `flock` the process running the job holds for the job's whole life.
  - `events.jsonl`: the events as the window receives them (`events.py`, serialised as for the bridge). One writer
    thread per job; the engine's thread only enqueues. `Progress` and `Waiting` are coalesced by today's `_same_slot`
    rule (the latest per slot, flushed at most twice a second). Capped: the first 2 000 events, a
    `Truncated {skipped}` marker, then a rolling tail of the last 10 000 (`events.tail.jsonl`), so a multi-hour sync
    neither slows down nor fills the disk (R17).
  - `result.json`: the final envelope (§4.1).
  - `log.txt`: warnings and tracebacks of that job (a worker's stderr).
  - `stop`: present once someone asked the job to stop (§6.4).
- **Retention:** the newest 100 jobs or 30 days, pruned at each job start; a job whose `alive` lock is held is never
  pruned.
- **Liveness:** a job is `lost` when its `state.json` says `queued`, `running` or `stopping` and its `alive` lock is
  free (one `LOCK_SH | LOCK_NB` try, released at once). Never by pid: pids are reused after a crash or a reboot (R6).
  The reader that finds it lost rewrites `status: lost`; the next writer's `recover_pending` finishes its journaled
  step as today; `doctor` names it; `job wait` on it answers `failed`, `reason: "worker_lost"`, `next: doctor`.
- **Ids:** `job:<8 hex>` for every job, the window's included (contract change: `JobStarted.id`, `JobFinished.id`,
  `job_status()` and `stop(job_id)` carry the string).

### 6.3 How a job runs

**From the terminal: a worker process.**
1. The client parses and checks the command line, resolves the roots (music, support, rekordbox, sandbox) as it sees
   them, writes `state.json` (`queued`) and starts the worker `Discjockey job _worker <id>` in a new session (stdin and
   stdout to `/dev/null`, stderr to `log.txt`; a write job under its own `caffeinate -i -w <pid>`).
2. The worker takes `alive`, records `pid` and `pid_started`, and builds a headless `HubApi` (§8.1) **from the roots
   in `state.json`, never from its own environment** (a sandbox job can't land on the real library, §10.3). It calls
   the catalogue's method with the stored args. `HubApi`'s `Jobs` runs **inline** in a worker: it adopts the job id of
   `state.json`, runs the work on the worker's **main thread** (the only thread that gets signals and where
   `deferred_interrupt` holds a Ctrl-C until a step is safe) and takes the locks of §6.1 there.
3. A held library lock: without `--wait-busy` the worker writes the `busy` envelope and ends; with `--wait-busy <s>`
   it tries again every 2 s until then (it rides out the window's opening scan and its 60 s rescan, L D28).
4. Signals: the first SIGINT cancels the token (Stop safely); a second one at least `CTRL_C_REPEAT_S` (1.0 s) later
   raises `KeyboardInterrupt` (stop at once, still held back inside a step by `deferred_interrupt`); a repeat sooner is
   ignored, as today.
5. At the end the worker writes `result.json`, then `status: done`, then releases `alive`.

The client meanwhile **follows** the registry (polls `state.json`, tails `events.jsonl`): progress to stderr, the final
envelope to stdout, by the rules of §6.5. Killing or closing the client (an agent's tool call timing out, a closed
Terminal tab) never touches the worker. Ctrl-C in an attached client becomes a stop request: the first press writes the
`stop` file, a second one ≥ 1 s later asks for `--now`.

**From the window.** `Jobs.start` registers the job the same way (in-process, `via: window`; the window process holds
the job's `alive` lock) and runs it on a thread as today; the job's writer thread writes its files. So `job list`,
`status` and `job show` see the window's jobs, and the window sees the terminal's (§6.6).

**Read jobs** take the same path without locks. **Brief saves** run in the client and answer at once, as in the
window.

### 6.4 Stopping, from any process

- `job stop <job|current>` writes `jobs/<id>/stop` and answers `ok` with `data.status: stopping` (`refused`,
  `not_running` when the job has ended). The job ends `stopped` (exit 5 for whoever waits on it).
- `CancelToken` gains a stop file: `cancelled` is true when its event is set **or** the file exists (one `stat` at most
  every 0.5 s); `check()` uses `cancelled`; `sleep()` waits in steps of at most 0.5 s and checks `cancelled` in each, so
  a Spotify rate-limit wait of minutes ends within a second (R18). Every place that checks the token today (between
  items, inside steps, in pacing sleeps) therefore stops for a request from any process, the window's own jobs
  included.
- `--now` (terminal jobs only; the window offers only "Stop safely", so a window job answers `refused`,
  `window_job`): the client sends SIGINT twice, ≥ 1.0 s apart, and only while the job's `alive` lock is held **and**
  the pid's start time equals `pid_started` (`proc_pidinfo`); otherwise the job is `lost` and no signal is sent to
  whatever process now has that pid.

### 6.5 Waiting and following

| Want | Command | Answer |
|---|---|---|
| Start and get the id at once | `<command> --detach` | returns once the worker reports `running` (it holds its locks) or has ended (a `busy` included), at most `--wait-busy` + 5 s later: `outcome: ok`, `job`, `data.status: running`, exit 0; or the job's own envelope when it ended first |
| Wait at most S seconds | `<command> --wait S` | the job's own envelope if it ended, else `outcome: running` (exit 8) with `job`, the progress and the live `person_steps` |
| No flag, stdout a terminal | — | follow to the end (a person in the Terminal sees today's behaviour) |
| No flag, stdout not a terminal (an agent, a pipe) | — | `--wait 90`: agent shells kill a call after about 2 minutes, and a killed `--json` client would have printed nothing (R21) |
| Follow events | `job follow <job> [--jsonl] [--from-end]` | the events from the start (or the end), then the final envelope; text mode = the console's progress lines |
| Wait for the end | `job wait <job> [--wait S]` | the job's envelope (its own outcome and exit code), or `running` (exit 8); the same default as above |
| See it | `job show <job> [--log]` | `state.json`, the last events, `result` when done, `log.txt` with `--log` |
| Stop it | `job stop <job\|current> [--now]` | §6.4 |
| Everything running and recent | `job list [--all]` | running first, then newest |

- The **first stderr line** of every job command is `Job job:… started (follow: <path> job follow job:…)`, before
  anything else, so an agent whose call was killed still has the id; with `--json` the envelope's `job` holds it.
- **A job that waits for a person says so while it runs** (R22). The process running the job writes live
  `person_steps` into `state.json` the moment the job reaches a person's step (`SignInPhase` waiting: `step:sign_in`;
  a Chromium cookie read about to raise the Keychain question: `step:keychain`; a batch that waits for rekordbox to
  close: `step:quit_rekordbox`) and clears them when it moves on. `running` envelopes, `job show`, `job list` and
  `status` carry them. The guide's rule: on `running` with `person_steps`, tell the user now, then `job wait` again.
- The agent guide and §15 use `--wait 90` and `job wait <job> --wait 90` in a loop, never one longer call.

### 6.6 The window open at the same time

| Topic | Rule |
|---|---|
| Shared library | one music folder, one `library.db`, one library lock; the window binds its folder at start, a command resolves it fresh each time (a worker takes it from `state.json`) |
| The lock | stays the arbiter: one library writer at a time. Window writes refused while a terminal job holds it answer `console` (bridge) as today, now with the job's `line`; terminal writes answer `busy` with `data.holder` {job, via, kind, line} |
| Who sees whose jobs | the window watches `<support>/jobs/` (one poll a second of the running jobs' `state.json`) instead of probing the lock every 3 s. The "running in the Terminal" banner shows the job's kind and `line` ("Sync running in the Terminal · 4 of 60"), and the Sync page can show its live view from `events.jsonl`. When a terminal job ends, the window emits the same `JobFinished` it emits for its own (from `result.json`) and re-reads, so a terminal write of any length refreshes the window (today one shorter than the 3 s probe was never noticed, A §5.6). The lock probe stays only for a holder with no registry entry (an older Discjockey) |
| Who sees whose batches | all batches in one table: `batch list` and the window list the same rows. The `console` scope is dropped: a batch records where it started (`via`) and its real scope (`library:<view>[:<key>]`, `todo:cdj`, `selection`), so the window's Resume links show stopped terminal batches too (T §0.5) |
| The plan | derived from the stored read (§9.2): the window's Sync page and `sync plan` show the same plan in any process, and a terminal sync's read is the window's next plan without any hook |
| Which windows are open | each window writes `<support>/windows/<pid>.json` (pid, start time, music root) and holds an `flock` on it while open; `where.windows_open` counts the files whose lock is held and never touches the window's own `.window.lock` (R19: taking that lock to probe it could make a starting window think it isn't first and lose its saved settings). A window start removes stale files |
| The window's own automatic work | scan at open and after 60 s, the first read, the automatic import once per session: they stay window behaviour (a person opened the window). Commands never start them by themselves; an agent runs `library scan`, `sync read`, `import run` |
| A music folder change | `setup music <path>` writes `config.json` (support lock); an open window keeps its folder until reopened: the answer carries `person_steps: [step:reopen_window]` when `windows_open > 0` |

Pinned by T10: a stop file stops a window job and a terminal job between items, and inside a 60 s token sleep within
1 s; a killed client leaves the job running and `job wait` then gets its envelope; a dead worker is `lost` (its `alive`
lock free) even when its pid now belongs to another process, and `--now` signals nothing then; two clients that start
writes at once get one `running` and one `busy`; a window job and a terminal job each appear in the other's list, and
the window gets a `JobFinished` for the terminal one; the locks table of §6.1 per catalogue entry; a rekordbox reader
during a (fake) write never opens master.db.

---

## 7. Writes: dry runs, confirmation, undo, selection

### 7.1 Dry runs and the gap to the apply

- **Every write that moves, renames, converts or deletes a file, writes rekordbox, edits playlists.txt or changes what
  a sync will do has `--dry-run`.** A dry run takes no lock and answers exactly what the window shows before the
  person presses the button: the AIFF plan, the tidy rows, the undo preview, the removal preview, the playlist
  change's preview with its save question, the limit's what-if, the upgrade's ways and outcomes.
- **What a dry run may write: exactly one file, its plan, `<support>/plans/<plan id>.json`.** Nothing in the music
  folder, rekordbox's folder, `settings.json` or `library.db` (T9 compares every byte outside `<support>/plans/` and
  `<support>/cache/`). Three rules make that true:
  - **No scan.** A dry run plans on the last scan, says when in `as_of.scanned_at`, and puts `library scan` in `next`
    when a watched folder's or `Library/`'s modified time is newer. (Today `prepare(dry_run=True)` stores a scan when it
    gets the lock.)
  - **No stored facts.** Missing file facts are read in memory for up to 50 files; more answer `refused`,
    `facts_missing`, `next: library facts` (the explicit write of §5.3). Today `convert --dry-run` fills facts under
    the lock (L §5); `importer`'s facts code splits into "read" and "store".
  - **No settings.** `limits set --dry-run` is the what-if; today's `--extra N` wrote settings in a dry run (A §1.4).
  - Reads open `library.db` with `?mode=ro` (today every open is read-write in WAL mode and its close checkpoints).
- **The plan id.** A dry run's answer carries `data.plan_id` (`plan:<12 hex>`, the hash of its kind, its music root and
  its sorted item keys) and stores the plan in `<support>/plans/` for 24 h: kind, root, the items with their keys and
  answers, and for a sync the read id and records generation it was derived from (§9.2). `<write> --plan <id>` runs
  **only the items of that plan**: each item is asked again as it runs (the engine's per-item checks stay), an item
  whose answer changed is skipped with `reason: "changed"`, an item that is new since the plan is left out and listed
  under `data.new_since_plan`. This is the window's sync rule (`run.select_actions` with `new_since_preview`) made
  general; the window's own Start sends the plan id it showed (`start_sync(plan_id, selected)`). An unknown plan id is
  `bad_args`, `unknown_id`; one older than 24 h or for another music folder is `refused`, `plan_expired`, with the dry
  run in `next`. Without `--plan` a write plans fresh, as the window does when the person presses a button without a
  panel. The agent guide says: dry run → show the user → apply with `--plan`.
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

- One engine function answers "which ids does this listing select" (`HubApi.select(listing)`, §8.1), used by `--rows` and
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

### 7.5 Qobuz and account protection across processes

Redesigned after the review (R1). Today the pause after 3 failures in a row and the pacing live inside one process:
`Budget` keeps the streak per run (the hub carries one for "Use this" in `HubApi._qobuz_streak` /
`_account_streaks`), a `Pacer` is made per run, and "Use this" runs with `NoPacer` (harmless at a person's speed). With
one process per command both would start fresh at every call, so an agent's loop of `version use` would get no pacing,
no break and no pause. The protection becomes shared state, one owner per fact:

| Fact | Today | Lives in | Changed by |
|---|---|---|---|
| Daily counts, carry-over, signals | `usage` table (library.db), per library | unchanged | every download, under the library lock (every download is a write job) |
| Failure streak and pause, per service (`failures_in_a_row`, `download_failed_in_row`, `paused`, `paused_at`) | memory, per run; the hub's session copy | the service's `usage` row, as `streak` beside the counts | `Budget`: loaded when built, saved with every `count` / `failed` / `succeeded`, under the library lock |
| Pacing, per service (`last_request_at`, `last_download_end_at`, `since_break`, `next_break`) | a `Pacer` per run | `<support>/pace.json`, guarded by `<support>/pace.lock` (an `flock` held only to read and reserve, never while sleeping) | the shared pacer, from every job and every network read of any process |

Rules:
- **One pacer for everything.** `pacing.SharedPacer` replaces `Pacer` and `NoPacer` in the sync, "Use this", "Use
  link", `version search` and `version preview`, in the window and in every command. Today's numbers, now across the
  processes of this Mac: a Qobuz search starts no sooner than 2–5 s after the previous Qobuz request; a Qobuz download
  no sooner than 20–60 s after the previous Qobuz download ended; after every 10–15 Qobuz downloads a 2–5 minute break;
  the same per account service (YouTube Premium, SoundCloud Go+); free fallback downloads keep their 3–8 s. Ten
  minutes without a download of that service count as the break (its count starts again), which keeps today's "a new
  run starts a fresh count" without letting back-to-back commands dodge the break.
- **Reservation, not a race.** Under `pace.lock` a request takes the next free slot (`max(now, last + drawn gap)`),
  writes it, releases the lock and waits for it on the token (a `Waiting` event as today, so the window and `job
  follow` show "Protection pause …"). Two processes asking at once get two slots a gap apart.
- **Why the support folder:** the logins, and so the accounts, belong to the support folder; two music folders on one
  account share one pace. The daily counts stay per library, as today (unchanged, noted).
- **The streak across processes.** A success ends it (today's rule, including "a search success doesn't end a row of
  failed downloads"); three failures in a row pause the service for every process; **the pause ends when the next
  sync starts**, in any process (`run.execute` clears it under the library lock: today's "paused for this run" and the
  hub's "the streak starts again when a sync starts", made durable). One change from today: a pause a sync ended with
  now also holds for "Use this" until the next sync. The account has just failed three times in a row, so this is the
  reading of the invariant that protects it.
- **Searches** (`version search`, no library lock) go through the pacer and leave out a paused Qobuz with a note
  ("Qobuz was not searched: it is paused after 3 failed requests in a row."), as today's not-set-up note does; they
  don't change the streak (as today in the window).
- `version search`, `version preview`, `version use` and the `login` checks answer `busy`, `sync_running` while a sync
  job of this support folder runs in any process (the registry, §6), replacing `_no_sync_running`'s in-process look.
- In a sandbox no account login exists at all (§10.3), so nothing there can count against a real account.
- `HubApi._qobuz_streak` and `_account_streaks` are deleted (§9.2).
- Tests: three processes that each fail once in turn pause Qobuz for all of them; two back-to-back `version use`
  workers start their Qobuz downloads at least the drawn gap apart; a sync's start clears the pause; a loop of
  `version search` is spaced 2–5 s per Qobuz request; the window's "Use this" waits for a slot a terminal job reserved.

---

## 8. "Everything the window shows" by construction (H1)

Redesigned after the reviews (R15, R16, R36, R37, R40–R44, C4). Three mechanisms make a gap fail rather than merely
unlikely: one object answers both front ends, so the CLI prints exactly the window's payloads; every word that depends
on data comes from the engine, and the window's fixed words are extracted into a catalogue the CLI prints; and checks
fail as soon as the window computes, words, colours, orders or offers anything its payloads don't carry.

### 8.1 One answer for both front ends: a headless `HubApi`

**Decision (R15): the CLI runs on `HubApi` itself, without a window. No `surface/` package is extracted.** Reasons:
- `HubApi(support, events=None, services=None, media=None)` already builds without a window; the CLI binds it to the
  library the way `app.main` does.
- Its reads need what a set of free functions has no place for: `Services` (95 uses of `self._svc`; what tests replace)
  and the caches that keep the window fast (`_rb_cache`, `_cdj_cache`, `_tag_cache`, covers). A headless `HubApi`
  keeps them; in a one-shot command they are just cold.
- What tied `HubApi` to one window is its session state, and §9.2 moves that to disk anyway (the stored read, `rev`,
  the registry, the import state, the shared streak). After that, two processes with a `HubApi` each give the same
  answers.
- Parity becomes true by construction: the command calls the very method the bridge calls. Extracting ~150 KB of
  `api.py` behind an unchanged bridge was the largest risk of the first draft's build, for no gain in reach.
- Splitting `api.py` into modules by area stays a refactor anyone may do later, never a prerequisite.

The shape:
- **`HubApi` is the one surface.** Every catalogue entry names a `HubApi` method. Reads the window lacks today
  (`status --ready`, `doctor`, `history`, `track find`, `rekordbox preview`, `rekordbox match`, `library superseded`,
  `upgrade_preview`, the Auto-upgrade phase alone, `library facts`, …) become `HubApi` methods too, marked `cli_first`
  in the catalogue (no window caller yet; the window may use them later). Only the CLI's housekeeping has no method:
  `help`, `where`, `job …`, `sandbox …`, `app install-command`, and `open …` (which calls the same engine helpers as
  the bridge's open methods).
- **Payloads carry paths.** Every payload carries `path`, `cover_path`, `upgrade.path`; the `bridge` decorator adds
  `cover_url` / `audio_url` beside them when a media server is attached (a declared transform list in
  `hub/catalog.py`, pinned by a test). Headless, no URL keys exist.
- **Answers carry the outcome.** `OpProblem` and `Busy` gain `reason`, `next`, `person_steps` and `data`; the `bridge`
  decorator maps `kind` to `outcome` through `hub/outcomes.py` and puts them all beside `{ok, kind, message}`
  (additive, §4.3). The CLI reads the same dict.
- **Writes** return `{job_id}` and finish with `JobFinished` as today. In a worker `Jobs` runs inline (§6.3), so the
  method returns after `JobFinished`, whose `result` is the envelope's `data`.
- **The CLI adapter** (`discjockey/cli/`): the parser generated from the catalogue, the envelope and exit codes, the
  text renderers (`discjockey/cli/render/`, one layout per schema), the job client (§6). **A CLI handler computes no
  fact:** T3 is an import and AST check that a handler calls only the `HubApi` methods the catalogue names (or the
  housekeeping modules above) and renders their answer.
- **`discjockey/hub/catalog.py`** is the table of §5.2 in code. Per entry: method → command path, kind (§5.2),
  `locks` (§6.1), `needs_yes`, the dry-run method, the per-item states that make it `partial` (R24), the schema name,
  and **the map of every parameter** (and every key of a dict parameter, through its `TypedDict`) to a flag or
  positional (R40); or `WINDOW_ONLY` with a reason from a closed set (`native_dialog`, `closes_window`). The parser,
  `help --json`, the agent reference and the tests are generated from it.
- `discjockey/hub/select.py` holds `select(listing)` (§7.3) and `discjockey/hub/outcomes.py` the outcome table; both
  serve `HubApi`. One name throughout: there is no `present/` or `surface/` package (R33).

### 8.2 Payload shapes, one source

- Every payload is a `TypedDict` in `discjockey/hub/shapes.py`. Every field is
  `Annotated[<type>, F(shown=<bool>, doc="<words>")]`: `shown` says whether the window shows it (the text renderer must
  place it, T7), `doc` gives its meaning for the reference. A field without `F` fails T6.
- An in-repo generator (`python -m discjockey.hub.shapes --export`) walks `typing.get_type_hints(include_extras=True)`
  and supports a closed set of constructs: `Literal`, `NotRequired`, `X | None`, `list[…]`, `dict[str, …]`, nested
  `TypedDict`s, `str`, `int`, `float`, `bool`; anything else is an error. It writes the JSON Schemas
  (`additionalProperties: false`; `help <cmd> --json`, T6), `hub-ui/src/lib/bridge/types.ts` (generated, replacing the
  hand-kept copy; CI checks it is fresh, like `hub/static`) and the renderers' field lists. No new dependency
  (no pydantic) (R36).
- `docs/hub-bridge-contract.md` shrinks to its rules (never reject, jobs and events, brief saves, the URL transform)
  plus a pointer to the generated reference; it is no longer a third copy of the shapes.
- The fake backend's payloads validate against the same schemas (T6), so the fake can't show a field the engine lacks
  (R16).

### 8.3 Words: data words from the engine, fixed words extracted

**Decision (R44): split by kind of word, made strict.**
- **Words that carry data come from the engine**, filled in next to their facts: `next_try` + `next_try_text`
  ("next try in 3 days"), `quality` + `quality_text`, `dim` + `dim_text`, `actions[]` with `label`, `primary`,
  `blocked` + `blocked_text`, the `steps[]` of a rekordbox check, `outcomes[]` with `tone` and `text`, `empty` +
  `empty_text`. `discjockey/words.py` (pure) holds them with named fields and plural forms, one copy each (today
  `REASON_WORDS` in the engine and `SAME_TRACK_WHY`/`WHY_NOT_LINE` in the UI, two size-word functions: T §0.4, L D36).
- **State words are data words.** A fixed word the window shows *because of* data (a badge, a chip label, an
  empty-state sentence, a status word, a reason, "Resume · k left", a tone's word) travels in the payload as
  `<fact>_text` next to its fact. The window never picks a word by a condition it computes.
- **Fixed words stay in the window's source.** Headings, column names, button labels, static explanations and
  tooltips that the window shows whatever the data stay literals in Svelte markup, or constants in `*.words.ts`
  modules (string constants only). A build step extracts them.

Why: moving every fixed word out of 163 Svelte and 129 TS files into keyed Python would be about two thirds of the
first draft's group 7 (one Sonnet group per page with screenshot comparisons) and buys no reach, because a fixed word
carries no fact. What an agent needs from fixed words (every tooltip and explanation, and which word stands for which
field) the extraction gives completely and without anyone keeping a list. What the guarantee needs is that **no word
depends on data unless the engine sent it**; that is a rule about the window's code (§8.4), not about where fixed words
are kept. So the single source of every *meaningful* word is the engine, and the fixed words have one source too: the
window's markup, read by the build.

The extraction:
- `hub-ui/scripts/words.mjs` runs in `npm run build` (Svelte's own parser for markup, the TypeScript parser for
  `*.words.ts`). It collects every text node; every `title`, `aria-label`, `placeholder` and `alt`; and the text props
  of the blocks that show words (`Hint`, `InfoTip`, `NoteCard`, button labels, …; a list kept beside the blocks).
- Each entry: `id` (`<component path>:<slug>`), `text` (the template), `kind` (`text` | `title` | `aria` |
  `placeholder` | `tip`), `page`, `component`, `term` (what an `InfoTip` explains: a required prop of `InfoTip`) and
  `when`: the payload field whose truth or value shows it, when the literal sits in an `{#if}` on a bare payload field
  or enum value (`row.hidden` → "Hidden"). `when` is how the CLI's glossary and text renderer know the window's word
  for a boolean or enum field.
- Output: `discjockey/hub/static/words.json` (build output, committed; CI checks a fresh build produces it, like the
  rest of `hub/static`). The app bundles it; `help glossary` prints it by page, each tooltip with its `term`; the
  text renderers use its `when` words for boolean and enum fields.
- **One template syntax for both languages (R37):** `{name}` fills a field, `{n|file|files}` picks the plural form,
  `**…**` marks emphasis. One `fill()` in Python (`words.py`) and one in TypeScript (`lib/fill.ts`), pinned by one
  shared fixture file. A fixed word with a view-state number ("Convert {n|file|files}" for a selection) is filled by
  the window; its fields are named, so the rendered check (§8.4) knows `n` comes from view state. A payload sentence
  with emphasis travels as `parts[] {text, strong}`.
- Dates and numbers: the engine sends ISO dates and raw numbers plus their `_text` ("31 Oct", "today", "1.2 GB"); the
  window may format a number it receives (grouping, `m:ss`) only through the shared helpers of `lib/format.ts`, which
  mirror `words.py`'s formatters and are pinned against them by the shared fixture.

### 8.4 Checks that fail when the window gains anything the CLI lacks

The CLI prints the payloads whole (§8.1), so the window can show more than the CLI only by producing something in
TypeScript. Four checks make that fail (C4, R41, R42), from the cheapest to the most complete:

1. **`derive` (static and type-aware; rule checker, part of `npm run check`).** In `hub-ui/src/{pages,lib}` (except
   `lib/bridge`, `lib/format.ts`, `lib/fill.ts`), every expression that reaches the screen (a text node, an attribute,
   a block's prop, a `class:` or `style:` directive, an `{#if}` condition, an `{#each}` list or key) must be one of:
   - a payload value read as is: a member chain from a value whose type comes from the generated `types.ts`, with
     `??` or optional chaining for absence;
   - a fixed literal in markup or a `*.words.ts` constant, or `fill()` of one with payload or view-state fields;
   - a shared format helper applied to a payload value;
   - as an `{#if}` condition: a payload boolean, or a payload enum compared with one of its own literals (presentation
     per value, such as which icon or which fixed word; the fact is the field, and the CLI prints it);
   - an `{#each}` over a payload list, in payload order;
   - view state: a value declared through the `view()` marker (`$state(view(…))`: selection, open panel, hover,
     scroll, width, player time, an unsent draft).

   Anything else that reads a payload value fails: arithmetic, comparisons other than the enum case, `.filter`,
   `.sort`, `.length`, `.reduce`, `.slice`, `.some`, `.find`, a table looked up by a payload value
   (`TONE[row.quality]`), strings built from payload values. Props that carry meaning by colour (`tone`, `dim`,
   `badge`, and a declared list of meaning classes) accept only a payload value read as is. The checker gets types
   through `svelte2tsx` and the TypeScript compiler (both already in the toolchain through `svelte-check`); a payload
   value cast to `any` or `unknown` fails.
   Exceptions live in `hub-ui/derive-allow.json`, each with a reason from a closed set: a view reason (`layout`,
   `selection`, `open_panel`, `player`, `scroll`, `width`, `loading`, `draft`) or `debt:<§9.3 row>`. `debt` entries
   may only shrink (a ratchet) and the §9.3 groups remove them; a view entry is reviewed like code. So the next
   `rowInTodo` (L D6: a count, order, tone, visibility or default a model computes from payload fields) fails the day
   it is written.
2. **`flows` (static; rule checker).** One user action (one event handler) calls at most one bridge write, because a
   window action built from several calls has no single command (R42). Today's exceptions sit in the allow file as
   `debt:<row>` and go to zero (L D10 is the known one).
3. **The rendered check (T5b; `npm run verify`, every shot).** The fake bridge records each shot's read answers. In
   every shot, every visible string (text plus `title`, `aria-label`, `placeholder`, `alt`, collected as
   `scripts/strings.mjs` does today) must be either a `words.json` entry filled with values of the shot's payloads or
   its named view fields, or a payload value **in scope**, as is or through a shared format helper. Scope: blocks emit
   `data-item="<id>"` from the item's `id` prop, so a string inside an item must come from that item's payload object
   or the page-level fields; a computed "3" can't pass because some other field happens to hold 3. Every
   `[data-tone]`, `[data-dim]` and `[data-badge]` must equal its item's payload field, and every `[data-list]` shows
   its items in payload order unless it carries `data-sort-view` (a view sort the allow file names). The escape routes
   of a literal-finder (template strings, `key.replace('_', ' ')`, enum keys printed as words, SVG `<text>`, CSS
   `content:`) all end up as a visible string that is neither, so they fail here: this is the backstop for whatever
   the static rule misses (R41).
4. **Every component is seen.** In fake mode a Vite plugin marks each component when it mounts; after the shots run,
   a component under `pages/` or `lib/components` that mounted in no shot fails (gallery-only blocks excepted by a list
   in the plugin), so a new screen part can't skip check 3 by having no shot. Every `shots.json` entry declares
   `reads: [...]` (the bridge reads behind it) or `view: "<reason>"` from the closed set; a vitest fails on neither.

On the Python side the same promise rests on: T1, which now maps every parameter and dict key of every bridge method,
so the window can't gain a choice the CLI lacks (R40); T6, every real output and every fake payload valid against its
schema; T7, the text rendering places every `shown` field; and the parity test on the Python hub fixtures
(`tests/hub_helpers.py`): for every read of the catalogue the bridge answer minus the URL keys equals `--json`'s
`data` (true by construction since §8.1, pinned so a handler that reshapes fails; R16). `file_state` is one
computation in `HubApi` (one stat per file), so a row and the details agree (Supplement C's `file_missing` surprise).

---

## 9. State and logic move into the engine

### 9.1 The rule

A computation the window does today **moves into the engine** (`HubApi`, the pure `views.py`, `words.py`) when it does any of:
(a) decides which items an action applies to, what it will do, or whether it may run;
(b) produces a fact, count, order, state, colour/tone or dimming the person reads;
(c) produces a sentence that carries data.
It **stays in the window** only when it is: layout and geometry; which panel, menu, dialog or fold is open; focus,
selection, scroll, hover; audio playback; timers and animation; an unsent draft; per-window view preferences (the sort
and filter remembered per view, A–Z, widths, folded sections, details hidden). Where the window *uses* a moved answer,
it calls the bridge field instead of its own copy, and the copy is deleted in the same change.

### 9.2 State the window holds today, and where it lives now

Redesigned after the review (R14): **store the playlist read, derive the plan.** A stored plan can't hold today's
`run.Prepared` (the whole planned snapshot, and `SourceTrack`s whose private link tokens are kept out of `asdict` on
purpose), and across processes every writer would have to re-plan and rewrite it after each change, in the right
order. The read has neither problem.

- **What is stored.** library.db's `playlist_reads` / `playlist_tracks` (they exist: playlist, service, read_at and
  the tracks) widen to everything the planner and the Sync, Playlists and Library pages need from a read. Per track:
  every `SourceTrack` fact the planner uses (isrc, album, image, link, duration, streamable, account_only, …),
  **never** the private SoundCloud link token. Per playlist: the read's problem and its service,
  `unread_folders` / `unread_members`, and the playlist's infos (name, owner, cover: today's `_infos`; the tracks a
  `playlist check` read: today's `_extra_tracks`). A read id (`read:<n>`, rising) names one stored read.
- **Who writes it.** Every read stores itself in one library.db transaction at its end: `sync read` (window or
  terminal) and the read a `sync run` makes. The records sit outside library state (like Favourites: no `generation`
  bump, not in `snapshot`), so writing them needs no library lock; the transaction keeps the newer read, so a slow
  read that finishes after a newer one was stored doesn't overwrite it (today's `PreviewStore.ready` rule, made
  durable). A failed read keeps the last good tracks and stores its problem beside them (today's "the last good plan
  with the problem next to it").
- **The plan is derived, never stored.** `plan = planner.plan(stored read, current records, settings)`, today's
  `run.replan`, pure. `HubApi` caches it per (read id, records generation, settings hash) in its own process. Any
  process that asks after any write gets the plan for the library as it is now: no writer needs a re-plan hook,
  nothing can go stale, and `stale` disappears (a sync's own read is the newest one).
- **Secrets stay in memory.** `sync run` reads the playlists again, as today (`sync_work` → `run.prepare`), so a
  private track's link token is fetched for the run and never written.
- **Binding.** `sync plan`'s `plan_id` is the hash of its root, read id and sorted action keys, stored in
  `<support>/plans/` (§7.1). `sync run --plan P` and the window's Start (`start_sync(plan_id, selected)`) select
  those actions from the run's fresh plan with `run.select_actions`, as today; actions new since the plan are listed
  under `new_since_plan`.
- **What this unlocks:** the Sync page, `library().rows[].track_link`, the same-song questions and duplicate groups
  and `dashboard.ready` exist in every process after any read, not only in the window that made it (A §0).

| State today | Where it lives now | Why |
|---|---|---|
| `PreviewStore.prep`, `read_at`, read problem, `stale`; `_infos`; `_extra_tracks` | the stored read in library.db; the plan derived on demand (above) | the Sync page, the questions and `dashboard.ready` exist only after a read in the same window today (A §0) |
| "Is this the same song?" questions and same-song duplicate groups (inside `prep`) | derived from the derived plan by `HubApi.todo`; `question list` | an agent can neither list nor answer them today (L finding 4) |
| `PreviewStore.auto_read` | stays (the window's one automatic read per session is window behaviour, §6.6) | a person opened the window |
| Sync scope switches (localStorage `sync.scope`), weekly checks on/off | `settings.json` `sync_scope` {`off`: [collections], `weekly_off`: [kinds]}; `sync scope show/on/off`; the window's switch becomes a settings write | the run's selection must be the same for the window and an agent (A U1) |
| Ticks and "how many" | stay a window draft; the presets and the default are engine answers (`sync plan` `presets`, `default_how_many`); `sync run` takes them as flags | a draft until Start is a view; what a choice means is not |
| `sync.lastSelection` (localStorage) | the job's `args` in the registry | the window's run list needs it after a reload; so does `job show` |
| `_shown` | `rev` tokens (§3) | stateless, works across processes |
| `_dropped`, `_selected` | the drop's `path` travels in `FileDropped` and back in `add_bought_file(track_id, path)` | a command passes a path (SA finding 3) |
| `_import_stopped`, `_import_auto_done` | library.db import state (`stopped_at`, `waiting`); the automatic import stays a window behaviour keyed on it | "Import stopped, n to go" must survive the window and be readable (L D29) |
| `Jobs.current`, `refresh`, `sign_in` | the job registry (§6.2) | every process sees every job |
| `_qobuz_streak`, `_account_streaks` | the `streak` in each service's `usage` row (§7.5) | one process per command would reset the protection at every call (R1) |
| `_rb_cache`, `_cdj_cache`, `_tag_cache`, the cover cache | stay per-process caches of `HubApi`, keyed by records generation, rekordbox's key or a file's size and mtime | no meaning; a cold cache costs only time |
| Recent toasts | each job's `result.json` | |

### 9.3 The rule applied to the audit rows

Ids: **L D1–D37** (library audit §2), **U1–U39** (app audit §2), **T:`fn`** (todo audit §2, by function), **SA/SB:
`file:fn`** (supplements). "→ field" names where the answer lives after the move.

**Moves into the engine (the window deletes its copy, and its `debt` entry in `derive-allow.json`, §8.4):**

| Rows | What moves | → where |
|---|---|---|
| L D1 | a route name is a playlist or a Library folder | `HubApi.resolve_collection(name)`; `--in` uses it |
| L D5, T:`decisionFor`, SA `TrackDetails` decision choice | which decision a track waits for (check > duplicate > upgrade) | `track().decision` {kind, item id} |
| L D6, SA `rowInTodo`/`inTodo` | "is it on the To-do list" (today it **diverges** from `views._group`/`todo_listed`) | row and track field `in_todo`, from the engine's one rule |
| L D7, D34, T:`actionsFor`/`IMPROVABLE`, SA `footAction`, `aiffShown`, `aiffVariant`, T `Details.aiff` | which actions an item/row offers, which one is the filled button, which menu items exist | `actions[]` {id, label, primary, blocked, blocked_text, command} on rows, tracks, to-do items |
| L D8, T:`canSwap`/`upgradeWays`/`defaultWay`/`UpgradeFlow.way`, `goes`/`NOWHERE`, `selectionWays`/`beforeLine`, SA `UpgradeCards` | the ways an upgrade offers, the default, the mode Replace sends with no choice, each way's outcomes, which selected items a way reaches, the n/m/k counts | `upgrade.ways[]` {way, recommended, outcomes[] {tone,text}, why_not_text}; `upgrade apply --dry-run` summary |
| L D9, T:`undoAsk`/`undoManyConfirm`, SB `ConfirmHost` callers | which actions confirm and their words | catalogue `needs_yes`; `confirm` {title, body, label} in the dry run |
| L D10, T:`groupIdOf` + `DuplicateFlow.#keepOne`, SA `DuplicateFoot` | "keep this file" as N−1 jobs with the group id recomputed in JS | one engine op `folders.keep_file(group, file_id, expect)` in one job; answer names the track holding the kept file (L D4 data part) |
| L D11, T:`keepWords`/`fileWords`/`fileFormat`/`lastFolder`/`keepLabel` | the duplicate's button and file words | `pair.files[].words`, `pair.keep_label` |
| L D12, D13, D14 (except `panelPhase`, `listShape` fold), T `aiffModel.*`, `aiffBatchModel.*`, SA `AiffCard`/`AiffFoot` | why Convert/Rename/Make is off (space, rekordbox open), button words, rows Now/Becomes/Name/Space, outcomes, notes, "Left as they are", drive names ("this Mac") | `aiff` card fields and `AiffPlan` gain `blocked`, `blocked_text`, `label`, `rows[]`, `outcomes[]`, `notes[]`, `left[]`, `space[].drive_name` |
| L D15, T:`cdjAllKeys`/`cdjReachable`/`wholeCdjGroup`/`upgradeAllKeys`/`wholeUpgradeGroup`/`multiScope`/`MULTI_GROUPS`, T `AiffBatchFlow.start` | what "all", ⌘A and a whole group select; which groups allow several | `HubApi.select(listing)` (§7.3); `groups[].multi`, `groups[].all` |
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
`LinkGuide` (fixed words, extracted into `words.json`, §8.3).

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
| `step:remove_test_tracks` | live tests only, at the clean-up (§15) | "In rekordbox, remove these test tracks from the collection: <names>. Then quit rekordbox." | the test script's `--clean` |
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

### 10.3 The sandbox: rehearsing without touching the real library, rekordbox or an account

Redesigned after the review (R2, R3, R8, R9, R10). The rule: **guard the roots, not a list of write calls.** A process
in a sandbox knows no path to the real library, the real rekordbox or the user's accounts, so a writer someone forgets
to guard can still only write inside. A sandbox folder holds exactly what `sandbox create` made: `music/`, `support/`,
`rekordbox/`, `watched/<n>/` (clones of watched folders) and the marker `.discjockey-sandbox` (JSON: id, created, made
from, the real roots at that moment, the list of what it made, the rekordbox mapping report).

| Command | Does | Refuses |
|---|---|---|
| `sandbox create <dir> [--from empty\|real] [--rekordbox none\|copy\|<fixture dir>] [--no-audio] [--wait-busy S]` | `--from real`, holding the real library lock for the copy: library.db through SQLite's backup API (a consistent copy, its WAL included), `playlists.txt`; the audio of `Library/`, `Superseded/`, `Upgrades ready/` and of each watched folder on the same volume cloned with `clonefile` (no extra space); the watched folders' paths rewritten in the copy to `watched/<n>/`, one on another volume left `folder_missing`; `settings.json` with every login, account and Qobuz setting removed (`qobuz_skipped`, no `accounts`). Never copied: login files, `jobs/`, `plans/`, `windows/`, caches, locks, `-wal`/`-shm` | `<dir>` exists and isn't empty (`exists`); `<dir>` equals, lies inside or contains the real music folder, a watched folder, rekordbox's folder, the support folder, the home folder or a volume root (`protected`); the real library's `pending` holds steps (`pending_steps`, `next: doctor`); no clone-capable volume (APFS, the library's volume) and no `--no-audio` (`no_clone`); `--rekordbox copy` while rekordbox runs (`needs_person`, `step:quit_rekordbox`) |
| `--sandbox <dir>` or `DISCJOCKEY_SANDBOX=<dir>` on any command | runs it against the sandbox, all roots taken from the marker's folder; every envelope says `sandbox`; text mode prints "Sandbox: <dir>" on stderr first | a folder without a valid marker (`bad_args`) |
| `sandbox info <dir>` | what it was made from, when, its size, the rekordbox tracks it couldn't map | — |
| `sandbox remove <dir> --yes` | deletes what the marker lists as made by `create` (with whatever later commands made inside those folders), then the marker and `<dir>` | anything else at the top of `<dir>` (`not_sandbox_content`); `<dir>` equal to, inside or containing a real root, the home folder or a volume root (`protected`), the real roots resolved from the default support folder whatever the environment says |

Why `remove` may delete: a sandbox's audio is clones and rehearsal output; removing a clone never touches its original.
What protects the user's music is that `remove` only ever deletes inside a folder that `create` found new or empty, and
only what the marker says `create` made there (R3: `sandbox create ~/Music` is refused, so `sandbox remove ~/Music`
can't follow).

**The root guard, in sandbox mode:**
- `SupportPaths`, `Paths` and `rekordbox.locate` resolve only inside the sandbox (support `<dir>/support`, rekordbox
  `<dir>/rekordbox`); a `config.json` that names a music folder outside the sandbox is `refused`, `outside_sandbox`,
  when the paths are resolved, before anything is read.
- Inputs that name a path: `setup music` and `folder add` refuse a path outside the sandbox; `version add-file <path>`
  reads a file from outside and copies it in; `--png <file>` writes where the person said.
- The write layer (`run_op`, `move_files`, `move_path`, `write_json_atomic`, `db.connect` for writing,
  `rekordbox.write.open_write`, the backup restore, `write.replace_bytes`, `playlists_file.save`, reports, the
  operations log, the tools updater) checks each target against the sandbox root as a second line (`outside_sandbox`).
  The first line is that no real root is known to the process at all.
- A worker takes every root from `state.json` (§6.3), never from its environment.
- `DISCJOCKEY_REQUIRE_SANDBOX=1` makes every command but `help` and `sandbox …` refuse (`sandbox_required`) unless a
  sandbox is set: for developer agents working on the code (CLAUDE.md tells them to export it).
- `DISCJOCKEY_SUPPORT` / `DISCJOCKEY_REKORDBOX` stay as the plumbing the tests use; the docs point agents to
  `--sandbox`.

**No accounts in a sandbox (R2).** Every account login write (`login qobuz`, `login use`, `login sign-in` for YouTube
or SoundCloud) answers `refused`, `sandbox_no_accounts`; settings loaded in a sandbox force `qobuz_skipped` and no
`accounts`, so a login file copied in by hand does nothing. The Spotify read login, anonymous reads and free streams
stay: reads have no limit, and free streams are paced by the shared pacer of §7.5 (with the sandbox's own `pace.json`).
Nothing in a sandbox can download through or count against a real account.

**rekordbox in a sandbox (R10).** `--rekordbox copy` is refused while rekordbox runs. It copies rekordbox's library
folder (master.db and the analysis `share` folder, files cloned) while holding `rekordbox.lock`, then, **inside the
copy only**, repoints every track whose file lies under the real music folder or a cloned watched folder to its clone
(`write.Writer`'s path change and `anlz.splice_ppth`, rekordbox's own scheme). `sandbox info` lists the tracks it
couldn't map (files elsewhere or on other volumes). So Same track, Convert and Rename rehearse their real repoint. The
real rekordbox app never opens the copy: any step that opens, looks at or plays in rekordbox belongs to the real
library (§15).

Pinned by T9: every write command of the catalogue, run in a sandbox made from a real-looking fixture library next to
it, changes no byte outside `<dir>` (except a named `--png` target); `create` on a folder that contains the music
folder, and `remove` of it, refuse with nothing deleted; a `config.json` naming an outside folder is refused at
resolve; a Qobuz login planted in the sandbox downloads nothing; a clone made while a fake writer holds the lock waits
or answers `busy`, and its library.db opens clean; a clone refuses while `pending` holds a step; `--rekordbox copy`
maps a fixture track to its clone and a Same track rehearsal repoints it in the copy.

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
| today's command modules (`batch_cmd`, `convert_cmd`, `upgrades_cmd`, `rekordbox_cmd`, `settings_cmd`, the bare sync) | **drop**, each in the group that lands its replacement (§16); until then the new parser routes their old words to them unchanged | H5: nothing is kept for compatibility, and migrating them into the new framework first would build them twice (R45) |
| the window's lock probe every 3 s (`watch_console`) | **change** → the registry watch (§6.6); the probe stays only for a holder without a registry entry | a command shorter than 3 s was never seen; the probe can't say which job or how far |

---

## 13. Completeness tests (keeping it complete forever)

| Test | Fails when |
|---|---|
| T1 catalogue ↔ bridge | a `@bridge` method of `HubApi` is missing from `hub/catalog.py`, or an entry names no method; a parameter of a bridge method, or a key of a dict parameter's `TypedDict`, has no flag or positional in its entry (`inspect.signature` against the entry's map, R40); a `WINDOW_ONLY` reason is outside `{native_dialog, closes_window}` |
| T2 catalogue ↔ parser | an entry's command path doesn't parse, or a parser command has no entry (the housekeeping commands are their own table in the catalogue); once the last replacement group has landed, a route to a legacy command module remains |
| T3 the CLI computes nothing | a CLI handler calls anything but the `HubApi` methods its entry names (or the housekeeping modules of §8.1), or builds data instead of rendering the answer (import and AST check) |
| T4 screen states ↔ reads; parity | a `shots.json` entry has neither `reads` nor a `view` reason (vitest); on the Python hub fixtures, a catalogue read's bridge answer minus the URL keys differs from its command's `--json` `data` (R16) |
| T5 the window adds nothing | static (§8.4, 1–2): `derive` finds an expression outside the allowed forms, `flows` a handler with two bridge writes, the allow file gains a `debt` entry or holds a reason outside the closed set; `words.json` is stale against a fresh extraction; the `fill()` fixture renders differently in Python and TypeScript. Rendered (T5b, §8.4, 3–4): in a shot, a visible string, `data-tone`, `data-dim`, `data-badge` or list order is not backed by the shot's payloads in scope or the word catalogue; a component mounted in no shot |
| T6 schemas | a payload field lacks its `F(shown, doc)`; a command's real output or a fake payload doesn't validate against its schema; `types.ts` is stale against `shapes.py` |
| T7 text shows everything | a field marked `shown` is not placed by its schema's text layout, on the real fixture outputs and on a generated sample with every optional field set (R43); the golden text of a schema changes without its file (a review aid, R30) |
| T8 outcomes | a command exits with a code not matching its `outcome`; a `ProblemKind` has no row in the outcome map; `--json` prints anything but one object (also for usage errors and crashes) |
| T9 safety | a dry run writes a byte outside `<support>/plans/` and `<support>/cache/` (every command's `--dry-run` on a fixture library: all files, library.db and the rekordbox fixture compared); a `needs_yes` command acts without `--yes`; any of the sandbox cases of §10.3 |
| T10 jobs and locks | any of the cases of §6.6 (stop files, killed clients, lost workers, `--now` safety, the locks table, two writers, window and terminal seeing each other, rekordbox readers during a write) |
| T11 docs | `docs/agent-commands.md` differs from `discjockey help --markdown`; a catalogue entry has no example in it |
| T12 app binary | a built app with any argument but `-psn_…` doesn't reach the CLI (self-test round trip) |
| T13 shared protection | any of the cases of §7.5 (the pause across processes, the pacing gap between back-to-back commands, the reset at a sync's start, searches spaced, the window waiting for a terminal's slot) |

The CLAUDE.md "Agent-ready" rule is rewritten to point at T1–T13: a new bridge method, parameter, payload field, word,
derivation or screen state can't land without its command, schema, text rendering and docs, because a test fails.

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
4. The workflow: `where` → `status` → read → dry run → ask → apply with `--plan` and `--wait 90` (or `--detach`) →
   `job wait <job> --wait 90` while it answers `running` (tell the user any live `person_steps` at once, §6.5) → tell
   the user every `person_steps` entry of the result word for word → follow `next`.
5. Ids, selection, outcomes and exit codes (the tables of §3, §4.3, §7.3).
6. The questions of §11 with their commands.

---

## 15. The issue 33 live tests (todo audit J11) with the new commands

Every step marked **P** needs the user; everything else the agent runs. "Real" = against the user's library and
rekordbox with their go; the stage plans' rehearsal parts can run in `--sandbox` with `--rekordbox copy` once the
sandbox group has landed.

**When (decision on R46):** right after the live-test slice of §16 (phase 1), not at the end of issue 39. The user's
goal is that an agent runs these tests through the CLI, and stages A–D sit merged but untested on a real library
until then; so the commands these tables use are built first, and the tests run as soon as they exist. Running them
now with today's commands (the review's option a) would test the rekordbox writes but not the goal, and would be done
again later; running them last (option c) leaves the rekordbox writes untested for the length of the rebuild. The
slice needs nothing of §9.2: C 1a reads the phase's before-start line from `sync run --auto-upgrade-only --dry-run`.

**Waiting:** every long step uses `--wait 90` and then `job wait <job> --wait 90` until it ends (§6.5); written below
as "`--wait 90` + `job wait`".

**Clean-up (decision on R48):** the agent never deletes a file, and Discjockey gets no "forget" command for tests.
Every live-test script names what it makes with the marker `(upgrade test)`, in the file name and in the title tag, so
every file Discjockey derives from them (a New track, a Convert, a clean name) carries it too. After the person has
removed the test tracks from rekordbox (`step:remove_test_tracks`), the agent runs `folder remove <scratch> --yes`, then
the script's `--clean <entry>`: it refuses unless rekordbox is closed and the library lock is free, removes the test
entries from library.db (today's `--remove`), moves to the macOS Trash exactly the marked files in `Library/`,
`Superseded/`, `Upgrades ready/` and the scratch folder (and the `_Upgrade test/` folders once empty), lists what it
moved, and ends with `library scan` in `next`. The Trash is not a deletion: the user empties it. Rejected: a
`track forget` command (a product write path that exists only for tests) and running the agent parts in a sandbox
(every stage has steps in the real rekordbox app, which never opens a sandbox copy).

**Stage A**

| Step | Who | Command |
|---|---|---|
| 1a rekordbox ready, the right library, closed | agent | `rekordbox status` |
| 1b open rekordbox | **P** | `step:open_rekordbox` |
| 1c "rekordbox is open" | agent | `rekordbox status` (`running: true`) |
| 2 offsets of an MP3, a 48 kHz M4A, an AIFF | agent | `rekordbox preview --path <file> --json` (`timing.offset_samples`, `entries[].offset_ms`) |
| 3a make a test track | agent | `scripts/make_upgrade_test.py --keep-lossy m4a` |
| 3b import, analyse, 3 hot cues, quit rekordbox | **P** | — |
| 3c Discjockey knows the file | agent | `folder add <scratch folder> --wait 90` + `job wait` |
| 3d New track | agent | `upgrade list`; `upgrade apply <track> --way new-track --dry-run`; apply `--plan P` |
| 3e Relocate the old track to the new `.aiff` | **P** | the answer's `person_steps` (`step:relocate_new` with the path) |
| 3f cues on the same beats, no click | **P** (looks, listens) | agent afterwards: `rekordbox preview --path <new>` |
| 3g clean up | **P**, then agent | `step:remove_test_tracks`; then `folder remove <scratch> --yes`, `scripts/make_upgrade_test.py --clean upgrade-test-<n>`, `library scan` (see Clean-up above) |

**Stage B**

| Step | Who | Command |
|---|---|---|
| 0a File › Library › Backup; a spare USB stick | **P** | — |
| 0b copy rekordbox's folder aside; four click tracks with parked upgrades; scratch folder | agent | file copy; script; `folder add <scratch> --wait 90` + `job wait` |
| 1 import, analyse, cues, playlists, edit a title, export to the stick, quit | **P** | — |
| 2a Upgrade all | agent | `upgrade apply --all --dry-run` → `--plan P --detach`; `job wait <job> --wait 90` |
| 2b Stop midway | agent | `job stop <job>` → the job ends `stopped` (exit 5), `next: batch resume aiff:<n>` |
| 2c Resume | agent | `batch resume aiff:<n> --wait 90` + `job wait` |
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
| 1a rekordbox open; the Sync page's before-start line | **P** opens; agent | `sync run --auto-upgrade-only --dry-run` (`start_note`, `auto_upgrade`) |
| 1b sync: "… wait for rekordbox to be closed" | agent | `sync run --auto-upgrade-only --wait 90` + `job wait` (no downloads needed) → `auto_upgrade.waiting`, rows `rekordbox_open` |
| 1c To-do marks them; nothing changed | agent; **P** may look | `todo list --group upgrade_ready` (`sub`: "Waits for rekordbox to be closed") |
| 2a quit rekordbox | **P** | — |
| 2b sync again: upgraded, end screen lists | agent | `sync run --auto-upgrade-only --wait 90` + `job wait`; `run show last` |
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
| 1b run it | agent | `aiff convert --all --in folder:<path> --plan P --wait 90` + `job wait` |
| 1c AIFF/44.1/16, cues, grid, playlist | **P** | agent: `rekordbox preview --path <new>` |
| 2a the AAC listed with its words | agent | `todo list --group cdj` / `aiff convert --all --todo cdj --dry-run` |
| 2b Convert all; plays with cues | agent; **P** plays | `aiff convert --all --todo cdj --plan P` |
| 3 the MP3 by hand | agent; **P** looks | `aiff convert <track> --dry-run`, apply |
| 4 Undo all on each check card | agent; **P** looks | `batch undo aiff:<n> --yes`, `track undo <track> --yes` |
| 5a open rekordbox | **P** | — |
| 5b Convert one file: "Quit rekordbox", nothing changed | agent | `aiff convert <track>` → `needs_person` (exit 4), the batch of one closed, no resume |
| 6 export to a stick, play on a CDJ | **P** | — |

After each of stages B, C and D: the clean-up of A 3g for that stage's test tracks (person step, `folder remove`, the
script's `--clean`, `library scan`).

---

## 16. Risks and how the build plan must split

| Risk | Why it is risky | What the plan must do |
|---|---|---|
| A headless `HubApi` in a worker (§8.1) | `HubApi` was built for one window: session state, threads, the media server | group 1.1 binds a headless instance and proves one read and one write end to end before anything else; the §9.2 moves land before the commands that need them |
| Job registry and worker processes (§6) | concurrency, crash recovery, signals, the window writing the same files | Opus group 1.2 with T10's terminal cases before any write command uses it; the window's side separately in 1.4 |
| Locks per job kind (§6.1) | a wrong lock blocks the window for minutes, or lets two processes race on `settings.json` | the catalogue's `locks` column and its T10 table test in 1.3 |
| Shared Qobuz and account protection (§7.5) | a slip in the pacer or the streak is a risk to the user's account | Opus group 2.4 with T13; no command that downloads (4.1, 4.3) lands before it |
| Stored read, derived plan (§9.2) | changes how the Sync page and the run choose actions | Opus group 2.2 with the sync's tests; the Sync page's small switch-over in the same group |
| Contract changes (string job ids, `track_id`, the mode enum, `add_bought_file(path)`, `keep_file`, `stop(job_id)`, `start_sync(plan_id, …)`, `expect`, the answer's added keys) | `types.ts`, `contract.ts`, the fake and `hub-bridge-contract.md` must move together | one change set per group; the generated `types.ts` (2.1) before the read groups |
| The guarantee tooling (§8.4) | a type-aware checker can be slow or flaky; the rendered check touches every block | Opus groups 5.2 and 5.3; the allow file is seeded with today's debt, so nothing fails on day one and the ratchet then drives phase 6 |
| Phase 6, the window switched to engine fields | a slip changes what the window shows | per cluster, model and UI in separate groups; shots compared to `main`, words identical unless a duplicate is merged |
| Sandbox (§10.3) | it must sit at the roots or it is decoration; `remove` deletes | Opus group 7 with T9's sandbox cases written first; an Opus review |
| App routing (§2.1) | a mistake opens the window for every command, or a command for every Finder open | in 1.1 with the self-test round trip (T12) |
| The live tests on the real library (§15) | they write the user's rekordbox library | only with the user's go, after phase 1, with the rekordbox backup step and the clean-up of §15 |

**The groups (decision on R45).** Sonnet groups are planned at ≤ 250k tokens and Opus groups at ≤ 300k (the record:
Sonnet 150–380k, Opus UI 300–360k). One deliverable each; the plan agent may split further, never merge. Today's
command modules are deleted in the group that lands their replacement, never migrated first (§12).

Phase 1, the live-test slice (decision on R46: the CLI the live tests need comes first):

| # | Group | Model | Size |
|---|---|---|---|
| 1.1 | CLI framework on a headless `HubApi`: catalogue skeleton, parser (global flags anywhere, `bad_args` envelope), envelope, `hub/outcomes.py` with its precedence, exit codes, typed ids, `help` / `help --json`, `where`, app routing, `OpProblem`'s new keys; legacy routes to today's modules | Sonnet | ~230k |
| 1.2 | Job registry and worker (§6.2–§6.5): files, `alive`, liveness, the worker, inline `Jobs`, signals, the `CancelToken` stop file and sleep, `job …`, the wait defaults, live `person_steps`, the events writer | Opus | ~300k |
| 1.3 | Locks (§6.1): the support lock, `locks` per catalogue entry, rekordbox shared readers, `tools` refusal | Sonnet | ~180k |
| 1.4 | The window on the registry: window jobs registered, string job ids (contract), the registry watch, `JobFinished` for terminal jobs, the window files | Opus | ~260k |
| 1.5 | Live-test reads: `rekordbox status` / `preview`, `todo list`, `check list`, `track show`, `track find`, `upgrade list`, `batch list` / `show`, `run show`, with their text layouts | Sonnet | ~220k |
| 1.6 | Live-test writes A: `upgrade apply` / `discard` (with the upgrade dry run), `batch resume` / `undo`, `track undo`, `check done`; the plan store, `--plan`, `--yes` | Sonnet | ~230k |
| 1.7 | Live-test writes B: `aiff convert` / `rename`, `library facts`, `folder add` / `remove`, `library scan`, `settings set auto-upgrade`, `sync run --auto-upgrade-only`; the test scripts' marker and `--clean` | Sonnet | ~230k |
| — | **The A–D live tests of §15** with the user (an agent at the commands, the user at the **P** steps) | — | ~300k |

Phase 2, foundations: 2.1 the shape generator, schemas, generated `types.ts`, the contract doc reduced (Sonnet,
~200k); 2.2 the stored read and the derived plan, the window's Start bound to a plan id (Opus, ~280k); 2.3 the other
persisted state: sync scope, import state, `rev`, the drop's path, `keep_file`, the three dropped methods (Sonnet,
~230k); 2.4 shared protection, §7.5 (Opus, ~250k).

Phase 3, reads by area, each with its shapes, text layouts and parity (Sonnet ×4, ~220k each): library and track (the
rest, with the spectrum's text and PNG); sync, runs, `status`, `history`, `doctor`, `status --ready`; playlists, limits,
logins, setup, tools, app; `rekordbox match`, `library superseded`, `open …`, the limits picture.

Phase 4, writes by area (Sonnet ×4, ~220k each): the full `sync run` and the playlist writes; folders, import, tidy,
questions, duplicates; versions (on §7.5), hide, never; logins, settings, limits, tools, setup.

Phase 5, the guarantee tooling: 5.1 the word extraction, `fill()` on both sides, `help glossary` (Sonnet, ~200k); 5.2
the `derive` and `flows` rules with the seeded allow file (Opus, ~280k); 5.3 the rendered check, the blocks' `data-*`
attributes, mount coverage, the fake's schema validation (Opus, ~280k).

Phase 6, §9.3 into the engine: about 40 rows in six clusters of at most eight, by page (Library; To-do decisions and
upgrades; To-do checks, batches and AIFF; Sync; Limits and Playlists; Settings, Setup and the import). Each cluster is
two groups: the engine fields with shapes, tests and the fake (Sonnet, ~200k), then the window switched to them with
its `debt` entries removed and shots compared to `main` (Opus, ~280k). Twelve groups.

Phase 7, the sandbox and T9's sandbox cases (Opus, ~300k). Phase 8: the docs (AGENTS.md, the generated reference,
README, CONTRIBUTING, the CLAUDE.md rule, T11; Sonnet, ~180k), then an Opus whole-design review (~250k).

**Total:** 37 build groups, about 8.7 M tokens of building; with a Sonnet review per group (~110k), fix rounds
(~120k for about two groups in three), an Opus review at the end of each phase and the live tests, **about 17 M tokens
(between 14 and 20 M)**. Phase 6 is the largest part (about 5 M with its reviews): it is what makes today's ~115
window decisions engine answers. The plan agent restates the count and the total for the user before the build
starts.

---

## 17. MCP: later, not now

**Decision: no MCP server in issue 39.** The agents the user names (Claude Code, Codex) have a shell; the CLI with
`--json`, `help --json` and jobs gives them everything an MCP server would, and long runs are solved by jobs either
way (an MCP tool call times out just like a shell call). An MCP server now would be a second surface to keep complete.
Because every command comes from `hub/catalog.py` with a JSON Schema per payload and per argument set, an MCP
server later is a thin generated adapter (one tool per catalogue entry, `needs_yes` as a required boolean, jobs as
`job_wait` polling). Build it when a user wants an agent without a shell (Claude Desktop); note it in `docs/issues.md`
then.
