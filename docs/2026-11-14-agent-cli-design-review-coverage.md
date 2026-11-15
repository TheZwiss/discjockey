# Issue 39: coverage review of the agent CLI design against the six audits

Reviewer: Sonnet, step 3a (2026-11-15). Design: `docs/2026-11-14-agent-cli-design.md` (cited as §n). Audits cited as
L, T, A, SA, SB, SC. Verdicts: answered (a named command, field, mechanism or rule gives it), by construction verified
(the shared mechanism reaches it, reason given), gap (`C<n>`).

## How items were counted

One item = one row of "Information shown", one decision row (D/U/T function), one action or bridge method, one screen-state
family row, one journey, one judged convention or numbered finding of the audit's §0/§5. A gap is attributed to exactly
one item (the one it is clearest in; related items are named in the finding). A defect that appears in several audits
(C1) is listed once, under the first audit that has it, and counted as one gap row in each audit it appears in. Findings
are numbered across the whole file, in audit order.

**What "by construction, verified" means in this file** (reasons are repeated by letter below):
- **V-payload**: the item is a field of a bridge payload and no window code computes or words it; §8.1 puts the bridge and the
  command on the same `surface` function, §4.2 prints every `shown` field, T3/T4/T7 check it.
- **V-words**: a word or tooltip that carries no data: it moves to `words.py`/`words.json` (§8.2), `help glossary` prints it, and
  T5 fails on a literal in the UI.
- **V-view**: pure view state (open panel, selection, scroll, sort pref, player, layout) on the §9.1 stays-in-window list; it
  is not information the person reads, and its data part is a payload field.
- **V-rule**: a window computation that §9.1 (a)(b)(c) moves and that §9.3 names or whose function name §9.3 lists.

---

## 1. `cli-audit-library.md` (L)

Items: actions 44 · decisions D1–D37 37 · screen-state families 15 · information rows 83 (header 11, table 17, one track 15,
several rows 7, browser/rail 8, foot 3, watched folders/import 8, tidy/undo 9, toasts/dialogs 5) · journeys J1–J16 16 ·
judged conventions §5 12 · findings §0 7. Total 214.

**Answered (180):** all 44 actions (every method has a command in §5.2, or a stated reason: `media_url`, `select` dropped,
`pick_folder`/`quit` not in this audit); 30 decisions (D1, D2, D4–D15, D17, D19–D26, D28–D31, D33, D34, D36 by §9.3 rows or
§5.2); 13 screen families; 60 information rows (named fields: `library list` rows/chips/summary/subtitle/songs/`empty`/`also`,
`dim`+`dim_why`, `file_state_text`, `next_try_text`, `actions[]`, `track show`, `library collections`, `folder list`,
`import status`, the AIFF card fields, `tidy run --dry-run`, `batch list --kind moves`, `check.steps`); 16 journeys; 17
conventions/findings (§0 F1–F3, F5–F7; §5 all but discoverability): the envelope, typed ids, global `--json`, one exit table,
`--dry-run` everywhere, `--yes` flags, `--wait-busy`, jobs, `--rows`, app routing, `status`/`as_of`.

**By construction, verified (30):**
- V-view (19): D3, D16, D18, D27, D35, D37 (per-collection filter, selection kept, columns, browser Play, spectrum trigger,
  refresh wiring); screen families `library-now-playing*` and `library-browser*/inspector*` (layout); information rows: search
  field text, details toggle, skeleton/ProblemCard, columns at width, selected-row wash, row heights, mini player,
  filter-match highlighting, now-playing row, foot bar playing and position rows.
- V-payload (9): page title, `#` position column, title/artist/length, folder/subfolder/playlist badge columns, UPGRADE badge,
  "Open in {Service}" (`track_link`), "Show some in the sidebar…" (`too_many`, `crate_count` are sidebar fields), the rail's
  counts and warning mark (nav counts in `library collections`, same `sidebar()` twin), "Can't play this file" (row `playable`).
- V-words (2): browser row tooltips (§9.1 (c): the sentence with data comes from `words.py`); the current-file card (its
  source-how words in `copy.ts` move by T5, its fields are `track` payload fields).
