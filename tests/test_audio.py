import shutil
import subprocess

import pytest
from mutagen.aiff import AIFF

from discjockey.audio import convert_to_aiff, write_tags
from discjockey.quality import probe

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def make_flac(path, seconds=3, rate=48000):
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", f"anoisesrc=d={seconds}:c=white:r={rate}:a=0.3",
         "-ac", "2", "-sample_fmt", "s32", "-c:a", "flac", str(path)],
        check=True,
    )


def test_convert_to_16_bit_44k_aiff(tmp_path):
    src, dst = tmp_path / "in.flac", tmp_path / "out.aiff"
    make_flac(src)
    convert_to_aiff(src, dst)
    info = probe(dst)
    assert (info.codec, info.sample_rate) == ("pcm_s16be", 44100)
    assert abs(info.duration_s - 3) < 0.1


def test_write_id3v23_tags(tmp_path):
    src, dst = tmp_path / "in.flac", tmp_path / "out.aiff"
    make_flac(src, seconds=1)
    convert_to_aiff(src, dst)
    write_tags(dst, title="Gimme Gimme", artists=("Vatoz Locoz", "Other"), album="Album",
               isrc="DECE72605755", label="Label", cover=b"\xff\xd8\xff\xe0fake", comment="Qobuz FLAC · verified lossless")
    tags = AIFF(str(dst)).tags
    assert tags.version[:2] == (2, 3)
    assert str(tags["TIT2"]) == "Gimme Gimme"
    assert str(tags["TPE1"]) == "Vatoz Locoz, Other"
    assert str(tags["TSRC"]) == "DECE72605755"
    assert str(tags["TPUB"]) == "Label"
    assert tags.getall("APIC")[0].data.startswith(b"\xff\xd8")
    assert tags.getall("COMM")[0].text == ["Qobuz FLAC · verified lossless"]


def test_conversion_reports_progress(tmp_path):
    src, dst = tmp_path / "in.flac", tmp_path / "out.aiff"
    make_flac(src, seconds=20)
    seen = []
    convert_to_aiff(src, dst, duration_s=20.0, progress=lambda done, total: seen.append((done, total)))
    assert seen and seen[-1][1] == 20.0
    assert 19 <= seen[-1][0] <= 20.5
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)


class Stop(BaseException):
    """Stands in for events.Cancelled (Task 9)."""


def test_stop_during_conversion_propagates(tmp_path):
    src, dst = tmp_path / "in.flac", tmp_path / "out.aiff"
    make_flac(src, seconds=20)
    calls = []

    def stop(done, total):
        calls.append(done)
        raise Stop()

    with pytest.raises(Stop):
        convert_to_aiff(src, dst, duration_s=20.0, progress=stop)
    assert len(calls) == 1  # the first progress report already stops it; ffmpeg is killed and reaped


def test_copy_tags(tmp_path):
    from discjockey.audio import copy_tags
    src, a, b = tmp_path / "in.flac", tmp_path / "a.aiff", tmp_path / "b.aiff"
    make_flac(src, seconds=1)
    convert_to_aiff(src, a)
    convert_to_aiff(src, b)
    write_tags(a, title="Song", artists=("Artist",), album="Album", isrc=None, label=None,
               cover=b"\xff\xd8\xff\xe0fake", comment="Qobuz FLAC · verified lossless")
    copy_tags(a, b)
    tags = AIFF(str(b)).tags
    assert tags.version[:2] == (2, 3) and str(tags["TIT2"]) == "Song"
    assert tags.getall("COMM")[0].text == ["Qobuz FLAC · verified lossless"] and tags.getall("APIC")
