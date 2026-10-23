"""The update check (spec public-release §8): versions, GitHub's answer, the day cache, silence on errors."""
import json
import logging
from datetime import datetime, timedelta, timezone

import pytest

import requests

from discjockey import app_update
from discjockey.app_update import Checker, is_newer, parse_version
from discjockey.tool_updates import HttpStatus

NOW = datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc)
PAGE = "https://github.com/TheZwiss/discjockey/releases/tag/"
REAL_FETCH = app_update.fetch_latest  # taken at import: the autouse fixture swaps the module's name for a stub per test


def answer(tag="v1.1.0", **kw) -> bytes:
    return json.dumps({"tag_name": tag, "draft": False, "prerelease": False, "html_url": PAGE + tag, **kw}).encode()


class Fetch:
    """GitHub, stubbed: each call takes the next answer (bytes, or an exception to raise); every URL is kept."""

    def __init__(self, *answers):
        self.answers, self.urls = list(answers), []

    def __call__(self, url):
        self.urls.append(url)
        a = self.answers.pop(0)
        if isinstance(a, BaseException):
            raise a
        return a


def checker(tmp_path, fetch, current="1.0.0"):
    clock = {"now": NOW}
    c = Checker(tmp_path / "cache" / app_update.CACHE_NAME, current=current, fetch=fetch, now=lambda: clock["now"])
    return c, clock


def cache_file(tmp_path):
    return tmp_path / "cache" / app_update.CACHE_NAME


def test_versions_compare_as_numbers():
    assert parse_version("1.1.0") == (1, 1, 0) and parse_version("v2.10.3") == (2, 10, 3)
    for odd in ("\u0661.\u0661.\u0660", "1.1.0-beta.1", "1.1", "nightly", "", " 1.1.0", "1.0.0.dev1", None, 110):
        assert parse_version(odd) is None
    assert is_newer("1.10.0", "1.9.0") and is_newer("v2.0.0", "1.9.9") and is_newer("1.0.1", "1.0.0")
    assert not is_newer("1.0.0", "1.0.0") and not is_newer("0.9.9", "1.0.0")
    assert not is_newer("nightly", "1.0.0") and not is_newer("1.1.0", "1.0.0+local")


def test_a_newer_release_is_available(tmp_path):
    fetch = Fetch(answer("v1.1.0"))
    c, _ = checker(tmp_path, fetch)
    assert c.status()["state"] == "unknown"  # before the first check
    assert c.check() is True
    assert c.status() == {"state": "available", "current": "1.0.0", "latest": "1.1.0", "url": PAGE + "v1.1.0"}
    assert fetch.urls == ["https://api.github.com/repos/TheZwiss/discjockey/releases/latest"]


def test_a_tag_without_v_links_to_its_own_page(tmp_path):
    c, _ = checker(tmp_path, Fetch(answer("1.2.0")))
    c.check()
    assert c.status()["url"] == PAGE + "1.2.0" and c.status()["latest"] == "1.2.0"


@pytest.mark.parametrize("tag, current", [("v1.0.0", "1.0.0"), ("v1.0.0", "1.1.0")])
def test_the_same_or_an_older_release_is_up_to_date(tmp_path, tag, current):
    c, _ = checker(tmp_path, Fetch(answer(tag)), current=current)
    assert c.check() is True
    assert c.status() == {"state": "up_to_date", "current": current, "latest": None, "url": None}


def test_no_release_yet_is_up_to_date_and_cached_for_the_day(tmp_path):
    fetch = Fetch(HttpStatus(404, "u"))
    c, clock = checker(tmp_path, fetch)
    assert c.check() is True and c.status()["state"] == "up_to_date"
    assert json.loads(cache_file(tmp_path).read_text())["version"] is None
    clock["now"] = NOW + timedelta(hours=23)
    assert c.check() is False and len(fetch.urls) == 1  # from the cache


@pytest.mark.parametrize("error", [OSError("offline"), TimeoutError(), HttpStatus(403, "u"), HttpStatus(429, "u"),
                                   HttpStatus(500, "u"), ValueError("anything else")])
