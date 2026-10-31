import unicodedata
from datetime import date

import pytest

from discjockey.models import FetchedPlaylist, PlaylistLine, SourceTrack
from discjockey.planner import (TidyRow, desired_folders, mirror_dir, out_of_place, plan, replacement_dir,
                                superseded_dir, tidy_rows, tidy_target, upgrades_ready_dir)
from discjockey.titles import split_title

TODAY = date(2026, 10, 20)


def tr(id, title=None, artist="Artist", dur=180000, isrc=None):
    return SourceTrack(id, title or f"Title {id}", (artist,), "Album", None, dur, isrc)


def pl(folder, *tracks, skipped=()):
    return FetchedPlaylist(PlaylistLine(folder, f"pl{folder}", 1), list(tracks), list(skipped))


def qb(id, title="Title t1", artist="Artist", dur=180000, isrc=None, streamable=True):
    """A Qobuz playlist's track (its key is `qobuz:<id>`)."""
    return SourceTrack(id, title, (artist,), "Album", None, dur, isrc, service="qobuz", streamable=streamable)


def qpl(folder, *tracks):
    return FetchedPlaylist(PlaylistLine(folder, "900000100", 1, "qobuz"), list(tracks), [])


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


# --- linking across services (spec §9.2): token, ISRC, name and length, new song ---

NAME_NOTE = ("Artist - Title t1: same song as one you already have (same artist, title and length), "
             "not downloaded again.")


def test_a_token_links_first_even_when_another_song_has_its_isrc():
    s = st(t1=entry(path="Library/A/x.aiff", isrc="DE1"), **{"qobuz:900000001": entry(path="Library/A/y.aiff")})
    p = plan([qpl("A", qb("900000001", isrc="DE1"))], s, ["Library/A/x.aiff", "Library/A/y.aiff"], TODAY)
    assert kinds(p) == [] and p.notes == []
    assert p.state["tracks"]["t1"]["aliases"] == [] and p.state["tracks"]["qobuz:900000001"]["aliases"] == []
    assert p.state["tracks"]["t1"]["in_playlists"] is False


