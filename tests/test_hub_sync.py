import json
from datetime import date, datetime
import threading
import time
from contextlib import contextmanager

import pytest

from discjockey import run, spotify
from discjockey.acquire import AcquireResult, Ready
from discjockey.events import RunFinished
from discjockey.hub import jobs
from discjockey.hub import views
from discjockey.hub.jobs import Jobs, PreviewStore
from discjockey.library import Paths, empty_state, load_state, save_state
from discjockey.settings import load_settings
from discjockey.models import FetchedPlaylist, SpotifyTrack

PLAYLISTS = "Hard_Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n"
TRACKS = [SpotifyTrack(f"t{i}", f"Song {i}", ("Artist",), "Al", None, 180000, None) for i in range(1, 4)]


class FakeAcquirer:
    def __init__(self):
        self.tracks = []

    def acquire(self, track, rejected, workdir, lossless_only, tracker):
        self.tracks.append(track.id)
        f = workdir / "q.aiff"
        f.write_bytes(b"audio")
        return AcquireResult("ready", Ready(f, "lossless", "qobuz", "q" + track.id, "flac", None, "ok"))


class Recorder:
    def __init__(self):
        self.events = []

    def __call__(self, event):
        self.events.append(event)

    def finished(self):
        return [e for e in self.events if isinstance(e, jobs.JobFinished)][-1]


@contextmanager
def no_awake(reason):
    yield


@pytest.fixture
def env(tmp_path, monkeypatch):
    paths = Paths(tmp_path, support=tmp_path / ".support")
    paths.data.mkdir()
    paths.playlists_file.write_text(PLAYLISTS)
    tracks = list(TRACKS)
    monkeypatch.setattr(spotify, "load_session", lambda p: spotify.Session("cid", p.spotify_token, {}))
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: FetchedPlaylist(line, list(tracks), []))
    acq = FakeAcquirer()
    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: acq)
    logins = []

    class FakeQobuz:
        check = None

        def close(self):
            pass

    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, p: logins.append(1) or FakeQobuz()))
    rec = Recorder()
    return paths, Jobs(paths.lock, rec, keep_awake=no_awake), PreviewStore(), rec, acq, logins, tracks


def refresh(js, paths, store):
    job = js.start_refresh(jobs.refresh_work(paths, store))
    assert job.done.wait(5)


def test_refresh_reads_spotify_and_keeps_the_preview(env):
    paths, js, store, rec, acq, logins, tracks = env
    save_state(paths.state_file, empty_state())
    before = paths.state_file.read_bytes()
    refresh(js, paths, store)
    assert rec.finished().ok and rec.finished().result == {"actions": 3}
    assert [a.track_id for a in store.prep.plan.actions] == ["t1", "t2", "t3"] and store.read_at is not None
    assert paths.state_file.read_bytes() == before  # read-only
    assert not (paths.data / "reports").exists()


def test_a_failed_refresh_keeps_the_last_known_preview(env, monkeypatch):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)
    first = store.prep

    def offline(s, line):
        raise spotify.SpotifyError("Cannot reach Spotify (no connection).", "offline")

    monkeypatch.setattr(spotify, "fetch_playlist", offline)
    refresh(js, paths, store)
    assert (rec.finished().ok, rec.finished().problem) == (False, "offline")
    assert store.prep is first and store.problem == "offline" and "Cannot reach" in store.message


def sync(js, paths, store, ticked):
    job = js.start("sync", jobs.sync_work(paths, store, ticked))
    assert job.done.wait(10)


def test_sync_runs_only_ticked_actions(env):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)
    keys = store.keys()
    ticked = {k for k in keys if k[1] != "t2"}
    sync(js, paths, store, ticked)
    assert acq.tracks == ["t1", "t3"] and logins == [1]
    finished = rec.finished()
    assert finished.ok and finished.result["exit_code"] == 0 and finished.result["actions"] == 2
    report = json.loads(open(finished.result["report"].replace(".md", ".json")).read())
    assert {r["track_id"]: r["note"] for r in report["results"] if r["section"] == "queued"} == {
        "t2": "left out of this run by you"}
    # the plan is worked out again from the run's own Spotify read and the library as the run left it (issue 20)
    assert [a.track_id for a in store.prep.plan.actions] == ["t2"] and not store.stale


