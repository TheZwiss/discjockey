# Library and sources: how the work is orchestrated

Rules for building `docs/2026-10-23-library-and-sources-design.md` (the spec) with subagents. Goals: the user spends as
little time and as few tokens as possible; no agent runs away; the orchestrator's context stays small. Archived with
the spec when the last stage is merged.

## 1. Roles

| Role | Who | Does | Never |
|------|-----|------|-------|
| **Orchestrator** | The main session | Writes briefs, dispatches, merges, runs the final checks, keeps `docs/issues.md`, memory and this file's progress table, tells the user what they need to know | Read full diffs, whole plans or big source files; write product code |
| **Planner** | Opus, one per stage | Writes the stage's plan (§3) | Write full code; run tests or builds; read outside its read list without counting it |
| **Implementer** | Opus or Sonnet by difficulty (§2), one per task group, in a worktree | Builds one task group with tests, commits on the group's branch | Read the whole plan or the spec; run `npm run verify`; touch a real library |
| **Reviewer** | Sonnet per task group; Opus once per stage | Reviews against the plan's tasks and CLAUDE.md's invariants | Rewrite the code itself |

Only one agent runs at a time (the user, 2026-10-24; parallel rounds in a plan run one after the other).

## 2. Which model

Opus where judgement is needed and a mistake is expensive. Sonnet where the plan has already made the decisions.

- **Opus:** each stage's planner; the database, migration and crash safety; the scanner and content keys; the
  planner rules (option A); tidy-up and undo; a hub page or a sidebar redesign (they may improve the approved design,
  CLAUDE.md §12); the final review of each stage.
- **Sonnet:** wiring a finished engine piece into `api.py` / `jobs.py` / views; contract, `types.ts` and fake-backend
  updates; README and `docs/` updates; a source whose interface the plan fixes (Qobuz, SoundCloud, YouTube Music);
  per-group reviews; re-reviews after a fix round.

When a Sonnet task turns out to need decisions the plan didn't make, it stops and reports. It never guesses.

## 3. Plans

CLAUDE.md "Plans are designs" applies and overrides `superpowers:writing-plans`. On top of it:

- **A plan is researched instructions, not code.** It names, for each task: the files and functions to change
  (`file:function`), the exact interfaces between tasks, the binding values and the user-facing words, the behaviours
  the tests must pin, and the reason for each decision. That "where" is what saves each implementer from exploring
  again. A short snippet is allowed only where the exact form *is* the decision (a schema, a signature, an event shape).
- **300–600 lines.** A planner that needs more splits the stage into two plans and says so.
- **Task groups.** The plan groups its tasks into implementer-sized groups (§5) and marks each group Opus or Sonnet.
  Every group lists its own read list, so its implementer reads only that.
- **Its last section is the stage's checks:** which tests, which screenshots, which live check for the user.

## 4. Briefs

Every brief has the same parts, in this order, and stays under about 60 lines:

1. **One deliverable.** What is done when the agent stops.
2. **Read list.** Exact files and sections, in reading order. Module docstrings and `grep -n "^def \|^class "`
   outlines come before whole files. For tests: `grep -n "def test_"` and the helper signatures, never whole test
   files unless the task changes them.
3. **Read budget and stop rule.** "Beyond the list, at most N more file reads (N = 10 for a planner, 6 for an
   implementer). If you need more, stop and report what is unclear." Planners also stop at the first spec conflict
   and report it, rather than reading on to resolve it.
4. **Don'ts.** No `docs/archive/` (unless a cited reason is needed: search it, don't read it); no `npm run verify`;
   no real library, Spotify, Qobuz or yt-dlp calls; no code in plans; nothing outside the task group.
5. **Checks to run.** While working, only the test files of the code the agent changed (`uv run pytest -q
   tests/test_x.py`, `npx vitest run <file>`, `npm run rules -- --page P --only …`), not after every edit. Once at
   the end of the task group, the full Python suite (`uv run pytest -q | tail -3`, about 25 s in parallel). Never
   `npm run verify` (§6).
