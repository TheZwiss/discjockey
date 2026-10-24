import inspect
import json
import threading
import time

import pytest
from hub_helpers import ID1, LOSSLESS, LOSSY, fake_spotify, make_api, make_root, refreshed, wait_job, write

from discjockey.hub import jobs
from discjockey.hub.api import HubApi
from discjockey.library import load_state, save_state

# The bridge contract (plan, Part B): every method the page may call, and nothing else.
CONTRACT = {
    "dashboard", "sidebar", "sync_preview", "refresh", "stop_refresh", "job_status", "library", "track", "todo",
    "playlists", "limits", "limits_what_if", "save_limits", "mark_warnings_seen", "runs", "run", "spectrum",
    "media_url", "setup_status", "select",
    "search_candidates", "preview", "add_playlist", "preview_playlist_change",
    "start_sync", "stop", "save_playlists", "hide", "never_download", "add_bought_file", "use_candidate",
    "use_link", "reject_current", "upgrade", "rekordbox_checked",
    "show_in_finder", "reveal", "open_report", "open_external", "app_update",
    "setup_check_tools", "setup_save_client_id", "setup_spotify_login", "setup_qobuz_login",
    "open_licenses", "update_tools", "rollback_tools", "quit",
    "setup_skip_qobuz", "setup_account", "setup_check_account", "setup_forget_account", "downloads_view",
    "find_logins", "account_sign_in", "stop_sign_in", "open_privacy_settings", "qobuz_check_login", "spotify_sign_out",
    "pick_folder", "check_music_folder", "set_music_folder", "retry_music_folder",
}
READ_ONLY = ["dashboard", "sidebar", "sync_preview", "job_status", "library", "todo", "limits",
             "runs", "setup_status", "playlists", "downloads_view"]


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
    assert inspect.getfullargspec(api.library).args == ["self", "folder", "query", "filter", "sort"]


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
    assert answer == {"ok": False, "kind": "config_invalid", "message": answer["message"]}
    assert "library.db" in answer["message"] and "Traceback" not in answer["message"]


def test_wrong_arguments_from_the_page(root, capsys):
    api, _ = make_api(root)
    answer = api.track()
    assert answer["kind"] == "crashed" and answer["message"].startswith("Something unexpected went wrong.")
    assert "TypeError" not in answer["message"] and "TypeError" in capsys.readouterr().err  # the detail goes to the terminal
    assert api.library(None, "", "everything")["kind"] == "refused"


def test_dashboard_after_reading_spotify(root):
    api, rec = make_api(root)
    assert api.dashboard()["ready"] is None
    refreshed(api, rec)
    d = api.dashboard()
    assert d["ready"]["counts"]["new"] == 2 and d["spotify"]["read_at"] == "2026-10-20T21:47:00"
    assert d["needs_you"]["upgrades"] == 1 and d["tiles"]["lossless"]["total"] == 3


def test_sync_preview_lists_the_actions_with_keys(root):
    api, rec = make_api(root)
    assert api.sync_preview()["empty"] == "no_preview"
    refreshed(api, rec)
    p = api.sync_preview()
    assert [g["key"] for g in p["groups"]] == ["acquire:new"]
    assert [a["key"] for a in p["groups"][0]["actions"]] == [["acquire", "t4", "Library/Hard_Bounce"],
                                                             ["acquire", "t5", "Library/Powertrance"]]
    assert p["groups"][0]["actions"][0]["cover_url"] == "https://i.scdn.co/image/t4"  # not downloaded yet: Spotify's


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
    assert api.job_status()["spotify"]["auto_read"] is False
    assert wait_job(api, rec, api.refresh(auto=True)).ok  # the first automatic read
    assert api.sync_preview()["spotify"]["auto_read"] is True
    again = api.refresh(auto=True)  # the Sync page opened again, or after a window reload
    assert again["ok"] is False and again["kind"] == "refused"
    assert len(started_reads(rec)) == 1
    assert refreshed(api, rec).ok  # "↻ Read Spotify" still reads
    assert len(started_reads(rec)) == 2 and api.dashboard()["spotify"]["auto_read"] is True


