"""Issue 43 E3a: the read shapes of a missing file: To-do's `missing_file` group and item, `track()`'s `missing`, the
Library rows' `file_state`, and the `views` rows of plan §3 (`_group`, `todo_listed`, `upgrade_ready_keys`,
`file_state`, `next_due`)."""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from hub_helpers import LOSSLESS, fake_spotify, make_api, make_root, write_state
from test_missing_rules import PARKED, SINCE, TODAY, e, gone, own, place, state

from discjockey import db, missing
from discjockey.hub import views
from discjockey.library import load_state


def group(out, key="missing_file"):
    return next((g for g in out["groups"] if g["key"] == key), None)


# --- the views rows of plan §3 ---

@pytest.mark.parametrize("entry,expected", [
    (gone(), "missing_file"),
    (gone(status="not_lossless", cutoff_hz=16000), "missing_file"),                  # over Weak
    (gone(status="fake_lossless", cutoff_hz=16000), "missing_file"),
    (gone(upgrade=PARKED), "missing_file"),                                          # over Upgrade ready
    (gone(import_state="identified"), "missing_file"),                              # over "sound not checked"
    (gone(file_gone="2026-11-18"), None),                                           # asked: it leaves To-do
    (e("missing", path=None, file_gone="2026-11-18"), None),                        # no file row, asked (folder remove)
    (e("missing", path=None), "not_found"),
    (e("not_lossless", cutoff_hz=16000, upgrade=PARKED), "upgrade_ready"),
    (e(), None),
])
def test_group_puts_a_missing_file_first_and_a_download_asked_nowhere(entry, expected):
    assert views._group(entry) == expected


def test_todo_lists_a_missing_song_whoever_it_belongs_to():
    assert views.todo_listed("t1", gone(), set(), {}) is True
    assert views.todo_listed("local:1", own(), set(), {}) is True                   # own, no parked upgrade
    assert views.todo_listed("t2", gone(in_playlists=False), set(), {}) is True     # a playlist song no playlist lists
    assert views.todo_listed("local:1", own(missing_since=None), set(), {}) is False
    assert views.todo_listed("t1", gone(), {"t1"}, {}) is False                     # a question still comes first


def test_upgrade_all_leaves_a_missing_song_out_and_its_parked_upgrade_stays():
    up = e("not_lossless", cutoff_hz=16000, upgrade=PARKED)
    st = state(a=up, b=gone(status="not_lossless", cutoff_hz=16000, upgrade=PARKED))
    assert views.upgrade_ready_keys(st) == ["a"]
    assert st["tracks"]["b"]["upgrade"] == PARKED


@pytest.mark.parametrize("entry,away,exists,expected", [
    (gone(), None, True, "file_missing"),                                           # the stored mark, no disk check
    (e(), None, True, "here"),
    (e(), None, False, "file_missing"),                                             # the live check, as before
    (gone(online=False), None, True, "offline"),                                    # offline wins: its drive can't tell
    (own(), {"/Volumes/Example/Music": "unmounted"}, True, "offline"),
    (own(), {"/Volumes/Example/Music": "missing"}, True, "folder_missing"),
    (e("missing", path=None, missing_since=None), None, True, "here"),               # no file: nothing to be away
])
def test_file_state_knows_a_marked_row(entry, away, exists, expected):
    assert views.file_state(entry, away, exists) == expected


def test_a_song_after_download_again_is_downloaded_at_the_next_sync():
    assert views.next_due(gone(file_gone="2026-11-18")) == "next_sync"
    assert views.next_check(gone(file_gone="2026-11-18"), TODAY) == "next_sync"
    # lossless, parked or its retry in the future: Download again still says the next sync
    assert views.next_due(gone(upgrade=PARKED, file_gone="2026-11-18")) == "next_sync"
    assert views.next_due(e("missing", path=None, file_gone="2026-11-18", last_attempt="2026-11-17")) == "next_sync"
    assert views.next_due(gone()) is None                                           # lossless: never looked again
    assert views.next_due(e("missing", path=None, last_attempt="2026-11-17")) == "2026-11-24"
    assert views.next_due(gone(in_playlists=False, file_gone="2026-11-18")) is None


