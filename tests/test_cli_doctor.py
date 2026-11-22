"""`doctor` through the command line (issue 39 phase 3, V3.2a): the hub fixture is healthy, and each machine read that
feeds a check is made to find its problem on a real fixture (a drive that is not there, a folder macOS would not open,
a job that stopped, a cut-off step). The checks themselves are pinned on plain facts in tests/test_hub_doctor.py."""
import json
import os
import shlex
from datetime import datetime, timedelta
from pathlib import Path

import pytest
from hub_helpers import choose_music, make_root, stub_headless
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import db, library, pending_signs, words
from discjockey.cli import parser
from discjockey.hub import doctor
from discjockey.hub.registry import Registry

ALL_OK = {c.key: "ok" for c in doctor.CHECKS}
NOT_ROOT = pytest.mark.skipif(os.geteuid() == 0, reason="root opens every folder")


@pytest.fixture
def lib(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    stub_headless(monkeypatch)
    monkeypatch.delenv("__CFBundleIdentifier", raising=False)
    monkeypatch.delenv("TERM_PROGRAM", raising=False)
    return paths


def doctor_json(capsys):
    code = cli.main(["doctor", "--json"])
    env = json.loads(capsys.readouterr().out)
    return code, env, env["data"]


def states(data):
    return {c["check"]: c["state"] for c in data["checks"]}


def watch(paths, folder):
    """`folder` as a watched import folder (its row only: no import ran)."""
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, Path(folder), datetime(2026, 11, 20, 9, 0))


def a_job(lib, status, started):
    """A job of this music folder in the registry, in the state it was left in."""
    roots = {"music": str(lib.root), "support": str(lib.support), "rekordbox": None, "rekordbox_share": None,
             "sandbox": None}
    files = Registry(lib.support).create("sync", "sync run", {}, "terminal", roots)
    files.release_claim()
    files.update(status=status, started=started.isoformat(timespec="seconds"), ended=started.isoformat(timespec="seconds"))
    return files.id


def test_a_healthy_fixture_has_nothing_wrong(lib, capsys):
    code, env, data = doctor_json(capsys)
    assert (code, env["outcome"]) == (0, "ok")
    assert states(data) == ALL_OK and data["problems"] == [] and data["text"] == words.DOCTOR_ALL_GOOD


def test_the_text_page_lists_the_problems_and_every_check(lib, capsys):
    watch(lib, "/Volumes/Gig Stick/Crates")
    assert cli.main(["doctor"]) == 0
    out = capsys.readouterr().out
    assert out.startswith("1 problem, 0 notes.") and "1 watched folder is on a drive that isn't connected." in out
    assert "Connect the drive Gig Stick." in out and "Download limits" in out


def test_a_watched_folder_on_a_drive_that_is_not_connected_names_the_drive(lib, capsys):
    watch(lib, "/Volumes/Gig Stick/Crates")
    watch(lib, "/Volumes/Gig Stick/More")
    _, env, data = doctor_json(capsys)
    assert env["outcome"] == "ok" and states(data)["drives_away"] == "problem"
    (problem,) = data["problems"]
    assert (problem["check"], problem["count"], problem["gig"]) == ("drives_away", 2, True)
    assert problem["person_steps"] == [{"id": "step:connect_drive", "say": "Connect the drive Gig Stick.", "then": None}]
    assert states(data)["folder_access"] == "ok"  # a drive that is away is not also an unreadable folder


@NOT_ROOT
def test_a_folder_the_app_may_not_open_asks_to_allow_the_app_the_command_runs_in(lib, tmp_path_factory, monkeypatch,
                                                                                   capsys):
    monkeypatch.setenv("__CFBundleIdentifier", "com.googlecode.iterm2")
    locked = tmp_path_factory.mktemp("outside") / "Locked"  # a watched folder cannot be inside the music folder
    locked.mkdir()
    watch(lib, locked)
    locked.chmod(0)
    try:
        _, _, data = doctor_json(capsys)
    finally:
        locked.chmod(0o755)
    (problem,) = data["problems"]
    assert (problem["check"], problem["level"]) == ("folder_access", "problem")
    assert problem["text"] == words.DOCTOR_ACCESS.format(folder=str(locked.resolve()))
    (step,) = problem["person_steps"]
    assert step["id"] == "step:folder_access" and step["say"].startswith(f"Allow iTerm to open {locked.resolve()}:")
    assert states(data)["folder_access"] == "problem" and states(data)["music_folder"] == "ok"


