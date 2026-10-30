import json
import threading
import time

import pytest
from hub_helpers import choose_music, fake_spotify, make_root

import discjockey.cli as cli
from discjockey import library
from discjockey.hub import app, jobs
from discjockey.hub.api import HubApi
from discjockey.hub.window_port import window_port
from discjockey.library import Paths, Resolved, run_lock


class Hooks(list):
    def __iadd__(self, fn):
        self.append(fn)
        return self

    def fire(self):
        return [fn() for fn in list(self)]


class FakeElementEvents:
    def __init__(self):
        self.handlers = {}

    def __getattr__(self, name):
        return self.handlers.setdefault(name, Hooks())

    def __setattr__(self, name, value):
        if name == "handlers":
            object.__setattr__(self, name, value)
        else:
            self.handlers[name] = value


class FakeWindow:
    """The parts of a pywebview window the hub uses; the dialog answers from a script."""

    def __init__(self, answers=()):
        self.events = type("E", (), {})()
        for name in ("closing", "loaded", "closed", "before_show"):
            setattr(self.events, name, Hooks())
        self.answers = list(answers)
        self.asked = []
        self.destroyed = threading.Event()
        self.scripts = []
        self.dom = type("D", (), {})()
        self.dom.document = type("Doc", (), {"events": FakeElementEvents()})()
        self.dom.elements = {}
        self.dom.get_element = lambda selector: self.dom.elements.setdefault(
            selector, type("El", (), {"events": FakeElementEvents()})())

    def create_confirmation_dialog(self, title, message):
        self.asked.append(message)
        answer = self.answers.pop(0)
        if isinstance(answer, threading.Event):  # the user takes a while
            answer.wait(5)
            return True
        return answer

    def destroy(self):
        self.destroyed.set()

    def show(self):
        self.shown = getattr(self, "shown", 0) + 1

    def evaluate_js(self, script):
        self.scripts.append(script)


class SlowJobs:
    """A write job that stops when asked (like a sync between two steps)."""

    def __init__(self):
        self.token = threading.Event()
        self.ended = threading.Event()
        self.stopped = False

    def running(self):
        return None if self.ended.is_set() else object()

    def stop(self):
        self.stopped = True
        threading.Timer(0.1, self.ended.set).start()
        return True

    def wait(self, timeout=None):
        return self.ended.wait(timeout)


def test_closing_without_a_job_closes_at_once():
    jobs_ = SlowJobs()
    jobs_.ended.set()
    assert app.CloseFlow(jobs_, lambda: FakeWindow()).on_closing() is True


def test_closing_during_a_job_asks_and_stops_safely_then_quits():
    jobs_, window = SlowJobs(), FakeWindow([True])
    flow = app.CloseFlow(jobs_, lambda: window)
    started = time.monotonic()
    assert flow.on_closing() is False and time.monotonic() - started < 0.05  # never waits on the main thread
    assert window.destroyed.wait(5)
    assert jobs_.stopped and jobs_.ended.is_set() and window.asked == [app.CLOSE_QUESTION]
    assert flow.on_closing() is True  # if pywebview asks again, the close goes through


def test_keep_the_window_open():
    jobs_, window = SlowJobs(), FakeWindow([False])
    flow = app.CloseFlow(jobs_, lambda: window)
    assert flow.on_closing() is False
    time.sleep(0.2)
    assert not jobs_.stopped and not window.destroyed.is_set()
    window.answers.append(True)
    assert flow.on_closing() is False  # asked again later
    assert window.destroyed.wait(5)


def test_cmd_q_while_the_question_is_open_does_not_ask_twice():
    """⌘Q goes through the same closing handler (pywebview's applicationShouldTerminate_)."""
    jobs_, slow = SlowJobs(), threading.Event()
    window = FakeWindow([slow])
    flow = app.CloseFlow(jobs_, lambda: window)
    assert flow.on_closing() is False
    time.sleep(0.05)
    assert flow.on_closing() is False  # ⌘Q pressed while the dialog is still open
    slow.set()
    assert window.destroyed.wait(5) and len(window.asked) == 1


def test_close_flow_with_the_real_jobs(tmp_path):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    paths.data.mkdir()
    js = jobs.Jobs(paths.lock, lambda e: None, keep_awake=lambda reason: _Null())

    def work(ctx):
        while True:
            ctx.token.check()
            time.sleep(0.01)

    js.start("sync", work)
    window = FakeWindow([True])
    assert app.CloseFlow(js, lambda: window).on_closing() is False
    assert window.destroyed.wait(5) and js.running() is None


class _Null:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeHandler:
    def __init__(self, fn, prevent_default=False):
        self.fn, self.prevent_default = fn, prevent_default


