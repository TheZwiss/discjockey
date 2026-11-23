"""The command line's frame (issue 39 group 1.2): the parser generated from the catalogue (T2), what a `cli/` module
may call (T3), global flags anywhere, the envelope and exit codes, the first read (`rekordbox status`), `call <method>`
and the routes to the old commands."""
import ast
import json
import re
import shlex
from dataclasses import replace
from pathlib import Path

import pytest
from hub_helpers import LOSSLESS, choose_music, cmd, make_root, write_state
from rekordbox_helpers import make_master

import discjockey.cli as cli
from discjockey import library
from discjockey.cli import bind, call, envelope, parser
from discjockey.hub import catalog
from discjockey.hub.outcomes import EXIT

CLI_DIR = Path(cli.__file__).parent
ENVELOPE_KEYS = ["v", "command", "outcome", "reason", "message", "data", "page", "next", "person_steps", "recovered",
                 "job", "as_of", "sandbox"]


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


@pytest.mark.parametrize("line,args", [
    ("sync read", {}), ("sync run", {}), ("sync run --auto-upgrade-only", {}),
    ("sync run --plan plan:000000000000 --how-many 5", {"plan_id": "plan:000000000000", "how_many": "5"}),
    ("sync run act:abc --plan plan:000000000000", {"selected": ["act:abc"], "plan_id": "plan:000000000000"}),
])
def test_t2_the_sync_words_parse(line, args):
    parsed = parser.parse(shlex.split(line))
    assert parsed.command == tuple(line.split()[:2]) and parsed.args == args
    assert parsed.flags.auto_upgrade_only == ("--auto-upgrade-only" in line)


@pytest.mark.parametrize("line", ["sync run --auto-upgrade-only --how-many 5", "sync run --auto-upgrade-only act:abc",
                                  "sync run --dry-run --plan plan:000000000000", "sync run --dry-run --how-many 5"])
def test_t2_a_switch_and_the_words_of_the_whole_run_that_clash_are_conflicting_flags(line, capsys):
    code, env = run_json([*shlex.split(line), "--json"], capsys)
    assert (code, env["outcome"], env["reason"]) == (EXIT["bad_args"], "bad_args", "conflicting_flags")


def test_t2_the_switch_picks_its_entry_and_the_whole_run_is_the_other():
    entries = parser.commands()[("sync", "run")]
    with_switch = call.choose(entries, parser.Flags(auto_upgrade_only=True), {})
    without = call.choose(entries, parser.Flags(), {})
    assert (with_switch.method, without.method) == ("auto_upgrade_run", "start_sync")
    assert call.choose(entries, parser.Flags(auto_upgrade_only=True, dry_run=True), {"plan_id": "plan:000000000000"}).method == "auto_upgrade_run"


@pytest.mark.parametrize("argv,where", [
    ([], "new"), (["--dry-run"], "new"), (["--json"], "new"), (["--limit", "3"], "new"), (["--yes", "update"], "new"),
    (["update"], "legacy"), (["--verbose"], "new"),
    (["setup"], "legacy"), (["upgrade", "list", "--json"], "new"), (["--json", "upgrade", "list"], "new"),
    (["upgrade", "apply", "--all"], "new"), (["upgrade", "discard", "t1"], "new"),
    (["upgrade", "undo", "t1"], "new"), (["rekordbox", "checked", "t1"], "new"), (["upgrades"], "new"), (["track", "undo", "t1"], "new"),
    (["check", "done", "--all"], "new"),
    (["batch", "list"], "new"), (["batch", "show", "aiff:1"], "new"), (["batch", "resume", "aiff:1"], "new"),
    (["batch", "undo", "aiff:1", "--yes"], "new"),
    (["convert", "--all", "lossless"], "new"), (["rename", "--all"], "new"), (["aiff", "convert", "--all"], "new"),
    (["aiff", "rename", "--all", "--dry-run"], "new"), (["hub"], "new"),
    (["rekordbox", "preview", "x"], "new"), (["rekordbox", "backups"], "new"), (["settings", "auto-upgrade"], "new"), (["settings", "show"], "new"),
    (["rekordbox", "status"], "new"), (["--json", "rekordbox", "status"], "new"), (["call", "quit"], "new"),
    (["nonsense"], "new"), (["--wait", "5", "setup"], "legacy"), (["help"], "new"), (["help", "setup"], "new"),
    (["where", "--json"], "new"), (["app", "open"], "new"),
])
def test_t2_the_route_of_a_line(argv, where):
    assert parser.route(argv) == where


