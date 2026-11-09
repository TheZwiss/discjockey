"""Test helpers for `discjockey/rekordbox`: a rekordbox library built from scratch (no real one is ever read).

`make_master(folder, rows)` writes `folder/master.db` the way rekordbox 7 keeps it: SQLCipher 4 with the key sent as
a passphrase, WAL mode, then a clean close (no `-wal`/`-shm` left). The tables carry rekordbox 7's full column lists
(checked 2026-11-07 against a rekordbox 7 library, names and types only), so stage B's whole-row compare uses the
same builder.

A row is a dict of `djmdContent` columns (`ID`, `FileType`, `usn`, …) plus these shortcuts:
- `path`: the file's whole path (`FolderPath`; `FileNameL` is its name, `FileType` follows the extension);
- `artist`, `album`, `label`: names; the lookup row is made (one per name) and its id set;
- `cues`, `playlists`, `history`, `mytags`: how many `djmdCue` (+ one `contentCue`), `djmdSongPlaylist`,
  `djmdSongHistory` and `djmdSongMyTag` rows the track gets;
- `ppth`: what the track's analysis files say in `PPTH` (with `anlz=True`; default `?/<file name>`, rekordbox 7's
  own form), `anlz`: False leaves one track without analysis files.
Lookup rows follow rekordbox 7's scheme (read on a copy 2026-11-08): `SearchStr` NULL, the sync flags 0, `usn` NULL.
`contentFile` rows (one per `.DAT`/`.EXT`/`.2EX`/`.3EX`) have rekordbox's `ID` form (`<folder>_<quoted Path>`),
`Path` like `AnalysisDataPath` and `rb_local_path` the file's whole path; with `make_master(..., anlz=True)` the
files are written under `folder/share` and `Hash`/`Size` are their MD5 and size, as rekordbox keeps them.
`running_after(n)` is a `running()` stub that answers True from its n-th call (rekordbox opening mid-batch).
`dump(db)` and `diff(before, after)` compare two states of a library row by row (the write tests' whole-database check).
`writer(db)` opens the library read-write in WAL mode and keeps `-wal`/`-shm` there: it stands in for a running
rekordbox.

Analysis files: `make_anlz(path, tags)` writes a PMAI file from `ppth_tag`, `pqtz_tag`, `pwv3_tag` and `unknown_tag`;
`pwv3_from(audio, sr, extra_s)` gives the waveform heights rekordbox would show for a file whose rekordbox timeline is
`audio` delayed by `extra_s`; `clicks(seconds, sr)` is a click track to measure on; `write_wav` saves one.

The MP3 fixtures `tests/fixtures/clicks-lame.mp3` (Info/LAME tag: ffmpeg trims 1105 samples) and `clicks-notag.mp3`
(no tag: ffmpeg trims nothing) were made once with an ffmpeg that has libmp3lame (the bundled one hasn't, issue 19):

    PYTHONPATH=.:tests python -c "from pathlib import Path; from rekordbox_helpers import clicks, write_wav; \
        write_wav(Path('clicks.wav'), clicks(30, 44100), 44100)"
    ffmpeg -i clicks.wav -map_metadata -1 -c:a libmp3lame -b:a 64k tests/fixtures/clicks-lame.mp3
    ffmpeg -i clicks.wav -map_metadata -1 -c:a libmp3lame -b:a 64k -write_xing 0 tests/fixtures/clicks-notag.mp3
"""
from __future__ import annotations

import hashlib
import os
import struct
import urllib.parse
import wave
from pathlib import Path

import numpy as np
import sqlcipher3

from discjockey.rekordbox.master import KEYS

_SYNC = (("UUID", "VARCHAR(255)"), ("rb_data_status", "INTEGER"), ("rb_local_data_status", "INTEGER"),
         ("rb_local_deleted", "TINYINT(1)"), ("rb_local_synced", "TINYINT(1)"), ("usn", "BIGINT"),
         ("rb_local_usn", "BIGINT"), ("created_at", "DATETIME"), ("updated_at", "DATETIME"))
