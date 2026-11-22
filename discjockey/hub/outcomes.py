"""One table for every answer's outcome (issue 39, design §4.3): the exit numbers, the closed list of reasons with
their words, the map from the bridge's problem kinds to an outcome, which outcome wins when several apply, and the
steps only a person can do. The bridge decorator and the command line both read it, so a command line answer and the
window's say the same thing: the window keeps `{ok, kind, message}` and gets `outcome`, `reason`, `next`,
`person_steps` and `data` beside them."""
from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from .. import missing
from ..problem import Problem
from ..rekordbox.eligible import REASONS as ITEM_REASONS
from ..rekordbox.preview import REASON_WORDS as ITEM_REASON_WORDS

VERSION = 1
NO_AS_OF = {"scanned_at": None, "read_at": None}
EXIT = {"ok": 0, "failed": 1, "bad_args": 2, "busy": 3, "needs_person": 4, "stopped": 5, "partial": 6, "refused": 7,
        "running": 8}

# When several outcomes apply to one command (several items, several problems), the first of these wins; `partial`
# is what is left when some items were done and others ended in a state the command counts as partial.
DONE_STATES = ("done", "undone")  # an item's states that mean it went through (an undo's is `undone`)
PRECEDENCE = ("bad_args", "busy", "refused", "needs_person", "stopped", "failed", "partial", "ok")


@dataclass(frozen=True)
class Reason:
    outcome: str
    text: str  # one plain sentence a DJ understands


def _group(outcome: str, words: Mapping[str, str]) -> dict[str, Reason]:
    return {key: Reason(outcome, text) for key, text in words.items()}


REASONS: dict[str, Reason] = {
    **_group("failed", {
        "crashed": "Discjockey stopped unexpectedly. Nothing was left half-done.",
        "offline": "Discjockey could not reach the internet or the service.",
        "ffmpeg": "Discjockey's audio tool (ffmpeg) could not do this.",
        "service_error": "The service answered with an error. Try again later.",
        "qobuz_login_failed": "Qobuz did not accept the saved login.",
        "login_failed": "The service did not accept the saved login.",
        "playlist_unreadable": "Discjockey could not read this playlist.",
        "config_invalid": "A settings or records file of Discjockey is damaged or from another version.",
        "worker_lost": "The job's process ended without saying how it went. Nothing was left half-done.",
        "failed": "It did not work. What was done before stays as it was.",
    }),
    **_group("bad_args", {
        "usage": "The command line is not right. Nothing was looked at.",
        "unknown_id": "There is nothing with that id.",
        "bad_id_kind": "That id names a different kind of thing than this command takes.",
        "conflicting_flags": "Two of the options say opposite things.",
    }),
    **_group("busy", {
        "library_lock": "Another Discjockey job is working on your music folder. Wait until it has finished.",
        "rekordbox_lock": "Another Discjockey window or terminal is changing your rekordbox library.",
        "support_lock": "Another Discjockey process is saving its own settings. Try again in a moment.",
        "import_running": "An import is running. Wait until it has finished.",
        "sync_running": "A sync is running. Wait until it has finished.",
        "console": "A run in the terminal holds your music folder. Wait until it has finished.",
    }),
    **_group("needs_person", {
        "rekordbox_open": "rekordbox is open. Quit rekordbox, then try again.",
        "login_needed": "A login is needed first.",
        "login_expired": "The saved login has run out. Log in again.",
        "keychain": "macOS asked for permission to read a saved password, and the person has to answer.",
        "folder_access": "macOS has not let Discjockey open that folder yet.",
        "full_disk_access": "Discjockey needs Full Disk Access in System Settings.",
        "drive_missing": "The drive is not connected.",
        "browser_sign_in": "Sign in to the service in the browser first.",
    }),
    **_group("stopped", {
        "stop": "Stopped. The steps finished so far stay finished.",
        "stop_now": "Stopped at once. The steps finished so far stay finished.",
    }),
    **_group("refused", {
        "no_library": "There is no music folder to work in yet, or it is not there.",
        "not_set_up": "This needs a setup step that is not done yet.",
        "needs_yes": "This changes things, so it needs --yes. Nothing was done.",
        "changed": "Things changed since the plan was made, so nothing was done.",
        "rev_changed": "This song changed since it was read, so nothing was done. Read it again for its new rev.",
        "not_stopped": "That job is not stopped, so it cannot be carried on.",
        "not_running": "Nothing is running, so there is nothing to stop.",
        "plan_expired": "That plan is more than a day old. Make a new one.",
        "setting_off": "A choice in Settings that this needs is off.",
        "facts_missing": "Discjockey does not know enough about the files yet. Run a sync or a scan first.",
        "window_job": "That job belongs to the window, so only the window can do this to it.",
        "exists": "There is something with that name already.",
        "protected": "This is protected, so Discjockey will not change it.",
        "pending_steps": "Steps for the person are still open. Do them first.",
        "no_clone": "This drive cannot make a copy of the music folder.",
        "not_sandbox_content": "That is not part of the practice library.",
        "outside_sandbox": "That is outside the practice library.",
        "sandbox_required": "This only runs in a practice library.",
        "sandbox_no_accounts": "The practice library has no logins to use.",
        "refused": "The rules say no, so nothing was done.",
    }),
    **_group("running", {
        "still_running": "The job is still running. It goes on by itself.",
    }),
}