def test_after_a_full_sync_the_preview_is_up_to_date_without_another_read(env, monkeypatch):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)
    reads = []
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: reads.append(1) or FetchedPlaylist(line, list(tracks), []))
    sync(js, paths, store, store.keys())
    assert reads == [1]  # only the sync's own read
    assert store.prep.plan.actions == [] and not store.stale and store.read_at is not None
    preview = views.sync_preview(store, load_state(paths.state_file), load_settings(paths.settings_file),
                                 date.today(), datetime.now(), False)
    assert preview["empty"] == "up_to_date" and preview["counts"] is not None


def crash_on(track_id, monkeypatch):
    """A bug outside the per-track safety net (each action's own errors only fail that track): the run itself stops."""
    add = run.rep.RunLog.add

    def broken(self, result):
        if result.track_id == track_id:
            raise KeyError("path")
        add(self, result)
    monkeypatch.setattr(run.rep.RunLog, "add", broken)


def main_text(md: str) -> str:
    return md.split("## Details for a bug report")[0]


def test_a_crash_during_the_run_files_a_crash_note_as_the_runs_report(env, monkeypatch):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)
    crash_on("t2", monkeypatch)
    sync(js, paths, store, store.keys())
    finished = rec.finished()
    assert (finished.ok, finished.problem) == (False, "crashed") and finished.message == run.rep.CRASH_MESSAGE
    result = finished.result
    assert result["exit_code"] == 1 and result["actions"] == 3 and result["new_since_preview"] == 0
    md = open(result["report"], encoding="utf-8").read()
    note = main_text(md)
    assert "The sync stopped unexpectedly" in note and "Artist - Song 2" in note and "KeyError" not in note
    assert "saved" in note and "Traceback" not in note
    assert "Traceback" in md and "KeyError: 'path'" in md.split("## Details for a bug report")[1]  # below the note
    data = json.loads(open(result["report"].replace(".md", ".json")).read())
    assert data["exit_code"] == 1 and "Song 2" in data["crashed"]
    assert [r["track_id"] for r in data["results"] if r["section"] == "new_lossless"] == ["t1"]
    assert [(e.exit_code, e.report_path) for e in rec.events if isinstance(e, RunFinished)] == [(1, result["report"])]
    assert [a.track_id for a in store.prep.plan.actions] == ["t3"]  # t2 was in place before the crash: saved state


def test_a_crash_before_the_run_starts_still_files_a_note(env, monkeypatch):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)

    def broken(*a, **k):
        raise RuntimeError("bad plan")

    monkeypatch.setattr(run.planner, "plan", broken)
    sync(js, paths, store, store.keys())
    finished = rec.finished()
    assert (finished.ok, finished.problem) == (False, "crashed") and finished.message == run.rep.CRASH_MESSAGE
    note = main_text(open(finished.result["report"], encoding="utf-8").read())
    assert "reading your Spotify playlists" in note and "RuntimeError" not in note
    assert "RuntimeError: bad plan" in open(finished.result["report"], encoding="utf-8").read()
    assert finished.result["actions"] == 0 and finished.result["exit_code"] == 1


def test_a_setup_problem_writes_no_crash_note(env, monkeypatch):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)
    monkeypatch.setattr(run, "open_qobuz", lambda prep: (_ for _ in ()).throw(run.SetupProblem("x", "not_set_up")))
    sync(js, paths, store, store.keys())
    assert rec.finished().problem == "not_set_up" and rec.finished().result is None
    assert not (paths.data / "reports").exists()