def test_a_spotify_and_a_qobuz_playlist_holding_one_song_plan_one_action():
    p = plan([pl("A", tr("t1", isrc="DE1")), qpl("B", qb("900000001", isrc="DE1", dur=181000))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1")]
    assert p.actions[0].folder == "A" and p.actions[0].aliases == ("qobuz:900000001",)
    assert p.actions[0].qobuz_id == "900000001"


def test_the_first_line_s_token_keys_the_song():
    p = plan([qpl("B", qb("900000001", isrc="DE1")), pl("A", tr("t1", isrc="DE1"))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "qobuz:900000001")]
    assert p.actions[0].folder == "B" and p.actions[0].aliases == ("t1",)


def test_a_qobuz_track_links_to_a_stored_spotify_song_by_isrc():
    s = st(t1=entry(path="Library/A/x.aiff", isrc="DE1"))
    p = plan([qpl("A", qb("900000001", isrc="de1", dur=182000))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == []
    assert p.state["tracks"]["t1"]["aliases"] == ["qobuz:900000001"]
    assert "ISRC de1" in p.notes[0]


def test_a_second_playlist_with_a_linked_track_resolves_by_its_token():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([qpl("A", qb("900000001")), qpl("B", qb("900000001"))], s, ["Library/A/x.aiff"], TODAY)
    assert p.state["tracks"]["t1"]["aliases"] == ["qobuz:900000001"]
    assert p.notes == [NAME_NOTE]


@pytest.mark.parametrize("dur,linked", [(183000, True), (177000, True), (183100, False), (176900, False)])
def test_a_track_without_isrc_links_by_name_and_length(dur, linked):
    s = st(t1=entry(path="Library/A/x.aiff", isrc="DE1"))
    p = plan([qpl("A", qb("900000001", dur=dur))], s, ["Library/A/x.aiff"], TODAY)
    if linked:
        assert kinds(p) == [] and p.notes == [NAME_NOTE]
        assert p.state["tracks"]["t1"]["aliases"] == ["qobuz:900000001"]
    else:
        assert kinds(p) == [("acquire", "qobuz:900000001")] and p.notes == []
        assert p.state["tracks"]["t1"]["aliases"] == []


def test_a_name_link_compares_names_normalised_as_the_qobuz_search_does():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([qpl("A", qb("900000001", title="TITLE T1 (Original Mix)", artist="artist"))], s,
             ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [] and p.state["tracks"]["t1"]["aliases"] == ["qobuz:900000001"]


def test_a_track_with_an_isrc_never_links_by_name():
    s = st(t1=entry(path="Library/A/x.aiff"))  # stored without an ISRC
    p = plan([qpl("A", qb("900000001", isrc="DE9"))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "qobuz:900000001")]
    assert p.state["tracks"]["t1"]["aliases"] == [] and p.notes == []


def test_a_different_name_doesnt_link():
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([qpl("A", qb("900000001", title="Title t2"), qb("900000002", artist="Other"))], s,
             ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "qobuz:900000001"), ("acquire", "qobuz:900000002")]


def test_two_new_tracks_without_isrc_link_by_name_in_one_run():
    p = plan([pl("A", tr("t1", title="Title t1")), qpl("B", qb("900000001", dur=181000))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1")]
    assert p.actions[0].aliases == ("qobuz:900000001",) and p.notes == []


def test_desired_folders_links_the_same_way():
    s = st(t1=entry(folder="A", path="Library/A/x.aiff"))
    assert desired_folders([qpl("B", qb("900000001"))], s) == {"t1": "B"}
    assert s["tracks"]["t1"]["aliases"] == []  # input state untouched


def test_a_song_without_artist_or_title_never_links_by_name():
    # two artist-less tracks with one title stay two songs (nothing says they are the same song)
    p = plan([pl("A", SourceTrack("t1", "Same", (), "Album", None, 180000, None),
                 SourceTrack("t2", "Same", (), "Album", None, 180000, None))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1"), ("acquire", "t2")] and p.notes == []
    # nor does a stored song without an artist take a new one
    s = st(t1=entry(path="Library/A/x.aiff", artist=""))
    p = plan([pl("A", SourceTrack("t2", "Title t1", (), "Album", None, 180000, None))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "t2")] and p.state["tracks"]["t1"]["aliases"] == []


def test_a_track_of_unknown_length_never_links_by_name():
    # a Qobuz item without `duration` has length 0: that is not a real length, on either side
    p = plan([pl("A", tr("t1", dur=0)), qpl("B", qb("900000001", dur=0))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1"), ("acquire", "qobuz:900000001")] and p.notes == []
    s = st(t1=entry(path="Library/A/x.aiff", duration_ms=0))
    p = plan([qpl("A", qb("900000001", dur=1000))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "qobuz:900000001")] and p.state["tracks"]["t1"]["aliases"] == []
    s = st(t1=entry(path="Library/A/x.aiff"))
    p = plan([qpl("A", qb("900000001", dur=0))], s, ["Library/A/x.aiff"], TODAY)
    assert kinds(p) == [("acquire", "qobuz:900000001")] and p.notes == []


# --- the exact Qobuz id on actions (I5) ---

def test_a_track_qobuz_won_t_deliver_gives_no_qobuz_id():
    p = plan([qpl("A", qb("900000001", isrc="DE1", streamable=False))], st(), [], TODAY)
    assert [(a.track_id, a.qobuz_id) for a in p.actions] == [("qobuz:900000001", None)]


def test_the_first_streamable_qobuz_track_of_the_song_gives_its_id():
    p = plan([qpl("A", qb("900000001", isrc="DE1", streamable=False)), pl("B", tr("t1", isrc="DE1")),
              qpl("C", qb("900000002", isrc="DE1")), qpl("D", qb("900000003", isrc="DE1"))], st(), [], TODAY)
    assert [(a.track_id, a.qobuz_id) for a in p.actions] == [("qobuz:900000001", "900000002")]
    assert p.actions[0].aliases == ("t1", "qobuz:900000002", "qobuz:900000003")


def test_an_upgrade_check_gets_the_qobuz_id_a_bought_file_doesnt():
    s = st(t1=entry(path="Library/A/x.mp3", status="not_lossless", isrc="DE1"),
           t2=entry(path="Library/A/y.mp3", status="not_lossless", title="Title t2", isrc="DE2"))
    p = plan([qpl("A", qb("900000001", isrc="DE1"), qb("900000002", title="Title t2", isrc="DE2"))], s,
             ["Library/A/x.mp3", "Library/A/y.mp3", "Library/A/Artist - Title t2.aiff"], TODAY)
    assert [(a.kind, a.track_id, a.qobuz_id) for a in p.actions] == [
        ("adopt_bought", "t2", None), ("upgrade", "t1", "900000001")]


def test_a_retry_gets_the_qobuz_id():
    s = st(t1=entry(status="missing", last_attempt="2026-10-01", aliases=["qobuz:900000001"]))
    p = plan([qpl("A", qb("900000001"))], s, [], TODAY)
    assert [(a.kind, a.reason, a.qobuz_id) for a in p.actions] == [("acquire", "retry", "900000001")]


def test_a_stored_qobuz_alias_alone_gives_no_qobuz_id():
    s = st(t1=entry(status="missing", last_attempt="2026-10-01", aliases=["qobuz:900000001"]))
    p = plan([pl("A", tr("t1"))], s, [], TODAY)
    assert [(a.kind, a.qobuz_id) for a in p.actions] == [("acquire", None)]


# --- the playlist's own upload on actions (stage 6 I5) ---

def sc(id, title="Title t1", artist="Artist", dur=180000, isrc=None, streamable=True, account_only=False):
    """A SoundCloud playlist's track as the source parses it (its key is `soundcloud:<id>`)."""
    return SourceTrack(id, title, (artist,), "", None, dur, isrc, service="soundcloud", streamable=streamable,
                       account_only=account_only)


def ytm(id, title="Title t1", artist="Artist", dur=180000):
    """A YouTube Music playlist's song entry: no album, no ISRC (stage 6 D6)."""
    return SourceTrack(id, title, (artist,), "", None, dur, None, service="youtube_music")


def scpl(folder, *tracks):
    return FetchedPlaylist(PlaylistLine(folder, "example-label/sets/example-set", 1, "soundcloud"), list(tracks), [])


def ytpl(folder, *tracks):
    return FetchedPlaylist(PlaylistLine(folder, "PLEXAMPLE0001", 1, "youtube_music"), list(tracks), [])


def test_a_split_soundcloud_title_and_a_spotify_track_of_the_same_length_are_one_song():
    artists, title = split_title("Example Artist - Example Title [FREE DL]", "example-label")
    p = plan([pl("A", tr("t1", title="Example Title", artist="Example Artist", dur=180000)),
              scpl("B", SourceTrack("900000101", title, artists, "", None, 182000, None, service="soundcloud"))],
             st(), [], TODAY)
    assert [(a.track_id, a.aliases) for a in p.actions] == [("t1", ("soundcloud:900000101",))]


def test_a_soundcloud_track_3_1_s_longer_is_another_song():
    p = plan([pl("A", tr("t1")), scpl("B", sc("900000101", dur=183100))], st(), [], TODAY)
    assert kinds(p) == [("acquire", "t1"), ("acquire", "soundcloud:900000101")]


def test_a_soundcloud_track_with_a_publisher_isrc_links_by_isrc():
    p = plan([pl("A", tr("t1", isrc="DE1")), scpl("B", sc("900000101", title="Other words", isrc="de1", dur=181000))],
             st(), [], TODAY)
    assert [(a.track_id, a.aliases) for a in p.actions] == [("t1", ("soundcloud:900000101",))]


def test_a_youtube_music_song_links_to_a_qobuz_track_by_name():
    p = plan([qpl("A", qb("900000001")), ytpl("B", ytm("EXAMPLEid01", dur=179000))], st(), [], TODAY)
    a, = p.actions
    assert (a.track_id, a.aliases, a.qobuz_id) == ("qobuz:900000001", ("youtube_music:EXAMPLEid01",), "900000001")
    assert a.upload == ytm("EXAMPLEid01", dur=179000)


def test_the_upload_is_the_first_streamable_soundcloud_or_youtube_music_track_of_the_song():
    p = plan([scpl("A", sc("900000101", streamable=False)), ytpl("B", ytm("EXAMPLEid01")),
              scpl("C", sc("900000102"))], st(), [], TODAY)
    a, = p.actions
    assert a.track_id == "soundcloud:900000101" and a.upload.key == "youtube_music:EXAMPLEid01"


def test_a_blocked_soundcloud_track_gives_no_upload():
    p = plan([scpl("A", sc("900000101", streamable=False))], st(), [], TODAY)
    assert [(a.track_id, a.upload) for a in p.actions] == [("soundcloud:900000101", None)]


def test_a_go_plus_only_track_is_still_the_upload():
    # the acquirer decides how it may be fetched (only through the account, D9)
    p = plan([scpl("A", sc("900000101", account_only=True))], st(), [], TODAY)
    assert p.actions[0].upload.account_only is True


def test_a_spotify_first_song_with_a_later_soundcloud_track_gets_that_upload():
    p = plan([pl("A", tr("t1")), scpl("B", sc("900000101", dur=181000))], st(), [], TODAY)
    a, = p.actions
    assert (a.track_id, a.track.service, a.upload.key) == ("t1", "spotify", "soundcloud:900000101")


def test_an_upgrade_check_gets_the_upload_a_bought_file_doesnt():
    s = st(t1=entry(path="Library/A/x.mp3", status="not_lossless"),
           t2=entry(path="Library/A/y.mp3", status="not_lossless", title="Title t2"))
    p = plan([scpl("A", sc("900000101", title="Title t1"), sc("900000102", title="Title t2"))], s,
             ["Library/A/x.mp3", "Library/A/y.mp3", "Library/A/Artist - Title t2.aiff"], TODAY)
    assert [(a.kind, a.track_id, a.upload and a.upload.id) for a in p.actions] == [
        ("adopt_bought", "t2", None), ("upgrade", "t1", "900000101")]


def test_a_stored_soundcloud_alias_alone_gives_no_upload():
    s = st(t1=entry(status="missing", last_attempt="2026-10-01", aliases=["soundcloud:900000101"]))
    p = plan([pl("A", tr("t1"))], s, [], TODAY)
    assert [(a.kind, a.upload) for a in p.actions] == [("acquire", None)]


def test_spotify_and_qobuz_input_carries_no_upload():
    p = plan([pl("A", tr("t1"), tr("t2", isrc="DE2")), qpl("B", qb("900000001", title="Title t3"))], st(), [], TODAY)
    assert [(a.track_id, a.upload) for a in p.actions] == [("t1", None), ("t2", None), ("qobuz:900000001", None)]


def test_spotify_only_input_plans_as_before():
    s = st(t1=entry(path="Library/A/x.mp3", status="not_lossless", isrc="DE1"))
    p = plan([pl("A", tr("t9", isrc="DE1"), tr("t2", isrc="DE2"), tr("t3"))], s, ["Library/A/x.mp3"], TODAY)
    assert [(a.kind, a.track_id, a.aliases, a.qobuz_id) for a in p.actions] == [
        ("acquire", "t2", (), None), ("acquire", "t3", (), None), ("upgrade", "t1", (), None)]
    assert p.state["tracks"]["t1"]["aliases"] == ["t9"]


def test_a_spotify_track_without_isrc_and_a_new_id_joins_a_stored_song_by_name():
    # the one intended change for Spotify-only input (spec 9.2): same artist, title and length (+-3 s)
    s = st(t1=entry(path="Library/A/x.mp3", status="not_lossless"))
    p = plan([pl("A", tr("t9", title="Title t1", dur=182000))], s, ["Library/A/x.mp3"], TODAY)
    assert [(a.kind, a.track_id, a.aliases) for a in p.actions] == [("upgrade", "t1", ())]
    assert p.state["tracks"]["t1"]["aliases"] == ["t9"] and p.notes == [NAME_NOTE]
    assert "t9" not in p.state["tracks"]


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
    assert [(key, t.id, folder, files) for key, t, folder, files in p.ambiguous] == [
        ("t1", "t1", "A", ["Library/B/x.aiff", "Library/C/x.aiff"])]


def test_an_ambiguous_song_is_listed_under_its_song_key():
    several = ["Library/B/x.aiff", "Library/C/x.aiff"]
    files = ["Library/A/x.aiff", *several]
    s = st(**{"qobuz:900000001": entry(status="not_lossless", path="Library/A/x.aiff", last_upgrade_check=None)})
    s["ambiguous"] = {"qobuz:900000001": several}
    p = plan([qpl("A", qb("900000001"))], s, files, TODAY)
    assert [(key, t.key) for key, t, _folder, _files in p.ambiguous] == [("qobuz:900000001", "qobuz:900000001")]
    # a song known from Spotify and linked by ISRC to the Qobuz track the playlist holds: the song's key, not the track's
    s = st(t1=entry(status="not_lossless", path="Library/A/x.aiff", isrc="DE1", last_upgrade_check=None))
    s["ambiguous"] = {"t1": several}
    p = plan([qpl("A", qb("900000001", isrc="DE1"))], s, files, TODAY)
    assert [(key, t.key) for key, t, _folder, _files in p.ambiguous] == [("t1", "qobuz:900000001")]


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


IMPORT = "/Volumes/Example/Music"  # an import folder: its files have absolute snapshot paths


def test_tidy_target_of_a_file_in_an_import_folder_is_its_playlist_folder_in_library():
    assert tidy_target(entry("F", path=f"{IMPORT}/House/a.flac")) == "Library/F/a.flac"
    assert tidy_target(entry("F", status="not_lossless", path=f"{IMPORT}/b.mp3")) == "Library/F/not_lossless/b.mp3"


def test_tidy_rows_an_import_file_in_a_playlist_is_an_unticked_row():
    rows = tidy_rows(tidy_state(a=tidy_entry("F", f"{IMPORT}/House/a.flac", 1, "import")))
    assert rows == [TidyRow("a", 1, f"{IMPORT}/House/a.flac", "Library/F/a.flac", "import", None)]
    assert not rows[0].ticked


def test_tidy_rows_an_offline_import_file_is_offline_and_a_taken_name_is_name_taken():
    s = tidy_state(files=[f"{IMPORT}/b.flac", "Library/F/b.flac"],
                   a=tidy_entry("F", f"{IMPORT}/a.flac", 1, "import", online=False),
                   b=tidy_entry("F", f"{IMPORT}/b.flac", 2, "import"))
    assert [(r.track_id, r.skip) for r in tidy_rows(s)] == [("a", "offline"), ("b", "name_taken")]


def test_a_song_of_the_users_own_has_no_tidy_target():
    own = tidy_entry(None, f"{IMPORT}/c.flac", 3, "import", in_playlists=False)
    assert tidy_target(own) is None and tidy_rows(tidy_state(**{"local:1": own})) == []


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


def test_tidy_rows_a_held_row_of_another_song_at_the_target_takes_the_name():
    # b's file is missing at the last scan (held): not on disk, but its row still has the path
    s = tidy_state(files=["Library/G/a.aiff"], a=tidy_entry("F", "Library/G/a.aiff", 1),
                   b=tidy_entry("X", "Library/F/a.aiff", 2, held=True))
    assert [(r.track_id, r.skip) for r in tidy_rows(s) if r.track_id == "a"] == [("a", "name_taken")]


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


# --- the user's own songs (plan library stage 4, I4) ---

IMPORTED = "/Volumes/Example/Music"


def own_entry(n, title="Night Drive", artist="Example Artist", dur=200000, status="lossless", import_state="done",
              first_seen="2026-10-01T10:00:00", **kw):
    """A song of the user's own: an imported file in no playlist."""
    e = entry(None, status=status, title=title, artist=artist, duration_ms=dur, in_playlists=False, source="manual",
              source_id=None, source_format="mp3" if status in ("not_lossless", "fake_lossless") else "flac",
              path=f"{IMPORTED}/{artist} - {title} {n}.mp3", file_id=100 + n, placed_by="import", online=True,
              held=False, import_state=import_state, first_seen=first_seen, last_attempt=None)
    e.update(kw)
    return e


def own_state(*playlist, decisions=None, **own):
    """A state with own songs (`local:<n>` keys, given as n1=…, n2=…) and playlist songs ((key, entry) pairs)."""
    s = st()
    s["tracks"] = {f"local:{k[1:]}": e for k, e in own.items()} | dict(playlist)
    s["decisions"] = decisions or {"same_song": [], "keep_both": []}
    return s


def files_of(s):
    return [e["path"] for e in s["tracks"].values() if e.get("path")]


def night(id="t1", dur=200000, artist="Example Artist", isrc=None, title="Night Drive"):
    return tr(id, title, artist, dur, isrc)


def test_a_new_track_certainly_an_own_song_links_to_it_with_a_note():
    s = own_state(n1=own_entry(1))
    p = plan([pl("A", night(dur=201000))], s, files_of(s), TODAY)
    assert kinds(p) == [] and p.questions == []
    assert p.state["tracks"]["local:1"]["aliases"] == ["t1"]
    assert p.state["tracks"]["local:1"]["in_playlists"] is True
    assert p.notes == ["Example Artist - Night Drive: the same song as a file of yours, not downloaded."]


def test_an_isrc_link_to_an_own_song_keeps_the_three_second_check():
    s = own_state(n1=own_entry(1, title="Something Else", isrc="DEX1"))
    p = plan([pl("A", night(dur=202500, isrc="dex1"))], s, files_of(s), TODAY)
    assert p.state["tracks"]["local:1"]["aliases"] == ["t1"]
    p = plan([pl("A", night(dur=203500, isrc="DEX1"))], s, files_of(s), TODAY)
    assert kinds(p) == [("acquire", "t1")]


def test_two_different_isrcs_never_link_to_an_own_song_by_name():
    s = own_state(n1=own_entry(1, isrc="DEX2"))
    p = plan([pl("A", night(isrc="DEX1"))], s, files_of(s), TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.questions == []


def test_a_plausible_own_song_holds_the_new_track_with_a_question():
    s = own_state(n1=own_entry(1, artist="Another Artist", dur=201000))
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert kinds(p) == []
    [q] = p.questions
    assert (q.song_key, q.folder, q.own_key, q.file_id, q.why, q.delta_s) == ("t1", "A", "local:1", 101, "artist", 1)
    assert q.track.id == "t1"
    assert p.state["tracks"]["local:1"]["aliases"] == []


def test_a_question_says_when_the_own_file_has_no_artist_or_the_length_differs():
    s = own_state(n1=own_entry(1, artist=""))
    [q] = plan([pl("A", night())], s, files_of(s), TODAY).questions
    assert q.why == "no_artist"
    s = own_state(n1=own_entry(1, dur=193000))
    [q] = plan([pl("A", night())], s, files_of(s), TODAY).questions
    assert (q.why, q.delta_s) == ("length", -7)


@pytest.mark.parametrize("own_ms, track_ms", [(None, 200000), (200000, 0), (None, 0)])
def test_a_question_without_a_length_says_so_and_has_no_difference(own_ms, track_ms):
    s = own_state(n1=own_entry(1, dur=own_ms))
    p = plan([pl("A", night(dur=track_ms))], s, files_of(s), TODAY)
    [q] = p.questions
    assert (q.why, q.delta_s) == ("no_length", None)
    assert kinds(p) == [] and p.state["tracks"]["local:1"]["aliases"] == []  # never linked without asking


def test_an_answer_not_same_lets_the_track_download():
    s = own_state(n1=own_entry(1, artist="Another Artist"),
                  decisions={"same_song": [["t1", "local:1", "not_same"]], "keep_both": []})
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.questions == []


def test_an_answer_same_links_the_track():
    s = own_state(n1=own_entry(1, title="Totally Different", artist="Another Artist", dur=150000),
                  decisions={"same_song": [["t1", "local:1", "same"]], "keep_both": []})
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert kinds(p) == [] and p.questions == []
    assert p.state["tracks"]["local:1"]["aliases"] == ["t1"]
    assert p.notes


def test_one_question_per_playlist_song_the_nearest_length():
    s = own_state(n1=own_entry(1, dur=208000), n2=own_entry(2, dur=196000))
    [q] = plan([pl("A", night())], s, files_of(s), TODAY).questions
    assert q.own_key == "local:2"


def test_one_question_per_own_song():
    s = own_state(n1=own_entry(1, artist="Another Artist"))
    p = plan([pl("A", night("t1"), night("t2", artist="Third Artist"))], s, files_of(s), TODAY)
    assert [q.song_key for q in p.questions] == ["t1"]
    assert kinds(p) == [("acquire", "t2")]


def test_an_offline_own_song_is_not_asked_about():
    s = own_state(n1=own_entry(1, artist="Another Artist", online=False))
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.questions == []


def test_desired_folders_follow_an_own_song_link():
    s = own_state(n1=own_entry(1))
    assert desired_folders([pl("A", night())], s) == {"local:1": "A"}


# --- rules 2 and 3: missing songs and duplicates ---

def missing_song(**kw):
    return entry("A", status="missing", title="Night Drive", duration_ms=200000, artist="Example Artist", **kw)


def test_a_missing_playlist_song_takes_over_an_own_songs_file():
    s = own_state(("t1", missing_song(file_gone="2026-10-19")), n1=own_entry(1))
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert "local:1" not in p.state["tracks"]
    e = p.state["tracks"]["t1"]
    assert (e["path"], e["status"], e["file_id"], e["placed_by"], e["import_state"]) == (
        f"{IMPORTED}/Example Artist - Night Drive 1.mp3", "lossless", 101, "import", "done")
    assert e["file_gone"] is None and e["in_playlists"] is True
    assert kinds(p) == [] and p.questions == [] and p.duplicates == []
    assert p.notes == ["Example Artist - Night Drive: the same song as a file of yours, not downloaded again."]
    assert "local:1" in s["tracks"]  # input state untouched


def test_a_merged_song_is_planned_for_like_any_other():
    s = own_state(("t1", missing_song()), n1=own_entry(1, status="not_lossless"))
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert kinds(p) == [("upgrade", "t1")]


def test_a_missing_song_plausibly_an_own_song_is_held_with_a_question():
    s = own_state(("t1", missing_song(last_attempt="2026-10-01")), n1=own_entry(1, dur=205000))
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert kinds(p) == []
    [q] = p.questions
    assert (q.song_key, q.own_key, q.why, q.delta_s) == ("t1", "local:1", "length", 5)
    assert p.state["tracks"]["local:1"]["path"]


def test_a_missing_song_answered_not_same_is_downloaded():
    s = own_state(("t1", missing_song(last_attempt="2026-10-01")), n1=own_entry(1, dur=205000),
                  decisions={"same_song": [["t1", "local:1", "not_same"]], "keep_both": []})
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert kinds(p) == [("acquire", "t1")] and p.questions == []


def test_a_missing_song_answered_same_takes_the_file():
    s = own_state(("t1", missing_song()), n1=own_entry(1, dur=205000),
                  decisions={"same_song": [["t1", "local:1", "same"]], "keep_both": []})
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert "local:1" not in p.state["tracks"] and p.state["tracks"]["t1"]["file_id"] == 101


def placed_song(**kw):
    return entry("A", path="Library/A/Example Artist - Night Drive.aiff", title="Night Drive",
                 artist="Example Artist", duration_ms=200000, file_id=7, online=True, held=False, **kw)


def test_a_song_with_a_file_and_an_own_song_that_certainly_is_it_are_a_same_song_group():
    s = own_state(("t1", placed_song()), n1=own_entry(1, dur=201000), n2=own_entry(2, dur=150000))
    p = plan([pl("A", night())], s, files_of(s), TODAY)
    assert [(g.id, g.why, g.file_ids) for g in p.duplicates] == [("dup:7-101", "same_song", (7, 101))]
    assert kinds(p) == [] and "local:1" in p.state["tracks"]


def test_every_own_song_that_certainly_is_it_joins_one_group():
    s = own_state(("t1", placed_song()), n1=own_entry(1), n2=own_entry(2, dur=199000))
    [g] = plan([pl("A", night())], s, files_of(s), TODAY).duplicates
    assert g.file_ids == (7, 101, 102)


def test_keep_both_hides_a_same_song_group():
    s = own_state(("t1", placed_song()), n1=own_entry(1), decisions={"same_song": [], "keep_both": ["dup:7-101"]})
    assert plan([pl("A", night())], s, files_of(s), TODAY).duplicates == []


def test_an_offline_own_song_is_no_duplicate():
    s = own_state(("t1", placed_song()), n1=own_entry(1, online=False))
    assert plan([pl("A", night())], s, files_of(s), TODAY).duplicates == []


# --- rules 4 and 5: upgrade checks of imported files, the first-check cap (D9) ---

def test_an_own_lossy_file_whose_sound_was_checked_gets_one_upgrade_check():
    s = own_state(n1=own_entry(1, status="not_lossless"))
    p = plan([pl("A", tr("t9"))], s, files_of(s), TODAY)
    [a] = [a for a in p.actions if a.kind == "upgrade"]
    assert (a.track_id, a.folder, a.order) == ("local:1", "", (1, 0))
    assert (a.track.title, a.track.first_artist, a.track.duration_ms, a.track.key) == (
        "Night Drive", "Example Artist", 200000, "local:1")


@pytest.mark.parametrize("change", [
    {"import_state": "identified"}, {"status": "lossless"}, {"online": False}, {"held": True},
    {"duration_ms": None}, {"last_upgrade_check": "2026-10-18"},
    {"upgrade": {"path": "Upgrades ready/x.aiff"}},
])
def test_no_upgrade_check_for_an_own_song_when(change):
    s = own_state(n1=own_entry(1, **{"status": "not_lossless", **change}))
    assert plan([], s, files_of(s), TODAY).actions == []


def test_a_linked_imported_file_waits_for_its_sound_check():
    s = own_state(n1=own_entry(1, status="not_lossless", import_state="identified", aliases=["t1"],
                               in_playlists=True))
    assert plan([pl("A", night())], s, files_of(s), TODAY).actions == []
    s["tracks"]["local:1"]["import_state"] = "done"
    assert kinds(plan([pl("A", night())], s, files_of(s), TODAY)) == [("upgrade", "local:1")]


def lossy_song(id, **kw):
    return entry("A", status="not_lossless", path=f"Library/A/not_lossless/{id}.mp3", title=f"Title {id}", **kw)


def test_the_cap_keeps_playlist_first_checks_first_and_counts_the_rest():
    s = own_state(("p1", lossy_song("p1")), ("p2", lossy_song("p2")),
                  ("p3", lossy_song("p3", last_upgrade_check="2026-10-01")),  # a weekly check, not a first one
                  n1=own_entry(1, status="not_lossless", first_seen="2026-10-02T00:00:00"),
                  n2=own_entry(2, title="Early", status="not_lossless", first_seen="2026-10-01T00:00:00"))
    fetched = [pl("A", tr("p1"), tr("p2"), tr("p3"))]
    p = plan(fetched, s, files_of(s), TODAY)
    assert kinds(p) == [("upgrade", "p1"), ("upgrade", "p2"), ("upgrade", "p3"), ("upgrade", "local:2"),
                        ("upgrade", "local:1")]
    assert p.deferred_checks == 0  # None: no cap
    p = plan(fetched, s, files_of(s), TODAY, first_checks=3)
    assert kinds(p) == [("upgrade", "p1"), ("upgrade", "p2"), ("upgrade", "p3"), ("upgrade", "local:2")]
    assert p.deferred_checks == 1
    p = plan(fetched, s, files_of(s), TODAY, first_checks=0)
    assert kinds(p) == [("upgrade", "p3")] and p.deferred_checks == 4
