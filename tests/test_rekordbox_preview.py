"""discjockey/rekordbox/preview.py and audio.file_facts: what the three actions would do for one file, read only, on a
tmp library and a fixture rekordbox (tests/rekordbox_helpers.py). The MP3 is a fixture with an Info/LAME tag."""
from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from audio_helpers import TINY_JPEG, music, needs_ffmpeg, write_aiff
from rekordbox_helpers import (
    make_anlz, make_master, own_entry as entry, pqtz_tag, pwv3_from, pwv3_tag, save_library as library, snapshot,
)

from discjockey import audio, quality, rekordbox
from discjockey.align import Alignment
from discjockey.library import Paths
from discjockey.rekordbox.preview import PreviewFailed, PreviewRefused, preview

FIXTURES = Path(__file__).parent / "fixtures"
LAME = FIXTURES / "clicks-lame.mp3"
OWN = "local:1"
MP3 = "Library/Mine/old name.mp3"

pytestmark = needs_ffmpeg


def put(paths, rel, src=None, data=None):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    if src is not None:
        shutil.copyfile(src, f)
    else:
        f.write_bytes(data)
    return f


@pytest.fixture
def paths(tmp_path):
    return Paths(tmp_path / "music", support=tmp_path / ".support")


def rekordbox_for(tmp_path, monkeypatch, file, **row):
    """A rekordbox library holding `file` with 3 cues, an analysis measured at the LAME tag's 1105 samples."""
    folder = tmp_path / "rb"
    make_master(folder, [{"ID": "1", "path": str(file), "cues": 3, "artist": "Artist", "album": "", **row}])
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    audio_, rate = quality.decode_mono(file)
    dat = folder / "share/PIONEER/USBANLZ/000/1/ANLZ0000.DAT"
    make_anlz(dat, [pqtz_tag(40)])
    make_anlz(dat.with_suffix(".EXT"), [pwv3_tag(pwv3_from(audio_, rate, 1105 / rate))])
    return folder


# --- file_facts ---

def test_file_facts_read_the_format_the_tags_and_the_cover(tmp_path):
    f = write_aiff(tmp_path / "a.aiff", music(1))
    plain = audio.file_facts(f)
    assert (plain.ext, plain.codec, plain.sample_rate, plain.bits, plain.has_cover) == (
        ".aiff", "pcm_s16be", 44100, 16, False)
    assert plain.tags == dict.fromkeys(audio.TEXT_FIELDS, "")
    audio.write_tags(f, title="Song", artists=("A", "B"), album="Album", isrc="ISRC1", label="Label",
                     cover=TINY_JPEG, comment="the line")
    tagged = audio.file_facts(f)
    assert tagged.tags == {"title": "Song", "artist": "A, B", "album": "Album", "label": "Label", "isrc": "ISRC1",
                           "comment": "the line"}
    assert tagged.has_cover


def test_file_facts_of_an_mp3_and_of_a_file_that_is_not_audio(tmp_path):
    got = audio.file_facts(LAME)
    assert (got.ext, got.codec, got.sample_rate, got.bits, got.has_cover) == (".mp3", "mp3", 44100, None, False)
    junk = tmp_path / "junk.mp3"
    junk.write_bytes(b"not audio at all")
    with pytest.raises(RuntimeError):
        audio.file_facts(junk)
    with pytest.raises(RuntimeError):
        audio.file_facts(tmp_path / "gone.mp3")


# --- an own MP3 that rekordbox holds ---

def test_an_own_mp3_in_rekordbox_would_convert_and_keeps_the_users_title(tmp_path, monkeypatch, paths):
    f = put(paths, MP3, LAME)
    library(paths, {OWN: entry()})
    rekordbox_for(tmp_path, monkeypatch, f, Title="My own title")
    got = preview(paths, track=OWN)
    assert got["ok"] and got["track"] == OWN and got["file"] == str(f.absolute())
    assert (got["codec"], got["sample_rate"], got["bits"]) == ("mp3", 44100, None)
    assert got["rekordbox"] == {"state": "ready", "running": False, "problem": None}
    assert got["timing"] == {"result": "measured", "offset_samples": 1105}
    (row,) = got["entries"]
    assert (row["id"], row["cues"], row["grid"], row["pwv3"], row["cloud"]) == ("1", 3, True, True, False)
    assert abs(row["offset_ms"] - 1105 / 44.1) < 0.12 and row["expected_ms"] == pytest.approx(1105 / 44.1, abs=0.03)
    assert row["score"] > 0.9
    assert row["fields_kept"] == ["title"]  # rekordbox says "My own title", the file says nothing
    assert got["eligible"] == {"same_track": "no_upgrade", "convert": None, "rename": "needs_convert"}
    assert got["new_file"] == str(paths.root / "Library/Mine/Artist - Song.aiff")
    assert got["superseded"] == str(paths.root / "Superseded/Mine/old name.mp3")


