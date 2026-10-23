import asyncio

import pytest
import requests

from discjockey import qobuz

from discjockey.library import Paths
from discjockey.models import Candidate
from discjockey.qobuz import QobuzError, QobuzSource, parse_track, write_config

ITEM = {
    "id": 123, "title": "Gimme Gimme", "version": "XYZ Remix", "isrc": "DECE72605755",
    "duration": 156, "streamable": True, "performer": {"name": "Vatoz Locoz"},
    "album": {"title": "Album", "artist": {"name": "Various"}, "label": {"name": "Label"},
              "image": {"large": "https://img/large.jpg"}},
}


def test_parse_track_builds_title_with_version():
    c = parse_track(ITEM)
    assert c == Candidate("qobuz", "123", "Gimme Gimme (XYZ Remix)", "Vatoz Locoz Various", 156.0,
                          isrc="DECE72605755", album="Album", label="Label", image_url="https://img/large.jpg")


def test_parse_track_without_version():
    assert parse_track({**ITEM, "version": None}).title == "Gimme Gimme"


def test_not_streamable_is_dropped():
    assert parse_track({**ITEM, "streamable": False}) is None


def test_missing_streamable_flag_is_kept():
    item = dict(ITEM)
    del item["streamable"]
    assert parse_track(item) is not None


class FakeClient:
    async def search(self, media_type, query, limit=500):
        assert media_type == "track"
        return [{"tracks": {"items": [ITEM]}}, {"tracks": {"items": [{**ITEM, "id": 456}]}}]


def test_search_flattens_pages():
    runner = asyncio.Runner()
    try:
        cands = QobuzSource(FakeClient(), runner).search("query")
    finally:
        runner.close()
    assert [c.id for c in cands] == ["123", "456"]


def test_write_config_clears_cached_app_secrets(tmp_path):
    from streamrip.config import Config
    paths = Paths(tmp_path, support=tmp_path / ".support")
    path = write_config(paths)
    cfg = Config(str(path))
    cfg.file.qobuz.app_id, cfg.file.qobuz.secrets = "stale", ["old"]
    cfg.file.set_modified()
    cfg.save_file()
    write_config(paths)
    cfg = Config(str(path))
    assert (cfg.file.qobuz.app_id, cfg.file.qobuz.secrets) == ("", [])


def test_write_config_sets_cd_quality_and_disables_database(tmp_path):
    from streamrip.config import Config
    paths = Paths(tmp_path, support=tmp_path / ".support")
    path = write_config(paths)
    cfg = Config(str(path))
    assert cfg.file.qobuz.quality == 2
    assert cfg.file.database.downloads_enabled is False
    assert cfg.file.downloads.folder == str(paths.streamrip_dir / "downloads")
    # running it again keeps the file valid (idempotent)
    write_config(paths)
    assert Config(str(path)).file.qobuz.quality == 2


class Stop(BaseException):
    """Stands in for events.Cancelled (Task 9): what the progress callback raises when the user presses Stop."""


class FakeResponse:
    def __init__(self, chunks, status=200):
        self.chunks, self.status = chunks, status
        self.headers = {"Content-Length": str(sum(len(c) for c in chunks))}

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def raise_for_status(self):
        if self.status != 200:
            raise requests.HTTPError(f"{self.status} Client Error")

    def iter_content(self, chunk_size):
        yield from self.chunks


FILE_URL = {"track_id": 7, "format_id": 6, "url": "https://streaming.example/file.flac", "duration": 156}


class DownloadClient:
    """streamrip's QobuzClient as far as download() uses it: the raw track/getFileUrl answer."""
    secret = "app-secret"

    class session:
        headers = {"X-App-Id": "1", "X-User-Auth-Token": "secret"}

    def __init__(self, answer=(200, FILE_URL)):
        self.answer = answer

    async def _request_file_url(self, track_id, quality, secret):
        assert (track_id, quality, secret) == ("7", 2, "app-secret")
        return self.answer


def download(tmp_path, monkeypatch, response=None, progress=None, client=None):
    calls = {}

    def fake_get(url, **kwargs):
        calls.update(kwargs, url=url)
        return response

    monkeypatch.setattr(qobuz.requests, "get", fake_get)
    runner = asyncio.Runner()
    try:
        out = QobuzSource(client or DownloadClient(), runner).download(
            Candidate("qobuz", "7", "t", "a", 1.0), tmp_path, progress=progress)
    finally:
        runner.close()
    return out, calls