_V, _I, _T = "VARCHAR(255)", "INTEGER", "TEXT"


def _cols(spec: str, types: dict[str, str] | None = None, default: str = _V) -> tuple[tuple[str, str], ...]:
    types = types or {}
    return tuple((name, types.get(name, default)) for name in spec.split())


CONTENT = _cols(
    "ID FolderPath FileNameL FileNameS Title ArtistID AlbumID GenreID BPM Length TrackNo BitRate BitDepth Commnt "
    "FileType Rating ReleaseYear RemixerID LabelID OrgArtistID KeyID StockDate ColorID DJPlayCount ImagePath "
    "MasterDBID MasterSongID AnalysisDataPath SearchStr FileSize DiscNo ComposerID Subtitle SampleRate "
    "DisableQuantize Analysed ReleaseDate DateCreated ContentLink Tag ModifiedByRBM HotCueAutoLoad DeliveryControl "
    "DeliveryComment CueUpdated AnalysisUpdated TrackInfoUpdated Lyricist ISRC SamplerTrackInfo SamplerPlayOffset "
    "SamplerGain VideoAssociate LyricStatus ServiceID OrgFolderPath Reserved1 Reserved2 Reserved3 Reserved4 ExtInfo "
    "rb_file_id DeviceID rb_LocalFolderPath SrcID SrcTitle SrcArtistName SrcAlbumName SrcLength",
    {**dict.fromkeys("BPM Length TrackNo BitRate BitDepth FileType Rating ReleaseYear DJPlayCount FileSize DiscNo "
                     "SampleRate DisableQuantize Analysed ContentLink SamplerTrackInfo SamplerPlayOffset LyricStatus "
                     "ServiceID SrcLength".split(), _I),
     **dict.fromkeys("Commnt Reserved1 Reserved2 Reserved3 Reserved4 ExtInfo".split(), _T), "SamplerGain": "FLOAT"},
) + _SYNC

TABLES: dict[str, tuple[tuple[str, str], ...]] = {
    "djmdContent": CONTENT,
    "djmdArtist": _cols("ID Name SearchStr") + _SYNC,
    "djmdAlbum": _cols("ID Name AlbumArtistID ImagePath Compilation SearchStr", {"Compilation": _I}) + _SYNC,
    "djmdLabel": _cols("ID Name") + _SYNC,
    "djmdCue": _cols("ID ContentID InMsec InFrame InMpegFrame InMpegAbs OutMsec OutFrame OutMpegFrame OutMpegAbs Kind "
                     "Color ColorTableIndex ActiveLoop Comment BeatLoopSize CueMicrosec InPointSeekInfo "
                     "OutPointSeekInfo ContentUUID",
                     dict.fromkeys("InMsec InFrame InMpegFrame InMpegAbs OutMsec OutFrame OutMpegFrame OutMpegAbs Kind "
                                   "Color ColorTableIndex ActiveLoop BeatLoopSize CueMicrosec".split(), _I)) + _SYNC,
    "contentCue": _cols("ID ContentID Cues rb_cue_count", {"Cues": _T, "rb_cue_count": _I}) + _SYNC,
    "contentFile": _cols("ID ContentID Path Hash Size rb_local_path rb_insync_hash rb_insync_local_usn "
                         "rb_file_hash_dirty rb_local_file_status rb_in_progress rb_process_type rb_temp_path "
                         "rb_priority rb_file_size_dirty",
                         {"Size": _I, "rb_insync_local_usn": "BIGINT", "rb_file_hash_dirty": _I,
                          "rb_local_file_status": _I, "rb_in_progress": "TINYINT(1)", "rb_process_type": _I,
                          "rb_priority": _I, "rb_file_size_dirty": _I}) + _SYNC,
    "djmdProperty": _cols("DBID DBVersion BaseDBDrive CurrentDBDrive DeviceID Reserved1 Reserved2 Reserved3 Reserved4 "
                          "Reserved5 created_at updated_at",
                          {**dict.fromkeys("Reserved1 Reserved2 Reserved3 Reserved4 Reserved5".split(), _T),
                           "created_at": "DATETIME", "updated_at": "DATETIME"}),
    "agentRegistry": _cols("registry_id id_1 id_2 int_1 int_2 str_1 str_2 date_1 date_2 text_1 text_2 created_at "
                           "updated_at",
                           {"int_1": "BIGINT", "int_2": "BIGINT", "date_1": "DATETIME", "date_2": "DATETIME",
                            "text_1": _T, "text_2": _T, "created_at": "DATETIME", "updated_at": "DATETIME"}),
    "djmdPlaylist": _cols("ID Seq Name ImagePath Attribute ParentID SmartList",
                          {"Seq": _I, "Attribute": _I, "SmartList": _T}) + _SYNC,
    "djmdHistory": _cols("ID Seq Name Attribute ParentID DateCreated", {"Seq": _I, "Attribute": _I}) + _SYNC,
    "djmdMyTag": _cols("ID Seq Name Attribute ParentID", {"Seq": _I, "Attribute": _I}) + _SYNC,
    "djmdSongPlaylist": _cols("ID PlaylistID ContentID TrackNo", {"TrackNo": _I}) + _SYNC,
    "djmdSongHistory": _cols("ID HistoryID ContentID TrackNo", {"TrackNo": _I}) + _SYNC,
    "djmdSongMyTag": _cols("ID MyTagID ContentID TrackNo", {"TrackNo": _I}) + _SYNC,
}

