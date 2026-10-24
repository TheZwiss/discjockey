"""playlists.txt for the hub's playlist page: rows to edit, a writer that keeps comments and blank lines, and what a
change would do. playlists.txt stays the source of truth, so the console keeps working.

A switched-off playlist is written as `#off# Folder = link`: a comment for the sync (its files stay, no more
updates), but never confused with the user's own comments.
"""
from __future__ import annotations

import hashlib
import os
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import config
from .library import fsync_dir, full_fsync
from .models import FetchedPlaylist, PlaylistLine, SpotifyTrack
from .names import fold
from .planner import desired_folders

OFF = "#off#"
CHANGED_ELSEWHERE = "playlists.txt was changed elsewhere (by hand or by the console). Reload the page and try again."


class PlaylistsChanged(Exception):
    pass


@dataclass(frozen=True)
class Row:
    folder: str
    link: str  # as written in the file (new rows: a clean link)
    enabled: bool = True

    @property
    def playlist_id(self) -> str | None:
        return config.playlist_id(self.link)


@dataclass
class Loaded:
    rows: list[Row]
    version: str  # SHA-256 of the file as read ("" when there is no file): saving checks it is still the same
    problem: str | None  # what the sync would say about the file (None when it is fine)


def version_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest() if data else ""


def clean_link(url: str) -> str:
    pid = config.playlist_id(url.strip())
    if pid is None:
        raise ValueError("That is not a Spotify playlist link. In Spotify: open the playlist → ⋯ → Share → Copy link "
                         "to playlist.")
    return f"https://open.spotify.com/playlist/{pid}"


def _row(line: str) -> Row | None:
    """The playlist on this line, or None for comments, blank lines and lines the sync would refuse."""
    text, enabled = line.strip(), True
    if text.startswith(OFF):
        text, enabled = text[len(OFF):].strip(), False
    elif not text or text.startswith("#"):
        return None
    if "=" not in text:
        return None
    folder, link = (part.strip() for part in text.split("=", 1))
    if not folder or config.playlist_id(link) is None:
        return None
    return Row(unicodedata.normalize("NFC", folder), link, enabled)


def _problem(text: str) -> str | None:
    try:
        config.parse_playlists(text)
    except config.ConfigError as e:
        return str(e)
    return None


def load(path: Path) -> Loaded:
    data = path.read_bytes() if path.exists() else b""
    text = data.decode("utf-8-sig")
    rows = [r for r in map(_row, text.splitlines()) if r is not None]
    return Loaded(rows, version_of(data), _problem(text) if data else None)


def _line(r: Row) -> str:
    return f"{OFF + ' ' if not r.enabled else ''}{r.folder} = {r.link}"


def render(text: str, rows: list[Row]) -> str:
    """The rows in their new order, written into the playlist lines of `text`; every other line stays where it is.
    Extra rows go to the end; lines of removed rows disappear."""
    out: list[str] = []
    rest = iter(rows)
    for line in text.splitlines():
        if _row(line) is None:
            out.append(line)
        elif (r := next(rest, None)) is not None:
            out.append(_line(r))
    out += [_line(r) for r in rest]
    return "\n".join(out) + "\n"


def validate(rows: list[Row]) -> None:
    """The sync's own rules for every row, also switched-off ones (so switching one on later cannot fail)."""
    try:
        config.parse_playlists("\n".join(f"{r.folder} = {r.link}" for r in rows))
    except config.ConfigError as e:
        if e.kind != "not_set_up":  # no rows at all is fine here
            raise


def save(path: Path, rows: list[Row], loaded_version: str) -> str:
    """Writes atomically; refuses when the file changed since the page loaded it. Returns the new version.
    The caller holds the run lock (a running sync reads this file)."""
    data = path.read_bytes() if path.exists() else b""
    if version_of(data) != loaded_version:
        raise PlaylistsChanged(CHANGED_ELSEWHERE)
    validate(rows)
    new = render(data.decode("utf-8-sig"), rows).encode("utf-8")
    tmp = path.with_name(path.name + ".tmp")
    try:
        with open(tmp, "wb") as f:
            f.write(new)
            f.flush()
            full_fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)
    fsync_dir(path.parent)
    return version_of(new)


# --- what a change does ---