def test_a_song_with_no_file_row_after_folder_remove_waits_in_its_playlist_instead_of_not_found():
    from test_hub_views import playlist_state, playlist_view
    st = playlist_state()
    assert {r["track_id"]: r["wait"] for r in playlist_view(st)["rows"]}["g"] == "not_found"
    st["tracks"]["g"]["file_gone"] = "2026-11-18"
    row = {r["track_id"]: r for r in playlist_view(st)["rows"]}["g"]
    assert (row["wait"], row["next_try"]) == ("waiting", None)
    assert views.todo(st, "all", False, {}, TODAY)["chips"]["not_found"] == 0


# --- To-do ---

def test_the_missing_files_group_is_second_with_its_label_and_hint():
    st = state(a=gone(title="B Song"), b=own(title="A Song"), c=e("not_lossless", cutoff_hz=16000, upgrade=PARKED))
    st["tracks"]["r"] = e(rekordbox_check={"reason": "swapped", "since": "2026-11-10"}, title="C")
    out = views.todo(st, "all", False, {}, TODAY, place=place)
    assert [g["key"] for g in out["groups"]] == ["rekordbox_check", "missing_file", "upgrade_ready"]
    g = group(out)
    assert (g["label"], g["hint"]) == ("Missing files", "not where they were; put a file back and it links again")
    assert [i["track_id"] for i in g["items"]] == ["b", "a"] or [i["title"] for i in g["items"]] == ["A Song", "B Song"]
    assert out["chips"]["missing_file"] == 2 and out["chips"]["all"] == 4
    assert views.TODO_GROUP_KEYS[:2] == ("rekordbox_check", "missing_file")


def test_a_missing_item_is_a_row_with_its_line_its_file_state_and_its_missing_object():
    st = state(a=gone(), b=own(), c=gone(upgrade=PARKED, status="not_lossless", cutoff_hz=16000))
    items = {i["track_id"]: i for i in group(views.todo(st, "all", False, {}, TODAY, place=place))["items"]}
    a = items["a"]
    assert a["group"] == "missing_file" and a["file_state"] == "file_missing" and a["free"] is False
    assert a["detail"] == "Missing since 12 Nov · was in Techno 2019"
    assert a["missing"] == missing.view("a", st["tracks"]["a"], st, place, TODAY)
    assert items["b"]["missing"]["action"] == "remove" and items["b"]["own"] is True
    assert items["b"]["detail"] == "Missing since 12 Nov · was in Old crates"
    assert items["c"]["missing"]["upgrade_waiting"] is True and items["c"]["upgrade_ready"] is True


def test_an_item_whose_drive_is_away_says_offline_not_missing_but_stays_in_the_group():
    st = state(a=own())
    away = {"/Volumes/Example/Music": "unmounted"}
    item = group(views.todo(st, "all", False, {}, TODAY, away=away, place=place))["items"][0]
    assert item["file_state"] == "offline" and item["missing"]["action"] == "remove"


def test_the_group_counts_what_the_head_link_acts_on_by_action():
    st = state(a=gone(), b=gone(title="B"), c=own(), d=own(title="D"), h=gone(title="Hidden", hidden=True),
               n=gone(title="N"), t=gone(title="T"), x=gone(title="X", file_gone=None))
    st["never"] = {"n": {}}
    st["ambiguous"] = {"t": ["a.aiff", "b.aiff"]}
    st["tracks"]["d"]["rekordbox_check"] = {"reason": "swapped", "since": "2026-11-10"}
    g = group(views.todo(st, "all", False, {}, TODAY, place=place))
    # a, b, x: Download again can run; c: Remove can run; d: check open; n: never; t: found twice; h: hidden
    assert g["all"] == {"download_again": 3, "remove": 1}
    reasons = {i["track_id"]: i["missing"]["why_not"] for i in g["items"]}
    assert reasons == {"a": None, "b": None, "c": None, "d": "check_open", "n": "never", "t": "found_twice",
                       "x": None}  # (h is hidden: left out of the list too)
    shown = group(views.todo(st, "all", True, {}, TODAY, place=place))
    assert shown["all"] == {"download_again": 3, "remove": 1}                       # hidden songs are never counted
    assert {"h"} == {i["track_id"] for i in shown["items"]} - set(reasons)


def test_hidden_missing_songs_are_counted_and_shown_on_request_like_any_item():
    st = state(a=gone(), h=gone(hidden=True, title="H"))
    out = views.todo(st, "all", False, {}, TODAY, place=place)
    assert [i["track_id"] for i in group(out)["items"]] == ["a"] and out["hidden_count"] == 1
    assert out["chips"]["missing_file"] == 1
    assert [i["track_id"] for i in group(views.todo(st, "all", True, {}, TODAY, place=place))["items"]] == ["h", "a"]  # by artist and title