def test_t2_no_argument_is_the_short_help_and_the_catalogue_with_json(capsys):
    from discjockey import cli
    assert cli.main([]) == 0
    out = capsys.readouterr().out
    assert "help --json" in out and "job stop" in out
    assert cli.main(["--json"]) == 0
    env = json.loads(capsys.readouterr().out)
    assert env["command"] == "help" and env["outcome"] == "ok" and env["data"]


@pytest.mark.parametrize("argv", [["--dry-run"], ["--yes", "--json"], ["--verbose"], ["--limit", "3"], ["--extra", "5"],
                                  ["--wait", "5"], ["--dry-run", "--yes"]])
def test_t2_the_bare_syncs_flags_say_where_the_sync_went(argv, capsys):
    from discjockey import cli
    code = cli.main(argv)
    captured = capsys.readouterr()
    if "--json" in argv:
        env = json.loads(captured.out)
        assert (env["outcome"], env["reason"], env["message"]) == ("bad_args", "usage", parser.SYNC_MOVED_WORDS)
        assert code == EXIT["bad_args"]
    else:
        assert code == EXIT["bad_args"] and parser.SYNC_MOVED_WORDS in captured.err


# --- T3: the command line computes nothing ---

BANNED_IMPORTS = {"sqlite3", "views", "db", "planner", "library", "run"}


def test_t3_a_cli_module_calls_only_what_its_entries_name():
    allowed = {e.method for e in catalog.ENTRIES} | {"resolve", "save_plan", "scan_next", "_job_envelope"}  # the last three: a dry run's plan, `next`, and the envelope of a finished job (the worker, `HubApi._job_envelope`)
    assert (CLI_DIR / "housekeeping.py").is_file()  # the command line's own words are checked like every module
    checked = 0
    for path in sorted(CLI_DIR.rglob("*.py")):
        if path.name == "legacy.py":
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


JOB_FLAG_LINES = (["--detach"], ["--wait", "30"], ["--wait-busy", "5"], ["--jsonl"])


def test_a_job_flag_on_a_command_that_answers_at_once_is_bad_args_never_ignored(capsys):
    """Design §2.2: a flag a command does not take is a usage error. A read, a brief save, `--dry-run` of a write that
    answers at once, and the command line's own words answer at once; --detach, --wait, --wait-busy and --jsonl are
    for a command that runs as a job."""
    for words in (["help"], ["where"], ["batch", "list"], ["rekordbox", "status"], ["job", "list"],
                  ["call", "rekordbox_status"], ["library", "facts", "--dry-run"]):
        for flag in JOB_FLAG_LINES:
            for form in ([], ["--json"]):
                if flag == ["--jsonl"] and form:
                    continue  # --json with --jsonl is its own conflict
                code, out, err = run([*words, *flag, *form], capsys)
                lines = out.splitlines()
                assert code == EXIT["bad_args"] == 2, (words, flag, form)
                if form or flag == ["--jsonl"]:
                    env = json.loads(lines[-1])
                    assert (env["outcome"], env["reason"], env["data"]) == ("bad_args", "usage", None), (words, flag)
                    assert list(env) == ENVELOPE_KEYS and "answers at once" in env["message"] and flag[0] in env["message"]
                else:
                    assert out == "" and "answers at once" in err and flag[0] in err, (words, flag)


def test_a_job_command_still_takes_the_job_flags(monkeypatch, capsys):
    seen = []

    def start(entry, kwargs, command, flags, **rest):
        seen.append((command, flags.detach, flags.wait, flags.jsonl))
        return envelope.envelope(command, "ok", data={"job": "job:x", "status": "running"})

    monkeypatch.setattr(call, "start_job", start)
    for flag in (["--detach"], ["--wait", "30"], ["--jsonl"]):
        code, out, _ = run(["library", "scan", *flag, *([] if flag == ["--jsonl"] else ["--json"])], capsys)
        assert code == 0 and json.loads(out.splitlines()[-1])["outcome"] == "ok", flag
    assert seen == [("library scan", True, None, False), ("library scan", False, 30.0, False),
                    ("library scan", False, None, True)]
    code, env = run_json(["job", "wait", "current", "--wait", "1", "--json"], capsys)  # `job wait` takes --wait
    assert env["reason"] != "usage" or "answers at once" not in env["message"]
    code, env = run_json(["job", "wait", "current", "--detach", "--json"], capsys)  # but not --detach
    assert (code, env["reason"]) == (2, "usage") and "--detach" in env["message"]


