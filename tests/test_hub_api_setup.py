import errno
import json
import threading
import time
from types import SimpleNamespace

import pytest
from hub_helpers import make_api, make_root, make_unbound_api, wait_job
from tools_helpers import CheckRun, FakePyPI

import discjockey
from discjockey import qobuz, setup_cmd, tool_updates, tools
from discjockey.sources import soundcloud, spotify
from discjockey.library import run_lock
from discjockey.settings import Account, Settings, load_settings, save_settings


@pytest.fixture
def root(tmp_path):
    return make_root(tmp_path)


def test_check_tools(root):
    import yt_dlp.version
    api, _ = make_api(root, which=lambda tool: None if tool == "deno" else f"/opt/homebrew/bin/{tool}")
    t = api.setup_check_tools()
    assert t["tools"] == {"ffmpeg": True, "ffprobe": True, "deno": False}
    assert t["missing"] == ["deno"] and t["hints"] == {"deno": "brew install deno"}
    assert t["redirect_uri"] == "http://127.0.0.1:8888/callback"
    assert "versions" not in t and t["download_tools_problem"] is None
    assert t["download_tools"]["yt-dlp"] == {"version": yt_dlp.version.__version__, "source": "built_in",
                                             "waiting": None, "previous": None}
    assert t["download_tools"]["streamrip"]["version"] and t["download_tools"]["streamrip"]["source"] == "built_in"


def test_save_client_id(root):
    api, rec = make_api(root)
    assert api.setup_save_client_id("not one")["kind"] == "refused"
    assert wait_job(api, rec, api.setup_save_client_id(" 4f1c" + "0" * 24 + "e9a2 ")).ok
    assert json.loads(root.spotify_app.read_text()) == {"client_id": "4f1c" + "0" * 24 + "e9a2"}


def test_spotify_login_opens_the_system_browser(root, monkeypatch):
    root.spotify_app.write_text(json.dumps({"client_id": "0" * 32}))
    seen = {}

    def fake_login(client_id, token_path, open_browser, token):
        seen.update(client_id=client_id, token_path=token_path)
        open_browser("https://accounts.spotify.com/authorize?x")
        token_path.write_text("{}")

    monkeypatch.setattr(spotify, "login", fake_login)
    monkeypatch.setattr(spotify, "load_session", lambda p: object())
    monkeypatch.setattr(spotify, "current_user", lambda s: ("dj1", "DJ One"))
    api, rec = make_api(root)
    f = wait_job(api, rec, api.setup_spotify_login())
    assert f.ok and f.result == {"user": "DJ One"} and seen["token_path"] == root.spotify_token
    assert json.loads(root.spotify_app.read_text()) == {"client_id": "0" * 32, "user": "DJ One"}  # Settings shows it
    assert api._svc.calls["open_url"] == ["https://accounts.spotify.com/authorize?x"]


def test_connecting_a_service_clears_its_stored_read_problem(root, monkeypatch):
    root.spotify_app.write_text(json.dumps({"client_id": "0" * 32}))
    monkeypatch.setattr(spotify, "login", lambda client_id, token_path, open_browser, token: None)
    monkeypatch.setattr(spotify, "load_session", lambda p: object())
    monkeypatch.setattr(spotify, "current_user", lambda s: ("dj1", "DJ One"))
    monkeypatch.setattr(qobuz, "password_login", lambda p, e, pw: None)
    api, rec = make_api(root)
    api._store.failed("not_set_up", "Connect Spotify first.", "spotify")
    assert wait_job(api, rec, api.setup_qobuz_login("dj@example.com", "pw")).ok
    assert api._store.problem_service == "spotify"  # Qobuz's login says nothing about Spotify's problem
    assert wait_job(api, rec, api.setup_spotify_login()).ok
    assert (api._store.problem, api._store.problem_service) == (None, None)
    api._store.failed("not_set_up", "Connect Qobuz first.", "qobuz")
    assert wait_job(api, rec, api.setup_qobuz_login("dj@example.com", "pw")).ok
    assert api._store.problem is None
    assert api.dashboard()["read_status"]["problem"] is None  # the page unblocks without a restart


def test_spotify_login_can_be_cancelled(root, monkeypatch):
    root.spotify_app.write_text(json.dumps({"client_id": "0" * 32}))

    def waiting(client_id, token_path, open_browser, token):
        while True:
            token.check()
            time.sleep(0.01)

    monkeypatch.setattr(spotify, "login", waiting)
    api, rec = make_api(root)
    answer = api.setup_spotify_login()
    time.sleep(0.05)
    assert api.stop()["stopped"]
    assert wait_job(api, rec, answer).problem == "stopped"


def test_spotify_login_without_a_client_id(root):
    api, rec = make_api(root)
    f = wait_job(api, rec, api.setup_spotify_login())
    assert (f.ok, f.message) == (False, "Paste the Client ID first.")


def test_spotify_login_failure_kind(root, monkeypatch):
    root.spotify_app.write_text(json.dumps({"client_id": "0" * 32}))

    def busy(*a, **k):
        raise spotify.SpotifyError("Port 8888 is busy.", "login_failed")

    monkeypatch.setattr(spotify, "login", busy)
    api, rec = make_api(root)
    assert wait_job(api, rec, api.setup_spotify_login()).problem == "login_failed"


