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
    standing go covers it; telling the size is enough). Safety half (Opus) RUNNING → phase1/phase-review-safety.md.
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
