"""Locks across processes (issue 39, group 1.7; design §6.1): the support lock around every read-change-write of the
support folder's files, the shared `rekordbox.lock` of readers and the writer's retry, and `tools update` refused while
a write job runs. The two-process tests start real children on scratch folders (`tmp_path`); the `procs` fixture
kills what a test left and fails it when a child outlives it."""
from __future__ import annotations

import json
import subprocess
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from batch_helpers import make_lib, needs_ffmpeg
from hub_helpers import make_api, make_unbound_api, services, wait_job
from discjockey import aiff_plan, library, rekordbox, tool_updates
from discjockey.hub import catalog, registry
from discjockey.rekordbox import lock as rb_lock
from discjockey.settings import Settings, load_settings, save_settings, update_settings
from tools_helpers import FakePyPI, write_site

REPO = Path(__file__).resolve().parent.parent

COUNTER = """
import sys
from dataclasses import replace
from pathlib import Path
from discjockey.settings import update_settings
path, n = Path(sys.argv[1]), int(sys.argv[2])
sys.stdin.readline()  # the start signal: both children begin together
for _ in range(n):
    update_settings(path, lambda s: replace(s, daily_qobuz_limit=s.daily_qobuz_limit + 1))
"""

HOLD = """
import sys
from pathlib import Path
from discjockey import library
from discjockey.rekordbox import lock
support, which = Path(sys.argv[1]), sys.argv[2]
hold = library.support_lock if which == "support" else lock.writer_lock
with hold(support):
    print("held", flush=True)
    sys.stdin.read()  # held until the parent closes stdin
"""


class Procs:
    def __init__(self):
        self.started: list[subprocess.Popen] = []

    def spawn(self, script: str, *args) -> subprocess.Popen:
        p = subprocess.Popen([sys.executable, "-c", script, *map(str, args)], cwd=REPO, stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, text=True)
        self.started.append(p)
        return p

    def holder(self, support: Path, which: str) -> subprocess.Popen:
        """A child that holds the support lock (`which` "support") or `rekordbox.lock` (`"writer"`) until released."""
        p = self.spawn(HOLD, support, which)
        assert p.stdout.readline().strip() == "held"
        return p

    def release(self, p: subprocess.Popen) -> None:
        p.stdin.close()
        assert p.wait(10) == 0

    def finish(self) -> None:
        left = [p for p in self.started if p.poll() is None]
        for p in left:
            p.kill()
            p.wait(10)
        assert not left, "a child process outlived its test"


@pytest.fixture
def procs():
    p = Procs()
    try:
        yield p
    finally:
        p.finish()


@pytest.fixture
def support(tmp_path):
    folder = tmp_path / "support"
    folder.mkdir()
    return folder


# --- the support lock ---

def test_two_processes_saving_settings_at_once_lose_neither_change(procs, support):
    path = support / "settings.json"
    save_settings(path, Settings(daily_qobuz_limit=100))
    children = [procs.spawn(COUNTER, path, 40) for _ in range(2)]
    for p in children:  # the start signal, then each ends by itself
        p.stdin.write("go\n")
        p.stdin.flush()
    for p in children:
        assert p.wait(60) == 0
    assert load_settings(path).daily_qobuz_limit == 180


def test_the_support_lock_waits_two_seconds_then_answers_busy_support_lock(procs, support):
    assert (library.SUPPORT_WAIT_S, rb_lock.WRITER_WAIT_S) == (2.0, 2.0)
    holder = procs.holder(support, "support")
    started = time.monotonic()
    with pytest.raises(library.SupportBusy) as raised:
        with library.support_lock(support):
            pytest.fail("the lock was taken while another process held it")
    assert 1.8 <= time.monotonic() - started < 6
    assert raised.value.reason == "support_lock"
    procs.release(holder)
    with library.support_lock(support):  # let go when the holder ended
        pass


def test_a_busy_support_lock_is_a_busy_answer_with_the_reason_of_its_own(procs, support, monkeypatch):
    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    api, _ = make_unbound_api(support)
    holder = procs.holder(support, "support")
    answer = api.setup_skip_import()
    assert (answer["ok"], answer["kind"], answer["outcome"], answer["reason"]) == (False, "busy", "busy", "support_lock")
    assert not (support / "settings.json").exists()  # nothing was saved
    procs.release(holder)
    assert api.setup_skip_import() == {"ok": True}
    assert load_settings(support / "settings.json").import_skipped is True


