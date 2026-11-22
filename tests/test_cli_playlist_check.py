"""`playlist check <url>` (issue 39 phase 3, V3.1b): `add_playlist` as a read job (RJ, design §5.2): the link is read from
its service (a network read that can take minutes), the found card answers, no library lock is held. The service is the
stub of the hub's playlist tests."""
import json

import pytest
from hub_helpers import choose_music, make_root
from test_cli_golden import dropped
from test_cli_upgrade import inline_workers  # noqa: F401 - the fixture: every job runs in this process
from test_hub_api_playlists import SC_SET, fake_soundcloud

import discjockey.cli as cli
from discjockey import library
from discjockey.cli import bind
from discjockey.sources.base import SourceError


@pytest.fixture
def lib(tmp_path, monkeypatch, inline_workers):  # noqa: F811
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(paths.support))
    return paths


def run_json(argv, capsys):
    code = cli.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def test_playlist_check_answers_the_found_card_as_a_read_job_that_holds_no_lock(lib, monkeypatch, capsys):
    fake_soundcloud(monkeypatch)
    code, env = run_json(["playlist", "check", SC_SET], capsys)
    card = {k: v for k, v in bind.default().add_playlist(SC_SET).items() if k != "ok"}
    assert code == 0 and env["outcome"] == "ok" and env["job"]
    assert env["data"] == card and card["readable"] is True and card["suggested_folder"] == "Example_Set"
    assert env["data"]["service"] == "soundcloud" and env["data"]["tracks"] == 1
    state = json.loads(next(lib.support.glob("jobs/*/state.json")).read_text())
    assert state["method"] == "add_playlist" and state["library_lock"] is False and state["status"] == "done"


def test_playlist_check_keeps_the_link_out_of_playlists_txt(lib, monkeypatch, capsys):
    """Checking is not adding: the playlist file is as it was (the read it stores is the engine's, every read stores itself)."""
    fake_soundcloud(monkeypatch)
    before = lib.playlists_file.read_text()
    code, _ = run_json(["playlist", "check", SC_SET], capsys)
    assert code == 0 and lib.playlists_file.read_text() == before


def test_a_link_no_service_reads_is_its_refusal(lib, capsys):
    code, env = run_json(["playlist", "check", "https://example.com/not-a-playlist"], capsys)
    assert code != 0 and env["outcome"] != "ok" and env["data"] is None
    assert "playlist link" in env["message"].lower()


def test_a_playlist_the_service_will_not_show_is_the_services_words(lib, monkeypatch, capsys):
    fake_soundcloud(monkeypatch, expand_error=SourceError("Use your profile's likes link.", "playlist_unreadable", "soundcloud"))
    code, env = run_json(["playlist", "check", "https://soundcloud.com/you/likes"], capsys)
    assert code != 0 and env["outcome"] != "ok" and env["message"] == "Use your profile's likes link."


def test_playlist_check_needs_a_music_folder_and_a_link(tmp_path, monkeypatch, inline_workers, capsys):  # noqa: F811
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    code, env = run_json(["playlist", "check", SC_SET], capsys)
    assert code == 7 and (env["outcome"], env["reason"]) == ("refused", "no_library")
    code, env = run_json(["playlist", "check"], capsys)
    assert code == 2 and "link" in env["message"].lower() or "url" in env["message"].lower()


def test_the_page_of_a_check_prints_every_leaf_of_the_card(lib, monkeypatch, capsys):
    """T7' for the one read the golden harness does not run (it starts a job): the verbose text drops nothing of `data`."""
    fake_soundcloud(monkeypatch)
    _, env = run_json(["playlist", "check", SC_SET], capsys)
    assert cli.main(["playlist", "check", SC_SET, "--verbose"]) == 0
    text = capsys.readouterr().out
    assert not dropped(env["data"], text), dropped(env["data"], text)
    assert "Example_Set" in text


def test_the_detach_flag_and_the_wait_flag_are_the_ones_of_a_job(lib, monkeypatch, capsys):
    fake_soundcloud(monkeypatch)
    code, env = run_json(["playlist", "check", SC_SET, "--detach"], capsys)  # the worker (here in-process) has ended: its answer
    assert code == 0 and env["job"]
    code, env = run_json(["playlist", "check", SC_SET, "--dry-run"], capsys)
    assert code == 2 and "--dry-run" in env["message"]