def test_no_answer_is_silent_and_not_cached(tmp_path, caplog, error):
    caplog.set_level(logging.DEBUG)
    c, _ = checker(tmp_path, Fetch(error))
    assert c.check() is False
    assert c.status() == {"state": "unknown", "current": "1.0.0", "latest": None, "url": None}
    assert not cache_file(tmp_path).exists()  # asked again at the next tick
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]


@pytest.mark.parametrize("data", [answer(draft=True), answer(prerelease=True), answer("v1.1.0-beta.1"),
                                  answer("nightly"), answer(tag_name=None), b"<html>rate limited</html>", b"[]",
                                  b"\xff\xfe", b"{}"])
def test_odd_answers_offer_nothing(tmp_path, data):
    c, _ = checker(tmp_path, Fetch(data))
    c.check()
    assert c.status() == {"state": "up_to_date", "current": "1.0.0", "latest": None, "url": None}


def test_the_answer_is_cached_for_a_day(tmp_path):
    fetch = Fetch(answer("v1.1.0"), answer("v1.2.0"))
    c, clock = checker(tmp_path, fetch)
    c.check()
    clock["now"] = NOW + timedelta(hours=23, minutes=59)
    assert c.check() is False and len(fetch.urls) == 1
    clock["now"] = NOW + timedelta(days=1, minutes=1)
    assert c.check() is True and len(fetch.urls) == 2 and c.status()["latest"] == "1.2.0"


def write_cache(tmp_path, checked_at, version="1.1.0", url=PAGE + "v1.1.0"):
    cache_file(tmp_path).parent.mkdir(parents=True, exist_ok=True)
    cache_file(tmp_path).write_text(json.dumps({"checked_at": checked_at, "version": version, "url": url}))


@pytest.mark.parametrize("checked_at", [(NOW + timedelta(hours=2)).isoformat(), "2026-10-23T11:00:00", "yesterday"])
def test_a_cache_from_the_future_or_broken_is_asked_again(tmp_path, checked_at):
    write_cache(tmp_path, checked_at)
    fetch = Fetch(answer("v1.1.0"))
    c, _ = checker(tmp_path, fetch)
    c.check()
    assert len(fetch.urls) == 1


@pytest.mark.parametrize("text", ["{", "[]", '"x"', ""])
def test_an_unreadable_cache_is_asked_again(tmp_path, text):
    cache_file(tmp_path).parent.mkdir(parents=True)
    cache_file(tmp_path).write_text(text)
    fetch = Fetch(answer("v1.1.0"))
    c, _ = checker(tmp_path, fetch)
    c.check()
    assert len(fetch.urls) == 1 and c.status()["state"] == "available"


def test_the_cached_release_is_compared_with_the_running_version(tmp_path):
    write_cache(tmp_path, (NOW - timedelta(hours=1)).isoformat())
    fetch = Fetch()
    c, _ = checker(tmp_path, fetch, current="1.1.0")  # the user installed 1.1.0 since
    c.check()
    assert c.status()["state"] == "up_to_date" and fetch.urls == []


def test_a_cached_url_that_is_not_the_release_page_is_ignored(tmp_path):
    write_cache(tmp_path, (NOW - timedelta(hours=1)).isoformat(), version="9.0.0", url="https://example.com/x")
    fetch = Fetch(answer("v1.1.0"))
    c, _ = checker(tmp_path, fetch)
    c.check()
    assert len(fetch.urls) == 1 and c.status()["url"] == PAGE + "v1.1.0"


def test_no_answer_keeps_the_last_status(tmp_path):
    c, clock = checker(tmp_path, Fetch(answer("v1.1.0"), OSError("offline")))
    c.check()
    clock["now"] = NOW + timedelta(days=2)
    assert c.check() is False and c.status()["state"] == "available"


def test_an_unwritable_cache_still_answers(tmp_path):
    (tmp_path / "cache").write_text("a file where the folder should be")
    c, _ = checker(tmp_path, Fetch(answer("v1.1.0")))
    assert c.check() is True and c.status()["state"] == "available"


def test_status_is_a_copy(tmp_path):
    c, _ = checker(tmp_path, Fetch())
    c.status()["state"] = "available"
    assert c.status()["state"] == "unknown"


