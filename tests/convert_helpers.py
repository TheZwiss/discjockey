"""A Discjockey library with one song whose current file isn't AIFF, a parked lossless upgrade of the same edit, and a
rekordbox library (built by make_master in tmp_path) whose track holds the file, with cues, a grid and a waveform
that puts rekordbox's timeline `d` samples after ffmpeg's decode. For tests/test_convert*.py; nothing real is read.

Old files: `lame` (tests/fixtures/clicks-lame.mp3: rekordbox at 1105 samples), `notag` (clicks-notag.mp3: 0), `m4a`
(an AAC made from a click track here: rekordbox at ffmpeg's start trim), `wav48` (a 48 kHz WAV: 0), `flac96` (a 24-bit
96 kHz FLAC: 0) and `aiff` (a 16-bit/44.1 kHz AIFF with the wrong tags: 0). The parked upgrade is ffmpeg's decode of
the old file as a 16-bit/44.1 kHz stereo AIFF with the download's tags, so the two are the same edit with L = 0.

`make_own` is the same library for Convert to AIFF (`convert.convert_file`): the song is the user's own (source
"manual", no parked upgrade) and its file row was placed by the import, with the old file's facts stored.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from discjockey import convert, db, library, quality
from discjockey.align import Alignment
from discjockey.audio import write_tags
from discjockey.library import Paths, load_state, save_state
from discjockey.planner import ENTRY_KEYS
from discjockey.rekordbox import probe
from discjockey.rekordbox.locate import Place
from discjockey.rekordbox.session import Session
from rekordbox_helpers import clicks, make_anlz, make_master, ppth_tag, pqtz_tag, pwv3_from, pwv3_tag, save_library
from rekordbox_helpers import write_wav
from audio_helpers import write_aiff

FIXTURES = Path(__file__).parent / "fixtures"
TID = "t1aaaaaaa"
PARKED = "Upgrades ready/A/Artist - Song.aiff"
NEW = "Library/A/Artist - Song.aiff"
EXACT = Alignment("exact", 0, 0.0, 0.0, "matches exactly")
NOW = datetime(2026, 11, 8, 12, 0)
OLD = {"lame": "Library/A/Old Name.mp3", "notag": "Library/A/Old Name.mp3", "m4a": "Library/A/Old Name.m4a",
       "wav48": "Library/A/Old Name.wav", "flac96": "Library/A/Old Name.flac", "aiff": "Library/A/Old Name.aiff"}
OWN = {"source": "manual", "source_id": None, "source_format": "mp3", "cutoff_hz": None, "upgrade": None,
       "status": "not_lossless", "in_playlists": False}  # the song record of an own file Convert works on


def never() -> bool:
    return False


def exact(current, new) -> Alignment:
    return EXACT


@dataclass
class Env:
    paths: Paths
    place: Place | None
    folder: Path   # the rekordbox library's folder
    old: str       # the current file (music-folder relative)
    d: int         # rekordbox's offset for it, 44.1 kHz samples

    @property
    def superseded(self) -> str:
        return "Superseded/" + self.old.removeprefix("Library/")

    def dat(self) -> Path:
        return self.folder / "share/PIONEER/USBANLZ/000/1/ANLZ0000.DAT"

    def anlz_files(self) -> dict[str, bytes]:
        share = self.folder / "share"
        return {str(p.relative_to(share)): p.read_bytes() for p in sorted(share.rglob("*")) if p.is_file()} \
            if share.is_dir() else {}

    def music(self) -> dict[str, bytes]:
        """Every file of the music folder outside .discjockey/, with its bytes."""
        root = self.paths.root
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
                if p.is_file() and ".discjockey" not in p.relative_to(root).parts}


def song(path: str, **kw) -> dict:
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=30000, folder="A", path=path,
             status="not_lossless", source="youtube_music", source_id="y1", source_format="opus", cutoff_hz=16000,
             rejected_sources=[], in_playlists=True, added="2026-10-01T10:00:00", last_attempt="2026-10-01",
             last_upgrade_check="2026-10-10",
             upgrade={"file": PARKED, "source": "qobuz", "source_id": "q1", "source_format": "flac",
                      "found": "2026-10-10", "alignment": EXACT.to_dict()})
    e.update(kw)
    return e


def _old_file(kind: str, dst: Path, scratch: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    if kind == "lame":
        shutil.copyfile(FIXTURES / "clicks-lame.mp3", dst)
    elif kind == "notag":
        shutil.copyfile(FIXTURES / "clicks-notag.mp3", dst)
    elif kind == "m4a":
        wav = write_wav(scratch / "clicks.wav", clicks(20, 44100), 44100)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "128k",
                        str(dst)], check=True)
    elif kind == "wav48":
        write_wav(dst, clicks(20, 48000), 48000)
    elif kind == "flac96":
        wav = write_wav(scratch / "clicks96.wav", clicks(20, 96000), 96000)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-sample_fmt", "s32",
                        "-bits_per_raw_sample", "24", "-c:a", "flac", str(dst)], check=True)
    elif kind == "aiff":
        write_aiff(dst, clicks(20, 44100))
        write_tags(dst, title="Wrong Title", artists=("Wrong Artist",), album="Old Album", isrc=None, label=None,
                   cover=None, comment="")
    else:
        raise ValueError(kind)


def make_env(tmp_path: Path, monkeypatch, kind: str = "lame", *, rekordbox: bool = True, holds_file: bool = True,
             analysed: bool = True, extra_s: float = 0.0, row: dict | None = None, entry: dict | None = None,
             watch: Path | None = None) -> Env:
    """The library (see the module docstring). `rekordbox=False`: no rekordbox on this Mac; `holds_file=False`: a
    rekordbox library whose track is another file; `analysed=False`: no waveform; `extra_s` moves the waveform off
    the expected value (a timing disagreement); `row` adds djmdContent columns; `entry` overrides the song; `watch`
    is an import folder the song's file sits in."""
    paths = Paths(tmp_path / "music", support=tmp_path / "support")
    old = (entry or {}).get("path", OLD[kind])
    old_file = paths.root / old
    scratch = tmp_path / "scratch"
    scratch.mkdir(exist_ok=True)
    _old_file(kind, old_file, scratch)
    parked = paths.root / PARKED
    parked.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(old_file), "-ar", "44100", "-ac", "2",
                    "-c:a", "pcm_s16be", "-f", "aiff", str(parked)], check=True)
    write_tags(parked, title="Song", artists=("Artist",), album="Album", isrc="ISRC00000001", label="Label",
               cover=None, comment="Qobuz FLAC · verified lossless")
    info = quality.probe(old_file)
    d = {"lame": 1105, "notag": 0, "wav48": 0, "flac96": 0, "aiff": 0}.get(kind)
    if d is None:
        d = round(probe.start_trim(old_file, info.codec, info.sample_rate) * 44100 / info.sample_rate)
    folder = tmp_path / "rb"
    place = None
    if rekordbox:
        held = os.path.abspath(old_file) if holds_file else "/Users/dj/Music/Another.mp3"
        make_master(folder, [{"ID": "1", "path": held, "cues": 3, "playlists": 1, "artist": "Artist", "album": "",
                              "Title": "", **(row or {})}], anlz=True)
        name = os.path.basename(held)
        dat = folder / "share/PIONEER/USBANLZ/000/1/ANLZ0000.DAT"
        make_anlz(dat, [ppth_tag("?/" + name), pqtz_tag(40)])
        if analysed:
            audio, rate = quality.decode_mono(old_file)
            make_anlz(dat.with_suffix(".EXT"), [ppth_tag("?/" + name), pwv3_tag(pwv3_from(audio, rate,
                                                                                         d / 44100 + extra_s))])
        else:
            dat.with_suffix(".EXT").unlink()
        place = Place(folder / "master.db", folder / "share", "override", None)
        monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    else:
        folder.mkdir()
        monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))  # an empty folder: no library
    entry = {k: v for k, v in (entry or {}).items() if k != "path"}
    if watch is None:
        save_library(paths, {TID: song(old, **entry)})
    else:
        save_library(paths, {})
        with db.connect(paths.db_file) as conn:
            db.add_watched_folder(conn, watch, NOW)
        state = load_state(paths)
        state["tracks"][TID] = song(old, **entry)
        save_state(paths, state)
    return Env(paths, place, folder, old, d)


