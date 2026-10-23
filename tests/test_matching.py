import pytest

from discjockey.matching import (
    fallback_match, isrc_match, normalize, normalize_artist, qobuz_match, rank,
)
from discjockey.models import Candidate, SpotifyTrack


def track(title="Gimme Gimme", artists=("Vatoz Locoz",), dur=156000, isrc="DECE72605755"):
    return SpotifyTrack("t1", title, artists, "Album", None, dur, isrc)


def qc(title="Gimme Gimme", artist="Vatoz Locoz Vatoz Locoz", dur=156.0, id="1", isrc=None):
    return Candidate("qobuz", id, title, artist, dur, isrc=isrc)


def fc(title, artist="", dur=156.0, source="youtube", id="y1"):
    return Candidate(source, id, title, artist, dur, url=f"https://x/{id}")


@pytest.mark.parametrize("raw,expected", [
    ("Gimme Gimme - Original Mix", "gimme gimme"),
    ("Gimme Gimme (Extended Mix)", "gimme gimme"),
    ("Song (feat. Someone)", "song"),
    ("Song feat. Someone", "song"),
    ("Song feat. X (Y Remix)", "song y remix"),
    ("Song (feat. X) - Y Remix", "song y remix"),
    ("Song [with Someone]", "song"),
    ("Song - Radio Edit", "song"),
    ("Song - Remastered 2011", "song"),
    ("Song - 2011 Remaster", "song"),
    ("Gimme Gimme - XYZ Remix", "gimme gimme xyz remix"),
    ("Gimme Gimme (XYZ Remix)", "gimme gimme xyz remix"),
    ("Über Drüben!", "über drüben"),
    ("Über", "über"),
])
def test_normalize(raw, expected):
    assert normalize(raw) == expected


def test_normalize_artist_collaborations():
    assert normalize_artist("A x B & C, D") == "a b c d"


def test_qobuz_version_field_matches_spotify_dash_remix():
    assert qobuz_match(track("Gimme Gimme - XYZ Remix"), qc("Gimme Gimme (XYZ Remix)"), set())


def test_qobuz_duration_limit():
    assert qobuz_match(track(), qc(dur=159.0), set())
    assert not qobuz_match(track(), qc(dur=159.5), set())
    assert not qobuz_match(track(), qc(dur=None), set())


def test_qobuz_rejects_other_song_and_other_artist():
    assert not qobuz_match(track(), qc(title="Never Gonna Give You Up"), set())
    assert not qobuz_match(track(), qc(artist="Someone Else"), set())


def test_rejected_source_is_skipped():
    assert not qobuz_match(track(), qc(id="1"), {"qobuz:1"})


def test_isrc_match():
    assert isrc_match(track(), qc(isrc="dece72605755"), set())
    assert not isrc_match(track(), qc(isrc="XX0000000000"), set())
    assert not isrc_match(track(), qc(isrc="DECE72605755", dur=170.0), set())
    assert not isrc_match(track(isrc=None), qc(isrc="DECE72605755"), set())


def test_fallback_youtube_style_title():
    c = fc("Vatoz Locoz - Gimme Gimme (Official Video)", artist="Vatoz Locoz")
    assert fallback_match(track(), c, set())


def test_fallback_artist_may_be_in_title_only():
    c = fc("Vatoz Locoz - Gimme Gimme [HQ]", artist="Random Uploader")
    assert fallback_match(track(), c, set())


def test_fallback_token_containment():
    c = fc("Gimme Gimme (Hardstyle Bootleg 2026)", artist="Vatoz Locoz")
    assert fallback_match(track(), c, set())


def test_fallback_rejects_unrelated():
    assert not fallback_match(track(), fc("Something Else Entirely", artist="Vatoz Locoz"), set())


def test_empty_artist_never_matches():
    t = track(artists=())
    assert not qobuz_match(t, qc(), set())
    assert not fallback_match(t, fc("Gimme Gimme", artist="Vatoz Locoz"), set())


def test_artist_must_match_whole_words():
    t = track(artists=("Ace",))
    assert not qobuz_match(t, qc(title="Gimme Gimme", artist="Grace Jones"), set())
    assert qobuz_match(t, qc(title="Gimme Gimme", artist="Ace Ventura"), set())


def test_rank_by_duration_difference():
    a, b = qc(dur=158.0, id="a"), qc(dur=156.5, id="b")
    assert [c.id for c in rank(track(), [a, b])] == ["b", "a"]