def test_qobuz_login_records_its_check(root, monkeypatch):
    logins = []
    monkeypatch.setattr(qobuz, "password_login", lambda p, e, pw: logins.append(("password", e)))
    save_settings(root.settings_file, Settings(qobuz_skipped=True))
    api, rec = make_api(root)
    assert wait_job(api, rec, api.setup_qobuz_login("dj@example.com", "pw")).ok
    assert logins == [("password", "dj@example.com")]
    s = load_settings(root.settings_file)
    assert not s.qobuz_skipped and s.qobuz_last_check == {"ok": True, "problem": None, "kbps": None,
                                                          "at": "2026-10-20T21:47:00"}


def test_a_rejected_qobuz_login_is_recorded_as_failed(root, monkeypatch):
    def refuse(p, e, pw):
        raise qobuz.QobuzLoginRejected("Qobuz did not accept your login. Run: discjockey setup")

    monkeypatch.setattr(qobuz, "password_login", refuse)
    api, rec = make_api(root)
    done = wait_job(api, rec, api.setup_qobuz_login("dj@example.com", "pw"))
    assert not done.ok
    assert load_settings(root.settings_file).qobuz_last_check["problem"] == "login_failed"


def test_an_offline_qobuz_login_records_no_check(root, monkeypatch):
    def offline(p, e, pw):
        raise qobuz.QobuzError("Couldn't reach Qobuz.")

    monkeypatch.setattr(qobuz, "password_login", offline)
    save_settings(root.settings_file, Settings())
    api, rec = make_api(root)
    done = wait_job(api, rec, api.setup_qobuz_login("dj@example.com", "pw"))
    assert (done.ok, done.problem) == (False, "failed")
    assert load_settings(root.settings_file).qobuz_last_check is None


def test_qobuz_login_failure_is_plain(root, monkeypatch):
    def refuse(p, e, pw):
        raise qobuz.QobuzError("Qobuz did not accept your login. Run: discjockey setup")

    monkeypatch.setattr(qobuz, "password_login", refuse)
    api, rec = make_api(root)
    f = wait_job(api, rec, api.setup_qobuz_login("dj@example.com", "secret pw"))
    assert (f.ok, f.problem) == (False, "failed") and "secret" not in f.message


def test_setup_status_says_the_version(tmp_path):
    api, _ = make_unbound_api(tmp_path / "support")
    status = api.setup_status()
    assert status["version"] == discjockey.__version__ and "app_created" not in status


def test_open_licenses_opens_the_folder(tmp_path, monkeypatch):
    folder = tmp_path / "licenses"
    folder.mkdir()
    monkeypatch.setattr(tools, "licenses_dir", lambda: folder)
    api, _ = make_unbound_api(tmp_path / "support")
    assert api.open_licenses()["ok"]
    assert api._svc.calls["open_path"] == [folder]


def test_open_licenses_refuses_a_missing_folder(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "licenses_dir", lambda: tmp_path / "gone")
    api, _ = make_unbound_api(tmp_path / "support")
    assert api.open_licenses()["kind"] == "refused"


def test_the_script_app_is_gone():
    from discjockey.hub import api as api_mod
    assert not hasattr(api_mod.HubApi, "setup_create_app")
    with pytest.raises(ImportError):
        __import__("discjockey.hub.bundle")


def test_update_tools(root):
    api, rec = make_api(root, fetch=FakePyPI("2999.1.1"), run=CheckRun())  # newer than any installed yt-dlp
    f = wait_job(api, rec, api.update_tools())
    assert f.ok and f.result["after"] == {"yt-dlp": "2999.1.1"} and f.result["restart"] is True
    assert api.setup_check_tools()["download_tools"]["yt-dlp"]["waiting"] == "2999.1.1"
    f = wait_job(api, rec, api.update_tools())  # the same newest again: nothing downloaded, the reopen still waits
    assert f.ok and f.result["before"] == f.result["after"] == {"yt-dlp": "2999.1.1"} and f.result["restart"] is True
    offline, rec2 = make_api(root)  # the default fetch: no network in tests
    f = wait_job(offline, rec2, offline.update_tools())
    assert (f.ok, f.problem, f.message) == (False, "failed", tool_updates.OFFLINE)


def test_update_tools_when_already_the_newest(root):
    api, rec = make_api(root, fetch=FakePyPI("2000.1.1"), run=CheckRun())  # older than the installed yt-dlp
    f = wait_job(api, rec, api.update_tools())
    assert f.ok and f.result["before"] == f.result["after"] and f.result["restart"] is False


def _server_error(url):
    raise tool_updates.HttpStatus(503, url)


def _not_json(url):
    return b"<html>maintenance</html>"


@pytest.mark.parametrize("kwargs,message", [
    ({"fetch": _server_error, "run": CheckRun()}, tool_updates.SERVER_ERROR),
    ({"fetch": _not_json, "run": CheckRun()}, tool_updates.BAD_ANSWER),
    ({"fetch": FakePyPI("2999.1.1", pure=False), "run": CheckRun()}, tool_updates.NO_WHEEL),
    ({"fetch": FakePyPI("2999.1.1", damage="yt"), "run": CheckRun()}, tool_updates.DAMAGED),
    ({"fetch": FakePyPI("2999.1.1"), "run": CheckRun(ok=False)}, tool_updates.CHECK_FAILED),
])
def test_update_tools_failures_are_plain_sentences(root, kwargs, message):
    api, rec = make_api(root, **kwargs)
    f = wait_job(api, rec, api.update_tools())
    assert (f.ok, f.problem, f.message) == (False, "failed", message)
    assert tools.current_folder(root.support) is None


