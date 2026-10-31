import dataclasses

import pytest

from discjockey.models import (SERVICE_NAMES, TRACK_LINKS, Action, PlaylistLine, SourceTrack, split_token, token,
                               track_link)

ID = "0DiscjockeyExampleTrack"


def test_a_spotify_token_is_the_bare_id():
    assert token("spotify", ID) == ID
    assert split_token(ID) == ("spotify", ID)


def test_another_service_gets_its_name_in_front():
    assert token("qobuz", "900000001") == "qobuz:900000001"
    assert split_token("qobuz:900000001") == ("qobuz", "900000001")
    assert split_token("soundcloud:1:2") == ("soundcloud", "1:2")  # split at the first colon only


@pytest.mark.parametrize("service,id", [("spotify", ID), ("qobuz", "900000001"), ("soundcloud", "12345")])
def test_tokens_round_trip(service, id):
    assert split_token(token(service, id)) == (service, id)


def test_track_link_follows_the_service():
    assert track_link(ID) == f"https://open.spotify.com/track/{ID}"
    assert track_link("qobuz:900000001") == "https://open.qobuz.com/track/900000001"
    assert track_link("soundcloud:900000101") == \
        "https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/900000101"
    assert track_link("youtube_music:EXAMPLEid01") == "https://music.youtube.com/watch?v=EXAMPLEid01"
    assert track_link("youtube:EXAMPLEid01") is None


def test_service_names_and_link_patterns():
    assert list(SERVICE_NAMES.items()) == [("spotify", "Spotify"), ("qobuz", "Qobuz"), ("soundcloud", "SoundCloud"),
                                           ("youtube_music", "YouTube Music")]
    assert set(TRACK_LINKS) == {"spotify", "qobuz", "soundcloud", "youtube_music"}


def test_a_source_track_fills_its_link_from_its_service():
    spotify = SourceTrack(ID, "Title", ("Example Artist",), "Album", None, 180000, None)
    assert (spotify.service, spotify.key) == ("spotify", ID)
    assert spotify.link == f"https://open.spotify.com/track/{ID}" and spotify.streamable
    qobuz = SourceTrack("900000001", "Title", ("Example Artist",), "Album", None, 180000, "USXXX0000001", "qobuz")
    assert (qobuz.key, qobuz.link) == ("qobuz:900000001", "https://open.qobuz.com/track/900000001")


def test_a_given_link_stays_and_a_service_without_a_pattern_has_none():
    given = SourceTrack("1", "T", (), "", None, 0, None, "soundcloud", "https://soundcloud.com/example/track")
    assert given.link == "https://soundcloud.com/example/track" and given.key == "soundcloud:1"
    assert SourceTrack("1", "T", (), "", None, 0, None, "youtube").link is None


def test_new_services_fill_their_links_and_account_only_defaults_off():
    sc = SourceTrack("900000101", "T", (), "", None, 0, None, "soundcloud")
    assert sc.link == "https://w.soundcloud.com/player/?url=https%3A//api.soundcloud.com/tracks/900000101"
    assert SourceTrack("EXAMPLEid01", "T", (), "", None, 0, None, "youtube_music").link == \
        "https://music.youtube.com/watch?v=EXAMPLEid01"
    assert sc.account_only is False and sc.streamable is True
    assert SourceTrack("1", "T", (), "", None, 0, None, "soundcloud", account_only=True).account_only
    assert dataclasses.fields(SourceTrack)[-1].name == "account_only"


def test_a_source_track_has_no_url_any_more():
    assert not hasattr(SourceTrack(ID, "T", (), "", None, 0, None), "url")


def test_field_order_keeps_old_positional_constructions_valid():
    names = [f.name for f in dataclasses.fields(SourceTrack)]
    assert names[:7] == ["id", "title", "artists", "album", "image_url", "duration_ms", "isrc"]


def test_a_playlist_line_has_a_ref():
    assert PlaylistLine("A", "0DiscjockeyExampleList", 1).ref == "0DiscjockeyExampleList"
    assert PlaylistLine("A", "900000001", 2, "qobuz").ref == "qobuz:900000001"


def test_an_action_carries_no_qobuz_id_by_default():
    track = SourceTrack(ID, "T", (), "", None, 0, None)
    assert Action("acquire", ID, "A", track, (0, 0)).qobuz_id is None
