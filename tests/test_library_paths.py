"""Where Discjockey keeps things (spec public-release §4): the music folder, its .discjockey/, the support folder."""
import json
import os

import pytest

from discjockey import library
from discjockey.library import (
    FOLDER_PROBLEMS, NoLibrary, Paths, Resolved, SupportPaths, check_music_folder, read_music_folder, resolve_in,
    resolve_paths, run_lock, support_dir, write_music_folder,
)


def test_every_path_under_its_root(tmp_path):
    music, support = tmp_path / "Music", tmp_path / "Support"
    p = Paths(music, support=support)
    assert (p.library, p.superseded, p.upgrades_ready, p.playlists_file) == (
        music / "Library", music / "Superseded", music / "Upgrades ready", music / "playlists.txt")
    data = music / ".discjockey"
    assert p.data == data
    assert (p.state_file, p.tmp, p.reports, p.not_lossless_md, p.lock, p.operations_log) == (
        data / "state.json", data / ".tmp", data / "reports", data / "not_lossless.md", data / ".lock",
        data / "reports" / "operations.jsonl")
    assert (p.config_file, p.settings_file, p.spotify_app, p.spotify_token, p.streamrip_dir, p.cache) == (
        support / "config.json", support / "settings.json", support / ".spotify_app.json",
        support / ".spotify_token.json", support / "streamrip", support / "cache")
    assert (p.window_file, p.window_lock) == (support / "window.json", support / ".window.lock")
    assert isinstance(p, SupportPaths) and not hasattr(p, "pipeline")


def test_tmp_stays_on_the_music_drive(tmp_path):
    # run_op renames from .tmp/ into Library/: both must be under root, so the rename is atomic
    p = Paths(tmp_path / "Music", support=tmp_path / "Support")
    assert p.tmp.is_relative_to(p.root)


def test_support_is_keyword_only(tmp_path):
    with pytest.raises(TypeError):
        Paths(tmp_path, tmp_path / "s")  # noqa


def test_support_dir_default_and_override(tmp_path):
    assert support_dir({}, tmp_path) == tmp_path / "Library" / "Application Support" / "Discjockey"
    assert support_dir({"DISCJOCKEY_SUPPORT": str(tmp_path / "x")}, tmp_path) == tmp_path / "x"


def test_no_config_is_not_chosen(tmp_path):
    r = resolve_in(tmp_path / "support")
    assert r == Resolved(tmp_path / "support", None, "not_chosen", None)


@pytest.mark.parametrize("text", ["{", "[]", '{"music_folder": 3}', '{"music_folder": "relative/x"}', "{}"])
def test_a_config_without_a_usable_folder_is_not_chosen(tmp_path, text):
    (tmp_path / "config.json").write_text(text)
    assert read_music_folder(tmp_path) is None and resolve_in(tmp_path).problem == "not_chosen"


def test_a_chosen_folder_resolves(tmp_path):
    music, support = tmp_path / "Music", tmp_path / "support"
    music.mkdir()
    write_music_folder(support, music)
    assert json.loads((support / "config.json").read_text()) == {"music_folder": str(music)}
    r = resolve_paths({"DISCJOCKEY_SUPPORT": str(support)})
    assert r.problem is None and r.paths == Paths(music, support=support) and r.music_folder == music


def test_a_missing_folder_is_never_made(tmp_path):
    support, gone = tmp_path / "support", tmp_path / "Volumes" / "DJ" / "Music"
    write_music_folder(support, gone)
    r = resolve_in(support)
    assert (r.paths, r.problem, r.music_folder) == (None, "missing", gone)
    assert not gone.exists() and not gone.parent.exists()


def test_write_music_folder_leaves_no_temp_file(tmp_path):
    write_music_folder(tmp_path, tmp_path / "a")
    write_music_folder(tmp_path, tmp_path / "b")
    assert sorted(os.listdir(tmp_path)) == ["config.json"]
    assert read_music_folder(tmp_path) == tmp_path / "b"