- Also relied on in "answered": the quality chips' "Fake only if >0" (`segOptions`) needs nothing, because all chip counts are in
  `library.chips`, which the command prints whole.

**Gaps (4):**

### C1. Save question: per-rename and per-file choices have no command form
- Audit: L D32, `tidyModel.ts` `saveFiles`/`saveMoving`; §1d `save_playlists(files)`; journey J11. Severity: **Important**.
- The window's save question lets the person keep a folder rename on or off one by one, and untick single files of the
  moves it offers (`renames: [[old,new]]`, `moves: [[file_id, from_path]]`). The design gives `playlist … --files move|leave`
  and `--no-rename` only (§5.2 `save_playlists`): all renames or none, all moves or none. The window does more than the
  command (hard rule 3). It can only be approximated by `--files leave` followed by `tidy run <files>`, and then a folder
  rename on disk is lost.
- Fix: `playlist save`-type writes take `--rename <old>=<new>` (repeatable; default = every offered rename, `--no-rename` =
  none) and `--move <file>…`/`--no-move <file>…`, and the dry run lists each rename and move with an id so the plan binds
  them (`--plan` already binds a subset if the items are individually addressable in the plan: say so).

### C2. Printed paths: absolute or relative is not decided
- Audit: L §5 "Discoverability" (JSON paths relative to the music folder for `Library/` files, absolute for watched-folder
  files). Severity: **Minor**.
- §4.1 says payloads carry `path`, `cover_path` and §3 accepts both forms on input, but nowhere says what a printed path is.
  An agent that gets `Library/Hard_Bounce/A - B.aiff` next to `/Volumes/Gig/…` cannot tell what it is relative to.
- Fix: one rule in §4.1: every `path` in a payload is absolute; add `rel_path` where the window shows the relative form.

### C3. The Library header's actions (Make AIFF…, Resume · k left) have no engine decision
- Audit: L §3b header row "Header button Make AIFF…", source `libraryModel.ts:602 aiffHeader`. Severity: **Minor**.
- §9.3 moves "which actions an item/row/track offers" (`actions[]`), but not what the view's header offers: hidden when no
  files, empty library or gone view; "Resume · k left" with its tooltip. `aiffHeader` is in no §9.3 row. The facts (`aiff_stopped`)
  are in the payload, the command exists (`aiff convert --all --in C`, `batch resume`), so no action is lost; the
  window's rule and words are.
- Fix: add `actions[]` (same shape) to the `library list` payload for the view; add `libraryModel.ts:aiffHeader` to the §9.3 D7 row.

### C4. Nothing guards a window-computed non-word fact the audits missed
- Audit: L §0 finding 4 ("the window holds state the engine does not") and D6/D7 as the pattern. Severity: **Important**.
- The design's H1 guarantee ("by construction") rests on three things: same payloads (T3/T4 compare the bridge with the
  command), the words rule (T5, strings only) and the §9.3 list, which is exactly what the audits found. A count, order, tone,
  visibility, dimming or default that a `*Model.ts` computes from payload fields passes T3 (the adapter is thin), T4 (payloads
  equal) and T5 (no string). D6 (`rowInTodo` diverging from `_group`) is such a case today. Nothing makes the next one fail.
- Fix: a second rule-checker check `derive`: every exported function of `hub-ui/src/{pages,lib}/**/*Model.ts` and `format.ts` is
  either listed in `hub-ui/derive-allow.json` with a `view` reason from the closed set of §8.3 or has a `surface` field it reads
  (a `reads:` tag in its docstring); an unlisted function fails; ratchet it down like `words-ratchet.json`.

---

## 2. `cli-audit-todo.md` (T)

Items: findings §0 8 · actions 39 (reads 11, upgrade/check/batch writes 13, other writes 11, owned elsewhere 4) · decisions
(§2 rows) 36 · screen-state families 15 · information rows 57 (page/list 18, details 24, question/duplicates/dialog 4,
selection and batch panels 6, pictures 5) · journeys 57 (J1–J10 10, J11 live tests: stage A 10, B 15, C 11, D 11) · judged
conventions §5 18. Total 230.

