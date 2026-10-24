"""Other versions of a track for the hub's "Wrong song?" dialog: search with match scores, links the user pastes,
and short previews. Nothing here downloads a whole track or changes state.json."""
from __future__ import annotations

import json
import os
import re
import shutil
import threading
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path

from . import audio
from .library import Paths
from .matching import (
    _contains, duration_ok, fallback_match, fallback_title, isrc_match, normalize, normalize_artist, qobuz_match,
)
from .models import Candidate, Protected, SourceTrack

LENGTH_SCALE_MS = 30_000  # a version this much longer or shorter than Spotify's gets no points for its length
PREVIEW_S = 30
PREVIEW_START_S = 60  # previews start a minute in (after the intro), or at the start of short tracks
SOURCE_RANK = {"qobuz": 0, "youtube_music": 1, "soundcloud": 2, "youtube": 3}
FALLBACK = ("youtube_music", "soundcloud", "youtube")
PROTECTED_FILE = "protected_sources.json"  # in .cache/: versions found to be DRM-protected, never offered again
LINK_HELP = "Discjockey can use a link to a Qobuz track, a YouTube or YouTube Music video, or a SoundCloud track."

_QOBUZ = re.compile(r"https?://(?:open|play|www)\.qobuz\.com/(?:[a-z]{2}-[a-z]{2}/)?track/(\d+)(?:[/?#].*)?")
_YTM = re.compile(r"https?://music\.youtube\.com/watch\?(?:.*&)?v=([\w-]{11})(?:[&#].*)?")
_YT = re.compile(r"https?://(?:www\.|m\.)?youtube\.com/watch\?(?:.*&)?v=([\w-]{11})(?:[&#].*)?")
_YT_SHORT = re.compile(r"https?://youtu\.be/([\w-]{11})(?:[/?#].*)?")
_SC = re.compile(r"(https?://(?:www\.|m\.)?soundcloud\.com/[^/?#\s]+/(?!sets/)[^/?#\s]+)(?:[?#].*)?")


@dataclass(frozen=True)
class Scored:
    candidate: Candidate
    score: int  # 0-100: how well title, artist and length fit the Spotify track
    matches: bool  # the engine's own matching rules would take it
    length_ok: bool  # within 3 s of Spotify's length (Discjockey only uses those)
    current: bool  # the version in the library now
    rejected: bool  # marked as wrong before (rejected_sources)


def score(track: SourceTrack, cand: Candidate) -> int:
    if cand.source == "qobuz" and isrc_match(track, cand, set()):
        return 100
    qobuz = cand.source == "qobuz"
    got = normalize(cand.title) if qobuz else fallback_title(cand.title, track.first_artist)
    title = SequenceMatcher(None, normalize(track.title), got).ratio()
    artist = 1.0 if _contains(normalize_artist(track.first_artist),
                              normalize_artist(cand.artist if qobuz else f"{cand.artist} {cand.title}")) else 0.0
    length = 0.0
    if cand.duration_s is not None:
        length = max(0.0, 1 - abs(cand.duration_s * 1000 - track.duration_ms) / LENGTH_SCALE_MS)
    return round(100 * (0.5 * title + 0.25 * artist + 0.25 * length))


def current_key(entry: dict) -> str | None:
    """`<source>:<id>` of the version in the library now (None for a bought file or no file)."""
    if entry.get("status") != "missing" and entry.get("source") and entry.get("source_id"):
        return f"{entry['source']}:{entry['source_id']}"
    return None


def protected(paths: Paths) -> set[str]:
    try:
        return set(json.loads((paths.cache / PROTECTED_FILE).read_text(encoding="utf-8")))
    except (OSError, ValueError, TypeError):
        return set()


def mark_protected(paths: Paths, key: str) -> None:
    keys = protected(paths) | {key}
    paths.cache.mkdir(parents=True, exist_ok=True)
    tmp = paths.cache / f".{PROTECTED_FILE}.tmp"
    tmp.write_text(json.dumps(sorted(keys)), encoding="utf-8")
    os.replace(tmp, paths.cache / PROTECTED_FILE)