def test_a_save_inside_a_job_that_meets_the_support_lock_keeps_its_reason(procs, support, monkeypatch):
    """The job ends `busy`; the worker names the support lock as the reason, not the library."""
    from discjockey.cli import envelope, worker
    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    api, rec = make_unbound_api(support)
    holder = procs.holder(support, "support")
    finished = wait_job(api, rec, api.setup_skip_qobuz())
    job = api._jobs.current
    assert (finished.ok, finished.problem) == (False, "busy") and job.error.reason == "support_lock"
    files = type("F", (), {"id": "job:00000000", "dir": support / "jobs" / "job:00000000"})()
    env = worker._busy("login skip qobuz", files, {}, job)
    assert (env["outcome"], env["reason"]) == ("busy", "support_lock")
    procs.release(holder)
    assert envelope.exit_code(env) == 3


def test_every_write_site_of_the_support_folder_holds_the_support_lock(support, monkeypatch):
    """The sites the group wrapped, one by one, each with a lock that records (check first: the list in the commit)."""
    from discjockey import qobuz
    from discjockey.sources import spotify
    taken = []
    real = library.support_lock

    def recording(folder, **kwargs):
        taken.append(Path(folder))
        return real(folder, **kwargs)

    monkeypatch.setattr(library, "support_lock", recording)
    update_settings(support / "settings.json", lambda s: s)
    library.write_music_folder(support, support / "music")
    spotify._save_token(support / ".spotify_token.json", {"access_token": "a"})
    api, rec = make_unbound_api(support)
    assert wait_job(api, rec, api.setup_save_client_id("0" * 32)).ok
    qobuz.write_config(library.SupportPaths(support=support))
    assert taken == [support] * 5
    assert tool_updates.library is library  # update / rollback take it through the same function


def test_spotify_sign_out_holds_the_support_lock(support, monkeypatch):
    taken = []
    real = library.support_lock
    monkeypatch.setattr(library, "support_lock", lambda folder: taken.append(Path(folder)) or real(folder))
    api, rec = make_unbound_api(support)
    (support / ".spotify_token.json").write_text("{}")
    (support / ".spotify_app.json").write_text(json.dumps({"client_id": "0" * 32, "user": "me"}))
    assert wait_job(api, rec, api.spotify_sign_out()).ok
    assert taken == [support] * 2  # the token's removal and the login's name in .spotify_app.json
    assert not (support / ".spotify_token.json").exists()
    assert json.loads((support / ".spotify_app.json").read_text()) == {"client_id": "0" * 32}


# Every line that writes a file with save_file / save_settings / os.replace / write_json_atomic, counted per source
# file. A new write site fails here and names its file: give it the support lock (or say why it needs none) and add it.
WRITE_SITES = {
    "app_update.py": (1, "app_update.json: one owner, one whole-file atomic write"),
    "candidates.py": (2, "the cache folder's own files: one owner, whole-file atomic writes"),
    "db.py": (4, "library.db's own files and backups: the library lock, not the support folder"),
    "hub/api.py": (1, "_save_spotify_app: inside support_lock"),
    "hub/media.py": (1, "the media cache: one owner, whole-file atomic write"),
    "hub/plan_store.py": (1, "<support>/plans/: one owner per plan file, whole-file atomic write (a dry run's one write)"),
    "hub/registry.py": (6, "the job registry's files: one owner per job, whole-file atomic writes"),
    "hub/window_port.py": (1, "window.json: one owner (the window), whole-file atomic write"),
    "hub/windows.py": (1, "<support>/windows/<pid>.json: one owner per window, whole-file atomic write"),
    "library.py": (4, "write_json_atomic itself, the library's state file (library lock), write_music_folder "
                      "(takes the support lock inside)"),
    "pacing.py": (1, "pace.json: under its own pace.lock (an flock held only to read and write), whole-file atomic write"),
    "pending_signs.py": (1, "the music folder's sign file: library lock"),
    "playlists_file.py": (1, "a playlist file in the music folder: library lock"),
    "qobuz.py": (3, "config.toml: _write_config and _save_login run inside support_lock, _save_secrets takes it"),
    "rekordbox/backup.py": (1, "a backup copy of master.db: under rekordbox's writer lock"),
    "rekordbox/write.py": (1, "master.db's own write: under rekordbox's writer lock"),
    "settings.py": (3, "save_settings itself, and update_settings: the support lock around read-change-write"),
    "setup_cmd.py": (1, ".spotify_app.json: inside support_lock"),
    "sources/spotify.py": (1, "the Spotify token: _save_token takes the support lock"),
    "tool_updates.py": (1, "_point_current: only called from update / rollback, under the support lock"),
}