def test_help_json_names_the_job_flags_as_the_job_commands_own(capsys):
    code, env = run_json(["help", "--json"], capsys)
    data = env["data"]
    assert {f["flag"] for f in data["global_flags"] if "job commands" in f["says"]} == {
        "--jsonl", "--wait", "--detach", "--wait-busy"}
    job_flags = {"--jsonl", "--wait", "--detach", "--wait-busy"}
    for command in data["commands"]:  # a command that answers at once never lists them
        assert not job_flags & set(command["flags"]) or command["job"], command["command"]
    assert any(c["job"] for c in data["commands"])


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
    assert api._jobs.running() is None


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
    state = library.load_state(paths)
    state["tracks"]["qobuz:12"] = {**state["tracks"]["t1"], "path": "Library/Hard_Bounce/Other - Song.aiff"}
    write_state(paths, state)
    answer = api.resolve("track", [absolute, LOSSLESS, "qobuz:12"])
    assert answer["ok"] and answer["kind"] == "track"
    assert answer["resolved"] == ["t1", "t1", "qobuz:12"]  # a key stays; one the library lacks is unknown_id
    lacking = api.resolve("track", ["local:7"])
    assert (lacking["outcome"], lacking["reason"]) == ("bad_args", "unknown_id") and "local:7" in lacking["message"]


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
    assert bind.default().resolve("track", ["local:3"])["reason"] == "no_library"  # a key is looked up in the records too


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
    (["call", "retry_music_folder"], "starts watching it"),
    (["call", "media_url"], "not offered"),
    (["call", "tidy_up"], "not built yet"),
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
    from discjockey.cli import call as call_mod
    from discjockey.hub import catalog
    assert call_mod.command_of(call_mod._pick(catalog.by_method("upgrade"), {"mode": "same_track"})) == "upgrade apply"
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
    entry = replace(catalog.by_method("setup_forget_account")[0], planned=None, kind="B")  # needs --yes, no dry run
    env = call.run(entry, {"service": "youtube"}, parser.Flags())
    assert (env["outcome"], env["reason"]) == ("refused", "needs_yes") and env["command"] == "login sign-out"
    monkeypatch.setattr(catalog, "ENTRIES", (entry,))
    flags = parser.Flags()
    env = call.run_method("setup_forget_account", {"service": "youtube"}, flags)
    assert env["reason"] == "needs_yes"


def test_the_windows_stop_controls_point_to_job_stop(capsys):
    code, env = run_json(["call", "stop", "--json"], capsys)
    assert code == 2 and env["message"] == "stop is the window's Stop safely: use `job stop <job>`."


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

def test_update_goes_to_the_old_parser_unchanged(capsys):
    code, out, err = run(["update"], capsys)
    assert code == 2 and "doesn't know your music folder yet" in out and err == ""  # plain words, no envelope


def test_the_support_folder_of_a_test_is_a_scratch_folder():
    assert "Application Support" not in str(library.support_dir())


def test_a_test_cannot_open_a_real_app_or_page(tmp_path):
    """conftest's guard (C-18): the opener the command line binds (`Services()`) and the calls under it refuse."""
    import subprocess
    import webbrowser
    from discjockey.hub.api import Services
    missing = tmp_path / "nothing-here"
    for call_ in (lambda: subprocess.run(["open", str(missing)], check=False),
                  lambda: subprocess.run(["open", "-R", str(missing)], check=False),
                  lambda: Services().open_path(missing), lambda: Services().reveal(missing),
                  lambda: webbrowser.get()):
        with pytest.raises(AssertionError, match="stub the opener"):
            call_()
    assert subprocess.run(["echo", "hi"], capture_output=True, text=True).stdout == "hi\n"  # other commands run


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


def test_a_rev_prints_only_with_verbose_in_rows_and_in_table_columns():
    from discjockey.cli.render import generic, layout
    payload = {"rev": "0123456789", "artist": "A",
               "rows": [{"track_id": "t1", "rev": "abcdef0123", "title": "One"}]}
    plain = layout.render(generic.page(payload))
    assert "0123456789" not in plain and "abcdef0123" not in plain and "One" in plain and "Rev" not in plain
    verbose = layout.render(generic.page(payload, verbose=True))
    assert "0123456789" in verbose and "abcdef0123" in verbose and "Rev" in verbose
    assert [k for k, _ in generic._columns(payload["rows"], False)] == ["track_id", "title"]


