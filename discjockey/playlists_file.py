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
from dataclasses import dataclass, field, replace
from datetime import date
from pathlib import Path

from . import config, sources, words
from .library import fsync_dir, full_fsync
from .models import FetchedPlaylist, PlaylistLine, SourceTrack, split_token, token
from .names import fold
from .planner import desired_folders

OFF = "#off#"
CHANGED_ELSEWHERE = "playlists.txt was changed elsewhere (by hand or by the console). Reload the page and try again."


class PlaylistsChanged(Exception):
    pass


LIKED_MUSIC_REF = token("youtube_music", "LM")  # the ref of YouTube Music's Liked music (sources-round D5)


def lists_liked_music(rows: list["Row"]) -> bool:
    """Whether a row is YouTube Music's Liked music, on or off."""
    return any(r.ref == LIKED_MUSIC_REF for r in rows)


@dataclass(frozen=True)
class Row:
    folder: str
    link: str  # as written in the file (new rows: a clean link)
    enabled: bool = True

    @property
    def service(self) -> str | None:
        """The playlist service the link belongs to (None for a link no source recognises)."""
        found = sources.recognise(self.link)
        return found[0] if found else None

    @property
    def ref(self) -> str | None:
        """The playlist's token (models.token): its id for Spotify, `service:id` for another service."""
        found = sources.recognise(self.link)
        return token(*found) if found else None


@dataclass
class Loaded:
    rows: list[Row]
    version: str  # SHA-256 of the file as read ("" when there is no file): saving checks it is still the same
    problem: str | None  # what the sync would say about the file (None when it is fine)


def version_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest() if data else ""


def clean_link(url: str) -> str:
    found = sources.recognise(url.strip())
    if found is None:
        raise ValueError("That isn't a playlist link Discjockey can read. Open the playlist in "
                         f"{sources.service_list()}, choose Share, then Copy link, and paste it here.")
    service, pid = found
    return sources.SOURCES[service].canonical_link(pid)


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
    if not folder or sources.recognise(link) is None:
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


# --- rules of the list and the single changes to it ---

OPS = ("add", "remove", "rename", "move", "enable", "disable", "edit")
# What each change needs, in the order its refusal names the missing ones, and what else it may carry (`add` only).
_NEEDS = {"add": ("url",), "remove": ("playlist",), "rename": ("playlist", "folder"), "move": ("playlist", "to"),
          "enable": ("playlist",), "disable": ("playlist",), "edit": ("file",)}
_MAY = {"add": ("folder", "at", "off")}
_KINDS = {"url": str, "playlist": str, "folder": str, "file": str, "at": int, "to": int, "off": bool}
# The operation names a change is logged under (`history` reads them), the window's whole-list save and Liked music
LOGGED = {"add": "playlist_add", "remove": "playlist_remove", "rename": "playlist_rename", "move": "playlist_move",
          "enable": "playlist_enable", "disable": "playlist_disable", "edit": "playlist_edit"}
SAVED = "playlist_saved"
LIKED_ADDED = "liked_music_add"
FOLDER_PREFIX = "playlist:"  # `playlist:<folder>` names a playlist by its folder, never as a link or a flag


def _name(folder: str) -> str:
    """A folder name as the list keeps it: NFC (macOS may hand back NFD) and trimmed."""
    return unicodedata.normalize("NFC", folder).strip()


def folder_problem(name: str, rows: list[Row], own_ref: str | None = None) -> str | None:
    """Why `name` can't be a playlist's folder, in the window's own words, or None. The playlist whose ref is `own_ref`
    may keep its own name (a case-only rename is fine)."""
    n = name.strip()
    if not n:
        return words.FOLDER_NEEDED
    if "/" in n:
        return words.FOLDER_SLASH
    if n in (".", ".."):
        return words.FOLDER_PICK_ANOTHER
    other = next((r for r in rows if r.ref != own_ref and fold(r.folder) == fold(n)), None)
    return words.FOLDER_USED.format(folder=other.folder) if other else None


