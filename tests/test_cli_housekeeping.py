"""The command line's own words (issue 39 group 1.3): `help` and `help --json`, `where`, `app open`, and the envelope's
`as_of` from `HubApi.freshness()`."""
import json
import shlex
from dataclasses import replace
from datetime import datetime
from pathlib import Path

import pytest
from hub_helpers import choose_music, make_root, stub_headless
from rekordbox_helpers import make_master
from test_cli_upgrade import inline_workers  # noqa: F401 - the fixture

import discjockey.cli as cli
from discjockey import __version__, db, library
from discjockey.cli import bind, housekeeping, parser
from discjockey.hub import catalog, shapes, windows


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
        assert set(found) >= {"command", "kind", "writes", "job", "pages", "args", "flags", "needs_yes", "dry_run", "locks",
                              "reasons", "example", "usage", "methods", "dry_run_method", "songs", "flag_values",
                              "required_flags"}, command
        assert all("id" in a for a in found["args"]), command
        assert found["example"] and found["usage"].startswith(command)
        assert "usage" in found["reasons"] and set(found["reasons"]) <= set(housekeeping.REASONS)
        assert found["schema"] is None or found["schema"] in {*shapes.ANSWERS.values(), *shapes.CLI_DATA.values()}  # the shape of a mapped method
    status = listed["rekordbox status"]
    assert (status["kind"], status["writes"], status["job"], status["flags"]) == ("R", False, False,
                                                                                  ["--limit", "--offset"])
    assert [f["flag"] for f in data["global_flags"]][:2] == ["--json", "--jsonl"]


def test_a_command_with_a_mapped_shape_names_it_and_help_of_it_carries_the_schema():
    built = catalog.entry_of("rekordbox_status", "rekordbox status")
    row = housekeeping.index_entry(built.command, [replace(built, schema="Freshness")])
    assert row["schema"] == "Freshness"
    [full] = housekeeping.with_schemas([row])
    assert full["data_schema"] == shapes.json_schema("Freshness") and full["dry_run_schema"] is None
    assert full["data_schema"]["$defs"]["Freshness"]["properties"]["read_at"]
    # a dry run that is answered by a mapped method brings that method's schema
    dry = housekeeping.with_schemas([{**row, "dry_run_method": "freshness"}])
    assert dry[0]["dry_run_schema"] == shapes.json_schema("Freshness")


def test_a_command_with_no_mapped_method_has_null_schemas_and_the_text_page_shows_none(capsys):
    row = run_json(["help", "rekordbox", "backups"], capsys)[1]["data"]["commands"][0]
    unmapped = {**row, "schema": None, "dry_run_method": None}  # every command is mapped now: a made-up row
    [full] = housekeeping.with_schemas([unmapped])
    assert (full["data_schema"], full["dry_run_schema"]) == (None, None)
    code = cli.main(["help", "rekordbox", "backups"])  # the text page shows no schema
    assert code == 0 and "schema" not in capsys.readouterr().out


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
    path = shlex.quote(housekeeping.command_path())  # a line a shell can take
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
    code, env = run_json(["help", "open"], capsys)
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
                           "jobs_running": 0, "windows_open": 0}
    assert resolved.support == paths.support  # DISCJOCKEY_SUPPORT honoured
    window = windows.register(resolved.support, paths.root)  # an open window is counted, and only while it is open
    try:
        assert run_json(["where"], capsys)[1]["data"]["windows_open"] == 1
    finally:
        window.close()
    assert run_json(["where"], capsys)[1]["data"]["windows_open"] == 0
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


# --- what the person types (C-2) ---

def _row(capsys, *words):
    code, env = run_json(["help", *words], capsys)
    assert code == 0, env
    return env["data"]["commands"][0]


def test_an_id_argument_is_listed_as_the_form_a_person_types(capsys):
    undo = _row(capsys, "batch", "undo")
    assert (undo["args"][0]["id"], undo["args"][0]["type"], undo["args"][0]["word"]) == ("batch", "str", "aiff:N|moves:N")  # by id kind
    show = _row(capsys, "batch", "show")
    assert (show["args"][0]["id"], show["args"][0]["word"]) == ("batch", "aiff:N|moves:N")
    assert _row(capsys, "folder", "remove")["args"][0]["word"] == "FOLDER"
    assert _row(capsys, "settings", "set", "auto-upgrade")["args"][0]["word"] == "on|off"


def test_a_songs_command_lists_the_ways_to_say_which_songs(capsys):
    done = _row(capsys, "check", "done")
    assert done["songs"] == ["TRACK...", "-", "--all", "--rows", "--batch"]
    assert done["args"][0]["name"] == "track_ids" and done["args"][0]["required"] is False
    assert done["flag_values"]["--batch"] == "aiff:N" and done["flag_values"]["--in"] == "COLLECTION"
    assert "(TRACK... | - | --all | --rows | --batch aiff:N)" in done["usage"]
    assert _row(capsys, "upgrade", "discard")["songs"] == ["TRACK...", "-", "--rows"]
    assert _row(capsys, "rekordbox", "status")["songs"] == []


def test_the_usage_of_a_flag_says_what_it_takes(capsys):
    apply = _row(capsys, "upgrade", "apply")
    assert "[--in COLLECTION]" in apply["usage"] and "[--way same-track|new-track]" in apply["usage"]
    assert "[--plan plan:ID]" in apply["usage"] and apply["flag_values"]["--way"] == "same-track|new-track"
    assert "[--limit N] [--offset N]" in _row(capsys, "todo", "list")["usage"]
    code = cli.main(["help", "upgrade", "apply"])
    assert code == 0 and "--in COLLECTION" in capsys.readouterr().out


