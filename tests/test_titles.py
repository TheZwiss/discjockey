"""The title splitter (stage 6 I2): artists and title out of a free-text upload title."""
import pytest

from discjockey.titles import clean_uploader, split_title

A = ("Example Artist",)

# (title, uploader, known artist, expected artists, expected title)
CASES = [
    # no dash: the uploader is the artist
    ("Example Title", "Example Artist", None, A, "Example Title"),
    ("Example Title", "Example Artist - Topic", None, A, "Example Title"),
    ("Example Title", "Example ArtistVEVO", None, A, "Example Title"),
    # one dash, several dashes
    ("Example Artist - Example Title", "Some Uploader", None, A, "Example Title"),
    ("Example Artist - Example Title - Extended Mix", "Some Uploader", None, A, "Example Title - Extended Mix"),
    ("Example Records - Example Artist - Example Title", "Example Records", None, A, "Example Title"),
    ("Example Records - Example Artist - Example Title - Dub", "Example Records", None, A, "Example Title - Dub"),
    # a label uploader: the artist comes from the title; without a dash the label stays (a known limit)
    ("Example Artist - Example Title", "Example Records", None, A, "Example Title"),
    ("Example Title", "Example Records", None, ("Example Records",), "Example Title"),
    # tags
    ("Example Artist - Example Title [FREE DL]", "x", None, A, "Example Title"),
    ("Example Artist - Example Title (Free Download)", "x", None, A, "Example Title"),
    ("Example Artist - Example Title (Premiere)", "x", None, A, "Example Title"),
    ("[FREE DL] Example Artist - Example Title", "x", None, A, "Example Title"),
    ("FREE DL: Example Artist - Example Title", "x", None, A, "Example Title"),
    ("PREMIERE: Example Artist - Example Title", "x", None, A, "Example Title"),
    ("Premiere - Example Artist - Example Title", "x", None, A, "Example Title"),
    ("Premiere | Example Artist - Example Title", "x", None, A, "Example Title"),
    ("[Premiere] Example Artist - Example Title", "x", None, A, "Example Title"),
    ("Example Artist - Example Title (Official Video)", "x", None, A, "Example Title"),
    ("Example Artist - Example Title [Official Music Video] [HD]", "x", None, A, "Example Title"),
    ("Example Artist - Example Title (Lyrics)", "x", None, A, "Example Title"),
    ("Example Artist - Example Title [Example Records]", "Example Records", None, A, "Example Title"),
    # a bracket that belongs to the song stays
    ("Example Artist - Example Title (Example Remix)", "x", None, A, "Example Title (Example Remix)"),
    ("Example Artist - Example Title [Example Edit]", "x", None, A, "Example Title [Example Edit]"),
    ("Example Artist - Example Title (VIP Mix) [FREE DL]", "x", None, A, "Example Title (VIP Mix)"),
    # emoji
    ("🔥 Example Artist - Example Title", "x", None, A, "Example Title"),
    ("Example Artist - Example 🔥 Title", "x", None, A, "Example Title"),
    ("Example Artist - Example Title 🔥🔥", "x", None, A, "Example Title"),
    ("Example Artist - Example Title 👍🏽 ❤️", "x", None, A, "Example Title"),
    ("🔥🔥", "Example Artist", None, A, "🔥🔥"),
    # featuring
    ("Example Artist feat. Other Artist - Example Title", "x", None, ("Example Artist", "Other Artist"),
     "Example Title"),
    ("Example Artist - Example Title (feat. Other Artist)", "x", None, ("Example Artist", "Other Artist"),
     "Example Title"),
    ("Example Artist - Example Title ft. Other Artist", "x", None, ("Example Artist", "Other Artist"),
     "Example Title"),
    ("Example Artist - Example Title ft. Other Artist - Extended Mix", "x", None,
     ("Example Artist", "Other Artist"), "Example Title - Extended Mix"),
    ("Example Artist (featuring Other Artist) - Example Title", "x", None, ("Example Artist", "Other Artist"),
     "Example Title"),
    ("Example Title (feat. Other Artist)", "Example Artist", None, ("Example Artist", "Other Artist"), "Example Title"),
    # several artists
    ("Chase & Status - Example Title", "x", None, ("Chase & Status",), "Example Title"),
    ("Example Artist x Other Artist - Example Title", "x", None, ("Example Artist", "Other Artist"), "Example Title"),
    ("Example Artist, Other Artist - Example Title", "x", None, ("Example Artist", "Other Artist"), "Example Title"),
    ("Lil Nas X - Example Title", "x", None, ("Lil Nas X",), "Example Title"),
    ("Above and Beyond - Example Title", "x", None, ("Above and Beyond",), "Example Title"),
    # dashes
    ("Jay-Z - Example Title", "x", None, ("Jay-Z",), "Example Title"),
    ("AC-DC - Example Title", "x", None, ("AC-DC",), "Example Title"),
    ("Example Artist – Example Title", "x", None, A, "Example Title"),
    ("Example Artist — Example Title", "x", None, A, "Example Title"),
    ("Example Title-Part Two", "Example Artist", None, A, "Example Title-Part Two"),
    # the pipe tail
    ("Example Artist - Example Title | Genre | NCS - Copyright Free Music", "NoCopyrightSounds", None, A,
     "Example Title"),
    # non-Latin
    ("エグザンプル - タイトル", "x", None, ("エグザンプル",), "タイトル"),
    ("タイトル", "エグザンプル", None, ("エグザンプル",), "タイトル"),
    ("Пример Артист - Пример названия", "x", None, ("Пример Артист",), "Пример названия"),
    # a known artist, with and without the prefix in the title
    ("Example Artist - Example Title", "Some Uploader", "Example Artist", A, "Example Title"),
    ("Example Title", "Some Uploader", "Example Artist", A, "Example Title"),
    ("Example Title - Extended Mix", "Some Uploader", "Example Artist", A, "Example Title - Extended Mix"),
    ("Example Artist & Other Artist - Example Title", "x", "Example Artist", ("Example Artist & Other Artist",),
     "Example Title"),
    # a known artist is part of the title's artist, or the other way round
    ("A - Title", "x", "A, B", ("A",), "Title"),
    ("Artist - Title", "x", "Artist & Other", ("Artist",), "Title"),
    ("Artist - Title", "x", "Artist x Other", ("Artist",), "Title"),
    ("ARTIST (UK) - Title", "x", "Artist", ("ARTIST (UK)",), "Title"),
    ("Artist - Title", "x", "ARTIST (UK)", ("Artist",), "Title"),
    ("The Artist - Title", "x", "Artist", ("The Artist",), "Title"),
    ("Title - Extended Mix", "x", "Artist", ("Artist",), "Title - Extended Mix"),
    # no known artist: a mix name after the only dash is no title
    ("Title - Extended Mix", "Example Artist", None, A, "Title - Extended Mix"),
    ("Title - Radio Edit", "Example Artist", None, A, "Title - Radio Edit"),
    # accents used as apostrophes
    ("Artist - Don´t Stop", "x", None, ("Artist",), "Don't Stop"),
    ("Artist - Don`t Stop", "x", None, ("Artist",), "Don't Stop"),
    # a dash left behind
    ("Artist - Title - ", "x", None, ("Artist",), "Title"),
    ("Title - feat. Other", "x", "Artist", ("Artist", "Other"), "Title"),
]


