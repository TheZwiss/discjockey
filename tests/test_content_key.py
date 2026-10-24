"""Content keys: the audio payload of each format is found, tag edits keep the key, audio changes change it."""
from __future__ import annotations

import hashlib
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
import pytest
from mutagen.apev2 import APEv2
from mutagen.flac import FLAC, Picture
from mutagen.id3 import APIC, ID3, TIT2
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggopus import OggOpus
from mutagen.oggvorbis import OggVorbis

from audio_helpers import SR, music, needs_ffmpeg, pcm, to_aac, write_aiff
from discjockey.content_key import AUDIO_EXTS, WINDOW, content_key

PICTURE = bytes(range(256)) * 400  # ~100 KB


def _encoders() -> str:
    if shutil.which("ffmpeg") is None:
        return ""
    return subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True).stdout


ENCODERS = _encoders()


def needs_encoder(name: str):
    return pytest.mark.skipif(f" {name} " not in ENCODERS, reason=f"ffmpeg has no {name} encoder")


def windows_key(data: bytes) -> str:
    """The key the spec describes, computed straight from the payload bytes."""
    n = len(data)
    h = hashlib.sha256()
    if n <= 3 * WINDOW:
        h.update(data)
    else:
        mid = (n - WINDOW) // 2
        for start in (0, mid, n - WINDOW):
            h.update(data[start:start + WINDOW])
    return f"1:{n}:{h.hexdigest()}"


def length_of(key: str) -> int:
    return int(key.split(":")[1])


def convert(src: Path, dst: Path, *codec: str) -> Path:
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), *codec, str(dst)], check=True)
    return dst


def source(tmp_path: Path, seconds: float = 5, nudge: bool = False) -> Path:
    x = music(seconds, seed=3)
    if nudge:
        x = x.copy()
        x[SR // 10] += 0.25  # one sample, early on (inside the first window)
    return write_aiff(tmp_path / ("nudged.aiff" if nudge else "src.aiff"), x)


# --- one encoder per format; the encoders the shipped ffmpeg has (CI uses it) -------------------------------------

def make_aiff(src: Path, dst: Path) -> Path:
    return Path(shutil.copy(src, dst))


def make_wav(src: Path, dst: Path) -> Path:
    return convert(src, dst, "-c:a", "pcm_s16le")


def make_flac(src: Path, dst: Path) -> Path:
    return convert(src, dst, "-c:a", "flac")


def make_m4a(src: Path, dst: Path) -> Path:
    return to_aac(src, dst)


def make_m4a_faststart(src: Path, dst: Path) -> Path:
    return convert(src, dst, "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart")


def make_ogg(src: Path, dst: Path) -> Path:
    return convert(src, dst, "-c:a", "vorbis", "-strict", "-2", "-ac", "2")


def make_opus(src: Path, dst: Path) -> Path:
    return convert(src, dst, "-c:a", "opus", "-strict", "-2", "-ar", "48000")


def make_mp3(src: Path, dst: Path) -> Path:
    return convert(src, dst, "-c:a", "libmp3lame", "-b:a", "192k")


# --- tag editors: a title and a ~100 KB picture --------------------------------------------------------------------

def tag_id3_chunk(path: Path) -> None:  # AIFF and WAV keep ID3 in a chunk
    from mutagen import File
    f = File(path)
    if f.tags is None:
        f.add_tags()
    f.tags.add(TIT2(encoding=3, text="A new title"))
    f.tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="cover", data=PICTURE))
    f.save()


def tag_flac(path: Path) -> None:
    f = FLAC(path)
    f["title"] = "A new title"
    pic = Picture()
    pic.type, pic.mime, pic.data = 3, "image/jpeg", PICTURE
    f.add_picture(pic)
    f.save()


def tag_mp4(path: Path) -> None:
    f = MP4(path)
    f["\xa9nam"] = ["A new title"]
    f["covr"] = [MP4Cover(PICTURE, imageformat=MP4Cover.FORMAT_JPEG)]
    f.save()


def tag_ogg(cls):
    def tag(path: Path) -> None:
        import base64
        f = cls(path)
        f["title"] = "A new title"
        pic = Picture()
        pic.type, pic.mime, pic.data = 3, "image/jpeg", PICTURE
        f["metadata_block_picture"] = [base64.b64encode(pic.write()).decode("ascii")]
        f.save()
    return tag


def tag_mp3(path: Path) -> None:
    tags = ID3()
    tags.add(TIT2(encoding=3, text="A new title"))
    tags.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="cover", data=PICTURE))
    tags.save(path, v1=2)  # ID3v2 at the start and ID3v1 at the end