def test_every_file_write_in_the_source_is_a_listed_site():
    import re
    pattern = re.compile(r"save_file\(|save_settings\(|os\.replace\(|write_json_atomic\(")
    root = REPO / "discjockey"
    found = {}
    for path in sorted(root.rglob("*.py")):
        count = sum(1 for line in path.read_text(encoding="utf-8").splitlines() if pattern.search(line))
        if count:
            found[path.relative_to(root).as_posix()] = count
    unlisted = {f: n for f, n in found.items() if f not in WRITE_SITES}
    changed = {f: (n, WRITE_SITES[f][0]) for f, n in found.items() if f in WRITE_SITES and WRITE_SITES[f][0] != n}
    gone = [f for f in WRITE_SITES if f not in found]
    assert not unlisted, f"a file write not in WRITE_SITES (does it hold the support lock?): {unlisted}"
    assert not changed, f"a file's number of writes changed (found, listed): {changed}"
    assert not gone, f"listed but has no write any more: {gone}"


def test_a_qobuz_login_takes_the_support_lock_and_keeps_what_another_process_saved(procs, support, monkeypatch):
    from discjockey import qobuz
    paths = library.SupportPaths(support=support)
    cfg_path = qobuz.write_config(paths)

    class Client:
        def __init__(self, cfg):
            self.config = cfg

        async def login(self):  # the seconds of the network: another process saves a new login meanwhile
            other = qobuz._load_config(cfg_path)
            other.file.qobuz.email_or_userid = "new@example.com"
            other.file.set_modified()
            other.save_file()
            self.config.file.qobuz.app_id = "12345"
            self.config.file.qobuz.secrets = ["s1"]

    monkeypatch.setattr(qobuz, "QobuzClient", Client)
    source = qobuz.QobuzSource.open(paths)
    source.runner.close()
    fresh = qobuz._load_config(cfg_path).file.qobuz
    assert fresh.email_or_userid == "new@example.com"  # not overwritten by the old cfg
    assert (fresh.app_id, list(fresh.secrets)) == ("12345", ["s1"])  # what the login fetched is saved

    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    holder = procs.holder(support, "support")
    with pytest.raises(library.SupportBusy):
        qobuz.QobuzSource.open(paths)
    procs.release(holder)


# --- tools: a support-only job ---

def _tools_env(tmp_path, support):
    site = write_site(tmp_path / "site", yt="2026.10.21")
    return (site / "yt_dlp").resolve()


def test_tools_update_and_rollback_wait_for_the_support_lock_where_tools_changes(procs, tmp_path, support, monkeypatch):
    monkeypatch.setattr(library, "SUPPORT_WAIT_S", 0.3)
    builtin = _tools_env(tmp_path, support)
    holder = procs.holder(support, "support")
    pypi = FakePyPI("2026.10.28", "0.8.1")
    with pytest.raises(library.SupportBusy):  # the download is done, then the change of tools/ meets the lock
        tool_updates.update(support, fetch=pypi, run=lambda *a, **k: None, running=builtin, builtin=builtin)
    assert any(url.endswith(".whl") for url in pypi.requested)
    assert not (support / "tools").exists() or not any((support / "tools").iterdir())  # nothing was changed
    with pytest.raises(library.SupportBusy):
        tool_updates.rollback(support, running=builtin, builtin=builtin)
    procs.release(holder)


def test_a_settings_save_succeeds_while_a_tools_update_is_downloading(tmp_path, support):
    builtin = _tools_env(tmp_path, support)
    pypi = FakePyPI("2026.10.28", "0.8.1")
    downloading, go = threading.Event(), threading.Event()

    def slow(url):
        if url.endswith(".whl"):
            downloading.set()
            assert go.wait(10)  # the download takes as long as the test wants
        return pypi(url)

    from tools_helpers import CheckRun
    done = []
    t = threading.Thread(target=lambda: done.append(tool_updates.update(support, fetch=slow, run=CheckRun(),
                                                                         running=builtin, builtin=builtin)))
    t.start()
    try:
        assert downloading.wait(10)
        started = time.monotonic()
        update_settings(support / "settings.json", lambda s: replace(s, daily_qobuz_limit=7))  # no SupportBusy
        assert time.monotonic() - started < 1.5
        assert load_settings(support / "settings.json").daily_qobuz_limit == 7
    finally:
        go.set()
        t.join(30)
    assert done and done[0][1] == {"yt-dlp": "2026.10.28"}