def listed(rows: list[Row], link: str) -> Row | None:
    """The row that lists the playlist `link` names (the same playlist by its ref, however the link is written), or None."""
    found = sources.recognise(link.strip())
    ref = token(*found) if found else None
    return next((r for r in rows if ref is not None and r.ref == ref), None)


def find(rows: list[Row], playlist: str) -> int:
    """The index of the row `playlist` names: `playlist:<folder>` is a folder (never read as a link), else a link a
    source recognises names the row with its ref, else the text is a folder name (compared as `fold` does).
    `ValueError` when none or more than one row fits."""
    text = playlist.strip()
    if text.startswith(FOLDER_PREFIX):
        name = text[len(FOLDER_PREFIX):].strip()
        hits = [i for i, r in enumerate(rows) if fold(r.folder) == fold(name)]
    elif (found := sources.recognise(text)) is not None:
        name, ref = text, token(*found)
        hits = [i for i, r in enumerate(rows) if r.ref == ref]
    else:
        name = text
        hits = [i for i, r in enumerate(rows) if fold(r.folder) == fold(name)]
    if not hits:
        raise ValueError(words.PLAYLIST_NOT_FOUND.format(name=name))
    if len(hits) > 1:
        raise ValueError(words.PLAYLIST_TWO.format(name=name))
    return hits[0]



def check_op(op: object) -> dict:
    """The change `op` as a dict, or `ValueError` saying what is wrong with it: no `op`, an `op` Discjockey doesn't know,
    a missing key, a key this change doesn't use, a value of the wrong kind. Checks the shape only; `apply` checks the
    values against the rows."""
    if not isinstance(op, dict) or "op" not in op:
        raise ValueError(words.PLAYLIST_OP_NEEDS.format(op="playlist", fields="op"))
    name = op["op"]
    if name not in OPS:
        raise ValueError(words.PLAYLIST_OP_UNKNOWN.format(op=name))
    missing = [k for k in _NEEDS[name] if k not in op]
    if missing:
        raise ValueError(words.PLAYLIST_OP_NEEDS.format(op=name, fields=" and ".join(missing)))
    allowed = ("op", *_NEEDS[name], *_MAY.get(name, ()))
    for key in op:
        if key not in allowed:
            raise ValueError(words.PLAYLIST_OP_FIELD.format(field=key, op=name))
    for key, value in op.items():
        kind = _KINDS.get(key)
        if kind is not None and (not isinstance(value, kind) or (kind is int and isinstance(value, bool))):
            raise ValueError(words.PLAYLIST_OP_TYPE.format(field=key, kind=words.PLAYLIST_OP_KINDS[kind.__name__]))
    return op


def _place(n: int, last: int) -> int:
    if not 1 <= n <= last:
        raise ValueError(words.PLAYLIST_PLACE.format(n=last))
    return n


def apply(rows: list[Row], op: dict) -> list[Row]:
    """Pure (but for `edit`, which reads its file): the rows after one change. `ValueError` with the words when the
    change can't be made to these rows."""
    op = check_op(op)
    rows = list(rows)
    name = op["op"]
    if name == "add":
        link = clean_link(op["url"])
        if listed(rows, link) is not None:
            raise ValueError(words.PLAYLIST_LISTED)
        if "folder" not in op:
            raise ValueError(words.PLAYLIST_OP_NEEDS.format(op="add", fields="folder"))
        folder = _name(op["folder"])
        if problem := folder_problem(folder, rows):
            raise ValueError(problem)
        at = _place(op.get("at", len(rows) + 1), len(rows) + 1)
        rows.insert(at - 1, Row(folder, link, not op.get("off", False)))
    elif name == "edit":
        path = Path(op["file"])
        if not path.is_absolute():
            raise ValueError(words.PLAYLIST_FILE_FULL_PATH)
        if not path.is_file():
            raise ValueError(words.PLAYLIST_FILE_MISSING.format(path=path))
        loaded = load(path)
        if loaded.problem:
            raise ValueError(loaded.problem)
        rows = loaded.rows
    else:
        i = find(rows, op["playlist"])
        if name == "remove":
            del rows[i]
        elif name == "rename":
            folder = _name(op["folder"])
            if problem := folder_problem(folder, rows, own_ref=rows[i].ref):
                raise ValueError(problem)
            rows[i] = replace(rows[i], folder=folder)
        elif name == "move":
            rows.insert(_place(op["to"], len(rows)) - 1, rows.pop(i))
        else:
            rows[i] = replace(rows[i], enabled=name == "enable")
    return rows


