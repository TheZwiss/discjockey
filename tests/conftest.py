import os

os.environ["DISCJOCKEY_CHECK_SHAPES"] = "1"  # before any discjockey import: every answer and job result is checked against its shape
import subprocess
import sys
import webbrowser

import pytest
import yt_dlp

from discjockey import app_update, tool_updates
from discjockey.hub import shapes
from discjockey.rekordbox import process as rekordbox_process

# Tests that do not wait for what a test does not need (each module says what it changes and the marker that turns it
# off): importing a fixture here is what registers it.
import tool_memo
from speed_durability import _durability  # noqa: F401
from speed_sqlcipher import _fast_sqlcipher_key  # noqa: F401
from tool_memo import _real_tools  # noqa: F401

subprocess.run = tool_memo.run  # an ffprobe / ffmpeg run on bytes seen before is answered from memory


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
def _no_real_app_opened(monkeypatch):
    """No test opens a real app, folder or page: `Services()` binds `open_url` (webbrowser.open), `open_path` and `reveal`
    (`subprocess.run(["open", ...])`), and the command line binds the real ones. A test that reaches one fails and says so;
    it stubs the opener (hub_helpers' `services`, or `Services(open_path=...)`)."""
    real = subprocess.run

    def guarded(args, *a, **k):
        if isinstance(args, (list, tuple)) and args and args[0] == "open":
            raise AssertionError(f"a test tried to open {list(args)}: stub the opener")
        return real(args, *a, **k)

    def refuse(*a, **k):
        raise AssertionError("a test tried to open a web page: stub the opener")

    monkeypatch.setattr(subprocess, "run", guarded)
    monkeypatch.setattr(webbrowser, "get", refuse)


@pytest.fixture(autouse=True)
def _no_real_pypi(monkeypatch):
    """No test reaches PyPI: every download of tool_updates goes through http_get."""
    def offline(url):
        raise OSError(f"no network in tests: {url}")
    monkeypatch.setattr(tool_updates, "http_get", offline)


@pytest.fixture(autouse=True)
def _answers_fit_their_shapes(request):
    """Every answer and job result of a mapped method or job kind is checked against its shape while the test runs
    (`shapes.note_answer`, `note_result`; the check is on through DISCJOCKEY_CHECK_SHAPES, set at the top of this
    file); a mismatch fails the test, naming where and what. A test whose job work or answer is a stub, not the
    engine's, has the marker `shapes_unchecked`."""
    shapes.take_mismatches()
    yield
    found = shapes.take_mismatches()
    if found and request.node.get_closest_marker("shapes_unchecked") is None:
        pytest.fail("an answer or job result does not fit its shape (hub/shapes):\n" + "\n".join(found), pytrace=False)


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
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX_SHARE", "")  # a worker that ran in this process leaves none behind


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
