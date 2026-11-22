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


# --- library list: the paged read the fixture's two songs make; `--in` is `view` and `key` (the spread of `call._arguments`)

@pytest.fixture
def songs(tmp_path, monkeypatch):
    """The three-song hub fixture: two songs have a file (the Library lists those), the third's is missing."""
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


def keys(env):
    return [r["track_id"] for r in env["data"]["rows"]]


def test_library_list_pages_its_rows(songs, capsys):
    _, env = run_json(["library", "list"], capsys)
    whole = keys(env)
    assert len(whole) == 2 and env["page"] == {"list": "rows", "offset": 0, "limit": 200, "total": 2, "next_offset": None}
    _, env = run_json(["library", "list", "--limit", "1"], capsys)
    assert keys(env) == whole[:1]
    assert env["page"] == {"list": "rows", "offset": 0, "limit": 1, "total": 2, "next_offset": 1}
    assert env["data"]["summary"]["tracks"] == 2  # every other field is the whole answer's
    _, env = run_json(["library", "list", "--offset", "1", "--limit", "1"], capsys)
    assert keys(env) == whole[1:] and env["page"]["next_offset"] is None
    _, env = run_json(["library", "list", "--offset", "9"], capsys)
    assert keys(env) == [] and env["page"]["total"] == 2 and env["page"]["next_offset"] is None
    _, env = run_json(["library", "list", "--limit", "0"], capsys)
    assert keys(env) == whole and env["page"]["limit"] == 0


def test_library_list_text_keeps_its_count_line(songs, capsys):
    assert cli.main(["library", "list", "--limit", "1"]) == 0
    assert "1 of 2 shown" in capsys.readouterr().out


def test_in_is_the_views_and_the_key_it_names(songs, capsys):
    from discjockey.cli import bind
    for typed, view, key in (("all", "all", None), ("unlisted", "unlisted", None), ("playlist:hard_bounce", "playlist", "Hard_Bounce"),
                             ("Hard_Bounce", "playlist", "Hard_Bounce")):
        code, env = run_json(["library", "list", "--in", typed], capsys)
        answer = bind.default().library(view, key)
        assert code == 0 and env["data"] == {k: v for k, v in answer.items() if k != "ok"}, typed
        assert (env["data"]["view"], env["data"]["key"]) == (view, key), typed
    code, env = run_json(["library", "list", "--in", "nope"], capsys)
    assert code == 2 and (env["outcome"], env["reason"]) == ("bad_args", "unknown_id") and env["page"] is None


def test_search_and_quality_narrow_the_rows(songs, capsys):
    _, env = run_json(["library", "list", "--search", "vatoz", "--quality", "lossless"], capsys)
    assert keys(env) == ["t1"] and env["page"]["total"] == 1
    _, env = run_json(["library", "list", "--search", "vatoz", "--quality", "weak"], capsys)
    assert keys(env) == []


def test_the_spread_sets_the_derived_argument_and_resolves_it_once(songs):
    from discjockey.cli import bind, call, parser
    from discjockey.hub import catalog
    entry = catalog.entry_of("library", "library list")
    parsed = parser.parse(["library", "list", "--in", "playlist:Hard_Bounce", "--search", "x"])
    kwargs, failed = call._arguments(entry, parsed.args, "library list", bind.default(), exact=False)
    assert failed is None and kwargs == {"view": "playlist", "key": "Hard_Bounce", "query": "x"}
    kwargs, _ = call._arguments(entry, {"view": "all"}, "library list", bind.default(), exact=False)
    assert kwargs == {"view": "all", "key": None}
    kwargs, _ = call._arguments(entry, {"query": "x"}, "library list", bind.default(), exact=False)
    assert kwargs == {"query": "x"}  # no --in: the method's own defaults
    kwargs, _ = call._arguments(entry, {"view": "playlist", "key": "k"}, "call", bind.default(), exact=True)
    assert kwargs == {"view": "playlist", "key": "k"}  # `call` sends the bridge's own arguments, nothing resolved


def test_sync_plan_search_narrows_the_actions_and_keeps_the_plan_whole(songs, capsys):
    from hub_helpers import ID1, ID2, TRACKS, store_sync_read

    from discjockey.models import FetchedPlaylist, PlaylistLine
    store_sync_read(songs, [FetchedPlaylist(PlaylistLine("Hard_Bounce", ID1, 2), TRACKS[ID1], []),
                            FetchedPlaylist(PlaylistLine("Powertrance", ID2, 3), TRACKS[ID2], [])])
    _, whole = run_json(["sync", "plan"], capsys)
    code, found = run_json(["sync", "plan", "--search", "PEGASSI"], capsys)
    assert code == 0 and found["page"] is None  # `groups` is the plan's own structure, not a list the command pages
    assert [a["title"] for g in found["data"]["groups"] for a in g["actions"]] == ["AEIOU"]
    assert found["data"]["search"] == "PEGASSI" and whole["data"]["search"] is None
    assert found["data"]["plan_id"] == whole["data"]["plan_id"] and found["data"]["counts"] == whole["data"]["counts"]
    _, none = run_json(["sync", "plan", "--search", "zzz"], capsys)
    assert none["data"]["groups"] == [] and none["data"]["counts"] == whole["data"]["counts"]
