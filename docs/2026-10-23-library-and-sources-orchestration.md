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
| 6 SoundCloud, YouTube Music | — | — | Not started |

### Stage 5 live-check queue (2026-10-31)

One agent at a time, each in a worktree `.claude/worktrees/5b-<name>` off `feat/library-5b-folders`, merged back with
`--no-ff`, pushed.

Done on the step branch: the 120 fps cap lifted (user confirmed); empty Artist column; crate panel jitter in a small
window (2ee90d0, **user to re-check**: import with a small window, then full screen); quality rule: fake line 20.8 kHz,
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
1. **Upgrade engine fixes** (Sonnet, code + tests, no UI shots):
   - Compare: send the CORS header for the page's own origin only (port from `window_port`), never `*`.
   - `views.upgrade_block` / `cue_text`: combine the measurement with `swap_possible`, and tests pin which button is
     primary.
   - `add_new`: store the measurement in `rekordbox_check`, and have `report.check_text` say "same edit: relocate in
     rekordbox, cues fit" unless the edit really differs.
2. **Upgrade undo** (Opus, engine + hub API): undo for add-as-new and swap. It restores the old file, path, entry and
   parked upgrade; it is refused if either file changed; it is crash-safe (reuse `recover_swap`); it is gone after
   "Done, checked in rekordbox".
3. **To-do decision panels design** (Opus + design skills, mockup with before/after for the user's approval, then
   build + shots):
   - Upgrade ready: show the outcome of "Add as new file" before the click, not in a tooltip; button order; where the
     Undo link sits.
   - Duplicates (user: "very bad UX"): "Move to Superseded" is jargon and badly placed, "Keep both" is the orange
     primary, there is no recommendation, paths serve as headings, and the Superseded explanation sits in a separate
     box.
4. **Tooltip cut off at the window edge** (To-do's "Add as new file makes a new rekordbox e…"), small UI fix + shots
   (may fold into 3).
5. **Ask the user:** re-judge old quality verdicts with the new rule? (`docs/issues.md` #27; e.g. 27 DJ Stick Jan
   WAVs still show lossless until judged again).
6. Then: CI + verify, the user's re-check, merge `feat/library-5b-folders` into main, update this table and memory.
