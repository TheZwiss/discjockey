"""ffmpeg conversion to 16-bit/44.1 kHz AIFF (`convert_to_aiff` for downloads, `render_aiff` for a sample-exact,
shifted render of any file), cover download, ID3v2.3 tagging, and `file_facts` (what a file is and what its tags say,
for rekordbox's eligibility rules)."""
from __future__ import annotations

import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import mutagen
from mutagen.aiff import AIFF
from mutagen.id3 import APIC, COMM, ID3, TALB, TIT2, TPE1, TPUB, TSRC
from mutagen.mp4 import MP4

from . import quality

# libsoxr is not available in this ffmpeg build, so use swr with a long filter and triangular dither
RESAMPLE = "aresample=44100:resampler=swr:filter_size=64:dither_method=triangular"


class ConversionError(Exception):
    pass


def convert_to_aiff(src: Path, dst: Path, duration_s: float | None = None,
                    progress: Callable[[float, float | None], None] | None = None) -> None:
    """progress(done_seconds, total_seconds) is called while ffmpeg works; if it raises (e.g. the user
    pressed Stop), ffmpeg is killed and the exception propagates."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-nostats", "-progress", "pipe:1", "-y", "-i", str(src),
           "-map", "0:a:0", "-map_metadata", "-1", "-af", RESAMPLE, "-sample_fmt", "s16", "-c:a", "pcm_s16be",
           "-f", "aiff", str(dst)]
    with tempfile.TemporaryFile() as err:  # a file, not a pipe: a full stderr pipe could block ffmpeg
        # own session: a Ctrl-C in the terminal goes to Discjockey, which decides when to stop ffmpeg
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=err, text=True, start_new_session=True)
        try:
            for line in proc.stdout:
                key, _, value = line.strip().partition("=")
                if key == "out_time_us" and value.isdigit() and progress:
                    progress(int(value) / 1_000_000, duration_s)
            proc.wait()
        except BaseException:
            proc.kill()
            proc.wait()
            raise
        finally:
            proc.stdout.close()
        if proc.returncode != 0:
            err.seek(0)
            raise ConversionError(err.read().decode(errors="replace").strip()[-500:] or "ffmpeg failed")


def render_aiff(src: Path, dst: Path, shift_samples: int) -> None:
    """`src` (any format) as a 16-bit/44.1 kHz AIFF at `dst`, shifted by `shift_samples` (44.1 kHz samples; positive
    trims that many at the start, negative puts that much silence in front), in one ffmpeg run; no tags (callers tag).
    An input that is 16-bit/44.1 kHz PCM already keeps its samples exactly (no resampling, no dither); any other is
    resampled with RESAMPLE first, so the shift counts output samples (design rekordbox-repoint §3.1). Raises
    ConversionError."""
    try:
        info = quality.probe(src)
    except RuntimeError as err:
        raise ConversionError(str(err)) from None
    filters = []
    exact = info.codec.startswith("pcm_s16") and info.bits == 16 and info.sample_rate == 44100
    if not exact:
        filters.append(RESAMPLE)
    if shift_samples > 0:
        filters.append(f"atrim=start_sample={shift_samples},asetpts=PTS-STARTPTS")
    elif shift_samples < 0:
        filters.append(f"adelay=delays={-shift_samples}S:all=1")
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-map_metadata", "-1"]
    if filters:
        cmd += ["-af", ",".join(filters)]
    if not exact:
        cmd += ["-sample_fmt", "s16"]
    cmd += ["-c:a", "pcm_s16be", "-f", "aiff", str(dst)]
    r = subprocess.run(cmd, capture_output=True, start_new_session=True)
    if r.returncode != 0:
        raise ConversionError(r.stderr.decode(errors="replace").strip()[-500:] or "ffmpeg failed")


def fetch_cover(url: str | None) -> bytes | None:
    if not url:
        return None
    try:
        with urllib.request.urlopen(url, timeout=20) as r:
            data = r.read()
    except OSError:
        return None
    return data if data[:3] == b"\xff\xd8\xff" else None


def write_tags(path: Path, *, title: str, artists: tuple[str, ...], album: str, isrc: str | None,
               label: str | None, cover: bytes | None, comment: str) -> None:
    f = AIFF(str(path))
    if f.tags is None:
        f.add_tags()
    t = f.tags
    t.add(TIT2(encoding=1, text=title))
    t.add(TPE1(encoding=1, text=", ".join(artists)))
    t.add(TALB(encoding=1, text=album))
    if isrc:
        t.add(TSRC(encoding=1, text=isrc))
    if label:
        t.add(TPUB(encoding=1, text=label))
    if cover:
        t.add(APIC(encoding=1, mime="image/jpeg", type=3, desc="Cover", data=cover))
    t.add(COMM(encoding=1, lang="eng", desc="", text=comment))
    f.save(v2_version=3)


def copy_tags(src: Path, dst: Path) -> None:
    """Every ID3 frame of one AIFF onto another (title, artists, cover, comment ...), saved as ID3v2.3."""
    tags = AIFF(str(src)).tags
    if not tags:
        return
    f = AIFF(str(dst))
    if f.tags is None:
        f.add_tags()
    for frame in tags.values():
        f.tags.add(frame)
    f.save(v2_version=3)


TEXT_FIELDS = ("title", "artist", "album", "label", "isrc", "comment")  # the text columns rekordbox keeps (design §5.11)


@dataclass(frozen=True)
class FileFacts:
    """What a file is and says: `ext` (lower case, with the dot), the stream's `codec`, `sample_rate`, `bits`
    (None for a lossy codec), the text `tags` (every one of TEXT_FIELDS, '' when missing or empty) and whether it
    carries a cover."""
    ext: str
    codec: str
    sample_rate: int
    bits: int | None
    tags: dict[str, str]
    has_cover: bool


def _first(values) -> str:
    return next((str(v).strip() for v in (values or []) if str(v).strip()), "")


def _label_and_comment(path: Path) -> tuple[str, str]:
    """The label and the comment of any audio file ('' for a missing one). A tag mutagen can't read is missing."""
    try:
        f = mutagen.File(path)
        tags = getattr(f, "tags", None)
        if tags is None:
            return "", ""
        if isinstance(tags, ID3):
            comment = next((_first(frame.text) for frame in tags.getall("COMM") if _first(frame.text)), "")
            return _first(tags["TPUB"].text) if "TPUB" in tags else "", comment
        if isinstance(f, MP4):
            label = tags.get("----:com.apple.iTunes:LABEL") or []
            return (_first(v.decode("utf-8", "replace") if isinstance(v, bytes) else v for v in label),
                    _first(tags.get("\xa9cmt")))
        return (_first(tags.get("label")) or _first(tags.get("organization")),
                _first(tags.get("comment")) or _first(tags.get("description")))
    except (mutagen.MutagenError, KeyError, ValueError, TypeError, AttributeError):
        return "", ""


