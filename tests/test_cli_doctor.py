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


@NOT_ROOT
def test_a_track_in_a_folder_the_app_may_not_open_does_not_end_doctor(lib, tmp_path, tmp_path_factory, monkeypatch, capsys):
    locked = tmp_path_factory.mktemp("outside") / "Locked"
    locked.mkdir()
    (locked / "a.mp3").write_bytes(b"audio")
    watch(lib, locked)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", [{"path": str(locked / "a.mp3")}]).parent))
    locked.chmod(0)
    try:
        code, env, data = doctor_json(capsys)
    finally:
        locked.chmod(0o755)
    assert (code, env["outcome"]) == (0, "ok")  # rekordbox's track is not claimed missing: `folder_access` says why
    assert [p["check"] for p in data["problems"]] == ["folder_access"] and states(data)["rekordbox_files"] == "ok"


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
    needs_library = {c.key: "skipped" for c in doctor.CHECKS if c.needs_library}
    assert states(data) == {**ALL_OK, **needs_library, "music_folder": "problem"}
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


def test_a_watched_folder_that_is_gone_from_no_drive_is_put_back_not_connected(lib, tmp_path_factory, capsys):
    gone = tmp_path_factory.mktemp("outside") / "Moved Crates"  # on no external drive, and not there
    watch(lib, gone)
    _, _, data = doctor_json(capsys)
    (problem,) = data["problems"]
    assert (problem["check"], problem["text"], problem["count"]) == ("drives_away", "1 watched folder is not there.", 1)
    assert problem["person_steps"] == [{"id": "step:folder_gone", "say": f"Put the folder {gone} back, or choose another folder.",
                                       "then": None}]


def test_records_that_cannot_be_read_are_said_by_doctor_which_skips_what_reads_them(lib, capsys):
    lib.db_file.write_bytes(b"this is not a database" * 50)
    code, env, data = doctor_json(capsys)
    assert (code, env["outcome"]) == (0, "ok")  # doctor is what a person runs then: it answers, it does not fail
    states_ = states(data)
    assert states_["records"] == "problem" and states_["music_folder"] == "ok"
    skipped = {c.key for c in doctor.CHECKS if c.reads_records}
    assert {k for k, v in states_.items() if v == "skipped"} == skipped
    (problem,) = [p for p in data["problems"] if p["check"] == "records"]
    assert problem["level"] == "problem" and problem["gig"] is True
    assert problem["text"].startswith("Discjockey can't read its records of this music folder (.discjockey/library.db)")
    assert problem["text"].endswith(words.DOCTOR_RECORDS_SKIPPED)
    assert problem["next"] == [{"run": "where", "why": "where Discjockey keeps its records"}]
    assert cli.main(["doctor"]) == 0 and "Records" in capsys.readouterr().out


def test_every_command_a_problem_says_to_run_is_one_the_command_line_has(capsys):
    worst = doctor.Inputs(
        music_state="not_chosen", music_path="", missing_tools=(("deno", "brew install deno"),),
        downloads={"qobuz": {"state": "paused", "last_check": {"ok": False}}, "youtube": {"state": "unreadable"},
                   "soundcloud": {"state": "paused"}},
        paused_accounts=frozenset({"soundcloud"}), unreadable_folders=("/x",), app="Terminal",
        rekordbox_state="unreadable", rekordbox_problem="unclean",
        lock_holder={"job": None, "text": words.UNNAMED_HOLDER},
        jobs=(doctor.JobRow("job:0a1b2c3d", "lost", datetime.now().astimezone().isoformat()),),
        now=datetime.now().astimezone(), pending=True, away_folders=("/Volumes/D/x",), tidy_rows=0, superseded_files=0,
        superseded_bytes=0, rekordbox_match=None, stopped_batches=(), check_tracks=0, cdj_files=0, missing_files=0,
        upgrades_ready=0, to_load=0)
    answer = doctor.answer(worst, True)
    assert {"problem", "note"} <= {c["state"] for c in answer["checks"]}
    runs = {n["run"] for p in answer["problems"] for n in p["next"]} | {
        s["then"] for p in answer["problems"] for s in p["person_steps"] if s["then"]}
    assert {"setup status", "login list", "rekordbox status", "rekordbox backups", "job list --all", "library scan",
            "job show job:0a1b2c3d", "limits show qobuz", "limits show soundcloud", "tools status"} <= runs
    for run in runs:
        assert parser.parse(shlex.split(run)).command, run


