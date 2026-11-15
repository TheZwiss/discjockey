"""Typed ids (issue 39, design §3): what a command line prints and accepts for a thing, with its kind in it, so an id
never means two things (`aiff:3` and `moves:3` are different batches). Pure: nothing here looks anything up. A path, a
playlist's name or a link is turned into an id by `HubApi.resolve`; `parse` only reads the typed forms and tells a
path from an id.

| kind | printed (`fmt`) | accepted by `parse` besides that |
|---|---|---|
| `track` | the song key as it is: a bare Spotify id, `qobuz:…`, `soundcloud:…`, `youtube_music:…`, `local:<n>` | `-` |
| `file` | `file:<n>` | |
| `aiff`, `moves` | `aiff:<n>`, `moves:<n>` (a bare number is refused) | |
| `job` | `job:<8 hex>` | `current` |
| `report` | `report:<YYYY-MM-DD_HHMMSS>` | the bare stamp, `last` |
| `plan` | `plan:<12 hex>` | |
| `folder` | `folder:<path>` | a bare path |
| `playlist` | `playlist:<folder>` | a bare folder name |
| `collection` | `all`, `unlisted`, `playlist:<folder>`, `folder:<path>` | |

A bare path where a track or a file is meant is `Ident("path", text)` for `resolve` to settle."""
from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass

from ..models import SERVICE_NAMES

KINDS = ("track", "file", "aiff", "moves", "job", "report", "plan", "folder", "playlist", "collection")
BATCH_KINDS = ("aiff", "moves")
SERVICE_PREFIXES = tuple(f"{service}:" for service in SERVICE_NAMES if service != "spotify")  # a Spotify id is bare

NUMBER = re.compile(r"\d+")
SPOTIFY_ID = re.compile(r"[A-Za-z0-9]{22}")
LOCAL_KEY = re.compile(r"local:\d+")
JOB_ID = re.compile(r"[0-9a-f]{8}")
PLAN_ID = re.compile(r"[0-9a-f]{12}")
REPORT_ID = re.compile(r"\d{4}-\d{2}-\d{2}_\d{6}")
COLLECTION_WORDS = ("all", "unlisted")


class BadId(Exception):
    """An id that can't be used: `reason` is `unknown_id` (nothing it could name) or `bad_id_kind` (an id of another
    kind than the command takes); both are `bad_args`."""

    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason
        self.message = message


@dataclass(frozen=True)
class Ident:
    """`kind` is one of `KINDS`, or `path` (text that names a file or folder, for `HubApi.resolve`). `value`: an int
    for `file`, `aiff` and `moves`; the song key, hex id, stamp, path, folder name or collection key for the rest."""
    kind: str
    value: int | str


def fmt(kind: str, value: int | str) -> str:
    """The printed id of `value`: `aiff:12`, `folder:/Music/Crate`, a song key as it is."""
    if kind not in KINDS:
        raise ValueError(f"no such id kind {kind!r}")
    if kind in ("track", "collection"):
        return str(value)
    return f"{kind}:{value}"


def parse(text: str, kinds: Iterable[str]) -> Ident:
    """The id `text` is, among `kinds` (in the order the command prefers them). Raises `BadId`."""
    allowed = tuple(kinds)
    unknown = [k for k in allowed if k not in KINDS]
    if unknown:
        raise ValueError(f"no such id kind {unknown[0]!r}")
    text = text.strip()
    if not text:
        raise BadId("unknown_id", "An id is missing.")
    if NUMBER.fullmatch(text):
        return _bare_number(text, allowed)
    prefix, sep, rest = text.partition(":")
    if sep:
        found = _prefixed(text, prefix, rest, allowed)
        if found is not None:
            return found
    return _bare(text, allowed)


def _wrong_kind(kind: str, allowed: tuple[str, ...], text: str) -> BadId:
    return BadId("bad_id_kind", f"{text} is {_article(kind)} id, but this command takes {_names(allowed)}.")