def test_update_tools_disk_problem_is_plain(root, monkeypatch):
    def full(folder):
        raise OSError(errno.ENOSPC, "No space left on device")

    monkeypatch.setattr(tool_updates, "_sync_folder", full)
    api, rec = make_api(root, fetch=FakePyPI("2999.1.1"), run=CheckRun())
    f = wait_job(api, rec, api.update_tools())
    assert (f.ok, f.problem) == (False, "failed")
    assert f.message == tool_updates.DISK.format(reason="the disk is full") and "errno" not in f.message.lower()


def test_rollback_tools(root):
    api, rec = make_api(root, fetch=FakePyPI("2999.1.1"), run=CheckRun())
    assert wait_job(api, rec, api.update_tools()).ok
    previous = api.setup_check_tools()["download_tools"]["yt-dlp"]["previous"]
    f = wait_job(api, rec, api.rollback_tools())
    assert f.ok and f.result["before"] == {"yt-dlp": "2999.1.1"} and f.result["after"] == {"yt-dlp": previous}
    assert f.result["restart"] is False  # this window never used 2999.1.1
    assert tools.current_folder(root.support) is None
    f = wait_job(api, rec, api.rollback_tools())
    assert (f.ok, f.problem, f.message) == (False, "refused", tool_updates.NOTHING_TO_UNDO)


def test_update_tools_is_refused_while_a_sync_holds_the_engine(root):
    import threading
    pypi = FakePyPI("2999.1.1")
    api, _ = make_api(root, fetch=pypi, run=CheckRun())
    release = threading.Event()
    api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    try:
        assert api.update_tools()["kind"] == "busy"
    finally:
        release.set()
        api._jobs.wait(5)
    with run_lock(root.lock):  # `discjockey` in a terminal is syncing
        answer = api.update_tools()
    assert answer["ok"] is False and answer["kind"] == "console"
    assert pypi.requested == [] and not tools.tools_root(root.support).exists()


def test_rollback_tools_is_refused_while_a_sync_or_the_console_holds_the_engine(root):
    import threading
    api, rec = make_api(root, fetch=FakePyPI("2999.1.1"), run=CheckRun())
    assert wait_job(api, rec, api.update_tools()).ok
    kept = tools.current_folder(root.support)
    release = threading.Event()
    api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    try:
        assert api.rollback_tools()["kind"] == "busy"
    finally:
        release.set()
        api._jobs.wait(5)
    with run_lock(root.lock):  # `discjockey` in a terminal is syncing
        answer = api.rollback_tools()
    assert answer["ok"] is False and answer["kind"] == "console"
    assert tools.current_folder(root.support) == kept and kept.is_dir()  # nothing was stepped back or deleted


def test_check_tools_survives_a_failing_download_tools_read(root, monkeypatch, caplog):
    def broken(support):
        raise RuntimeError("secret detail")

    monkeypatch.setattr(tool_updates, "current_status", broken)
    api, _ = make_api(root, which=lambda tool: None if tool == "deno" else f"/opt/homebrew/bin/{tool}")
    with caplog.at_level("WARNING"):
        t = api.setup_check_tools()
    assert t["ok"] is not False and t["tools"] == {"ffmpeg": True, "ffprobe": True, "deno": False}
    assert t["missing"] == ["deno"] and t["download_tools"] is None
    assert t["download_tools_problem"] == api_mod.DOWNLOAD_TOOLS_UNREADABLE and "secret" not in t["download_tools_problem"]
    assert "secret detail" in caplog.text


def test_console_update(root, monkeypatch, capsys):
    monkeypatch.setattr(tool_updates, "update", lambda support: ({"yt-dlp": "2026.10.21"},
                                                                 {"yt-dlp": "2026.10.28"}, True))
    assert setup_cmd.run_update(root.support) == 0
    out = capsys.readouterr().out
    assert "yt-dlp 2026.10.21 -> 2026.10.28" in out and "Start Discjockey again" in out

    def offline(support):
        raise tool_updates.ToolsError(tool_updates.OFFLINE)
    monkeypatch.setattr(tool_updates, "update", offline)
    assert setup_cmd.run_update(root.support) == 2
    assert tool_updates.OFFLINE in capsys.readouterr().out


def test_the_whole_contract_is_there(root):
    from test_hub_api import CONTRACT
    api, _ = make_api(root)
    assert {name for name in dir(api) if not name.startswith("_")} == CONTRACT


def test_the_qobuz_password_steps_name_the_page():
    assert setup_cmd.QOBUZ_PASSWORD_URL == "https://www.qobuz.com/signin/forget-password"
    assert setup_cmd.QOBUZ_PASSWORD_URL in setup_cmd.QOBUZ_PASSWORD_STEPS


