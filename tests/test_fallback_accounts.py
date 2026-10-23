"""FallbackSource with browser logins: only format listings and downloads use them, never a search."""
import pytest
import yt_dlp

from discjockey import fallback as fb
from discjockey.fallback import FallbackSource
from discjockey.models import Candidate, SpotifyTrack

T = SpotifyTrack("t1", "Gimme Gimme", ("Vatoz Locoz",), "Album", None, 156000, "DECE72605755")


class Recorder:
    """Stands in for yt_dlp.YoutubeDL: remembers every options dict; formats get 256 kbps only with a login."""
    seen: list[dict] = []

    def __init__(self, opts):
        self.opts = opts
        Recorder.seen.append(opts)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def extract_info(self, url, download=False):
        if url.startswith(("https://music.youtube.com/search", "scsearch", "ytsearch")):
            return {"entries": [{"id": "abc", "url": "https://music.youtube.com/watch?v=abc", "title": "x",
                                 "duration": 156}]}
        return {"id": "abc", "abr": 256 if "cookiesfrombrowser" in self.opts else 129}

    def prepare_filename(self, info):
        return "/nonexistent"


@pytest.fixture(autouse=True)
def recorder(monkeypatch):
    Recorder.seen = []
    monkeypatch.setattr(yt_dlp, "YoutubeDL", Recorder)
    return Recorder


def test_search_never_uses_the_login(recorder):
    FallbackSource(logins={"youtube": ("chrome", None), "soundcloud": ("firefox", None)}).search(T)
    assert recorder.seen and not any("cookiesfrombrowser" in o for o in recorder.seen)


def test_stream_kbps_uses_the_login_only_when_asked_and_only_for_its_source(recorder):
    src = FallbackSource(logins={"youtube": ("chrome", None)})
    assert src.stream_kbps("youtube_music", "abc") == 129
    assert src.stream_kbps("youtube_music", "abc", account=True) == 256
    assert recorder.seen[-1]["extractor_args"] == {"youtube": {"player_client": ["web_music", "default"]}}
    assert src.stream_kbps("youtube", "abc", account=True) == 129  # videos: never the login
    assert src.stream_kbps("soundcloud", "1", account=True) == 129  # no SoundCloud login set up


def test_download_with_the_login(recorder, tmp_path):
    src = FallbackSource(logins={"soundcloud": ("firefox", None)})
    cand = Candidate("soundcloud", "1", "x", "y", 156.0, url="https://soundcloud.com/a/b")
    with pytest.raises(RuntimeError):  # Recorder writes no file
        src.download(cand, tmp_path, account=True)
    assert recorder.seen[-1]["cookiesfrombrowser"] == ("firefox", None, None, None)


def test_download_with_a_login_in_another_browser_profile(recorder, tmp_path):
    src = FallbackSource(logins={"soundcloud": ("chrome", "Profile 2")})
    cand = Candidate("soundcloud", "1", "x", "y", 156.0, url="https://soundcloud.com/a/b")
    with pytest.raises(RuntimeError):
        src.download(cand, tmp_path, account=True)
    assert recorder.seen[-1]["cookiesfrombrowser"] == ("chrome", "Profile 2", None, None)


class Cookie:
    def __init__(self, name, domain):
        self.name, self.domain, self.value = name, domain, "secret-never-shown"


def checker(monkeypatch, cookies=None, error=None, kbps=256):
    src = FallbackSource()

    def jar(browser, profile=None):
        if error:
            raise error
        return cookies or []

    monkeypatch.setattr(src, "_browser_cookies", jar)
    monkeypatch.setattr(src, "stream_kbps", lambda source, source_id, account=False: kbps)
    return src


def test_check_account_ok(monkeypatch):
    src = checker(monkeypatch, [Cookie("SAPISID", ".youtube.com")])
    assert src.check_account("youtube", "chrome") == {"ok": True, "problem": None, "kbps": 256, "detail": ""}


def test_check_account_problems(monkeypatch):
    unreadable = checker(monkeypatch, error=PermissionError("[Errno 1] Operation not permitted: 'Cookies.binarycookies'"))
    assert unreadable.check_account("youtube", "safari")["problem"] == "cookies_unreadable"
    logged_out = checker(monkeypatch, [Cookie("PREF", ".youtube.com")])
    assert logged_out.check_account("youtube", "chrome")["problem"] == "not_logged_in"
    no_premium = checker(monkeypatch, [Cookie("oauth_token", ".soundcloud.com")], kbps=128)
    assert no_premium.check_account("soundcloud", "firefox") == {"ok": False, "problem": "no_premium", "kbps": 128,
                                                                  "detail": ""}


def test_check_account_never_returns_a_cookie_value(monkeypatch):
    src = checker(monkeypatch, [Cookie("SAPISID", ".youtube.com")])
    assert "secret-never-shown" not in repr(src.check_account("youtube", "chrome"))


class GoPlusDrm(Recorder):
    """The listing through the login: SoundCloud's Go+ stream exists but only DRM-protected; yt-dlp picks 128 kbps."""
    drm, abr = True, 128

    def add_info_extractor(self, ie):
        self.ie = ie

    def extract_info(self, url, download=False):
        self.ie.drm_premium = self.drm
        return {"id": "1", "abr": self.abr}


def test_a_go_plus_stream_that_is_only_drm_protected_is_reported_as_drm_not_as_missing(monkeypatch):
    monkeypatch.setattr(yt_dlp, "YoutubeDL", GoPlusDrm)
    src = FallbackSource(logins={"soundcloud": ("firefox", None)})
    with pytest.raises(Exception) as err:
        src.stream_kbps("soundcloud", "1", account=True)
    assert fb.drm_protected(err.value)
    GoPlusDrm.drm = False
    try:
        assert src.stream_kbps("soundcloud", "1", account=True) == 128  # no Go+ stream at all: as before
    finally:
        GoPlusDrm.drm = True


def test_check_account_skips_a_song_whose_go_plus_stream_is_drm_protected(monkeypatch):
    src = checker(monkeypatch, [Cookie("oauth_token", ".soundcloud.com")])
    monkeypatch.setattr(src, "_extract", lambda url, flat: {"entries": [
        {"id": i, "url": f"https://soundcloud.com/a/{i}", "title": "x", "duration": 1} for i in ("1", "2")]})

    def kbps(source, source_id, account=False):
        if source_id == "1":
            raise RuntimeError("[soundcloud] 1: the Go+ stream is DRM protected")
        return 256

    monkeypatch.setattr(src, "stream_kbps", kbps)
    assert src.check_account("soundcloud", "firefox") == {"ok": True, "problem": None, "kbps": 256, "detail": ""}
