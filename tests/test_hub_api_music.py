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


def test_binding_a_library_lets_its_first_plan_in_whatever_the_stored_ones_generation(tmp_path):
    from datetime import datetime
    from discjockey.models import Plan
    from discjockey.run import Prepared
    from discjockey.settings import Settings

    def prep(generation):
        st = {"version": 2, "tracks": {}, "generation": generation}
        return Prepared(None, st, Settings(), Plan(st, [], [], []), None)

    paths = make_root(tmp_path)
    api, _ = make_api(paths)
    api._store.ready(prep(5), datetime(2026, 10, 25, 12, 0))
    api._attach(paths)  # the records are opened again: they count their generation from 0
    fresh = prep(0)
    api._store.ready(fresh, datetime(2026, 10, 25, 12, 1))
    assert api._store.prep is fresh


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


def test_a_folder_that_is_gone_is_missing_and_keeps_its_files(tmp_path, monkeypatch):
    import shutil
    paths, folder, api, rec = watched(tmp_path, monkeypatch)
    shutil.move(str(folder), str(tmp_path / "moved"))  # not under /Volumes: no drive to blame, the folder is not found
    row = api.watched_folders()["folders"][1]
    assert (row["state"], row["files"]) == ("missing", 2)


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


def test_the_library_row_shows_its_own_waiting_and_unreadable_files(tmp_path, monkeypatch):
    from discjockey import db, importer
    paths, folder, api, rec = watched(tmp_path, monkeypatch)
    with db.connect(paths.db_file) as conn:  # two files that came into Library/ before the import finished them
        ids = [i for (i,) in conn.execute("SELECT f.id FROM files f JOIN watched_folders w ON w.id = f.folder "
                                          "WHERE w.kind = 'library' ORDER BY f.id")]
        conn.execute("UPDATE files SET import_state = 'new' WHERE id = ?", (ids[0],))
        db.set_unreadable(conn, ids[1], importer.NO_ACCESS)
    out = api.watched_folders()
    library, imported = out["folders"]
    assert (library["waiting"], library["unreadable"]) == (1, 1) and (imported["waiting"], imported["unreadable"]) == (0, 0)
    assert [(u["folder_id"], u["reason"]) for u in out["unreadable"]] == [
        (library["id"], "macOS doesn't let Discjockey read it")]
    assert out["unreadable"][0]["path"].startswith(str(paths.library)) and out["waiting"] == 1


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



def test_the_library_row_counts_what_all_tracks_counts_before_there_is_a_library_db(tmp_path):
    from hub_helpers import music_root
    from discjockey.library import load_state, write_json_atomic
    paths = music_root(tmp_path)
    snapshot = load_state(paths)  # an old library: state.json (version 1), not yet migrated to library.db
    paths.db_file.unlink()
    write_json_atomic(paths.state_file, {**snapshot, "version": 1}, indent=2, ensure_ascii=False, sort_keys=True)
    api, _ = make_api(paths)
    row = api.watched_folders()["folders"][0]
    assert not paths.db_file.exists() and row["kind"] == "library"
    assert row["files"] == api.sidebar()["all_tracks"] and row["files"] > 0


# --- the sound picture and the player of an own file in an import folder ---

def own_track(api):
    """(track id, entry) of the first own song whose file sits in an import folder."""
    return next((k, e) for k, e in api._state()["tracks"].items() if e.get("path") and e["path"].startswith("/"))


def tiny_aiff(path):
    """A valid silent AIFF (1 s, 44.1 kHz, 16 bit, stereo) written by hand, so no ffmpeg is needed."""
    import struct
    frames = 44100
    comm = b"COMM" + struct.pack(">IhIh", 18, 2, frames, 16) + b"\x40\x0e\xac\x44\x00\x00\x00\x00\x00\x00"
    data = bytes(frames * 4)
    ssnd = b"SSND" + struct.pack(">III", 8 + len(data), 0, 0) + data
    body = b"AIFF" + comm + ssnd
    path.write_bytes(b"FORM" + struct.pack(">I", len(body)) + body)


