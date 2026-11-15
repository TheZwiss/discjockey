"""The command line's frame (issue 39 group 1.2): the parser generated from the catalogue (T2), what a `cli/` module
may call (T3), global flags anywhere, the envelope and exit codes, the first read (`rekordbox status`), `call <method>`
and the routes to the old commands."""
import ast
import json
import shlex
from dataclasses import replace
from pathlib import Path

import pytest
from hub_helpers import LOSSLESS, choose_music, make_root
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import library
from discjockey.cli import bind, call, parser
from discjockey.hub import catalog
from discjockey.hub.outcomes import EXIT

CLI_DIR = Path(cli.__file__).parent
ENVELOPE_KEYS = ["v", "command", "outcome", "reason", "message", "data", "next", "person_steps", "recovered", "job",
                 "as_of", "sandbox"]


def run(argv, capsys):
    code = cli.main(argv)
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def run_json(argv, capsys):
    code, out, err = run(argv, capsys)
    assert len(out.splitlines()) == 1, out  # exactly one object on stdout
    return code, json.loads(out)


# --- T2: the parser and the catalogue ---

def leaf_commands(root) -> set[tuple[str, ...]]:
    """Every command the parser knows, read off its tree."""
    found = set()

    def walk(p):
        action = next((a for a in p._actions if a.__class__.__name__ == "_SubParsersAction"), None)
        if action is None:
            found.add(tuple(p.get_default("_command")))
            return
        for sub in action.choices.values():
            walk(sub)

    walk(root)
    return found


def test_t2_every_built_entry_parses_and_every_parser_command_is_built_or_housekeeping():
    built = parser.built()
    assert built, "1.2 builds at least rekordbox status"
    for entry in built:
        assert entry.example, f"{entry.command} has no example"
        parsed = parser.parse(shlex.split(entry.example))
        assert parsed.command == entry.command and entry.method in {e.method for e in parsed.entries}
    assert leaf_commands(parser.build()) == {e.command for e in built} | set(parser.HOUSEKEEPING)
    # the command line's own words are the catalogue's housekeeping list (the `job` words are the job client's, 1.6)
    assert set(parser.HOUSEKEEPING) == set(catalog.HOUSEKEEPING)


@pytest.mark.parametrize("argv,where", [
    ([], "legacy"), (["--dry-run"], "legacy"), (["--json"], "legacy"), (["--limit", "3"], "legacy"),
    (["setup"], "legacy"), (["upgrade", "list", "--json"], "new"), (["--json", "upgrade", "list"], "new"),
    (["upgrade", "apply", "--all"], "legacy"),
    (["batch", "list"], "new"), (["batch", "show", "aiff:1"], "new"), (["batch", "resume", "1"], "legacy"),
    (["convert", "--all", "lossless"], "legacy"), (["hub"], "new"),
    (["rekordbox", "preview", "x"], "new"), (["rekordbox", "backups"], "legacy"), (["settings", "auto-upgrade"], "legacy"),
    (["rekordbox", "status"], "new"), (["--json", "rekordbox", "status"], "new"), (["call", "quit"], "new"),
    (["nonsense"], "new"), (["--wait", "5", "setup"], "legacy"), (["help"], "new"), (["help", "setup"], "new"),
    (["where", "--json"], "new"), (["app", "open"], "new"),
])
def test_t2_the_route_of_a_line(argv, where):
    assert parser.route(argv) == where


# --- T3: the command line computes nothing ---

BANNED_IMPORTS = {"sqlite3", "views", "db", "planner", "library", "run"}


def test_t3_a_cli_module_calls_only_what_its_entries_name():
    allowed = {e.method for e in catalog.ENTRIES} | {"resolve"}
    assert (CLI_DIR / "housekeeping.py").is_file()  # the command line's own words are checked like every module
    checked = 0
    for path in sorted(CLI_DIR.rglob("*.py")):
        if path.name in ("legacy.py", "legacy_out.py"):
            continue  # today's code, moved unchanged, until its routes are gone
        tree = ast.parse(path.read_text())
        checked += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                names = {a.name for a in node.names} | set((node.module or "").split("."))
                banned = names & BANNED_IMPORTS - ({"library"} if path.name == "bind.py" else set())
                assert not banned, f"{path.name} imports {banned}"
            if isinstance(node, ast.Import):
                assert not {a.name for a in node.names} & BANNED_IMPORTS, path.name
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and isinstance(node.func.value, ast.Name) \
                    and node.func.value.id == "api":
                # bind.py is the one module that builds the HubApi: it attaches the library and reads the missing folder
                assert node.func.attr in allowed | ({"_attach"} if path.name == "bind.py" else set()), \
                    f"{path.name} calls api.{node.func.attr}"
            if isinstance(node, ast.Subscript) and isinstance(node.value, ast.Name):
                assert node.value.id != "state", f"{path.name} indexes into state"
    assert checked >= 8