def test_download_streams_with_timeout_and_reports_progress(tmp_path, monkeypatch):
    seen = []
    out, calls = download(tmp_path, monkeypatch, FakeResponse([b"abcd", b"efghij"]),
                          progress=lambda done, total: seen.append((done, total)))
    assert out.read_bytes() == b"abcdefghij"
    assert seen == [(4, 10), (10, 10)]
    assert calls["timeout"] == qobuz.DOWNLOAD_TIMEOUT and calls["stream"] is True
    assert calls["headers"]["X-User-Auth-Token"] == "secret"


def test_stop_during_download_propagates(tmp_path, monkeypatch):
    def stop(done, total):
        raise Stop()

    with pytest.raises(Stop):
        download(tmp_path, monkeypatch, FakeResponse([b"abcd", b"efgh"]), progress=stop)


def test_http_error_is_a_qobuz_error(tmp_path, monkeypatch):
    with pytest.raises(qobuz.QobuzError, match="403"):
        download(tmp_path, monkeypatch, FakeResponse([], status=403))


def test_region_locked_track_is_unavailable(tmp_path, monkeypatch):
    answer = (200, {"track_id": 7, "restrictions": [{"code": "TrackRestrictedByRightHolders"}]})
    with pytest.raises(qobuz.TrackUnavailable, match="Track restricted by right holders") as excinfo:
        download(tmp_path, monkeypatch, client=DownloadClient(answer))
    assert excinfo.value.permanent is True


def test_preview_only_is_a_temporary_qobuz_failure(tmp_path, monkeypatch):
    # streamrip 2.1.0 ignores the API's "sample" flag and would hand out the 30 s preview link
    answer = (200, {**FILE_URL, "sample": True, "duration": 30,
                    "restrictions": [{"code": "TrackRestrictedByPurchaseCredentials"}]})
    with pytest.raises(qobuz.QobuzPreviewOnly, match="subscription") as excinfo:
        download(tmp_path, monkeypatch, FakeResponse([b"abcd"]), client=DownloadClient(answer))
    assert not getattr(excinfo.value, "permanent", False)
    assert excinfo.value.signal == "preview_only"
    assert not (tmp_path / "qobuz_7.flac").exists()  # nothing was downloaded


def test_file_url_error_status_is_a_qobuz_error(tmp_path, monkeypatch):
    with pytest.raises(qobuz.QobuzError, match="400"):
        download(tmp_path, monkeypatch, client=DownloadClient((400, {"message": "Invalid request signature"})))


# --- streamrip's aiohttp session has no timeout: Discjockey bounds each call and checks Stop while it waits ---

class SlowClient(DownloadClient):
    async def search(self, media_type, query, limit=500):
        await asyncio.sleep(60)

    async def _request_file_url(self, track_id, quality, secret):
        await asyncio.sleep(60)


@pytest.fixture
def fast_clock(monkeypatch):
    monkeypatch.setattr(qobuz, "CALL_TIMEOUT_S", 0.3)
    monkeypatch.setattr(qobuz, "STOP_POLL_S", 0.02)


def slow_source(check=lambda: None):
    runner = asyncio.Runner()
    return QobuzSource(SlowClient(), runner, check=check), runner


@pytest.mark.usefixtures("fast_clock")
@pytest.mark.parametrize("call", ["search", "download"])
def test_stalled_qobuz_call_times_out(tmp_path, monkeypatch, call):
    monkeypatch.setattr(qobuz.requests, "get", lambda *a, **k: pytest.fail("no download after a timeout"))
    source, runner = slow_source()
    try:
        with pytest.raises(qobuz.QobuzError, match="did not answer"):
            if call == "search":
                source.search("query")
            else:
                source.download(Candidate("qobuz", "7", "t", "a", 1.0), tmp_path)
    finally:
        runner.close()


@pytest.mark.parametrize("call", ["search", "download"])
def test_stop_while_waiting_for_qobuz(tmp_path, monkeypatch, call):
    monkeypatch.setattr(qobuz, "STOP_POLL_S", 0.02)  # the 30 s timeout stays: Stop must not wait for it
    checks = []

    def check():
        checks.append(1)
        if len(checks) >= 3:
            raise Stop()

    source, runner = slow_source(check)
    try:
        with pytest.raises(Stop):
            if call == "search":
                source.search("query")
            else:
                source.download(Candidate("qobuz", "7", "t", "a", 1.0), tmp_path)
    finally:
        runner.close()


def test_stop_poll_and_timeout_defaults():
    assert (qobuz.CALL_TIMEOUT_S, qobuz.STOP_POLL_S) == (30, 0.5)


# --- login (QobuzSource.open) with fakes: no network, no real config ---

class FakeConfig:
    def __init__(self):
        self.saved = 0

    def save_file(self):
        self.saved += 1


