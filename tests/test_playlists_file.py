import os
from datetime import date

import pytest

from discjockey import playlists_file as pf, words
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
    assert str(excinfo.value) == ("That isn't a playlist link Discjockey can read. Open the playlist in Spotify, Qobuz, "
                                  "SoundCloud or YouTube Music, choose Share, then Copy link, and paste it here.")


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


# --- the rules of the list and the single changes to it (issue 39 V4.2a) ---

SC = "https://soundcloud.com/some-dj/sets/warm-up"
QB = "https://open.qobuz.com/playlist/1234567"
LIKED = "https://music.youtube.com/playlist?list=LM"
LIST = [Row("Hard_Bounce", pf.clean_link(URL1)), Row("Old", f"spotify:playlist:{ID3}", False),
        Row("Powertrance", pf.clean_link(f"https://open.spotify.com/playlist/{ID2}"))]


def shape(rows):
    return [(r.folder, r.ref, r.enabled) for r in rows]


def raised(fn, *args):
    with pytest.raises(ValueError) as e:
        fn(*args)
    return str(e.value)


@pytest.mark.parametrize("name, own, said", [
    ("  ", None, "A folder name is needed."),
    ("a/b", None, 'A folder name can\'t contain "/".'),
    (" . ", None, "Pick another folder name."),
    ("..", None, "Pick another folder name."),
    ("powertrance", None, "Another playlist already uses the folder Powertrance."),
    ("POWERTRANCE", ID2, None),  # its own folder, other case: a case-only rename
    ("powertrance", ID1, "Another playlist already uses the folder Powertrance."),
    ("Fresh", None, None),
])
def test_folder_problem(name, own, said):
    assert pf.folder_problem(name, LIST, own) == said


def test_folder_problem_compares_folded_names():
    rows = [Row("Café", pf.clean_link(URL1))]  # NFC
    assert pf.folder_problem("Café", rows)  # NFD spelling of the same name


@pytest.mark.parametrize("link", [URL1, f"spotify:playlist:{ID1}", f"https://open.spotify.com/playlist/{ID1}?si=zzz"])
def test_listed_finds_a_spotify_playlist_whatever_the_link_looks_like(link):
    assert pf.listed(LIST, link) is LIST[0]


@pytest.mark.parametrize("link", [SC, QB, LIKED])
def test_listed_by_ref_for_every_service(link):
    rows = [*LIST, Row("X", pf.clean_link(link))]
    assert pf.listed(rows, link) is rows[-1]
    assert pf.listed(LIST, link) is None


def test_listed_is_none_for_a_link_nobody_knows():
    assert pf.listed(LIST, "https://example.com/x") is None


def test_find_by_folder_ignores_case_and_spelling():
    assert pf.find(LIST, "powertrance") == 2
    assert pf.find(LIST, "  Old ") == 1


def test_find_with_the_playlist_prefix_reads_a_folder_never_a_link():
    assert pf.find(LIST, "playlist:Powertrance") == 2
    rows = [Row("spotify:playlist:" + ID1, pf.clean_link(URL1)), Row("Other", pf.clean_link(f"https://open.spotify.com/playlist/{ID2}"))]
    assert pf.find(rows, "playlist:spotify:playlist:" + ID1) == 0
    assert pf.find(rows, "spotify:playlist:" + ID2) == 1  # without the prefix it is a link


def test_find_by_link_including_a_si_variant():
    assert pf.find(LIST, URL1) == 0
    assert pf.find(LIST, f"spotify:playlist:{ID3}") == 1


def test_find_names_none_and_two():
    assert raised(pf.find, LIST, "Nothing") == "None of your playlists is called Nothing."
    assert raised(pf.find, LIST, "playlist:Nothing") == "None of your playlists is called Nothing."
    assert raised(pf.find, LIST, "https://open.spotify.com/playlist/0Unlisted") == (
        "None of your playlists is called https://open.spotify.com/playlist/0Unlisted.")
    twins = [Row("Same", pf.clean_link(URL1)), Row("same", pf.clean_link(f"https://open.spotify.com/playlist/{ID2}"))]
    assert raised(pf.find, twins, "SAME") == "SAME names more than one of your playlists: say its folder name."


@pytest.mark.parametrize("op", ["add", None, 5, {"playlist": "x"}])
def test_check_op_needs_an_op_key(op):
    assert raised(pf.check_op, op) == "A playlist change needs op."


