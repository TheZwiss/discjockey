"""The colleague's web browsers, read from their files (spec settings-setup §6.1): which are installed, the default
one, their profiles, and which profiles hold a YouTube or SoundCloud login. Only cookie *names* and hosts are read
(from a copy of the database, so a running browser's lock doesn't matter); nothing is decrypted, so macOS never asks
for a password, and no cookie value leaves this module. Safari's file needs Full Disk Access ("no_access")."""
from __future__ import annotations

import configparser
import json
import plistlib
import sqlite3
import tempfile
from pathlib import Path

from .accounts import BROWSERS, LOGIN_COOKIES

APPS = {"safari": "Safari.app", "chrome": "Google Chrome.app", "firefox": "Firefox.app",
        "brave": "Brave Browser.app", "edge": "Microsoft Edge.app"}
BUNDLE_IDS = {"com.apple.safari": "safari", "com.google.chrome": "chrome", "org.mozilla.firefox": "firefox",
              "com.brave.browser": "brave", "com.microsoft.edgemac": "edge"}
CHROMIUM = {"chrome": "Library/Application Support/Google/Chrome",
            "brave": "Library/Application Support/BraveSoftware/Brave-Browser",
            "edge": "Library/Application Support/Microsoft Edge"}
FIREFOX = "Library/Application Support/Firefox"
SAFARI_COOKIES = ("Library/Containers/com.apple.Safari/Data/Library/Cookies/Cookies.binarycookies",
                  "Library/Cookies/Cookies.binarycookies")
LAUNCH_SERVICES = "Library/Preferences/com.apple.LaunchServices/com.apple.launchservices.secure.plist"

LoginScan = dict  # {"readable": bool, "problem": None | "no_access" | "locked", "profiles": [str | None]}


def installed(home: Path, apps: tuple[Path, ...] = (Path("/Applications"),)) -> list[str]:
    """Browser ids (BROWSERS order) whose app is in `apps` or in the user's own Applications folder."""
    where = (*apps, home / "Applications")
    return [b for b in BROWSERS if any((d / APPS[b]).exists() for d in where)]


def default_browser(home: Path) -> str | None:
    """The browser that opens https links. Safari when LaunchServices names no handler (macOS's own default); None
    when the file can't be read or the handler is not one of ours."""
    try:
        handlers = plistlib.loads((home / LAUNCH_SERVICES).read_bytes()).get("LSHandlers", [])
    except (OSError, ValueError, AttributeError):  # plistlib's parse errors are ValueError subclasses
        return None
    for scheme in ("https", "http"):
        for h in handlers:
            if isinstance(h, dict) and str(h.get("LSHandlerURLScheme", "")).lower() == scheme:
                return BUNDLE_IDS.get(str(h.get("LSHandlerRoleAll", "")).lower())
    return "safari"


def _firefox_profiles(home: Path) -> list[tuple[str, str, Path]]:
    """[(id, name, folder)] from profiles.ini. A relative profile's id is its folder name; an absolute one keeps its
    full path (yt-dlp accepts both)."""
    root = home / FIREFOX
    ini = configparser.ConfigParser(interpolation=None)
    try:
        ini.read_string((root / "profiles.ini").read_text(encoding="utf-8"))
    except (OSError, ValueError, configparser.Error):
        return []
    out = []
    for sec in ini.sections():
        if not (sec.startswith("Profile") and ini.has_option(sec, "Path")):
            continue
        path = ini.get(sec, "Path")
        if ini.get(sec, "IsRelative", fallback="1").strip() == "0":
            out.append((path, ini.get(sec, "Name", fallback=Path(path).name), Path(path)))
        else:
            out.append((Path(path).name, ini.get(sec, "Name", fallback=Path(path).name), root / path))
    return out


