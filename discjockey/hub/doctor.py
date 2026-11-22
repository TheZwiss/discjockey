"""`doctor` (issue 39, design §5.3): every check of the setup, the machine and the library, each problem with what to do
next. Pure: `CliApi.doctor` gathers the facts into `Inputs` (it is the one that reads the machine, the records and
rekordbox), `answer` runs the checks on them and puts the findings in the engine's words (`discjockey/words.py`), so a
check is tested with plain values and nothing in this module opens a file, a database or a lock.

A check yields problems; a problem is `problem` (something to fix) or `note` (worth knowing, nothing to fix). Each is
told with `next` (commands that look further or move on) and `person_steps` (what only the person can do, from
`outcomes.STEPS`). A check that needs the library is `skipped` while no music folder is bound: `music_folder` says why.
"""
from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, NamedTuple

from .. import words
from ..accounts import ACCOUNTS, SERVICE_NAMES, SERVICES
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


def drive_name(path: str) -> str:
    """The drive a path is on, as the person knows it: the `/Volumes/<name>` part; any other path is its own name."""
    parts = Path(path).parts
    return parts[2] if len(parts) >= 3 and parts[:2] == ("/", "Volumes") else path


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
    return [_problem(words.MISSING.format(path=i.music_path),
                     steps=[person_step("connect_drive", drive=drive_name(i.music_path))])]


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


def _pending_steps(i: Inputs) -> list[dict]:
    if not i.pending:
        return []
    return [_problem(words.DOCTOR_PENDING, next=[_next("library scan", words.DOCTOR_WHY_SCAN)])]


def _drives_away(i: Inputs) -> list[dict]:
    if not i.away_folders:
        return []
    drives = dict.fromkeys(drive_name(path) for path in i.away_folders)
    return [_problem(words.plural(len(i.away_folders), *words.DOCTOR_AWAY), count=len(i.away_folders),
                     steps=[person_step("connect_drive", drive=drive) for drive in drives])]


def _downloads_paused(i: Inputs) -> list[dict]:
    paused = paused_services(i.downloads, i.paused_accounts)
    if not paused:
        return []
    return [_problem(words.DOCTOR_PAUSED.format(services=", ".join(SERVICE_NAMES[s] for s in paused)), level="note",
                     next=[_next(f"limits show {s}", words.DOCTOR_WHY_LIMITS) for s in paused])]


@dataclass(frozen=True)
class Check:
    key: str
    label: str
    gig: bool  # what the next gig depends on (`status --ready` lists these)
    needs_library: bool  # skipped while no music folder is bound
    run: Callable[[Inputs], list[dict]]


CHECKS: tuple[Check, ...] = (
    Check("music_folder", "Music folder", True, False, _music_folder),
    Check("tools", "Programs", False, False, _tools),
    Check("logins", "Logins", False, False, _logins),
    Check("folder_access", "Folder access", True, False, _folder_access),
    Check("rekordbox", "rekordbox", True, False, _rekordbox),
    Check("stale_lock", "Library lock", False, False, _stale_lock),
    Check("lost_jobs", "Jobs", False, False, _lost_jobs),
    Check("pending_steps", "Cut-off steps", True, True, _pending_steps),
    Check("drives_away", "Drives", True, True, _drives_away),
    Check("downloads_paused", "Download limits", False, True, _downloads_paused),
)


def answer(inputs: Inputs, library: bool) -> dict:
    """`Doctor`: the problems (problems first, then notes, each in check order), one line per check, and the sentence.
    `library`: a music folder is bound; the checks that need it are `skipped` without."""
    found: list[dict] = []
    checks: list[dict] = []
    for check in CHECKS:
        if check.needs_library and not library:
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
