"""Test helpers for `discjockey/rekordbox`: a rekordbox library built from scratch (no real one is ever read).

`make_master(folder, rows)` writes `folder/master.db` the way rekordbox 7 keeps it: SQLCipher 4 with the key sent as
a passphrase, WAL mode, then a clean close (no `-wal`/`-shm` left). The tables carry rekordbox 7's full column lists
(checked 2026-11-07 against a rekordbox 7 library, names and types only), so stage B's whole-row compare uses the
same builder.

A row is a dict of `djmdContent` columns (`ID`, `FileType`, `usn`, …) plus these shortcuts:
- `path`: the file's whole path (`FolderPath`; `FileNameL` is its name, `FileType` follows the extension);
- `artist`, `album`, `label`: names; the lookup row is made (one per name) and its id set;
- `cues`, `playlists`, `history`, `mytags`: how many `djmdCue` (+ one `contentCue`), `djmdSongPlaylist`,
  `djmdSongHistory` and `djmdSongMyTag` rows the track gets.
`writer(db)` opens the library read-write in WAL mode and keeps `-wal`/`-shm` there: it stands in for a running
rekordbox.
"""
from __future__ import annotations

import os
from pathlib import Path

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
_SHORTCUTS = ("path", "artist", "album", "label", "cues", "playlists", "history", "mytags")


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
                dbid: str = "1234567890", drop: dict[str, tuple[str, ...] | None] | None = None) -> Path:
    """`folder/master.db` holding `rows` (see the module docstring). `drop` leaves columns out of a table, or the
    whole table with None (for the schema guard)."""
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
            put(table, {"ID": lookups[(table, name)], "Name": name, "UUID": f"u-{lookups[(table, name)]}"})
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
        if values["AnalysisDataPath"]:
            for ext in ("DAT", "EXT"):
                serial += 1
                put("contentFile", {"ID": f"f{serial}", "ContentID": content_id, "UUID": f"uf{serial}",
                                    "Path": values["AnalysisDataPath"][:-3] + ext, "Hash": "0" * 32, "Size": 100})
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