def test_the_generic_page_headline_is_the_first_text_field_and_lists_page_by_limit_and_offset():
    from discjockey.cli.render import generic, layout
    rows = [{"n": i} for i in range(5)]
    page = generic.page({"headline": "Five rows.", "rows": rows}, limit=2, offset=1)
    text = layout.render(page)
    assert text.splitlines()[0] == "Five rows."
    assert "2 of 5 shown · --limit 0 for all" in text and text.splitlines()[-3:-1] == ["1", "2"]
    assert "5 of 5 shown" in layout.render(generic.page({"rows": rows}, limit=0))
    assert generic.page({"state_text": "Ready.", "state": "ready"}).headline == "Ready."


def test_the_generic_page_headline_is_the_top_level_text_before_any_other_text_field_and_is_not_repeated():
    from discjockey.cli.render import generic, layout
    page = generic.page({"state_text": "A", "text": "B"})
    assert page.headline == "B"
    lines = layout.render(page).splitlines()
    assert lines[0] == "B" and lines.count("B") == 1 and not [line for line in lines[1:] if line.startswith("Text")]


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
                            person_steps=[{"id": "step:quit_rekordbox", "say": "Quit rekordbox.", "then": "track hide x"}],
                            next=[{"run": "track hide x", "why": "after that"}])
    assert cli.emit(env, parser.Flags()) == EXIT["needs_person"] == 4
    captured = capsys.readouterr()
    assert captured.out == "" and captured.err.splitlines() == [
        "rekordbox is open.", f"Your turn: Quit rekordbox. Then: {cmd('track hide x')}", f"Next: {cmd('track hide x')}  (after that)"]
    assert cli.emit(env, parser.Flags(json=True)) == 4
    assert json.loads(capsys.readouterr().out)["person_steps"][0]["id"] == "step:quit_rekordbox"


def test_the_command_lines_own_constants_are_defined_once():
    from discjockey.cli.render import generic
    assert parser.HOUSEKEEPING is catalog.HOUSEKEEPING and parser.DEFAULT_LIMIT is generic.DEFAULT_LIMIT
    for name in ("HELP", "WHERE", "APP_OPEN", "CALL", *("JOB_" + w for w in ("LIST", "SHOW", "FOLLOW", "WAIT", "STOP"))):
        assert getattr(parser, name) in parser.HOUSEKEEPING, name


def test_every_command_the_envelope_names_is_a_full_command_line(monkeypatch, capsys):
    from discjockey.cli import envelope, housekeeping
    path = housekeeping.command_path()
    env = envelope.envelope("sync read", "needs_person", reason="rekordbox_open", message="Open.",
                            person_steps=[{"id": "step:quit_rekordbox", "say": "Quit.", "then": None},
                                          {"id": "step:reload_tag", "say": "Reload.", "then": "check done t1"}],
                            next=[{"run": "sync read", "why": "again"}, {"run": f"{path} job show job:1", "why": "x"}],
                            data={"person_steps": [{"then": "check done t1"}]})
    assert cli.emit(env, parser.Flags(json=True)) == 4
    out = json.loads(capsys.readouterr().out)
    assert [n["run"] for n in out["next"]] == [cmd("sync read"), f"{path} job show job:1"]  # one path, never two
    assert [s["then"] for s in out["person_steps"]] == [None, cmd("check done t1")]
    assert out["data"] == {"person_steps": [{"then": "check done t1"}]}  # data is the bridge's answer, left alone
    # a path with a space (a checkout under "DJ Downloader/") is quoted, once, also where the line already has it
    monkeypatch.setattr(housekeeping, "command_path", lambda: "/Users/x y/bin/discjockey")
    quoted = "'/Users/x y/bin/discjockey'"
    spaced = envelope.envelope("sync read", "ok", next=[{"run": "sync read", "why": "a"}, {"run": f"{quoted} job wait j", "why": "b"}])
    assert cli.runnable(spaced)["next"] == [{"run": f"{quoted} sync read", "why": "a"}, {"run": f"{quoted} job wait j", "why": "b"}]
    from discjockey.cli import follow
    assert follow.first_line("job:1") == f"Job job:1 started (follow: {quoted} job follow job:1)"
    assert follow.running_envelope("job wait", {"id": "job:1", "status": "running"})["next"][0]["run"].startswith(quoted + " job wait")


