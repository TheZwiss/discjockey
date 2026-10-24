"""A fingerprint of a file's audio bytes that survives renames, moves and tag edits (spec
library-and-sources §6.2).

The key is ``1:<payload length>:<sha256>``: the hash runs over three windows (start, middle, end) of the audio
payload, or over all of it when it is at most three windows long. The payload is found per format as a list of
byte ranges, so a payload split over several places (M4A's `mdat` atoms, Ogg's page bodies) hashes the same however
the tags around it grow. A file whose payload can't be found gets the same windows over the whole file. The leading
``1:`` is the algorithm's version, so a later change can re-key.
"""
from __future__ import annotations

import hashlib
import os
import struct
from pathlib import Path
from typing import BinaryIO

AUDIO_EXTS = (".aiff", ".aif", ".wav", ".flac", ".mp3", ".m4a", ".ogg", ".opus")
WINDOW = 256 * 1024
VERSION = "1"

Ranges = list[tuple[int, int]]  # (offset, length) in the file


class _Unparsable(Exception):
    """The payload can't be found: the key falls back to the whole file."""


def content_key(path: Path) -> str:
    """The content key of the file at `path`. Errors reading it (gone, permission) raise `OSError`."""
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        parse = _PARSERS.get(path.suffix.lower())
        ranges: Ranges | None = None
        if parse is not None:
            try:
                ranges = parse(f, size)
            except (_Unparsable, struct.error):
                ranges = None
        if ranges is None or sum(n for _, n in ranges) == 0:
            ranges = [(0, size)]
        return _key(f, ranges)