def search(track: SourceTrack, entry: dict, qobuz, fallback,
           skip: set[str] | frozenset = frozenset()) -> tuple[list[Scored], list[str]]:
    """Qobuz (by ISRC and by name) and the fallback sources, side by side. Returns the scored versions, the one in
    the library first and the others best first, and notes about searches that failed. `skip`: versions that can
    never be used (DRM-protected), left out."""
    found: dict[str, Candidate] = {}
    notes: list[str] = []
    qobuz_found: list[Candidate] = []
    qobuz_notes: list[str] = []

    def search_qobuz() -> None:
        for query in ([track.isrc] if track.isrc else []) + [f"{track.first_artist} {track.title}"]:
            try:
                qobuz_found.extend(qobuz.search(query, limit=10))
            except Exception as e:
                qobuz_notes.append(f"Qobuz search failed: {str(e)[:200]}")
                break

    worker = None
    if qobuz is None:
        notes.append("Qobuz is not set up, so only YouTube Music, SoundCloud and YouTube were searched.")
    else:  # Qobuz in its own thread (its session is used by that thread only) while the fallback searches run
        worker = threading.Thread(target=search_qobuz, name="search-qobuz", daemon=True)
        worker.start()
    fallback_found: list[Candidate] = []
    try:
        if fallback is not None:
            fallback_found, errors = fallback.search(track)
            notes += errors
    finally:
        if worker is not None:
            worker.join()
    notes[:0] = qobuz_notes
    for c in qobuz_found + fallback_found:
        if c.key not in skip:
            found.setdefault(c.key, c)
    current = current_key(entry)
    rejected = set(entry.get("rejected_sources") or [])
    scored = [Scored(c, score(track, c),
                     (qobuz_match if c.source == "qobuz" else fallback_match)(track, c, set()) or
                     isrc_match(track, c, set()),
                     duration_ok(track, c.duration_s), c.key == current, c.key in rejected)
              for c in found.values()]
    scored.sort(key=lambda s: (not s.current, -s.score, SOURCE_RANK[s.candidate.source]))
    return scored, notes


def parse_link(text: str) -> tuple[str, str]:
    """(source, Qobuz track id or a clean link). ValueError with a plain message for anything else."""
    url = text.strip()
    if m := _QOBUZ.fullmatch(url):
        return "qobuz", m.group(1)
    if m := _YTM.fullmatch(url):
        return "youtube_music", f"https://music.youtube.com/watch?v={m.group(1)}"
    if m := (_YT.fullmatch(url) or _YT_SHORT.fullmatch(url)):
        return "youtube", f"https://www.youtube.com/watch?v={m.group(1)}"
    if m := _SC.fullmatch(url):
        return "soundcloud", m.group(1)
    raise ValueError(LINK_HELP)


def link_candidate(text: str, qobuz, fallback) -> Candidate:
    """The version behind a pasted link, with its title and length (asked from Qobuz or yt-dlp, no download)."""
    source, ref = parse_link(text)
    if source == "qobuz":
        if qobuz is None:
            raise ValueError("Qobuz is not set up, so Discjockey can't use Qobuz links yet.")
        return qobuz.track(ref)
    cand = fallback.lookup(source, ref)
    if cand is None:
        raise ValueError("Discjockey found no track at that link.")
    return Candidate(source, cand.id, cand.title, cand.artist, cand.duration_s, url=ref)


def _safe(text: str) -> str:
    return re.sub(r"[^\w-]", "_", text)[:80]


def preview(paths: Paths, cand: Candidate, fallback) -> Path:
    """30 seconds of a YouTube Music, SoundCloud or YouTube version as AIFF (WebKit plays it) in
    .cache/previews/, reused when it exists. Qobuz versions get no preview: fetching part of a Qobuz stream is the
    same request as a download, outside the pacing."""
    if cand.source not in FALLBACK:
        raise ValueError("Qobuz versions have no preview.")
    folder = paths.cache / "previews"
    folder.mkdir(parents=True, exist_ok=True)
    out = folder / f"{cand.source}_{_safe(cand.id)}.aiff"
    if out.exists():
        return out
    start = PREVIEW_START_S if (cand.duration_s or 0) >= PREVIEW_START_S + PREVIEW_S + 30 else 0
    work = folder / f".work-{cand.source}_{_safe(cand.id)}"
    work.mkdir(exist_ok=True)
    try:
        try:
            part = fallback.download(cand, work, section=(start, start + PREVIEW_S))
        except Protected:
            mark_protected(paths, cand.key)
            raise
        tmp = work / "preview.aiff"
        audio.convert_to_aiff(part, tmp)
        os.replace(tmp, out)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    return out
