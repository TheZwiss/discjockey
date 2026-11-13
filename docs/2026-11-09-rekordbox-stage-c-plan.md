# rekordbox stage C: Auto-upgrade on sync (issue 33): plan

Status: plan, 2026-11-09. Design: `docs/2026-11-07-rekordbox-repoint-design.md` (the design). This plan builds its
§13 stage C: §2.5 (binding), with §2.2's set, §5.6–§5.8, §5.12, §8's Auto-upgrade rows, §9.2, §10's two stage C rows
and §11's `set_auto_upgrade`, on top of stage B (`docs/2026-11-07-rekordbox-stage-b-plan.md`, merged 0c2261b). Branch
`feat/rekordbox-c` from `main`; group worktrees `.claude/worktrees/rb-c-<group>` on `feat/rekordbox-c-<group>`, each
merged into the stage branch when its checks are green. No mockup (the user's rule for this round): §6 gives each new
UI state its design direction, built only from existing blocks.

**Stage C in one line:** with a switch that is on by default (Setup and Settings), every sync ends with one AIFF batch
that does Same track for exactly Upgrade all's set while rekordbox is closed, with the batch's backup, journal and
undo; rekordbox open means nothing is upgraded that run and the upgrades are marked as waiting for it; a refusal is
recorded so later syncs don't decode the track again until rekordbox analyses it again; the sync's results, summary
line, report and `--json` say what happened.

**Not in stage C:** Convert to AIFF, Give it its clean name, the CDJ group, Make all lossless files AIFF (D); rekordbox
following Discjockey's moves (E, issue 40); a write to a USB stick; the full agent surface of issue 39 (stage C adds
only the sync's `--json` that design §10 needs and `settings auto-upgrade`); anything for users updating from an
older version (no notes, no migration words: a missing key simply reads as on).

---

## 0. Decisions this plan adds to the design (with reasons)

1. **The phase is its own module, `discjockey/auto_upgrade.py`**, called by `run.py` at the end of both ways a sync
   ends (`execute` after the plan's actions, and `finish_quietly` when the plan had none). Reason: `run.py` stays the
   run's skeleton; the phase's rules (which tracks, the rekordbox check, the records) are tested on their own; both
   front ends get it without code of their own.
2. **The phase runs only when the run reached its end.** A sync stopped (Stop, Ctrl-C) or crashed before the phase
   doesn't start it; a dry run plans it and changes nothing. Reason: Stop means stop; a crash note must name the step
   that crashed, not a batch started afterwards.
3. **The set is one function both ways start it from:** `views.upgrade_ready_keys(state, held)` (To-do's Upgrade ready
   list, hidden ones left out; `held` = the plan's question keys) filtered by `eligible.same_track_quick` with
   `batches.present` and rekordbox's `Status`. That is exactly what `HubApi.upgrade_all` counts (its `same_track is
   None`). Reason: design §2.5 "exactly Upgrade all's set"; one answer, so the Sync line, To-do's count and the phase
   can't differ. Check first: that `upgrade_all`'s list and this one agree on a fixture with hidden, held, away and
   unreadable-rekordbox tracks (a test pins it).
4. **Stricter start than a user batch.** rekordbox running when the phase starts → no batch is recorded at all and
   every track of the set waits (AIFF swaps included). The phase asks `process.running()` (the injected `running`)
   itself, then starts the batch with `batches.run(..., require_closed=True)`, which makes the session's start check
   treat every item as needing a write (it covers rekordbox opening between the two). Reason: design §2.5 (a track
   may be loaded on a deck); no batch row for a run that did nothing.
5. **Auto batches are never resumed.** When Stop or rekordbox opening ends the batch, or a crash leaves it `running`,
   its `planned` items are closed as `skipped` (`rekordbox_open`, or the new reason `not_reached`) and the batch ends
   `done`, its backup id kept, so To-do never offers Resume for it; its done tracks keep their undo and check card.
   `batches.recover` does the same for a crashed `auto_upgrade` batch instead of marking it `stopped`. Reason: design
   §5.12 ("the next sync plans afresh"); a Resume would move files outside a sync without a fresh rekordbox check.
6. **Two records on the parked upgrade** (`e["upgrade"]`, the `upgrade` JSON column; no schema change):
   - `auto_refused: {"reason", "message", "at", "anlz": {path: mtime_ns | null} | null, "free": int | null}` for the
     four refusals of design §2.5 (`timing`, `not_analysed`, `cloud`, `space`). `message` is the item's words (a
     `space` refusal keeps its sizes). Other skip reasons (`unclean`, `changed`, `needs_choice`, `file_missing`,
     `away`, `rekordbox_unreadable`, `busy`) are not recorded: they say so in this run's results only.
   - `auto_waits: "<ISO time>"` when the phase met rekordbox open (at the start, or opened mid-phase) for that track.
   Both are written into the run's state and saved with it (the phase holds the library lock). The phase removes
   `auto_waits` from every track of the set it reaches with rekordbox closed; a done track loses its upgrade anyway; a
   new parked version (a new `upgrade` dict) starts without either. Reason: the design records the refusal "on it";
   the waiting mark must survive a restart and name exactly the tracks that waited.
7. **When a recorded refusal still holds** (`auto_upgrade.refusal_holds`, pure): for `timing`, `not_analysed` and
   `cloud`, while the analysis files of every rekordbox track of the file are the same set with the same mtimes as
   recorded (`anlz`; rekordbox analysing again changes them, and a first analysis adds them); for `space`, while the
   drive's free space is not larger than recorded (`free`: freeing space leaves no other trace, and the check is one
   `statvfs`). A record whose `anlz` is null (it couldn't be read) never holds. The current stamps come from one
   read open of the library (`master.open_read` + `index`, then `offset.analysis_files` per entry), made only when
   a track of the set has a record; the stamps of new refusals from one more read open after the batch. Reason:
   design §2.5's "until rekordbox analyses the track again"; the stored set of paths (not one mtime) also catches the
   first analysis of a track that had none; a read open costs about 0.4 s, a decode 1–3 s per track.
8. **`auto_refused` steers only the phase.** Upgrade all, a selection and a single Replace are the user acting: they
   run the track again (design §2.5 "until the user acts"). Upgrade all's count stays the quick answer (it already
   can't know timing). Reason: design §2.2's "never eligible: refused before by Auto-upgrade" exists so "a sync
   doesn't decode it again each time"; a click is an explicit try.
9. **Busy (`rekordbox.lock` held by another window or the Terminal):** nothing is done, every track of the set is a
   `waiting` result with reason `busy` (no record: the next sync simply tries). Reason: rare (two music folders on one
   Mac), and the next sync is the natural retry.
10. **The sync gets `--json`** (design §10's "the run's `--json`"; there is none today). One object at the end, human
    lines to stderr, `--json` without `--yes` and without `--dry-run` refused (`needs_yes`, exit 1) because a command
    never prompts. Reason: the design's JSON block needs a run to carry it; the rest of the agent surface stays with
    issue 39.
11. **Setup shows the switch in the Downloads step**, as its own card under the account cards. Reason: that step is
    where the user meets "a lossless version" and Qobuz; the Existing music step promises that the import copies,
    moves and renames nothing, and a switch that moves files beside that line would read as contradicting it; every
    user passes Downloads (with Qobuz or "I don't have Qobuz").
12. **Settings › Upgrades is a new row `upgrades` in the "This Mac" group, after Watched folders.** Reason: it acts on
    the files and the rekordbox library of this Mac; the Downloads group is the services with their logos.
13. **The Sync page's before-start line reads rekordbox live through a new `rekordbox_status()`** (promised by stage B
    §0.9 and design §11), asked when the page opens and when the window gets focus again. Reason: the user quits
    rekordbox in rekordbox and comes back to Discjockey, so focus is the moment the answer changes for them; no timer.
14. **"Moving never renames" names Auto-upgrade too.** Its last sentence becomes "… while rekordbox is closed (Same
    track for a file that isn't AIFF, by hand or through Auto-upgrade). That step is refused when it can't." Reason:
    the invariant must stay true on `main` once the sync can run that step.
15. **The run's results get two report sections:** `upgraded` (done; counted with `swapped` in the run's lossless
    numbers, not as a new file for rekordbox: its track already plays it) and `upgrade_waits` (waiting, refused, not
    reached; never an error). A failed item goes to `errors` as any failed step does (exit code 1). Reason: the end
    screen and the report read sections; failures already have their place.

---

## 1. Architecture (binding interfaces)

### 1.1 Modules

| Module | Change | Group |
|---|---|---|
| `settings.py` | `Settings.auto_upgrade: bool = True`; load (`data.get("auto_upgrade", True)`, a non-bool → `SettingsError` "auto_upgrade must be true or false."), save | C1 |
| `rekordbox/eligible.py` | `REASONS` + `"not_reached"`; the comment on `auto_refused` says what it is now (the phase's own skip) | C1 |
| `rekordbox/preview.py` | `REASON_WORDS["not_reached"]` = "the sync stopped before it got to this one; it is tried again at your next sync" | C1 |
| `batches.py` | `run(..., require_closed=False)`; `end_auto(paths, batch_id, reason, *, now)`; `recover` ends `auto_upgrade` batches; docstring | C1 |
| `auto_upgrade.py` (new) | the phase: `plan`, `run_phase`, `refusal_holds`, `stamps`, the records, `Outcome` | C1 (pure parts), C2 |
| `run.py` | `execute(..., rekordbox=None)` and `finish_quietly(prep, emit, token=None, rekordbox=None)` run the phase | C2 |
| `report.py` | `SECTIONS` + `upgraded`, `upgrade_waits`; `RunLog.auto_upgrade`; `auto_upgrade_line`; render + `.json` | C2 |
| `console.py`, `cli.py` | the sync's dry-run lines, the before-start line, BatchProgress lines, the summary line, `--json`; `settings auto-upgrade` | C3 |
| `batch_cmd.py` | `upgrade list`: `auto_refused` (object), `auto_waits` | C3 |
| `hub/api.py`, `views.py`, `jobs.py` | `set_auto_upgrade`, `rekordbox_status`, `setup_status.auto_upgrade`, views (§4) | C4 |

### 1.2 `auto_upgrade.py`

```python
@dataclass(frozen=True)
class Planned:        # what the phase would do now
    run: list[str]                     # song keys, in upgrade_ready_keys order
    waiting: list[tuple[str, str]]     # (key, "rekordbox_open" | "busy")
    refused: list[tuple[str, dict]]    # (key, its auto_refused record): held, not tried
    rekordbox_running: bool

@dataclass(frozen=True)
class Outcome:        # the run's block (report, --json, the end screen)
    batch: int | None; backup: str | None; done: int; waiting: int; refused: int; failed: int
    stopped: bool; dry_run: bool
    results: list[dict]   # {"track", "name", "state": "done"|"would"|"waiting"|"refused"|"failed", "reason", "message", "how"}
    def to_dict(self) -> dict

def plan(paths, state, held, settings, *, running, place) -> Planned | None   # None: the switch is off
def run_phase(paths, prep_state, held, settings, log, *, emit, token, running, place, compare, now,
              dry_run=False) -> Outcome | None
def refusal_holds(record: dict, anlz_now: dict | None, free_now: int | None) -> bool   # pure (§0.7)
def stamps(paths, keys, state, *, running, place) -> dict[str, dict | None]           # one read open
```

- `plan`: off → None. The set (§0.3); rekordbox's `Status` from `master.status(place, running)` only when a track of
  the set isn't an AIFF (check first: its cost and that it answers `none` for the tests' empty folder). Running →
  everything `waiting` (`rekordbox_open`), no read open. Else the records: `stamps` for the tracks that have one,
  `refusal_holds` per track (free space: `convert.free_space` of the file's folder).
- `run_phase`: `plan`; dry run → an `Outcome` with `would` rows (`how`: `in_place` | `new_aiff`, as `swap_how`),
  nothing written. Else, when `run` is empty: write the records (`auto_waits` set or cleared, §0.6), no batch. Else
  `batches.start(paths, [(k, "same_track")…], started_by="auto_upgrade", scope="sync")` then `batches.run(...,
  require_closed=True, state=prep_state, emit, token, running, place, compare, now)`:
  - returns / `Refused` → per item: done → `Result("upgraded", …, note=item message, status/source/path of the new
    file)`; skipped with one of the four reasons → the `auto_refused` record (stamps after the batch) and an
    `upgrade_waits` result with the message; other skips → `upgrade_waits` result only; failed → `errors` result.
  - `RekordboxOpen` → `batches.end_auto(…, "rekordbox_open")`; the planned ones get `auto_waits`.
  - `Stopped` / `KeyboardInterrupt` → `end_auto(…, "not_reached")`, results as above, then `Outcome.stopped=True`
    (`KeyboardInterrupt` re-raised after the records are in the state, so the console's run ends as stopped).
  - `Busy` → `end_auto(…, "busy")`; every track `waiting` (`busy`).
  The phase adds its results to `log` and sets `log.auto_upgrade = outcome.to_dict()`.
- Events: none new. `batches.run` emits `BatchProgress`; the phase emits one `Message("info", "Upgrading {n} tracks
  at the end of the sync…")` before it starts, and `Message("info", <the before-start line>)` when it waits.
- Log: `batches.run` writes operations.log per item (`upgrade_same_track`) as it does.

### 1.3 `batches.py` additions (C1)

- `run(..., require_closed: bool = False)`: passes `items_need_write = lambda view: True` to the session when set
  (rekordbox running at the start → `RekordboxOpen`, nothing changed, the batch `stopped`/`rekordbox_open`, which
  `end_auto` then closes). Everything else as today (plan §0.7: rekordbox opening stops any batch).
- `end_auto(paths, batch_id, reason, *, now=datetime.now) -> BatchResult`: every `planned` item → `skipped` with
  `reason` and `_words(reason)`; the batch → `done`, `ended=now()`, **backup kept** (unlike `close_unrun`); returns
  the result. Refuses (ValueError) a batch not started by `auto_upgrade`.
- `recover`: a `running` batch started by `auto_upgrade` → `end_auto(…, "not_reached")` instead of
  `stopped`/`crash`. Check first: that `recover` runs after the crashed item's own step recovery
  (`recover_pending` order), so an item the recovery finished is `done`, not closed as `not_reached`.
- Check first: `db.set_aiff_batch(state="done", stop_reason=…)` is allowed; if `stop_reason` is only for `stopped`,
  `end_auto` leaves it null (the items carry the reason).

### 1.4 `run.py` (C2)

- `execute(prep, qobuz, *, …, rekordbox: dict | None = None)`: after `executor.run(...)` returned (not on
  `Cancelled`/`KeyboardInterrupt`/a crash), `step = "upgrading at the end of the sync"` and
  `auto_upgrade.run_phase(paths, state, held, prep.settings, prep.log, emit=tracking, token=token, **opts)`;
  `opts` = `rekordbox` or the real ones (`running=process.running`, `place` located, `compare=align.compare_files`).
  `stopped` → code 130. Then the existing `finally` (save, not_lossless.md, report) writes the records and the block.
  `held` = `{q.song_key for q in prep.plan.questions}`.
- `finish_quietly(prep, emit=no_emit, token=None, rekordbox=None)`: the same call before its save.
- `Prepared` is unchanged; the console's dry run calls `auto_upgrade.run_phase(..., dry_run=True)` itself (C3).
- `hub/jobs.sync_work` passes `rekordbox={"running": svc.rekordbox_running, "place": svc.rekordbox_place(),
  "compare": svc.compare}` and its token to both calls (C4). Check first: how `sync_work` gets the services today.

### 1.5 `report.py` (C2)

- `SECTIONS` gains, after `added_new`: `("upgraded", "Upgraded (your cues stayed)")`,
  `("upgrade_waits", "Upgrades still waiting")`.
- `RunLog.auto_upgrade: dict | None = None`; `write_run` puts it in the `.json` as `"auto_upgrade"` (absent when
  None); `render_report` writes, right after the `upgraded` items, "Backup of your rekordbox library from before
  these upgrades: {id}" when the block has a backup, and the summary line at the top of the report's sections.
- `auto_upgrade_line(block: dict | None) -> str | None` (§3's words; None when the block is None or empty). The
  console summary, the report and `views.run_detail` all use it.
- `views.LOSSLESS_SECTIONS` + `upgraded` (C4).

### 1.6 The run's JSON block (design §10, extended)

`auto_upgrade` is `null` when the switch is off, else:

```json
{"batch": 12, "backup": "2026-11-09T21-04-11Z", "done": 9, "waiting": 3, "refused": 1, "failed": 0,
 "stopped": false, "dry_run": false,
 "results": [{"track": "local:41", "name": "Artist – Title", "state": "done", "reason": null,
              "message": "Your track keeps its cues, playlists and history", "how": "new_aiff"}]}
```

`waiting` counts `rekordbox_open`, `busy` and `not_reached` and (amended by the stage review) the unrecorded skips
(`changed`, `unclean`, `other_library`, `rekordbox_unreadable`, ...: To-do never shows them, so they are not
"couldn't go in"; the row keeps its own reason and words, and the summary line puts them with the next sync); `refused`
only the five recorded reasons (`auto_upgrade.REFUSALS`: held or new); a dry run has `batch: null`, `done: 0` and `would` rows. The sync's JSON:
`{"ok": true, "exit_code": 0|1|130, "dry_run": bool, "report": "<path>"|null, "counts": {section: n},
"auto_upgrade": <block>|null}`; a setup problem `{"ok": false, "kind", "message"}` (exit 2), the lock held
`{"ok": false, "kind": "busy", …}` (exit 3), `needs_yes` (exit 1). The rekordbox exit code 4 is not used by the sync:
waiting is a normal end of a sync, and the block says it.

---

## 2. Commands (C3; design §10)

- `discjockey [--yes] [--dry-run] [--limit N] [--json]` (the sync): §1.6. Human output unchanged plus: in the
  printed plan, when the switch is on and the set isn't empty, "At the end, {n} upgrades go in place of your files;
  your cues stay." (and §3's before-start line when rekordbox runs); `--dry-run` lists them ("  Artist - Title (in
  place)" / "(new AIFF)") and the held refusals with their reason; during the phase one line per BatchProgress
  ("Upgrading 3 of 12: Artist - Title"); after the run's summary, `auto_upgrade_line`. Check first: how
  `cli.main` answers `LockHeld` for a sync (exit 3) and that `--json` reaches that branch.
- `discjockey settings auto-upgrade [on|off] [--json]`: without a value prints the current value (no lock, exit 0);
  with one, takes the library lock (exit 3 when held), saves, prints "Upgrade automatically when I sync: on|off";
  JSON `{"ok": true, "auto_upgrade": bool}`. Needs a set-up music folder like the other commands (exit 2). A new
  `settings` sub-command group so issue 39 can add the other settings beside it.
- `discjockey upgrade list --json`: per row `auto_refused` = `{reason, message, at}` | null, `auto_waits` = bool
  (the record is there and the switch is on).
- CONTRIBUTING.md › "Commands for scripts and agents": both commands, the sync's JSON and exit codes; issue 39's line
  in `docs/issues.md` names them.

---

## 3. Words (binding; design §8 plus what C adds)

Design §8's Auto-upgrade rows (Settings switch + Hint, Setup switch + line, sync summary, waiting item), the
`rekordbox_open` problem, the batch-stopped line, the refusals and the result notes. Added here:

| Where | Text |
|---|---|
| Summary line (`auto_upgrade_line`), n > 0 | "Upgraded {n} tracks; your cues stayed." (1: "Upgraded 1 track; your cues stayed.") then, when m > 0, " {m} wait for rekordbox to be closed." (1: "1 waits …"), when j > 0 (Stop, another window, a skip nothing is recorded for) " {j} wait for your next sync.", when k > 0 (only the five recorded reasons, §1.6), " {k} couldn't go in; To-do says why." |
| Summary line, n = 0 | "{m} upgrades wait for rekordbox to be closed." (1: "1 upgrade waits …"); "{k} upgrades couldn't go in; To-do says why." (1: "1 upgrade …") |
| Summary line, waiting for another reason | not reached (Stop) and busy ones get their own clause after the rekordbox one: " {j} wait for your next sync." (1: "1 waits …"; n = 0: "{j} upgrades wait for your next sync.") |
| Waiting row (results, To-do panel), rekordbox | design §8 "Waits for rekordbox to be closed: it is upgraded at your next sync, or press Upgrade all." |
| Waiting row, not reached | "The sync stopped before this one; it is upgraded at your next sync." |
| Waiting row, busy | "Another Discjockey window or the Terminal was changing your rekordbox library; it is upgraded at your next sync." |
| Refused row | the item's own message (design §8's refusal sentences) |
| To-do row detail, waiting | "Waits for rekordbox to be closed" |
| To-do row detail, refused | "{Short} · not upgraded at your sync" (reason first: the row cuts its end at 1100; stage review B2) with short, capitalised, = timing "couldn't line it up", not_analysed "not analysed in rekordbox", cloud "in Cloud Library Sync", space "not enough free space" |
| Sync before-start Hint (switch on, rekordbox open, n ≥ 1) | "rekordbox is open: quit it before the sync ends, so the sync can put {n} upgrades in place." (1: "1 upgrade"; amended by the stage review: the check is made when the phase begins, at the end of the sync, so "before you start" was wrong) |
| Console plan line | "At the end, {n} upgrades go in place of your files; your cues stay." (1: "1 upgrade goes …") |
| Live progress (the sync's phase) | "{done} of {total} upgraded" over "Upgrading · {Artist – Title}", ProgressBar labelled "Upgrading" (and in the foot bar). Not stage B's "of {total} done": next to the downloads' lists "3 of 8 done" read as their count (stage review B3) |
| End screen section | "Upgraded" (rows, how each went), "Still waiting" (the tracks tried again at the next sync; short reason), "Couldn't go in" (the refusals; To-do's short reason) |
| Report | headings of §1.5; "Backup of your rekordbox library from before these upgrades: {id}" |
| Batch check row (To-do) of an auto batch | name "{n} tracks upgraded", sub "{date} · Upgraded during your sync" |
| Batch card foot of an auto batch | design §2.5 "Undo all from this sync" (in place of "Undo all {n}") |
| Settings row | name "Upgrades"; line on: "Automatic at the end of each sync"; off: "Off: upgrades wait for you in To-do" |
| Settings InfoTip | "Only upgrades that are the same recording as your file, measured to the sample; a different edit always waits for your choice. Each sync's upgrades are one batch, with a backup of rekordbox's library first. Undo one track or all of them in To-do." |
| Setup card title | "Upgrades" |
| `needs_yes` (sync `--json`) | "Add --yes to start the sync without a question, or --dry-run to look first. Nothing was changed." |
| `set_auto_upgrade` refused | "on must be true or false." (as `set_read_liked_music`) |

The UI agent may shorten panel rows to fit; each meaning stays, with the reason in its commit.

---

## 4. Bridge and contract (C4; design §11)

Into `docs/hub-bridge-contract.md` (a new section "Auto-upgrade (issue 33 stage C)" after stage B's, and the
Settings table), `types.ts` + `contract.ts`, the fake backend, in the same commit:

- **`set_auto_upgrade(on)`**: job `set_auto_upgrade`, result `{}`; non-bool → `refused` ("on must be true or
  false."); takes the library lock as every settings write (busy/console answered). Model: `set_read_liked_music`.
- **`setup_status().auto_upgrade: boolean`** (Setup and Settings read it). `SettingKey` gains `'auto_upgrade'`.
- **`rekordbox_status()`**: immediate, `{state: "ready"|"none"|"unreadable", running: boolean}` from
  `_rekordbox_status()` (cached; answers its last value while a write job runs, as today).
- **`sync_preview().auto_upgrade: {on: boolean, ready: number} | null`**: `ready` = the phase's set size now
  (`auto_upgrade.plan` minus `refused`, by the quick answer, no read open: api passes the cached status and `held`;
  records whose hold can't be told without a read count as held). null when off or no preview.
- **`upgrade_block.auto_refused`**: `{reason, message, at} | null` (was the placeholder `null`; type changes from
  `string | null`); new **`auto_waits: boolean`** (the record is there, the switch is on, `swap_possible`).
- **`todo()`**: an Upgrade ready item's `detail` follows §3 (waiting / refused) before `upgrade_status`; the batch
  item's `batch` gains `started_by` and its `detail` follows §3 for `auto_upgrade`. `views.todo(..., auto_on: bool)`.
- **`run_detail` / `run_summary`**: `auto_upgrade: <block (§1.6)> & {line: string | null} | null` from the report's
  `.json`; `sections` carry `upgraded` and `upgrade_waits`; `upgraded` counts in `counts.lossless`/`lossy` by status.
- **Events:** a sync job now sends `BatchProgress` during its phase (contract's Events table: "also from a sync").
- **Stores:** `lib/stores/run` keeps `phase: 'upgrading'` with `{done, total, name}` while a sync job's
  `BatchProgress` arrives (pure transition + `run.test.ts`); `rekordboxStatus()` read helper in `client.ts` users.
- **Fake:** settings `auto_upgrade` (default true) with `set_auto_upgrade`; `rekordbox_status` with a toolbar
  toggle "rekordbox open"; a sync whose end sends `BatchProgress` and finishes with the block; scenarios: `sync:
  auto-done` (9 upgraded, 3 waiting, 1 refused), `sync:auto-rekordbox-open` (before start, n = 4), `sync:auto-running`
  (the live phase), `todo:auto-waits`, `todo:auto-refused`, `todo:auto-batch` (the card with "Undo all from this
  sync"), `settings:upgrades-on`, `settings:upgrades-off`, `setup:downloads-auto`. Check first: each page's
  scenario naming in its `fake.ts`.

---

## 5. Tests and behaviours to pin (offline; design §12 "Auto-upgrade")

Fixtures as stage B (`tests/rekordbox_helpers.py`: `make_master`, `make_anlz`, `running_after`, `dump`, `diff`);
`DISCJOCKEY_REKORDBOX` an empty folder unless a test builds one; `compare` injected; no real library.

**C1** (`test_settings.py`, `test_batches.py`, `test_auto_upgrade.py` for the pure part):
- A settings file without `auto_upgrade` reads as on; `Settings()` is on; false round-trips; a non-bool is refused.
- `require_closed`: rekordbox running, a batch of only AIFF swaps → `RekordboxOpen`, nothing changed, no backup.
- `end_auto`: planned → skipped with the reason and words, batch `done`, backup kept, done items untouched;
  refuses a `user` batch. `recover` ends a crashed auto batch (`not_reached`), a crashed user batch stays `stopped`.
- `refusal_holds`: each reason both ways; a changed mtime, an added file, a removed file → not held; `anlz` null →
  not held; `space` holds at equal free space, not above.

**C2** (`test_auto_upgrade.py`, `test_run.py`, `test_report.py`):
- **Off → the sync moves no file:** a library with three eligible upgrades and the switch off: after `execute` and
  after `finish_quietly`, every music file, `Superseded/`, `Upgrades ready/` and rekordbox's `dump` are unchanged, no
  `aiff_batches` row, `auto_upgrade` absent from the report `.json`.
- **On:** only the set runs (a hidden one, a held one, a `different` edit, an away file, a non-AIFF with an unreadable
  library stay); it runs after the downloads (event order: the last `ActionFinished` before the first
  `BatchProgress`); one batch `started_by="auto_upgrade"`, one backup; results in `upgraded`; the set equals
  `upgrade_all`'s on the same fixture (§0.3).
- **Both ways a sync ends:** a plan without actions (`finish_quietly`) runs the phase too.
- **Dry run:** `would` rows, nothing written (files, records, library.db rows, rekordbox).
- **Stop between tracks:** the token set after the first item → one done, the rest `skipped`/`not_reached`, batch
  `done` (no Resume: `views.todo`'s `stopped` is null), run code 130, the done one keeps its undo. Ctrl-C the same.
- **rekordbox open at the start:** nothing done, no batch row, every track `auto_waits`, `waiting` = n, run code 0.
- **rekordbox opens mid-phase** (`running_after(1)`): the item in work rolled back (stage B), the batch ends via
  `end_auto("rekordbox_open")`, the rest get `auto_waits`; the next phase with rekordbox closed clears them.
- **`auto_refused` + the ANLZ mtime re-try:** a `not_analysed` refusal is recorded with its stamps; the next sync
  doesn't call `compare` for it (a counting fake) and lists it under `refused`; touching its analysis file (mtime) →
  the sync after tries it again; a `space` refusal re-tried once free space grows; an unrecorded skip (`changed`)
  is tried at the next sync.
- **Report:** the `.md` has "Upgraded (your cues stayed)" with the rows and the backup line naming the batch's
  backup id; the `.json` carries the block; `auto_upgrade_line` for every §3 case (singulars, n = 0, rekordbox and next-sync waits together).
- **Crash in the phase** (an item raising past the batch): filed as the run's crash with step "upgrading at the end
  of the sync"; the next `recover_pending` ends the batch `not_reached`.

**C3** (`test_cli.py`, `test_console.py`, `test_batch_cmd.py`): the sync's `--json` shape (ok, dry run, stopped
130, busy 3, setup 2, `needs_yes` 1), the block equal to the report's; `settings auto-upgrade` read, on, off, busy,
JSON; the console's plan line, dry-run list and summary line; `upgrade list --json`'s `auto_refused`/`auto_waits`.

**C4** (`test_hub_views.py`, `test_hub_api_*.py`, `test_hub_contract*.py`, vitest `fake.test.ts`, `run.test.ts`):
`set_auto_upgrade` job and refusal; `setup_status.auto_upgrade` default true; `rekordbox_status`; `sync_preview.
auto_upgrade` (off → null; on → ready count equals the phase's set); `upgrade_block.auto_refused`/`auto_waits`
(switch off hides the mark); the To-do details; `_batch_item` for an auto batch; `run_detail.auto_upgrade.line`;
the sync job passes the services (a hub sync with the fake rekordbox running → nothing upgraded); contract tests.

---

## 6. The UI (U1, U2): design direction, complete

Read first: `docs/hub-design-language.md`; load `apple-design` and `emil-design-eng`. Existing blocks only
(`Surface`, `ListRow`, `ListSection`, `ToggleRow`, `Hint`, `InfoTip`, `NoteCard`, `ProgressBar`, `Badge`, `Cover`,
`Button`); no new block, so no mockup. If a state truly needs one, stop and report (the coordinator decides on a
single-component mockup).

**Drift list (must not change):** the foot bar (player), the sidebar and its icons, every page outside the states
below, Settings' icon (never a sun) and every other Settings row, the coloured service logos, the filter strip, the
row grid (`--row-cols`), the list's sticky section heads, one filled button per screen, stage B's panels and cards
apart from the named words. Choices stay `ToggleRow`/`Segmented`/grouped rows, never floating pills.

### 6.1 Settings › Upgrades (U1)
A new row `upgrades` in `ROW_GROUPS` "This Mac" after `folders` (`SETTINGS_ROWS`, `ROW_NAMES` "Upgrades", a glyph
lead in the sidebar's style that reads as "better version"; check first which glyph To-do's Upgrade ready group
uses and take it; never a sun). Its line (§3) from `setup_status.auto_upgrade`. Its panel (`RowPanel`): one
`Surface kind="list"` with one `ToggleRow` "Upgrade automatically when I sync", its `sub` the design §8 Hint, an
`InfoTip` (§3) on the row; it saves at once (`set_auto_upgrade`, `runJob` quiet) like YouTube Music's Liked music
switch, the switch showing the pending value until the job ends; an error as `NoteCard tone="problem"` under it. No
filled button in the panel.

### 6.2 Setup › Downloads (U1)
Under the account cards, one `Surface kind="list"` card labelled "Upgrades": one `ToggleRow` "Upgrade automatically
when I sync" (on from `setup_status.auto_upgrade`), its `sub` the design §8 Setup line. It never becomes the step's
filled button and never blocks Continue. Check the ladder-beside-cards layout at 1100 and 2560 (the card sits in the
cards' column, its width).

### 6.3 To-do (U1)
- Upgrade ready rows: the `detail` from the view (§3); no new badge or colour (the row's existing tone).
- The single upgrade panel: `auto_waits` → the design §8 waiting sentence as a `Hint` under the Replace actions (the
  UI agent may say "press Replace" there instead of "press Upgrade all": the same meaning in that panel);
  `auto_refused` → `NoteCard tone="warn"` with its `message` above the actions. Replace stays as it is (§0.8).
- The batch check item of an auto batch: sub from the view; the foot's second button "Undo all from this sync".

### 6.4 Sync (U2)
- **Before start:** with `sync_preview.auto_upgrade.on` and `ready ≥ 1`: rekordbox running (`rekordbox_status().running`)
  is the §3 sentence as a warn `NoteCard` ABOVE Start sync in "This run" (amended by the stage review B7: a note under
  the button moved it when rekordbox quit; a one-line spacer under Start keeps its place); rekordbox closed is a
  one-line `Hint` under Start, "{n} upgrades go in at the end; cues stay." (1: "1 upgrade goes …"; shortened from the
  console's words, which the panel cuts at 1100). The console-running and nothing-today hints come first when they
  apply. `rekordbox_status()` is read on page open and on window `focus`.
- **Live:** during `phase: 'upgrading'` the run's progress card shows "{done} of {total} upgraded" and the bar in place
  of "Track x of y" (§3; the foot bar says the same); Stop safely stays in the foot, unchanged.
- **End screen:** the summary line (`run_detail.auto_upgrade.line`) as one more note in the notes under the stat
  cards; a list `Surface` "Upgraded" (`ListSection` head with the count) after the new-file lists and before Other
  changes: per row `Cover`, Artist – Title, the quality badge as other lossless rows, sub = the engine's note only when
  it holds kept edits or "not in rekordbox", else how it went (the block's `how`); then, split by each track's state in
  the block (stage review B1, B5, B6), a `ListSection` "Still waiting" (sub "Waits for rekordbox to be closed" for
  `rekordbox_open`, "Waits for your next sync" for every other waiting reason; Review → to the track) and a
  `ListSection` "Couldn't go in" (the refused tracks: To-do's short reason as sub, the full sentence as the row's
  tooltip, Fix →). The counts are the block's `waiting` and `refused`. An empty part is left out; a switch-off run
  shows none.

### 6.5 Shots (S)
`shots.json` entries for every §4 fake scenario: Settings (row list with Upgrades, the panel on and off), Setup
Downloads with the card (1100, 1280, 2560), To-do (waiting row + panel, refused row + panel, the auto batch card),
Sync (before start with the line, the live phase, the end screen with both sections). Each compared with `main`'s
shot of the same page for drift.

---

## 7. Task groups (one agent each, in this order, one at a time)

Every group: read `CLAUDE.md`, this plan and the design sections it names; touched tests while working, then
`~/.local/bin/uv run pytest -q | tail -3` once at the end (UI groups: `npx vitest run <files>`, `npm run check`,
`npm run rules -- --page <p> --only <shots>`; `npm run verify` only once, §7 V); `scripts/check_public.sh
--require-denylist` before each commit; commits `feat(auto-upgrade): …`, `feat(hub): …`, `feat(hub-ui): …`,
`test(…)`, `docs(…)`, `build(hub): static`. Stop at the named deliverable, commit what is green, report what is left.
Never start rekordbox, a real sync or the app; never read `~/Library/Pioneer`, `~/Music/Discjockey` or the real
library (except RH, only as written there); no waiter loops or `pgrep`; long commands in the background with a
status line.

### C1. Switch, batch additions, the phase's pure rules — Sonnet, ~150–190k
Files: `discjockey/settings.py`, `discjockey/batches.py`, `discjockey/rekordbox/{eligible,preview}.py`,
`discjockey/auto_upgrade.py` (the dataclasses, `refusal_holds`, `stamps`, `plan`), tests `test_settings.py`,
`test_batches.py`, `test_auto_upgrade.py` (plan + pure). Builds §1.1's C1 rows, §1.2's `plan`/`stamps`/
`refusal_holds`, §1.3. Pins §5 C1 and `plan`'s set (§0.3 against `upgrade_all`'s list). **Check first:** §1.3's two;
§1.2's `master.status` cost; that `offset.analysis_files` gives every analysis file of an entry (`.DAT`, `.EXT`,
`.2EX`), else extend it there.
Stop point: `plan` answers every §0.3/§0.4/§0.7 case on fixtures; `end_auto` and `recover` pinned.

### R-C1. Review of C1 — Sonnet, ~110–140k; fix round (if needed) — fresh Sonnet, ~115–150k
The diff against §0, §1.2–§1.3, §5 C1: the set equals Upgrade all's, the hold rule, `end_auto` never drops a backup
id, `recover`'s order. Minors fixed in the same round.

### C2. The phase in the run, records, report — Sonnet, ~170–200k
Files: `discjockey/auto_upgrade.py` (`run_phase`, the records, `Outcome`), `discjockey/run.py`,
`discjockey/report.py`, tests `test_auto_upgrade.py`, `test_run.py` (or the run's existing test file; check first its
name), `test_report.py`. Builds §1.2's `run_phase`, §1.4, §1.5, §1.6's block. Pins §5 C2. **Check first:** that
`batches.run(state=prep.state)` keeps the run's state current so the final `save()` keeps both the steps' writes and
the records; that `upgrades.swap` / `convert.same_track` store the re-measured alignment when it says "not the same
edit" (if not, the To-do keeps offering Same track: fix it here, it is a stage B bug, and note it in the commit).
Stop point: every C2 behaviour green on a tmp library with a fixture rekordbox.

### R-C2. Review of C2 — Sonnet, ~120–150k; fix round — fresh Sonnet, ~115–150k
Against §0.1–§0.9, §1.2, §1.4–§1.6, design §2.5 and §5.6–§5.8: "off moves no file" holds on every path, the phase
never starts after Stop or a crash, rekordbox open at the start writes nothing (no backup, no batch row), the
records' life cycle, the crash step name. Runs the full suite once. **Stop point:** the coordinator reads both
reviews before C3.

### C3. Commands and docs — Sonnet, ~150–190k
Files: `discjockey/cli.py`, `discjockey/console.py`, `discjockey/batch_cmd.py` (`upgrade list` fields), a
`settings` sub-command (in `cli.py`, or `discjockey/settings_cmd.py` if `cli.py` would grow past its shape: check
first), tests `test_cli.py`, `test_console.py`, `test_batch_cmd.py`; `CONTRIBUTING.md` (§2), `README.md` (§8),
`CLAUDE.md` (§8), `docs/issues.md` (issue 39 line), the design doc's corrections (§8). Builds §2. Pins §5 C3.
Stop point: every command on a fixture library, human and `--json`.

### C4. Bridge, views, contract, fake, run store — Sonnet, ~170–200k
Files: `discjockey/hub/{api,views,jobs}.py`, `docs/hub-bridge-contract.md`, `hub-ui/src/lib/bridge/{types,contract,
client,events}.ts`, `hub-ui/src/lib/bridge/fake/*`, `hub-ui/src/lib/stores/run.ts` (+ test), each page's `fake.ts`
scenarios (§4, data only: no component), tests §5 C4. Builds §4. The existing panels keep working on the new shapes
(`npm run check`, vitest). Stop point: contract tests green; the fake answers every new method and scenario.

### RH. Rehearsal of a sync's phase on a copy — Sonnet, ~150–190k
Extends `scripts/rekordbox_rehearsal.py` with a step `rehearse-sync` (same safety: marked work folder, refuses
while rekordbox runs or `-wal`/`-shm` lie beside the source, every path an argument, names never leave the work
folder). Run once over the copy stage B's steps make (`copy-db`, `copy-tracks`) and report pass/fail with numbers:
1. **Prepare** as `rehearse` does (scratch support + music folder, the copies as own songs, parked same-edit
   upgrades), with a `playlists.txt` holding no switched-on line. Check first: that a sync with it reads no network
   and plans no action (`bin/discjockey --dry-run --json`: no actions; if own songs get first upgrade checks, set
   their `next` check dates ahead in the scratch library). One MP3 pick has its analysis copy removed (a
   `not_analysed` refusal to come).
2. **Switch off:** `settings auto-upgrade off`, `bin/discjockey --yes --json`: block null; music tree, `Superseded/`
   and `dump(copy)` byte-equal to before; no batch row.
3. **Dry run on:** `settings auto-upgrade on`, `--dry-run --json`: `would` rows = the picks minus none; nothing
   changed.
4. **The phase:** `--yes --json`: the block's batch `started_by` `auto_upgrade` (`batch show`), done = picks − 1,
   refused 1 (`not_analysed`, recorded with stamps); then stage B's `check_run` checks per done track (columns,
   text, ANLZ splice, timing snaps to 0, backup = the before copy); the report `.md` has the Upgraded section and the
   backup line with the block's backup id.
5. **No repeat:** a second `--yes --json`: no new batch, no new backup, the refused one listed as held (and no
   decode: the run's time for it under 0.2 s), done 0.
6. **Re-analysed:** put the analysis copy back (new mtime), sync again: the track is tried (refused or done, either
   way the record changes), proving the re-try.
7. **Undo all from this sync:** `batch undo <id> --json`: stage B's `check_undo` checks.
8. **Clean up** the work folder; nothing real in the repo; report numbers, no names. **Stop point:** any fail → the
   coordinator decides on a fix group before U1.

### U1. Settings, Setup, To-do states (UI build) — Opus, ~170–200k
Files: `hub-ui/src/lib/router.ts` (`SETTINGS_ROWS`), `pages/settings/{settingsModel.ts,settingsModel.test.ts,
Page.svelte}` + a small `UpgradesPanel.svelte` if `RowPanel` can't hold a ToggleRow (check first how the Liked music
panel is wired), `pages/setup/StepDownloads.svelte` (+ `setupModel` if a rule changes), `pages/todo/*` and
`lib/decisions/{UpgradeCards,BatchCheckFoot}.svelte` for §6.3's words, `shots.json` entries of those pages. Builds
§6.1–§6.3. No shots beyond one look per state at 1280 to build against; `npm run build` → `build(hub): static`.
Stop point: every U1 state reachable in fake mode.

### U2. Sync states (UI build) — Opus, ~180–200k
Files: `pages/sync/{BeforeStart,SyncCard,LiveView,EndScreen}.svelte`, `endModel.ts` (+ test), `planModel.ts` (+
test) for the line's rule, `shots.json`. Builds §6.4. `build(hub): static`.

### S. Shots — Sonnet, ~110–140k
§6.5 at their sizes, compared with `main` for drift (the §6 drift list), each checked for meaning (every grey,
colour, word and count), empty, first-open and no-selection states, icons at real size. Reports findings; fixes
nothing.

### R2. Stage review — Opus, ~150–180k; fix rounds — fresh Sonnet, ~115–150k each (code/docs, UI)
The whole diff against this plan and design §2.5: the CLAUDE.md invariant text word for word, "off moves no file",
the words (§3), the contract, the drift list, the rehearsal's report. Minors fixed in the same rounds.

### V. Verify and merge
`npm run verify` once in the background (about 20 min), `npm run smoke`, CI green on the stage branch push; merge
`Merge feat/rekordbox-c: Auto-upgrade on sync` into `main`, push. **No release** before the user's live test (§9).

Total: about 2.2–2.7 M tokens over 13 runs plus fix rounds; the engine (C1, C2 and their reviews) is about 40 %. It
writes the user's files and rekordbox's library without a click, so each engine group gets its own review before
the next builds on it, and the stage gets the Opus review and the rehearsal.

---

## 8. Docs and issues

- **CLAUDE.md** (C3): the Invariants bullet replaced by design §2.5's text, word for word:
  > **Files move only in a batch the user started:** a move batch (tidy-up, the Playlists save question, a folder
  > rename on disk) or an AIFF batch (Same track, Convert to AIFF, Give it its clean name, Upgrade all, Make all
  > lossless files AIFF), logged in `library.db` and undoable. The sync itself never moves a file (option A), with one
  > exception: **Auto-upgrade**, a switch that is on by default and shown in Setup and Settings, is the user's
  > standing go for Same track on upgrades that need no decision (a measured same edit) while it is on. The sync then
  > runs them as one AIFF batch at its end, only while rekordbox is closed, with the same backup, journal and undo as
  > a batch started by hand. Switched off, the sync moves no file.

  "Moving never renames": §0.14's sentence. Layout: a row for `discjockey/auto_upgrade.py` ("the sync's last phase,
  Auto-upgrade: which upgrades, the rekordbox check, one AIFF batch, the `auto_refused`/`auto_waits` records"); the
  `batches.py` row names `end_auto` and the `auto_upgrade` starter; `run.py`'s row "… and, with the switch on, its
  Auto-upgrade phase".
- **README** (C3): Upgrades: "Upgrade automatically when I sync" (what it does, on by default, only same-edit
  upgrades, only while rekordbox is closed, the waiting mark, a refusal waits until rekordbox analyses the track
  again, Undo one or "Undo all from this sync", how to turn it off in Settings › Upgrades or `discjockey settings
  auto-upgrade off`); rekordbox: Discjockey now also changes its library at the end of a sync while the switch is on;
  the console: the sync's `--json`; Setup: the switch in the Downloads step.
- **Contract** (C4), **design language**: no block changes; if U1/U2 must change a block after all, that commit
  updates the design language and the gallery.
- **Design corrections** (C3 commits them into the design doc, each with "corrected in stage C; plan §0.n"): §2.2's
  "never eligible: refused before by Auto-upgrade" applies to the phase only (§0.8); §2.5's record shape and hold
  rule (§0.6, §0.7); §10's sync `--json` (§0.10, §1.6); §5.12 auto batches closed, not resumed (§0.5); §9.2's Setup
  place (§0.11).
- **Issues** (V): issue 33: "stage C merged (`<sha>`), live test pending (plan stage C §9); stages D–E open". Issue
  39: the sync's `--json` and `settings auto-upgrade` are in. A finding out of scope goes into `docs/issues.md`.
- **Archive:** this plan moves to `docs/archive/` when its live test passes; the design stays until the last stage.

---

## 9. The user's live test (about 10 minutes; only what needs a person with rekordbox)

On the throwaway click tracks of stage B's test (or two new ones: one MP3, one AIFF, each with hot cues), each with a
parked same-edit upgrade, rekordbox backed up first (File › Library › Backup):
1. rekordbox open, Sync: the before-start line shows; the sync ends with "… wait for rekordbox to be closed"; To-do
   marks both. Nothing changed in rekordbox.
2. rekordbox closed, Sync: both upgraded; the end screen's Upgraded list and summary line; rekordbox shows the AIFF
   with its cues; To-do's card says "Undo all from this sync".
3. "Undo all from this sync": both back with their cues in rekordbox.
4. Settings › Upgrades off, Sync with an upgrade waiting: nothing moves.
After it passes: release on the user's go.