@contextmanager
def session(env: Env, running=never, batch_id: int | None = None):
    with Session.open(env.paths, place=env.place, running=running, items_need_write=lambda v: True,
                      batch_id=batch_id) as s:
        yield s


def run(env: Env, *, compare=exact, running=never, batch: tuple[int, int] | None = None, state: dict | None = None):
    """Same track for the song, in its own session; returns (Result, state)."""
    state = load_state(env.paths) if state is None else state
    with session(env, running, batch[0] if batch else None) as s:
        r = convert.same_track(env.paths, state, TID, dict(state["tracks"][TID]["upgrade"]), session=s,
                               compare=compare, now=lambda: NOW, batch=batch)
    return r, state


def start_batch(env: Env) -> int:
    with db.connect(env.paths.db_file) as conn:
        return db.start_aiff_batch(conn, "upgrade", "user", None, [(TID, "same_track")], NOW)


def batch_row(env: Env, batch_id: int):
    with db.connect(env.paths.db_file) as conn:
        return db.aiff_batch(conn, batch_id)


def file_rows(env: Env) -> list[tuple]:
    with db.connect(env.paths.db_file) as conn:
        return conn.execute("SELECT path, placed_by FROM files ORDER BY path").fetchall()


def make_own(tmp_path: Path, monkeypatch, kind: str = "lame", *, entry: dict | None = None, **kw) -> Env:
    """`make_env` for Convert to AIFF: an own song (`OWN` plus `entry`) whose file row came from the import
    (`placed_by` "import") with the old file's facts stored."""
    env = make_env(tmp_path, monkeypatch, kind, entry={**OWN, **(entry or {})}, **kw)
    path = env.paths.root / load_state(env.paths)["tracks"][TID]["path"]
    with db.connect(env.paths.db_file) as conn:
        conn.execute("UPDATE files SET placed_by = 'import'")
        conn.commit()
        (file_id,) = conn.execute("SELECT id FROM files").fetchone()
        db.set_file_facts(conn, file_id, quality.file_audio(quality.probe(path)))
        conn.commit()
    return env


