"""rekordbox's analysis files (ANLZ, `.DAT`, `.EXT`, `.2EX`), read (plan rekordbox stage A §1.6) and, for stage B's
repoint, one tag rewritten as bytes (`splice_ppth`, plan stage B §1.4; the file write is `write.py`'s).

A track's analysis lives in `share/PIONEER/USBANLZ/…/ANLZ0000.DAT` (its `AnalysisDataPath` under the library's
`share` folder) with `.EXT` beside it. Both are PMAI files, big-endian: `PMAI`, `u32 header_len`, `u32 file_len`
(the whole file), then tags back to back, each `fourcc`, `u32 header_len`, `u32 total_len` (header included) and
its own header fields. Read here:

- `PPTH` (`.DAT`, `.EXT`, `.2EX`): `u32 path_len` (bytes), then the audio file's path in UTF-16BE with a trailing NUL.
  rekordbox 7's own library files hold only `?/<file name>` there (checked on a copy 2026-11-08: every `PPTH` of a
  desktop library); an exported stick and older files hold the whole path. `ppth_after` keeps whichever form is there.
  `.3EX` is no PMAI file (a msgpack blob without a path): `read` answers None and the repoint leaves it alone.
- `PQTZ` (`.DAT`, the beat grid): `u32 0`, `u32 0x00080000`, `u32 beat_count`, then 8 bytes per beat
  (`u16 number`, `u16 tempo × 100`, `u32 time_ms`).
- `PWV3` (`.EXT`, the scrolling waveform): `u32 entry_bytes` (1), `u32 entries`, `u32 0x00960000`, then one byte per
  column at 150 columns per second: the height is `byte & 0x1F`, the top three bits its whiteness.

The layout follows Deep Symmetry's crate-digger analysis (`rekordbox_anlz.ksy`) and was checked on rekordbox 7
files 2026-11-07 (header 28 bytes; `PQTZ`'s second word is `0x00080000`). `Anlz` keeps the file's bytes and each
tag's span, so stage B can rewrite one tag (`splice_ppth`) and keep every other byte. An unknown tag is skipped by its
`total_len`. A file that isn't there, can't be read, or doesn't hold together (wrong magic, a length past the end) is
"no analysis": `read` answers None, never raises.
"""
from __future__ import annotations

import hashlib
import struct
import unicodedata
from dataclasses import dataclass
from pathlib import Path

import numpy as np

MAGIC = b"PMAI"
HEAD = struct.Struct(">4sII")  # fourcc (or magic), header_len, total_len (file_len for the file header)
U32 = struct.Struct(">I")
COLUMNS_PER_SECOND = 150
HEIGHT_MASK = 0x1F


@dataclass(frozen=True)
class Tag:
    fourcc: str
    start: int       # offset of the tag's fourcc in the file
    header_len: int
    total_len: int

    @property
    def body_start(self) -> int:
        return self.start + self.header_len

    @property
    def end(self) -> int:
        return self.start + self.total_len


@dataclass(frozen=True)
class Anlz:
    header_len: int
    tags: tuple[Tag, ...]
    data: bytes

    def tag(self, fourcc: str) -> Tag | None:
        """The first tag of this kind, or None."""
        return next((t for t in self.tags if t.fourcc == fourcc), None)

    def field(self, tag: Tag, index: int) -> int:
        """The `index`-th `u32` of `tag`'s own header fields (after its fourcc and two lengths)."""
        return U32.unpack_from(self.data, tag.start + HEAD.size + 4 * index)[0]


class Malformed(ValueError):
    """The bytes are not a whole PMAI file."""


def parse(data: bytes) -> Anlz:
    """`data` as a PMAI file. Raises `Malformed`."""
    if len(data) < HEAD.size:
        raise Malformed("shorter than a header")
    magic, header_len, file_len = HEAD.unpack_from(data, 0)
    if magic != MAGIC:
        raise Malformed("not a PMAI file")
    if file_len != len(data) or not HEAD.size <= header_len <= file_len:
        raise Malformed("lengths don't fit the file")
    tags: list[Tag] = []
    pos = header_len
    while pos < file_len:
        if pos + HEAD.size > file_len:
            raise Malformed("a tag header runs past the end")
        fourcc, tag_header, total = HEAD.unpack_from(data, pos)
        if not HEAD.size <= tag_header <= total or pos + total > file_len:
            raise Malformed("a tag's lengths run past the end")
        tags.append(Tag(fourcc.decode("latin-1"), pos, tag_header, total))
        pos += total
    return Anlz(header_len, tuple(tags), data)


