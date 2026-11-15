"""Group V1.10, part b (issue 39, design §7.3): which songs a listing selects (`discjockey/hub/select.py`,
`CliApi.select_listing`) and the selection forms of a bulk write in the call path (`<ids>`, `-`, `--all`, `--rows`: exactly
one of them). The bulk commands are not built yet (their groups come later), so the call path is tried through hand-made
entries whose methods are put on `CliApi` for the test, as `tests/test_cli_dryrun.py` does for the plan."""
from __future__ import annotations

import io
import json

import pytest
from batch_helpers import make_lib, needs_ffmpeg
from convert_helpers import EXACT
from hub_helpers import LOSSLESS, LOSSY, _MADE, Recorder, choose_music, make_root, services

from discjockey import align
from discjockey.cli import bind, call, parser
from discjockey.cli.parser import Flags, UsageError
from discjockey.hub import catalog, select
from discjockey.hub.api import CliApi, cli_first
from discjockey.hub.catalog import Entry
from discjockey.hub.ids import BadId

SEEN: list[list[str]] = []


def demo_bulk(self, track_ids: list[str], plan_id: str | None = None) -> dict:
    SEEN.append(list(track_ids))
    return {"done": list(track_ids)}


def bulk_entry(**kw) -> Entry:
    fields = dict(method="demo_bulk", command=("demo", "bulk"), kind="B", params={"track_ids": catalog.TRACKS})
    return Entry(**{**fields, **kw})


def cli_api(paths, **kw) -> CliApi:
    api = CliApi(paths.support, Recorder(), services(**kw))
    _MADE.append(api)  # conftest stops its jobs at teardown
    api._attach(paths)
    return api


@pytest.fixture
def lib(tmp_path, monkeypatch):
    monkeypatch.setattr(CliApi, "demo_bulk", cli_first(demo_bulk), raising=False)
    monkeypatch.setattr(CliApi, "_resolve_track", lambda self, text: text)  # the test's keys are not real song keys
    SEEN.clear()
    paths = make_root(tmp_path)
    choose_music(tmp_path, monkeypatch)
    return paths


def go(e: Entry, args: dict, api, **flags) -> dict:
    return call.run(e, args, Flags(**flags), api=api)


def rows_of(answer: dict) -> list[str]:
    return [r["track_id"] for r in (*answer["rows"], *(answer.get("also") or ())) if r["file_state"] != "no_file"]


# --- the words of a listing ---

@pytest.mark.parametrize("listing,reason", [
    ({"nope": 1}, "usage"), ("all", "usage"), ({"source": "sync"}, "usage"), ({"in": 3}, "usage"),
    ({"group": "upgrade_ready", "in": "all"}, "conflicting_flags"),   # a word of the other source is never ignored
    ({"source": "todo", "search": "x"}, "conflicting_flags"), ({"source": "library", "hidden": True}, "conflicting_flags"),
    ({"verb_all": "upgrade_all", "in": "all"}, "conflicting_flags"), ({"verb_all": "sing"}, "usage"),
    ({"group": "nowhere"}, "unknown_id"), ({"quality": "great"}, "unknown_id"), ({"in": "folder:"}, "unknown_id"),
    ({"hidden": "yes"}, "usage"),
])
def test_a_listing_that_means_nothing_is_bad_args(listing, reason):
    with pytest.raises(BadId) as e:
        select.parse(listing)
    assert e.value.reason == reason


def test_a_listing_is_read_as_the_source_it_names():
    assert select.parse({}) == select.Listing("library")
    assert select.parse({"in": "unlisted", "search": "x", "quality": "weak"}) == select.Listing(
        "library", view="unlisted", search="x", quality="weak")
    assert select.parse({"in": "playlist:Hard_Bounce"}).view == "playlist"
    assert select.parse({"in": "/Music/Crate"}) == select.Listing("library", view="folder", key="/Music/Crate")
    assert select.parse({"group": "weak", "hidden": True}) == select.Listing("todo", group="weak", hidden=True)
    assert select.parse({"verb_all": "check_done"}).verb_all == "check_done"


def test_a_playlist_song_without_a_file_is_no_song_to_act_on():
    answer = {"rows": [{"track_id": "a", "file_state": "here"}, {"track_id": "w", "file_state": "no_file"}],
              "also": [{"track_id": "b", "file_state": "offline"}, {"track_id": "a", "file_state": "here"}]}
    assert select.library_ids(answer) == ["a", "b"]
    assert select.library_ids({"rows": [], "also": None}) == []


