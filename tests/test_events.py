import threading

import pytest

from discjockey.events import (IMPORT_PHASES, Cancelled, CancelToken, ImportProgress, Progress, StepChanged, Tracker,
                               error_kind, null_tracker)
from discjockey.hub import jobs


def test_cancelled_is_not_swallowed_by_except_exception():
    token = CancelToken()
    token.cancel()
    with pytest.raises(Cancelled):
        try:
            token.check()
        except Exception:  # how the executor guards single actions
            pytest.fail("Cancelled must pass through 'except Exception'")


def test_token_can_be_set_from_another_thread():
    token = CancelToken()
    t = threading.Thread(target=token.cancel)
    t.start()
    t.join()
    assert token.cancelled


def test_tracker_reports_steps_and_throttles_progress():
    events, clock = [], [0.0]
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0.25, clock=lambda: clock[0])
    tracker.step("download")
    tracker.progress(1, 100, "bytes")
    clock[0] = 0.1
    tracker.progress(2, 100, "bytes")  # too soon, dropped
    clock[0] = 0.4
    tracker.progress(50, 100, "bytes")
    tracker.progress(100, 100, "bytes")  # the final value is always shown
    assert events[0] == StepChanged("t1", "download")
    assert [e.done for e in events if isinstance(e, Progress)] == [1, 50, 100]
    assert all(e.step == "download" for e in events if isinstance(e, Progress))


def test_tracker_stops_on_cancel():
    token = CancelToken()
    tracker = Tracker(lambda e: None, token, "t1")
    token.cancel()
    with pytest.raises(Cancelled):
        tracker.progress(1, 2, "bytes")
    with pytest.raises(Cancelled):
        tracker.step("convert")


def test_null_tracker_never_stops():
    tracker = null_tracker()
    tracker.step("search")
    tracker.progress(1, None, "bytes")


@pytest.mark.parametrize("errors,kind", [
    (["Qobuz search by ISRC failed: Cannot connect to host www.qobuz.com:443 ssl:default "
      "[nodename nor servname provided, or not known]"], "network"),
    (["Download from qobuz (1) failed: download failed (HTTPSConnectionPool(host='x'): Max retries exceeded)"],
     "network"),
    (["YouTube Music search failed: ERROR: Unable to download webpage: <urlopen error [Errno 8] nodename>"],
     "network"),
    (["Qobuz search by name failed: Qobuz did not answer within 30 seconds"], "network"),
    (["Download from qobuz (1) failed: Qobuz only offers a 30-second preview of this track."], "qobuz"),
    (["Could not convert the youtube file: Invalid data found when processing input"], "other"),
    ([], "other"),
])
def test_error_kind(errors, kind):
    assert error_kind(errors) == kind


def test_token_sleep_wakes_up_on_stop():
    import time
    token = CancelToken()
    threading.Timer(0.1, token.cancel).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        token.sleep(30)
    assert time.monotonic() - started < 1


def test_token_sleep_waits_without_stop():
    import time
    token = CancelToken()
    started = time.monotonic()
    token.sleep(0.05)
    assert time.monotonic() - started >= 0.04


def test_import_progress_is_a_hub_event_with_its_phases():
    assert ImportProgress in jobs.EVENT_TYPES
    assert IMPORT_PHASES == ("scan", "tags", "sound", "link")
    assert jobs.event_dict(ImportProgress("sound", 3, 10, 1)) == {
        "type": "ImportProgress", "phase": "sound", "done": 3, "total": 10, "unreadable": 1}