def test_both_your_turn_lines_start_with_the_one_prefix(monkeypatch, capsys):
    from discjockey.cli import envelope, follow
    monkeypatch.setattr(envelope, "YOUR_TURN", "Over to you: ")
    env = envelope.envelope("track hide", "needs_person", reason="rekordbox_open",
                            person_steps=[{"id": "step:quit_rekordbox", "say": "Quit rekordbox.", "then": None}])
    assert cli.notices(env)[-1] == "Over to you: Quit rekordbox."
    source = Path(follow.__file__).read_text()
    assert "Your turn" not in source and "envelope.YOUR_TURN" in source


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


def test_an_ok_answers_next_and_person_steps_are_the_envelopes_not_data():
    from discjockey.cli import envelope
    step = {"id": "step:connect_drive", "say": "Connect the drive Gig Stick.", "then": None}
    answer = {"ok": True, "rows": [1], "next": [{"run": "doctor", "why": "look further"}], "person_steps": [step]}
    env = envelope.from_answer("status", answer)
    assert (env["outcome"], env["data"]) == ("ok", {"rows": [1]})
    assert env["next"] == [{"run": "doctor", "why": "look further"}] and env["person_steps"] == [step]
    plain = envelope.from_answer("status", {"ok": True, "rows": []})
    assert plain["next"] == [] and plain["person_steps"] == []


# --- `rev` replaces the window's memory of what it showed ---

def test_the_api_keeps_no_memory_of_what_a_page_showed():
    import inspect

    from discjockey.hub.api import HubApi
    assert not any(hasattr(HubApi, name) for name in ("_shown", "_check_shown", "_remember"))
    assert "remember" not in inspect.signature(HubApi.__init__).parameters
    source = inspect.getsource(HubApi)
    assert not re.search(r"\._shown\b|_check_shown|\._remember\b", source)


def test_a_write_checks_the_rev_only_when_it_is_given(tmp_path):
    import hub_helpers
    from discjockey import models
    paths = make_root(tmp_path)
    api, rec = hub_helpers.make_api(paths)
    stale = hub_helpers.wait_job(api, rec, api.hide("t1", True, "0123456789"))  # no page showed t1: only the rev counts
    assert (stale.ok, stale.problem) == (False, "changed")
    current = models.rev(library.load_state(paths)["tracks"]["t1"])
    assert hub_helpers.wait_job(api, rec, api.hide("t1", True, current)).ok
    assert hub_helpers.wait_job(api, rec, api.hide("t1", False)).ok  # no expect: acts on the record as it is


def test_a_parameter_named_expect_is_the_flag_if_rev():
    import inspect

    from discjockey.hub.api import HubApi
    arg = catalog.generated_arg("expect", inspect.signature(HubApi.hide).parameters["expect"])
    assert arg.flag == "--if-rev" and not arg.positional


# --- the removal of `batch_cmd` and `upgrades_cmd` (issue 39, group 1.12) ---

def test_the_deleted_modules_are_gone_and_no_module_names_them():
    import importlib.util
    import re
    from pathlib import Path
    for name in ("discjockey.batch_cmd", "discjockey.upgrades_cmd"):
        assert importlib.util.find_spec(name) is None, name
    package = Path(__file__).resolve().parent.parent / "discjockey"
    named = [str(p.relative_to(package)) for p in package.rglob("*.py")
             if re.search(r"\b(batch_cmd|upgrades_cmd)\b", p.read_text(encoding="utf-8"))]
    assert named == []


@pytest.mark.parametrize("argv,say", [
    (["upgrades"], "say `upgrade …`"), (["upgrades", "--yes"], "say `upgrade …`"),
    (["rekordbox", "checked", "t1"], "say `check done`"), (["rekordbox", "checked", "--batch", "1"], "say `check done`"),
    (["upgrade", "undo", "t1"], "say `track undo`"),
])
def test_the_removed_words_are_bad_args_that_say_what_to_say_instead(argv, say, capsys):
    assert parser.route(argv) == "new"  # no route reaches the old parser
    code, out, err = run([*argv, "--json"], capsys)
    env = json.loads(out)
    assert (code, env["outcome"], env["reason"]) == (2, "bad_args", "usage") and say in env["message"]
    code, out, err = run(argv, capsys)  # the plain page says it too, on stderr
    assert code == 2 and out == "" and say in err