def test_a_flag_a_command_cannot_run_without_has_no_brackets(capsys):
    phase = _row(capsys, "sync", "run")
    assert phase["required_flags"] == ["--auto-upgrade-only"]
    assert " --auto-upgrade-only" in phase["usage"] and "[--auto-upgrade-only" not in phase["usage"]


# --- the reasons of a command (C-3) ---

def test_a_command_lists_the_reasons_its_entries_and_locks_answer_with(capsys):
    restore = _row(capsys, "rekordbox", "restore")
    assert {"rekordbox_lock", "rekordbox_open", "no_library", "still_running", "conflicting_flags"} <= set(
        restore["reasons"])
    assert "no_library" in _row(capsys, "batch", "list")["reasons"]
    assert "no_library" not in _row(capsys, "rekordbox", "status")["reasons"]
    assert "no_library" not in _row(capsys, "settings", "set", "auto-upgrade")["reasons"]
    assert {"window_job", "worker_lost", "not_running", "unknown_id"} <= set(_row(capsys, "job", "stop")["reasons"])
    assert "still_running" in _row(capsys, "job", "wait")["reasons"]
    assert {"needs_yes", "refused"} <= set(_row(capsys, "call")["reasons"])


def test_a_read_answers_no_library_exactly_when_the_catalogue_says_it_needs_one(tmp_path, monkeypatch, capsys,
                                                                                 inline_workers):  # noqa: F811
    """`NEEDS_NO_LIBRARY` is the fact behind the `no_library` reason: run every built read with no music folder chosen
    (on the services of the hub fixtures: no browser or tool of this Mac is read; a read that runs as a job
    (`playlist check`) runs in this process, so no worker starts)."""
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    stub_headless(monkeypatch)
    seen = 0
    for command, entries in parser.commands().items():
        for e in entries:
            if e.kind in ("R", "RJ") and e.example and e.command == command and not e.dry_run:
                code, env = run_json(shlex.split(e.example), capsys)
                needs = e.method not in catalog.NEEDS_NO_LIBRARY
                assert (env["outcome"], env["reason"]) == (("refused", "no_library") if needs else ("ok", None)), e.example
                assert ("no_library" in housekeeping.reasons_of([e])) == needs
                seen += 1
    assert seen >= 10


# --- the methods (C-4) ---

def test_the_index_names_the_methods_a_row_runs_and_call_lists_what_it_takes(capsys):
    code, env = run_json(["help"], capsys)
    rows = {c["command"]: c for c in env["data"]["commands"]}
    assert rows["aiff convert"]["methods"] == ["convert", "make_aiff", "aiff_plan"]
    assert rows["aiff convert"]["dry_run_method"] == "aiff_plan"
    assert rows["help"]["methods"] == [] and rows["help"]["dry_run_method"] is None
    methods = env["data"]["call_methods"]
    assert "select_listing" in methods and "upgrade_preview" in methods
    assert not {"select", "quit", "stop", "pick_folder"} & set(methods)
    for name in methods:  # a catalogue assertion: calling them would start workers
        built = [e for e in catalog.by_method(name) if not e.planned]
        assert built and name not in catalog.WINDOW_ONLY and name not in catalog.DROPPED, name


# --- a noun and a command, in words (C-19) ---

def test_the_short_list_says_what_each_noun_is_for_and_a_new_noun_cannot_ship_without_words(capsys):
    from discjockey.words import NOUN_WORDS
    assert {c[0] for c in parser.commands()} <= set(NOUN_WORDS)
    assert cli.main(["help"]) == 0
    out = capsys.readouterr().out
    assert "The folders Discjockey watches for your own files. (add, check, list, remove)" in out


def test_help_of_one_word_prints_its_sentence(capsys):
    assert cli.main(["help", "where"]) == 0
    out = capsys.readouterr().out
    assert "Say where Discjockey's folders" in out
    assert cli.main(["help", "job", "stop"]) == 0 and "Ask a job to stop" in capsys.readouterr().out


# --- `--help` after a word (C-6) ---

def test_a_noun_or_a_command_with_help_shows_its_rows(capsys):
    code, out, _ = _run(["upgrade", "--help"], capsys)
    assert code == 0 and [l.split("  ")[0] for l in out.splitlines() if l.startswith("upgrade ")] == [
        "upgrade apply", "upgrade discard", "upgrade list"]
    code, env = run_json(["upgrade", "apply", "--help"], capsys)
    assert code == 0 and [c["command"] for c in env["data"]["commands"]] == ["upgrade apply"]
    code, env = run_json(["upgrade", "apply", "local:1", "-h"], capsys)
    assert code == 0 and [c["command"] for c in env["data"]["commands"]] == ["upgrade apply"]


def test_help_of_a_word_that_does_not_exist_is_still_bad_args(capsys):
    code, env = run_json(["nonsense", "--help"], capsys)
    assert code == 2 and env["outcome"] == "bad_args"
    code, env = run_json(["help", "upgrade", "nonsense"], capsys)  # the last words drop off until a command matches
    assert code == 0 and {c["command"] for c in env["data"]["commands"]} == {"upgrade apply", "upgrade discard",
                                                                           "upgrade list"}


def _run(argv, capsys):
    code = cli.main(argv)
    out, err = capsys.readouterr()
    return code, out, err
