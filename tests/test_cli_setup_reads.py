"""The plain reads of V3.1b (issue 39 phase 3): `limits show`, `playlist list`, `login list`, `login find`, `tools status`
and `setup status`. Their pages, their `--json` parity and `--verbose` completeness are the golden harness's
(tests/test_cli_golden.py); this file pins what is particular to them: the service word, the refusals, and that the
setup reads need no music folder."""
import json

import pytest
from hub_helpers import choose_music, make_root, stub_headless

import discjockey.cli as cli
from discjockey import library


@pytest.fixture
def lib(tmp_path, monkeypatch):
    stub_headless(monkeypatch, "1.0.0")
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


def run_json(argv, capsys):
    code = cli.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_limits_show_without_a_service_is_qobuz_and_a_service_that_does_not_exist_is_refused(lib, capsys):
    _, plain = run_json(["limits", "show"], capsys)
    _, qobuz = run_json(["limits", "show", "qobuz"], capsys)
    assert plain["outcome"] == "ok" and plain["data"] == qobuz["data"] and qobuz["data"]["usage"]["service"] == "qobuz"
    code, env = run_json(["limits", "show", "tidal"], capsys)
    assert code != 0 and env["outcome"] != "ok" and "service must be one of" in env["message"]


def test_the_limits_and_playlist_reads_need_a_music_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    for argv in (["limits", "show"], ["playlist", "list"], ["limits", "set", "qobuz", "40", "--dry-run"],
                 ["tidy", "run", "--dry-run"]):
        code, env = run_json(argv, capsys)
        assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library"), argv


def test_the_setup_reads_answer_with_no_music_folder_and_never_write(tmp_path, monkeypatch, capsys):
    support = tmp_path / "support"
    monkeypatch.setenv(library.SUPPORT_ENV, str(support))
    stub_headless(monkeypatch, "1.0.0")
    for argv in (["setup", "status"], ["tools", "status"], ["login", "list"], ["login", "find", "soundcloud"],
                 ["setup", "music", str(tmp_path / "Music"), "--dry-run"]):
        code, env = run_json(argv, capsys)
        assert code == 0 and env["outcome"] == "ok", argv
    _, status = run_json(["setup", "status"], capsys)
    assert status["data"]["music"]["state"] == "not_chosen" and status["data"]["complete"] is False
    assert not (support / "config.json").exists()  # a read chooses nothing


def test_setup_status_says_where_the_music_folder_is_and_how_it_stands(lib, capsys):
    """`retry_music_folder` is the window's Try again: a command resolves the folder fresh on every call, so this read is its answer."""
    _, env = run_json(["setup", "status"], capsys)
    assert env["data"]["music"]["state"] == "ok" and env["data"]["music"]["path"] == str(lib.root)


def test_a_music_folder_check_says_whether_a_folder_would_do(lib, tmp_path, capsys):
    good = tmp_path / "Elsewhere"
    code, env = run_json(["setup", "music", str(good), "--dry-run"], capsys)
    assert code == 0 and env["data"]["usable"] is True and env["data"]["path"] == str(good)
    code, env = run_json(["setup", "music", "--dry-run"], capsys)
    assert code == 2 and "path" in env["message"].lower()