def profiles(browser: str, home: Path) -> list[dict]:
    """[{"id": yt-dlp's profile argument (None: the browser's default), "name": what the colleague knows it as}]."""
    if browser in CHROMIUM:
        root = home / CHROMIUM[browser]
        try:
            cache = json.loads((root / "Local State").read_text(encoding="utf-8"))["profile"]["info_cache"]
            found = [{"id": k, "name": str(v.get("name") or k)} for k, v in cache.items() if (root / k).is_dir()]
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            found = []
        if not found and (root / "Default").is_dir():
            found = [{"id": "Default", "name": "Default"}]
        return sorted(found, key=lambda p: (p["id"] != "Default", p["id"]))
    if browser == "firefox":
        return [{"id": pid, "name": name} for pid, name, _ in _firefox_profiles(home)]
    if browser == "safari":
        return [{"id": None, "name": "Safari"}]
    return []


def _read_bytes(path: Path) -> bytes:
    return path.read_bytes()


def _names_from_sqlite(db: Path, query: str) -> list[tuple[str, str]]:
    """(host, name) rows from a copy of the database and its -wal/-shm files (the browser may hold a lock on the
    original, and its newest cookies may still be in the WAL)."""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "db"
        for suffix in ("", "-wal", "-shm"):
            src = db.with_name(db.name + suffix)
            if suffix == "" or src.exists():
                Path(str(copy) + suffix).write_bytes(_read_bytes(src))
        con = sqlite3.connect(copy)
        try:
            return [(str(h), str(n)) for h, n in con.execute(query)]
        finally:
            con.close()


def _safari_names(data: bytes) -> list[tuple[str, str]]:
    from yt_dlp.cookies import parse_safari_cookies
    try:
        return [(c.domain, c.name) for c in parse_safari_cookies(data)]
    except Exception as e:  # yt-dlp raises its own error types for a file it can't parse
        raise ValueError(f"unreadable Safari cookies: {e}") from e


def _safari_file(home: Path) -> bytes | None:
    """Safari's cookie file, read directly: without Full Disk Access macOS refuses the read (PermissionError), and an
    exists() check would only say "not there" (it swallows that error on newer Pythons)."""
    for rel in SAFARI_COOKIES:
        try:
            return _read_bytes(home / rel)
        except (FileNotFoundError, NotADirectoryError):
            continue
    return None


def _has_login(service: str, rows: list[tuple[str, str]]) -> bool:
    domain, names = LOGIN_COOKIES[service]
    domain = domain.lstrip(".")
    return any(n in names and (h.lstrip(".") == domain or h.endswith("." + domain)) for h, n in rows)


def _newest(files: list[Path]) -> Path | None:
    found = [f for f in files if f.exists()]
    return max(found, key=lambda f: f.stat().st_mtime) if found else None


def logins(service: str, browser: str, home: Path) -> LoginScan:
    """Which of the browser's profiles hold a login to `service` (YouTube or SoundCloud); a profile id of None is the
    browser's only/default one (Safari)."""
    found: list[str | None] = []
    try:
        if browser in CHROMIUM:
            for p in profiles(browser, home):
                base = home / CHROMIUM[browser] / p["id"]
                db = _newest([base / "Network" / "Cookies", base / "Cookies"])
                if db and _has_login(service, _names_from_sqlite(db, "SELECT host_key, name FROM cookies")):
                    found.append(p["id"])
        elif browser == "firefox":
            for pid, _, folder in _firefox_profiles(home):
                db = folder / "cookies.sqlite"
                if db.exists() and _has_login(service, _names_from_sqlite(db, "SELECT host, name FROM moz_cookies")):
                    found.append(pid)
        elif browser == "safari":
            data = _safari_file(home)
            if data is not None and _has_login(service, _safari_names(data)):
                found.append(None)
    except PermissionError:
        return {"readable": False, "problem": "no_access", "profiles": []}
    except (OSError, sqlite3.Error, ValueError):
        return {"readable": False, "problem": "locked", "profiles": []}
    return {"readable": True, "problem": None, "profiles": found}
