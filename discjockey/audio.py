"""ffmpeg conversion to 16-bit/44.1 kHz AIFF, cover download and ID3v2.3 tagging."""
from __future__ import annotations

import subprocess
import tempfile
import urllib.request
from pathlib import Path
from typing import Callable

from mutagen.aiff import AIFF
from mutagen.id3 import APIC, COMM, TALB, TIT2, TPE1, TPUB, TSRC

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