**Answered (213):** all 8 findings (`todo list`, `rev`, `check.steps`, `words.py`, scope dropped, `bought_name`, app routing,
selection rule); all 39 actions (each bridge method has its command in §5.2; `select` and `media_url` are dropped with a
reason; one-track writes take `--if-rev`); 31 decisions (the §9.3 T rows: `cdjAllKeys`…`wholeUpgradeGroup`, `goes`, `selectionWays`,
`canSwap`/`upgradeWays`/`defaultWay`, `sameTrackWhy`, the check/undo/batch-end card functions, `groupIdOf`, `keepWords`, `decisionFor`,
`checkTracks`…, `headerSub`, `segOptions`…, `itemKey`, `MULTI_GROUPS`, `actionsFor`, `rowOff`…, `compareLines`, `qobuzText`,
`aiffModel.*`, `aiffBatchModel.*`, `AiffBatchFlow.start`, `adopt`, `headResume`, `Details.aiff`, the `WrongSongDialog` tones,
`writeBlockedReason`, `autoUpgradeOn`); 15 screen families (the ended batch view of a New track/Discard batch, "held only by the
window", is kept by every job's `result.json`, §6.1); 47 information rows; 55 journey rows (J1–J9; stages A–D rows by the §15
tables: each of the 47 live-test steps has an agent command or a named person step, except two gaps below); 18 conventions.

**By construction, verified (14):**
- V-payload (6): `autoNotes` (the audit says the engine already has it: `views.upgrade_detail`, and `track show` prints
  `upgrade.auto_refused`/`auto_waits`); list head label/hint (`groups[].label/hint` are payload fields); the trailing
  UPGRADE/FREE/HIDDEN badges (`upgrade_ready`, `free`, `hidden`); the list order (`views.todo` sort, same function);
  "Open in {Service}" (`track_link`); the check card's "other" note (`check.text`).
- V-words (3): "found 18 Oct" (`upgrade.found`, the date text from the shared formatter), the Now label/tooltip (both fields
  `source_format_line` and `quality_label` are in `track show`; the choice is presentation, the tooltip is static), the Edit row
  "The same edit, 4 ms apart" (`alignment {result, offset_ms}` are payload fields; the sentence template moves by T5).
- V-view (5): `dropDecision` (a drag and drop; the engine's readability check runs in `version add-file`), `keepSelection` and
  the other selection/hold/deep-link helpers, `Page.svelte:load`, the "N checks selected" title, the selected wash.

**Gaps (3):**

### C5. `upgrade apply` without `--way`: what happens is not stated
- Audit: T §2 `decisionModel.ts:canSwap/upgradeWays/defaultWay` and `UpgradeFlow.way` ("with no choice, which mode Replace sends"),
  §0.4; §1.2 `upgrade add_new` ("`--all` is refused for new-track"). Severity: **Minor**.
- §9.3 moves the default and the "mode Replace sends with no choice" into `upgrade.ways[] {recommended}`, but §5.2 lists
  `upgrade apply <tracks> --way same-track|new-track` and says nothing about a missing `--way`, nor about `--all --way new-track`.
  An agent that copies the window's Replace has no stated command.
- Fix: say in §5.2/§7.3: `--way` omitted = each track's engine default (`recommended`; the only way when there is no choice),
  `--all` = Upgrade all (Same track only); `--all --way new-track` is `bad_args` with the window's reason.

### C6. `not_lossless.md` (the buy list) has no command and is not named
- Audit: T J10 ("not_lossless.md: none"), J6, §1.3 `hide` (rewrites it), README "Reports and not_lossless.md". Severity: **Minor**.
- The design never mentions the file or the buy links (`track.buy_links`, `free_downloads`) outside "the whole details payload".
  The per-track data is reachable (`track show`), but the file's own overview (every not-lossless song with its links and the exact
  filename to save it as) is a document the user is told to read, and `where` does not give its path.
- Fix: `where` and `open report` name `.discjockey/not_lossless.md` (`open file not-lossless`), and `todo list --links` prints the
  buy links, free downloads and `bought_name` per item.