# --- the command line's words for a wrong line (phase review C-7, C-15) ---

@pytest.mark.parametrize("argv,message", [
    (["batch", "resume"], "Say which batch: aiff:N."),
    (["batch", "show"], "Say which batch: aiff:N|moves:N."),
    (["job", "show"], "Say which job: job:ID|current."),
    (["call"], "Say which method: call <METHOD>."),
    (["settings", "set", "auto-upgrade"], "Say on or off."),
    (["todo", "list", "--foo"], "todo list does not take --foo. `help todo list` lists what it takes."),
    (["upgrade", "apply", "x", "--way"], "--way needs a value."),
    (["todo", "list", "--limit", "many"], "--limit takes a number, not many."),
])
def test_a_wrong_line_is_answered_in_the_command_lines_words_not_argparses(argv, message, capsys):
    code, env = run_json([*argv, "--json"], capsys)
    assert (code, env["outcome"], env["reason"], env["message"]) == (2, "bad_args", "usage", message)


def test_a_usage_error_under_jsonl_still_ends_with_the_envelope_line(capsys):
    code, out, err = run(["todo", "list", "--jsonl", "--bogus"], capsys)
    lines = out.splitlines()
    assert code == 2 and len(lines) == 1 and err == ""
    assert json.loads(lines[0])["outcome"] == "bad_args" and "--bogus" in json.loads(lines[0])["message"]


# --- a TypedDict parameter's keys as words (`<param>.<key>`): the mechanism, on test-only entries ---

TRIAL = catalog._e("save_playlists", "playlist trial", "J", "playlist trial A B --to 2", built=True, locks={"library"},
                   dry_run="preview_playlist_change",
                   params={"op.playlist": catalog._positional(), "op.folder": catalog._positional(),
                           "op.to": catalog.Arg("--to", type="int", required=True),
                           "op.off": catalog.Arg("--off", type="bool"), "files.choice": catalog.Arg("--files")},
                   fixed={"op.op": "rename", "lines": None, "loaded_version": None})
OTHER = catalog._e("save_playlists", "playlist other", "J", "playlist other A", built=True, locks={"library"},
                   params={"op.playlist": catalog._positional()},
                   fixed={"op.op": "remove", "lines": None, "loaded_version": None})


@pytest.fixture
def trial(monkeypatch):
    """The catalogue with two test-only commands that map `save_playlists`' TypedDict parameters, in place of the method's
    own (planned) entries."""
    monkeypatch.setattr(catalog, "ENTRIES", (*(e for e in catalog.ENTRIES if e.method != "save_playlists"), TRIAL, OTHER))
    return TRIAL


def test_a_dotted_word_parses_into_its_dotted_name(trial):
    parsed = parser.parse(shlex.split("playlist trial A B --to 2 --off --files move --dry-run"))
    assert parsed.command == ("playlist", "trial") and parsed.flags.dry_run
    assert parsed.args == {"op.playlist": "A", "op.folder": "B", "op.to": 2, "op.off": True, "files.choice": "move"}
    assert parser.parse(shlex.split("playlist other A")).args == {"op.playlist": "A"}


@pytest.mark.parametrize("line,message", [
    ("playlist trial A B", "--to is missing."),  # a required flag
    ("playlist trial A --to 2", "Say which folder: FOLDER."),  # a dotted positional is named by its key
    ("playlist trial --to 2", "Say which playlist: PLAYLIST."),
    ("playlist trial A B --to x", "--to takes a number, not x."),
    ("playlist trial A B --to", "--to needs a value."),
])
def test_a_dotted_word_that_is_wrong_says_so_in_its_own_words(trial, line, message):
    with pytest.raises(parser.UsageError) as e:
        parser.parse(shlex.split(line))
    assert e.value.message == message


def test_help_says_which_flags_a_command_cannot_run_without(trial):
    from discjockey.cli import housekeeping
    row = housekeeping.index_entry(("playlist", "trial"), [trial])
    assert {a["name"]: (a["word"], a["positional"], a["required"]) for a in row["args"]} == {
        "files.choice": ("--files", False, False), "op.playlist": ("PLAYLIST", True, True),
        "op.folder": ("FOLDER", True, True), "op.to": ("--to", False, True), "op.off": ("--off", False, False)}
    assert row["required_flags"] == ["--to"]
    assert row["flag_values"] == {"--files": "CHOICE", "--to": "TO"}
    # the positionals first, then the flag it cannot run without (no brackets), then the others in their order
    assert row["usage"] == "playlist trial PLAYLIST FOLDER --to TO [--files CHOICE] [--off] [--dry-run]"


