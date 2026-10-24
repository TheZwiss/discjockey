import pytest

from discjockey import sources
from discjockey.config import ConfigError, load_playlists, parse_playlists

ID1 = "0DiscjockeyExampleList"
ID2 = "3DiscjockeyExampleList"


def test_valid_file_with_comments_and_blank_lines():
    text = (
        "# comment\n"
        "\n"
        f"Hard_Bounce = https://open.spotify.com/playlist/{ID1}?si=507076b55d4b4f8d\n"
        f"Powertrance=spotify:playlist:{ID2}\n"
        "# Sing_Along_Remixes =\n"
    )
    lines = parse_playlists(text)
    assert [(l.folder, l.playlist_id, l.line_no) for l in lines] == [
        ("Hard_Bounce", ID1, 3),
        ("Powertrance", ID2, 4),
    ]


@pytest.mark.parametrize("ref", [
    f"https://open.spotify.com/playlist/{ID1}",
    f"https://open.spotify.com/playlist/{ID1}?si=abc",
    f"https://open.spotify.com/intl-de/playlist/{ID1}",
    f"spotify:playlist:{ID1}",
])
def test_url_variants(ref):
    assert sources.recognise(ref) == ("spotify", ID1)


@pytest.mark.parametrize("ref", [
    f"https://open.spotify.com/album/{ID1}",
    "https://example.com/playlist/x",
    "spotify:playlist:short",
])
def test_bad_urls(ref):
    assert sources.recognise(ref) is None
    with pytest.raises(ConfigError, match="line 1"):
        parse_playlists(f"Folder = {ref}")


def test_empty_link_names_the_line():
    with pytest.raises(ConfigError, match="line 2.*empty"):
        parse_playlists(f"A = spotify:playlist:{ID1}\nBouncy =\n")


def test_missing_equals():
    with pytest.raises(ConfigError, match="line 1"):
        parse_playlists("Hard_Bounce https://open.spotify.com/playlist/x")


def test_duplicate_folder_case_insensitive():
    with pytest.raises(ConfigError, match="line 2"):
        parse_playlists(f"Bounce = spotify:playlist:{ID1}\nbounce = spotify:playlist:{ID2}\n")


def test_duplicate_playlist_id():
    with pytest.raises(ConfigError, match="line 2"):
        parse_playlists(f"A = spotify:playlist:{ID1}\nB = spotify:playlist:{ID1}\n")


@pytest.mark.parametrize("folder", ["not_lossless", "Not_Lossless", "a/b", "a:b", "a\\b", ".hidden", "x" * 101])
def test_forbidden_folder_names(folder):
    with pytest.raises(ConfigError, match="line 1"):
        parse_playlists(f"{folder} = spotify:playlist:{ID1}")


def test_no_active_lines():
    with pytest.raises(ConfigError, match="no active playlists"):
        parse_playlists("# only comments\n\n")


def test_load_missing_file(tmp_path):
    with pytest.raises(ConfigError, match="setup"):
        load_playlists(tmp_path / "playlists.txt")


def test_error_kinds(tmp_path):
    with pytest.raises(ConfigError) as excinfo:
        load_playlists(tmp_path / "playlists.txt")
    assert excinfo.value.kind == "not_set_up"
    with pytest.raises(ConfigError) as excinfo:
        parse_playlists("# only a comment\n")
    assert excinfo.value.kind == "not_set_up"
    with pytest.raises(ConfigError) as excinfo:
        parse_playlists("Bouncy =\n")
    assert excinfo.value.kind == "config_invalid"


def test_a_line_carries_its_service_and_ref():
    line = parse_playlists(f"A = spotify:playlist:{ID1}")[0]
    assert (line.service, line.playlist_id, line.ref) == ("spotify", ID1, ID1)


def test_an_unknown_link_gives_the_words_for_both_services():
    with pytest.raises(ConfigError) as excinfo:
        parse_playlists("A = https://example.com/playlist/x")
    assert str(excinfo.value) == ("playlists.txt line 1: this is not a Spotify or Qobuz playlist link: "
                                  "https://example.com/playlist/x")


def test_the_format_hint_is_service_neutral():
    with pytest.raises(ConfigError) as excinfo:
        parse_playlists("Hard_Bounce")
    assert str(excinfo.value) == "playlists.txt line 1: expected 'Folder = playlist link', found: Hard_Bounce"
