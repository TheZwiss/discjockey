"""The command line's own words (issue 39 group 1.3): `help` and `help --json`, `where`, `app open`, and the envelope's
`as_of` from `HubApi.freshness()`."""
import json
import shlex
from datetime import datetime
from pathlib import Path

import pytest
from hub_helpers import choose_music, make_root
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import __version__, db, library
from discjockey.cli import bind, housekeeping, parser
from discjockey.hub import catalog


def run_json(argv, capsys):
    code = cli.main([*argv, "--json"])
    out = capsys.readouterr().out
    assert len(out.splitlines()) == 1, out
    return code, json.loads(out)


# --- help ---

def test_help_json_lists_every_built_entry_with_what_an_agent_needs(capsys):
    code, env = run_json(["help"], capsys)
    assert code == 0 and env["command"] == "help" and env["outcome"] == "ok"
    data = env["data"]
    assert data["command"] == housekeeping.command_path() and data["version"] == __version__
    listed = {c["command"]: c for c in data["commands"]}
    assert set(listed) == {" ".join(c) for c in parser.commands()} | {" ".join(c) for c in parser.HOUSEKEEPING}
    built = {" ".join(c) for c in parser.commands()}
    planned = {" ".join(e.command) for e in catalog.ENTRIES if e.planned and e.command} - built  # `batch undo` is built for AIFF batches
    assert not planned & set(listed)  # nothing that is not built
    for command, found in listed.items():
        assert set(found) >= {"command", "kind", "writes", "job", "args", "flags", "needs_yes", "dry_run", "locks",
                              "reasons", "example", "usage"}, command
        assert found["example"] and found["usage"].startswith(command)
        assert "usage" in found["reasons"] and set(found["reasons"]) <= set(housekeeping.REASONS)
        assert "schema" not in found  # plan v2 D11: no data schema in phase 1
    status = listed["rekordbox status"]
    assert (status["kind"], status["writes"], status["job"], status["flags"]) == ("R", False, False,
                                                                                  ["--limit", "--offset"])
    assert [f["flag"] for f in data["global_flags"]][:2] == ["--json", "--jsonl"]


def test_every_example_of_the_index_parses(capsys):
    _, env = run_json(["help"], capsys)
    for found in env["data"]["commands"]:
        assert parser.parse(shlex.split(found["example"])).command == tuple(found["command"].split())


def test_the_index_describes_a_write_by_its_catalogue_entry():
    entries = [catalog.Entry("save_playlists", ("playlist", "add"), "J", needs_yes=True, dry_run="preview_playlist_change",
                             locks=frozenset({"library"}), params={"lines": catalog.Arg(type="list", resolve="x")})]
    found = housekeeping.index_entry(("playlist", "add"), entries)
    assert (found["kind"], found["writes"], found["job"], found["needs_yes"], found["dry_run"]) == ("J", True, True, True,
                                                                                                   True)
    assert found["locks"] == ["library"] and found["flags"] == ["--dry-run", "--yes"]
    assert {"unknown_id", "needs_yes", "library_lock", "no_library"} <= set(found["reasons"])


def test_the_short_help_starts_with_the_agents_line_and_lists_the_words(capsys):
    code = cli.main(["help"])
    out, err = capsys.readouterr()
    path = housekeeping.command_path()
    assert code == 0 and out.splitlines()[0] == f"AI agents: run `{path} help --json` first."
    for word in ("rekordbox", "help", "where", "app open", "call"):
        assert any(line.startswith(word + " ") for line in out.splitlines()), word
    assert "help <word>" in err  # what to run next


def test_help_of_one_noun_or_command(capsys):
    code, env = run_json(["help", "rekordbox"], capsys)
    assert code == 0 and [c["command"] for c in env["data"]["commands"]] == [
        "rekordbox backups", "rekordbox preview", "rekordbox restore", "rekordbox status"]
    code, env = run_json(["help", "rekordbox", "status"], capsys)
    assert code == 0 and env["data"]["commands"][0]["example"] == "rekordbox status"
    code, env = run_json(["help", "app", "open"], capsys)
    assert code == 0 and env["data"]["commands"][0]["usage"] == "app open"
    code = cli.main(["help", "rekordbox", "status"])
    assert code == 0 and "rekordbox status [--limit N] [--offset N]" in capsys.readouterr().out


def test_help_of_a_word_that_is_not_there_is_bad_args(capsys):
    code, env = run_json(["help", "nonsense"], capsys)
    assert (code, env["outcome"], env["reason"]) == (2, "bad_args", "usage") and "nonsense" in env["message"]


def test_a_command_not_built_is_in_no_help(capsys):
    code, env = run_json(["help", "playlist"], capsys)
    assert code == 2 and env["outcome"] == "bad_args"


@pytest.mark.parametrize("argv", [["--help"], ["-h"]])
def test_the_usual_first_probe_prints_the_short_help(argv, capsys):
    assert cli.main(argv) == 0
    assert capsys.readouterr().out.startswith("AI agents: run `")


# --- where ---

