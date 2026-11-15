# Issue 39: adversarial review of the agent CLI design

Status: review, 2026-11-15. Reviews `docs/2026-11-14-agent-cli-design.md` (cited as §n). The coverage review
(`docs/2026-11-14-agent-cli-design-review-coverage.md`, findings C1–C9) is not repeated here; where a finding here
touches one of those, it says so. Claims about the code were checked by grep against `discjockey/` and `hub-ui/src/`
(file:line given where it matters).

Findings are numbered `R<n>`, grouped by the area attacked. Each gives a severity (Critical: a hard rule or invariant
broken, or it can't be built as written; Important; Minor), the design section, the scenario, and a stated fix or
"needs a decision".

---

## 1. Safety

### R1. Qobuz protection only holds inside one process; an agent's loop of single commands bypasses it
- Severity: **Critical** (Qobuz protection). Sections: §9.2 (`_qobuz_streak` "stays"), §5.2 `version search` / `use`,
  §6.1.
- The pause after 3 failures is an in-memory streak (`pacing.Budget.failures_in_a_row` / `stopped`, carried between
  jobs only by `HubApi._qobuz_streak` and `_account_streaks`, api.py:327, 1326–1348). The pacing (20–60 s between
  Qobuz downloads, a 2–5 min break every 10–15, 2–5 s before a search) lives in a `pacing.Pacer` made per run. In the
  design every terminal write is its own worker process. Scenario: an agent works through To-do with
  `version use <t> cand:qobuz:…` for 50 tracks, one command each. Every worker starts with a fresh streak and a fresh
  Pacer: no pause between downloads, no break, and three failures in a row never pause Qobuz, because the count
  starts again at 0 each time. Only the daily limit still holds (it is in `usage`). The same goes for `version search`
  (kind R, no lock, no job), which an agent can run in a tight loop: one Qobuz search per call with no pacing across
  calls. A person clicking in the window is slow enough; an agent is not.
- Fix: make the protection state shared across processes. Store it per service in library.db `usage`:
  `last_request_at`, `since_break`, `next_break`, `failures_in_a_row`, `download_failed_in_row` and `paused`, with
  today's reset rules (a success ends the streak; `paused` ends when the next sync starts, which is the hub-session
  rule made durable). Add one cross-process pacer, `pacing.SharedPacer`, that waits against `last_request_at` under
  a short `<support>/qobuz.pace` flock (searches take no library lock, so the pacer needs its own). Every Qobuz and
  account request from any command or job goes through it: `version search`, `preview`, `use`, `use --link`, the
  sync and Auto-upgrade. `version …` refuses (`busy`, `sync_running`) while a sync of *any* process runs, looked up
  in the registry rather than through `_no_sync_running`'s in-process check. Tests: three processes, each failing
  once in turn, pause Qobuz for all of them; two back-to-back `version use` workers wait 20–60 s between their Qobuz
  downloads.

