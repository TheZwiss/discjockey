# Discjockey's command line for agents and people: build plan v2 (issue 39)

Status: plan, 2026-11-15. Design: `docs/2026-11-14-agent-cli-design.md` (cited as §n). First plan:
`docs/2026-11-15-agent-cli-plan.md` (cited as **v1**, its groups as `v1 1.1` … `v1 8.2`). This plan keeps every goal of
the user's brief and drops only cost that buys nothing toward them. Its groups carry the prefix **V** (`V1.1` …) so a
number never means two groups. Phase 1 is planned in full; phases 2–8 are groups with sizes, detailed by a later run
after the user's go. v1's interfaces (§2) and phase 1 behaviours (§3) stay binding except where this plan changes them.

The goals (fixed): **G1** the engine is the single source of truth (§9.2, §9.3, every audit row); **G2** the window
works exactly as well as today; **G3** the CLI is as good as possible (everything the window shows and more, text for
people, a machine shape for agents, everything doable under the invariants, the safety fixes in full: Qobuz protection
across processes, locks, jobs that survive an agent's timeout, dry runs and `--plan`); **G4** the drift can't come
back (a CLAUDE.md rule plus a check); **G5** reviews and rehearsals on a copy for every group that writes the user's
files, library.db, master.db or settings.

---

## 0. Summary

| Phase | What it gives | v1 groups | V groups | v1 total | **v2 total** |
|---|---|---|---|---|---|
| 1 | The CLI slice the A–D live tests need | 15 | 15 + brief writer | 5 270k | **5 100k** |
| — | The A–D live tests | — | — | 300k | **300k** |
| 2 | Window on the registry; stored read, derived plan; `rev`; persisted state; shared Qobuz protection | 10 | 6 | 3 560k | **2 390k** |
| 3 | Every other read (generic), new reads, hand-made pages | 7 | 4 | 1 920k | **1 230k** |
| 4 | Every other write | 8 | 8 | 3 990k | **3 675k** |
| 5 | The G4 check (`derive`, `flows`, the ratchet, the CLAUDE.md rule's check) | 5 | 2 | 1 690k | **735k** |
| 6 | §9.3: the window's decisions into the engine | 12 | 12 | 4 830k | **4 670k** |
| 7 | The sandbox: root guard, `--from empty` | 3 | 2 | 1 990k | **1 205k** |
| 8 | Agent docs, final review | 2 | 2 | 820k | **750k** |
| | **Base (every goal; see E1 below)** | **62** | **52** | **24 370k** | **≈ 20.1 M** |
| | Extras, all ticked (§7) | | | | + 4.3 M → 24.4 M |

**Range** (v1 §9's method: groups at plan → the record's upper half, ×0.86 … ×1.27): **17.2–25.5 M** for the base.

**Where the difference comes from** (v1 → v2 base, k tokens; the arithmetic is one script, every row has a basis in §1):

| Row | Kind | Δ | What |
|---|---|---|---|
| A | moved, **not a saving** | −2 580 | v1 groups now priced as extras the user ticks: 2.2 (E9), 2.3–2.5 (E7), 3.2 (E6), 5.1 (E1), 5.4 (E2), 5.5 and 5.3's declarations (E3), 7.3 and 7.2's real clone (E5), with their reviews, rehearsals and shots |
| B1 | saving, estimated from one record | −572 | Self-contained briefs for build groups: −17k each (46 carried over) + 210k for the agent that writes phase 1's briefs. Rests on D3a (a build group read its plan whole, §1.2) |
| B2 | saving, **not measured** | −600 | The same −20k for each review (30): no record says a reviewer read the plan whole, and v1 §4 already gave reviewers a short list |
| C | process cut, **not measured** | −540 | A writer group's rehearsal runs inside its last agent (fix round, or the review when it has no fix) instead of a fresh agent; still one rehearsal on a copy per writer group (G5); the 40k unit has no record (§1.1) |
| D1 | saving, estimated, no record | −113 | Generic path in phases 1 and 4: the named modules not written (`render/rekordbox`, `batch`, `report`, `upgrade`, `check`; a handler and text layout per phase 4 command, −15k a group) |
| D2 | saving, estimated, no record | −380 | Phase 3 recut 7 → 4: v1 3.1, 3.5, 3.6's ~20 plain reads each had a handler, layout and golden file; in V3.1 they are catalogue rows under one parametrised test. V3.2 and V3.3 are new engine reads the generic path doesn't shorten: they keep v1 3.3, 3.4, 3.7's engine work (status, doctor, history, superseded, match) and lose their commands' text layouts, which V3.4's four pages and the generic printer replace |
| E | saving, by the checklist's rule | −440 | Phase 6 keeps its per-cluster reviews and drops the extra Opus phase review (checklist line 6: per-group reviews **or** a stage review; phase 6 writes no user data) |
| F | estimate correction, both plans | +725 | Units from the record instead of v1's: own review 150k (v1 125k), fix round 150k (v1 130k), Opus phase review 200k (v1 300k), shots pass 120k (v1 80k) |
| H | gaps closed | +75 | §9.3 rows v1 placed in no group (U17, U18, U19, U9; the "Deleted" list), `app install-command` (in no v1 group), flags generated from signatures |
| I | rounding | +90 | each group rounded up to 5k |
| J | v1's arithmetic | +20 | v1's phase 6 rows add up to 2 690k, its total uses 2 670k; v2 builds on the rows |
| | | **−4 315** | 24 370k → 20 055k |

So the savings are **B + C + D + E ≈ 2.6 M**: 1.0 M rests on a record or a rule (B1, E), 1.6 M is estimated without a record or not measured (B2, C, D1, D2). **If only B1 and E hold, the base is ≈ 21.7 M** (20 055 + 600 + 540 + 493). 2.6 M more is extras moved out (priced in §7, 4.3 M at v2's record
units), and the record corrections add 0.7 M back. **With every extra ticked v2 costs what v1 costs (24.4 M)**: the
savings pay for record-based unit sizes, the gaps v1 left, and an MCP server v1 didn't price.

**What stayed expensive, and why:**
- **Merges barely fit.** A merge saves one start (~80k, est.), so two groups fit under ~250k only when their sizes add
  to ≤ ~330k. The smallest v2 pairs (V8.1 + V8.2 = 270k, V1.9 + V1.15 = 265k) don't. Only phase 3, where the generic
  path removed most per-command work, was recut (7 → 4).
- **The ~100k start is mostly not shared docs** (§1.2): what v1 told a group to read beyond its material is ~3k; the
  record that groups read the whole plan (20.7k) gives the −17k used here. If the brief's premise held (whole design
  and plan read, ~58k), the base would be ~2.8 M lower (≈ 17.2 M); it is not measured, so it isn't counted.
- **Phase 6 (G1) and phase 4 (G5)** carry 8.3 M between them: 12 groups that move ~115 window decisions with shots,
  and 8 writer groups each with its own review and rehearsal. Both are goals.
- **E1 is needed by G3 in the strict sense** (the window's fixed tooltips and explanations reach the CLI only through
  the word catalogue). The base meets G3 for every fact and every data word; with E1 it is ≈ 20.3 M.

---

## 1. The basis for every number

### 1.1 Units

| Unit | v1 | v2 | Kind | Basis |
|---|---|---|---|---|
| Build group | 100k + 1.5 × material + work | **80k + 1.5 × material + work** | estimated | v1's start (record: D3a, Sonnet 304k, "reading CLAUDE.md + plan + notes + convert.py is ~100k before work", orchestration doc, stage D) minus v1 read whole (82 748 chars / 4 = 20.7k, measured), the part a self-contained brief removes |
| Material | `wc -c` / 4 of files and ranges | the same, **plus the brief** | measured (whole files) / estimated (`~` ranges of big files, v1's figures) | a brief = the group's design extracts (v1 counted them as material) + ~2k of v1 §2 interface lines and its own section (39 124 chars / 15 groups / 4 = 0.65k, measured); so v2 material = v1 material + 2k |
| Work | 60–100k | v1's work per group (v1 size − 100k − 1.5 × material), minus the generic path's savings (§3) | estimated | v1 §9 |
| Own review (Sonnet) | 125k | **130k** | estimated | record: dispatch checklist 110–180k; stage C/D reviews 144k, 186k, 189k, 203k (orchestration doc); 150k − 20k for the plan no longer read |
| Fix round (2 in 3 reviewed groups) | 130k | **150k** | estimated | record: checklist 115–200k; engine fix rounds 105k, 181k, 193k |
| Rehearsal | 70k, own agent | **40k inside the last agent** | not measured | the only record (RH, stage C, 201k) also wrote 138 checks; in v2 the build group writes the steps, the host agent runs them on a copy and reports PASS counts |
| Opus phase review + fix | 300k + 140k | **180k + 150k** | estimated | record: Opus stage/step reviews 148k, 160k, 250k (orchestration doc); 200k − 20k |
| Final whole-design review + fix | 300k + 140k | **250k + 150k** | estimated | record: R2 Opus 250k |
| Shots pass | 80k | **120k** | estimated | record: S, Sonnet 240k for 38 shots; v2 shows the agent only shots whose bytes differ from `main` (§2) |
| Opus UI build | 240k (v1 6.14) | **320k** | estimated | record: checklist "Opus UI build 300–400k" |
| Live tests | 300k | 300k | not measured | v1's figure; no record |

### 1.2 The "~100k of shared docs" premise, measured

| What | Size | Kind |
|---|---|---|
| CLAUDE.md (loaded into every agent by the harness; a brief can't remove it) | 38 686 chars → 9.7k | measured |
| The auto-loaded memory index (same) | 15 827 chars → 4.0k | measured |
| What v1 §1.1 told a group to read beyond its material: v1 §1–§2 (10 451 chars) + its own section (~2.6k chars) | 3.3k | measured |
| v1 read whole | 20.7k | measured |
| The design read whole | 148 098 chars → 37.0k | measured |
| Harness, system prompt, tool list | — | not measured; the record's smallest Sonnet agent (Fix C, 49k, stage C) bounds harness + auto-loaded files + a small task from above |

So the premise is not supported as "shared docs": v1 told groups to read ~3k of shared text. The record (D3a) says
groups read their plan whole, notes and a code file in the first ~100k; the code file is the group's material, already
counted. v2 takes only the plan's 20.7k as removed (B row). Note: the Read tool counts v1 at 36.4k tokens where
`wc -c` / 4 gives 20.7k; table-heavy docs tokenise ~1.7× denser, so every `wc -c` / 4 figure here is low for tables.
It is kept as the brief's unit and not rescaled.

---

## 2. What v2 changes, against v1 and the design

| # | Change | Against | Why it keeps the goals | Saving |
|---|---|---|---|---|
| D1 | **Self-contained brief per group** (§4): the agent reads its brief and its files, never the plan or the design | v1 §1.1 | the brief carries the exact interface lines, design extracts, decisions and tests the group needs | B |
| D2 | **Generic call path**: one `call.run(entry, args)` for every entry kind (R, RJ, J, B), no handler per command; noun-verb commands generated from the catalogue for all 90 | v1 §1.3 "a command lands whole" (handler + text layout per command) | the catalogue still holds locks, `needs_yes`, dry run, `partial`, selection (§3) | D |
| D3 | **Generic text printer + "nothing hidden" appendix**: every page prints every field it doesn't place under "More"; hand-made pages only for library, to-do, sync, track (with cutoff), verdict and spectrum, runs | design §4.2, T7 (schema-based) | T7 becomes T7′: every leaf of `data` appears in the text with `--verbose`, on every read's fixture output; works without schemas (E7) | D |
| D4 | **`discjockey call <method> --args <json\|->`**: any method by its bridge name, through the same entry | design §2.2 (noun-verb only) | same entry, same safety (§3.2); noun-verb stays the documented form | — |
| D5 | **Flags generated from the method signature** (`track_ids` → `<ids>`, `dry_run` → `--dry-run`), overridden only where the design names a flag | v1 §2.2 (`Arg` per parameter by hand) | T1 unchanged: every parameter and dict key mapped (a default counts) and listed in `help` | in V1.1 |
| D6 | **Rehearsal inside the last agent** of a writer group (fix round, else the review) | v1 §4 (own agent) | G5: every writer group still gets its review and a rehearsal on a copy, after its fixes; PASS counts go into the report and the coordinator checks them by script. Loss: the rehearsal no longer runs in an agent that didn't write the fix | C |
| D7 | **Phase 6: per-cluster reviews only** | v1 §8 (both) | checklist line 6; the ratchet at zero and T4's ⌘A half are script checks in the last cluster's review | E |
| D8 | **Shots judged only where bytes differ from `main`** (a script compares `npm run verify`'s shots of both; check first in V5.2: renders are byte-stable) | v1 §8 (agent looks at every shot) | G2: an identical picture needs no eyes; every changed one gets them | in F |
| D9 | **The CLAUDE.md rule of G4 lands in V1.3** (text only); its check lands in V5.1–V5.2 with the seeded allow file | v1 (rule in 8.2) | the rule guards phases 1–4's window edits before the check exists | — |
| D10 | Phase 3 **recut** (7 → 4 groups) | design §16 "may split further, never merge" | the user's brief asks for merges; the recut follows the generic path's removed work; every other merge was tested and fails ~250k (§0) | D |
| D11 | Extras out of the base (§7) | v1, design §8.2–§8.4, §10.3, §6.6 | each named with its loss and the goal it touches | A |

---

## 3. The generic call path, and what each family gets

### 3.1 How a command runs

- **One runner.** `cli/call.py` `run(entry, args, flags) -> envelope`: R and B call the `HubApi` method in the
  client; RJ and J create a registry job and start the worker (V1.5); J-control writes the stop file. Nothing per
  command beyond the catalogue row. The parser, `help --json`, T1, T2 and T8 all read the same `ENTRIES`.
- **What stays hand-made, because it adds safety or meaning:** the selection forms (`<ids>|-|--all|--rows`,
  `--in`, `--todo`, `check done --batch`; §7.3), `--dry-run` (the entry's `dry_run` method, never the write with a
  flag), `--plan`, `--yes` (`needs_yes` from the catalogue, the window's question in `message`), person steps
  (engine data, printed as "Your turn:" lines), the job client (`--wait`, `--detach`, `--jsonl`, Ctrl-C).
- **Text.** `render/generic.py` turns any payload into a page: a headline (`message`, else the payload's
  `headline` or first `*_text`), scalars as label/value rows (a `<fact>` with a `<fact>_text` prints the words; the
  raw fact only with `--verbose`), lists of objects as tables in payload order (`--limit` 200, `--offset`, a count
  line), nested objects as sections. A hand page names the fields it places; `generic.rest(payload, placed)` prints
  the others under "More". Labels are field names in words until E1 gives the window's labels.
- **T7′ (replaces schema-based T7):** for every read entry on the hub fixtures, every leaf value of `data` (formatted
  as the printer formats it) occurs in the text output with `--verbose`; pages may reorder and word, never drop.
- **T4 parity** is one parametrised test over every live read entry (bridge answer minus `ok` and URL keys ==
  `--json` `data`); each entry's `example` gives the fixture arguments.

### 3.2 `call <method>`: the same entry, never a way around it

| Rule | Behaviour |
|---|---|
| Same path | `call upgrade --args '{"track_ids": [...], "mode": "same_track"}'` runs the `upgrade apply` entry: worker, locks, `--dry-run`, `--plan`, `--wait`; the result envelope names `command: "upgrade apply"` |
| Confirmation | an entry with `needs_yes` refuses without `--yes` (`refused`, `needs_yes`), as the noun-verb form |
| Not offered | `WINDOW_ONLY` (`pick_folder`, `quit`) and `DROPPED` methods → `bad_args`, `usage`, naming the reason; an entry still `planned` → `bad_args`, `usage`, "not built yet" |
| Secrets | an `Arg` marked `secret` (`setup_qobuz_login.password`) is refused inside `--args`; it comes only from `--password-stdin` |
| Arguments | the bridge's parameter names and shapes (`docs/hub-bridge-contract.md`), so an agent can send the window's exact payloads; unknown keys → `bad_args`, `usage` |
| T3 | `call` is a housekeeping module that only calls `call.run`; T2 counts it |

### 3.3 Per family: what an agent and a person get

| Family | Commands | Agent (`--json`) | Person (text) | Built |
|---|---|---|---|---|
| Discovery | `help`, `where`, `status`, `doctor`, `history` | envelope; `help --json` index with args, flags, writes, job kind, reasons, an example | short help, pages | V1.3, V3.2, V3.3 |
| Screens with a hand page | `library list`, `todo list` (+ `upgrade list`, `check list`), `sync plan`, `track show`, `track spectrum`, `report list/show`, `history` | the bridge's payload whole in `data` | the window's headings, verdict and cutoff sentences, quality words, "Your turn:" lines, then "More" | V1.8, V3.4 |
| Other reads | `library collections`, `folder list/check`, `limits show`, `playlist list/check`, `login list/find`, `setup status`, `tools status`, `app info`, `rekordbox status/preview/backups/match`, `batch list/show`, `job list/show`, `import status` | the same | generic page | V1.2, V1.9, V3.1–V3.3 |
| Pictures | `track spectrum`, `limits show` | `cols`, `matrix`, `cutoff_hz`, `verdict`; `days[]`, `zones[]` | verdict line, cutoff sentence, 22×64 sketch, waveform sparkline, a bar per day; PNG only with E6 | V3.4 |
| Jobs | `job list/show/follow/wait/stop`, `--wait`, `--detach`, `--jsonl` | job id first, `running` (exit 8), events | today's console progress lines | V1.4–V1.6 |
| Bulk writes | `upgrade apply/discard`, `aiff convert/rename`, `check done`, `track hide/unhide/never/download/undo`, `tidy run`, `batch resume/undo`, `duplicate keep`, `question answer` | dry run with `plan_id`, `--plan`, per-item `results` with reasons, `partial` | results table and counts | V1.10–V1.13, V4.x |
| Single writes | `settings set`, `limits set/seen`, `login …`, `playlist …`, `folder add/remove/crates`, `setup …`, `tools …`, `sync scope`, `library favourites`, `rekordbox restore` | the same envelope; person steps (`step:sign_in`, `step:keychain`, …) | generic page | V1.12, V1.14, V2.5, V4.x |
| Any method | `call <method>` | the window's argument shapes | generic page | V1.2 |

---

## 4. Rules every group follows

### 4.1 The self-contained brief

A brief is a file the coordinator's brief writer makes (V1.0 for phase 1; the detailing run for later phases). It is
the only text the group reads besides CLAUDE.md (already loaded) and its files. Every brief has these parts:

| Part | Content | Source |
|---|---|---|
| 1 Goal and stop | one deliverable; "when it is committed and green, report your size and stop" | this plan |
| 2 Interfaces | the exact v1 §2 lines the group uses or makes (names, signatures, shapes), nothing else | v1 §2 |
| 3 Design extracts | the design sections the group's row names, copied with their § numbers | the design |
| 4 Decisions and tests | v1 §3's decisions, check-firsts and behaviours-to-pin table for the group, with this plan's changes applied | v1 §3, this plan |
| 5 Files | touched files; files to read, with `grep -n` targets and line budgets for `api.py`, `views.py`, `db.py`, `library.py`, `rekordbox_rehearsal.py`, the contract doc, `types.ts`, the fake | this plan |
| 6 Change and green rules | v1 §1.2 and §1.3 copied (contract in one commit, legacy words leave with every caller, invariants), the public check before every commit | v1 §1 |
| 7 Don'ts | don't open the plan or the design; no dev server, no shots, no real library, no `pgrep`/`sleep` loops; leave no process (`ps` for `job _worker` at the end) | checklist |

### 4.2 Stop point, models, overruns

- **Stop: "committed and green"** = touched tests while working, the full Python suite once at the end
  (`uv run pytest -q | tail -3`), `npm run check` and the touched vitest files when `hub-ui/` changed, the public
  check; `npm run verify` only once per phase branch, by the coordinator, in the background.
- Sonnet for every build group the design decided; Opus only for the phase reviews and the final review (and E4's
  component). Every group is planned under ~250k; the record says Sonnet groups land up to 1.5× plan, so a group past
  ~300k stops at its next green commit and the rest goes to a fresh agent with its findings.
- Branches as v1 §6 (`feat/cli-<phase>-<topic>`, group worktrees `.claude/worktrees/cli<phase>-<n>`).

---

## 5. Phase 1 in full: the CLI slice the A–D live tests need

Branch `feat/cli-1-live-slice`; one group at a time, in this order; v1 §3's reorder against §16 (the window's side of
the registry waits for phase 2) stands. Each group's v1 "Touches" and "Reads" cells stay its file lists (the brief
copies them), minus the design reads, which its brief carries. **Material** = the v1-measured files (`wc -c` / 4;
`~` = targeted ranges of big files, v1's figures) + the brief (design extracts measured by `wc -c` of their lines,
+ ~2k interface lines, estimated). **Size** = 80k + 1.5 × material + v1's work ± §3's changes (estimated, §1.1).
**Stop** for every group: committed and green (§4.2), size reported.

### V1.0 Phase 1's briefs (Sonnet, 210k)

Writes `V1.1.md` … `V1.15.md` into the coordinator's brief folder (outside the repo), each with §4.1's parts. Material: v1 §2–§3 (47 172 chars → 11.8k), design §2–§7 (66 745 chars → 16.7k), §10.1 and §15 (~3.4k), this
plan §3–§5 (~8k) ≈ 40k; output ~15 × 4–5k. Check after it (coordinator, script): each brief has the seven parts,
names only files that exist, and is ≤ 8k tokens. Not in v1's total (v1's groups read the plan instead): row B pays it.

### V1.1 Answers, ids and the catalogue (v1 1.1) — Sonnet, 205k

| | |
|---|---|
| Goal | outcome, reason, `next`, person steps on every engine answer; typed ids; the catalogue of all 95 methods |
| Design | §3, §4.3, §5.2 (whole table), §8.1 (catalogue, outcomes), §10.1, §13 T1 T8 |
| Change vs v1 | `Arg` defaults come from `inspect.signature` (D5): the flag is the parameter in words, a list parameter is the positional ids; the entry overrides only the design's named flags (`filter` → `--group`, `show_hidden` → `--hidden`, `mode` → `--way`, …); `Arg.secret`; every R entry gets an `example` with fixture arguments (V1.8 and V3.1 run them) |
| Material | files 20k (`ops.py`, `jobs.py`, `api.py` `bridge` + `@bridge` list, `rekordbox/lock.py`, `test_hub_dispatch.py`, `contract.ts`, the contract doc's problem part) + brief 10k (§5.2 13 161 chars, §4.3 6 327, §3 4 070 → 5.9k measured; §10.1, T1/T8, interfaces) = **30k** |
| Review | phase review only (writes no user data) |

Brief outline: interfaces of v1 §2.1 (`outcomes.py`, `ids.py`, `catalog.py` rows), §2.2 (the entry, with `secret`),
§2.3 (`OpProblem`, the decorator's added keys); v1 1.1's tests (T1, T8 engine half, ids, bridge) and its check-first
(Python kinds vs `PROBLEM_KINDS`); plus: "a default flag counts as mapped; T1 lists it in `help`".

### V1.2 The CLI frame, the generic path and `call` (v1 1.2) — Sonnet, 230k

| | |
|---|---|
| Goal | `discjockey/cli/` with the generated parser, envelope, exit codes, headless `HubApi`, legacy routes; **`call.run`** for R and B; **`render/generic.py`** with `rest()`; **`call <method>`** (§3.2); first read `rekordbox status` |
| Design | §2.2, §4.1, §4.2, §8.1 (CLI adapter, T3), §12 (legacy rows) |
| Change vs v1 | no `render/rekordbox.py` (generic page); + the T7′ harness (§3.1) and the golden harness (one parametrised test, `tests/cli_golden/<noun>_<verb>.txt`); + `call` with its four refusals; `rekordbox status`'s C7 fields stay in V1.9 |
| Material | files 27k (`cli.py` 4.4k, `rekordbox_cmd.py` 1.7k, `hub/app.py` 2.1k, `api.py` init/attach ~2k, `test_cli.py` 11.7k, `bin/discjockey`, V1.1's modules ~5k) + brief 6k = **33k** |
| Review | phase review |

Brief outline: v1 1.2's decisions (headless bind, `remember=False`, routing per (noun, verb), text pages) and tests
(T2, T3, global flags, crash, first read, legacy); §3.1–§3.2 of this plan copied; the envelope's key order (§4.1).

### V1.3 Discovery, the app binary, the G4 rule's text (v1 1.3) — Sonnet, 185k

| | |
|---|---|
| Goal | `help`, `help --json`, `help <noun> [<verb>]`, `where`, `as_of`; app routing (§2.1) with `app open`; the self-test round trip; CONTRIBUTING's short section; **CLAUDE.md's tests rule rewritten for G4** |
| Design | §2.1, §2.3, §4.1 (`as_of`), §10.2, §13 T12; §9.1 (the rule's words) |
| Change vs v1 | + CLAUDE.md line 177: "UI logic in a pure `*Model.ts`" becomes "the window computes no fact, decision or state (§9.1); a `*Model.ts` only formats what the engine sent; the `derive` and `flows` checks enforce it from phase 5; new engine logic gets its tests in `tests/`" (D9) |
| Material | files 22k (`app_main.py`, `selftest.py` 2.9k, `test_app_main.py` 1.1k, `test_selftest.py` 3.4k, `library.resolve_paths` ~1.5k, CONTRIBUTING lines 26–326 6.2k, V1.2's `cli/` ~6k) + brief 4k = **26k** |
| Review | phase review |

### V1.4 The job registry and string job ids (v1 1.4) — Sonnet, 195k

| | |
|---|---|
| Goal | `hub/registry.py` (v1 §2.4), the `CancelToken` stop file, `job:<8 hex>` everywhere (contract change), `where.jobs_running`; `result.json` is the record the window's recent toasts read later (§9.2) |
| Design | §6.2, §6.4, §6.5 |
| Material | files 19.5k (`events.py` 1.8k, `jobs.py` ~3k, `write_json_atomic`, `test_events.py` 0.9k, `test_hub_events.py` 0.7k, hub-ui id users ~6k) + brief 3.5k = **23k** |
| Review | phase review |

### V1.5 The worker (v1 1.5) — Sonnet, 215k (the riskiest group)

| | |
|---|---|
| Goal | `job _worker <id>` that outlives the client; inline `Jobs`; signals; `--wait-busy`; first write `library scan`; **`call.run` for J** |
| Design | §6.3, §6.1 (write job's lock), §2.1 (`caffeinate`) |
| Material | files 19k (`jobs.py` `Jobs` ~6k, `deferred_interrupt` + `run_lock` ~2k, the two Ctrl-C helpers ~1.5k, V1.4's registry ~5k, `test_hub_jobs.py` 5k) + brief 3k = **22k** |
| Review | phase review; if a Sonnet run stalls, the coordinator re-runs it as Opus (+~100k, est.) |

### V1.6 The job client and the `job` noun (v1 1.6) — Sonnet, 195k

| | |
|---|---|
| Goal | the wait defaults, `--detach`, `--wait S`, the first stderr line, `--jsonl`, Ctrl-C, `job list/show/follow/wait/stop [--now]`; RJ through the worker without locks |
| Design | §6.4, §6.5, §4.1 (`--jsonl`), §4.3 (`running`, `not_running`, `window_job`, `worker_lost`) |
| Material | files 10.5k (`console.py` 1.9k, V1.4/V1.5 modules ~8k, `_ctrl_c` ~1k) + brief 3.5k = **14k** |
| Review | phase review |

### V1.7 Locks across processes (v1 1.7) — Sonnet, 185k

| | |
|---|---|
| Goal | the support lock; rekordbox readers shared and non-blocking; the `locks` column of every built entry (T10 table); `tools update/rollback` refused during a write job |
| Design | §6.1 (2 817 chars) |
| Material | files 22k (`settings.py` 3.1k, `rekordbox/lock.py` 0.4k, `master.py` open ~3k, `tool_updates.py` ~2k, `test_settings.py` 3.3k, `test_rekordbox_session.py` 1.5k, `api.py` settings users and `_rekordbox_status` ~4k, `lock_briefly` ~1k) + brief 3k = **25k** |
| Review | **own Sonnet review** (writes settings, config and logins); rehearsal in its last agent: a scratch support folder with a copy of the real `settings.json` (no login files), two processes saving at once, a fixture writer during a reader |

### V1.8 Reads I: To-do, tracks and checks (v1 1.8) — Sonnet, 210k

| | |
|---|---|
| Goal | `todo list [--group G] [--hidden]`, `upgrade list`, `check list`, `track show`, `track find`; the check's person step in the engine; **hand pages** for to-do and track (verdict, cutoff sentence, quality words, then `rest()`); the T4 parity harness |
| Design | §3, §4.2, §5.2 rows `todo`, `track`, §10.1, §13 T4 |
| Material | files 22k (`api.py` `todo`/`_todo`/`track` ~4k, `views.py` `todo`/`track_detail`/`check_view` ~8k, `report.check_text` ~1k, `decisionModel.ts` check helpers ~3k, `test_hub_api.py` ~2k, `hub_helpers.py` 3.2k) + brief 5k = **27k** |
| Review | phase review |

### V1.9 Reads II: rekordbox, batches, reports (v1 1.9) — Sonnet, 180k

| | |
|---|---|
| Goal | `rekordbox preview` (C7 entry columns), `rekordbox status` (`modified_at`, `size`, `problem`, `version`), `batch list/show` for both kinds, `report show <report\|last>`; `rekordbox_cmd.py` deleted |
| Change vs v1 | generic pages; no `render/rekordbox.py`, `render/batch.py`, `render/report.py` (−15k work, est.); the runs page comes in V3.4 |
| Material | files 17k (`preview.py` 2.8k, `rekordbox_cmd.py` 1.7k, `master.Status` ~1k, batch queries ~3k, `batch_cmd` list/show ~2k, `api.py` `move_batches`/`run`/`runs` ~2k, `run_detail` ~2k, `test_rekordbox_preview.py` 3.3k) + brief 4k = **21k** |
| Review | phase review |

### V1.10 Dry runs, plans and selection (v1 1.10) — Sonnet, 205k

| | |
|---|---|
| Goal | `plan_store`, `--plan`, `--yes`/`needs_yes`, read-only dry runs (`?mode=ro`), `HubApi.select(listing)` (L D15's engine half), `upgrade_preview` |
| Design | §7.1, §7.2, §7.3, §13 T9 (dry-run half) |
| Material | files 15k (`db.connect` ~2k, `open_state` ~1k, `batch_cmd` dry run ~3k, `views.library`/`_matches`/grouping ~4k, `api` signatures ~2k, `select_actions` ~1k, `test_aiff_plan.py` ~2k) + brief 5k = **20k** |
| Review | phase review (it writes only `<support>/plans/`) |

### V1.11 Writes A1: upgrades, track undo, checks (v1 1.11) — Sonnet, 185k

| | |
|---|---|
| Goal | `upgrade apply`, `upgrade discard`, `track undo`, `check done` on V1.10's plans and selection; the mode enum `same_track\|new_track\|discard` (contract) |
| Change vs v1 | results through the generic results table (no `render/upgrade.py`, `render/check.py`; −8k work, est.) |
| Material | files 23k (`api.py` upgrade/undo/checked ~5k, `batch_cmd` apply/discard/undo/checked ~5k, `test_batch_cmd.py` ~6k, `test_hub_api_batches.py` 4k, hub-ui mode callers ~3k) + brief 6k = **29k** |
| Review | **own Sonnet review**; its rehearsal runs with V1.12's |

### V1.12 Writes A2: batches, backups, legacy removal (v1 1.12) — Sonnet, 200k

| | |
|---|---|
| Goal | `batch resume aiff:<n>`, `batch undo aiff:<n> --yes [--dry-run]`, `rekordbox backups`, `rekordbox restore <backup> --yes [--dry-run]`; schema 10 `via`; real scopes; `batch_cmd.py`, `upgrades_cmd.py` deleted with every caller |
| Material | files 33k (`batch_cmd.py` ~5k, `batches.py` ~3k, `db.py` schema ~4k, `backup.py` 3.6k, `upgrades_cmd.py` 2.2k + test 3.7k, `test_batch_cmd.py` ~6k, `rekordbox_rehearsal.py` `rehearse` ~5k) + brief 4k = **37k** |
| Review | **own Sonnet review**; **rehearsal on a copy for V1.11 + V1.12** in the last agent: `rekordbox_rehearsal.py copy-db / copy-tracks / rehearse` on a copy of the user's rekordbox library, rekordbox closed, all PASS |

### V1.13 Writes B: AIFF and file facts (v1 1.13) — Sonnet, 210k

| | |
|---|---|
| Goal | `aiff convert`, `aiff rename` in every selection form, dry runs that write nothing (≤ 50 facts in memory, `facts_missing`), `library facts`; `HubApi.resolve("collection")` (L D1's engine half); `convert_cmd.py` deleted |
| Material | files 31k (`convert_cmd.py` 4k, `fill_facts` ~1.5k, `aiff_plan.plan` ~2k, `api.py` AIFF methods ~5k, `test_convert_cmd.py` 9.5k, `test_hub_api_convert.py` ~3k, `rehearse-convert` ~4k) + brief 4k = **35k** |
| Review | **own Sonnet review**; rehearsal on a copy: `rehearse-convert` all PASS |

### V1.14 Writes C: folders, settings, the Auto-upgrade phase alone (v1 1.14) — Sonnet, 215k

| | |
|---|---|
| Goal | `folder add`, `folder remove` (`--dry-run`, `--yes`), `settings show`, `settings set auto-upgrade on\|off`, `sync run --auto-upgrade-only [--dry-run]` (never the planner); `settings_cmd.py` deleted |
| Material | files 28k (`auto_upgrade.py` ~3k, `run.py` phase and report ~3k, `report.py` ~2k, `folders.py` 3k, `settings_cmd.py` 0.9k, `api.py` folder/rescan/settings ~4k, `test_hub_auto_upgrade.py` 5.5k, `BeforeStart.svelte` ~1.5k, `rehearse-sync` ~4k) + brief 4k = **32k** |
| Review | **own Sonnet review**; rehearsal on a copy: `rehearse-sync` all PASS |

### V1.15 The live-test kit (v1 1.15) — Sonnet, 165k

| | |
|---|---|
| Goal | `scripts/make_upgrade_test.py --click …`, the `(upgrade test)` marker, `--clean <entry>\|--all-marked` (to the Trash, never `unlink`) |
| Material | files 12k (`make_upgrade_test.py` 2.5k, its test 1.7k, `audio_helpers.py` 1.0k, the stage plans' live-test sections ~6k) + brief 4k = **16k** |
| Review | **own Sonnet review** (moves the user's files to the Trash); rehearsal on a scratch library: make, import, upgrade, `--clean` |

### Phase 1 at a glance

| Group | Size | Own review | Rehearsal (in the last agent) |
|---|---|---|---|
| V1.0 briefs | 210k | — | — |
| V1.1–V1.6, V1.8–V1.10 | 205 + 230 + 185 + 195 + 215 + 195 + 210 + 180 + 205 = 1 820k | — (phase review) | — |
| V1.7 | 185k | yes | scratch support, two processes |
| V1.11, V1.12 | 185k + 200k | yes, yes | `rehearse` on a copy (once, for both) |
| V1.13 | 210k | yes | `rehearse-convert` on a copy |
| V1.14 | 215k | yes | `rehearse-sync` on a copy |
| V1.15 | 165k | yes | scratch library |
| **Build** | **3 190k** | 6 × 130k = 780k; 4 fixes × 150k = 600k | 5 × 40k = 200k |
| Opus phase review + fix | 180k + 150k (over V1.1–V1.6, V1.8–V1.10, and T1–T3, T7′, T8–T10 whole) | | |
| **Phase 1** | **5 100k**, then the live tests (v1 §7, unchanged) 300k | | |

**Per group: design, files touched, and what its brief carries** (parts 2–4 of §4.1; part 5 = v1's "Touches" and
"Reads" cells ± the change named; parts 1, 6, 7 are the same for all):

| Group | Design (copied into the brief) | Touches: v1's cell ± | Brief carries besides |
|---|---|---|---|
| V1.1 | §3, §4.3, §5.2, §8.1, §10.1, §13 T1 T8 | v1 1.1 + `Arg.secret`, signature defaults | v1 §2.1–§2.3; v1 1.1's tests, check-first; D5 |
| V1.2 | §2.2, §4.1, §4.2, §8.1, §12 | v1 1.2 − `render/rekordbox.py` + `render/generic.py`, `cli/call` command, T7′ and golden harnesses | v1 1.2's decisions and tests; this plan §3.1–§3.2 |
| V1.3 | §2.1, §2.3, §4.1, §9.1, §10.2, §13 T12 | v1 1.3 + CLAUDE.md line 177 | v1 1.3's decisions and tests; D9's rule text |
| V1.4 | §6.2, §6.4, §6.5 | v1 1.4 | v1 §2.4; v1 1.4's tests |
| V1.5 | §2.1, §6.1, §6.3 | v1 1.5 + `call.run` J path | v1 §2.4; v1 1.5's decisions, tests, check-first |
| V1.6 | §4.1, §4.3, §6.4, §6.5 | v1 1.6 + RJ path | v1 1.6's tests |
| V1.7 | §6.1 | v1 1.7 | v1 1.7's tests; the rehearsal steps for the last agent |
| V1.8 | §3, §4.2, §5.2 (`todo`, `track`), §10.1, §13 T4 | v1 1.8; `render/todo.py`, `render/track.py` on `rest()` | v1 1.8's decisions, check-first, tests; T4 as a parametrised harness |
| V1.9 | §3, §5.2 (`rekordbox_status`, `move_batches`, `run`), §5.3 | v1 1.9 − the three render modules | v1 1.9's tests |
| V1.10 | §7.1, §7.2, §7.3, §13 T9 | v1 1.10 | v1 §2.5; v1 1.10's decisions, check-first, tests |
| V1.11 | §4.3 (R24, R29), §4.4, §5.2 (`upgrade`, `upgrade_all`, `undo_upgrade`, `rekordbox_checked`), §7.2, §7.4, §12 | v1 1.11 − `render/upgrade.py`, `render/check.py` | v1 1.11's decisions and tests |
| V1.12 | §5.2 (`batch_resume`, `batch_undo`), §6.6, §7.4, §12 | v1 1.12 | v1 1.12's tests; the rehearsal for V1.11 + V1.12 |
| V1.13 | §5.2 (`aiff_plan`, `convert`, `rename`, `make_aiff`), §5.3, §7.1, §9.3 L D1 | v1 1.13 | v1 1.13's tests; `rehearse-convert` |
| V1.14 | §5.2 (folder, `set_auto_upgrade`, `start_sync`), §6.1, §15 C | v1 1.14 | v1 1.14's decisions, check-first, tests; `rehearse-sync` |
| V1.15 | §10.1, §15 Clean-up | v1 1.15 | v1 1.15's tests, check-first; the scratch-library rehearsal |

**§15 against phase 1** (every command the A–D tables and v1 §7's runbook use, and its group): `where` V1.3;
`rekordbox status` V1.2 (+C7 fields V1.9); `rekordbox preview --path` V1.9; `folder add`, `folder remove --yes`,
`settings set auto-upgrade`, `sync run --auto-upgrade-only [--dry-run]` V1.14; `library scan` V1.5; `job wait/stop`,
`--wait 90`, `--detach` V1.6; `upgrade list`, `check list`, `todo list --group upgrade_ready|cdj`, `track find`,
`person_steps` V1.8; `batch show`, `report show last` V1.9; `--dry-run`, `--plan`, `-` from stdin V1.10;
`upgrade apply [--all] --way`, `track undo --yes` V1.11; `batch resume`, `batch undo --yes` V1.12; `aiff convert
--all --in folder:|--todo cdj|<track>` V1.13; `make_upgrade_test.py --keep-lossy|--click|--clean` V1.15.

---

## 6. Phases 2–8: groups with sizes

A later run details each phase (and writes its briefs) after the user's go. Sizes: 80k + 1.5 × material + work, where
a group carries a v1 group over its size is v1's − 17k ± the named change; new cuts are estimated from v1's measured
material for the same files. Sonnet unless named.

### Phase 2: foundations (2 390k)

| # | Group | From | Design | Size | Review |
|---|---|---|---|---|---|
| V2.1 | Window on the registry, engine: window jobs registered (`via: window`), the registry watch replaces `watch_console` (the probe kept for a holder with no entry), `JobFinished` for terminal jobs from `result.json` (the window re-reads; recent toasts from `result.json`), `ConsoleBusy` gains kind and `line` (the banner keeps today's words; E9 shows them), window files and `where.windows_open`, `job stop` reaching window jobs | v1 2.1 | §6.3, §6.6, §9.2 | 200k | phase |
| V2.2 | Stored read, derived plan: `playlist_reads`/`playlist_tracks` widened, one transaction keeping the newer read, the plan derived and cached per (read id, generation, settings hash), `PreviewStore` reduced (its `auto_read` stays); questions and same-song duplicates derived from it | v1 2.6 | §9.2 | 225k | **own + rehearsal** (a copy of the real library.db: derived plan == today's) |
| V2.3 | Plan binding: `sync plan` with `plan_id`, `presets`, `default_how_many`; `start_sync(plan_id, selected)`, `new_since_plan`; the Sync page sends its plan id; `sync.lastSelection` → the job's args | v1 2.7 | §9.2, §7.1 | 195k | phase |
| V2.4 | `rev` replaces `_shown`: reads print `rev`, writes take `expect`/`--if-rev`, the window sends it; V1.2's `remember=False` removed | v1 2.8 | §3 | 205k | phase |
| V2.5 | Other persisted state: `FileDropped` path + `add_bought_file(track_id, path)`, `folders.keep_file` (L D10 engine), the three dropped methods removed, `sync_scope` in settings + `sync scope show\|on\|off` + `syncScope.ts` off localStorage (U1), import state in library.db | v1 2.9 | §9.2, §9.3 L D10, U1 | 215k | **own + rehearsal** |
| V2.6 | Shared protection: `SharedPacer` (`pace.json`/`pace.lock`), the streak in `usage` rows, the pause cleared at a sync's start, paced searches skipping a paused Qobuz, `_qobuz_streak`/`_account_streaks` deleted, `sync_running` from the registry; T13 | v1 2.10 | §7.5 | 210k | **own + rehearsal** (fake services only) |

Build 1 250k; own reviews 3 × 130k, fixes 2 × 150k, rehearsals 3 × 40k; Opus phase review + fix 330k (V2.1, V2.3,
V2.4 and the whole phase). No shots: no screen changes (`npm run verify` before the merge catches any).

### Phase 3: every other read (1 230k)

| # | Group | From | Size |
|---|---|---|---|
| V3.1 | **Every bridge read live** through the generic path: `library list/collections`, `folder list/check`, `folder remove --dry-run`, `tidy run --dry-run`, `batch undo moves:<n> --dry-run`, `job_status`, `track spectrum --json`, `status`'s Dashboard part, `report list`, `sync plan [--search]`, `limits show`, `limits set --dry-run`, `playlist list`, `playlist check` (RJ), `login list/find`, `setup status`, `app info`, `setup music --dry-run`, `tools status`, `open file\|folder\|url\|report\|licences\|privacy-settings`; paging (`--limit`, `--offset`, `total`, `next_offset`), `--since` (`today`, `yesterday`, `<n>d`, `<n>h`, ISO); each entry's `example`, T4 parity and T7′ over all of them. Material: catalogue ~8k, `hub_helpers.py` 3.2k, `test_hub_api.py` 5.0k, `api.py` R signatures ~3k, `views.library` paging ~3k, brief 5k ≈ 27k | v1 3.1, 3.5, 3.6 (plain reads) | 225k |
| V3.2 | `status` (Dashboard + nav counts + running jobs + live person steps), `doctor` (every check of §5.3, `folder_access`), `status --ready` (a filter of doctor's), `app info --check` (C8) | v1 3.3, 3.4 (doctor), 3.6 (check) | 235k |
| V3.3 | `history` (reports, batches, the operations log; `undo`/`cant_text`), `library superseded`, `rekordbox match [--in C]`, `todo list --group` taking several groups (contract change) | v1 3.4 (history), 3.7, 3.1 (superseded) | 230k |
| V3.4 | **Hand pages**: `library list`, `sync plan`, `track spectrum` (verdict, cutoff sentence, 22×64 sketch, waveform sparkline), `report list/show` and `history` (runs); each on `rest()` | v1 3.1, 3.2 (text), 3.3 (pages) | 210k |

All read-only: one Opus phase review + fix 330k. `--png` is E6. `offer`, the six setup steps, the zone table (C9) and
`import status` are §9.3 rows and land in phase 6.

### Phase 4: every other write (3 675k)

| # | Group | From | Size |
|---|---|---|---|
| V4.1 | The whole sync: `sync read`, `sync run [selection] [--plan] [--how-many]` (`partial` only for `failed`), the legacy sync and `cli/legacy.py` deleted, `bin/discjockey` without `caffeinate` | v1 4.1 | 225k |
| V4.2 | Playlist writes `add/remove/rename/move/enable/disable/edit --file/add-liked`; `playlists_file.apply(lines, op)` + `validate` (U25, U26 engine half); `--if-version`; changes logged for `history` | v1 4.2 | 185k |
| V4.3 | The save question (C1): `--files move\|leave`, `--rename`, `--no-rename`, `--move`, `--no-move`, ids in the dry run, `--plan` binding a subset | v1 4.3 | 190k |
| V4.4 | `tidy run [--all\|--with-yours\|--plan]`, `batch undo moves:<n>`, `import run` | v1 4.4 | 185k |
| V4.5 | `question list/answer`, `duplicate list/keep` (on `keep_file`) | v1 4.5 | 170k |
| V4.6 | `version search/preview/use/reject/add-file` (shared pacer; `busy` while a sync runs anywhere), `track hide/unhide/never/download` | v1 4.6 | 195k |
| V4.7 | Accounts: `login use`, `login sign-in` (person job, live `step:sign_in`, `step:keychain`), `check`, `sign-out --yes`, `skip`, `qobuz --password-stdin`, `spotify`; `setup_cmd.py` deleted | v1 4.7 | 210k |
| V4.8 | `settings set` (the rest), `limits set/seen`, `tools update/rollback`, `setup music [--yes]`, `setup skip-import`, `library favourites …`, `folder crates …`, setting changes logged for `history` (v1 3.4), **`app install-command`** (§2.1; in no v1 group); legacy `update` deleted | v1 4.8 | 205k |

Every group writes the user's files, playlists.txt, library.db or settings: own review each (8 × 130k), fixes
5 × 150k, a rehearsal on a copy or scratch support folder in the last agent each (8 × 40k; V4.6 and V4.7 with fake
services and no real login). Each group's work is v1's − 15k (no handler or render module per command, est.), V4.1
excepted (its page is V3.4's). No phase review (as v1).

### Phase 5: the G4 check (735k)

| # | Group | From | Size |
|---|---|---|---|
| V5.1 | `derive` (type-aware through `svelte2tsx` and the TypeScript compiler), the `view()` marker, `derive-allow.json` seeded with today's debt (closed reasons) and §9.3's "stays in the window" rows as view entries | v1 5.2 | 230k |
| V5.2 | `flows` (one handler, at most one bridge write) and its seeding (L D10 as `debt`); the ratchet test (`debt` entries only shrink); CLAUDE.md's tests rule points at both checks (V1.3 wrote its text); the byte-compare script for phase 6's shots (check first: two `npm run verify` runs of one commit give identical bytes). Material: `rules.mjs` 2.0k, `rules-page.js` ~2k, handler sample ~8k, brief 4k ≈ 16k | v1 5.3 (flows half) | 175k |

Opus phase review + fix 330k. The word catalogue (E1), the rendered check (E2) and mount coverage (E3) are extras.

### Phase 6: §9.3 into the engine (4 670k)

Six clusters, each two Sonnet groups: the engine fields with tests and the fake, then the window switched to them with
its `debt` entries removed and words identical. Per cluster: one Sonnet review (130k), a fix round for about four
(150k), a shots pass on the shots whose bytes changed (120k). No Opus phase review (D7). Rows per cluster: §8.2.

| Cluster | Engine | Window | Notes |
|---|---|---|---|
| V6.1–V6.2 Library | 205k | 220k | + the "Deleted" components |
| V6.3–V6.4 To-do decisions and upgrades | 205k | 215k | |
| V6.5–V6.6 To-do checks, batches, AIFF | 205k | 215k | the numbered check steps replace V1.8's one step |
| V6.7–V6.8 Sync and Dashboard | 220k | 235k | + U17, U18, U19 and U9 (in no v1 cluster), +15k each |
| V6.9–V6.10 Limits and Playlists | 200k | 215k | the one zone table (C9) |
| V6.11–V6.12 Settings, Setup, import | 210k | 225k | + `import status` (from v1 3.1), +10k each |

Build 2 570k; reviews 780k; fixes 600k; shots 720k.

### Phase 7: the sandbox (1 205k)

| # | Group | From | Size |
|---|---|---|---|
| V7.1 | The root guard: `SupportPaths`, `Paths`, `rekordbox.locate` resolve only inside a sandbox; `outside_sandbox` at resolve; the write layer's second line; `DISCJOCKEY_REQUIRE_SANDBOX` | v1 7.1 | 215k |
| V7.2 | `sandbox create --from empty [--rekordbox none\|<fixture>]`, `sandbox info`, `sandbox remove --yes` with every refusal (`exists`, `protected`, `not_sandbox_content`); no accounts in a sandbox; T9's sandbox cases for these | v1 7.2 minus `--from real` (−50k, est.) | 170k |

Both write (`remove` deletes): own review + rehearsal each (2 × 130k, 1 fix 150k, 2 × 40k); Opus phase review + fix
330k. The clones of the real library and rekordbox are E5.

### Phase 8: docs and the final review (750k)

| # | Group | From | Size |
|---|---|---|---|
| V8.1 | `AGENTS.md`, `help agents`, `help concepts`, `help --markdown` → `docs/agent-commands.md`, T11 | v1 8.1 | 195k |
| V8.2 | README "Let an AI agent run Discjockey", CONTRIBUTING's pointer, CLAUDE.md "Agent-ready" rewritten to point at T1–T5, T7′–T13, `docs/issues.md` (the MCP note unless E8), the plans, design and audits archived | v1 8.2 | 155k |

Then the Opus whole-design review (250k) and a fix round (150k), and the final `npm run verify`.

---

## 7. The extras (the user ticks them)

Prices at v2's units (§1.1): the group(s), plus a share of the phase's review where one exists, else an own review and
a fix; shots where the window changes. "Goal" says whether a goal needs it.

| # | What it is | Price | What the user loses without it | Goal | Needs |
|---|---|---|---|---|---|
| E1 | **The word catalogue**: `hub-ui/scripts/words.mjs` in the build, `words.json` (CI-fresh), `fill()` in Python and TypeScript with one fixture, `help glossary`, the window's labels in text pages (v1 5.1) | 235k (205k + review share) | The CLI has every fact and every data word, but not the window's **fixed** words: tooltips, explanations, headings, column names; text pages label fields by name | **G3, strictly** ("everything the window shows" includes tooltips) | — |
| E2 | **The rendered check (T5b)**: blocks emit `data-item/-tone/-dim/-badge/-list`, the fake records each shot's reads, every visible string traced to a payload or `words.json` (v1 5.4) | 380k (230k + shots 120k + review share) | `derive` (V5.1) is static: template strings, enum keys printed as words, SVG `<text>`, CSS `content:` can slip past it; nothing then fails | G4 partly (closes the static check's known holes) | E1 |
| E3 | **Mount coverage** and every `shots.json` entry declaring `reads` or `view` (v1 5.5's half, v1 5.3's declarations; `shots.json` files ~35k measured by v1) | 245k | A new component without a shot escapes E2 | only with E2 | E2 |
| E4 | **The window's live view of a Terminal job** (the Sync page track by track from `events.jsonl`; v1 6.13 Sonnet + 6.14 Opus UI at the record's 320k) | 835k (165k + 320k + shots 120k + review 130k + fix 100k) | A Terminal sync shows in the window as today's banner only | none (G2 = as today) | V2.1 |
| E5 | **The sandbox's clones of the real library and rekordbox**: `sandbox create --from real` (SQLite backup under the lock, `clonefile`, watched folders rewritten, settings scrubbed, `pending_steps`, `no_clone`) and `--rekordbox copy` (repoint inside the copy; v1 7.3) | 890k (175k + 225k + 2 own reviews, a fix, 2 rehearsals) | An agent rehearses only on an empty sandbox or a fixture; developer agents keep `scripts/rekordbox_rehearsal.py` for copies (G5's rehearsals don't need E5) | none | V7.2 |
| E6 | **`--png` pictures**: the spectrum with cutoff line and axis, the waveform in it, `limits show --png`, the window's colour map exported once (v1 3.2 minus the text sketch, which stays in V3.4) | 180k | A person or a vision agent without the window can't see the spectrum or the usage chart as pictures; numbers, verdict, sketch and sparkline remain | G3 partly (the user's design rule H2 asked for picture files) | — |
| E7 | **Generated schemas instead of the hand-written `types.ts`**: `hub/shapes.py` with `F(shown, doc)`, JSON Schemas in `help <cmd> --json`, generated `types.ts` (CI-fresh), the contract doc reduced to its rules, T6, the fake validated against the schemas (v1 2.3–2.5, 5.5's half) | 820k | `help` gives args, flags, outcomes and an example but no data schema and no per-field meaning; `types.ts` and the 150 KB contract doc stay hand-kept third copies; the fake can show a field the engine lacks (caught only by review) | G3 partly (documented machine shape); not G1, G4 | — |
| E8 | **MCP**: a generated adapter, one tool per catalogue entry, `needs_yes` a required boolean, jobs polled (design §17 says later) | 430k (est., no record) | Agents without a shell (Claude Desktop) can't use Discjockey; shell agents lose nothing | none | E7 for output schemas |
| E9 | **The banner names the Terminal job and its progress** ("Sync running in the Terminal · 4 of 60"; v1 2.2) | 305k (155k + shots 120k + review share) | The banner keeps today's words | none | V2.1 |

**v1's cost notes:**

| Note | Here |
|---|---|
| C-1 window half of phase 6 | **Not offered: breaks G1 and G4.** Price if dropped ≈ 2.7 M (V6.2/4/6/8/10/12 1 325k, shots 720k, about half the cluster reviews and fixes); loss: the window keeps its own copies of ~115 rules beside the engine's, nothing pins that they agree, the ratchet stays above zero |
| C-2 rendered check + mount coverage | E2 + E3 |
| C-3 sandbox reduced to `--from empty` | E5 (the base is already reduced) |
| C-4 live view | E4 |
| C-5 generated `types.ts` | E7 (all of the shapes work, not only v1 2.5) |
| C-6 rehearsals once per phase | **Not offered: breaks G5.** D6 keeps one rehearsal per writer group and saves 540k instead |
| C-7 `--png` | E6 |

---

## 8. Mapping tables

### 8.1 Every v1 group → one v2 place

| v1 | → | Notes (parts that move elsewhere) |
|---|---|---|
| 1.1 | V1.1 | flags from signatures (D5) |
| 1.2 | V1.2 | + generic path, printer, `call` |
| 1.3 | V1.3 | + the G4 rule's text |
| 1.4 | V1.4 | |
| 1.5 | V1.5 | |
| 1.6 | V1.6 | |
| 1.7 | V1.7 | |
| 1.8 | V1.8 | |
| 1.9 | V1.9 | generic pages |
| 1.10 | V1.10 | |
| 1.11 | V1.11 | generic results table |
| 1.12 | V1.12 | |
| 1.13 | V1.13 | |
| 1.14 | V1.14 | |
| 1.15 | V1.15 | |
| 2.1 | V2.1 | |
| 2.2 | E9 | the engine fields stay in V2.1 |
| 2.3 | E7 | |
| 2.4 | E7 | |
| 2.5 | E7 | |
| 2.6 | V2.2 | |
| 2.7 | V2.3 | |
| 2.8 | V2.4 | |
| 2.9 | V2.5 | |
| 2.10 | V2.6 | |
| 3.1 | V3.1 | `library superseded` → V3.3; the library page → V3.4; `import status` → V6.11 (§9.3 L D29) |
| 3.2 | E6 | the text sketch and sparkline → V3.4 |
| 3.3 | V3.2 | `sync plan --search`, `report list` → V3.1; the report and sync pages → V3.4 |
| 3.4 | V3.3 | `doctor`, `status --ready` → V3.2 |
| 3.5 | V3.1 | the zone table (C9, U21–U24) → V6.9 |
| 3.6 | V3.1 | `login find`'s `offer` (U30) and the six setup steps (U32) → V6.11; `app info --check` → V3.2 |
| 3.7 | V3.3 | `open …` → V3.1 |
| 4.1 | V4.1 | |
| 4.2 | V4.2 | |
| 4.3 | V4.3 | |
| 4.4 | V4.4 | |
| 4.5 | V4.5 | |
| 4.6 | V4.6 | |
| 4.7 | V4.7 | |
| 4.8 | V4.8 | + `app install-command` |
| 5.1 | E1 | |
| 5.2 | V5.1 | |
| 5.3 | V5.2 | `shots.json` `reads`/`view` declarations → E3 |
| 5.4 | E2 | |
| 5.5 | E3 | the fake's schema validation → E7 |
| 6.1 | V6.1 | |
| 6.2 | V6.2 | |
| 6.3 | V6.3 | |
| 6.4 | V6.4 | |
| 6.5 | V6.5 | |
| 6.6 | V6.6 | |
| 6.7 | V6.7 | |
| 6.8 | V6.8 | |
| 6.9 | V6.9 | |
| 6.10 | V6.10 | |
| 6.11 | V6.11 | |
| 6.12 | V6.12 | |
| 6.13 | E4 | optional in v1 too |
| 6.14 | E4 | optional in v1 too |
| 7.1 | V7.1 | |
| 7.2 | V7.2 | `--from real` → E5 |
| 7.3 | E5 | |
| 8.1 | V8.1 | |
| 8.2 | V8.2 | |

Nothing of v1 is dropped. v1's per-command handler and render modules, and its Opus review of phase 6, are process
changes (D2, D3, D7), not groups.

### 8.2 Every row of §9.2 and §9.3 → its group

**§9.2 (13 rows):**

| Row (state today) | → | |
|---|---|---|
| `PreviewStore.prep`, `read_at`, read problem, `stale`; `_infos`; `_extra_tracks` | V2.2 | stored read, derived plan |
| same-song questions and duplicate groups inside `prep` | V2.2 | commands in V4.5 |
| `PreviewStore.auto_read` | V2.2 | stays (window behaviour); V2.2 keeps it, keyed on the stored read |
| sync scope switches (localStorage), weekly checks on/off | V2.5 | `sync_scope` in settings, `sync scope` |
| ticks and "how many" | V2.3 | presets and `default_how_many` from the engine; ticks stay a draft |
| `sync.lastSelection` | V2.3 | the job's `args` |
| `_shown` | V2.4 | `rev` |
| `_dropped`, `_selected` | V2.5 | `FileDropped` path, `add_bought_file(track_id, path)` |
| `_import_stopped`, `_import_auto_done` | V2.5 | library.db import state |
| `Jobs.current`, `refresh`, `sign_in` | V2.1 | the registry from V1.4; the window on it in V2.1 |
| `_qobuz_streak`, `_account_streaks` | V2.6 | `streak` in `usage` rows |
| `_rb_cache`, `_cdj_cache`, `_tag_cache`, cover cache | V1.2 | stay per-process caches; the headless bind keeps them cold (no change, pinned by V1.2's first read) |
| recent toasts | V2.1 | from `result.json` (written from V1.4 on) |

**§9.3, moves into the engine (38 rows):** engine half in the first group, window half (its `debt` entries removed) in
the second.

| # | Row ids | → |
|---|---|---|
| 1 | L D1 | V1.13 (`resolve("collection")`) + V6.1/V6.2 |
| 2 | L D5, T:`decisionFor`, SA `TrackDetails` | V6.1/V6.2 |
| 3 | L D6, SA `rowInTodo`/`inTodo` | V6.1/V6.2 |
| 4 | L D7, L D34, T:`actionsFor`/`IMPROVABLE`, SA `footAction`, `aiffShown`, `aiffVariant`, T `Details.aiff`, `libraryModel.ts:aiffHeader` | V6.1/V6.2 |
| 5 | L D8, T:`canSwap`/`upgradeWays`/`defaultWay`/`UpgradeFlow.way`, `goes`/`NOWHERE`, `selectionWays`/`beforeLine`, SA `UpgradeCards` | V6.3/V6.4 |
| 6 | L D9, T:`undoAsk`/`undoManyConfirm`, SB `ConfirmHost` callers | V1.10 (`needs_yes`) + V6.3/V6.4 (`confirm` words) |
| 7 | L D10, T:`groupIdOf` + `DuplicateFlow.#keepOne`, SA `DuplicateFoot` | V2.5 (`keep_file`) + V6.3/V6.4 |
| 8 | L D11, T:`keepWords`/`fileWords`/`fileFormat`/`lastFolder`/`keepLabel` | V6.3/V6.4 |
| 9 | L D12, L D13, L D14, T `aiffModel.*`, `aiffBatchModel.*`, SA `AiffCard`/`AiffFoot` | V6.5/V6.6 |
| 10 | L D15, T:`cdjAllKeys`/`cdjReachable`/`wholeCdjGroup`/`upgradeAllKeys`/`wholeUpgradeGroup`/`multiScope`/`MULTI_GROUPS`, T `AiffBatchFlow.start` | V1.10 (`select`) + V6.1/V6.2 (⌘A, `groups[].multi/all`, T4's ⌘A half) |
| 11 | L D19, L D20, L D21, L D22, SA `noFileNote`, `waitWords`, `notFoundTip`, `cutoffStat`, `qualityWords`, `fileAwayWords`, `titleNote`, `placeLine`, SA `TrackHead` line | V6.1/V6.2 |
| 12 | L D23, L D25, SA `RowLead` | V6.1/V6.2 |
| 13 | L D24, U34, SB `cratesModel`, `CrateSwitches` | V4.8 (`folder crates`) + V6.1/V6.2 |
| 14 | L D26 | V4.8 (`library favourites`) + V6.1/V6.2 |
| 15 | L D29, U33, SA `ImportCard`, `WatchedFolderList`, `watchedFoldersModel.*` | V6.11/V6.12 (`import status`) |
| 16 | L D31, L D32, L D33, U27, SB `TidyList`, `tidyModel.*` | V4.3/V4.4 (flags) + V6.11/V6.12 |
| 17 | L D17 | V6.1/V6.2 |
| 18 | L D36, U39, SB `ToastHost` | V6.1/V6.2 |
| 19 | T:`sameTrackWhy`/`WHY_NOT_LINE` vs `REASON_WORDS` | V6.5/V6.6 |
| 20 | T:`checkCard`/`batchCheckCard`/`USB_STEP`/`RELOCATE_NEW`/`BEATGRID`/`keptLine`/`inRekordbox`/`isOwnCheck`, SA `CheckCards`, `BatchCheckCards` | V1.8 (one step) + V6.5/V6.6 |
| 21 | T:`replacedCard`/`undoTitle`/`undoLabel`/`doneLabel`/`undoneToast`/`undoFoot`, SA `CheckFoot`, `BatchCheckFoot` | V6.5/V6.6 |
| 22 | T:`batchEnd`/`endRows`/`endNote`/`canTryAgain`/`endWords`/`progressRows`/`runLabel`, SA/SB batch panels | V6.5/V6.6 |
| 23 | T:`checkTracks`/`batchRowName`/`batchRowSub`/`batchListTitle`, `headerSub`, `segOptions`/`FILTER_LABEL`/`FILTER_DOT`/`FILTER_ORDER`, `itemKey`, `rowOff`/`rowWaits`/`rowDim`/`rowBadge`, `compareLines`/`filePlace`/`linkService`, `qobuzText`/`freeHint`/`filedAs` | V6.3/V6.4 |
| 24 | T `Page.svelte:headResume`/`groupAction`, `Details` | V6.5/V6.6 |
| 25 | T `WrongSongDialog` `blocked`, `candidates.ts:lengthTone`/`matchTone`/`previewOffer`/`canUse` | V6.3/V6.4 |
| 26 | T `hub.ts:writeBlockedReason`/`networkReadsAllowed`, U9, SB `WriteButton`, `AccountPanel` blocked | V6.7/V6.8 (in no v1 cluster) |
| 27 | U2, U3, U6, U7, U8, U10, U16-search-excluded, SB `KindStrip`, `RunPanel`, `PlanRows`, `PlanFolds`, `WhyMark`, `NextDot`, `WaitingAnswersNote`, `DayBar`/`dayBarModel` | V6.7/V6.8 |
| 28 | U1 | V2.5 |
| 29 | U12, SB `SyncCard`, `StepBar`, `SyncPart`/`activity.ts`, `RunList`, `results.ts` | V6.7/V6.8 |
| 30 | U13 | V6.7/V6.8 |
| 31 | U14, U15, U20, SB `EndScreen`/`endModel`, `UpToDatePanel`, `RunRow`, `RunsPage` | V6.7/V6.8 |
| 32 | U17, U18, U19, SB `SummaryStrip`/`summaryStripModel`, `QualityBar` words | V6.7/V6.8 (in no v1 cluster) |
| 33 | U21, U22, U23, U24, SB `UsageChart`, `RiskScale` | V6.9/V6.10 |
| 34 | U25, U26, SB `AddRow`/`addRowModel` | V4.2 (engine) + V6.9/V6.10 |
| 35 | U28, SB `PlaylistLine`/`changeModel.infoLine/setupLine` | V6.9/V6.10 |
| 36 | U29, U30, U31, SB `AccountPanel`/`accountModel`, `SourceLadder`/`ladderModel`, `RowPanel`, `YouTubeMusicPanel` | V6.11/V6.12 |
| 37 | U32, SB `Step*`, `StepFooter` | V6.11/V6.12 |
| 38 | U36, SB `MusicMissing`, `StepMusic` | V4.8 (`setup music --dry-run`) + V6.11/V6.12 |

**Stays in the window (view only)** → V5.1 seeds each as a view entry of `derive-allow.json` with its reason: L D2,
L D3, L D4 (its data part is row 11), L D16, L D18, L D27, L D28, U37, L D35, L D37, U38, U4, U5, U11, U16, U35,
T:`keepSelection` and the selection/hold/deep-link helpers, T `flows` `adopt`, the panel phases, `FILTER_MAX`, SA
`ComparePlayer`, `MiniPlayer`, `NowPlayingRow`, `PlayButton`, `FilePlay`, `ListRow`, `ShareStrip`, `ShareBar`
geometry, `qualityBarModel` percentages, `Spinner`, `ErrorBoundary`, `NotFound`, `LinkGuide`.
**Not in §9.3 at all: L D30** (the watched-folder add/remove sequence; the library audit's verdict "W", the engine
re-checks on add) → V5.1 seeds it as a view entry, and V5.2's `flows` pins its one write.
**Deleted:** `PageStub.svelte`, `SectionLabel.svelte`, `TrackRow.svelte` and its gallery entry → V6.2.

---

## 9. Risks

| Risk | Where | What this plan does |
|---|---|---|
| **The start saving rests on one record** (D3a: groups read their plan whole) | row B | if groups would have kept to v1 §1.1's ~3k reading list, B is ~1k per group and the base is ~1.3 M higher (≈ 21.4 M); the brief's "~58k of shared docs" premise is not counted |
| Groups overrun (record: Sonnet lands up to 1.5× plan) | all | planned ≤ ~250k; stopped at a green commit near ~300k, the rest to a fresh agent; range 17.2–25.5 M |
| A brief misses an interface or a decision, and the group guesses | every group | §4.1's seven parts; the coordinator's script checks each brief before dispatch; a group that finds a gap stops and reports, never opens the plan to fill it |
| The brief writer (V1.0) copies v1 wrongly | phase 1 | briefs quote v1 §2–§3 verbatim; the coordinator diffs each brief's part 2 and 4 against v1 by script |
| `call` used to skip the noun-verb safety | V1.2 | §3.2: the same entry, `needs_yes`, worker and locks; refusals for window-only, dropped, planned and secret arguments; T2 and T3 cover it |
| The generic printer hides a field a page didn't place | V1.2 → all reads | T7′ on every read's fixture output; hand pages only add order and words |
| Without E7, payload drift between engine, `types.ts` and the fake | phases 2–6 | the contract rule (one commit: contract doc, `types.ts`, `contract.ts`, fake) stays; T4 parity holds on the engine side |
| Rehearsal inside the fixing agent (D6) | writer groups | PASS counts go into the report; the coordinator checks the count against the script's total; a failing rehearsal is a finding, never edited away |
| Shots not byte-stable (D8) | phase 6 | V5.2 checks first; if not, the shots agent judges every cluster shot (record 240k per pass: +0.7 M) |
| The worker process (riskiest group) | V1.5 | v1 §11's measures; an Opus re-run if a Sonnet run stalls (+~100k, est.) |
| `?mode=ro` on a WAL library; the Auto-upgrade phase without the planner; legacy routes outliving replacements; `rekordbox_rehearsal.py` (106 KB) read whole | V1.10, V1.14, V1.2 → V4.8 | as v1 §11 |
| The live tests write the real library and rekordbox | after phase 1 | as v1 §7: only with the user's go, rekordbox backup first, test tracks by name, dry run first, the marked-files clean-up |

**Between groups the coordinator checks** v1 §11's seven points, plus: the brief's parts by script before dispatch;
the group's real size logged against this plan's; for a writer group the rehearsal's PASS count.
