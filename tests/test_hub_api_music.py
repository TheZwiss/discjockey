"""The hub without a music folder, choosing one, binding it, and a folder that went away (spec public-release §4)."""
import json
import threading

import pytest
from hub_helpers import make_api, make_root, make_unbound_api, services, wait_job

from discjockey import library, tools
from discjockey.hub import api as api_mod
from discjockey.hub.api import LIBRARY_METHODS, HubApi
from discjockey.library import Paths, Resolved, run_lock


@pytest.fixture
def support(tmp_path):
    return tmp_path / "support"


def started(monkeypatch):
    """What _bind starts, recorded instead of run (no Spotify, no threads)."""
    seen = []
    monkeypatch.setattr(HubApi, "refresh", lambda self, auto=False: seen.append(("refresh", auto)) or {"ok": True})
    monkeypatch.setattr(HubApi, "_watch_playlists_file", lambda self, interval=2.0: seen.append(("watch",)))
    return seen


def test_unbound_setup_status_starts_with_the_music_folder(support):
    api, _ = make_unbound_api(support)
    s = api.setup_status()
    assert s["ok"] and s["next_step"] == "music" and s["complete"] is False
    assert s["music"] == {"state": "not_chosen", "path": None,
                          "suggested": "/nonexistent-home/Music/Discjockey"}
    assert s["playlists"] is False


def test_every_library_method_answers_no_library_while_unbound(support):
    api, rec = make_unbound_api(support)
    for name in sorted(LIBRARY_METHODS):
        r = getattr(api, name)()
        assert (r["ok"], r["kind"]) == (False, "no_library"), name
        assert r["message"] == api_mod.NOT_CHOSEN, name
    assert rec.events == [] and api._jobs.running() is None


def test_library_methods_are_bridge_methods(support):
    api, _ = make_unbound_api(support)
    public = {n for n in dir(api) if not n.startswith("_")}
    assert LIBRARY_METHODS <= public


def test_setup_works_without_a_music_folder(support):
    api, rec = make_unbound_api(support)
    assert api.job_status()["ok"] and api.setup_check_tools()["ok"]
    assert api.downloads_view()["ok"]
    f = wait_job(api, rec, api.setup_save_client_id("0" * 32))
    assert f.ok and json.loads((support / ".spotify_app.json").read_text()) == {"client_id": "0" * 32}
    f = wait_job(api, rec, api.setup_skip_qobuz())
    assert f.ok and json.loads((support / "settings.json").read_text())["qobuz_skipped"] is True
    assert sorted(p.name for p in support.iterdir()) == [".spotify_app.json", "settings.json"]


def test_choosing_a_folder_binds_it_in_place(support, tmp_path, monkeypatch):
    seen = started(monkeypatch)
    api, _ = make_unbound_api(support)
    music = tmp_path / "home" / "Music" / "Discjockey"
    r = api.set_music_folder(str(music))
    assert r["ok"] and r["restart"] is False and r["music"]["state"] == "ok"
    assert r["music"]["path"] == str(music.resolve()) and music.is_dir()  # "new": made on the user's choice
    assert library.read_music_folder(support) == music.resolve()
    assert api._paths == Paths(music.resolve(), support=support)
    assert api._jobs.lock == music.resolve() / ".discjockey" / ".lock"
    assert seen == [("watch",), ("refresh", True)]
    assert api.sidebar()["ok"] and api.setup_status()["next_step"] != "music"
    with pytest.raises(RuntimeError):  # a library is bound once per process
        api._bind(Paths(tmp_path, support=support))
    api._jobs.close()  # stops the terminal-run watch


@pytest.mark.parametrize("where", ["relative", "/", "SUPPORT", "SUPPORT/x", "FILE"])
def test_set_music_folder_refuses_and_writes_nothing(support, tmp_path, where):
    support.mkdir()
    (tmp_path / "file").write_text("x")
    api, _ = make_unbound_api(support)
    path = where.replace("SUPPORT", str(support)).replace("FILE", str(tmp_path / "file"))
    r = api.set_music_folder(path)
    assert (r["ok"], r["kind"]) == (False, "refused") and r["message"] in library.FOLDER_PROBLEMS.values()
    assert not (support / "config.json").exists() and not (support / "x").exists()
    assert api.setup_status()["music"]["state"] == "not_chosen"