def test_a_todo_answer_gives_songs_once_a_batch_its_tracks_and_a_question_none():
    def item(key, **kw):
        return {"track_id": key, **kw}
    answer = {"groups": [
        {"key": "rekordbox_check", "items": [item("batch:3", batch={"tracks": [item("a"), item("b")]}), item("c")]},
        {"key": "same_song", "items": [item("q", pair={})]},
        {"key": "upgrade_ready", "items": [item("a", same_track=None), item("d", same_track="needs_choice"),
                                           item("e", same_track=None)]},
    ]}
    assert select.todo_ids(answer) == ["a", "b", "c", "d", "e"]
    assert select.upgrade_all_ids(answer) == ["a", "e"]
    assert select.check_done_ids(answer) == ["a", "b", "c"]


# --- --rows is what the screen shows ---

def test_rows_of_a_folder_are_the_rows_library_list_shows_for_it(lib):
    api = cli_api(lib)
    shown = api.library("folder", "Library/Hard_Bounce")
    assert rows_of(shown) and len(rows_of(shown)) == 2
    for typed in ("folder:Library/Hard_Bounce", f"folder:{lib.root / 'Library' / 'Hard_Bounce'}",
                  f"folder:{lib.root}/Library/Hard_Bounce"):
        assert api.select_listing({"in": typed}) == {"ok": True, "ids": rows_of(shown)}


def test_rows_follow_the_search_and_the_quality_filter(lib):
    api = cli_api(lib)
    every = api.select_listing({})["ids"]
    assert sorted(every) == ["t1", "t2"]  # t3 has no file
    assert api.select_listing({"search": "naughty"})["ids"] == rows_of(api.library("all", None, "naughty"))
    assert api.select_listing({"search": "naughty"})["ids"] == ["t2"]
    assert api.select_listing({"search": "zzz"})["ids"] == []
    for quality in ("lossless", "weak", "all"):
        assert api.select_listing({"quality": quality})["ids"] == rows_of(api.library("all", None, "", quality))
    assert api.select_listing({"in": "unlisted"})["ids"] == rows_of(api.library("unlisted"))


def test_rows_of_a_playlist_hold_the_also_rows(lib):
    api = cli_api(lib)
    shown = api.library("playlist", "Hard_Bounce")  # no read yet: the files of its folder are its `also` rows
    assert shown["also"] and not shown["rows"]
    ids = api.select_listing({"in": "playlist:Hard_Bounce"})["ids"]
    assert ids == rows_of(shown) == [r["track_id"] for r in shown["also"]]
    assert api.select_listing({"in": "playlist:Nowhere"})["ids"] == []  # the view says `gone`, as `library list` does


def test_a_folder_that_is_not_in_the_library_selects_nothing(lib):
    assert cli_api(lib).select_listing({"in": "folder:Library/Nowhere"}) == {"ok": True, "ids": []}


def test_todo_rows_are_the_items_todo_list_shows(lib):
    api = cli_api(lib)
    shown = api.todo("all")
    expected = list(dict.fromkeys(i["track_id"] for g in shown["groups"] for i in g["items"] if "pair" not in i))
    assert expected and api.select_listing({"group": "all"})["ids"] == expected
    for g in shown["groups"]:
        assert api.select_listing({"group": g["key"]})["ids"] == [i["track_id"] for i in g["items"]]
    assert api.select_listing({"group": "other"}) == {"ok": True, "ids": []}


def test_a_bad_listing_is_a_problem_answer_not_a_crash(lib):
    r = cli_api(lib).select_listing({"group": "nowhere"})
    assert (r["ok"], r["kind"], r["reason"]) == (False, "bad_args", "unknown_id")
    assert cli_api(lib).select_listing("all")["reason"] == "usage"


def test_select_listing_leaves_the_window_s_select_alone(lib):
    api = cli_api(lib)
    assert api.select("t2") == {"ok": True} and api._selected == "t2"
    assert api.select_listing({})["ids"]


# --- the verb's own "all": the Upgrade all set ---

@needs_ffmpeg
def test_upgrade_all_is_the_group_s_same_track_none_set_and_the_dry_run_agrees(tmp_path, monkeypatch):
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "stale", "aiff", "mp3_plain"])
    monkeypatch.setattr(align, "compare_files", lambda a, b: EXACT)
    choose_music(tmp_path, monkeypatch)
    api = cli_api(lib.paths, compare=lambda a, b: EXACT, rekordbox_running=lambda: False,
                  rekordbox_place=lambda: lib.place)
    group = next(g for g in api.todo("upgrade_ready")["groups"])
    wanted = [i["track_id"] for i in group["items"] if i["same_track"] is None]
    assert len(wanted) == group["all"]["n"] and lib.tracks[1] not in wanted  # `stale` needs a choice
    assert api.select_listing({"verb_all": "upgrade_all"})["ids"] == wanted
    assert [i["key"] for i in api.upgrade_preview(all=True)["items"]] == wanted


