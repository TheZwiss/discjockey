import json
import threading
import time
from datetime import datetime

from discjockey.acquire import AcquireResult, Ready
from discjockey.events import ActionFinished, CancelToken, Message, Progress, Waiting
from discjockey.execute import Executor
from discjockey.hub.jobs import HubEvents
from discjockey.library import Paths, empty_state
from discjockey.models import Action, SpotifyTrack
from discjockey.report import RunLog


class FakeWindow:
    """Records what the hub asks the page to run."""

    def __init__(self):
        self.scripts = []

    def evaluate_js(self, script):
        self.scripts.append(script)

    def events(self):
        return [json.loads(s[len("window.dj && window.dj.onEvent("):-1]) for s in self.scripts]


class RaisingWindow(FakeWindow):
    def evaluate_js(self, script):
        super().evaluate_js(script)
        raise RuntimeError("the page is not ready yet")


class BlockingWindow(FakeWindow):
    """Like pywebview's evaluate_js while the main thread is busy: it waits."""

    def __init__(self):
        super().__init__()
        self.release = threading.Event()

    def evaluate_js(self, script):
        self.release.wait(10)
        super().evaluate_js(script)


def wait_for(cond, timeout=3):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def test_events_reach_the_page_in_order():
    window = FakeWindow()
    hub = HubEvents(lambda: window)
    hub.start()
    hub.emit(Message("info", "one"))
    hub.emit(Message("info", "two"))
    assert wait_for(lambda: len(window.scripts) == 2)
    assert [e["text"] for e in window.events()] == ["one", "two"]
    assert window.scripts[0].startswith("window.dj && window.dj.onEvent({")
    hub.stop()


def test_only_the_latest_progress_and_pause_are_sent_when_the_page_lags():
    window = BlockingWindow()
    hub = HubEvents(lambda: window)
    hub.start()
    hub.emit(Message("info", "first"))  # the dispatcher waits on the page with this one
    assert wait_for(lambda: hub.pending() == 0)
    for i in range(100):
        hub.emit(Progress("t1", "download", i, 99, "bytes"))
    hub.emit(Progress("t2", "download", 5, 9, "bytes"))
    for left in (3.0, 2.0, 1.0):
        hub.emit(Waiting("between", "Protection pause", left, 40))
    hub.emit(Message("info", "last"))
    assert hub.pending() == 4
    window.release.set()
    assert wait_for(lambda: len(window.scripts) == 5)
    sent = window.events()
    assert [(e["type"], e.get("done"), e.get("remaining")) for e in sent[1:4]] == [
        ("Progress", 99, None), ("Progress", 5, None), ("Waiting", None, 1.0)]
    hub.stop()


def test_a_window_that_raises_or_is_gone_is_ignored():
    hub = HubEvents(lambda: RaisingWindow())
    hub.start()
    hub.emit(Message("info", "x"))
    gone = HubEvents(lambda: None)
    gone.start()
    gone.emit(Message("info", "x"))
    hub.stop()
    gone.stop()


def run_engine(tmp_path, emit, n=30):
    """The real execution loop with a fake download that reports progress through `emit`."""
    class Acq:
        def acquire(self, track, rejected, workdir, lossless_only, tracker):
            for i in range(20):
                tracker.progress(i, 19, "bytes")
            f = workdir / "q.aiff"
            f.write_bytes(b"audio")
            return AcquireResult("ready", Ready(f, "lossless", "qobuz", track.id, "flac", None, "ok"))

    paths = Paths(tmp_path, support=tmp_path / ".support")
    paths.library.mkdir()
    ex = Executor(paths, empty_state(), RunLog(datetime(2026, 10, 20)), Acq(), lambda p: ("flac", None), emit=emit,
                  token=CancelToken())
    actions = [Action("acquire", f"t{i:03d}", "A", SpotifyTrack(f"t{i:03d}", f"Song {i}", ("Artist",), "", None,
                                                                180000, None), (0, i), reason="new")
               for i in range(n)]
    started = time.monotonic()
    ex.run(actions)
    return ex, time.monotonic() - started


def test_a_raising_window_does_not_disturb_the_engine(tmp_path):
    window = RaisingWindow()
    hub = HubEvents(lambda: window)
    hub.start()
    ex, _ = run_engine(tmp_path, hub.emit)
    assert [r.section for r in ex.log.results] == ["new_lossless"] * 30  # no fake download failures
    assert wait_for(lambda: any('"ActionFinished"' in s for s in window.scripts))
    hub.stop()


def test_a_blocking_window_does_not_stall_the_engine(tmp_path):
    window = BlockingWindow()
    hub = HubEvents(lambda: window)
    hub.start()
    ex, seconds = run_engine(tmp_path, hub.emit)
    # 600 events: a wait of even 10 ms per event would take 6 s; 5 s leaves room for a loaded parallel test run
    assert [r.section for r in ex.log.results] == ["new_lossless"] * 30 and seconds < 5
    window.release.set()
    assert wait_for(lambda: sum('"ActionFinished"' in s for s in window.scripts) == 30)
    hub.stop()


def test_emit_never_raises_even_after_stop():
    hub = HubEvents(lambda: FakeWindow())
    hub.start()
    hub.stop()
    hub.emit(ActionFinished(None, None))  # not even for an event that cannot be turned into JSON
    hub.emit(object())


def test_an_event_that_cannot_be_serialised_is_skipped():
    window = FakeWindow()
    hub = HubEvents(lambda: window)
    hub.start()
    hub.emit(object())
    hub.emit(Message("info", "after"))
    assert wait_for(lambda: len(window.scripts) == 1)
    assert window.events()[0]["text"] == "after"
    hub.stop()