6. **Report format.** At most 15 lines, no code, no diffs: what was done, commits (hash + subject), checks run with
   their result, what is left or doubtful, anything added to `docs/issues.md`.
7. **Scope, whenever the work follows a mockup.** Three short lists:
   - **Build from the mockup:** the exact elements and states the task takes from it, by name.
   - **Must not change:** the pages, shared components, icons, tokens and the foot outside the task. Everything else
     the mockup shows is illustration, not a spec.
   - **Mockup errors:** a shape, colour or word copied from the mockup is still checked at real size for what it reads
     as (the stage 5 mockup drew Settings as a sun, and A3 copied it). Fix what is wrong and name it in the report.
   Any change the agent finds necessary outside "build from the mockup" goes in the report as "beyond scope", with
   before/after shots, and is not done silently.

The orchestrator tells the user each job's expected size before sending it (a planner: about 100–150k tokens; an
Opus implementer: up to about 150k; a Sonnet task: 40–100k). It estimates from the record, not the plan's line counts:
in stage 5, every Opus UI group that also took its own shots used 300–420k (B6 about twice that, over two agents).

## 5. Sizing and runaway protection

- **A task group fits in one agent:** at most about 8 plan tasks or about 1,500 changed lines, one area of the code.
  Bigger groups are split before dispatch.
- **A UI group is two agents** (the user, 2026-10-30): a *build* agent writes the code and its tests and takes no
  shots; a *shots* agent then takes the group's shots, looks at each once, and fixes only what they show. Screenshots
  stay in an agent's context and are re-read on every later step, so they never share an agent with the build.
- **Every brief carries a hard stop:** at about 80 tool calls the agent commits what works and reports what is left.
  The orchestrator then sends a fresh, narrower brief for the rest, never a "keep going".
- **Fix rounds go to the implementer that wrote the code** (by `SendMessage`) only while its context is still small:
  check its reported tokens first, and **above about 150k never resume it** (resuming reloads its whole transcript on
  every step). After a second fix round, when the fix concerns another area, or above that size, a fresh Sonnet gets
  the findings plus the exact files instead. Minors are fixed in the same round; only spec conflicts and user decisions are
  parked.
- **An agent that stops at its budget is not restarted with "keep going".** The orchestrator reads its report, then
  narrows the task or answers the question, and sends a fresh, smaller brief.
- **Two failed rounds on the same problem** go to the user with a short summary and a recommendation.

## 6. Reviews and checks

- **Per task group:** one Sonnet review of the group's diff against its plan tasks and CLAUDE.md's invariants.
  It does not review the whole stage.
- **Per stage, before the merge:** one Opus review of the whole stage branch against the spec's sections for that
  stage.
- **The full Python suite** (about 1,700 tests) runs in parallel by default (pytest-xdist) in about 25 s. Agents run
  it once at the end of their task group, never after each edit, and report only its summary line. CI (`check.yml`)
  runs it again when the orchestrator pushes the stage branch before the merge; the orchestrator reads only the
  result (`gh run list` / `gh run view --log-failed`). A failure goes to a fix round with the failing tests' names.
- **`npm run verify`** isn't in CI (its design rules take 15+ minutes there); the orchestrator runs it once in the
  background, only for stages that change `hub-ui`, and reads only its last lines.
- **Touched tests while working** (§4.5): when a change reaches into a module many tests use (`library.py`, `db.py`,
  `planner.py`, `models.py`), the plan names the test files that cover it, so agents run those while working.
- The orchestrator checks claims cheaply: `git log --oneline`, `git diff --stat`, and the test summaries. It reads
  code only to settle a disagreement between an implementer and a reviewer.

## 7. Branches, merges, releases

- One branch per stage (`feat/library-<stage>`). Each task group works in a worktree off it and is merged back after
  its review.
- The stage branch is pushed for CI before the merge (§6). A stage merges into `main` after its final review and a
  green CI run, and `main` is pushed. Stages 1 and 2 are merged
  together.
