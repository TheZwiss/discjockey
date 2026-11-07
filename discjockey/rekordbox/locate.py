"""Where rekordbox keeps its library on this Mac (design rekordbox-repoint §5.1, plan stage A §1.3).

`locate()` answers a `Place`: the library file `master.db`, the `share` folder that holds the analysis files
(`AnalysisDataPath` is `/PIONEER/USBANLZ/…` under it), where the answer came from, and the newest installed
rekordbox's version (shown and logged, never a guard). No `master.db` means no rekordbox library: rekordbox 5's
`datafile.edb` counts as none, because only rekordbox 6 and 7 keep `master.db`.

The order:
1. `DISCJOCKEY_REKORDBOX=<folder>` replaces everything: `<folder>/master.db` and `<folder>/share`, no version. Tests
   set it for every test (`tests/conftest.py`), so no test reads a real rekordbox.
2. rekordboxAgent's `options.json` (`{"options": [[name, value], ...]}`): `db-path` names the library,
   `analysis-data-root-path` the share folder (when it is missing, `share` beside the library).
3. rekordbox's default place, `~/Library/Pioneer/rekordbox/master.db` and its `share`.
An options file that can't be read, has another shape or names a library that isn't there falls through to 3.
"""
from __future__ import annotations

import json
import os
import plistlib
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

ENV = "DISCJOCKEY_REKORDBOX"
DB_NAME = "master.db"
OPTIONS = Path("Library/Application Support/Pioneer/rekordboxAgent/storage/options.json")
DEFAULT_DIR = Path("Library/Pioneer/rekordbox")
APPLICATIONS = Path("/Applications")

Source = Literal["options", "default", "override"]


@dataclass(frozen=True)
class Place:
    db: Path
    share: Path
    source: Source
    app_version: str | None


def locate(env: Mapping[str, str] = os.environ, home: Path | None = None,
           apps: Path = APPLICATIONS) -> Place | None:
    """The rekordbox library this Mac uses, or None when there is none. `home` defaults to the user's home and is
    only looked at without the override; `apps` is where the rekordbox apps are installed."""
    override = env.get(ENV)
    if override:
        folder = Path(override)
        db = folder / DB_NAME
        return Place(db, folder / "share", "override", None) if db.is_file() else None
    home = Path.home() if home is None else home
    found = _from_options(home / OPTIONS)
    if found is not None:
        db, share = found
        return Place(db, share, "options", app_version(apps))
    db = home / DEFAULT_DIR / DB_NAME
    if db.is_file():
        return Place(db, db.parent / "share", "default", app_version(apps))
    return None


def _from_options(path: Path) -> tuple[Path, Path] | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        pairs = {str(name): value for name, value in data["options"]}
    except (OSError, ValueError, TypeError, KeyError):
        return None
    db_path = pairs.get("db-path")
    if not isinstance(db_path, str) or not db_path:
        return None
    db = Path(db_path)
    if db.name != DB_NAME or not db.is_file():
        return None
    share = pairs.get("analysis-data-root-path")
    return db, Path(share) if isinstance(share, str) and share else db.parent / "share"


def _version_key(version: str) -> tuple[int, ...]:
    return tuple(int(n) for n in re.findall(r"\d+", version))


def app_version(apps: Path = APPLICATIONS) -> str | None:
    """The newest `<apps>/rekordbox */rekordbox.app`'s `CFBundleShortVersionString`, or None."""
    versions = []
    try:
        folders = list(apps.glob("rekordbox */rekordbox.app/Contents/Info.plist"))
    except OSError:
        return None
    for plist in folders:
        try:
            with plist.open("rb") as f:
                version = plistlib.load(f).get("CFBundleShortVersionString")
        except (OSError, plistlib.InvalidFileException, ValueError, AttributeError):
            continue
        if isinstance(version, str) and _version_key(version):
            versions.append(version)
    return max(versions, key=_version_key, default=None)