def test_where_resolves_exactly_as_the_window_does(tmp_path, monkeypatch, capsys):
    (tmp_path / "music").mkdir()
    paths = choose_music(tmp_path / "music", monkeypatch)
    box = tmp_path / "rb"
    make_master(box, [])
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(box))
    code, env = run_json(["where"], capsys)
    resolved = library.resolve_paths()
    assert code == 0 and env["command"] == "where"
    assert env["data"] == {"music": {"path": str(paths.root), "state": "ok"}, "not_lossless": None,
                           "support": str(resolved.support), "rekordbox": str(box / "master.db"),
                           "command": housekeeping.command_path(), "version": __version__, "sandbox": None,
                           "jobs_running": 0}
    assert resolved.support == paths.support  # DISCJOCKEY_SUPPORT honoured
    paths.not_lossless_md.parent.mkdir(parents=True, exist_ok=True)
    paths.not_lossless_md.write_text("buy these")
    assert run_json(["where"], capsys)[1]["data"]["not_lossless"] == str(paths.not_lossless_md)


def test_where_music_state_is_not_chosen_missing_or_ok(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    assert run_json(["where"], capsys)[1]["data"]["music"] == {"path": None, "state": "not_chosen"}
    gone = tmp_path / "gone"
    gone.mkdir()
    library.write_music_folder(tmp_path / "support", gone)
    assert run_json(["where"], capsys)[1]["data"]["music"] == {"path": str(gone), "state": "ok"}
    gone.rmdir()  # the drive went away
    data = run_json(["where"], capsys)[1]["data"]
    assert data["music"] == {"path": str(gone), "state": "missing"} and data["not_lossless"] is None
    assert data["rekordbox"] is None  # conftest: DISCJOCKEY_REKORDBOX is an empty folder


def test_where_prints_a_page_and_the_program_path(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    assert cli.main(["where"]) == 0
    out = capsys.readouterr().out
    assert housekeeping.command_path() in out and "not_chosen" in out and __version__ in out
    assert Path(housekeeping.command_path()).is_absolute()


# --- app open ---

def test_app_open_opens_the_window_without_an_answer_on_stdout(tmp_path, monkeypatch, capsys):
    paths = choose_music(tmp_path, monkeypatch)
    opened = []
    from discjockey.hub import app
    monkeypatch.setattr(app, "main", lambda resolved: opened.append(resolved.paths.root) or 0)
    assert cli.main(["app", "open"]) == 0
    assert opened == [paths.root] and capsys.readouterr().out == ""


def test_app_open_opens_without_a_music_folder_too(tmp_path, monkeypatch):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    seen = []
    from discjockey.hub import app
    monkeypatch.setattr(app, "main", lambda resolved: seen.append(resolved.problem) or 0)
    assert cli.main(["app", "open"]) == 0 and seen == ["not_chosen"]


def test_a_noun_alone_asks_for_its_verb(capsys):
    code, env = run_json(["app"], capsys)
    assert code == 2 and "open" in env["message"]


# --- as_of ---

def test_a_read_carries_as_of_from_freshness(tmp_path, monkeypatch, capsys):
    make_root(tmp_path)
    paths = choose_music(tmp_path, monkeypatch)
    library.open_records(paths)
    with db.connect(paths.db_file) as conn, db.transaction(conn):
        assert conn.execute("SELECT COUNT(*) FROM watched_folders").fetchone()[0] >= 1
        conn.execute("UPDATE watched_folders SET last_scan = ?", ("2026-11-01T10:00:00",))
        conn.execute("INSERT INTO playlist_reads (playlist, service, read_at) VALUES ('a', 'spotify', ?), "
                     "('b', 'spotify', ?)", ("2026-11-02T08:00:00", "2026-11-03T09:30:00"))
    fresh = bind.default().freshness()
    assert fresh == {"ok": True, "scanned_at": "2026-11-01T10:00:00", "read_at": "2026-11-03T09:30:00"}
    code, env = run_json(["rekordbox", "status"], capsys)
    assert code == 0 and env["as_of"] == {"scanned_at": "2026-11-01T10:00:00", "read_at": "2026-11-03T09:30:00"}
    datetime.fromisoformat(env["as_of"]["read_at"])  # ISO


def test_as_of_is_null_without_a_music_folder_or_a_database(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    assert bind.default().freshness() == {"ok": True, "scanned_at": None, "read_at": None}
    assert run_json(["rekordbox", "status"], capsys)[1]["as_of"] == {"scanned_at": None, "read_at": None}
    make_root(tmp_path / "lib")  # a library with no library.db yet
    choose_music(tmp_path / "lib", monkeypatch)
    assert bind.default().freshness() == {"ok": True, "scanned_at": None, "read_at": None}


def test_a_freshness_that_fails_leaves_as_of_null_and_the_answer_alone(tmp_path, monkeypatch, capsys):
    make_root(tmp_path)
    paths = choose_music(tmp_path, monkeypatch)
    library.open_records(paths)
    paths.db_file.write_bytes(b"this is not a database" * 100)  # damaged: freshness cannot read it
    answer = bind.default().freshness()
    assert answer["ok"] is False and answer["reason"] == "config_invalid"
    code, env = run_json(["rekordbox", "status"], capsys)
    assert code == 0 and env["outcome"] == "ok" and env["as_of"] == {"scanned_at": None, "read_at": None}
