"""T1, catalogue <-> bridge (issue 39, design §13): every @bridge method of HubApi has an entry, every entry names a
method, every parameter has a word, window-only and dropped rows are what the design says."""
import inspect
import typing
from dataclasses import replace

import pytest

from discjockey.hub import catalog
from discjockey.hub.api import CliApi, HubApi
from discjockey.hub.catalog import Arg, Entry

# The phase 1 ceiling: how many entries may still be `planned` (their command not built). Every group that builds a
# command lowers the number; nothing may raise it. 1.1 plans them all; 1.2 builds `rekordbox status` and `resolve`; 1.3 builds `freshness`; 1.8 builds `track show`, `todo list`, `upgrade list`,
# `check list` and `track find`; 1.9 builds `rekordbox preview`, `batch list`, `batch show`, `report show`
# and takes `move_batches` out of the plan (it has no command: `batches` is `batch list`); 1.10 builds the two methods
# its dry runs and selections need (`select_listing`, `upgrade_preview`: no command of their own); 1.11 builds `upgrade apply`
# and `upgrade_all` (part a), `upgrade discard`, `track undo` and `check done` (part b) and `undo_upgrade_preview`;
# 1.12 builds `batch resume`, `batch undo aiff:<n>` and `batch_undo_preview` (the moves forms are phase 4's), then (part b)
# `rekordbox backups`, `rekordbox restore` and `rekordbox_restore_preview`; 1.13 part a builds `library facts` (and its
# read, `facts_preview`), part b `aiff convert` and `aiff rename` (`convert`, `rename`, `make_aiff` and the two `aiff_plan`
# reads that are their dry runs); 1.14 part a builds `sync run --auto-upgrade-only` (`auto_upgrade_run` and its dry run
# `auto_upgrade_preview`; `start_sync`'s own `sync run` row stays planned for phase 4), part b `folder add`, `folder remove`
# (`add_watched_folder`, `remove_watched_folder`, and `removal_preview`, which is its dry run: no command of its own),
# `settings show` (`settings_view`) and `settings set auto-upgrade` (`set_auto_upgrade`).
PHASE_1_CEILING = 83  # 80 + the planned `login check <service>` row (`setup_account` with the saved browser: U2) + issue 43's `missing download` / `missing remove` rows (E3b2 builds them)

CLI_FIRST = {"freshness", "resolve", "find_tracks", "rekordbox_preview", "batches", "batch_detail", "select_listing",
             "upgrade_preview", "undo_upgrade_preview", "batch_undo_preview", "result_words", "fill_facts", "facts_preview", "auto_upgrade_preview", "auto_upgrade_run", "settings_view",
             "rekordbox_backups", "rekordbox_restore", "rekordbox_restore_preview"}


def bridge_methods() -> dict[str, inspect.Signature]:
    return {name: inspect.signature(fn.__wrapped__) for name, fn in vars(HubApi).items()
            if getattr(fn, "is_bridge", False)}


BRIDGE = bridge_methods()
EXISTING = [e for e in catalog.ENTRIES if not e.cli_first]


def test_the_bridge_has_97_methods_and_each_has_an_entry():
    assert len(BRIDGE) == 97
    assert set(BRIDGE) == {e.method for e in EXISTING}


def test_an_entry_names_no_method_the_bridge_lacks():
    for e in EXISTING:
        assert e.method in BRIDGE, e
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
        assert e.schema is None  # phase 2 fills it


def test_the_entries_are_well_formed():
    seen = set()
    for e in catalog.ENTRIES:
        assert e.kind in ("R", "RJ", "J", "J-control", "B", "W", "dropped"), e
        key = (e.method, e.command, e.cli_first, tuple(sorted(e.fixed.items(), key=str)))
        assert key not in seen, e
        seen.add(key)
        assert e.planned is None or e.planned.startswith("phase "), e
    assert {("help",), ("where",), ("app", "open"), ("call",)} <= set(catalog.HOUSEKEEPING)


def test_the_planned_count_only_shrinks():
    planned = [e for e in catalog.ENTRIES if e.planned]
    assert len(planned) <= PHASE_1_CEILING, f"{len(planned)} planned entries"


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
