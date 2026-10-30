"""The hub window (spec "hub" 6.2, 6.5, 6.6, 6.10): pywebview on the main thread, its own page-server port
(window_port.py), the bridge, the audio server, the music folder dialog, the close flow and drag and drop. Started
with `discjockey hub` (or Discjockey.app, which runs that in the background)."""
from __future__ import annotations

import importlib
import logging
import os
import sys
import threading
from pathlib import Path

from ..library import Resolved, SupportPaths
from .api import HubApi
from .jobs import HubEvents
from .media import MediaServer
from .window_port import window_port

TITLE = "Discjockey"
SIZE = (1280, 800)
MIN_SIZE = (1100, 700)
BACKGROUND = "#000000"
SHOW_AT_LATEST = 3.0  # seconds: the window starts hidden and shows once the page has loaded, or after this anyway
STATIC = Path(__file__).parent / "static" / "index.html"
ICON = Path(__file__).parent / "icon" / "discjockey.icns"


def page_url() -> str:
    """The page with its build time as a query: WebKit kept serving a cached index.html after a rebuild (and with it
    the old bundle), so every build gets an address of its own."""
    return f"{STATIC}?v={STATIC.stat().st_mtime_ns}"
CLOSE_QUESTION = ("Discjockey is still changing your library. Stop safely and quit? The current track is finished or "
                  "cleanly discarded; the next sync goes on from there.")
DIALOG_BUTTONS = {"global.ok": "Stop safely and quit", "global.cancel": "Keep the window open"}


class CloseFlow:
    """Closing the window or ⌘Q while a write job runs (both go through pywebview's `closing` event): say "don't
    close" at once and ask from another thread, so the main thread never waits. "Stop safely and quit" sets the job's
    stop flag; when the job has ended, the window is destroyed (destroy() does not fire `closing` again)."""

    def __init__(self, jobs, window):
        self.jobs, self.window = jobs, window  # window: () -> the pywebview window
        self.allowed = False
        self._asking = threading.Lock()

    def on_closing(self) -> bool:
        if self.allowed or self.jobs.running() is None:
            return True
        if self._asking.acquire(blocking=False):  # one question at a time
            threading.Thread(target=self._ask, name="hub-close", daemon=True).start()
        return False

    def _ask(self) -> None:
        try:
            window = self.window()
            if not window.create_confirmation_dialog(TITLE, CLOSE_QUESTION):
                return  # keep the window open; the job goes on
            self.jobs.stop()
            self.jobs.wait()
            self.allowed = True
            window.destroy()
        finally:
            self._asking.release()


class ShowOnce:
    """The window starts hidden, so it never flashes grey before the black page is there. It shows on the first
    `loaded`, or after SHOW_AT_LATEST seconds if the page is slow, never twice."""

    def __init__(self, window):
        self.window = window
        self._done = threading.Lock()

    def __call__(self) -> None:
        if self._done.acquire(blocking=False):
            self.window.show()


def register_drop(window, api: HubApi, handler_class) -> None:
    """On every page load: the drop handler on #drop-catcher, an empty element over the whole window that the page
    makes hittable only while a file is dragged (hub-ui/src/lib/stores/drag.ts). pywebview sends each event to Python
    with the element it sits on and everything inside it; on the document that was the whole page on every dragover
    (3-80 MB, 0.2-4 s each), and the window froze. The page itself prevents the browser default on dragover and drop
    (index.html), so WebKit never opens the dropped file. pywebview fills pywebviewFullPath."""
    catcher = window.dom.get_element("#drop-catcher") or window.dom.document  # an old page: slow, but it works
    catcher.events.drop += handler_class(api._on_drop, prevent_default=True)