### C7. §15 step B-9b relies on a `rekordbox status` field that the design removes
- Audit: T J11 stage B step 9b ("no command shows master.db modification, `contentFile` values"). Severity: **Important**.
- §15 says "`rekordbox status` (modified time)", but §12 says "`rekordbox status` … gains nothing", and §5.2 gives the bridge
  only `problem` and `version` from the console's answer. No section defines a modified time (or size/hash) of `master.db`.
  The check that rekordbox did not touch its library meanwhile cannot be run as written. `rekordbox preview` gains
  `content_file`/`folder_path`/`updated_at` per entry (§5.3), which covers the second half only.
- Fix: add `modified_at`, `size` (and the existing `db_version`) to `rekordbox status`, correct §12's "gains nothing", and say it in the
  schema.

---

## 3. `cli-audit-app.md` (A)

Items: §0 state rows 9 · actions 69 (sync 9, runs 5, shell 7, limits 4, playlists 6, tidy 5, logins 15, other settings 7, setup
5, watched folders 6) · decisions U1–U39 39 · screen-state families 54 (Dashboard 8, Sync 15, Limits 4, Playlists 9, Settings
8, Setup 7, Shell 3) · information rows 44 (Sync before 10, running/end 6, Dashboard 6, Limits 6, Playlists 6, Settings/Setup/
shell 10) · journeys J1–J19 19 · judged conventions §5 37 (5.1 11, 5.2 5, 5.3 1, 5.4 2, 5.5 2, 5.6 13, 5.7 3). Total 271.

**Answered (256):** all 9 state rows (each has a home in §9.2: plan.json, `sync_scope`, the job registry, import state, `rev`,
`plan_infos.json`); 68 actions (every method has a §5.2 command, or `pick_folder`/`quit` are window-only for a closed reason and
`setup_check_account` is dropped for a reason); 34 decisions (§9.3 U rows: U1–U3, U5–U10, U12–U15, U17–U26, U28–U34, U36, U39,
and U16/U37 by `sync plan --search` / `library scan`); 49 screen families; 40 information rows; 19 journeys; 37 conventions
(the sync becomes `sync read|plan|run`, the app binary routes any argument, `--wait-busy`, one lock rule, registry-based
visibility between window and Terminal, per-job `log.txt`).

**By construction, verified (13):**
- V-view (9): U4 (ticks carried over), U11 (which sync view shows), U35 (the "99+" cap; the counts it caps are `status` fields),
  U38 (refresh wiring); screen families `dashboard-error`, `sync-search`, `sync-analysed` (4 s timer), shell view state,
  design gallery/frames (not app states). Their data parts (counts, results, verdicts) are payload fields.