# --- global flags, the envelope and the exit codes ---

def test_global_flags_stand_anywhere(capsys):
    results = [run_json(argv, capsys) for argv in (["--json", "rekordbox", "status"], ["rekordbox", "--json", "status"],
                                                   ["rekordbox", "status", "--json"])]
    assert results[0] == results[1] == results[2]
    code, env = results[0]
    assert code == 0 and list(env) == ENVELOPE_KEYS
    assert env["v"] == 1 and env["command"] == "rekordbox status" and env["outcome"] == "ok" and env["reason"] is None
    assert env["recovered"] == [] and env["next"] == [] and env["person_steps"] == []
    assert env["as_of"] == {"scanned_at": None, "read_at": None} and env["job"] is None and env["sandbox"] is None


def test_a_flag_the_command_does_not_take_is_bad_args_with_one_object(capsys):
    for argv in (["rekordbox", "status", "--dry-run", "--json"], ["rekordbox", "status", "--nonsense", "--json"],
                 ["--json", "nonsense"], ["rekordbox", "status", "extra", "--json"], ["--json", "call"],
                 ["rekordbox", "status", "--wait", "--json"], ["call", "--json"]):
        code, env = run_json(argv, capsys)
        assert code == EXIT["bad_args"] == 2, argv
        assert (env["outcome"], env["reason"]) == ("bad_args", "usage") and env["message"] and env["data"] is None
        assert list(env) == ENVELOPE_KEYS


def test_conflicting_flags_and_text_usage_errors(capsys):
    code, env = run_json(["rekordbox", "status", "--json", "--jsonl"], capsys)
    assert (code, env["reason"]) == (2, "conflicting_flags")
    code, env = run_json(["rekordbox", "status", "--detach", "--wait", "3", "--json"], capsys)
    assert (code, env["reason"]) == (2, "conflicting_flags")
    code, out, err = run(["rekordbox", "status", "--bogus"], capsys)
    assert code == 2 and out == "" and "--bogus" in err


def test_a_crash_is_one_failed_envelope_and_exit_1(monkeypatch, capsys):
    def boom(*args, **kwargs):
        raise RuntimeError("inside")
    monkeypatch.setattr(call, "run", boom)
    code, env = run_json(["rekordbox", "status", "--json"], capsys)
    assert code == 1 and (env["outcome"], env["reason"]) == ("failed", "crashed") and "inside" not in json.dumps(env)
    code, out, err = run(["rekordbox", "status"], capsys)
    assert code == 1 and out == "" and "stopped unexpectedly" in err


# --- the first read: rekordbox status ---

def test_rekordbox_status_equals_the_bridge_inside_data(tmp_path, monkeypatch, capsys):
    folder = tmp_path / "rb"
    make_master(folder, [])
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    code, env = run_json(["rekordbox", "status", "--json"], capsys)
    answer = bind.default().rekordbox_status()
    assert code == 0 and answer["ok"] and answer["state"] == "ready"
    assert env["data"] == {k: v for k, v in answer.items() if k != "ok"}


def test_rekordbox_status_needs_no_music_folder_and_prints_a_page(capsys):
    code, out, err = run(["rekordbox", "status"], capsys)  # conftest: an empty rekordbox folder, no music folder
    assert code == 0 and err == ""
    assert out.splitlines() == ["no rekordbox library on this Mac", "", "Running      no", "Problem      none",
                                "Version      none", "Library      none", "Db version   none", "Modified at  none",
                                "Size         none"]
    code, env = run_json(["rekordbox", "status", "--json"], capsys)
    assert (code, env["data"]) == (0, {
        "state": "none", "running": False, "state_text": "no rekordbox library on this Mac", "problem": None,
        "problem_text": None, "version": None, "library": None, "db_version": None, "modified_at": None, "size": None})