def _has_cover(path: Path) -> bool:
    try:
        f = mutagen.File(path)
        tags = getattr(f, "tags", None)
        if f is None:
            return False
        if isinstance(tags, ID3):
            return bool(tags.getall("APIC"))
        if isinstance(f, MP4):
            return bool((tags or {}).get("covr"))
        return bool(getattr(f, "pictures", None)) or bool(tags and tags.get("metadata_block_picture"))
    except (mutagen.MutagenError, KeyError, ValueError, TypeError, AttributeError):
        return False


def file_facts(path: Path) -> FileFacts:
    """The facts of the audio file at `path`: ffprobe's codec, rate and bit depth (`quality.probe`), the title,
    artist, album, ISRC the import reads (`importer.read_tags`) plus label and comment, and whether a cover is
    there. Raises RuntimeError when ffprobe finds no audio (also for a file that isn't there), OSError when mutagen
    can't open it."""
    from .importer import read_tags  # lazy: the importer pulls in the whole library
    path = Path(path)
    info = quality.probe(path)
    read = read_tags(path)
    label, comment = _label_and_comment(path)
    tags = {"title": read["title"] or "", "artist": read["artist"] or "", "album": read["album"] or "",
            "label": label, "isrc": read["isrc"] or "", "comment": comment}
    return FileFacts(path.suffix.lower(), info.codec, info.sample_rate, info.bits, tags, _has_cover(path))
