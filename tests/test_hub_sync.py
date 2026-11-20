import json
from datetime import date, datetime
import threading
import time
from contextlib import contextmanager

import pytest

from discjockey import db, run
from discjockey.sources import qobuz as qobuz_source, spotify
from discjockey.sources.base import LoginState
from discjockey.acquire import AcquireResult, Ready
from discjockey.events import RunFinished
from discjockey.hub import jobs
from discjockey.hub import views
from discjockey.hub.jobs import Jobs
from discjockey.library import Paths, empty_state, load_state, save_state
from discjockey.settings import load_settings
from discjockey.models import FetchedPlaylist, PlaylistInfo, SourceTrack

PLAYLISTS = "Hard_Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n"
TRACKS = [SourceTrack(f"t{i}", f"Song {i}", ("Artist",), "Al", None, 180000, None) for i in range(1, 4)]


class FakeAcquirer:
    def __init__(self):
        self.tracks = []

    def acquire(self, track, rejected, workdir, lossless_only, tracker, exact=None, upload=None):
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
    monkeypatch.setattr(spotify, "login_state", lambda p: LoginState("ok"))
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
    return paths, Jobs(paths.lock, rec, keep_awake=no_awake), lambda: derived(paths), rec, acq, logins, tracks


def derived(paths):
    """The plan `HubApi._plan` derives from the stored read (no cache); None before a good read."""
    if not paths.db_file.exists():
        return None
    with db.connect(paths.db_file, read_only=True) as conn:
        loaded = db.load_read(conn)
    return None if loaded is None else run.prepared_from_read(paths, loaded)


def head(paths):
    """The stored read's head (`db.read_head`): its problem, service and words are what the window shows."""
    with db.connect(paths.db_file, read_only=True) as conn:
        return db.read_head(conn)


def planned_of(plan):
    """The plan now as a stored Sync plan holds it (what a sync's `planned` is): action id -> (kind, track_id, to_dir)."""
    prep = plan()
    ids = run.action_ids(prep) if prep else {}
    return {ids[run.action_key(a)]: run.action_key(a) for a in prep.plan.actions} if prep else {}


def refresh(js, paths):
    job = js.start_refresh(jobs.refresh_work(paths))
    assert job.done.wait(5)


def test_refresh_reads_spotify_and_keeps_the_preview(env):
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())
    before = load_state(paths)
    refresh(js, paths)
    assert rec.finished().ok and rec.finished().result == {"actions": 3, "read_id": "read:1"}
    assert [a.track_id for a in plan().plan.actions] == ["t1", "t2", "t3"] and head(paths).read_at is not None
    assert load_state(paths) == before  # read-only
    assert not (paths.data / "reports").exists()


def test_the_windows_read_keeps_the_playlists_records(env):
    """Plan library stage 5, D1: the read the window shows is also what its playlist views show later, offline."""
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())
    refresh(js, paths)
    assert rec.finished().ok
    with db.connect(paths.db_file) as conn:
        records = db.playlist_records(conn)
    assert list(records) == ["0DiscjockeyExampleList"]
    assert [(t.token, t.title) for t in records["0DiscjockeyExampleList"].tracks] == [
        ("t1", "Song 1"), ("t2", "Song 2"), ("t3", "Song 3")]


def test_a_failed_refresh_keeps_the_last_known_preview(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    first = [a.track_id for a in plan().plan.actions]

    def offline(s, line):
        raise spotify.SpotifyError("Cannot reach Spotify (no connection).", "offline")

    monkeypatch.setattr(spotify, "fetch_playlist", offline)
    refresh(js, paths)
    assert (rec.finished().ok, rec.finished().problem) == (False, "offline")
    assert [a.track_id for a in plan().plan.actions] == first  # the last good read's plan stays
    assert head(paths).problem == "offline" and "Cannot reach" in head(paths).message


def test_a_refresh_names_the_read_it_stored(env):
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())
    refresh(js, paths)
    assert rec.finished().result["read_id"] == "read:1"
    refresh(js, paths)
    assert rec.finished().result["read_id"] == "read:2"
    with db.connect(paths.db_file, read_only=True) as conn:
        assert db.load_read(conn).id == 2 and db.read_head(conn).problem is None


