"""Group V3.1c (issue 39): the six `open ...` commands. Every line here either says `--print` or runs on services whose
openers only record (`hub_helpers.services()`): nothing opens a real app, a folder or a page (conftest guards it)."""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from hub_helpers import LOSSLESS, LOSSY, choose_music, make_root, services

import discjockey.cli as cli
from discjockey import library, tools, words
from discjockey.cli import bind
from discjockey.hub import api as api_module
from discjockey.hub.api import CliApi


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """The hub fixtures (two songs and a playlists.txt of Hard_Bounce and Powertrance), run on services whose openers
    record: `lib.svc.calls` says what was opened."""
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    svc = services()

    def default():
        resolved = library.resolve_paths()
        api = CliApi(resolved.support, None, svc)
        api._attach(resolved.paths)
        return api
    monkeypatch.setattr(bind, "default", default)
    return SimpleNamespace(root=paths.root, reports=paths.reports, not_lossless_md=paths.not_lossless_md, svc=svc)


def run(argv, capsys):
    code = cli.main(argv)
    out = capsys.readouterr().out
    return code, json.loads(out) if "--json" in argv else out


def opened_nothing(lib) -> bool:
    return not any(lib.svc.calls.values())


def buy_list(lib):
    lib.not_lossless_md.write_text("# Songs to buy\n")
    return lib.not_lossless_md


def report(lib, stamp="2026-11-10_110000"):
    lib.reports.mkdir(parents=True, exist_ok=True)
    (lib.reports / f"{stamp}.json").write_text(json.dumps({"started": "2026-11-10T11:00:00", "results": []}))
    (lib.reports / f"{stamp}.md").write_text("# Run\n")
    return lib.reports / f"{stamp}.md"


# --- every opener: what it opened, and --print opens nothing ---

OPENERS = {  # the line, the opener it calls, the target
    "file": (lambda lib: ["open", "file", LOSSY], "reveal", lambda lib: str(lib.root / LOSSY)),
    "folder": (lambda lib: ["open", "folder", "all"], "reveal", lambda lib: str(lib.root / "Library")),
    "url": (lambda lib: ["open", "url", "https://example.com/a?b=1"], "open_url", lambda lib: "https://example.com/a?b=1"),
    "report": (lambda lib: ["open", "report", "last"], "open_path", lambda lib: str(report(lib))),
    "licences": (lambda lib: ["open", "licences"], "open_path", lambda lib: str(tools.licenses_dir())),
    "privacy-settings": (lambda lib: ["open", "privacy-settings"], "open_url", lambda lib: api_module._PRIVACY_SETTINGS),
}


@pytest.mark.parametrize("which", OPENERS)
def test_print_says_what_would_open_and_opens_nothing(which, lib, capsys):
    line, _, target = OPENERS[which]
    want = target(lib)  # (a report is written first)
    code, env = run([*line(lib), "--print", "--json"], capsys)
    assert code == 0 and env["outcome"] == "ok"
    assert env["data"] == {"target": want, "opened": False}
    assert opened_nothing(lib)


@pytest.mark.parametrize("which", OPENERS)
def test_without_print_the_opener_is_called_once_with_the_target(which, lib, capsys):
    line, opener, target = OPENERS[which]
    want = target(lib)
    code, env = run([*line(lib), "--json"], capsys)
    assert code == 0 and env["data"] == {"target": want, "opened": True}
    got = Path(want) if opener != "open_url" else want  # a place goes to the opener as a path, a web address as text
    assert {k: v for k, v in lib.svc.calls.items() if v} == {opener: [got]}


def test_the_text_page_names_the_target(lib, capsys):
    code, text = run(["open", "folder", "all", "--print"], capsys)
    assert code == 0 and str(lib.root / "Library") in text and "no" in text.split("Opened")[1]
    assert opened_nothing(lib)


# --- open folder: a place, never a playlist by a bare word ---

def test_open_folder_takes_all_a_playlist_a_folder_and_a_path(lib, capsys):
    (lib.root / "Superseded").mkdir()
    for place, target in (("all", "Library"), ("playlist:Hard_Bounce", "Library/Hard_Bounce"),
                          ("playlist:hard_bounce", "Library/Hard_Bounce"),  # any case, as `--in` takes it
                          ("folder:Library/Hard_Bounce", "Library/Hard_Bounce"),
                          ("Superseded", "Superseded"), ("Library/Hard_Bounce", "Library/Hard_Bounce"),
                          (str(lib.root / "Library" / "Hard_Bounce"), "Library/Hard_Bounce"), (str(lib.root), "")):
        code, env = run(["open", "folder", place, "--print", "--json"], capsys)
        want = str(lib.root / target) if target else str(lib.root)
        assert code == 0 and env["data"] == {"target": want, "opened": False}, place