# --- the change log: the words of a change, its undo and what `history` says of it ---

def op_words(op: dict) -> list[str]:
    """The command words that make the change `op` (checked, and for `add` with its folder): the one writer of them, for
    the undo `history` offers and for a dry run's lines."""
    name = op["op"]
    if name == "add":
        out = ["playlist", "add", op["url"]]
        if "folder" in op:
            out += ["--folder", op["folder"]]
        if "at" in op:
            out += ["--at", str(op["at"])]
        return out + (["--off"] if op.get("off") else [])
    if name == "rename":
        return ["playlist", "rename", op["playlist"], op["folder"]]
    if name == "move":
        return ["playlist", "move", op["playlist"], "--to", str(op["to"])]
    if name == "edit":
        return ["playlist", "edit", "--file", op["file"]]
    return ["playlist", name, op["playlist"]]


def undo_op(before: list[Row], op: dict | None, copy: str | None) -> dict:
    """The change that puts `before` (the rows the change `op` was made to) back. `op` None (the window's whole-list
    save) or `edit` can only be undone by replacing the list with `copy`, the file as it was. The playlist in it is
    always `playlist:<folder>`, so no folder is read as a flag or a link."""
    if op is None or op["op"] == "edit":
        if copy is None:
            raise ValueError("Undoing a replaced list needs the copy of the file as it was.")
        return {"op": "edit", "file": copy}
    name = op["op"]
    if name == "add":
        return {"op": "remove", "playlist": FOLDER_PREFIX + _name(op["folder"])}
    i = find(before, op["playlist"])
    row = before[i]
    if name == "remove":
        back: dict = {"op": "add", "url": row.link, "folder": row.folder, "at": i + 1}
        return back | ({} if row.enabled else {"off": True})
    if name == "rename":
        return {"op": "rename", "playlist": FOLDER_PREFIX + _name(op["folder"]), "folder": row.folder}
    if name == "move":
        return {"op": "move", "playlist": FOLDER_PREFIX + row.folder, "to": i + 1}
    # enable / disable: the switch back as it was (a switch already so changes nothing and is never logged)
    return {"op": "enable" if row.enabled else "disable", "playlist": FOLDER_PREFIX + row.folder}


def _said(before: list[Row], op: dict) -> tuple[str, dict]:
    """The operation's name and the words' fields of the change `op` (not an add of Liked music)."""
    name = op["op"]
    if name == "add":
        return LOGGED[name], {"folder": _name(op["folder"]), "at": op.get("at", len(before) + 1)}
    if name == "edit":
        return LOGGED[name], {"file": op["file"]}
    i = find(before, op["playlist"])
    fields = {"folder": before[i].folder}
    if name == "rename":
        fields |= {"old": before[i].folder, "new": _name(op["folder"])}
    elif name == "move":
        fields |= {"old": i + 1, "to": op["to"]}
    return LOGGED[name], fields


def change_log(before: list[Row], op: dict | None, copy: str | None) -> tuple[str, str, list[str]]:
    """`(operation, message, undo words)` for the change `op` made to `before` (`op` None: the window's whole-list
    save, `copy` the file as it was). What `ops.log_change` writes and `history` offers; an add of YouTube Music's Liked
    music is logged as its own operation, whichever way it was added."""
    undo = op_words(undo_op(before, op, copy))
    if op is None:
        return SAVED, words.PLAYLIST_LOGGED[SAVED], undo
    found = sources.recognise(op["url"].strip()) if op["op"] == "add" else None
    if found is not None and token(*found) == LIKED_MUSIC_REF:
        return LIKED_ADDED, words.PLAYLIST_LOGGED[LIKED_ADDED].format(folder=_name(op["folder"])), undo
    operation, fields = _said(before, op)
    switched_off = operation == LOGGED["add"] and op.get("off")
    template = words.PLAYLIST_LOGGED_ADD_OFF if switched_off else words.PLAYLIST_LOGGED[operation]
    return operation, template.format(**fields), undo


