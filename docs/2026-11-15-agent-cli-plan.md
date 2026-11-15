# Discjockey's command line for agents and people: the build plan (issue 39)

Status: plan, 2026-11-15. Design: `docs/2026-11-14-agent-cli-design.md` (cited as §n). Phase 1 is planned in full;
phases 2–8 are a costed outline that a later run details after the user's go. The design stays as it is; where this
plan orders or splits differently from §16, it says why.

## 0. Summary for the user

| Phase | What it gives | Groups | Tokens (expected) |
|---|---|---|---|
| **1** | **The CLI slice the A–D live tests need, then the live tests** | **15 + live tests** | **≈ 5.3 M + 0.3 M** |
| 2 | The window on the job registry; payload shapes; stored read and derived plan; persisted state; shared Qobuz protection | 10 | ≈ 3.6 M |
| 3 | Every other read, by area | 7 | ≈ 1.9 M |
| 4 | Every other write, by area; the last legacy commands go | 8 | ≈ 4.0 M |
| 5 | The guarantee tooling (words, `derive`, `flows`, rendered check) | 5 | ≈ 1.7 M |
| 6 | §9.3: the window's ~115 decisions move into the engine | 12 (+2 optional) | ≈ 4.8 M (+0.5 M) |
| 7 | The sandbox | 3 | ≈ 2.0 M |
| 8 | Agent docs and the final review | 2 | ≈ 0.8 M |
| | **All** | **62 (+2)** | **≈ 24.4 M (21–31 M)** |

The design's §16 said about 17 M for 37 groups. This plan is larger for three measured reasons (§9): each group pays
~100k before it starts work, so groups that must stay under ~250k are more and smaller; the groups that write the
user's files, library.db, master.db or settings get their own review and a rehearsal on a copy; and the work the
design implied but did not place (the check steps, the plan store, selection, the rehearsal scripts, the test kit)
is placed and costed. §10 lists what costs much and adds little, with the saving of each.

---

## 1. Rules every group follows

### 1.1 What a group reads, and what it never reads

- CLAUDE.md, this plan's §1–§2 and its own group section, then the design sections and files its table names.
- `discjockey/hub/api.py` and `views.py` (about 150 KB each) are never read whole: `grep -n` for the method, then
  the line range. The same holds for `hub-ui/src/lib/bridge/fake/bridge.ts` and `docs/hub-bridge-contract.md`.
- "check first: …" in a group is a question the builder answers from the code before deciding; the answer goes into
  the commit message.

### 1.2 What every group leaves green (its stop point: "committed and green")

| Check | When |
|---|---|
| The touched tests (`uv run pytest -q tests/test_<x>.py`, `npx vitest run <file>`) | while working |
| The full Python suite once, `uv run pytest -q \| tail -3` | at the end of the group |
| `cd hub-ui && npm run check` and the touched vitest files | when the group touches `hub-ui/` |
| `npm run verify` | **never in a group**; once per phase branch before its merge, run by the coordinator in the background |
| `scripts/check_public.sh --require-denylist` | before every commit |
| The catalogue tests T1, T2, T3, T8 (from 1.1/1.2 on) | in the full suite |

A group ends with one commit (or a few) on its group branch, green, and reports its token size. It starts no
background process that outlives it; a test that starts a worker process reaps it (1.5).

### 1.3 The change rules

- **Contract:** a change to an answer of `api.py`, a `views.py` shape or a `jobs.py` event updates
  `docs/hub-bridge-contract.md`, `hub-ui/src/lib/bridge/types.ts` (+ `contract.ts`) and the fake in the same commit
  (CLAUDE.md). Additive optional keys need no fake change.
- **A command lands whole:** its catalogue entry (with an `example` line), its handler, its text layout, a `--json`
  test, an exit-code test, and a golden text file of its human page on the fixture library
  (`tests/cli_golden/<noun>_<verb>.txt`, a review aid for R30).
- **A legacy word leaves with all its callers:** the group that lands a replacement deletes the old handler and in
  the same commit updates every caller: tests, `scripts/rekordbox_rehearsal.py`, `scripts/make_upgrade_test.py`,
  CONTRIBUTING, CLAUDE.md (Layout rows and the Commands table), README. Nothing is kept for compatibility (H5).
- **Docs in phase 1:** 1.3 replaces CONTRIBUTING's "Commands for scripts and agents" (and its three stage sections)
  with a short section: grammar, envelope, exit codes, the job rules, "every command: `discjockey help <noun>
  <verb>`", and the `DISCJOCKEY_SUPPORT` / `DISCJOCKEY_REKORDBOX` rule. Later groups add no hand-written command
  shapes; the catalogue's `example` and `help` carry them until phase 8 generates `docs/agent-commands.md` (T11).
- **Invariants hold for commands:** the lock, never delete, moves only in batches, Qobuz protection, dry runs where
  the hub has one. No group adds a code path around them.

### 1.4 Models and sizes

- Sonnet for everything the design decided; Opus only for a new UI decision (one optional group in phase 6, 6.14) and for
  the one review per phase the brief allows.
- A group's expected size = ~100k (CLAUDE.md, this plan, notes) + 1.5 × its measured material + its work. Material is
  measured with `wc -c` / 4 (whole small files; for big files the targeted ranges named). Every group is planned under
  ~250k; the record says Sonnet groups land up to 1.5× their plan, so a group that passes ~300k is stopped at its
  next green commit and the rest goes to a fresh agent with the findings.

---
## 2. Interfaces fixed for phase 1

Names and shapes the groups share. A group that finds one of them wrong stops and reports; it never renames on its own.

### 2.1 Modules and where things live

| Module | Group | Holds |
|---|---|---|
| `discjockey/hub/outcomes.py` | 1.1 | `EXIT = {"ok": 0, "failed": 1, "bad_args": 2, "busy": 3, "needs_person": 4, "stopped": 5, "partial": 6, "refused": 7, "running": 8}`; `REASONS: dict[str, Reason]` (`Reason(outcome, text)`: the closed list of §4.3 with its words); `KIND_OUTCOME` (every `ProblemKind` → outcome, §4.3's bullet); `PRECEDENCE = ("bad_args", "busy", "refused", "needs_person", "stopped", "failed", "partial", "ok")`; `pick(outcomes) -> str`; `STEPS` (the §10.1 person steps phase 1 uses: `quit_rekordbox`, `relocate_new`, `reload_tag`, `folder_access`, `connect_drive`, with their `say` templates) |
| `discjockey/hub/ids.py` | 1.1 | `parse(text, kinds) -> Ident(kind, value)`, `fmt(kind, value) -> str`; `BadId(reason, message)` with `reason` `unknown_id` / `bad_id_kind`; kinds `track`, `file`, `aiff`, `moves`, `job`, `report`, `plan`, `folder`, `playlist`, `collection`; a bare number where a batch is meant is `bad_id_kind` with "say aiff:12 or moves:12" |
| `discjockey/hub/catalog.py` | 1.1 | `Entry`, `Arg`, `ENTRIES` (all 95 bridge methods + the phase 1 `cli_first` methods), `HOUSEKEEPING`, `WINDOW_ONLY`, `DROPPED` (§2.2 below) |
| `discjockey/cli/` (package; today's `cli.py` becomes it) | 1.2 | `__init__.main(argv) -> int`; `parser.py` (generated from the catalogue); `envelope.py`; `bind.py` (the headless `HubApi`); `call.py` (runs an entry: R and B directly, J/RJ through the job client); `render/` (`layout.py` + one module per noun); `legacy.py` (today's sync code and the routes to the old modules); `housekeeping.py` (1.3: `help`, `where`); `worker.py` (1.5); `follow.py` (1.6) |
| `discjockey/hub/registry.py` | 1.4 | the job registry (§2.4 below) |
| `discjockey/hub/plan_store.py` | 1.10 | dry-run plans in `<support>/plans/` (§2.5) |
| `discjockey/hub/select.py` | 1.10 | `select(listing) -> list[str]` (§7.3) |
| `discjockey/words.py` | 1.8 | the first data words the engine owns (§8.3): the check steps' words; later phases add to it |

Names that would clash: `api.py` imports `aiff_plan as plans`, hence `plan_store`; `discjockey/hub/jobs.py`'s `Jobs`
stays the in-process runner, `registry.py` is the cross-process record.

### 2.2 The catalogue entry

```
Entry(method: str, command: tuple[str, ...], kind: "R" | "RJ" | "J" | "J-control" | "B" | "W" | "dropped",
      locks: frozenset[str], needs_yes: bool, dry_run: str | None, partial: frozenset[str],
      params: Mapping[str, Arg], fixed: Mapping[str, object], cli_first: bool,
      planned: str | None, example: str, schema: str | None)
Arg(flag: str | None, positional: bool, type: str, many: bool, resolve: str | None)
```

- `planned` is `"phase N"` for an entry whose command is not built yet: T1 counts it as covered, the parser and
  `help --json` leave it out, and T2's last-phase form fails while any `planned` remains. So T1 holds from 1.1 on
  without a half-built parser; the count of `planned` entries only shrinks (a test pins the phase 1 ceiling).
- `fixed` binds arguments a command never takes from the user: `upgrade list` = `todo` with `fixed={"filter":
  "upgrade_ready"}`, `check list` = `todo` with `filter="rekordbox_check"`.
- `resolve` names the `HubApi.resolve` kind that turns what the user typed (a path, `last`, `folder:<path>`) into the
  method's argument; the CLI never looks anything up itself (T3).
- `locks` uses `library`, `support`, `rekordbox_w`, `rekordbox_r` (1.7 fills it for every built entry; T10).
- `schema` stays `None` in phase 1; phase 2 (shapes) fills it.

### 2.3 Answers and the envelope

- `OpProblem(message, kind, *, reason=None, next=(), person_steps=(), data=None)`; `hub.jobs.Busy`,
  `rekordbox.lock.Busy` and `library.LockHeld` carry the same four. `next` items are `{"run", "why"}`, person steps
  `{"id", "say", "then"}`.
- The `bridge` decorator keeps `{ok, kind, message}` (+ `service`, `setting`) and adds `outcome`, `reason`, `next`,
  `person_steps`, `data` on a problem (§4.3 bullet; optional keys in `types.ts`'s `Fail`).
- `discjockey/cli/envelope.py`: `envelope(command, outcome, *, reason=None, message=None, data=None, next=(),
  person_steps=(), recovered=(), job=None, as_of=None, sandbox=None) -> dict`, keys in §4.1's order, `v: 1`;
  `recovered` always a list. With `--json` stdout holds exactly this object, for a usage error and a crash too.
- `HubApi` gains, as `cli_first` methods in phase 1: `freshness()` (`{scanned_at, read_at}` for `as_of`, 1.3),
  `resolve(kind, values)` (1.2; kinds grow per group), `find_tracks(words=None, path=None)` (1.8),
  `rekordbox_preview(track_id=None, path=None)` and `batches(kind=None, limit=20)` / `batch_detail(batch)` (1.9),
  `select(listing)` and `upgrade_preview(track_ids, mode, all)` (1.10), `fill_facts()` (1.12),
  `auto_upgrade_preview()` / `auto_upgrade_run()` and `settings_view()` (1.13).

### 2.4 The job registry (1.4) and the worker (1.5)

```
registry.new_job_id() -> "job:<8 hex>"
Registry(support).create(kind, command, args, via, roots) -> JobFiles      # state.json "queued"
JobFiles: .id .dir .state() .update(**fields) .alive() (context: holds the flock)
          .is_alive() (one LOCK_SH|LOCK_NB try) .events() (writer thread; .emit(event))
          .write_result(envelope) .request_stop() .stop_requested() .set_person_steps([...])
