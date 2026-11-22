"""`doctor` on plain facts (issue 39 phase 3, V3.2a): each check's problem and its ok, the order, the skipped checks and
the app a person grants. The machine reads that gather the facts are tests/test_cli_doctor.py's."""
from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from discjockey import words
from discjockey.hub import doctor
from discjockey.hub.doctor import Inputs, JobRow

NOW = datetime(2026, 11, 22, 9, 0).astimezone()
GOOD = Inputs(music_state="ok", music_path="/music", missing_tools=(), downloads={}, paused_accounts=frozenset(),
              unreadable_folders=(), app="Terminal", rekordbox_state="ready", rekordbox_problem=None, lock_holder=None,
              jobs=(), now=NOW, pending=False, away_folders=(), tidy_rows=0, superseded_files=0, superseded_bytes=0,
              rekordbox_match={"matched": 5, "missing": 0, "superseded": 0, "away": 0, "not_in_library": 0,
                               "not_in_rekordbox": 0, "outside": 0},
              stopped_batches=(), check_tracks=0, cdj_files=0, missing_files=0, upgrades_ready=0, to_load=0)
LAST_CHECK_FAILED = {"ok": False, "problem": "login_failed"}


def run(key, **facts):
    """The problems of one check on the good facts changed by `facts`."""
    check = next(c for c in doctor.CHECKS if c.key == key)
    return check.run(replace(GOOD, **facts))


def only(key, **facts):
    problems = run(key, **facts)
    assert len(problems) == 1, problems
    return problems[0]


def test_every_check_is_ok_on_good_facts():
    answer = doctor.answer(GOOD, True)
    assert answer["problems"] == [] and answer["text"] == words.DOCTOR_ALL_GOOD
    assert [c["state"] for c in answer["checks"]] == ["ok"] * len(doctor.CHECKS)
    assert [c["check"] for c in answer["checks"]] == [c.key for c in doctor.CHECKS] == [
        "music_folder", "tools", "logins", "folder_access", "rekordbox", "stale_lock", "lost_jobs", "pending_steps",
        "drives_away", "downloads_paused", "out_of_place", "superseded", "rekordbox_files", "stopped_batches",
        "open_checks", "cdj", "songs_without_file", "upgrades_waiting"]


def test_the_shape_names_exactly_the_checks_there_are():
    from typing import get_args

    from discjockey.hub.shapes.cli import DoctorCheckKey
    literal = get_args(DoctorCheckKey)[0]
    assert get_args(literal) == tuple(c.key for c in doctor.CHECKS)


def test_the_checks_say_which_a_gig_depends_on_and_which_need_the_library():
    assert {c.key for c in doctor.CHECKS if c.gig} == {
        "music_folder", "folder_access", "rekordbox", "pending_steps", "drives_away", "rekordbox_files", "stopped_batches",
        "open_checks", "cdj", "songs_without_file", "upgrades_waiting"}
    assert {c.key for c in doctor.CHECKS if not c.needs_library} == {
        "music_folder", "tools", "logins", "folder_access", "rekordbox", "stale_lock", "lost_jobs"}


# --- the checks ---

def test_no_music_folder_chosen_points_at_setup():
    p = only("music_folder", music_state="not_chosen", music_path="")
    assert (p["level"], p["text"], p["count"], p["person_steps"]) == ("problem", words.NOT_CHOSEN, None, [])
    assert p["next"] == [{"run": "setup status", "why": "what Setup still needs"}]


def test_a_music_folder_that_is_not_there_names_its_drive():
    p = only("music_folder", music_state="missing", music_path="/Volumes/Gig Stick/Music")
    assert p["text"] == words.MISSING.format(path="/Volumes/Gig Stick/Music") and p["next"] == []
    assert p["person_steps"] == [{"id": "step:connect_drive", "say": "Connect the drive Gig Stick.", "then": None}]
    elsewhere = only("music_folder", music_state="missing", music_path="/Users/dj/Music")
    assert elsewhere["person_steps"][0]["say"] == "Connect the drive /Users/dj/Music."  # no drive: the path itself