def test_the_filter_word_missing_file_keeps_only_its_group():
    st = state(a=gone(), c=e("not_lossless", cutoff_hz=16000, upgrade=PARKED))
    out = views.todo(st, "missing_file", False, {}, TODAY, place=place)
    assert [g["key"] for g in out["groups"]] == ["missing_file"]
    assert out["chips"]["upgrade_ready"] == 1                                       # the chips count every group


def test_a_missing_song_is_in_no_other_group_but_a_check_and_a_download_asked_leaves():
    st = state(w=gone(status="not_lossless", cutoff_hz=16000), u=gone(upgrade=PARKED, status="not_lossless",
                                                                      cutoff_hz=16000),
               asked=gone(file_gone="2026-11-18", title="Asked"))
    st["tracks"]["w"]["rekordbox_check"] = {"reason": "swapped", "since": "2026-11-10"}
    out = views.todo(st, "all", False, {}, TODAY, place=place)
    assert {g["key"]: [i["track_id"] for i in g["items"]] for g in out["groups"]} == {
        "rekordbox_check": ["w"], "missing_file": ["w", "u"]}                       # both of w's groups; "asked" nowhere
    assert out["chips"]["all"] == 2                                                # each track once
    assert views.upgrade_ready_keys(st) == []


def test_a_missing_song_found_in_several_places_is_in_missing_files_not_in_other():
    st = state(t=gone())
    st["ambiguous"] = {"t": ["Library/A/x.aiff", "/Volumes/Example/y.aiff"]}
    others = {"t": "SEVERAL FILES · could be this track, nothing done"}
    out = views.todo(st, "all", False, others, TODAY, place=place)
    assert [g["key"] for g in out["groups"]] == ["missing_file"]
    item = group(out)["items"][0]
    assert item["detail"] == "In 2 places now · keep one and it links again"
    assert item["missing"]["why_not"] == "found_twice"


def test_a_download_asked_for_a_song_with_several_files_falls_back_to_other():
    st = state(t=gone(file_gone="2026-11-18"))
    others = {"t": "SEVERAL FILES · could be this track, nothing done"}
    assert [g["key"] for g in views.todo(st, "all", False, others, TODAY, place=place)["groups"]] == ["other"]


def test_a_missing_own_song_is_not_in_the_cdj_group():
    own_flac = own(file_codec="flac", file_rate=192000, file_bits=24, path="/Volumes/Example/Music/a.flac")
    st = state(**{"local:1": own_flac})
    assert [g["key"] for g in views.todo(st, "all", False, {}, TODAY, place=place)["groups"]] == ["missing_file"]


def test_the_group_is_absent_when_no_file_is_missing():
    out = views.todo(state(a=e()), "all", False, {}, TODAY)
    assert group(out) is None and out["chips"]["missing_file"] == 0


# --- Library and the track's details ---

def test_library_rows_say_file_missing_and_the_summary_counts_the_to_do():
    st = state(a=gone(), b=e(title="B"), c=own(title="C"))
    lib = views.library(st, "all", None, "", "all", None, lines=[])
    assert {r["track_id"]: r["file_state"] for r in lib["rows"]} == {"a": "file_missing", "b": "here",
                                                                      "c": "file_missing"}
    assert lib["summary"]["to_do"] == 2                                              # a playlist song and an own song
    away = views.library(st, "all", None, "", "all", None, away={"/Volumes/Example/Music": "unmounted"}, lines=[])
    assert {r["track_id"]: r["file_state"] for r in away["rows"]}["c"] == "offline"


def test_track_detail_carries_the_missing_object_with_line_and_hint():
    st = state(a=gone(), b=e())
    d = views.track_detail("a", st["tracks"]["a"], [], TODAY, exists=True, place="Techno 2019", records=st, where=place)
    assert d["file_state"] == "file_missing" and d["audio_url"] is None
    assert d["missing"] == missing.detail_view("a", st["tracks"]["a"], st, place, TODAY)
    assert d["missing"]["line"] == "Not seen since 12 Nov. It was in Techno 2019."
    assert d["next_qobuz_check"] is None
    ok = views.track_detail("b", st["tracks"]["b"], [], TODAY, exists=True, place="A", records=st, where=place)
    assert ok["missing"] is None and ok["file_state"] == "here"
    asked = gone(file_gone="2026-11-18")
    d = views.track_detail("a", asked, [], TODAY, records=state(a=asked), where=place)
    assert d["missing"]["why_not"] == "asked" and d["next_qobuz_check"] == "next_sync"
    assert views.track_detail("b", e(), [], TODAY)["missing"] is None                # no records given: still answers


