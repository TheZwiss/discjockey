from datetime import date

import pytest

from discjockey.models import FetchedPlaylist, PlaylistLine, SpotifyTrack
from discjockey.planner import plan

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


# --- moves, adopts, re-downloads ---

def test_move_when_priority_changes():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("B", tr("t1"))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [("move", "t1")]
    assert (p.actions[0].src, p.actions[0].dest_dir) == ("Library/A/x.aiff", "Library/B")


def test_move_keeps_not_lossless_subfolder():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check="2026-10-20"))
    p = plan([pl("B", tr("t1"))], s, ["Library/A/not_lossless/x.aiff"], TODAY)
    assert kinds(p) == [("move", "t1")]
    assert p.actions[0].dest_dir == "Library/B/not_lossless"


def test_renamed_folder_moves_tracks():
    s = st(t1=entry(folder="Bounce", path="Library/Bounce/x.aiff"))
    p = plan([pl("Bouncy", tr("t1"))], s, ["Library/Bounce/x.aiff"], TODAY)
    assert p.actions[0].dest_dir == "Library/Bouncy"


def test_folder_case_change_does_not_move():
    s = st(t1=entry(folder="bounce", path="Library/bounce/x.aiff"))
    p = plan([pl("Bounce", tr("t1"))], s, ["Library/bounce/x.aiff"], TODAY)
    assert kinds(p) == []


def test_move_and_upgrade_in_same_run():
    s = st(t1=entry(status="not_lossless", path="Library/A/not_lossless/x.aiff", last_upgrade_check="2026-10-01"))
    p = plan([pl("B", tr("t1"))], s, ["Library/A/not_lossless/x.aiff"], TODAY)
    assert kinds(p) == [("move", "t1"), ("upgrade", "t1")]


def test_deleted_file_is_downloaded_again():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A", tr("t1"))], s, [], TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.actions[0].reason == "redownload"


def test_hand_moved_file_is_adopted():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A", tr("t1"))], s, ["Library/Other/x.aiff"], TODAY)
    assert kinds(p) == [("adopt", "t1")]
    assert (p.actions[0].src, p.actions[0].dest_dir) == ("Library/Other/x.aiff", "Library/A")


def test_adopt_ignores_case():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A", tr("t1"))], s, ["Library/Other/X.AIFF"], TODAY)
    assert kinds(p) == [("adopt", "t1")]


def test_two_candidate_files_are_ambiguous():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([pl("A", tr("t1"))], s, ["Library/B/x.aiff", "Library/C/x.aiff"], TODAY)
    assert kinds(p) == []
    assert p.ambiguous[0][2] == ["Library/B/x.aiff", "Library/C/x.aiff"]


def test_file_owned_by_other_entry_is_not_adopted():
    s = st(t1=entry(path="Library/A/x.aiff"), t2=entry(folder="B", path="Library/B/x.aiff", title="Title t2"))
    p = plan([pl("A", tr("t1")), pl("B", tr("t2"))], s, ["Library/B/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "t1")]


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
    ("lossless", True, True, ["move"]),
    ("lossless", False, False, ["acquire"]),
    ("lossless", False, True, ["acquire"]),
    ("not_lossless", True, False, ["upgrade"]),
    ("not_lossless", True, True, ["move", "upgrade"]),
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
        ("move", "t3"), ("move", "t2"),
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
    s = st(t1=entry(path="Library/A/x.aiff"))  # gone from disk; a file with its name is a pending swap's target
    s["pending"].append({"kind": "swap", "track_id": "t9", "target": "Library/C/x.aiff", "staged": "s",
                         "backup": "b", "parked": "p", "renames": [], "entry": None})
    p = plan([pl("A", tr("t1"))], s, ["Library/C/x.aiff"], TODAY)
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


def test_never_download_does_not_stop_moves_of_a_file_that_exists():
    s = st(t1=entry(folder="B", path="Library/B/x.aiff"))
    s["never"] = {"t1": {"artist": "Artist", "title": "x", "folder": "B", "at": "2026-10-18"}}
    p = plan([pl("A", tr("t1"))], s, ["Library/B/x.aiff"], TODAY)
    assert kinds(p) == [("move", "t1")] and p.never == []