def test_missing_programs_are_one_problem_with_a_step_per_install_command():
    p = only("tools", missing_tools=(("ffmpeg", "brew install ffmpeg"), ("ffprobe", "brew install ffmpeg"),
                                    ("deno", "brew install deno")))
    assert (p["level"], p["text"], p["count"]) == ("problem", "Missing: ffmpeg, ffprobe, deno.", None)
    assert [s["say"] for s in p["person_steps"]] == ["Paste `brew install ffmpeg` into the Terminal.",
                                                      "Paste `brew install deno` into the Terminal."]
    assert {s["then"] for s in p["person_steps"]} == {"tools status"} and run("tools") == []


def test_a_login_whose_last_check_failed_is_a_problem_each():
    downloads = {"qobuz": {"state": "off", "last_check": LAST_CHECK_FAILED},
                 "youtube": {"state": "no_premium", "last_check": None},
                 "soundcloud": {"state": "unreadable", "last_check": None}}
    problems = run("logins", downloads=downloads)
    assert [p["text"] for p in problems] == ["Qobuz: its last login check failed.",
                                             "YouTube Premium: its last login check failed.",
                                             "SoundCloud Go+: its last login check failed."]
    assert problems[0]["level"] == "problem" and problems[0]["next"] == [{"run": "login list", "why": "each login's state"}]
    only_check = {"youtube": {"state": "off", "last_check": LAST_CHECK_FAILED}}
    assert [p["text"] for p in run("logins", downloads=only_check)] == ["YouTube Premium: its last login check failed."]


def test_a_login_that_works_is_off_or_skipped_is_no_problem():
    fine = {"qobuz": {"state": "on", "last_check": {"ok": True}}, "youtube": {"state": "paused", "last_check": None},
            "soundcloud": {"state": "off", "last_check": None}}
    assert run("logins", downloads=fine) == []
    skipped = {"qobuz": {"state": "skipped", "last_check": LAST_CHECK_FAILED}}
    assert run("logins", downloads=skipped) == []  # Qobuz was left out in Setup: its old failed check does not count


def test_a_folder_macos_does_not_let_us_open_names_the_app_to_allow():
    problems = run("folder_access", unreadable_folders=("/Users/dj/Crates", "/Users/dj/Library/Pioneer"), app="iTerm")
    assert [p["text"] for p in problems] == ["Discjockey can't open /Users/dj/Crates.",
                                             "Discjockey can't open /Users/dj/Library/Pioneer."]
    step = problems[0]["person_steps"][0]
    assert step["id"] == "step:folder_access" and step["then"] is None
    assert step["say"].startswith("Allow iTerm to open /Users/dj/Crates:") and problems[0]["level"] == "problem"


@pytest.mark.parametrize("state, problem, level", [
    ("unreadable", None, "problem"), ("unreadable", "key", "problem"), ("unreadable", "db_version", "problem"),
    ("unreadable", "schema", "problem"), ("unreadable", "unclean", "problem"), ("ready", "unclean", "problem"),
    ("ready", "busy", "note")])
def test_rekordbox_problems_and_the_busy_note(state, problem, level):
    p = only("rekordbox", rekordbox_state=state, rekordbox_problem=problem)
    state_text, problem_text = words.rekordbox_words(state, problem)
    assert (p["level"], p["text"]) == (level, problem_text or state_text)
    assert p["next"][0] == {"run": "rekordbox status", "why": "what rekordbox's library says"}
    assert [n["run"] for n in p["next"]] == (["rekordbox status", "rekordbox backups"] if problem == "unclean"
                                             else ["rekordbox status"])


@pytest.mark.parametrize("state, problem", [("none", None), ("ready", None)])
def test_rekordbox_that_is_not_there_or_reads_is_ok(state, problem):
    assert run("rekordbox", rekordbox_state=state, rekordbox_problem=problem) == []


def test_a_lock_held_by_nobody_the_registry_names_is_a_note():
    holder = {"job": None, "via": None, "kind": None, "line": None, "text": words.UNNAMED_HOLDER, "where": None}
    p = only("stale_lock", lock_holder=holder)
    assert p["level"] == "note" and p["text"] == ("Something outside Discjockey's job list holds your library: "
                                                  + words.UNNAMED_HOLDER)
    assert p["next"] == [{"run": "job list --all", "why": "every job Discjockey knows of"}]
    named = {**holder, "job": "job:0a1b2c3d", "kind": "sync", "text": "Sync running in the Terminal"}
    assert run("stale_lock", lock_holder=named) == [] and run("stale_lock") == []  # `job list` shows a named job