def _running_job(support: Path, method: str, status: str = "running") -> registry.JobFiles:
    files = registry.Registry(support).create(method, "x", {}, "terminal", {})
    files.update(method=method, status=status)
    files.flush()
    return files


def test_tools_update_is_busy_while_a_registry_write_job_runs_and_takes_no_library_lock(support, tmp_path, monkeypatch):
    taken = []
    real = library.run_lock
    monkeypatch.setattr(library, "run_lock", lambda path: taken.append(path) or real(path))
    paths = library.Paths(tmp_path / "music", support=support)
    paths.data.mkdir(parents=True)
    api, rec = make_api(paths)
    files = _running_job(support, "rescan_library")  # `library scan`: its catalogue entry holds the library
    try:
        answer = api.update_tools()
        assert (answer["ok"], answer["kind"], answer["reason"]) == (False, "busy", "library_lock")
        assert answer["data"]["holder"]["job"] == files.id
        assert api.rollback_tools()["kind"] == "busy"
    finally:
        files.update(status="done")
        files.flush()
        files.release_claim()
    assert taken == []  # nothing took the library lock, not even to be refused
    answer = api.update_tools()  # the job is over (its claim let go): not refused any more
    assert answer["ok"], answer
    finished = wait_job(api, rec, answer)
    assert finished.problem == "failed"  # no network in tests: it got as far as asking
    assert taken == []  # a support-only job never takes the library lock


def test_a_running_job_that_holds_no_library_lock_does_not_stop_tools_update(support, tmp_path):
    paths = library.Paths(tmp_path / "music", support=support)
    paths.data.mkdir(parents=True)
    api, rec = make_api(paths)
    files = _running_job(support, "rekordbox_status")  # a read: no library lock in its entry
    try:
        assert api.update_tools()["ok"]
        wait_job(api, rec, {"ok": True, "job_id": api._jobs.current.id})
    finally:
        files.update(status="done")
        files.release_claim()


# --- rekordbox readers ---

def test_a_reader_never_makes_a_writer_busy_and_a_writer_makes_the_reader_say_so(support):
    with rb_lock.reader_lock(support) as free:
        assert free is True
        with rb_lock.reader_lock(support) as second:  # readers share
            assert second is True
    with rb_lock.writer_lock(support):
        with rb_lock.reader_lock(support) as free:
            assert free is False


def test_the_writer_retries_while_a_reader_holds_and_goes_on_when_it_lets_go(support):
    import threading
    (support / rb_lock.LOCK_NAME).touch()  # a reader holds the file a writer has made once; it never makes it itself
    release = threading.Event()
    held = threading.Event()

    def reader():
        with rb_lock.reader_lock(support) as free:
            assert free
            held.set()
            release.wait(5)

    t = threading.Thread(target=reader)
    t.start()
    try:
        assert held.wait(5)
        threading.Timer(0.3, release.set).start()
        started = time.monotonic()
        with rb_lock.writer_lock(support):  # the reader's brief hold: the writer waited, never `Busy`
            waited = time.monotonic() - started
        assert 0.2 <= waited < 2.0
    finally:
        release.set()
        t.join(5)


def test_the_writer_is_busy_after_two_seconds_when_another_writer_holds(procs, support):
    holder = procs.holder(support, "writer")
    started = time.monotonic()
    with pytest.raises(rb_lock.Busy) as raised:
        with rb_lock.writer_lock(support):
            pytest.fail("two writers")
    assert 1.8 <= time.monotonic() - started < 6 and raised.value.reason == "rekordbox_lock"
    procs.release(holder)


def test_a_reader_without_a_support_folder_or_a_writable_one_reads_as_before(tmp_path):
    with rb_lock.reader_lock(tmp_path / "not-there") as free:
        assert free is True
    assert not (tmp_path / "not-there").exists()  # a read makes no folder


def main_facts(answer: dict) -> dict:
    """The four facts the window's Sync page reads of `rekordbox_status()` (the answer has more: library, version, the
    size and time of master.db)."""
    return {k: v for k, v in answer.items() if k in ("ok", "state", "running", "writing", "as_of")}



def test_status_with_a_writer_holding_answers_writing_with_the_last_value_and_as_of(procs, support, monkeypatch):
    api, _ = make_unbound_api(support)
    first = main_facts(api.rekordbox_status())
    assert first == {"ok": True, "state": "none", "running": False}  # nobody writes: no `writing` key
    boom = lambda *a, **k: pytest.fail("master.db was opened while a writer held rekordbox.lock")  # noqa: E731
    monkeypatch.setattr(rekordbox, "status", boom)
    holder = procs.holder(support, "writer")
    again = main_facts(api.rekordbox_status())
    assert again == {"ok": True, "state": "none", "running": False, "writing": True, "as_of": "2026-10-20T21:47:00"}
    procs.release(holder)


