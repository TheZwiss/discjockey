"""The update notice (spec public-release §8): is a newer Discjockey out? Asks GitHub for the public repo's latest
release at most once a day (the answer is cached in <support>/cache/app_update.json) and compares it with the running
version. No answer says nothing at all: offline, a rate limit, a server error (logged at INFO, never as an error;
asked again at the next check). A repo without releases (404) is an answer: nothing newer. So are a draft, a
prerelease, a tag that isn't a plain version and an answer that isn't a release: GitHub never names them as the
latest, and if it does, nothing is offered. The cache keeps the release, not the comparison, so a newly installed
version stops the notice at once. Nothing is downloaded or installed; the window shows the result
(hub/api.py app_update and the AppUpdate event)."""
from __future__ import annotations

import json
import logging
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable

from . import __version__
from .library import write_json_atomic
from .tool_updates import HttpStatus

REPO = "TheZwiss/discjockey"
LATEST_URL = f"https://api.github.com/repos/{REPO}/releases/latest"
RELEASE_PAGE = f"https://github.com/{REPO}/releases/tag/"
CACHE_NAME = "app_update.json"
MAX_AGE = timedelta(days=1)
TIMEOUT_S = 15
_VERSION = re.compile(r"v?([0-9]{1,6})\.([0-9]{1,6})\.([0-9]{1,6})")
log = logging.getLogger(__name__)


def parse_version(text: object) -> tuple[int, int, int] | None:
    """(1, 1, 0) for "1.1.0" or "v1.1.0"; None for anything else ("1.1.0-beta.1", "1.1", a name, not a string)."""
    m = _VERSION.fullmatch(text) if isinstance(text, str) else None
    return (int(m[1]), int(m[2]), int(m[3])) if m else None


def is_newer(latest: str, current: str) -> bool:
    a, b = parse_version(latest), parse_version(current)
    return a is not None and b is not None and a > b


@dataclass(frozen=True)
class Release:
    version: str  # "1.1.0", without the "v"
    url: str  # its page: RELEASE_PAGE + the tag


class NoAnswer(Exception):
    """Offline, a rate limit, a server error: say nothing, ask again at the next check."""


def fetch_latest(url: str) -> bytes:
    """One unauthenticated GET to GitHub's API (60 an hour per address; this asks about once a day). conftest
    replaces it: no network in tests."""
    import requests
    response = requests.get(url, timeout=TIMEOUT_S, headers={
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": f"Discjockey/{__version__}"})
    if response.status_code >= 400:
        raise HttpStatus(response.status_code, url)
    return response.content


def read_release(data: bytes) -> Release | None:
    """GitHub's answer -> the release it offers, or None (a draft, a prerelease, a tag that isn't a plain version,
    anything that isn't a release). The page is built from the checked tag, so it can only be the release page."""
    try:
        info = json.loads(data)
    except (ValueError, RecursionError):  # ValueError includes UnicodeDecodeError; RecursionError is absurdly deep JSON
        return None
    if not isinstance(info, dict) or info.get("draft") or info.get("prerelease"):
        return None
    tag = info.get("tag_name")
    version = parse_version(tag)
    if version is None:
        return None
    return Release(".".join(map(str, version)), RELEASE_PAGE + tag)


def ask(fetch: Callable[[str], bytes]) -> Release | None:
    """The latest release from GitHub; None when there is none (404: no release, or no public repo yet).
    NoAnswer when GitHub couldn't be asked."""
    try:
        data = fetch(LATEST_URL)
    except HttpStatus as e:
        if e.status == 404:
            return None
        raise NoAnswer(f"HTTP {e.status}") from None  # 403/429: the rate limit; 5xx: GitHub's trouble
    except Exception as e:  # requests' connection errors and timeouts, and anything else on the way
        raise NoAnswer(type(e).__name__) from None
    return read_release(data)


def load_cached(path: Path, now: datetime) -> tuple[bool, Release | None]:
    """(True, the release or None) for an answer younger than a day; (False, None) when there is none, it is older,
    dated in the future (the clock was changed), without a timezone, unreadable, or names a page that isn't a
    release page."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        age = now - datetime.fromisoformat(data["checked_at"])
    except (OSError, ValueError, KeyError, TypeError, RecursionError):
        return False, None
    if not timedelta(0) <= age < MAX_AGE:
        return False, None
    version, url = data.get("version"), data.get("url")
    if version is None:
        return True, None
    # The link must be the release page of exactly the cached version: RELEASE_PAGE + a plain tag (no ".." or more
    # path).
    if (parse_version(version) is None or not isinstance(url, str) or not url.startswith(RELEASE_PAGE)
            or parse_version(url[len(RELEASE_PAGE):]) != parse_version(version)):
        return False, None
    return True, Release(version, url)


def save_cached(path: Path, release: Release | None, now: datetime) -> None:
    """Never fails: a cache that can't be written only means asking again at the next check."""
    data = {"checked_at": now.isoformat(), "version": release.version if release else None,
            "url": release.url if release else None}
    try:
        write_json_atomic(path, data, parents=True, indent=2)
    except OSError as e:
        log.info("update check: couldn't keep the answer: %s", e)


def latest(cache_file: Path, *, fetch: Callable[[str], bytes], now: datetime) -> Release | None:
    """The cached answer while it is younger than a day, else GitHub's (then cached). NoAnswer passes through."""
    fresh, release = load_cached(cache_file, now)
    if fresh:
        return release
    release = ask(fetch)
    save_cached(cache_file, release, now)
    return release


def unknown(current: str) -> dict:
    return {"state": "unknown", "current": current, "latest": None, "url": None}


def status_of(current: str, release: Release | None) -> dict:
    """What the window shows. A running version that isn't a plain one (a developer's) is never compared."""
    if parse_version(current) is None:
        return unknown(current)
    if release is not None and is_newer(release.version, current):
        return {"state": "available", "current": current, "latest": release.version, "url": release.url}
    return {"state": "up_to_date", "current": current, "latest": None, "url": None}


class Checker:
    """What the window shows, kept in memory: status() never touches the network; check() brings it up to date
    (the cache, or GitHub once the cache is a day old) and says whether it changed. No answer keeps the last
    status. Thread-safe."""

    def __init__(self, cache_file: Path, *, current: str = __version__,
                 fetch: Callable[[str], bytes] | None = None, now: Callable[[], datetime] | None = None):
        self.cache_file, self.current = cache_file, current
        self._fetch = fetch or (lambda url: fetch_latest(url))  # looked up per call: conftest stubs fetch_latest
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._lock = threading.Lock()
        self._status = unknown(current)

    def status(self) -> dict:
        with self._lock:
            return dict(self._status)

    def check(self) -> bool:
        if parse_version(self.current) is None:  # a developer's version is never compared: don't ask, stay unknown
            return False
        try:
            release = latest(self.cache_file, fetch=self._fetch, now=self._now())
        except NoAnswer as e:
            log.info("update check: no answer (%s)", e)
            return False
        new = status_of(self.current, release)
        with self._lock:
            changed, self._status = new != self._status, new
        return changed
