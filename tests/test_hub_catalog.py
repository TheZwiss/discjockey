"""T1, catalogue <-> bridge (issue 39, design §13): every @bridge method of HubApi has an entry, every entry names a
method, every parameter has a word, window-only and dropped rows are what the design says."""
import inspect
import re
import typing
from dataclasses import replace

import pytest

from discjockey.hub import catalog, shapes
from discjockey.hub.api import CliApi, HubApi
from discjockey.hub.catalog import Arg, Entry

# The ceiling of entries that may still be `planned` (their command not built). Every group that builds a command lowers
# the number; nothing may raise it. Phase 1 built the AIFF, upgrade, folder, rekordbox and settings commands; phase 3
# group V3.1a (this number: 74) builds `library list`, `library collections`, `folder list`, `folder check`,
# `report list`, `sync plan` and `track spectrum`. V3.1b (13 rows: the setup, limits, playlist, login and tidy reads) is
# lowering it in steps (70: its four dry-run-only rows are built). The next to lower it after it, V3.1c (6: the `open` commands), V3.2b (1: `status`); phase 4's rows stay planned until it builds
# them (`planned` names the group).
PLANNED_CEILING = 70
# The phases that are finished: no row may be planned for one of them (V3.2b sets 3 when phase 3 ends).
FINISHED_PHASES = 2

CLI_FIRST = {"freshness", "resolve", "find_tracks", "rekordbox_preview", "batches", "batch_detail", "select_listing",
             "upgrade_preview", "undo_upgrade_preview", "batch_undo_preview", "result_words", "fill_facts", "facts_preview", "auto_upgrade_preview", "auto_upgrade_run", "settings_view",
             "rekordbox_backups", "rekordbox_restore", "rekordbox_restore_preview"}


def bridge_methods() -> dict[str, inspect.Signature]:
    return {name: inspect.signature(fn.__wrapped__) for name, fn in vars(HubApi).items()
            if getattr(fn, "is_bridge", False)}


BRIDGE = bridge_methods()
EXISTING = [e for e in catalog.ENTRIES if not e.cli_first]


def test_the_bridge_has_97_methods_and_each_has_an_entry():
    # a dropped method (kind `dropped`) keeps its row for the command line's refusal; the bridge has none of them
    assert len(BRIDGE) == 97
    assert not set(BRIDGE) & catalog.DROPPED
    assert set(BRIDGE) == {e.method for e in EXISTING if e.kind != "dropped"}


def test_an_entry_names_no_method_the_bridge_lacks():
    for e in EXISTING:
        assert e.kind == "dropped" or e.method in BRIDGE, e
    for e in catalog.ENTRIES:
        if e.cli_first:
            # a method that does not exist yet is planned until its group builds it
            assert e.planned or hasattr(CliApi, e.method), e


def test_the_cli_first_methods_are_the_listed_ones():
    assert {e.method for e in catalog.ENTRIES if e.cli_first} == CLI_FIRST


def test_a_cli_first_method_exists_exactly_when_its_entry_is_built():
    # the window's HubApi has none of them: pywebview would hand them to the page
    assert not any(getattr(getattr(HubApi, n, None), "is_cli_first", False) for n in dir(HubApi))
    for e in catalog.ENTRIES:
        if e.cli_first:
            method = getattr(CliApi, e.method, None)
            assert (method is not None) == (e.planned is None), e
            if method is not None:
                assert getattr(method, "is_cli_first", False) and not getattr(method, "is_bridge", False), e


def test_window_only_and_dropped():
    assert catalog.WINDOW_ONLY == {"pick_folder": "native_dialog", "quit": "closes_window"}
    assert set(catalog.WINDOW_ONLY.values()) <= {"native_dialog", "closes_window"}
    assert catalog.DROPPED == {"media_url", "select", "setup_check_account"}
    assert {e.method for e in EXISTING if e.kind == "W"} == set(catalog.WINDOW_ONLY)
    assert {e.method for e in EXISTING if e.kind == "dropped"} == catalog.DROPPED
    for e in catalog.ENTRIES:
        if e.kind in ("W", "dropped"):
            assert e.command == () and e.planned is None


