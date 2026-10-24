import unicodedata
from datetime import date

import pytest

from discjockey.models import FetchedPlaylist, PlaylistLine, SpotifyTrack
from discjockey.planner import (TidyRow, mirror_dir, out_of_place, plan, replacement_dir, superseded_dir, tidy_rows,
                                tidy_target, upgrades_ready_dir)

TODAY = date(2026, 10, 20)


def tr(id, title=None, artist="Artist", dur=180000, isrc=None):
    return SpotifyTrack(id, title or f"Title {id}", (artist,), "Album", None, dur, isrc)


def pl(folder, *tracks, skipped=()):
    return FetchedPlaylist(PlaylistLine(folder, f"pl{folder}", 1), list(tracks), list(skipped))


def entry(folder="A", status="lossless", path=None, title="Title t1", **kw):
    e = {
        "aliases": [], "isrc": None, "artist": "Artist", "title": title, "duration_ms": 180000,
        "folder": folder, "path": path, "status": status, "source": "qobuz", "source_id": "1",
        "source_format": "flac", "cutoff_hz": None, "rejected_sources": [], "in_playlists": True,
        "added": "2026-10-01T10:00:00", "last_attempt": "2026-10-01", "last_upgrade_check": None,
        "free_downloads": None,
    }
    if status == "missing":
        e.update(path=None, source=None, source_id=None, source_format=None)
    e.update(kw)
    return e


def st(**tracks):
    return {"version": 1, "tracks": tracks, "pending": [], "qobuz_usage": {"days": {}, "signals": []}}


def kinds(p):
    return [(a.kind, a.track_id) for a in p.actions]


# --- identity and flags ---