def test_quit_closes_the_window_but_not_during_a_change(root):
    import threading
    api, _ = make_api(root)
    asked = []
    api._quit = lambda: asked.append(1)
    gate = threading.Event()
    api._jobs.start("x", lambda ctx: gate.wait(5))
    try:
        r = api.quit()
        assert (r["ok"], r["kind"]) == (False, "busy") and "quit" in r["message"] and asked == []
    finally:
        gate.set()
        api._jobs.wait(5)
    assert api.quit() == {"ok": True} and asked == [1]


class CheckingFallback:
    answer = {"ok": True, "problem": None, "kbps": 256, "detail": ""}

    def __init__(self, **kw):
        pass

    def check_account(self, service, browser, profile=None):
        return dict(CheckingFallback.answer)


def test_setup_account_checks_saves_and_keeps_the_qobuz_limit(root):
    save_settings(root.settings_file, Settings(75))
    api, rec = make_api(root, fallback=CheckingFallback)
    done = wait_job(api, rec, api.setup_account("youtube", "chrome"))
    assert done.result["saved"] and done.result["check"]["message"] == "✓ YouTube Premium works (256 kbps)."
    s = load_settings(root.settings_file)
    checked = {"ok": True, "problem": None, "kbps": 256, "at": "2026-10-20T21:47:00"}
    assert s.daily_qobuz_limit == 75 and s.accounts["youtube"] == Account("chrome", 30, last_check=checked)
    assert api.setup_status()["accounts"]["youtube"] == {"browser": "chrome", "browser_name": "Chrome",
                                                         "daily_limit": 30, "profile": None, "profile_name": None,
                                                         "last_check": checked}


def test_a_saved_soundcloud_login_clears_a_stored_soundcloud_read_problem(root):
    """A you/likes line whose login SoundCloud did not accept blocks the read (login_expired, service soundcloud) until
    the user signs in again in Settings; saving that login makes the stored problem out of date."""
    api, rec = make_api(root, fallback=CheckingFallback)
    api._store.failed("login_expired", "SoundCloud didn't accept the login from Chrome.", "soundcloud")
    assert wait_job(api, rec, api.setup_account("soundcloud", "chrome")).result["saved"]
    assert api._store.problem is None
    api._store.failed("login_expired", "Qobuz is not accepted.", "qobuz")  # another service's problem stays
    assert wait_job(api, rec, api.setup_account("soundcloud", "chrome")).result["saved"]
    assert api._store.problem == "login_expired"


def test_a_saved_soundcloud_login_leaves_an_offline_problem(root):
    """A login cannot cure SoundCloud not answering: only login_expired and the likes hint are cleared."""
    api, rec = make_api(root, fallback=CheckingFallback)
    api._store.failed("offline", "SoundCloud is not responding.", "soundcloud")
    assert wait_job(api, rec, api.setup_account("soundcloud", "chrome")).result["saved"]
    assert (api._store.problem, api._store.problem_service) == ("offline", "soundcloud")


def test_a_saved_soundcloud_login_clears_the_likes_hint_only(root):
    """W8 (a likes link without the account) is cured by the login; W4/W5 (a private or removed set) are not."""
    api, rec = make_api(root, fallback=CheckingFallback)
    api._store.failed("playlist_unreadable", soundcloud.LIKES_HINT, "soundcloud")
    assert wait_job(api, rec, api.setup_account("soundcloud", "chrome")).result["saved"]
    assert api._store.problem is None
    for words in (soundcloud.UNREADABLE_SET, soundcloud.UNREADABLE_HINT):
        api._store.failed("playlist_unreadable", words, "soundcloud")
        assert wait_job(api, rec, api.setup_account("soundcloud", "chrome")).result["saved"]
        assert (api._store.problem, api._store.message) == ("playlist_unreadable", words)


def test_a_youtube_login_without_premium_is_not_saved(root):
    CheckingFallback.answer = {"ok": False, "problem": "no_premium", "kbps": 129, "detail": ""}
    try:
        api, rec = make_api(root, fallback=CheckingFallback)
        done = wait_job(api, rec, api.setup_account("youtube", "chrome"))
        assert not done.result["saved"] and "no Premium formats" in done.result["check"]["message"]
        assert dict(load_settings(root.settings_file).accounts) == {}
        done = wait_job(api, rec, api.setup_account("soundcloud", "chrome"))  # SoundCloud: saved with a note
        assert done.result["saved"]
    finally:
        CheckingFallback.answer = {"ok": True, "problem": None, "kbps": 256, "detail": ""}


def test_skip_qobuz_and_log_in_again(root):
    api, rec = make_api(root)
    wait_job(api, rec, api.setup_skip_qobuz())
    st = api.setup_status()
    assert st["qobuz_skipped"] and st["next_step"] != "downloads"
    assert load_settings(root.settings_file).qobuz_skipped


def test_forget_account(root):
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}))
    api, rec = make_api(root)
    wait_job(api, rec, api.setup_forget_account("youtube"))
    assert api.setup_status()["accounts"] == {"youtube": None, "soundcloud": None}


def test_setup_account_refuses_unknown_names(root):
    api, _ = make_api(root)
    assert api.setup_account("tidal", "chrome")["ok"] is False
    assert api.setup_account("youtube", "arc")["ok"] is False