def test_check_op_refusals():
    assert raised(pf.check_op, {"op": "merge"}) == "Discjockey can't make the change merge to your playlists."
    assert raised(pf.check_op, {"op": "add"}) == "A add change needs url."
    assert raised(pf.check_op, {"op": "rename"}) == "A rename change needs playlist and folder."
    assert raised(pf.check_op, {"op": "move", "at": 2}) == "A move change needs playlist and to."
    assert raised(pf.check_op, {"op": "edit"}) == "A edit change needs file."
    assert raised(pf.check_op, {"op": "remove", "playlist": "x", "to": 2}) == "to is not part of a remove change."
    assert raised(pf.check_op, {"op": "add", "url": URL1, "playlist": "x"}) == "playlist is not part of a add change."
    assert raised(pf.check_op, {"op": "enable", "playlist": "x", "off": True}) == "off is not part of a enable change."


@pytest.mark.parametrize("op, said", [
    ({"op": "add", "url": 5}, "url in a playlist change takes text."),
    ({"op": "add", "url": URL1, "at": "2"}, "at in a playlist change takes a whole number."),
    ({"op": "add", "url": URL1, "at": True}, "at in a playlist change takes a whole number."),
    ({"op": "move", "playlist": "x", "to": 1.5}, "to in a playlist change takes a whole number."),
    ({"op": "add", "url": URL1, "off": "yes"}, "off in a playlist change takes true or false."),
    ({"op": "rename", "playlist": "x", "folder": None}, "folder in a playlist change takes text."),
])
def test_check_op_types(op, said):
    assert raised(pf.check_op, op) == said


def test_apply_add_at_the_end_with_its_folder_trimmed_and_normalised():
    rows = pf.apply(LIST, {"op": "add", "url": f"  {SC}?x=1 ", "folder": "  Warm\u0075\u0308p "})
    assert rows[-1] == Row("Warm\u00fcp", pf.clean_link(SC), True)  # NFC, trimmed, the clean link, switched on
    assert shape(rows[:3]) == shape(LIST) and len(LIST) == 3  # the input is untouched


def test_apply_add_at_a_place_and_switched_off():
    rows = pf.apply(LIST, {"op": "add", "url": QB, "folder": "Q", "at": 2, "off": True})
    assert [(r.folder, r.enabled) for r in rows] == [("Hard_Bounce", True), ("Q", False), ("Old", False), ("Powertrance", True)]
    assert [r.folder for r in pf.apply(LIST, {"op": "add", "url": QB, "folder": "Q", "at": 1})][0] == "Q"
    assert pf.apply(LIST, {"op": "add", "url": QB, "folder": "Q", "at": 4})[-1].folder == "Q"


@pytest.mark.parametrize("at", [0, 5, -1])
def test_apply_add_refuses_a_place_outside_the_list(at):
    assert raised(pf.apply, LIST, {"op": "add", "url": QB, "folder": "Q", "at": at}) == (
        "A place in your playlists goes from 1 to 4.")


def test_apply_add_refusals_come_in_order():
    assert raised(pf.apply, LIST, {"op": "add", "url": "https://example.com/x", "folder": "Q"}).startswith(
        "That isn't a playlist link")
    assert raised(pf.apply, LIST, {"op": "add", "url": URL1, "folder": "Q"}) == "This playlist is already in your list."
    assert raised(pf.apply, LIST, {"op": "add", "url": URL1}) == "This playlist is already in your list."
    assert raised(pf.apply, LIST, {"op": "add", "url": QB}) == "A add change needs folder."
    assert raised(pf.apply, LIST, {"op": "add", "url": QB, "folder": "old"}) == (
        "Another playlist already uses the folder Old.")
    assert raised(pf.apply, LIST, {"op": "add", "url": QB, "folder": " "}) == "A folder name is needed."


def test_apply_remove_rename_move_and_the_switches():
    assert [r.folder for r in pf.apply(LIST, {"op": "remove", "playlist": "old"})] == ["Hard_Bounce", "Powertrance"]
    renamed = pf.apply(LIST, {"op": "rename", "playlist": "Old", "folder": "Older"})
    assert [(r.folder, r.link, r.enabled) for r in renamed] == [(r.folder if r.folder != "Old" else "Older", r.link, r.enabled)
                                                                for r in LIST]
    assert pf.apply(LIST, {"op": "rename", "playlist": "Powertrance", "folder": "POWERTRANCE"})[2].folder == "POWERTRANCE"
    assert [r.folder for r in pf.apply(LIST, {"op": "move", "playlist": "Powertrance", "to": 1})] == [
        "Powertrance", "Hard_Bounce", "Old"]
    assert [r.folder for r in pf.apply(LIST, {"op": "move", "playlist": "Hard_Bounce", "to": 3})] == [
        "Old", "Powertrance", "Hard_Bounce"]
    assert [r.enabled for r in pf.apply(LIST, {"op": "enable", "playlist": "Old"})] == [True, True, True]
    assert [r.enabled for r in pf.apply(LIST, {"op": "disable", "playlist": "Old"})] == [True, False, True]
    assert pf.apply(LIST, {"op": "enable", "playlist": "Hard_Bounce"}) == LIST  # already on: nothing changes


