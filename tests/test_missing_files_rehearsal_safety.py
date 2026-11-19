"""The missing-files rehearsal's guards (scripts/missing_files_rehearsal.py; issue 43, plan §10.2): it refuses a work
folder inside the repo or one that holds something, and runs every child process with both overrides inside the work
folder. Nothing here starts a command or touches a library."""
from __future__ import annotations

import importlib.util

import pytest

from discjockey import REPO


@pytest.fixture(scope="module")
def script():
    spec = importlib.util.spec_from_file_location("missing_files_rehearsal", REPO / "scripts" / "missing_files_rehearsal.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_a_work_folder_in_or_around_the_repo_or_with_content_is_refused_with_exit_2(script, tmp_path, capsys):
    full = tmp_path / "full"
    full.mkdir()
    (full / "precious.txt").write_text("not a rehearsal's", encoding="utf-8")
    for work in (REPO / "work", REPO, REPO.parent, full):
        with pytest.raises(script.Refused):
            script.check_work(work)
        assert script.main(["--work", str(work)]) == 2
    assert (full / "precious.txt").exists() and not (REPO / "work").exists()
    assert script.check_work(tmp_path / "new") == (tmp_path / "new").resolve()
    (tmp_path / "empty").mkdir()
    assert script.check_work(tmp_path / "empty") == (tmp_path / "empty").resolve()


def test_every_child_process_gets_both_overrides_inside_the_work_folder_and_dead_proxies(script, tmp_path, monkeypatch):
    work = tmp_path.resolve()
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", "/somewhere/real")  # an inherited value is replaced, never kept
    env = script.env_for(work)
    assert env["DISCJOCKEY_SUPPORT"] == str(work / "support") and env["DISCJOCKEY_REKORDBOX"] == str(work / "rb")
    assert all(env[name] == script.DEAD_PROXY for name in script.PROXY_VARS)