def test_a_file_of_an_import_folder_gives_its_embedded_artwork_as_the_cover(tmp_path, monkeypatch):
    # the plan's cover link (what the Sync page's live card shows for a track whose service has no picture) comes from
    # the file's own cover, also when the file sits in an import folder outside the music folder
    from discjockey import audio
    from discjockey.hub.media import MediaServer
    paths, folder, api, rec = watched(tmp_path, monkeypatch, n=2)
    api._media = MediaServer(paths)
    api._media.bind(paths, api._file_path)
    jpeg = b"\xff\xd8\xff\xe0" + b"jpeg data" * 10
    tiny_aiff(folder / "Example Artist - Song 1.aiff")
    audio.write_tags(folder / "Example Artist - Song 1.aiff", title="Song 1", artists=("Example Artist",), album="",
                     isrc=None, label=None, cover=jpeg, comment="x")
    tiny_aiff(folder / "Example Artist - Song 2.aiff")  # a file without artwork
    tracks = api._state()["tracks"]
    by_name = {k: v for k, v in tracks.items() if (v.get("path") or "").startswith("/")}
    with_art = next(k for k, v in by_name.items() if v["path"].endswith("Song 1.aiff"))
    without = next(k for k, v in by_name.items() if v["path"].endswith("Song 2.aiff"))
    cover = api._cover({})
    url = cover(with_art, by_name[with_art])
    assert url.startswith(f"http://127.0.0.1:{api._media.port}/{api._media.token}/cache/covers/") and ".jpg" in url
    assert (paths.cache / "covers").iterdir() and next((paths.cache / "covers").glob("*.jpg")).read_bytes() == jpeg
    assert cover(without, by_name[without]) is None  # neither a service picture nor artwork: the placeholder
    assert api._cover({without: "https://example.com/c.jpg"})(without, by_name[without]) == "https://example.com/c.jpg"


def test_the_sound_picture_and_the_player_open_a_file_of_an_import_folder(tmp_path, monkeypatch):
    import numpy as np
    from discjockey.hub.media import MediaServer
    from hub_helpers import fake_import, fake_spotify, import_folder, music_root
    fake_spotify(monkeypatch)
    fake_import(monkeypatch)
    paths = music_root(tmp_path)
    folder = import_folder(tmp_path, 2)
    api, rec = make_api(paths, decode=lambda p: (np.zeros(44100, dtype=np.float32), 44100))
    api._media = MediaServer(paths)
    api._media.bind(paths, api._file_path)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    track_id, e = own_track(api)
    pic = api.spectrum(track_id)
    assert pic["ok"] and pic["spectrum"]["cols"] == 400 and pic["spectrum"]["which"] == "current"
    url = api.media_url(track_id)["url"]
    assert url.startswith(f"http://127.0.0.1:{api._media.port}/{api._media.token}/file/{e['file_id']}?v=")
    other = next(k for k, v in api._state()["tracks"].items() if (v.get("path") or "").startswith("/") and k != track_id)
    assert len(list((paths.cache / "spectrum").iterdir())) == 1  # one picture so far
    api.spectrum(other)
    assert len(list((paths.cache / "spectrum").iterdir())) == 2  # a cache entry per file


def test_an_import_file_that_is_offline_is_refused_though_its_path_still_exists(tmp_path, monkeypatch):
    import numpy as np
    from discjockey.hub.media import MediaServer
    paths, folder, api, rec = watched(tmp_path, monkeypatch, n=1)
    api._svc.decode = lambda p: (np.zeros(44100, dtype=np.float32), 44100)
    api._media = MediaServer(paths)
    api._media.bind(paths, api._file_path)
    track_id, e = own_track(api)
    from discjockey import db
    with db.connect(paths.db_file) as conn:  # its drive is marked offline, the file is still on disk
        conn.execute("UPDATE files SET online = 0 WHERE id = ?", (e["file_id"],))
    assert open(e["path"], "rb").read()
    for call in (api.spectrum, api.media_url):
        r = call(track_id)
        assert (r["ok"], r["kind"]) == (False, "refused")