def test_apply_refusals_of_the_other_changes():
    assert raised(pf.apply, LIST, {"op": "rename", "playlist": "Old", "folder": "powertrance"}) == (
        "Another playlist already uses the folder Powertrance.")
    assert raised(pf.apply, LIST, {"op": "rename", "playlist": "Old", "folder": "a/b"}) == 'A folder name can\'t contain "/".'
    assert raised(pf.apply, LIST, {"op": "move", "playlist": "Old", "to": 4}) == "A place in your playlists goes from 1 to 3."
    assert raised(pf.apply, LIST, {"op": "move", "playlist": "Old", "to": 0}) == "A place in your playlists goes from 1 to 3."
    assert raised(pf.apply, LIST, {"op": "remove", "playlist": "Zed"}) == "None of your playlists is called Zed."
    assert raised(pf.apply, LIST, {"op": "nonsense"}) == "Discjockey can't make the change nonsense to your playlists."


def test_apply_edit_takes_the_rows_of_a_file(tmp_path, path):
    rows = pf.apply([Row("Z", pf.clean_link(QB))], {"op": "edit", "file": str(path)})
    assert shape(rows) == shape(pf.load(path).rows)


def test_apply_edit_refusals(tmp_path):
    assert raised(pf.apply, LIST, {"op": "edit", "file": "relative.txt"}) == "Give the playlists file as a full path."
    gone = tmp_path / "gone.txt"
    assert raised(pf.apply, LIST, {"op": "edit", "file": str(gone)}) == f"There is no file at {gone}."
    bad = tmp_path / "bad.txt"
    bad.write_text("Same = " + URL1 + "\nSame = " + URL1 + "\n", encoding="utf-8")
    assert raised(pf.apply, LIST, {"op": "edit", "file": str(bad)}) == pf.load(bad).problem


# (the op, the words that make it)
WORDS = [
    ({"op": "add", "url": QB, "folder": "Q"}, ["playlist", "add", QB, "--folder", "Q"]),
    ({"op": "add", "url": QB, "folder": "Q", "at": 2, "off": True},
     ["playlist", "add", QB, "--folder", "Q", "--at", "2", "--off"]),
    ({"op": "add", "url": QB, "folder": "Q", "off": False}, ["playlist", "add", QB, "--folder", "Q"]),
    ({"op": "remove", "playlist": "Old"}, ["playlist", "remove", "Old"]),
    ({"op": "enable", "playlist": "Old"}, ["playlist", "enable", "Old"]),
    ({"op": "disable", "playlist": "Old"}, ["playlist", "disable", "Old"]),
    ({"op": "rename", "playlist": "Old", "folder": "Older"}, ["playlist", "rename", "Old", "Older"]),
    ({"op": "move", "playlist": "Old", "to": 3}, ["playlist", "move", "Old", "--to", "3"]),
    ({"op": "edit", "file": "/x/y.txt"}, ["playlist", "edit", "--file", "/x/y.txt"]),
]


@pytest.mark.parametrize("op, said", WORDS)
def test_op_words(op, said):
    assert pf.op_words(op) == said


# (the op, the message, the undo words) for LIST
LOG = [
    ({"op": "add", "url": QB, "folder": "Q"}, "playlist_add", "Added the playlist Q at place 4.",
     ["playlist", "remove", "playlist:Q"]),
    ({"op": "add", "url": QB, "folder": "Q", "at": 2, "off": True}, "playlist_add",
     "Added the playlist Q at place 2, switched off.", ["playlist", "remove", "playlist:Q"]),
    ({"op": "remove", "playlist": "Powertrance"}, "playlist_remove",
     "Removed the playlist Powertrance. Its files stay in your library.",
     ["playlist", "add", f"https://open.spotify.com/playlist/{ID2}", "--folder", "Powertrance", "--at", "3"]),
    ({"op": "remove", "playlist": "Old"}, "playlist_remove",
     "Removed the playlist Old. Its files stay in your library.",
     ["playlist", "add", f"spotify:playlist:{ID3}", "--folder", "Old", "--at", "2", "--off"]),
    ({"op": "rename", "playlist": "Old", "folder": "Older"}, "playlist_rename", "Renamed the playlist Old to Older.",
     ["playlist", "rename", "playlist:Older", "Old"]),
    ({"op": "move", "playlist": "Powertrance", "to": 1}, "playlist_move",
     "Moved the playlist Powertrance from place 3 to place 1.", ["playlist", "move", "playlist:Powertrance", "--to", "3"]),
    ({"op": "enable", "playlist": "old"}, "playlist_enable", "Switched the playlist Old on.",
     ["playlist", "disable", "playlist:Old"]),
    ({"op": "disable", "playlist": "Powertrance"}, "playlist_disable",
     "Switched the playlist Powertrance off. Its files stay.", ["playlist", "enable", "playlist:Powertrance"]),
    ({"op": "edit", "file": "/x/new.txt"}, "playlist_edit", "Replaced your playlists with the list in /x/new.txt.",
     ["playlist", "edit", "--file", "/x/copy.txt"]),
    (None, "playlist_saved", "Saved your playlists in the window.", ["playlist", "edit", "--file", "/x/copy.txt"]),
]