Registry.list(music=None, all=False) -> [state]   Registry.get(id) -> JobFiles   Registry.prune(now)
CancelToken(stop_file: Path | None = None)        # cancelled = event set or the file exists (stat ≤ every 0.5 s)
Jobs(lock, emit, *, inline: JobFiles | None = None, ...)   # inline: adopt the id, run on the calling thread
```

`state.json` fields are §6.2's list; `roots` = `{music, support, rekordbox, sandbox}` (sandbox always null in phase
1). Status order at the end: `result.json`, then `status: done`, then the `alive` lock released (§6.3 step 5).

### 2.5 Plans (1.10)

`plan_store.save(support, kind, root, items, extra) -> "plan:<12 hex>"` (hash of kind, root and the sorted item keys;
the same dry run twice gives the same id); `plan_store.load(support, plan_id, root) -> Plan` raises `UnknownPlan`
(→ `bad_args`, `unknown_id`) or `PlanExpired` (older than 24 h, or another root → `refused`, `plan_expired`, `next`:
the dry run). Pruned at each save. Bridge methods that take a plan gain `plan_id: str | None = None` (T1 maps it to
`--plan`): `upgrade`, `upgrade_all`, `convert`, `rename`, `make_aiff`, `auto_upgrade_run`. A run with a plan runs only
its items; an item whose answer changed is `skipped`, `reason: "changed"`; an item new since the plan is listed in
`data.new_since_plan` and left out.

---
## 3. Phase 1 in full: the CLI slice the live tests need

Branch `feat/cli-1-live-slice`; group worktrees `.claude/worktrees/cli1-<n>` on `feat/cli-1-<n>`; one group at a time,
in this order. Each table row "Material" is measured (`wc -c` / 4) on the files and targeted ranges named.

**Reorder against §16, and why.** The design's group 1.4 (the window on the registry: window jobs registered, the
registry watch, `JobFinished` for terminal jobs, the window files, the banner words) moves to phase 2 (2.1, 2.2). The
live tests don't use the window, and while a terminal job runs today's 3-second lock probe still switches the window's
writes off and shows its banner, so nothing is unsafe meanwhile; phase 1 then changes no screen, needs no shots pass,
and reaches the live tests one window group (~380k with its shots pass) sooner. The string job ids, a contract change
the registry needs at once, stay in phase 1 (1.4). `where.windows_open` arrives with the window files in 2.1 (until
then the key is absent; adding it later is additive within `v: 1`).

### 1.1 Outcomes, ids and the catalogue

| | |
|---|---|
| Goal | The engine's answer carries outcome, reason, next and person steps; typed ids; the catalogue of all 95 bridge methods |
| Design | §3, §4.3, §5.2, §8.1 (catalogue, outcomes), §10.1 (the phase 1 steps), §13 T1 and T8 |
| Touches | new `hub/outcomes.py`, `hub/ids.py`, `hub/catalog.py`; `ops.py` (`OpProblem`), `hub/jobs.py` (`Busy`, `problem_of`), `rekordbox/lock.py`, `library.py` (`LockHeld`), `hub/api.py` (`bridge` decorator), `types.ts` (`Fail` optional keys), `hub-bridge-contract.md` (the problem section); tests `test_hub_outcomes.py`, `test_hub_ids.py`, `test_hub_catalog.py` |
| Reads | `ops.py` 5k (OpProblem region), `jobs.py` 10k (lines of `Busy`, `problem_of`, `hub_message` only, ~2.5k), `api.py` `bridge` + `LIBRARY_METHODS` + the method list (`grep -n "@bridge" -A2`, ~4k), `rekordbox/lock.py`, `test_hub_dispatch.py`, `contract.ts`, the contract doc's problem part (~3k), the design sections (~8k) |
| Material | ≈ 28k |
| Model, size | Sonnet, ≈ 215k |
| Green | touched tests, full pytest, `npm run check` + `contract.test.ts` |

Behaviours to pin:

| Test | Pins |
|---|---|
| T1 | every `@bridge` method of `HubApi` has an entry; every built entry maps every parameter (and the keys of a dict parameter's `TypedDict` when it has one) to a flag or positional or a `fixed` value; `WINDOW_ONLY` reasons ⊂ {`native_dialog`, `closes_window`}; `DROPPED` = {`media_url`, `select`, `setup_check_account`}; the `planned` count ≤ the phase 1 ceiling the test names |
| T8 (engine half) | every `ProblemKind` in `types.ts`'s `PROBLEM_KINDS` has a `KIND_OUTCOME` row (the test reads the TS list); every `REASONS` key belongs to one outcome; `pick` follows `PRECEDENCE` for every pair |
| ids | each kind round-trips `fmt` → `parse`; a bare `12` for a batch is `bad_id_kind` with "say aiff:12 or moves:12"; a track key passes as is (`local:<n>`, `qobuz:…`, a bare Spotify id) |
| bridge | a refused `OpProblem` with `reason` and `next` answers `{ok: false, kind, message, outcome: "refused", reason, next, person_steps: [], data: null}`; `Busy` answers `outcome: "busy"`; a crash answers `failed`, `crashed`; an `ok` answer is unchanged |

Check first: whether any `ProblemKind` the window uses is raised under another name in Python (grep `OpProblem(`'s
kinds against `PROBLEM_KINDS`); a kind that exists only on one side is a finding for the commit message, mapped, never
dropped.

### 1.2 The CLI adapter on a headless HubApi

| | |
|---|---|
| Goal | `discjockey/cli/` package: the parser generated from the catalogue, global flags anywhere, the envelope, exit codes, the text-page framework, the headless `HubApi`, the R and B call path, legacy routes; the first read end to end: `rekordbox status` |
| Design | §2.2, §4.1, §4.2, §8.1 (CLI adapter, T3), §12 (the legacy rows) |
| Touches | `discjockey/cli.py` → `discjockey/cli/` (today's sync code moves unchanged into `cli/legacy.py`), `__main__.py`, new `cli/{parser,envelope,bind,call}.py`, `cli/render/{layout,rekordbox}.py`; `test_cli.py` split into `test_cli_legacy.py` (today's sync tests, imports moved) and `test_cli_frame.py`; T2, T3 |
| Reads | `cli.py` 4.4k, `rekordbox_cmd.py` 1.7k (the status lines to port), `hub/app.py` 2.1k (how `main` binds), `api.py` `__init__`/`_bind`/`_attach` (~2k), `test_cli.py` 11.7k, `bin/discjockey`; 1.1's modules (~5k); design (~4k) |
| Material | ≈ 31k |
| Model, size | Sonnet, ≈ 230k |
| Green | touched tests, full pytest |

Decisions:
- **Headless bind:** `cli/bind.py` `headless(resolved) -> HubApi` builds `HubApi(support, events=None)` and calls
  `_attach(paths)` only (no console watch, no playlists watch, no drives watch, no media server); no music folder is
  not an error at bind time (reads that need one answer `refused`, `no_library` through `LIBRARY_METHODS`).
- **Headless writes act on the record as it is now** (§3 "a command without it acts on the record as it is now"):
  `HubApi(…, remember=False)` makes `_single` and `_each_work` skip the `_shown` check. Phase 2 (2.8) replaces both
  with `rev`; until then the window path is unchanged.
- **Routing:** the parser tries the catalogue first; a (noun, verb) without a built entry whose first word is a legacy
  word (`setup`, `update`, `upgrades`, `upgrade`, `batch`, `convert`, `rename`, `rekordbox`, `settings`, `hub`, or a
  leading sync flag `--dry-run` / `--yes` / `--limit` / `--extra` / `--json` / `--verbose`) is handed unchanged to the
  old parser in `cli/legacy.py`. Per (noun, verb): `rekordbox status` is new now, `rekordbox preview` stays legacy until
  1.9. The legacy output keeps its old shapes until its replacement lands.
- **Text pages:** `render/layout.py` `Page(headline, sections=[Section(heading, rows=[Row(label, value)])])`; ids,
  `rev` and raw numbers that have words print only with `--verbose`; progress and notices to stderr; `--no-color`,
  `NO_COLOR`.

| Test | Pins |
|---|---|
| T2 | every built entry's command parses; every parser command has a built entry or is housekeeping or a legacy route |
| T3 | an AST check: a handler module in `cli/` calls only the `HubApi` methods its entries name, `HubApi.resolve`, and the housekeeping modules; no handler indexes into `state`, opens `library.db` or imports `views` |
| global flags | `--json upgrade list`, `upgrade --json list`, `upgrade list --json` give the same; a flag a command doesn't take is `bad_args`, `usage`, exit 2, one JSON object |
| crash | an exception in a handler prints one `failed`/`crashed` envelope with `--json` and exit 1 |
| first read | `rekordbox status --json` on the fixture (`make_master`) equals the bridge's `rekordbox_status()` minus `ok`, inside `data`; no music folder → still answers (it needs none) |
| legacy | `discjockey --dry-run --json` (the sync), `batch list --json`, `convert … --dry-run` still give their old answers |

### 1.3 Discovery and the app binary

| | |
|---|---|
| Goal | `help`, `help --json`, `help <noun> [<verb>] [--json]`, `where`, the envelope's `as_of`; the app routing of §2.1 with `app open`; the self-test round trip; CONTRIBUTING's new short section |
| Design | §2.1, §2.3, §4.1 (`as_of`), §10.2, §13 T12 |
| Touches | `cli/housekeeping.py`, `app_main.py` (drop `CLI_COMMANDS`), `selftest.py`, `bin/discjockey` (`app open` runs without `caffeinate`, as `hub` did), `HubApi.freshness()`, CONTRIBUTING (§1.3 above), CLAUDE.md (Commands table: `bin/discjockey hub` → `app open`; the `app_main` Layout row) |
| Reads | `app_main.py`, `selftest.py` 2.9k, `test_app_main.py`, `test_selftest.py` 3.4k, `library.resolve_paths` (~1.5k), CONTRIBUTING lines 26–326 (6.2k: what to keep), design (~2k) |
| Material | ≈ 24k |
| Model, size | Sonnet, ≈ 200k |
| Green | touched tests, full pytest |

Decisions: launchd start = parent pid 1 or a single `-psn_…` argument; `--check-tools` and `--self-test` keep their
places; no argument from a shell prints the short help and exits 0 (its first line: "AI agents: run `<path> help
--json` first."; 8.1 changes it to `help agents` when the guide exists, so no line names a command that isn't there);
`hub` stays a legacy route only until this group lands `app open`. `where` prints §2.3's fields minus `windows_open`;
`jobs_running` arrives with 1.4.

| Test | Pins |
|---|---|
| T12 | `app_main.main([])` with a shell parent prints the help and exits 0, never imports `webview`; with parent pid 1 or `-psn_123` it opens the hub (stubbed); `app open` opens it from a shell; any other argument reaches `cli.main` |
| self-test | the round trip runs `help --json` and `where --json` in its scratch support folder and checks `v`, `outcome`, `data.command` |
| `help --json` | lists every built entry with args, flags, `writes`, job kind, reasons; no `planned` entry |
| `where` | resolves exactly as `library.resolve_paths` (`DISCJOCKEY_SUPPORT` honoured), `music.state` `ok` / `missing` / `not_chosen` |

### 1.4 The job registry and string job ids

| | |
|---|---|
| Goal | `hub/registry.py` (§2.4) and the `CancelToken` stop file; every job id becomes `job:<8 hex>`, the window's too |
| Design | §6.2, §6.4 (the stop file, `sleep` in ≤ 0.5 s steps), §6.5 (live person steps) |
| Touches | new `hub/registry.py`, `events.py` (`CancelToken`), `hub/jobs.py` (`Job.id`, `JobContext.job_id`, `JobStarted` / `JobFinished` ids, `new_job_id`), `api.py` (`stop`, `job_status` ids); `types.ts`, `contract.ts`, the fake's job ids, `stores/hub.ts`, `stores/run.ts`, `stores/jobs.ts` and the other id users (`grep -rn "job_id\|jobId" hub-ui/src`), the contract doc; `where.jobs_running` |
| Reads | `events.py` 1.8k, `jobs.py` (`HubEvents`, `_same_slot`, `event_dict`, `Job`, ~3k), `library.write_json_atomic`, `test_events.py`, `test_hub_events.py`, the hub-ui id users (~6k targeted), design (~1.5k) |
| Material | ≈ 21k |
| Model, size | Sonnet, ≈ 210k |
| Green | touched tests, full pytest, `npm run check` + the touched vitest files |

| Test | Pins |
|---|---|
| liveness | a job whose `state.json` says `running` and whose `alive` lock is free is `lost` (the reader rewrites `status: lost`), even when its recorded pid is the test's own (pid reuse) |
| events | 5 000 `Progress` events in a burst write ≤ 2 lines a second per slot (`_same_slot`); the file keeps the first 2 000, a `Truncated {skipped}` marker, and a rolling `events.tail.jsonl` of 10 000 |
| retention | the newest 100 or 30 days stay; a job whose `alive` is held is never pruned |
| stop | `CancelToken(stop_file)` reports `cancelled` within 0.5 s of the file appearing; `sleep(60)` ends within 1 s of it |
| ids | `JobStarted.id` is a string matching `^job:[0-9a-f]{8}$`; the fake's ids have the same form; vitest's job-store tests pass with strings |

### 1.5 The worker

| | |
|---|---|
| Goal | A write job runs in its own process that outlives the client: `job _worker <id>`, the headless `HubApi` from `state.json`'s roots, `Jobs` inline on the main thread, signals, `--wait-busy`; the first write end to end: `library scan` |
| Design | §6.3 (steps 1–5), §6.1 (write job's library lock), §2.1 (`caffeinate -i -w <pid>`) |
| Touches | `cli/worker.py`, `cli/call.py` (J path: create the job, spawn the worker), `hub/jobs.py` (`Jobs(inline=…)`), `api.py` (`rescan_library` reached from the catalogue), the catalogue entry `library scan` |
| Reads | `jobs.py` `Jobs` (~6k of 10k: `start`, `_run`, `_finish`, `lock_briefly`), `library.deferred_interrupt` + `run_lock` (~2k), `batch_cmd._interruptible` and `cli/legacy._ctrl_c` (~1.5k), 1.4's registry (~5k), `test_hub_jobs.py` 5k, design (~1k) |
| Material | ≈ 20k |
| Model, size | Sonnet, ≈ 230k — the riskiest group of the phase (§11) |
| Green | touched tests, full pytest; `ps` shows no `job _worker` left after the suite |

Decisions:
- Spawn: `subprocess.Popen([sys.executable, "-m", "discjockey", "job", "_worker", id], start_new_session=True,
  stdin=DEVNULL, stdout=DEVNULL, stderr=<log.txt>)`; in the app binary the same through `sys.executable` (frozen:
  the app's own program). A write job's worker starts `caffeinate -i -w <own pid>` itself.
- The worker reads only `state.json` for its roots and args, never its environment (§6.3 step 2).
- `Jobs(inline=files)` adopts `files.id`, takes the kind's locks on the calling (main) thread, sends events to
  `files.events()`, and returns after `JobFinished`; the method's `{job_id}` answer is then followed by the result.
- Held library lock: without `--wait-busy` the worker writes the `busy` envelope (`data.holder` from the registry's
  running job, else `{via: "unknown"}`) and ends; with it, it retries every 2 s until the deadline.
- Signals: first SIGINT cancels the token; a second one ≥ `CTRL_C_REPEAT_S` later raises `KeyboardInterrupt` (still
  held back by `deferred_interrupt`); a sooner repeat is ignored. `CTRL_C_REPEAT_S` moves to `events.py`, one copy.

| Test | Pins |
|---|---|
| T10 worker | a worker started for `library scan` on a fixture library writes `running`, holds `alive`, ends `done` with `result.json` before releasing `alive`; killing the parent test client leaves it running and finishing |
| roots | a worker started with `DISCJOCKEY_SUPPORT` pointing elsewhere still uses `state.json`'s support folder |
| busy | two workers for writes at once: one `running`, one `busy` (exit 3 in its envelope); with `--wait-busy 5` the second runs after the first ends |
| signals | SIGINT once → `stopped`, `reason: "stop"`; twice 1.1 s apart → `stop_now`; twice 0.2 s apart → as once |
| lost | a worker killed with SIGKILL is `lost` on the next read; `recover_pending` runs at the next write as today |

Check first: how a frozen app (PyInstaller) starts a child of itself (`sys.executable` is the app's program; the
`-m` form does not exist there): the worker argument list differs between checkout and app; pin both in a test of
`call.worker_argv()`.

### 1.6 The job client and the `job` noun

| | |
|---|---|
| Goal | Following, waiting and stopping from any process: the default waits, `--detach`, `--wait S`, the first stderr line, `--jsonl`, Ctrl-C in an attached client, `job list / show / follow / wait / stop [--now]` |
| Design | §6.4, §6.5, §4.1 (`--jsonl`), §4.3 (`running`, exit 8; `not_running`; `window_job`; `worker_lost`) |
| Touches | `cli/follow.py`, `cli/call.py`, `cli/render/job.py`; the `job` entries in `HOUSEKEEPING` |
| Reads | `console.py` 1.9k (today's progress lines, reused for text follow), 1.4/1.5's modules (~8k), `cli/legacy._ctrl_c` (~1k), design (~1.5k) |
| Material | ≈ 12k |
| Model, size | Sonnet, ≈ 210k |
| Green | touched tests, full pytest; no worker left (`ps`) |

| Test | Pins |
|---|---|
| defaults | stdout a TTY: follow to the end; not a TTY: `--wait 90` (the test uses a short override through an env var the worker ignores); `--wait 1` on a long fake job → `running`, exit 8, `job` set, progress and live `person_steps` in `data` |
| detach | returns once the worker is `running` or ended (a `busy` envelope included), at most `--wait-busy` + 5 s later |
| first line | the first stderr line is `Job job:… started (follow: <path> job follow job:…)` before anything else |
| follow | `job follow` text = today's console progress lines; `--jsonl` = one event per line then the envelope; `--from-end` starts at the tail |
| wait | `job wait` on an ended job prints its own envelope and exit code; on a `lost` one `failed`, `worker_lost`, `next: job show <job> --log` (3.4 adds `doctor` to it) |
| stop | `job stop` writes the stop file and answers `ok`, `data.status: stopping`; an ended job → `refused`, `not_running`; `current` = the one running write job of this music folder |
| --now | sends SIGINT twice ≥ 1 s apart only while `alive` is held **and** the pid's start time (`proc_pidinfo` through `ctypes` on libproc) equals `pid_started`; a lost job gets no signal |
| Ctrl-C | an attached client's first Ctrl-C writes the stop file, a second ≥ 1 s later asks for `--now` |

### 1.7 Locks across processes (own review + rehearsal)

| | |
|---|---|
| Goal | The support lock; rekordbox readers on a shared, non-blocking `rekordbox.lock`; the `locks` column of every built entry; `tools update/rollback` refused while a write job runs |
| Design | §6.1 |
| Touches | new `library.support_lock(support)` (flock on `<support>/.support.lock`, ≤ 2 s, then `Busy` `support_lock`); `settings.save`, `config.json` writes, the login file writes, `tool_updates` (around their read-change-write; `_settings_mutex` stays in front); `rekordbox/lock.py` (`reader_lock()`: `LOCK_SH \| LOCK_NB`; `writer_lock` retries ≤ 2 s); `api._rekordbox_status` (answers `writing` with its last cached answer and `as_of` while a writer holds it, instead of the in-process rule); `api.update_tools` / `rollback_tools` (registry check) |
| Reads | `settings.py` 3.1k, `rekordbox/lock.py`, `rekordbox/master.py` 3k (the open), `tool_updates.py` 5.3k (targeted ~2k), `test_settings.py` 3.3k, `test_rekordbox_session.py`, `api.py` `_settings*` users and `_rekordbox_status` (~4k), `jobs.lock_briefly` (~1k), design §6.1 |
| Material | ≈ 23k |
| Model, size | Sonnet, ≈ 200k |
| Green | touched tests, full pytest |
| Review | own Sonnet review (it changes how settings, config and logins are written); rehearsal: on a scratch support folder holding a copy of the real `settings.json` (no login files), two processes save settings at once and a fixture rekordbox writer runs while a reader reads |

| Test | Pins |
|---|---|
| T10 locks table | for every built entry, the locks it takes equal its `locks` column (a fake lock layer records them) |
| support lock | two processes doing a read-change-write of `settings.json` at once lose neither change; a holder for > 2 s makes the other answer `busy`, `support_lock` |
| rekordbox readers | while a (fake) writer holds `rekordbox.lock`, `rekordbox status`, `todo` and `track` never open master.db and answer `writing` with `as_of`; a reader's shared hold never makes a writer `Busy` (the writer's 2 s retry) |
| tools | `tools update` while a registry write job runs → `busy`; it takes no library lock |

### 1.8 Reads I: To-do, tracks and checks

| | |
|---|---|
| Goal | `todo list [--group G] [--hidden]`, `upgrade list`, `check list`, `track show`, `track find`; the check's person steps in the engine; the parity test |
| Design | §3 (finding ids, `rev` later), §4.2, §5.2 rows `todo`, `track`, §10.1 (the check steps), §13 T4 (parity half) |
| Touches | catalogue entries (`todo` with `filter`→`--group` (one value in phase 1), `show_hidden`→`--hidden`; `upgrade list` and `check list` as `todo` with `fixed`); `HubApi.find_tracks` (artist/title folded as `views.library` folds its query; `--path` absolute or relative to the music folder); `HubApi.resolve("track", …)` for paths; `views.check_view` gains `person_steps`; new `discjockey/words.py` with the steps' words; `render/todo.py`, `render/track.py`; the contract doc + `types.ts` (`check.person_steps`, optional) |
| Reads | `api.py` `todo`, `_todo`, `track` (~4k), `views.py` `todo`, `track_detail`, `check_view` (~8k), `report.check_text` (~1k), hub-ui `decisions/decisionModel.ts`'s check-card helpers (~3k: the words the window shows), `test_hub_api.py` (~2k targeted), `hub_helpers.py` 3.2k, design (~3k) |
| Material | ≈ 25k |
| Model, size | Sonnet, ≈ 225k |
| Green | touched tests, full pytest, `npm run check` |

Decisions:
- `check.person_steps` (one per check): an added file (New track) → `step:relocate_new` with the new file's path; a
  swap, Same track or Convert → `step:reload_tag`; `say` is the engine's own sentence (`report.check_text`), `then`
  `check done <track>`. Phase 6 splits it into the numbered steps of §10.1 and removes the window's copy. Check
  first: whether `report.check_text` says everything the window's numbered steps say (the USB step); a missing step
  is added to `check_text`, never to the CLI.
- An upgrade result for one track (`New track`) carries the same `person_steps` (A 3e).
- `find_tracks` answers `{rows: [{track_id, artist, title, path, rel_path}], total}`; `track find` with no hit: `ok`, `data.total: 0`, `as_of.read_at`, and `next: sync read` when the read is older than a
  day (R28).

| Test | Pins |
|---|---|
| T4 parity | for `todo`, `track`, `upgrade list`, `check list` on the hub fixtures: the bridge answer minus `ok` and the URL keys equals the command's `--json` `data` |
| person steps | a New track check gives `step:relocate_new` with the absolute new path; a Same track check `step:reload_tag`; both `then` `check done <track>` |
| find | words fold like the Library search (`"Beyonce"` finds `Beyoncé`); `--path` finds the song holding the file; `track show <path>` resolves through `resolve` |
| text | each page places the window's headings (the To-do group names, the track's sections) and the `auto_waits` mark as words |

### 1.9 Reads II: rekordbox, batches and reports

| | |
|---|---|
| Goal | `rekordbox preview` (entry columns and master.db facts of C7), `batch list` / `batch show` for both kinds with typed ids, `report show <report\|last>`; `rekordbox_cmd.py` deleted |
| Design | §5.2 rows `rekordbox_status`, `move_batches`, `run`; §5.3 (`rekordbox preview`'s new columns); §3 (`aiff:`, `moves:`, `report:`) |
| Touches | `HubApi.rekordbox_preview` (wraps `rekordbox/preview.py`; gains per entry `folder_path`, `content_file`, `updated_at`), `rekordbox_status` gains `modified_at`, `size` of master.db (C7) and the console's richer answer (`problem`, `version`); `HubApi.batches(kind, limit)` (AIFF and move batches in one newest-first list), `batch_detail(batch)`; `HubApi.run` accepts `last`; `render/rekordbox.py`, `render/batch.py`, `render/report.py`; delete `rekordbox_cmd.py` and its legacy route; contract doc + `types.ts` for the additive status keys |
| Reads | `rekordbox/preview.py` 2.8k, `rekordbox_cmd.py` 1.7k, `master.Status` (~1k), `db.aiff_batch*` and the move-log batch queries (~3k), `batch_cmd` list/show (~2k), `api.py` `move_batches`, `run`, `runs` (~2k), `views.run_detail` (~2k), `test_rekordbox_preview.py` 3.3k, design (~2k) |
| Material | ≈ 19k |
| Model, size | Sonnet, ≈ 210k |
| Green | touched tests, full pytest, `npm run check` |

| Test | Pins |
|---|---|
| preview | `rekordbox preview --path <fixture mp3> --json` has `timing.offset_samples` and `entries[].offset_ms`, `folder_path`, `content_file`, `updated_at`; a file the library doesn't know still gets the rekordbox part |
| status | `modified_at` and `size` match the fixture master.db's `stat` |
| batches | `batch list` shows `aiff:<n>` and `moves:<n>` rows newest first with `kind`, `state`, counts; `batch show aiff:<n>` has each item's paths and `rekordbox.entries/kept`; `batch show 3` is `bad_args`, `bad_id_kind` |
| report | `report show last` = the newest report's run detail; `report:<id>` round-trips |
| T4 parity | the same check as 1.8 for these reads |

### 1.10 Dry runs, plans and selection

| | |
|---|---|
| Goal | The plan store and `--plan`; `--yes` / `needs_yes`; read-only dry runs; `HubApi.select(listing)` for `--all` and `--rows`; `upgrade_preview` (Upgrade all's and a selection's dry run) |
| Design | §7.1, §7.2, §7.3, §13 T9 (dry-run half) |
| Touches | `hub/plan_store.py`, `hub/select.py`, `HubApi.select`, `HubApi.upgrade_preview` (moves `batch_cmd._dry_run` / `_plan_row` / `_space` into the engine, beside `batches`), `cli/call.py` (`--dry-run`, `--plan`, `--yes`, the selection flags, `-` from stdin), `db.connect(read_only=True)` (`file:…?mode=ro`) used by every read path of `HubApi` and by dry runs; `library.open_state(read_only=True)` |
| Reads | `db.connect` (~2k), `library.open_state` (~1k), `batch_cmd` dry run (~3k), `views.library` + `_matches` + the To-do grouping (~4k), `api.library` / `todo` signatures (~2k), `run.select_actions` (~1k), `test_aiff_plan.py` (~2k targeted), design (~3k) |
| Material | ≈ 18k |
| Model, size | Sonnet, ≈ 220k |
| Green | touched tests, full pytest |

Decisions:
- `select(listing)`: `listing = {source: "library" | "todo", in, group, search, quality, verb_all}`; `--rows` = every
  row that listing shows (filter and search applied, `also` rows included, rows without a file left out); `--all` =
  the verb's own "all" (the catalogue names it per entry). The window's ⌘A keeps its own code until phase 6 (L D15);
  T4's ⌘A half lands there.
- `needs_yes` without `--yes`: `refused`, `needs_yes`, `message` = the window's question (the words live beside the
  catalogue entry until phase 6 moves them into `confirm`), `data` = the dry run.
- Read-only opens: check first: SQLite's rules for `mode=ro` on a WAL database (it needs the `-shm` or a writable
  folder); when the `-wal`/`-shm` are absent, the read opens `?mode=ro` all the same and a test pins that no
  `-wal`/`-shm`/`library.db` file appears where none was.

| Test | Pins |
|---|---|
| T9 (phase 1 commands) | every `--dry-run` of a built entry on the fixture library changes no byte outside `<support>/plans/` and `<support>/cache/` (all files, library.db, the rekordbox fixture compared) |
| plans | the same dry run twice → the same `plan_id`; `--plan` of another music folder or older than 24 h → `refused`, `plan_expired`, `next` = the dry run; unknown → `bad_args`, `unknown_id`; an item changed since → `skipped`, `changed`; a new one → `new_since_plan` |
| selection | `--rows --in folder:<path>` = the ids `library list --in folder:<path>` prints; `-` reads ids one per line or as a JSON array; exactly one of ids / `--all` / `--rows` (else `bad_args`, `conflicting_flags`) |
| upgrade dry run | `upgrade apply --all --dry-run` lists what Upgrade all would run (the To-do group's `same_track is None` set), per item `planned`/`skipped` with reason, space per drive, rekordbox `needs_closed` |

### 1.11 Writes A1: upgrades, track undo, checks (own review)

| | |
|---|---|
| Goal | `upgrade apply`, `upgrade discard`, `track undo`, `check done`, on the plan store and selection of 1.10 |
| Design | §5.2 rows `upgrade`, `upgrade_all`, `undo_upgrade`, `rekordbox_checked`; §4.3 (R24 `partial`, R29 nothing to do = `ok`); §4.4; §7.2; §7.4; §12 (`--way` words, mode enum) |
| Touches | catalogue entries with `partial` states and `needs_yes` (`upgrade discard`, `track undo`); `api.upgrade(track_ids, mode, plan_id=None)` with the mode enum `same_track \| new_track \| discard` (contract change: `types.ts`, the fake, every hub-ui caller of `upgrade(`, the contract doc); `api.upgrade_all(plan_id=None)`; `api.rekordbox_checked(track_ids, batch_id=None)`; `track undo --dry-run` from `upgrades.can_undo`; the outcome rows (`rekordbox_open` → `needs_person` with `step:quit_rekordbox` and `then` = the same command, or `batch resume aiff:<n>` when a batch stopped); `render/upgrade.py`, `render/check.py` |
| Reads | `api.py` `upgrade`, `upgrade_all`, `_each_work`, `_batch_work`, `_undo_work`, `rekordbox_checked`, `undo_upgrade` (~5k), `batch_cmd` apply/discard/undo/checked (~5k), `test_batch_cmd.py` (~6k targeted), `test_hub_api_batches.py` 4k, hub-ui callers of the mode (`grep -rn "'swap'\|add_new" hub-ui/src`, ~3k), design (~4k) |
| Material | ≈ 27k |
| Model, size | Sonnet, ≈ 210k |
| Green | touched tests, full pytest, `npm run check` + touched vitest |
| Review | own Sonnet review; its rehearsal runs with 1.12's (below) |

Decisions: in phase 1 `--way` is required for named tracks (`bad_args` without it); `--all` means Same track
(`--all --way new-track` → `bad_args` with the window's reason). Phase 6 (the L D8 row) adds `upgrade.ways[]` with
`recommended` and makes `--way` optional (C5).

| Test | Pins |
|---|---|
| apply | `upgrade apply <t> --way new-track --plan P` runs only P's item; the result has `person_steps` (`step:relocate_new`, 1.8); `--way same-track` on three tracks is one AIFF batch `aiff:<n>` |
| outcomes | a batch with one skip ends `partial`, exit 6, never `ok` with exit 1; `--all` with nothing left → `ok`, `data.total: 0`, the window's message; rekordbox open before the batch of one named track → `needs_person`, exit 4, the batch closed, `next` names no resume |
| yes | `upgrade discard <t>` and `track undo <t>` without `--yes` → `refused`, `needs_yes`, nothing changed, `data` = the dry run |
| check | `check done <t>` ends the check and its undo (the `message` says so); `--batch aiff:<n>` checks that batch's tracks; a track with nothing to check is `skipped`, not an error |

### 1.12 Writes A2: batches, backups, legacy removal (own review + rehearsal)

| | |
|---|---|
| Goal | `batch resume aiff:<n>`, `batch undo aiff:<n> --yes` (with `--dry-run`), `rekordbox backups`, `rekordbox restore <backup> --yes` (with `--dry-run`); batches record `via` and their real scope; `batch_cmd.py` and `upgrades_cmd.py` deleted |
| Design | §5.2 rows `batch_resume`, `batch_undo`; §6.6 "Who sees whose batches"; §7.4; §12 (`console` scope dropped, `upgrade undo` → `track undo`, `rekordbox checked` → `check done`) |
| Touches | `db.py` schema 10: `via` (`window` \| `terminal`) on `aiff_batches` and on the move log's batches (one bump for both; move batches get their commands in phase 4); `batches.start(…, via=…)`; scopes from the selection form (`selection`, `library:<view>[:<key>]`, `todo:cdj`); `views.stopped_batch` reads the real scopes, so the window's Resume shows terminal batches; `api.batch_resume/batch_undo` take the typed id through `resolve`; `rekordbox_backups()` / `rekordbox_restore(backup, dry_run)` as `cli_first` methods; delete `batch_cmd.py`, `upgrades_cmd.py`, their tests and legacy routes; `scripts/rekordbox_rehearsal.py` (`rehearse`: the new `upgrade apply`, `batch undo aiff:<n> --yes`, the envelope's `data`), README (the restore advice, lines ~810), CLAUDE.md (the `batch_cmd.py` row goes; `batches.py`'s "console" words) |
| Reads | `batch_cmd.py` (resume/undo/backups/restore, ~5k), `batches.py` (`start`, `close_unrun`, ~3k), `db.py` schema and the batch tables (~4k), `rekordbox/backup.py` 3.6k, `upgrades_cmd.py` 2.2k + its test 3.7k, `test_batch_cmd.py` (~6k), `rekordbox_rehearsal.py` (`rehearse` and `discjockey()`, ~5k targeted), design (~2k) |
| Material | ≈ 35k |
| Model, size | Sonnet, ≈ 215k |
| Green | touched tests, full pytest, `test_rekordbox_rehearsal_safety.py` |
| Review | own Sonnet review; **rehearsal on a copy** for 1.11 and 1.12 together: `rekordbox_rehearsal.py copy-db` / `copy-tracks` / `rehearse` on a copy of the user's rekordbox library (rekordbox closed; never the real library), all checks PASS |

| Test | Pins |
|---|---|
| resume/undo | a stopped batch resumes its `planned` items; `batch undo aiff:<n> --yes` with rekordbox open undoes nothing, `needs_person`, `step:quit_rekordbox`, exit 4; `--dry-run` lists per item whether it can be undone and why not |
| via, scope | a batch started by a command records `via: terminal` and its selection's scope; the window's Resume link shows a stopped terminal batch of a Library view |
| restore | without `--yes` → `needs_yes`; with rekordbox open → `needs_person`; the answer has `saved_current` and `missing_after` |
| removal | no route reaches the deleted modules; `discjockey upgrades` and `rekordbox checked` are `bad_args` with "say `upgrade …`" / "say `check done`" |

### 1.13 Writes B: AIFF and file facts (own review + rehearsal)

| | |
|---|---|
| Goal | `aiff convert`, `aiff rename` in all selection forms, their dry runs without writes, `library facts`; `convert_cmd.py` deleted |
| Design | §5.2 rows `aiff_plan`, `convert`, `rename`, `make_aiff`; §5.3 `library facts`; §7.1 (no stored facts in a dry run, ≤ 50 read in memory, `facts_missing`); §9.3 L D1 (`resolve_collection`) |
| Touches | catalogue entries (`--all --in C` → `make_aiff({kind: lossless, view, key})`, `--all --todo cdj` → `make_aiff({kind: cdj})`, ids/`--rows` → `convert` / `rename`, `rename --all` → `select`); `HubApi.resolve("collection", …)` (`all`, `unlisted`, `playlist:<folder>`, `folder:<path>`; an unknown one is `bad_args`, `unknown_id`, "No playlist called “X”." / "No folder at X."); `aiff_plan` / `HubApi.aiff_plan` read missing facts in memory only; `importer.fill_facts` split into `read_facts` (pure of library.db) and `store_facts`; `HubApi.fill_facts()` write job; delete `convert_cmd.py`, its tests and route; `rekordbox_rehearsal.py rehearse-convert` on the new commands; CLAUDE.md (`convert_cmd.py` row goes) |
| Reads | `convert_cmd.py` 4k, `importer.fill_facts` (~1.5k), `aiff_plan.plan` (~2k), `api.py` `aiff_plan`, `_aiff_scope`, `_aiff_work`, `_selection_job`, `convert`, `rename`, `make_aiff` (~5k), `test_convert_cmd.py` 9.5k, `test_hub_api_convert.py` (~3k), `rekordbox_rehearsal.py` `rehearse-convert` (~4k), design (~2k) |
| Material | ≈ 33k |
| Model, size | Sonnet, ≈ 225k |
| Green | touched tests, full pytest, `test_rekordbox_rehearsal_safety.py` |
| Review | own Sonnet review; rehearsal on a copy: `rehearse-convert` all PASS |

| Test | Pins |
|---|---|
| dry run | `aiff convert --all --in folder:<p> --dry-run` writes nothing (T9) with 50 files lacking facts; with 51 → `refused`, `facts_missing`, `next: library facts` |
| run | `--plan P` runs P's items as one AIFF batch (`started_by` `make_aiff` / `cdj_all` / `user`); nothing to change → `ok`, `total: 0`, "Nothing to change: these are clean AIFFs already." |
| one file | a named track with rekordbox open → `needs_person`, exit 4, the batch of one closed (no resume) |
| facts | `library facts` stores the missing facts under the library lock; a second run → `ok`, `total: 0` |

### 1.14 Writes C: folders, settings, the Auto-upgrade phase alone (own review + rehearsal)

| | |
|---|---|
| Goal | `folder add`, `folder remove` (`--dry-run`, `--yes`), `settings show`, `settings set auto-upgrade on\|off`, `sync run --auto-upgrade-only [--dry-run]`; `settings_cmd.py` deleted |
| Design | §5.2 rows `add_watched_folder`, `remove_watched_folder`, `removal_preview`, `set_auto_upgrade`, `start_sync` (`--auto-upgrade-only`, R38); §6.1 (settings write); §15 C |
| Touches | `HubApi.resolve("folder", path)` → folder id; `HubApi.settings_view()`; `run.auto_upgrade_only(paths, settings, *, emit, token, rekordbox, dry_run)` and `HubApi.auto_upgrade_preview()` / `auto_upgrade_run(plan_id=None)`; the report of a phase-only run (`report.py`: a run kind `auto_upgrade_only` its title says); the dry run's `start_note` (the Sync page's before-start line for the phase, words moved into `words.py`); delete `settings_cmd.py` and its route; `rekordbox_rehearsal.py rehearse-sync` uses `sync run --auto-upgrade-only` where a step is about the phase alone (steps that need a whole sync stay on the legacy `--yes` route until phase 4) |
| Reads | `auto_upgrade.py` (`plan`, `run_phase`, ~3k), `run.py` `upgrade_phase`, `finish_quietly`, report writing (~3k), `report.py` (~2k targeted), `folders.py` 3k, `settings_cmd.py`, `api.py` folder, rescan and settings methods (~4k), `test_hub_auto_upgrade.py` 5.5k, `hub-ui/src/pages/sync/BeforeStart.svelte` (~1.5k: the line's words), `rekordbox_rehearsal.py` `rehearse-sync` (~4k), design (~2k) |
| Material | ≈ 30k |
| Model, size | Sonnet, ≈ 230k |
| Green | touched tests, full pytest, `test_rekordbox_rehearsal_safety.py` |
| Review | own Sonnet review; rehearsal on a copy: `rehearse-sync` all PASS |

Decisions:
- `auto_upgrade_only` never calls the planner: with no fetched playlists the planner would mark songs as gone from
  their playlists. It opens the state, runs `recover_pending`, `auto_upgrade.run_phase`, saves, writes
  `not_lossless.md` and a report holding only the `auto_upgrade` block. Check first: whether a song held by a
  same-song question (`prep.plan.questions`) can hold a parked upgrade; if it can't, `held = ∅` is exact; if it can,
  `held` comes from the questions the import stored.
- `sync run` in phase 1 requires `--auto-upgrade-only` (usage error otherwise, naming `discjockey --yes` for the whole
  sync); 4.1 lands the whole `sync run` and removes the legacy sync.
- `partial` for this command: only `failed` items (R24). Switch off: `ok`, `data.auto_upgrade: null`, message
  "Auto-upgrade is off, so nothing was moved." (R38).

| Test | Pins |
|---|---|
| phase alone | on a fixture with two same-edit upgrades and rekordbox closed: one AIFF batch `started_by: auto_upgrade`, a report whose `report show last` has the block; rekordbox running: both `waiting`, `rekordbox_open`, nothing moved, exit 0 |
| dry run | writes nothing (T9); has `start_note` and the `auto_upgrade` block with `dry_run: true` |
| folders | `folder add <p>` imports in the same job; `folder remove <p>` without `--yes` → `needs_yes` with the removal preview; a path not watched → `bad_args`, `unknown_id` |
| settings | `settings set auto-upgrade off` takes the support lock and the library lock briefly (§6.1); `settings show` needs no music folder |

### 1.15 The live-test kit (own review + rehearsal)

| | |
|---|---|
| Goal | What §15 needs besides commands: synthetic click tracks with parked upgrades, the `(upgrade test)` marker on everything they make, and the clean-up `--clean` |
| Design | §15 "Clean-up" (R48), §10.1 (`step:remove_test_tracks`); the stage plans' live-test sections (B §9, C §9, D §9) for the tracks they ask for |
| Touches | `scripts/make_upgrade_test.py`: `--click mp3\|m4a48\|flac\|aiff\|aac [--bpm 120] --into <scratch folder>` (a 120 BPM click track, the marker in file name and title tag, a parked lossless upgrade where the stage needs one; `--same-edit` for stage C), `--clean <entry>\|--all-marked [--json]` replacing `--remove`; `tests/test_make_upgrade_test.py` |
| Reads | `make_upgrade_test.py` 2.5k, its test 1.7k, `audio_helpers.py` (tone/click making), the three stage plans' §9 (~6k), design §15 (~2k) |
| Material | ≈ 14k |
| Model, size | Sonnet, ≈ 180k |
| Green | touched tests, full pytest |
| Review | own Sonnet review (it moves the user's files to the Trash); rehearsal on a scratch library: make, import, upgrade, `--clean` |

| Test | Pins |
|---|---|
| clean | refuses while rekordbox runs or the library lock is held; moves to the Trash only files whose names carry ` (upgrade test)` inside `Library/`, `Superseded/`, `Upgrades ready/` and the scratch folder, removes empty `_Upgrade test/` folders, removes the test entries from library.db, lists what it moved, `next: library scan`; a file without the marker beside them stays |
| derived names | a New track, a Convert and a clean name made from a marked file carry the marker (so `--clean` finds them) |

Check first: how to move to the Trash without a new dependency: `NSFileManager.trashItemAtURL` through pyobjc when
the checkout's environment has it (pywebview brings pyobjc on macOS), else `osascript` asking the Finder; the script
never calls `unlink` on an audio file.

### Phase 1 at a glance

| # | Group | Model | Material | Expected | Own review | Rehearsal |
|---|---|---|---|---|---|---|
| 1.1 | Outcomes, ids, catalogue | Sonnet | 28k | 215k | — | — |
| 1.2 | CLI adapter, headless HubApi | Sonnet | 31k | 230k | — | — |
| 1.3 | Discovery, app binary | Sonnet | 24k | 200k | — | — |
| 1.4 | Job registry, string ids | Sonnet | 21k | 210k | — | — |
| 1.5 | The worker | Sonnet | 20k | 230k | — | — |
| 1.6 | Job client, `job` noun | Sonnet | 12k | 210k | — | — |
| 1.7 | Locks | Sonnet | 23k | 200k | yes | scratch support, two processes |
| 1.8 | Reads I | Sonnet | 25k | 225k | — | — |
| 1.9 | Reads II | Sonnet | 19k | 210k | — | — |
| 1.10 | Dry runs, plans, selection | Sonnet | 18k | 220k | — | — |
| 1.11 | Writes A1 | Sonnet | 27k | 210k | yes | with 1.12 |
| 1.12 | Writes A2 | Sonnet | 35k | 215k | yes | `rehearse` on a copy |
| 1.13 | Writes B (AIFF) | Sonnet | 33k | 225k | yes | `rehearse-convert` on a copy |
| 1.14 | Writes C | Sonnet | 30k | 230k | yes | `rehearse-sync` on a copy |
| 1.15 | Live-test kit | Sonnet | 14k | 180k | yes | scratch library |
| | **Build** | | **360k** | **3 210k** | | |

---

## 4. Reviews

| Phase 1 review | Covers | Model | Size |
|---|---|---|---|
| Own review (×6) | 1.7, 1.11, 1.12, 1.13, 1.14, 1.15: each right after its group, before the next starts; a fix round only for findings with a stated fix (fresh Sonnet when the builder is over ~150k) | Sonnet | ~125k each; fix ~130k for about two in three |
| Rehearsal (×5) | 1.7; 1.11 + 1.12 together; 1.13; 1.14; 1.15. On a copy or a scratch folder, never the real library; rekordbox closed (the coordinator checks `rekordbox status` first and waits for the user only if it is open) | Sonnet | ~70k each |
| Phase review | 1.1–1.6, 1.8–1.10 (the frame, the jobs, the reads, the plans), read per group diff with their interfaces (§2) as the brief; plus a whole-phase look at T1–T3, T8–T10 | Opus | ~300k + one fix round ~140k |
| Shots pass | none: phase 1 changes no screen (types only) | — | — |
| `npm run verify` | once on the phase branch before its merge (1.1 and 1.4 touch `hub-ui` types and the fake) | machine | ~20 min, background with a status line |

The reviewer's brief for every own review: the group's section of this plan, the invariants of CLAUDE.md, the design
sections the group names, the diff. It checks the behaviours of the group's table one by one, every refusal path,
that nothing writes outside its own files, and that the deleted legacy words have no caller left.

---

## 5. How today's commands move onto the new design

Nothing is kept for compatibility. Until its replacement lands a legacy command answers as today (1.2's routes); the
group that lands the replacement deletes the old handler and updates its tests, scripts and docs in the same commit.

| Today | New | Group |
|---|---|---|
| `hub` | `app open` | 1.3 |
| `rekordbox status`, `rekordbox preview` | the same words, the envelope, the new fields; `rekordbox_cmd.py` deleted | 1.2, 1.9 |
| `upgrade list` | `upgrade list` (= To-do's Upgrade ready group) | 1.8 |
| `batch list`, `batch show <n>` | `batch list` (both kinds), `batch show aiff:<n>` | 1.9 |
| `upgrade apply … --way` | `upgrade apply <ids>\|-\|--all\|--rows … --way …` with `--dry-run` / `--plan` | 1.10, 1.11 |
| `upgrade discard` | `upgrade discard … --yes` | 1.11 |
| `upgrade undo` | `track undo … --yes` | 1.11 |
| `rekordbox checked` | `check done <ids>\|--batch aiff:<n>\|--all` | 1.11 |
| `batch resume <n>`, `batch undo <n>` | `batch resume aiff:<n>`, `batch undo aiff:<n> --yes`; `batch_cmd.py` deleted | 1.12 |
| `rekordbox backups`, `rekordbox restore … --yes` | the same words, the envelope | 1.12 |
| `upgrades` (interactive) | dropped (→ `upgrade …`); `upgrades_cmd.py` deleted | 1.12 |
| `convert …`, `rename …` | `aiff convert …`, `aiff rename …`; `convert_cmd.py` deleted | 1.13 |
| `settings auto-upgrade [on\|off]` | `settings show`, `settings set auto-upgrade on\|off`; `settings_cmd.py` deleted | 1.14 |
| the bare sync `[--dry-run\|--yes] [--json] [--limit] [--verbose]` | `sync read`, `sync plan`, `sync run [selection] [--plan] [--how-many]`; `cli/legacy.py` deleted; `bin/discjockey` drops `caffeinate` (workers keep the Mac awake) | 4.1 |
| `--extra N` | `limits set <service> <n> --extra-today N` | 4.8 |
| `setup` (interactive) | `setup status`, `setup music`, `login …`; `setup_cmd.py` deleted | 4.7 |
| `update` | `tools update`, `tools rollback --yes` | 4.8 |
| `--self-test`, `--check-tools` | unchanged | — |

Callers that move with them: `tests/test_cli.py` (split in 1.2), `test_batch_cmd.py`, `test_upgrades_cmd.py`,
`test_convert_cmd.py` (deleted with their modules; their behaviours re-pinned against the new commands),
`scripts/rekordbox_rehearsal.py` (1.12, 1.13, 1.14, 4.1), `scripts/make_upgrade_test.py` (1.15), README's restore
advice (1.12) and its Terminal section (4.1, 4.7), CONTRIBUTING (1.3 once, then nothing hand-written), CLAUDE.md's
Layout rows and Commands table (each deleting group).

---

## 6. Branches and merges

| Step | Rule |
|---|---|
| Phase branch | `feat/cli-<phase>-<topic>` from `main` (phase 1: `feat/cli-1-live-slice`) |
| Group | worktree `.claude/worktrees/cli<phase>-<n>` on `feat/cli-<phase>-<n>` from the phase branch; merged into the phase branch when green (and, where it has one, after its own review and fix round) |
| Main moves meanwhile | issues commit to `main`; `main` is merged into the phase branch at the next group boundary |
| Phase → main | after the phase review's fixes, CI green on the phase branch and `npm run verify` green; `Merge feat/cli-<n>-…: <summary>`; pushed |
| Release | none without the user's go; the live tests run on `main` in the checkout, not in a built app |
| After phase 1 | the live tests (§7) on `main`; their bugs are fixed on `main` before phase 2's branch starts |

---

## 7. The A–D live tests (after phase 1)

**Where:** on `main` after phase 1 has merged, in the checkout (`bin/discjockey …`), against the user's real music
folder and real rekordbox, only with the user's go. Before each stage the agent runs `where --json` and reads the
music folder back to the user, and `rekordbox status`. Every long step is `--wait 90`, then `job wait <job> --wait
90` until it ends; a live `person_steps` on a `running` answer is told to the user at once. With the window open,
writes use `--wait-busy 60` (the window's own scans hold the lock for seconds).

**The steps that need the user** (from §15; everything else the agent runs):

| Stage | **P** steps |
|---|---|
| A | 1b open rekordbox; 3b import the test track, analyse, set 3 hot cues, quit; 3e Relocate the old track to the new `.aiff` (the answer's `step:relocate_new`); 3f cues on the same beats, listen for a click; 3g remove the test tracks from rekordbox's collection (`step:remove_test_tracks`) |
| B | 0a rekordbox File › Library › Backup and a spare USB stick; 1 import, analyse, cues, playlists, edit a title, export to the stick, quit; 3 look (AIFF/44.1/16, plays, cues and grid, names, sorting, history, playlists); 4–6 reopen, seek, re-analyse, Reload Tag, the USB stick (the agent reads out `check list`'s steps); 7a open rekordbox; 7b quit, look at the old files' cues; 8 relocate tries; 9a leave rekordbox closed a minute; 9b answer rekordbox's prompt; the clean-up's rekordbox step |
| C | 0 the rekordbox backup; 1a open rekordbox; 1c may look at To-do; 2a quit rekordbox; 2c AIFF with cues in rekordbox; 3 look after the undo; the clean-up's rekordbox step |
| D | 0 backup, five click tracks analysed with cues in a playlist, rekordbox closed; 1c look (AIFF/44.1/16, cues, grid, playlist); 2b play the converted AAC; 3 look; 4 look after the undos; 5a open rekordbox; 6 export to a stick, play on a CDJ; the clean-up's rekordbox step |

**Decisions for the runbook** (they change no command; they keep the tests on the test tracks):
- **Only the test tracks.** `upgrade apply --all` (B 2a) and `aiff convert --all --todo cdj` (D 2b) act on the whole
  real library. The agent always runs the dry run first; when it lists anything but the `(upgrade test)` tracks, it
  names them instead: `track find "(upgrade test)" --json | jq -r '.data.rows[].track_id' | discjockey upgrade apply -
  --way same-track` (the same batch path; `started_by: user` instead of `upgrade_all`). The `--all` form runs only
  when its dry run lists the test tracks alone.
- **Auto-upgrade (C 1–2)** has no selection: the phase runs over every same-edit upgrade. The agent shows the user
  `sync run --auto-upgrade-only --dry-run`'s list; real tracks in it would be upgraded at the next sync anyway
  (Auto-upgrade is on); going on is `step:decide`.
- **Phase 1's fields for §15's wording:** C 1c reads the item's `auto_waits` (the `sub` words arrive in phase 6);
  C 2d reads the batch check entry and its `can_undo` (the `undo.label` words arrive in phase 6); A 3e and B 4–6 read
  `person_steps` / `check.person_steps` (one step per check in phase 1, §1.8).
- **Clean-up after every stage:** `step:remove_test_tracks`, then `folder remove <scratch> --yes`, then
  `scripts/make_upgrade_test.py --clean --all-marked`, then `library scan`.

**Cost:** about 300k: one agent session per stage (~60–90k each, the user present), the coordinator reporting
between stages. A stage that finds a bug stops; the fix goes to `main` as a small group before the stage runs again.

---
## 8. Phases 2–8: the costed outline

Each group below is detailed (behaviours, check-firsts, files touched) by a later planning run after the user's go.
Material is measured like phase 1's; "expected" uses the same method (§1.4). Models: Sonnet unless named.

### Phase 2: foundations (branch `feat/cli-2-foundations`)

| # | Group | Design | Material | Expected |
|---|---|---|---|---|
| 2.1 | The window on the registry, engine: window jobs registered (`via: window`), the 1-second registry watch replacing `watch_console` (the probe kept for a holder with no entry), `JobFinished` for terminal jobs from `result.json`, `ConsoleBusy` with the job's kind and `line`, the window files and `where.windows_open`, `job stop` reaching window jobs (`--now` → `window_job`) | §6.3, §6.6 | `jobs.py` ~6k, `api.py` bind/attach ~3k, `hub/app.py` 2k, registry ~4k, `test_hub_jobs.py` 5k, design ~2k ≈ 22k | 215k |
| 2.2 | The window on the registry, window: the banner "Sync running in the Terminal · 4 of 60" from those fields; fake scenario and `shots.json` entry | §6.6 | `Banners.svelte`, `stores/hub.ts` 3.6k, `events.ts` 1.8k, fake (~4k targeted), design-language doc (~3k) ≈ 15k | 170k + shots pass 80k |
| 2.3 | Shapes I: the generator, `F(shown, doc)`, JSON Schemas, `help <cmd> --json` schemas, T6 on real outputs, T7 and its sample with every optional field; the shapes of phase 1's payloads | §8.2, §4.2, §13 T6 T7 | `views.py` todo/track/check/run (~10k), phase 1 `render/` (~6k), `types.ts` (~5k), design ~2k ≈ 25k | 210k |
| 2.4 | Shapes II: Library, collections, Sync, runs, Dashboard, limits | §8.2 | `views.py` (~20k targeted), `types.ts` (~6k) ≈ 26k | 230k |
| 2.5 | Shapes III; `types.ts` generated (CI freshness check like `hub/static`); the contract doc reduced to its rules | §8.2 | contract doc 37.6k, `types.ts` 13.5k, `api.py` answers (~6k) ≈ 57k | 245k |
| 2.6 | Stored read, derived plan: `playlist_reads` / `playlist_tracks` widened (schema), one transaction per read keeping the newer, the plan derived and cached per (read id, generation, settings hash), `PreviewStore` reduced | §9.2 | `run.py` 7k, `planner.py` (~3k), `jobs.py` PreviewStore/refresh/sync work (~5k), `db.py` read records (~5k), `api.py` `_store.prep` users (~6k), design ~1.5k ≈ 27k | 240k |
| 2.7 | Plan binding: `sync plan` with `plan_id`, presets and `default_how_many`; `start_sync(plan_id, selected)`, `new_since_plan`; the Sync page sends its plan id; `sync.lastSelection` → the job's args | §9.2, §7.1 | `api.py` sync (~3k), `views.sync_preview` (~4k), Sync page + `stores/run.ts` (~8k), `run.select_actions` ≈ 16k | 210k |
| 2.8 | `rev` replaces `_shown`: reads print `rev`, writes take `expect` / `--if-rev`, the window sends it; 1.2's `remember=False` removed | §3 | `api.py` + `ops.run_single` (~4k), `views` rows (~3k), hub-ui `decisions/` flows (~10k), `types.ts` ≈ 19k | 220k |
| 2.9 | Other persisted state: the drop's path (`FileDropped`, `add_bought_file(track_id, path)`), `folders.keep_file` (one job), the three dropped methods removed, sync scope in settings (`sync scope show\|on\|off`; `syncScope.ts` off localStorage), import state in library.db | §9.2, §9.3 L D10, U1 | `api.py` (~6k), `folders.py` 3k, `importer.py` (~2k), `settings.py` 3k, hub-ui (~5k), `db.py` (~2k) ≈ 21k | 230k |
| 2.10 | Shared protection: `SharedPacer` (`pace.json` / `pace.lock`), the streak in `usage` rows, the pause cleared at a sync's start, searches paced and skipping a paused Qobuz, `_qobuz_streak` deleted, `sync_running` from the registry; T13 | §7.5 | `pacing.py`, `acquire.py` (~4k), `fallback.py` (~2k), `qobuz.py` (~1k), `api.py` streak users (~3k), `db.py` usage (~2k), `test_pacing.py`, design ≈ 18k | 225k |

Reviews: own review + rehearsal for 2.6 (a copy of the real library.db: the derived plan equals today's), 2.9 and 2.10
(fake services only, never a real account); Opus phase review over 2.1–2.5, 2.7, 2.8; shots pass for 2.2.
**Phase total ≈ 3.6 M** (build 2 195k, own reviews 375k, fixes 260k, rehearsals 210k, Opus review + fix 440k, shots 80k).

### Phase 3: every other read (branch `feat/cli-3-reads`)

| # | Group | Design | Material | Expected |
|---|---|---|---|---|
| 3.1 | Library: `library list` (paging, `--in/--search/--quality/--sort`, the view's `actions[]`), `library collections`, `library superseded`, `folder list`, `folder check`, `import status` | §5.2, §5.3 | `views.library`, sidebar, watched folders (~13k), `api.py` (~5k), design ≈ 22k | 215k |
| 3.2 | Pictures: `track spectrum` (the 22×64 sketch, `--png` with `zlib` + `struct`, the window's colour map exported once, the waveform sparkline), `limits show --png` | §4.5 | `hub/spectrum.py`, the window's canvas colour map (~3k), limits views (~3k), design ≈ 12k | 200k |
| 3.3 | Sync and runs: `sync plan --search`, `report list --since`, `status` (Dashboard, nav counts, running jobs, person steps) | §5.2, §5.3, §11 | `views` sync/dashboard/runs (~10k), `api.py` (~3k) ≈ 18k | 215k |
| 3.4 | `history` (reports, batches, the operations log; `undo` / `cant_text`; playlist and setting changes logged), `doctor` (every check of §5.3, roots readable → `folder_access`), `status --ready` (a filter of doctor's) | §5.3, §7.4, R23, R26, R47 | `ops.log_operation`, `db.py` queries (~6k), `report.py` (~2k), rekordbox match pieces (~3k), design ≈ 18k | 235k |
| 3.5 | Playlists and limits: `playlist list`, `playlist check <url>` (network read job), `limits show` with one zone table (C9) | §5.2, §9.3 U21–U24 | `views` limits/playlists (~8k), `api.add_playlist` (~2k), `pacing` zones ≈ 14k | 210k |
| 3.6 | Accounts and setup: `login list`, `login find` (`offer`), `setup status` (six steps), `tools status`, `app info [--check]` | §5.2, C8 | `setup_status`, `downloads_view`, `find_logins` (~8k), `app_update.py` 2k ≈ 13k | 205k |
| 3.7 | `rekordbox match`, `open file\|folder\|url\|report\|licences\|privacy-settings`, `open file not-lossless`; `todo list --group` widened to several groups (`todo(filter)` takes a list: contract change) | §5.2, §5.3, C6 | `rekordbox/master.py`, `preview.py` (~5k), `api.py` opens (~3k) ≈ 12k | 200k |

Reviews: all read-only: one Opus phase review + one fix round. **Phase total ≈ 1.9 M** (build 1 480k, review + fix 440k).

### Phase 4: every other write (branch `feat/cli-4-writes`)

| # | Group | Design | Material | Expected |
|---|---|---|---|---|
| 4.1 | The whole sync: `sync read` (playlist-read job), `sync run [selection] [--plan] [--how-many]` (`partial` only for `failed`), the legacy sync and `cli/legacy.py` deleted, `bin/discjockey` without `caffeinate` | §5.2, §6.1, §12 | `run.py` 7k, `cli/legacy.py` 4k, `jobs.sync_work` (~3k), rehearsal `rehearse-sync` (~4k), design ≈ 22k | 240k |
| 4.2 | Playlist writes: `add`, `remove`, `rename`, `move`, `enable`, `disable`, `edit --file`, `add-liked`; `playlists_file.apply(lines, op)` + `validate`; `--if-version`; changes logged for `history` | §5.2, §9.3 U25 U26 | `playlists_file.py` 2.5k, `api.py` save/preview (~6k), `sources/__init__.py` (~2k) ≈ 15k | 215k |
| 4.3 | The save question (C1): `--files move\|leave`, `--rename`, `--no-rename`, `--move`, `--no-move`, each rename and move with its id in the dry run, `--plan` binding a subset | §5.2, §7.1, C1 | `tidy.py` 7k, `api.save_playlists` (~3k), design ≈ 14k | 220k |
| 4.4 | `tidy run [--all\|--with-yours\|--plan]`, `batch undo moves:<n>` (`--dry-run`), `import run` | §5.2, §7.4 | `tidy.py`, `importer.py` (~10k), `api.py` (~3k) ≈ 15k | 215k |
| 4.5 | `question list / answer`, `duplicate list / keep` (on `keep_file`) | §5.2 | `folders.py` 3k, `views` pairs (~4k), `api.py` (~2k) ≈ 11k | 200k |
| 4.6 | `version search / preview / use / reject / add-file` (on the shared pacer; `busy` while a sync runs anywhere), `track hide / unhide / never / download` | §5.2, §7.5 | `ops.py` 5k, `candidates.py` 2k, `api.py` (~6k) ≈ 15k | 225k |
| 4.7 | Accounts: `login use`, `login sign-in` (person job, live `step:sign_in`, `step:keychain`), `check`, `sign-out --yes`, `skip`, `qobuz --password-stdin`, `spotify`; legacy `setup` and `setup_cmd.py` deleted | §5.2, §6.5, §10.1 | `api.py` setup_* (~10k), `accounts.py`, `browsers.py` (~4k), `setup_cmd.py` 2k ≈ 18k | 240k |
| 4.8 | `settings set` (the rest), `limits set / seen` (dry run = what-if), `tools update / rollback`, `setup music [--yes]`, `setup skip-import`, `library favourites …`, `folder crates …` (brief saves); legacy `update` deleted | §5.2, §6.1 | `settings.py`, `tool_updates.py`, `api.py` (~8k) ≈ 18k | 225k |

Reviews: every group writes the user's files, playlists.txt, library.db or settings: own review each, a rehearsal on a
copy or a scratch support folder each (4.6 and 4.7 with fake services and no real login). **Phase total ≈ 4.0 M**
(build 1 780k, own reviews 1 000k, fixes 650k, rehearsals 560k).

### Phase 5: the guarantee tooling (branch `feat/cli-5-guarantee`)

| # | Group | Design | Material | Expected |
|---|---|---|---|---|
| 5.1 | Word extraction: `hub-ui/scripts/words.mjs` in `npm run build`, `words.json` (committed, CI-fresh), `fill()` in Python and TypeScript with one shared fixture, `help glossary` | §8.3 | hub-ui scripts (~5k), a sample of components (~10k), design ≈ 18k | 220k |
| 5.2 | `derive` rule (type-aware through `svelte2tsx` and the TypeScript compiler), the `view()` marker, `derive-allow.json` seeded with today's debt (closed reasons) | §8.4 (1) | `rules.mjs`, `rules-page.js` (~5k), pages sampled (~20k), design ≈ 27k | 245k |
| 5.3 | `flows` rule and its allow seeding; every `shots.json` entry declares `reads` or `view` (vitest) | §8.4 (2), (4) | the eight `shots.json` (35k), `rules.mjs` ≈ 38k | 230k |
| 5.4 | The rendered check T5b: blocks emit `data-item / data-tone / data-dim / data-badge / data-list`, the fake records each shot's reads, the strings check | §8.4 (3) | components (~25k targeted of 111k), `strings.mjs`, `shot-lib.mjs` ≈ 30k | 245k |
| 5.5 | Mount coverage (a Vite plugin) and the fake's payloads validated against the schemas | §8.4 (4), §8.2 | the fake (~20k targeted of 124k), `vite.config.ts` ≈ 22k | 230k |

Reviews: one Opus phase review; shots pass for 5.4 (attributes only, the pictures must not move). **Phase total ≈
1.7 M** (build 1 170k, review + fix 440k, shots 80k).

### Phase 6: §9.3, the window's decisions into the engine (branch `feat/cli-6-engine`)

Six clusters, each two Sonnet groups: the engine fields with shapes, tests and the fake (≈ 210–220k), then the window
switched to them with its `debt` entries removed and shots compared to `main` (≈ 230k). No new UI decision: words and
pictures stay identical unless two copies of one word are merged.

| Cluster | §9.3 rows | Window material | Engine + window |
|---|---|---|---|
| 6.1–6.2 Library | L D1, D5–D7, D15, D17, D19–D26, D36 | `pages/library` 33k, `libraryModel.ts` | 215k + 230k |
| 6.3–6.4 To-do decisions and upgrades | L D8–D11, T `decisionFor`, `upgradeWays`, candidates, `rowInTodo` | `decisions/` 44k (targeted), `pages/todo` 28k | 220k + 230k |
| 6.5–6.6 To-do checks, batches, AIFF | L D12–D14, T `checkCard` … `batchEnd` (the numbered check steps of §10.1 replace phase 1's one step) | `decisions/`, `pages/todo` | 220k + 230k |
| 6.7–6.8 Sync | U2–U16, U12, U14 (one `report.outcome`) | `pages/sync` 44k | 220k + 235k |
| 6.9–6.10 Limits and Playlists | U21–U28 | `pages/limits` 10k, `pages/playlists` 25k | 215k + 230k |
| 6.11–6.12 Settings, Setup, import | U29–U36, L D29, D31–D33 | `pages/settings` 17k, `pages/setup` 14k | 215k + 230k |
| 6.13–6.14 (optional) | The Sync page's live view of a terminal sync from `events.jsonl` (§6.6 "can show"): a new UI decision. 6.13 the view model from the registry's events, its fake scenario and tests (Sonnet); 6.14 the component (Opus) | `pages/sync` 44k (targeted), `stores/run.ts` | 180k + 240k + shots 80k |

Reviews: one shared Sonnet review per cluster (the phase's diff is too large for one agent) + fix rounds for about
four; shots pass per cluster; one Opus phase review at the end over the ratchet (`debt` entries at zero) and T4's ⌘A
half. **Phase total ≈ 4.8 M** (build 2 670k, cluster reviews 720k, fixes 520k, shots 480k, Opus review + fix 440k),
**+ 0.5 M** for 6.13–6.14.

### Phase 7: the sandbox (branch `feat/cli-7-sandbox`)

| # | Group | Design | Material | Expected |
|---|---|---|---|---|
| 7.1 | The root guard: `SupportPaths`, `Paths` and `rekordbox.locate` resolve only inside a sandbox; `outside_sandbox` at resolve; the write layer's second line; `DISCJOCKEY_REQUIRE_SANDBOX` | §10.3 | `library.py` paths and write functions (~10k), `locate.py`, `write.open_write`, `backup.restore` (~4k), design ≈ 18k | 230k |
| 7.2 | `sandbox create / info / remove`: the copy under the real lock (SQLite backup API, `clonefile`), watched folders rewritten, settings scrubbed (no accounts), the marker, every refusal | §10.3 | `db.py` (~3k), `library.py` (~4k), `settings.py`, design ≈ 15k | 235k |
| 7.3 | `--rekordbox copy` (repoint inside the copy with the writer and `splice_ppth`), no accounts in a sandbox, T9's sandbox suite | §10.3, §13 T9 | `rekordbox/write.py` (~4k), `anlz.py` (~2k), 1.10's T9 harness (~3k) ≈ 20k | 240k |

Reviews: own review + rehearsal each (7.2's first `--from real` with the user's go: it reads the real library to
copy it); one Opus phase review. **Phase total ≈ 2.0 M** (build 705k, own reviews 375k, fixes 260k, rehearsals 210k,
Opus review + fix 440k).

### Phase 8: docs and the final review (branch `feat/cli-8-docs`)

| # | Group | Design | Material | Expected |
|---|---|---|---|---|
| 8.1 | `AGENTS.md`, `help agents`, `help concepts`, `help --markdown` → `docs/agent-commands.md`, T11 | §14, §11 | design §11, §14 (~2k), the catalogue (~8k), README "Why" and "How it works" (~4k) ≈ 16k | 210k |
| 8.2 | README "Let an AI agent run Discjockey", CONTRIBUTING's pointer, the CLAUDE.md "Agent-ready" rule rewritten to T1–T13, `docs/issues.md` (the MCP note, §17), the plan, design and audits archived | §13, §14, §17 | CLAUDE.md, CONTRIBUTING, README parts ≈ 10k | 170k |

Then one Opus whole-design review and a fix round, and the final `npm run verify`. **Phase total ≈ 0.8 M**.

---
## 9. Totals and how they were made

**Method.** A group's expected size = ~100k before work (CLAUDE.md, this plan, notes; the record) + 1.5 × its
measured material (§1.4: read once, parts read again while editing and testing) + its work (60–100k: code, tests,
runs). Reviews from the record: an own Sonnet review ~125k (record 110–140k), a fix round ~130k (record 115–145k) for
about two in three reviewed groups, a rehearsal ~70k, an Opus phase review ~300k with one fix round ~140k, a shots pass
~80k, the live tests ~300k. `npm run verify` and CI are machine time.

| Phase | Groups | Build | Own reviews + fixes | Rehearsals | Phase review + fix | Shots / live tests | **Total** |
|---|---|---|---|---|---|---|---|
| **1 (up to the live tests)** | **15** | **3 210k** | **1 270k** | **350k** | **440k** | — | **5 270k** |
| **1, the live tests** | — | — | — | — | — | **300k** | **300k** |
| 2 | 10 | 2 195k | 635k | 210k | 440k | 80k | 3 560k |
| 3 | 7 | 1 480k | — | — | 440k | — | 1 920k |
| 4 | 8 | 1 780k | 1 650k | 560k | — | — | 3 990k |
| 5 | 5 | 1 170k | — | — | 440k | 80k | 1 690k |
| 6 | 12 | 2 670k | 1 240k (per cluster) | — | 440k | 480k | 4 830k |
| 6.13–6.14 (optional) | 2 | 420k | — | — | — | 80k | 500k |
| 7 | 3 | 705k | 635k | 210k | 440k | — | 1 990k |
| 8 | 2 | 380k | — | — | 440k | — | 820k |
| **All** | **62 (+2)** | **13 590k** | | | | | **≈ 24.4 M (24.9 M with 6.13–6.14)** |

**Phase 1 apart:** about **5.3 M up to the live tests, 5.6 M with them**. That is what the user decides on first; it
ends with the A–D tests run by an agent through the CLI on the real library, and leaves every later phase free to
start or not.

**Range:** 21–31 M. The low end assumes groups land at their plan and fewer fix rounds; the high end that groups land
like the record's upper half (1.3× plan). Compared with §16's ~17 M: the per-group start cost (62 groups × ~100k ≈
6.2 M before any work, where §16's 37 groups carried ~3.7 M), own reviews and rehearsals for every writer group (about
5.5 M across phases 1, 2, 4 and 7), and the work §16 implied but did not place (the check steps, the plan store,
selection, read-only dry runs, the rehearsal and test scripts, the legacy removals with their callers).

---

## 10. Cost notes (the user decides; the design stays as it is)

| # | Work | Saving | What is lost |
|---|---|---|---|
| C-1 | Phase 6's window half (6.2, 6.4, 6.6, 6.8, 6.10, 6.12 and their shots): build only the engine fields | ≈ 2.4 M | The CLI still gets every fact as engine data, so an agent sees and does everything; but the window keeps its own copies of ~115 rules beside the engine's. Nothing pins that the two agree, so the window and the CLI can drift apart over time, and the `derive` ratchet stays above zero (it still blocks new copies) |
| C-2 | Phase 5's rendered check and mount coverage (5.4, 5.5) | ≈ 0.6 M | The backstop for what the static rule misses (template strings, enum keys printed as words, SVG text, CSS `content:`), the order and tone checks per shot, and the catch for a new component without a shot |
| C-3 | The sandbox reduced to `--from empty` and the root guard (7.2's `--from real` clone and 7.3's rekordbox copy left out) | ≈ 0.8 M | An agent can't rehearse on a copy of the real library and rekordbox; it rehearses on an empty library, and developer agents keep `scripts/rekordbox_rehearsal.py` for copies |
| C-4 | 6.13–6.14, the Sync page's live view of a terminal sync | ≈ 0.5 M | A sync started in the Terminal shows in the window only as the banner line ("Sync running in the Terminal · 4 of 60"), not track by track |
| C-5 | Generated `types.ts` and the reduced contract doc (2.5) | ≈ 0.35 M | A hand-kept third copy of the shapes stays in `types.ts`; drift is caught only where 5.5 validates the fake |
| C-6 | Rehearsals once per phase instead of per writer group (phases 1 and 4) | ≈ 0.7 M | A defect a rehearsal would have caught is found after more groups built on it, when its fix costs more |
| C-7 | `--png` pictures (3.2's PNG and the limits picture) | ≈ 0.15 M | A person or a vision agent without the window can't see the spectrum or the usage chart; the numbers and the text sketch remain |

None of these touches account protection (2.10), the locks (1.7), never-delete or the dry runs: those stay whatever
the user picks.

---

## 11. Risks, and what the coordinator checks between groups

| Risk | Where | What this plan does |
|---|---|---|
| **The worker process (riskiest group)**: lifetime, signals on the main thread, the frozen app starting itself, locks taken in the right thread | 1.5 | real-subprocess tests with a reaper; `worker_argv()` pinned for checkout and app; `ps` after the suite; if a Sonnet run stalls on it, the coordinator re-runs it as Opus (+~100k) |
| Headless reads differ from the window's until the stored read (2.6): no `_store.prep` in a command, so a track's planned aliases and a playlist's planned rows are missing | 1.2, 1.8 | parity is pinned on fixtures without a read; the live tests use no field that depends on it (§7) |
| `remember=False` lets a command act without the window's "as shown" check | 1.2 → 2.8 | the window path is unchanged; the engine's per-item checks still hold; 2.8 replaces both with `rev` |
| `?mode=ro` on a WAL library | 1.10 | check first; a test that no `-wal`/`-shm`/`library.db` appears; a rehearsal-free group, so the phase review looks at it |
| The Auto-upgrade phase without the planner | 1.14 | the planner is never called; a fixture test that no song's flags change; `rehearse-sync` on a copy |
| The live tests write the real library and rekordbox | §7 | only with the user's go, after a rekordbox backup step, test tracks selected by name, dry run first, clean-up by the marked-files script |
| Contract changes (string job ids 1.4, `check.person_steps` 1.8, status fields 1.9, the mode enum 1.11) | phase 1 | each with `types.ts`, the fake and the contract doc in its own commit; `npm run verify` before the merge |
| Groups overrun | all | planned under ~250k; stopped at a green commit near ~300k, the rest to a fresh agent with the findings |
| A legacy route outlives its replacement | 1.2 → 4.8 | each group deletes its words; T2's last form fails while any remains |
| `scripts/rekordbox_rehearsal.py` (106 KB) | 1.12–1.14, 4.1 | never read whole: the step function and `discjockey()` only |

**Between groups the coordinator checks:**

1. The group's report: its commit(s), the green lines (`pytest | tail -3`, the public check), its token size (logged).
2. No process left: `ps -ax | grep -E "job _worker|discjockey"`; `git worktree list` has only the expected worktrees.
3. The diff touches the files the group's table names (plus tests and docs); nothing under a real support or music
   folder; no stray `library.db`.
4. T1's `planned` ceiling went down by the group's new entries; no new legacy route.
5. For a writer group: its own review, then its fix round with stated fixes only, then its rehearsal (rekordbox closed,
   checked with `rekordbox status`; on a copy or scratch folder only), before the next group starts.
6. The group branch merged into the phase branch and pushed (CI); `main` merged in when it moved.
7. At the phase's end: the phase review, its fix round, CI green, `npm run verify` green (background, status line),
   the merge into `main`, the push. No release without the user's go.