def test_downloads_view_shows_each_source_and_the_library(root):
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30, profile="Profile 2")}))
    api, _ = make_api(root)
    d = api.downloads_view()["downloads"]
    assert d["qobuz"]["state"] in ("on", "off") and d["youtube"]["state"] == "on"
    assert d["youtube"]["profile"] == "Profile 2" and d["youtube"]["profile_name"] == "Profile 2"  # no browser files
    assert d["soundcloud"]["state"] == "off" and set(d["library"]) == {"lossless", "account", "free"}


# --- signing in through the browser (spec settings-setup §5, §7, §13) ---

from browser_helpers import chrome_cookies, local_state  # noqa: E402

from discjockey import browsers  # noqa: E402
from discjockey.hub import api as api_mod, jobs  # noqa: E402

NO_LOGIN = {"readable": True, "problem": None, "profiles": []}


@pytest.fixture
def chrome_home(tmp_path, monkeypatch):
    home = tmp_path / "home"
    local_state(home, {"Default": "Person 1", "Profile 2": "DJ"})
    (home / "Library/Application Support/Google/Chrome/Default").mkdir(parents=True, exist_ok=True)
    chrome_cookies(home, "Profile 2", [(".youtube.com", "SAPISID")])
    monkeypatch.setattr(browsers, "installed", lambda h, apps=None: ["safari", "chrome"])
    monkeypatch.setattr(browsers, "default_browser", lambda h: "chrome")
    return home


def wait_sign_in(api, rec, answer, timeout=10):
    assert answer["ok"], answer
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        f = rec.finished(answer["job_id"])
        if f is not None:
            return f
        time.sleep(0.01)
    raise AssertionError("the sign-in did not finish")


def test_find_logins_lists_installed_browsers_with_their_profiles(root, chrome_home):
    api, _ = make_api(root, home=chrome_home)
    r = api.find_logins("youtube")
    assert [b["id"] for b in r["browsers"]] == ["chrome", "safari"]  # the default browser first
    chrome = r["browsers"][0]
    assert chrome["default"] and chrome["readable"]
    assert chrome["profiles"] == [{"id": "Default", "name": "Person 1", "signed_in": False},
                                  {"id": "Profile 2", "name": "DJ", "signed_in": True}]
    assert api.find_logins("qobuz")["ok"] is False


def test_sign_in_opens_the_page_waits_then_checks_and_saves_the_profile(root, chrome_home, monkeypatch):
    polls = iter([NO_LOGIN, NO_LOGIN, NO_LOGIN, {"readable": True, "problem": None, "profiles": ["Profile 2"]}])
    monkeypatch.setattr(browsers, "logins", lambda s, b, h: next(polls))
    monkeypatch.setattr(api_mod, "_SIGN_IN_POLL", 0.01)
    api, rec = make_api(root, home=chrome_home, fallback=CheckingFallback)
    done = wait_sign_in(api, rec, api.account_sign_in("youtube", "chrome"))
    assert done.ok and done.result["saved"] and done.result["profile"] == "Profile 2"
    assert api._svc.calls["open_in"] == [("chrome", api_mod._SIGN_IN_URLS["youtube"], None)]
    assert [e.phase for e in rec.events if isinstance(e, jobs.SignInPhase)] == ["waiting", "checking"]
    a = load_settings(root.settings_file).accounts["youtube"]
    assert (a.browser, a.profile, a.last_check["ok"], a.last_check["kbps"]) == ("chrome", "Profile 2", True, 256)
    assert api.setup_status()["accounts"]["youtube"]["profile_name"] == "DJ"


def test_sign_in_does_not_block_other_hub_work(root, chrome_home, monkeypatch):
    monkeypatch.setattr(browsers, "logins", lambda s, b, h: NO_LOGIN)
    monkeypatch.setattr(api_mod, "_SIGN_IN_POLL", 0.01)
    api, rec = make_api(root, home=chrome_home)
    start = api.account_sign_in("soundcloud", "chrome")
    other = api.setup_forget_account("youtube")  # a write job while the sign-in waits
    assert other["ok"] and wait_job(api, rec, other).ok
    assert api.job_status()["sign_in"]["kind"] == "account_sign_in"
    assert api.account_sign_in("youtube", "chrome")["kind"] == "busy"  # one sign-in at a time
    assert api.stop()["stopped"] is False  # Stop is for write jobs; it never ends the sign-in
    assert api.stop_sign_in()["stopped"] is True
    done = wait_sign_in(api, rec, start)
    assert not done.ok and done.problem == "stopped"
    assert dict(load_settings(root.settings_file).accounts) == {}


def test_sign_in_times_out_and_changes_nothing(root, chrome_home, monkeypatch):
    monkeypatch.setattr(browsers, "logins", lambda s, b, h: NO_LOGIN)
    monkeypatch.setattr(api_mod, "_SIGN_IN_POLL", 0.01)
    monkeypatch.setattr(api_mod, "_SIGN_IN_TIMEOUT", 0.05)
    api, rec = make_api(root, home=chrome_home)
    done = wait_sign_in(api, rec, api.account_sign_in("youtube", "chrome"))
    assert not done.ok and done.problem == "failed" and "10 minutes" in done.message
    assert dict(load_settings(root.settings_file).accounts) == {}