def job(n, status, days_ago, hours=0):
    return JobRow(f"job:{n:08x}", status, (NOW - timedelta(days=days_ago, hours=hours)).isoformat(timespec="seconds"))


def test_jobs_lost_this_week_are_counted_and_the_newest_is_named():
    jobs = (job(3, "lost", 0, 1), job(2, "done", 1), job(4, "lost", 3), job(1, "lost", 6, 23), job(9, "lost", 8))
    p = only("lost_jobs", jobs=jobs)
    assert (p["level"], p["text"], p["count"]) == ("problem", "3 jobs stopped without finishing this week.", 3)
    assert p["next"] == [{"run": "job show job:00000003", "why": "what it did before it stopped"}]
    one = only("lost_jobs", jobs=(job(5, "lost", 2),))
    assert one["text"] == "1 job stopped without finishing this week." and one["count"] == 1


def test_a_job_lost_more_than_a_week_ago_or_not_lost_is_no_problem():
    assert run("lost_jobs", jobs=(job(1, "lost", 7, 1), job(2, "running", 0), job(3, "done", 0))) == []
    assert run("lost_jobs", jobs=(JobRow("job:00000001", "lost", "not a time"),)) == []


def test_a_job_started_at_a_naive_local_time_counts_in_local_time():
    started = (datetime.now() - timedelta(days=1)).isoformat(timespec="seconds")
    assert only("lost_jobs", jobs=(JobRow("job:00000001", "lost", started),), now=datetime.now())["count"] == 1


def test_cut_off_steps_say_the_next_change_finishes_them():
    p = only("pending_steps", pending=True)
    assert (p["level"], p["text"], p["count"]) == ("problem", words.DOCTOR_PENDING, None)
    assert p["next"] == [{"run": "library scan", "why": "finishes them, then scans"}] and run("pending_steps") == []


def test_watched_folders_away_are_counted_with_a_step_per_drive():
    away = ("/Volumes/Gig Stick/Crates", "/Volumes/Gig Stick/More", "/Volumes/Backup/Old", "/Users/dj/Gone")
    p = only("drives_away", away_folders=away)
    assert (p["level"], p["text"], p["count"]) == ("problem", "4 watched folders are on a drive that isn't connected.", 4)
    assert [s["say"] for s in p["person_steps"]] == ["Connect the drive Gig Stick.", "Connect the drive Backup.",
                                                     "Connect the drive /Users/dj/Gone."]
    one = only("drives_away", away_folders=("/Volumes/Gig Stick/Crates",))
    assert one["text"] == "1 watched folder is on a drive that isn't connected." and one["count"] == 1
    assert run("drives_away") == []


def test_a_source_paused_today_is_a_note_with_its_limits_command():
    downloads = {"qobuz": {"state": "paused"}, "youtube": {"state": "on"}, "soundcloud": {"state": "used_up"}}
    p = only("downloads_paused", downloads=downloads, paused_accounts=frozenset({"soundcloud"}))
    assert (p["level"], p["text"]) == ("note", "Paused today to protect your account: Qobuz, SoundCloud Go+.")
    assert [n["run"] for n in p["next"]] == ["limits show qobuz", "limits show soundcloud"]
    assert {n["why"] for n in p["next"]} == {"today's downloads and why they paused"}
    waiting = only("downloads_paused", paused_accounts=frozenset({"youtube"}))
    assert waiting["text"] == "Paused today to protect your account: YouTube Premium."
    assert run("downloads_paused", downloads={"qobuz": {"state": "used_up"}}) == []  # used up is not paused


# --- the library's own checks ---

def counts(**changed):
    return {**GOOD.rekordbox_match, **changed}