def test_a_bare_word_is_a_path_not_a_playlist(lib, capsys):
    """`Powertrance` is a playlist of the fixture; `open folder Powertrance` means the folder of that name in the music
    folder, which is not there: refused, and never the playlist's folder."""
    code, env = run(["open", "folder", "Powertrance", "--print", "--json"], capsys)
    assert code == 7 and env["outcome"] == "refused" and "not there" in env["message"]
    (lib.root / "Library" / "Powertrance").mkdir()
    code, env = run(["open", "folder", "Powertrance", "--print", "--json"], capsys)
    assert code == 7  # still: the path Powertrance, not Library/Powertrance
    code, env = run(["open", "folder", "playlist:Powertrance", "--print", "--json"], capsys)
    assert code == 0 and env["data"]["target"] == str(lib.root / "Library" / "Powertrance")
    assert opened_nothing(lib)


def test_a_playlist_nothing_is_called_is_unknown_and_unlisted_is_no_folder(lib, capsys):
    code, env = run(["open", "folder", "playlist:Nobody", "--print", "--json"], capsys)
    assert code == 2 and env["outcome"] == "bad_args" and "Nobody" in env["message"]
    code, env = run(["open", "folder", "unlisted", "--print", "--json"], capsys)
    assert code == 2 and env["outcome"] == "bad_args" and env["message"] == words.NO_PLACE
    assert opened_nothing(lib)


def test_a_place_outside_the_music_folder_is_refused_even_with_print(lib, capsys):
    for place in ("../outside", "/etc"):
        code, env = run(["open", "folder", place, "--print", "--json"], capsys)
        assert code != 0 and env["outcome"] != "ok", place
    assert opened_nothing(lib)


# --- open report ---

def test_open_report_names_a_stamp_last_or_the_buy_list(lib, capsys):
    path = report(lib, "2026-11-09_090000")
    newest = report(lib)
    for word, want in (("report:2026-11-09_090000", path), ("2026-11-09_090000", path), ("last", newest)):
        code, env = run(["open", "report", word, "--print", "--json"], capsys)
        assert code == 0 and env["data"]["target"] == str(want), word
    code, env = run(["open", "report", "report:2000-01-01_000000", "--print", "--json"], capsys)
    assert code == 2 and env["outcome"] == "bad_args"
    assert opened_nothing(lib)


def test_the_buy_list_opens_when_it_is_there_and_is_refused_when_it_is_not(lib, capsys):
    code, env = run(["open", "report", "not-lossless", "--print", "--json"], capsys)
    assert code == 7 and env["outcome"] == "refused" and env["message"] == words.NO_BUY_LIST
    want = buy_list(lib)
    code, env = run(["open", "report", "not-lossless", "--json"], capsys)
    assert code == 0 and env["data"] == {"target": str(want), "opened": True}
    assert lib.svc.calls["open_path"] == [want]


# --- open file / url ---

def test_open_file_names_the_current_file_or_the_parked_one(lib, capsys):
    code, env = run(["open", "file", LOSSLESS, "--which", "current", "--print", "--json"], capsys)
    assert code == 0 and env["data"]["target"] == str(lib.root / LOSSLESS)
    code, env = run(["open", "file", LOSSY, "--which", "upgrade", "--print", "--json"], capsys)  # no better version parked
    assert code == 7 and env["outcome"] == "refused"
    assert opened_nothing(lib)


def test_the_old_upgrade_switch_is_gone_one_word_for_one_idea(lib, capsys):
    code, _ = run(["open", "file", LOSSY, "--upgrade", "--print", "--json"], capsys)
    assert code == 2


def test_open_url_opens_web_links_only(lib, capsys):
    code, env = run(["open", "url", "file:///etc/passwd", "--print", "--json"], capsys)
    assert code != 0 and env["outcome"] != "ok"
    assert opened_nothing(lib)


# --- no music folder: the three that need none ---

def test_url_licences_and_privacy_settings_answer_with_no_music_folder(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    for line in (["open", "url", "https://example.com"], ["open", "licences"], ["open", "privacy-settings"]):
        code, env = run([*line, "--print", "--json"], capsys)
        assert code == 0 and env["data"]["opened"] is False, line
    for line in (["open", "folder", "all"], ["open", "report", "last"], ["open", "file", "t1"]):
        code, env = run([*line, "--print", "--json"], capsys)
        assert (code, env["outcome"], env["reason"]) == (7, "refused", "no_library"), line