def effective(entry: Entry) -> dict[str, Arg]:
    return catalog.effective_params(entry, BRIDGE[entry.method])


@pytest.mark.parametrize("entry", [e for e in EXISTING if e.kind not in ("W", "dropped")],
                         ids=lambda e: f"{e.method}:{' '.join(e.command)}")
def test_every_parameter_has_a_flag_or_positional_or_fixed_value(entry):
    signature = BRIDGE[entry.method]
    names = set(signature.parameters) - {"self"}
    assert set(entry.params) <= names, "an override names a parameter the method does not have"
    assert set(entry.fixed) <= names, "a fixed value names a parameter the method does not have"
    assert not set(entry.params) & set(entry.fixed)
    words = effective(entry)
    assert set(words) | set(entry.fixed) == names
    for name, arg in words.items():
        assert arg.flag or arg.positional or arg.resolve, f"{name} has no word and nothing builds it"
        if arg.flag:
            assert arg.flag.startswith("--") and arg.flag == arg.flag.lower()
        if arg.type in ("dict", "list") and not arg.positional:
            assert arg.resolve, f"{name} is a {arg.type} nothing builds"
        if str(signature.parameters[name].annotation).split("|")[0].strip() == "dict":
            assert name in entry.params and arg.resolve, f"the dict {name} needs its entry to say how it is built"
    flags = [a.flag for a in words.values() if a.flag]
    assert len(flags) == len(set(flags)), "two parameters share a flag"
    assert catalog.LOCKS and entry.locks <= set(catalog.LOCKS)


def test_a_dict_parameters_typeddict_keys_are_mapped():
    class Scope(typing.TypedDict):
        kind: str
        tracks: list

    assert catalog.typed_dict_keys(Scope) == {"kind", "tracks"}
    assert catalog.typed_dict_keys(dict) == frozenset()
    # no bridge parameter has a TypedDict today: when one does, its keys belong in `params` as "<param>.<key>"
    for name, signature in BRIDGE.items():
        for pname, p in signature.parameters.items():
            if catalog.typed_dict_keys(p.annotation):
                for entry in catalog.by_method(name):
                    for key in catalog.typed_dict_keys(p.annotation):
                        assert f"{pname}.{key}" in entry.params


def test_flags_are_made_from_the_signature():
    flags = {e.method: effective(e) for e in EXISTING if e.method in ("limits_what_if", "refresh", "todo", "library")}
    assert flags["limits_what_if"]["extra_today"].flag == "--extra-today"
    assert flags["limits_what_if"]["limit"].positional
    assert flags["refresh"]["auto"].flag == "--auto"
    todo = effective(catalog.by_method("todo")[0])
    assert todo["filter"].flag == "--group" and todo["show_hidden"].flag == "--hidden"
    library = effective(catalog.by_method("library")[0])
    assert (library["view"].flag, library["query"].flag, library["filter"].flag) == ("--in", "--search", "--quality")
    assert library["view"].resolve == "collection"
    # a trailing _id is dropped, a list is a positional that takes many
    sig = inspect.signature(lambda plan_id=None, track_ids=(): None)
    assert catalog.generated_arg("plan_id", sig.parameters["plan_id"]).flag == "--plan"
    arg = catalog.generated_arg("track_ids", inspect.Parameter("track_ids", 1, annotation="list[str]"))
    assert arg.positional and arg.many and arg.resolve == "track"


def test_fixed_values_make_the_commands_of_one_method():
    never = {e.command: e.fixed for e in catalog.by_method("never_download")}
    assert never == {("track", "never"): {"never": True}, ("track", "download"): {"never": False}}
    todo = {e.command: e.fixed for e in catalog.by_method("todo")}
    assert todo[("upgrade", "list")] == {"filter": "upgrade_ready"}
    assert todo[("check", "list")] == {"filter": "rekordbox_check"}


def test_the_password_is_secret_and_only_it():
    secrets = [(e.method, n) for e in catalog.ENTRIES for n, a in e.params.items() if a.secret]
    assert secrets == [("setup_qobuz_login", "password")]