def test_run_lock_never_makes_the_music_folder(tmp_path):
    p = Paths(tmp_path / "gone", support=tmp_path / "support")
    with pytest.raises(NoLibrary) as e:
        with run_lock(p.lock):
            pass
    assert str(e.value) == library.MUSIC_GONE and not (tmp_path / "gone").exists()


def test_run_lock_makes_dot_discjockey_in_an_existing_folder(tmp_path):
    p = Paths(tmp_path, support=tmp_path / "support")
    with run_lock(p.lock):
        assert p.data.is_dir()


# --- choosing a folder ---

def check(folder, tmp_path, **kw):
    args = {"support": tmp_path / "support", "program": tmp_path / "App", "home": tmp_path / "home"}
    args.update(kw)
    return check_music_folder(folder, **args)


def test_check_kinds(tmp_path):
    new = check(tmp_path / "home" / "Music" / "Discjockey", tmp_path)
    assert (new.usable, new.exists, new.kind, new.problem) == (True, False, "new", None)
    empty = tmp_path / "empty"
    empty.mkdir()
    (empty / ".DS_Store").write_bytes(b"")
    assert check(empty, tmp_path).kind == "empty"
    for marker in (".discjockey", "Library"):
        lib = tmp_path / f"lib{marker}"
        (lib / marker).mkdir(parents=True)
        assert check(lib, tmp_path).kind == "discjockey_library"
    txt = tmp_path / "txt"
    txt.mkdir()
    (txt / "playlists.txt").write_text("")
    assert check(txt, tmp_path).kind == "discjockey_library"
    other = tmp_path / "other"
    other.mkdir()
    (other / "song.mp3").write_bytes(b"x")
    c = check(other, tmp_path)
    assert (c.usable, c.kind) == (True, "other_files")


def test_check_expands_and_resolves(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    c = check("~/Music/Discjockey", tmp_path)
    assert c.path == (tmp_path / "home" / "Music" / "Discjockey").resolve() and c.usable


@pytest.mark.parametrize("where,problem", [
    ("relative/folder", "not_absolute"),
    ("/", "system_folder"),
    ("/Users", "system_folder"),
    ("/Volumes", "system_folder"),
    ("/System/Library", "system_folder"),
    ("/Applications/Something", "system_folder"),
    ("HOME", "system_folder"),
    ("HOME/Library/Music", "system_folder"),
    ("APP/Contents/Resources", "inside_app"),
    ("SUPPORT", "is_support_dir"),
    ("SUPPORT/cache", "is_support_dir"),
])
def test_check_refuses(tmp_path, where, problem):
    for d in ("home", "App", "support"):
        (tmp_path / d).mkdir()
    folder = (where.replace("HOME", str(tmp_path / "home")).replace("APP", str(tmp_path / "App"))
              .replace("SUPPORT", str(tmp_path / "support")))
    c = check(folder, tmp_path)
    assert (c.usable, c.problem, c.kind) == (False, problem, None)
    assert FOLDER_PROBLEMS[problem]


def test_check_refuses_a_file(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("x")
    assert check(f, tmp_path).problem == "not_a_folder"


@pytest.mark.skipif(os.geteuid() == 0, reason="root can write anywhere")
def test_check_refuses_a_folder_it_cant_write(tmp_path):
    locked = tmp_path / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    try:
        assert check(locked, tmp_path).problem == "not_writable"
        assert check(locked / "new", tmp_path).problem == "not_writable"
    finally:
        locked.chmod(0o700)


def test_saving_state_never_recreates_a_vanished_music_folder(tmp_path):
    root = tmp_path / "Unplugged"
    root.mkdir()
    paths = Paths(root, support=tmp_path / "support")
    root.rmdir()
    with pytest.raises(NoLibrary):
        library.save_state(paths, library.empty_state())
    assert not root.exists()
