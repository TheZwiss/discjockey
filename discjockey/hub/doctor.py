"""`doctor` (issue 39, design §5.3): every check of the setup, the machine and the library, each problem with what to do
next. Pure: `CliApi.doctor` gathers the facts into `Inputs` (it is the one that reads the machine, the records and
rekordbox), `answer` runs the checks on them and puts the findings in the engine's words (`discjockey/words.py`), so a
check is tested with plain values and nothing in this module opens a file, a database or a lock.

A check yields problems; a problem is `problem` (something to fix) or `note` (worth knowing, nothing to fix). Each is
told with `next` (commands that look further or move on) and `person_steps` (what only the person can do, from
`outcomes.STEPS`). A check that needs the library is `skipped` while no music folder is bound: `music_folder` says why. A check
that reads the library's records is `skipped` too while library.db cannot be read: `records` says why.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from .. import words
from ..accounts import ACCOUNTS, SERVICE_NAMES, SERVICES
from ..scanner import volume_of
from .outcomes import person_step

LOST_DAYS = 7  # a job that stopped without finishing counts for this long (the registry keeps jobs for 30 days)


class JobRow(NamedTuple):
    """One job of the registry, as far as `doctor` needs it."""
    id: str
    status: str
    started: str  # an ISO time


@dataclass(frozen=True)
class Inputs:
    """The facts the checks read, gathered by `CliApi.doctor`. Library facts keep their empty value while no music
    folder is bound; the checks that read them are skipped then."""
    music_state: str  # "ok", "not_chosen" or "missing" (`HubApi._music_status`)
    music_path: str  # the folder chosen or bound; "" when none is chosen
    missing_tools: tuple[tuple[str, str], ...]  # (program, the command that installs it), the programs that are not there
    downloads: Mapping[str, Any]  # `views.downloads`: each source's state and last login check
    paused_accounts: frozenset[str]  # account services paused today, counting the signs waiting for the library lock
    unreadable_folders: tuple[str, ...]  # roots (music folder, watched folders, rekordbox's folder) macOS does not let us list
    app: str  # the app macOS charges for this command's folder access (`words.running_app`)
    rekordbox_state: str  # "ready", "none" or "unreadable" (`rekordbox.Status`)
    rekordbox_problem: str | None  # `unclean`, `busy`, `key`, `db_version`, `schema`
    lock_holder: Mapping[str, Any] | None  # `Jobs.console_holder`: who holds the library lock besides this process
    jobs: tuple[JobRow, ...]  # the registry's jobs of this music folder (and those with none), newest first
    now: datetime
    pending: bool  # a file step was cut off (`db.has_pending`)
    away_folders: tuple[str, ...]  # watched folders on a drive that isn't connected, or gone
    tidy_rows: int  # files the playlist order would put elsewhere (`planner.tidy_rows`)
    superseded_files: int  # files under Superseded/
    superseded_bytes: int  # and their size together
    rekordbox_match: Mapping[str, int] | None  # `rekordbox match`'s counts; None: no rekordbox library to compare, or unreadable
    stopped_batches: tuple[str, ...]  # typed ids (`aiff:2`) of the AIFF batches whose state is `stopped`
    check_tracks: int  # tracks with an open rekordbox check (To-do's `check_tracks`)
    cdj_files: int  # To-do's CDJ group
    missing_files: int  # To-do's Missing files group
    upgrades_ready: int  # To-do's Upgrade ready group
    to_load: int  # playlist songs the next sync would download (the Dashboard's "still to load"; 0 before a first read)
    records_problem: str | None = None  # the words of the failure when library.db cannot be read; the facts above that come from it are empty
    rekordbox_match_why: str | None = None  # why `rekordbox_match` is None while a rekordbox library is there (a writer, busy, unreadable)


def failed_logins(downloads: Mapping[str, Any]) -> list[str]:
    """The services whose login is set up and whose last check failed, in quality order. Qobuz: a failed check (a
    skipped Qobuz has none that counts); an account: its state says the saved browser's login is not usable, or its last
    check failed."""
    def failed(check: Mapping[str, Any] | None) -> bool:
        return bool(check) and not check["ok"]

    found = []
    qobuz = downloads.get("qobuz") or {}
    if qobuz.get("state") != "skipped" and failed(qobuz.get("last_check")):
        found.append("qobuz")
    for service in ACCOUNTS:
        account = downloads.get(service) or {}
        if account.get("state") in ("unreadable", "no_premium") or failed(account.get("last_check")):
            found.append(service)
    return found


def paused_services(downloads: Mapping[str, Any], paused_accounts: frozenset[str]) -> list[str]:
    """The services paused today, in quality order: a source whose card says `paused` and the account signs still
    waiting for the library lock."""
    return [s for s in SERVICES if (downloads.get(s) or {}).get("state") == "paused" or s in paused_accounts]


def lost_jobs(jobs: Sequence[JobRow], now: datetime) -> list[JobRow]:
    """The jobs that stopped without finishing in the last `LOST_DAYS` days, in the order given (newest first)."""
    since = _aware(now) - timedelta(days=LOST_DAYS)
    found = []
    for job in jobs:
        try:
            started = _aware(datetime.fromisoformat(job.started))
        except ValueError:
            continue  # without a time it cannot be told to be this week's
        if job.status == "lost" and started >= since:
            found.append(job)
    return found


def _aware(moment: datetime) -> datetime:
    return moment if moment.tzinfo else moment.astimezone()


def _next(run: str, why: str) -> dict:
    return {"run": run, "why": why}


def _problem(text: str, *, level: str = "problem", count: int | None = None, next: Sequence[dict] = (),
             steps: Sequence[dict] = ()) -> dict:
    return {"level": level, "text": text, "count": count, "next": list(next), "person_steps": list(steps)}


# --- the checks: `Inputs` -> the problems of one check ---

def _music_folder(i: Inputs) -> list[dict]:
    if i.music_state == "ok":
        return []
    if i.music_state == "not_chosen":
        return [_problem(words.NOT_CHOSEN, next=[_next("setup status", words.DOCTOR_WHY_SETUP)])]
    return [_problem(words.MISSING.format(path=i.music_path), steps=[_whereabouts_step(i.music_path)])]


def _whereabouts_step(path: str) -> dict:
    """What only the person can do for a folder that is not there: connect its drive, or, for a folder on no external
    drive (moved or deleted), put it back."""
    drive = volume_of(Path(path))
    return person_step("connect_drive", drive=drive) if drive else person_step("folder_gone", folder=path)


def _tools(i: Inputs) -> list[dict]:
    if not i.missing_tools:
        return []
    hints = dict.fromkeys(hint for _, hint in i.missing_tools)  # one step per command, in order
    return [_problem(words.DOCTOR_TOOLS.format(tools=", ".join(tool for tool, _ in i.missing_tools)),
                     steps=[person_step("install_tools", hint=hint) for hint in hints])]


def _logins(i: Inputs) -> list[dict]:
    # V4.7 makes the next `login check <service>`
    return [_problem(words.DOCTOR_LOGIN.format(service=SERVICE_NAMES[service]),
                     next=[_next("login list", words.DOCTOR_WHY_LOGINS)]) for service in failed_logins(i.downloads)]


def _folder_access(i: Inputs) -> list[dict]:
    return [_problem(words.DOCTOR_ACCESS.format(folder=folder),
                     steps=[person_step("folder_access", app=i.app, folder=folder)]) for folder in i.unreadable_folders]


def _rekordbox(i: Inputs) -> list[dict]:
    state, problem = i.rekordbox_state, i.rekordbox_problem
    if state == "none" or not (problem or state == "unreadable"):
        return []  # no rekordbox library to check, or one that reads
    state_text, problem_text = words.rekordbox_words(state, problem)
    next_ = [_next("rekordbox status", words.DOCTOR_WHY_REKORDBOX)]
    if problem == "unclean":
        next_.append(_next("rekordbox backups", words.DOCTOR_WHY_BACKUPS))
    return [_problem(problem_text or state_text, level="note" if problem == "busy" else "problem", next=next_)]


def _stale_lock(i: Inputs) -> list[dict]:
    holder = i.lock_holder
    if holder is None or holder.get("job") is not None:
        return []  # nobody, or a job the registry names (the window and `job list` say it)
    return [_problem(words.DOCTOR_FOREIGN_LOCK.format(text=holder["text"]), level="note",
                     next=[_next("job list --all", words.DOCTOR_WHY_JOBS)])]


def _lost_jobs(i: Inputs) -> list[dict]:
    lost = lost_jobs(i.jobs, i.now)
    if not lost:
        return []
    return [_problem(words.plural(len(lost), *words.DOCTOR_LOST), count=len(lost),
                     next=[_next(f"job show {lost[0].id}", words.DOCTOR_WHY_LOST)])]


def _records(i: Inputs) -> list[dict]:
    if not i.records_problem:
        return []
    return [_problem(f"{i.records_problem} {words.DOCTOR_RECORDS_SKIPPED}",
                     next=[_next("where", words.DOCTOR_WHY_RECORDS)])]


def _pending_steps(i: Inputs) -> list[dict]:
    if not i.pending:
        return []
    return [_problem(words.DOCTOR_PENDING, next=[_next("library scan", words.DOCTOR_WHY_SCAN)])]


def _drives_away(i: Inputs) -> list[dict]:
    if not i.away_folders:
        return []
    gone = sum(volume_of(Path(path)) is None for path in i.away_folders)  # on no drive: moved or deleted
    text = " ".join(words.plural(n, *forms)
                    for n, forms in ((len(i.away_folders) - gone, words.DOCTOR_AWAY), (gone, words.DOCTOR_GONE)) if n)
    steps: dict[str, dict] = {}  # one step per drive and per folder that is gone, in the order of the folders
    for path in i.away_folders:
        step = _whereabouts_step(path)
        steps.setdefault(step["say"], step)
    return [_problem(text, count=len(i.away_folders), steps=list(steps.values()))]


def _downloads_paused(i: Inputs) -> list[dict]:
    paused = paused_services(i.downloads, i.paused_accounts)
    if not paused:
        return []
    return [_problem(words.DOCTOR_PAUSED.format(services=", ".join(SERVICE_NAMES[s] for s in paused)), level="note",
                     next=[_next(f"limits show {s}", words.DOCTOR_WHY_LIMITS) for s in paused])]


def _out_of_place(i: Inputs) -> list[dict]:
    if not i.tidy_rows:
        return []
    return [_problem(words.plural(i.tidy_rows, *words.DOCTOR_OUT_OF_PLACE), level="note", count=i.tidy_rows,
                     next=[_next("tidy run --dry-run", words.DOCTOR_WHY_TIDY)])]


def _superseded(i: Inputs) -> list[dict]:
    if not i.superseded_files:
        return []
    return [_problem(words.doctor_superseded(i.superseded_files, i.superseded_bytes), level="note",
                     count=i.superseded_files, next=[_next("library superseded", words.DOCTOR_WHY_SUPERSEDED)])]


def _rekordbox_files(i: Inputs) -> list[dict]:
    if i.rekordbox_match is None:  # rekordbox could not be compared: say so, never read it as "everything matches"
        if not i.rekordbox_match_why:
            return []  # no rekordbox library here: nothing to compare
        return [_problem(words.DOCTOR_RB_NOT_COMPARED.format(why=i.rekordbox_match_why), level="note",
                         next=[_next("rekordbox status", words.DOCTOR_WHY_NOT_COMPARED)])]
    n = i.rekordbox_match["missing"] + i.rekordbox_match["superseded"]
    if not n:
        return []
    return [_problem(words.plural(n, *words.DOCTOR_RB_FILES), count=n,
                     next=[_next("rekordbox match", words.DOCTOR_WHY_MATCH)])]


def _stopped_batches(i: Inputs) -> list[dict]:
    if not i.stopped_batches:
        return []
    next_ = [_next(f"batch resume {b}", words.DOCTOR_WHY_RESUME) for b in i.stopped_batches]  # an AIFF batch goes on where it stopped
    return [_problem(words.plural(len(i.stopped_batches), *words.DOCTOR_STOPPED), count=len(i.stopped_batches),
                     next=next_)]


def _open_checks(i: Inputs) -> list[dict]:
    if not i.check_tracks:
        return []
    return [_problem(words.plural(i.check_tracks, *words.DOCTOR_CHECKS), level="note", count=i.check_tracks,
                     next=[_next("check list", words.DOCTOR_WHY_CHECKS)])]


def _cdj(i: Inputs) -> list[dict]:
    if not i.cdj_files:
        return []
    return [_problem(words.plural(i.cdj_files, *words.DOCTOR_CDJ), level="note", count=i.cdj_files,
                     next=[_next("todo list --group cdj", words.DOCTOR_WHY_CDJ)])]


def _songs_without_file(i: Inputs) -> list[dict]:
    found = []
    if i.missing_files:
        found.append(_problem(words.plural(i.missing_files, *words.DOCTOR_MISSING_FILES), level="note",
                              count=i.missing_files, next=[_next("missing list", words.DOCTOR_WHY_MISSING)]))
    if i.to_load:
        found.append(_problem(words.plural(i.to_load, *words.DOCTOR_TO_LOAD), level="note", count=i.to_load,
                              next=[_next("sync plan", words.DOCTOR_WHY_SYNC_PLAN)]))
    return found


def _upgrades_waiting(i: Inputs) -> list[dict]:
    if not i.upgrades_ready:
        return []
    return [_problem(words.plural(i.upgrades_ready, *words.DOCTOR_UPGRADES), level="note", count=i.upgrades_ready,
                     next=[_next("upgrade list", words.DOCTOR_WHY_UPGRADES)])]


@dataclass(frozen=True)
class Check:
    key: str  # `words.DOCTOR_LABELS` says what it looks at
    gig: bool  # what the next gig depends on (`status --ready` lists these)
    needs_library: bool  # skipped while no music folder is bound
    run: Callable[[Inputs], list[dict]]
    reads_records: bool = False  # skipped while library.db cannot be read (`records` says why)

    @property
    def label(self) -> str:
        return words.DOCTOR_LABELS[self.key]


CHECKS: tuple[Check, ...] = (
    Check("music_folder", True, False, _music_folder),
    Check("tools", False, False, _tools),
    Check("logins", False, False, _logins),
    Check("folder_access", True, False, _folder_access),
    Check("rekordbox", True, False, _rekordbox),
    Check("stale_lock", False, False, _stale_lock),
    Check("lost_jobs", False, False, _lost_jobs),
    Check("records", True, True, _records),
    Check("pending_steps", True, True, _pending_steps, reads_records=True),
    Check("drives_away", True, True, _drives_away, reads_records=True),
    Check("downloads_paused", False, True, _downloads_paused, reads_records=True),
    Check("out_of_place", False, True, _out_of_place, reads_records=True),
    Check("superseded", False, True, _superseded),
    Check("rekordbox_files", True, True, _rekordbox_files, reads_records=True),
    Check("stopped_batches", True, True, _stopped_batches, reads_records=True),
    Check("open_checks", True, True, _open_checks, reads_records=True),
    Check("cdj", True, True, _cdj, reads_records=True),
    Check("songs_without_file", True, True, _songs_without_file, reads_records=True),
    Check("upgrades_waiting", True, True, _upgrades_waiting, reads_records=True),
)


def answer(inputs: Inputs, library: bool) -> dict:
    """`Doctor`: the problems (problems first, then notes, each in check order), one line per check, and the sentence.
    `library`: a music folder is bound; the checks that need it are `skipped` without, and so are those that read the
    records while `inputs.records_problem` says they cannot be read."""
    found: list[dict] = []
    checks: list[dict] = []
    for check in CHECKS:
        if (check.needs_library and not library) or (check.reads_records and inputs.records_problem):
            checks.append({"check": check.key, "label": check.label, "state": "skipped"})
            continue
        problems = [{"check": check.key, "level": p["level"], "gig": check.gig, **{k: v for k, v in p.items() if k != "level"}}
                    for p in check.run(inputs)]
        found += problems
        levels = {p["level"] for p in problems}
        checks.append({"check": check.key, "label": check.label,
                       "state": "problem" if "problem" in levels else "note" if levels else "ok"})
    ordered = [p for p in found if p["level"] == "problem"] + [p for p in found if p["level"] == "note"]
    return {"text": words.doctor_text(sum(p["level"] == "problem" for p in found), sum(p["level"] == "note" for p in found)),
            "problems": ordered, "checks": checks}