def test_dry_runs_name_a_method_that_exists_or_is_planned():
    known = set(BRIDGE) | CLI_FIRST
    for e in catalog.ENTRIES:
        if e.dry_run:
            assert e.dry_run in known, e


def test_every_read_with_a_command_has_an_example_that_starts_with_it():
    for e in EXISTING:
        if e.kind == "R" and e.command:
            assert e.example, f"{e.method} {e.command} has no example"
            assert e.example.startswith(" ".join(e.command)), e.example
        assert e.schema == shapes.ANSWERS.get(e.method), e


def test_the_entries_are_well_formed():
    seen = set()
    for e in catalog.ENTRIES:
        assert e.kind in ("R", "RJ", "J", "J-control", "B", "W", "dropped"), e
        key = (e.method, e.command, e.cli_first, repr(sorted(e.fixed.items(), key=str)))  # a fixed value may be a list
        assert key not in seen, e
        seen.add(key)
        assert e.planned is None or re.fullmatch(r"phase (\d): V\1\.\d+[a-z]?", e.planned), e
    assert {("help",), ("where",), ("app", "open"), ("call",)} <= set(catalog.HOUSEKEEPING)


def test_the_planned_count_only_shrinks():
    planned = [e for e in catalog.ENTRIES if e.planned]
    assert len(planned) <= PLANNED_CEILING, f"{len(planned)} planned entries"


def test_no_entry_is_planned_for_a_finished_phase():
    late = [e for e in catalog.ENTRIES if e.planned and int(e.planned[len("phase "):][0]) <= FINISHED_PHASES]
    assert not late, late


def test_pages_names_a_top_level_list_of_the_answer_of_a_read():
    paged = [e for e in catalog.ENTRIES if e.pages]
    assert {(e.method, e.pages) for e in paged} == {("library", "rows"), ("runs", "runs")}
    for e in paged:
        assert e.kind == "R" and e.planned is None, e  # a page is cut where the answer is whole: a read that answers at once
        assert e.schema, f"{e.method} has no shape: its list cannot be checked"
        field = shapes.DEFAULT.definition(e.schema)["properties"].get(e.pages)
        assert field is not None and field.get("type") == "array", (e.method, e.pages)


def test_a_row_that_is_not_built_needs_its_label():
    with pytest.raises(ValueError):
        catalog._e("hide", "track hide", "J")
    assert catalog._e("hide", "track hide", "J", planned="phase 4: V4.6").planned == "phase 4: V4.6"
    assert catalog._e("hide", "track hide", "J", built=True).planned is None
    assert catalog._e("quit", "", "W").planned is None


def _all_built(monkeypatch):
    """Every entry as if its command were built (`planned` cleared): what the parser must still be able to make."""
    monkeypatch.setattr(catalog, "ENTRIES", tuple(replace(e, planned=None) for e in catalog.ENTRIES))


def test_the_parser_builds_with_every_planned_command_built(monkeypatch):
    """A command line that cannot be made stops every line: the rows phase 1 wrote down must not collide (the three-word
    login rows `login sign-in spotify` and `login sign-in <service>` did)."""
    from discjockey.cli import parser
    _all_built(monkeypatch)
    assert parser.build() is not None
    assert {("login", "check"), ("login", "sign-in"), ("login", "sign-out"), ("login", "skip")} <= set(parser.commands())


def test_a_command_with_several_writes_names_the_rule_that_picks_one(monkeypatch):
    """The parser takes its words from the first write of a command; the rest are reached by a rule the group that builds
    the command writes in `call.choose`. Every such command is named in `DISPATCH`, built or planned."""
    several = {}
    for e in catalog.ENTRIES:
        if e.command and e.kind not in ("R", "W", "dropped"):
            several.setdefault(" ".join(e.command), []).append(e)
    needs = {command for command, entries in several.items() if len(entries) > 1}
    assert needs <= set(catalog.DISPATCH), sorted(needs - set(catalog.DISPATCH))
    assert set(catalog.DISPATCH) <= needs, "a rule for a command that has one write only"
    assert all(catalog.DISPATCH.values())


