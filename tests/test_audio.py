import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest
from mutagen.aiff import AIFF

from audio_helpers import picture
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
               isrc="DECE72605755", label="Label", cover=picture(300, 300), comment="Qobuz FLAC · verified lossless")
    tags = AIFF(str(dst)).tags
    assert tags.version[:2] == (2, 3)
    assert str(tags["TIT2"]) == "Gimme Gimme"
    assert str(tags["TPE1"]) == "Vatoz Locoz, Other"
    assert str(tags["TSRC"]) == "DECE72605755"
    assert str(tags["TPUB"]) == "Label"
    assert tags.getall("APIC")[0].data.startswith(b"\xff\xd8") and tags.getall("APIC")[0].mime == "image/jpeg"
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
               cover=picture(300, 300), comment="Qobuz FLAC · verified lossless")
    copy_tags(a, b)
    tags = AIFF(str(b)).tags
    assert tags.version[:2] == (2, 3) and str(tags["TIT2"]) == "Song"
    assert tags.getall("COMM")[0].text == ["Qobuz FLAC · verified lossless"] and tags.getall("APIC")


# --- render_aiff: any file as a 16-bit/44.1 kHz AIFF, shifted to the sample (plan rekordbox stage A §1.8) ---

def _render(src, tmp_path, k, name="out.aiff"):
    from discjockey.audio import render_aiff
    dst = tmp_path / name
    render_aiff(src, dst, k)
    return dst


@pytest.mark.parametrize("k", [0, 517, -517])
def test_render_keeps_the_samples_of_a_16_bit_44k_aiff_and_shifts_them_exactly(tmp_path, k):
    from audio_helpers import music, pcm, write_aiff
    src = write_aiff(tmp_path / "in.aiff", music(3))
    a, b = pcm(src), pcm(_render(src, tmp_path, k))
    want = a[k:] if k >= 0 else np.concatenate([np.zeros((-k, 2), dtype=a.dtype), a])
    assert np.array_equal(b, want)  # no resampling, no dither: every sample as it was
    assert AIFF(str(tmp_path / "out.aiff")).tags is None  # no metadata: callers tag


@pytest.mark.parametrize("make", ["flac_24_96", "wav_48"])
def test_render_makes_16_bit_44k_from_other_formats(tmp_path, make):
    src = tmp_path / ("in.flac" if make == "flac_24_96" else "in.wav")
    if make == "flac_24_96":
        make_flac(src, seconds=2, rate=96000)
        assert (probe(src).bits, probe(src).sample_rate) == (24, 96000)
    else:
        subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=2:c=white:r=48000:a=0.3",
                        "-c:a", "pcm_s24le", str(src)], check=True)
    info = probe(_render(src, tmp_path, -100))
    assert (info.codec, info.sample_rate, info.bits, info.channels) == ("pcm_s16be", 44100, 16, probe(src).channels)
    assert abs(info.duration_s - (2 + 100 / 44100)) < 0.002


def test_render_refuses_a_file_that_is_not_audio(tmp_path):
    from discjockey.audio import ConversionError
    bad = tmp_path / "bad.m4a"
    bad.write_bytes(b"not audio")
    with pytest.raises(ConversionError):
        _render(bad, tmp_path, 10)


def _mono(path):
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-ac", "1", "-f", "f32le", "-"],
                       capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype=np.float32)


def _lag(x, ref):
    """Where `ref`'s content sits in `x`, in samples (positive: later in x), by full cross-correlation."""
    n = 1 << int(np.ceil(np.log2(len(x) + len(ref))))
    c = np.fft.irfft(np.fft.rfft(x, n) * np.conj(np.fft.rfft(ref, n)), n)
    i = int(np.argmax(c))
    return i if i < n // 2 else i - n


def test_render_puts_the_audio_where_rekordboxs_timeline_has_it(tmp_path):
    """The clicks of an M4A and both MP3 fixtures, rendered with k = −d, sit where rekordbox's timeline has them
    (ffmpeg's decode delayed by rekordbox's extra samples, as rekordbox_helpers.pwv3_from builds it) to ±1 sample."""
    from discjockey import quality
    from rekordbox_helpers import clicks, write_wav
    fixtures = Path(__file__).parent / "fixtures"
    wav = write_wav(tmp_path / "clicks.wav", clicks(12, 48000), 48000)
    m4a = tmp_path / "clicks.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(m4a)], check=True)
    cases = [(m4a, 1024), (fixtures / "clicks-lame.mp3", 1105), (fixtures / "clicks-lame.mp3", 1105 + 1152),
             (fixtures / "clicks-notag.mp3", 1105)]  # file, rekordbox's extra samples at the file's own rate
    for src, extra in cases:
        decoded, sr = quality.decode_mono(src)
        d = round(extra / sr * 44100)
        timeline = np.concatenate([np.zeros(extra, dtype=np.float32), decoded])  # rekordbox's timeline, native rate
        if sr != 44100:  # onto the 44.1 kHz grid (linear is plenty for where the clicks are)
            t = np.arange(int(len(timeline) * 44100 / sr)) / 44100
            timeline = np.interp(t, np.arange(len(timeline)) / sr, timeline).astype(np.float32)
        out = _mono(_render(src, tmp_path, -d, f"{src.stem}-{extra}.aiff"))
        assert abs(_lag(out, timeline)) <= 1, (src.name, extra)


# --- issue 33 stage D: CDJ-safe artwork (plan §0.11), a file's own picture, the stream's bitrate ---

def jpeg_size(data):
    from discjockey.audio import _baseline_jpeg_size
    return _baseline_jpeg_size(data)