def test_the_preview_leaves_nothing_behind_and_takes_no_lock(tmp_path, monkeypatch, paths):
    f = put(paths, MP3, LAME)
    library(paths, {OWN: entry()})
    folder = rekordbox_for(tmp_path, monkeypatch, f)
    music_before, rb_before = snapshot(paths.root / "Library"), snapshot(folder)
    from discjockey.library import run_lock
    with run_lock(paths.lock):  # a running sync doesn't stop a read
        preview(paths, track=OWN)
    assert snapshot(folder) == rb_before and snapshot(paths.root / "Library") == music_before
    assert not (folder / "master.db-wal").exists() and not (folder / "master.db-shm").exists()
    assert not (paths.root / "Superseded").exists() and not (paths.root / "Upgrades ready").exists()


def test_a_cloud_track_and_an_unreadable_library_are_reasons(tmp_path, monkeypatch, paths):
    f = put(paths, MP3, LAME)
    library(paths, {OWN: entry()})
    rekordbox_for(tmp_path, monkeypatch, f, usn=7)
    got = preview(paths, track=OWN)
    assert got["entries"][0]["cloud"] and got["eligible"]["convert"] == "cloud"
    assert got["new_file"] is None and got["superseded"] is None  # nothing can run
    make_master(tmp_path / "rb2", [{"path": str(f)}], key="ab" * 32)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path / "rb2"))
    got = preview(paths, track=OWN)
    assert got["rekordbox"]["state"] == "unreadable" and got["rekordbox"]["problem"] == "key"
    assert got["timing"] == {"result": "unreadable", "offset_samples": None}
    assert got["eligible"]["convert"] == "rekordbox_unreadable"


def test_no_rekordbox_on_this_mac(paths):
    put(paths, MP3, LAME)
    library(paths, {OWN: entry()})
    got = preview(paths, track=OWN)  # conftest: an empty rekordbox folder
    assert got["rekordbox"]["state"] == "none" and got["entries"] == []
    assert got["timing"] == {"result": "no_rekordbox", "offset_samples": 0}
    assert got["eligible"]["convert"] is None


# --- parked upgrades and AIFF files ---

def parked(rel, result="exact"):
    return {"file": rel, "source": "qobuz", "source_id": "q1", "source_format": "flac", "found": "2026-10-10",
            "alignment": Alignment(result, 0, 0.0, 0.0, "").to_dict()}


def test_an_aiff_with_a_same_edit_upgrade_swaps_in_place(paths):
    rel, up = "Library/Mine/Artist - Song.aiff", "Upgrades ready/Mine/Artist - Song.aiff"
    (paths.root / rel).parent.mkdir(parents=True)
    write_aiff(paths.root / rel, music(1))
    put(paths, up, data=b"parked")
    library(paths, {"t1": entry(rel, source="youtube_music", source_id="y1", source_format="opus",
                                status="not_lossless", cutoff_hz=19000, upgrade=parked(up))})
    got = preview(paths, track="t1")
    assert got["eligible"]["same_track"] is None
    assert got["new_file"] == str(paths.root / rel)  # the swap keeps the file's own path
    assert got["superseded"] == str(paths.root / "Superseded/Mine/Artist - Song.aiff")
    assert got["eligible"]["convert"] == "downloaded" and got["eligible"]["rename"] == "downloaded"


def test_a_different_edit_needs_the_users_choice(paths):
    rel, up = "Library/Mine/Artist - Song.aiff", "Upgrades ready/Mine/Artist - Song.aiff"
    (paths.root / rel).parent.mkdir(parents=True)
    write_aiff(paths.root / rel, music(1))
    put(paths, up, data=b"parked")
    library(paths, {"t1": entry(rel, source="youtube_music", source_id="y1", source_format="opus",
                                status="not_lossless", upgrade=parked(up, "different"))})
    got = preview(paths, track="t1")
    assert got["eligible"]["same_track"] == "needs_choice" and got["new_file"] is None


def test_a_non_aiff_upgrade_becomes_a_new_aiff_in_the_files_folder(paths):
    up = "Upgrades ready/Mine/Artist - Song.aiff"
    put(paths, MP3, LAME)
    put(paths, up, data=b"parked")
    library(paths, {OWN: entry(upgrade=parked(up))})
    got = preview(paths, track=OWN)
    assert got["eligible"]["same_track"] is None
    assert got["eligible"]["convert"] == "upgrade_waits"  # the parked upgrade wins (plan stage D §0.2)
    assert got["new_file"] == str(paths.root / "Library/Mine/Artist - Song.aiff")  # a lossless one leaves not_lossless/
    assert got["superseded"] == str(paths.root / "Superseded/Mine/old name.mp3")


def clean_aiff(paths, rel):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    write_aiff(f, music(1))
    audio.write_tags(f, title="Song", artists=("Artist",), album="", isrc=None, label=None, cover=None, comment="x")
    return f