def test_a_login_row_names_its_service_in_match_not_in_its_command():
    rows = {e.method: e for e in catalog.ENTRIES if e.command[:1] == ("login",) and e.match}
    assert {m: dict(e.match) for m, e in rows.items()} == {
        "qobuz_check_login": {"service": "qobuz"}, "setup_skip_qobuz": {"service": "qobuz"},
        "setup_spotify_login": {"service": "spotify"}, "spotify_sign_out": {"service": "spotify"},
        "setup_skip_spotify": {"service": "spotify"}}
    assert all(len(e.command) == 2 for e in rows.values())


def test_secret_arguments_never_reach_a_job_record():
    """`SECRET_PARAMS` is every `Arg(secret=True)` of the catalogue by method; `public_args` leaves those out."""
    assert catalog.SECRET_PARAMS == {"setup_qobuz_login": frozenset({"password"})}
    assert catalog.public_args("setup_qobuz_login", {"email": "a@b.c", "password": "pw"}) == {"email": "a@b.c"}
    assert catalog.public_args("hide", {"track_id": "t1", "password": "kept"}) == {"track_id": "t1", "password": "kept"}
    assert catalog.public_args(None, {}) == {}


def test_a_job_holds_the_library_by_its_own_record_else_by_the_catalogue():
    assert catalog.holds_library({"method": "hide", "library_lock": True})  # a window hide: its `locks` is empty
    assert not catalog.holds_library({"method": "rescan_library", "library_lock": False})
    assert catalog.holds_library({"method": "rescan_library"})  # a record without the field: the `locks` column
    assert not catalog.holds_library({"method": "settings_view"}) and not catalog.holds_library({})


def test_add_bought_file_takes_the_files_path_after_the_track():
    (entry,) = catalog.by_method("add_bought_file")
    assert list(entry.params) == ["track_id", "path"] and entry.params["path"].positional and entry.params["path"].type == "str"


def test_duplicate_keep_with_a_file_id_runs_keep_file_and_all_runs_keep_duplicates():
    by_method = {m: catalog.by_method(m)[0] for m in ("keep_duplicates", "keep_file")}
    assert {e.command for e in by_method.values()} == {("duplicate", "keep")} and not catalog.by_method("supersede_duplicate")
    assert "supersede_duplicate" not in BRIDGE
    assert list(by_method["keep_file"].params) == ["group_id", "file_id", "paths"]
    assert by_method["keep_file"].params["file_id"].positional and by_method["keep_file"].params["paths"].resolve == "duplicate_paths"
    assert catalog.DISPATCH["duplicate keep"] == ("a file id as the second word runs keep_file, `--all` runs keep_duplicates")


def test_a_read_stands_in_for_a_write_that_is_planned_and_only_until_the_write_is_built(monkeypatch):
    stand = {e.method for e in catalog.ENTRIES if catalog.stands_in(e)}
    assert stand == {"tidy_preview", "limits_what_if", "check_music_folder", "undo_preview"}
    assert [c for c in (("tidy", "run"), ("limits", "set"), ("setup", "music"), ("batch", "undo"), ("sync", "run"),
                        ("limits", "show"), ("nothing", "here")) if catalog.dry_run_only(c)] == [
        ("tidy", "run"), ("limits", "set"), ("setup", "music")]  # `batch undo` has a built write (`batch_undo`)
    monkeypatch.setattr(catalog, "ENTRIES", tuple(replace(e, planned=None) if e.method == "tidy_up" else e
                                                  for e in catalog.ENTRIES))
    assert not catalog.dry_run_only(("tidy", "run")) and not catalog.stands_in(catalog.by_method("tidy_preview")[0])
    assert catalog.dry_run_only(("limits", "set"))  # the others keep standing in


def test_a_command_that_dispatches_by_id_kind_names_a_positional_and_a_rule():
    from discjockey.hub import ids
    assert set(catalog.BY_ID_KIND) <= set(catalog.DISPATCH)
    for command, (name, forms) in catalog.BY_ID_KIND.items():
        rows = [e for e in catalog.ENTRIES if " ".join(e.command) == command and name in e.params]
        assert len(rows) >= 2 and forms in ids.FORMS
        assert {e.params[name].resolve for e in rows if e.kind in ("J", "B")} == set(ids.FORMS[forms].replace(":N", "").split("|"))
