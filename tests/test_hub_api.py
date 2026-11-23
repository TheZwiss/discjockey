import inspect
import json
import os
import re
import threading
import time
from datetime import datetime, timedelta

import pytest
from hub_helpers import (ID1, LOSSLESS, LOSSY, PLAYLISTS, QOBUZ_LINK, fake_qobuz, fake_spotify, make_api, make_root,
                         refreshed, wait_job, write, window)

from discjockey import words
from discjockey.hub import api as api_module, jobs
from discjockey.hub.api import HubApi
from discjockey.library import load_state, save_state
from discjockey.settings import Settings, save_settings
from discjockey.sources import qobuz as qobuz_source, spotify

# The bridge contract (plan, Part B): every method the page may call, and nothing else.
CONTRACT = {
    "dashboard", "sidebar", "sync_preview", "refresh", "stop_refresh", "job_status", "library", "track", "todo",
    "playlists", "limits", "limits_what_if", "save_limits", "mark_warnings_seen", "runs", "run", "spectrum",
    "setup_status",
    "search_candidates", "preview", "add_playlist", "preview_playlist_change",
    "start_sync", "stop", "save_playlists", "hide", "never_download", "add_bought_file", "use_candidate",
    "use_link", "reject_current", "upgrade", "upgrade_all", "undo_upgrade", "batch_resume", "batch_undo",
    "aiff_plan", "convert", "rename", "make_aiff", "rekordbox_checked", "rescan_library",
    "show_in_finder", "reveal", "open_report", "open_external", "app_update",
    "setup_check_tools", "setup_save_client_id", "setup_spotify_login", "setup_qobuz_login",
    "open_licenses", "update_tools", "rollback_tools", "quit",
    "setup_skip_qobuz", "setup_skip_spotify", "setup_account", "setup_forget_account", "downloads_view",
    "find_logins", "account_sign_in", "stop_sign_in", "open_privacy_settings", "qobuz_check_login", "spotify_sign_out",
    "pick_folder", "check_music_folder", "set_music_folder", "retry_music_folder",
    "tidy_preview", "move_batches", "undo_preview", "tidy_up", "undo_moves",
    "watched_folders", "check_import_folder", "removal_preview", "add_watched_folder", "remove_watched_folder",
    "start_import", "answer_same_song", "keep_duplicates", "keep_file", "setup_skip_import",
    "set_favourites", "set_crate_shown", "set_crates_shown", "set_read_liked_music", "add_liked_music",
    "set_auto_upgrade", "rekordbox_status", "job_events", "missing_files_preview", "missing_files", "sync_scope", "set_sync_scope",
}
READ_ONLY = ["dashboard", "sidebar", "sync_preview", "job_status", "library", "todo", "limits",
             "runs", "setup_status", "playlists", "downloads_view", "tidy_preview", "move_batches", "watched_folders"]