def test_a_failure_in_the_bridge_answers_failed_with_exit_1(monkeypatch, capsys):
    from discjockey.hub.api import HubApi

    def boom(*a, **k):
        raise PermissionError("no access")
    monkeypatch.setattr(HubApi, "_rekordbox_read", boom)
    code, env = run_json(["rekordbox", "status", "--json"], capsys)
    assert code == 1 and env["outcome"] == "failed" and env["reason"] == "crashed" and env["data"] is None


# --- the headless HubApi ---

def test_the_headless_api_binds_nothing_and_answers_no_library_without_a_folder(tmp_path):
    api = bind.default()
    answer = api.dashboard()
    assert (answer["ok"], answer["kind"], answer["outcome"], answer["reason"]) == (False, "no_library", "refused",
                                                                                   "no_library")
    assert api._remember is not None and api._check_shown is False and api._jobs.running() is None


def test_the_headless_api_of_a_missing_folder_says_so(tmp_path, monkeypatch):
    gone = tmp_path / "gone"
    gone.mkdir()
    monkeypatch.setenv(library.SUPPORT_ENV, str(tmp_path / "support"))
    library.write_music_folder(tmp_path / "support", gone)
    gone.rmdir()  # the drive went away
    answer = bind.default().dashboard()
    assert answer["reason"] == "no_library" and str(gone) in answer["message"]


# --- HubApi.resolve ---