# --- what a change does ---

@dataclass
class Change:
    before: dict[str, int]  # folder -> tracks that belong there with the saved lines
    after: dict[str, int]  # ... and with the edited ones
    moves: list[tuple[str, str, str]]  # (track id, from folder, to folder) for tracks that have a file
    reroutes: list[tuple[str, str, str]] = field(default_factory=list)  # ... for tracks without a file yet
    new: list[str] = field(default_factory=list)  # track ids that would be downloaded because of the change
    stopped: list[str] = field(default_factory=list)  # track ids in no active playlist any more (files stay)
    unknown: list[str] = field(default_factory=list)  # playlist refs not read yet (their tracks are not counted)


def _fetched(rows: list[Row], tracks_by_id: dict[str, list[SourceTrack]]) -> list[FetchedPlaylist]:
    """The switched-on rows as the planner sees them, with the tracks last read; rows not read yet are left out."""
    return [FetchedPlaylist(PlaylistLine(r.folder, split_token(r.ref)[1], i, r.service), list(tracks_by_id[r.ref]), [])
            for i, r in enumerate(rows, start=1) if r.enabled and r.ref in tracks_by_id]


def placement(rows: list[Row], tracks_by_id: dict[str, list[SourceTrack]], state: dict) -> dict[str, str]:
    """Pure: state key -> the folder the song belongs in under `rows`, for the songs of the playlists read so far
    (a playlist not read yet places none of its songs)."""
    return desired_folders(_fetched(rows, tracks_by_id), state)


def _changed(before: dict[str, str], after: dict[str, str]) -> list[tuple[str, str, str]]:
    """(key, folder before, folder after) for songs placed by both whose folder differs other than in case (a
    case-only rename is no move, as in the planner)."""
    return [(k, before[k], folder) for k, folder in after.items() if k in before and fold(before[k]) != fold(folder)]


def retargeted(old: list[Row], new: list[Row], tracks_by_id: dict[str, list[SourceTrack]],
               state: dict) -> dict[str, str]:
    """Pure: the songs whose folder the edit from `old` to `new` changes -> their new folder (the tidy-up's
    `folders` for the save preview). Songs of playlists not read yet are not in it."""
    before, after = placement(old, tracks_by_id, state), placement(new, tracks_by_id, state)
    return {k: folder for k, _, folder in _changed(before, after)}


def renames(old: list[Row], new: list[Row]) -> list[tuple[str, str]]:
    """Pure: (old folder, new folder) for every playlist (the same playlist in both) whose folder name the edit
    changes other than in case, in `new`'s order, each pair once (the on-disk folder renames to offer)."""
    before: dict[str, str] = {}
    for r in old:
        if r.ref is not None:
            before.setdefault(r.ref, r.folder)
    out: list[tuple[str, str]] = []
    for r in new:
        was = before.get(r.ref) if r.ref is not None else None
        if was is not None and fold(was) != fold(r.folder) and (was, r.folder) not in out:
            out.append((was, r.folder))
    return out


def preview_change(old: list[Row], new: list[Row], tracks_by_id: dict[str, list[SourceTrack]], state: dict,
                   files: list[str], today: date) -> Change:
    """Pure: the planner's view of the edited lines against the last playlists read from Spotify."""
    unknown = [r.ref for r in new if r.enabled and r.ref not in tracks_by_id]
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


def overlaps(rows: list[Row], tracks_by_id: dict[str, list[SourceTrack]]) -> list[tuple[SourceTrack, list[str], str]]:
    """Tracks in several active playlists: (track, the folders it is in, the folder it lands in = the first)."""
    seen: dict[str, tuple[SourceTrack, list[str]]] = {}
    for r in rows:
        if not r.enabled:
            continue
        for t in tracks_by_id.get(r.ref, []):
            folders = seen.setdefault(t.key, (t, []))[1]
            if r.folder not in folders:
                folders.append(r.folder)
    return [(t, folders, folders[0]) for t, folders in seen.values() if len(folders) > 1]