@pytest.mark.parametrize("op, operation, message, undo", LOG)
def test_change_log(op, operation, message, undo):
    assert pf.change_log(LIST, op, "/x/copy.txt") == (operation, message, undo)
    if op is not None and op["op"] != "edit":
        assert undo == pf.op_words(pf.undo_op(LIST, op, "/x/copy.txt"))


def test_an_add_of_liked_music_is_logged_as_its_own_operation_by_either_path():
    for op in ({"op": "add", "url": LIKED, "folder": "Liked_music"},
               {"op": "add", "url": LIKED, "folder": "Liked_music", "at": 1, "off": True}):
        assert pf.change_log(LIST, op, None) == ("liked_music_add", "Added Liked music as the playlist Liked_music.",
                                                 ["playlist", "remove", "playlist:Liked_music"])


def test_the_logged_names_are_the_ones_history_knows():
    assert set(pf.LOGGED) == set(pf.OPS) and set(words.PLAYLIST_LOGGED) == {*pf.LOGGED.values(), pf.SAVED, pf.LIKED_ADDED}


ROUND_TRIP = [op for op, _ in WORDS if op["op"] != "edit"] + [
    {"op": "remove", "playlist": "Powertrance"}, {"op": "remove", "playlist": "Old"},
    {"op": "rename", "playlist": "Powertrance", "folder": "POWERTRANCE"},
    {"op": "move", "playlist": "Hard_Bounce", "to": 3}, {"op": "move", "playlist": "Powertrance", "to": 1},
    {"op": "enable", "playlist": "Old"}, {"op": "disable", "playlist": "Hard_Bounce"},
    {"op": "add", "url": QB, "folder": "Q", "at": 1}]


@pytest.mark.parametrize("op", ROUND_TRIP, ids=lambda op: " ".join(pf.op_words(op)))
def test_a_change_and_its_undo_leave_the_list_as_it_was(op):
    after = pf.apply(LIST, op)
    undo = pf.undo_op(LIST, op, "/unused")
    assert shape(pf.apply(after, undo)) == shape(LIST)


def test_an_edit_and_a_window_save_are_undone_by_the_copy(tmp_path):
    copy = tmp_path / "copy.txt"
    copy.write_text(pf.render("", LIST), encoding="utf-8")
    other = tmp_path / "other.txt"
    other.write_text(f"Z = {QB}\n", encoding="utf-8")
    for op in ({"op": "edit", "file": str(other)}, None):
        after = pf.apply(LIST, {"op": "edit", "file": str(other)})
        undo = pf.undo_op(LIST, op, str(copy))
        assert undo == {"op": "edit", "file": str(copy)}
        assert shape(pf.apply(after, undo)) == shape(LIST)


def test_an_undone_remove_brings_back_a_clean_link(tmp_path):
    rows = [Row("A", URL1), Row("B", pf.clean_link(QB))]  # A was written with ?si=
    op = {"op": "remove", "playlist": "A"}
    after = pf.apply(rows, op)
    undo = pf.undo_op(rows, op, None)
    assert undo["url"] == URL1
    back = pf.apply(after, undo)
    assert back[0].link == f"https://open.spotify.com/playlist/{ID1}" and shape(back) == shape(rows)


def test_undo_words_name_the_playlist_by_its_folder_even_when_the_folder_looks_like_a_flag_or_a_link():
    rows = [Row("--to", pf.clean_link(URL1)), Row(f"spotify:playlist:{ID2}", pf.clean_link(QB))]
    for op in ({"op": "disable", "playlist": "playlist:--to"}, {"op": "move", "playlist": f"playlist:spotify:playlist:{ID2}", "to": 1}):
        undo = pf.undo_op(rows, op, None)
        assert undo["playlist"].startswith("playlist:")
        assert shape(pf.apply(pf.apply(rows, op), undo)) == shape(rows)