def test_resolve_turns_a_path_into_the_song_key_and_a_key_stays(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    api = bind.default()
    absolute = str(paths.root / LOSSLESS)
    answer = api.resolve("track", [absolute, LOSSLESS, "local:7", "qobuz:12"])
    assert answer["ok"] and answer["kind"] == "track"
    assert answer["resolved"] == ["t1", "t1", "local:7", "qobuz:12"]


def test_resolve_refuses_what_it_cannot_make_an_id_of(tmp_path, monkeypatch):
    make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    api = bind.default()
    for text in ("/no/such/file.aiff", "hello", "aiff:3", "-"):
        answer = api.resolve("track", [text])
        assert (answer["ok"], answer["outcome"]) == (False, "bad_args"), text
        assert answer["reason"] in ("unknown_id", "bad_id_kind")
    assert api.resolve("nonsense", ["x"])["outcome"] == "failed"
    assert api.resolve("track", [])["resolved"] == []


def test_resolve_of_a_path_needs_the_library(capsys):
    answer = bind.default().resolve("track", ["/some/file.aiff"])
    assert (answer["ok"], answer["reason"]) == (False, "no_library")
    assert bind.default().resolve("track", ["local:3"])["resolved"] == ["local:3"]  # a key needs nothing


def test_call_run_resolves_what_was_typed_and_never_looks_up_itself(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    entry = replace(catalog.by_method("track")[0], planned=None)  # `track show` as if it were built
    env = call.run(entry, {"track_id": str(paths.root / LOSSLESS)}, parser.Flags())
    assert env["command"] == "track show" and env["outcome"] == "ok" and env["data"]["track"]["track_id"] == "t1"
    env = call.run(entry, {"track_id": "/no/such/file"}, parser.Flags())
    assert (env["outcome"], env["reason"]) == ("bad_args", "unknown_id") and env["command"] == "track show"


# --- call <method> ---

def test_call_equals_the_noun_verb_form(capsys):
    _, direct = run_json(["rekordbox", "status", "--json"], capsys)
    code, called = run_json(["call", "rekordbox_status", "--json"], capsys)
    assert code == 0 and called == direct and called["command"] == "rekordbox status"
    code, called = run_json(["call", "rekordbox_status", "--args", "{}", "--json"], capsys)
    assert called == direct
    code, out, err = run(["call", "rekordbox_status"], capsys)
    assert code == 0 and out.splitlines()[0] == "no rekordbox library on this Mac"


def test_call_reads_its_arguments_from_stdin(monkeypatch, capsys):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
    code, env = run_json(["call", "rekordbox_status", "--args", "-", "--json"], capsys)
    assert code == 0 and env["outcome"] == "ok"


@pytest.mark.parametrize("argv,message", [
    (["call", "quit"], "closes the window"),
    (["call", "pick_folder"], "dialog"),
    (["call", "media_url"], "not offered"),
    (["call", "upgrade_all"], "not built yet"),
    (["call", "no_such_method"], "no method"),
    (["call", "rekordbox_status", "--args", "{\"nope\": 1}"], "no argument nope"),
    (["call", "rekordbox_status", "--args", "not json"], "not JSON"),
    (["call", "rekordbox_status", "--password-stdin"], "takes no password"),
    (["call", "never_download", "--args", "{\"track_id\": [\"a\"]}"], "needs never"),
])
def test_call_refuses_what_is_not_offered_as_bad_args(argv, message, capsys, monkeypatch):
    import io
    monkeypatch.setattr("sys.stdin", io.StringIO("secret\n"))
    code, env = run_json([*argv, "--json"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "usage"), env
    assert message in env["message"]


def test_call_names_the_entry_its_arguments_pick(capsys):
    code, env = run_json(["call", "upgrade", "--args", "{\"track_ids\": [\"a\"], \"mode\": \"same_track\"}", "--json"],
                         capsys)
    assert env["command"] == "upgrade apply" and env["message"].endswith("not built yet.")
    code, env = run_json(["call", "upgrade", "--args", "{\"track_ids\": [\"a\"], \"mode\": \"discard\"}", "--json"],
                         capsys)
    assert env["command"] == "upgrade discard"
    code, env = run_json(["call", "todo", "--args", "{\"filter\": \"upgrade_ready\"}", "--json"], capsys)
    assert env["command"] == "upgrade list"


def test_call_refuses_a_secret_inside_args(capsys):
    code, env = run_json(["call", "setup_qobuz_login", "--args", "{\"email\": \"a@b.c\", \"password\": \"x\"}", "--json"],
                         capsys)
    assert code == EXIT["refused"] == 7 and env["outcome"] == "refused" and "--password-stdin" in env["message"]
    assert "\"x\"" not in json.dumps(env)


def test_call_and_noun_verb_refuse_without_yes(monkeypatch):
    entry = replace(catalog.by_method("batch_undo")[0], planned=None, kind="B")
    env = call.run(entry, {"batch_id": 1}, parser.Flags())
    assert (env["outcome"], env["reason"]) == ("refused", "needs_yes") and env["command"] == "batch undo"
    monkeypatch.setattr(catalog, "ENTRIES", (entry,))
    flags = parser.Flags()
    env = call.run_method("batch_undo", {"batch_id": 1}, flags)
    assert env["reason"] == "needs_yes"


def test_a_dry_run_on_a_command_without_one_is_bad_args(capsys):
    code, env = run_json(["call", "rekordbox_status", "--dry-run", "--json"], capsys)
    assert code == 2 and "no --dry-run" in env["message"]


def test_a_dry_run_runs_the_entrys_dry_run_method(tmp_path, monkeypatch):
    make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    entry = replace(catalog.by_method("save_limits")[0], planned=None)
    env = call.run(entry, {"service": "qobuz", "limit": 40}, parser.Flags(dry_run=True))
    assert env["command"] == "limits set" and env["outcome"] == "ok" and env["data"]["limit"] == 40


# --- the old commands keep their words ---

def test_the_bare_sync_goes_to_the_old_parser_unchanged(capsys):
    code, out, err = run(["--dry-run", "--json"], capsys)
    data = json.loads(out)
    assert code == 2 and data["ok"] is False and data["kind"] == "refused" and data["reason"] == "no_library"
    assert "ok" in data and "outcome" not in data  # the old shape until the replacement lands


def test_the_old_commands_still_answer_with_their_old_shapes(tmp_path, monkeypatch, capsys):
    choose_music(tmp_path, monkeypatch)
    make_root(tmp_path)
    code, out, err = run(["rekordbox", "backups", "--json"], capsys)
    data = json.loads(out)
    assert code == 0 and data["ok"] is True and "outcome" not in data
    code, out, err = run(["--json", "rekordbox", "backups"], capsys)  # as today: the old parser drops this --json
    assert code == 0 and not out.lstrip().startswith("{")
    code, out, err = run(["convert", "--all", "lossless", "--dry-run", "--json"], capsys)
    data = json.loads(out)
    assert data["ok"] is True and "outcome" not in data and code == 0


def test_the_support_folder_of_a_test_is_a_scratch_folder():
    assert "Application Support" not in str(library.support_dir())


# --- the generic printer and the page framework ---

def test_the_generic_page_prints_words_for_facts_and_every_field_with_verbose():
    from discjockey.cli.render import generic, layout
    payload = {"cutoff_hz": 16000, "cutoff_hz_text": "FAKE · 16.0 kHz", "running": True, "path": None,
               "tags": ["a", "b"], "inner": {"depth": 2, "deeper": {"x": 1}},
               "rows": [{"id": 1, "name": "One"}, {"id": 2, "name": "Two", "extra": "yes"}]}
    plain = layout.render(generic.page(payload, message="Done."))
    assert plain.splitlines()[0] == "Done."
    assert "FAKE · 16.0 kHz" in plain and "16000" not in plain  # the words stand for the raw fact
    assert "Running  yes" in plain or "Running" in plain
    assert "Inner › Deeper" in plain and "2 of 2 shown" in plain
    verbose = layout.render(generic.page(payload, verbose=True))
    assert all(leaf in verbose for leaf in generic.leaves(payload))
    assert "16000" in verbose


def test_the_generic_page_headline_is_the_first_text_field_and_lists_page_by_limit_and_offset():
    from discjockey.cli.render import generic, layout
    rows = [{"n": i} for i in range(5)]
    page = generic.page({"headline": "Five rows.", "rows": rows}, limit=2, offset=1)
    text = layout.render(page)
    assert text.splitlines()[0] == "Five rows."
    assert "2 of 5 shown · --limit 0 for all" in text and text.splitlines()[-3:-1] == ["1", "2"]
    assert "5 of 5 shown" in layout.render(generic.page({"rows": rows}, limit=0))
    assert generic.page({"state_text": "Ready.", "state": "ready"}).headline == "Ready."


def test_rest_prints_what_a_hand_page_did_not_place_under_more():
    from discjockey.cli.render import generic, layout
    sections = generic.rest({"a": 1, "b": 2, "c": [{"x": 1}]}, {"a"})
    text = layout.render(layout.Page("Hand page", sections))
    assert "More" in text and "B  2" in text and "A  1" not in text and "More › C" in text


def test_colour_only_on_a_terminal_that_wants_it():
    import io
    from discjockey.cli.render import layout

    class Tty(io.StringIO):
        def isatty(self):
            return True
    assert layout.use_color(Tty(), environ={}) is True
    assert layout.use_color(Tty(), no_color=True, environ={}) is False
    assert layout.use_color(Tty(), environ={"NO_COLOR": "1"}) is False
    assert layout.use_color(io.StringIO(), environ={}) is False
    assert "\033[1m" in layout.render(layout.Page("Hi"), color=True) and "\033" not in layout.render(layout.Page("Hi"))


def test_a_problem_prints_its_message_and_steps_on_stderr_and_exits_with_its_number(monkeypatch, capsys):
    from discjockey.cli import envelope
    env = envelope.envelope("track hide", "needs_person", reason="rekordbox_open", message="rekordbox is open.",
                            person_steps=[{"id": "step:quit_rekordbox", "say": "Quit rekordbox.", "then": "carry on"}],
                            next=[{"run": "discjockey track hide x", "why": "after that"}])
    assert cli.emit(env, parser.Flags()) == EXIT["needs_person"] == 4
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.splitlines() == [
        "rekordbox is open.", "Your turn: Quit rekordbox. Then: carry on", "Next: discjockey track hide x  (after that)"]
    assert cli.emit(env, parser.Flags(json=True)) == 4
    assert json.loads(capsys.readouterr().out)["person_steps"][0]["id"] == "step:quit_rekordbox"


def test_the_envelope_rejects_a_word_it_does_not_know():
    from discjockey.cli import envelope
    with pytest.raises(ValueError):
        envelope.envelope("x", "great")
    with pytest.raises(ValueError):
        envelope.envelope("x", "failed", reason="made_up")
    answer = {"ok": False, "kind": "busy", "message": "Busy.", "outcome": "busy", "reason": "library_lock",
              "next": [], "person_steps": [], "data": {"holder": "sync"}}
    env = envelope.from_answer("sync run", answer)
    assert (env["outcome"], env["reason"], env["data"]) == ("busy", "library_lock", {"holder": "sync"})


# --- remember=False: a write acts on the record as it is ---

def test_a_write_checks_nothing_against_how_a_page_showed_it_when_remember_is_off(tmp_path):
    import hub_helpers
    from discjockey.hub.api import HubApi
    results = {}
    for remember in (True, False):
        root = tmp_path / str(remember)
        root.mkdir()
        paths = make_root(root)
        rec = hub_helpers.Recorder()
        api = HubApi(paths.support, rec, hub_helpers.services(), remember=remember)
        hub_helpers._MADE.append(api)
        api._attach(paths)
        api._jobs.keep_awake = hub_helpers._no_awake
        finished = hub_helpers.wait_job(api, rec, api.hide("t1", True))  # no page ever showed t1
        results[remember] = finished.ok
    assert results == {True: False, False: True}
