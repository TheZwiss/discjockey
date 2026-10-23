"""Qobuz through streamrip's Python client: login, search, download one track as FLAC."""
from __future__ import annotations

import asyncio
import hashlib
import re
from pathlib import Path
from typing import Callable

import requests

from streamrip.client import QobuzClient
from streamrip.config import Config, OutdatedConfigError, set_user_defaults
from streamrip.exceptions import (
    AuthenticationError, IneligibleError, InvalidAppIdError, InvalidAppSecretError, MissingCredentialsError,
)
from streamrip.rip.prompter import get_prompter

from .library import SupportPaths
from .models import Candidate

CD_QUALITY = 2  # streamrip: 1 = MP3 320, 2 = 16-bit/44.1 kHz FLAC
DOWNLOAD_TIMEOUT = (15, 30)  # seconds to connect, seconds without any data before giving up
CHUNK_BYTES = 2 ** 17
CALL_TIMEOUT_S = 30  # streamrip's own requests (search, download link) have no timeout of their own
STOP_POLL_S = 0.5  # how often a waiting Qobuz request looks at the stop flag


class QobuzError(Exception):
    pass


class QobuzNotSetUp(QobuzError):
    """No streamrip config yet: setup has not been run."""


class QobuzLoginRejected(QobuzError):
    """Qobuz refused the saved login itself (wrong or expired login, an account that may not download), as opposed
    to being unreachable or a changed web player."""


class TrackUnavailable(QobuzError):
    """Qobuz will never deliver this track (region lock, withdrawn). Not worth retrying."""
    permanent = True


class QobuzPreviewOnly(QobuzError):
    """Qobuz offers only a 30-second preview. Usually the account, not the track: a failed request, tried again
    next run (not rejected, not counted toward the daily limit)."""
    signal = "preview_only"

    def __init__(self) -> None:
        super().__init__("Qobuz only offers a 30-second preview of this track. Your Qobuz subscription may not "
                         "allow full downloads; check it on qobuz.com")


def login_problem(e: BaseException) -> str:
    """Plain-English reason for a failed Qobuz login. Never streamrip's own text: some of its login errors
    contain the e-mail address and the password hash, which must not be printed or saved in state.json."""
    if isinstance(e, QobuzError):
        return str(e)
    if isinstance(e, (MissingCredentialsError, AuthenticationError)):
        return "Qobuz did not accept your login. Run: discjockey setup"
    if isinstance(e, IneligibleError):
        return "This Qobuz account is not allowed to download tracks."
    if isinstance(e, (InvalidAppIdError, InvalidAppSecretError)):
        return ("Qobuz did not accept Discjockey's app key, even after fetching a new one. Qobuz probably changed "
                "its web player: run discjockey update, then discjockey setup")
    # streamrip raises plain exceptions when Qobuz changes its web player
    return (f"Could not log in to Qobuz ({type(e).__name__}). Check the internet connection; "
            "if it keeps happening, run: discjockey update, then discjockey setup")


def _clear_app_secrets(cfg: Config) -> None:
    """streamrip only fetches new app secrets from the Qobuz web player when the cached ones are empty."""
    for data in (cfg.file, cfg.session):
        data.qobuz.app_id = ""
        data.qobuz.secrets = []
    cfg.file.set_modified()
    cfg.save_file()


def config_file(paths: SupportPaths) -> Path:
    return paths.streamrip_dir / "config.toml"


def _load_config(path: Path) -> Config:
    try:
        return Config(str(path))
    except OutdatedConfigError:
        Config.update_file(str(path))
        return Config(str(path))


def write_config(paths: SupportPaths) -> Path:
    path = config_file(paths)
    path.parent.mkdir(parents=True, exist_ok=True)
    if not path.exists():
        set_user_defaults(str(path))
    cfg = _load_config(path)
    f = cfg.file
    f.qobuz.quality = CD_QUALITY
    f.qobuz.download_booklets = False
    f.qobuz.app_id = ""  # setup always refetches the app secrets, which repairs a stale cache
    f.qobuz.secrets = []
    # Discjockey never lets streamrip download (QobuzSource.download streams into its own work folder), so this
    # folder stays unused; it lives in the support folder, so a Qobuz login needs no music folder
    f.downloads.folder = str(paths.streamrip_dir / "downloads")
    f.downloads.concurrency = False
    f.database.downloads_enabled = False
    f.database.downloads_path = str(paths.streamrip_dir / "downloads.db")
    f.database.failed_downloads_enabled = False
    f.database.failed_downloads_path = str(paths.streamrip_dir / "failed_downloads.db")
    f.set_modified()
    cfg.save_file()
    return path