### R2. In a sandbox, a login makes downloads that the real daily limit never sees
- Severity: **Critical** (Qobuz protection, account risk). Section: §10.3 ("Qobuz protection holds trivially").
- `usage` (daily counts, carry-over, signals) is a table in each music folder's `library.db`. A sandbox has its own
  clone, and the Qobuz login is a file in the sandbox's support folder (`streamrip/config.toml`), so `login qobuz …
  --password-stdin` works inside a sandbox. Rehearsing setup is a natural thing for an agent to do. Scenario: the agent
  logs in inside the sandbox, rehearses `sync run`, and 60 Qobuz downloads count only in the sandbox. The real
  library's sync downloads another 60 the same day, so the account sees 120 on one day. The same applies to
  YouTube Premium and SoundCloud Go+ through `login use` (the browser cookies are the user's real account).
- Fix: in a sandbox, every login write (`login qobuz`, `login use`, `login sign-in` for an account service) is
  `refused`, `reason: "sandbox_no_accounts"`. `Settings` loaded in a sandbox force `qobuz_skipped` and no
  `accounts`, so a login file copied in by hand does nothing either. Anonymous reads, the Spotify read login (reads
  have no limit) and free streams stay. Test: a sandbox with a planted `streamrip/config.toml` downloads nothing from
  Qobuz.

### R3. `sandbox remove` can delete the real library
- Severity: **Critical** (never delete a music file). Section: §10.3.
- The rule deletes a folder that "holds the marker and is neither the real music folder, a watched folder, nor
  inside one". Two holes:
  - `sandbox create` doesn't say the folder must be new or empty, so the marker can land in a folder that *contains*
    real music. Scenario: `sandbox create ~/Music` on a library at `~/Music/Discjockey`, then
    `sandbox remove ~/Music --yes`. `~/Music` is not the music folder, not a watched folder and not inside one, so
    the whole library is deleted.
  - "The real music folder" is unclear when `DISCJOCKEY_SUPPORT` or `--sandbox` changes the support folder: the
    check may compare against the sandbox's own folder.
- Fix:
  - `sandbox create` accepts only a folder that doesn't exist or is empty, on a path not inside the music folder, a
    watched folder, rekordbox's folder or the support folder.
  - `sandbox remove` resolves the real folders from the default support folder, whatever the environment says. It
    refuses (`protected`) when the folder equals, contains or is inside the real music folder, any watched folder,
    rekordbox's folder, the home folder or a volume root.
  - It deletes only what `sandbox create` made (`music/`, `support/`, `rekordbox/`, the marker) and refuses when
    anything else is in the folder.
  - T9 gains the `~/Music` scenario.

### R4. Reads of rekordbox's library while another process writes it can be torn
- Severity: **Important**. Sections: §1.2 principle 2 ("Read commands … take no lock … work while the window runs"),
  §6.4.
- `master.connect` opens master.db `mode=ro&immutable=1` (no locks) whenever rekordbox is closed
  (rekordbox/master.py:9–11, 133). Discjockey writes master.db only while rekordbox is closed, so its writes and the
  immutable reads happen at the same time. Today the hub avoids this in its own process: `_rekordbox_status` never
  opens master.db while a write job of this hub runs (api.py:665–692). Across processes nothing does. Scenario: a
  terminal `upgrade apply --all` repoints tracks while the window or an agent runs `todo list`, `track show`,
  `check list`, `rekordbox match` or `status --ready`. The reader sees a half-written database: SQLite reports
  "malformed", or the answer is wrong.
- Fix: readers of master.db try `rekordbox.lock` with `LOCK_SH | LOCK_NB`. While a writer holds it, a reader never
  opens master.db and answers its rekordbox part as `writing` (the last cached answer, when there is one, with
  `as_of`). `writer_lock` retries for up to 2 s, so a reader's brief shared hold never turns a writer `Busy`. Test: a
  reader during a (fake) write never opens immutable.

### R5. Which lock a job takes is not decided per job kind
- Severity: **Important**. Sections: §6.1 ("The worker takes the library lock"), §5.2 kinds J / B.
- Today the jobs differ:
  - Sign-ins run beside write jobs without the library lock, for up to minutes (jobs.py:453).
  - The playlist read (`start_refresh`) takes no lock; its scan takes it only when the lock is free (`scan_lock`).
  - Settings saves take the library lock briefly, or only an in-process mutex while no music folder is bound
    (`Jobs.lock is None`).
  - `tools update` touches only the support folder.
- §6.1 gives every job the library lock. Built that way, a 10-minute `login sign-in` blocks every write in the
  window ("Terminal is running"), and `sync read` waits for an import, which the window doesn't do. Built the other
  way, there is no rule: `settings.json` and `config.json` get read-change-write from two processes with no shared
  lock (the window before Setup has a music folder; two windows bound to different music folders; `tools update`
  from the window and the Terminal).
- Fix:
  - Each catalogue entry declares `locks`, a subset of {`library`, `support`, `rekordbox`}.
  - A new `<support>/.support.lock` (flock, waits ≤ 2 s, then `busy`) guards `settings.json`, `config.json`,
    `tools/` and the login files.
  - Sign-in jobs take only `support`, for the moment of their save.
  - `sync read` takes no lock for the network part, the library lock only for its scan (as `scan_lock` does), and
    stores the read in one library.db transaction.
  - T10 pins the table.

### R6. Telling a dead job from a live one by its pid is unsafe
- Severity: **Important**. Sections: §6.1 (`pid`, `lost`), §6.2 (`job stop --now` "sends SIGINT twice").
- After a crash or a reboot, a `running` job's pid can belong to another process (pids restart low after a boot).
  Then `status` and `job list` show a phantom job forever, `job wait` never returns `lost`, `current` resolves to
  it, and `job stop --now` sends SIGINT to an unrelated process of the user's.
- Fix:
  - The worker (and the window, for its in-process jobs) holds an flock on `jobs/<id>/alive` for the job's whole
    life. A job is `lost` when its state says `running` and that lock is free.
  - `--now` signals only while the alive lock is held *and* the pid's start time matches the one stored in
    `state.json`.
  - The second SIGINT goes at least `CTRL_C_REPEAT_S` (1.0 s) after the first, or the worker ignores it as a
    repeat.
  - The worker runs the job on its main thread, the only thread that gets signals and where `deferred_interrupt`
    works.

### R7. The job registry sits in the wrong folder
- Severity: **Important**. Section: §6.1 (`<music>/.discjockey/jobs/`).
- Jobs exist that have no music folder: `tools update` ("no music folder", §5.2), logins and `setup music` during
  Setup. The registry also disappears with an unplugged drive, and `sandbox create --from real` clones the real
  `jobs/` into the sandbox (phantom running jobs there).
- Fix: put the registry in `<support>/jobs/`. Each job records its music root (or null), and `job list` filters by
  the current root unless `--all`. `sandbox create` never copies `jobs/`, `plans/`, `.lock` or `-wal`/`-shm`.

### R8. The sandbox guard is not at the lowest write layer, and roots can point out of it
- Severity: **Important**. Section: §10.3 ("No write escapes").
- The listed guard points (`run_op`, `move_files`, `move_path`, `open_write`, the tools updater, settings and config
  writes) miss real writers:
  - `rekordbox/backup.py` `_copy_checked`, which is how `rekordbox restore` writes master.db, not through
    `open_write`;
  - `rekordbox/write.replace_bytes` (the ANLZ files);
  - `playlists_file.save`;
  - the staging copies in `upgrades.py`;
  - reports, the operations log and library.db itself.
- There are also two ways out at the root level:
  - Inside a sandbox, `setup music /Users/you/Music/Discjockey` writes a `config.json` that is inside the sandbox
    but names the real folder; from then on the "sandbox" reads the real library, and its writes rely only on the
    incomplete list. `folder add <real folder>` does the same for watched folders.
  - A worker that resolves its folders from its own environment, not from the job, can run a sandbox job on the
    real library.
- Fix: guard at the roots, not at a list of write calls.
  - In a sandbox, `SupportPaths`, `Paths` and `rekordbox.locate` refuse any root outside the sandbox (a
    `config.json` naming an outside folder is `outside_sandbox` at resolve time).
  - `setup music` and `folder add` refuse outside paths.
  - The move layer refuses targets outside the sandbox, so files of watched folders outside are read-only.
  - The worker takes every root (`music`, `support`, `rekordbox`, `sandbox`) from `state.json`, never from its
    environment.
  - T9 keeps its "no byte outside changed" run over every write command.

### R9. Cloning the real library while it is in use gives a torn copy
- Severity: **Important**. Section: §10.3 `sandbox create --from real`.
- `clonefile` of `.discjockey/` while the window's 60 s rescan or a terminal job writes `library.db` (WAL mode,
  db.py:245) copies the main file and the WAL at different moments. The copy can also take the real library's open
  `pending` journal along, and the sandbox's first writer then "recovers" steps that name the real library's paths.
- Fix:
  - Take the library lock for the clone (`--wait-busy` applies).
  - Copy library.db with SQLite's backup API, not `clonefile`.
  - Refuse (`refused`, `pending_steps`, `next: doctor`) while `pending` holds steps.
  - The audio clones stay `clonefile`.

### R10. `--rekordbox copy` doesn't rehearse rekordbox
- Severity: **Important**. Sections: §10.3, §15 ("rehearsal … in `--sandbox` with `--rekordbox copy`").
- The copied master.db and ANLZ files name the real files' paths, while the sandbox's files sit under
  `<dir>/music/…`. `rekordbox.entries_for` (a path index) finds no track for any sandbox file, so Same track, Convert
  and Rename rehearse "not in rekordbox" and none of the repoint runs. Copying while rekordbox runs (WAL open)
  is only "must", with no refusal behind it.
- Fix:
  - `sandbox create --rekordbox copy` refuses while rekordbox runs (`needs_person`, `step:quit_rekordbox`).
  - After the copy it repoints, inside the copy only, every track whose file lies under the cloned music or watched
    folders to its clone (`write.Writer` path change and `anlz.splice_ppth` in the copied share folder).
  - `sandbox info` lists the tracks it couldn't map.

### R11. The window's ⌘A sends a listing, so it acts on rows the person never saw
- Severity: **Important**. Section: §7.3 ("the window's ⌘A, which sends the listing instead of the ids").
- The listing is evaluated when the job runs. Scenario: the person selects all 40 rows of a playlist and presses
  Convert. Meanwhile the 60 s rescan or an import added 8 files to that view. Today the window sends the 40 ids it
  showed. With a listing, 48 files are converted and rekordbox is written for 8 the person never saw. That undoes
  the protection `_shown` / `rev` exists for.
- Fix: the window keeps sending ids. `present.select(listing)` gives the window the ids for its ⌘A (one function,
  so still "the same answer by construction"); a test pins window ⌘A ids == `select(listing)` on the same payload.
  The CLI's `--rows` binds to what was seen through `--dry-run` → `--plan` (§7.1), so it needs no change.

### R12. Dry runs and reads: three contradictions with "writes nothing"
- Severity: **Minor**. Sections: §7.1, §13 T9.
- A dry run "writes nothing", yet it "stores the plan in `.discjockey/plans/`", so T9 ("a dry run writes a byte")
  fails by construction.
- Reads open `library.db` read-write in WAL mode (db.py:232–245); closing the last connection checkpoints and
  removes `-wal`/`-shm`.
- `sync run --dry-run` and `sync plan` would have to scan. Today `prepare(dry_run=True)` scans and stores the scan
  when it gets the lock, and the hub's preview without the lock "plans on the records as the last scan".
- Fix:
  - A dry run writes exactly one file, `.discjockey/plans/<id>.json`, and T9 excludes that path by name.
  - Read paths open library.db with `?mode=ro`.
  - A dry run never stores a scan: it plans on the last one, says when in `as_of.scanned_at`, and puts
    `library scan` in `next` when files changed since.

### R13. Kind R "never writes" is not true for four reads
- Severity: **Minor**. Section: §5.2 kinds.
- `version search` (candidate cache, candidates.py:78–79), `version preview` (the clip), `track spectrum`
  (hub/spectrum.py:99) and cover reads (hub/media.py:221) write caches.
- Fix: define R as "writes nothing but caches under `<support>/cache`", and let T9 allow that folder.

---

## 2. Feasibility in this code base

### R14. A persisted `plan.json` can't hold today's plan object, and nothing says who keeps it fresh
- Severity: **Important**. Sections: §9.2 (`PreviewStore.prep` → `.discjockey/plan.json`, "re-planned without network
  when library state changes"), §6.4 "The stored plan".
- What is in `run.Prepared` today:
  - `state`: the whole planned library snapshot.
  - `settings`, `plan`, `log`.
  - `fetched`: `SourceTrack`s whose secret SoundCloud link token and record label are `InitVar`s, kept out of
    `asdict` on purpose (models.py:79–100).
- Problems with storing it:
  - Written as JSON, it either drops the secret, so a run from it can't fetch private tracks, or writes a secret to
    disk that today never leaves memory.
  - Today's freshness rules are in memory and in one process: `PreviewStore.ready` drops a plan of an older
    generation, `replanned_work` re-plans after a write. Across processes, every writer in every process would
    have to re-plan and rewrite `plan.json` after each change, in the right order.
- Fix: store the **read**, not the plan.
  - The `playlist_reads` / `playlist_tracks` tables already exist (db.py:136). Widen them to every `SourceTrack`
    fact the planner needs (isrc, album, image, link, streamable, account_only, never the secret), plus the read's
    problem, `unread_folders` / `unread_members` and the infos.
  - Derive the plan on demand: `run.replan` is `planner.plan(fetched, load_state, settings)`, pure. Cache it per
    (read id, generation, settings hash).
  - `plan_id` is the hash of its action keys.
  - No writer needs a re-plan hook. `sync run` reads the playlists again as today (jobs.py:701–757), so secrets stay
    in memory.

### R15. `surface/` as free functions can't carry what the hub needs, and the simpler shape is the hub itself
- Severity: **Important** (can't be built as T3 states). Sections: §8.1, §13 T3, §16 group 2.
- What `HubApi`'s reads use besides the bound paths:
  - the services that tests replace (`Services`: rekordbox place and running, clock, fetch, `mounted`; 95 uses of
    `self._svc`);
  - caches the window depends on for speed: `_rb_cache` (one master.db open per change), `_cdj_cache`, `_tag_cache`
    and the cover cache.
- "One function per bridge method, same arguments, gathers what it needs from disk", together with T3 ("each
  `HubApi` read method body is a call to its `surface` twin plus the declared transform"), leaves no place for those.
  The window would then open master.db and read tags on every To-do and details read, or T3 fails.
- `HubApi(support, events=None, media=None)` already builds without a window (api.py:292–330). Once §9.2 moves its
  session state to disk (which the design does anyway), a headless `HubApi` *is* the one surface: the CLI calls the
  same method, so the payloads are equal by construction with no extraction.
- Fix:
  - The CLI adapter is built on a headless `HubApi`. The bridge's `{ok, kind, message}` maps to the envelope
    through `outcomes`, and payloads carry paths beside URLs.
  - T3 becomes "a CLI handler only calls `HubApi` methods and renders".
  - Splitting `api.py` into modules is an optional refactor, never a prerequisite.
  - If the extraction is kept anyway, `surface` is an object `Surface(paths, services, caches)` held by `HubApi`,
    and T3 allows `self._surface.<name>(…)` plus the transform.

### R16. T4's Python half has no scenario libraries to run on
- Severity: **Important** (can't be built as written). Sections: §8.3, §13 T4.
- The fake backend is "an in-memory Discjockey state shaped like the contract. Reads are computed from it"
  (hub-ui/src/lib/bridge/fake/data.ts:1), in TypeScript. No Python library sits behind a fake scenario, so "for every
  declared read of every scenario's library, the command twin … payloads are equal" has nothing to run against.
- Fix:
  - Keep the vitest half (every `shots.json` entry declares `reads` or a `view` reason).
  - The bridge-vs-command parity runs on the Python hub fixtures (`tests/hub_helpers.py`, `test_hub_fixture.py`);
    with R15 it is true by construction anyway.
  - Validate every fake payload against the generated JSON Schema (T6), so a field the engine gains shows up as a
    failure in the fake.

### R17. The window's registry writes sit in the engine's hot path
- Severity: **Minor**. Section: §6.1 (`events.jsonl`: "every event").
- `Jobs._job_emit` runs synchronously in the engine's thread. A download sends a `Progress` per chunk, and a
  multi-hour sync makes a large `events.jsonl` and slows the work.
- Fix:
  - One writer thread per job.
  - Coalesce with today's `_same_slot` rule (the latest `Progress` / `Waiting` per slot, flushed at most twice a
    second).
  - `state.json` through `write_json_atomic` at most once a second.
  - Cap `events.jsonl` (keep the head and tail, with a `truncated` event between them).

### R18. A stop file doesn't wake a sleeping token
- Severity: **Minor**. Section: §6.3.
- `CancelToken.sleep` is `Event.wait(seconds)` and `check()` reads the event directly (events.py:34–41). Spotify's
  rate-limit waits sleep through the token (sources/spotify.py:248–309, possibly minutes), so a stop file is noticed
  only when the sleep ends.
- Fix: `sleep` waits in steps of ≤ 0.5 s checking `cancelled`, and `check()` uses `cancelled`. Test: a 60 s token
  sleep ends within 1 s of the stop file.

### R19. Checking `window_open` can steal the window's lock
- Severity: **Minor**. Section: §2.3 `where.window_open`.
- The only signal is `.window.lock`, an exclusive flock (hub/window_port.py:70–86), and two windows may run.
  Probing it means taking it: a window that starts during the probe thinks it isn't first and picks an unkept port,
  which loses its saved settings (they are kept per origin).
- Fix: each window writes `<support>/windows/<pid>.json` (pid and start time) while open; the probe reads those
  files and never takes the lock. `window_open` is a count.

---

## 3. The agent's view

### R20. An agent's first probe, the bare binary, opens the window and blocks
- Severity: **Important**. Sections: §2.1, §2.3 step 1 ("no TTY and no args: still the window").
- An agent with no prior knowledge runs `/Applications/Discjockey.app/Contents/MacOS/Discjockey` first. The window
  opens on the user's screen and the tool call hangs until the window closes or the call times out.
- Fix: open the window with no arguments only when LaunchServices started the process (parent pid 1, or a `-psn_`
  argument). From a shell (parent is not launchd), no arguments prints the short help with "AI agents: run
  `<path> help agents` first" and exits 0; `app open` opens the window from a shell. Test pins both.

### R21. Long calls run past an agent's tool timeout, and a killed `--json` client leaves nothing behind
- Severity: **Important**. Sections: §6.2 (the default is "follow to the end"; the guide says `--wait 120`, then
  `job wait --timeout 300`), §15 (`--wait 600` in nine steps).
- Common agent shells kill a call after about 2 minutes (Claude Code's default is 120 s, at most 600 s). A call
  that runs longer is killed, and in `--json` mode the killed client has printed nothing on stdout, so no job id.
  The agent doesn't know a job is running and may start it again (`busy`, or a second run once the first ends).
  `--detach` answers `ok` before the worker holds the lock, so a later `busy` looks like a broken job.
- Fix:
  - With stdout not a TTY and neither `--wait` nor `--detach`, the default is `--wait 90`.
  - The first stderr line of every job command is "Job job:… started (follow: `<path> job follow job:…`)".
  - `--detach` returns once the worker reports `running` or ends (`busy` included, within `--wait-busy` + 5 s).
  - The guide and §15 use `--wait 90` and `job wait --timeout 90`.

### R22. A job that waits for a person says only "running"
- Severity: **Important**. Sections: §4.1 (`person_steps` only for `needs_person`), §10.1 (`step:sign_in`,
  `step:keychain` with `then: job wait`).
- `login sign-in` and `login use` wait inside the job for the person: the browser, the macOS Keychain question.
  An agent following §6.2 sees `running` (exit 8) each time and keeps waiting; nobody tells the user to act until the
  sign-in times out after 10 minutes.
- Fix: the job's `state.json` holds live `person_steps`, set by the worker when the browser opens or a Keychain
  prompt is due. `running` envelopes, `job show` and `status` carry them, and the guide says: on `running` with
  `person_steps`, tell the user now.

### R23. Commands from a shell get the terminal app's macOS privacy rights, not Discjockey's
- Severity: **Important**. Sections: §10.1 (`step:full_disk_access`: "Turn on Discjockey …"), §4.3 reasons.
- macOS charges a process started from Terminal, iTerm or an agent's shell (and its detached worker) to that
  terminal app. A music folder on an external drive, or a watched folder in Documents, Downloads or Desktop (a common
  place for crates), raises a prompt naming the terminal app, or fails with `PermissionError` and no reason in §4.3.
  Safari's cookies need Full Disk Access *for the terminal app*, so the step's words send the user to the wrong
  switch.
- Fix:
  - `PermissionError` on a root, a watched folder or a browser's cookie file maps to `needs_person` with reason
    `folder_access` or `full_disk_access`.
  - The words name the app the command runs in (taken from the client's `__CFBundleIdentifier` or `TERM_PROGRAM`,
    else "the app you run this command in").
  - `doctor` checks that every root can be read.

### R24. Every normal sync would end `partial`
- Severity: **Important**. Sections: §4.3 (`partial` = "some items were skipped or failed"), §4.4.
- Almost every sync has songs not found ("next try in 3 days"), songs left for later by `--limit`, and songs that
  stay lossy. If those count as `skipped`, every sync exits 6, and an agent reports "half done" after a normal run.
- Fix: each catalogue entry names which per-item states make it `partial`. For `sync run`: only `failed` items
  (network, service or crash errors per track). Not found, queued, left out and not lossless are `ok`, with their
  counts in `data`.

### R25. No rule for which outcome wins when several apply
- Severity: **Minor**. Section: §4.3.
- A batch can have failed items, be stopped, and meet rekordbox opening, all in one run. Exit 4, 5 or 6?
- Fix: one order, in `present/outcomes.py` and pinned by T8: `bad_args` > `busy` > `refused` > `needs_person` >
  `stopped` > `failed` (nothing done) > `partial` > `ok`. The other facts stay visible in `data.results`.

### R26. "Undo yesterday's work" promises more than the commands can do
- Severity: **Important**. Sections: §7.4 last row, §11 "History and recovery".
- `history --since yesterday` lists batches, which can be undone. Much of a day's work can't:
  - downloads;
  - playlist edits (not logged anywhere: `playlists_file.save` writes no log);
  - hides, never-downloads, settings and limits;
  - `duplicate keep` (no undo);
  - tracks after `check done`.
- An agent that undoes the batches and reports "undone" misleads the user. `--since` has no defined format either.
- Fix:
  - Every `history` entry carries `undo`: the command that undoes it, or `null` with `cant_text`.
  - Playlist edits and setting changes are written to the operations log (`ops.log_operation`) with the old value,
    so they appear in `history` with the opposite command as their undo.
  - `--since` takes an ISO date or time, `today`, `yesterday`, `<n>d` or `<n>h`.

### R27. Some reads can take minutes, and reads have no job form
- Severity: **Important**. Sections: §5.2 kind R, §7.1 ("the dry run reads missing facts in memory").
- Examples:
  - `aiff convert --all --dry-run` on a library whose rows predate schema 8 probes every file without facts, and
    because a dry run stores nothing, it probes them again on every call.
  - `rekordbox match` and `status --ready` stat every rekordbox track's file, possibly on slow drives.
  - `version search` and `playlist check` wait on the network.
- All run inside the client, past a tool timeout, with no job id to pick up again.
- Fix:
  - A read the catalogue marks `slow` runs as a read job (registry, no lock) under the same `--wait` rules as
    writes (R21).
  - Missing facts become an explicit write, `library facts` (today's `importer.fill_facts`, a job with the lock). A
    dry run that meets more than 50 files without facts answers `refused`, `facts_missing`, with
    `next: library facts`.

### R28. `track find` with no hit doesn't say why
- Severity: **Minor**. Section: §3 "Finding ids".
- A song the user added to a playlist after the last read is in no record, so "why didn't X download?" finds nothing.
- Fix: no hit answers `ok` with `total: 0`, `as_of.read_at`, and `next: sync read` when the read is older than the
  playlists' last change or a day.

### R29. "Nothing to do" as a refusal breaks commands that are run again
- Severity: **Minor**. Section: §4.3 (`nothing_to_do` under `refused`, exit 7).
- `upgrade apply --all` run a second time, or `check done --all` with nothing open, exits 7. Scripts with `set -e`
  and agents then treat a finished job as a refusal.
- Fix: nothing to do is `ok` with `data.total: 0` and a `message`.

---

## 4. The person's view

The cutoff, the verdict and the spectrum are visible to a person: the verdict line, the cutoff sentence, a text sketch,
and `--png` / `--open` (§4.5). That holds. Three gaps:

### R30. "Every shown field is printed" makes a field dump, not a readable answer
- Severity: **Minor**. Sections: §4.2, §13 T7.
- T7 forces every `shown` field into the text. Nothing says how the text is laid out. A Sonnet builder meets T7
  most cheaply with `key: value` lines: `track show` would print `rev`, `file_id`, `cutoff_hz: 16000`, `generation`.
  A DJ can't read that.
- Fix:
  - Each schema's renderer declares a layout: a headline (the verdict or state sentence), sections with the
    window's headings, labels from the word catalogue, values as their words.
  - Ids, `rev` and raw numbers that have words appear only with `--verbose`.
  - T7 checks that the layout places every `shown` field, and a golden-text test per schema lets a reviewer see the
    page.

### R31. The 12-row spectrum sketch can't show the cutoff that matters
- Severity: **Minor**. Section: §4.5.
- 12 rows over 0–22 kHz is 1.8 kHz a row. "Weak" is a cutoff ≤ 17 kHz, so 16 and 17.5 kHz land in the same row.
- Fix: one row per kHz (22 rows), the cutoff row labelled with its number ("─ 16.0 kHz cutoff"), and the axis in kHz.

### R32. `app install-command` installs to a folder that isn't on the PATH
- Severity: **Minor**. Section: §2.1.
- `~/.local/bin` is not on macOS's default `PATH` for zsh. The person types `discjockey` and gets
  "command not found".
- Fix: the answer says whether the folder is on `PATH`; when it isn't, it adds a person step with the exact line for
  `~/.zprofile`.

---

## 5. Consistency

### R33. One package with two names
- Severity: **Minor**. Sections: §1.1, §4.3, §7.3 (`present/`, `present.select`) vs §8, §9 (`surface/`).
- Fix: one name throughout (R15 may make it `HubApi`).

### R34. Grammar breaks its own rules
- Severity: **Minor**. Sections: §2.2, §5.
- Breaks:
  - `run` is a noun (past syncs) and a verb (`sync run`, `tidy run`, `import run`).
  - `--limit` means "how many to download" on `sync run` and "how many rows" on lists (`0` = all there, invalid
    today for the sync).
  - Three-word verbs break `<noun> <verb>`: `library favourites add`, `folder crates show`, `sync scope on`.
  - The never-download switch is `sync never` / `sync again`, while hide is `track hide` / `unhide`.
  - `--wait` vs `job wait --timeout`.
  - `check done --batch aiff:<n>` is a fourth selection form beside §7.3's "exactly one of three".
  - `playlist edit` (§5.2) is missing from §5.1.
  - The bare noun means "the read verb", but `tidy`, `aiff` and `version` have none.
- Fix:
  - Rename the noun `run` to `report` (`report list`, `report show last`, `open report`).
  - Rename the sync's flag to `--how-many N`.
  - Allow `<noun> <verb> <object>` only for these three nouns, listed in the grammar.
  - Move the never-download switch to `track never` / `track download`.
  - Use `--wait` for `job wait` too.
  - List `--batch` as a fourth form in §7.3.
  - Add `playlist edit` to §5.1.
  - A bare noun without a read verb prints the noun's help.

### R35. Reason keys are scattered, and an expired plan has none
- Severity: **Minor**. Sections: §4.3, §6.2 (`window_job`), §7.1.
- Some reasons appear only in their own section (`window_job`, `still_running`, `outside_sandbox`); others exist
  nowhere: a stop for a job that isn't running, a `--plan` older than 24 h.
- Fix: §4.3's table is the closed list, generated from `present/outcomes.py` and printed by `help --json`. Add
  `not_running` (refused) and `plan_expired` (refused, `next`: the dry run again). An unknown plan id stays
  `bad_args`, `unknown_id`.

### R36. The schema tooling and the contract doc are left for the builder to decide
- Severity: **Important**. Sections: §4.1, §4.2, §8.1, §14.
- Open points:
  - JSON Schema, `types.ts` (54 KB, 150 types today) and the text field lists are all to come from `TypedDict`s.
    `TypedDict` carries no per-field `shown` flag, and no generator is named. Pydantic would be a new dependency.
  - Whether a field without the flag is shown is not said.
  - `docs/hub-bridge-contract.md` (150 KB, hand-kept, required by CLAUDE.md for every contract change) is not
    mentioned: it becomes a third copy of the shapes.
  - Window job ids change from integers (`itertools.count`, jobs.py:340) to `job:…` strings, which is a contract
    change missing from §16's list.
- Fix:
  - An in-repo generator over `typing.get_type_hints(include_extras=True)`, supporting a closed set of constructs
    (`Literal`, `NotRequired`, unions with `None`, lists, nested `TypedDict`s).
  - Every field is `Annotated[…, F(shown=…, doc=…)]`, and T6 fails on a field without it.
  - The contract doc becomes generated, or a pointer to the generated reference, in the same group.
  - Add string job ids to §16's contract changes.
  - The generator is its own group, before the extraction groups.

### R37. The word catalogue's template and emphasis formats are not defined
- Severity: **Minor**. Section: §8.2 ("named fields and plural forms").
- The window shows emphasised parts inside sentences (`<b>` in the setup steps and the limits cards; `parts[]` with
  `strong` in the check cards). Words with view-state numbers ("Convert 3 files") must be filled in TypeScript.
  Neither the template syntax nor the emphasis shape is defined, so Python and TypeScript would each invent one.
- Fix: one syntax (`{n}`, `{n|file|files}`, `**…**` for emphasis), rendered by one Python and one TypeScript
  function, pinned by a shared fixture file. Payload sentences with emphasis travel as `parts[] {text, strong}`.

### R38. `sync run --auto-upgrade-only` with the switch off has no stated answer
- Severity: **Minor**. Sections: §5.2, §15 C 4b.
- §15 C 4b assumes `auto_upgrade: null`. A builder could equally answer `refused`, `setting_off`.
- Fix: `ok`, `data.auto_upgrade: null`, `message` "Auto-upgrade is off, so nothing was moved."

### R39. Word fields are named in three styles
- Severity: **Minor**. Sections: §8.2, §9.3.
- Most fields end in `_text`, but there are also `quality_word` and `dim_why`. The renderer and T7 pair a fact with
  its words by name.
- Fix: `<fact>_text` everywhere (`quality_text`, `dim_text`).

---

## 6. Keeping it complete forever

Coverage finding C4 already covers numbers, tones and orders that a window model computes from payload fields.
Three more ways the window can gain something the CLI lacks while T1–T11 stay green:

### R40. T1 checks bridge method names, not their parameters
- Severity: **Important**. Section: §13 T1, T2.
- Scenario: the window gains a choice (a new `upgrade(ids, mode, keep_tags)` argument, a new key in `save_playlists`'
  `files`). The method is still in the catalogue and the command still parses, so T1 and T2 pass, and the agent can't
  make that choice (this is how C1 happened).
- Fix: each catalogue entry maps every parameter of the bridge method (and every key of a dict parameter, through its
  `TypedDict`) to a flag or positional. T1 compares `inspect.signature` and the parameter shapes with that map and
  fails on any unmapped one.

### R41. The words rule is static and easy to get around; a rendered check already exists
- Severity: **Important**. Sections: §8.2, §13 T5.
- A literal-finder misses visible text built from pieces: template strings, `key.replace('_', ' ')`, enum keys
  printed as words, SVG `<text>`, CSS `content:`, `alt=`. It also can't tell a visible literal from a key that looks
  like one. The `view:` reasons in `shots.json` are declared by whoever adds the shot, with nothing to check them.
  `hub-ui/scripts/strings.mjs` already collects every visible text and `aria-label` / `placeholder` / `title` per
  shot.
- Fix: add T5b to `npm run verify`. For every shot (`view` shots included), each visible string must be a
  `words.json` entry rendered with its fields, or a payload value of that shot's reads. Keep the static rule as the
  fast check.

### R42. A window action built from several bridge calls has no command
- Severity: **Important**. Sections: §8, §13.
- Today's "keep this file" sends N−1 jobs and works out the group id in TypeScript (L D10). §9.3 fixes that case. A new
  flow of the same kind (one button that runs `upgrade`, then `rekordbox_checked`) would pass T1–T5, because each
  call has its command; the agent would have to know the sequence.
- Fix: a rule-checker check `flows`: a user action (one event handler) calls at most one bridge write. Existing
  exceptions go in an allow file with their §9.3 row and are ratcheted to empty.

### R43. T7 tests a sample that leaves out optional fields
- Severity: **Minor**. Section: §13 T7.
- A field that is null in the sample is never rendered, so it is never checked.
- Fix: T7 uses a generated "every optional field set" sample per schema, as well as the real fixture outputs.

---

## 7. Scope and cost

### R44. Moving every static window word into the engine costs the most and adds least
- Severity: **Important**. **Needs a decision.** Sections: §8.2, §16 group 7.
- Words that carry data must come from the engine; the design is right there. Headings, button labels and static
  explanations carry no facts. Moving them all means one Sonnet group per page across 162 `.svelte` and 127 `.ts`
  files (§16 says "~60"), with screenshots compared each time and a ratchet. It is probably the largest single cost
  of the design.
- Options:
  - (a) **As designed:** the engine owns every word.
  - (b) **Split by kind of word.** Data-carrying words come from the engine, as designed. Static words stay in
    Svelte and are *extracted* at build time into `words.json` (generated, committed, checked by CI like
    `hub/static`), and `help glossary` prints them. The guard becomes: no visible string built from data in the UI
    (no template literal or concatenation producing visible text outside the shared format helpers) plus R41's
    rendered check. Same reach for the agent and the same check, for about a third of the group-7 cost.
- The decision is cost against having a single source of words.

### R45. §16's group sizes don't fit the build record, and there is no total
- Severity: **Important**. Section: §16.
- §16 says "< 150k each". The record is 150–310k for a Sonnet group and 300–360k for an Opus UI group. As written:
  - group 1 migrates seven command modules (≈ 310 KB of `cli.py` and `*_cmd.py`) and their tests into a framework
    that groups 2 and 5 then replace. Rule H5 means today's commands need no migration.
  - each extraction group of group 2 moves about 24 methods out of `api.py` and also builds their commands,
    schemas, renderers and parity tests;
  - group 3 combines the registry, the worker, the job commands, the `CancelToken` change and the window's wiring;
  - group 6 is about 40 §9.3 rows in two group lines.
- None of those fits ~250k. Counted at the record, the design is about 35–45 groups, roughly 10–15 M tokens
  including reviews and fix rounds, and §16 doesn't say so.
- Fix:
  - Group 1: envelope, outcomes, parser, `help`, `where`, app routing only. Today's commands are deleted when
    their replacement lands, not migrated.
  - The schema generator (R36) is its own group.
  - Reads by area are built on the headless `HubApi` (R15), each with its renderers.
  - Jobs split into 3a (registry, worker, `job …`, liveness, R6/R7) and 3b (window wiring, stop files in the
    window's jobs).
  - Group 6 is split into clusters of at most ~8 §9.3 rows, model and UI in separate groups.
  - The plan states the group count and the total estimate for the user before the build starts.

### R46. The A–D live tests come last, behind the whole rebuild
- Severity: **Important**. **Needs a decision.** Section: §16 step 11.
- Issue 33's stages A–D are merged into main, unreleased, with their live tests pending. §16 runs those tests after
  all ten build groups, so the rekordbox writes stay untested on a real library for the length of issue 39.
- Options:
  - (a) Run A–D now with today's commands. J11's "Command today" column covers every agent step except C 1b (the
    upgrade-only sync: use a scratch library whose playlists are all downloaded, as J11 says) and B 2b (stop: Ctrl-C).
  - (b) Run them after groups 1, 3a and the upgrades/AIFF write group.
  - (c) Last, as designed.

### R47. Three overviews overlap
- Severity: **Minor**. Sections: §5.3, §11.
- `status`, `status --ready` and `doctor` each list "rekordbox tracks on missing or superseded files", stopped
  batches and drives away.
- Fix: `status` = what the window's Dashboard and nav show; `doctor` = everything wrong, each problem with `next`;
  `status --ready` = `doctor`'s problems that matter for playing a set (rekordbox checks open, CDJ problems, files
  missing, drives away), as a filter of `doctor`, never its own computation.

### R48. A–D step 3g removes files by hand, against the agent's own rules
- Severity: **Minor**. **Needs a decision.** Sections: §15 A 3g, §14.2 rule 3.
- §15 says the agent "deletes the script's own files". §14.2 tells agents never to delete a music file by hand.
  New track also left a new AIFF in `Library/`, and the test song stays in library.db with no command to remove it.
- Options:
  - (a) Deleting is a person step (`step:delete_test_files` with the script's file list), then `folder remove` and
    `library scan`, and the test song stays as a "file missing" record.
  - (b) A new `track forget <track> --yes` that removes a song's records once its file is gone, never a file.
  - (c) Run the agent-only parts in a sandbox (after R10's fix) and keep the real library free of test songs.

---

## 8. Walks

### 8.1 Goal questions, as an agent with only a shell

| Question / step | Commands | Result |
|---|---|---|
| First contact | `Discjockey` (bare) | **R20** (the window opens and the call blocks) |
| | `Discjockey --help` → `help agents` → `where --json` → `help --json` | ok (`window_open`: **R19**) |
| "Is my library ready for Saturday's gig?" | `status --ready --json` | ok in shape; slow on a big library (**R27**); torn while a write runs elsewhere (**R4**); overlaps `doctor` (**R47**) |
| "Why didn't X download?" | `track find "X"` → `track show <id>` (`why[]`, `next`) | ok; X added after the last read: **R28** |
| "Undo yesterday's work" | `history --since yesterday` → `batch undo <id> --dry-run` → `--yes`, newest first | batches ok; `--since` format and the changes with no undo: **R26** |
| "Does rekordbox match my files?" | `rekordbox match --json` | ok; **R4**, **R27** |
| "Is this upgrade real?" | `upgrade list` → `track show X` (`upgrade` block) → `track spectrum X --which upgrade --png f.png` → `step:listen` | ok; the text sketch can't show the cutoff (**R31**) |
| "What changed since last week?" | `history --since 7d` | playlist edits and settings missing (**R26**) |
| "Sync my new tracks" | `sync read` → `sync plan` (`plan_id`) → `sync run --plan P --detach` → `job wait` loop → `run show last` | timeouts (**R21**); the stored plan (**R14**); a normal sync exits 6 (**R24**) |
| "Swap in the better versions" | `upgrade apply --all --dry-run` → `--plan P --detach` → `check list` → person steps → `check done --all` | ok (the way left out: C5) |
| "Use these Qobuz versions" (30 tracks) | `version search` / `version use` per track | **R1** (no pacing, no auto-stop across calls) |
| "Sign me in to YouTube" | `login use youtube --browser chrome` | Keychain prompt during `running`: **R22**; Safari / folder access: **R23** |
| "Rehearse first" | `sandbox create d --from real --rekordbox copy` → `--sandbox d …` → `sandbox remove d --yes` | **R9**, **R10**, **R2** (a login inside), **R3** (remove) |
| "Make Hard_Bounce AIFF" (old library) | `aiff convert --all --in playlist:Hard_Bounce --dry-run` | facts read on every dry run (**R27**) |

### 8.2 The A–D live tests with the new commands

Legend: **P** = a person; "sbx" = whether a sandbox can stand in for the step.

| Step | Commands | Result | sbx |
|---|---|---|---|
| A 1a, 1c | `rekordbox status` | ok | yes after R10 |
| A 1b, 3b, 3e, 3f | — | **P** (3e: `person_steps` gives the path; 3f: `rekordbox preview --path <new>` afterwards) | no: the real rekordbox app never opens the copy |
| A 2 | `rekordbox preview --path <file>` | ok | yes after R10 |
| A 3a, 3c | script; `folder add <scratch> --wait 90` → `job wait` | ok after **R21** (§15's `--wait 600`) | yes |
| A 3d | `upgrade list`; `upgrade apply <t> --way new-track --dry-run` → `--plan P` | ok | yes after R10 |
| A 3g | `folder remove <scratch> --yes`; the files | **R48** | — |
| B 0a, 1, 4–6, 8, 9a | — | **P** (5: the file's tags have no command; P reads them in the Finder) | no |
| B 0b | file copy; script; `folder add` | ok | — |
| B 2a–2c | `upgrade apply --all --dry-run` → `--plan P --detach`; `job stop`; `batch resume aiff:<n>` | ok | yes after R10 |
| B 3 | `batch show aiff:<n>`, `rekordbox preview --path <new>` | ok for the agent's part; looks **P** | partly |
| B 7a, 7b | `batch undo aiff:<n> --yes` (exit 4, then ok) | ok; opening and quitting rekordbox **P** | 7a no (the real rekordbox app) |
| B 9b | `rekordbox status`, `rekordbox preview --path <new>` | the modified time is missing (C7) | no |
| C 0 | script, `folder add`; the rekordbox backup **P** | ok | — |
| C 1a | `sync plan` (`start_note`) | ok once a read is stored (**R14**) | yes |
| C 1b, 2b | `sync run --auto-upgrade-only --wait 90` → `job wait` | ok after **R21** | yes after R10 |
| C 1c, 2d, 3, 4a | `todo list --group upgrade_ready`; `check list`; `batch undo … --yes`; `settings set auto-upgrade off` | ok | yes |
| C 2a, 2c | — | **P** | no |
| C 4b | `sync run --auto-upgrade-only` | **R38** | yes |
| D 0, 1c, 5a, 6 | — | **P** | no |
| D 1a, 1b, 2a, 2b, 3, 4 | `aiff convert --all --in folder:<p> --dry-run` / `--plan P`; `todo list --group cdj`; `aiff convert --all --todo cdj …`; `aiff convert <t>`; `batch undo`, `track undo` | ok (plays and looks **P**) | yes after R10 |
| D 5b | `aiff convert <t>` → exit 4, the batch of one closed | ok | no (the real rekordbox app is open) |

Every agent step of A–D has a command (after C7, R21 and R38). The sandbox can stand in only for agent steps, and
only after R10. Every step that looks at, plays in or opens the rekordbox app needs the real library and a person.

---

## 9. Verdict

**Ready after fixes, except four parts that need redesigning before the plan is written.** The grammar, the
envelope and outcomes, the catalogue of §5, the goal map of §11, the §9.3 moves and the A–D mapping stand once
their stated fixes go in. These four parts don't:

1. **Shared Qobuz and account protection (new part, R1).** Today pacing and the auto-stop live in one process. Under a
   CLI of one process per command they must live in library.db and in one cross-process pacer, or an agent's loop of
   commands gets around them.
2. **§6, the job registry (R5, R6, R7, R21, R22).** The registry moves to the support folder. Each job kind declares
   its locks, with a support-folder lock for settings, config, tools and logins. Liveness uses an `alive` flock, not
   a pid. Non-TTY callers get a short default `--wait`. Running jobs carry the person's steps.
3. **§9.2, the stored plan (R14).** Store the playlist read in library.db and derive the plan on demand, instead of
   a `plan.json` that every writer in every process must keep fresh (and that would need the secret tokens).
4. **§10.3, the sandbox (R2, R3, R8, R9, R10).** Guard the roots, not a list of write calls. No logins in a
   sandbox. A safe `create` and `remove`. A consistent clone. A rekordbox copy repointed to the clone.

One design choice to settle with them: R15 (build the CLI on a headless `HubApi` instead of extracting `surface/`).
It removes T3, most of group 2 and a source of drift, and changes §8.1 and §16.

| Severity | Count | Findings |
|---|---|---|
| Critical | 3 | R1, R2, R3 |
| Important | 25 | R4, R5, R6, R7, R8, R9, R10, R11, R14, R15, R16, R20, R21, R22, R23, R24, R26, R27, R36, R40, R41, R42, R44, R45, R46 |
| Minor | 20 | R12, R13, R17, R18, R19, R25, R28, R29, R30, R31, R32, R33, R34, R35, R37, R38, R39, R43, R47, R48 |
| **Total** | **48** | |

Needs a decision rather than a stated fix: **3**.
- R44: static words in the engine, or extracted from the UI.
- R46: when the A–D live tests run.
- R48: how the live-test songs are cleaned up.

Every other finding has a stated fix. Together with coverage findings C1–C9, they make up the step-4 fix round.
The four redesigned parts go to an Opus design pass. The rest is design text a Sonnet fix round can apply.