# --- the call path: exactly one of ids / --all / --rows, and `-` ---

def test_the_ids_typed_go_to_the_method_as_they_are(lib):
    env = go(bulk_entry(), {"track_ids": ["t1", "t2"]}, cli_api(lib))
    assert env["outcome"] == "ok" and SEEN == [["t1", "t2"]]


def test_rows_binds_the_ids_the_listing_shows(lib):
    api = cli_api(lib)
    env = go(bulk_entry(), {}, api, rows=True, where="folder:Library/Hard_Bounce")
    assert env["outcome"] == "ok" and SEEN == [rows_of(api.library("folder", "Library/Hard_Bounce"))]
    SEEN.clear()
    go(bulk_entry(), {}, api, rows=True, search="naughty", quality="weak")
    assert SEEN == [rows_of(api.library("all", None, "naughty", "weak"))]
    SEEN.clear()
    go(bulk_entry(), {}, api, rows=True, todo="all")
    assert SEEN == [api.select_listing({"group": "all"})["ids"]]
    SEEN.clear()
    go(bulk_entry(), {}, api, rows=True)  # no narrowing: every row of the Library
    assert SEEN == [api.select_listing({})["ids"]]


def test_all_is_the_verb_s_own_all_where_the_catalogue_names_it(lib, monkeypatch):
    api = cli_api(lib)
    env = go(bulk_entry(), {}, api, all=True)
    assert (env["outcome"], env["reason"]) == ("bad_args", "usage") and "no --all" in env["message"] and SEEN == []
    monkeypatch.setitem(catalog.ALL_OF, "demo bulk", "check_done")
    env = go(bulk_entry(), {}, api, all=True)
    assert env["outcome"] == "ok" and SEEN == [api.select_listing({"verb_all": "check_done"})["ids"]]
    env = go(bulk_entry(), {}, api, all=True, search="x")  # --all is the verb's list: nothing narrows it
    assert env["reason"] == "conflicting_flags"


@pytest.mark.parametrize("args,flags", [
    ({"track_ids": ["t1"]}, {"all": True}), ({"track_ids": ["t1"]}, {"rows": True}), ({}, {"all": True, "rows": True}),
    ({"track_ids": ["t1"]}, {"all": True, "rows": True}),
])
def test_exactly_one_of_ids_all_and_rows(lib, monkeypatch, args, flags):
    monkeypatch.setitem(catalog.ALL_OF, "demo bulk", "check_done")
    env = go(bulk_entry(), args, cli_api(lib), **flags)
    assert (env["outcome"], env["reason"]) == ("bad_args", "conflicting_flags") and SEEN == []


def test_no_form_at_all_is_a_usage_error(lib):
    env = go(bulk_entry(), {}, cli_api(lib))
    assert (env["outcome"], env["reason"]) == ("bad_args", "usage") and "Say which songs" in env["message"]
    assert go(bulk_entry(), {"track_ids": []}, cli_api(lib))["reason"] == "usage"


@pytest.mark.parametrize("flags", [{"where": "all"}, {"search": "x"}, {"quality": "weak"}, {"todo": "weak"}])
def test_a_narrowing_word_without_rows_is_conflicting_flags(lib, flags):
    env = go(bulk_entry(), {"track_ids": ["t1"]}, cli_api(lib), **flags)
    assert env["reason"] == "conflicting_flags" and SEEN == []


def test_in_and_todo_name_two_lists_and_search_is_the_library_s(lib):
    for flags in ({"where": "all", "todo": "weak"}, {"todo": "weak", "search": "x"}):
        env = go(bulk_entry(), {}, cli_api(lib), rows=True, **flags)
        assert env["reason"] == "conflicting_flags" and SEEN == []


def test_a_listing_the_engine_refuses_is_the_answer(lib):
    env = go(bulk_entry(), {}, cli_api(lib), rows=True, todo="nowhere")
    assert (env["outcome"], env["reason"]) == ("bad_args", "unknown_id") and SEEN == []


def test_a_selection_that_picks_nothing_still_reaches_the_method(lib):
    go(bulk_entry(), {}, cli_api(lib), rows=True, search="zzz")
    assert SEEN == [[]]  # the method says what an empty list means for it


