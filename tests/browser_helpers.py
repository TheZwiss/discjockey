"""Fake browser folders for the browser tests: Chrome cookies and Local State, Firefox profiles, and a SQLite file
whose newest rows are only in its WAL. Everything is built under a `home` the test passes in (a tmp_path)."""
from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

CHROME = "Library/Application Support/Google/Chrome"
FIREFOX = "Library/Application Support/Firefox"
SAFARI = "Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies"


def chrome_cookies(home: Path, profile: str, rows, network: bool = False) -> Path:
    """A Chrome profile's cookie database ((host, name) rows; the value is a dummy). Returns its path."""
    d = home / CHROME / profile / ("Network" if network else "")
    d.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(d / "Cookies")
    db.execute("CREATE TABLE cookies (host_key TEXT, name TEXT, encrypted_value BLOB)")
    db.executemany("INSERT INTO cookies VALUES (?, ?, x'00')", rows)
    db.commit()
    db.close()
    return d / "Cookies"


def local_state(home: Path, names: dict) -> None:
    """Chrome's Local State with the given {profile folder: profile name}."""
    (home / CHROME).mkdir(parents=True, exist_ok=True)
    (home / CHROME / "Local State").write_text(json.dumps({"profile": {"info_cache": {
        k: {"name": v} for k, v in names.items()}}}))


def firefox_cookies(db_path: Path, rows) -> Path:
    """A Firefox cookies.sqlite ((host, name) rows; the value is a dummy)."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(db_path)
    db.execute("CREATE TABLE moz_cookies (host TEXT, name TEXT, value TEXT)")
    db.executemany("INSERT INTO moz_cookies VALUES (?, ?, 'x')", rows)
    db.commit()
    db.close()
    return db_path


def firefox_profile(home: Path, name: str, path: str, rows=(), relative: bool = True) -> Path:
    """Add a profile to Firefox's profiles.ini. A relative `path` lives under the Firefox folder, an absolute one
    wherever it points. With rows, the folder gets a cookies.sqlite. Returns the profile folder."""
    root = home / FIREFOX
    root.mkdir(parents=True, exist_ok=True)
    ini = root / "profiles.ini"
    text = ini.read_text() if ini.exists() else ""
    n = text.count("[Profile")
    ini.write_text(text + f"[Profile{n}]\nName={name}\nIsRelative={1 if relative else 0}\nPath={path}\n\n")
    folder = root / path if relative else Path(path)
    folder.mkdir(parents=True, exist_ok=True)
    if rows:
        firefox_cookies(folder / "cookies.sqlite", rows)
    return folder


def wal_only_firefox_db(db_path: Path, rows) -> sqlite3.Connection:
    """A Firefox cookies.sqlite in WAL mode whose `rows` exist only in the -wal file (checkpointing is off). Keep
    the returned connection open until the files are copied, then close it."""
    firefox_cookies(db_path, [])
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA wal_autocheckpoint=0")
    con.executemany("INSERT INTO moz_cookies VALUES (?, ?, 'x')", rows)
    con.commit()
    return con


def copy_db_files(src: Path, dst_dir: Path) -> None:
    """Copy a database with its -wal and -shm files (those that exist) into `dst_dir`."""
    dst_dir.mkdir(parents=True, exist_ok=True)
    for suffix in ("", "-wal", "-shm"):
        f = src.with_name(src.name + suffix)
        if f.exists():
            shutil.copyfile(f, dst_dir / f.name)