def test_check_music_folder_reports_what_is_there(support, tmp_path):
    api, _ = make_unbound_api(support)
    lib = tmp_path / "DJ"
    (lib / "Library").mkdir(parents=True)
    r = api.check_music_folder(str(lib))
    assert r == {"ok": True, "path": str(lib.resolve()), "exists": True, "usable": True, "problem": None,
                 "kind": "discjockey_library", "message": None}
    r = api.check_music_folder(str(support))
    assert (r["usable"], r["problem"], r["message"]) == (False, "is_support_dir",
                                                          library.FOLDER_PROBLEMS["is_support_dir"])


def test_change_of_a_bound_folder_saves_and_asks_to_restart(tmp_path, monkeypatch):
    paths = make_root(tmp_path / "old")
    api, _ = make_api(paths)
    library.write_music_folder(paths.support, paths.root)
    other = tmp_path / "new"
    other.mkdir()
    r = api.set_music_folder(str(other))
    assert r["ok"] and r["restart"] is True, r
    assert library.read_music_folder(paths.support) == other.resolve()
    assert api._paths.root == paths.root  # no live rebind: the window closes and opens on the new folder


def test_choosing_the_open_folder_again_after_a_change_puts_config_right(tmp_path):
    paths = make_root(tmp_path / "a")
    api, _ = make_api(paths)
    library.write_music_folder(paths.support, paths.root)
    other = tmp_path / "b"
    other.mkdir()
    assert api.set_music_folder(str(other))["restart"] is True
    r = api.set_music_folder(str(paths.root))  # back to the open one: no restart needed
    assert r["ok"] and r["restart"] is False
    assert library.read_music_folder(paths.support) == paths.root


def test_the_same_folder_again_changes_nothing(tmp_path):
    paths = make_root(tmp_path / "lib")
    api, _ = make_api(paths)
    library.write_music_folder(paths.support, paths.root)
    before = paths.config_file.stat().st_mtime_ns
    r = api.set_music_folder(str(paths.root))
    assert r["ok"] and r["restart"] is False and paths.config_file.stat().st_mtime_ns == before


def test_change_is_refused_while_a_job_or_the_console_runs(tmp_path):
    paths = make_root(tmp_path / "lib")
    api, _ = make_api(paths)
    library.write_music_folder(paths.support, paths.root)
    other = tmp_path / "other"
    other.mkdir()
    gate = threading.Event()
    api._jobs.start("sync", lambda ctx: gate.wait(5))
    try:
        r = api.set_music_folder(str(other))
        assert (r["ok"], r["kind"]) == (False, "busy")
    finally:
        gate.set()
        api._jobs.wait(5)
    with run_lock(paths.lock):  # a terminal run
        r = api.set_music_folder(str(other))
        assert (r["ok"], r["kind"]) == (False, "console")
    assert library.read_music_folder(paths.support) == paths.root


def test_missing_at_start_answers_no_library_then_binds_when_back(support, tmp_path, monkeypatch):
    seen = started(monkeypatch)
    gone = tmp_path / "DJ drive" / "Music"
    library.write_music_folder(support, gone)
    api, _ = make_unbound_api(support)
    api._start(library.resolve_in(support))
    status = api.setup_status()["music"]
    assert status["state"] == "missing" and status["path"] == str(gone)
    r = api.todo()
    assert (r["ok"], r["kind"]) == (False, "no_library") and str(gone) in r["message"]
    r = api.start_sync([])
    assert (r["ok"], r["kind"], r["message"]) == (False, "no_library", api_mod.MISSING.format(path=gone))
    assert api.retry_music_folder()["music"]["state"] == "missing" and not gone.exists() and seen == []
    (support / "config.json").unlink()  # config.json no longer names a folder: back to Setup's first step
    assert api.retry_music_folder()["music"] == {"state": "not_chosen", "path": None,
                                                 "suggested": "/nonexistent-home/Music/Discjockey"}
    library.write_music_folder(support, gone)
    assert api.retry_music_folder()["music"]["state"] == "missing"
    gone.mkdir(parents=True)
    assert api.retry_music_folder()["music"]["state"] == "ok"
    assert api._paths.root == gone and seen == [("watch",), ("refresh", True)]


def test_choose_another_while_missing_binds_it(support, tmp_path, monkeypatch):
    started(monkeypatch)
    library.write_music_folder(support, tmp_path / "gone")
    api, _ = make_unbound_api(support)
    api._start(library.resolve_in(support))
    other = tmp_path / "other"
    other.mkdir()
    r = api.set_music_folder(str(other))
    assert r["ok"] and r["restart"] is False and api._paths.root == other.resolve()
    assert not (tmp_path / "gone").exists()