def _article(kind: str) -> str:
    return f"a {kind}" if kind != "aiff" else "an aiff batch"


def _names(allowed: tuple[str, ...]) -> str:
    words = [_KIND_WORDS[k] for k in allowed]
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " or " + words[-1]


_KIND_WORDS = {"track": "a track", "file": "a file", "aiff": "an aiff batch (aiff:<n>)", "moves": "a move batch (moves:<n>)",
               "job": "a job", "report": "a report", "plan": "a plan", "folder": "a folder", "playlist": "a playlist",
               "collection": "a collection"}


def _bare_number(text: str, allowed: tuple[str, ...]) -> Ident:
    if any(k in allowed for k in BATCH_KINDS):
        raise BadId("bad_id_kind", f"A batch id names its kind: say aiff:{text} or moves:{text}.")
    if "track" in allowed and SPOTIFY_ID.fullmatch(text):
        return Ident("track", text)  # a Spotify id that happens to be all digits
    raise BadId("unknown_id", f"{text} is not an id of the kind this command takes ({_names(allowed)}).")


def _prefixed(text: str, prefix: str, rest: str, allowed: tuple[str, ...]) -> Ident | None:
    """The id of a `<prefix>:<rest>` text, or None when the prefix is no id kind (then it is a bare text)."""
    if prefix in ("aiff", "moves", "file"):
        kind = prefix
        if kind not in allowed:
            raise _wrong_kind(kind, allowed, text)
        if not NUMBER.fullmatch(rest):
            raise BadId("unknown_id", f"{text} is not {_article(kind)} id: {kind}:<number> is.")
        return Ident(kind, int(rest))
    if prefix in ("job", "plan", "report"):
        kind = prefix
        if kind not in allowed:
            raise _wrong_kind(kind, allowed, text)
        pattern = {"job": JOB_ID, "plan": PLAN_ID, "report": REPORT_ID}[kind]
        if not pattern.fullmatch(rest):
            raise BadId("unknown_id", f"{text} is not a {kind} id.")
        return Ident(kind, rest)
    if prefix in ("folder", "playlist"):
        if not rest:
            raise BadId("unknown_id", f"{text} names nothing: say {prefix}:<name>.")
        for kind in (prefix, "collection"):
            if kind in allowed:
                return Ident(kind, rest if kind == prefix else text)
        raise _wrong_kind(prefix, allowed, text)
    if LOCAL_KEY.fullmatch(text) or text.startswith(SERVICE_PREFIXES):
        if "track" not in allowed:
            raise _wrong_kind("track", allowed, text)
        if not rest:
            raise BadId("unknown_id", f"{text} is not a track id.")
        return Ident("track", text)
    if prefix == "local":
        raise BadId("unknown_id", f"{text} is not a track id: local:<number> is.")
    return None


def _path_like(text: str) -> bool:
    return "/" in text or text.startswith("~")


def _bare(text: str, allowed: tuple[str, ...]) -> Ident:
    """A text with no id prefix: a word (`last`, `current`, `all`), a path, a name, a bare Spotify id."""
    if text == "-" and "track" in allowed:
        return Ident("track", "-")
    if text == "last" and "report" in allowed:
        return Ident("report", "last")
    if text == "current" and "job" in allowed:
        return Ident("job", "current")
    if text in COLLECTION_WORDS and "collection" in allowed:
        return Ident("collection", text)
    if REPORT_ID.fullmatch(text) and "report" in allowed:
        return Ident("report", text)
    if _path_like(text):
        if "track" in allowed or "file" in allowed:
            return Ident("path", text)
        if "folder" in allowed:
            return Ident("folder", text)
        if "collection" in allowed:
            return Ident("collection", f"folder:{text}")
    else:
        if "track" in allowed and SPOTIFY_ID.fullmatch(text):
            return Ident("track", text)
        if "playlist" in allowed:
            return Ident("playlist", text)
    raise BadId("unknown_id", f"{text} is not an id of the kind this command takes ({_names(allowed)}).")
