"""Group V1.9 (issue 39): `rekordbox status` and `rekordbox preview`. The parity, golden and T7' harnesses of every
built read are in tests/test_cli_golden.py; this file pins what is particular to these two: master.db's own facts, the
entry columns a live test needs (`folder_path`, `content_file`, `updated_at`), a file the library doesn't know, the
refusals, and a reader that never opens master.db while a writer holds `rekordbox.lock`."""
import json
import os
from datetime import datetime
from pathlib import Path

import pytest
from audio_helpers import needs_ffmpeg
from hub_helpers import LOSSLESS, LOSSY, choose_music, make_root
from rekordbox_helpers import make_master
from test_rekordbox_preview import LAME, rekordbox_for

import discjockey.cli as cli
from discjockey import rekordbox
from discjockey.library import run_lock
from discjockey.rekordbox import lock as rb_lock


def data_of(argv, capsys):
    code = cli.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


@pytest.fixture
def lib(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


def test_status_has_master_dbs_modified_time_and_size(lib, tmp_path, monkeypatch, capsys):
    master = make_master(tmp_path / "rekordbox", [])
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(master.parent))
    os.utime(master, (1_700_000_000, 1_700_000_000))
    code, env = data_of(["rekordbox", "status"], capsys)
    stat = master.stat()
    assert code == 0 and env["outcome"] == "ok"
    data = env["data"]
    assert (data["state"], data["running"], data["problem"], data["db_version"], data["library"]) == (
        "ready", False, None, "6000", str(master))
    assert data["size"] == stat.st_size
    assert data["modified_at"] == datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds")  # local, to the second
    assert data["state_text"] and data["problem_text"] is None
    master.write_bytes(master.read_bytes() + b"\0")                       # master.db changed meanwhile: the cache follows
    code, again = data_of(["rekordbox", "status"], capsys)
    assert again["data"]["size"] == stat.st_size + 1


def test_status_without_a_library_or_a_music_folder(tmp_path, monkeypatch, capsys):
    empty = tmp_path / "none"
    empty.mkdir()
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(empty))
    code, env = data_of(["rekordbox", "status"], capsys)                  # conftest: no music folder chosen either
    assert code == 0 and env["data"]["state"] == "none"
    assert (env["data"]["library"], env["data"]["modified_at"], env["data"]["size"]) == (None, None, None)
    assert env["data"]["state_text"] == "no rekordbox library on this Mac"


def test_status_names_what_is_wrong_with_a_library(lib, tmp_path, monkeypatch, capsys):
    folder = tmp_path / "rb"
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(folder, [], version="9999").parent))
    code, env = data_of(["rekordbox", "status"], capsys)
    assert code == 0 and (env["data"]["state"], env["data"]["problem"], env["data"]["db_version"]) == (
        "unreadable", "db_version", "9999")
    assert "version" in env["data"]["problem_text"]


def test_status_while_a_writer_holds_the_lock_never_opens_master_db(lib, tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rb", []).parent))
    code, free = data_of(["rekordbox", "status"], capsys)
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: pytest.fail("master.db was opened"))
    with rb_lock.writer_lock(lib.support):
        # a new process has nothing cached: it answers `ready`, writing, nothing known of the file
        code, env = data_of(["rekordbox", "status"], capsys)
    assert code == 0 and env["data"]["writing"] is True and env["data"]["size"] is None and free["data"]["size"]


@needs_ffmpeg
def test_preview_of_a_file_has_the_timing_and_each_entrys_columns(lib, tmp_path, monkeypatch, capsys):
    file = tmp_path / "Mine" / "old name.mp3"
    file.parent.mkdir()
    file.write_bytes(LAME.read_bytes())
    rekordbox_for(tmp_path, monkeypatch, file)
    code, env = data_of(["rekordbox", "preview", "--path", str(file)], capsys)
    assert code == 0
    data = env["data"]
    assert data["track"] is None and data["timing"]["offset_samples"] == 1105 and data["timing"]["result"] == "measured"
    assert data["timing"]["result_text"] == "measured" and data["rekordbox"]["state_text"]
    (entry,) = data["entries"]
    assert entry["offset_ms"] is not None and entry["folder_path"] == str(file) and entry["cues"] == 3
    assert isinstance(entry["updated_at"], str) and all(f["hash"] and f["size"] for f in entry["content_file"])
    assert sorted(Path(f["path"]).suffix for f in entry["content_file"]) == [".2EX", ".3EX", ".DAT", ".EXT"]
    assert all(set(f) == {"path", "hash", "size", "updated_at"} for f in entry["content_file"])
    assert data["eligible"]["same_track"] == "not_in_library" and data["eligible"]["same_track_text"]
    assert cli.main(["rekordbox", "preview", "--path", str(file)]) == 0
    assert "Folder path" in capsys.readouterr().out


@needs_ffmpeg
def test_preview_of_a_file_the_library_does_not_know_still_gets_the_rekordbox_part(tmp_path, monkeypatch, capsys):
    file = tmp_path / "Mine" / "old name.mp3"                      # conftest: no music folder is chosen
    file.parent.mkdir()
    file.write_bytes(LAME.read_bytes())
    rekordbox_for(tmp_path, monkeypatch, file)
    code, env = data_of(["rekordbox", "preview", "--path", str(file)], capsys)
    assert code == 0 and len(env["data"]["entries"]) == 1 and env["data"]["rekordbox"]["state"] == "ready"