def test_pick_folder_uses_the_window_dialog(support, tmp_path):
    asked = []
    api, _ = make_unbound_api(support, pick_folder=lambda start: asked.append(start) or "/Users/dj/Music/DJ")
    assert api.pick_folder() == {"ok": True, "path": "/Users/dj/Music/DJ"}
    assert asked == ["/"]  # /nonexistent-home/Music doesn't exist: the nearest folder that does
    (tmp_path / "start").mkdir()
    api.pick_folder(str(tmp_path / "start"))
    assert asked[-1] == str(tmp_path / "start")
    cancelled, _ = make_unbound_api(support, pick_folder=lambda start: None)
    assert cancelled.pick_folder() == {"ok": True, "path": None}
    none, _ = make_unbound_api(support)
    assert none.pick_folder()["kind"] == "refused"


def test_reveal_dot_is_the_music_folder(tmp_path):
    paths = make_root(tmp_path)
    api, _ = make_api(paths)
    assert api.reveal(".")["ok"] and api._svc.calls["reveal"] == [paths.root]


def test_attach_refuses_a_library_of_another_support_folder(tmp_path):
    api, _ = make_unbound_api(tmp_path / "a")
    with pytest.raises(ValueError):
        api._attach(Paths(tmp_path, support=tmp_path / "b"))