def fake_open(tmp_path, monkeypatch, *login_errors):
    """QobuzSource.open where the n-th client's login raises login_errors[n] (None = logs in)."""
    path = tmp_path / "config.toml"
    path.write_text("")
    cfg, clients, cleared = FakeConfig(), [], []

    class LoginClient:
        def __init__(self, config):
            assert config is cfg
            self.error = login_errors[len(clients)]
            clients.append(self)

        async def login(self):
            if self.error:
                raise self.error

    monkeypatch.setattr(qobuz, "config_file", lambda paths: path)
    monkeypatch.setattr(qobuz, "_load_config", lambda p: cfg)
    monkeypatch.setattr(qobuz, "QobuzClient", LoginClient)
    monkeypatch.setattr(qobuz, "_clear_app_secrets", lambda c: cleared.append(c))
    return cfg, clients, cleared


@pytest.mark.parametrize("stale", ["InvalidAppIdError", "InvalidAppSecretError"])
def test_stale_app_secrets_are_refetched_once(tmp_path, monkeypatch, stale):
    from streamrip import exceptions
    cfg, clients, cleared = fake_open(tmp_path, monkeypatch, getattr(exceptions, stale)("stale"), None)
    source = QobuzSource.open(Paths(tmp_path, support=tmp_path / ".support"))
    try:
        assert cleared == [cfg] and len(clients) == 2
        assert source.client is clients[1]  # the fresh client that logged in with the new secrets
        assert cfg.saved == 1  # the new secrets are kept for the next run
    finally:
        source.runner.close()


SECRET_PARAMS = "{'email': 'dj@example.com', 'password': '5f4dcc3b5aa765d61d8327deb882cf99', 'app_id': '123'}"


@pytest.mark.parametrize("retry_error", ["InvalidAppIdError", "RuntimeError"])
def test_login_message_never_contains_streamrip_text(tmp_path, monkeypatch, retry_error):
    # streamrip puts the e-mail and the password hash into some login errors; they must not be printed or
    # saved into state.json's warning signs
    from streamrip import exceptions
    make = getattr(exceptions, retry_error, None) or RuntimeError
    fake_open(tmp_path, monkeypatch, exceptions.InvalidAppIdError(f"Invalid app id from params {SECRET_PARAMS}"),
              make(f"Invalid app id from params {SECRET_PARAMS}"))
    with pytest.raises(qobuz.QobuzError) as excinfo:
        QobuzSource.open(Paths(tmp_path, support=tmp_path / ".support"))
    text = str(excinfo.value)
    assert "5f4dcc3b" not in text and "dj@example.com" not in text and "params" not in text
    assert "discjockey update" in text


@pytest.mark.parametrize("error, rejected", [("AuthenticationError", True), ("MissingCredentialsError", True),
                                              ("IneligibleError", True), ("ConnectionError", False)])
def test_open_tells_a_refused_login_from_other_failures(tmp_path, monkeypatch, error, rejected):
    # Settings' "Check again" records login_failed only when Qobuz refused the login itself, never when offline
    from streamrip import exceptions
    make = getattr(exceptions, error, None) or ConnectionError
    fake_open(tmp_path, monkeypatch, make("no"))
    with pytest.raises(qobuz.QobuzError) as excinfo:
        QobuzSource.open(Paths(tmp_path, support=tmp_path / ".support"))
    assert isinstance(excinfo.value, qobuz.QobuzLoginRejected) is rejected


def test_login_problem_texts():
    from streamrip import exceptions
    assert "not accept your login" in qobuz.login_problem(exceptions.AuthenticationError(SECRET_PARAMS))
    assert "app key" in qobuz.login_problem(exceptions.InvalidAppSecretError(["s1", "s2"]))
    assert "(OSError)" in qobuz.login_problem(OSError(SECRET_PARAMS))
    assert qobuz.login_problem(qobuz.QobuzError("our own text")) == "our own text"


# --- e-mail and password from the hub's setup window (no streamrip prompter) ---

class PasswordClient:
    seen = None

    def __init__(self, cfg):
        self.cfg = cfg

    async def login(self):
        c = self.cfg.session.qobuz
        PasswordClient.seen = (c.use_auth_token, c.email_or_userid, c.password_or_token)


def test_password_login_stores_the_md5_like_streamrip(tmp_path, monkeypatch):
    import hashlib

    from streamrip.config import Config

    from discjockey import qobuz
    monkeypatch.setattr(qobuz, "QobuzClient", PasswordClient)
    monkeypatch.setattr(QobuzSource, "search", lambda self, query, limit=10: ["hit"])
    paths = Paths(tmp_path, support=tmp_path / ".support")
    qobuz.password_login(paths, " dj@example.com ", "secret pw")
    md5 = hashlib.md5("secret pw".encode()).hexdigest()
    assert PasswordClient.seen == (False, "dj@example.com", md5)
    text = qobuz.config_file(paths).read_text()
    assert "secret pw" not in text and md5 in text
    q = Config(str(qobuz.config_file(paths))).file.qobuz
    assert (q.use_auth_token, q.email_or_userid, q.password_or_token) == (False, "dj@example.com", md5)


