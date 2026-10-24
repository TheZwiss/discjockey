import os
from datetime import date

import pytest

from discjockey import playlists_file as pf
from discjockey.config import ConfigError, parse_playlists
from discjockey.models import SourceTrack
from discjockey.planner import ENTRY_KEYS
from discjockey.playlists_file import PlaylistsChanged, Row

ID1, ID2, ID3 = "0DiscjockeyExampleList", "3DiscjockeyExampleList", "37i9dQZF1DXcBWIGoYBM5M"
URL1 = f"https://open.spotify.com/playlist/{ID1}?si=abc"
TEXT = f"""# My playlists
# top = highest priority

Hard_Bounce = {URL1}
#off# Old = spotify:playlist:{ID3}
# a note about Powertrance
Powertrance = https://open.spotify.com/playlist/{ID2}
"""


@pytest.fixture
def path(tmp_path):
    p = tmp_path / "playlists.txt"
    p.write_text(TEXT, encoding="utf-8")
    return p


def test_load_rows_and_version(path):
    loaded = pf.load(path)
    assert loaded.rows == [Row("Hard_Bounce", URL1), Row("Old", f"spotify:playlist:{ID3}", False),
                           Row("Powertrance", f"https://open.spotify.com/playlist/{ID2}")]
    assert [r.ref for r in loaded.rows] == [ID1, ID3, ID2]
    assert loaded.version == pf.version_of(TEXT.encode()) and loaded.problem is None


def test_load_without_a_file(tmp_path):
    loaded = pf.load(tmp_path / "playlists.txt")
    assert loaded.rows == [] and loaded.version == "" and loaded.problem is None


def test_load_reports_a_problem_but_still_shows_the_rows(path):
    path.write_text(TEXT + "Broken =\n")
    loaded = pf.load(path)
    assert len(loaded.rows) == 3 and "line 8" in loaded.problem


def test_reorder_rename_and_switch_off_keep_comments_and_blank_lines(path):
    loaded = pf.load(path)
    hard, old, power = loaded.rows
    pf.save(path, [Row("Powertrance", power.link), Row("Hard Bounce", hard.link, False), old], loaded.version)
    assert path.read_text() == f"""# My playlists
# top = highest priority

Powertrance = https://open.spotify.com/playlist/{ID2}
#off# Hard Bounce = {URL1}
# a note about Powertrance
#off# Old = spotify:playlist:{ID3}
"""
    assert [line.folder for line in parse_playlists(path.read_text())] == ["Powertrance"]


def test_rows_fill_the_playlist_lines_in_order_and_removed_rows_disappear(path):
    loaded = pf.load(path)
    new = Row("Bouncy", pf.clean_link("https://open.spotify.com/intl-de/playlist/1A2b3C4d5E6f7G8h9I0jKl?si=1"))
    pf.save(path, [loaded.rows[0], new], loaded.version)
    assert path.read_text() == f"""# My playlists
# top = highest priority

Hard_Bounce = {URL1}
Bouncy = https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl
# a note about Powertrance
"""


def test_more_rows_than_lines_go_to_the_end(path):
    loaded = pf.load(path)
    extra = Row("Bouncy", "https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl")
    pf.save(path, loaded.rows + [extra], loaded.version)
    assert path.read_text() == TEXT + "Bouncy = https://open.spotify.com/playlist/1A2b3C4d5E6f7G8h9I0jKl\n"


def test_save_refuses_a_file_changed_elsewhere(path):
    loaded = pf.load(path)
    path.write_text(TEXT + "# edited by hand\n")
    with pytest.raises(PlaylistsChanged, match="changed elsewhere"):
        pf.save(path, loaded.rows[:1], loaded.version)
    assert path.read_text().endswith("# edited by hand\n")


def test_save_refuses_invalid_rows_and_changes_nothing(path):
    loaded = pf.load(path)
    for rows in ([Row("not_lossless", URL1)], [Row("A", URL1), Row("a", f"spotify:playlist:{ID2}")],
                 [Row("A", URL1), Row("B", URL1, False)], [Row("A/B", URL1)]):
        with pytest.raises(ConfigError):
            pf.save(path, rows, loaded.version)
    assert path.read_text() == TEXT