FILE_TYPES = {".mp3": 1, ".m4a": 4, ".flac": 5, ".wav": 11, ".aiff": 12, ".aif": 12}
STAMP = "2026-01-02 03:04:05.678 +00:00"
_SHORTCUTS = ("path", "artist", "album", "label", "cues", "playlists", "history", "mytags", "ppth", "anlz")
ANLZ_EXTS = ("DAT", "EXT", "2EX", "3EX")


def _open(db: Path, key: str):
    con = sqlcipher3.connect(str(db))
    con.execute(f"PRAGMA key = '{key}'")
    return con


def _default(name: str, kind: str):
    if name in ("created_at", "updated_at"):
        return STAMP
    if name in ("usn", "rb_LocalFolderPath", "ArtistID", "AlbumID", "LabelID", "RemixerID", "OrgArtistID",
                "ComposerID", "GenreID", "KeyID", "ColorID"):
        return None
    return 0 if kind in (_I, "BIGINT", "TINYINT(1)", "FLOAT") else ""


def _insert(con, table: str, columns: dict, values: dict) -> None:
    row = {name: values.get(name, _default(name, kind)) for name, kind in TABLES[table] if name in columns}
    con.execute(f"INSERT INTO {table} ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def make_master(folder: Path, rows: list[dict], key: str = KEYS[0], version: str = "6000",
                dbid: str = "1234567890", drop: dict[str, tuple[str, ...] | None] | None = None,
                anlz: bool = False) -> Path:
    """`folder/master.db` holding `rows` (see the module docstring). `drop` leaves columns out of a table, or the
    whole table with None (for the schema guard). `anlz` writes each track's analysis files under `folder/share`."""
    drop = drop or {}
    folder.mkdir(parents=True, exist_ok=True)
    db = folder / "master.db"
    con = _open(db, key)
    con.execute("PRAGMA journal_mode = WAL")
    columns = {}
    for table, spec in TABLES.items():
        if table in drop and drop[table] is None:
            continue
        kept = [(n, k) for n, k in spec if n not in (drop.get(table) or ())]
        columns[table] = {n for n, _ in kept}
        key_col = kept[0][0]
        con.execute(f"CREATE TABLE {table} ({', '.join(f'{n} {k}' + (' PRIMARY KEY' if n == key_col else '') for n, k in kept)})")

    def put(table, values):
        if table in columns:
            _insert(con, table, columns[table], values)

    put("djmdProperty", {"DBID": dbid, "DBVersion": version, "DeviceID": "device-1"})
    put("agentRegistry", {"registry_id": "localUpdateCount", "int_1": len(rows)})
    put("djmdPlaylist", {"ID": "p1", "Name": "Crate", "ParentID": "root"})
    put("djmdHistory", {"ID": "h1", "Name": "Night", "ParentID": "root"})
    put("djmdMyTag", {"ID": "t1", "Name": "Warm-up", "ParentID": "root"})
    lookups: dict[tuple[str, str], str] = {}

    def lookup(table: str, name: str | None) -> str | None:
        if name is None:
            return None
        if (table, name) not in lookups:
            lookups[(table, name)] = f"{table[4:].lower()}-{len(lookups) + 1}"
            put(table, {"ID": lookups[(table, name)], "Name": name, "UUID": f"u-{lookups[(table, name)]}",
                        "SearchStr": None, "rb_local_usn": len(lookups)})
        return lookups[(table, name)]

    serial = 0
    for i, spec in enumerate(rows):
        content_id = str(spec.get("ID", 1000 + i))
        path = spec.get("path", f"/Users/dj/Music/Track {i}.mp3")
        values = {"ID": content_id, "UUID": f"uuid-{content_id}", "FolderPath": path,
                  "FileNameL": os.path.basename(path), "FileType": FILE_TYPES.get(Path(path).suffix.lower(), 1),
                  "Title": f"Title {i}", "rb_local_usn": i + 1,
                  "AnalysisDataPath": f"/PIONEER/USBANLZ/{i:03x}/{content_id}/ANLZ0000.DAT",
                  "ArtistID": lookup("djmdArtist", spec.get("artist")),
                  "AlbumID": lookup("djmdAlbum", spec.get("album")),
                  "LabelID": lookup("djmdLabel", spec.get("label"))}
        values.update({k: v for k, v in spec.items() if k not in _SHORTCUTS})
        put("djmdContent", values)
        if values["AnalysisDataPath"] and spec.get("anlz", True):
            for ext in ANLZ_EXTS:
                serial += 1
                rel = values["AnalysisDataPath"][:-3] + ext
                file = folder / "share" / rel.lstrip("/")
                digest, size = "0" * 32, 100
                if anlz:
                    write_track_anlz(file, ext, spec.get("ppth", "?/" + os.path.basename(path)))
                    data = file.read_bytes()
                    digest, size = hashlib.md5(data).hexdigest(), len(data)
                folder_name = rel.split("/")[3] + rel.split("/")[4]
                put("contentFile", {"ID": f"{folder_name}_{urllib.parse.quote(rel, safe='')}", "ContentID": content_id,
                                    "UUID": f"uf{serial}", "Path": rel, "rb_local_path": str(file), "Hash": digest,
                                    "Size": size, "rb_local_usn": 100 + serial})
        for n in range(spec.get("cues", 0)):
            serial += 1
            put("djmdCue", {"ID": f"c{serial}", "ContentID": content_id, "InMsec": 1000 * n, "Kind": n,
                            "ContentUUID": values["UUID"], "UUID": f"uc{serial}"})
        if spec.get("cues", 0):
            put("contentCue", {"ID": f"cc{content_id}", "ContentID": content_id, "Cues": "[]",
                               "rb_cue_count": spec["cues"], "UUID": f"ucc{content_id}"})
        for table, parent, column in (("djmdSongPlaylist", "p1", "PlaylistID"), ("djmdSongHistory", "h1", "HistoryID"),
                                      ("djmdSongMyTag", "t1", "MyTagID")):
            short = {"djmdSongPlaylist": "playlists", "djmdSongHistory": "history", "djmdSongMyTag": "mytags"}[table]
            for n in range(spec.get(short, 0)):
                serial += 1
                put(table, {"ID": f"s{serial}", column: parent, "ContentID": content_id, "TrackNo": n + 1,
                            "UUID": f"us{serial}"})
    con.commit()
    con.close()
    leftover = [p.name for p in folder.iterdir() if p.name.startswith("master.db-")]
    assert not leftover, f"make_master left {leftover}"
    return db


