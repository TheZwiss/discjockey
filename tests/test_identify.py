import pytest

from discjockey.identify import CERTAIN_MS, PLAUSIBLE_MS, SAME_LENGTH_MS, compare, own_name


def own(artist="Example Artist", title="Night Drive", ms=200000, isrc=None):
    return {"artist": artist, "title": title, "duration_ms": ms, "isrc": isrc}


# --- ISRC (D5) ---

def test_the_same_isrc_within_three_seconds_is_certain():
    assert compare("Someone Else", "Other Title", 202500, "dex1", own(isrc="DEX1")) == ("certain", "isrc")


def test_the_same_isrc_further_apart_is_no_match_even_with_the_same_name():
    assert compare("Example Artist", "Night Drive", 200000 + SAME_LENGTH_MS + 1, "DEX1", own(isrc="DEX1")) is None


def test_two_different_isrcs_are_two_recordings_whatever_the_name():
    assert compare("Example Artist", "Night Drive", 200000, "DEX1", own(isrc="DEX2")) is None


def test_an_isrc_on_one_side_only_leaves_it_to_the_names():
    assert compare("Example Artist", "Night Drive", 200000, "DEX1", own()) == ("certain", "name")
    assert compare("Example Artist", "Night Drive", 200000, None, own(isrc="DEX1")) == ("certain", "name")


def test_the_same_isrc_with_an_unknown_length_is_left_to_the_names():
    assert compare("Example Artist", "Night Drive", 200000, "DEX1", own(isrc="DEX1", ms=None)) == (
        "plausible", "no_length")
    # the words for "no_length" say the artist and title are the same: the ISRC alone is not asked about
    assert compare("Someone Else", "Other Title", 200000, "DEX1", own(isrc="DEX1", ms=None)) is None


# --- names (D3) ---

@pytest.mark.parametrize("delta, expected", [
    (0, ("certain", "name")),
    (CERTAIN_MS, ("certain", "name")),
    (-CERTAIN_MS, ("certain", "name")),
    (CERTAIN_MS + 1, ("plausible", "length")),
    (-PLAUSIBLE_MS, ("plausible", "length")),
    (PLAUSIBLE_MS, ("plausible", "length")),
    (PLAUSIBLE_MS + 1, None),
])
def test_same_artist_and_title_by_length(delta, expected):
    assert compare("Example Artist", "Night Drive", 200000, None, own(ms=200000 + delta)) == expected


@pytest.mark.parametrize("artist", ["Another Artist", ""])
def test_same_title_with_a_different_or_missing_artist_is_plausible_when_the_length_is_close(artist):
    assert compare("Example Artist", "Night Drive", 200000, None, own(artist=artist, ms=201500)) == ("plausible", "artist")


def test_same_title_with_another_artist_and_a_length_further_off_is_no_match():
    assert compare("Example Artist", "Night Drive", 200000, None, own(artist="Another Artist", ms=203000)) is None


def test_a_different_title_is_no_match():
    assert compare("Example Artist", "Day Drive", 200000, None, own()) is None


def test_an_empty_title_is_no_match():
    assert compare("Example Artist", "", 200000, None, own(title="")) is None


def test_an_own_song_without_a_length_is_at_most_plausible():
    assert compare("Example Artist", "Night Drive", 200000, None, own(ms=None)) == ("plausible", "no_length")
    assert compare("Example Artist", "Night Drive", 200000, None, own(artist="", ms=None)) is None


@pytest.mark.parametrize("track_ms", [0, None])
def test_a_track_of_unknown_length_is_at_most_plausible(track_ms):
    assert compare("Example Artist", "Night Drive", track_ms, None, own()) == ("plausible", "no_length")


def test_both_lengths_unknown_is_at_most_plausible():
    assert compare("Example Artist", "Night Drive", None, None, own(ms=None)) == ("plausible", "no_length")
    assert compare("Example Artist", "Night Drive", 0, None, own(ms=0)) == ("plausible", "no_length")


def test_feat_and_original_mix_normalise_away():
    mine = own(artist="Example Artist feat. Guest", title="Night Drive (Original Mix)")
    assert compare("Example Artist", "Night Drive", 200500, None, mine) == ("certain", "name")
    assert compare("Example Artist", "Night Drive - Original Mix", 200500, None, own()) == ("certain", "name")


def test_case_and_punctuation_normalise_away():
    assert compare("EXAMPLE ARTIST", "night drive!", 200000, None, own()) == ("certain", "name")


# --- own_name ---

def test_own_name_takes_the_tags_first():
    assert own_name({"artist": "Example Artist", "title": "Night Drive"}, "01 track.mp3") == (
        "Example Artist", "Night Drive")


def test_own_name_takes_a_title_tag_without_an_artist():
    assert own_name({"artist": None, "title": " Night Drive "}, "Other - Name.mp3") == ("", "Night Drive")


def test_own_name_splits_the_file_name_on_the_first_spaced_dash():
    assert own_name({}, "Example Artist - Night Drive - Extended.flac") == ("Example Artist", "Night Drive - Extended")
    assert own_name({"title": ""}, "Example Artist – Night Drive.mp3") == ("Example Artist", "Night Drive")


def test_own_name_falls_back_to_the_file_name_as_the_title():
    assert own_name({}, "night-drive_final.wav") == ("", "night-drive_final")
    assert own_name({}, " - Night Drive.mp3") == ("", "- Night Drive")
