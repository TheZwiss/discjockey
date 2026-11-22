"""The update notice in the hub (spec public-release §8): app_update() and the AppUpdate event."""
import json
import logging
import time
from datetime import datetime, timedelta, timezone

from hub_helpers import make_unbound_api

from discjockey import __version__, words
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
    assert api.app_update() == {"ok": True, "state": "unknown", "current": __version__, "latest": None, "url": None,
                                "ran_check": False, "checked_at": None, "message": None}


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


# --- the command line's `app info [--check]`: the same answer without a window ---

def cache_of(support, *, age: timedelta, version: str | None = "999.0.0") -> str:
    """Writes the update cache `age` old (a newer release, or none for a null `version`) and returns its `checked_at`."""
    when = (datetime.now(timezone.utc) - age).isoformat()
    path = support / "cache" / "app_update.json"
    path.parent.mkdir(parents=True)
    url = f"https://github.com/TheZwiss/discjockey/releases/tag/v{version}" if version else None
    path.write_text(json.dumps({"checked_at": when, "version": version, "url": url}))
    return when


def test_a_fresh_cache_answers_without_a_check_and_without_the_network(tmp_path):
    asked = []
    support = tmp_path / "support"
    when = cache_of(support, age=timedelta(hours=3))
    api, _ = make_unbound_api(support, fetch_release=lambda url: asked.append(url) or NEWER)
    answer = api.app_update()
    assert (answer["state"], answer["latest"], answer["ran_check"], answer["checked_at"]) == ("available", "999.0.0", False, when)
    assert asked == []


def test_a_cache_a_day_old_is_not_an_answer_but_its_time_is_told(tmp_path):
    asked = []
    support = tmp_path / "support"
    when = cache_of(support, age=timedelta(days=2))
    api, _ = make_unbound_api(support, fetch_release=lambda url: asked.append(url) or NEWER)
    answer = api.app_update()
    assert (answer["state"], answer["ran_check"], answer["checked_at"]) == ("unknown", False, when) and asked == []


def test_check_asks_the_network_once_writes_the_cache_and_says_so(tmp_path):
    asked = []
    support = tmp_path / "support"
    api, _ = make_unbound_api(support, fetch_release=lambda url: asked.append(url) or NEWER)
    answer = api.app_update(check=True)
    assert (answer["state"], answer["latest"], answer["ran_check"]) == ("available", "999.0.0", True) and len(asked) == 1
    assert answer["checked_at"] == json.loads((support / "cache" / "app_update.json").read_text())["checked_at"]
    again = api.app_update(check=True)  # the Checker's own cap: a fresh cache is the answer
    assert len(asked) == 1 and again["checked_at"] == answer["checked_at"]
    assert api.app_update()["state"] == "available"  # and the process keeps it


def test_check_with_a_fresh_cache_asks_nothing_and_a_check_that_gets_no_answer_stays_unknown(tmp_path):
    asked = []
    support = tmp_path / "support"
    cache_of(support, age=timedelta(hours=1), version=None)  # a repo with no release: nothing newer
    api, _ = make_unbound_api(support, fetch_release=lambda url: asked.append(url) or NEWER)
    answer = api.app_update(check=True)
    assert (answer["state"], answer["ran_check"]) == ("up_to_date", True) and asked == []

    def offline(url):
        raise OSError("offline")

    api, _ = make_unbound_api(tmp_path / "other", fetch_release=offline)
    answer = api.app_update(check=True)
    assert (answer["state"], answer["ran_check"], answer["checked_at"]) == ("unknown", True, None)


def test_a_check_that_ran_is_not_overwritten_by_an_older_cache_read(tmp_path):
    support = tmp_path / "support"
    api, _ = make_unbound_api(support, fetch_release=lambda url: NEWER)
    api._update.check()
    cache = support / "cache" / "app_update.json"
    cache.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(), "version": None, "url": None}))
    assert api.app_update()["state"] == "available"  # the window's check of this process stands


def test_the_checkers_status_keeps_its_four_keys_for_the_window_event(tmp_path):
    api, _ = make_unbound_api(tmp_path / "support", fetch_release=lambda url: NEWER)
    api._update.check()
    assert set(api._update.status()) == {"state", "current", "latest", "url"}  # `AppUpdate(**status())` builds the event


def test_a_check_that_ends_unknown_says_why_in_the_message(tmp_path):
    """`app info --check`: a developer's version asks nobody, an offline machine asks and gets nothing: both are `unknown`
    with no `checked_at`, and only the message tells them apart (no check, no message)."""
    asked = []
    api, _ = make_unbound_api(tmp_path / "dev", fetch_release=lambda url: asked.append(url) or NEWER)
    api._update.current = "1.0.0-dev"  # no plain release number
    answer = api.app_update(check=True)
    assert (answer["state"], answer["ran_check"], answer["checked_at"], answer["message"]) == (
        "unknown", True, None, words.UPDATE_NO_ANSWER_DEV) and asked == []

    def offline(url):
        asked.append(url)
        raise OSError("offline")

    api, _ = make_unbound_api(tmp_path / "offline", fetch_release=offline)
    answer = api.app_update(check=True)
    assert (answer["state"], answer["ran_check"], answer["checked_at"], answer["message"]) == (
        "unknown", True, None, words.UPDATE_NO_ANSWER_OFFLINE) and len(asked) == 1
    assert api.app_update()["message"] is None  # without `check` nobody asked: nothing to explain


def test_a_check_with_an_answer_has_no_message(tmp_path):
    api, _ = make_unbound_api(tmp_path / "support", fetch_release=lambda url: NEWER)
    assert api.app_update(check=True)["message"] is None