def dump(db: Path, key: str = KEYS[0]) -> dict[str, list[tuple]]:
    """Every row of every table of `db`, in rowid order, through a keyed read-only immutable open (nothing is left
    beside the file): what a write test compares before and after."""
    from discjockey.rekordbox.master import connect
    con = connect(db, key)
    try:
        tables = [n for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")]
        return {t: [tuple(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY rowid")] for t in tables}
    finally:
        con.close()


def diff(before: dict[str, list[tuple]], after: dict[str, list[tuple]]) -> list[tuple]:
    """What changed between two `dump`s as `(table, id, column, before, after)`, sorted: a changed cell, or for a row
    added / removed `(table, id, "<row>", None, row)` / `(table, id, "<row>", row, None)`. A row's id is its first
    column; the column names are the fixture's `TABLES` (`colN` for a table built with `drop`)."""
    out = []
    for table in sorted(before.keys() | after.keys()):
        names = [n for n, _ in TABLES.get(table, ())]
        old = {r[0]: r for r in before.get(table, [])}
        new = {r[0]: r for r in after.get(table, [])}
        for row_id in sorted(old.keys() | new.keys(), key=str):
            a, b = old.get(row_id), new.get(row_id)
            if a is None or b is None:
                out.append((table, row_id, "<row>", a, b))
                continue
            columns = names if len(names) == len(a) else [f"col{i}" for i in range(len(a))]
            out += [(table, row_id, columns[i], x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
    return out


def running_after(n: int):
    """A `running()` stub: False for its first n - 1 calls, True from the n-th on (rekordbox opening mid-batch)."""
    calls = {"n": 0}

    def running() -> bool:
        calls["n"] += 1
        return calls["n"] >= n
    running.calls = calls
    return running


def write_track_anlz(file: Path, ext: str, ppth: str) -> Path:
    """One analysis file as rekordbox 7 writes them for a track: `.DAT` (path, an unknown tag, a grid), `.EXT` (path,
    waveform, an unknown tag), `.2EX` (path, an unknown tag), `.3EX` (no PMAI file: a msgpack blob without a path)."""
    if ext == "3EX":
        file.parent.mkdir(parents=True, exist_ok=True)
        file.write_bytes(b"\x81\xa9embedding" + bytes(range(64)))
        return file
    tags = {"DAT": [ppth_tag(ppth), unknown_tag(), pqtz_tag(8)],
            "EXT": [ppth_tag(ppth), pwv3_tag(np.arange(300, dtype=np.uint8) % 32), unknown_tag()],
            "2EX": [ppth_tag(ppth), unknown_tag()]}[ext]
    return make_anlz(file, tags)


def writer(db: Path, key: str = KEYS[0]):
    """A read-write connection standing in for a running rekordbox: WAL mode, no automatic checkpoint, so `-wal` and
    `-shm` stay beside the library (with what it commits) until it closes."""
    con = _open(db, key)
    con.execute("PRAGMA journal_mode = WAL")
    con.execute("PRAGMA wal_autocheckpoint = 0")
    return con


def snapshot(folder: Path) -> list[tuple[str, int, int]]:
    """Every file under `folder` with its size and mtime: equal before and after means nothing was left or touched."""
    return sorted((str(p.relative_to(folder)), p.stat().st_size, p.stat().st_mtime_ns)
                  for p in folder.rglob("*") if p.is_file())


# --- analysis files (ANLZ) and rekordbox's waveform ---

def _tag(fourcc: bytes, fields: tuple[int, ...], body: bytes) -> bytes:
    header_len = 12 + 4 * len(fields)
    return struct.pack(f">4sII{len(fields)}I", fourcc, header_len, header_len + len(body), *fields) + body


def ppth_tag(path: str) -> bytes:
    """`PPTH`: the audio file's path, UTF-16BE with a trailing NUL."""
    body = (path + "\0").encode("utf-16-be")
    return _tag(b"PPTH", (len(body),), body)


def pqtz_tag(beats: int, bpm: float = 120.0) -> bytes:
    """`PQTZ`: a grid of `beats` beats at `bpm` from 0 ms."""
    body = b"".join(struct.pack(">HHI", i % 4 + 1, round(bpm * 100), round(i * 60000 / bpm)) for i in range(beats))
    return _tag(b"PQTZ", (0, 0x00080000, beats), body)


def pwv3_tag(heights: np.ndarray, whiteness: bool = True) -> bytes:
    """`PWV3`: one byte per column; `whiteness` fills the top three bits as rekordbox does (the reader masks them)."""
    data = np.asarray(heights, dtype=np.uint8) & 0x1F
    if whiteness:
        data = data | (np.arange(len(data), dtype=np.uint8) % 8 << 5).astype(np.uint8)
    return _tag(b"PWV3", (1, len(data), 0x00960000), data.tobytes())


def unknown_tag() -> bytes:
    """A tag the reader doesn't know (shaped like rekordbox's `PVBR`), to be skipped by its length."""
    return _tag(b"PVB2", (0,), bytes(range(256)) * 2)


def make_anlz(path: Path, tags: list[bytes]) -> Path:
    """A PMAI file at `path` holding `tags` (from the `*_tag` builders), with rekordbox 7's 28-byte file header."""
    body = b"".join(tags)
    header = struct.pack(">4sII", b"PMAI", 28, 28 + len(body)) + struct.pack(">IIII", 1, 0x00010000, 0x00010000, 0)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(header + body)
    return path


def pwv3_from(audio: np.ndarray, sr: int, extra_s: float, seed: int = 0) -> np.ndarray:
    """Waveform heights as rekordbox shows them for a file whose rekordbox timeline is ffmpeg's decode `audio` delayed
    by `extra_s` (seconds; negative: earlier): the peak per 1/150 s column, scaled to 0–31, with ±1 of noise."""
    x = np.abs(np.asarray(audio, dtype=np.float64))
    shift = int(round(extra_s * sr))
    x = np.concatenate([np.zeros(shift), x]) if shift >= 0 else x[-shift:]
    col = sr / 150
    starts = (np.arange(int(len(x) // col)) * col).astype(np.int64)
    peaks = np.maximum.reduceat(x, starts)
    noise = np.random.default_rng(seed).integers(-1, 2, len(peaks))
    return np.clip(np.round(peaks / max(peaks.max(), 1e-9) * 31) + noise, 0, 31).astype(np.uint8)


def clicks(seconds: float, sr: int, bpm: float = 120, seed: int = 1) -> np.ndarray:
    """A click track: a quiet noise bed and one click per beat from 0.5 s, each a decaying noise burst of its own
    length and level, a few ms off the beat (so its onset falls at a different place in rekordbox's 1/150 s columns
    each time), so a waveform comparison has one clear, sharp best shift."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    x = 0.01 * rng.standard_normal(n)
    step = 60 / bpm
    for t in np.arange(0.5, seconds - 0.1, step):
        length = int(rng.integers(sr // 400, sr // 40))
        start = int((t + rng.uniform(-0.02, 0.02)) * sr)
        burst = rng.standard_normal(length) * np.exp(-np.arange(length) / (length / 4)) * rng.uniform(0.3, 0.9)
        x[start:start + length] += burst[:max(0, n - start)]
    return np.clip(x, -1, 1).astype(np.float32)


def write_wav(path: Path, audio: np.ndarray, sr: int) -> Path:
    """`audio` (mono float) as a 16-bit WAV."""
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes((np.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())
    return path


# --- a Discjockey library for the rekordbox commands ---

def own_entry(path: str | None = "Library/Mine/old name.mp3", **kw) -> dict:
    """A song record of the user's own file (source "manual") as `library.save_state` takes it; `kw` overrides."""
    from discjockey.planner import ENTRY_KEYS
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=30000, folder="Mine", path=path,
             status="lossless", source="manual", source_id=None, source_format="mp3", cutoff_hz=None,
             rejected_sources=[], in_playlists=False, added="2026-10-01T10:00:00")
    e.update(kw)
    return e


def save_library(paths, tracks: dict[str, dict]) -> None:
    """The records of `paths`' library: exactly `tracks` (their files must exist first)."""
    from discjockey.library import empty_state, save_state
    state = empty_state()
    state["tracks"].update(tracks)
    save_state(paths, state)
