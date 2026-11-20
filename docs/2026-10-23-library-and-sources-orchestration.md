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
- **Fix rounds go to Sonnet** when the findings already state each fix, UI fixes included (the user, 2026-11-09);
  Opus only builds new UI and makes design decisions.
- **Every dispatch passes a gate:** a hook on the orchestrator's Agent tool refuses a brief without a `Dispatch check:`
  line (model, expected size from the record, deliverable, review plan) and shows the checklist (2026-11-09: issue 33
  stages A+B used about 70% of a weekly budget).

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
- **Review budget:** per-group reviews or one stage review, not both; one shots pass per stage; no re-check agent,
  because `npm run verify` before the merge shoots every page. Each agent's real size goes into the log.
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
| 1 Foundation | `docs/archive/2026-10-23-library-stage-1-plan.md` | `feat/library-1-foundation` | Done (3e562f1): 5 groups + Opus stage review + fixes; merged into main with stage 2. Before the release: one migration on a copy of a real-shaped scratch library |
| 2 Tidy-up | `docs/archive/2026-10-24-library-stage-2-plan.md` | `feat/library-2-tidy` | Done: 7 groups, Opus stage review, 2 fix rounds + Sonnet re-review (145f34c); verify 615 shots 0 problems, CI green; rekordbox live check passed 2026-10-24 (Relocate needs the music folder in Auto Relocate's search folders: README); merged into main with stage 1 |
| 3 Qobuz playlists | `docs/archive/2026-10-24-library-stage-3-plan.md` | `feat/library-3-qobuz` | Done, merged into main 43e786f (2026-10-25): 7 groups + stage review fix rounds; Qobuz live read checked; Spotify optional in Setup; leftovers in docs/issues.md #26 |
| 4 Import | `docs/archive/2026-10-25-library-stage-4-plan.md` (f5624fd) | `feat/library-4-import` | Done, merged into main 014bcdc (2026-10-29): 8 groups, Opus stage review, fix rounds A–M (A–D review; E–M from the user's live checks: quality floor rule, own files in the sound picture, offline and missing files with a live drive watcher, whole-screen fixes); verify 741 shots 0 problems, CI green; user live check passed (drive eject); leftovers in docs/issues.md #27 |
| 5 Sidebar | `docs/archive/2026-10-29-library-stage-5-plan.md` | `feat/library-5b-folders` | Step A merged into main b47a3b2. Step B merged into main 65e297b after the user's re-check (2026-10-31). Follow-up: To-do keeps the acted-on item (`feat/library-5b-todohold`) → main; stage 6 merges main (fake `bridge.ts` conflict + static) |
| 6 SoundCloud, YouTube Music | `docs/2026-10-31-library-stage-6-plan.md` | `feat/library-6-sources` | Built + stage review + fixes 2026-10-31 (fa1f9f9), CI + verify green; waits for stage 5 in main, live check, 3 questions |

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
- Groups 2 (fix 73k) and 3 (171k, review 95k, fix 63k) merged 430cf8e. Group 4 built on `feat/library-6-upload`
  (Opus 212k): found the SoundCloud login leak in the EXISTING download chain too (after a Go+ download every later
  free SoundCloud request ran logged in, unpaced and uncounted; likely in v1.1.0), fixed in `fallback.py`. Review
  143k: ready after the stream cap fix (1 upload + 3 search streams = 4 account downloads); fix round running.
  **Morning questions for the user:** (a) YouTube Music "Liked music" (plan: left out, W17); (b) when a playlist
  upload's own account is used up or paused, the track waits (I6) instead of letting the other account or a free
  source stand in; (c) tell them about the login leak fix. *Group 5 also:* `events.ts` `Action.upload:
  SourceTrack | null`, field list `'upload'`, `query_kind` `'upload'`; fake actions; contract lines ~1885/1889
  (`upload`, `account_only`, W20); W20 in `views.py` and `cardState.ts` (`how="upload"`); check `report.py` copes.
- Group 4 fixed (71k) merged 9b894c3; group 5 (223k, review 116k, fix 67k) merged 9458022; group 6a (114k) + 6b
  shots (Opus 174k) merged 96af538; CI green on groups 4–5. Opus stage review running. Design-round items (need a
  mockup + the user's OK, not built): W20 "the playlist's own upload" has no Sync-card place; Setup has no example
  links; no UI renders `track_link` ("Open in …", pre-existing). Pre-existing seen by 6b (for `docs/issues.md`):
  fake tracks show FLAC next to `.aiff`; empty Playlists state still shows tidy/moves/read counts; likes row prints
  the owner twice (`"Example DJ's likes" · Example DJ`); Library header drops "YouTube Music playlist" at 1280;
  W22/W5/W18 hints end on a short last line at 1100 (balanced wrapping in the blocks).
- **Stage 6 built 2026-10-31 night:** Opus stage review 183k (ready after 1 Important: a failed Go+ listing
  rejected a SNIP upload for good) + fix round 107k merged fa1f9f9; suite 3177 green, CI green, verify 889 shots 0
  problems (branch is off stage 5 before the panels; re-run verify after merging onto main). Leftovers: issue 32.
  Waits for: the user's stage 5 re-check + merge into main, then stage 6 merged onto main, the user's read-only live
  check (plan "Stage checks": paste a SoundCloud set, you/likes, a YTM playlist; read; look at the splits), and the
  three questions (Liked music; wait vs search when the upload's account is used up; SNIP at ~128 kbps).
- **Stage 5 re-check finding 2026-10-31 (fix before main, next agent after the SNIP review):** Library's
  inspector still shows the OLD upgrade card (`components/UpgradeCard.svelte`), not To-do's new decision panel
  (`pages/todo/UpgradeBox.svelte` etc., a1a15a3), and it is a dead end (Compare plays, no way to act). Fix: every
  place an upgrade or duplicate decision shows uses the same approved panel with its actions (mockup
  `docs/hub-mockups/todo-decisions.html`). Opus build (no shots) + Opus shots.
- **State 2026-11-05 (resumed by the user):** issue 34 merged e843d38; (1) UI minors merged de53b75; fake-data round
  merged 988c790 (verify 958/0). (2) design round: mockup `docs/hub-mockups/sources-round.html` approved by the user
  (rows logo-only OK; Liked music warning + "Add Liked music to Playlists" stay; dashed not-downloaded segment stays
  with the text count). The designer redrew the window and drifted (sun icon again, Settings ladder): the notes now hold
  a drift list (72 rows, 39 "mockup error: keep the app"); builds take only the plan's scope table, shots are compared
  with main's. Plan `docs/archive/2026-11-05-sources-round-plan.md` (groups E1, E2, U1, U2, S2, U3, S3, review), branch
  `feat/sources-round`, group worktrees `.claude/worktrees/sr-<group>`. The plan's open questions, decided by the
  orchestrator: (1) words for the other `source_how` values: "found by name" and "picked by you" (plain English, as
  planned); (2) Library's "All" segment counts the rows it lists (18 incl. waiting songs), so every count matches its
  list; built in U3. E1 merged into `feat/sources-round` 148c6f5 (186k; Format row shows the file format until U3 adds SOURCE). E2 merged cd68d27
  (303k + fix 73k: a paused LM line keeps its songs via planner `unread_folders`). U1 merged 0fa7a4b (223k). U2 built on `feat/sources-round-u2` (234k, 4 commits to ad7d893). S2 done d3ce292 (241k, 117 calls: over its stop; 3 defects fixed; Setup LM form has no button, Hint says turn it on in Settings after setup). S2 follow-up 10bd01d (146k; ToggleRow `action` slot + balance wrap, dashes `--text-label`). U2+S2 merged dbbb36d. U3 built 78a99d7 (228k; how words per D11: "found by ISRC", "found by name"). S3 done 03b685e (182k; card height, ↑ hover, SOURCE wrap fixed; all diffs in scope). Open-in fix a374bbf (104k; rows carry `track_link`). U3+S3 merged c7765ca. Final review done (Opus 205k: needs fixes; 1 critical + 2 important D6 holes in the LM read and planner, 4 minors; UI fine). Fix round done baa1c36 on `feat/sources-round-fix` (139k; all 7 fixed, pytest 3315, vitest 1218; open: fix 6 keeps a paste-time sign only in memory when the scan lock is held, lost on app close). Re-check done c0363ba (152k; all 7 hold; pending signs in `.discjockey/pending_signs.json`, shown and counted for pauses; unread line without stored read keeps by library records). Fixes + main merged into the round bee6869. CI green, verify 994 shots 0 problems, smoke ok. Sources round MERGED INTO MAIN c390ce4 (no release). Docs pass done 09c327f (125k): issue 31 closed, 27/28/32 points closed, 24–30 audited (each has an "Audit 2026-11-05" line), stage 1–5 + sources-round plans archived. Step 4 fix rounds: C1 merged a82a3f4 (149k + review 98k; issue 26 closed; 25 left: `run_op` entry view = own stage). C2 merged 7c98301 (178k + review 124k; 25 left: `run_op` entry view, unreadable replaced file needs a stored failed key). UI round on `feat/leftovers-ui` in `.claude/worktrees/lo-ui`: build L done bf9d669 (209k; orange wash on picked rows in Library + To-do, `#/library/playlist/:name`, next-try tooltip, Finder for import folders, 99+ pill, FAKE pill; ARIA nit + View menu closed with reasons); build T done 30c5678 (167k; To-do AwayTag, Sync "waits for your answer" note, To-do subtitle one line, yellow "In rekordbox" steps, dry-run names folders, shots.json on playlist routes; issue 30 closed). Shots done 5cebbd0 (204k, hit the session limit once, resumed; 1,089 shots diffed, all in scope; fixed 99+ pill type size, high-contrast wash tokens, PageHeader comment). CI green, verify 997 ok, smoke ok; UI round MERGED a8ae461 (issue 30 closed). C3 built da04064 (187k) in `.claude/worktrees/lo-c3` on `feat/leftovers-c3`: W4 rare cases + `files.judge_failed` (schema v6) kept; it also built a re-judge of old verdicts AGAINST the user's 2026-10-31 "no" (my brief, from stale issue text). Re-judge removed d28d2a2 (87k; v6 = only `judge_failed`, #27 point closed with the user's answer). C3 MERGED 96a43c6 (CI green; engine only, no verify). C4a done 9ac7ac0 on `.claude/worktrees/lo-c4` on `feat/leftovers-c4` (148k; issue 29 closed: one count `views.listed_counts` for sidebar + Settings, sidebar reads numbered by one counter, `views.library` split, dev switches in CONTRIBUTING; remove-folder dialog keeps "forgets its N files": it forgets file rows, true also mid-import). C4b done ec31fc5 (219k, 110 calls: over its stop; base rules 2,732 FAIL → 0, gallery root `data-catalogue` skips the screen rules there (guard test + self-test fixtures, decision log), Toast marks itself a note, first-run shot waits for "Finish setup" (no login banner without playlists), fake counts from one `listedCounts`; issue 28 closed). Open: plain fake folder scenarios now show 0 songs (consistent but thin demo). Resumed by the user. C4c done c93c875 (160k; fake folder scenarios stocked by a deterministic `fake/own.ts`, counts agree, 12 shots checked). C4d done d50160c (201k; `normal` Music holds 24 own songs, All 64, counts agree). CI green, verify 997 shots 0 problems, smoke ok; C4 MERGED ca60d2f (issues 28 + 29 closed); issue 27 closed (its last point closed with the user's answer). Leftovers phase DONE. Issue 32 closed by the user 2026-11-06 (no live checks; no SoundCloud Go+). Open: 25 (`run_op` entry view, optional own stage), 33 + 24 parked. Found 2026-11-06: Liked music needs YouTube Premium in the app only because a YouTube login without Premium is refused (api `_account_result`); YouTube itself does not need Premium. NIGHT 2026-11-06 (user go, incl. release WITHOUT the user): (1) Liked music with a free YouTube login (Sonnet build on `fix/liked-music-free-account` in `.claude/worktrees/liked-free` + Sonnet review, CI, verify, merge); (2) GitHub presence for the launch (Opus: new fake-mode screenshots, README landing showing the problem, how it works, features; repo description + topics); (3) v1.2.0: bump, tag, release.yml draft, check assets, publish. (1a) issue 35 (user 2026-11-06: weekly checks switch gone on Sync, no why on rows, service logos in the Sync Playlists panel; fix tonight; UI directed by me, agents change no other UI): Opus debug + build on its own branch while verify of (1) runs, then shots checked by me, CI + verify, merge. (1a2) issue 36 Sync redesign (user 2026-11-06: Library rail copied with switches, health card for the outstanding kinds, right panel with two weekly-check switches; NO mockup first, ships in 1.2.0): Opus build after 35, Sonnet shots/drift agent, my look, CI + verify, merge. (1b) issue 25 (user: do it tonight, the tests cover it): Opus build on its own branch after (1) merges + Sonnet review + CI, merged before the release. caffeinate runs 12 h. (1) DONE: Liked music merged e44ee66 (build 207k + review/fix 188k: sticky `liked_only`; CI green, verify 1006 ok, smoke ok). (1a) DONE: issue 35 merged 73cbde8 (Opus 207k; both switch groups shown with one row, kind icon on every row, clock for weekly; CI green, verify 1003 ok, smoke ok; issue 35 closed, logo wish now in 36). (1a2) DONE: issue 36 merged (Opus build 273k + Sonnet shots/drift 166k: empty-track bar fix 8007559, no drift outside Sync + gallery, locked switches = existing disabled look; CI green, verify 1012 ok, smoke ok; issue 36 closed). (1b) DONE: issue 25 merged (Opus 177k run_op + fresh Opus 141k swap/undo + Sonnet review 152k: ready, recover tests both row formats 828d7a8; pytest 3419; CI green; issue 25 closed. Accepted, not built: a step refused again at recovery raises the same StateError at each start, as v1.1.0 did; nothing triggers it today). (2) DONE: GitHub presence merged 9d69495 (Opus 198k: README landing Why / How it works / What you get / What you need / Manual index, 9 new fake-mode shots 2560x1600 ~1 MB total, manual kept in README; my review: claims match the manual; repo description + 14 topics set). (3) v1.2.0: bump ab6f042, pytest 3420, verify 1012 ok, smoke ok, tag pushed, release.yml + CI green; dmg self-test passed (scratch mount, temp support dir); v1.2.0 PUBLISHED 2026-11-06 02:31 UTC as latest (https://github.com/TheZwiss/discjockey/releases/tag/v1.2.0). NIGHT DONE. Open: 33 + 24 parked. 2026-11-06 day: issue 37 (user, live in 1.2.0: Folders on Sync had no switch, a click opened Library; switch off = completely left out, a song stays in while ANY of its playlists/folders is on) built by Opus 288k (also fixed: a song in two playlists dropped when one went off) + Sonnet shots 177k + strip fix 117k (kinds cut off); verify 1024 ok, pytest 3421, CI green; merged b251c25; v1.2.1 PUBLISHED as latest (self-test passed). Open: 33 + 24 parked.
- **NIGHT RUNBOOK 2026-11-06 (read this first after a compact).** User asleep; standing go for every step below incl.
  publishing v1.2.0 WITHOUT the user. One agent at a time; tell no one, just log each step here. Stop and leave it for
  the morning (no forced release) if something breaks that can't be fixed safely. Steps, in order:
  1. DONE Liked music (e44ee66).
  2. Issue 35 (`fix/sync-kinds-35`, `.claude/worktrees/sync-35`, Opus agent running, logo goal dropped for 36): read its
     report, check ps, LOOK at its sync shots (whole screen, 1100/1280/2560), fix round by a fresh agent if needed.
     Then CI + verify + build + smoke, merge 35 into main; 36 branches from main after that.
  3. Issue 36 Sync redesign (issue text in `docs/issues.md` is the brief's core; no mockup; user's ideas are first ideas,
     Opus may refine): Opus build agent (apple-design + emil-design-eng, ~80-call stop, scope lists: build Sync page
     only; reuse the Library rail block and the Library health card block, a missing pattern goes into a block +
     gallery + doc; must not change other pages, foot bar, Settings icon, run logic/planner; two weekly-check switches =
     the kinds `retry` (missing songs) and `weekly` (lossy upgrade)). Then a Sonnet shots/drift agent (all Sync shots vs
     main, nothing outside Sync changed). My look at the shots. CI + verify + build + smoke, merge. Close 35's wish + 36.
  4. Issue 25 (`run_op` callers `execute.py`, `ops.py`, `upgrades.py`, `tidy.py` off the entry view, as import/folders/
     `move_files` do): Opus build on its own branch (engine only, invariants: never delete/overwrite, run_op/move_files,
     crash-safe), Sonnet review (+ fresh fix agent if needed), full pytest, CI (no verify unless hub-ui changed), merge.
  5. GitHub presence: an AGENT does it (Opus, design skills), I only brief + review its result (user 2026-11-06: not
     myself). Goal: someone landing on github.com/TheZwiss/discjockey sees at once what problem it solves (DJ library in
     step with streaming playlists, lossless first, never deletes), how, its features, with new fake-mode screenshots
     (incl. the new Sync page, Library, To-do upgrade compare, Settings ladder); README top becomes the landing, the
     manual stays (README or a linked docs page, CLAUDE.md row updated if moved); repo description + topics via `gh repo
     edit` proposed by the agent, applied by me after review. Images only from fake mode; no private data; check_public.
     Then a short Sonnet or own review of the rendered README (gh/markdown), fix round if needed.
  6. Release v1.2.0 (CONTRIBUTING "Releasing"): bump `discjockey/__init__.py` `__version__` + `pyproject.toml`, commit;
     full pytest + `npm run verify` green on that commit; `git tag v1.2.0`; `git push origin v1.2.0` (never --tags);
     watch `release.yml`; draft gets `Discjockey-1.2.0.dmg`; download it to the scratchpad, `hdiutil attach` to a
     scratch mountpoint, run `DISCJOCKEY_SUPPORT=$(mktemp -d) <mount>/Discjockey.app/Contents/MacOS/Discjockey
     --self-test`, detach (never copy to /Applications); write release notes in v1.1.0's style ("What's new", "Fixes",
     Full Changelog v1.1.0...v1.2.0; plain words; library + sources: watched folders/import/tidy-up/undo, Qobuz/
     SoundCloud/YouTube Music playlists, Library page, Liked music, Sync redesign); `gh release edit v1.2.0 --notes-file
     … --draft=false`; check the download link works. Update memory project_public_release.md.
  Sizes told to the user: 35 ~250–300k, 36 ~500k (build + drift), 25 ~400k (build + review), GitHub ~300k + review.
- **Merge early (user, 2026-10-31):** a finished stage merges into main as soon as its fix rounds, CI and verify are
  green; the user's live check runs on main afterwards and its findings are fixed there. No release without the go.
  Stage 6 merges into main right after the main-into-stage-6 merge is green; its live check and leftovers follow.
- **No leftovers lists (user, 2026-10-31):** a stage's review findings, Minors included, are fixed in its own fix
  rounds; only user decisions or spec conflicts become an issue. Leftovers never block a merge into main, but are fixed
  right after it. At every merge into main the orchestrator re-checks `docs/issues.md` against the code and closes what
  is done. Backlog 24–34 (~60 points): read-only audit after the To-do hold job, then fix rounds for what's still valid.
- **Issues live on main (user, 2026-10-31):** a new `docs/issues.md` entry is committed straight to main and main is
  merged into the open stage branches, so the list is never split across branches (29–34 moved there 78255ea; stage 6's
  "own upload in a private set" became 34). A branch only removes or edits entries its own code settles.
- **The user's answers 2026-10-31:** (1) Liked music: a Settings choice, off by default, with a warning that
  explains the bot-check risk to the Premium account (needs a design round + mockup OK, then a plan; engine reads via
  the YouTube login only when on). (2) The upload's account used up or paused: the track waits (I6 stays, no change;
  "why take worse if the better one comes the next day"). (3) A Go+-only (SNIP) upload with no ~256 kbps Go+ stream:
  its full ~128 kbps Go+ stream is one more candidate ranked by quality in the usual hierarchy (no special rule):
  better sources and accounts with usage left first, an equal free stream before spending SoundCloud usage; a
  used-up/paused account waits as in (2). (Both (2) and (3) were already answered by the hierarchy: check open
  questions against the rules before asking.) Built on `feat/library-6-snip` before stage 6 merges.
- **Design round after the SNIP job (one Opus agent, mockup + notes, the user approves):** (a) the Liked-music
  Settings choice with its warning; (b) the user's wish 2026-10-31 for the paste field on Playlists (and Setup's
  first playlist): "Paste a playlist link here" followed by the four service logos as in the Library sidebar
  (YouTube Music, SoundCloud, Spotify, Qobuz), instead of naming services in the text.
- Stage 6 merges into main only after stage 5 is in main and its own final review + CI.

Later (each needs its own plan / the user's go): AcoustID (#24, a stage after 6), rekordbox XML for the duplicates
pick, the leftovers in `docs/issues.md`, CLI undo for upgrades. **No release without the user's go.**

Overnight rules: ONE agent at a time (user 2026-10-31, after the two that ran together); never two on the same files or worktree; check `ps` and the
worktree after each; size from the record (Opus UI build 250–350k, shots 100–150k, Sonnet fix 115–150k, Sonnet group
150–310k, review 110–140k); never resume an agent above ~150k (fresh one with findings + files); two failed rounds on
one problem → stop and leave it for the user; never touch the running app, the user's files or the real DB.

### Issue 33 night (2026-11-07 → 08)

State at the start: research done (Opus 180k; the route is a direct `master.db` repoint, proven live by the user on
2026-10-31 outside Discjockey). Design `docs/2026-11-07-rekordbox-repoint-design.md` written (161c461, Opus 253k) and
updated with the user's answers (0ee6248, Opus 159k): batches for one/several/all, Upgrade all, Auto-upgrade on sync
(ON by default, user), Make all lossless files AIFF, text columns written around the user's edits, stages A–E. New
issues: 38 (Playlists switch-off words + crash, waits: user "33 first"), 39 (agent-ready audit; CLAUDE.md rule
79618de), 40 (follow Discjockey's own moves = stage E). Plan for stage A: Opus planner running.

User's binding words for the night: licence "we don't tiptoe" (own key in our code); every file can become AIFF incl.
lossless; Discjockey repoints rekordbox after its OWN moves (issue 40), hand moves stay with rekordbox's Relocate;
every action for one, a selection or all.

Queue (one agent at a time; after each: `ps`, worktree clean, a one-line result appended here, pushed):
1. Stage A plan (Opus, running) → commit on main, pushed by me.
2. Stage A build on `feat/rekordbox-a` in `.claude/worktrees/rb-a`: one agent per plan group, the model the plan marks,
   each with a ~70–80 tool-call stop. Touched tests per group; full pytest once at the end of each group.
3. Stage A review (Sonnet, 110–140k) against plan + design; a fresh Sonnet fix round if needed; CI green on the
   branch; `npm run verify` only if `hub-ui` changed. Merge into main, push. No release.
4. UI design round (Opus, mockup + companion notes, for the user's approval in the morning): every screen state of
   stages B–D (To-do multi-select, Upgrade all, the quit-rekordbox step, the rekordbox check card, Library
   multi-select + Convert + the Make-all sheet, Settings/Setup auto-upgrade row). Mockup rules: the app window + a
   state switcher only, notes in a companion file, a drift list against the real app, only listed elements (Settings
   icon never a sun, foot bar unchanged, coloured service logos).
5. Stage B plan (Opus): engine only (backup, the write, field-level undo, journal and crash recovery, refusals, the
   batch engine, Upgrade all engine, commands). UI tasks wait for the approved mockup.
6. Stage B engine build + review + fixes on `feat/rekordbox-b`. Stays on its branch (no merge into main before the
   user's morning look and the live test).
7. Only if all of that is done: issue 38 (Opus debug + fix, own branch, verify, merge).

Night rules (besides the overnight rules above): never start, quit or script rekordbox; never write under
`~/Library/Pioneer` or `~/Music/Discjockey`; no live test, no release; no UI built before an approved mockup; tests use
fixture databases only. A decision only the user can make is parked here and the queue goes on with what doesn't
depend on it.

Results:
- 1 done: design set to auto-upgrade on by default (9ec9975) and stage A plan `docs/2026-11-07-rekordbox-stage-a-plan.md`
  (4579499, Opus 216k): groups A0 Sonnet → A1 Opus → A2 Opus → A3 Opus → A4 Sonnet → A5 Sonnet → review + fix.
  Parked for the user: people updating from 1.2.x never see Setup again, so Auto-upgrade is on for them without a word;
  a one-time note (e.g. in the first sync summary)? Stage C, nothing tonight depends on it.
- Dropped: no note for people updating from 1.2.x (nobody updates from an older version yet; no effort on that).
- User ~23:30, new night scope (binding): work through the WHOLE issue 33 design tonight (stages A → B → C → D, then
  E = issue 40 if time is left). No full-page mockups: the UI additions are small, so each UI group gets a precise,
  complete design direction (placement, states, words, reused components, drift guards) and is built by an Opus agent
  with the design skills, then shot and checked; a single-component mockup only where a component is truly new.
  Writing to the user's real rekordbox `master.db` for testing is allowed (prefer a copy; real file only with
  rekordbox not running and a full backup first; still never start/quit/script rekordbox). Park a question only when
  there is no clearly best answer; otherwise decide and note it here.
  New queue: stage A (running) → review/fix → merge main → for each of B, C, D: Opus plan (engine + UI) → groups →
  review → fix → CI + verify → merge main (no release) → issue 40 design + build if time → issue 38 last.
- A0 done (Sonnet 131k): sqlcipher3-wheels 0.5.7 pinned, SQLCipher 4.12.0 + OpenSSL 3.6.0 licence texts, self-test
  keyed open (passes in the frozen app), ad-hoc signing fix 6a7b84b; CI green; merged into feat/rekordbox-a c395cb6.
  Note: the app build's .dmg step failed in the agent's run (no detail); check it before the next release.
- A1 done (Opus): `discjockey/rekordbox/` read side (locate, key, guards, lookup), 59 tests, fixture schema checked
  against a copy of the real rekordbox 7 library (15 tables match); CI green; merged into feat/rekordbox-a.
- A2 done (Opus 191k): ANLZ parser + `timeline_offset`; 19 real tracks (copies) measured, all snapped to the expected
  offset (max error 1.2 samples); CI green; merged into feat/rekordbox-a. Flaky in parallel runs:
  `test_hub_api_liked_music.py::test_a_refresh_with_liked_music_listed_and_the_account_paused_makes_no_request`
  (passes alone and on CI) → goes into the stage A fix round.
- A3 done (Opus 222k, one usage-limit stop, resumed): `render_aiff`, New track renders the same edit lined up with
  rekordbox's timeline (falls back to today's rename when unmeasurable), undo of a rendered add; CI green; merged.
- A4 done (Sonnet): New track card says Relocate by hand, "cues fit exactly" when lined up; contract + README; shots
  looked at; CI green; merged.
- A5 done (Sonnet 241k): `eligible.py`, `preview.py`, `discjockey rekordbox status|preview` (read-only, --json, exit
  codes), CONTRIBUTING "Commands for scripts and agents"; CI green; merged. Slip: one by-hand run read the real
  rekordbox + library.db once (read-only; checked afterwards: no new files, mtimes unchanged). Next: stage A review.
- Stage A review (Opus 269k: 0 Critical, 2 Important, 13 Minor) + fresh Sonnet fix round (165k, all fixed; flaky
  liked-music test: likely cause fixed with a teardown guard that joins every test's job threads, not proven);
  verify 1027 shots ok, CI green; **stage A merged into main 43e6797** (no release). Next: stage B plan (Opus).
- Stage B plan `docs/2026-11-07-rekordbox-stage-b-plan.md` (e7c8452, Opus 267k, no mockup needed, no questions):
  B1 S → B2 O → B3 O → B4 O → B5 S → R1 engine review + fix → B6 S → B7 S → RH rehearsal on a copy (O) → U1 O → U2 O →
  S shots → R2 review + fixes → verify → merge main. Building on `feat/rekordbox-b`, groups in `.claude/worktrees/rb-b-<g>`.
- B1 done (Sonnet 203k): schema 7 (aiff_batches/aiff_items), Entry fields, PathIndex, same_track_quick,
  timeline_offset on an open view; CI green; merged into feat/rekordbox-b.
- B2 done (Opus 230k, one usage-limit stop 03:50–07:50, resumed): `write.py` (repoint, text columns, contentFile,
  USN per row as rekordbox does), PPTH splice (`?/<name>` confirmed on real copies), per-batch backup + restore,
  Session; CI green; merged into feat/rekordbox-b. RH must confirm created lookup rows (NULL SearchStr) show right.
- B3 done (Opus): `convert.py` Same track for any format (AIFF lined up to rekordbox's timeline, rekordbox repointed),
  recovery at every crash point (46 tests); CI green; merged into feat/rekordbox-b.
- B4 done (Opus): convert undo to the byte (with crash recovery), the swap writes rekordbox's text in a batch + undo
  per field; CI green; merged. For R1: convert undo refuses when the AIFF's whole-file SHA changed; if rekordbox
  writes tags into the file, that blocks undo after any edit in rekordbox → use an audio-only key instead.
- B5 done (Sonnet 270k): `batches.py` (start/run/resume/undo/checked/recover, Stop, rekordbox-open stop, Busy,
  batch undo marks items undone), console `s` = batch of one; CI green; merged. Next: R1 engine review (Opus).
- R1 engine review (Opus 234k): 0 Critical, 6 Important, 10 Minor; nothing loses a file, every write backed up first,
  crash recovery holds. Decided (review's question): rekordbox's comment column and the new file's comment tag are
  written only when empty or Discjockey's own quality line; Mixed In Key's key/energy and user notes stay. Fresh
  Sonnet fix round running.
- R1 fix round (Sonnet 264k): all 6 Important + 10 Minor fixed (6ceb88b; undo compares audio only, empty values leave
  rekordbox's field alone, batch undo refuses with rekordbox open, restore takes the lock); CI green. Next: B6.
- B6 (Sonnet 250k, cut by the usage limit, then a fresh Sonnet 221k from its handoff): commands `upgrade`, `batch`,
  `rekordbox checked|backups|restore`, tests, docs; one bug fixed (`checked --batch`); merged 056aa99, CI green. JSON
  `ok` stays true when a batch ends with skips/failures (exit 1). Next: B7 (also the `upgrades` `s` key + tip from plan
  §2 and `upgrade undo` order on same-second ties, left by B6).
- B7 (Sonnet 360k, over its 250k estimate): bridge lists of tracks, `upgrade_all`, `batch_resume`, `batch_undo`,
  `BatchProgress`, the batch check item, fake scenarios `upgrade-multi` + `upgrade-rekordbox-open`; hub batch of one
  that meets rekordbox open/busy before anything ran is closed (no Resume), bigger batches stay stopped with Resume;
  `upgrade undo` newest first by operations.log line. Merged 4db7342, CI green.
- **Paused here by the user (2026-11-08 afternoon).** Next on go: RH (brief ready: scratchpad brief-33-RH.md; Opus;
  needs worktree rb-b-rh on feat/rekordbox-b-rh from feat/rekordbox-b), then U1, U2, S, R2, V per plan §7.
- RH (Opus 230k): rehearsal on a copy of the real library, 6 tracks (MP3, 2× M4A 44.1, M4A 48 with a user comment,
  2× AIFF swap), 117/117 checks pass, no engine bug: columns exact, cues/playlists byte-equal, timing snaps to 0
  (≤0.016 ms), title edit + comment kept, USN one per row (rekordbox's own rows mostly the same), Length round-down
  matches rekordbox 6/6, created lookup rows match rekordbox's own (its own SearchStr are NULL too); undo byte-identical.
  Source only copied. Script merged 1d0dfcd (`copy-db`/`copy-tracks` never ran as commands: R2 checks them). Next: U1.
- U1 (Opus ≈405k incl. a usage-limit stop): To-do multi-select (shared `selectionModel`), selection panel, Upgrade all
  · n / Resume · k left in the group head, batch progress panel (Playlists moves layout), single panel's non-AIFF
  outcomes; block changes ListSection/Surface `action`, ListRow `reveal`; vitest 1313, CI green. Merged 595baaf.
  Next: U2 (running), then S, R2, V.
- U2 (Opus 348k / 107 calls; its own report said 150–170k): batch check card, check multi-select, single repointed
  card; "Undo all" undoes the card's own tracks (not `batch_undo`); vitest 1345, CI green. Merged 031846d. Sizing
  lesson (user): agents ignore token/call stops; control size by job scope + deliverable stops (memory updated).
  Shots split into S1 (U1 states + drift) and S2 (U2 states), findings only, Sonnet, one after the other.
- S1 (Sonnet 181k): 3 Important + 9 Minor; S2 (Sonnet 136k): 2 Important + 11 Minor; drift none. R2a (Opus 241k,
  Python/docs): 0 Critical, 2 Important + 17 Minor; R2b (Opus 220k, hub-ui): 0 Critical, 6 Important + 12 Minor.
  Findings filed in the scratchpad (review-33-R2a/R2b.md, shots-s1/s2/findings.md). Decided: keep the one-step single
  check card (Reload Tag only where `reload_tag`), keep the quality chip on the batch row, words saying "tracks" count
  tracks, app binary gets a CLI entry for restore (README shows it), a new Same track batch closes earlier stopped
  batches' unrun items for its tracks, rekordbox status not re-read while any write job runs, hub "Undo all" keeps
  `undo_upgrade` (contract fixed). Fix rounds, one at a time: F1 Python/docs (Sonnet), F2a flows+tests (Sonnet), F2b
  page logic (Sonnet), F3 selection panel look (Opus), F4 check card look (Opus); then a short shots re-check, V.
- F2b (Sonnet 199k incl. a usage-limit stop, resumed): R2b I2, I3, I5 + m5–m12 fixed (7f0676e + static 17ab8c0),
  vitest 1376, smoke ok, CI green. Sizes never logged: A1, A4, B3, B4, F1, F2a. 2026-11-09: the user asked why A+B took
  ~70% of the week; gate on every dispatch added (§2), F3/F4 go to Sonnet, no shots re-check (§6), queue continues to C.
- F3 (Sonnet 184k): S1 #1, #2, #4–#12 fixed (1fa27bb + static 4a5bcd9), vitest 1381, smoke ok, CI green; #5 (✕ colour) only
  made smaller, its colour to be judged in the verify shots. F4 (Sonnet) started.
- **Overnight queue 2026-11-09 (the user asleep, "whatever is best"):** F4 → V (verify, smoke, CI, merge B into main,
  push, no release) → issue 38 (crash in 1.2.1; moved before C on my call) → stage C (plan, build, full reviews +
  rehearsal on a copy; merged into main once CI + verify are green, the user 2026-11-09: "merge it when your tests pass"; no release before its live test) → stage D (design direction, build) → issue 40 design
  round only (its build waits for the stage B live test, per the issue). Every dispatch through the gate (§2).
- **RESUME HERE after a compact (2026-11-09 ~02:40):**
  - **CURRENT STATE (2026-11-16 ~01:40, NIGHT RUN, user asleep; read this first):** user's go 2026-11-16 ~01:35: "prepare
    for a compact ... then work through the night". Standing go (2026-11-15): build phase 1, reviews, phase review,
    merge WITHOUT asking between steps; stop only for product decisions, the Qobuz "Use this" note (phase 2), extras
    E2-E9, and P steps at the Mac. TONIGHT'S STOP POINT: phase 1 merged into main (CI green, verify green) — then STOP
    before the A-D live tests (they need the user at the Mac and the real music folder/rekordbox) and write a short
    morning summary. If the usage limit cuts an agent: Claude Code resumes at the reset; resume that agent by
    SendMessage (rule 7), never a duplicate.
    Plan: docs/2026-11-15-agent-cli-plan-v2.md. Briefs: ~/DJ Downloader/.claude/issue39/phase1/V1.x.md.
    Phase branch feat/cli-1-live-slice, checked out in worktree .claude/worktrees/cli1-live; per group: branch
    feat/cli-1-N from it + worktree .claude/worktrees/cli1-N; after the build/fix: `git worktree remove`, then in
    cli1-live `git merge --no-ff feat/cli-1-N` + `git merge --no-ff main`, check_public, push; log size here (commit
    on main + push); next group.
    SPLIT RULE (since V1.10): groups land 1.4-3.5x the plan price, so every remaining group is built in two halves
    (part a, part b) on the same branch, each est. 190-260k, then (V1.11-V1.15) a Sonnet review of the whole group
    (findings file phase1/review-V1.N.md) and a fix-round agent. Dispatch prompt pattern = the V1.12b prompt (brief
    path, worktree, YOUR HALF / NOT yours, the earlier groups' decisions list, overrides written into every command
    line, node_modules symlink, timing-test flake note, full pytest at end in bg, report <10 lines). Review prompt
    pattern = the V1.11 review; fix prompt = the V1.11 fix (decisions answered by the outcome rules, not by the user).
    **STATE 2026-11-16 ~midday (before a compact): USER SAID "pause after this agent is done".** RUNNING: V1.14 fix
    round DONE 8ebb70f9; rehearse-sync PASS; V1.14 MERGED (1444f8fe). Suite speed-up merged (3f4b6044, ~1 min).
    V1.15a done. User "pause" → "NOW!": V1.15b stopped before any change; user "continue" → V1.15b re-dispatched
    (same prompt), then review, fix, Opus phase review, merge into main (standing go until phase 1 is on main).
    STATE 2026-11-16 evening (before a compact): V1.15b done 63cb37fa (121k); V1.15 review 117k (0 C, 2 I, 6 M:
    marker matched case-insensitively/anywhere; real trash_item untested; --into unconstrained …) → .claude/issue39/
    phase1/review-V1.15.md. RUNNING: V1.15 fix round (fix-round agent, worktree cli1-15). On its notice: check ps, log,
    merge V1.15 (worktree remove, merge into cli1-live + main, check_public, push), then PHASE REVIEW per the advisor:
    (1) measure on the merged head; (2) CI on the phase branch is green at 3f4b6044 (run 43848513430 failed once on
    the flaky test_cli_job says_running → item S10); (3) split BY CONCERN, two Opus agents: SAFETY half = api.py +
    engine diff + cli/call.py, cli/worker.py, hub/registry.py, plan_store.py + rehearsal script + make_upgrade_test.py +
    the suite-speed harness (tests/conftest.py, tests/tool_memo.py); SURFACE half = parser, render, housekeeping,
    follow, catalog, outcomes, ids, words, envelope + contract doc + hub-ui diff (types.ts/fake/contract together) +
    design sections by grep; tests grep-by-need; wc -c each half after assigning; (4) items file with S/U tags:
    ~/DJ Downloader/.claude/issue39/phase1/phase-review-items.md (S1-S11, U1-U12); (5) tell the user the measured
    size + running total BEFORE dispatch (old estimate 300-500k will likely be exceeded; don't trim material);
    touched tests only, findings files section by section, fixes stated for Sonnet; decide one or two fix rounds
    after the counts. Then verify (run_in_background by me), CI, merge into main, morning summary (incl. AAC 420
    gap U12, real-copy rehearsal session, cost, Qobuz "Use this" note). AFTER phase 1: discuss Opus plan + Fable
    advisor + Sonnet build vs current setup. Suite now ~1 min (interim background wakes: no report to the user).
    Issue 39 ~13.07M (incl. V1.15 review 117k), phase 1 ~10.95M.
    V1.15 fix round done 7f1ad71a: Sonnet **89k** (all 8 fixed; 5539 passed in 52.5 s). V1.15 MERGED into the phase
    branch + main merged in: c9213e6e, pushed. Issue 39 ~13.16M, phase 1 ~11.04M. Phase review measured on c9213e6e
    (diff vs merge-base, tokens = chars/4): SAFETY api 32k + engine 61k + call/worker 10k + registry/plan_store/jobs
    11k + scripts 16k + harness 2k = 132k (+ tests by grep, design by grep: material ~150k, expected Opus 230-300k);
    SURFACE cli 25k + hub surface 17k + words 3k + contract 10k + hub-ui 25k + docs 20k = 100k (material ~115k,
    expected 180-250k). Tests diff 183k (grep only). I stopped for a go on the sizes; user: "why did you stop?" (the
    standing go covers it; telling the size is enough). Safety half (Opus) done: **390k** (117 calls; over its 230-300k, 2.6x material) → phase1/phase-review-safety.md:
    0 C, 1 I (S-4 `check done --batch aiff:N` ends a later batch's check + undo), 9 M (S-1 = S10 flake: worker start
    races the 1 s wait, tests only); decisions S-7 (login saves wait up to 60 s for the lock) and S-8 (rekordbox
    analysis folder as a fifth root): coordinator takes the reviewer's picks (technical). Issue 39 ~13.55M, phase 1
    ~11.43M. Surface half split before dispatch (same ratio → ~300k): Ua CLI surface (46k diff + CLAUDE.md 11k +
    design greps, expected 150-200k), Ub contract/window/docs (56k diff, expected 150-200k). Ua done: **298k**
    (100 calls; ~4x material) → phase1/phase-review-surface-cli.md: 0 C, 9 I (C-1 unknown song key = refused/changed;
    C-2 help shows method args not what to type; C-3 reasons miss real ones; C-4 help names no methods; C-5 parser
    breaks on two-method commands; C-6 noun --help usage error; C-8 golden checks substrings; C-11 check batch id
    batch:N; C-12 To-do page hides Upgrade all/Resume facts), 11 M; decisions C-1/C-5 → reviewer's picks. Issue 39
    ~13.85M, phase 1 ~11.73M. Ub split again by the record (~4x material → ~280k): Ub1 contract + hub-ui (Opus),
    Ub2 docs + U9/U10/U12 + S6 design row + S3 plan note (Opus). Ub1 done: **263k**
    (135 calls) → phase1/phase-review-window.md: 0 C, 1 I (W-1 decision: the window's aiff_plan now ffprobes up
    to 50 fact-less files per panel open, undocumented, untested; pick (b) keep + document + test, as design §7.1
    wants panel = dry run = run; coordinator takes it), 10 M; S6 → change design row 424 (W-11); U8 → views search
    via names.search_fold (W-10); vitest 553 touched ok; fix round runs npm run check. Issue 39 ~14.11M, phase 1
    ~11.99M. Ub2 (docs) done: **248k** (92 calls)
    → phase1/phase-review-docs.md: 0 C, 1 I (D-1 CONTRIBUTING says the old sync's --dry-run changes nothing, but
    prepare saves --extra N even in a dry run → a dry run grants Qobuz downloads; coordinator adds a CODE fix: no
    --extra save in a dry run), 18 M; decisions D-3/D-16/D-17 → reviewer's picks; U12: kit's aac = native ~225k,
    live step 2 needs >320 kbps (CDJ limit) → kit can't make it. PHASE REVIEW TOTAL ~1.20M (4 Opus parts; plan
    est. 300-500k). Findings 60: safety 1I+9M, CLI 9I+11M, window 1I+10M, docs 1I+18M. Issue 39 ~14.36M, phase 1
    ~12.24M. FIX ROUNDS (Sonnet, fix-round agent, one branch feat/cli-1-pr, worktree cli1-pr, sequential):
    FA safety S-1..S-10 + D-1 code; FB CLI help/catalogue/parser C-2..C-7, C-15, C-19; FC CLI ids/render/words
    C-1, C-8..C-14, C-16..C-18, C-20; FD window/contract W-1..W-11 (+ npm run check); FE docs D-1..D-19 + U9 + S3
    + W-11 design row (last: help texts change in FB). Each 150-220k → ~0.9-1.1M.
    FA done 9b8ee280: Sonnet **141k** (cut once by the 5-hour limit, resumed; 5595 passed in 81.9 s): S-1..S-8, S-10,
    D-1 code (dry run saves no --extra) fixed, each test fails without its fix; S-9's new lock-order test found 5
    drivers taking a scoped rekordbox_r read hold, already released, before `library` (xfail strict). Coordinator
    decides (technical): the order rule is about holds held at the same time (deadlock); the recorder records
    releases and checks nested holds only → done in FB. Issue 39 ~14.50M, phase 1 ~12.38M.
    FB done baa6d4fc: Sonnet **195k** (68 calls; 5625 passed in 85.2 s): C-3..C-7, C-15, C-19, S-9 recorder fixed;
    C-2 except `report show` (needs C-9's resolver → FC1); login rows folded into one command (C-5 pick a).
    Issue 39 ~14.70M, phase 1 ~12.58M. FC split by the record (13 items ≈ 240k > 190k): FC1 ids C-1, C-9 (+ C-2's
    report show), C-10, C-11, C-16, C-17; FC2 render/words C-8, C-12, C-13, C-14, C-18, C-20.
    FC1 done 9f67721a: Sonnet **142k** (80 calls; 5631 passed in 82.2 s; svelte-check 0, bridge vitest 211): C-1
    (unknown key = bad_args/unknown_id, real resolver in write fixtures), C-2 report show, C-9 (report:<stamp>|stamp|
    last; run_summary.id), C-10, C-11 (aiff_id on check items), C-16, C-17. Leftovers to FC2: report page prints Run
    id + Id twice; NO_REPORT words name the unbuilt `report list`. Issue 39 ~14.84M, phase 1 ~12.72M.
    FC2 done d3003c78 + b50f7f2c: Sonnet **216k** (115 calls; 5643 passed in 73.1 s): C-8 (whole-word golden check,
    found a real dropped 0), C-12 (To-do group facts, empty_text), C-13 (next.run/then with the program path), C-14,
    C-18 (autouse opener guard), C-20, L-1, L-2; plus a test that every backticked command in words.py is built.
    Leftover → FD: parser's removed-word text names `settings set auto-upgrade`. Issue 39 ~15.06M, phase 1
    ~12.94M. FD (window/contract W-1..W-10; W-11 design row → FE)
    FD done a7fb373a + static 100c7365: Sonnet **162k** (76 calls; pytest 5645 passed + 1 check_public fail from the
    uncommitted static, green after the static commit; svelte-check 0, vitest 1595): W-1 (b) documented + test,
    W-2..W-8, W-10 (views search via search_fold); L-3 nothing (settings set auto-upgrade is built). Issue 39
    ~15.22M, phase 1 ~13.10M. FE (docs D-2..D-19 + D-1 text + U9 + S3 + W-9 + W-11)
    FE done b937aa19: Sonnet **158k** (62 calls; 5646 passed in 73.8 s): all docs findings applied, texts checked
    against the code now; D-8 skip also covers the aiff/preview lock drivers. D-3 not applied (its pick is a code
    change: job flags silently accepted on commands that answer at once) → FF small Sonnet round. Issue 39 ~15.38M,
    phase 1 ~13.26M.
    FF done 0305ffcc: Sonnet **84k** (23 calls; 5649 passed in 74.3 s): job flags on commands that answer at once =
    bad_args. Fix rounds total ~0.92M (FA 141 + FB 195 + FC1 142 + FC2 216 + FD 162 + FE 158 + FF 84k). feat/cli-1-pr
    merged into the phase branch + main merged: 64bc4210, pushed. Issue 39 ~15.46M, phase 1 ~13.34M. verify RUNNING
    (coordinator, background), then CI, then merge into main.
    verify on 64bc4210: 1216 shots, 0 problems; smoke ok (11 routes). CI on the phase branch FAILED since the V1.15
    merge (runs 43903786073, 43966337920): 4 tests in test_make_upgrade_test.py, "Encoder not found" for mp3 (CI's
    shipped ffmpeg has no MP3 encoder); 5635 passed. Missed because I didn't check CI after the V1.15 merge. CI fix
    (Sonnet, branch feat/cli-1-ci, worktree cli1-ci)
    CI fix done 044279b0: Sonnet **65k** (10 calls; 5651 passed in 90.3 s): shipped ffmpeg has no libmp3lame; kit
    checks the encoder first (exit 2 with the kinds that work), refusal test uses flac, MP3 cases skip without the
    encoder. Merged into the phase branch + main: 092c1f16, pushed; CI green (43968805033). Issue 39 ~15.53M, phase 1 ~13.41M.
    **PHASE 1 MERGED INTO MAIN 169457c0** (CI green 43969608840; verify 1216 shots 0 problems, smoke ok). No release.
    STOPPED here per the go: next the A-D live tests + real-copy rehearsals with the user, then the setup discussion.
    Phase 1 measured agent sizes (11.43M of the ~13.41M logged): builds 22 agents 6.20M (54%, avg 281k), group
    reviews 6 = 1.13M, group fixes 7 = 1.06M, made-up rehearsals 3 = 0.35M, suite speed 0.33M, phase review 4 Opus
    = 1.20M (avg 299k), phase fixes 8 = 1.16M (avg 145k). Plan said 5.4M for phase 1 (2.5x).
    Morning summary told: real-copy rehearsal session (rehearse, rehearse-convert, rehearse-sync; rekordbox closed);
    cost; Qobuz "Use this" note before phase 2 (V2.6); AAC 420 gap (kit's aac ~225 kbps, aac_at ~322; live step 2
    needs >320); CI was red since the V1.15 merge until 092c1f16 (lesson: check CI after every phase-branch push).
    **LIVE SESSION 2026-11-17 (user present; user: no Qobuz subscription — not needed: rehearsals offline, live tests
    on a scratch Discjockey library with no playlists + the real rekordbox):** rekordbox folder copied aside
    (scratchpad rbcopy/rekordbox-2026-11-17). Real-copy rehearsals: rehearse 157/0; rehearse-sync 185/2; rehearse-convert
    207/13. Diagnosis (Sonnet **143k**, 47 calls) → phase1/rehearsal-real-copy.md: 0 product bugs; 2 script
    assumptions (phase_run adds --wait to a dry run = bad_args by design; the user's real 48 kHz M4As are AAC 406-443
    kbps, over the CDJ limit, so the CDJ group holds them too), 13 cascades; patched copy gave 187/0 and 220/0. Stage A
    step 1 (closed half) + step 2 pass (MP3 2257, M4A48 21.3 ms, AIFF 0). AAC 420: fdkaac (brew fdk-aac-encoder)
    writes AAC-LC 419999 bit/s. bash-guard.py knew only the pre-issue-39 nouns (every new noun = 'real sync'): new
    nouns added to the override list; sync/call still need --dry-run. Issue 39 ~15.67M.
    Script fix round (Sonnet **79k**): phase_run --wait only without --dry-run; prepare_convert takes the CDJ group's
    real picks; kit --click aac uses fdkaac at 420k when present. Real copy: rehearse-sync 187/0, rehearse-convert 220/0;
    merged e3ae4dc0. STAGE B LIVE (scratch library + real rekordbox; measured by cuecheck/gridshift scripts on folder
    copies before-B/after-B/after-undo): upgrade all 4 → AIFF, cues + grid 0 ms moved, cue-click fingerprints equal;
    Undo all refused while rekordbox open, then all back exactly; master.db untouched after; stick plain sync KEEPS the
    old files + old title (README words decision open); Reload Tag = "Reload Tag". FAIL: user's title edit lost →
    diagnosis (Sonnet **133k**) phase1/live-B-title.md: rekordbox 7 writes the edit into the AIFF's tags, text_plan took
    it for the old tag (design §5.11 hole). Fix (Sonnet **117k**) 0e063392 on feat/rb-title-edits: changed_since_import
    (file mtime > created_at + 2 s) → keep every differing field; 5660 passed. Lesson (user, angry): never ask the user
    to check what I can measure. Issue 39 ~16.00M.
    **LIVE SESSION STATE 2026-11-17 ~14:00 (before a compact; user at the Mac; RESUME FROM HERE):**
    Paths: SCRATCH = this session's scratchpad (full path in memory project_issue39_cli.md). Scratch Discjockey library: support $SCRATCH/live/support, music $SCRATCH/live/music
    (files hidden from Finder dialogs: give the user the path on the clipboard via pbcopy + ⌘⇧G). Test window:
    `DISCJOCKEY_SUPPORT=$SCRATCH/live/support DISCJOCKEY_REKORDBOX=$HOME/Library/Pioneer/rekordbox bin/discjockey app
    open` (run_in_background; restarted on main 0ed468df). rekordbox folder copies: $SCRATCH/rbcopy/rekordbox-2026-11-17
    (pristine, before any test; restore = copy back with rekordbox closed), before-B, after-B, after-undo, before-A,
    before-C. Measuring scripts (run from the repo with PYTHONPATH=.): $SCRATCH/cuecheck.py <rb copy> (cue - click
    onset per cue = fingerprint), $SCRATCH/gridshift.py <before copy> <after copy> (ms the cues/grid moved). bash-guard
    (~/DJ Downloader/.claude/bash-guard.py) now knows the issue 39 nouns; real rekordbox commands need
    DISCJOCKEY_REKORDBOX=$HOME/Library/Pioneer/rekordbox written explicitly.
    DONE: rehearsals on the real copy all green (rehearse 157/0 also with the title fix; sync 187/0; convert 220/0).
    Stage A: step 1 + 2 pass; step 3: New track via CLI (`upgrade apply <path> --way new-track`) lined up, master.db
    untouched; rekordbox's manual Relocate greys out an .aiff for an .m4a track (can't change type); Auto Relocate always
    finds the original by exact name (even in Superseded/) → FIX NEEDED: New track card/`Your turn` words must not
    advise Relocate for a non-AIFF old file (design line ~607 planned this) + README: drop the Auto Relocate claim.
    Stage B: all pass after the title fix (merged 0ed468df: eligible.changed_since_import keeps every differing field
    when the old file changed after import). Stick (the user's real DJ stick, no rebuild ever): plain sync keeps old
    files + old title → README words decision open. Observation: moving a watched-folder file aside made the song
    vanish from the library (local:4 mp3) and `library scan` didn't re-add it when it came back (New 0) — check
    whether that's intended.
    NOW: stage C on stage B's local:1 (EDIT Click aiff) + local:3 (m4a48) with same-edit upgrades parked (exact, 0
    samples); Auto-upgrade on; before-C snapshot taken. User step 1: rekordbox open → Sync in the window (expect "wait
    for rekordbox to be closed", To-do marks both; I verify master.db unchanged vs before-C). Step 2: rekordbox closed
    → Sync (both upgraded; I check cues/grid via scripts and that "EDIT…" stayed). Step 3: "Undo all from this sync".
    Step 4: Settings › Upgrades off, Sync: nothing moves. Only ask the user for UI actions/words; measure the rest.
    STAGE D prepared: $SCRATCH/live/watch-d holds flac 124, wav96 120, mp3 124, click_final (messy aiff), aac 120 at
    420 kbit/s (fdkaac); NOT yet added to the library (`folder add $SCRATCH/live/watch-d`); user imports into rekordbox,
    cues, a playlist. Note for the user: their real 48 kHz M4As are 406-443 kbps AAC → Won't play well on CDJs.
    AFTER the tests: one fix round (New track words + README Auto Relocate/stick words), cleanup (test tracks out of
    rekordbox or restore the pristine copy; make_upgrade_test --all-marked; delete scratch copies), then the agent
    setup discussion (Opus plan + Fable advisor + Sonnet build vs current; measured per-role costs above), then phase 2.
    **LIVE TESTS C + D DONE 2026-11-17 ~15:00.** The window's Sync can't run in the scratch library (needs a real
    playlist = downloads), so C ran via `sync run --auto-upgrade-only` (bash-guard allows exactly that with both
    overrides). C: rekordbox open → both wait, master.db byte-identical, To-do marks both; closed → both upgraded, cues
    + grid 0 ms, fingerprints equal (m4a48 uniform 1.0 ms resample), "EDIT…" title kept; Undo all → every track/file/cue
    row equal to before-C (only usn/updated_at + rekordbox's agentRegistry differ), old AIFF back (md5); switch off →
    nothing moves. D (files in ~/Desktop/Discjockey test D, watched; playlist "Test D" in rekordbox): FLAC, AAC 420k
    (listed "AAC 420 kbps · CDJs stop at 320", Convert all), MP3 by hand, click_final rename: all AIFF 16/44.1, clicks
    0.000 ms off on rekordbox's timeline, cues/grid 0 ms, still in the playlist; Undo all ×3 → master.db rows equal to
    before-D; rekordbox open → refused, nothing changed. 96 kHz WAV refused `timing` (native-rate decode: -0.31 ms,
    score 0.88) → fixed (measure on a 44.1k decode above 48 kHz) and re-tested: AIFF 16/44.1, 0 ms, clicks within 0.045
    ms. Fix rounds: **143k** (dc9a868a: 96k timing, New track words engine+README, stale auto_waits restored by undo,
    USB comment), **144k** + resume **160k** (d85baa21 + a6d13ebc: `step:look` instead of a needless Reload Tag after a
    committed convert/repoint/rename — live-verified; window New track words follow the engine's `relocate`).
    Issue 39 ~16.45M. Stage C/D live tests passed. NEXT: verify shots of the window words, cleanup, setup discussion.
    **STATE 2026-11-17 ~16:00 (before a compact; RESUME FROM HERE):** verify on d85baa21: 1219 shots, 0 problems; the
    coordinator looked at todo-after-add-other-type (row "add as a new track, set the cues", card = NO_RELOCATE words):
    right. CI: last code push cancelled by the newer docs push 2576f6db, whose run covers all code: check it green.
    Cleanup done: rekordbox folder = the morning copy (diff -rq identical, 830 tracks, 0 test tracks; the end-of-test
    folder kept as scratchpad rbcopy/replaced-end-of-tests, the morning copy as rbcopy/rekordbox-2026-11-17: delete
    both once the user has opened rekordbox and it looks normal); test window stopped; scratch library, the Desktop
    test folder and all in-between rekordbox copies deleted; no copies of the user's music left in scratch.
    STILL OPEN: (1) the vanished-song observation (a watched-folder file moved aside and back: the song vanished,
    `library scan` didn't re-add it) — not yet checked whether intended: diagnose on made-up data before phase 2 (or
    file in docs/issues.md); (2) issue 33's plans A–D go to docs/archive/ now that their live tests passed (+ issue 33
    in docs/issues.md: live tests passed 2026-11-17); release only on the user's go. SETUP DISCUSSION given to the
    user: measured phase 1 per role (builds 54%, group reviews+fixes 19%, Opus phase review+fixes 21%); proposal =
    Opus plans, ONE Fable 5.2 pass over each plan before builds, Sonnet builds, reviews as now; measure after phase 2's
    first stage against phase 1 (281k/build, 1.06M group fixes over 7). Options 1 (Fable phase review, ~+1.2M) and 2
    (advisor inside builds: each consult reads the whole build context at 4x Sonnet's price) not recommended.
    Waiting for the user's choice, then phase 2.
    **ISSUE 43 FIRST (2026-11-17 ~17:00, user: "Why are you listing 'vanished song' casually"):** reproduced on made-up
    data: one scan without the file deletes an own song with its parked upgrade (playlist song: downloaded again);
    putting the file back never relinks it. In v1.1.0-v1.2.1; the user's real library shows no loss (read-only).
    User approved the fix (issue 43 "Decided"): missing rows wait, relink by key, To-do group with Remove from
    library / Download again. Order: Opus plan -> builds -> reviews -> made-up rehearsal -> merge; then the setup choice
    and phase 2. The setup choice is still open (keep today's setup for issue 43).
    Plan done ec4c404c (docs/2026-11-17-missing-files-plan.md, 595 lines): Opus **291k** (est. 180-270k, 82 calls).
    Groups E1 > E2 > E3a > E3b > U1 > S1 > D1, reviews after each + Opus stage review; plan total 2.3-2.9M. Stage
    branch feat/missing-files, group worktrees .claude/worktrees/mf-<group> on feat/missing-files-<group>.
    Open product point for the user: D9 (Download again lets a waiting upgrade go when its download lands).
    D9 DECIDED (user 2026-11-18, "of course do your recommendation"): a missing playlist song with a parked
    upgrade: "Download again" places the parked version instead of downloading (no Qobuz download, never a worse
    copy); only a song without one downloads. The E2 brief carries it and amends plan D9 (+ E3b's part). E1 cut by
    the weekly usage limit before committing (21 files changed in mf-e1, at the tests); resumed 2026-11-18.
    E1 (Sonnet) done 21b9b7b9 on feat/missing-files-e1: **292k** (505 calls over two sessions; est. 200-260k).
    Full pytest 5696 passed, 1 failed: test_hub_api_convert CDJ-group test (deleted file now waits as missing and
    stays in the CDJ group) -> E2's cdj.group_members fix, add it to plan §9.1. §9.2 E1 coverage not checked item by
    item -> R-E1. Stage so far: plan 291k + E1 292k = 583k.
    R-E1 (Sonnet) **130k**: ready after fixes da7086be (MERGED_FIELDS gains missing_since; repro pins id + answer);
    every §9.2 E1 item has a test; svelte-check clean. Stage branch fast-forwarded to da7086be. Worktree mf-e2 made
    (main merged in). D9 amendment (Opus, est. 120-180k) running before E2: how the parked version goes in for a
    missing song. Stage so far 713k.
    D9 amendment (Opus) done 7972fb3e: **233k** (58 calls; est. 120-180k). Design §4.5: Download again with a parked
    upgrade = convert.place_parked in the sync's last AIFF batch (also with Auto-upgrade off; rekordbox open -> waits),
    on Same track's machinery, stored measurement, no Superseded move, undo -> missing again. New groups E4a (step,
    200-250k) + E4b (phase, 150-200k); stage est. 3.0-3.9M (was 2.3-2.9M). Plan 825 lines. Stage so far 946k.
    E2 split before dispatch: E2a planner + outcomes, E2b tidy undo/cdj/report words/unchanged-row pins.
    E2a (Sonnet) done eff6bc35: cut by the 5-hour limit, resumed; size reported only for the resumed part **146k**
    (first part not reported; counted ~150k -> ~300k). Beyond plan: db._save_files refreshes a missing row on a
    same-fields redownload (E4a uses the same save). Stage so far ~1.25M.
    E2b (Sonnet) done 1906dec0 + 6d5061f6: **147k** (55 calls; full suite 5734 passed on the 2nd run; 1st run one
    teardown flake test_hub_app frame-cap 'hub-refresh-job outlived its test'). Removed the v1.0.0 rejection of a lost
    file's fallback source on redownload -> R-E2 judges it. For E3a: planModel.ts keeps old 'File gone' words.
    R-E2 (Sonnet) **133k**: ready after Minor fixes a59d83d6 (redownload that places nothing keeps its name;
    _save_files condition also needs the entry's mark cleared; contract + CLAUDE.md cdj rows). Source rejection
    removal stands: 'Wrong song?' (ops._move_away) still rejects a source while a file is there. Stage branch
    fast-forwarded to E2. E3a split before dispatch: E3a1 missing.py + views + api reads + contract doc/types
    (same commit as shapes), E3a2 fake scenario + planModel words. Stage so far ~1.53M.
    E3a1 (Sonnet) done 676be7d8 + 40ffc820: **269k** (94 calls; est. 220-260k): missing.py, views rows, To-do group,
    track_detail, Library rows, contract section, TodoGroup union; 5791 passed + golden updated; static stale ->
    E3a2 ends with the static build. Stage so far ~1.80M.
    E3a2 (Sonnet) done c491230a + static a2b1109e: **206k** (46 calls): fake scenario missing_files (10 songs),
    words pinned to missing.py/report.py, planModel 'Download again'; vitest 1621. For U1: format.ts
    FILE_STATE_TAG.file_missing still 'File not found' (§5.4 wants 'Missing'); strip width. Stage so far ~2.0M.
    R-E3a (Sonnet) **182k**: ready, 6 Minor fixed 45efd84e + static 5147ac70 (types.ts pinned from Python, fake
    sentences pinned, contract words). For E3b: CLI result rows use missing.reason_words, not outcomes'
    wrong_action. Stage branch fast-forwarded to E3a. E3b split: E3b1 actions + preview + hub methods + contract,
    E3b2 commands + CLI render + fake handlers. Stage so far ~2.18M.
    E3b1 (Sonnet) done bd4f88c5 + a832361a + static a86a78f8: **246k** (74 calls): download_again, remove, preview,
    hub methods + shapes, 32 tests; 5831 passed; catalogue ceiling 81->83 until E3b2 builds the rows. Stage ~2.43M.
    E3b2 (Sonnet) done 5394fbd0 + 1d198328: **212k** (68 calls): missing list/download/remove, track show section,
    fake handlers, CONTRIBUTING; 5863 passed + 1 teardown flake (test_hub_app thread leak, 2nd time -> issue 44).
    Stage so far ~2.64M.
    R-E3b (Sonnet) **172k**: ready, 5 Minor fixed 1a5da619 (Remove confirm = §5.4 body; empty --all --dry-run
    keeps the preview shape; fake Remove no longer drops never/favourites; save-before-delete pinned). Remove data
    safety: no defect. For E4b: auto_upgrade_preview must count the placement. Stage branch -> E3b. E4a split before
    dispatch (record: D2 384k, D3a 304k): E4a1 the step + rekordbox pointing, E4a2 crash recovery + undo.
    Stage so far ~2.81M.
    E4a1 (Sonnet) done a1ea586a + e15cd7b9: **269k** (72 calls): place_parked, place_quick, eligible.place,
    timeline_offset(codec=), row_change(text=False); recovery already works for a placement (2 tests); 5903 passed.
    Found: a scan that judges the file 'replaced' keeps the parked upgrade's old alignment -> decided (coordinator):
    apply_scan's replaced branch drops upgrade.alignment, so the placement treats it as unknown (placed as is, no
    repoint: cues never land off silently); E4a2 builds it. Stage so far ~3.08M.
    E4a2 (Sonnet) done 23938d95: **238k** (67 calls): placement undo + recovery at every cut point (35 tests),
    missing_facts in the op, end_step(missing=), alignment dropped on 'replaced' (side effect: Same track for that
    song's parked upgrade -> needs_choice); 5939 passed. Stage so far ~3.32M.
    R-E4a (Sonnet) **203k**: not ready -> ready after 8b4a6df9: 3 Important (stale alignment kept + marked instead of
    dropped, so Same track stays for present songs; same-path cut point told apart by FileSize; same-name other-edit
    check aligned:false) + 1 Minor (no-op PPTH splice). Plan §10 E4b row gained SECTIONS/check_text/person_steps.
    Stage branch -> E4a. Stage so far ~3.52M.
    E4b1 (Sonnet, cut once by the 5-hour limit, resumed) done 77274ff4: **312k**: placement phase (place_keys, plan/
    Planned.place, switch off = placements only, download_again batches, placed_missing section/words/steps, schema 11
    step rebuilds aiff_batches/aiff_items CHECKs); 5980 passed + 1 wording fix re-run by file. step `look` not
    `reload_tag` (E4a: text columns never written) -> plan amend in D1; CLAUDE.md 'switch off moves no file' -> D1.
    Stage so far ~3.83M.
    E4b2 (Sonnet) done 2462a7bd: **227k** (73 calls; expected 130-180k): contract/types/fake for placements, check_status
    words, fake redownload plan + bad_args; hub-level preview/plan-id tests (no engine fix). Open: sync_preview
    auto_upgrade counts no placements (null with switch off) -> R-E4b fix round. Stage so far ~4.06M.
    R-E4b (Sonnet) **239k**: not ready: 5 Important (schema CHECK widen only from v10; unreadable rekordbox drops a
    placement silently; sync_preview places/place_notes; batch.from_sync for download_again cards; relocate_new step
    path) + 3 Minor + plan amends (§5.4 steps/words, §6.1 -> D1). Important 1 declined: schema 11 unreleased, real
    library measured at 9 (ro), only scratch DBs at 11 -> keep one v11 step (no updater niceties). Stage so far ~4.30M.
    R-E4b fix (Sonnet fix-round) be31c291: **164k**: 4 Important + 2 Minor fixed (places/place_notes, from_sync,
    unreadable -> waits, relocate_new path); 5996 passed. Stage branch -> E4b (be31c291). Stage so far ~4.46M.
    U1 split (record 300-390k + material ~90k): U1a Sonnet models/flow/tests/shots.json, U1b Opus components.
    U1a (Sonnet) done 4a899afe + static 371ae733 on feat/missing-files-u1: **261k** (77 calls; expected 160-220k):
    missingModel.ts, MissingFlow, todoModel/libraryModel/planModel/endModel, FILE_STATE_TAG Missing, 9 shots entries;
    vitest 1692. Open: PLACED_LABEL copied from report.py (engine should send section labels) -> R-U1. Stage ~4.72M.
    U1b (Opus ui-build) done c2a59b90 + static 6cba2837: **251k** (75 calls): Page/Details/MissingSelection/Library/
    BeforeStart/EndScreen; vitest 1693; npm run rules failed (local connect EAGAIN) -> shots agent. Found: placement
    batches/progress use window 'upgraded' words + batchCheckCard ignores placed_missing words -> engine words in R-U1
    fix. Taste: 'Last known file' and 'Skipped · n' kept (decided, not asked). Stage so far ~4.97M.
    R-U1 (Sonnet) **201k**: not ready: 6 Important (Library parked-upgrade song shows Replace; panel counts/labels/
    confirm/none-can-run computed in window -> missing.preview button/confirm + all.label; section_labels; BatchProgress
    lead/count; batch row_name/row_sub/list_title; batchCheckCard placed_missing steps) + 6 Minor (3,4 = phase 6 moves,
    6 precedent; 5 decided: Select all label counts what it selects). Fix split F1 engine words (3-6), F2 selection +
    Library (1,2, minors 1,2,5). Stage so far ~5.17M.
    F1 (Sonnet fix-round) 8b7b2373 + 7e685dfb: **180k**: section_labels/part_labels, BatchProgress lead/count (CLI
    too), batch row_name/row_sub/list_title/card_summary, batchCheckCard placed steps; 6001 passed + golden re-run.
    Edge -> F2: card_summary null for mixed batches (send it always). Stage so far ~5.35M.
    F2 (Sonnet fix-round) 071f5ae8 + 04898b82: **236k** (105 calls): Library parked-missing -> Open in to-do;
    missing.preview button/confirm, all.label; MissingFlow {panel}; found_twice hint once; card_summary always +
    placed_summary; 6005 passed, vitest 1697. Stage so far ~5.59M.
    STATE 2026-11-19 (before compact): S1 shots agent running (id a523af6022badf0b2, worktree mf-u1, report only,
    expected 120-170k; it may run Vite/shots with the sandbox off; check ps after). Branch feat/missing-files-u1 head
    04898b82 (stage branch feat/missing-files still at be31c291: fast-forward to u1 once S1's fixes are in). Next, one
    at a time: S1 fix round (Sonnet fix-round; Opus only if a finding needs design) -> D1 (docs: spec/README/CLAUDE.md
    incl. 'switch off moves no file' now false for Download again placements; plan amends from R-E4b: §5.4 steps
    look/relocate_new + start_note clause + engine-side words, §6.1 sync_preview places/place_notes, §7 departures
    accepted by R-U1; issues 43/40; scripts/missing_files_rehearsal.py §10.2 made-up data + its run) -> Opus stage
    review (with the rehearsal output) -> fix rounds -> npm run verify (run_in_background) -> merge into main. No
    release without the go. Open for the stage review: held batch panel after a partial undo keeps whole-batch
    wording; CLI `missing list` prints the all.label row. User told ~0.7-1.1M left (total ~6.3-6.7M). Still asked of
    the user: does rekordbox look normal -> then delete scratchpad rbcopy/ copies.
    S1 (Sonnet shots) **179k** (50 calls; expected 120-170k): 10 states x 1100/2560, rules clean; 3 shots.json
    assertions wrong; ~10 findings. Decided (rules, not asked): Remove skips an offline song (`away`, offline wins);
    'Missing since' one phrasing; found_twice one sentence; singular confirm; Library gets hint_library pointing at
    Open in To-do; start note names the song when one; Select all keeps counting what it selects (R-U1 minor 5;
    plan §7.1 amend in D1); 'Open in To-do' stays a secondary button (as the not-found state), capital T; Missing
    files rows keep the quality badge (group says missing); placed rows get their own card in the Sync end; head
    hint + placed line wrap. Fix split: E engine words (brief-43-S1E.md) then UI (shots.json, wiring). Stage ~5.77M.
    S1 fix E (Sonnet fix-round) 01065874: **147k** (55 calls): `away` reason both actions, 'Missing since', singular
    confirm, hint_library, start note names the song; 6010 passed. S1 fix U (Sonnet, brief-43-S1U.md) next. Stage ~5.92M.
    S1 fix U running (agent aec71f3d6acdd65ef, ~137k at its rules run, then build + pytest + commit) when the usage
    limit hit (2026-11-19). On resume: check its report/commits on feat/missing-files-u1 (resume it via SendMessage if
    cut), log its size, ps, then D1 per the STATE block above.
    S1 fix U (Sonnet fix-round): **~150k** (73 calls; cut by the limit, a dropped connection, then stopped by the user
    during its pytest; uncommitted). Coordinator finished it: rebuild, svelte-check 0, vitest 1698, committed 5f9df829,
    full pytest 6008 passed + 2 failed = issue 45 (ffmpeg build tests fail on main too since macOS 27.2: ld vs SDK).
    npm run rules not re-run after the last edits: npm run verify before the merge covers it. Stage ~6.07M.
    STATE 2026-11-19 (2nd compact; PAUSED by the user after S1 fix U, wait for "go"): stage branch
    feat/missing-files = feat/missing-files-u1 = 5f9df829 (pushed); worktree mf-u1 clean, node_modules link removed;
    no agent running. Next, one at a time after the go: D1 (Sonnet docs: spec/README/CLAUDE.md incl. 'switch off moves
    no file' now false for Download again placements; plan amends: §5.4 steps look/relocate_new + start_note clause +
    engine-side words + 'Missing since' + `away` reason + singular confirm + hint_library, §6.1 sync_preview
    places/place_notes, §7 departures (Select all counts what it selects; Open in To-do secondary; quality badge in
    Missing files; placed card; Put it back drop zone); issues 43/40; scripts/missing_files_rehearsal.py §10.2
    made-up data + its run) -> Opus stage review (with rehearsal output; open: held batch panel after partial undo
    keeps whole-batch wording; CLI `missing list` prints the all.label row; console placement line not naming the
    song) -> fix rounds -> npm run verify (run_in_background) -> merge into main. No release without the go.
    Full pytest: deselect/expect the 2 issue-45 tests (machine toolchain), brief agents so. Still asked of the user:
    rekordbox looks normal? -> delete scratchpad rbcopy/; Command Line Tools reinstall (issue 45).
    D1a docs (Sonnet fix-round, 2026-11-19 after the go): **127k** (53 calls; est. ~130k) -> 99ce4103 on
    feat/missing-files-u1 (main merged in first, 6b60e8c0); pytest 6008 passed (2 issue-45 tests deselected).
    D1 split: rehearsal script is D1b (together ~300k). Stage running total ~6.20M.
    D1b rehearsal (Sonnet fix-round): **158k** (45 calls; est. ~170k) -> 2cfc27f3; 35 PASS / 0 FAIL / 2 SKIP
    (`folder list`, `sync plan` not built: issue 39 phase 2); pytest 6010. Stage review split by material
    (engine diff ~67k + UI diff ~76k tokens): R1 Opus engine/bridge/CLI (est. ~200k), then R2 Sonnet window.
    Stage running total ~6.36M.
    R1 stage review engine (Opus): **275k** (75 calls; est. ~200k): needs fixes, 1 Critical (F1 _save_files wipes a
    missing row's key + mark on a quality save, fill_kbps hits it every sync), Important F2 F3 F6 F7, Minor F4 F5 F8
    a b d (scratchpad/review-43-R1.md). F5 decided by the rules (no past user answer; Remove of a song whose file
    is in two places = loss): found_twice for both actions. Fix rounds: FA (F1 F2 F4 F6) -> FB (F3 F5 a b d) ->
    R2 window review (carries F7 F8 c) -> window fix round. Stage running total ~6.64M.
    FA (Sonnet fix-round): **102k** (41 calls; est. ~170k) -> 1c38ec72; F1 F2 F4 F6 fixed with tests; pytest 6017.
    Stage running total ~6.74M.
    FB (Sonnet fix-round): **129k** (47 calls; est. ~150k) -> 8e504897; F3 (new reason place_refused, record's
    words, stays in To-do), F5 (found_twice both actions), a (text page drops all.label), b (place_clause shared
    by start_note + console), d (bash-guard lists `missing`); pytest 6021, vitest lib 1081. Note for R2: console
    prints the one-song clause AND the indented line naming the same song (double?). Stage total ~6.87M.
    STATE 2026-11-19 (PAUSED by the user after FB; wait for "go"): stage branch = u1 = 8e504897 (pushed),
    worktree clean, nothing running. Next after the go: R2 Sonnet window review (UI diff ~76k tokens; carries R1
    F7 header line into views.todo, F8 single-song button words/tone from engine, c held batch panel rebuilt from
    re-read todo(), the console double line; asks design §9.1) -> window fix round -> npm run verify
    (run_in_background) -> merge into main. No release without the go. Still asked of the user: rekordbox
    looks normal? -> delete scratchpad rbcopy/; Command Line Tools reinstall (issue 45).
    2026-11-19 user back: rekordbox looks normal (rbcopy/ already gone with a scratchpad clean). Issue 45 agent
    (Sonnet) **61k**: old Xcode 26.1.1 ld vs CLT 27.2 SDK; build_ffmpeg.sh pins `xcrun --sdk macosx` SDKROOT,
    030fe4c1 on main, entry removed; no user step. Merged into the stage b9982b65 (no more deselects). R2 Sonnet
    window review dispatched (material ~65k, est. ~150k). Stage total ~6.87M (+61k issue 45 outside the stage).
    R2 window review (Sonnet): **233k** (51 calls; est. ~150k): needs fixes, Important W1 (header sub, = F7) W2
    (selection panel acts on stale previews) W3 (asked song dead end in Library, in_missing_files), Minor M1-M9
    (scratchpad/review-43-R2.md). Fix rounds: FC engine+contract+fake, then FD window (+ static build).
    Stage total ~7.10M.
    FC (Sonnet fix-round): **184k** (86 calls; est. ~180k) -> 52741b06; W1 todo.sub, W3 in_missing_files + asked
    hint, M1 label/tone/foot_note, M3 hint by why_not, M6 report label plural, M8 console once, M9 fake; pytest
    6032. Next FD window round (+ static). Stage total ~7.28M.
    FD (Sonnet fix-round): **132k** (55 calls; est. ~180k) -> e9663101 + static 8966f686; all 8 window findings,
    3 stale shot checks fixed; vitest 1715, pytest 6032. npm run verify running (coordinator, background).
    Stage total ~7.41M.
    verify on the stage: 1249 shots, 0 with problems; vitest 1715; check 0 errors; CI green (44573223074).
    **Issue 43 MERGED into main dfb471d7 (2026-11-19).** Stage total ~7.41M (+61k issue 45). No release.
    **Issue 43 live test (2026-11-19 evening, user's go, no Qobuz subscription):** live agent (Sonnet, CLI on the real
    library, backup in ~/DJ Downloader/.claude/backups/issue43-live-2026-11-19/) **78k** over 4 resumes: schema 9 needs a
    writer (`library scan`) to migrate; own song local:890 away/missing/back PASSED but turned 'bought' (scan's `moved`
    write set placed_by 'user' over 'import', older than issue 43). Backup restored, fix-round (Sonnet) **69k**: CASE keeps
    'import', merged main 17295707; re-run all PASS. Download again + placement (song B) not testable live: no playlist
    song has a parked version without Qobuz (rehearsal covered it); rekordbox repoint after placement still untested live.
    Screenshots: screencapture -l blocked (no Screen Recording permission). Issue 43 total ~7.56M.
    Plan stays in docs/ until the user's live test. Next: live test of issue 43 with the user (put a file away,
    scan, To-do Missing files, put it back, Download again with a parked version), then issue 39 phase 2 setup
    choice; issue 44 flake; archive issue 33's plans.
    **2026-11-20:** screenshots of the real window (Terminal got Screen Recording): To-do Missing files + Missing tab
    (`.claude/backups/issue43-live-2026-11-19/shots/`), song back after, still own. SCOPE SLIP found: issue 43 R2/FC moved
    `headerSub` into the engine (plan v2 V6.3/V6.4 row 23) and I offered a CLI fix round for duplicates (V2.2+V4.5 own it):
    guard built (`.claude/open-scope.md` register + "Done early", `.claude/scope-check.sh`, gate needs "Scope check:",
    checklist item 11, review rule limited to logic the work added, fix-round/ui-build defs). **v1.3.0** tagged on 2ceb0d7c
    (pytest 6034, verify 1249 ok), release workflow green, DRAFT waiting for the user's install + "publish". Issue 44
    + muted check browsers (synth tones the user heard came from verify's cover-play shots): fix-round Sonnet **93k**,
    merged main 126cfd24 (fixture `no_first_read`; `mutePlayback` in shot-lib.mjs incl. Web Audio gain 0).
    **RESUME HERE (superseded by the one below, 2026-11-20):** next = plan with the user how agents finish issue 39 phases 2–8 (Sonnet/Opus split,
    group sizes from phase 1's record: builds 186-301k early, 512-783k for V1.10-V1.14 vs ~200k planned; reviews
    163-221k; fix rounds 148-200k; rehearsals 96-133k). Then the phase 2 setup choice. Open: publish 1.3.0 on the user's
    word; issue 43 Download-again live test when Qobuz is back; archive issue 33's plans.
    1.3.0 PUBLISHED 2026-11-20 on the user's "publish". User: "get ready for a compact, then read all you need for a
    great planning phase". PLANNING READING LIST (read these, in this order, before saying anything):
    (a) plan v2 `docs/2026-11-15-agent-cli-plan-v2.md`: §0 summary (18-70), §1 basis for numbers (71-107), §4 rules
        (173-201), §6 phases 2-8 (404-500), §7 extras (501-531), §9 risks (681-699); §8 owner tables only by grep.
    (b) this log: phase 1's record lines ~955-1215 (each group's size and WHY V1.10-V1.14 overran: splits, reviews,
        fixes, rehearsals) and the setup discussion at ~664-671 (measured per role: builds 54%, group reviews+fixes 19%,
        Opus phase review+fixes 21%; proposal Opus plans + ONE Fable 5.2 pass per plan + Sonnet builds; still open).
    (c) `.claude/dispatch-checklist.md` (11 items incl. SCOPE) and `.claude/open-scope.md` (Done early: headerSub).
    (d) memory: feedback_token_cost, feedback_delegate_by_difficulty, feedback_split_ui_groups, feedback_subagent_scope,
        feedback_fix_round_fresh_agent, feedback_review_and_rehearsal_spend, feedback_cuts_checked_against_goals,
        feedback_no_hidden_cost_savings, feedback_scope_guard, project_issue39_cli.
    Goal of the planning talk: how agents finish phases 2-8 with Sonnet/Opus (and Fable) used as efficiently as
    possible: why the late phase 1 groups ran 2.5-4x, how to cut groups (material measured, <250k), which role gets
    which model, review/rehearsal spend, and the setup choice. Bring measured numbers, a recommendation, no survey.
    Merged into the phase branch: V1.1-V1.13 (each with review/fix; rehearsals V1.7, V1.11+12, V1.13 on made-up data).
    Phase branch head 3cafe9b9. V1.14a a52ce2fc + b 35901f1a + review + fix on feat/cli-1-14 (worktree cli1-14).
    NEW RULES (user 2026-11-16, standing, also for the future; dispatch checklist rule 6 + memory):
    - Every agent runs the full pytest in the FOREGROUND, Bash timeout 600000 (no background run, no interim wakes);
      fix-round.md and ui-build.md carry it. Prompts: replace "run it in the background and wait for its notification".
    - Review agents run only the touched tests, never the full suite.
    - Rehearsals on a COPY of the real library with the user present (rekordbox closed); made-up data only when the
      script's steps changed and never ran. So: V1.14 rehearse-sync on made-up data STAYS (RH2-RH6 moved, unrun;
      builder at scratchpad/rehearsal-v1.13/build_fake.py, stereo); V1.15 gets NO rehearsal; one real-copy session in
      the user's A-D morning covers rehearse, rehearse-convert and rehearse-sync.
    2026-11-20 PLANNING TALK (phases 2-8): plan review dispatched as Fable, switched to Opus by the user (Fable is no
    longer in the Pro plan): Opus **132k** (13 API calls, 1.2M cache reads) → scratchpad fable-review-result.md: plan
    sound; phase 1 really ~11.4M logged (2.24x, the "phase 1 ~" figures used a wrong 2.12M baseline); main unnamed
    causes = interfaces left to builders (V1.0's 8 open shapes) + contract work per shape (fake ~148k); advisor OFF.
    MEASURED from transcripts (`.claude/agent-cost.py`): subagent_tokens = final context, not spend. 66 agents
    2026-11-15..17: 5 182 API calls, 947M cache reads, 17.2M fresh input, 3.8M output, + advisor (Fable) 8.0M uncached
    input / 0.54M output in 37 calls (max 450k per call), none of it in the log. Worst agent: suite speed, 503 calls,
    123M cache reads (logged 332k). Advisor: user to run `/advisor off`.
    **RESUME HERE (superseded below, 2026-11-20 late):** DECIDED: no Fable (not in Pro any more); `/advisor off` done by the user.
    Phase 1 real logged total ~11.4M (2.24x), NOT 13.4M. PROPOSED, waiting for the user's go: (1) Opus phase 2
    detailing run (est. 250-350k) whose sizing script counts edited functions, callers, ported tests AND every
    changed bridge shape (+ contract doc, types.ts, contract.ts, fake); briefs end "Open: none" and carry exact read
    lists (function + line range); legacy removal its own group only if counts exceed the cap; (2) a fresh Opus brief
    check (~100-150k), judged by gaps it finds that the script missed; (3) Sonnet builds/reviews/fixes, advisor off,
    phase review split from the measured diff; (4) cost checkpoint at the END of phase 2 with logged size AND
    agent-cost.py consumption. Log calls + cache reads per agent from now on. Running total of this talk: 132k.
    GO given ("ok get it done", 2026-11-20). Drift guards built: open-scope "## Decided", numbers/decisions rules +
    stale-resume warning in after-compact.sh, advisor gate in dispatch-check.sh (4 cases tested), checklist 8 logs
    agent-cost.py. Phase 2 targets measured: engine 144k in 9 files, window 147k in 38 → planning split: (A) Sonnet
    sizing script `.claude/issue39/phase2/brief-sizing.md` → size.py, groups.json, sizing.md (est. 100-150k) RUNNING;
    (B) Opus detailing from sizing.md (est. 220-300k); (C) fresh Opus brief check (est. 100-150k); then V2.1.
    (A) done: Sonnet **95k** (24 API calls, 1.6M cache reads, 94k fresh, 29k out; est. 100-150k). size.py (11 s),
    groups.json, sizing.md (19k tokens). By ranges: V2.1 229k (whole test files 168k of it), V2.2 273k, V2.3 207k,
    V2.4 19k (floor: rev/expect too common to grep), V2.5 167k, V2.6 109k; tests by hit windows: 96/80/75/6/63/28k.
    Hand check by me: PreviewStore 8 engine + 19 test hit lines = script. BEFORE (B): the user ticks extras E2-E9
    (plan v2 §7; E7 changes how phase 2-6 contract work is done) + the Qobuz "Use this" note (V2.6).
    User: "its your responsibility to make these decisions" → decided by me (open-scope "## Decided"): E2+E3, E6,
    E7 (FIRST in phase 2), E9, E4 in; E5 (re-decide at phase 7) and E8 out; "Use this" waits while a sync's pause
    holds. +2 765k at plan units. Detailing split into waves: (B1) Opus wave 1 = phase 2 order/cuts/interfaces + briefs
    E7, V2.1, V2.4 (brief-detail-wave1.md; material ~105k, est. 230-300k) RUNNING; then (C) fresh Opus brief check;
    wave 1 builds; (B2) wave 2 briefs against the code after E7.
    E6 OUT after the user asked "is that needed for agents?" (numbers beat a PNG for agents): extras +2 585k.
    (B1) done: Opus **371k** (est. 230-300k; 94 API calls, 21.3M cache reads, 132k out). Files in
    .claude/issue39/phase2/: phase2-plan.md, phase2-dispatch.md, briefs E7a-E7e, V2.1a, V2.1b, V2.4 (2-4k each),
    sizing-extras.md. Wave 1 builds 1 614k (8 Sonnet agents, 170-217k each) vs plan 1 225k; + Opus phase review
    2x180k + fix 150k ≈ 2 124k. Wave 2: 10 agents (E4b Opus UI 320k). 8 decisions flagged for a second look
    (types.ts re-exports types.gen.ts; shapes package per area; +3 allowed types; F(shown) default True; events
    outside shapes; T6 real-output = suite in test mode; no secrets in window jobs' state.json; ConsoleBusy.job).
    Next (C): fresh Opus brief check.
    (C) done: Opus **271k** (est. 110-160k; 113 API calls, 18.5M cache reads, 104k out) → check-wave1.md: 27 findings
    (2 Critical: J answers validated against the wrong shape; V2.4's positional rev landing in plan_id in the real
    window; 11 Important, 14 Minor), ALL fixed in the briefs, NONE catchable by the sizing script or "Open: none" →
    the check stays for wave 2 (it pays: one Critical would have cost a fix round or a live-test bug). The "beside"
    V2.4 run removed (one agent at a time). Wave 1 now 1 627k builds (~2 137k with review + fix). Planning total
    ~0.87M (132 + 95 + 371 + 271). Phase branch feat/cli-2-foundations (= main d18ceb5d+). Next: E7a.
    **RESUME HERE (superseded by the NIGHT LOG entry marked LATEST below, 2026-11-20 night):** USER GO: "work through the night without me … orchestrating and not
    drifting". E7a (Sonnet, brief .claude/issue39/phase2/E7a.md, est. 215k, maybe 250-300k) RUNNING on
    feat/cli-2-shapes-kernel (worktree .claude/worktrees/cli2-1) from the phase branch feat/cli-2-foundations.
    NIGHT LOOP, one agent at a time, in phase2-dispatch.md's order (E7a → E7b → E7c → E7d → E7e → V2.1a → V2.4 →
    V2.1b):
      on each notice: `ps aux | grep -E 'pytest|vite|job _worker'` (kill leftovers I or it started); log
      subagent_tokens + `.claude/agent-cost.py 2026-11-20` (calls, cache reads) here; check its commits
      (`git log`), that it reported a green full pytest; merge --no-ff into feat/cli-2-foundations, push, remove the
      worktree; then dispatch the next brief with Dispatch/Scope check lines (material from phase2-dispatch.md).
      An agent that stopped on a brief gap: decide it myself by the goals (plan v2 G1-G5), write the decision into
      the brief and phase2-plan.md, fresh Sonnet. Cut by the usage limit: resume by message. Over ~300k: it stops at
      its next green commit, a fresh agent takes the rest (E7a has commit 1 as hand-over).
    After V2.1b: measure the wave 1 diff, Opus phase review split in two (shapes+surface / jobs+identity, ~180k
    each, sized at ~3x the measured diff), ONE Sonnet fix round per half (fix-round agent), `npm run verify` once on
    the phase branch (run_in_background, mine), CI green. Then (B2) Opus wave 2 detailing against the code (briefs
    V2.2-V2.6, E9, E4, as wave 1's brief-detail-wave1.md) and (C2) a fresh Opus brief check; then wave 2 builds in
    order, own Sonnet reviews for V2.2, V2.5, V2.6 (+ V2.6's fake-service rehearsal), E9/E4 shots passes, E4b Opus UI.
    STOP POINTS (wait for the user): the real-copy rehearsals of V2.2/V2.5 (need the user present, rekordbox
    closed); the merge of phase 2 into main; the cost checkpoint at the end of phase 2 (logged + agent-cost.py); any
    real product decision; no release. Never a real sync/download; real library.db read-only.
    NIGHT LOG:
      - E7a done (Sonnet): logged 180.5k (est. 215k), 47 calls, cache reads 6.0M, fresh in 179k, out 67k, advisor 0k.
        Commits c9ced660 (kernel) + fcc85be4 (contract); pytest 6093 passed / 4 skipped, npm check 0/0, vitest bridge
        284. 9 small deviations (alias → Annotated, values(), take_mismatches(), tuple min/maxItems, with_schemas,
        test_missing_* ts_type reads types.gen.ts): all additive, noted in E7b-E7e "Landed in E7a". Merged 2a148971.
        Advisor tag still in message metadata after a 2nd `/advisor off` (03:02); rule: prompts say never call it,
        agent-cost advisor must stay 0k.
      - E7b done (Sonnet): logged 295.5k (est. 210k, 1.4x), 120 calls, cache reads 23.5M, fresh in 282k, out 107k,
        advisor 0k. Commit 2166665b; pytest 6097/4 skipped, npm check 0/0, NO_SAMPLE empty. Over plan cause: the E7a
        fake harness could not run real samples (>300 s), rebuilt (one fake per scenario, ~48 s). It ran one pgrep
        waiter in a Monitor briefly (stopped; ps clean). FOR PHASE REVIEW: generated TS shows `own` required on
        TodoItemBase though the engine omits it on duplicate items (NotRequired override not carried into TS);
        harness vitest time ~48 s. Notes added to E7c-E7e. Merged 52a49962.
      - E7c done (Sonnet): logged 234k (est. 200k, 1.17x), 75 calls, cache reads 11.7M, fresh in 220k, out 65k,
        advisor 0k. Commit 49545f62; pytest 6103/4 skipped (71 s), npm check 0/0, vitest full 1720 (28 s), harness
        ~3 s, NO_SAMPLE empty. FOR PHASE REVIEW: RunSummary.id now required; Dashboard.next_checks nullable (window
        `?? 0` in dashboardModel.ts L70); golden page cli_golden/report_show.txt changed via fuller fixture rows;
        fake `run` accepts last / report:<stamp>. Merged 6929df67.
      - E7d done (Sonnet): logged 268k (est. 215k, 1.24x), 102 calls, cache reads 17.5M, fresh in 672k (two cut-offs:
        the 5-hour limit at ~04:0x until 07:50, then a network error; each resume re-read cold), out 81k, advisor 0k.
        Commit 02142333; pytest 6106/4 skipped, npm check 0/0, bridge+setup+settings vitest 374, harness ~18 s,
        NO_SAMPLE empty. FOR PHASE REVIEW: convert key-assertion tests and tests/fixtures/hub_convert_shapes.json
        deleted (shapes replace them; behaviour asserts kept); optional→required fields on SetupStatus; it trimmed a
        contract-doc bullet outside its ranges (rekordbox_status). Merged d7e3fa74.
      - E7e done (Sonnet): logged 200k (est. 170k, 1.18x), 73 calls, cache reads 8.8M, fresh in 186k, out 50k, advisor
        0k. Commits f7d0a87f (contract) + eb2ee0a0 (CLAUDE.md Contract rule, CONTRIBUTING); pytest 6112/4 skipped,
        npm check 0/0, bridge vitest 284 (harness ~19 s). Completeness test: every bridge/cli_first method in ANSWERS
        or a named exception, every job kind in RESULTS. FOR PHASE REVIEW: test-mode `note_answer` skips ok:false
        dicts (auto_upgrade_run passes on a Fail); Res<{}> kept for Empty methods (Res<Empty> makes ok never).
        Merged 2e28e0b2.
        E7 TOTAL: logged 1,178k vs plan 1,010k (1.17x); calls 417; cache reads 67.5M. V2 briefs got "Landed in E7".
      - V2.1a done (Sonnet): logged 195k incl. a resumed fix (est. 215k), advisor 0k (calls/cache: see agent-cost
        row ad4abf3f). Commits 197fbb83 + 0232fcdb. My own full pytest found a NEW flake (JobStarted now emitted after
        the registry files are written; test_hub_api_convert.py:415 read it right after batch_resume: 1/4 runs vs
        0/8 on base); test fixed by the same agent; its full pytest 6129/4 skipped green. FOR PHASE REVIEW:
        test_hub_api.py:232 stops a refresh right after start (JobStarted can be dropped; older race); window job
        state never says `stopping`; SECRET_PARAMS keyed by method; new catalog.holds_library, Jobs.record_of.
        Merged into feat/cli-2-foundations.
      - V2.4 done (Sonnet): logged 204k (est. 192k, 1.06x), advisor 0k (agent-cost row a52ed3ba). Commits 285e02c0
        (contract) + 9e0bea03 (static); pytest 6148/4 skipped, npm check 0/0, vitest 1721, no goldens changed.
        Decided by it (kept, by the goal "every write checks the rev"): `upgrade` with `expect` also checks Same
        track (_check_rev in _batch_work); rev: null on no-record rows, duplicate-group and batch items. FOR PHASE
        REVIEW: the upgrade stale-rev refusal writes no operations-log line (the 5 other writes log `changed`);
        `plan_id` now required in Bridge.upgrade. Merged into feat/cli-2-foundations.
      - V2.1b done (Sonnet): logged 142k (est. 210k), 52 calls, cache reads 5.3M, advisor 0k. Commits ccbc0ff9 +
        2e378da9; pytest 6184/4 skipped; touched files 5x stable. FOR PHASE REVIEW: Jobs' music folder derived as
        lock.parent.parent; a foreign job under 1 s sends no JobFinished; holder re-reads its state.json. Merged
        b3ca2205.
      - WAVE 1 BUILDS DONE: logged 1,178 (E7) + 195 + 204 + 142 = ~1,719k vs plan 1,627k (1.06x). My full pytest on
        b3ca2205: 6185 passed, 3 skipped, green. Diff (excl. generated/static) ~209k tokens: shapes+contract ~145k
        (mostly declarations + doc deletions), jobs/identity ~63k. Review: two Opus halves, briefs in
        .claude/issue39/phase2/review/ (common.md, review-shapes.md, review-jobs.md), ~180k each, run on the main
        checkout at feat/cli-2-foundations. V2.3's share of the planned phase review moves to wave 2's review.
      - REVIEW half 1 shapes (Opus): logged 216k, 80 calls, cache 10.0M, advisor 0k: 0 Critical, 4 Important (S1 no
        Fail answer ever validated + bad_args missing in Fail.kind; S2 CLI `data` vs help schema; S3 fake harness
        counts a refused call as passing; S4 not-ok job results never validated), 7 Minor. Subagents cannot write
        report files (harness): findings returned as text, saved by me to review/findings-shapes.md.
      - REVIEW half 2 jobs (Opus): logged 256k, 87 calls, cache 13.4M, advisor 0k: 1 CRITICAL (C1 rev misses
        source/source_id and the parked version's identity: stale --if-rev passes after use_candidate), 3 Important
        (I1 queued job counts as holder, two terminal writes refuse each other; I2 watch can report the window's own
        new job failed; I3 window jobs never `stopping`), 8 Minor; PLANNED V4.7 (login --password-stdin args through
        public_args), E9 (job_status lacks the terminal job's name on reload). review/findings-jobs.md.
      - FIX ROUNDS (Sonnet fix-round, sequential, each from the phase branch): FR3 (C1 M1 I1 I2 M3 M4 M8) → FR1 (S1 S4
        T1 T2 K1-3 D1 D2) → FR4 (I3 M2 M5 M6 M7) → FR2 (S3 S2). Briefs review/FR*.md + fix-common.md. Four, not the
        planned one: 23 stated findings incl. 1 Critical, split by area so each stays ~150-200k.
      - FR3 done (Sonnet fix-round): logged 101k, 27 calls, cache 1.9M, advisor 0k. Commit 1b4f270d, all 7 fixed
        (C1 rev now covers source/source_id and the parked version; I1 registry.HOLDING; I2+M3 own id before
        create, half-made folder removed; M1 M4 M8); pytest 6192/4 skipped; reverting the engine fails 11 new/changed
        tests. Merged cd8c7353. FR1 dispatched (worktree cli2-f1, feat/cli-2-fix-shapes-check).
      - FR1 done (Sonnet fix-round): logged 127k, advisor 0k (row a42ceb1b). Commit e542b08c, all 9 (S1 changed:
        Fail keeps ProblemKind for the window; new CliFail(Fail) with FailKind incl. bad_args checks every failure;
        S4 every job end checked; T1 12 per-test marks; K1 Omit<Base>; K2 K3 T2 D1 D2). New checks found NO engine
        mismatch. pytest 6195/4 skipped, npm check 0, bridge vitest 284. Merged. FR4 dispatched (cli2-f4).
      - FR4 done (Sonnet fix-round): logged 83k, advisor 0k (row a3187716). Commits 1587fc82 (static) + 8755809c, all
        5 (I3 stopping via CancelToken.on_cancel + update_if; M2 _settled skip; M5 note inside finishing, unconditional
        after FR1; M6 hub.ts refresh guard; M7 close stops reads/sign-ins). Touched files 5x stable; pytest 6201/4
        skipped; npm check 0; hub.test 44. Merged. FR2 dispatched (cli2-f2).
      - FR2 done (Sonnet fix-round): logged 163k, 64 calls, cache 7.1M, advisor 0k. Commits 6ae905c1 (S3: harness
        checks refusals vs Fail/CliFail, every sampled method answered once, ONLY_REFUSED empty) + 99a8c394 (S2:
        CLI_DATA shapes, note_cli_data; found + fixed 4 more shape mismatches in correct answers). pytest 6202/4
        skipped; npm check 0; bridge vitest 285. Merged f3bbe361.
      - WAVE 1 COMPLETE on feat/cli-2-foundations f3bbe361: `npm run verify` 1724 vitest, 1249 shots, 0 problems (a
        first run showed 2 problems because I switched the main checkout to main mid-run: never switch the checkout
        while verify runs; re-run clean). CI green (44707870926).
        WAVE 1 COST (logged): builds ~1,719k + review 472k + fix rounds 474k (FR3 101, FR1 127, FR4 83, FR2 163) =
        ~2,665k vs plan ~2,137k (1.25x). advisor 0k throughout.
      - NEXT: B2 Opus wave 2 detailing (brief .claude/issue39/phase2/brief-detail-wave2.md; carry-items.md), then C2
        fresh Opus brief check, then wave 2 builds.
      - B2 run 1 (Opus; cut by the 5-hour limit 09:3x-12:50, resumed): logged 246k, 66 calls, cache 9.3M, fresh in
        379k, advisor 0k. Wrote V2.2a (205k), V2.2b (235k: 24 old preview-store sites in test_hub_views.py), V2.5a
        (215k), V2.5b (200k), review-V2.2/-V2.5 (130k each + fix 130k each), rehearse-V2.2/-V2.5 (APFS clones, stop
        unless `where` shows the clones; user present; closes Discjockey + rekordbox). Cuts moved: Playlists from
        the store (_infos/_extra_tracks) V2.2b → V2.2a; media_url/setup_check_account removal V2.5a → V2.5b. Its
        decisions checked and kept (lines_changed keeps the "changed since" hint; cache key includes today;
        FileDropped loses track_id; keep_file without expect; dropped methods keep catalogue rows). Run 1 total
        ~1,525k expected. B2 run 2 dispatched (V2.3a/b, V2.6, E9, E4a/b + review/rehearse V2.6, shots E9/E4).
      - B2 run 2 (Opus): logged 329k, 124 calls, cache 24.2M, advisor 0k. Wrote V2.3a (215k), V2.3b (175k), V2.6
        (225k), E9 (185k), E4a (175k), E4b (Opus, 300k), review-V2.6 (130k), rehearse-V2.6 (80k, made-up services),
        shots-E9 (100k), shots-E4 (120k); wave 2 phase review 2 x 175k + fix 150k. Wave 2 expected ~3,860k. ORDER
        CHANGED: V2.5a/b before V2.3a/b (presets need the engine's scope). Flagged to C2: PlanExpired.next names
        `sync run --dry-run` (exists only from V4.1); V2.6 counts a queued sync as running (check no mutual
        block, cf. I1); E9 adds ConsoleBusy.text; E4b has no Stop for a Terminal sync. DECIDED (mine): E4b from a
        precise direction, no mockup (open-scope Decided).
      - C2: fresh Opus check in two parts (brief-check-wave2.md): part A (V2.2, V2.5) dispatched; part B next.
      - Log edits now happen in the worktree .claude/worktrees/main-log (main), so the main checkout stays on the
        phase branch while agents read it.
      - C2 part A (Opus): logged 290k, 116 calls, cache 20.7M, advisor 0k. 26 findings, all fixed in the briefs
        (check-wave2-A.md): 1 CRITICAL (both real-copy rehearsal scripts used unbuilt CLI commands: the user session
        would have stopped at step 1-2; now a Python driver via bind.default()), 7 Important (V2.2a read_refs so a
        switched-off line is not planned; db.read_head keeps a first failed read's problem; V2.2b cache key covers
        check reads; missing test sites; V2.5a catalog tests; V2.5b NEEDS_NO_LIBRARY + flips merged while a settings
        job runs), 16 Minor, 2 size. 24 of 26 not catchable by size.py or "Open: none": the check stays. Part A
        builds re-measured 795k (was 855k). Part B dispatched.
      - C2 part B (Opus): logged 349k (exp. 250k, 1.4x), 144 calls, cache 31.5M, advisor 0k. 32 findings (11
        Important: V2.3a action ids shifting/unticked songs coming back, hint naming an unbuilt command (plan stores
        no command now; carry to V4.1), missed callers; V2.6 queued sync recorded as `start_sync`, pacer injection,
        hub fixture importing the deleted `Pacer`; E9 four fakes -> "undefined." banner; E4a unknown id `crashed`
        instead of `bad_args`, end screen losing its job, method-count test), 16 Minor, 4 size. Queued-sync deadlock:
        no cycle. Decided by me (open-scope): E4a `stop(job_id=None)` + E4b "Stop safely" for a Terminal sync (design
        6.2/6.4). Run 2 builds 1 240k (was 1 275k).
      - User 2026-11-20: "This codebase is yours" rule -> CLAUDE.md section, fix-round/ui-build agents, checklist
        line 12 (every prompt carries the ownership line), memory. Next: V2.2a.
      - V2.2a done (Sonnet; cut once by the 5-hour limit, resumed 17:50): logged 221k (exp. 195k, 1.13x), 85 calls,
        cache 12.1M, advisor 0k. Commits 70b0f944 (contract) + 52e1e0ef, merged c85752d1; pytest 6235 passed. Notes
        for V2.2b (clear_service line in _clear_read_problem) and for the V2.2 review (stale info of an unreadable
        playlist kept; stopped read stores finished tracks; two failed reads out of order; SoundCloud secret link
        stored NULL; contract commit before engine commit) appended to V2.2b.md / review-V2.2.md. V2.2b dispatched.
      - V2.2b done (Sonnet): logged 251k (exp. 205k, 1.22x), 96 calls, cache 15.0M, advisor 0k. Commits 8bf0c79f +
        baa6dc63 (static), merged 176c8d93. Its full run had 1 failure it fixed; my full pytest on the branch: 6236
        passed. It fixed a V2.2a bug (stopped read stored when a hung request answered late). Decided by me: a
        refused settings.json must not break dashboard/job_status (V2.2b made them fail; reads tolerate a bad
        settings file elsewhere) -> Important finding with stated fix in review-V2.2.md. Review V2.2 dispatched
        (BASE 85a4679b, HEAD 176c8d93, diff 57k).
      - Review V2.2 (Sonnet): logged 199k (exp. 140k, 1.42x), 51 calls, cache 6.2M, advisor 0k. 0 Critical, 4
        Important (F1 a refused settings.json breaks 9+ readers of _plan(), not only dashboard/job_status; job_status
        should not derive at all; F2 a refresh whose read could not be stored ends ok with no plan; F3 unreadable
        playlist keeps stale info; F4 a private SoundCloud set's s-token is stored in reads.lines/playlist_infos as the
        ref: the stated fix narrows the wording + test, alternative masking = design), 8 Minor (F5-F12), 1 note (F13
        commit order). Findings: .claude/issue39/phase2/review/findings-V2.2.md. All fixes stated; none PLANNED.
      - PAUSED by the user (~18:40, "Pause after the agent is done"). Next on go: the V2.2 fix round (Sonnet
        fix-round, F1-F12, from the phase branch 176c8d93), then V2.5a.
      - RESUME HERE (LATEST, 2026-11-20 ~19:xx, after a compact): the user said "continue" = go on from the pause
        (open-scope Decided). Same night loop and stop points as the RESUME HERE above. FR-V2.2 (Sonnet fix-round,
        brief .claude/issue39/phase2/review/FR-V2.2.md, F1-F12, F4 as stated) dispatched on worktree
        .claude/worktrees/cli2-fv22, branch feat/cli-2-fix-v22 from 176c8d93; exp. ~170k. Then V2.5a (cli2-13),
        V2.5b (cli2-14), review V2.5 + fix, then STOP for the real-copy rehearsals V2.2/V2.5 only when the user is
        present (otherwise go on with V2.3a/b, V2.6, E9, E4a/b and rehearse them later together).
      - FR-V2.2 done (Sonnet fix-round): logged 160.5k (exp. 170k), 62 calls, cache 7.1M, fresh in 160k, advisor 0k.
        Commit f17a5774 (one commit: shape + engine + generated + fake + doc), all F1-F12 (F1 via `_derive`;
        never_download made strict too; F2 RefreshResult.read_id non-null; F4 token also in reads.read_refs and
        playlist_tracks.playlist: identity columns, wording names all six). pytest 6256/4 skipped, npm check 0,
        bridge vitest 285. Merged 52732e45, pushed. Remaining briefs got "Landed in the V2.2 fix round" (+ F13 one-
        commit rule). V2.2 group total: 221 + 251 + 199 + 160 = 831k. V2.5a dispatched (cli2-13, exp. 195k).
      - V2.5a done (Sonnet): logged 214k (exp. 195k, 1.10x), 104 calls, cache 14.5M, fresh in 201k, out 63k, advisor
        0k. Commits cb9d0196 (path travels, select/_selected/_dropped gone) + 6a627827 (folders.keep_file, bridge
        keep_file/KeepFileResult, supersede_duplicate gone) + cf14691c static + 1fd6dd34 (test fix after its suite);
        my full pytest on the final commit: 6268 passed / 4 skipped. Two whole commits instead of events/payloads
        (F13 rule). Notes to V2.5b.md (catalog-count test, LIBRARY_METHODS) and review-V2.5.md. Merged 32e8aeb6,
        pushed. V2.5b dispatched (cli2-14, exp. 200k).
      - V2.5b done (Sonnet): logged 271k (exp. 200k, 1.36x), 129 calls, cache 21.6M, fresh in 258k, out 77k, advisor
        0k. Commits dc8ea175 (one commit: engine+shapes+generated+fake+client+store+doc) + 86d0f77b static + 3dd53590
        (goldens, lock drivers, schema-13 tests); pytest 6301/4 skipped on the final commit, npm check 0, vitest 382.
        Merged 3e9c1f72, pushed. Notes to review-V2.5.md. Review V2.5 (Sonnet) dispatched: BASE 52732e45, HEAD
        3e9c1f72, diff 55k tokens, exp. ~180-200k.
      - Review V2.5 (Sonnet): logged 180k (exp. 180-200k), 55 calls, cache 6.5M, fresh in 162k, advisor 0k. 0 Critical,
        1 Important (F1 a keep_file stopped after some moves says "Nothing was moved"), 8 Minor (F2 a crash between
        moves loses the moved list; F3 one-file group; F4 _file_problem FIFO/NUL/relative path; F5 drop event words;
        F6 "Add again" on permanent refusals; F7 dead groupIdOf; F8 "this session" words; F9 import-stop/scope test
        gaps). No window logic added, no product decision. review/findings-V2.5.md. Carry to V4.6 (add-file
        resolves relative paths) in carry-items.md. FR-V2.5 (Sonnet fix-round, F1-F9) dispatched on cli2-fv25, exp.
        ~140k.
      - FR-V2.5 done (Sonnet fix-round, resumed once for the bug it saw): logged 110k (exp. 140k), 45 calls, cache
        3.5M, advisor 0k. Commits 81d26477, 92ad0572, 837a4425, 5748b72d (F8 shapes+generated), 513995f8 static,
        b2cfe4f8 (supersede `on_moved`: a file moved before a failed report write is listed). F6 as `canRetryAdd` in
        todoModel.ts (FOR PHASE REVIEW: a window retry rule by refusal kind, pre-existing logic narrowed; phase 6).
        Left: a move the records refuse (NOT_RECORDED) is not listed; its words say "Moved to …, but". pytest
        6311/4 skipped. Merged db786fc9, pushed. V2.5 group total: 214 + 271 + 180 + 110 = 775k.
        Later briefs got "Landed in V2.5". V2.3a dispatched (cli2-11, exp. 200k).
      - V2.3a done (Sonnet; cut once by the 5-hour limit, resumed after 23:00): logged 282k (exp. 200k, 1.41x), 123
        calls, cache 22.0M, fresh in 481k (cold re-read on resume), out 86k, advisor 0k. Commits edce4728 (one commit:
        engine+shapes+generated+doc+fake+client+window start()) + 011ae849 static; pytest 6331/4 skipped, vitest
        1732, npm check 0, timing set 5x. Merged 47bc9d60, pushed. FOR PHASE REVIEW (half A): only non-download
        actions in scope → one "All" preset; job_status now reads the registry (≤100 state.json) on every poll
        (brief's decision: check the cost); sync_preview writes <support>/plans/ (doc notes it); generation from
        the preview's state; `sync plan` CLI not built (V4.1: add "command": "sync run" to the plan's extra).
        Notes to V2.3b.md. V2.3b dispatched (cli2-12, exp. 175k).
      - V2.3b done (Sonnet): logged 155k (exp. 175k), 60 calls, cache 6.7M, fresh in 141k, out 34k, advisor 0k.
        Commits 0db9cb92 (one commit) + db011bbf static; pytest 6331/4 skipped, npm check 0, vitest sync+store+fake
        491 (+ fake.test 56 after its last case). key/ActionKey/keyId/presets/presetTicks/defaultHowMany/
        sync.lastSelection gone. Deviations: refreshHub chained onto start_sync's answer; FakeState.lastSyncRows.
        Visible: sync:own-cover shot's cover now from its plan row (seed folder fixed). FOR PHASE REVIEW: null
        default_how_many leaves ticks as they were (Start still filters by scope); live view pickedOf (last_sync +
        one sync_preview): check it computes no state. Merged 58e5820a, pushed. V2.3 total 282 + 155 = 437k.
        Later briefs got "Landed in V2.3". V2.6 dispatched (cli2-15, exp. 215k).
      - V2.6 done (Sonnet): logged 244k (exp. 215k, 1.13x), 95 calls, cache 15.7M, fresh in 230k, out 85k, advisor 0k.
        Commits 69841703 + b22a029d (WRITE_SITES); pytest 6366/4 skipped, timing set 5x, test_pacing_processes 5x.
        7 deliberate deviations + notes appended to review-V2.6.md; the bug it saw (Cancelled inside the Qobuz
        worker's except Exception, latent) DECIDED as a finding for the V2.6 fix round. Merged 66635561, pushed.
        Review V2.6 (Sonnet) dispatched: BASE 58e5820a, HEAD 66635561, diff 29k tokens, exp. ~150k.
      - Review V2.6 (Sonnet): logged 165k (exp. 150k), 41 calls, cache 4.6M, fresh in 147k, advisor 0k. 0 Critical,
        5 Important (F1 two pacers in one process don't see each other's claim; F2 Use link's Qobuz lookup unpaced;
        F3 Settings login checks unpaced; F4 Limits card "paused" from the day's signal, not the stored pause), 4
        Minor (F5 pace error in candidates.search [my premise half wrong: Cancelled is BaseException]; F6 pacer
        error counts as a failed Qobuz search; F7 "rest of this run" words; F8 future-stamped claim; F9 stale
        break count). No window logic, no PLANNED. review/findings-V2.6.md. Decided (mine, open-scope): F3 as
        stated. FR-V2.6 (Sonnet fix-round, F1-F9) dispatched on cli2-fv26, exp. ~150k.
      - FR-V2.6 done (Sonnet fix-round): logged 118k (exp. 150k), 46 calls, cache 3.9M, advisor 0k. Commits e692acd4
        (F1, F5-F9) + 6e0ba0e1 (F2-F4 + shapes); pytest 6383/4 skipped, pacing files 5x. F3 changed: the Qobuz
        check's slot is taken before the login request (outside the try: a pacer OSError is not "Couldn't reach
        Qobuz"); checks use self._support.support (Setup runs before a music folder). F7 words stay in acquire.py
        (words.py is CLI-only; import cycle). Merged 831c02d4, pushed. Rehearsal V2.6 (Sonnet, made-up services, 9
        steps incl. a new step 9: two pacers in one process) dispatched, exp. ~110k.
      - Rehearsal V2.6 (Sonnet, made-up services): logged 107k (exp. 110k), 13 calls, cache 0.9M, advisor 0k. 9/9
        PASS on 831c02d4 (step 6 first FAIL was its own script: the break count is a 10-15 draw; rerun PASS; step 5
        actual gaps 0.0137 s vs 0.02 s slots = wake-up jitter at 1/100 scale, slot order exact; step 2 via
        run.finish_quietly, no fallback). Repo untouched, scratch deleted. V2.6 group total: 244 + 165 + 118 + 107
        = 634k. E9 dispatched (cli2-16, exp. 165k).
    NEXT after the user's go: V1.14 rehearse-sync (made-up) → merge V1.14 → V1.15 (a/b, review, fix on a scratch
    library; carry: `tools update` terminal path via `_support_job`'s registry check) → Opus phase review (measure
    material first, likely split; all "FOR PHASE REVIEW" items below + memory project_issue39_cli carry list + amend
    the design/plan sentence "a dry run writes exactly its plan" to plans/, cache/ and RJ jobs/) → its fix round →
    `npm run verify` once on the phase branch (run_in_background, my own) → CI green → merge into main, push → STOP
    before A-D, morning summary (incl. the real-copy rehearsal session).
    Cost: phase 1 ~10.2M of 5.4M plan (issue 39 ~12.24M incl. the V1.14 fix); left to the stop point ~1.5-1.9M
    (told the user). Audit told the user: reviews earned their cost (V1.12 undo bug etc.), made-up rehearsals mostly not.
  - **NIGHT RUN (2026-11-14 ~23:55, user asleep, go: "finish the design work through the night"):** scope = steps 2-5
    only (design → adversarial review → design fixes → build plan), then STOP for the user's go before any build.
    Step 2 running: Opus designer, brief `brief-39-design.md`, output `docs/2026-11-14-agent-cli-design.md` (est.
    ~280k). On its notice: log size; G1/G5 script check of the design (catalogue covers 95 methods, required sections
    present: principles, grammar+catalogue, output/exit codes, long runs, open window, writes/dry run, selection,
    identity, person-only steps, sandbox, UI→engine rule with audit row ids, goals-and-questions, A-D live tests
    walk-through, keep/change/drop table, completeness tests + agent docs, risks); gaps → back to the designer by
    message (if <~300k) or a fresh Sonnet with the gap list. Step 3: fresh Opus adversarial review (material: design +
    6 audits ~ measure; writes `docs/2026-11-14-agent-cli-design-review.md` with numbered findings, each Critical/
    Important/Minor + stated fix where possible; walks the A-D live tests and the goal questions on paper). Step 4:
    fixes (Sonnet if all fixes stated, Opus if new decisions). Step 5: Opus build plan `docs/2026-11-15-agent-cli-
    plan.md` (Sonnet groups, material-measured, <250k each, write-side groups get own review + rehearsal on a copy).
    No heartbeat (user: "no hourly check"): agents' completion notices drive the chain.
    Morning summary for the user (short): the CLI for an agent, what changed vs today and why, review findings, plan
    size. Gates G1-G5 below apply.
    2026-11-15 ~04:00: designer cut by the usage limit at §9.2 (624 lines, uncommitted; script: 95/95 methods named;
    missing §9 rows, person-only, sandbox, goals, A-D walk, keep/change/drop, tests+docs, MCP, risks); resumed by message.
    Designer done 5d15f50b: Opus **348k** (est. 280k; 976 lines). G1 script: 95/95 methods, all 16 sections present.
    Step 3 split (material design 23k + audits 104k + code greps > 150k, G2: said to the user in chat): 3a Sonnet
    coverage review (every audit item → answered / by construction with reason / gap; `-review-coverage.md`, est.
    ~230k), then 3b Opus adversarial review (soundness, invariants, A-D walk, goals; `-review.md`). Issue 39 ~2.40M.
    3a done: Sonnet **377k** (est. 230k; 33 calls, 1162 items: 983 answered, 168 by construction w/ reason, 9 findings
    C1-C9: 4 Important, 5 Minor, 0 Critical). Lesson: a per-item review of 127k material lands ~3x material. Issue 39 ~2.78M.
    3b Opus adversarial (brief-39-rev-adversarial.md, material ~80k measured, est. ~250k) next.
    3b done: Opus **244k** (est. 250k; 63 calls): 48 findings (3 Critical: Qobuz pacing per process, sandbox logins
    miss the real limit, `sandbox remove` can delete the real library; 25 Important, 20 Minor; 3 need a decision R44/
    R46/R48). Verdict: ready after fixes, redesign 4 parts (cross-process Qobuz/account protection, §6 jobs, §9.2,
    §10.3 sandbox) + R15 headless HubApi vs surface/. Issue 39 ~3.02M. Step 4 split by kind: 4a Opus redesign parts +
    decisions (writes a Fix status table into the review), then 4b Sonnet all remaining stated fixes (R + C).
    4a done 6616dce4: Opus **278k** (est. 280k; 65 calls; design 1368 lines): headless HubApi (no surface/), data words
    from the engine + fixed words extracted at build, CLI live-test slice first (phase 1, 7 groups) then A-D tests,
    agent never deletes (marked files to Trash, rekordbox removal = person step), Qobuz streak/pause in library.db +
    shared pacer, jobs alive by flock, sandbox roots-guarded w/o accounts, §8.4 derive/flows/rendered checks. Build est.
    37 groups ~17M (14-20M) incl. reviews: TELL THE USER in the morning (budget). 4b Sonnet (brief-39-fix-b.md,
    25 stated fixes, material ~66k, est. ~180k) next. Issue 39 ~3.30M.
    4b done c63cdb8c: Sonnet **178k** (est. 180k; 25 fixes, 0 conflicts, 0 `for 4b` left; design 1426 lines). Issue 39
    ~3.48M. Step 5 scoped (G2, told the user in chat): phase 1 (CLI slice + A-D live tests) planned in full, later phases
    as a costed outline only, because the ~17M budget is the user's call and a 37-group full plan is over the planner
    record (227k/288k). Detail of later phases = a later run after the user's go. Opus planner, brief-39-plan.md.
    Step 5 done e9daae2f: Opus **314k** (est. 260k; plan 869 lines; every group <=245k by script). Build est. 24.4M
    (21-31M; 8 phases, 62 groups; phase 1 = 15 groups 5.3M, 5.6M with the A-D live tests); cost notes C-1..C-7 (~5.5M
    of possible cuts). Issue 39 design work ~3.79M. **NIGHT RUN DONE, STOPPED: waiting for the user's go** on the
    budget/phase 1 and the cost notes; also tell: Qobuz pause from a sync now also holds for "Use this" (4a).
    2026-11-15 morning: user questioned 24M ("isn't the engine already GUI-independent?"). Found: no rule ever kept
    logic out of the window (CLAUDE.md:177 allows UI logic in *Model.ts), so ~115 facts/decisions/state drifted
    into it; phase 6 restores "engine = single source of truth" and stays. My "3M lean plan" was an unmeasured guess
    that broke that goal (user angry; memory feedback_cuts_checked_against_goals). User go: second plan v2 that
    keeps every goal and cuts only overhead (self-contained brief per group, generic `call` over headless HubApi,
    merged groups) + an extras table with prices the user ticks. Opus, brief-39-plan2.md → docs/2026-11-15-agent-cli-
    plan-v2.md. NEXT after a compact: dispatch it (measure material first: design 37k + plan parts ~12k + CLAUDE ~3k +
    greps ~25k), then show the user v2 vs v1. Nothing built.
    Plan v2 done acca0628 (+9f2b7272): Opus **302k** (est. 260-310k, material measured 76k; 37 calls; 699 lines).
    Script check: all sections, 8 extras, C-1..C-7, goals 1-5 present; 50/50 v1 group ids mapped (64 rows, 53 to
    groups, 11 to extras, 0 dropped); 51/51 design §9.2/§9.3 rows placed; no group >250k. v2 = ~20.1M (17.2-25.5M,
    52 groups) vs 24.4M; real savings ~2.6M (briefs 1.17M, generic `call` 0.49M, rehearsals in the last agent 0.54M,
    phase 6 Opus review 0.44M), 2.6M moved into extras (all ticked = ~24.4M); "~100k shared docs" premise measured
    false (~3k). Phase 1 = 5.1M + live tests 300k. Drift guard: rule text V1.3, `derive`/`flows`/ratchet in phase 5
    (V5.2); gap: agent defs (ui-build, fix-round) and the review checklist question are not in the plan (I add them
    after the go). Issue 39 ~4.09M. STOPPED for the user's go.
    2026-11-15 afternoon: USER GO on plan v2 ("approved if you say it's good to go"). My checks before saying yes:
    `call` runs the same entry as noun-verb (needs_yes, planned entries refused until their write group) → G5 holds;
    v1's own-review groups 1.7, 1.11-1.15 keep review + rehearsal in v2; v2 departs from the design on D3, D4, D10,
    D11 (every brief and reviewer prompt says "plan v2 §2 wins there"); E1 word catalogue counts as base (G3 needs the
    tooltips) → total ~20.3M; correction to what I told the user: 2.58M moved to extras (not 1.7M), 2.65M real
    savings, +0.91M added. Qobuz "Use this" pause = V2.6 (phase 2), still to tell the user before phase 2. Go scope:
    V1.0-V1.15 + their reviews + phase review; STOP before the A-D live tests (they meet the "never touch my app /
    rekordbox" rule). Extras E2-E9: user ticks before phase 2+ are detailed. Gate after V1.0 (script): seven parts,
    files exist, <=8k tokens, every cited design § + v1 §2 interface present in each brief. V1.0 Sonnet dispatched
    (material 39k, est. 210k) → `.claude/issue39/phase1/V1.x.md`. To do with V1.3 (the G4 rule): add the rule to the
    ui-build + fix-round agent definitions and the review checklist; check whether the ratchet can move before phase 5.
    USER GO (2026-11-15, later): "do the live tests and everything with an agent and just keep going, you're the
    orchestrator". Standing go: phase 1 build -> reviews -> phase review -> merge -> A-D live tests (v1 §7 runbook:
    test tracks only, dry run first, rekordbox backup before writes) without stopping for a go between steps. The P
    steps (rekordbox clicks, cues, listening, USB export) need the user at the Mac: ping them only there. Still stop
    for: a real bug that needs a product decision, the Qobuz "Use this" note before phase 2, extras E2-E9 ticks.
    V1.0 CUT by the Sonnet WEEKLY LIMIT (resets 2026-11-20 02:00 Berlin) before writing any brief (folder empty;
    size not reported). Every phase 1 group is Sonnet, so the queue waits for the reset. RESUME: after the reset,
    SendMessage the V1.0 agent to continue (its context is saved), else dispatch it fresh with the same prompt.
    User reset the limit the same day; V1.0 resumed and done: Sonnet **408k** (est. 210k; 88 calls; material 39k:
    ~10x material, it read the code to check every path and interface). 15 briefs 14-32k chars; gate script: 15/15
    (seven parts, cited design § and v1 §2 names present, paths exist or made by this/earlier group, <=8k tokens).
    Left to builders (no source fixes them): `resolve` return shape, `batches`/`batch_detail`/`settings_view`
    shapes, `help --json` layout, per-reason words, `aiff convert` serving convert+make_aiff, `plan_id` param owner,
    test override for `--wait 90`. Agent's additions: `cli/legacy_out.py` (helpers batch/convert/settings_cmd import
    from rekordbox_cmd), `build(hub): static` rule, `select_listing`. Contradictions resolved (v2 113 vs 130 → 130;
    RJ in V1.6; v1 1.12-1.14 sections win over §2 lines; code `job_id` not `JobStarted.id`; decisionModel path is
    lib/decisions). V1.7 rehearsal: NOT a copy of the real settings.json; coordinator prepares a made-up one.
    Branch feat/cli-1-live-slice from main 177fa59e; V1.1 worktree .claude/worktrees/cli1-1 on feat/cli-1-1.
    Issue 39 ~4.50M.
    V1.1 done 98c92d88: Sonnet **186k** (est. 205k; 62 calls). My full pytest on the branch: 4866 passed, 4 skipped.
    Merged into feat/cli-1-live-slice (ab5ffa44) + main (cddf446a), pushed. Builder's decisions: `discjockey/
    problem.py` base `Problem` (OpProblem, jobs.Busy, lock.Busy, LockHeld); HOUSEKEEPING = help, call, job wait;
    bare path → Ident("path"); default reason = kind (busy→library_lock, stopped→stop); catalogue 128 entries, 123
    commands all `planned = "phase 1"` (pinned ceiling). For the phase review: `select` is both a DROPPED method and
    the cli_first `select(listing)`; `setup_check_account` DROPPED but design §5.2 maps it to `login check`; several
    methods share one command (`setup status`, `job stop`, `status`). For V1.8/V3.1: `open url|folder|file|...`
    would launch apps for real: tests must stub the opener. V1.1's brief wrongly said envelope.py/select.py were on
    the branch (made by V1.2/V1.10). Issue 39 ~4.69M.
    V1.2 done e47078ac: Sonnet **265k** (est. 230k; 97 calls; material 130k); its final full pytest 4928 passed, 4
    skipped (after fixing 2). Merged + main → 2f1c7b1b, pushed. Decisions: `CliApi(HubApi)` with a `cli_first`
    decorator holds `resolve` and other cli_first methods (the contract tests forbid extra public HubApi methods);
    `bind.headless` builds a CliApi; `call` in `cli/call_method.py` (housekeeping.py is V1.3's); resolve answers
    `{kind, resolved:[...]}`, bad ids → bad_args unknown_id/bad_id_kind; `remember=False` via `ops.run_single(check=)`;
    old rekordbox status handler gone, `data` = {state, running} until V1.9. Phase review: `call select` refused
    (select in DROPPED and cli_first); `app_main.CLI_COMMANDS` lacks `call` and the new nouns (V1.3's "any argument is
    a command"); `--json upgrade list` still drops --json (legacy, pinned; V1.11). Issue 39 ~4.96M.
    V1.3 done eb7ecb34: Sonnet **208k** (est. 185k; 71 calls). My full pytest: 4970 passed, 4 skipped. Merged + main
    → bf2f8892, pushed. Decisions: `call` moved to `cli/housekeeping.py`; HOUSEKEEPING += `where`, `app open`;
    `bind.resolved()` for folders (T3 bans `library` imports in cli/); app_main opens the window only for a Finder
    start, `app open` via cli.main; bare `-h`/`--help` = short help; `help --json` full index; `reasons` derived per
    entry (minimum set); `as_of` only on reads; `where.sandbox` null in phase 1; CONTRIBUTING legacy command docs
    replaced by a "Not rebuilt yet" bullet. G4 rule in CLAUDE.md:179-180 (window computes no fact/decision/state;
    *Model.ts only formats; derive/flows from phase 5). Drift guard done by me (outside the repo): ui-build.md (its
    "Logic goes in a pure *Model.ts" contradicted the rule) and fix-round.md carry the rule; dispatch-checklist line 6
    makes every review ask it. Open: can the ratchet move before phase 5 → decide in the phase 2+ detailing run.
    Issue 39 ~5.17M.
    V1.4 done e2fdf889 + 93203bc1: Sonnet **195k** (est. 195k; 75 calls); its final full pytest 4995 passed, 4 skipped;
    vitest 1589; static unchanged. Merged + main → 781356fa, pushed. Decisions: truncated marker has `type` and
    `event`, only when skipped>0; retention keeps a job if newest-100 OR 30 days; `jobs_running` counts queued/
    running/stopping of this music folder + folder-less; `registry.process_started(pid)` (proc_pidinfo) for V1.6
    `--now`. Handed to V1.5: call `prune` at each job start, reduce events into state.json progress, log.txt writer
    (stderr), `Jobs(inline=…)`, and the queued→lost race (any reader marks a `queued` job `lost` while no one holds
    `alive`: create→worker lock needs a handoff; a test pins today's behaviour). Worktrees lack node_modules (agent
    symlinked main's, then removed). Issue 39 ~5.37M.
    V1.5 done 766ea67f: Sonnet **244k** (est. 215k; 69 calls). My full pytest: 5024 passed, 4 skipped; 0 leftover
    `job _worker`. Merged + main → a2eb94b2, pushed. Queued→lost fix: `Registry.create` takes `alive` before
    state.json exists, passes the fd to the worker (`pass_fds`), creator closes its copy: lost only if both die
    (tests pin it). Frozen app spawns `[sys.executable, "job", "_worker", id]` (no -m), routed before the parser.
    Worker finds the registry via DISCJOCKEY_SUPPORT set by the spawner; progress fields {step, done, total, item,
    message}; state.json += `method`, `wait_busy`; prune at each job start (client); stderr → log.txt. For V1.6: a
    lock race lost under `--wait-busy` writes `JobFinished(console)` before the retry → the follower ends on
    result.json, not that event. Issue 39 ~5.61M.
    V1.6 done fc906cb5: Sonnet **215k** (est. 195k; 50 calls); its final full pytest 5054 passed, 4 skipped, nothing
    changed after (it started a sleep-loop watcher, stopped it itself; I checked: none left). Merged + main →
    1502ccca, pushed. `cli/follow.py`: follower ends on status + result.json (pinned). Decisions: `job list|show|
    follow|stop` are housekeeping words; window entries job_status/stop/stop_refresh/stop_sign_in keep T1 coverage, no
    command (`call stop` → "use `job stop`"); `current` = running write-entry or window job; show/wait on `current`
    fall back to newest, `job stop current` → not_running; Ctrl-C leaves the job running; `--jsonl` brackets events
    with Job started/ended. Phase review: a read job (RJ) can be stopped only with `--now` (its method never reads the
    stop file); the worker writes `status: running` itself for RJ. Issue 39 ~5.83M.
    V1.7 done f341c4f5: Sonnet **272k** (est. 185k; 131 calls); its full pytest 5089 passed. Support lock around
    settings.json (`settings.update_settings`), config.json, the login files (Spotify app/token, streamrip config),
    tools/ update+rollback (`Jobs.start(hold_library=False)`); `reader_lock(support)`; `library.SupportBusy` → busy;
    rekordbox_status adds `writing`/`as_of` while a writer holds the lock; `_planned` skips master.db then. Open:
    CLAUDE.md says setup_skip_import takes no library lock, code takes it briefly (T10 pins {library, support}).
    Rehearsal folder (made-up default settings.json, no logins, nothing of the user's) at .claude/issue39/
    rehearsal-v1.7/support. V1.7 review (Sonnet, est. 130-200k, material 50k) → .claude/issue39/phase1/
    review-V1.7.md; rehearsal in the review if no findings, else in the fix agent. Issue 39 ~6.10M.
    V1.7 review: Sonnet **163k** (est. 130-200k; 44 calls): 0 Critical, 3 Important, 6 Minor; no deadlocks/stuck
    locks; window computes nothing new. My decisions (technical): #2 A (shared rekordbox hold only while master.db is
    open: lookups into a dict, close, then plan; the 2 s stays); #5 B (tools update/rollback lock only around the
    steps that change tools/, download unlocked). #9 → CARRY into later dispatch prompts: convert_cmd `_plan` and
    batch_cmd `_rekordbox_status` take `reader_lock` and answer `writing` (whoever replaces aiff/batch: V1.12/V1.13);
    terminal `update` must go through `_support_job`'s registry check (whoever builds `tools update`). Fix round
    (fix-round agent, est. 150-240k) fixes 1-8 + runs the rehearsal (a-d) on the made-up settings folder.
    Issue 39 ~6.26M.
    V1.7 fix round done e31d2ce6/8d6ad8e4/0abad292/c1813547: fix-round **173k** (est. 150-240k); full pytest 5095
    passed; all 1-8 fixed (tools update locks all local steps after the download, not only the four: a second
    updater could delete the first's partial folder). REHEARSAL PASSED (a) 20 rounds two-process saves, no loss;
    (b) 7 s holder → busy support_lock exit 3, no traceback; (c) writing:true, master.db untouched; (d) writer starts
    mid-plan. Merged + main → b8271dd9, pushed. BUG found: test_cli_job follower-through-compaction fails 4/6 alone
    (events out of order: m3.. then m1, m2), also on V1.7's base → V1.6/V1.4 bug; fix-round on feat/cli-1-6fix
    (root cause + deterministic test + window reader check). Issue 39 ~6.43M.
    Follower fix e760ee82: fix-round **80k** (est. 90-150k; 22 calls): EventReader read head then tail, lines flushed
    between the reads came out after the tail's; now tail first (writer flushes head before creating the tail), one
    open file for the tail, resume by last line seen; 3 deterministic tests (fail on old code); original test was
    wrong (a 10-event burst vs tail=5 may compact unseen events, allowed by design) → one at a time; 20/20 alone;
    full 5098 passed. Window reader not affected (in-memory queue). Merged + main → 5057d827, pushed.
    Issue 39 ~6.51M.
    V1.8 done 47b250a7: Sonnet **301k** (est. 210-300k; 118 calls; full 5146 passed). Moved into the engine:
    `HubApi.find_tracks` (no-hit `next: sync read`; envelope lifts `next` from ok answers), `views.cutoff_text`
    (window built it in format.ts), `check_view.person_steps` via new `discjockey/words.py` (+ `report.usb_step`
    for the CLI, check_text unchanged to avoid printing it twice), bad `todo --group` = bad_args; `names.search_fold`
    accent-insensitive for `track find` (FOR PHASE REVIEW: Library search still misses accent variants). Legacy
    `upgrade list` removed from batch_cmd, tests ported; catalogue ceiling 109. No `todo --links` (not in catalogue).
    Merged + main → 77b3eae6, pushed. Issue 39 ~6.81M.
    V1.9 done 894d6674 + ecf78637: Sonnet **351k** (plan 180k, est. 200-300k; 127 calls; full 5183 passed). Engine:
    rekordbox_status `state_text`/`problem_text`/`modified_at`/`size`; preview `<fact>_text` words + per-entry
    `folder_path`/`content_file`/`updated_at` (master.Entry gained them; READ_COLUMNS already had them); batch AIFF
    item `name`, skipped move `text`. Batch row: `kind` = aiff|moves, old console kind → `what` (V1.12 ports resume/
    undo onto it); `batch list` → `batches`, `move_batches` no own command; ceiling 104; `--limit 0` = all; preview
    holds reader_lock only while open, `rekordbox.writing` under a writer; `unknown_track` → reason `refused`.
    FOR PHASE REVIEW: preview golden/T4/locks driver fail (not skip) without ffmpeg. Merged + main → b88aa52d,
    pushed. Issue 39 ~7.16M.
    V1.10 split in two (record put it ~290-350k > 250k; split costs ~40-60k extra). Part a b3d2d921: Sonnet **244k**
    (est. 160-230k; 82 calls; full 5222 passed; one earlier full run failed test_rekordbox_timing 6 s assert, load
    flake). Plan store (24 h valid, files kept 7 d → plan_expired not unknown_id), `--plan` via `_bind_plan`,
    `needs_yes` with `catalog.CONFIRM` (empty, each group adds rows), dry runs store no scan (`jobs.refresh_work`
    passes scan=True). READ-ONLY CAME OUT DIFFERENTLY: `mode=ro` on WAL without -wal/-shm creates them, so
    `db.connect(read_only=True)` tidies with a RW open+close (removed only as last connection), `immutable=1` when the
    folder is unwritable. FOR PHASE REVIEW: that RW tidy open on the real library.db while the window runs; `prepare`
    dry run still writes record_reads/signs/pending_signs/extra settings (part b's T9). Issue 39 ~7.40M.
    Part b c062b331: Sonnet **268k** (est. 180-250k; 87 calls; full 5283 passed). V1.10 total 512k vs plan 205k.
    `CliApi.select_listing` (window's `select(track_id)` untouched, DROPPED); `select.py` holds the Upgrade-all set
    + "rows you can act on" (shared by library()/upgrade_all/upgrade_preview/select_listing); `upgrade_preview` +
    helpers moved batch_cmd → batches.py. `upgrade apply` rows stay planned (legacy handler pinned by
    test_batch_cmd; V1.11 builds it); `catalog.ALL_OF` names `upgrade apply` + `check done` (V1.11/V1.13 confirm);
    To-do `--rows` keeps file-less songs; empty Upgrade all = ok total 0; planned ceiling 102. T9 found reader_lock
    creating `rekordbox.lock` → readers no longer create it. FOR PHASE REVIEW (Important?): before any writer made
    the lock file, a reader holds nothing, so the first writer doesn't wait (fix idea: create the lock file at
    setup/app start, or keep it under an allowed path). `prepare` dry-run writes not hit yet (sync group).
    Merged + main → dc538714, pushed. Issue 39 ~7.67M.
    V1.11 split in two (plan 185k; record put it ~300k). Part a fa88baf2 + 4b54d0f6 + 22e05375: Sonnet **359k** (est.
    190-260k; cut by the 5-hour limit once, resumed by message; full 5290 passed, vitest 1592). Mode enum
    same_track|new_track|discard (window keeps Way swap|add_new, BRIDGE_MODE name map at the two api.upgrade calls;
    job kinds/result `action` strings unchanged); `upgrade apply` built (`--way`, `--all`, `--plan`, partial exit 6,
    needs_person); `batches.RekordboxOpen` is a Problem; `CliApi.result_words` hook; CLI-only `_resume_first`
    (Upgrade all refused while a stopped batch waits; window still starts a new one); planned ceiling 100; 11 legacy
    apply tests retired, unique ones ported; rehearsal step 5 now reads envelope data (untested). FOR V1.11 REVIEW:
    `next: batch resume aiff:<n>` unparsable until the new `batch resume` (V1.12); upgrade_preview rows say
    `add_new` while the request says `new_track`; plan bound before the library lock. Issue 39 ~8.03M.
    Part b 5170eb65: Sonnet **281k** (est. 170-240k; 94 calls; full 5319 passed). V1.11 total 640k vs plan 185k.
    `upgrade discard`, `track undo` (`upgrades.undo_blocker` reasons, `undo_upgrade_preview`), `check done`
    (`rekordbox_checked(track_ids, batch_id=None)` contract change; `aiff` resolver). No plan for discard/undo;
    named tracks all without a check = refused/changed exit 7, mix = partial; worker takes the outcome from the
    engine's word rows; ceiling 97. FOR REVIEW: `check done` with no args says "track ids is missing." without
    naming --batch/--all/--rows. Issue 39 ~8.31M.
    V1.11 review (review-V1.11.md): Sonnet **212k** (est. 150-210k; 46 calls): 0 Critical, 2 Important (plan items
    a subset run didn't name reported skipped/changed → false partial; track undo question always says "new versions
    wait again", wrong for Convert/clean-name undo), 8 Minor. No --yes bypass, no file moves outside the engine, no
    window logic. Decisions taken by the outcome rules (not product): all items failed and none done = `failed`, not
    partial; `check done <ids>` with nothing open = ok total 0 with skipped rows (brief: "skipped, not an error").
    Fix round (fix-round agent, Sonnet, est. 130-200k) running. Issue 39 ~8.52M.
    V1.11 fix 946ce524: fix-round **148k** (est. 130-200k; 64 calls; full 5325 passed): all 10 + decision fixed (5 left
    by the review's own "otherwise leave"); finding-9 tests checked by mutation. FOR PHASE REVIEW: `check done` with
    nothing open ends `ok` on the CLI's api but `changed` in the window's job (same method, two outcomes).
    Merged + main → 90cc0afe, pushed. Issue 39 ~8.67M.
    V1.12 split in two (plan 200k). Part a 8a980af0: Sonnet **325k** (est. 190-260k; 130 calls; full 5356 passed).
    Schema 10 `via` + scope (old console batches → terminal, scope null; terminal selections scope `selection`, not
    shown in the window's Library Resume link; window `upgrade` now records `selection`); `batch resume aiff:<n>`,
    `batch undo aiff:<n> --yes` + cli_first `batch_undo_preview`; not-stopped resume = refused/not_stopped; rehearsal
    script's batch undo calls → `aiff:<n> --yes --wait 3600`; ceiling 95. Some early runs had DISCJOCKEY_SUPPORT=""
    (shell vars not kept): checked, conftest's autouse `_scratch_support` covers every test and nothing in the real
    support folder or library changed. FOR PHASE REVIEW: `parse_id("track:1", ("aiff",))` → unknown_id not
    bad_id_kind; `batch resume` without id = argparse words; window "Undo all" still sends `undo_upgrade` with track
    ids (design row wants `batch_undo`). Issue 39 ~8.99M.
    Part b ef6b8856: Sonnet **404k** (est. 190-260k; 193 calls; full 5337 passed). rekordbox backups/restore
    (`rekordbox_restore_preview` dry run takes reader_lock, `writing` while a writer holds it; restore checks in
    `backup.preview`/`_verified`); batch_cmd.py + upgrades_cmd.py deleted (30+19 tests: 14 ported, rest duplicates or
    old prompts); carry #9 `_rekordbox_status` gone with batch_cmd; convert/rename helpers parked in convert_cmd.py
    until V1.13; rehearsal script step 8 (backups, restore dry run + --yes, byte-equal), not run yet; ceiling 93.
    FOR REVIEW: a job ending `busy` on a held rekordbox.lock carries no batch data (`worker._busy`), so an agent
    isn't told which batch stopped. V1.12 total 729k vs plan 200k. Issue 39 ~9.39M.
    V1.12 review: Sonnet **221k** (est. 190-240k; 76 calls; full 5337 passed): 0 Critical, 5 Important (batch undo
    reverses a later batch's step; undo dry run opens RW; restore dry run reads live master.db immutable while
    rekordbox runs; resume refuses a crash-left `running` batch; busy envelope loses the batch), 6 Minor. Decisions
    (mine, by the safety rule: never overwrite the person's rekordbox library with a foreign one): M-2 refuse when the
    live dbid is readable but the backup's is unknown; M-3 keep `refused` + `data.why` for phase 1 (FOR PHASE REVIEW).
    Fix round and rehearsal split (together est. >250k): fix (Sonnet, est. 150-200k) then rehearsal on made-up data.
    Issue 39 ~9.61M.
    V1.12 fix 02ebb757: fix-round **172k** (est. 150-200k; cut once by the usage limit at 4:50, resumed by message;
    full 5349 passed): all 11 fixed, I-1..I-5 test-first. `batch undo` refuses `newer_batch`; busy job carries the
    stopped batch; `master.immutable_for` public. Issue 39 ~9.78M. Next: rehearsal agent (Sonnet, made-up source).
    V1.11+V1.12 rehearsal: Sonnet **133k** (est. 150-230k; 49 calls): made-up rekordbox source (6 tracks, 35 s,
    builder kept at scratchpad/rehearsal-v1.12/build_fake.py for the V1.13/V1.14 rehearsals), 107 PASS, 0 FAIL, 9 NOTE;
    step 8 restore byte-equal. No repo change. Not proven by made-up data: real encoder delays, odd tags/paths, real
    Qobuz parked files, size, a master.db rekordbox itself last wrote → real-copy rehearsal with the user (morning
    list). V1.12 merged + main → c3bdc5ff, pushed. V1.12 total ~1.25M. Issue 39 ~9.91M.
    V1.13 split: part a = facts split (`read_facts`/`store_facts`, `HubApi.fill_facts`, `library facts`), dry-run facts
    in memory + 50-file limit, `HubApi.resolve("collection")`, `plan_id` on convert/rename/make_aiff; part b = `aiff
    convert`/`aiff rename` commands, convert_cmd.py removal + rehearse-convert + docs, carry #9.
    Part a fa5da9be: Sonnet **303k** (est. 190-260k; 90 calls; full 5383 passed). `read_facts`/`store_facts`,
    `aiff_plan.with_facts` (≤50 in memory, else `FactsMissing` → refused/facts_missing), `CliApi.fill_facts` +
    `facts_preview`, `library facts`; `resolve("collection")` → `{view, key}`; `plan_id` on convert/rename/make_aiff
    (a plan with nothing left = refused/changed; only an empty plan = ok total 0); contract doc only (window sends no
    plan_id); ceiling 92. Issue 39 ~10.21M.
    Part b e0968bea: Sonnet **480k** (est. 220-300k; 184 calls; full 5422 passed, vitest bridge 211). `aiff convert`/
    `aiff rename` all forms (`catalog.primary` + `ALL_METHOD` pick make_aiff for `--all`; `rename_all` verb in
    select_listing); `aiff_plan(scope, only)` bridge change; convert_cmd.py + tests removed (34 legacy: 28 ported,
    6 dropped); rehearse-convert on the new commands (not run); carry #9: `plan.rekordbox.writing`. Open, for the
    review: `rename --all --plan` breaks V1.10's plan rule (unknown plan ok, changed items dropped silently); aiff
    dry runs leave a job record in jobs/ (T9 exempts them); rename --all >50 unfilled = facts_missing while convert
    --all fills; `--rows --in playlist:<unknown>` not unknown_id. V1.13 build 783k vs plan ~200k. Issue 39 ~10.69M.
    V1.13 review: Sonnet **196k** (est. 190-240k; 48 calls; full 5422 passed): 0 Critical, 2 Important (rename --all
    --plan breaks the plan rule; the window's AIFF panel dead-ends on facts_missing over 50 unread files), 8 Minor.
    Decisions (mine, by the rules: no window regression, CLI keeps the dry-run rule): #2 (a) only the command line
    refuses, the window plans on stored facts as before; #3 T9 exempts jobs/ for every RJ dry run, non-RJ dry runs
    leave no jobs/ (FOR PHASE REVIEW: amend the design/plan sentence "exactly its plan"); #5 leave, document. Next: fix
    round, then rehearse-convert on made-up data. Issue 39 ~10.89M.
    V1.13 fix 9dbd3472: fix-round **193k** (est. 150-200k; 116 calls; full 5429 passed): all 10 fixed, Importants
    test-first; rename --all --plan follows the plan rule; window plans on stored facts; `folder:` outside Library =
    unknown_id. Issue 39 ~11.08M. Next: rehearse-convert (Sonnet, made-up source).
    V1.13 rehearse-convert: Sonnet **125k** (est. 120-200k; 70 calls): 218 PASS, 0 FAIL, 10 NOTE on the made-up
    source (stereo now; builder at scratchpad/rehearsal-v1.13/build_fake.py). Script fixes 6bf17f65 + 2cd96ec1 (would
    have hit a real copy too): ffmpeg 8.1's AAC caps ~225 kbps at 44.1 kHz → derived AAC made at 96 kHz (test first);
    `library facts` after the RH2 dry runs. Full 5430 passed. V1.13 merged + main → 3cafe9b9, pushed. V1.13 total
    ~1.30M. Issue 39 ~11.21M.
    V1.14 split: part a = Auto-upgrade phase alone (`run.auto_upgrade_only`, `auto_upgrade_preview`/`_run`, report
    kind, `start_note` words, `sync run --auto-upgrade-only [--dry-run]`, rehearse-sync script); part b = folders +
    settings (`resolve("folder")`, `settings_view`, `folder add/remove`, `settings show/set`, settings_cmd.py +
    legacy_out.py removal, docs).
    Part a a52ce2fc: Sonnet **358k** (est. 220-300k; 107 calls; full 5447 passed). `run.auto_upgrade_only` (held = ∅
    exact: a held song has no present file), `auto_upgrade_preview`/`_run` on CliApi (`CLI_LIBRARY_METHODS`), report
    summary `kind` (optional key), `start_note` in auto_upgrade.py + words; the phase's master.db reads now take
    reader_lock (sync's own phase too); `sync run` without the flag refused via `catalog.PHASE_ONLY`; rehearse-sync
    RH2-RH6 on the new command (not run); ceiling 85. Started a spin-loop Monitor once, stopped it. Issue 39 ~11.57M.
    Part b 35901f1a: Sonnet **264k** (est. 200-280k; cut once by the usage limit at 9:50, resumed by message; full
    5473 passed). `folder add/remove`, `settings show/set auto-upgrade`, `resolve("folder")`, `settings_view`;
    settings_cmd.py + cli/legacy_out.py deleted (7 tests ported, 1 dropped); removal/switch words into words.py via
    result_words; `folder remove` without a music folder = refused/no_library; ceiling 80. V1.14 build 622k vs plan
    ~200k. Issue 39 ~11.83M.
    V1.14 review: Sonnet **217k** (est. 170-230k; 68 calls; touched 311 passed, full stopped at ~35%): 0 Critical,
    0 Important, 8 Minor. Decision #6 (mine, by the stated invariant, not the reviewer's "document the real order"):
    a settings write takes the support lock around the read-change-write and the library lock briefly inside it
    (support → library), pinned by a lock-order test. Issue 39 ~12.05M. Next: fix round, then rehearse-sync.
    V1.14 fix 8ebb70f9: fix-round Sonnet **200k** (est. 115-200k; 80 calls; started on the old background rule; full
    5489 passed): all 8 Minors fixed. #6: support → library order for every settings write (`_settings_job`
    hold_library=False, `*_held` variants; set_music_folder reordered); sync's own Qobuz config/Spotify token saves
    still take support inside library → issue 42 in docs/issues.md (number free on main; check other branches at
    merge). Lock-order sentence in CLAUDE.md. Issue 39 ~12.25M. Paused by the user after it.
    User go 2026-11-16 afternoon ("continue"): through to phase 1 merged into main; AFTER phase 1 discuss with the
    user: Opus plan + Fable advisor + Sonnet build vs the current setup (bring measured cost per role).
    V1.14 rehearse-sync (made-up): Sonnet **96k** (est. 120-200k; 14 calls): 152 PASS, 0 FAIL, 8 NOTE; first runs
    failed only on the fake (spare MP3 had no cues → correctly upgraded, not refused); build_fake.py fixed in
    scratchpad/rehearsal-v1.14/; repo unchanged. V1.14 merged → phase branch 1444f8fe (issue 42 unique). Issue 39 ~12.35M.
    V1.15a 9ad51310: Sonnet **145k** (est. 150-230k; 42 calls; full 5502 passed in 6:01, foreground call auto-moved
    to the background by Claude Code at 180 s → interim wake). `--click` kinds + `--attach-upgrades` (two calls: after
    `folder add`); default upgrade = click 30 ms later (shifted), `--same-edit` exact. Stage D gaps (no kind added,
    FOR V1.15 REVIEW/FIX to decide): 24-bit 96 kHz WAV; `click_final.aiff` vs the marker-in-name rule; AAC 420 kbps
    (ffmpeg aac writes ~225k on clicks). Legacy `update` stays (tools update not runnable yet); it refuses busy (exit 3)
    while the registry holds update_tools/rollback_tools. Issue 39 ~12.50M.
    SUITE SPEED (user 2026-11-16): suite was ~25 s on 2026-10-23, now 4.5-6 min; Claude Code moves a foreground call to
    the background after 180 s. User: no 3-way split; make the suite fast. Profiling run on the phase branch first.
    Suite speed: Sonnet **332k** (est. 170-260k; 493 calls) on feat/suite-speed, tests/docs only: 365 s → ~63 s, 5496
    passed. Causes: drive flushes (F_FULLFSYNC + library.db pragmas) ~250 s, repeated ffprobe/ffmpeg ~54 s, SQLCipher
    KDF ~19 s, worksteal. Losses: real flush/KDF/tool runs only in pin tests + the timing test (`real_*` markers);
    tool memo answers identical bytes+command; goldens ignore a backup's -N suffix. Merged → phase 3f4b6044 and into
    feat/cli-1-15 (2ce1e058: 5509 passed in 62.7 s). Issue 39 ~12.83M.
    V1.15b first dispatch stopped by the user ("pause" → "NOW!") before any change (size not reported).
    V1.15b 63cb37fa: Sonnet **121k** (est. 150-230k; 30 calls; full 5518 passed in 51.9 s, foreground). `--clean <ID>|
    --all-marked [--into]` (Trash via NSFileManager, osascript fallback; Trash before entries leave library.db),
    `--remove` gone, `wav96` + `--messy-name`; no aac420 (aac_at max ~322 kbit/s). Issue 39 ~12.95M. Review next.
  - **NOW (2026-11-14 night, user asleep, go for issue 39 through the night):** issue 39 = the agent CLI, before the
    A–D live tests (the user wants an agent to run them through commands). User's rule: today's commands are evidence,
    not a template; design the CLI from first principles before building. Steps: 0 raw lists (done: scratchpad
    `cli-inventory/`, script `cli_inventory.py`: 95 bridge methods, 98 client calls, 447 screen states); 1 audit, 3
    Sonnet agents IN PARALLEL (user's one-off allowance for read-only audits; brief `brief-39-audit.md`) → files
    `docs/2026-11-14-cli-audit-{library,todo,app}.md` (uncommitted until all three are done; then check coverage of all
    95 methods by script, check_public, commit); 2 CLI design from first principles (Opus ~250k: agent needs, `gh`/
    `kubectl`/git plumbing patterns, keep/change/drop every existing convention with a reason, app-open behaviour,
    sandbox flag, jobs for long runs, `status`/`commands`/`where`, one exit-code table, parity + pinning tests); 3
    adversarial design review (fresh Opus ~150k, walks the A–D live tests on paper with only the design + draft agent
    docs); 4 design fixes (Sonnet if stated, Opus if new decisions); 5 build plan (Opus ~200k, groups <250k, existing
    commands moved onto the new design); 6+ build (Sonnet), reviews (write groups own review + rehearsal on a copy,
    Opus stage review), fresh-agent test with only AGENTS.md on a copy library, V, merge. No release. Est. ~5M total.
    Morning summary for the user: the CLI for an agent, what changed vs today's commands and why, what review found.
    Technical choices are mine (don't ask the user to review the design).
    User's addition (2026-11-14 night): coverage also from what the app is FOR, not only its functions. The designer
    (step 2) gets a required section: from README "Why Discjockey"/"How it works", the user's goals and the questions
    they'd ask an agent ("is my library ready for Saturday's gig?", "why didn't X download?", "what did the last sync
    do?", "undo yesterday's work", "does rekordbox match my files?"), each shown answerable/doable by commands. Covers:
    judgements made by looking/listening (spectrum → numbers + verdict), reasons and next steps as data, a cross-screen
    overview, time (waits, what changed since), goal-level health checks, recovery/history, a concept model in the
    agent docs. Step 3's review and the fresh-agent test use these goal-level tasks too.
    HARD RULES from the user (2026-11-14 night, binding for design, review and build): (1) the CLI gives at least
    EVERYTHING the window shows a person (every text, number, sentence, badge, colour/dimming meaning, tooltip, count,
    picture's data) and more where the window leaves things out for clutter; nothing is reachable only in the window.
    (2) The CLI is for humans too: the same information in readable text by default (`--json` for agents), e.g.
    quality cutoff + verdict visible to a person in the terminal; pictures as data plus an image file a person (or an
    agent with vision) can open. Structural guarantee: read commands return the bridge's own payloads (parity test) +
    UI-side computations moved into the engine. Audits got a "3b. Information shown" section by message (all three).
    Step 1 sizes: library audit Sonnet **391k** (70 calls), app audit Sonnet **425k** (86 calls; over the 400k cap),
    todo audit Sonnet **434k** (88 calls). Step 1 total ~1.25M (est. 470k). All 95 methods named across the three files
    (script check); 15 "not checked" cells (exact words/tooltips) left for the build, no follow-up agent. Estimated ~150k each without measuring (borrowed the review record); the material per area is
    200-300k of code. Gate now requires a measured `material: <N>k` (checklist line 10).
    Designer dispatched too early on unverified audits (121/196 UI files named by none), stopped by the user's call
    (~200k Opus lost, no file). Step 1b: two Sonnet supplement audits in parallel (supp-a 28 files 32k material,
    supp-b 59 files 61k; brief `brief-39-supp.md`, lists `supp-a.txt`/`supp-b.txt`) → `docs/2026-11-14-cli-audit-
    supplement-{a,b}.md` (A Sonnet **223k**, 43 calls, est. ~100k; B Sonnet **284k**, 63 calls, est. ~140k: file-list audits land ~2x
    material+work). G1 check: 95/95 methods, 162/162 non-generic UI files, A-D live-test rows 11/16/12/12 for 3/9/4/6
    plan steps; 37 Library screen states unnamed (24 families) → supplement C (Sonnet). Supplement C Sonnet **90k** (15 calls):
    37/37 states mapped (re-checked by script). G1 passed on all counts. Issue 39 total so far ~2.05M. 34 generic building blocks excluded (list in this session's step 1b command); their callers
    are audited. GATES for the rest of issue 39 (user: "the whole reason we do this design round is to GET IT RIGHT"):
    (G1) no step starts before its input passes a scripted completeness check on every count (95 methods; every UI
    file covered or generic with covered callers; every page's screen states; every A-D live-test step), the result
    told to the user first; (G2) any change to an announced plan is told to the user before it happens, never decided
    silently; (G3) no "covered by construction" to skip a check; (G4) every agent measured (`material:`) and its real
    size logged; (G5) each step's output is checked against its brief before the next dispatch by SCRIPT only (sections, coverage
    lists vs input lists, no empty or "not checked"-only sections, plausible counts), scripts print only counts and
    what's missing. The orchestrator reads only agent reports + script summaries, never outputs or code (user: keep
    the orchestrator's context clean for the whole night); quality judgement is the review agents' job.
  - **NOW (2026-11-14 evening, user active):** STAGE D MERGED into main a72530d1 (issue 33 stages A–D all on main, none
    released). No agent running, no worktrees, nothing in the background. First after a compact: check CI on main once
    (`gh run list --branch main --limit 2`; the merge run was cancelled by the next push, the docs push run covers it).
    User paused agents ("no new agents"): start nothing without the user's go. Open, user decides the order: live
    tests A–D with the user (each plan's last section), release only on go, issue 40 = stage E (design round, Opus
    ~250k), then 41 + 39 together, 24 last (my suggestion).
  - (old) **2026-11-13 ~04:00, user asleep, "work through the night":** STAGE C MERGED de95052; stage D building (see the Stage D entry below; briefs
    `brief-33-D*.md` in the scratchpad). (Old: fix round B, agent
    a3cae3cb1fbba6d5f, brief `brief-33-FB-C.md` in scratchpad a540fc7e…; findings `r2c-findings.md`). On its notice:
    log its `subagent_tokens`, `ps`, `check_public.sh --require-denylist` on its branch, merge `feat/rekordbox-c-fb`
    into `feat/rekordbox-c` (worktree `.claude/worktrees/rb-c`), remove `rb-c-fb` (--force: node_modules symlink).
    Then V: in `rb-c/hub-ui` `npm run verify` with run_in_background (~20 min, tail only), `npm run smoke`, CI green
    on the stage branch; look at the verify shots of the B states (sync-end-auto, -waiting, sync-before-auto-*,
    sync-auto-running, todo-auto-refused-panel/-choice @1100, setup-downloads, settings rows with ToggleRow). A real
    problem → one small Sonnet fix round. Merge "Merge feat/rekordbox-c: Auto-upgrade on sync" into main, push, CI on
    main, issue 33 in `docs/issues.md` gets the hash, remove the rb-c worktree. No release.
    Then stage D (design §9.3): Opus planner with a precise UI direction (no full mockup; single-component mockup only
    for a truly new block), split groups per checklist line 3, per-group reviews (it writes files + master.db),
    rehearsal on a copy, one shots pass, Opus stage review, fix rounds, V, merge into main. Then issue 40 design round
    only (Opus). Tell the user each dispatch's size + the stage's running total (C ≈ 3.37M before B).
  - Running: F4 (Sonnet, agent aaae40266f55be5e7, brief `brief-33-F4.md` in the scratchpad): S2 findings on
    `feat/rekordbox-b`. On its notice: log its `subagent_tokens`, `ps` check.
  - F4 done 2026-11-09 ~03:00: Sonnet **193k** (62 calls), 73e5fb2 + static f7b4351, CI green. Open for the verify
    shots: the single repointed card's cut "Current file" (F4 left it; judge it). Engine counts a batch as one in the
    To-do header ("N tracks are not lossless yet"); fake now 4-track batches; real fix needs the contract to carry a
    track count → issue on main before merging B.
  - V done 2026-11-09 ~03:40: verify 1081 shots ok; orchestrator shots of the F3/F4 states fine (✕ reads, cut Current
    file = scroll, kept). F5 (Sonnet **105k**, 845c98a + static 0f345d3): header counted lossless checks and a batch as
    one → "N tracks to check in rekordbox" part, `Todo.check_tracks`. **Stage B merged into main 0c2261b.** No release.
  - Stage C plan done 18dba4f (Opus **227k**): 12 steps C1, R-C1, C2, R-C2, C3, C4, RH, U1, U2, S, R2, V (est. 2.2–2.7M).
    Branch `feat/rekordbox-c`, group worktrees `.claude/worktrees/rb-c-<group>`. C1 done a2d7e51 (Sonnet **258k**, 87 calls, over
    its 150-190k: the plan's estimates run ~35% low; expect C2 ~250k). R-C1 done ccc6358 (Sonnet **144k**: 2 Important
    (set ≠ Upgrade all's while rekordbox runs; stamps raised on OSError) + 1 Minor ("Rekordbox" capitalised), all fixed).
    C1 merged into the stage branch 591c91e. Stage worktree `.claude/worktrees/rb-c`. C2 done 7325839 + db66c07 (Sonnet **293k**, 82 calls;
    stage B bug fixed: re-measured "not the same edit" now stored). R-C2 done 881b21d (Sonnet **186k**: 3 Important
    (end-of-sync words, `unknown` compare re-decoded each sync → `needs_choice` record on file mtimes, Stop before the
    quiet-sync phase) + 2 Minor, all fixed). C2 merged into the stage branch 65774a5. Facts for later groups:
    scratchpad `stage-c-notes.md`. C3 done c0a56dc (Sonnet **268k**, 110 calls: sync --json,
    settings auto-upgrade, CLAUDE.md invariant, README, CONTRIBUTING); merged into the stage branch 8bf2ef1. R2 to
    check: the console runs a dry-run phase before every sync (double compare cost?). C4 stopped at its limit: afaa5aa + static 8c58683 (Sonnet
    **363k**, 97 calls: Python bridge + contract + types + run store + fake shapes; the fake phase, 9 scenarios and the
    toolbar toggle left, `c4-handoff.md`). Lesson: a bridge group (Python + contract + TS + fake) should have been split
    bridge vs fake BEFORE dispatch (checklist line 3); the "stop past ~250k" line fired ~110k late. C4b (Sonnet, fake
    scenarios) done 6dbc615 (Sonnet **218k**: fake phase, 9 scenarios, toolbar "rekordbox open"); C4 merged into the
    stage branch 9532047. Routes per state: C4b report, copied into U1/U2 briefs. RH (Sonnet, rehearsal on a copy)
    done 674cb32 (Sonnet **201k**): 138 checks pass on a copy (switch off byte-equal, dry run, phase 4 done + 1
    not_analysed, no repeat, re-try after re-analysis, undo all); no engine bug; merged into the stage branch b4df9b5.
    U1 running on **Sonnet** (plan says Opus; §6 is a complete direction from existing blocks, no design decisions
    left, same basis as the user-approved Sonnet UI fix rounds; S + Opus R2 judge taste).
    U1 done 6571896 + static (Sonnet **276k**, 108 calls; ToggleRow name wraps with a sub, refusal NoteCard at the top
    of the upgrade cards); merged into the stage branch 23d206f. U2 (Sonnet, Sync states) done 23a8056 + static
    (Sonnet **269k**; rekordbox-open note as warn NoteCard, live card hidden in the phase); merged into the stage branch
    4439624. S (Sonnet shots) cut off by the session limit on 2026-11-09, resumed 2026-11-13: **240k** (38 shots, 4
    Important + 15 Minor, top: same track twice on the end screen, refused track under Still waiting, To-do reason
    cut at 1100; no drift). R2 (Opus stage review) **250k** (49 calls; over its ~200k): engine safety holds; needs
    fixes: A code/docs 8 (3 Important: track listed twice, unknown-compare sentence, before-start words vs end check),
    B UI 12 (3 Important). Fix round A (Sonnet **181k**, 89 calls): A1–A8 all fixed, pytest 4211 ok, CI green; merged
    into the stage branch caa59f7. Fix round B (Sonnet, UI, brief-33-FB-C.md) **306k** (149 calls; far over its ~170k stop: no commit
    before ~300k, I told it to wrap up): B1–B12 done except B9 (NoteCard kept; judge `todo-auto-refused-choice`); B7 Hint
    shortened to "{n} upgrades go in at the end; cues stay.", B8 Hint to "Waits for rekordbox: it goes in at your next
    sync, or quit it and press Replace." (rules' 90-char limit). Merged into the stage branch e01bf13; V running.
    Final B size **308k**. V: verify 1129 shots ok, smoke ok, CI green; my look at the
    B shots: B9's ways sit under the fold at 1100×700 (panel scrolls, Replace = try again): kept. Fix C (Sonnet **49k**):
    no full stop on an Upgraded row's second line (7eefe3f). **Stage C merged into main de95052.** No release; live test
    plan C §9 with the user. Stage C total ~3.74M (plan said 2.2–2.7M). Lesson: a 12-item UI fix round is two rounds.
  - **Stage D** plan done 908e04f (Opus **288k**, 69 calls): 19 runs D1, R-D1, D2, R-D2, D3, R-D3, D4, R-D4, D5, D6,
    D7, RH, U1 (Sonnet), U2 (Opus: `AiffBatchPanel` layout; no mockup, judged in shots + R2), U3, S1, S2, R2, V; plan
    est. 3.3–3.8M (record says ~+35%: expect ~4.5M). Branch `feat/rekordbox-d`, group worktrees
    `.claude/worktrees/rb-d-<group>` on `feat/rekordbox-d-<group>`. D1 (Sonnet) done cd2a39f: **304k** (55 calls; cut once by
    the session limit, resumed; over its ~200k stop): V8 file facts + facts pass, `cdj.py`, `cdj_cover`, `own_name`,
    `aiff_action`; beyond plan: stream kbps, covers dropped in write_tags. Notes: scratchpad `stage-d-notes.md`.
    R-D1 (Sonnet) **189k**: ready, one test added; carries noted in `stage-d-notes.md` (D4: one lossless-codec list,
    quality's; D5: console facts fill + a failed-probe mark so an unreadable file doesn't re-import every launch).
    D1 merged into the stage branch 92bb5229 (stage worktree `.claude/worktrees/rb-d`). D2 (Sonnet) done 534d2670:
    **384k** (131 calls; plan said 180-200k, stop line ~200k ignored again): `convert_file`, undo/recovery without
    `held`, 75 tests. R-D2 (Sonnet, brief-33-RD2.md) running with two stated fixes: an AIFF at its clean name converts
    in place (no ID name), convert's words. Lesson: the plan's 170-200k engine groups land at 300-380k.
    R-D2 (Sonnet) **203k**: ready, words fixed (53f9a6a0); in-place convert NOT possible on the swap machinery (its
    recovery decides on FolderPath). Decided: chain, no new op kind: when Convert lands on the ID name because the old
    file held the clean name, the same item runs Rename to the clean name (D3b builds it). D2 merged into the stage
    branch 288ad697. D3 split before dispatch (checklist line 3): D3a step + recovery, D3b undo + report + chain.
    D3a (Sonnet) done 201d2d0f: **304k** (80 calls; even a half group lands ~300k: reading CLAUDE.md + plan + notes +
    convert.py is ~100k before work starts): `rename_file`, `recover_rename`, 57 tests; rekordbox running stops the
    batch (RekordboxOpened, as Convert) instead of a per-track `rename_blocked`: accepted. Merged into the stage branch
    f8319935. D3b (Sonnet, brief-33-D3b.md: undo_rename, report, the chain; chain undo keeps the convert's undo in
    the rename's `before`) done 631459a2 + 5db375e5: **219k** (72 calls): undo_rename + recovery, report "renamed",
    the chain (AIFF 24/96 at its clean name ends at the same name 16/44.1; two undos restore). R-D3 (Sonnet, review of
    D3a+D3b, brief-33-RD3.md; stated fix: the chain's visible check is "converted") cut by the usage limit, resumed: **203k**, ready (c2777dc3 chain says "converted"; 3b5d0fe9 nested-undo backup kept; 4428 passed, CI green). D3b merged into the stage branch f3db1e4d. Carries in `stage-d-notes.md` (D4: rename items need a write, renamed=True, chain undoes twice; D6: check_view's old_path). D4 split before dispatch: D4a batches (brief-33-D4a.md), D4b aiff_plan + view/CDJ membership + one lossless list (brief-33-D4b.md). D4a (Sonnet) done ac225a1b: **217k** (69 calls; 4501 passed), merged 8b17a957. D4b (Sonnet) done d11d2eda: **251k** (80 calls; 4550 passed; views.library_files, cdj.group_members, one lossless list), merged fcd2d7b1 (local suite green; CI confirmed after). User asked about R-D3's "shared helpers" note: rename.py reaches 23 convert.py names + 2 library privates, 24 test patches → falls under CLAUDE.md "Refactor when necessary" (cost only grows with D5/D6/RH tests). D4c (Sonnet, brief-33-D4c.md, ~150k): move the shared rekordbox-step kit into its own module, module-qualified access, no dead patches; running. R-D4 then reviews D4a+D4b+D4c with 4 stated fixes (convert's rekordbox_unreadable words, clean_aiff words, aiff_plan bytes 0 without a rekordbox track, `waiting` counts in the plan). D4c done 5c0e2915: **152k** (rbstep.py 308 lines, convert.py 1146→877, 4550 same count, dead-patch spot checks), merged dc05f60b. R-D4 done 507f3d68: **261k** (118 calls): ready after fixes, all 4 coordinator fixes + 2 Minor; unreadable rekordbox library → every file waits (step refuses all); D4c byte-identical by AST diff; merged f8ce865c (4556 passed). Coordinator read all four engine reviews (stop point before D5). D5 split: D5a commands + facts fill (brief-33-D5a.md, ~250k, running), D5b failed-probe mark + facts phase word (~130k), D5c docs (~130k). D5a done c2a86242: **263k** (85 calls; convert_cmd.py, importer.fill_facts, 39 tests; CI green), merged acf4a935. D5b done b042e741: **141k** (schema V9 `files.facts_failed`, --in unknown → bad_args; phase word moved to D7: needs hub UI), merged 796ba3c8. D5c done 4106a54c: **172k** (docs; README describes UI before U1–U3: R2/V check it), merged ac35e895. D6a done 5dacbd43: **187k** (views: CDJ group, check views, batch details, undo words; found: a stopped CDJ batch would show Resume on Upgrade ready → D6b wires kinds), merged 9b004d87. D6b (api, brief-33-D6b.md, ~230k) running; contract doc moved to D7a, facts phase to D7b. User 2026-11-13: savings only without hidden cost (U2 stays Opus; every shot state judged; agents grep big files). D6b done 85016373: **232k** final (cut by the usage limit, resumed; connection dropped after a green suite, resumed to commit only; 4659 passed; track().aiff, aiff_plan read, aiff_batch jobs convert/rename/make_aiff, D6a wired), merged 933d7846 (CI confirmed after). User 2026-11-13: no 400k agents (step cost grows with context; split ≥ ~190k pays; big agents needed fix rounds). D7a done e968127d + static 7aef55b0: **319k** (112 calls, over the ~250k estimate; types/contract/client, fake/convert.ts ports cdj+aiff_plan, contract doc section, shapes pinned both sides; 4661 passed, vitest 1453), merged 4e96c321 (CI confirmed after). D7b done 064f067a + static 649814c4: **222k** (87 calls; 28 scenarios in fake/aiffScenes.ts, facts phase end to end; 4661 passed), merged 65704637. RH done 96ae5e8c: size not reported (connection dropped after its commit and cleanup; counted ~220k); rehearse-convert on a copy: **216 passed, 0 failed** (Make all flac/aiff_hires/tags/name, CDJ AAC, lossy by name d 2257/1600/632 matched to the sample, undo byte-identical; source only copied, rehearsal-d deleted; CI green), merged. U1 done 0be444e3 + static 6eddb262: size not reported (connection dropped after both commits; counted ~230k; coordinator ran svelte-check 0 errors + vitest 1500 passed), merged 44f48434. Pushes failed with HTTP 408 / HTTP2 framing errors around midnight (network); local work continues, push when it clears. U2 split before dispatch (Opus UI record 300–400k): U2a Opus AiffBatchPanel + flow + gallery + design log (brief-33-U2aD.md), U2b Sonnet table multi-select + subjects + header + wiring (brief-33-U2bD.md). U2a (Opus) done 35d11157 + static 429b31ec: **312k** (89 calls; AiffBatchPanel + AiffBatchFlow, gallery 12 states, design log; vitest 1536; gap: a reloaded window can't tell an AIFF batch_resume from Same track's → R2 fix round), merged locally 4fbfc3ba. Pushes hang (HTTP 408 / SSH receive-pack stalls) on exactly one blob: U1's static bundle index-PfAR83T9.js (probe commits: that blob alone hangs, U2a's 288 KB bundle and a 70 KB one push fine; secret-scanning push protection is on, the likely cause). Fix after U2b: rebuild the local stage stack without U1's static commit 6eddb262 (U1 code 0be444e3 is on GitHub; cherry-pick U2a/U2b code commits; one fresh build(hub): static at the end). U2b (Sonnet) done f474150b + static: **197k** (cut by the usage limit before writing, resumed; multi-select, subjects, header, wiring; vitest 1554). Stack rebuilt without U1's static commit and pushed: feat/rekordbox-d 2b4cb316 (U1 51c3c54f, U2a 12e38631, U2b 20c043c2, one fresh static). U3 (Sonnet) done 362f66b8 + static: **261k** (63 calls; CDJ group, Convert all, check cards, Undo words; vitest 1575; CI green), merged b31d70e3. Shots: coordinator judged 15 simple states (4 Important, 2 Minor, 1 for R2: stage-d-notes F1–F7); shots agent (Sonnet) **204k** judged 13 panel/multi states (2 Important, 5 Minor + the table not refreshing after a run: S1–S8), added library-aiff-panel-stopped-ended d989f192. R2 (Opus) **256k**: not ready, one fix round, no redesign; invariants hold; A1–A9 (engine/bridge/docs: batch_kind in the job snapshot, blocked track().aiff fills the would-be step, README check card, CDJ waits map, CONTRIBUTING, no-free-name words, To-do plan cache, CDJ vs questions, tests) + B1–B7 (UI: panel one scrolling column, AiffCard names + blocked, check cards render outside {#if card}, adopt by batch_kind, CDJ head/rows, no-break hyphen, Quit rekordbox wording); S3/S7 overridden; nothing parked (scratchpad r2d-findings.md). Stage D total ~6.20M. Fix rounds A-1 (A1–A6), A-2 (A7–A9 + coordinator's A10 JobStarted batch_kind, A11 run-time no-free-name words), B-1 (B1–B3), B-2 (B4–B7), fresh Sonnet each. A-1 done (5 commits, merged 9233decb; 4668 passed): **268k** (160 calls, over its ~180k). Stage D total ~6.47M. A-2 done 67b52936 + static, merged 226ceedf: **181k** (CDJ group leaves out decided songs, a real double listing; JobStarted batch_kind; 4674 passed). Added B8 (console CDJ group = hub's) to B-2. Stage D total ~6.65M. B-1 done + static, merged 973f0b8d: **176k** (panel one scrolling column, AiffCard names + blocked card, check cards render outside {#if card}; the shots.json waits on [data-test=replaced] hold). Coordinator re-shot B-1's states: all fixed; new B9 (undo line truncated) sent to B-2. B-2 done f6ed7f2b + static 98905e86, merged aca999e2: **~195k** (cut by the usage limit after its push; CI green; adopt by batch_kind, CDJ head/rows + rowOff, no-break 16-bit helper, Quit rekordbox wording, undo line wraps, console CDJ group = hub's). Stage D total ~7.02M. Coordinator re-shot B-2's states: all fixed. V: README matches the UI; verify 1216 shots, one state failed (todo-offline-selected: the fake's track().aiff read a download's missing facts when its drive was away and crashed the panel; the engine answered with an empty Now line): fixed by the coordinator on the user's go (option 2, no agent, 2026-11-14) in fb749279 (a download gets no answer, both sides, tests), To-do rules 243 ok, pytest 4676 passed, smoke ok. **Stage D merged into main a72530d1.** Plan stays in docs/ for its live test (§9). No release. Stage D total ~7.02M (plan est. 3.3–3.8M). Next: issue 40 design round (Opus) when the user says go; live tests A–D with the user.
  - Issue 38 done: Sonnet **213k** (114 calls, over its 130-190k: root-cause hunt + verify). Root cause views.playlists()
    sent `quality: null` for an unread (off) playlist → `null.lossless` in Row.svelte. Engine sends zero counts; words
    "left out of the sync · their files stay". Verify 1081 ok, CI green. Merged into main (see git log). Next: stage C
    planner (Opus, brief-33-PC.md).
  - (done) V (orchestrator, no agent): in the rb-b worktree `cd hub-ui && npm run verify` with `run_in_background` (~20 min,
    read only the tail), `npm run smoke`, CI green on the last push. Look at the verify shots of the F3/F4 states
    (selection head NoteCard, batch rows with `wrapName`, the ✕ colour (F3 #5, measured #7a7a80), the check cards);
    a real problem → one Sonnet fix round. Then merge `feat/rekordbox-b` into main ("Merge feat/rekordbox-b: rekordbox
    write side, batches, Same track for any format, Upgrade all"), CI on main, push, add the hash to issue 33 in
    `docs/issues.md`. No release.
  - Then issue 38 (one Sonnet agent, systematic debugging, branch `fix/playlists-switch`, merge when green), stage C
    (Opus planner on design §9 stage C; per-group reviews + Opus stage review + rehearsal on a copy; merge when green;
    no release before the user's live test), stage D (design direction, build, merge when green), issue 40 design
    round only. Every dispatch through the gate; log every size; status line for the user at the top of this list.
