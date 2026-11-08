import sys

import pytest
import yt_dlp

from discjockey import app_update, tool_updates
from discjockey.rekordbox import process as rekordbox_process


class _Offline:
    def __init__(self, *a, **k):
        raise OSError("no network in tests: stub yt_dlp.YoutubeDL")


@pytest.fixture(autouse=True)
def _no_real_yt_dlp(monkeypatch):
    """No test reaches YouTube or SoundCloud (a slow answer made sync tests miss their timeouts). Tests that need
    yt-dlp put their own fake in its place."""
    monkeypatch.setattr(yt_dlp, "YoutubeDL", _Offline)


@pytest.fixture(autouse=True)
def _scratch_support(tmp_path_factory, monkeypatch):
    """No test reads or writes the real ~/Library/Application Support/Discjockey (or a config.json there)."""
    monkeypatch.setenv("DISCJOCKEY_SUPPORT", str(tmp_path_factory.mktemp("support")))


@pytest.fixture(autouse=True)
def _no_real_pypi(monkeypatch):
    """No test reaches PyPI: every download of tool_updates goes through http_get."""
    def offline(url):
        raise OSError(f"no network in tests: {url}")
    monkeypatch.setattr(tool_updates, "http_get", offline)


@pytest.fixture(autouse=True)
def _no_real_github(monkeypatch):
    """No test asks GitHub for the latest release: the update check goes through app_update.fetch_latest."""
    def offline(url):
        raise OSError(f"no network in tests: {url}")
    monkeypatch.setattr(app_update, "fetch_latest", offline)


@pytest.fixture(autouse=True)
def _no_real_rekordbox_library(tmp_path_factory, monkeypatch):
    """No test reads the maintainer's rekordbox library: DISCJOCKEY_REKORDBOX points at an empty folder (no
    library: state "none"). A test that needs one builds it there or elsewhere with rekordbox_helpers.make_master."""
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(tmp_path_factory.mktemp("rekordbox")))


@pytest.fixture(autouse=True)
def _rekordbox_not_running(monkeypatch):
    """No test depends on whether the maintainer's rekordbox is open: process.running answers False."""
    monkeypatch.setattr(rekordbox_process, "running", lambda: False)


_JOB_THREADS = ("hub-job-", "hub-refresh-", "hub-sign-in-")


@pytest.fixture(autouse=True)
def _no_hub_job_outlives_its_test():
    """A hub job runs on a daemon thread; one a test never waited for would go on into the next test of the same
    worker and, through the module-level patches (yt_dlp.YoutubeDL, class-level call lists), show up in its asserts.
    At teardown every api that `hub_helpers` made stops: its jobs are cancelled and its threads joined (a thread that
    won't end in 5 s fails the test that left it)."""
    import threading
    before = set(threading.enumerate())
    yield
    helpers = sys.modules.get("hub_helpers")
    for api in (helpers.made_apis() if helpers is not None else ()):
        for job in (api._jobs.current, api._jobs.refresh, api._jobs.sign_in):
            if job is not None:
                job.token.cancel()
        api._jobs.close()
    stuck = []
    for thread in set(threading.enumerate()) - before:
        if thread.name.startswith(_JOB_THREADS):
            thread.join(5)
            if thread.is_alive():
                stuck.append(thread.name)
    assert not stuck, f"a hub job thread outlived its test: {stuck}"