@needs_ffmpeg
def test_preview_of_a_song_by_the_path_of_its_file(lib, tmp_path, monkeypatch, capsys):
    (lib.root / LOSSY).write_bytes(LAME.read_bytes())
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(make_master(tmp_path / "rb", []).parent))
    code, by_path = data_of(["rekordbox", "preview", LOSSY], capsys)
    assert code == 0 and by_path["data"]["track"] == "t2" and by_path["data"]["timing"]["result"] == "not_in_rekordbox"
    code, by_key = data_of(["rekordbox", "preview", "t2"], capsys)           # not a key's shape: `unknown_id`
    assert code == 2 and by_key["reason"] == "unknown_id"


def test_preview_refusals(lib, capsys):
    code, env = data_of(["rekordbox", "preview", LOSSLESS], capsys)    # the fixture's file is no audio: nothing to decode
    assert code == 1 and env["outcome"] == "failed" and "couldn't read" in env["message"]
    (lib.root / LOSSLESS).unlink()
    code, env = data_of(["rekordbox", "preview", "--path", str(lib.root / LOSSLESS)], capsys)
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "file_missing")
    code, env = data_of(["rekordbox", "preview", "local:99"], capsys)  # a key of the right shape that nothing holds
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "refused") and "local:99" in env["message"]
    code, env = data_of(["rekordbox", "preview", "--path", str(lib.root / "nope.mp3")], capsys)
    assert code == 7 and env["reason"] == "file_missing"
    code, env = data_of(["rekordbox", "preview"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "usage")
    code, env = data_of(["rekordbox", "preview", "local:1", "--path", "x"], capsys)
    assert code == 2 and env["reason"] == "conflicting_flags"


def test_preview_of_a_song_needs_a_music_folder_a_file_does_not(tmp_path, capsys):
    code, env = data_of(["rekordbox", "preview", "local:1"], capsys)   # conftest: no Setup done
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library")
    code, env = data_of(["rekordbox", "preview", "--path", str(tmp_path / "nope.mp3")], capsys)
    assert code == 7 and env["reason"] == "file_missing"


@needs_ffmpeg
def test_preview_with_a_writer_holding_the_lock_does_not_open_master_db(lib, tmp_path, monkeypatch, capsys):
    from discjockey.rekordbox import master
    file = tmp_path / "Mine" / "old name.mp3"
    file.parent.mkdir()
    file.write_bytes(LAME.read_bytes())
    rekordbox_for(tmp_path, monkeypatch, file)
    monkeypatch.setattr(master, "open_read", lambda *a, **k: pytest.fail("master.db was opened"))
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: pytest.fail("master.db was opened"))
    with rb_lock.writer_lock(lib.support):
        code, env = data_of(["rekordbox", "preview", "--path", str(file)], capsys)
    data = env["data"]
    assert code == 0 and data["rekordbox"]["writing"] is True and data["rekordbox"]["writing_text"]
    assert data["entries"] == [] and data["timing"]["result"] == "unreadable"


def own_library(root):
    """A music folder with one own MP3 (a fixture) and, for rekordbox, nothing yet; chosen as the music folder."""
    import shutil

    from rekordbox_helpers import own_entry, save_library

    from discjockey.library import Paths
    paths = Paths(root, support=root / ".support")
    file = root / "Library/Mine/old name.mp3"
    file.parent.mkdir(parents=True)
    shutil.copyfile(LAME, file)
    save_library(paths, {"local:1": own_entry()})
    return paths, "local:1", file


@needs_ffmpeg
def test_preview_of_a_song_by_its_key_answers_what_each_action_would_do(tmp_path, monkeypatch, capsys):
    paths, key, file = own_library(tmp_path)
    choose_music(tmp_path, monkeypatch)
    with run_lock(paths.lock):  # a sync is running: a read still answers
        code, env = data_of(["rekordbox", "preview", key], capsys)
        assert code == 0 and cli.main(["rekordbox", "preview", key]) == 0
    data = env["data"]
    assert data["track"] == key and data["file"] == str(file)
    assert {k: data["eligible"][k] for k in ("same_track", "convert", "rename")} == {
        "same_track": "no_upgrade", "convert": None, "rename": "needs_convert"}
    assert data["eligible"]["convert_text"] == "possible"
    assert data["eligible"]["rename_text"] == "needs Convert to AIFF first"
    assert data["new_file"] == str(tmp_path / "Library/Mine/Artist - Song.aiff")
    assert data["superseded"] == str(tmp_path / "Superseded/Mine/old name.mp3")
    assert set(data) == {"track", "file", "codec", "sample_rate", "bits", "new_file", "superseded", "rekordbox",
                         "timing", "entries", "eligible"}
    out = capsys.readouterr().out
    assert "Convert     possible" in out and "Same track  no better version is waiting" in out


@needs_ffmpeg
def test_preview_of_a_file_asks_for_no_setup(tmp_path, capsys):
    file = Path(__file__).parent / "fixtures" / "clicks-notag.mp3"
    code, env = data_of(["rekordbox", "preview", "--path", str(file)], capsys)  # conftest: no Setup done
    assert code == 0 and env["data"]["track"] is None and env["data"]["file"] == str(file)
    assert {v for k, v in env["data"]["eligible"].items() if not k.endswith("_text")} == {"not_in_library"}
    assert cli.main(["rekordbox", "preview", "--path", str(file)]) == 0
    assert "not a file of your library" in capsys.readouterr().out


def test_preview_of_an_unreadable_file_is_failed(lib, capsys):
    (lib.root / "bad.mp3").write_bytes(b"not audio")
    code, env = data_of(["rekordbox", "preview", "--path", str(lib.root / "bad.mp3")], capsys)
    assert (code, env["outcome"]) == (1, "failed") and "couldn't read bad.mp3" in env["message"]