@pytest.fixture
def root(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    return make_root(tmp_path, upgrade=True)


def public(api):
    return {name for name in dir(api) if not name.startswith("_")}


def test_the_page_sees_exactly_the_contract(root):
    api, _ = make_api(root)
    implemented = public(api) & CONTRACT
    assert public(api) <= CONTRACT  # nothing else is reachable from the page (pywebview exposes every public name)
    for name in implemented:
        assert inspect.ismethod(getattr(api, name))


def test_parameter_names_are_visible_to_pywebview(root):
    api, _ = make_api(root)
    assert inspect.getfullargspec(api.library).args == ["self", "view", "key", "query", "filter", "sort"]


@pytest.mark.parametrize("name", READ_ONLY)
def test_read_methods_answer_json(root, name):
    api, _ = make_api(root)
    answer = getattr(api, name)()
    assert answer["ok"] is True, answer
    json.dumps(answer)


def test_reads_never_write_anything(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    before = load_state(root)
    for name in READ_ONLY:
        getattr(api, name)()
    api.track("t2")
    api.run("2026-10-20_120000")
    api.limits_what_if("qobuz", 90, 10)
    assert load_state(root) == before
    assert not (root.data / "reports").exists() and not root.not_lossless_md.exists()


def test_errors_are_plain_json_never_a_traceback(root):
    api, _ = make_api(root)
    root.db_file.write_bytes(b"not a database, just some bytes" * 100)
    answer = api.dashboard()
    assert window(answer) == {"ok": False, "kind": "config_invalid", "message": answer["message"]}
    assert "library.db" in answer["message"] and "Traceback" not in answer["message"]


def test_wrong_arguments_from_the_page(root, capsys):
    api, _ = make_api(root)
    answer = api.track()
    assert answer["kind"] == "crashed" and answer["message"].startswith("Something unexpected went wrong.")
    assert "TypeError" not in answer["message"] and "TypeError" in capsys.readouterr().err  # the detail goes to the terminal
    assert api.library("all", None, "", "everything")["kind"] == "refused"
    assert api.library("somewhere")["kind"] == "refused" and api.library("playlist")["kind"] == "refused"  # no key


def test_dashboard_after_reading_spotify(root):
    api, rec = make_api(root)
    assert api.dashboard()["ready"] is None
    refreshed(api, rec)
    d = api.dashboard()
    assert d["ready"]["counts"]["new"] == 2 and d["read_status"]["read_at"] is not None  # when the read was stored
    assert d["needs_you"]["upgrades"] == 1 and d["tiles"]["lossless"]["total"] == 3


def test_sync_preview_lists_the_actions_with_ids(root):
    api, rec = make_api(root)
    assert api.sync_preview()["empty"] == "no_preview"
    refreshed(api, rec)
    p = api.sync_preview()
    assert [g["key"] for g in p["groups"]] == ["acquire:new"]
    rows = p["groups"][0]["actions"]
    assert [a["id"] for a in rows] == ["act:acquire:t4:1", "act:acquire:t5:2"] and not any("key" in a for a in rows)
    assert p["groups"][0]["actions"][0]["cover_url"] == "https://i.scdn.co/image/t4"  # not downloaded yet: Spotify's
    # issue 37: each row names the playlists it is in, by the browser column's keys, and the preview names them
    ins = [a["in"] for a in p["groups"][0]["actions"]]
    assert all(len(i) == 1 and i[0].startswith("playlist:") for i in ins) and ins[0] != ins[1]
    assert [p["collections"][i[0]] for i in ins] == ["Hard_Bounce", "Powertrance"]


def test_sync_preview_search_narrows_the_actions_like_the_librarys_search_and_nothing_else(root):
    api, rec = make_api(root)
    assert api.sync_preview("pegassi")["groups"] == [] and api.sync_preview("pegassi")["empty"] == "no_preview"  # no read yet
    refreshed(api, rec)
    whole = api.sync_preview()
    assert whole["search"] is None and api.sync_preview("") == whole and api.sync_preview("  ") == whole
    found = api.sync_preview(" Pégassi ")  # case, accents and the spaces around are not the words
    assert [(g["key"], [a["title"] for a in g["actions"]]) for g in found["groups"]] == [("acquire:new", ["AEIOU"])]
    assert found["search"] == "Pégassi"
    assert {k: v for k, v in found.items() if k not in ("groups", "search")} == {
        k: v for k, v in whole.items() if k not in ("groups", "search")}  # counts, estimate, presets, plan_id: the whole plan's
    assert found["groups"][0]["actions"][0] == whole["groups"][0]["actions"][0]  # the row is the whole plan's own row
    assert api.sync_preview("non stop")["groups"][0]["actions"][0]["id"] == whole["groups"][0]["actions"][1]["id"]
    assert api.sync_preview("torben")["groups"][0]["actions"][0]["artist"] == "torbentorben"  # the artist counts too
    assert api.sync_preview("no such song")["groups"] == [] and api.sync_preview("no such song")["counts"] == whole["counts"]
    assert len(list((root.support / "plans").iterdir())) == 1  # a search stores no plan of its own


def plan_file(root, plan_id):
    return root.support / "plans" / f"{plan_id.removeprefix('plan:')}.json"


def test_sync_preview_gives_every_action_an_id_and_stores_its_plan(root):
    api, rec = make_api(root)
    before = api.sync_preview()
    assert (before["plan_id"], before["presets"], before["default_how_many"]) == (None, [], None)
    assert not (root.support / "plans").exists()  # no plan: nothing to store
    refreshed(api, rec)
    p = api.sync_preview()
    actions = p["groups"][0]["actions"]
    assert [a["id"] for a in actions] == ["act:acquire:t4:1", "act:acquire:t5:2"]  # n: the folder's place in playlists.txt
    assert re.fullmatch(r"plan:[0-9a-f]{12}", p["plan_id"])
    body = json.loads(plan_file(root, p["plan_id"]).read_text())
    assert body["items"] == {"act:acquire:t4:1": {"kind": "acquire", "track_id": "t4", "to_dir": "Library/Hard_Bounce"},
                             "act:acquire:t5:2": {"kind": "acquire", "track_id": "t5", "to_dir": "Library/Powertrance"}}
    assert body["kind"] == "sync" and body["root"] == str(root.root) and body["extra"]["read_id"] == "read:1"
    assert isinstance(body["extra"]["generation"], int) and body["extra"]["command"] == "sync run"  # what an expired one says to repeat
    assert [(x["key"], x["downloads"], x["selected"]) for x in p["presets"]] == [
        ("all", 2, ["act:acquire:t4:1", "act:acquire:t5:2"])] and p["default_how_many"] == "all"


def test_a_sync_preview_that_changed_nothing_saves_nothing_new_until_an_hour_passed(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    first = api.sync_preview()["plan_id"]
    file = plan_file(root, first)
    os.utime(file, ns=(1_000_000_000, 1_000_000_000))  # a mark to see a second save by
    assert api.sync_preview()["plan_id"] == first
    assert file.stat().st_mtime_ns == 1_000_000_000  # same plan, saved a moment ago: left alone
    api._saved_plan = (first, api._saved_plan[1], datetime.now() - timedelta(hours=2))
    api.sync_preview()
    assert file.stat().st_mtime_ns != 1_000_000_000  # over an hour: saved again, the 24 hours start over
    assert wait_job(api, rec, api.never_download("t4", True)).ok  # another plan: another id and file
    second = api.sync_preview()["plan_id"]
    assert second != first and plan_file(root, second).is_file()
    assert {f.name for f in (root.support / "plans").iterdir()} == {f"{first[5:]}.json", f"{second[5:]}.json"}


def test_a_target_that_changed_under_the_same_plan_id_is_saved_at_once(root):
    api, rec = make_api(root)
    refreshed(api, rec)
    first = api.sync_preview()["plan_id"]
    root.playlists_file.write_text(root.playlists_file.read_text().replace("Powertrance =", "Powertrance2 ="))
    refreshed(api, rec)
    p = api.sync_preview()
    assert p["plan_id"] == first  # the id hashes the action ids only
    assert [a["to_dir"] for a in p["groups"][0]["actions"]] == ["Library/Hard_Bounce", "Library/Powertrance2"]
    items = json.loads(plan_file(root, first).read_text())["items"]
    assert items["act:acquire:t5:2"]["to_dir"] == "Library/Powertrance2"  # the stored plan follows what was shown


def test_never_download_and_back(root):
    api, rec = make_api(root)
    assert api.never_download("t4", True)["kind"] == "changed"  # not read yet: nothing to mark
    refreshed(api, rec)
    assert wait_job(api, rec, api.never_download("t4", True)).ok
    saved = load_state(root)["never"]["t4"]
    assert (saved["folder"], saved["at"]) == ("Hard_Bounce", "2026-10-20")
    p = api.sync_preview()
    assert [r["track_id"] for r in p["never"]] == ["t4"]
    assert [a["track_id"] for a in p["groups"][0]["actions"]] == ["t5"]
    assert wait_job(api, rec, api.never_download("t4", False)).ok
    assert load_state(root)["never"] == {}
    assert api.sync_preview()["never"] == []
    # the log tells the two switches from issue 43's Download again of a missing file ("download again")
    lines = [json.loads(line) for line in root.operations_log.read_text().splitlines()]
    assert [(line["track_id"], line["operation"], line["result"]) for line in lines] == [
        ("t4", "never download", "done"), ("t4", "download allowed", "done")]


def test_a_changed_playlists_txt_is_read_again_by_itself(root):
    api, rec = make_api(root)
    api._watch_playlists_file(interval=0.02)
    time.sleep(0.1)
    assert not [e for e in rec.events if isinstance(e, jobs.JobStarted)]  # nothing changed yet
    root.playlists_file.write_text(root.playlists_file.read_text() + "\n# a comment\n")
    end = time.monotonic() + 5
    while not [e for e in rec.events if isinstance(e, jobs.JobFinished) and e.kind == "refresh"]:
        assert time.monotonic() < end, "no refresh started"
        time.sleep(0.02)
    api._jobs.close()


def started_reads(rec):
    return [e for e in rec.events if isinstance(e, jobs.JobStarted) and e.kind == "refresh"]


def test_spotify_is_read_by_itself_once_per_session(root):
    api, rec = make_api(root)
    assert api.job_status()["read_status"]["auto_read"] is False
    assert wait_job(api, rec, api.refresh(auto=True)).ok  # the first automatic read
    assert api.sync_preview()["read_status"]["auto_read"] is True
    again = api.refresh(auto=True)  # the Sync page opened again, or after a window reload
    assert again["ok"] is False and again["kind"] == "refused"
    assert len(started_reads(rec)) == 1
    assert refreshed(api, rec).ok  # "↻ Read Spotify" still reads
    assert len(started_reads(rec)) == 2 and api.dashboard()["read_status"]["auto_read"] is True


def test_a_qobuz_playlist_without_a_qobuz_login_blocks_the_read_under_qobuz(root, monkeypatch):
    fake_qobuz(monkeypatch, connected=False)
    root.playlists_file.write_text(PLAYLISTS + f"Example_Playlist = {QOBUZ_LINK}\n")
    api, rec = make_api(root)
    done = wait_job(api, rec, api.refresh())
    assert (done.ok, done.problem) == (False, "not_set_up")
    expected = [{"service": "spotify", "name": "Spotify", "connected": True},
                {"service": "qobuz", "name": "Qobuz", "connected": False}]
    for status in (api.job_status()["read_status"], api.sync_preview()["read_status"], api.dashboard()["read_status"]):
        assert (status["problem"], status["problem_service"]) == ("not_set_up", "qobuz")
        assert status["services"] == expected


def test_only_the_services_the_switched_on_lines_use_are_listed(root, monkeypatch):
    fake_qobuz(monkeypatch, connected=False)
    root.playlists_file.write_text(PLAYLISTS + f"#off# Example_Playlist = {QOBUZ_LINK}\n")
    api, rec = make_api(root)
    assert [s["service"] for s in api.job_status()["read_status"]["services"]] == ["spotify"]
    root.playlists_file.write_text("# nothing yet\n")
    assert api.job_status()["read_status"]["services"] == []


def test_a_playlists_file_that_cannot_be_read_never_fails_the_poll(root):
    root.playlists_file.write_bytes(b"\xff\xfe")
    api, rec = make_api(root)
    status = api.job_status()
    assert status["ok"] and status["read_status"]["services"] == []


def test_a_login_file_that_makes_no_sense_never_fails_the_poll(root, monkeypatch):
    fake_qobuz(monkeypatch)

    def broken(paths):
        raise AttributeError("'str' object has no attribute 'get'")  # a [qobuz] entry that isn't a table

    monkeypatch.setattr(qobuz_source, "login_state", broken)
    root.playlists_file.write_text(PLAYLISTS + f"Example_Playlist = {QOBUZ_LINK}\n")
    api, rec = make_api(root)
    status = api.job_status()
    assert status["ok"]
    assert [(s["service"], s["connected"]) for s in status["read_status"]["services"]] == [
        ("spotify", True), ("qobuz", False)]


def test_a_failed_first_automatic_read_is_not_repeated_by_itself(root, monkeypatch):
    api, rec = make_api(root)

    def offline(s, line):
        raise spotify.SpotifyError("Cannot reach Spotify (no connection).", "offline")

    monkeypatch.setattr(spotify, "fetch_playlist", offline)
    assert wait_job(api, rec, api.refresh(auto=True)).problem == "offline"
    assert api.refresh(auto=True)["ok"] is False and len(started_reads(rec)) == 1


def test_a_stopped_first_automatic_read_is_not_repeated_by_itself(root, monkeypatch):
    api, rec = make_api(root)
    release = threading.Event()
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: release.wait(10) and None)
    answer = api.refresh(auto=True)
    deadline = time.monotonic() + 3
    while len(started_reads(rec)) != 1 and time.monotonic() < deadline:  # the thread sends JobStarted a moment after
        time.sleep(0.01)
    assert len(started_reads(rec)) == 1
    assert api.stop_refresh()["stopped"] is True
    assert wait_job(api, rec, answer, timeout=2).problem == "stopped"
    assert api.refresh(auto=True)["ok"] is False and len(started_reads(rec)) == 1
    release.set()


def test_an_automatic_read_that_could_not_start_does_not_count(root):
    api, rec = make_api(root)
    release = threading.Event()
    api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    assert api.refresh(auto=True)["kind"] == "busy"
    assert api.job_status()["read_status"]["auto_read"] is False
    release.set()
    api._jobs.wait(5)
    assert wait_job(api, rec, api.refresh(auto=True)).ok


def test_library_track_and_todo(root):
    api, rec = make_api(root)
    lib = api.library("folder", "Library/Hard_Bounce", "", "all", "title")
    assert [r["track_id"] for r in lib["rows"]] == ["t2", "t1"]
    t = api.track("t2")["track"]
    assert t["upgrade"]["cue_text"] == "matches exactly, cues stay" and t["quality"] == "weak"
    todo = api.todo()
    assert [g["key"] for g in todo["groups"]] == ["upgrade_ready", "not_found"]
    assert api.track("nope")["kind"] == "changed"


def test_a_todo_filter_that_is_no_group_is_the_command_lines_bad_args_and_cdj_is_a_group(root):
    api, _ = make_api(root)
    nope = api.todo("nope")
    assert (nope["ok"], nope["kind"], nope["outcome"], nope["reason"]) == (False, "bad_args", "bad_args", "usage")
    assert "cdj" in nope["message"]                       # the words name every group the page can ask for
    assert api.todo("cdj")["ok"] is True


def test_library_rows_carry_the_same_track_link_as_the_details(root):
    """The row menu's "Open in …" reads the row (there when the menu opens): the same link the details' head has,
    here from the keys (no read yet); asking for the rows makes no call to a service (fake_spotify only serves reads)."""
    api, _ = make_api(root)
    rows = api.library("folder", "Library/Hard_Bounce", "", "all", "title")["rows"]
    assert rows and all(r["track_link"] == api.track(r["track_id"])["track"]["track_link"] for r in rows)
    assert all(r["track_link"] and r["track_link"]["label"].startswith("Open in ") for r in rows)


def test_sidebar_counts(root):
    api, _ = make_api(root)
    sb = api.sidebar()
    assert sb["todo"] == 2 and sb["all_tracks"] == 2
    assert [(p["name"], p["enabled"]) for p in sb["playlists"]] == [("Hard_Bounce", True), ("Powertrance", True)]
    assert sb["library_folders"] == []


def test_sidebar_lists_every_playlists_line_with_its_service_and_switch(root):
    api, _ = make_api(root)
    root.playlists_file.write_text(PLAYLISTS + f"#off# Example_Playlist = {QOBUZ_LINK}\n")
    rows = api.sidebar()["playlists"]
    assert [(p["name"], p["service"], p["enabled"]) for p in rows] == [
        ("Hard_Bounce", "spotify", True), ("Powertrance", "spotify", True), ("Example_Playlist", "qobuz", False)]
    assert rows[2]["ref"].startswith("qobuz:") and rows[2]["songs"] is None  # never read


def test_a_finished_read_gives_the_sidebar_each_playlists_songs(root):
    api, rec = make_api(root)
    assert [p["songs"] for p in api.sidebar()["playlists"]] == [None, None]
    finished = refreshed(api, rec)  # B2.4: the page re-reads the sidebar on this JobFinished
    assert (finished.kind, finished.ok) == ("refresh", True)
    sb = api.sidebar()
    assert [(p["name"], p["songs"]) for p in sb["playlists"]] == [("Hard_Bounce", 4), ("Powertrance", 2)]
    assert (sb["favourites"], sb["watched"]) == ([], [])
    assert sb["library_folders"] == []


def test_library_subtitle_comes_from_the_playlists_lines(root):
    api, _ = make_api(root)
    assert api.library("folder", "Library/Hard_Bounce")["subtitle"] == ["2 tracks", "Library › Hard_Bounce"]  # in use
    assert api.library("playlist", "Hard_Bounce")["subtitle"] == ["Spotify playlist", "not read yet"]
    assert api.library()["subtitle"] == ["2 tracks", "every folder"]
    summary = api.library()["summary"]
    assert summary["not_lossless"] == 1 and summary["by_quality"]["lossless"] == 1


def test_a_playlist_view_comes_from_its_read_record_and_the_track_says_where_it_sits(root):
    api, rec = make_api(root)
    never = api.library("playlist", "hard_bounce")
    assert (never["rows"], never["read_at"], never["title"]) == ([], None, "Hard_Bounce")
    assert [r["track_id"] for r in never["also"]] == ["t2", "t1"]  # the folder's files by artist and title, before any read
    refreshed(api, rec)
    out = api.library("playlist", "Hard_Bounce")
    assert out["read_at"] and out["service"] == "spotify" and out["enabled"] is True and out["also"] == []
    assert [(r["track_id"], r["position"], r["file_state"], r["wait"]) for r in out["rows"]] == [
        ("t1", 1, "here", None), ("t2", 2, "here", None), ("t3", 3, "no_file", "not_found"),  # t3 is in the library
        ("t4", 4, "no_file", "waiting")]  # t4 isn't yet
    assert api.library("playlist", "Nowhere")["empty"] == "gone"
    assert api.library("folder", "Library/Nowhere")["empty"] == "gone"
    assert api.track("t2")["track"]["place"] == "Hard_Bounce"
    assert api.library()["rows"][0]["place"] == "Hard_Bounce"


def test_runs_and_one_run(root):
    api, _ = make_api(root)
    (root.reports).mkdir()
    (root.reports / "2026-10-19_214700.json").write_text(json.dumps(
        {"started": "2026-10-19T21:47:00", "finished": "2026-10-19T22:11:00", "exit_code": 0, "results": []}))
    (root.reports / "operations.jsonl").write_text("{}\n")
    assert [r["run_id"] for r in api.runs()["runs"]] == ["2026-10-19_214700"]
    assert api.run("2026-10-19_214700")["run"]["duration_s"] == 1440
    assert api.run("../../etc/passwd")["kind"] == "refused"


def test_spectrum_needs_a_file(root):
    import numpy as np
    api, _ = make_api(root, decode=lambda p: (np.zeros(44100, dtype=np.float32), 44100))
    s = api.spectrum("t2")["spectrum"]
    assert s["cols"] == 400 and s["cutoff_hz"] == 16000 and s["which"] == "current"
    assert api.spectrum("t2", "upgrade")["spectrum"]["cutoff_hz"] is None
    assert api.spectrum("t3")["kind"] == "refused"  # not found: no file
    assert api.spectrum("t2", "elsewhere")["kind"] == "refused"


def test_show_in_finder_reveal_and_links(root):
    api, _ = make_api(root)
    api.show_in_finder("t1")
    assert api._svc.calls["reveal"] == [root.root / LOSSLESS]
    assert api.reveal("Library/Hard_Bounce")["ok"]
    assert api.reveal("../outside")["kind"] == "refused" and api.reveal("/etc")["kind"] == "refused"
    assert api.open_external("https://www.beatport.com/search?q=x")["ok"]
    assert api.open_external("file:///etc/passwd")["kind"] == "refused"
    assert api._svc.calls["open_url"] == ["https://www.beatport.com/search?q=x"]
    write(root, ".discjockey/reports/2026-10-19_214700.md", b"# report")
    assert api.open_report("2026-10-19_214700")["ok"] and api.open_report("x")["kind"] == "refused"


def test_the_openers_answer_what_they_opened_and_print_only_opens_nothing(root):
    api, _ = make_api(root)
    calls = api._svc.calls
    write(root, ".discjockey/reports/2026-10-19_214700.md", b"# report")
    url = "https://www.beatport.com/search?q=x"
    cases = [  # the call, the opener it uses, what it names
        (lambda **k: api.show_in_finder("t1", **k), "reveal", str(root.root / LOSSLESS)),
        (lambda **k: api.reveal("Library/Hard_Bounce", **k), "reveal", str(root.root / "Library/Hard_Bounce")),
        (lambda **k: api.open_report("2026-10-19_214700", **k), "open_path", str(root.root / ".discjockey/reports/2026-10-19_214700.md")),
        (lambda **k: api.open_external(url, **k), "open_url", url),
        (lambda **k: api.open_privacy_settings(**k), "open_url", api_module._PRIVACY_SETTINGS),
    ]
    for call, opener, target in cases:
        assert call(print_only=True) == {"ok": True, "target": target, "opened": False,
                                          "text": words.NOT_OPENED.format(target=target)}
        assert not any(calls.values()), target
        assert call() == {"ok": True, "target": target, "opened": True,
                          "text": words.OPENED.format(target=target)}
        assert len(calls[opener]) == 1, target
        calls[opener].clear()
    # every check still runs with print_only: nothing is told about a place the page may not open
    assert api.reveal("../outside", print_only=True)["kind"] == "refused"
    assert api.open_external("file:///etc/passwd", print_only=True)["kind"] == "refused"
    assert api.open_report("x", print_only=True)["kind"] == "refused"
    assert not any(calls.values())


def test_the_buy_list_is_a_report_file_open_report_names(root):
    api, _ = make_api(root)
    assert api.open_report("not-lossless", print_only=True)["message"] == words.NO_BUY_LIST
    write(root, ".discjockey/not_lossless.md", b"# buy")
    assert api.open_report("not-lossless") == {
        "ok": True, "target": str(root.not_lossless_md), "opened": True, "text": words.OPENED.format(target=root.not_lossless_md)}
    assert api._svc.calls["open_path"] == [root.not_lossless_md]


def test_setup_status_never_shows_secrets(root):
    api, _ = make_api(root)
    root.spotify_app.write_text(json.dumps({"client_id": "0" * 32}))
    root.spotify_token.write_text(json.dumps({"access_token": "SECRET-A", "refresh_token": "SECRET-R"}))
    cfg = root.streamrip_dir / "config.toml"
    cfg.parent.mkdir()
    cfg.write_text('[qobuz]\nemail_or_userid = "dj@example.com"\npassword_or_token = "SECRET-P"\n')
    s = api.setup_status()
    assert s["complete"] and s["next_step"] is None and s["tools"]["deno"]
    assert "SECRET" not in json.dumps(s) and "dj@example.com" not in json.dumps(s)
    api._svc.which = lambda tool: None if tool == "deno" else "/x"
    assert api.setup_status()["next_step"] == "tools"


def test_setup_status_names_the_downloads_step(root):
    # Qobuz neither signed in nor left out: the step to finish is Downloads (Qobuz and the other logins together)
    api, _ = make_api(root)
    root.spotify_app.write_text(json.dumps({"client_id": "0" * 32}))
    root.spotify_token.write_text(json.dumps({"access_token": "a", "refresh_token": "r"}))
    s = api.setup_status()
    assert not s["qobuz"] and not s["qobuz_skipped"]
    assert s["next_step"] == "downloads" and not s["complete"]


def test_the_window_s_selection_is_not_a_bridge_method(root):
    api, _ = make_api(root)
    assert not hasattr(api, "select") and not hasattr(api, "_selected")


def test_a_skipped_spotify_is_no_problem_until_playlists_txt_has_a_spotify_line(root, monkeypatch):
    fake_qobuz(monkeypatch, connected=True)
    save_settings(root.settings_file, Settings(spotify_skipped=True))
    root.playlists_file.write_text(f"Example_Playlist = {QOBUZ_LINK}\n")
    api, rec = make_api(root)
    assert api.setup_status()["next_step"] != "spotify"
    status = api.job_status()["read_status"]
    assert status["services"] == [{"service": "qobuz", "name": "Qobuz", "connected": True}]
    assert status["problem"] is None
    root.playlists_file.write_text(PLAYLISTS + f"Example_Playlist = {QOBUZ_LINK}\n")
    assert [s["service"] for s in api.job_status()["read_status"]["services"]] == ["spotify", "qobuz"]