# --- the library's own checks (V3.2b): each fact of `Inputs` is read from a real fixture ---

def problem_of(data, check):
    return next((p for p in data["problems"] if p["check"] == check), None)


def test_a_stopped_aiff_batch_is_a_problem_with_its_resume_command(lib, capsys):
    from test_cli_batches import with_batches
    with_batches(lib)  # aiff:1 done, aiff:2 stopped, moves:1 done
    _, _, data = doctor_json(capsys)
    p = problem_of(data, "stopped_batches")
    assert (p["level"], p["gig"], p["count"], p["text"]) == ("problem", True, 1, "1 batch stopped before its end.")
    assert p["next"] == [{"run": "batch resume aiff:2", "why": "goes on where it stopped"}]
    assert states(data)["stopped_batches"] == "problem"


def test_open_checks_and_waiting_upgrades_come_from_the_to_do_answer(tmp_path, monkeypatch, capsys):
    from test_cli_reads import rich_library
    rich_library(tmp_path, monkeypatch)
    _, _, data = doctor_json(capsys)
    checks, upgrades = problem_of(data, "open_checks"), problem_of(data, "upgrades_waiting")
    assert (checks["level"], checks["count"], checks["next"][0]["run"]) == ("note", 2, "check list")
    assert checks["text"] == "2 tracks wait for a check in rekordbox."
    assert (upgrades["count"], upgrades["text"]) == (1, "1 better version waits for you.")
    assert upgrades["next"] == [{"run": "upgrade list", "why": "the versions waiting"}]


def test_rekordbox_tracks_on_a_missing_file_or_in_superseded_are_counted(lib, tmp_path, monkeypatch, capsys):
    old = lib.root / "Superseded/Hard_Bounce/Old.mp3"
    old.parent.mkdir(parents=True)
    old.write_bytes(b"x" * 1_200_000)
    rows = [{"path": str(lib.root / rel), "artist": "A", "Title": rel} for rel in (
        "Library/Hard_Bounce/Gone.aiff", "Superseded/Hard_Bounce/Old.mp3", "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff")]
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", rows).parent))
    _, _, data = doctor_json(capsys)
    p = problem_of(data, "rekordbox_files")
    assert (p["level"], p["gig"], p["count"]) == ("problem", True, 2)
    assert p["text"] == "2 rekordbox tracks point at files that are missing or in Superseded/."
    assert p["next"] == [{"run": "rekordbox match", "why": "which tracks, and their files"}]
    note = problem_of(data, "superseded")
    assert (note["level"], note["gig"], note["count"], note["text"]) == ("note", False, 1, "1 file in Superseded/, 1 MB.")


def test_a_rekordbox_that_cannot_be_read_is_one_problem_and_no_claim_about_its_tracks(lib, tmp_path, monkeypatch, capsys):
    folder = make_master(tmp_path / "rekordbox", []).parent
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    (folder / "master.db").write_bytes(b"not a database" * 100)
    _, _, data = doctor_json(capsys)
    assert states(data)["rekordbox"] == "problem"
    (note,) = [p for p in data["problems"] if p["check"] == "rekordbox_files"]  # not compared: said, never "all match"
    assert note["level"] == "note" and note["text"].startswith("rekordbox's tracks could not be compared with your files: ")


def test_while_a_writer_holds_rekordbox_the_tracks_are_not_compared_and_doctor_says_so(lib, tmp_path, monkeypatch, capsys):
    from discjockey.rekordbox import lock as rb_lock
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rekordbox", []).parent))
    with rb_lock.writer_lock(lib.support):
        code, env, data = doctor_json(capsys)
    assert (code, env["outcome"]) == (0, "ok")
    p = problem_of(data, "rekordbox_files")
    assert (p["level"], p["gig"]) == ("note", True)
    assert p["text"] == f"rekordbox's tracks could not be compared with your files: {words.WRITING_WORDS}."
    assert p["next"] == [{"run": "rekordbox status", "why": "whether rekordbox can be read now"}]
    _, _, again = doctor_json(capsys)  # the writer is done: compared again, nothing to say
    assert states(again)["rekordbox_files"] == "ok"


