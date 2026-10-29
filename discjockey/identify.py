"""Pure: whether a playlist song and a song of the user's own (a file the import read) are the same song (spec
library-and-sources §10.3, plan library stage 4 D3/D5), and an own song's name from its tags or file name. No I/O.

The planner calls `compare` on every plan (D2), so a playlist added months after the import still finds the files.
"""
from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import PurePosixPath
from typing import Literal

from .matching import _DASH, normalize, normalize_artist

_COLLAB = re.compile(r"[,&;]|\s+x\s+", re.IGNORECASE)  # how a tag joins several artists: "A, B", "A & B", "A; B", "A x B"

Match = Literal["certain", "plausible"]

SAME_LENGTH_MS = 3000  # how far apart two lengths may be for one song: an ISRC link and a name link (spec §9.2)
CERTAIN_MS = 2000  # same artist and title: linked when the lengths are this close (§10.3)
PLAUSIBLE_MS = 10000  # same artist and title, lengths off by more than CERTAIN_MS up to this: asked (D3 b)


def compare(artist: str, title: str, duration_ms: int | None, isrc: str | None,
            own: Mapping) -> tuple[Match, str] | None:
    """(match, why) for a playlist song (`artist` its first artist) against an own song's entry (`artist`, `title`,
    `duration_ms`, `isrc`), else None. `why`: "isrc" | "name" (certain), "artist" | "length" | "no_length"
    (plausible).

    - Both ISRCs known: two different ones are two recordings (None, D5). The same one is certain when the lengths
      are within SAME_LENGTH_MS, None when they are further apart; with a length unknown the names decide (below:
      To-do's words for "no_length" say the artist and title are the same, so the same ISRC alone isn't asked).
    - Names (normalised as planner._song_name does: the artist and the title without "(Original Mix)", "feat. X"
      and the like; the own song's tag may name several artists, "A & B", and its first one alone only
      makes a plausible match, see below): the same artist and title within CERTAIN_MS is certain ("name"); off by up to PLAUSIBLE_MS is
      plausible ("length"). The same title with a different or missing artist within CERTAIN_MS is plausible
      ("artist", D3 a); so is a match on the tag's first artist only (the full artists differ: "Earth" against
      "Earth, Wind & Fire"), whatever the length, if it is unknown or within CERTAIN_MS.
    - A length unknown on either side (None or 0) is at most plausible: the same artist and title ("no_length"); a
      title alone never, it would match every "Intro"."""
    track_ms, own_ms = duration_ms or None, own.get("duration_ms") or None
    delta = None if track_ms is None or own_ms is None else abs(own_ms - track_ms)
    own_isrc = own.get("isrc")
    if isrc and own_isrc:
        if isrc.upper() != own_isrc.upper():
            return None
        if delta is not None:
            return ("certain", "isrc") if delta <= SAME_LENGTH_MS else None
    name = normalize(title or "")
    if not name or name != normalize(own.get("title") or ""):
        return None
    ours, theirs = normalize_artist(artist or ""), normalize_artist(own.get("artist") or "")
    if ours and ours == theirs:
        if delta is None:
            return "plausible", "no_length"
        if delta <= CERTAIN_MS:
            return "certain", "name"
        return ("plausible", "length") if delta <= PLAUSIBLE_MS else None
    if ours and ours == normalize_artist(_first_artist(own.get("artist") or "")):
        # Only the tag's first artist matches ("Earth, Wind & Fire" vs "Earth"): never certain, the user is asked
        return ("plausible", "artist") if delta is None or delta <= CERTAIN_MS else None
    if delta is not None and delta <= CERTAIN_MS:
        return "plausible", "artist"
    return None


def _first_artist(tag: str) -> str:
    """The first artist of a tag that names several ("A & B", "A, B", "A x B", "A; B" -> "A")."""
    return _COLLAB.split(tag, maxsplit=1)[0].strip()


def own_name(tags: Mapping[str, str | None], file_name: str) -> tuple[str, str]:
    """(artist, title) of an own song: the tags when they give a title (the artist tag, or "" without one); else a
    file name "Artist - Title" (split on the first spaced dash); else the file name without its extension is the
    title and the artist is ""."""
    title = (tags.get("title") or "").strip()
    if title:
        return (tags.get("artist") or "").strip(), title
    stem = PurePosixPath(file_name).stem.strip()
    parts = _DASH.split(stem, maxsplit=1)
    if len(parts) == 2 and parts[0].strip() and parts[1].strip():
        return parts[0].strip(), parts[1].strip()
    return "", stem