FORMATS = [
    pytest.param(".aiff", make_aiff, tag_id3_chunk, id="aiff"),
    pytest.param(".wav", make_wav, tag_id3_chunk, id="wav"),
    pytest.param(".flac", make_flac, tag_flac, id="flac", marks=needs_encoder("flac")),
    pytest.param(".m4a", make_m4a, tag_mp4, id="m4a", marks=needs_encoder("aac")),
    pytest.param(".m4a", make_m4a_faststart, tag_mp4, id="m4a-faststart", marks=needs_encoder("aac")),
    pytest.param(".ogg", make_ogg, tag_ogg(OggVorbis), id="ogg", marks=needs_encoder("vorbis")),
    pytest.param(".opus", make_opus, tag_ogg(OggOpus), id="opus", marks=needs_encoder("opus")),
    pytest.param(".mp3", make_mp3, tag_mp3, id="mp3", marks=needs_encoder("libmp3lame")),
]


@needs_ffmpeg
@pytest.mark.parametrize("ext,make,tag", FORMATS)
def test_payload_found_and_tags_dont_change_the_key(tmp_path, ext, make, tag):
    f = make(source(tmp_path), tmp_path / f"a{ext}")
    before = content_key(f)
    assert before.startswith("1:")
    assert 0 < length_of(before) < f.stat().st_size  # the payload, not the whole file
    tag(f)
    assert content_key(f) == before
    copy = Path(shutil.copy(f, tmp_path / f"Renamed copy{ext}"))
    assert content_key(copy) == before


@needs_ffmpeg
@pytest.mark.parametrize("ext,make,tag", FORMATS)
def test_changing_one_sample_changes_the_key(tmp_path, ext, make, tag):
    a = make(source(tmp_path), tmp_path / f"a{ext}")
    b = make(source(tmp_path, nudge=True), tmp_path / f"b{ext}")
    assert content_key(a) != content_key(b)


@needs_ffmpeg
def test_aiff_key_is_the_windows_over_the_samples(tmp_path):
    f = source(tmp_path)  # 5 s: more than three windows, so the windows are used
    samples = pcm(f)
    payload = samples.astype(">i2").tobytes()
    assert len(payload) > 3 * WINDOW
    assert content_key(f) == windows_key(payload)


@needs_ffmpeg
def test_wav_key_length_is_the_sample_bytes(tmp_path):
    f = make_wav(source(tmp_path), tmp_path / "a.wav")
    frames = len(pcm(f))
    assert length_of(content_key(f)) == frames * 2 * 2


@needs_ffmpeg
def test_short_payload_is_hashed_whole(tmp_path):
    f = write_aiff(tmp_path / "short.aiff", music(1, seed=1))
    payload = pcm(f).astype(">i2").tobytes()
    assert len(payload) <= 3 * WINDOW
    assert content_key(f) == windows_key(payload)


@needs_ffmpeg
def test_truncated_file_falls_back_to_the_whole_file(tmp_path):
    f = source(tmp_path)
    data = f.read_bytes()[:-1000]  # the SSND chunk now claims more than the file has
    f.write_bytes(data)
    assert content_key(f) == windows_key(data)


@needs_ffmpeg
def test_flac_with_a_leading_id3_tag_keeps_its_key(tmp_path):
    f = make_flac(source(tmp_path), tmp_path / "a.flac")
    before = content_key(f)
    tags = ID3()
    tags.add(TIT2(encoding=3, text="Tagged by another app"))
    tags.save(f)
    assert f.read_bytes()[:3] == b"ID3"
    assert content_key(f) == before


# --- hand-made files: exact payloads, no ffmpeg needed ---------------------------------------------------------------

FRAMES = b"\xff\xfb\x90\x64" + bytes(range(256)) * 20  # stands in for MPEG frames


def syncsafe(n: int) -> bytes:
    return bytes([(n >> 21) & 0x7F, (n >> 14) & 0x7F, (n >> 7) & 0x7F, n & 0x7F])


def ape(path: Path, **items: str) -> None:
    tag = APEv2()
    tag.update(items)
    tag.save(path)


def test_mp3_strips_id3v2_with_footer_id3v1_and_ape(tmp_path):
    body = b"\x00" * 300
    id3v2 = b"ID3\x04\x00\x10" + syncsafe(len(body)) + body + b"3DI\x04\x00\x10" + syncsafe(len(body))
    id3v1 = b"TAG" + b"\x20" * 125
    f = tmp_path / "a.mp3"
    f.write_bytes(id3v2 + FRAMES + id3v1)
    assert content_key(f) == windows_key(FRAMES)
    ape(f, Title="x")  # written before ID3v1, as players expect
    assert content_key(f) == windows_key(FRAMES)