def set_app_name(name: str, icon: Path | None = None) -> None:
    """The name in the menu bar, and the Dock icon when the hub runs outside Discjockey.app (a checkout's
    `bin/discjockey hub`)."""
    try:
        from Foundation import NSBundle
        bundle_ = NSBundle.mainBundle()
        info = bundle_.localizedInfoDictionary() or bundle_.infoDictionary()
        info["CFBundleName"] = name
        if icon is not None and icon.exists():
            from AppKit import NSApplication, NSImage
            image = NSImage.alloc().initWithContentsOfFile_(str(icon))
            if image is not None:
                NSApplication.sharedApplication().setApplicationIconImage_(image)
    except Exception:
        pass


FRAME_CAP_FEATURE = "PreferPageRenderingUpdatesNear60FPSEnabled"  # WebKit's own switch for the ~60 fps page cap


def _view_preferences(window):
    """The WKPreferences of this window's WKWebView (pywebview keeps the view in its cocoa BrowserView)."""
    cocoa = importlib.import_module("webview.platforms.cocoa")
    return cocoa.BrowserView.instances[window.uid].webview.configuration().preferences()


def render_at_display_rate(window) -> None:
    """WKWebView caps page rendering near 60 fps by default; turn that internal feature off so a ProMotion display
    animates at its full rate. Runs on pywebview's `before_show` (the view exists, the page has not loaded yet).
    Only a nicety: any missing piece (not macOS, no WebKit, WebKit renamed the feature) does nothing."""
    try:
        if sys.platform != "darwin":
            return
        prefs = _view_preferences(window)
        feature = next((f for f in type(prefs)._features() if f.key() == FRAME_CAP_FEATURE), None)
        if feature is not None:
            prefs._setEnabled_forFeature_(False, feature)
    except Exception:
        logging.getLogger(__name__).debug("could not lift the 60 fps page cap", exc_info=True)


def folder_dialog(window, webview, start: str) -> str | None:
    """pywebview's native folder dialog (works from a bridge thread; proven in the frozen app by the packaging
    spike). The chosen folder, or None when cancelled."""
    picked = window.create_file_dialog(webview.FileDialog.FOLDER, directory=start)
    return str(picked[0]) if picked else None


def main(resolved: Resolved, webview=None) -> int:
    webview = webview or importlib.import_module("webview")
    handler_class = importlib.import_module("webview.dom").DOMEventHandler

    holder: dict = {}
    events = HubEvents(lambda: holder.get("window"))
    media = MediaServer()
    api = HubApi(resolved.support, events, media=media)
    window = webview.create_window(TITLE, url=page_url(), js_api=api, width=SIZE[0], height=SIZE[1],
                                   min_size=MIN_SIZE, background_color=BACKGROUND, localization=DIALOG_BUTTONS,
                                   hidden=True)
    holder["window"] = window
    api._svc.pick_folder = lambda start: folder_dialog(window, webview, start)
    show = ShowOnce(window)
    window.events.before_show += lambda: render_at_display_rate(window)
    window.events.loaded += show
    threading.Timer(SHOW_AT_LATEST, show).start()
    api._quit = lambda: threading.Timer(0.3, window.destroy).start()  # the page gets its answer first
    close = CloseFlow(api._jobs, lambda: window)
    window.events.closing += close.on_closing
    window.events.loaded += lambda: register_drop(window, api, handler_class)

    def closed() -> None:
        holder.pop("window", None)
        events.stop()
        api._jobs.close()
        media.stop()

    window.events.closed += closed
    set_app_name(TITLE, ICON)
    media.start()
    events.start()
    api._watch_app_update()  # spec public-release §8
    api._start(resolved)  # the library's services, when the music folder is there (else Setup / the missing screen)
    storage = SupportPaths(support=resolved.support).cache / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    port = window_port(resolved.support)  # issue 17: our own port, the same at every start
    try:
        webview.start(private_mode=False, storage_path=str(storage), http_server=True, http_port=port.port,
                      debug=bool(os.environ.get("DISCJOCKEY_HUB_DEBUG")))
        api._jobs.wait()  # the close flow only lets the window go once the job has ended
    finally:
        port.release()
    return 0