def read(path: Path) -> Anlz | None:
    """The analysis file at `path`, or None when it isn't there, can't be read or is malformed."""
    try:
        return parse(Path(path).read_bytes())
    except (OSError, Malformed):
        return None


def ppth(a: Anlz) -> str | None:
    """The audio file's path the analysis was made for, or None (no `PPTH`, or one that doesn't hold together)."""
    tag = a.tag("PPTH")
    if tag is None or tag.header_len < HEAD.size + 4:
        return None
    length = a.field(tag, 0)
    if length % 2 or tag.body_start + length > tag.end:
        return None
    try:
        text = a.data[tag.body_start:tag.body_start + length].decode("utf-16-be")
    except UnicodeDecodeError:
        return None
    return text[:-1] if text.endswith("\0") else text


def beat_count(a: Anlz) -> int:
    """How many beats the grid (`PQTZ`) holds; 0 without a grid, or with one that doesn't hold together."""
    tag = a.tag("PQTZ")
    if tag is None or tag.header_len < HEAD.size + 12:
        return 0
    count = a.field(tag, 2)
    return count if tag.body_start + 8 * count <= tag.end else 0


def pwv3_heights(a: Anlz) -> np.ndarray | None:
    """The scrolling waveform's heights (`PWV3`, 0–31, 150 per second) as uint8, or None without a usable one."""
    tag = a.tag("PWV3")
    if tag is None or tag.header_len < HEAD.size + 12:
        return None
    entry_bytes, entries = a.field(tag, 0), a.field(tag, 1)
    if entry_bytes != 1 or tag.body_start + entries > tag.end:
        return None
    raw = np.frombuffer(a.data, dtype=np.uint8, count=entries, offset=tag.body_start)
    return raw & HEIGHT_MASK


# --- stage B: the repoint's splice ---

NAME_ONLY = "?/"  # the prefix of rekordbox 7's own PPTH: "?/<file name>"


def _fold(text: str) -> str:
    return unicodedata.normalize("NFC", text).casefold()


def ppth_after(current: str | None, old_path: str, new_path: str) -> str | None:
    """What `PPTH` should say once rekordbox's track moves from `old_path` to `new_path` (both whole paths), keeping the
    form that is there: `?/<new name>` where it held `?/<old name>`, the whole new path where it held the whole old
    path (NFC and case-folded compare). None when it names something else (or nothing): the file is left alone."""
    if current is None:
        return None
    old_name, new_name = old_path.rsplit("/", 1)[-1], new_path.rsplit("/", 1)[-1]
    if _fold(current) == _fold(NAME_ONLY + old_name):
        return NAME_ONLY + unicodedata.normalize("NFC", new_name)
    if _fold(current) == _fold(old_path):
        return unicodedata.normalize("NFC", new_path)
    return None


def splice_ppth(a: Anlz, new_path: str) -> bytes:
    """`a`'s bytes with the first `PPTH` tag's path replaced by `new_path` (UTF-16BE, trailing NUL): the tag's
    `path_len` and `total_len` and the file header's `file_len` follow, every other byte stays where it was in order.
    Pure. Raises `Malformed` when `a` has no `PPTH` that holds together."""
    tag = a.tag("PPTH")
    if tag is None or ppth(a) is None:
        raise Malformed("no PPTH to replace")
    body = (new_path + "\0").encode("utf-16-be")
    old_len = a.field(tag, 0)
    rest_of_body = a.data[tag.body_start + old_len:tag.end]  # bytes after the path inside the tag (none in practice)
    header = bytearray(a.data[tag.start:tag.body_start])
    total = tag.header_len + len(body) + len(rest_of_body)
    struct.pack_into(">I", header, 8, total)
    struct.pack_into(">I", header, HEAD.size, len(body))
    out = bytearray(a.data[:tag.start]) + header + body + rest_of_body + a.data[tag.end:]
    struct.pack_into(">I", out, 8, len(out))
    return bytes(out)


def md5_size(path: Path) -> tuple[str, int]:
    """The MD5 (hex) and size of a file: what rekordbox keeps in `contentFile.Hash` and `Size` for an analysis file
    (checked on a copy 2026-11-08)."""
    data = Path(path).read_bytes()
    return hashlib.md5(data).hexdigest(), len(data)  # noqa: S324 (rekordbox's own checksum, not security)
