"""Commands whose write is phase 4's and whose dry run is a read (issue 39 phase 3, V3.1b): `tidy run`, `limits set`,
`setup music` can only be tried (`--dry-run`) until their write is built, and `batch undo moves:<n>` is tried while
`batch undo aiff:<n>` already runs. The page of each is `tests/cli_golden/<command>.txt` (tests/test_cli_golden.py)."""
import json
from dataclasses import replace

import pytest
from hub_helpers import choose_music, make_root

import discjockey.cli as cli
from discjockey.cli import bind, housekeeping, parser
from discjockey.hub import catalog
from discjockey.hub.catalog import Entry
from test_cli_batches import with_batches


@pytest.fixture
def lib(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


def run_json(argv, capsys):
    code = cli.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


ONLY = (["tidy", "run"], ["limits", "set", "qobuz", "40"], ["setup", "music", "/Music/Discjockey"])


@pytest.mark.parametrize("argv", ONLY, ids=lambda a: " ".join(a[:2]))
def test_without_dry_run_the_command_says_it_can_only_be_tried(lib, argv, capsys):
    code, env = run_json(argv, capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "usage")
    assert env["message"] == parser.DRY_RUN_ONLY_WORDS.format(command=" ".join(argv[:2]))
    assert "--dry-run" in env["message"]


@pytest.mark.parametrize("argv", ONLY, ids=lambda a: " ".join(a[:2]))
def test_help_prints_dry_run_without_brackets_and_names_the_read_that_answers_it(argv, capsys):
    code, env = run_json(["help", *argv[:2]], capsys)
    (data,) = env["data"]["commands"]
    assert code == 0 and "--dry-run" in data["flags"] and data["required_flags"] == ["--dry-run"]
    assert " --dry-run" in data["usage"] and "[--dry-run]" not in data["usage"]
    assert data["dry_run"] is True and data["dry_run_method"] == data["methods"][0] and not data["writes"]


def test_a_dry_run_only_command_answers_its_read_as_data_and_no_plan(lib, capsys):
    api = bind.default()
    for argv, method, args in ((["tidy", "run"], "tidy_preview", ()), (["limits", "set", "qobuz", "40"], "limits_what_if", ("qobuz", 40))):
        code, env = run_json([*argv, "--dry-run"], capsys)
        answer = getattr(api, method)(*args)
        assert code == 0 and env["outcome"] == "ok"
        assert env["data"] == {k: v for k, v in answer.items() if k != "ok"} and "plan_id" not in env["data"]
        assert env["next"] == [] and env["as_of"] is not None


def test_a_what_if_takes_the_extra_for_today(lib, capsys):
    api = bind.default()
    code, env = run_json(["limits", "set", "qobuz", "40", "--extra-today", "5", "--dry-run"], capsys)
    assert code == 0 and env["data"]["extra_today"] == 5
    assert env["data"] == {k: v for k, v in api.limits_what_if("qobuz", 40, 5).items() if k != "ok"}


def test_a_dry_run_only_command_refuses_the_job_flags_and_yes(lib, capsys):
    code, env = run_json(["tidy", "run", "--dry-run", "--detach"], capsys)
    assert code == 2 and env["reason"] == "usage"
    code, env = run_json(["tidy", "run", "--dry-run", "--yes"], capsys)
    assert code == 2  # `--yes` is for a command that writes: this one does not take it


def test_a_command_stops_being_dry_run_only_when_its_write_is_built(monkeypatch):
    assert parser.extra_flags(parser.commands()[("tidy", "run")]) == ["--dry-run", "--limit", "--offset"]
    built = tuple(replace(e, planned=None, kind="B") if e.method == "tidy_up" else e for e in catalog.ENTRIES)
    monkeypatch.setattr(catalog, "ENTRIES", built)
    entries = parser.commands()[("tidy", "run")]
    assert not catalog.dry_run_only(("tidy", "run")) and catalog.primary(entries).method == "tidy_up"
    assert housekeeping.index_entry(("tidy", "run"), entries)["required_flags"] == []
    assert "--dry-run" in parser.extra_flags(entries)  # the write answers its own dry run now
    with pytest.raises(parser.UsageError) as refused:  # the write's own words now (it needs the moves), not "say --dry-run"
        parser.parse(["tidy", "run"])
    assert refused.value.message != parser.DRY_RUN_ONLY_WORDS.format(command="tidy run")


def test_call_takes_a_stand_in_as_a_read_and_refuses_a_dry_run_of_a_read_with_no_write(lib, capsys):
    code, env = run_json(["call", "tidy_preview", "--dry-run"], capsys)
    assert code == 0 and env["data"]["empty"]  # the stand-in is its own dry run
    code, env = run_json(["call", "library", "--args", "{}", "--dry-run"], capsys)
    assert code == 2 and "has no --dry-run" in env["message"]
