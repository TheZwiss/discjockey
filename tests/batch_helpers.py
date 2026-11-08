"""A library for the batch tests and the command tests: songs of several kinds, each with a parked lossless upgrade of
the same edit, and a fixture rekordbox that holds them (plan stage B §5.1). Built in tmp_path; nothing real is read."""
from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from audio_helpers import needs_ffmpeg
from convert_helpers import EXACT, FIXTURES, song
from discjockey import db, library, quality
from discjockey.align import Alignment
from discjockey.audio import write_tags
from discjockey.library import Paths, load_state
from discjockey.rekordbox import master
from discjockey.rekordbox.locate import Place
from rekordbox_helpers import (
    clicks, dump, make_anlz, make_master, ppth_tag, pqtz_tag, pwv3_from, pwv3_tag, save_library, write_wav,
)

__all__ = ["D", "DIFFERENT", "Lib", "PowerOff", "make_lib", "needs_ffmpeg", "use"]

D = 1105  # rekordbox's offset for clicks-lame.mp3, 44.1 kHz samples
DIFFERENT = Alignment("different", text="doesn't line up")


class PowerOff(BaseException):
    """The process dies here: nothing after it runs."""


@dataclass
class Lib:
    paths: Paths
    place: Place
    folder: Path
    tracks: list[str]     # song keys, in the order of `kinds`
    olds: list[str]       # their current files (music-folder relative)

    def entry(self, i: int) -> dict:
        return load_state(self.paths)["tracks"][self.tracks[i]]

    def row(self, i: int) -> dict:
        with master.open_read(self.place, False) as m:
            cur = m.con.execute("SELECT * FROM djmdContent WHERE ID = ?", (str(i + 1),))
            return dict(zip([c[0] for c in cur.description], cur.fetchone()))

    def dump(self):
        return dump(self.place.db)

    def music(self) -> dict[str, bytes]:
        root = self.paths.root
        return {p.relative_to(root).as_posix(): p.read_bytes() for p in sorted(root.rglob("*"))
                if p.is_file() and ".discjockey" not in p.relative_to(root).parts}

    def batch(self, batch_id: int):
        with db.connect(self.paths.db_file) as conn:
            return db.aiff_batch(conn, batch_id)


def make_lib(tmp_path: Path, monkeypatch, kinds: list[str]) -> Lib:
    """One song per kind, all parked with a lossless upgrade of the same edit (L = 0):
    `mp3` (rekordbox holds it, analysed), `mp3_plain` (rekordbox holds it, not analysed), `mp3_free` (rekordbox
    doesn't hold it), `aiff` (an AIFF rekordbox holds), `stale` (the stored alignment is a different edit)."""
    paths = Paths(tmp_path / "music", support=tmp_path / "support")
    folder = tmp_path / "rb"
    wav = write_wav(tmp_path / "clicks.wav", clicks(6, 44100), 44100)
    rows, library_, olds, analysed = [], {}, [], []
    for i, kind in enumerate(kinds):
        tid = f"t{i}aaaaaaa"
        if kind in ("mp3", "mp3_plain", "mp3_free", "stale"):
            old = f"Library/A/Old {i}.mp3"
            (paths.root / old).parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(FIXTURES / "clicks-lame.mp3", paths.root / old)
        else:
            old = f"Library/A/Artist - Song {i}.aiff"
            (paths.root / old).parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(wav), "-c:a", "pcm_s16be", "-f",
                            "aiff", str(paths.root / old)], check=True)
            write_tags(paths.root / old, title=f"Song {i}", artists=("Artist",), album="", isrc=None, label=None,
                       cover=None, comment="")
        parked = f"Upgrades ready/A/Artist - Song {i}.aiff"
        (paths.root / parked).parent.mkdir(parents=True, exist_ok=True)
        subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(paths.root / old), "-ar", "44100", "-ac",
                        "2", "-c:a", "pcm_s16be", "-f", "aiff", str(paths.root / parked)], check=True)
        write_tags(paths.root / parked, title=f"Song {i}", artists=("Artist",), album="Album", isrc="ISRC00000001",
                   label="Label", cover=None, comment="Qobuz FLAC · verified lossless")
        alignment = DIFFERENT if kind == "stale" else EXACT
        library_[tid] = song(old, title=f"Song {i}",
                             upgrade={"file": parked, "source": "qobuz", "source_id": f"q{i}",
                                      "source_format": "flac", "found": "2026-10-10",
                                      "alignment": alignment.to_dict()})
        olds.append(old)
        if kind != "mp3_free":
            rows.append({"ID": str(i + 1), "path": os.path.abspath(paths.root / old), "cues": 2, "artist": "Artist",
                         "album": "", "Title": f"Song {i}" if kind == "aiff" else ""})
            if kind in ("mp3", "mp3_plain", "stale"):
                analysed.append((i, kind))
    make_master(folder, rows, anlz=True)
    for i, kind in analysed:
        name = os.path.basename(paths.root / olds[i])
        dat = folder / f"share/PIONEER/USBANLZ/{rows.index(next(r for r in rows if r['ID'] == str(i + 1))):03x}" \
                       f"/{i + 1}/ANLZ0000.DAT"
        make_anlz(dat, [ppth_tag("?/" + name), pqtz_tag(40)])
        if kind == "mp3_plain":
            dat.with_suffix(".EXT").unlink()
        else:
            audio, rate = quality.decode_mono(paths.root / olds[i])
            make_anlz(dat.with_suffix(".EXT"), [ppth_tag("?/" + name), pwv3_tag(pwv3_from(audio, rate, D / 44100))])
    save_library(paths, library_)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    return Lib(paths, Place(folder / "master.db", folder / "share", "override", None), folder, list(library_), olds)


def use(lib: Lib, monkeypatch) -> Paths:
    """The library as the console finds it: DISCJOCKEY_SUPPORT at its support folder, whose config.json names the
    music folder (`discjockey ...` through cli.main then resolves exactly these Paths)."""
    monkeypatch.setenv(library.SUPPORT_ENV, str(lib.paths.support))
    library.write_music_folder(lib.paths.support, lib.paths.root)
    return lib.paths