def test_a_failed_first_automatic_read_is_not_repeated_by_itself(root, monkeypatch):
    api, rec = make_api(root)

    def offline(s, line):
        raise jobs.spotify.SpotifyError("Cannot reach Spotify (no connection).", "offline")

    monkeypatch.setattr(jobs.spotify, "fetch_playlist", offline)
    assert wait_job(api, rec, api.refresh(auto=True)).problem == "offline"
    assert api.refresh(auto=True)["ok"] is False and len(started_reads(rec)) == 1


def test_a_stopped_first_automatic_read_is_not_repeated_by_itself(root, monkeypatch):
    api, rec = make_api(root)
    release = threading.Event()
    monkeypatch.setattr(jobs.spotify, "fetch_playlist", lambda s, line: release.wait(10) and None)
    answer = api.refresh(auto=True)
    assert api.stop_refresh()["stopped"] is True
    assert wait_job(api, rec, answer, timeout=2).problem == "stopped"
    assert api.refresh(auto=True)["ok"] is False and len(started_reads(rec)) == 1
    release.set()


def test_an_automatic_read_that_could_not_start_does_not_count(root):
    api, rec = make_api(root)
    release = threading.Event()
    api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    assert api.refresh(auto=True)["kind"] == "busy"
    assert api.job_status()["spotify"]["auto_read"] is False
    release.set()
    api._jobs.wait(5)
    assert wait_job(api, rec, api.refresh(auto=True)).ok


def test_library_track_and_todo(root):
    api, rec = make_api(root)
    lib = api.library("Hard_Bounce", "", "all", "title")
    assert [r["track_id"] for r in lib["rows"]] == ["t2", "t1"]
    t = api.track("t2")["track"]
    assert t["upgrade"]["cue_text"] == "matches exactly, cues stay" and t["quality"] == "weak"
    todo = api.todo()
    assert [g["key"] for g in todo["groups"]] == ["upgrade_ready", "not_found"]
    assert api.track("nope")["kind"] == "changed"


def test_sidebar_counts(root):
    api, _ = make_api(root)
    sb = api.sidebar()
    assert sb["todo"] == 2 and sb["all_tracks"] == 2
    assert [f["folder"] for f in sb["folders"]] == ["Hard_Bounce", "Powertrance"]


def test_runs_and_one_run(root):
    api, _ = make_api(root)
    (root.reports).mkdir()
    (root.reports / "2026-10-19_214700.json").write_text(json.dumps(
        {"started": "2026-10-19T21:47:00", "finished": "2026-10-19T22:11:00", "exit_code": 0, "results": []}))
    (root.reports / "operations.jsonl").write_text("{}\n")
    assert [r["run_id"] for r in api.runs()["runs"]] == ["2026-10-19_214700"]
    assert api.run("2026-10-19_214700")["run"]["duration_s"] == 1440
    assert api.run("../../etc/passwd")["kind"] == "refused"


def test_spectrum_and_media_need_a_file(root):
    import numpy as np
    api, _ = make_api(root, decode=lambda p: (np.zeros(44100, dtype=np.float32), 44100))
    s = api.spectrum("t2")["spectrum"]
    assert s["cols"] == 400 and s["cutoff_hz"] == 16000 and s["which"] == "current"
    assert api.spectrum("t2", "upgrade")["spectrum"]["cutoff_hz"] is None
    assert api.spectrum("t3")["kind"] == "refused"  # not found: no file
    assert api.media_url("t2")["kind"] == "refused"  # no media server in this test
    assert api.spectrum("t2", "elsewhere")["kind"] == "refused"


def test_media_url_through_the_server(root):
    from discjockey.hub.media import MediaServer
    api, _ = make_api(root)
    api._media = MediaServer(root)
    url = api.media_url("t2", "upgrade")["url"]
    assert url.startswith(f"http://127.0.0.1:{api._media.port}/{api._media.token}/Upgrades%20ready/")


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


def test_select_remembers_the_shown_track(root):
    api, _ = make_api(root)
    assert api.select("t2") == {"ok": True} and api._selected == "t2"
