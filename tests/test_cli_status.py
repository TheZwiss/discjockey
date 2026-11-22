"""`status [--ready]` through the command line (issue 39 phase 3, V3.2b): what the Dashboard and the navigation show, the
jobs that run now with the steps they wait for, and the gig check as a filter of `doctor`'s problems. The golden page and the
parity of the answer with the bridge are tests/test_cli_golden.py's."""
import json
from datetime import datetime
from pathlib import Path

import pytest
from test_cli_batches import with_batches
from hub_helpers import choose_music, make_root, services, stub_headless

import discjockey.cli as cli
from discjockey import db, library, pending_signs, words
from discjockey.cli import bind
from discjockey.hub.api import CliApi
from discjockey.hub.registry import Registry

STEP = {"id": "step:connect_drive", "say": "Connect the drive Gig Stick.", "then": None}


@pytest.fixture
def lib(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    stub_headless(monkeypatch)
    return paths


@pytest.fixture
def api(lib, monkeypatch):
    """The command line's api and the test's own are one, on the hub's fixed clock: what the command prints is what the
    bridge answers."""
    api = CliApi(lib.support, None, services())
    api._attach(lib)
    monkeypatch.setattr(bind, "default", lambda: api)
    return api


def status_json(capsys, *flags):
    code = cli.main(["status", *flags, "--json"])
    env = json.loads(capsys.readouterr().out)
    return code, env


def a_job(lib, status="running", line="3 of 12", steps=(), started="2026-11-22T09:00:00+00:00"):
    """A job of this music folder in the registry, in the state the worker leaves it; its `alive` lock stays taken by the
    returned handle (released by the test's end), so the registry does not call it lost."""
    roots = {"music": str(lib.root), "support": str(lib.support), "rekordbox": None, "rekordbox_share": None,
             "sandbox": None}
    files = Registry(lib.support).create("sync", "sync run", {}, "terminal", roots)
    files.update(status=status, started=started, progress={"line": line}, person_steps=list(steps))
    return files


def test_status_carries_the_dashboard_whole_and_the_navigation_counts(api, capsys):
    code, env = status_json(capsys)
    assert (code, env["outcome"]) == (0, "ok")
    data = env["data"]
    assert data["dashboard"] == {k: v for k, v in api.dashboard().items() if k != "ok"}
    sidebar = api.sidebar()
    assert data["nav"] == {k: sidebar[k] for k in ("todo", "all_tracks", "not_in_playlist", "limits_warning")}
    assert data["jobs"] == [] and data["ready"] is None
    assert "person_steps" not in data and env["person_steps"] == []


def test_a_running_job_is_listed_and_its_steps_are_the_envelopes_not_data(lib, capsys):
    ended = a_job(lib, "done", "9 of 9", started="2026-11-21T09:00:00+00:00")
    ended.update(status="done", ended="2026-11-21T09:05:00+00:00")
    older = a_job(lib, "running", None, started="2026-11-22T08:00:00+00:00")
    newest = a_job(lib, "stopping", "3 of 12 · Pegassi - AEIOU", steps=[STEP])
    try:
        code, env = status_json(capsys)
    finally:
        for files in (ended, older, newest):
            files.release_claim()
    assert (code, env["outcome"]) == (0, "ok")
    assert [(j["id"], j["status"], j["line"]) for j in env["data"]["jobs"]] == [
        (newest.id, "stopping", "3 of 12 · Pegassi - AEIOU"), (older.id, "running", None)]
    assert env["data"]["jobs"][0] == {"id": newest.id, "command": "sync run", "via": "terminal", "status": "stopping",
                                      "line": "3 of 12 · Pegassi - AEIOU", "started": "2026-11-22T09:00:00+00:00"}
    assert "person_steps" not in env["data"] and env["person_steps"] == [STEP]


def test_the_steps_print_as_your_turn_lines(lib, capsys):
    files = a_job(lib, steps=[STEP])
    try:
        assert cli.main(["status"]) == 0
    finally:
        files.release_claim()
    assert "Your turn: Connect the drive Gig Stick." in capsys.readouterr().err


def test_ready_is_the_gig_problems_of_doctor_and_nothing_of_its_own(lib, api, capsys):
    with db.connect(lib.db_file) as conn:
        db.add_watched_folder(conn, Path("/Volumes/Gig Stick/Crates"), datetime(2026, 11, 20, 9, 0))
    pending_signs.add(lib, [("youtube", "auto_stop", "YouTube asked for a pause")],
                     datetime(2026, 10, 20, 12, 0))  # today on the fixture's clock: a note, not a gig's
    code, env = status_json(capsys, "--ready")
    assert code == 0
    everything = api.doctor()["problems"]
    assert {p["check"] for p in everything} == {"drives_away", "downloads_paused"}
    assert env["data"]["ready"] == [p for p in everything if p["gig"]]
    assert [p["check"] for p in env["data"]["ready"]] == ["drives_away"]


def test_a_library_that_is_ready_says_so_with_an_empty_list_not_null(lib, capsys):
    _, env = status_json(capsys, "--ready")
    assert env["data"]["ready"] == [] and env["data"]["ready_text"] == words.READY_YES
    _, plain = status_json(capsys)
    assert "ready_text" not in plain["data"]  # the verdict comes with the question only


def test_ready_says_how_many_things_to_look_at_and_the_text_page_starts_with_it(lib, capsys):
    with db.connect(lib.db_file) as conn:
        db.add_watched_folder(conn, Path("/Volumes/Gig Stick/Crates"), datetime(2026, 11, 20, 9, 0))
    _, env = status_json(capsys, "--ready")
    assert env["data"]["ready_text"] == "1 thing to look at before a gig." == words.ready_text(1)
    assert words.ready_text(3) == "3 things to look at before a gig."
    assert cli.main(["status", "--ready"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "1 thing to look at before a gig."


def test_ready_lists_a_stopped_batch(lib, capsys):
    with_batches(lib)  # a stopped AIFF batch: a problem a gig depends on
    _, env = status_json(capsys, "--ready")
    assert [(p["check"], p["gig"]) for p in env["data"]["ready"]] == [("stopped_batches", True)]


def test_without_a_music_folder_status_is_refused_no_library(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    stub_headless(monkeypatch)
    code, env = status_json(capsys)
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library")


def test_the_text_page_names_the_ready_problems(lib, capsys):
    with db.connect(lib.db_file) as conn:
        db.add_watched_folder(conn, Path("/Volumes/Gig Stick/Crates"), datetime(2026, 11, 20, 9, 0))
    assert cli.main(["status", "--ready"]) == 0
    out = capsys.readouterr().out
    assert "Ready" in out and "1 watched folder is on a drive that isn't connected." in out