def test_sign_in_with_safari_without_full_disk_access_ends_at_once(root, chrome_home, monkeypatch):
    monkeypatch.setattr(browsers, "logins", lambda s, b, h: {"readable": False, "problem": "no_access",
                                                            "profiles": []})
    api, rec = make_api(root, home=chrome_home)
    done = wait_sign_in(api, rec, api.account_sign_in("youtube", "safari"))
    assert not done.ok and "Full Disk Access" in done.message
    assert api._svc.calls["open_in"] == []  # nothing opened: it couldn't see the login anyway
    assert api.open_privacy_settings()["ok"]
    assert api._svc.calls["open_url"] == [api_mod._PRIVACY_SETTINGS]


def test_sign_in_refuses_unknown_or_missing_browsers(root, chrome_home):
    api, _ = make_api(root, home=chrome_home)
    assert api.account_sign_in("tidal", "chrome")["ok"] is False
    assert api.account_sign_in("youtube", "arc")["ok"] is False
    r = api.account_sign_in("youtube", "brave")
    assert r["ok"] is False and "isn't installed" in r["message"]


def test_a_failed_check_of_the_saved_login_is_recorded(root):
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}))
    CheckingFallback.answer = {"ok": False, "problem": "not_logged_in", "kbps": None, "detail": ""}
    try:
        api, rec = make_api(root, fallback=CheckingFallback)
        done = wait_job(api, rec, api.setup_account("youtube", "chrome"))
        assert done.ok and not done.result["saved"]
        a = load_settings(root.settings_file).accounts["youtube"]
        assert a.browser == "chrome" and a.last_check["problem"] == "not_logged_in"
        assert api.downloads_view()["downloads"]["youtube"]["state"] == "off"
    finally:
        CheckingFallback.answer = {"ok": True, "problem": None, "kbps": 256, "detail": ""}


def test_check_account_stores_the_last_check(root):
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30, profile="Profile 2")}))
    api, _ = make_api(root, fallback=CheckingFallback)
    assert api.setup_check_account("youtube")["ok"]
    assert load_settings(root.settings_file).accounts["youtube"].last_check["kbps"] == 256


class QobuzCheckSource:
    def __init__(self, hits=None, error=None):
        self.hits, self.error = hits, error

    def search(self, query, limit=10):
        if self.error:
            raise self.error
        return self.hits

    def close(self):
        pass


def test_qobuz_check_login_records_the_outcome(root):
    api, rec = make_api(root, open_qobuz=lambda p: QobuzCheckSource(["hit"]))
    assert wait_job(api, rec, api.qobuz_check_login()).ok
    assert load_settings(root.settings_file).qobuz_last_check["ok"] is True
    api._store.failed("not_set_up", "Connect Qobuz first.", "qobuz")  # a good check clears the stored read problem...
    assert wait_job(api, rec, api.qobuz_check_login()).ok and api._store.problem is None

    def refuse(p):
        raise qobuz.QobuzLoginRejected("Qobuz did not accept your login. Run: discjockey setup")

    api, rec = make_api(root, open_qobuz=refuse)
    api._store.failed("not_set_up", "Connect Qobuz first.", "qobuz")
    done = wait_job(api, rec, api.qobuz_check_login())
    assert not done.ok and done.message == "Qobuz did not accept your login. Run: discjockey setup"
    assert load_settings(root.settings_file).qobuz_last_check["problem"] == "login_failed"
    assert api._store.problem == "not_set_up"  # ...a refused one doesn't


def test_qobuz_check_login_logged_in_but_the_search_finds_nothing(root):
    api, rec = make_api(root, open_qobuz=lambda p: QobuzCheckSource([]))
    done = wait_job(api, rec, api.qobuz_check_login())
    assert not done.ok and done.problem == "failed" and "found nothing" in done.message
    last = load_settings(root.settings_file).qobuz_last_check
    assert (last["ok"], last["problem"]) == (False, "search_failed")


@pytest.mark.parametrize("where", ["open", "search", "plain"])
def test_qobuz_check_login_offline_records_no_check(root, where):
    # being offline or a Qobuz hiccup says nothing about the login: the last check stays, Qobuz isn't shown signed out
    save_settings(root.settings_file, Settings(qobuz_last_check={"ok": True, "problem": None, "kbps": None,
                                                                 "at": "2026-10-19T10:00:00"}))

    def opening(p):
        if where == "open":
            raise qobuz.QobuzError("Could not log in to Qobuz (ClientConnectorError). Check the internet connection")
        if where == "search":
            return QobuzCheckSource(error=qobuz.QobuzError("Qobuz did not answer within 30 seconds"))
        return QobuzCheckSource(error=OSError("Network is unreachable"))

    api, rec = make_api(root, open_qobuz=opening)
    done = wait_job(api, rec, api.qobuz_check_login())
    assert not done.ok and done.problem == "failed"
    assert {"open": "internet connection", "search": "did not answer",
            "plain": "Couldn't reach Qobuz"}[where] in done.message
    assert load_settings(root.settings_file).qobuz_last_check["at"] == "2026-10-19T10:00:00"