def test_new_track_goes_to_first_playlist():
    p = plan([pl("A", tr("t1")), pl("B", tr("t1"))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1")]
    assert p.actions[0].folder == "A" and p.actions[0].reason == "new"


def test_same_id_twice_in_one_playlist_is_one_track():
    p = plan([pl("A", tr("t1"), tr("t1"))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1")]


def test_isrc_alias_to_existing_entry():
    s = st(t1=entry(path="Library/A/x.aiff", isrc="DE1", duration_ms=180000))
    p = plan([pl("A", tr("t9", isrc="de1", dur=181000))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == []
    assert p.state["tracks"]["t1"]["aliases"] == ["t9"]
    assert p.notes
    assert s["tracks"]["t1"]["aliases"] == []  # input state untouched


def test_isrc_alias_rejected_when_duration_differs():
    s = st(t1=entry(path="Library/A/x.aiff", isrc="DE1", duration_ms=180000))
    p = plan([pl("A", tr("t1"), tr("t9", isrc="DE1", dur=190000))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "t9")]


def test_two_new_ids_with_same_isrc_in_one_run():
    p = plan([pl("A", tr("t1", isrc="DE1")), pl("B", tr("t2", isrc="DE1"))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1")]
    assert p.actions[0].aliases == ("t2",)


def test_alias_lookup_recognises_known_alias():
    s = st(t1=entry(path="Library/A/x.aiff", aliases=["t9"]))
    p = plan([pl("A", tr("t9"))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == []


def test_dropped_track_flagged_not_touched():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A")], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [] and p.dropped == ["t1"]
    assert p.state["tracks"]["t1"]["in_playlists"] is False


def test_already_dropped_track_not_reported_again():
    s = st(t1=entry(path="Library/A/x.aiff", in_playlists=False))
    p = plan([pl("A")], s, ["Library/A/x.aiff"], TODAY)
    assert p.dropped == []


def test_return_to_playlist():
    s = st(t1=entry(path="Library/A/x.aiff", in_playlists=False))
    p = plan([pl("A", tr("t1"))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [] and p.dropped == []
    assert p.state["tracks"]["t1"]["in_playlists"] is True


def test_skipped_items_do_not_orphan_tracks():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A", tr("t1"), skipped=["Local song (local file)"])], s, ["Library/A/x.aiff"], TODAY)
    assert p.dropped == []


def test_empty_playlist_keeps_files():
    s = st(t1=entry(path="Library/A/x.aiff"), t2=entry(path="Library/A/y.aiff", title="Title t2"))
    p = plan([pl("A")], s, ["Library/A/x.aiff", "Library/A/y.aiff"], TODAY)
    assert kinds(p) == []
    assert sorted(p.dropped) == ["t1", "t2"]
    assert p.state["tracks"]["t1"]["path"] == "Library/A/x.aiff"


# --- option A: files stay where they are (spec §7) ---

def test_a_song_whose_folder_changed_is_not_moved():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("B", tr("t1"))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == []
    assert p.state["tracks"]["t1"]["folder"] == "B"  # the placement folder follows the order
    assert p.state["tracks"]["t1"]["path"] == "Library/A/x.aiff"


def test_a_renamed_folder_moves_nothing():
    s = st(t1=entry(folder="Bounce", path="Library/Bounce/x.aiff"))
    p = plan([pl("Bouncy", tr("t1"))], s, ["Library/Bounce/x.aiff"], TODAY)
    assert kinds(p) == [] and p.state["tracks"]["t1"]["folder"] == "Bouncy"


def test_folder_case_change_does_not_move():
    s = st(t1=entry(folder="bounce", path="Library/bounce/x.aiff"))
    p = plan([pl("Bounce", tr("t1"))], s, ["Library/bounce/x.aiff"], TODAY)
    assert kinds(p) == []


def test_a_folder_change_still_gets_the_weekly_upgrade_check():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check="2026-10-01"))
    p = plan([pl("B", tr("t1"))], s, ["Library/A/not_lossless/x.aiff"], TODAY)
    assert kinds(p) == [("upgrade", "t1")] and p.actions[0].folder == "B"


def test_a_file_moved_by_hand_gets_no_action_and_no_download():
    s = st(t1=entry(path="Library/Sets/2024/x.aiff", placed_by="user", online=True))
    p = plan([pl("A", tr("t1"))], s, ["Library/Sets/2024/x.aiff"], TODAY)
    assert kinds(p) == [] and p.never == [] and p.ambiguous == []
    assert p.state["tracks"]["t1"]["path"] == "Library/Sets/2024/x.aiff"


def test_new_downloads_follow_the_playlist_order():
    p = plan([pl("B", tr("t2")), pl("A", tr("t1"), tr("t2"))], st(), [], TODAY)
    assert [(a.track_id, a.folder) for a in p.actions] == [("t2", "B"), ("t1", "A")]


def test_deleted_file_is_downloaded_again():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A", tr("t1"))], s, [], TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.actions[0].reason == "redownload"


def test_a_file_of_the_same_name_elsewhere_is_not_picked_up_by_name():
    # finding a moved file is the scanner's job (content key, spec §6.3); the planner never matches by name
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A", tr("t1"))], s, ["Library/Other/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.actions[0].reason == "redownload"


def test_a_file_gone_is_downloaded_again_at_once():
    s = st(t1=entry(status="missing", last_attempt="2026-10-20", file_gone="2026-10-20"))
    p = plan([pl("A", tr("t1"))], s, [], TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.actions[0].reason == "redownload"


def test_a_file_gone_takes_a_bought_file_first():
    s = st(t1=entry(status="missing", file_gone="2026-10-20"))
    p = plan([pl("A", tr("t1"))], s, ["Library/A/Artist - Title t1.wav"], TODAY)
    assert kinds(p) == [("adopt_bought", "t1")]


def test_an_offline_file_gets_nothing_not_even_the_weekly_check():
    s = st(t1=entry(status="not_lossless", path="/Volumes/Gig/A/x.aiff", online=False, last_upgrade_check=None))
    p = plan([pl("A", tr("t1"))], s, [], TODAY)
    assert kinds(p) == [] and p.never == [] and p.ambiguous == []


@pytest.mark.parametrize("files", [["Library/A/x.aiff"], []])
def test_a_held_file_gets_nothing_not_even_the_weekly_check(files):
    """Missing at the last scan, which couldn't rule out a move: as offline, whether or not `files` names it."""
    s = st(t1=entry(status="not_lossless", path="Library/A/x.aiff", held=True, last_upgrade_check=None))
    p = plan([pl("A", tr("t1"))], s, files, TODAY)
    assert kinds(p) == [] and p.never == [] and p.ambiguous == []


def test_a_file_moved_to_one_of_several_places_is_listed_and_nothing_done():
    s = st(t1=entry(status="not_lossless", path="Library/A/x.aiff", last_upgrade_check=None))
    s["ambiguous"] = {"t1": ["Library/B/x.aiff", "Library/C/x.aiff"]}
    p = plan([pl("A", tr("t1"))], s, ["Library/A/x.aiff", "Library/B/x.aiff", "Library/C/x.aiff"], TODAY)
    assert kinds(p) == []
    assert [(t.id, folder, files) for t, folder, files in p.ambiguous] == [
        ("t1", "A", ["Library/B/x.aiff", "Library/C/x.aiff"])]


# --- missing tracks and bought files ---

def test_missing_retried_only_after_seven_days():
    s6 = st(t1=entry(status="missing", last_attempt="2026-10-14"))
    s7 = st(t1=entry(status="missing", last_attempt="2026-10-13"))
    assert kinds(plan([pl("A", tr("t1"))], s6, [], TODAY)) == []
    p = plan([pl("A", tr("t1"))], s7, [], TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.actions[0].reason == "retry"


def test_missing_folder_change_is_state_only():
    s = st(t1=entry(status="missing", last_attempt="2026-10-20"))
    p = plan([pl("B", tr("t1"))], s, [], TODAY)
    assert kinds(p) == []
    assert p.state["tracks"]["t1"]["folder"] == "B"
    assert p.notes


def test_bought_file_for_missing_track():
    s = st(t1=entry(status="missing", last_attempt="2026-10-20"))
    p = plan([pl("A", tr("t1"))], s, ["Library/A/Artist - Title t1.wav"], TODAY)
    assert kinds(p) == [("adopt_bought", "t1")]
    assert p.actions[0].src == "Library/A/Artist - Title t1.wav"


def test_bought_file_replaces_not_lossless():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/Artist - Title t1.aiff"))
    files = ["Library/A/not_lossless/Artist - Title t1.aiff", "Library/A/artist - title t1.AIFF"]
    p = plan([pl("A", tr("t1"))], s, files, TODAY)
    assert kinds(p) == [("adopt_bought", "t1")]


def test_a_bought_file_next_to_the_current_file_is_adopted():
    s = st(t1=entry(status="not_lossless", path="Library/Sets/2024/x.aiff"))
    files = ["Library/Sets/2024/x.aiff", "Library/Sets/2024/Artist - Title t1.wav"]
    p = plan([pl("A", tr("t1"))], s, files, TODAY)
    assert kinds(p) == [("adopt_bought", "t1")] and p.actions[0].src == "Library/Sets/2024/Artist - Title t1.wav"


def test_a_bought_file_in_the_current_playlist_folder_is_adopted():
    # add_bought_file puts it there (replacement_dir); a crash before the adopt leaves exactly this
    s = st(t1=entry(status="not_lossless", path="Library/B/not_lossless/x.aiff"))
    files = ["Library/B/not_lossless/x.aiff", "Library/B/Artist - Title t1.aiff"]
    p = plan([pl("A", tr("t1"))], s, files, TODAY)
    assert kinds(p) == [("adopt_bought", "t1")] and p.actions[0].src == "Library/B/Artist - Title t1.aiff"


def test_a_bought_file_in_the_placement_folder_still_counts():
    s = st(t1=entry(status="not_lossless", path="Library/Sets/x.aiff"))
    p = plan([pl("A", tr("t1"))], s, ["Library/Sets/x.aiff", "Library/A/Artist - Title t1.wav"], TODAY)
    assert kinds(p) == [("adopt_bought", "t1")] and p.actions[0].src == "Library/A/Artist - Title t1.wav"


# --- upgrade checks ---

@pytest.mark.parametrize("last,expected", [
    (None, [("upgrade", "t1")]),
    ("2026-10-13", [("upgrade", "t1")]),
    ("2026-10-14", []),
])
def test_upgrade_check_every_seven_days(last, expected):
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check=last))
    assert kinds(plan([pl("A", tr("t1"))], s, ["Library/A/not_lossless/x.aiff"], TODAY)) == expected


def test_no_upgrade_check_when_not_in_any_playlist():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff"))
    assert kinds(plan([pl("A")], s, ["Library/A/not_lossless/x.aiff"], TODAY)) == []


def test_lossless_never_upgrade_checked():
    s = st(t1=entry(path="Library/A/x.aiff"))
    assert kinds(plan([pl("A", tr("t1"))], s, ["Library/A/x.aiff"], TODAY)) == []


# --- precedence table ---

@pytest.mark.parametrize("status,present,differs,expected", [
    ("lossless", True, False, ["-"]),
    ("lossless", True, True, ["-"]),
    ("lossless", False, False, ["acquire"]),
    ("lossless", False, True, ["acquire"]),
    ("not_lossless", True, False, ["upgrade"]),
    ("not_lossless", True, True, ["upgrade"]),
    ("not_lossless", False, True, ["acquire"]),
    ("fake_lossless", True, False, ["upgrade"]),
    ("missing", False, False, ["acquire"]),
    ("missing", False, True, ["acquire"]),
])
def test_rule_precedence(status, present, differs, expected):
    sub = "/not_lossless" if status in ("not_lossless", "fake_lossless") else ""
    path = f"Library/A{sub}/x.aiff"
    e = entry(status=status, path=path, last_attempt="2026-10-01", last_upgrade_check="2026-10-01")
    folder = "B" if differs else "A"
    p = plan([pl(folder, tr("t1"))], st(t1=e), [path] if present else [], TODAY)
    assert ([a.kind for a in p.actions] or ["-"]) == expected
    for a in p.actions:
        assert a.folder == folder


# --- ordering ---

def test_execution_order_and_playlist_priority():
    s = st(
        t2=entry(path="Library/A/b.aiff", title="Title t2"),
        t3=entry(status="not_lossless", path="Library/B/not_lossless/c.aiff", folder="B", title="Title t3"),
    )
    files = ["Library/A/b.aiff", "Library/B/not_lossless/c.aiff"]
    p = plan([pl("A", tr("t5"), tr("t1"), tr("t3")), pl("B", tr("t2"), tr("t4"))], s, files, TODAY)
    # t3 is first seen on line A (index 0, position 2), t2 on line B (index 1, position 0)
    assert kinds(p) == [
        ("acquire", "t5"), ("acquire", "t1"), ("acquire", "t4"),
        ("upgrade", "t3"),
    ]


# --- parked upgrades (spec "Upgrades", 2026-10-16) ---

PARKED = {"file": "Upgrades ready/A/Artist - Title t1.aiff", "source": "qobuz", "source_id": "q1",
          "source_format": "flac", "found": "2026-10-01", "alignment": {"result": "exact"}}


def test_no_upgrade_check_while_one_is_parked():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check="2026-10-01",
                    upgrade=PARKED))
    assert kinds(plan([pl("A", tr("t1"))], s, ["Library/A/not_lossless/x.aiff"], TODAY)) == []


def test_upgrade_check_again_after_discard_when_due():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check="2026-10-01",
                    upgrade=None, rejected_sources=["qobuz:q1"]))
    assert kinds(plan([pl("A", tr("t1"))], s, ["Library/A/not_lossless/x.aiff"], TODAY)) == [("upgrade", "t1")]


def test_entry_written_before_the_upgrade_field_is_checked():
    e = entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check="2026-10-01")
    assert "upgrade" not in e
    assert kinds(plan([pl("A", tr("t1"))], st(t1=e), ["Library/A/not_lossless/x.aiff"], TODAY)) == [("upgrade", "t1")]


def test_bought_file_still_wins_over_a_parked_upgrade():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/Artist - Title t1.aiff", upgrade=PARKED))
    files = ["Library/A/not_lossless/Artist - Title t1.aiff", "Library/A/Artist - Title t1.wav"]
    assert kinds(plan([pl("A", tr("t1"))], s, files, TODAY)) == [("adopt_bought", "t1")]


def test_files_named_by_a_pending_swap_are_never_adopted():
    s = st(t1=entry(status="missing", last_attempt="2026-10-01"))  # a file with its bought name is a swap's target
    s["pending"].append({"kind": "swap", "track_id": "t9", "target": "Library/A/Artist - Title t1.wav",
                         "staged": "s", "backup": "b", "parked": "p", "renames": [], "entry": None})
    p = plan([pl("A", tr("t1"))], s, ["Library/A/Artist - Title t1.wav"], TODAY)
    assert kinds(p) == [("acquire", "t1")]


def test_hidden_tracks_still_get_their_weekly_upgrade_check():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", hidden=True))
    assert kinds(plan([pl("A", tr("t1"))], s, ["Library/A/not_lossless/x.aiff"], TODAY)) == [("upgrade", "t1")]


def test_lossy_tracks_from_before_free_downloads_are_checked_once():
    e = entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check="2026-10-20")
    del e["free_downloads"]
    assert kinds(plan([pl("A", tr("t1"))], st(t1=e), ["Library/A/not_lossless/x.aiff"], TODAY)) == [("upgrade", "t1")]
    e["free_downloads"] = []
    assert kinds(plan([pl("A", tr("t1"))], st(t1=e), ["Library/A/not_lossless/x.aiff"], TODAY)) == []


# --- never download ---

def test_never_download_keeps_new_retry_and_redownload_out_of_the_plan():
    s = st(m=entry(status="missing", last_attempt="2026-09-01"), g=entry(path="Library/A/gone.aiff"))
    s["never"] = {k: {"artist": "Artist", "title": "x", "folder": "A", "at": "2026-10-18"} for k in ("n", "m", "g")}
    p = plan([pl("A", tr("n"), tr("m"), tr("g"), tr("ok"))], s, [], TODAY)
    assert kinds(p) == [("acquire", "ok")]
    assert [(a.kind, a.track_id, a.reason) for a in p.never] == [
        ("acquire", "n", "new"), ("acquire", "m", "retry"), ("acquire", "g", "redownload")]


def test_never_download_leaves_a_file_in_another_folder_alone():
    s = st(t1=entry(folder="B", path="Library/B/x.aiff"))
    s["never"] = {"t1": {"artist": "Artist", "title": "x", "folder": "B", "at": "2026-10-18"}}
    p = plan([pl("A", tr("t1"))], s, ["Library/B/x.aiff"], TODAY)
    assert kinds(p) == [] and p.never == []


# --- placement helpers (option A, spec §7) ---

@pytest.mark.parametrize("path,mirror", [
    ("Library/A/x.aiff", "A"),
    ("Library/A/not_lossless/x.aiff", "A"),
    ("Library/A/Not_Lossless/x.aiff", "A"),
    ("Library/Sets/2024/x.aiff", "Sets/2024"),
    ("Library/A/B/not_lossless/x.aiff", "A/B/not_lossless"),
    ("Library/x.aiff", ""),
])
def test_mirror_dir(path, mirror):
    assert mirror_dir(path) == mirror


@pytest.mark.parametrize("path,superseded,ready", [
    ("Library/A/not_lossless/x.aiff", "Superseded/A", "Upgrades ready/A"),
    ("Library/Sets/2024/x.aiff", "Superseded/Sets/2024", "Upgrades ready/Sets/2024"),
    ("Library/x.aiff", "Superseded", "Upgrades ready"),
])
def test_superseded_and_upgrades_ready_mirror_the_file_folder(path, superseded, ready):
    assert superseded_dir(path) == superseded
    assert upgrades_ready_dir(path) == ready


@pytest.mark.parametrize("path,status,where", [
    (None, "lossless", "Library/A"),  # no file: the placement folder
    (None, "not_lossless", "Library/A/not_lossless"),
    ("Library/B/not_lossless/x.aiff", "lossless", "Library/B"),  # lossless leaves a playlist folder's not_lossless/
    ("Library/B/not_lossless/x.aiff", "not_lossless", "Library/B/not_lossless"),
    ("Library/B/x.aiff", "fake_lossless", "Library/B/not_lossless"),
    ("Library/Sets/2024/x.aiff", "lossless", "Library/Sets/2024"),  # anywhere else: the file's own folder
    ("Library/Sets/2024/x.aiff", "not_lossless", "Library/Sets/2024"),
    ("Library/A/B/not_lossless/x.aiff", "lossless", "Library/A/B/not_lossless"),
    ("Library/x.aiff", "lossless", "Library"),
])
def test_replacement_dir(path, status, where):
    e = entry(folder="A", path=path) if path else entry(folder="A", status="missing")
    assert replacement_dir(e, status) == where


# --- tidy-up targets (plan library stage 2, group 2) ---

def test_tidy_target_keeps_the_file_name_and_folds_lossy_into_not_lossless():
    assert tidy_target(entry("F", path="Library/G/Artist - Title t1.aiff")) == "Library/F/Artist - Title t1.aiff"
    lossy = entry("F", status="not_lossless", path="Library/G/Artist - Title t1.m4a")
    assert tidy_target(lossy) == "Library/F/not_lossless/Artist - Title t1.m4a"
    assert tidy_target(entry("F", status="fake_lossless", path="Library/F/x.flac")) == "Library/F/not_lossless/x.flac"
    assert tidy_target(entry("F", path="Library/G/my edit (final).aiff")) == "Library/F/my edit (final).aiff"


def test_tidy_target_folder_overrides_the_entry_folder():
    assert tidy_target(entry("F", path="Library/F/a.aiff"), "New") == "Library/New/a.aiff"


@pytest.mark.parametrize("e", [
    entry("F", status="missing"),
    entry("F", path="Library/G/a.aiff", in_playlists=False),
    entry("F", path="Superseded/G/a.aiff"),
    entry("F", path="Imports/G/a.aiff"),
])
def test_tidy_target_none_without_a_file_a_playlist_or_outside_library(e):
    assert tidy_target(e) is None


def tidy_entry(folder, path, file_id=1, placed_by="app", **kw):
    return entry(folder, path=path, file_id=file_id, placed_by=placed_by, **{"online": True, "held": False, **kw})


def tidy_state(files=None, ambiguous=None, **tracks):
    s = st(**tracks)
    s["files"] = sorted(e["path"] for e in tracks.values() if e.get("path")) if files is None else files
    s["ambiguous"] = ambiguous or {}
    return s


def test_tidy_rows_lists_files_outside_their_target_and_ticks_by_placed_by():
    s = tidy_state(a=tidy_entry("F", "Library/G/a.aiff", 1), b=tidy_entry("F", "Library/G/b.aiff", 2, "user"),
                   c=tidy_entry("F", "Library/H/c.aiff", 3, "import"), d=tidy_entry("F", "Library/F/d.aiff", 4))
    rows = tidy_rows(s)
    assert rows == [TidyRow("a", 1, "Library/G/a.aiff", "Library/F/a.aiff", "app", None),
                    TidyRow("b", 2, "Library/G/b.aiff", "Library/F/b.aiff", "user", None),
                    TidyRow("c", 3, "Library/H/c.aiff", "Library/F/c.aiff", "import", None)]
    assert [r.ticked for r in rows] == [True, False, False]


def test_tidy_rows_a_case_only_folder_difference_is_no_move():
    assert tidy_rows(tidy_state(a=tidy_entry("Hard_Bounce", "Library/hard_bounce/a.aiff"))) == []


def test_tidy_rows_a_file_in_a_subfolder_of_its_target_folder_is_a_row():
    rows = tidy_rows(tidy_state(a=tidy_entry("F", "Library/F/sub/a.aiff")))
    assert [(r.src, r.dst, r.skip) for r in rows] == [("Library/F/sub/a.aiff", "Library/F/a.aiff", None)]


def test_tidy_rows_a_lossless_file_leaves_not_lossless():
    rows = tidy_rows(tidy_state(a=tidy_entry("F", "Library/F/not_lossless/a.aiff")))
    assert [r.dst for r in rows] == ["Library/F/a.aiff"]


def test_tidy_rows_skip_reasons_in_order():
    s = tidy_state(
        files=["Library/G/c.aiff", "Library/G/e.aiff", "Library/F/e.aiff"],
        ambiguous={"c": ["Library/X/c.aiff", "Library/Y/c.aiff"]},
        a=tidy_entry("F", "Library/G/a.aiff", 1, online=False, held=True),  # offline wins over held
        b=tidy_entry("F", "Library/G/b.aiff", 2, held=True),
        c=tidy_entry("F", "Library/G/c.aiff", 3),  # ambiguous
        d=tidy_entry("F", "Library/G/d.aiff", 4),  # not in state["files"]
        e=tidy_entry("F", "Library/G/e.aiff", 5))  # Library/F/e.aiff is taken
    assert [(r.track_id, r.skip) for r in tidy_rows(s)] == [
        ("a", "offline"), ("b", "not_found"), ("c", "not_found"), ("d", "not_found"), ("e", "name_taken")]


def test_tidy_rows_a_taken_name_is_matched_in_any_case():
    s = tidy_state(files=["Library/G/A.aiff", "Library/f/a.AIFF"], a=tidy_entry("F", "Library/G/A.aiff"))
    assert [r.skip for r in tidy_rows(s)] == ["name_taken"]


def test_tidy_rows_two_files_with_one_target_name_the_second_is_taken():
    s = tidy_state(a=tidy_entry("F", "Library/G/x.aiff", 1), b=tidy_entry("F", "Library/H/x.aiff", 2))
    assert [(r.src, r.skip) for r in tidy_rows(s)] == [("Library/G/x.aiff", None), ("Library/H/x.aiff", "name_taken")]


def test_tidy_rows_a_name_another_row_frees_still_counts_as_taken():
    # b would leave Library/F/x.aiff for G; a wants that name: one more tidy-up moves a
    s = tidy_state(a=tidy_entry("F", "Library/A/x.aiff", 1), b=tidy_entry("G", "Library/F/x.aiff", 2))
    assert [(r.track_id, r.skip) for r in tidy_rows(s)] == [("a", "name_taken"), ("b", None)]


def test_tidy_rows_go_by_source_folder_then_file_name_folded():
    s = tidy_state(a=tidy_entry("F", "Library/b/Z.aiff", 1), b=tidy_entry("F", "Library/B/a.aiff", 2),
                   c=tidy_entry("F", "Library/A/y.aiff", 3))
    assert [r.track_id for r in tidy_rows(s)] == ["c", "b", "a"]


def test_tidy_rows_only_and_folders():
    s = tidy_state(a=tidy_entry("F", "Library/G/a.aiff", 1), b=tidy_entry("F", "Library/G/b.aiff", 2),
                   c=tidy_entry("F", "Library/F/c.aiff", 3))
    assert [r.track_id for r in tidy_rows(s, only={"b"})] == ["b"]
    rows = tidy_rows(s, {"a": "G", "c": "New"})
    assert [(r.track_id, r.dst) for r in rows] == [("c", "Library/New/c.aiff"), ("b", "Library/F/b.aiff")]
    assert tidy_rows(s, {"a": "G", "c": "New"}, only=["c"]) == rows[:1]


def test_tidy_rows_leave_files_without_a_target_alone():
    s = tidy_state(a=tidy_entry("F", "Library/G/a.aiff", in_playlists=False),
                   b=entry("F", status="missing"), c=tidy_entry("F", "Upgrades ready/G/c.aiff"))
    assert tidy_rows(s) == []


def test_out_of_place_counts_only_the_default_ticks():
    s = tidy_state(files=["Library/G/a.aiff", "Library/G/b.aiff", "Library/G/d.aiff"],
                   a=tidy_entry("F", "Library/G/a.aiff", 1), b=tidy_entry("F", "Library/G/b.aiff", 2, "user"),
                   c=tidy_entry("F", "Library/G/c.aiff", 3), d=tidy_entry("F", "Library/G/d.aiff", 4, online=False),
                   e=tidy_entry("F", "Library/F/e.aiff", 5))
    assert len(tidy_rows(s)) == 4 and out_of_place(s) == 1


def test_tidy_rows_app_placed_rows_claim_a_target_name_before_the_users_rows():
    s = tidy_state(a=tidy_entry("F", "Library/A/x.aiff", 1, "user"), b=tidy_entry("F", "Library/B/x.aiff", 2),
                   c=tidy_entry("F", "Library/C/x.aiff", 3, "import"))
    rows = tidy_rows(s)
    assert [(r.track_id, r.skip, r.ticked) for r in rows] == [
        ("a", "name_taken", False), ("b", None, True), ("c", "name_taken", False)]
    assert out_of_place(s) == 1
    s = tidy_state(a=tidy_entry("F", "Library/A/x.aiff", 1, "user"), c=tidy_entry("F", "Library/C/x.aiff", 3, "import"))
    assert [(r.track_id, r.skip) for r in tidy_rows(s)] == [("a", None), ("c", "name_taken")]


def test_tidy_rows_and_target_fold_nfd_against_nfc():
    nfc, nfd = "Caf\u00e9", unicodedata.normalize("NFD", "Caf\u00e9")
    assert nfc != nfd
    # the folder on disk in NFD, the playlist folder in NFC: no move
    assert tidy_rows(tidy_state(a=tidy_entry(nfc, f"Library/{nfd}/a.aiff"))) == []
    # the file name keeps its own form byte for byte
    assert tidy_target(entry("F", path=f"Library/G/{nfd}.aiff")) == f"Library/F/{nfd}.aiff"
    # a taken name and the file's own path are matched in either form
    s = tidy_state(files=[f"Library/G/{nfd}.aiff", f"Library/F/{nfc}.aiff"], a=tidy_entry("F", f"Library/G/{nfc}.aiff"))
    assert [r.skip for r in tidy_rows(s)] == ["name_taken"]
    s = tidy_state(files=[f"Library/G/{nfd}.aiff"], a=tidy_entry("F", f"Library/G/{nfc}.aiff"))
    assert [r.skip for r in tidy_rows(s)] == [None]