def test_same_track_keeps_what_the_parked_downloads_text_would_leave_alone(tmp_path, monkeypatch, paths):
    up = "Upgrades ready/Mine/Artist - Song.aiff"
    f = put(paths, MP3, LAME)
    parked_file = paths.root / up
    parked_file.parent.mkdir(parents=True)
    write_aiff(parked_file, music(1))
    audio.write_tags(parked_file, title="Qobuz Title", artists=("Artist",), album="", isrc=None, label=None, cover=None,
                     comment="x")
    library(paths, {OWN: entry(upgrade=parked(up))})  # the record says "Song", the download says "Qobuz Title"
    rekordbox_for(tmp_path, monkeypatch, f, Title="Qobuz Title")
    got = preview(paths, track=OWN)
    assert got["eligible"]["same_track"] is None
    assert got["entries"][0]["fields_kept"] == []  # the new file says what rekordbox shows: nothing to lose
    parked_file.write_bytes(b"parked")  # a parked file that can't be read: the record's text is the guess
    assert preview(paths, track=OWN)["entries"][0]["fields_kept"] == ["title"]


def test_a_clean_aiff_with_a_messy_name_would_only_be_renamed(paths):
    clean_aiff(paths, "Library/Mine/track01.aiff")
    library(paths, {OWN: entry("Library/Mine/track01.aiff", source_format="pcm_s16be")})
    got = preview(paths, track=OWN)
    assert got["eligible"] == {"same_track": "no_upgrade", "convert": "clean_aiff", "rename": None}
    assert got["new_file"] == str(paths.root / "Library/Mine/Artist - Song.aiff")
    assert got["superseded"] is None  # a rename moves nothing aside


def test_a_clean_aiff_with_its_clean_name_has_nothing_to_do(paths):
    clean_aiff(paths, "Library/Mine/Artist - Song.aiff")
    library(paths, {OWN: entry("Library/Mine/Artist - Song.aiff", source_format="pcm_s16be")})
    got = preview(paths, track=OWN)
    assert got["eligible"] == {"same_track": "no_upgrade", "convert": "clean_aiff", "rename": "named_already"}
    assert got["new_file"] is None


# --- a path, and refusals ---

def test_a_path_the_library_does_not_know_still_gets_the_rekordbox_part(tmp_path, monkeypatch, paths):
    f = tmp_path / "elsewhere" / "x.mp3"
    f.parent.mkdir()
    shutil.copyfile(LAME, f)
    rekordbox_for(tmp_path, monkeypatch, f, Title="Edited")
    got = preview(paths, path=f)
    assert got["track"] is None and got["new_file"] is None and got["superseded"] is None
    assert got["eligible"] == dict.fromkeys(("same_track", "convert", "rename"), "not_in_library")
    assert got["timing"]["result"] == "measured" and got["entries"][0]["cues"] == 3
    # rekordbox shows a title and an artist the file's tags (empty) don't, so they are the user's own: kept
    assert got["entries"][0]["fields_kept"] == ["title", "artist"]
    assert preview(None, path=str(f))["track"] is None  # no music folder at all


def test_a_path_of_a_library_file_finds_its_song(paths):
    f = put(paths, MP3, LAME)
    library(paths, {OWN: entry()})
    got = preview(paths, path=f)
    assert got["track"] == OWN and got["eligible"]["convert"] is None


def test_refusals_and_failures(paths):
    put(paths, MP3, LAME)
    library(paths, {OWN: entry(), "t2": entry("Library/Mine/gone.mp3", title="Gone"), "t3": entry(path=None)})
    with pytest.raises(PreviewRefused) as e:
        preview(paths, track="nope")
    assert e.value.reason == "unknown_track"
    for key in ("t2", "t3"):
        with pytest.raises(PreviewRefused) as e:
            preview(paths, track=key)
        assert e.value.reason == "file_missing"
    with pytest.raises(PreviewRefused) as e:
        preview(paths, path=paths.root / "nothing.mp3")
    assert e.value.reason == "file_missing"
    with pytest.raises(PreviewRefused) as e:
        preview(paths, path="/Volumes/NoSuchDrive-Discjockey-Test/a.mp3")
    assert e.value.reason == "away"
    with pytest.raises(PreviewRefused):
        preview(None, track=OWN)
    bad = put(paths, "Library/Mine/bad.mp3", data=b"not audio")
    with pytest.raises(PreviewFailed):
        preview(paths, path=bad)
    with pytest.raises(ValueError):
        preview(paths)


def test_an_ffmpeg_failure_in_the_timing_is_a_failure_of_that_file(paths, monkeypatch):
    put(paths, MP3, LAME)
    library(paths, {OWN: entry()})

    def broken(path):
        raise rekordbox.offset.probe.ProbeError("ffmpeg could not decode x")
    with pytest.raises(PreviewFailed, match="couldn't read old name.mp3"):
        preview(paths, track=OWN, offset=broken)


