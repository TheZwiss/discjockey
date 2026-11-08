"""rekordbox's analysis files (discjockey/rekordbox/anlz.py): the path, the beat grid and the waveform read back, an
unknown tag skipped, and a broken file read as "no analysis". Every file here is built by
rekordbox_helpers.make_anlz."""
from __future__ import annotations

import numpy as np

from discjockey.rekordbox import anlz
from rekordbox_helpers import make_anlz, ppth_tag, pqtz_tag, pwv3_tag, unknown_tag

PATH = "/Users/dj/Music/Ärtist - Sóng.mp3"


def test_path_grid_and_waveform_read_back(tmp_path):
    heights = np.arange(300, dtype=np.uint8) % 32
    dat = anlz.read(make_anlz(tmp_path / "ANLZ0000.DAT", [ppth_tag(PATH), unknown_tag(), pqtz_tag(64)]))
    ext = anlz.read(make_anlz(tmp_path / "ANLZ0000.EXT", [ppth_tag(PATH), pwv3_tag(heights)]))
    assert anlz.ppth(dat) == PATH and anlz.ppth(ext) == PATH
    assert anlz.beat_count(dat) == 64
    got = anlz.pwv3_heights(ext)
    assert got.dtype == np.uint8 and np.array_equal(got, heights)  # the whiteness bits are masked off
    assert anlz.pwv3_heights(dat) is None and anlz.beat_count(ext) == 0


def test_an_unknown_tag_is_skipped_and_every_byte_and_span_is_kept(tmp_path):
    path = make_anlz(tmp_path / "ANLZ0000.DAT", [unknown_tag(), ppth_tag(PATH), unknown_tag(), pqtz_tag(3)])
    a = anlz.read(path)
    assert [t.fourcc for t in a.tags] == ["PVB2", "PPTH", "PVB2", "PQTZ"]
    assert a.data == path.read_bytes() and a.header_len == 28
    assert a.tags[0].start == 28 and all(t.end == n.start for t, n in zip(a.tags, a.tags[1:]))
    assert a.tags[-1].end == len(a.data)
    assert anlz.ppth(a) == PATH and anlz.beat_count(a) == 3


def test_no_tags_of_a_kind_read_as_none_or_zero(tmp_path):
    a = anlz.read(make_anlz(tmp_path / "ANLZ0000.DAT", [unknown_tag()]))
    assert anlz.ppth(a) is None and anlz.beat_count(a) == 0 and anlz.pwv3_heights(a) is None


def test_broken_files_are_no_analysis(tmp_path):
    good = make_anlz(tmp_path / "good.EXT", [ppth_tag(PATH), pwv3_tag(np.ones(500, dtype=np.uint8))]).read_bytes()
    cases = {
        "truncated": good[:-10],
        "wrong magic": b"PMAX" + good[4:],
        "tiny": b"PMA",
        "tag past the end": good[:28] + good[28:32] + (10 ** 6).to_bytes(4, "big") * 2 + good[40:],
    }
    for name, data in cases.items():
        (tmp_path / name).write_bytes(data)
        assert anlz.read(tmp_path / name) is None, name
    assert anlz.read(tmp_path / "missing.DAT") is None


def test_a_waveform_whose_count_runs_past_its_tag_is_none(tmp_path):
    tag = bytearray(pwv3_tag(np.ones(100, dtype=np.uint8)))
    tag[16:20] = (101).to_bytes(4, "big")  # entries
    a = anlz.read(make_anlz(tmp_path / "ANLZ0000.EXT", [bytes(tag)]))
    assert a is not None and anlz.pwv3_heights(a) is None


# --- stage B: the PPTH splice ---

def test_splice_replaces_only_the_path_and_fixes_the_lengths(tmp_path):
    path = make_anlz(tmp_path / "ANLZ0000.EXT", [unknown_tag(), ppth_tag("?/Old.mp3"), pwv3_tag(np.arange(90) % 32),
                                                 unknown_tag()])
    a = anlz.read(path)
    out = anlz.splice_ppth(a, "?/Ärtist - A much longer new name.aiff")
    b = anlz.parse(out)  # the lengths hold together
    assert anlz.ppth(b) == "?/Ärtist - A much longer new name.aiff"
    assert [t.fourcc for t in b.tags] == [t.fourcc for t in a.tags]
    for old, new in zip(a.tags, b.tags):
        if old.fourcc != "PPTH":
            assert a.data[old.start:old.end] == out[new.start:new.end]  # every other tag byte for byte
    assert out[:28][12:] == a.data[:28][12:] and len(out) == int.from_bytes(out[8:12], "big")
    assert anlz.splice_ppth(b, "?/Old.mp3") == a.data  # and back: the same bytes


def test_splice_refuses_a_file_without_a_path(tmp_path):
    a = anlz.read(make_anlz(tmp_path / "ANLZ0000.DAT", [pqtz_tag(4)]))
    try:
        anlz.splice_ppth(a, "?/x.aiff")
    except anlz.Malformed:
        pass
    else:
        raise AssertionError("a file without PPTH can't be spliced")


def test_ppth_after_keeps_the_form_and_leaves_other_paths():
    old, new = "/Users/dj/Music/Old Song.mp3", "/Users/dj/Music/Artist - Song.aiff"
    assert anlz.ppth_after("?/Old Song.mp3", old, new) == "?/Artist - Song.aiff"  # rekordbox 7's own form
    assert anlz.ppth_after("?/OLD SONG.mp3", old, new) == "?/Artist - Song.aiff"  # case-folded compare
    assert anlz.ppth_after(old, old, new) == new  # the whole path (a stick, an older file)
    nfd = "/Users/dj/Music/Café.mp3"
    assert anlz.ppth_after("?/Café.mp3", nfd, new) == "?/Artist - Song.aiff"  # NFC compare
    assert anlz.ppth_after("?/Something else.mp3", old, new) is None
    assert anlz.ppth_after(None, old, new) is None


def test_md5_size_is_rekordboxs_checksum(tmp_path):
    import hashlib
    p = make_anlz(tmp_path / "ANLZ0000.DAT", [ppth_tag(PATH)])
    assert anlz.md5_size(p) == (hashlib.md5(p.read_bytes()).hexdigest(), p.stat().st_size)