def test_the_tests_never_reach_github():
    with pytest.raises(OSError):
        app_update.fetch_latest(app_update.LATEST_URL)


def test_non_ascii_digits_are_not_a_version(tmp_path):
    c, _ = checker(tmp_path, Fetch(answer("v\u0661.\u0661.\u0660")))
    c.check()
    assert c.status()["state"] == "up_to_date" and c.status()["url"] is None


@pytest.mark.parametrize("url", [PAGE + "v1.1.0/../../x", PAGE + "v1.1.0/more", PAGE + "v1.2.0", PAGE + "..", PAGE])
def test_a_cached_url_must_be_the_page_of_the_cached_version(tmp_path, url):
    write_cache(tmp_path, (NOW - timedelta(hours=1)).isoformat(), version="1.1.0", url=url)
    fetch = Fetch(answer("v1.1.0"))
    c, _ = checker(tmp_path, fetch)
    c.check()
    assert len(fetch.urls) == 1 and c.status()["url"] == PAGE + "v1.1.0"


def test_a_cached_url_without_the_v_is_the_page_of_that_version(tmp_path):
    write_cache(tmp_path, (NOW - timedelta(hours=1)).isoformat(), version="1.1.0", url=PAGE + "1.1.0")
    fetch = Fetch()
    c, _ = checker(tmp_path, fetch)
    c.check()
    assert fetch.urls == [] and c.status()["url"] == PAGE + "1.1.0"


def test_absurdly_deep_json_is_just_an_odd_answer(tmp_path):
    c, _ = checker(tmp_path, Fetch(b"[" * 200000))
    assert c.check() is True
    assert c.status() == {"state": "up_to_date", "current": "1.0.0", "latest": None, "url": None}


def test_absurdly_deep_json_in_the_cache_is_asked_again(tmp_path):
    cache_file(tmp_path).parent.mkdir(parents=True)
    cache_file(tmp_path).write_text("[" * 200000)
    fetch = Fetch(answer("v1.1.0"))
    c, _ = checker(tmp_path, fetch)
    c.check()
    assert len(fetch.urls) == 1 and c.status()["state"] == "available"


@pytest.mark.parametrize("current", ["1.0.0.dev1", "1.0.0+local", "dev"])
def test_a_developer_version_does_not_ask_and_stays_unknown(tmp_path, current):
    fetch = Fetch()
    c, _ = checker(tmp_path, fetch, current=current)
    assert c.check() is False
    assert fetch.urls == [] and not cache_file(tmp_path).exists()
    assert c.status() == {"state": "unknown", "current": current, "latest": None, "url": None}


class Response:
    def __init__(self, status_code, content=b"{}"):
        self.status_code, self.content = status_code, content


def stub_get(monkeypatch, response):
    calls = []

    def get(url, **kw):
        calls.append((url, kw))
        if isinstance(response, BaseException):
            raise response
        return response
    monkeypatch.setattr(requests, "get", get)
    return calls


def test_fetch_latest_asks_github_with_its_headers_and_returns_the_body(monkeypatch):
    calls = stub_get(monkeypatch, Response(200, b'{"tag_name": "v1.1.0"}'))
    assert REAL_FETCH(app_update.LATEST_URL) == b'{"tag_name": "v1.1.0"}'
    (url, kw), = calls
    assert url == app_update.LATEST_URL and kw["timeout"] == app_update.TIMEOUT_S
    assert kw["headers"]["Accept"] == "application/vnd.github+json"
    assert kw["headers"]["User-Agent"].startswith("Discjockey/")


@pytest.mark.parametrize("status", [403, 404, 429, 500])
def test_fetch_latest_turns_an_error_status_into_http_status(monkeypatch, status):
    stub_get(monkeypatch, Response(status))
    with pytest.raises(HttpStatus) as e:
        REAL_FETCH(app_update.LATEST_URL)
    assert e.value.status == status


def test_fetch_latest_lets_connection_errors_through_to_the_checker(monkeypatch, tmp_path):
    stub_get(monkeypatch, requests.ConnectionError("offline"))
    c, _ = checker(tmp_path, REAL_FETCH)
    assert c.check() is False and c.status()["state"] == "unknown"
    assert not cache_file(tmp_path).exists()