def test_a_command_without_songs_takes_no_selection_words(lib, monkeypatch):
    monkeypatch.setattr(CliApi, "demo_none", cli_first(lambda self: {}), raising=False)
    env = go(Entry(method="demo_none", command=("demo", "none"), kind="B"), {}, cli_api(lib), rows=True)
    assert env["reason"] == "usage" and "no selection words" in env["message"]


# --- `-` reads the ids from standard input ---

def stdin(monkeypatch, text: str) -> None:
    monkeypatch.setattr("sys.stdin", io.StringIO(text))


def test_a_dash_reads_ids_one_per_line_or_as_a_json_array(lib, monkeypatch):
    track = lambda self, text: text  # noqa: E731
    monkeypatch.setattr(CliApi, "_resolve_track", track)
    api = cli_api(lib)
    stdin(monkeypatch, "t1\n\n  t2  \n")
    assert go(bulk_entry(), {"track_ids": ["-"]}, api)["outcome"] == "ok"
    stdin(monkeypatch, json.dumps(["t2", "t1"]))
    assert go(bulk_entry(), {"track_ids": ["-"]}, api)["outcome"] == "ok"
    stdin(monkeypatch, '[\n "t1",\n "t2"\n]\n')
    go(bulk_entry(), {"track_ids": ["-"]}, api)
    assert SEEN == [["t1", "t2"], ["t2", "t1"], ["t1", "t2"]]


@pytest.mark.parametrize("text", ["", "  \n", "[1, 2]", "[\"a\", \"\"]", "[\"a\""])
def test_a_dash_with_no_ids_on_stdin_is_a_usage_error(lib, monkeypatch, text):
    monkeypatch.setattr(CliApi, "_resolve_track", lambda self, t: t)
    stdin(monkeypatch, text)
    env = go(bulk_entry(), {"track_ids": ["-"]}, cli_api(lib))
    assert (env["outcome"], env["reason"]) == ("bad_args", "usage") and SEEN == []


# --- the parser offers the words where a command takes songs ---

@pytest.fixture
def built_bulk(monkeypatch):
    monkeypatch.setattr(CliApi, "demo_bulk", cli_first(demo_bulk), raising=False)
    entry = bulk_entry(planned=None, kind="J")
    monkeypatch.setattr(catalog, "ENTRIES", (*catalog.ENTRIES, entry))
    return entry


def test_the_parser_reads_the_selection_words_into_the_flags(built_bulk):
    parsed = parser.parse(["demo", "bulk", "--rows", "--in", "folder:Library/X", "--search", "love", "--quality", "weak"])
    f = parsed.flags
    assert (f.rows, f.where, f.search, f.quality, f.all, f.todo) == (True, "folder:Library/X", "love", "weak", False, None)
    assert "track_ids" not in parsed.args  # --rows says which songs: no ids needed
    assert parser.parse(["demo", "bulk", "--rows", "--todo", "weak"]).flags.todo == "weak"
    assert parser.parse(["demo", "bulk", "t1", "t2"]).args["track_ids"] == ["t1", "t2"]
    assert parser.parse(["demo", "bulk", "-"]).args["track_ids"] == ["-"]
    with pytest.raises(UsageError):
        parser.parse(["demo", "bulk"])  # no ids and no selection word: the song ids are missing


def test_the_parser_offers_all_only_where_the_catalogue_names_the_verb_s_all(built_bulk, monkeypatch):
    with pytest.raises(UsageError):
        parser.parse(["demo", "bulk", "--all"])
    monkeypatch.setitem(catalog.ALL_OF, "demo bulk", "check_done")
    assert parser.parse(["demo", "bulk", "--all"]).flags.all is True


def test_a_read_has_no_selection_words():
    with pytest.raises(UsageError):
        parser.parse(["todo", "list", "--rows"])


def test_help_lists_the_selection_words_of_a_command_that_takes_songs(built_bulk, monkeypatch):
    from discjockey.cli import housekeeping
    monkeypatch.setitem(catalog.ALL_OF, "demo bulk", "check_done")
    row = housekeeping.index_entry(("demo", "bulk"), [built_bulk])
    assert row["flags"] == ["--all", "--rows", "--in", "--todo", "--search", "--quality"]
    assert "[--rows]" in row["usage"]
    monkeypatch.delitem(catalog.ALL_OF, "demo bulk")
    assert "--all" not in housekeeping.index_entry(("demo", "bulk"), [built_bulk])["flags"]
    read = housekeeping.index_entry(("todo", "list"), [e for e in catalog.ENTRIES if e.command == ("todo", "list")])
    assert not {"--rows", "--all"} & set(read["flags"])