def test_a_music_folder_that_vanishes_while_open_is_missing_not_empty(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    paths = Paths(music, support=tmp_path / "support")
    paths.data.mkdir(parents=True)
    paths.support.mkdir()
    paths.playlists_file.write_text("")
    api, rec = make_api(paths)
    assert api.todo("all", False)["ok"] and api.setup_status()["music"]["state"] == "ok"
    moved = tmp_path / "moved"
    music.rename(moved)  # the drive is unplugged
    for name in ("todo", "library", "dashboard", "sidebar"):
        r = getattr(api, name)() if name != "todo" else api.todo("all", False)
        assert (r["ok"], r["kind"], r["message"]) == (False, "no_library", library.MUSIC_GONE), name
    status = api.setup_status()
    assert status["ok"] and status["music"] == {"state": "missing", "path": str(music),
                                                "suggested": "/nonexistent-home/Music/Discjockey"}
    assert api.retry_music_folder()["music"]["state"] == "missing"  # nothing to rebind, still not there
    moved.rename(music)  # plugged in again
    r = api.retry_music_folder()
    assert r["ok"] and r["music"]["state"] == "ok"
    assert api.todo("all", False)["ok"]


def test_choosing_another_folder_while_the_bound_one_is_gone_asks_for_a_restart(tmp_path):
    music = tmp_path / "music"
    music.mkdir()
    paths = Paths(music, support=tmp_path / "support")
    paths.data.mkdir(parents=True)
    paths.support.mkdir()
    api, _ = make_api(paths)
    library.write_music_folder(paths.support, music)
    music.rename(tmp_path / "moved")
    r = api.set_music_folder(str(tmp_path / "moved"))
    assert r["ok"] and r["restart"] is True, r
    assert library.read_music_folder(paths.support) == tmp_path / "moved"


def test_a_folder_inside_the_installed_app_is_refused(tmp_path, monkeypatch):
    """Issue #13: the app bundle, not the source checkout, is Discjockey's own folder once frozen."""
    app = tmp_path / "Discjockey.app"
    (app / "Contents" / "Resources").mkdir(parents=True)
    monkeypatch.setattr(tools, "program_dir", lambda: app)
    api, _ = make_unbound_api(tmp_path / "support")
    r = api.check_music_folder(str(app / "Contents" / "Resources" / "Music"))
    assert (r["ok"], r["usable"], r["problem"]) == (True, False, "inside_app")


# --- watched folders: what the window reads (plan library stage 4, I11) ---

def watched(tmp_path, monkeypatch, n=2):
    """A hub over a small library with one import folder of n files, imported."""
    from datetime import datetime
    from hub_helpers import fake_import, fake_spotify, import_folder, music_root
    from discjockey import db
    fake_spotify(monkeypatch)
    fake_import(monkeypatch)
    paths = music_root(tmp_path)
    folder = import_folder(tmp_path, n)
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    return paths, folder, api, rec


def test_the_watched_folders_list_the_library_first_with_counts_and_states(tmp_path, monkeypatch):
    paths, folder, api, rec = watched(tmp_path, monkeypatch)
    out = api.watched_folders()
    assert out["ok"] and (out["waiting"], out["stopped"], out["unreadable"]) == (0, False, [])
    assert [(r["kind"], r["name"], r["path"], r["state"], r["files"], r["waiting"], r["unreadable"])
            for r in out["folders"]] == [
        ("library", "Library", str(paths.library), "online", 2, 0, 0),
        ("import", "Music", str(folder), "online", 2, 0, 0)]


def test_a_folder_whose_drive_is_gone_is_offline_and_keeps_its_files(tmp_path, monkeypatch):
    import shutil
    paths, folder, api, rec = watched(tmp_path, monkeypatch)
    shutil.move(str(folder), str(tmp_path / "unplugged"))
    row = api.watched_folders()["folders"][1]
    assert (row["state"], row["files"]) == ("offline", 2)


def test_files_the_import_could_not_read_are_listed_with_their_folder_and_reason(tmp_path, monkeypatch):
    from discjockey import db, importer
    paths, folder, api, rec = watched(tmp_path, monkeypatch)
    with db.connect(paths.db_file) as conn:
        fid = conn.execute("SELECT id FROM files WHERE import_state = 'done' ORDER BY id").fetchone()[0]
        db.set_unreadable(conn, fid, importer.NO_ACCESS)
    out = api.watched_folders()
    assert [(u["folder_id"], u["reason"]) for u in out["unreadable"]] == [
        (out["folders"][1]["id"], "macOS doesn't let Discjockey read it")]
    assert out["unreadable"][0]["path"].startswith(str(folder)) and out["folders"][1]["unreadable"] == 1


def test_the_watched_folders_of_a_library_without_records_are_just_the_library(tmp_path):
    from hub_helpers import music_root
    paths = music_root(tmp_path)
    paths.db_file.unlink()
    api, _ = make_api(paths)
    out = api.watched_folders()
    assert out["ok"] and [(r["kind"], r["files"]) for r in out["folders"]] == [("library", 0)]


def test_checking_a_folder_says_what_it_would_be_in_the_refusals_words(tmp_path, monkeypatch):
    paths, folder, api, rec = watched(tmp_path, monkeypatch, n=1)
    ok = api.check_import_folder(str(tmp_path))  # holds the music folder
    assert (ok["ok"], ok["usable"], ok["problem"]) == (True, False, "holds_music")
    assert ok["message"] == "This folder holds your music folder. Choose a folder inside it instead."
    inside = api.check_import_folder(str(paths.library))
    assert (inside["problem"], inside["message"]) == (
        "music", "This is inside your music folder, which Discjockey watches already.")
    deeper = folder / "Sub"
    deeper.mkdir()
    in_watched = api.check_import_folder(str(deeper))
    assert in_watched["problem"] == "watched"
    assert in_watched["message"] == "This is inside Music, which Discjockey watches already."
    again = api.check_import_folder(str(folder))
    assert (again["problem"], again["message"]) == ("already", "Discjockey watches this folder already.")
    gone = api.check_import_folder(str(tmp_path / "nope"))
    assert (gone["problem"], gone["exists"], gone["message"]) == (
        "not_found", False, "That folder isn't there. If it is on a drive, connect the drive first.")
    relative = api.check_import_folder("Music")
    assert relative["problem"] == "not_absolute" and relative["message"]
    fresh = tmp_path / "outside" / "Another"
    fresh.mkdir()
    free = api.check_import_folder(str(fresh))
    assert (free["usable"], free["problem"], free["kind"], free["message"], free["merges"], free["merge_hints"]) == (
        True, None, "import", None, [], [])


def test_a_folder_holding_watched_ones_says_it_takes_them_over(tmp_path, monkeypatch):
    paths, folder, api, rec = watched(tmp_path, monkeypatch, n=1)
    parent = folder.parent
    out = api.check_import_folder(str(parent))
    assert (out["usable"], out["merges"]) == (True, [str(folder)])
    assert out["merge_hints"] == ["Music is inside it and becomes part of it."]


def test_the_removal_preview_names_the_folder_and_counts_what_goes(tmp_path, monkeypatch):
    paths, folder, api, rec = watched(tmp_path, monkeypatch, n=3)
    fid = api.watched_folders()["folders"][1]["id"]
    assert api.removal_preview(fid) == {"ok": True, "name": "Music", "files": 3, "redownload": 0}
    for bad in (api.watched_folders()["folders"][0]["id"], 999, "1", None, True):
        r = api.removal_preview(bad)
        assert (r["ok"], r["kind"], r["message"]) == (False, "refused", "That folder isn't one of the watched folders.")
