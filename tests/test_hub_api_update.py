"""The update notice in the hub (spec public-release §8): app_update() and the AppUpdate event."""
import json
import logging
import time

from hub_helpers import make_unbound_api

from discjockey import __version__
from discjockey.hub import jobs

NEWER = json.dumps({"tag_name": "v999.0.0", "draft": False, "prerelease": False}).encode()


def wait_for(cond, timeout=5.0):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if cond():
            return True
        time.sleep(0.01)
    return False


def updates(rec):
    return [e for e in rec.events if isinstance(e, jobs.AppUpdate)]


def test_app_update_answers_before_any_check_and_without_a_music_folder(tmp_path):
    api, _ = make_unbound_api(tmp_path / "support")
    assert api.app_update() == {"ok": True, "state": "unknown", "current": __version__, "latest": None, "url": None}


def test_the_watch_checks_at_start_and_sends_the_answer_once(tmp_path):
    urls = []
    api, rec = make_unbound_api(tmp_path / "support", fetch_release=lambda url: urls.append(url) or NEWER)
    ticks = []
    check = api._update.check
    api._update.check = lambda: ticks.append(1) or check()
    thread = api._watch_app_update(interval=0.02)
    assert wait_for(lambda: len(ticks) >= 5)  # several ticks: the cache answers all but the first
    api._jobs.close()
    thread.join(2)
    assert not thread.is_alive() and len(urls) == 1
    assert [(e.state, e.latest) for e in updates(rec)] == [("available", "999.0.0")]
    assert updates(rec)[0].url == "https://github.com/TheZwiss/discjockey/releases/tag/v999.0.0"
    assert api.app_update()["state"] == "available"
    assert (tmp_path / "support" / "cache" / "app_update.json").exists()


def test_an_offline_watch_sends_nothing_and_logs_no_warning(tmp_path, caplog):
    caplog.set_level(logging.DEBUG)
    calls = []

    def offline(url):
        calls.append(url)
        raise OSError("offline")

    api, rec = make_unbound_api(tmp_path / "support", fetch_release=offline)
    thread = api._watch_app_update(interval=0.02)
    assert wait_for(lambda: len(calls) >= 2)  # asked again at the next tick: errors aren't cached
    api._jobs.close()
    thread.join(2)
    assert updates(rec) == [] and api.app_update()["state"] == "unknown"
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


def test_a_failing_tick_is_logged_and_the_watch_goes_on(tmp_path, caplog):
    api, rec = make_unbound_api(tmp_path / "support", fetch_release=lambda url: NEWER)
    real, calls = api._update.check, []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("bug")
        return real()

    api._update.check = flaky
    thread = api._watch_app_update(interval=0.02)
    assert wait_for(lambda: updates(rec))  # the second tick got through
    assert thread.is_alive()
    api._jobs.close()
    thread.join(2)
    assert [r.getMessage() for r in caplog.records if r.levelno == logging.WARNING] == ["update check failed"]


def test_a_hub_closed_before_the_watch_starts_asks_nothing(tmp_path):
    urls = []
    api, rec = make_unbound_api(tmp_path / "support", fetch_release=lambda url: urls.append(url) or NEWER)
    api._jobs.close()
    api._watch_app_update(interval=0.02).join(2)
    assert urls == [] and updates(rec) == []
