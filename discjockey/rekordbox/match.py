"""Does rekordbox match the library? (issue 39, `rekordbox match`, `library superseded`, `doctor`.)

`classify` puts every rekordbox track that holds a file into one kind, and finds the library files no track holds. It is
pure: the caller passes the tracks (`Master.tracks()`), the library's files, the roots and a function that says whether a
path is there. `read` opens the library read-only for one such read; the caller holds `rekordbox.lock` shared around it.

A rekordbox track is, the first that applies:
- `superseded`: its file lies under `<root>/Superseded/` (a replaced file; rekordbox still points at it);
- `away`: it lies under a watched folder whose drive is not connected now;
- `missing`: the file is not there;
- `outside`: it is there but under none of the roots: a file of the DJ's own elsewhere. Counted, never a problem (a
  rekordbox library may hold thousands of them);
- `not_in_library`: it is there, inside a root, but no song of the library has it as its file;
- `matched`: the file is a song's current file.

Then each file of the library that no track holds is `not_in_rekordbox`. Paths compare as `names.fold` does (NFC, case
folded), the way `Master.entries_for` compares.
"""
from __future__ import annotations

from collections.abc import Callable, Collection, Iterable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

import sqlcipher3

from ..names import fold
from . import master
from .locate import Place
from .master import Entry, Unreadable

Kind = Literal["matched", "outside", "missing", "superseded", "away", "not_in_library", "not_in_rekordbox"]
LISTED: tuple[Kind, ...] = ("missing", "superseded", "away", "not_in_library", "not_in_rekordbox")  # the kinds a person reads, in order
SUPERSEDED_DIR = "Superseded"  # `Paths.superseded`'s name, under the music folder
T = TypeVar("T")


@dataclass(frozen=True)
class Row:
    """One finding. `entry` is the rekordbox track (None for `not_in_rekordbox`); `key` the library song whose current
    file it is, if any; `folded` the file's folded path (the order of the rows, and for `not_in_rekordbox` the only form
    of the path `classify` was given: the caller names the file by `key`)."""
    kind: Kind
    entry: Entry | None
    key: str | None
    folded: str


def under(folded_path: str, folded_base: str) -> bool:
    """Whether `folded_path` is inside the folder `folded_base` (both folded)."""
    return folded_path.startswith(folded_base.rstrip("/") + "/")


def classify(tracks: Iterable[Entry], *, root: Path, roots: Collection[Path], library_files: Mapping[str, str],
             away_roots: Collection[Path], exists: Callable[[Path], bool]) -> list[Row]:
    """Every track's kind, then the `not_in_rekordbox` files, listed kinds first (`LISTED` order), each by folded path.
    `root` is the music folder, `roots` it and every watched folder, `library_files` maps the folded absolute path of each
    song's current file to the song's key, `away_roots` the watched folders whose drive is away now, `exists` says
    whether a file is there."""
    superseded = fold(str(root / SUPERSEDED_DIR))
    away = [fold(str(p)) for p in away_roots]
    inside = [fold(str(p)) for p in roots]
    rows: list[Row] = []
    held: set[str] = set()
    for entry in tracks:
        folded = fold(entry.folder_path)
        held.add(folded)
        key = library_files.get(folded)
        if under(folded, superseded):
            kind: Kind = "superseded"
        elif any(under(folded, a) for a in away):
            kind = "away"
        elif not exists(Path(entry.folder_path)):
            kind = "missing"
        elif not any(under(folded, r) for r in inside):
            kind = "outside"
        elif key is None:
            kind = "not_in_library"
        else:
            kind = "matched"
        rows.append(Row(kind, entry, key, folded))
    rows += [Row("not_in_rekordbox", None, key, folded) for folded, key in library_files.items() if folded not in held]
    order = {kind: i for i, kind in enumerate((*LISTED, "matched", "outside"))}
    return sorted(rows, key=lambda r: (order[r.kind], r.folded, r.entry.id if r.entry else ""))


def read(place: Place, running: bool, reading: Callable[[master.Master], T]) -> T:
    """`reading(master)` on `place`'s library, opened read-only and closed again. Raises `Unreadable`; a read that fails
    inside (a busy or damaged file) is `Unreadable` too (`busy` while rekordbox runs, else `schema`)."""
    try:
        with master.open_read(place, running) as library:
            return reading(library)
    except sqlcipher3.DatabaseError:
        raise Unreadable("busy" if running else "schema") from None