def test_status_with_a_writer_and_nothing_read_yet_answers_ready_writing_without_as_of(procs, support, monkeypatch):
    api, _ = make_unbound_api(support)
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: pytest.fail("opened"))
    holder = procs.holder(support, "writer")
    assert main_facts(api.rekordbox_status()) == {"ok": True, "state": "ready", "running": False, "writing": True, "as_of": None}
    procs.release(holder)


@needs_ffmpeg
def test_todo_and_track_never_open_master_db_while_a_writer_holds_rekordbox_lock(procs, tmp_path, monkeypatch):
    from discjockey.rekordbox import master
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "clean"])
    api, rec = make_api(lib.paths, rekordbox_running=lambda: False, rekordbox_place=lambda: lib.place)
    todo, track = api.todo(), api.track(lib.tracks[0])  # the first reads open it and fill the cache
    assert todo["ok"] and track["ok"]
    opened = []
    real = master.open_read
    monkeypatch.setattr(master, "open_read", lambda *a, **k: opened.append(a) or real(*a, **k))
    monkeypatch.setattr(rekordbox, "status", lambda *a, **k: pytest.fail("master.db was opened"))
    with open(lib.place.db, "ab") as f:  # master.db changed: a free reader would open it again
        f.write(b"\0")
    holder = procs.holder(lib.paths.support, "writer")
    assert api.todo()["ok"] and api.track(lib.tracks[0])["track"]["upgrade"] is not None
    assert api.rekordbox_status()["writing"] is True and opened == []
    procs.release(holder)


@needs_ffmpeg
def test_a_writer_can_start_while_a_plan_read_is_past_its_lookups(tmp_path, monkeypatch):
    """The shared hold lasts while master.db is open (the lookups), not through the plan's tag reads."""
    from discjockey.library import load_state
    lib = make_lib(tmp_path, monkeypatch, ["mp3", "aiff"])
    api, _ = make_api(lib.paths, rekordbox_running=lambda: False, rekordbox_place=lambda: lib.place)
    state = load_state(lib.paths)
    real, in_plan, go, seen = aiff_plan.plan, threading.Event(), threading.Event(), {}

    def slow_plan(*args, **kw):
        seen["entries"] = kw["entries"]
        in_plan.set()  # master.db is closed by now
        assert go.wait(10)
        return real(*args, **kw)

    monkeypatch.setattr(aiff_plan, "plan", slow_plan)
    out = []
    t = threading.Thread(target=lambda: out.append(api._planned_read(state, {"kind": "tracks", "tracks": lib.tracks})))
    t.start()
    try:
        assert in_plan.wait(30)
        started = time.monotonic()
        with rb_lock.writer_lock(lib.paths.support):  # no Busy: the plan holds nothing any more
            pass
        assert time.monotonic() - started < 1.0
    finally:
        go.set()
        t.join(30)
    plan, blind = out[0]
    assert blind is False and len(plan.items) + len(plan.skipped) == 2
    assert all(seen["entries"](lib.paths.root / p) for p in lib.olds)  # the lookups were made before the release


# --- the catalogue's `locks` column ---

def test_the_locks_words_are_the_four_of_the_design():
    assert catalog.LOCKS == ("library", "support", "rekordbox_w", "rekordbox_r")
    assert all(e.locks <= set(catalog.LOCKS) for e in catalog.ENTRIES)


def test_a_login_save_can_wait_longer_than_the_default_for_the_support_lock(tmp_path):
    def hold_briefly(seconds):
        with library.support_lock(tmp_path):
            time.sleep(seconds)

    assert library.SUPPORT_LOGIN_WAIT_S == 60.0
    holder = threading.Thread(target=hold_briefly, args=(0.3,))
    holder.start()
    time.sleep(0.1)  # the holder has the lock
    with library.support_lock(tmp_path, wait_s=1):  # waits the 0.2 s that are left
        pass
    holder.join()
    holder = threading.Thread(target=hold_briefly, args=(0.5,))
    holder.start()
    time.sleep(0.1)
    with pytest.raises(library.SupportBusy):
        with library.support_lock(tmp_path, wait_s=0.1):
            pass
    holder.join()
