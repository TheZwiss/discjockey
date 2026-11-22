import json
import os

from discjockey.hub import windows


def test_register_writes_the_file_and_holds_the_lock(tmp_path):
    window = windows.register(tmp_path, tmp_path / "music")
    try:
        path = tmp_path / "windows" / f"{os.getpid()}.json"
        data = json.loads(path.read_text())
        assert data["pid"] == os.getpid() and data["music"] == str(tmp_path / "music") and "pid_started" in data
        assert windows.count_open(tmp_path) == 1  # held by another open file of the same process: still counted
    finally:
        window.close()


def test_a_stale_file_is_not_counted_and_a_second_register_removes_it(tmp_path):
    stale = tmp_path / "windows" / "99999.json"
    stale.parent.mkdir()
    stale.write_text("{}")
    assert windows.count_open(tmp_path) == 0
    window = windows.register(tmp_path, None)
    try:
        assert not stale.exists() and windows.count_open(tmp_path) == 1
    finally:
        window.close()


def test_close_removes_the_file_and_the_count(tmp_path):
    window = windows.register(tmp_path, tmp_path)
    window.close()
    window.close()  # once
    assert not (tmp_path / "windows" / f"{os.getpid()}.json").exists() and windows.count_open(tmp_path) == 0


def test_count_open_never_opens_the_window_lock(tmp_path, monkeypatch):
    (tmp_path / ".window.lock").write_text("")
    window = windows.register(tmp_path, None)
    opened = []
    real = open
    monkeypatch.setattr("builtins.open", lambda path, *a, **k: opened.append(str(path)) or real(path, *a, **k))
    try:
        assert windows.count_open(tmp_path) == 1
    finally:
        monkeypatch.undo()
        window.close()
    assert opened and not [p for p in opened if p.endswith(".window.lock")]


def test_no_windows_folder_is_no_window(tmp_path):
    assert windows.count_open(tmp_path / "nowhere") == 0