def test_actions_new_since_the_preview_wait_for_the_next_run(env):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)
    ticked = store.keys()
    tracks.append(SpotifyTrack("t4", "Song 4", ("Artist",), "Al", None, 180000, None))  # added in Spotify meanwhile
    sync(js, paths, store, ticked)
    assert acq.tracks == ["t1", "t2", "t3"]
    assert rec.finished().result["new_since_preview"] == 1


def test_nothing_ticked_finishes_quietly_without_qobuz(env):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)
    sync(js, paths, store, set())
    assert acq.tracks == [] and logins == []  # filtered before open_qobuz: no login for nothing
    assert rec.finished().ok and rec.finished().result["actions"] == 0
    assert any(isinstance(e, RunFinished) for e in rec.events)  # the end screen works the same way
    assert paths.state_file.exists()  # finish_quietly saved flags and wrote the report


def test_sync_without_a_preview_is_refused(env):
    paths, js, store, rec, acq, logins, tracks = env
    sync(js, paths, store, set())
    assert (rec.finished().ok, rec.finished().problem) == (False, "refused")
    assert "Read your Spotify playlists first" in rec.finished().message


def test_a_setup_problem_ends_the_sync_with_its_kind(env, monkeypatch):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)

    def expired(s, line):
        raise spotify.SpotifyError("Your Spotify login has expired.", "login_expired")

    monkeypatch.setattr(spotify, "fetch_playlist", expired)
    sync(js, paths, store, store.keys())
    assert (rec.finished().ok, rec.finished().problem) == (False, "login_expired")


def test_stop_during_the_sync(env, monkeypatch):
    paths, js, store, rec, acq, logins, tracks = env
    refresh(js, paths, store)

    def stop_on_second(track, rejected, workdir, lossless_only, tracker):
        if track.id == "t2":
            js.stop()
            tracker.progress(1, 10, "bytes")
        return FakeAcquirer.acquire(acq, track, rejected, workdir, lossless_only, tracker)

    monkeypatch.setattr(acq, "acquire", stop_on_second)
    sync(js, paths, store, store.keys())
    finished = rec.finished()
    assert finished.ok and finished.result["exit_code"] == 130  # stopped safely: a normal end of a run
    assert [e.exit_code for e in rec.events if isinstance(e, RunFinished)] == [130]


REAL_FETCH = spotify.fetch_playlist  # the env fixture replaces it


def test_stop_ends_a_read_stuck_in_one_slow_request_and_its_late_result_is_dropped(env, monkeypatch):
    """Stop while the only playlist's request hangs (no token check inside a request): the job ends within ~2 s as
    stopped; when the request answers later, its plan is not stored and no second JobFinished follows."""
    paths, js, store, rec, acq, logins, tracks = env
    entered, release = threading.Event(), threading.Event()
    page = {"items": [{"track": {"id": "t9", "name": "Late", "artists": [{"name": "A"}], "album": {},
                                 "duration_ms": 180000}}], "next": None}

    def slow_http(method, url, headers=None, form=None):
        entered.set()
        release.wait(10)
        return 200, {}, json.dumps(page).encode()

    token = {"access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
    monkeypatch.setattr(spotify, "load_session", lambda p: spotify.Session("cid", p.spotify_token, dict(token)))
    monkeypatch.setattr(spotify, "fetch_playlist", REAL_FETCH)
    monkeypatch.setattr(spotify, "_http", slow_http)
    job = js.start_refresh(jobs.refresh_work(paths, store))
    assert entered.wait(5)
    t0 = time.monotonic()
    assert js.stop_refresh()
    assert job.done.wait(2) and time.monotonic() - t0 < 2
    assert (rec.finished().ok, rec.finished().problem) == (False, "stopped")
    assert not js.status()["refresh_running"]
    release.set()
    worker = next(t for t in threading.enumerate() if t.name == f"hub-refresh-{job.id}")
    worker.join(5)
    assert not worker.is_alive()
    assert store.prep is None and store.read_at is None and store.problem is None  # the late plan was dropped
    assert len([e for e in rec.events if isinstance(e, jobs.JobFinished)]) == 1