- V-rule (3): the read-problem card's "Hard_Bounce, Powertrance and 2 more aren't read until Qobuz is connected" (`readBlockLine`),
  the "N more tracks left out" note (`leftOutTitle/leftOutBody`) and the Playlists list head "N playlists · M switched off"
  (`listSummary`). None of the three function names is in §9.3, but each is a sentence with data (§9.1 (c)), its facts are
  payload fields (`playlist list` rows with `service`/`needs_setting`, `read_status.services`, the plan's `in[]` and the stored scope)
  and T5 stops the window from composing it from a literal.
- V-payload (1): the Dashboard greeting (`dashboard.greeting` is a payload field of the surface twin of `status`).

**Gaps (2 rows, 2 distinct findings, one of them counted before):**

### C8. The update check exists only while the window is open
- Audit: A §1.3 `app_update` ("A console never checks for a newer version"), J17, §3b Sidebar "Discjockey 1.3 is available".
  Severity: **Important**.
- §5.2 maps `app_update()` to `app info` as a read. The engine's `_update.status()` is "the last answer of the update check, never the
  network", and the check runs only in the window's `hub-update-check` thread (start, then hourly, GitHub once a day). With the window
  closed the cache is as old as the last window session, so `app info` would say `unknown` or an old version. An agent cannot
  learn "a newer version exists", which the window shows in the sidebar and in Settings › About.
- Fix: `app info [--check]` where `--check` runs `Checker.check()` (network, the same once-a-day cap) and says so; state in §5.3 that `app info`
  also prints the cached answer's age (`as_of`).

### C1 (repeated). App U27: the save question's payload is built in the window
- Audit: A U27 and J8, same defect as C1 (per-rename and per-file choices of the save question). Counted as a gap row here; the
  finding is listed once, under L.

---

## 4. `cli-audit-supplement-a.md` (SA)

Items: 28 UI files, each counted by its information rows, its decision bullets and its action bullets ("none" bullets are
not counted; a generic file that only shows its caller's data is one item): LibraryTable 36 · TrackDetails 30 · ListRow 1 ·
BatchCheckCards 16 · BatchCheckFoot 10 · WatchedFolderList 15 · UpgradeCards 18 · TrackHead 2 · ComparePlayer 3 · MiniPlayer 5 ·
PlayButton 1 · NowPlayingRow 8 · RowLead 1 · FilePlay 3 · DuplicateChoice 12 · DuplicateFoot 6 · DuplicateDetails 4 ·
CheckCards 5 · CheckFoot 6 · AiffCard 10 · AiffFoot 6 · TrackRow 1 · QualityBar 5 · ImportCard 8 · DropZone 7 · QualityBadge 4 ·
AwayTag 1 · ListLine 1, plus the 7 findings. Total 232.

**Answered (159):** the rows and decisions that §9.3 names by file or function (SA `TrackDetails`, `rowInTodo`/`inTodo`,
`footAction`, `aiffShown`, `aiffVariant`, `UpgradeCards`, `CheckCards`, `BatchCheckCards`, `CheckFoot`, `BatchCheckFoot`,
`DuplicateFoot`, `AiffCard`, `AiffFoot`, `ImportCard`, `WatchedFolderList`, `noFileNote`, `waitWords`, `notFoundTip`, `cutoffStat`,
`qualityWords`, `fileAwayWords`, `titleNote`, `placeLine`, `TrackHead` line, `RowLead`) and the rows a named command prints
(`library list` fields, `track show`, `check list`, `import status`, `folder list`); all 7 findings (words in the engine, `keep_file`,
`version add-file <track> <path>`, `in_todo`, `TrackRow` deleted, paths in every payload, `import run`/`import status`).

**By construction, verified (73):**
- V-view (49): selection, ⌘-click, hover, skeletons, scroll windowing, column widths and which optional columns show, the
  A/B and mini players, the foot's now-playing row and every play button (§9.1: audio playback and layout stay in the window; the
  files they play are `path` in the payloads and `open file` plays them), the duplicate card's "Goes to Superseded/" marking and the
  chosen radio (it is a pick, a view state until the foot acts), the drag highlight and busy spinner of the drop zone, the
  QualityBar shimmer and its percentages (the counts and words are payload fields), `pickable`, `sharesName`.
- V-payload (21): table cells that are payload fields only (`#`, artist, length, folder, subfolder, playlist badge with "+n", UPGRADE
  badge), the Current-file card (`format_line`, `playlists`, `added`, `path`), `hasFile`, the watched-folder name/path/count, `RowLead`'s
  service and away mark, `FilePlay`'s `online`, the Not-checked badge (`sound_checked`), `nowLabel`/`autoNotes` (both fields are in
  `track show`).