def test_mp3_tag_edits_with_mutagen_keep_the_key(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(FRAMES)
    assert content_key(f) == windows_key(FRAMES)
    tag_mp3(f)
    ape(f, Title="x", Artist="y")
    assert content_key(f) == windows_key(FRAMES)


def test_mp3_strips_the_extended_id3v1_block(tmp_path):
    f = tmp_path / "a.mp3"
    f.write_bytes(FRAMES + b"TAG+" + b"\x20" * 223 + b"TAG" + b"\x20" * 125)
    assert content_key(f) == windows_key(FRAMES)


def test_flac_strips_trailing_id3v1_and_ape_tags(tmp_path):
    frames = b"\xff\xf8" + bytes(range(256)) * 20  # stands in for FLAC frames
    f = tmp_path / "a.flac"
    f.write_bytes(b"fLaC" + b"\x80\x00\x00\x22" + b"\x00" * 34 + frames)  # STREAMINFO, the last block
    assert content_key(f) == windows_key(frames)
    ape(f, Title="x")
    with open(f, "ab") as out:
        out.write(b"TAG" + b"\x20" * 125)
    assert content_key(f) == windows_key(frames)


def test_m4a_uses_every_mdat_in_order_and_64_bit_sizes(tmp_path):
    def atom(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", 8 + len(data)) + kind + data

    def wide(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", 1) + kind + struct.pack(">Q", 16 + len(data)) + data

    a, b, c = b"first-audio" * 10, b"second-audio" * 10, b"last-audio" * 10
    f = tmp_path / "a.m4a"
    f.write_bytes(atom(b"ftyp", b"M4A \x00\x00\x00\x00") + atom(b"mdat", a) + atom(b"moov", b"\x00" * 50)
                  + wide(b"mdat", b) + struct.pack(">I", 0) + b"mdat" + c)  # size 0: to the end of the file
    assert content_key(f) == windows_key(a + b + c)


def ogg_page(serial: int, seq: int, packets: list[bytes], header_type: int = 0) -> bytes:
    lacing, body = b"", b""
    for p in packets:
        n = len(p)
        lacing += b"\xff" * (n // 255) + bytes([n % 255])
        body += p
    return (b"OggS\x00" + bytes([header_type]) + struct.pack("<qIIIB", 0, serial, seq, 0, len(lacing))
            + lacing + body)


def test_ogg_key_is_the_page_bodies_after_the_header_packets(tmp_path):
    head = b"OpusHead" + b"\x01\x02" + b"\x00" * 9
    audio1, audio2 = b"\x11" * 400, b"\x22" * 100
    f = tmp_path / "a.opus"

    def build(comment: bytes, first_seq: int) -> bytes:
        return (ogg_page(7, 0, [head], 2) + ogg_page(7, 1, [b"OpusTags" + comment])
                + ogg_page(7, first_seq, [audio1]) + ogg_page(7, first_seq + 1, [audio2], 4))

    f.write_bytes(build(b"short", 2))
    first = content_key(f)
    assert first == windows_key(audio1 + audio2)
    f.write_bytes(build(b"a much longer comment" * 50, 5))  # other page numbers, same audio
    assert content_key(f) == first


@pytest.mark.parametrize("ext", AUDIO_EXTS + (".txt",))
def test_unparsable_files_use_the_whole_file(tmp_path, ext):
    f = tmp_path / f"junk{ext}"
    data = b"not audio at all " * 1000
    f.write_bytes(data)  # bad magic everywhere; an untagged MP3 has no magic, so all of it is its payload anyway
    assert content_key(f) == windows_key(data)


def test_empty_file(tmp_path):
    f = tmp_path / "empty.flac"
    f.write_bytes(b"")
    assert content_key(f) == windows_key(b"")


def test_large_file_reads_only_the_windows(tmp_path):
    payload = np.random.default_rng(0).integers(0, 256, 4 * 1024 * 1024, dtype=np.uint8).tobytes()
    f = tmp_path / "big.mp3"
    f.write_bytes(payload)
    assert content_key(f) == windows_key(payload)


def test_missing_file_raises_oserror(tmp_path):
    with pytest.raises(OSError):
        content_key(tmp_path / "nope.aiff")