def parse_track(item: dict) -> Candidate | None:
    if item.get("streamable") is False:  # previews and region-locked tracks
        return None
    title = item.get("title") or ""
    if item.get("version"):
        title = f"{title} ({item['version']})"
    album = item.get("album") or {}
    artist = " ".join(n for n in ((item.get("performer") or {}).get("name"),
                                  (album.get("artist") or {}).get("name")) if n)
    return Candidate(
        source="qobuz",
        id=str(item["id"]),
        title=title,
        artist=artist,
        duration_s=float(item["duration"]) if item.get("duration") else None,
        isrc=item.get("isrc"),
        album=album.get("title"),
        label=(album.get("label") or {}).get("name"),
        image_url=(album.get("image") or {}).get("large"),
    )


class QobuzSource:
    def __init__(self, client, runner: asyncio.Runner, check: Callable[[], None] = lambda: None):
        self.client = client
        self.runner = runner
        self.check = check  # raises events.Cancelled once Stop was pressed (set by run.execute)

    def _call(self, coro):
        """Runs one streamrip request; gives up after CALL_TIMEOUT_S and reacts to Stop while waiting."""
        async def guarded():
            task = asyncio.ensure_future(coro)
            deadline = asyncio.get_running_loop().time() + CALL_TIMEOUT_S
            try:
                while asyncio.get_running_loop().time() < deadline:
                    done, _ = await asyncio.wait({task}, timeout=STOP_POLL_S)
                    if done:
                        return True, task.result()
                    self.check()
                return False, None
            finally:
                if not task.done():
                    task.cancel()
                    await asyncio.wait({task}, timeout=1)

        finished, result = self.runner.run(guarded())
        if not finished:
            raise QobuzError(f"Qobuz did not answer within {CALL_TIMEOUT_S} seconds")
        return result

    @classmethod
    def open(cls, paths: SupportPaths) -> "QobuzSource":
        path = config_file(paths)
        if not path.exists():
            raise QobuzNotSetUp("Qobuz is not set up yet. Run: discjockey setup")
        cfg = _load_config(path)
        client = QobuzClient(cfg)
        runner = asyncio.Runner()
        try:
            try:
                runner.run(client.login())
            except (InvalidAppIdError, InvalidAppSecretError):
                _clear_app_secrets(cfg)
                client = QobuzClient(cfg)
                runner.run(client.login())
        except Exception as e:
            runner.close()
            raise _login_error(e) from None
        cfg.save_file()  # streamrip may have fetched new app secrets
        return cls(client, runner)

    def search(self, query: str, limit: int = 10) -> list[Candidate]:
        pages = self._call(self.client.search("track", query, limit=limit))
        items = [it for page in pages for it in (page.get("tracks") or {}).get("items", [])]
        return [c for it in items if (c := parse_track(it)) is not None]

    def track(self, track_id: str) -> Candidate:
        """One track by its Qobuz id (a link the user pasted)."""
        c = parse_track(self._call(self.client.get_metadata(track_id, "track")) or {"streamable": False})
        if c is None:
            raise TrackUnavailable("Qobuz cannot deliver this track (it can't be streamed in your country).")
        return c

    def download(self, cand: Candidate, workdir: Path,
                 progress: Callable[[int, int | None], None] | None = None) -> Path:
        out = workdir / f"qobuz_{cand.id}.flac"
        url = self._file_url(cand.id)
        # Stream the file ourselves instead of streamrip's downloader: it has no timeout (a stalled connection
        # would hang forever and Stop could never reach it) and ignores HTTP errors.
        headers = dict(self.client.session.headers)
        done = 0
        try:
            with requests.get(url, headers=headers, stream=True, timeout=DOWNLOAD_TIMEOUT) as resp:
                resp.raise_for_status()
                total = int(resp.headers.get("Content-Length") or 0) or None
                with open(out, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=CHUNK_BYTES):
                        f.write(chunk)
                        done += len(chunk)
                        if progress:
                            progress(done, total)  # an exception here (Stop pressed) aborts the download
        except requests.RequestException as e:
            raise QobuzError(f"download failed ({e})") from None
        if done == 0:
            raise QobuzError("the download produced no file")
        return out

    def _file_url(self, track_id: str) -> str:
        """The download link. Asks Qobuz directly instead of streamrip's get_downloadable(), which ignores the
        answer's "sample" flag and would hand out the 30-second preview link as if it were the track."""
        status, answer = self._call(self.client._request_file_url(track_id, CD_QUALITY, self.client.secret))
        if status != 200:
            raise QobuzError(f"Qobuz did not give a download link (HTTP {status})")
        if answer.get("sample"):
            raise QobuzPreviewOnly()
        if not answer.get("url"):
            codes = [r.get("code", "") for r in answer.get("restrictions") or []]
            words = re.findall(r"[A-Z][a-z]+", codes[0]) if codes else []
            reason = " ".join([words[0], *(w.lower() for w in words[1:])]) if words else "no download link"
            raise TrackUnavailable(f"Qobuz cannot deliver this track ({reason})")
        return answer["url"]

    def close(self) -> None:
        try:
            session = getattr(self.client, "session", None)
            if session is not None:
                self.runner.run(session.close())
        finally:
            self.runner.close()