# --- through the hub (api.todo, api.track, api.library) ---

@pytest.fixture
def hub(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    st = load_state(paths)
    st["tracks"]["t1"]["upgrade"] = None
    write_state(paths, st)
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET missing_since = ? WHERE path = ?", (SINCE, LOSSLESS.removeprefix("Library/")))
        conn.commit()
    api, _ = make_api(paths)
    return api, paths


def test_the_hub_answers_the_group_the_details_and_the_library_rows_for_a_missing_file(hub):
    api, paths = hub
    out = api.todo()
    g = group(out)
    assert [x["key"] for x in out["groups"]][0] == "missing_file" and g["label"] == "Missing files"
    item = g["items"][0]
    assert item["track_id"] == "t1" and item["file_state"] == "file_missing"
    assert item["detail"] == "Missing since 12 Nov · was in Hard_Bounce"            # Sites.place: the playlist's folder
    assert item["missing"]["action"] == "download_again" and item["missing"]["why_not"] is None
    assert g["all"] == {"download_again": 1, "remove": 0}
    assert api.todo("missing_file")["ok"] is True and api.todo("missing_file")["chips"]["missing_file"] == 1
    t = api.track("t1")["track"]
    assert t["file_state"] == "file_missing" and t["missing"]["line"] == "Not seen since 12 Nov. It was in Hard_Bounce."
    assert t["missing"]["hint"].endswith("Or download it again at your next sync.")
    rows = api.library("folder", "Library/Hard_Bounce", "", "all", "title")["rows"]
    assert {r["track_id"]: r["file_state"] for r in rows}["t1"] == "file_missing"
    assert api.track("t2")["track"]["missing"] is None


def test_the_sidebars_to_do_count_includes_a_missing_song(hub):
    api, _ = hub
    assert api.todo()["chips"]["all"] >= 1
    counted = api._todo(api._state(), "all", False, count_only=True)
    assert counted["chips"]["missing_file"] == 1 and counted["chips"]["all"] == api.todo()["chips"]["all"]


# --- the contract: the window's types name what the views send ---

TYPES_TS = Path(__file__).resolve().parents[1] / "hub-ui" / "src" / "lib" / "bridge" / "types.ts"
CONTRACT = Path(__file__).resolve().parents[1] / "docs" / "hub-bridge-contract.md"


def ts_type(name):
    """The body of `export type <name> = ...;` in types.ts, up to its terminating semicolon."""
    return re.search(rf"export type {name} =(.*?);\n(?=\n|/\*\*|export |type |//)", TYPES_TS.read_text(encoding="utf-8"), re.S).group(1)


def test_types_ts_names_the_filters_actions_reasons_and_fields_the_views_send():
    quoted = lambda body: re.findall(r"'([a-z_]+)'", body)
    assert set(views.TODO_GROUP_KEYS) <= set(quoted(ts_type("TodoFilter")))
    assert quoted(ts_type("MissingAction")) == list(missing.ACTIONS)
    assert quoted(ts_type("MissingReason")) == list(missing.REASONS)
    fields = lambda body: re.findall(r"(\w+)\??:", body)
    view = missing.view("t", gone(), state(t=gone()), place, TODAY)
    assert fields(ts_type("MissingView")) == list(view)
    assert fields(ts_type("MissingDetail")) == ["line", "hint"]
    assert fields(ts_type("MissingAll")) == list(missing.ACTIONS)
    detail = missing.detail_view("t", gone(), state(t=gone()), place, TODAY)
    assert list(detail) == [*view, "line", "hint"]


def test_the_contract_doc_names_every_reason_and_the_group():
    text = " ".join(CONTRACT.read_text(encoding="utf-8").split())  # the doc wraps its lines
    assert "## Missing files (issue 43)" in text and "missing_file" in text
    for reason, words in missing.REASONS.items():
        assert f"`{reason}`" in text
        if "{other}" not in words:
            assert words in text