- A release (`git tag v…`) is outward-facing: the orchestrator asks the user once per release.

## 8. The orchestrator's context

- It never pulls file contents in when a report or a summary line will do.
- After each stage's merge it updates this file's progress table and its memory, then tells the user it's a good
  moment to `/compact`. Everything needed to go on lives in this file, the plan and memory, so nothing is lost by
  compacting.
- It also suggests `/compact` before a stage's implementation starts when planning took many rounds.

## 9. What the user is asked for

Only:

- product decisions the spec doesn't settle, and spec conflicts a planner finds;
- the stage 5 mockups, before building;
- the live checks: rekordbox after a tidy-up and an undo (stage 2), importing their own library (stage 4);
- a go for each release;
- the AcoustID question (issue 24), after stage 4.

Everything else is decided and done without asking, and reported in one short message per stage.

## 10. Progress

| Stage | Plan | Branch | State |
|-------|------|--------|-------|
| 1 Foundation | `docs/2026-10-23-library-stage-1-plan.md` | `feat/library-1-foundation` | Done (3e562f1): 5 groups + Opus stage review + fixes; merged into main with stage 2. Before the release: one migration on a copy of a real-shaped scratch library |
| 2 Tidy-up | `docs/2026-10-24-library-stage-2-plan.md` | `feat/library-2-tidy` | Done: 7 groups, Opus stage review, 2 fix rounds + Sonnet re-review (145f34c); verify 615 shots 0 problems, CI green; rekordbox live check passed 2026-10-24 (Relocate needs the music folder in Auto Relocate's search folders: README); merged into main with stage 1 |
| 3 Qobuz playlists | `docs/2026-10-24-library-stage-3-plan.md` | `feat/library-3-qobuz` | Done, merged into main 43e786f (2026-10-25): 7 groups + stage review fix rounds; Qobuz live read checked; Spotify optional in Setup; leftovers in docs/issues.md #26 |
| 4 Import | `docs/2026-10-25-library-stage-4-plan.md` (f5624fd) | `feat/library-4-import` | Done, merged into main 014bcdc (2026-10-29): 8 groups, Opus stage review, fix rounds A–M (A–D review; E–M from the user's live checks: quality floor rule, own files in the sound picture, offline and missing files with a live drive watcher, whole-screen fixes); verify 741 shots 0 problems, CI green; user live check passed (drive eject); leftovers in docs/issues.md #27 |
| 5 Sidebar | `docs/2026-10-29-library-stage-5-plan.md` | `feat/library-5b-folders` | Step A merged into main b47a3b2. Step B built + reviewed; in the user's live check (2026-10-31), fix queue below; merge into main after the user's re-check |
| 6 SoundCloud, YouTube Music | `docs/2026-10-31-library-stage-6-plan.md` (planning) | `feat/library-6-sources` | Planning started 2026-10-31 (lane B of the live-check queue) |

### Stage 5 live-check queue (2026-10-31)

One agent at a time, each in a worktree `.claude/worktrees/5b-<name>` off `feat/library-5b-folders`, merged back with
`--no-ff`, pushed.

Done on the step branch: the 120 fps cap lifted (user confirmed); empty Artist column; crate panel jitter in a small
window (2ee90d0, user confirmed fixed 2026-10-31); quality rule: fake line 20.8 kHz,
weak 12 dB wall only 19.5–20.4 kHz (7b71617; calibrated on 120 real Qobuz files + 31 DJ Stick Jan WAVs, all right);
Sync's blank playlist row for own songs (765085d).

Item 1 done, the upgrade investigation (Opus, 107k, report only). Results:
- Compare fails because `ComparePlayer.load()` uses `fetch()` across ports and `media.py:MediaServer._serve` sends no
  `Access-Control-Allow-Origin` header. It has never worked in the real app.
- Basswell is the same edit (measured: lag 0, 1 sample apart). "cues stay" ignored that an MP3 can't be swapped
  (`swap_possible` is AIFF only). The "different edit" text after the step is a fixed sentence: `upgrades.add_new`
  always adds `REKORDBOX_CHECK["added_as_new"]`.
- The user pressed "Add as new file", which was primary because Swap is impossible for an MP3. That makes a new
  rekordbox entry with no cues.
- There is no undo for upgrades anywhere.
- The stray `library.db` came from our own agent's `sqlite3` CLI on a wrong path; deleted.

Open, in order:
1. ~~Upgrade engine fixes~~ done (Sonnet 135k, merged bf470aa): Compare CORS for the page origin only; card text
   uses `swap_possible`; the text after "Add as new" follows the stored measurement. Leftovers: the CLI
   `upgrades_cmd.REKORDBOX_ADDED` and README (~431–441) still carry the old fixed sentence (goes with item 2); `cueTone`
   colours "same edit, but a new rekordbox entry" green (goes to item 3); a shifted file added as new sits N ms off
   the old cues (the wording says so; note only).
2. ~~Upgrade undo~~ done (Opus 214k): undo for Swap and Add as new until "Done, checked in rekordbox"; the record
   lives in `rekordbox_check.undo`; a swap now also leaves a rekordbox-check row; a swap's undo deletes the
   byte-identical `(lossy)` copy last; plain "Undo" link under Done (design round places it). Not done: CLI undo.
   Notes: after "Wrong song?" the old undo record stays (undo not offered, a swap's kept download waits until Done);
   an upgrade on a track with an earlier rekordbox check overwrites that check's text (older behaviour).
3. **To-do decision panels** — design approved by the user 2026-10-31 (mockup `docs/hub-mockups/todo-decisions.html`
   + notes, 45e964b on `feat/library-5b-panels`, worktree `.claude/worktrees/5b-panels`). User answers: label
   "Replace with lossless"; one "quit rekordbox first" line in the In rekordbox card; rekordbox XML for duplicates
   later (list it next to AcoustID). Orchestrator changes: the Duplicates button names the result ("Keep the AIFF",
   "the MP3 goes to Superseded/, not deleted"); NOW/NEW both show quality. Scope: ONLY the right details panel
   (Upgrade ready, rekordbox check, Duplicates, empty state) + the short status in To-do list rows; the mockup's
   sidebar, settings icon, foot player, header, tabs, list layout are hand-drawn and must not change.
   - a. Build (Opus, no shots) — running overnight 2026-10-31.
   - b. Shots agent (Opus or Sonnet per findings; ~100–150k): every fake state at 1100×700 + full window, light/dark;
     compare the WHOLE screen with today's app, anything changed outside scope is a bug to revert; fix what shots
     show; check the old orange "Undo" text link is gone. Hard stop ~80 calls.
   - c. Merge `feat/library-5b-panels` into the step branch (`--no-ff`), push, remove worktree.
4. **Tooltip cut off at the window edge**: check it is gone after 3 (the design removed the tooltip); if any remain,
   small fix in the shots round.
5. **Sync: no cover for folder-imported tracks** in the top card (next up / syncing now) while a sync runs (user,
   2026-10-31, shot at 00:58). Qobuz/Spotify tracks show covers in the rows; Kø:lab shows a gradient (not on Spotify).
   Find where the top card gets its cover and why imported own songs have none; consider the file's embedded artwork
   as the fallback, also for rows like Kø:lab. Sonnet, code + tests + a fake shot; worktree `5b-covers`.
6. ~~Ask the user: re-judge old quality verdicts?~~ User 2026-10-31: **no**, the new imports are only test files.
   Close the #27 re-judge point in `docs/issues.md` with that answer (fold into item 5's commit or a docs commit).
7. Then: CI + `npm run verify` (background), and **stop for the user**: their re-check (the new panels with a real upgrade + duplicate, Compare plays, sync covers). Only after their OK: merge
   `feat/library-5b-folders` into main (`--no-ff`), push, update this table and memory.

**Lane B (user 2026-10-31: continue the implementation plan). Back to ONE agent at a time once the panels build and
stage 6 group 1 are done (user, 2026-10-31). Lane A is finished FIRST (3b → 3c → 4 → 5 → 6 → 7, stop for the
user's re-check is NOT a stop: the user sleeps, so after item 7 lane B goes straight on (group 1's review, then
groups 2–5, one agent at a time); the user re-checks stage 5 in the morning and only the merge into main waits for
their OK; never lane B between lane A items (user 2026-10-31):**
- B1. **Stage 6 plan** (Opus planner): `docs/2026-10-31-library-stage-6-plan.md` on branch `feat/library-6-sources`
  (off `feat/library-5b-folders`; rebased/merged onto main after stage 5 lands), worktree `.claude/worktrees/6-sources`.
  Spec §9.4, §9.5, §4 row 6. The planner lists product questions and whether any UI change needs a mockup.
- B2. Build stage 6 groups per the plan, one group at a time in this lane (worktrees `6-<group>`), review per §6.
  Engine/non-UI groups may run overnight; a UI group with a design change waits for the user's mockup approval;
  product questions wait for the user.
- **Lane A done 2026-10-31 night:** panels merged a1a15a3 (build 294k + shots 199k), covers merged ecca764 (151k;
  left out: a console-started run and a track downloaded during the run get no file cover; would need the cover in
  run events), #27 re-judge closed, issue 30 opened; CI green, verify 913 shots 0 problems. Waiting for the user's
  morning re-check, then the merge into main.
- Group 1 built 2026-10-31 on `feat/library-6-split` (5011d61…3923348, Sonnet 129k, suite green, pushed); review
  not yet run. Its report for later briefs: (1) short links (`on.soundcloud.com/…`) are refused by `clean_link` before
  `expand` runs: group 2's `recognise` must accept them or I4 changes; (2) `preview_playlist_change` also switched to
  `.connected`; (3) `test_sources.py` pins `SOURCES == [spotify, qobuz]`: groups 2/3 update it; (4) `account_only` on
  SourceTrack events: group 5 adds it to `types.ts`, `contract.ts`, contract doc (still says "Spotify or Qobuz");
  (5) splitter: with a known artist a dash splits only if the left part holds that artist; (6) two flaky
  `test_hub_dispatch.py` tests under load.
- Group 1 fixed (review 87k, fix 70k) and merged 60d9d12. Group 2 built on `feat/library-6-soundcloud` (146k, 6 live
  public probes, no curl_cffi needed), review 103k: shared yt-dlp `_HEADERS` leak (a `you/likes` login would make
  every later SoundCloud request authenticated) + 4 minors, fix round running. For later briefs:
  *group 4:* don't rely on `fallback.py` for yt-dlp state isolation; build exact-upload URLs from `SourceTrack.id`
  via `fallback.stream_url("soundcloud", id)`; tracks in a private set may need the set's secret token, which
  `SourceTrack` lacks: park it in `docs/issues.md`. *group 5:* `types.ts` `track_count: number | null` (likes give
  None) + fakes; `sources.expand` can raise `SourceError` (W6–W9) and open a browser-login Keychain prompt inside
  `add_playlist`: check `@bridge` returns `{ok:false, kind, service}` and `login_expired` for soundcloud reaches the
  Settings banner; a `you/likes` line in `playlists.txt` logs in on every read (D4): sync summary needs W9's text.
- Stage 6 merges into main only after stage 5 is in main and its own final review + CI.

Later (each needs its own plan / the user's go): AcoustID (#24, a stage after 6), rekordbox XML for the duplicates
pick, the leftovers in `docs/issues.md`, CLI undo for upgrades. **No release without the user's go.**

Overnight rules: ONE agent at a time (user 2026-10-31, after the two that ran together); never two on the same files or worktree; check `ps` and the
worktree after each; size from the record (Opus UI build 250–350k, shots 100–150k, Sonnet fix 115–150k, Sonnet group
150–310k, review 110–140k); never resume an agent above ~150k (fresh one with findings + files); two failed rounds on
one problem → stop and leave it for the user; never touch the running app, the user's files or the real DB.
