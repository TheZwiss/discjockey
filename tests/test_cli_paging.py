"""JSON paging and `--since` through the command line (issue 39 phase 3): `report list` is paged by `runs`, `--since`
resolves through `HubApi.resolve`; the pages of a read without `pages` are whole (tests/test_cli_reads.py)."""
import json

import pytest
from hub_helpers import choose_music, make_root
from test_cli_batches import with_report

import discjockey.cli as cli
from discjockey import words

STAMPS = ("2026-11-08_090000", "2026-11-09_100000", "2026-11-10_110000")  # three runs, newest 11-10


@pytest.fixture
def reports(tmp_path, monkeypatch):
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    for stamp in STAMPS:
        with_report(paths, stamp)
    return paths


def run_json(argv, capsys):
    code = cli.main([*argv, "--json"])
    return code, json.loads(capsys.readouterr().out)


def ids(env):
    return [r["run_id"] for r in env["data"]["runs"]]


def test_a_page_of_runs_says_which_slice_it_is(reports, capsys):
    code, env = run_json(["report", "list", "--limit", "1"], capsys)
    assert code == 0 and ids(env) == [STAMPS[2]]
    assert env["page"] == {"list": "runs", "offset": 0, "limit": 1, "total": 3, "next_offset": 1}
    _, env = run_json(["report", "list", "--limit", "1", "--offset", "2"], capsys)
    assert ids(env) == [STAMPS[0]] and env["page"]["next_offset"] is None
    _, env = run_json(["report", "list", "--offset", "9"], capsys)
    assert ids(env) == [] and env["page"] == {"list": "runs", "offset": 9, "limit": 200, "total": 3, "next_offset": None}
    _, env = run_json(["report", "list", "--limit", "0"], capsys)
    assert ids(env) == list(reversed(STAMPS)) and env["page"]["limit"] == 0 and env["page"]["next_offset"] is None


def test_the_text_page_keeps_its_own_count_line_and_the_json_page_leaves_the_text_alone(reports, capsys):
    assert cli.main(["report", "list", "--limit", "1"]) == 0
    assert "1 of 3 shown" in capsys.readouterr().out


def test_a_usage_error_and_a_problem_have_a_null_page(reports, capsys):
    code, env = run_json(["report", "list", "--since", "soon"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "usage") and env["page"] is None
    assert env["message"] == words.BAD_SINCE.format(text="soon")
    code, env = run_json(["report", "show", "report:nope"], capsys)
    assert code == 2 and env["page"] is None


def test_call_answers_what_the_bridge_answers_with_no_page(reports, capsys):
    code, env = run_json(["call", "runs"], capsys)
    assert code == 0 and env["page"] is None and ids(env) == list(reversed(STAMPS))


def test_since_keeps_the_runs_from_that_time_on(reports, capsys):
    _, env = run_json(["report", "list", "--since", "2000-01-01"], capsys)
    assert ids(env) == list(reversed(STAMPS))
    _, env = run_json(["report", "list", "--since", "2026-11-09"], capsys)
    assert ids(env) == [STAMPS[2], STAMPS[1]]
    _, env = run_json(["report", "list", "--since", "2026-11-10T11:00:01"], capsys)
    assert ids(env) == [] and env["data"] == {"runs": []}
    _, env = run_json(["report", "list", "--since", "1h"], capsys)  # the fixtures' dates are long ago
    assert ids(env) == []


def test_since_paged_counts_only_the_runs_it_kept(reports, capsys):
    _, env = run_json(["report", "list", "--since", "2026-11-09", "--limit", "1"], capsys)
    assert ids(env) == [STAMPS[2]] and env["page"]["total"] == 2 and env["page"]["next_offset"] == 1