def test_spotify_sign_out_keeps_the_client_id_and_saves_the_name_at_login(root):
    root.spotify_app.write_text(json.dumps({"client_id": "a" * 32, "user": "DJ One"}))
    root.spotify_token.write_text('{"refresh_token": "r"}')
    api, rec = make_api(root)
    assert api.setup_status()["spotify_user"] == "DJ One"
    assert wait_job(api, rec, api.spotify_sign_out()).ok
    st = api.setup_status()
    assert st["spotify_app"] and not st["spotify_login"] and st["spotify_user"] is None
    assert json.loads(root.spotify_app.read_text()) == {"client_id": "a" * 32}


# --- the sign-in slot and the one-writer rule (spec settings-setup §13) ---

class NoCheckFallback:
    def __init__(self, **kw):
        pass

    def check_account(self, service, browser, profile=None):
        pytest.fail("no account check beside a sync")


def switchable_logins(monkeypatch):
    """browsers.logins that finds nothing until seen["profiles"] is set."""
    seen = {"profiles": []}
    monkeypatch.setattr(browsers, "logins",
                        lambda s, b, h: {"readable": True, "problem": None, "profiles": list(seen["profiles"])})
    monkeypatch.setattr(api_mod, "_SIGN_IN_POLL", 0.01)
    return seen


def wait_for(cond, timeout=5):
    end = time.monotonic() + timeout
    while not cond():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.01)


def waiting_phase(rec):
    return any(isinstance(e, jobs.SignInPhase) and e.phase == "waiting" for e in rec.events)


def test_a_sign_in_that_ends_during_a_hub_sync_does_not_check(root, chrome_home, monkeypatch):
    seen = switchable_logins(monkeypatch)
    api, rec = make_api(root, home=chrome_home, fallback=NoCheckFallback)
    start = api.account_sign_in("youtube", "chrome")
    wait_for(lambda: waiting_phase(rec))
    release = threading.Event()
    sync = api._jobs.start("sync", lambda ctx: release.wait(5) and None)  # the user starts a sync meanwhile
    try:
        seen["profiles"] = ["Profile 2"]
        done = wait_sign_in(api, rec, start)
        assert not done.ok and done.problem == "sync_running" and "Check again after the sync" in done.message
        assert [e.phase for e in rec.events if isinstance(e, jobs.SignInPhase)] == ["waiting"]
    finally:
        release.set()
        assert sync.done.wait(5)
    assert dict(load_settings(root.settings_file).accounts) == {}


def test_a_sign_in_that_ends_during_a_console_run_does_not_check(root, chrome_home, monkeypatch):
    seen = switchable_logins(monkeypatch)
    api, rec = make_api(root, home=chrome_home, fallback=NoCheckFallback)
    start = api.account_sign_in("youtube", "chrome")
    wait_for(lambda: waiting_phase(rec))
    with run_lock(root.lock):  # a terminal run started meanwhile
        seen["profiles"] = ["Profile 2"]
        done = wait_sign_in(api, rec, start)
    assert not done.ok and done.problem == "sync_running"
    assert dict(load_settings(root.settings_file).accounts) == {}


def test_a_sign_in_save_never_races_a_write_job(root, chrome_home, monkeypatch):
    # the write job holds the engine lock and changes settings itself: the sign-in's save must not overwrite it
    seen = switchable_logins(monkeypatch)
    save_settings(root.settings_file, Settings(75))
    api, rec = make_api(root, home=chrome_home, fallback=CheckingFallback)
    start = api.account_sign_in("youtube", "chrome")
    wait_for(lambda: waiting_phase(rec))
    release = threading.Event()

    def save_limit(ctx):
        release.wait(5)
        api._update_settings(lambda s: s.with_limit("qobuz", 90, None, 0))  # inside the job: no deadlock
        return {}

    job = api._jobs.start("save_limits", save_limit)
    seen["profiles"] = ["Profile 2"]
    done = wait_sign_in(api, rec, start)
    release.set()
    assert job.done.wait(5) and rec.finished(job.id).ok
    assert not done.ok and done.problem == "busy" and "couldn't save it" in done.message
    s = load_settings(root.settings_file)
    assert s.daily_qobuz_limit == 90 and dict(s.accounts) == {}


def test_check_account_from_the_page_answers_busy_while_a_write_job_holds_the_lock(root):
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}))
    api, _ = make_api(root, fallback=CheckingFallback)
    release = threading.Event()
    job = api._jobs.start("save_limits", lambda ctx: release.wait(5) and None)
    try:
        r = api.setup_check_account("youtube")
        assert r["ok"] is False and r["kind"] == "busy"
    finally:
        release.set()
        assert job.done.wait(5)
    assert load_settings(root.settings_file).accounts["youtube"].last_check is None
    assert api.setup_check_account("youtube")["ok"]  # fine again afterwards


def test_sign_in_with_firefox_accepts_a_login_in_any_profile(root, chrome_home, monkeypatch):
    # Firefox can't be told which profile to open: the page opens in its default one, so any login counts
    monkeypatch.setattr(browsers, "installed", lambda h, apps=None: ["firefox", "chrome"])
    polls = iter([NO_LOGIN, {"readable": True, "problem": None, "profiles": ["abc.default-release"]}])
    monkeypatch.setattr(browsers, "logins", lambda s, b, h: next(polls))
    monkeypatch.setattr(api_mod, "_SIGN_IN_POLL", 0.01)
    api, rec = make_api(root, home=chrome_home, fallback=CheckingFallback)
    done = wait_sign_in(api, rec, api.account_sign_in("youtube", "firefox", "xyz.dj"))
    assert done.ok and done.result["saved"] and done.result["profile"] == "abc.default-release"
    a = load_settings(root.settings_file).accounts["youtube"]
    assert (a.browser, a.profile) == ("firefox", "abc.default-release")


