"""A Discjockey library for Give it its clean name (`rename.rename_file`; tests/test_rename*.py): the user's own AIFF
(16-bit/44.1 kHz) whose tags say what the song record says, under a messy name, in a rekordbox library (built by
make_master in tmp_path) whose track holds it, with cues, a grid and a waveform. Built on tests/convert_helpers.py;
nothing real is read.

`power_off(monkeypatch, at)` cuts the step as convert_helpers' does (after the journal, a mark, or inside the end);
the clean-up steps of the step never run after a power cut.
"""
from __future__ import annotations

from pathlib import Path

import convert_helpers as ch
from convert_helpers import NOW, TID, Env, PowerOff, make_own
from discjockey import rbstep, rename
from discjockey.audio import write_tags
from discjockey.library import load_state
from discjockey.rekordbox.session import Session

OLD = "Library/A/Old Name.aiff"
CLEAN = "Library/A/Artist - Song.aiff"
ID_NAME = "Library/A/Artist - Song [t1aaaa].aiff"
LOSSLESS = {"status": "lossless", "source_format": None}  # an own lossless file (its AIFF would be in Library/A/)


def make_clean(tmp_path: Path, monkeypatch, *, entry: dict | None = None, **kw) -> Env:
    """`make_own` for Rename: an own AIFF 16/44.1 with the record's title and artist in its tags under the name
    `Old Name.aiff` (`entry` overrides the song, `kw` the rest as `make_env`)."""
    env = make_own(tmp_path, monkeypatch, "aiff", entry={**LOSSLESS, **(entry or {})}, **kw)
    path = env.paths.root / load_state(env.paths)["tracks"][TID]["path"]
    write_tags(path, title="Song", artists=("Artist",), album="Old Album", isrc=None, label=None, cover=None,
               comment="")
    return env


def run_rename(env: Env, *, running=ch.never, batch: tuple[int, int] | None = None, state: dict | None = None,
               track: str = TID, need_write: bool = True):
    """Give it its clean name for the song, in its own session (`need_write`: whether the batch's items need a
    rekordbox write, which a running rekordbox refuses at the session's start); returns (Result, state)."""
    state = load_state(env.paths) if state is None else state
    with Session.open(env.paths, place=env.place, running=running, items_need_write=lambda v: need_write,
                      batch_id=batch[0] if batch else None) as s:
        r = rename.rename_file(env.paths, state, track, session=s, now=lambda: NOW, batch=batch)
    return r, state


def start_rename_batch(env: Env) -> int:
    from discjockey import db
    with db.connect(env.paths.db_file) as conn:
        return db.start_aiff_batch(conn, "convert", "user", None, [(TID, "rename")], NOW)


MARKS = {"backed_up": 1, "placed": 2, "record": 3, "committed_unmarked": 4, "committed": 4}
BEFORE_COMMIT = ["journaled", "backed_up", "placed", "record"]
AFTER_COMMIT = ["committed_unmarked", "committed", "ended"]


def power_off(monkeypatch, at: str) -> None:
    """Cut the step at `at`: after the journal (`journaled`: the backup is the next thing), a mark (written first,
    except `committed_unmarked`: rekordbox committed, its mark not written) or inside the end (`ended`)."""
    def die(*a, **k):
        raise PowerOff

    for name in ("_drop", "_roll_back", "_settle"):  # the step's own clean-up never runs after a power cut
        monkeypatch.setattr(rename, name, die)
    if at == "journaled":
        monkeypatch.setattr(Session, "ensure_backup", die)
        monkeypatch.setattr(rename, "move_path", die)
        return
    if at == "ended":
        monkeypatch.setattr(rename, "end_op", die)
        return
    real, calls = rename.mark_op, {"n": 0}

    def mark(paths, state, op):
        calls["n"] += 1
        if calls["n"] == MARKS[at]:
            if at != "committed_unmarked":
                real(paths, state, op)
            raise PowerOff
        real(paths, state, op)
    monkeypatch.setattr(rename, "mark_op", mark)
    monkeypatch.setattr(rbstep, "mark_op", mark)  # the `record` mark is journaled by rbstep.journal_record


UNDO_MARKS = {"restored": 1, "outcome": 2, "committed_unmarked": 3, "committed": 3}


def power_off_undo(monkeypatch, at: str) -> None:
    """The same for an undo (`journaled`, `restored`, `outcome`: inside rekordbox's transaction, `committed_unmarked`,
    `committed`, `ended`); the undo's own clean-up never runs after a power cut."""
    def die(*a, **k):
        raise PowerOff

    for name in ("_undo_back", "_settle_undo"):
        monkeypatch.setattr(rename, name, die)
    if at == "journaled":
        monkeypatch.setattr(rename, "move_path", die)
        monkeypatch.setattr(rename, "end_op", die)
        return
    if at == "ended":
        monkeypatch.setattr(rename, "_end_undo", die)
        return
    real, calls = rename.mark_op, {"n": 0}

    def mark(paths, state, op):
        calls["n"] += 1
        if calls["n"] == UNDO_MARKS[at]:
            if at != "committed_unmarked":
                real(paths, state, op)
            raise PowerOff
        real(paths, state, op)
    monkeypatch.setattr(rename, "mark_op", mark)


next_start = ch.next_start
file_facts_row = ch.file_facts_row
batch_row = ch.batch_row