def _key(f: BinaryIO, ranges: Ranges) -> str:
    total = sum(n for _, n in ranges)
    h = hashlib.sha256()
    if total <= 3 * WINDOW:
        spans = [(0, total)]
    else:
        spans = [(0, WINDOW), ((total - WINDOW) // 2, WINDOW), (total - WINDOW, WINDOW)]
    for start, length in spans:
        for chunk in _read_span(f, ranges, start, length):
            h.update(chunk)
    return f"{VERSION}:{total}:{h.hexdigest()}"


def _read_span(f: BinaryIO, ranges: Ranges, start: int, length: int):
    """The bytes at payload offsets [start, start + length), read across the file ranges."""
    pos = 0  # payload offset where the current range begins
    end = start + length
    for offset, n in ranges:
        lo, hi = max(start, pos), min(end, pos + n)
        if lo < hi:
            f.seek(offset + lo - pos)
            want = hi - lo
            data = f.read(want)
            if len(data) != want:  # the file shrank while it was read
                raise OSError("the file changed while it was read")
            yield data
        pos += n
        if pos >= end:
            break


def _read(f: BinaryIO, offset: int, n: int) -> bytes:
    f.seek(offset)
    data = f.read(n)
    if len(data) != n:
        raise _Unparsable
    return data


def _check(ranges: Ranges, size: int) -> Ranges:
    for offset, n in ranges:
        if offset < 0 or n < 0 or offset + n > size:
            raise _Unparsable
    return ranges


# --- AIFF / WAV: one chunk of a chunked container ------------------------------------------------------------------

def _chunk(f: BinaryIO, size: int, *, start: int, want: bytes, fmt: str) -> tuple[int, int]:
    """(data offset, data length) of the first chunk named `want` after `start`; sizes in `fmt` (">I" or "<I")."""
    pos = start
    while pos + 8 <= size:
        head = _read(f, pos, 8)
        name, n = head[:4], struct.unpack(fmt, head[4:])[0]
        if name == want:
            if pos + 8 + n > size:
                raise _Unparsable
            return pos + 8, n
        pos += 8 + n + (n & 1)  # chunks are padded to an even length
    raise _Unparsable


def _aiff(f: BinaryIO, size: int) -> Ranges:
    head = _read(f, 0, 12)
    if head[:4] != b"FORM" or head[8:12] not in (b"AIFF", b"AIFC"):
        raise _Unparsable
    data, n = _chunk(f, size, start=12, want=b"SSND", fmt=">I")
    if n < 8:
        raise _Unparsable
    offset = struct.unpack(">I", _read(f, data, 4))[0]  # then the block size; the samples follow
    if 8 + offset > n:
        raise _Unparsable
    return _check([(data + 8 + offset, n - 8 - offset)], size)


def _wav(f: BinaryIO, size: int) -> Ranges:
    head = _read(f, 0, 12)
    if head[:4] != b"RIFF" or head[8:12] != b"WAVE":
        raise _Unparsable
    return _check([_chunk(f, size, start=12, want=b"data", fmt="<I")], size)


# --- FLAC / MP3: tags around one run of frames ----------------------------------------------------------------------

def _id3v2_end(f: BinaryIO, size: int, pos: int = 0) -> int:
    """The offset after any ID3v2 tags at `pos` (syncsafe sizes, the footer flag adds 10 bytes)."""
    while pos + 10 <= size:
        head = _read(f, pos, 10)
        if head[:3] != b"ID3" or any(b & 0x80 for b in head[6:10]):
            break
        n = (head[6] << 21) | (head[7] << 14) | (head[8] << 7) | head[9]
        pos += 10 + n + (10 if head[5] & 0x10 else 0)
    if pos > size:
        raise _Unparsable
    return pos


def _flac(f: BinaryIO, size: int) -> Ranges:
    pos = _id3v2_end(f, size)
    if _read(f, pos, 4) != b"fLaC":
        raise _Unparsable
    pos += 4
    while True:
        head = _read(f, pos, 4)
        pos += 4 + int.from_bytes(head[1:4], "big")
        if pos > size:
            raise _Unparsable
        if head[0] & 0x80:  # the last metadata block
            return [(pos, _trailer_start(f, pos, size) - pos)]


def _mp3(f: BinaryIO, size: int) -> Ranges:
    start = _id3v2_end(f, size)
    return [(start, _trailer_start(f, start, size) - start)]


def _trailer_start(f: BinaryIO, start: int, end: int) -> int:
    """Where the tags at the end of the frames begin: ID3v1 (with its 227-byte "TAG+" extension) and APEv2, in
    either order."""
    while True:
        if end - start >= 128 and _read(f, end - 128, 3) == b"TAG":
            end -= 128
            if end - start >= 227 and _read(f, end - 227, 4) == b"TAG+":
                end -= 227
            continue
        if end - start >= 32:
            footer = _read(f, end - 32, 32)
            if footer[:8] == b"APETAGEX":
                n, flags = struct.unpack("<I", footer[12:16])[0], struct.unpack("<I", footer[20:24])[0]
                n += 32 if flags & 0x80000000 else 0  # the size counts the items and footer, not the header
                if n < 32 or n > end - start:
                    raise _Unparsable
                end -= n
                continue
        return end


# --- M4A: every top-level mdat atom ---------------------------------------------------------------------------------

def _m4a(f: BinaryIO, size: int) -> Ranges:
    ranges: Ranges = []
    pos = 0
    while pos < size:
        head = _read(f, pos, 8)
        n, kind = struct.unpack(">I", head[:4])[0], head[4:]
        header = 8
        if n == 1:
            n = struct.unpack(">Q", _read(f, pos + 8, 8))[0]
            header = 16
        elif n == 0:
            n = size - pos
        if n < header or pos + n > size:
            raise _Unparsable
        if kind == b"mdat":
            ranges.append((pos + header, n - header))
        pos += n
    if not ranges:
        raise _Unparsable
    return ranges


# --- Ogg (Vorbis, Opus): page bodies after the header packets -------------------------------------------------------

def _ogg(f: BinaryIO, size: int) -> Ranges:
    """Page bodies of the first stream after its header packets; page headers are left out because a longer
    comment packet renumbers (and so re-checksums) every later page while the audio stays the same."""
    ranges: Ranges = []
    serial = None
    headers = None  # how many header packets the codec has
    packets = 0  # header packets completed so far
    first = b""  # the start of the first packet, to tell the codec
    pos = 0
    while pos < size:
        head = _read(f, pos, 27)
        if head[:4] != b"OggS":
            raise _Unparsable
        page_serial, nsegs = struct.unpack("<I", head[14:18])[0], head[26]
        lacing = _read(f, pos + 27, nsegs)
        body = pos + 27 + nsegs
        body_len = sum(lacing)
        if body + body_len > size:
            raise _Unparsable
        if serial is None:
            serial = page_serial
            first = _read(f, body, min(body_len, 8))
            if first.startswith(b"\x01vorbis"):
                headers = 3
            elif first.startswith(b"OpusHead"):
                headers = 2
            else:
                raise _Unparsable
        if page_serial == serial:
            if packets < headers:
                offset = 0
                for value in lacing:
                    offset += value
                    if value < 255:
                        packets += 1
                        if packets == headers:
                            break
                if packets == headers and offset < body_len:
                    ranges.append((body + offset, body_len - offset))
            elif body_len:
                ranges.append((body, body_len))
        pos = body + body_len
    if headers is None or packets < headers:
        raise _Unparsable
    return ranges


_PARSERS = {
    ".aiff": _aiff, ".aif": _aiff, ".wav": _wav, ".flac": _flac, ".mp3": _mp3, ".m4a": _m4a,
    ".ogg": _ogg, ".opus": _ogg,
}