def test_a_flag_the_all_word_stands_in_for_is_not_required_in_help(capsys):
    row = run_json(["help", "upgrade", "apply", "--json"], capsys)[1]["data"]["commands"][0]
    way = next(a for a in row["args"] if a["word"] == "--way")
    assert "--all" in row["flags"] and way["required"] is False and row["required_flags"] == []


def test_the_arguments_of_a_command_pack_the_dotted_keys_into_their_dict(trial):
    kwargs, failed = call._arguments(trial, {"op.playlist": "A", "op.folder": "B", "op.to": 2}, "playlist trial", None, False)
    assert failed is None
    assert kwargs == {"op": {"playlist": "A", "folder": "B", "to": 2, "op": "rename"}, "lines": None, "loaded_version": None}  # no `files`: no key given


def test_a_dict_given_whole_is_copied_and_never_changed(trial):
    whole = {"playlist": "A", "folder": "B", "to": 2}
    kwargs, failed = call._arguments(trial, {"op": whole}, "playlist trial", None, True)
    assert failed is None and kwargs["op"] == {**whole, "op": "rename"} and kwargs["op"] is not whole
    assert whole == {"playlist": "A", "folder": "B", "to": 2}


def test_packing_leaves_a_dict_out_when_none_of_its_keys_is_given():
    assert call._packed({"lines": None, "loaded_version": "v"}) == {"lines": None, "loaded_version": "v"}
    given = {"op": {"op": "add"}}
    assert call._packed({**given, "op.url": "u", "files.choice": "move"}) == {
        "op": {"op": "add", "url": "u"}, "files": {"choice": "move"}}
    assert given == {"op": {"op": "add"}}


def test_a_dotted_word_with_a_resolver_is_resolved_before_it_is_packed(monkeypatch):
    entry = catalog._e("save_playlists", "playlist trial", "J", built=True, fixed={"op.op": "edit", "lines": None},
                       params={"op.file": catalog.Arg("--file", resolve="local_path", required=True)})

    class Api:
        def resolve(self, kind, values):
            return {"ok": True, "resolved": [f"{kind}:{v}" for v in values]}

    kwargs, failed = call._arguments(entry, {"op.file": "my.txt"}, "playlist trial", Api(), False)
    assert failed is None and kwargs["op"] == {"file": "local_path:my.txt", "op": "edit"}


def test_a_method_call_picks_its_entry_by_a_fixed_key_inside_the_dict(trial):
    entries = catalog.by_method("save_playlists")
    pick = lambda args: (e := call._pick(entries, args)) and call.command_of(e)  # noqa: E731
    assert pick({"op": {"op": "rename", "playlist": "A"}}) == "playlist trial"
    assert pick({"op": {"op": "remove", "playlist": "A"}, "files": {"choice": "move"}}) == "playlist other"
    assert pick({"op": {"op": "add", "url": "u"}}) is None  # no entry takes this value
    assert pick({"lines": ["a = b"]}) is None  # the window's whole-list save is `playlist edit --file`
    assert pick({"op": "rename"}) is None and pick({}) is None


def test_a_method_call_that_names_no_entry_says_which_keys_it_needs(trial):
    def said(method, args):
        env = call.run_method(method, args, parser.Flags())
        assert (env["outcome"], env["reason"]) == ("bad_args", "usage"), env
        return env["message"]

    assert said("save_playlists", {"lines": []}) == "save_playlists needs op.op with one of the values it takes."
    assert said("save_playlists", {"op": {"op": "add"}}) == "save_playlists needs op.op with one of the values it takes."
    assert said("refresh", {"auto": True}) == "refresh needs auto with one of the values it takes."
    assert said("never_download", {"track_id": ["a"]}) == "never_download needs never with one of the values it takes."


def test_a_fixed_value_that_is_its_default_goes_unsaid_in_a_method_call():
    refresh = catalog.by_method("refresh")
    assert call.command_of(call._pick(refresh, {})) == "sync read"  # `auto: False` is the default
    assert call._pick(refresh, {"auto": True}) is None