def test_sign_in_prefers_the_chosen_profile_and_chromium_waits_for_it(root, chrome_home, monkeypatch):
    monkeypatch.setattr(browsers, "installed", lambda h, apps=None: ["firefox", "chrome"])
    monkeypatch.setattr(browsers, "logins",
                        lambda s, b, h: {"readable": True, "problem": None, "profiles": ["a.default", "b.dj"]})
    monkeypatch.setattr(api_mod, "_SIGN_IN_POLL", 0.01)
    api, rec = make_api(root, home=chrome_home, fallback=CheckingFallback)
    assert wait_sign_in(api, rec, api.account_sign_in("youtube", "firefox", "b.dj")).result["profile"] == "b.dj"

    monkeypatch.setattr(browsers, "logins",
                        lambda s, b, h: {"readable": True, "problem": None, "profiles": ["Default"]})
    monkeypatch.setattr(api_mod, "_SIGN_IN_TIMEOUT", 0.05)
    done = wait_sign_in(api, rec, api.account_sign_in("soundcloud", "chrome", "Profile 2"))
    assert not done.ok and "10 minutes" in done.message  # Chrome opened Profile 2's window: only its login counts


def test_open_in_opens_a_chosen_chromium_profile_in_its_own_window(monkeypatch):
    runs = []
    monkeypatch.setattr(api_mod.subprocess, "run", lambda cmd, check: runs.append(cmd))
    api_mod._open_in("chrome", "https://music.youtube.com", "Profile 2")
    api_mod._open_in("brave", "https://soundcloud.com", None)
    api_mod._open_in("firefox", "https://soundcloud.com", "xyz.dj")
    assert runs == [
        ["open", "-na", "Google Chrome", "--args", "--profile-directory=Profile 2", "https://music.youtube.com"],
        ["open", "-a", "Brave Browser", "https://soundcloud.com"],
        ["open", "-a", "Firefox", "https://soundcloud.com"],
    ]


def test_skip_spotify_and_connect_it_later(root, monkeypatch):
    api, rec = make_api(root)
    assert api.setup_status()["next_step"] == "spotify" and not api.setup_status()["spotify_skipped"]
    assert wait_job(api, rec, api.setup_skip_spotify()).ok
    st = api.setup_status()
    assert st["spotify_skipped"] and not st["spotify_login"] and st["next_step"] != "spotify"
    assert load_settings(root.settings_file).spotify_skipped
    root.spotify_app.write_text(json.dumps({"client_id": "0" * 32}))
    monkeypatch.setattr(spotify, "login", lambda *a, **k: None)
    monkeypatch.setattr(spotify, "load_session", lambda paths: None)
    monkeypatch.setattr(spotify, "current_user", lambda session: ("id", "DJ One"))
    assert wait_job(api, rec, api.setup_spotify_login()).ok
    assert not load_settings(root.settings_file).spotify_skipped


def test_the_existing_music_step_is_done_by_a_folder_or_a_skip_and_never_blocks(tmp_path, monkeypatch):
    from datetime import datetime
    from hub_helpers import import_folder, music_root
    from discjockey import db
    paths = music_root(tmp_path)
    api, rec = make_api(paths)
    st = api.setup_status()
    assert (st["existing"], st["import_folders"], st["import_skipped"]) == (False, 0, False)
    required = (st["complete"], st["next_step"])
    assert api.setup_skip_import() == {"ok": True}  # a brief save, not a job
    assert rec.events == [] and load_settings(paths.settings_file).import_skipped
    st = api.setup_status()
    assert (st["existing"], st["import_folders"], st["import_skipped"]) == (True, 0, True)
    assert (st["complete"], st["next_step"]) == required  # the required steps are the same either way
    save_settings(paths.settings_file, Settings())
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, import_folder(tmp_path, 1), datetime(2026, 10, 20))
    st = api.setup_status()
    assert (st["existing"], st["import_folders"], st["import_skipped"]) == (True, 1, False)
    assert (st["complete"], st["next_step"]) == required


def test_the_existing_music_step_without_a_music_folder_and_while_a_job_writes(tmp_path):
    api, rec = make_unbound_api(tmp_path / "support")
    st = api.setup_status()
    assert (st["existing"], st["import_folders"]) == (False, 0) and st["next_step"] == "music"
    assert api.setup_skip_import() == {"ok": True}  # Setup's skip works before the library is bound too
    assert api.setup_status()["existing"] is True


def test_skipping_the_existing_music_step_waits_for_a_running_job(root):
    api, rec = make_api(root)
    gate = threading.Event()
    api._jobs.start("x", lambda ctx: gate.wait(5))
    try:
        r = api.setup_skip_import()
        assert (r["ok"], r["kind"]) == (False, "busy") and not load_settings(root.settings_file).import_skipped
    finally:
        gate.set()
        api._jobs.wait(5)
    assert api.setup_skip_import() == {"ok": True}