# The reasons of one item (`rekordbox.eligible.REASONS`) are `refused` for that item. The keys come by reference; the
# words are the preview's own (lower-case pieces of a sentence) made into a sentence. A key the list above has
# already (`changed`, `rekordbox_open`) keeps its row there.
for _key in ITEM_REASONS:
    if _key not in REASONS:
        _words = ITEM_REASON_WORDS[_key]
        REASONS[_key] = Reason("refused", _words[0].upper() + _words[1:] + ".")

# The reasons of a missing file's action (issue 43, `missing.why_not`): `refused` for that song. The command line's
# result rows say them with the action filled in (`missing.reason_words`); here `wrong_action` names no action.
for _key, _text in missing.REASONS.items():
    if _key != "away":  # `away` is the rekordbox rows' key too (its words stay: this module's row is the same outcome)
        REASONS[_key] = Reason("refused", _text.format(other="the other action"))

# Every bridge ProblemKind (types.ts PROBLEM_KINDS) is one row, and the kind is that row's reason (`KIND_REASON`).
KIND_OUTCOME = {
    "busy": "busy", "console": "busy", "sync_running": "busy",
    "not_set_up": "refused", "no_library": "refused", "setting_off": "refused", "exists": "refused",
    "changed": "refused", "refused": "refused", "protected": "refused",
    "login_expired": "needs_person", "rekordbox_open": "needs_person",
    "offline": "failed", "playlist_unreadable": "failed", "config_invalid": "failed", "qobuz_login_failed": "failed",
    "login_failed": "failed", "failed": "failed", "crashed": "failed",
    "stopped": "stopped",
}

# The reason a problem kind stands for when whoever raised it named none: the kind itself, except `busy` (the hub's
# own job holds the library: library_lock) and `stopped` (stop).
KIND_REASON = {**{kind: kind for kind in KIND_OUTCOME}, "busy": "library_lock", "stopped": "stop"}


@dataclass(frozen=True)
class Step:
    say: str   # a template; its fields are named in `person_step`'s call
    then: str | None  # the command to run once the person did it; None: run the same command again


STEPS: dict[str, Step] = {
    "quit_rekordbox": Step("Quit rekordbox, then tell me to carry on.", None),
    "relocate_new": Step("In rekordbox, relocate {tracks} to the new file.", "check done {tracks}"),
    "reload_tag": Step("In rekordbox, reload the tags of {tracks}.", "check done {tracks}"),
    "look": Step("In rekordbox, have a look at {tracks}.", "check done {tracks}"),
    "folder_access": Step("Allow {app} to open {folder}: answer the macOS question, or turn it on in System Settings "
                          "› Privacy & Security › Files and Folders.", None),
    "connect_drive": Step("Connect the drive {drive}.", None),
    "install_tools": Step("Paste `{hint}` into the Terminal.", "tools status"),
}


def person_step(name: str, **fields: str) -> dict:
    """`{"id": "step:<name>", "say", "then"}` for one of `STEPS`, its templates filled with `fields`."""
    step = STEPS[name]
    return {"id": f"step:{name}", "say": step.say.format(**fields), "then": step.then.format(**fields) if step.then else None}