def test_the_drop_handler_sits_on_the_empty_drop_catcher_not_on_the_document(tmp_path):
    # pywebview sends the whole event to Python, its element and everything inside it included: a handler on the
    # document sent the whole page (3-80 MB, 0.2-4 s each) on every dragover, which froze the window during a drag
    api = HubApi(tmp_path / "support")
    window = FakeWindow()
    app.register_drop(window, api, FakeHandler)
    assert window.dom.document.events.handlers == {}
    handlers = window.dom.elements["#drop-catcher"].events.handlers
    assert set(handlers) == {"drop"}
    assert handlers["drop"][0].fn == api._on_drop and handlers["drop"][0].prevent_default


class FakeWebview:
    def __init__(self, window):
        self.window, self.created, self.started = window, None, None

    def create_window(self, title, **kw):
        self.created = {"title": title, **kw}
        return self.window

    def start(self, **kw):
        self.started = kw
        self.window.events.loaded.fire()
        assert self.window.events.closing.fire() == [True]  # nothing runs: closes at once
        self.window.events.closed.fire()


def test_main_makes_the_window(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    window = FakeWindow()
    web = FakeWebview(window)
    assert app.main(Resolved(paths.support, paths, None, paths.root), webview=web) == 0
    c = web.created
    assert c["title"] == "Discjockey" and (c["width"], c["height"]) == (1280, 800) and c["min_size"] == (1100, 700)
    assert c["background_color"] == "#000000" and c["url"] == f"{app.STATIC}?v={app.STATIC.stat().st_mtime_ns}"
    assert c["hidden"] is True and window.shown == 1  # shown once the page has loaded
    assert isinstance(c["js_api"], HubApi) and c["localization"]["global.ok"] == "Stop safely and quit"
    assert web.started["private_mode"] is False and web.started["http_server"] is True
    assert web.started["storage_path"] == str(paths.cache / "webview")
    assert web.started["http_port"] == json.loads((paths.support / "window.json").read_text())["port"]
    # the media server lets the page's own origin (the window's port) read the files, for the compare player
    assert c["js_api"]._media.page_origin == f"http://127.0.0.1:{web.started['http_port']}"
    # the window is closed: the lock is let go, so the next window is the first again
    again = window_port(paths.support, free=lambda p: True)
    assert again.kept and again.lock is not None
    again.release()
    assert set(window.dom.elements["#drop-catcher"].events.handlers) == {"drop"}


class RaisingWebview(FakeWebview):
    def start(self, **kw):
        self.started = kw
        raise RuntimeError("the window could not start")


def test_main_lets_go_of_the_window_lock_when_the_window_fails_to_start(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    with pytest.raises(RuntimeError, match="could not start"):
        app.main(Resolved(paths.support, paths, None, paths.root), webview=RaisingWebview(FakeWindow()))
    again = window_port(paths.support, free=lambda p: True)  # the lock is free: this window is the first again
    assert again.lock is not None
    again.release()


@pytest.fixture(autouse=True)
def no_update_watch(monkeypatch):
    """app.main starts the hourly update watcher; FakeWebview never closes, so no test keeps a thread waiting.
    (test_main_starts_the_update_check counts the start itself.)"""
    monkeypatch.setattr(HubApi, "_watch_app_update", lambda self, interval=3600.0: None)


def test_main_starts_the_update_check(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    started = []
    monkeypatch.setattr(HubApi, "_watch_app_update", lambda self, interval=3600.0: started.append(self))
    app.main(Resolved(paths.support, paths, None, paths.root), webview=FakeWebview(FakeWindow()))
    assert len(started) == 1


def test_the_window_shows_once_on_load_or_after_the_timeout():
    window = FakeWindow()
    show = app.ShowOnce(window)
    show()
    show()  # the late timer after the page already loaded
    assert window.shown == 1


def test_main_reads_spotify_once_by_itself_when_it_opens(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    window = FakeWindow()
    seen = []
    monkeypatch.setattr(HubApi, "refresh", lambda self, auto=False: seen.append(("refresh", auto)) or {"ok": True})
    app.main(Resolved(paths.support, paths, None, paths.root), webview=FakeWebview(window))
    assert seen == [("refresh", True)]  # the session's one automatic read


def test_discjockey_hub_opens_the_window_in_its_own_process_without_holding_the_lock(tmp_path, monkeypatch):
    choose_music(tmp_path, monkeypatch)
    opened = []

    def fake_main(resolved):
        with run_lock(resolved.paths.lock):  # free: the hub only takes it for each change
            opened.append(resolved.paths.root)
        return 0

    monkeypatch.setattr(app, "main", fake_main)
    assert cli.parse_args(["hub"]).command == "hub"
    assert cli.main(["hub"]) == 0 and opened == [tmp_path]


def test_the_launcher_starts_the_hub_without_caffeinate():
    text = (__import__("pathlib").Path(__file__).parents[1] / "bin" / "discjockey").read_text()
    hub = text.index('if [ "$1" = "hub" ]; then')
    assert 'exec "$DIR/.venv/bin/python" -m discjockey "$@"' in text[hub:text.index("fi", hub)]


def test_the_placeholder_page_prevents_the_browser_default_on_drop():
    page = app.STATIC.read_text()
    assert "dragover" in page and "preventDefault" in page and "window.dj" in page
    assert '<div id="drop-catcher"></div>' in page and "#drop-catcher.on" in page


def test_setting_the_app_name_never_fails():
    app.set_app_name("Discjockey")  # with or without pyobjc


class FakeFeature:
    def __init__(self, key):
        self._key = key

    def key(self):
        return self._key


def fake_prefs(keys, on=None):
    on = {} if on is None else on

    class Prefs:
        @classmethod
        def _features(cls):
            return [FakeFeature(k) for k in keys]

        def _setEnabled_forFeature_(self, value, feature):
            on[feature.key()] = value

    return Prefs()


def test_the_60_fps_page_cap_is_turned_off(monkeypatch):
    on = {}
    monkeypatch.setattr(app.sys, "platform", "darwin")
    monkeypatch.setattr(app, "_view_preferences", lambda window: fake_prefs(["Other", app.FRAME_CAP_FEATURE], on))
    app.render_at_display_rate(FakeWindow())
    assert on == {app.FRAME_CAP_FEATURE: False}  # only that feature, and only off


def test_the_frame_cap_does_nothing_when_a_piece_is_missing(monkeypatch):
    monkeypatch.setattr(app.sys, "platform", "darwin")
    on = {}
    monkeypatch.setattr(app, "_view_preferences", lambda window: fake_prefs(["Other"], on))
    app.render_at_display_rate(FakeWindow())  # WebKit renamed the feature
    assert on == {}

    class NoSelector:
        pass

    monkeypatch.setattr(app, "_view_preferences", lambda window: NoSelector())
    app.render_at_display_rate(FakeWindow())  # no _features selector

    def no_webkit(window):
        raise ModuleNotFoundError("webview.platforms.cocoa")

    monkeypatch.setattr(app, "_view_preferences", no_webkit)
    app.render_at_display_rate(FakeWindow())
    monkeypatch.undo()
    app.render_at_display_rate(FakeWindow())  # the real lookup: this fake has no view behind it


def test_the_frame_cap_is_left_alone_off_macos(monkeypatch):
    on = {}
    monkeypatch.setattr(app.sys, "platform", "linux")
    monkeypatch.setattr(app, "_view_preferences", lambda window: fake_prefs([app.FRAME_CAP_FEATURE], on))
    app.render_at_display_rate(FakeWindow())
    assert on == {}


def test_main_lifts_the_frame_cap_before_the_window_shows(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    window = FakeWindow()
    seen = []
    monkeypatch.setattr(app, "render_at_display_rate", lambda w: seen.append(w))
    app.main(Resolved(paths.support, paths, None, paths.root), webview=FakeWebview(window))
    assert window.events.before_show.fire() == [None] and seen == [window]


def test_quit_from_the_page_destroys_the_window(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    window = FakeWindow()
    web = FakeWebview(window)
    app.main(Resolved(paths.support, paths, None, paths.root), webview=web)
    window.destroyed.clear()
    assert web.created["js_api"].quit()["ok"]
    assert window.destroyed.wait(5)


def test_main_without_a_music_folder_starts_nothing_of_the_library(tmp_path, monkeypatch):
    seen = []
    monkeypatch.setattr(HubApi, "refresh", lambda self, auto=False: seen.append("refresh") or {"ok": True})
    monkeypatch.setattr(jobs.Jobs, "watch_console", lambda self, interval=3.0: seen.append("watch"))
    web = FakeWebview(FakeWindow())
    support = tmp_path / "support"
    assert app.main(library.resolve_in(support), webview=web) == 0
    assert seen == [] and web.started["storage_path"] == str(support / "cache" / "webview")
    api = web.created["js_api"]
    assert api.setup_status()["music"]["state"] == "not_chosen" and api._svc.pick_folder is not None


def test_folder_dialog_returns_the_chosen_folder():
    class Win:
        def create_file_dialog(self, kind, directory=""):
            self.asked = (kind, directory)
            return ("/Users/dj/Music/DJ",)
    class Web:
        class FileDialog:
            FOLDER = 20
    w = Win()
    assert app.folder_dialog(w, Web, "/Users/dj/Music") == "/Users/dj/Music/DJ" and w.asked == (20, "/Users/dj/Music")