@NOT_ROOT
def test_rekordbox_s_folder_is_checked_too(lib, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("TERM_PROGRAM", "WarpTerminal")
    folder = make_master(tmp_path / "rekordbox", []).parent
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    folder.chmod(0o111)  # can be walked through, not listed: the file is found, the folder is refused
    try:
        _, _, data = doctor_json(capsys)
    finally:
        folder.chmod(0o755)
    access = [p for p in data["problems"] if p["check"] == "folder_access"]
    assert [p["text"] for p in access] == [words.DOCTOR_ACCESS.format(folder=str(folder))]
    assert access[0]["person_steps"][0]["say"].startswith("Allow Warp to open ")


def test_a_job_that_stopped_this_week_is_counted_and_an_older_one_is_not(lib, capsys):
    now = datetime.now().astimezone()
    a_job(lib, "lost", now - timedelta(days=8))
    _, _, data = doctor_json(capsys)
    assert states(data)["lost_jobs"] == "ok"
    newest = a_job(lib, "lost", now - timedelta(hours=2))
    a_job(lib, "done", now - timedelta(hours=1))
    _, _, data = doctor_json(capsys)
    (problem,) = data["problems"]
    assert (problem["check"], problem["count"], problem["text"]) == (
        "lost_jobs", 1, "1 job stopped without finishing this week.")
    assert problem["next"] == [{"run": f"job show {newest}", "why": "what it did before it stopped"}]


def test_a_cut_off_file_step_is_a_problem_and_doctor_finishes_nothing(lib, capsys):
    with db.connect(lib.db_file) as conn:
        db.journal_step(conn, {"kind": db.STEP, "track_id": "t1", "entry": None}, db._generation(conn))
    _, _, data = doctor_json(capsys)
    (problem,) = data["problems"]
    assert (problem["check"], problem["text"]) == ("pending_steps", words.DOCTOR_PENDING)
    assert problem["next"] == [{"run": "library scan", "why": "finishes them, then scans"}]
    _, _, again = doctor_json(capsys)  # a read: the step is still there
    assert [p["check"] for p in again["problems"]] == ["pending_steps"]


def test_a_source_paused_today_is_a_note_with_its_limits_command(lib, capsys):
    pending_signs.add(lib, [("youtube", "auto_stop", "YouTube asked for a pause")], datetime.now())  # waits for the lock
    _, env, data = doctor_json(capsys)
    assert env["outcome"] == "ok"
    (problem,) = data["problems"]
    assert (problem["check"], problem["level"], problem["gig"]) == ("downloads_paused", "note", False)
    assert problem["text"] == words.DOCTOR_PAUSED.format(services="YouTube Premium")
    assert problem["next"] == [{"run": "limits show youtube", "why": "today's downloads and why they paused"}]
    assert states(data)["downloads_paused"] == "note" and data["text"] == "0 problems, 1 note."


def test_without_a_music_folder_it_still_answers_and_says_what_it_skipped(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    stub_headless(monkeypatch)
    code, env, data = doctor_json(capsys)
    assert (code, env["outcome"]) == (0, "ok")
    assert [(p["check"], p["text"]) for p in data["problems"]] == [("music_folder", words.NOT_CHOSEN)]
    assert states(data) == {**ALL_OK, "music_folder": "problem", "pending_steps": "skipped", "drives_away": "skipped",
                            "downloads_paused": "skipped"}
    assert data["text"] == "1 problem, 0 notes."


def test_a_music_folder_that_is_gone_is_a_problem_with_its_drive(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    library.write_music_folder(tmp_path / "support", Path("/Volumes/Gig Stick/Music"))
    stub_headless(monkeypatch)
    _, env, data = doctor_json(capsys)
    assert env["outcome"] == "ok"
    (problem,) = data["problems"]
    assert problem["text"] == words.MISSING.format(path="/Volumes/Gig Stick/Music")
    assert problem["person_steps"][0]["say"] == "Connect the drive Gig Stick."
    assert states(data)["pending_steps"] == "skipped"


def test_every_command_a_problem_says_to_run_is_one_the_command_line_has(capsys):
    worst = doctor.Inputs(
        music_state="not_chosen", music_path="", missing_tools=(("deno", "brew install deno"),),
        downloads={"qobuz": {"state": "paused", "last_check": {"ok": False}}, "youtube": {"state": "unreadable"},
                   "soundcloud": {"state": "paused"}},
        paused_accounts=frozenset({"soundcloud"}), unreadable_folders=("/x",), app="Terminal",
        rekordbox_state="unreadable", rekordbox_problem="unclean",
        lock_holder={"job": None, "text": words.UNNAMED_HOLDER},
        jobs=(doctor.JobRow("job:0a1b2c3d", "lost", datetime.now().astimezone().isoformat()),),
        now=datetime.now().astimezone(), pending=True, away_folders=("/Volumes/D/x",))
    answer = doctor.answer(worst, True)
    assert {c["state"] for c in answer["checks"]} == {"problem", "note"}
    runs = {n["run"] for p in answer["problems"] for n in p["next"]} | {
        s["then"] for p in answer["problems"] for s in p["person_steps"] if s["then"]}
    assert {"setup status", "login list", "rekordbox status", "rekordbox backups", "job list --all", "library scan",
            "job show job:0a1b2c3d", "limits show qobuz", "limits show soundcloud", "tools status"} <= runs
    for run in runs:
        assert parser.parse(shlex.split(run)).command, run