def pick(outcomes: Iterable[str]) -> str:
    """The outcome that wins when several apply (`PRECEDENCE`); `ok` for none."""
    found = set(outcomes)
    unknown = found - set(PRECEDENCE)
    if unknown:
        raise ValueError(f"no precedence for outcome {sorted(unknown)[0]!r}")
    return next((o for o in PRECEDENCE if o in found), "ok")


def run_outcome(results: Iterable[Mapping] | None, partial: Iterable[str]) -> str:
    """`ok`, or `partial` when a finished run has an item in a state its command counts (the catalogue's `partial`
    column, design §4.3, R24): never `ok` with the failures hidden, never `failed` for a run that did the rest. A run
    in which no item was done and at least one failed is `failed`: `partial` is for a run that did some and not all."""
    states = set(partial)
    rows = list(results or ())
    if not any(r.get("state") in states for r in rows):
        return "ok"
    if not any(r.get("state") in DONE_STATES for r in rows) and any(r.get("state") == "failed" for r in rows):
        return "failed"
    return "partial"


def problem_fields(kind: str, error: BaseException | None = None) -> dict:
    """What the bridge adds beside `{ok, kind, message}` for a problem of `kind`: `outcome`, `reason`, `next`,
    `person_steps`, `data`. `error` is what was raised: a `Problem` carries its own reason, next, person steps and
    data; any other exception gets the kind's defaults. A kind the table lacks is a crash (`failed`)."""
    if kind not in KIND_OUTCOME:
        kind = "crashed"
    outcome = KIND_OUTCOME[kind]
    carried = error if isinstance(error, Problem) else None  # other exceptions may have fields of their own names
    reason = getattr(carried, "reason", None)
    if reason not in REASONS or REASONS[reason].outcome != outcome:  # a reason of another row says nothing here
        reason = KIND_REASON[kind]
    person_steps = list(getattr(carried, "person_steps", None) or ())
    if not person_steps and kind == "rekordbox_open":
        person_steps = [person_step("quit_rekordbox")]
    return {"outcome": outcome, "reason": reason, "next": list(getattr(carried, "next", None) or ()),
            "person_steps": person_steps, "data": getattr(carried, "data", None)}


_OUTCOME_PROBLEM = {"failed": "failed", "refused": "refused", "busy": "busy", "stopped": "stopped",
                    "needs_person": "refused", "bad_args": "refused"}


def finished_problem(envelope: Mapping) -> str | None:
    """The problem kind (`JobFinished.problem`) a job's `result.json` stands for, as the window would have said it:
    None for `ok` and `partial`. The envelope's `reason` when it is a bridge problem kind; the lock's and the stop
    reasons by their kinds; else the outcome's own kind."""
    outcome = envelope.get("outcome")
    if outcome in ("ok", "partial"):
        return None
    reason = envelope.get("reason")
    if reason in KIND_OUTCOME:
        return reason
    if reason == "library_lock":
        return "busy"
    if reason in ("stop", "stop_now"):
        return "stopped"
    return _OUTCOME_PROBLEM.get(outcome, "failed")


def envelope(command: str, outcome: str, *, reason: str | None = None, message: str | None = None,
             data: Mapping | None = None, page: Mapping | None = None, next: Iterable[Mapping] = (), person_steps: Iterable[Mapping] = (),
             recovered: Iterable[Mapping] = (), job: str | None = None, as_of: Mapping | None = None,
             sandbox: str | None = None) -> dict:
    """The envelope (design §4.1), its keys in design order: what `--json` prints for a command and what a job's
    `result.json` holds, the window's jobs too. `recovered` is always a list, `as_of` always has both keys. `page` is
    null, or says which list of `data` was cut to a page (`cli/call.py` `paged`: `list`, `offset`, `limit`, `total`,
    `next_offset`)."""
    if outcome not in EXIT:
        raise ValueError(f"no such outcome {outcome!r}")
    if reason is not None and reason not in REASONS:
        raise ValueError(f"no such reason {reason!r}")
    return {"v": VERSION, "command": command, "outcome": outcome, "reason": reason, "message": message,
            "data": dict(data) if data is not None else None, "page": dict(page) if page is not None else None,
            "next": [dict(n) for n in next],
            "person_steps": [dict(s) for s in person_steps], "recovered": [dict(r) for r in recovered], "job": job,
            "as_of": {**NO_AS_OF, **(as_of or {})}, "sandbox": sandbox}