def test_save_allows_every_playlist_switched_off(path):
    loaded = pf.load(path)
    pf.save(path, [Row(r.folder, r.link, False) for r in loaded.rows], loaded.version)
    assert pf.load(path).problem is not None  # "no active playlists": the sync says so until one is on again


def test_save_is_atomic(path, monkeypatch):
    loaded = pf.load(path)

    def crash(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(pf.os, "replace", crash)
    with pytest.raises(OSError):
        pf.save(path, loaded.rows[:1], loaded.version)
    assert path.read_text() == TEXT and sorted(p.name for p in path.parent.iterdir()) == ["playlists.txt"]


def test_save_returns_the_new_version_and_creates_the_file(tmp_path):
    p = tmp_path / "playlists.txt"
    v = pf.save(p, [Row("A", pf.clean_link(URL1))], "")
    assert p.read_text() == f"A = https://open.spotify.com/playlist/{ID1}\n" and v == pf.version_of(p.read_bytes())


def test_clean_link_refuses_other_links():
    with pytest.raises(ValueError) as excinfo:
        pf.clean_link("https://open.spotify.com/album/0DiscjockeyExampleList")
    assert str(excinfo.value) == ("That isn't a Spotify or Qobuz playlist link. Open the playlist in Spotify or Qobuz, "
                                  "choose Share, then Copy link, and paste it here.")


def test_clean_link_gives_the_canonical_link_of_the_recognising_source():
    assert pf.clean_link(f"  spotify:playlist:{ID1}  ") == f"https://open.spotify.com/playlist/{ID1}"
    assert pf.clean_link(URL1) == f"https://open.spotify.com/playlist/{ID1}"


def test_a_row_knows_its_service_and_ref():
    row = Row("A", URL1)
    assert (row.service, row.ref) == ("spotify", ID1)
    assert (Row("B", "https://example.com/x").service, Row("B", "https://example.com/x").ref) == (None, None)


def test_placement_keys_by_ref_and_hands_the_planner_the_service_ids():
    rows = [Row("A", URL1), Row("B", f"spotify:playlist:{ID2}")]
    fetched = pf._fetched(rows, {ID1: [SourceTrack("x", "X", ("Artist",), "", None, 1000, None)]})
    assert [(f.line.folder, f.line.playlist_id, f.line.service) for f in fetched] == [("A", ID1, "spotify")]


# --- what a change would do (pure; no downloads, no file changes) ---

def t(tid, title=None):
    return SourceTrack(tid, title or f"Song {tid}", ("Artist",), "Album", None, 180000, None)


def entry(folder, status="lossless", title=None, tid="x"):
    e = dict.fromkeys(ENTRY_KEYS)
    path = None if status == "missing" else f"Library/{folder}/Artist - {title or 'Song ' + tid}.aiff"
    e.update(aliases=[], artist="Artist", title=title or f"Song {tid}", duration_ms=180000, folder=folder, path=path,
             status=status, rejected_sources=[], in_playlists=True)
    return e


FETCHED = {ID1: [t("a"), t("b"), t("c")], ID2: [t("b"), t("c"), t("d")]}
STATE = {"version": 1, "pending": [], "qobuz_usage": {"days": {}, "signals": []},
         "tracks": {"a": entry("Hard_Bounce", tid="a"), "b": entry("Hard_Bounce", tid="b"),
                    "c": entry("Hard_Bounce", "not_lossless", tid="c"), "d": entry("Powertrance", tid="d")}}
FILES = [e["path"] for e in STATE["tracks"].values()]
OLD = [Row("Hard_Bounce", URL1), Row("Powertrance", f"spotify:playlist:{ID2}")]


def change(new, fetched=FETCHED, state=STATE):
    return pf.preview_change(OLD, new, fetched, state, FILES, date(2026, 10, 20))


def test_reorder_moves_the_shared_tracks():
    c = change([OLD[1], OLD[0]])
    assert sorted(c.moves) == [("b", "Hard_Bounce", "Powertrance"), ("c", "Hard_Bounce", "Powertrance")]
    assert c.before == {"Hard_Bounce": 3, "Powertrance": 1} and c.after == {"Hard_Bounce": 1, "Powertrance": 3}
    assert c.new == [] and c.stopped == [] and c.unknown == []


def test_switch_off_stops_updates_but_moves_nothing_away():
    c = change([OLD[0], Row("Powertrance", OLD[1].link, False)])
    assert c.stopped == ["d"] and c.moves == [] and c.after == {"Hard_Bounce": 3}


def test_rename_moves_every_file_of_the_folder():
    c = change([Row("Hard Bounce", URL1), OLD[1]])
    assert sorted(c.moves) == [("a", "Hard_Bounce", "Hard Bounce"), ("b", "Hard_Bounce", "Hard Bounce"),
                               ("c", "Hard_Bounce", "Hard Bounce")]


def test_add_counts_new_downloads_and_says_when_a_playlist_is_not_read_yet():
    fetched = {**FETCHED, ID3: [t("a"), t("e"), t("f")]}
    c = change(OLD + [Row("New", f"spotify:playlist:{ID3}")], fetched)
    assert c.new == ["e", "f"] and c.moves == []
    c = change(OLD + [Row("New", f"spotify:playlist:{ID3}")])
    assert c.unknown == [ID3] and c.new == []


def test_a_case_only_rename_moves_nothing():
    assert change([Row("hard_bounce", URL1), OLD[1]]).moves == []


def test_tracks_without_a_file_change_folder_without_a_move():
    state = {**STATE, "tracks": {**STATE["tracks"], "b": entry("Hard_Bounce", "missing", tid="b")}}
    c = change([OLD[1], OLD[0]], state=state)
    assert [m[0] for m in c.moves] == ["c"] and c.reroutes == [("b", "Hard_Bounce", "Powertrance")]
    fetched = {ID1: [t("a"), t("x")], ID2: [t("x"), t("d")]}  # x: never downloaded
    c = change([OLD[1], OLD[0]], fetched)
    assert c.moves == [] and c.reroutes == [("x", "Hard_Bounce", "Powertrance")]


def test_overlaps():
    found = pf.overlaps(OLD, FETCHED)
    assert [(tr.id, folders, lands) for tr, folders, lands in found] == [
        ("b", ["Hard_Bounce", "Powertrance"], "Hard_Bounce"), ("c", ["Hard_Bounce", "Powertrance"], "Hard_Bounce")]


# --- what a change retargets and renames (plan library stage 2, task 2.4) ---

def test_placement_places_the_songs_of_read_playlists():
    assert pf.placement(OLD, FETCHED, STATE) == {"a": "Hard_Bounce", "b": "Hard_Bounce", "c": "Hard_Bounce",
                                                 "d": "Powertrance"}
    assert pf.placement([Row("New", f"spotify:playlist:{ID3}")] + OLD, FETCHED, STATE) == pf.placement(
        OLD, FETCHED, STATE)


def test_an_order_change_retargets_the_shared_tracks_only():
    assert pf.retargeted(OLD, [OLD[1], OLD[0]], FETCHED, STATE) == {"b": "Powertrance", "c": "Powertrance"}


def test_an_unread_playlist_retargets_nothing():
    unread = Row("New", f"spotify:playlist:{ID3}")
    assert pf.retargeted(OLD, [unread] + OLD, FETCHED, STATE) == {}
    fetched = {**FETCHED, ID3: [t("a"), t("d")]}  # once read, its songs follow it
    assert pf.retargeted(OLD, [unread] + OLD, fetched, STATE) == {"a": "New", "d": "New"}


def test_retargeted_ignores_case_only_renames_and_follows_real_ones():
    assert pf.retargeted(OLD, [Row("hard_bounce", URL1), OLD[1]], FETCHED, STATE) == {}
    assert pf.retargeted(OLD, [Row("Hard Bounce", URL1), OLD[1]], FETCHED, STATE) == {
        "a": "Hard Bounce", "b": "Hard Bounce", "c": "Hard Bounce"}


def test_renames_by_playlist_in_the_new_order_without_case_only_ones():
    new = [Row("Trance", OLD[1].link), Row("hard_bounce", URL1), Row("New", f"spotify:playlist:{ID3}")]
    assert pf.renames(OLD, new) == [("Powertrance", "Trance")]
    new = [Row("Trance", OLD[1].link, False), Row("Hard Bounce", f"spotify:playlist:{ID1}")]
    assert pf.renames(OLD, new) == [("Powertrance", "Trance"), ("Hard_Bounce", "Hard Bounce")]
    assert pf.renames(OLD, OLD) == [] and pf.renames(OLD, []) == []
