"""T8, the engine half (issue 39): the outcome table, the closed list of reasons, the precedence, and what the bridge
decorator adds to a problem."""
import itertools

import pytest

from discjockey import library
from discjockey.hub import outcomes, shapes
from discjockey.hub.api import bridge
from discjockey.hub.jobs import Busy
from discjockey.ops import OpProblem
from discjockey.rekordbox import eligible
from discjockey.rekordbox import lock as rb_lock


def problem_kinds_of_the_window() -> list[str]:
    """The kinds of the `ProblemKind` alias: the window's `PROBLEM_KINDS` is generated from it (hub/shapes/common.py)."""
    return list(shapes.values("ProblemKind"))


def test_every_problem_kind_of_the_window_has_an_outcome():
    kinds = problem_kinds_of_the_window()
    assert len(kinds) == 20
    assert set(kinds) == set(outcomes.KIND_OUTCOME)
    for kind in kinds:
        assert outcomes.KIND_OUTCOME[kind] in outcomes.EXIT


def test_the_kinds_follow_the_design_bullet():
    got = {}
    for kind, outcome in outcomes.KIND_OUTCOME.items():
        got.setdefault(outcome, set()).add(kind)
    assert got == {
        "busy": {"busy", "console", "sync_running"},
        "refused": {"not_set_up", "no_library", "setting_off", "exists", "changed", "refused", "protected"},
        "needs_person": {"login_expired", "rekordbox_open"},
        "failed": {"offline", "playlist_unreadable", "config_invalid", "qobuz_login_failed", "login_failed", "failed",
                   "crashed"},
        "stopped": {"stopped"}}


def test_every_kind_stands_for_a_reason_of_its_own_outcome():
    for kind, outcome in outcomes.KIND_OUTCOME.items():
        reason = outcomes.KIND_REASON[kind]
        assert outcomes.REASONS[reason].outcome == outcome, kind


def test_exit_numbers():
    assert outcomes.EXIT == {"ok": 0, "failed": 1, "bad_args": 2, "busy": 3, "needs_person": 4, "stopped": 5,
                             "partial": 6, "refused": 7, "running": 8}


def test_every_reason_belongs_to_one_outcome_with_words():
    for key, reason in outcomes.REASONS.items():
        assert reason.outcome in outcomes.EXIT and reason.outcome not in ("ok", "partial"), key
        assert reason.text.endswith(".") and len(reason.text) > 10, key
    assert "nothing_to_do" not in outcomes.REASONS


def test_the_closed_list_of_the_design():
    by_outcome = {}
    for key, reason in outcomes.REASONS.items():
        by_outcome.setdefault(reason.outcome, set()).add(key)
    assert by_outcome["failed"] == {"crashed", "offline", "ffmpeg", "service_error", "qobuz_login_failed", "login_failed",
                                    "playlist_unreadable", "config_invalid", "worker_lost", "failed"}
    assert by_outcome["bad_args"] == {"usage", "unknown_id", "bad_id_kind", "conflicting_flags"}
    assert by_outcome["busy"] == {"library_lock", "rekordbox_lock", "support_lock", "import_running", "sync_running",
                                  "console"}
    assert by_outcome["needs_person"] == {"rekordbox_open", "login_needed", "login_expired", "keychain", "folder_access",
                                          "full_disk_access", "drive_missing", "browser_sign_in"}
    assert by_outcome["stopped"] == {"stop", "stop_now"}
    assert by_outcome["running"] == {"still_running"}
    assert {"no_library", "needs_yes", "plan_expired", "sandbox_no_accounts", "refused"} <= by_outcome["refused"]
    assert {"rev_changed", "version_changed", "needs_choice"} <= by_outcome["refused"]  # a write's own refusals (issue 39 V4.2a)


def test_the_reasons_of_one_item_come_from_the_rekordbox_list():
    for key in eligible.REASONS:
        assert key in outcomes.REASONS
        if key not in ("rekordbox_open",):  # the design lists rekordbox_open as a reason for the whole command
            assert outcomes.REASONS[key].outcome == "refused", key


@pytest.mark.parametrize("a,b", itertools.combinations(outcomes.PRECEDENCE, 2))
def test_pick_follows_the_precedence_for_every_pair(a, b):
    assert outcomes.pick([a, b]) == a  # PRECEDENCE lists the winner first
    assert outcomes.pick([b, a]) == a


def test_pick_of_nothing_is_ok_and_of_unknown_is_an_error():
    assert outcomes.PRECEDENCE == ("bad_args", "busy", "refused", "needs_person", "stopped", "failed", "partial", "ok")
    assert outcomes.pick([]) == "ok"
    assert outcomes.pick(["ok", "ok"]) == "ok"
    with pytest.raises(ValueError):
        outcomes.pick(["running"])


def test_a_step_with_no_command_of_its_own_has_a_null_then():
    """`then` is a command or None (run the same command again), never prose (C-13)."""
    for name, fields in (("quit_rekordbox", {}), ("folder_access", {"app": "A", "folder": "F"}),
                         ("connect_drive", {"drive": "D"})):
        assert outcomes.person_step(name, **fields)["then"] is None
    assert outcomes.person_step("relocate_new", tracks="t1")["then"] == "check done t1"
    assert outcomes.person_step("install_tools", hint="brew install ffmpeg")["then"] == "tools status"
    assert all(step.then is None or step.then.startswith(("check done", "tools status")) for step in outcomes.STEPS.values())


