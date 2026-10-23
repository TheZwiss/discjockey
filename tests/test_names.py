import unicodedata

from discjockey.names import expected_stem, fold, sanitize_stem, split_name, strip_id_suffix


def test_forbidden_chars():
    assert sanitize_stem('AC/DC - What? "Yes" <No> | a*b:c\\d') == "AC-DC - What- -Yes- -No- - a-b-c-d"


def test_control_chars_and_whitespace():
    assert sanitize_stem("a\tb\x00c") == "a-b-c"
    assert sanitize_stem("a    b ") == "a b"


def test_leading_and_trailing_dots():
    assert sanitize_stem("..hidden. ") == "hidden"


def test_nfc():
    nfd = unicodedata.normalize("NFD", "Mötley")
    assert sanitize_stem(nfd) == unicodedata.normalize("NFC", "Mötley")


def test_truncate_multibyte_without_splitting():
    assert sanitize_stem("ü" * 150) == "ü" * 100
    out = sanitize_stem("a" + "ü" * 150)
    assert out == "a" + "ü" * 99
    assert len(out.encode()) <= 200


def test_empty_becomes_unknown():
    assert sanitize_stem("...") == "Unknown"


def test_expected_stem_empty_artist():
    assert expected_stem("", "Title") == "Unknown Artist - Title"
    assert expected_stem("A", "  ") == "A - Unknown Title"


def test_emoji_and_long_title():
    stem = expected_stem("DJ 🔥", "x" * 300)
    assert stem.startswith("DJ 🔥 - x")
    assert len(stem.encode()) <= 200


def test_fold():
    assert fold(unicodedata.normalize("NFD", "Ä")) == fold("ä")


def test_split_name_keeps_dots_in_stem():
    assert split_name("Mr. X - Y.aiff") == ("Mr. X - Y", ".aiff")


def test_strip_id_suffix():
    assert strip_id_suffix("A - B [abc123].aiff", "abc123XYZ") == "A - B.aiff"
    assert strip_id_suffix("A - B [abc123XYZ].aiff", "abc123XYZ") == "A - B.aiff"
    assert strip_id_suffix("A - B.aiff", "abc123XYZ") == "A - B.aiff"
