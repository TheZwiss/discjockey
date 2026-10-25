"""Title/artist normalization and the candidate matching rules."""
from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

from .models import Candidate, SourceTrack

DURATION_TOLERANCE_MS = 3000
QOBUZ_MIN_RATIO = 0.85
FALLBACK_MIN_RATIO = 0.70
FALLBACK_JUNK = frozenset({
    "official video", "official audio", "official music video", "lyrics", "lyric video",
    "visualizer", "audio", "hd", "hq", "free download", "out now",
})

_JUNK = re.compile(
    r"original mix|extended mix|radio edit"
    r"|(?:\d{4} )?remaster(?:ed)?\b.*"
    r"|(?:feat\.?|ft\.?|featuring|with)\s.*"
)
_BRACKET = re.compile(r"[\(\[]([^\(\)\[\]]*)[\)\]]")
_DASH = re.compile(r"\s[-–—]\s")
# unbracketed "feat. X" up to the next " - ", bracket or the end (keeps "(Y Remix)" after it)
_FEAT = re.compile(r"\b(?:feat|ft|featuring)\b\.?[^()\[\]]*?(?=\s[-–—]\s|[\(\[]|$)")


def _is_junk(text: str, extra) -> bool:
    t = text.strip()
    return bool(_JUNK.fullmatch(t)) or t in extra


def normalize(text: str, extra=frozenset()) -> str:
    s = unicodedata.normalize("NFKC", text).lower()
    s = _FEAT.sub(" ", s)
    s = _BRACKET.sub(lambda m: " " if _is_junk(m.group(1), extra) else f" {m.group(1)} ", s)
    parts = _DASH.split(s)
    s = " ".join([parts[0]] + [p for p in parts[1:] if not _is_junk(p, extra)])
    s = re.sub(r"[^\w\s]|_", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def normalize_artist(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"\bx\b", " ", normalize(text))).strip()


def _contains(needle: str, haystack: str) -> bool:
    """Whole-word containment: 'ace' is in 'ace ventura' but not in 'grace jones'."""
    return bool(needle) and f" {needle} " in f" {haystack} "


def fallback_title(title: str, first_artist: str) -> str:
    """YouTube-style 'Artist - Title (Official Video)' -> normalized 'title'."""
    parts = _DASH.split(unicodedata.normalize("NFKC", title), maxsplit=1)
    artist = normalize_artist(first_artist)
    if len(parts) == 2 and _contains(artist, normalize_artist(parts[0])):
        title = parts[1]
    return normalize(title, FALLBACK_JUNK)


def duration_ok(track: SourceTrack, seconds: float | None) -> bool:
    return seconds is not None and abs(seconds * 1000 - track.duration_ms) <= DURATION_TOLERANCE_MS


def isrc_match(track: SourceTrack, cand: Candidate, rejected: set[str]) -> bool:
    return (
        bool(track.isrc and cand.isrc)
        and cand.isrc.upper() == track.isrc.upper()
        and duration_ok(track, cand.duration_s)
        and cand.key not in rejected
    )


def qobuz_match(track: SourceTrack, cand: Candidate, rejected: set[str]) -> bool:
    if cand.key in rejected or not duration_ok(track, cand.duration_s):
        return False
    if SequenceMatcher(None, normalize(track.title), normalize(cand.title)).ratio() < QOBUZ_MIN_RATIO:
        return False
    artist = normalize_artist(track.first_artist)
    return _contains(artist, normalize_artist(cand.artist))


def fallback_match(track: SourceTrack, cand: Candidate, rejected: set[str]) -> bool:
    if cand.key in rejected or not duration_ok(track, cand.duration_s):
        return False
    want = normalize(track.title)
    got = fallback_title(cand.title, track.first_artist)
    ratio = SequenceMatcher(None, want, got).ratio()
    contained = bool(want) and set(want.split()) <= set(got.split())
    if ratio < FALLBACK_MIN_RATIO and not contained:
        return False
    artist = normalize_artist(track.first_artist)
    return _contains(artist, normalize_artist(f"{cand.artist} {cand.title}"))


def rank(track: SourceTrack, cands: list[Candidate]) -> list[Candidate]:
    return sorted(cands, key=lambda c: abs((c.duration_s or 0) * 1000 - track.duration_ms))
