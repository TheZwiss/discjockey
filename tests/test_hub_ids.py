"""Typed ids (issue 39, design §3): each kind round-trips, a bare batch number is refused with the words to say."""
import pytest

from discjockey.hub import ids

SPOTIFY = "4uLU6hMCjMI75M1A2tKUQC"

ROUND_TRIPS = [
    ("track", SPOTIFY, "track"), ("track", "qobuz:123456", "track"), ("track", "soundcloud:777", "track"),
    ("track", "youtube_music:abcDEF-1", "track"), ("track", "local:12", "track"),
    ("file", 7, "file"), ("aiff", 12, "aiff"), ("moves", 12, "moves"), ("job", "1a2b3c4d", "job"),
    ("report", "2026-11-15_093000", "report"), ("plan", "0123456789ab", "plan"),
    ("folder", "/Music/Crates/House", "folder"), ("playlist", "Warm Up", "playlist"),
    ("collection", "all", "collection"), ("collection", "unlisted", "collection"),
    ("collection", "playlist:Warm Up", "collection"), ("collection", "folder:/Music/Crates/House", "collection"),
]


@pytest.mark.parametrize("kind,value,expect", ROUND_TRIPS)
def test_each_kind_round_trips(kind, value, expect):
    printed = ids.fmt(kind, value)
    assert ids.parse(printed, [kind]) == ids.Ident(expect, value)


def test_printed_forms():
    assert ids.fmt("aiff", 12) == "aiff:12"
    assert ids.fmt("moves", 3) == "moves:3"
    assert ids.fmt("file", 5) == "file:5"
    assert ids.fmt("folder", "/a/b") == "folder:/a/b"
    assert ids.fmt("track", "local:2") == "local:2"
    with pytest.raises(ValueError):
        ids.fmt("nothing", 1)


def test_a_bare_number_for_a_batch_says_which_batch():
    for kinds in (["aiff"], ["moves"], ["aiff", "moves"]):
        with pytest.raises(ids.BadId) as e:
            ids.parse("12", kinds)
        assert e.value.reason == "bad_id_kind"
        assert "say aiff:12 or moves:12" in e.value.message


def test_a_batch_id_of_the_other_kind_is_refused():
    with pytest.raises(ids.BadId) as e:
        ids.parse("aiff:3", ["moves"])
    assert e.value.reason == "bad_id_kind"
    assert ids.parse("moves:3", ["aiff", "moves"]) == ids.Ident("moves", 3)


def test_an_id_of_another_kind_is_bad_id_kind_and_a_broken_one_is_unknown():
    with pytest.raises(ids.BadId) as e:
        ids.parse("job:1a2b3c4d", ["track"])
    assert e.value.reason == "bad_id_kind"
    for text in ("aiff:x", "job:xyz", "plan:12", "report:yesterday", "file:", "local:", "", "  "):
        with pytest.raises(ids.BadId) as e:
            ids.parse(text, list(ids.KINDS))
        assert e.value.reason == "unknown_id", text


def test_a_track_key_passes_as_it_is():
    for key in (SPOTIFY, "qobuz:55", "soundcloud:a:b", "youtube_music:LM", "local:9"):
        assert ids.parse(key, ["track"]) == ids.Ident("track", key)
    assert ids.parse("-", ["track"]) == ids.Ident("track", "-")


def test_words_and_paths():
    assert ids.parse("last", ["report"]) == ids.Ident("report", "last")
    assert ids.parse("2026-11-15_093000", ["report"]) == ids.Ident("report", "2026-11-15_093000")
    assert ids.parse("current", ["job"]) == ids.Ident("job", "current")
    assert ids.parse("/Music/Library/a.aiff", ["track", "file"]) == ids.Ident("path", "/Music/Library/a.aiff")
    assert ids.parse("Library/a.aiff", ["track"]).kind == "path"
    assert ids.parse("/Music/Crate", ["folder"]) == ids.Ident("folder", "/Music/Crate")
    assert ids.parse("folder:/Music/Crate", ["collection"]) == ids.Ident("collection", "folder:/Music/Crate")
    assert ids.parse("Warm Up", ["playlist"]) == ids.Ident("playlist", "Warm Up")
    assert ids.parse("playlist:Warm Up", ["playlist", "collection"]) == ids.Ident("playlist", "Warm Up")
    # a 22-letter word is a Spotify id where a track is meant, a folder name where only a playlist is
    assert ids.parse(SPOTIFY, ["playlist", "track"]) == ids.Ident("track", SPOTIFY)
    assert ids.parse(SPOTIFY, ["playlist"]) == ids.Ident("playlist", SPOTIFY)


def test_a_word_no_kind_takes_is_unknown():
    with pytest.raises(ids.BadId) as e:
        ids.parse("whatever", ["moves"])
    assert e.value.reason == "unknown_id"
    with pytest.raises(ValueError):
        ids.parse("x", ["bogus"])