@dataclass
class Change:
    before: dict[str, int]  # folder -> tracks that belong there with the saved lines
    after: dict[str, int]  # ... and with the edited ones
    moves: list[tuple[str, str, str]]  # (track id, from folder, to folder) for tracks that have a file
    reroutes: list[tuple[str, str, str]] = field(default_factory=list)  # ... for tracks without a file yet
    new: list[str] = field(default_factory=list)  # track ids that would be downloaded because of the change
    stopped: list[str] = field(default_factory=list)  # track ids in no active playlist any more (files stay)
    unknown: list[str] = field(default_factory=list)  # playlist ids not read yet (their tracks are not counted)


def _fetched(rows: list[Row], tracks_by_id: dict[str, list[SpotifyTrack]]) -> list[FetchedPlaylist]:
    """The switched-on rows as the planner sees them, with the tracks last read; rows not read yet are left out."""
    return [FetchedPlaylist(PlaylistLine(r.folder, r.playlist_id, i), list(tracks_by_id[r.playlist_id]), [])
            for i, r in enumerate(rows, start=1) if r.enabled and r.playlist_id in tracks_by_id]


def placement(rows: list[Row], tracks_by_id: dict[str, list[SpotifyTrack]], state: dict) -> dict[str, str]:
    """Pure: state key -> the folder the song belongs in under `rows`, for the songs of the playlists read so far
    (a playlist not read yet places none of its songs)."""
    return desired_folders(_fetched(rows, tracks_by_id), state)


def _changed(before: dict[str, str], after: dict[str, str]) -> list[tuple[str, str, str]]:
    """(key, folder before, folder after) for songs placed by both whose folder differs other than in case (a
    case-only rename is no move, as in the planner)."""
    return [(k, before[k], folder) for k, folder in after.items() if k in before and fold(before[k]) != fold(folder)]


def retargeted(old: list[Row], new: list[Row], tracks_by_id: dict[str, list[SpotifyTrack]],
               state: dict) -> dict[str, str]:
    """Pure: the songs whose folder the edit from `old` to `new` changes -> their new folder (the tidy-up's
    `folders` for the save preview). Songs of playlists not read yet are not in it."""
    before, after = placement(old, tracks_by_id, state), placement(new, tracks_by_id, state)
    return {k: folder for k, _, folder in _changed(before, after)}


def renames(old: list[Row], new: list[Row]) -> list[tuple[str, str]]:
    """Pure: (old folder, new folder) for every playlist (the same playlist id in both) whose folder name the edit
    changes other than in case, in `new`'s order, each pair once (the on-disk folder renames to offer)."""
    before: dict[str, str] = {}
    for r in old:
        if r.playlist_id is not None:
            before.setdefault(r.playlist_id, r.folder)
    out: list[tuple[str, str]] = []
    for r in new:
        was = before.get(r.playlist_id) if r.playlist_id is not None else None
        if was is not None and fold(was) != fold(r.folder) and (was, r.folder) not in out:
            out.append((was, r.folder))
    return out


def preview_change(old: list[Row], new: list[Row], tracks_by_id: dict[str, list[SpotifyTrack]], state: dict,
                   files: list[str], today: date) -> Change:
    """Pure: the planner's view of the edited lines against the last playlists read from Spotify."""
    unknown = [r.playlist_id for r in new if r.enabled and r.playlist_id not in tracks_by_id]
    before = placement(old, tracks_by_id, state)
    after = placement(new, tracks_by_id, state)
    tracks = state["tracks"]
    on_disk = {fold(f) for f in files}
    changed = _changed(before, after)
    has_file = {k for k, _, _ in changed if k in tracks and tracks[k].get("path")
                and fold(tracks[k]["path"]) in on_disk}
    change = Change(dict(Counter(before.values())), dict(Counter(after.values())),
                    [c for c in changed if c[0] in has_file], [c for c in changed if c[0] not in has_file])
    change.new = [k for k in after if k not in before and k not in tracks]
    change.stopped = [k for k in before if k not in after and k in tracks]
    change.unknown = unknown
    return change


def overlaps(rows: list[Row], tracks_by_id: dict[str, list[SpotifyTrack]]) -> list[tuple[SpotifyTrack, list[str], str]]:
    """Tracks in several active playlists: (track, the folders it is in, the folder it lands in = the first)."""
    seen: dict[str, tuple[SpotifyTrack, list[str]]] = {}
    for r in rows:
        if not r.enabled:
            continue
        for t in tracks_by_id.get(r.playlist_id, []):
            folders = seen.setdefault(t.id, (t, []))[1]
            if r.folder not in folders:
                folders.append(r.folder)
    return [(t, folders, folders[0]) for t, folders in seen.values() if len(folders) > 1]