def test_files_out_of_place_is_a_note_that_looks_at_the_tidy_up():
    assert run("out_of_place") == []
    p = only("out_of_place", tidy_rows=3)
    assert (p["level"], p["count"], p["text"]) == ("note", 3, "3 files are not where the playlist order puts them.")
    assert p["next"] == [{"run": "tidy run --dry-run", "why": "which files a tidy-up would move"}]
    assert only("out_of_place", tidy_rows=1)["text"] == "1 file is not where the playlist order puts it."


def test_superseded_files_are_a_note_with_their_size():
    assert run("superseded") == []
    p = only("superseded", superseded_files=2, superseded_bytes=36_200_000)
    assert (p["level"], p["count"]) == ("note", 2)
    assert p["text"] == words.doctor_superseded(2, 36_200_000) and p["text"].startswith("2 files in Superseded/, ")
    assert only("superseded", superseded_files=1, superseded_bytes=10)["text"].startswith("1 file in Superseded/, ")
    assert p["next"] == [{"run": "library superseded", "why": "the files and what rekordbox still uses"}]


def test_rekordbox_tracks_on_missing_or_superseded_files_are_a_problem_a_gig_depends_on():
    assert run("rekordbox_files") == []
    assert run("rekordbox_files", rekordbox_match=counts(away=4, not_in_library=2, not_in_rekordbox=9)) == []  # not these
    p = only("rekordbox_files", rekordbox_match=counts(missing=2, superseded=1))
    assert (p["level"], p["count"]) == ("problem", 3)
    assert p["text"] == "3 rekordbox tracks point at files that are missing or in Superseded/."
    assert p["next"] == [{"run": "rekordbox match", "why": "which tracks, and their files"}]
    assert only("rekordbox_files", rekordbox_match=counts(superseded=1))["text"].startswith("1 rekordbox track points ")


def test_a_rekordbox_that_was_not_compared_claims_nothing():
    assert run("rekordbox_files", rekordbox_match=None) == []  # never read as "everything matches" or as a problem


def test_a_stopped_aiff_batch_can_be_resumed_and_a_stopped_move_batch_is_looked_at():
    assert run("stopped_batches") == []
    p = only("stopped_batches", stopped_batches=("aiff:2", "moves:3", "aiff:1"))
    assert (p["level"], p["count"]) == ("problem", 3) and p["text"] == "3 batches stopped before their end."
    assert p["next"] == [{"run": "batch resume aiff:2", "why": "goes on where it stopped"},
                         {"run": "batch show moves:3", "why": "what it moved"},
                         {"run": "batch resume aiff:1", "why": "goes on where it stopped"}]
    assert only("stopped_batches", stopped_batches=("aiff:2",))["text"] == "1 batch stopped before its end."


def test_open_checks_cdj_problems_and_waiting_upgrades_are_notes_with_their_list():
    for key, fact, run_, text in (
            ("open_checks", "check_tracks", "check list", "2 tracks wait for a check in rekordbox."),
            ("cdj", "cdj_files", "todo list --group cdj", "2 files won't play well on CDJs."),
            ("upgrades_waiting", "upgrades_ready", "upgrade list", "2 better versions wait for you.")):
        assert run(key) == []
        p = only(key, **{fact: 2})
        assert (p["level"], p["count"], p["text"], p["next"][0]["run"]) == ("note", 2, text, run_)
    assert only("open_checks", check_tracks=1)["text"] == "1 track waits for a check in rekordbox."
    assert only("cdj", cdj_files=1)["text"] == "1 file won't play well on CDJs."
    assert only("upgrades_waiting", upgrades_ready=1)["text"] == "1 better version waits for you."


def test_songs_without_a_file_says_each_part_on_its_own():
    assert run("songs_without_file") == []
    (missing,) = run("songs_without_file", missing_files=3)
    assert missing["text"] == "3 songs' files are missing." and missing["next"][0]["run"] == "missing list"
    (load,) = run("songs_without_file", to_load=1)
    assert load["text"] == "1 playlist song has no file yet." and load["next"][0]["run"] == "sync plan"
    both = run("songs_without_file", missing_files=1, to_load=5)
    assert [p["text"] for p in both] == ["1 song's file is missing.", "5 playlist songs have no file yet."]
    assert {p["level"] for p in both} == {"note"}