def test_a_large_png_becomes_a_small_baseline_jpeg():
    from discjockey.audio import COVER_MAX_BYTES, cdj_cover
    out = cdj_cover(picture(3000, 3000, "png"))
    assert out is not None and len(out) <= COVER_MAX_BYTES
    assert jpeg_size(out) == (600, 600)  # baseline (SOF0) and scaled down


def test_a_wide_picture_keeps_its_proportions_and_a_small_one_is_never_scaled_up():
    from discjockey.audio import cdj_cover
    assert jpeg_size(cdj_cover(picture(1800, 900, "png"))) == (600, 300)
    out = cdj_cover(picture(200, 100, "png"))
    assert jpeg_size(out) == (200, 100)


def test_a_600px_baseline_jpeg_comes_back_byte_identical():
    from discjockey.audio import cdj_cover
    data = picture(600, 600)
    assert jpeg_size(data) == (600, 600)
    assert cdj_cover(data) == data


def test_a_jpeg_over_the_size_limit_or_in_pixels_is_made_to_fit():
    from discjockey.audio import COVER_MAX_BYTES, cdj_cover
    big = picture(2000, 2000)
    assert jpeg_size(big) == (2000, 2000)
    out = cdj_cover(big)
    assert jpeg_size(out) == (600, 600) and len(out) <= COVER_MAX_BYTES


def test_a_progressive_jpeg_is_not_taken_as_baseline():
    from discjockey.audio import _baseline_jpeg_size
    data = bytearray(picture(300, 300))
    i = data.index(b"\xff\xc0")
    data[i + 1] = 0xC2  # the frame header names progressive DCT
    assert _baseline_jpeg_size(bytes(data)) is None


def test_garbage_and_empty_data_are_no_cover():
    from discjockey.audio import cdj_cover
    assert cdj_cover(b"") is None
    assert cdj_cover(b"not a picture at all") is None
    assert cdj_cover(b"\xff\xd8\xff\xe0 tiny cover \xff\xd9") is None


def test_write_tags_and_copy_tags_pass_covers_through_cdj_cover(tmp_path):
    from discjockey.audio import copy_tags
    src, a, b = tmp_path / "in.flac", tmp_path / "a.aiff", tmp_path / "b.aiff"
    make_flac(src, seconds=1)
    convert_to_aiff(src, a)
    convert_to_aiff(src, b)
    write_tags(a, title="Song", artists=("Artist",), album="Album", isrc=None, label=None,
               cover=picture(2000, 2000, "png"), comment="c")
    assert jpeg_size(AIFF(str(a)).tags.getall("APIC")[0].data) == (600, 600)
    # a big cover already in a file (written by something else) is made CDJ-safe on its way to the new file
    from mutagen.id3 import APIC
    f = AIFF(str(a))
    f.tags.setall("APIC", [APIC(encoding=1, mime="image/png", type=3, desc="", data=picture(1500, 1500, "png"))])
    f.save(v2_version=3)
    copy_tags(a, b)
    frame = AIFF(str(b)).tags.getall("APIC")[0]
    assert frame.mime == "image/jpeg" and jpeg_size(frame.data) == (600, 600)
    c = tmp_path / "c.aiff"
    convert_to_aiff(src, c)
    write_tags(c, title="Song", artists=("Artist",), album="Album", isrc=None, label=None, cover=b"garbage",
               comment="c")
    assert not AIFF(str(c)).tags.getall("APIC")  # a cover that can't be made safe is left out


def test_embedded_cover_reads_the_picture_of_any_format(tmp_path):
    from mutagen.flac import FLAC, Picture
    from mutagen.mp4 import MP4, MP4Cover

    from audio_helpers import music, to_aac, write_aiff
    from discjockey.audio import embedded_cover
    pic = picture(300, 300)
    aiff = write_aiff(tmp_path / "a.aiff", music(1))
    assert embedded_cover(aiff) is None
    m4a = to_aac(aiff, tmp_path / "a.m4a")  # before the picture: ffmpeg would take it for a video stream
    write_tags(aiff, title="T", artists=("A",), album="", isrc=None, label=None, cover=pic, comment="")
    assert embedded_cover(aiff) == pic
    f = MP4(str(m4a))
    f["covr"] = [MP4Cover(pic, imageformat=MP4Cover.FORMAT_JPEG)]
    f.save()
    assert embedded_cover(m4a) == pic
    flac = tmp_path / "a.flac"
    make_flac(flac, seconds=1)
    picture_block = Picture()
    picture_block.data, picture_block.type, picture_block.mime = pic, 3, "image/jpeg"
    f = FLAC(str(flac))
    f.add_picture(picture_block)
    f.save()
    assert embedded_cover(flac) == pic
    assert embedded_cover(tmp_path / "nothing.mp3") is None  # not there


def test_the_stored_bitrate_is_the_streams_not_the_files_with_its_cover(tmp_path):
    """ffprobe's format bit rate counts embedded artwork: a 320 kbps MP3 with a big picture must not read above 320."""
    from audio_helpers import music, write_aiff
    from discjockey.quality import file_audio
    mp3 = tmp_path / "a.mp3"
    wav = write_aiff(tmp_path / "a.aiff", music(3))
    pic = tmp_path / "cover.jpg"
    pic.write_bytes(picture(1500, 1500))
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-i", str(pic), "-map", "0:a",
                        "-map", "1:v", "-c:a", "libmp3lame", "-b:a", "320k", "-c:v", "copy", "-id3v2_version", "3",
                        str(mp3)], capture_output=True)
    if r.returncode != 0:
        pytest.skip("this ffmpeg has no MP3 encoder")
    info = probe(mp3)
    assert info.kbps > 320 and info.stream_kbps == 320
    assert file_audio(info).kbps == 320