def test_songs_whose_file_is_missing_are_counted_with_the_command_that_lists_them(tmp_path, monkeypatch, capsys):
    from test_cli_missing import missing_library
    missing_library(tmp_path, monkeypatch)
    _, _, data = doctor_json(capsys)
    (p,) = [p for p in data["problems"] if p["check"] == "songs_without_file"]
    assert (p["level"], p["gig"], p["count"], p["text"]) == ("note", True, 5, "5 songs' files are missing.")
    assert p["next"] == [{"run": "missing list", "why": "the songs and what can be done"}]


def test_playlist_songs_without_a_file_come_from_the_stored_read_s_plan(lib, monkeypatch, capsys):
    from test_cli_golden import with_read
    with_read(lib, monkeypatch)  # the playlists read: songs the next sync downloads
    _, _, data = doctor_json(capsys)
    (p,) = [p for p in data["problems"] if p["check"] == "songs_without_file"]
    assert (p["level"], p["count"], p["text"]) == ("note", 2, "2 playlist songs have no file yet.")
    assert p["next"] == [{"run": "sync plan", "why": "what the next sync downloads"}]
    assert states(data)["songs_without_file"] == "note"


def test_an_own_file_the_club_players_refuse_is_counted_with_the_group_that_lists_it(lib, capsys):
    from hub_helpers import entry, write, write_state
    state = library.load_state(lib)
    state["tracks"]["t9"] = entry(artist="Own Artist", title="Own Song", duration_ms=180000, folder="Hard_Bounce",
                                  path="Library/Hard_Bounce/Own Artist - Own Song.ogg", status="lossless",
                                  source="manual", in_playlists=False)
    write(lib, "Library/Hard_Bounce/Own Artist - Own Song.ogg", b"ogg")
    write_state(lib, state)
    with db.connect(lib.db_file) as conn:
        conn.execute("UPDATE files SET file_codec = 'vorbis', file_rate = 44100, file_bits = NULL, file_kbps = 192 "
                     "WHERE path LIKE '%Own Song.ogg'")
        conn.commit()
    _, _, data = doctor_json(capsys)
    p = problem_of(data, "cdj")
    assert (p["level"], p["gig"], p["count"], p["text"]) == ("note", True, 1, "1 file won't play well on CDJs.")
    assert p["next"] == [{"run": "todo list --group cdj", "why": "the files and why"}]


def test_files_the_playlist_order_would_move_are_a_note(lib, capsys):
    from hub_helpers import write_state
    state = library.load_state(lib)
    state["tracks"]["t1"]["folder"] = "Powertrance"  # the playlist order puts it in another folder than the file is in
    write_state(lib, state)
    _, _, data = doctor_json(capsys)
    p = problem_of(data, "out_of_place")
    assert (p["level"], p["count"], p["text"]) == ("note", 1, "1 file is not where the playlist order puts it.")
    assert p["next"] == [{"run": "tidy run --dry-run", "why": "which files a tidy-up would move"}]


def test_every_command_the_library_checks_say_to_run_is_one_the_command_line_has():
    facts = doctor.Inputs(
        music_state="ok", music_path="/m", missing_tools=(), downloads={}, paused_accounts=frozenset(),
        unreadable_folders=(), app="Terminal", rekordbox_state="ready", rekordbox_problem=None, lock_holder=None, jobs=(),
        now=datetime.now().astimezone(), pending=False, away_folders=(), tidy_rows=1, superseded_files=1,
        superseded_bytes=1, rekordbox_match={"missing": 1, "superseded": 1}, stopped_batches=("aiff:2",),
        check_tracks=1, cdj_files=1, missing_files=1, upgrades_ready=1, to_load=1)
    answer = doctor.answer(facts, True)
    assert [c["state"] for c in answer["checks"][-8:]] == ["note", "note", "problem", "problem", "note", "note", "note",
                                                          "note"]
    runs = {n["run"] for p in answer["problems"] for n in p["next"]}
    assert len(runs) == 9
    for run in runs:
        assert parser.parse(shlex.split(run)).command, run