@pytest.mark.parametrize("title,uploader,artist,artists,song", CASES)
def test_split_title(title, uploader, artist, artists, song):
    assert split_title(title, uploader, artist) == (artists, song)


def test_only_tags_keeps_the_cleaned_title():
    assert split_title("[FREE DL]", "Example Artist") == (A, "[FREE DL]")


def test_a_dash_with_nothing_on_one_side_is_not_a_split():
    assert split_title("Example Title - ", "Example Artist") == (A, "Example Title")  # the dangling dash goes


def test_no_uploader_and_no_dash_gives_no_artists():
    assert split_title("Example Title", "") == ((), "Example Title")


def test_full_width_text_is_normalised():
    assert split_title("Ｅｘａｍｐｌｅ Ａｒｔｉｓｔ - Ｔｉｔｌｅ", "x") == (A, "Title")


@pytest.mark.parametrize("name,cleaned", [
    ("Example Artist - Topic", "Example Artist"), ("Example ArtistVEVO", "Example Artist"),
    ("Example Artist VEVO", "Example Artist"), ("  Example Artist  ", "Example Artist"),
    ("Example-Artist", "Example-Artist"), ("VEVO", "VEVO"), ("- Topic", "- Topic"),
])
def test_clean_uploader(name, cleaned):
    assert clean_uploader(name) == cleaned
