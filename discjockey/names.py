"""Pure file-name helpers."""
from __future__ import annotations

import re
import unicodedata
from pathlib import PurePosixPath

from .models import OWN_PREFIX

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


def id_tags(track_id: str) -> list[str]:
    """The tags a file name takes, in order, when the name without one is taken: a song's ID, short then whole
    (`[abc123]`, `[abc123XYZ]`); an own song's key `local:<n>` as `[local <n>]`, without the colon, which Finder
    shows as "/". None for "" (a file of no song)."""
    if not track_id:
        return []
    if track_id.startswith(OWN_PREFIX):
        return [f"[local {track_id[len(OWN_PREFIX):]}]"]
    return [f"[{track_id[:6]}]", f"[{track_id}]"]


def strip_id_suffix(name: str, track_id: str) -> str:
    stem, ext = split_name(name)
    for suffix in (f" {tag}" for tag in reversed(id_tags(track_id))):  # the whole ID first
        if stem.endswith(suffix):
            return stem[: -len(suffix)] + ext
    return name