def test_a_refresh_whose_read_could_not_be_stored_fails_with_a_message(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())
    monkeypatch.setattr(run, "store_read", lambda *a, **k: None)  # library.db busy: nothing was stored
    refresh(js, paths)
    done = rec.finished()
    assert (done.ok, done.problem) == (False, "failed") and "could not be saved" in done.message
    assert plan() is None  # and there is no plan to show: the page does not claim a read it has not got


def test_a_playlist_that_turns_unreadable_loses_its_stored_name_and_cover(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())
    page = PlaylistInfo("spotify", "0DiscjockeyExampleList", "Hard Bounce", "me", "Me", False, "https://img.example/c.jpg",
                        3, True, True)
    monkeypatch.setattr(spotify, "playlist_info", lambda s, pid, me: page)
    monkeypatch.setattr(spotify, "current_user", lambda s: ("me", "Me"))
    assert js.start_refresh(jobs.refresh_work(paths, infos={})).done.wait(5) and rec.finished().ok
    assert list(stored_infos(paths)) == ["0DiscjockeyExampleList"]

    def unreadable(s, pid, me):
        raise spotify.SpotifyError("Spotify doesn't show this playlist.", "playlist_unreadable")

    monkeypatch.setattr(spotify, "playlist_info", unreadable)
    assert js.start_refresh(jobs.refresh_work(paths, infos={})).done.wait(5) and rec.finished().ok
    assert stored_infos(paths) == {}


def stored_infos(paths):
    with db.connect(paths.db_file, read_only=True) as conn:
        return db.stored_infos(conn)


def test_a_failed_refresh_stores_its_problem_beside_the_last_good_tracks(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())
    refresh(js, paths)

    def offline(s, line):
        raise spotify.SpotifyError("Cannot reach Spotify (no connection).", "offline")

    monkeypatch.setattr(spotify, "fetch_playlist", offline)
    refresh(js, paths)
    with db.connect(paths.db_file, read_only=True) as conn:
        loaded = db.load_read(conn)
    assert loaded.id == 1 and [t.id for t in loaded.fetched[0].tracks] == ["t1", "t2", "t3"]
    assert (loaded.problem, loaded.problem_service, loaded.message) == ("offline", "spotify", head(paths).message)
    assert "Cannot reach" in loaded.message


def test_a_stopped_refresh_stores_no_problem(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())

    def stopped_then_failing(s, line):
        assert js.stop_refresh()  # Stop arrives, the read ends in a failure meanwhile
        raise spotify.SpotifyError("Cannot reach Spotify (no connection).", "offline")

    monkeypatch.setattr(spotify, "fetch_playlist", stopped_then_failing)
    job = js.start_refresh(jobs.refresh_work(paths))
    assert job.done.wait(5)
    with db.connect(paths.db_file, read_only=True) as conn:
        assert db.read_head(conn) is None