def test_person_step_fills_its_words():
    step = outcomes.person_step("folder_access", app="Discjockey", folder="Music")
    assert step["id"] == "step:folder_access"
    assert step["say"].startswith("Allow Discjockey to open Music")
    assert outcomes.person_step("quit_rekordbox") == {
        "id": "step:quit_rekordbox", "say": "Quit rekordbox, then tell me to carry on.", "then": None}
    assert set(outcomes.STEPS) == {"quit_rekordbox", "relocate_new", "reload_tag", "look", "folder_access", "connect_drive",
                                   "folder_gone", "install_tools"}


class Fake:
    @bridge
    def refused(self):
        raise OpProblem("No.", "refused", reason="needs_yes", next=[{"run": "x --yes", "why": "to go on"}],
                        data={"total": 2})

    @bridge
    def plain_refused(self):
        raise OpProblem("Nope.")

    @bridge
    def busy(self):
        raise Busy("A job runs.", "busy")

    @bridge
    def console(self):
        raise Busy("Terminal.", "console", data={"holder": {"via": "terminal"}})

    @bridge
    def rekordbox_lock(self):
        raise rb_lock.Busy()

    @bridge
    def lock_held(self):
        raise library.LockHeld()

    @bridge
    def boom(self):
        raise RuntimeError("secret detail")

    @bridge
    def fine(self):
        return {"n": 1}

    @bridge
    def wrong_arguments(self):
        raise TypeError("takes 1 positional argument")


def test_a_refused_problem_answers_with_its_outcome_reason_and_next():
    assert Fake().refused() == {
        "ok": False, "kind": "refused", "message": "No.", "outcome": "refused", "reason": "needs_yes",
        "next": [{"run": "x --yes", "why": "to go on"}], "person_steps": [], "data": {"total": 2}}


def test_a_problem_without_a_reason_gets_the_one_of_its_kind():
    got = Fake().plain_refused()
    assert (got["kind"], got["outcome"], got["reason"], got["next"], got["person_steps"], got["data"]) == (
        "refused", "refused", "refused", [], [], None)


def test_busy_answers_busy():
    got = Fake().busy()
    assert (got["kind"], got["outcome"], got["reason"]) == ("busy", "busy", "library_lock")
    got = Fake().console()
    assert (got["kind"], got["outcome"], got["reason"], got["data"]) == (
        "console", "busy", "console", {"holder": {"via": "terminal"}})


def test_the_rekordbox_and_library_locks_name_their_reason():
    got = Fake().rekordbox_lock()
    assert (got["kind"], got["outcome"], got["reason"]) == ("busy", "busy", "rekordbox_lock")
    got = Fake().lock_held()
    assert (got["kind"], got["outcome"], got["reason"]) == ("console", "busy", "console")


def test_a_crash_answers_failed_crashed_and_hides_the_detail(capsys):
    got = Fake().boom()
    assert (got["ok"], got["kind"], got["outcome"], got["reason"]) == (False, "crashed", "failed", "crashed")
    assert "secret detail" not in got["message"]
    got = Fake().wrong_arguments()
    assert (got["kind"], got["outcome"], got["reason"]) == ("crashed", "failed", "crashed")


def test_an_ok_answer_is_unchanged():
    assert Fake().fine() == {"ok": True, "n": 1}


def test_rekordbox_open_carries_the_quit_step():
    got = outcomes.problem_fields("rekordbox_open")
    assert got["outcome"] == "needs_person" and got["reason"] == "rekordbox_open"
    assert [s["id"] for s in got["person_steps"]] == ["step:quit_rekordbox"]


def test_a_reason_the_list_lacks_falls_back_to_the_kind():
    err = OpProblem("x", "changed", reason="not_a_reason")
    assert outcomes.problem_fields("changed", err)["reason"] == "changed"
    assert outcomes.problem_fields("never_heard_of")["outcome"] == "failed"


def test_a_run_that_did_nothing_and_failed_is_failed_and_a_run_that_did_some_is_partial():
    row = lambda state: {"state": state}
    partial = ("skipped", "failed")
    assert outcomes.run_outcome([row("done")], partial) == "ok"
    assert outcomes.run_outcome([row("done"), row("skipped")], partial) == "partial"
    assert outcomes.run_outcome([row("done"), row("failed")], partial) == "partial"
    assert outcomes.run_outcome([row("skipped"), row("failed")], partial) == "failed"  # nothing went through
    assert outcomes.run_outcome([row("failed")], partial) == "failed"
    assert outcomes.run_outcome([row("skipped")], partial) == "partial"  # nothing failed: not everything went through
    assert outcomes.run_outcome([row("undone"), row("failed")], ("refused", "failed")) == "partial"
    assert outcomes.run_outcome([row("refused"), row("failed")], ("refused", "failed")) == "failed"


@pytest.mark.parametrize("outcome, reason, problem", [
    ("ok", None, None), ("partial", None, None),  # a job that went through has no problem
    ("failed", "offline", "offline"), ("refused", "setting_off", "setting_off"), ("needs_person", "rekordbox_open", "rekordbox_open"),
    ("busy", "library_lock", "busy"), ("busy", "console", "console"), ("busy", "import_running", "busy"),
    ("stopped", "stop", "stopped"), ("stopped", "stop_now", "stopped"), ("stopped", None, "stopped"),
    ("failed", "worker_lost", "failed"), ("failed", None, "failed"), ("refused", "unknown_thing", "refused"),
    ("needs_person", "away", "refused"), ("bad_args", "usage", "refused"), ("busy", None, "busy"),
])
def test_finished_problem_is_the_problem_kind_the_window_would_have_said(outcome, reason, problem):
    assert outcomes.finished_problem({"outcome": outcome, "reason": reason}) == problem