def test_password_login_failure_is_a_plain_message(tmp_path, monkeypatch):
    from streamrip.exceptions import AuthenticationError

    from discjockey import qobuz

    class Refusing(PasswordClient):
        async def login(self):
            raise AuthenticationError("Invalid credentials from params {'email': 'dj@example.com', 'password': 'x'}")

    monkeypatch.setattr(qobuz, "QobuzClient", Refusing)
    with pytest.raises(QobuzError) as excinfo:
        qobuz.password_login(Paths(tmp_path, support=tmp_path / ".support"), "dj@example.com", "secret pw")
    assert str(excinfo.value) == "Qobuz did not accept your login. Run: discjockey setup"
    assert isinstance(excinfo.value, qobuz.QobuzLoginRejected)


def test_password_login_offline_is_not_a_refused_login(tmp_path, monkeypatch):
    from discjockey import qobuz

    class Offline(PasswordClient):
        async def login(self):
            raise OSError("Cannot connect to host www.qobuz.com")

    monkeypatch.setattr(qobuz, "QobuzClient", Offline)
    with pytest.raises(QobuzError) as excinfo:
        qobuz.password_login(Paths(tmp_path, support=tmp_path / ".support"), "dj@example.com", "secret pw")
    assert not isinstance(excinfo.value, qobuz.QobuzLoginRejected)


@pytest.mark.parametrize("email,password", [("", "pw"), ("dj@example.com", ""), ("no-at-sign", "pw")])
def test_password_login_checks_the_fields_first(tmp_path, monkeypatch, email, password):
    from discjockey import qobuz
    monkeypatch.setattr(qobuz, "QobuzClient", lambda cfg: pytest.fail("no login with empty fields"))
    with pytest.raises(QobuzError):
        qobuz.password_login(Paths(tmp_path, support=tmp_path / ".support"), email, password)


def test_track_asks_qobuz_for_one_track(tmp_path):
    class MetaClient:
        async def get_metadata(self, item, media_type):
            assert (item, media_type) == ("123", "track")
            return ITEM

    with asyncio.Runner() as runner:
        c = QobuzSource(MetaClient(), runner).track("123")
    assert (c.key, c.title, c.duration_s) == ("qobuz:123", "Gimme Gimme (XYZ Remix)", 156.0)


def test_track_that_cannot_be_streamed(tmp_path):
    class MetaClient:
        async def get_metadata(self, item, media_type):
            return {**ITEM, "streamable": False}

    with asyncio.Runner() as runner:
        with pytest.raises(QobuzError, match="cannot deliver"):
            QobuzSource(MetaClient(), runner).track("123")


def test_a_rejected_login_puts_the_working_one_back(tmp_path, monkeypatch):
    from streamrip.exceptions import AuthenticationError

    from discjockey import qobuz
    monkeypatch.setattr(qobuz, "QobuzClient", PasswordClient)
    monkeypatch.setattr(QobuzSource, "search", lambda self, query, limit=10: ["hit"])
    paths = Paths(tmp_path, support=tmp_path / ".support")
    qobuz.password_login(paths, "dj@example.com", "good pw")
    working = qobuz.config_file(paths).read_bytes()

    class Refusing(PasswordClient):
        async def login(self):
            raise AuthenticationError("Invalid credentials")

    monkeypatch.setattr(qobuz, "QobuzClient", Refusing)
    with pytest.raises(QobuzError):
        qobuz.password_login(paths, "other@example.com", "wrong pw")
    assert qobuz.config_file(paths).read_bytes() == working


def test_a_rejected_first_login_leaves_no_config(tmp_path, monkeypatch):
    from streamrip.exceptions import AuthenticationError

    from discjockey import qobuz

    class Refusing(PasswordClient):
        async def login(self):
            raise AuthenticationError("Invalid credentials")

    monkeypatch.setattr(qobuz, "QobuzClient", Refusing)
    with pytest.raises(QobuzError):
        qobuz.password_login(Paths(tmp_path, support=tmp_path / ".support"), "dj@example.com", "wrong pw")
    assert not qobuz.config_file(Paths(tmp_path, support=tmp_path / ".support")).exists()


def test_write_config_needs_no_music_folder(tmp_path):
    from streamrip.config import Config
    from discjockey.library import SupportPaths
    path = write_config(SupportPaths(support=tmp_path / "support"))
    assert path == tmp_path / "support" / "streamrip" / "config.toml"
    assert Config(str(path)).file.downloads.folder == str(tmp_path / "support" / "streamrip" / "downloads")