def test_the_refresh_stores_the_playlists_infos_it_found(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    save_state(paths, empty_state())
    page = PlaylistInfo("spotify", "0DiscjockeyExampleList", "Hard Bounce", "me", "Me", False, None, 3, True, True)
    monkeypatch.setattr(spotify, "playlist_info", lambda s, pid, me: page)
    monkeypatch.setattr(spotify, "current_user", lambda s: ("me", "Me"))
    infos = {}
    job = js.start_refresh(jobs.refresh_work(paths, infos=infos))
    assert job.done.wait(5) and rec.finished().ok
    with db.connect(paths.db_file, read_only=True) as conn:
        assert db.stored_infos(conn) == infos and list(infos) == ["0DiscjockeyExampleList"]


def test_a_missing_qobuz_login_files_the_problem_under_qobuz(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    paths.playlists_file.write_text(PLAYLISTS + "Example_Playlist = https://open.qobuz.com/playlist/900000001\n")
    monkeypatch.setattr(qobuz_source, "login_state", lambda p: LoginState("missing", qobuz_source.NOT_SET_UP))
    refresh(js, paths)
    assert (rec.finished().ok, rec.finished().problem) == (False, "not_set_up")
    read = head(paths)
    assert (read.problem, read.problem_service) == ("not_set_up", "qobuz") and "Qobuz" in read.message
    status = views.read_status(views.ReadView(problem=read.problem, problem_service=read.problem_service,
                                              message=read.message), datetime(2026, 10, 20, 21, 47), False,
                               [("spotify", True), ("qobuz", False)])
    assert status["problem_service"] == "qobuz"
    assert status["services"] == [{"service": "spotify", "name": "Spotify", "connected": True},
                                  {"service": "qobuz", "name": "Qobuz", "connected": False}]


def test_a_spotify_problem_names_spotify_and_a_good_read_clears_it(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env

    def expired(s, line):
        raise spotify.SpotifyError("Your Spotify login has expired.", "login_expired")

    monkeypatch.setattr(spotify, "fetch_playlist", expired)
    refresh(js, paths)
    assert (head(paths).problem, head(paths).problem_service) == ("login_expired", "spotify")
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: FetchedPlaylist(line, list(tracks), []))
    refresh(js, paths)
    assert (head(paths).problem, head(paths).problem_service) == (None, None)


def sync(js, paths, planned, ticked=None):
    """A sync of the plan `planned` that runs the actions with these keys (None: all of them)."""
    chosen = [act for act, key in planned.items() if ticked is None or key in ticked]
    job = js.start("sync", jobs.sync_work(paths, planned, chosen))
    assert job.done.wait(10)


def test_sync_runs_only_ticked_actions(env):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    planned = planned_of(plan)
    sync(js, paths, planned, {k for k in planned.values() if k[1] != "t2"})
    assert acq.tracks == ["t1", "t3"] and logins == [1]
    finished = rec.finished()
    assert finished.ok and finished.result["exit_code"] == 0 and finished.result["actions"] == 2
    report = json.loads(open(finished.result["report"].replace(".md", ".json")).read())
    assert {r["track_id"]: r["note"] for r in report["results"] if r["section"] == "queued"} == {
        "t2": "left out of this run by you"}
    # the plan is derived from the run's own stored read and the library as the run left it (issue 20)
    assert [a.track_id for a in plan().plan.actions] == ["t2"]


def test_after_a_full_sync_the_preview_is_up_to_date_without_another_read(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    reads = []
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: reads.append(1) or FetchedPlaylist(line, list(tracks), []))
    sync(js, paths, planned_of(plan))
    assert reads == [1]  # only the sync's own read
    assert plan().plan.actions == [] and head(paths).read_at is not None
    preview = views.sync_preview(views.ReadView(plan(), head(paths).read_at), load_state(paths), load_settings(paths.settings_file),
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
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    crash_on("t2", monkeypatch)
    sync(js, paths, planned_of(plan))
    finished = rec.finished()
    assert (finished.ok, finished.problem) == (False, "crashed") and finished.message == run.rep.CRASH_MESSAGE
    result = finished.result
    assert result["exit_code"] == 1 and result["actions"] == 3 and result["new_since_plan"] == []
    md = open(result["report"], encoding="utf-8").read()
    note = main_text(md)
    assert "The sync stopped unexpectedly" in note and "Artist - Song 2" in note and "KeyError" not in note
    assert "saved" in note and "Traceback" not in note
    assert "Traceback" in md and "KeyError: 'path'" in md.split("## Details for a bug report")[1]  # below the note
    data = json.loads(open(result["report"].replace(".md", ".json")).read())
    assert data["exit_code"] == 1 and "Song 2" in data["crashed"]
    assert [r["track_id"] for r in data["results"] if r["section"] == "new_lossless"] == ["t1"]
    assert [(e.exit_code, e.report_path) for e in rec.events if isinstance(e, RunFinished)] == [(1, result["report"])]
    assert [a.track_id for a in plan().plan.actions] == ["t3"]  # t2 was in place before the crash: saved state


def test_a_crash_before_the_run_starts_still_files_a_note(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)

    def broken(*a, **k):
        raise RuntimeError("bad plan")

    planned = planned_of(plan)
    monkeypatch.setattr(run.planner, "plan", broken)
    sync(js, paths, planned)
    finished = rec.finished()
    assert (finished.ok, finished.problem) == (False, "crashed") and finished.message == run.rep.CRASH_MESSAGE
    note = main_text(open(finished.result["report"], encoding="utf-8").read())
    assert "reading your playlists" in note and "RuntimeError" not in note
    assert "RuntimeError: bad plan" in open(finished.result["report"], encoding="utf-8").read()
    assert finished.result["actions"] == 0 and finished.result["exit_code"] == 1


def test_a_setup_problem_writes_no_crash_note(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    monkeypatch.setattr(run, "open_qobuz", lambda prep: (_ for _ in ()).throw(run.SetupProblem("x", "not_set_up")))
    sync(js, paths, planned_of(plan))
    assert rec.finished().problem == "not_set_up" and rec.finished().result is None
    assert not (paths.data / "reports").exists()


def test_actions_new_since_the_plan_wait_for_the_next_run_and_are_listed_by_their_ids(env):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    planned = planned_of(plan)
    tracks.append(SourceTrack("t4", "Song 4", ("Artist",), "Al", None, 180000, None))  # added in Spotify meanwhile
    sync(js, paths, planned)
    assert acq.tracks == ["t1", "t2", "t3"]
    assert rec.finished().result["new_since_plan"] == ["act:acquire:t4:1"]  # its id in the run's fresh plan


def test_an_action_whose_target_moved_is_not_run_and_is_listed_as_new(env):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    planned = {act: (k, t, "Library/Elsewhere" if t == "t1" else d) for act, (k, t, d) in planned_of(plan).items()}
    sync(js, paths, planned)  # the plan said t1 goes elsewhere; today it goes to the playlist's folder
    assert acq.tracks == ["t2", "t3"]
    assert rec.finished().result["new_since_plan"] == ["act:acquire:t1:1"] and rec.finished().result["actions"] == 2
    report = json.loads(open(rec.finished().result["report"].replace(".md", ".json")).read())
    assert {r["track_id"]: r["note"] for r in report["results"] if r["section"] == "queued"} == {
        "t1": run.NEW_SINCE_PREVIEW}


def test_a_sync_runs_only_the_ids_it_is_given_in_any_order(env):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    planned = planned_of(plan)
    job = js.start("sync", jobs.sync_work(paths, planned, ["act:acquire:t3:1", "act:acquire:t1:1"]))
    assert job.done.wait(10)
    assert sorted(acq.tracks) == ["t1", "t3"] and rec.finished().result["new_since_plan"] == []


def test_nothing_ticked_finishes_quietly_without_qobuz(env):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    sync(js, paths, planned_of(plan), set())
    assert acq.tracks == [] and logins == []  # filtered before open_qobuz: no login for nothing
    assert rec.finished().ok and rec.finished().result["actions"] == 0
    assert any(isinstance(e, RunFinished) for e in rec.events)  # the end screen works the same way
    assert paths.state_file.exists()  # finish_quietly saved flags and wrote the report


def test_a_setup_problem_ends_the_sync_with_its_kind(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)

    def expired(s, line):
        raise spotify.SpotifyError("Your Spotify login has expired.", "login_expired")

    monkeypatch.setattr(spotify, "fetch_playlist", expired)
    sync(js, paths, planned_of(plan))
    assert (rec.finished().ok, rec.finished().problem) == (False, "login_expired")


def test_stop_during_the_sync(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)

    def stop_on_second(track, rejected, workdir, lossless_only, tracker, exact=None, upload=None):
        if track.id == "t2":
            js.stop()
            tracker.progress(1, 10, "bytes")
        return FakeAcquirer.acquire(acq, track, rejected, workdir, lossless_only, tracker)

    monkeypatch.setattr(acq, "acquire", stop_on_second)
    sync(js, paths, planned_of(plan))
    finished = rec.finished()
    assert finished.ok and finished.result["exit_code"] == 130  # stopped safely: a normal end of a run
    assert [e.exit_code for e in rec.events if isinstance(e, RunFinished)] == [130]


REAL_FETCH = spotify.fetch_playlist  # the env fixture replaces it


def test_stop_ends_a_read_stuck_in_one_slow_request_and_its_late_result_is_dropped(env, monkeypatch):
    """Stop while the only playlist's request hangs (no token check inside a request): the job ends within ~2 s as
    stopped; when the request answers later, its plan is not stored and no second JobFinished follows."""
    paths, js, plan, rec, acq, logins, tracks = env
    entered, release = threading.Event(), threading.Event()
    page = {"items": [{"track": {"id": "t9", "name": "Late", "artists": [{"name": "A"}], "album": {},
                                 "duration_ms": 180000}}], "next": None}

    def slow_http(method, url, headers=None, form=None):
        entered.set()
        release.wait(10)
        return 200, {}, json.dumps(page).encode()

    token = {"access_token": "a", "refresh_token": "r", "expires_at": time.time() + 3600}
    monkeypatch.setattr(spotify, "load_session", lambda p: spotify.Session("cid", p.spotify_token, dict(token)))
    monkeypatch.setattr(spotify, "login_state", lambda p: LoginState("ok"))
    monkeypatch.setattr(spotify, "fetch_playlist", REAL_FETCH)
    monkeypatch.setattr(spotify, "_http", slow_http)
    job = js.start_refresh(jobs.refresh_work(paths))
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
    assert plan() is None  # the late plan was dropped
    assert len([e for e in rec.events if isinstance(e, jobs.JobFinished)]) == 1


QOBUZ_PLAYLISTS = "Hard_Bounce = https://open.qobuz.com/playlist/900000001\n"
CONSOLE_TEXT = "Your playlists include a Qobuz playlist, but Qobuz isn't set up yet. Run: discjockey setup"


def test_a_missing_login_reads_as_connect_first_and_names_its_service(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    paths.playlists_file.write_text(QOBUZ_PLAYLISTS)
    monkeypatch.setattr(qobuz_source, "login_state", lambda p: LoginState("missing", CONSOLE_TEXT))
    refresh(js, paths)
    done = rec.finished()
    assert (done.ok, done.problem, done.service, done.message) == (False, "not_set_up", "qobuz", "Connect Qobuz first.")
    read = head(paths)
    assert (read.problem, read.problem_service, read.message) == ("not_set_up", "qobuz", "Connect Qobuz first.")
    assert "discjockey setup" not in done.message


def test_a_sync_that_fails_while_reading_keeps_the_service_and_the_hub_words(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    paths.playlists_file.write_text(PLAYLISTS + QOBUZ_PLAYLISTS.replace("Hard_Bounce", "Deep_Cuts"))
    monkeypatch.setattr(qobuz_source, "login_state", lambda p: LoginState("missing", CONSOLE_TEXT))
    sync(js, paths, planned_of(plan))
    done = rec.finished()
    assert (done.ok, done.problem, done.service) == (False, "not_set_up", "qobuz")
    assert done.message == "Connect Qobuz first." and not logins  # nothing was downloaded or logged in to


def test_a_job_that_is_not_about_a_service_finishes_without_one(env):
    paths, js, plan, rec, acq, logins, tracks = env
    refresh(js, paths)
    assert rec.finished().service is None
    sync(js, paths, planned_of(plan), set())
    assert rec.finished().service is None


def test_a_hub_read_logs_in_to_qobuz_once_and_takes_the_playlist_page_from_the_tracks(env, monkeypatch):
    paths, js, plan, rec, acq, logins, tracks = env
    paths.playlists_file.write_text(QOBUZ_PLAYLISTS)
    monkeypatch.setattr(qobuz_source, "login_state", lambda p: LoginState("ok"))
    page = PlaylistInfo("qobuz", "900000001", "Example Playlist", "7", "Example Curator", False, None, 1, False, True)
    opened = []

    class OneLoginReader:
        want_info = False

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            pass

        def fetch(self, line):
            return FetchedPlaylist(line, [], [], page if self.want_info else None)

        def info(self, playlist_id):
            raise AssertionError("the page was in the tracks' answer: no second request, no second login")

    monkeypatch.setattr(qobuz_source, "open", lambda p, t: opened.append(1) or OneLoginReader())
    infos = {}
    job = js.start_refresh(jobs.refresh_work(paths, infos=infos))
    assert job.done.wait(5) and rec.finished().ok
    assert opened == [1] and infos == {"qobuz:900000001": page}
    # a read without the page (the console's sync, a plan after a run) doesn't ask for it
    opened.clear()
    job = js.start_refresh(jobs.refresh_work(paths))
    assert job.done.wait(5) and opened == [1]


# --- the plan is derived from the stored read, in any process (issue 39 phase 2, V2.2b) ---

from hub_helpers import (ID1, fake_import, fake_spotify, import_folder, make_api, make_root, music_root, refreshed, sync_plan,
                         store_sync_read, wait_job)
from discjockey.models import PlaylistLine, StoredRead
from discjockey.settings import Settings, save_settings


def rows_of_reads(paths):
    """Everything the reads keep in library.db, to compare before and after."""
    with db.connect(paths.db_file, read_only=True) as conn:
        return [conn.execute(f"SELECT * FROM {table} ORDER BY 1, 2").fetchall()
                for table in ("reads", "playlist_reads", "playlist_tracks", "playlist_infos")]


def jobs_folder(paths):
    folder = paths.support / "jobs"
    return sorted(p.name for p in folder.iterdir()) if folder.is_dir() else []


def test_another_process_has_the_plan_a_read_made_and_asking_writes_nothing(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    fakes = fake_import(monkeypatch)
    paths = music_root(tmp_path, upgrade=True)
    folder = import_folder(tmp_path, 3)
    a, rec = make_api(paths)
    refreshed(a, rec)
    fakes.tags["Example Artist - Song 1.aiff"] = {"artist": "Other Artist", "title": "AEIOU"}
    fakes.seconds["Example Artist - Song 1.aiff"] = 180.0
    wait_job(a, rec, a.add_watched_folder(str(folder)))
    shown = a.sync_preview()
    questions = {i["track_id"] for g in a.todo()["groups"] if g["key"] == "same_song" for i in g["items"]}
    assert shown["groups"] and shown["read_id"] == "read:1" and questions
    before = (rows_of_reads(paths), jobs_folder(paths))
    b, _ = make_api(paths)  # a second window / the command line: no memory of A's read
    again = b.sync_preview()
    assert again["read_id"] == shown["read_id"] and again["groups"] == shown["groups"]
    assert again["read_status"]["read_at"] == shown["read_status"]["read_at"]
    assert b.dashboard()["ready"] is not None and b.dashboard()["ready"] == a.dashboard()["ready"]
    assert {i["track_id"] for g in b.todo()["groups"] if g["key"] == "same_song" for i in g["items"]} == questions
    assert (rows_of_reads(paths), jobs_folder(paths)) == before  # S3: the plan is derived, asking writes nothing


@pytest.fixture
def hub(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    paths = make_root(tmp_path)
    derived, loads = [], []
    real_plan, real_load = run.prepared_from_read, db.load_read
    monkeypatch.setattr(run, "prepared_from_read", lambda p, loaded: derived.append(loaded.id) or real_plan(p, loaded))
    monkeypatch.setattr(db, "load_read", lambda conn: loads.append(1) or real_load(conn))
    api, rec = make_api(paths)
    return api, rec, paths, derived, loads


def test_the_plan_is_derived_once_per_read_records_settings_and_day(hub):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    api.sync_preview()
    api.sync_preview()
    api.todo()
    assert (len(derived), len(loads)) == (1, 1)  # the second ask is the cached plan: no read loaded, nothing planned
    check = StoredRead("check", datetime.now(), [FetchedPlaylist(PlaylistLine("Hard_Bounce", ID1, 2), list(TRACKS), [])])
    with db.connect(paths.db_file) as conn:
        db.store_read(conn, check, None)  # a check read may replace a record the plan's songs come from
    api.sync_preview()
    assert len(derived) == 2 and derived[-1] == 1  # still the sync read the plan is from
    refreshed(api, rec)  # a new stored read
    api.sync_preview()
    assert len(derived) == 3 and derived[-1] == 3
    wait_job(api, rec, api.hide("t2", True))  # a write of the records bumps their generation
    api.sync_preview()
    assert len(derived) == 4
    save_settings(paths.settings_file, Settings(daily_qobuz_limit=50))  # a changed settings.json
    api.sync_preview()
    assert len(derived) == 5
    api._svc.now = lambda: datetime(2026, 10, 21, 8, 0)  # the day moves on: today's budgets and first checks changed
    api.sync_preview()
    assert len(derived) == 6
    api.sync_preview()
    assert len(derived) == 6
    assert len(loads) == len(derived)


def test_a_hub_sync_makes_its_own_read_the_plan_and_needs_a_stored_read_to_start(hub):
    api, rec, paths, derived, loads = hub
    refused = api.start_sync(api.sync_preview()["plan_id"], [])  # no read yet: no plan id (null), nothing starts
    assert (refused["ok"], refused["kind"]) == (False, "refused") and "Read your playlists first" in refused["message"]
    refreshed(api, rec)
    assert api.sync_preview()["read_id"] == "read:1"
    plan_id, ids = sync_plan(api)
    assert ids
    f = wait_job(api, rec, api.start_sync(plan_id, []))  # nothing ticked: a quiet sync, which still reads and stores itself
    assert f.ok and f.result["new_since_plan"] == [] and f.result["actions"] == 0
    assert api.sync_preview()["read_id"] == "read:2"  # the run's own read is the newest: the plan is derived from it


def test_a_failed_first_read_shows_its_problem_in_a_new_window_with_no_plan(hub):
    api, rec, paths, derived, loads = hub
    store_sync_read(paths, failed=("not_set_up", "qobuz", "Connect Qobuz first."))
    b, _ = make_api(paths)
    status = b.job_status()["read_status"]
    assert (status["problem"], status["problem_service"], status["message"]) == ("not_set_up", "qobuz", "Connect Qobuz first.")
    assert status["read_at"] is None and status["lines_changed"] is False
    preview = b.sync_preview()
    assert preview["empty"] == "no_preview" and preview["read_id"] is None and preview["read_status"]["problem"] == "not_set_up"
    assert derived == []


def test_the_automatic_read_is_refused_the_second_time(hub):
    api, rec, paths, derived, loads = hub
    assert wait_job(api, rec, api.refresh(auto=True)).ok
    again = api.refresh(auto=True)
    assert (again["ok"], again["kind"]) == (False, "refused") and api.job_status()["read_status"]["auto_read"] is True
    assert make_api(paths)[0].job_status()["read_status"]["auto_read"] is False  # the window's own, not stored


REFUSED = '{"auto_upgrade": 7}'  # a settings.json the planner refuses (and `HubApi._settings` falls back from)


def answered(answer):
    return not (isinstance(answer, dict) and answer.get("ok") is False)


def test_a_refused_settings_file_leaves_every_page_but_the_sync_preview_answering(hub):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    paths.settings_file.write_text(REFUSED)
    for answer in (api.dashboard(), api.job_status(), api.sidebar(), api.todo(), api.library(), api.playlists(),
                   api.limits(), api.tidy_preview()):
        assert answered(answer), answer
    for status in (api.dashboard()["read_status"], api.job_status()["read_status"]):
        assert status["problem"] == "config_invalid" and "settings.json" in status["message"]
        assert status["read_at"] is not None and status["lines_changed"] is False
    assert api.dashboard()["ready"] is None  # no plan to count


def test_a_refused_settings_file_is_the_error_of_the_sync_preview_and_of_a_sync(hub):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    plan_id = api.sync_preview()["plan_id"]
    paths.settings_file.write_text(REFUSED)
    refused = api.sync_preview()
    assert refused["ok"] is False and "settings.json" in refused["message"]
    f = wait_job(api, rec, api.start_sync(plan_id, []))
    assert (f.ok, f.problem) == (False, "config_invalid") and "Read your playlists first" not in f.message
    assert api.never_download("t1", True)["ok"] is False


def test_job_status_derives_no_plan(hub):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    api.sync_preview()
    assert len(derived) == 1
    with db.connect(paths.db_file) as conn:
        db._bump(conn)  # the records' generation moves on, as an import's or a sync's writes do
    status = api.job_status()["read_status"]
    assert status["read_at"] is not None and status["lines_changed"] is False and len(derived) == 1
    paths.playlists_file.write_text("")  # no line on any more: the read's lines are gone from the file
    assert api.job_status()["read_status"]["lines_changed"] is True and len(derived) == 1


def test_a_plan_cached_for_another_library_is_a_miss(hub, tmp_path):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    api.sync_preview()
    assert len(derived) == 1
    key, prep = api._plan_cache
    other = (str(tmp_path / "elsewhere"), *key[1:])
    api._plan_cache = (other, prep)  # a plan that finished for library A after the hub switched to B
    api.sync_preview()
    assert len(derived) == 2


def test_playlists_changed_to_none_on_shows_as_changed(hub):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    assert api.job_status()["read_status"]["lines_changed"] is False
    paths.playlists_file.write_text("# Hard_Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n")
    assert api.job_status()["read_status"]["lines_changed"] is True
    assert api.sync_preview()["read_status"]["lines_changed"] is True


@pytest.mark.parametrize("name", ["sync_preview", "library", "todo"])
def test_a_page_asks_for_the_plan_once(hub, monkeypatch, name):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    asked = []
    real = api._derive
    monkeypatch.setattr(api, "_derive", lambda *a, **k: asked.append(1) or real(*a, **k))
    getattr(api, name)()
    assert len(asked) == 1


# --- the plan binding (issue 39 phase 2): the plan another window saved, the job's args and the last sync ---

def test_a_plan_saved_by_one_hub_starts_in_a_new_hub_on_the_same_folder(hub):
    api, rec, paths, derived, loads = hub
    refreshed(api, rec)
    plan_id, ids = sync_plan(api)
    assert ids
    other, other_rec = make_api(paths)  # another window or the command line: no memory of A's save, the same plans/
    wrong = other.start_sync(plan_id, [ids[0], "act:acquire:nope:1"])  # the ids are checked against A's saved plan
    assert (wrong["kind"], "act:acquire:nope:1" in wrong["message"]) == ("refused", True)
    f = wait_job(other, other_rec, other.start_sync(plan_id, []))
    assert f.ok and f.result["actions"] == 0 and f.result["new_since_plan"] == []


def wait_for(read, timeout=5.0):
    """The value `read()` gives as soon as it is not None (a registry record is written a moment after the end)."""
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        if (value := read()) is not None:
            return value
        time.sleep(0.01)
    raise AssertionError("it did not come")


def test_a_sync_records_what_it_was_started_with_and_job_status_names_the_last_sync(hub, monkeypatch):
    api, rec, paths, derived, loads = hub
    assert api.job_status()["last_sync"] is None
    refreshed(api, rec)
    plan_id, ids = sync_plan(api)
    held, release, real = threading.Event(), threading.Event(), run.prepare

    def held_prepare(*a, **k):
        held.set()
        release.wait(5)
        return real(*a, **k)

    monkeypatch.setattr(run, "prepare", held_prepare)
    answer = api.start_sync(plan_id, [])
    assert held.wait(5)
    state = json.loads((paths.support / "jobs" / answer["job_id"] / "state.json").read_text())
    assert state["kind"] == "sync" and state["args"] == {"plan_id": plan_id, "selected": []}
    running = api.job_status()["last_sync"]
    assert running == {"job": answer["job_id"], "args": {"plan_id": plan_id, "selected": []}, "ended": None}
    release.set()
    wait_job(api, rec, answer)
    done = wait_for(lambda: api.job_status()["last_sync"]["ended"])
    assert api.job_status()["last_sync"] == {"job": answer["job_id"], "args": {"plan_id": plan_id, "selected": []},
                                             "ended": done}
    other, _ = make_api(paths)
    assert other.job_status()["last_sync"]["job"] == answer["job_id"]  # a reloaded window finds it in the registry


def test_a_sync_record_with_malformed_args_answers_empty_ones(hub):
    api, rec, paths, derived, loads = hub
    folder = paths.support / "jobs" / "job:0badc0de"
    folder.mkdir(parents=True)
    (folder / "state.json").write_text(json.dumps({"id": "job:0badc0de", "kind": "sync", "args": {"plan_id": 7, "selected": "x"},
                                                   "roots": {"music": str(paths.root)}, "started": "2099-01-01T00:00:00",
                                                   "status": "done", "ended": None}))
    assert api.job_status()["last_sync"] == {"job": "job:0badc0de", "args": {"plan_id": None, "selected": []},
                                             "ended": None}
    (folder / "state.json").write_text(json.dumps({"id": "job:0badc0de", "kind": "sync", "args": {"selected": ["a", 3]},
                                                   "roots": {"music": str(paths.root)}, "started": "2099-01-01T00:00:00"}))
    assert api.job_status()["last_sync"]["args"] == {"plan_id": None, "selected": ["a"]}
    (folder / "state.json").write_text(json.dumps({"id": "job:0badc0de", "kind": "refresh", "args": {},
                                                   "roots": {"music": str(paths.root)}, "started": "2099-01-01T00:00:00"}))
    assert api.job_status()["last_sync"] is None  # a refresh is no sync