# --- the answer ---

def test_without_a_music_folder_the_library_checks_are_skipped_and_say_nothing():
    broken = replace(GOOD, music_state="not_chosen", music_path="", pending=True, away_folders=("/Volumes/X/y",),
                     paused_accounts=frozenset({"youtube"}))
    answer = doctor.answer(broken, False)
    states = {c["check"]: c["state"] for c in answer["checks"]}
    assert states["pending_steps"] == states["drives_away"] == states["downloads_paused"] == "skipped"
    assert states["music_folder"] == "problem" and states["tools"] == "ok"
    assert [p["check"] for p in answer["problems"]] == ["music_folder"]
    assert answer["text"] == "1 problem, 0 notes."
    assert doctor.answer(broken, True)["text"] == "3 problems, 1 note."  # with a folder the same facts are all read


def test_problems_come_first_then_notes_each_in_check_order():
    facts = replace(GOOD, missing_tools=(("deno", "brew install deno"),), pending=True, away_folders=("/Volumes/X/y",),
                    rekordbox_state="ready", rekordbox_problem="busy", paused_accounts=frozenset({"youtube"}),
                    unreadable_folders=("/Users/dj/Crates",))
    answer = doctor.answer(facts, True)
    assert [(p["check"], p["level"]) for p in answer["problems"]] == [
        ("tools", "problem"), ("folder_access", "problem"), ("pending_steps", "problem"), ("drives_away", "problem"),
        ("rekordbox", "note"), ("downloads_paused", "note")]
    assert answer["text"] == "4 problems, 2 notes."
    states = {c["check"]: c["state"] for c in answer["checks"]}
    assert states["rekordbox"] == states["downloads_paused"] == "note" and states["tools"] == "problem"


def test_a_problem_carries_its_check_and_whether_a_gig_depends_on_it():
    answer = doctor.answer(replace(GOOD, missing_tools=(("deno", "brew install deno"),), pending=True), True)
    tools, pending = answer["problems"]
    assert (tools["check"], tools["gig"]) == ("tools", False) and (pending["check"], pending["gig"]) == ("pending_steps", True)
    assert list(pending) == ["check", "level", "gig", "text", "count", "next", "person_steps"]


def test_one_problem_one_note_use_the_one_forms():
    facts = replace(GOOD, pending=True, rekordbox_problem="busy")
    assert doctor.answer(facts, True)["text"] == "1 problem, 1 note."


# --- the app a person grants ---

@pytest.mark.parametrize("environ, app", [
    ({"__CFBundleIdentifier": "com.apple.Terminal"}, "Terminal"),
    ({"__CFBundleIdentifier": "com.googlecode.iterm2"}, "iTerm"),
    ({"__CFBundleIdentifier": "com.microsoft.VSCode"}, "Visual Studio Code"),
    ({"__CFBundleIdentifier": "dev.warp.Warp-Stable"}, "Warp"),
    ({"TERM_PROGRAM": "Apple_Terminal"}, "Terminal"), ({"TERM_PROGRAM": "iTerm.app"}, "iTerm"),
    ({"TERM_PROGRAM": "vscode"}, "Visual Studio Code"), ({"TERM_PROGRAM": "WarpTerminal"}, "Warp"),
    ({"__CFBundleIdentifier": "com.apple.Terminal", "TERM_PROGRAM": "vscode"}, "Terminal"),  # the bundle id wins
    ({"__CFBundleIdentifier": "com.example.Unknown", "TERM_PROGRAM": "iTerm.app"}, "iTerm"),  # an id we do not know: the next
    ({}, "the app you run this command in"), ({"TERM_PROGRAM": "tmux"}, "the app you run this command in")])
def test_running_app_names_the_app_the_command_runs_in(environ, app):
    assert words.running_app(environ) == app


def test_drive_name():
    assert doctor.drive_name("/Volumes/Gig Stick/Music/Crates") == "Gig Stick"
    assert doctor.drive_name("/Volumes/Gig Stick") == "Gig Stick"
    assert doctor.drive_name("/Volumes") == "/Volumes" and doctor.drive_name("/Users/dj") == "/Users/dj"
