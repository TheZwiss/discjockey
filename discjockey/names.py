"""Pure file-name helpers."""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

MAX_STEM_BYTES = 200
_FORBIDDEN = set('/:\\?*"<>|')


def fold(s: str) -> str:
    """Comparison key for names: NFC (macOS may hand back NFD) and casefold (the disk ignores case)."""
    return unicodedata.normalize("NFC", s).casefold()


def _truncate_utf8(s: str, limit: int) -> str:
    return s.encode("utf-8")[:limit].decode("utf-8", "ignore")


def sanitize_stem(name: str) -> str:
    s = unicodedata.normalize("NFC", name)
    s = "".join("-" if c in _FORBIDDEN or ord(c) < 32 or ord(c) == 127 else c for c in s)
    s = re.sub(r"\s+", " ", s).strip()
    s = s.lstrip(". ")
    s = _truncate_utf8(s, MAX_STEM_BYTES).rstrip(". ")
    return s or "Unknown"


def expected_stem(artist: str, title: str) -> str:
    """`<first artist> - <title>`, the name a track's file gets (without collision suffix)."""
    return sanitize_stem(f"{artist.strip() or 'Unknown Artist'} - {title.strip() or 'Unknown Title'}")


def split_name(name: str) -> tuple[str, str]:
    p = PurePosixPath(name)
    return p.stem, p.suffix


def strip_id_suffix(name: str, track_id: str) -> str:
    stem, ext = split_name(name)
    for suffix in (f" [{track_id}]", f" [{track_id[:6]}]"):
        if stem.endswith(suffix):
            return stem[: -len(suffix)] + ext
    return name