- V-words (3): the "Keys and clicks" help text (T5 moves it to `words.json`; a command's equivalent is `help`), the Source line's
  source-how words (`copy.ts`, moved by T5), the "Now playing" group label.

**Gaps (0).** Every information row, decision and action of these 28 files is either one the earlier audits already contain
(and §9.3 names) or view state. The one weakness seen is the one reported under C4 (library): `UpgradeCards` is named in §9.3's D8
row as a file, but only `ways[]` has named target fields, so the Edit row's dot tone and "3 ms apart" text, the card title/found
text and the NOW/NEW lines depend on the build plan naming `upgrade.edit {tone,text}`, `upgrade.title_text`, `upgrade.found_text`.

---

## 5. `cli-audit-supplement-b.md` (SB)

Items: 59 UI files (Sync, Setup, Settings, Playlists, Limits, Dashboard, shell, shared parts), each counted by its information
bullets, its decision bullets and its actions (one item per file; a generic file that only shows its caller's data is one item), plus the
6 "Notes for the CLI designer". AccountPanel 14 · RowPanel 13 · AddRow 9 · EndScreen 15 · SourceLadder 7 · SyncCard 9 · RunPanel 9 ·
the six Setup steps 3 each · PlanRows, PlanFolds, RunsPage, RunRow, SummaryStrip, YouTubeMusicPanel, FoldersPanel, CrateSwitches,
MusicMissing, SyncPart, RunList, TidyList, UpToDatePanel 3 each · KindStrip, ReadingCard, RiskScale, UsageChart 2 each · the other 29
files 1 each · notes 6. Total 176.

**Answered (148):** everything §9.3 names by file or function in its U/SB rows (`AccountPanel`/`accountModel`, `SourceLadder`/`ladderModel`,
`RowPanel`, `YouTubeMusicPanel`, `KindStrip`, `RunPanel`, `PlanRows`, `PlanFolds`, `WhyMark`, `NextDot`, `WaitingAnswersNote`, `DayBar`/`dayBarModel`,
`EndScreen`/`endModel`, `UpToDatePanel`, `RunRow`, `RunsPage`, `SyncCard`, `StepBar`, `SyncPart`/`activity.ts`, `RunList`, `results.ts`,
`Step*`, `StepFooter`, `SummaryStrip`, `summaryStripModel`, `qualityBarModel`, `UsageChart`, `RiskScale`, `CrateSwitches`/`cratesModel`, `FoldersPanel`,
`MusicMissing`, `StepMusic`, `ToastHost`, `WriteButton`, `ConfirmHost`), the commands of §5.2 for every action (`login …`, `tools …`, `playlist …`,
`settings …`, `limits …`, `run list|show`, `sync plan|run|never|again`, `setup …`), and the deletions (`PageStub`, `SectionLabel`).
All 6 notes: plan in `plan.json`, account and settings state in `login list`/`settings show`/`tools status`/`setup status`, words in the
catalogue, duplicated rules (§9.3 U13, U14, U18, ladder), the run's report as `run show`.

**By construction, verified (26):**
- V-view (17): AddRow's `bannerSaysIt`, EndScreen's 500 ms retry, SourceLadder's click handler, ReadingCard's bar fraction, ShareStrip
  (generic), UpToDatePanel's reply-dropping and links, PlanFolds' fold-appears rule, RunsPage's month grouping and links, RunRow's click,
  RiskScale's draft, SummaryStrip's links, SyncPart's link, RunList's segment filter and Fix link, ErrorBoundary, Spinner, NotFound.
- V-words (5): AccountPanel's compact "what it gives" lines and risk notes (static; T5 moves them to `words.json`, the agent guide §14.2
  says the account-risk rule), RowPanel's before/after update words (`words.py`), LinkGuide and `linkGuideModel` (static help).
- V-payload (3): AccountPanel's gain arithmetic (`library {lossless, account, free}` are in `login list`), the Reports count
  (`run list` `total`), ServiceMark (the `service` field).
- V-rule (1): EndScreen's "Sync the rest ->" (`syncRest`: stopped with `queued > 0`): §9.1 (a) moves it and the envelope's `next` carries it;
  the function name is not in §9.3.

**Gaps (2 rows, 1 new finding):**

### C1 (repeated). SB TidyList actions
- `TidyList` serves the save question (ticks, rename rows) and Tidy up; its ticks are "window-only `Set<file_id>`" and the save question's
  payload `{choice, renames, moves}` is built in the window. Same defect as C1 (per-rename and per-file choices). Counted as a gap row here.

### C9. Two rules for "which zone is this limit in" survive
- Audit: SB UsageChart ("the engine also has `assessment(service, limit)` … slightly different tops 40/60/80/100"), App U23, U24. Severity: **Minor**.
- `accounts.py` has `ZONE_TOPS` (zones for the slider and the day colours: careful ≤ 40, normal ≤ 60, faster ≤ 79, fast ≤ 100) and
  `ASSESSMENT_TOPS` (the verdict word: 80 for "fast"). §9.3 moves `zoneIndex`/`riskOf` into the engine and §5.2 prints `zones[]`, `zone` per day,
  `assessment` and the `suggestion`, but it does not say the two tables become one. A person who sets 79 sees "fast" on the scale and the
  verdict at the same moment "faster" or the reverse; an agent that reads both sees two answers to one question (and the user's account-risk
  decision rides on it).
- Fix: §9.3 U23 states one table: `zones(service)` is the only source, `assessment` is derived from it (the `level` of the zone that holds the
  limit), and a test pins that `assessment(s, n).label == zone_of(s, n).name` for every n in 1..500.

---

## 6. `cli-audit-supplement-c.md` (SC)

Items: 37 Library screen states (25 Data, 12 View) + the 2 "surprises" (`file_missing` only through `track()`; no paging). Total 39.

**Answered (27):** the 25 Data states, each by a named read: `track show` (`quality_word`, `cutoff_text`, `source_how`, `playlists`, `added`, `path`,
`file_state`, `upgrade` block), `library list` (`rows`, `empty` with `no_match`/`empty_library`/`never_read`, `chips`, `summary`, `songs`, `read_at`,
`--sort -quality`, `--filter`, `--search`), `library collections`, `track spectrum`; surprise 1 (`file_state` computed once in the surface, one stat
per file, §8.3 names this surprise and closes it, §5.2 `file_missing` per row); surprise 2 (`--limit` default 200, `--offset`, `total`,
`next_offset`, §4.2).

**By construction, verified (12):** the 12 View states: `library-context-menu`, `library-big` (windowing; its data and its paging are the rows
above), `library-inspector-1100`, `library-pick-opens`, `library-details-hidden` and `-1100`, `library-inspector-empty`,
`library-first-open-old-prefs`, `library-first-open-hidden`, `library-closed-1280` and `-1100` (player), `library-long-titles-1100`. V-view
for all: each is an open panel, a stored preference, a width, a menu or the player (§9.1 stays list: L D16, D17, D18, D27, D35, D37). What
each shows is a `track show` or `library list` field the other states already use, and `help` lists the commands the menu stands for
(`open file`, `open url`, `todo list`).

**Gaps (0).**

---

## 7. Findings index

| # | Audit file · row | Severity | One line |
|---|---|---|---|
| C1 | library D32 (also app U27, SB TidyList) | Important | The save question's per-rename and per-file choices have no command form (`--no-rename` is all or nothing) |
| C2 | library §5 discoverability | Minor | The design never says whether printed paths are absolute |
| C3 | library §3b header "Make AIFF…" | Minor | `aiffHeader` (the view's Make AIFF… / Resume · k left button) is in no §9.3 row; the listing has no `actions[]` |
| C4 | library §0 finding 4 | Important | Nothing fails when a window model computes a count, tone, order or visibility from payload fields (T3/T4/T5 pass); add a `derive` checker |
| C5 | todo `UpgradeFlow.way`, §1.2 | Minor | `upgrade apply` without `--way`, and `--all --way new-track`, are unspecified |
| C6 | todo J10 `not_lossless.md` | Minor | The buy list file and `buy_links` have no command or path in the design |
| C7 | todo J11 stage B step 9b | Important | §15 uses `rekordbox status` "modified time", which §12 removes and no section defines |
| C8 | app `app_update` (J17) | Important | The update check runs only in the window; `app info` cannot ask for it |
| C9 | SB UsageChart / app U23 | Minor | `ZONE_TOPS` and `ASSESSMENT_TOPS` stay two tables (79 vs 80) |

Critical: none (no information or action is wholly out of the agent's reach). C1 (rule 3), C7 and C8 (rule 1) are partial reaches; C4 is a hole in the guarantee for future rows, not a missing row today.

---

## 8. Tally

| audit file | items checked | answered | by construction verified | gaps |
|---|---|---|---|---|
| cli-audit-library.md | 214 | 180 | 30 | 4 |
| cli-audit-todo.md | 230 | 213 | 14 | 3 |
| cli-audit-app.md | 271 | 256 | 13 | 2 |
| cli-audit-supplement-a.md | 232 | 159 | 73 | 0 |
| cli-audit-supplement-b.md | 176 | 148 | 26 | 2 |
| cli-audit-supplement-c.md | 39 | 27 | 12 | 0 |
| **total** | **1162** | **983** | **168** | **11** |

Gap rows 11 = 9 distinct findings (C1 is counted in library, app and supplement-b; C2–C9 once). By severity: Critical 0, Important 4
(C1, C4, C7, C8), Minor 5 (C2, C3, C5, C6, C9).