def run_file(env: Env, *, running=never, batch: tuple[int, int] | None = None, state: dict | None = None):
    """Convert to AIFF for the song, in its own session; returns (Result, state)."""
    state = load_state(env.paths) if state is None else state
    with session(env, running, batch[0] if batch else None) as s:
        r = convert.convert_file(env.paths, state, TID, session=s, now=lambda: NOW, batch=batch)
    return r, state


def start_file_batch(env: Env) -> int:
    with db.connect(env.paths.db_file) as conn:
        return db.start_aiff_batch(conn, "convert", "user", None, [(TID, "convert")], NOW)


def file_facts_row(env: Env) -> tuple:
    """(path, placed_by, file_codec, file_rate, file_bits, file_kbps) of every file row."""
    with db.connect(env.paths.db_file) as conn:
        return tuple(conn.execute("SELECT path, placed_by, file_codec, file_rate, file_bits, file_kbps FROM files "
                                  "ORDER BY path").fetchall())


class PowerOff(BaseException):
    """The Mac went off: nothing after it runs."""


STEP_MARKS = {"backed_up": 1, "placed": 2, "record": 3, "committed_unmarked": 4, "committed": 4, "superseded": 5}
BEFORE_COMMIT = ["rendered", "journaled", "backed_up", "placed", "record"]
AFTER_COMMIT = ["committed_unmarked", "committed", "superseded", "ended"]
UNDO_MARKS = {"restored": 1, "outcome": 2, "committed_unmarked": 3, "committed": 3}


def power_off(monkeypatch, at: str) -> None:
    """Cut the step at `at`: after the render, the journal, a mark (written first, except `committed_unmarked`:
    rekordbox committed, its mark not written), or inside the end."""
    def die(*a, **k):
        raise PowerOff

    for name in ("_drop", "_roll_back", "_settle"):  # the step's own clean-up never runs after a power cut
        monkeypatch.setattr(convert, name, die)
    if at == "rendered":
        monkeypatch.setattr(convert, "journal_op", die)
        return
    if at == "journaled":
        monkeypatch.setattr(Session, "ensure_backup", die)
        return
    if at == "ended":
        monkeypatch.setattr(convert, "end_op", die)
        return
    _cut_at_mark(monkeypatch, STEP_MARKS[at], at != "committed_unmarked")


def power_off_undo(monkeypatch, at: str) -> None:
    """The same for an undo (`journaled`, `restored`, `outcome`, `committed_unmarked`, `committed`, `ended`)."""
    def die(*a, **k):
        raise PowerOff

    if at == "journaled":
        monkeypatch.setattr(convert, "move_path", die)
        monkeypatch.setattr(convert, "end_op", die)
        return
    if at == "ended":
        monkeypatch.setattr(convert, "_end_undo", die)
        return
    _cut_at_mark(monkeypatch, UNDO_MARKS[at], at != "committed_unmarked")


def _cut_at_mark(monkeypatch, number: int, written: bool) -> None:
    real, calls = convert.mark_op, {"n": 0}

    def mark(paths, state, op):
        calls["n"] += 1
        if calls["n"] == number:
            if written:
                real(paths, state, op)
            raise PowerOff
        real(paths, state, op)
    monkeypatch.setattr(convert, "mark_op", mark)


def next_start(env: Env):
    """What the next start does: the clean-up of .tmp/, `recover_pending`, the clean-up again. (messages, state)."""
    state = load_state(env.paths)
    library.clear_tmp(env.paths, state)
    messages = library.recover_pending(env.paths, state)
    library.clear_tmp(env.paths, state)
    return messages, state