def interactive_login(paths: SupportPaths) -> None:
    """Asks for e-mail and password (streamrip stores an MD5 of the password), then test-searches."""
    path = write_config(paths)
    cfg = _load_config(path)
    client = QobuzClient(cfg)
    with asyncio.Runner() as runner:
        try:
            prompter = get_prompter(client, cfg)
            runner.run(prompter.prompt_and_login())
            prompter.save()
            cfg.save_file()
            _test_search(client, runner)
        finally:
            _close(client, runner)


def _save_login(paths: SupportPaths, email: str, secret: str) -> None:
    """Writes the login into streamrip/config.toml, logs in and test-searches. Any failure is a QobuzError with a
    plain message (never streamrip's own text, see login_problem), and the config is put back as it was: a rejected
    login never replaces one that worked. A login Qobuz refused is a QobuzLoginRejected (see _login_error)."""
    before = config_file(paths).read_bytes() if config_file(paths).exists() else None
    path = write_config(paths)
    cfg = _load_config(path)
    for data in (cfg.file, cfg.session):
        data.qobuz.use_auth_token = False
        data.qobuz.email_or_userid = email
        data.qobuz.password_or_token = secret
    cfg.file.set_modified()
    cfg.save_file()
    client = QobuzClient(cfg)
    with asyncio.Runner() as runner:
        try:
            runner.run(client.login())
            cfg.save_file()  # streamrip fetched new app secrets
            _test_search(client, runner)
        except Exception as e:
            if before is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(before)
            raise _login_error(e) from None
        finally:
            _close(client, runner)


def _login_error(e: Exception) -> QobuzError:
    """A failed Qobuz login in plain words: QobuzLoginRejected when Qobuz refused the login itself, a plain
    QobuzError for everything else (offline, a Qobuz hiccup, a failed test search), which says nothing about it."""
    rejected = isinstance(e, (MissingCredentialsError, AuthenticationError, IneligibleError))
    return (QobuzLoginRejected if rejected else QobuzError)(login_problem(e))


def password_login(paths: SupportPaths, email: str, password: str) -> None:
    """E-mail and password typed into the hub's setup window. Stored as streamrip's prompter does it: the MD5 of the
    password, never the password itself."""
    email = email.strip()
    if "@" not in email or not password:
        raise QobuzError("Type the e-mail address and the password of your Qobuz account.")
    _save_login(paths, email, hashlib.md5(password.encode("utf-8")).hexdigest())


def _test_search(client, runner: asyncio.Runner) -> None:
    if not QobuzSource(client, runner).search("Daft Punk One More Time", limit=1):
        raise QobuzError("Logged in to Qobuz, but a test search found nothing.")


def _close(client, runner: asyncio.Runner) -> None:
    session = getattr(client, "session", None)  # streamrip only creates it when the login starts
    if session is not None:
        runner.run(session.close())
