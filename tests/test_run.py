import copy
import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import date, datetime

import pytest
from audio_helpers import music, write_aiff

from discjockey import db, library, run
from discjockey.sources import spotify
from discjockey.acquire import AcquireResult, Ready
from discjockey.events import ActionFinished, CancelToken, Message, ReadingPlaylist, RunFinished
from discjockey.library import Paths, empty_state, save_state
from discjockey.models import FetchedPlaylist, Plan, PlannedMove, SourceTrack
from discjockey.settings import Account, Settings, save_settings

PLAYLISTS = "Hard_Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n"
TRACKS = [SourceTrack(f"t{i}", f"Song {i}", ("Artist",), "Al", None, 180000, None) for i in range(1, 4)]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    p = Paths(tmp_path, support=tmp_path / ".support")
    p.data.mkdir()
    p.support.mkdir(parents=True, exist_ok=True)
    p.playlists_file.write_text(PLAYLISTS)
    p.spotify_app.write_text(json.dumps({"client_id": "cid"}))  # what Setup leaves: the login check looks for it
    p.spotify_token.write_text(json.dumps({"access_token": "A", "refresh_token": "R", "expires_at": 0}))
    monkeypatch.setattr(spotify, "load_session", lambda paths: spotify.Session("cid", paths.spotify_token, {}))
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: FetchedPlaylist(line, list(TRACKS), []))
    return p


class FakeAcquirer:
    def __init__(self, on_call=None):
        self.on_call, self.calls = on_call, 0

    def acquire(self, track, rejected, workdir, lossless_only, tracker, better_than=None, exact=None, upload=None):
        self.calls += 1
        if self.on_call:
            self.on_call(self.calls, tracker)
        f = workdir / "q.aiff"
        f.write_bytes(b"audio")
        return AcquireResult("ready", Ready(f, "lossless", "qobuz", "q", "flac", None, "ok"))


def test_prepare_plans_and_needs_qobuz(paths):
    events = []
    prep = run.prepare(paths, emit=events.append)
    assert [a.kind for a in prep.plan.actions] == ["acquire"] * 3 and prep.needs_qobuz
    assert any(isinstance(e, Message) and "Reading your playlists..." == e.text for e in events)
    assert run.budget_text(prep).startswith("Qobuz today: 0 of 80 used")


def test_prepare_reports_recovered_steps(paths):
    state = empty_state()
    state["pending"].append({"track_id": "t9", "renames": [[".discjockey/.tmp/t9/x.aiff", "Library/A/x.aiff"]],
                             "entry": {"artist": "A", "title": "Lost", "path": "Library/A/x.aiff"}})
    save_state(paths, state)
    events = []
    prep = run.prepare(paths, emit=events.append)
    warnings = [e.text for e in events if isinstance(e, Message) and e.level == "warning"]
    assert warnings and "Lost" in warnings[0]
    assert prep.log.section("errors")


def test_prepare_closes_a_tidy_up_a_crash_left_open_and_says_so(paths):
    state = empty_state()
    for key in ("s1", "s2"):
        rel = f"Library/Old/A - {key}.aiff"
        (paths.root / rel).parent.mkdir(parents=True, exist_ok=True)
        (paths.root / rel).write_bytes(f"audio of {key}".encode())
        state["tracks"][key] = {"artist": "A", "title": key, "path": rel, "status": "lossless", "folder": "New",
                                "in_playlists": True}
    save_state(paths, state)
    ids = {k: e["file_id"] for k, e in library.load_state(paths)["tracks"].items()}
    moves = [PlannedMove("file", ids[k], f"A - {k}", f"Library/Old/A - {k}.aiff", f"Library/New/A - {k}.aiff",
                         None, "app", "app") for k in ("s1", "s2")]
    with db.connect(paths.db_file) as conn:  # a batch that was started, and nothing moved before the crash
        batch = db.start_batch(conn, started_by="tidy", about=None, undoes=None, moves=moves,
                               now=datetime(2026, 1, 1))
    events = []
    prep = run.prepare(paths, emit=events.append)
    said = [e.text for e in events if isinstance(e, Message) and "tidy-up was stopped" in e.text]
    assert said and "stopped before it moved anything" in said[0]
    assert prep.log.section("recovered")
    for key in ("s1", "s2"):  # the files not reached stay where they are
        assert (paths.root / f"Library/Old/A - {key}.aiff").exists()
        assert not (paths.root / f"Library/New/A - {key}.aiff").exists()
    with db.connect(paths.db_file) as conn:
        assert db.open_batches(conn) == []
        assert [(m.state, m.reason) for m in db.batch_moves(conn, batch)] == [("skipped", "stopped")] * 2


def test_setup_problems_are_reported_not_raised_raw(paths):
    paths.playlists_file.write_text("Bouncy =\n")
    with pytest.raises(run.SetupProblem, match="line 1"):
        run.prepare(paths)


def test_execute_writes_everything_and_announces_the_end(paths, monkeypatch):
    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: FakeAcquirer())
    events = []
    prep = run.prepare(paths)
    code, report = run.execute(prep, None, emit=events.append)
    assert code == 0 and report.exists() and report.with_suffix(".json").exists()
    assert isinstance(events[-1], RunFinished) and events[-1].exit_code == 0
    assert sum(isinstance(e, ActionFinished) for e in events) == 3
    assert (paths.data / "not_lossless.md").exists()


def test_stop_from_another_thread_gives_every_action_a_result(paths, monkeypatch):
    """The hub runs execute() in a worker thread and stops it from its window (here: the test's main thread)."""
    token = CancelToken()
    second_track_started = threading.Event()
    release = threading.Event()

    def on_call(n, tracker):
        if n == 2:
            second_track_started.set()
            release.wait(5)
            tracker.progress(1, 10, "bytes")  # the next progress report notices the stop

    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: FakeAcquirer(on_call))
    prep = run.prepare(paths)
    outcome = {}
    worker = threading.Thread(target=lambda: outcome.update(result=run.execute(prep, None, token=token)))
    worker.start()
    assert second_track_started.wait(5)
    token.cancel()
    release.set()
    worker.join(5)
    code, report = outcome["result"]
    assert code == 130
    results = json.loads(report.with_suffix(".json").read_text())["results"]
    assert [r["section"] for r in results] == ["new_lossless", "queued", "queued"]
    assert results[1]["note"] == "stopped before this track was done"
    assert not any((paths.tmp).iterdir())


def test_finish_quietly_without_actions(paths, monkeypatch):
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: FetchedPlaylist(line, [], []))
    prep = run.prepare(paths)
    code, report = run.finish_quietly(prep)
    assert code == 0 and report.exists() and paths.state_file.exists()


def test_execute_lets_qobuz_calls_notice_a_stop(paths, monkeypatch):
    class FakeQobuz:
        check = None

        def close(self):
            pass

    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: FakeAcquirer())
    token, qobuz = CancelToken(), FakeQobuz()
    run.execute(run.prepare(paths), qobuz, token=token)
    assert qobuz.check == token.check  # a Qobuz search or link request that hangs still reacts to Stop


def test_execute_lets_fallback_searches_notice_a_stop(paths, monkeypatch):
    seen = {}
    monkeypatch.setattr(run, "FallbackSource", lambda **kw: seen.update(kw))
    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: FakeAcquirer())
    token = CancelToken()
    run.execute(run.prepare(paths), None, token=token)
    assert seen["check"] == token.check


def test_a_step_that_could_not_be_finished_keeps_its_downloaded_file(paths, monkeypatch):
    from discjockey import library
    src = ".discjockey/.tmp/t9/x.aiff"
    (paths.root / src).parent.mkdir(parents=True)
    (paths.root / src).write_bytes(b"audio")
    state = empty_state()
    state["pending"].append({"track_id": "t9", "renames": [[src, "Library/A/x.aiff"]],
                             "entry": {"artist": "A", "title": "Stuck", "path": "Library/A/x.aiff"}})
    save_state(paths, state)

    def refuse(root, s, d):
        raise PermissionError("Operation not permitted")

    monkeypatch.setattr(library, "safe_rename", refuse)
    prep = run.prepare(paths)
    assert len(prep.state["pending"]) == 1  # tried again on the next start...
    assert (paths.root / src).read_bytes() == b"audio"  # ...and its file is still there for that


# --- for the hub: problem kinds, Stop while reading Spotify, the fetched playlists ---

def test_prepare_says_which_playlist_it_reads(paths):
    paths.playlists_file.write_text(PLAYLISTS + "Bouncy = https://open.spotify.com/playlist/3DiscjockeyExampleList\n")
    events = []
    run.prepare(paths, dry_run=True, emit=events.append)
    assert [e for e in events if isinstance(e, ReadingPlaylist)] == [
        ReadingPlaylist(1, 2, "Hard_Bounce"), ReadingPlaylist(2, 2, "Bouncy")]


def test_prepare_keeps_the_fetched_playlists(paths):
    prep = run.prepare(paths, dry_run=True)
    assert [fp.line.folder for fp in prep.fetched] == ["Hard_Bounce"]
    assert [t.id for t in prep.fetched[0].tracks] == ["t1", "t2", "t3"]
    assert [line.folder for line in prep.lines] == ["Hard_Bounce"]


@pytest.mark.parametrize("text,kind", [
    (None, "not_set_up"),
    ("# nothing active yet\n", "not_set_up"),
    ("Bouncy =\n", "config_invalid"),
])
def test_setup_problem_kinds_for_playlists_txt(paths, text, kind):
    if text is None:
        paths.playlists_file.unlink()
    else:
        paths.playlists_file.write_text(text)
    with pytest.raises(run.SetupProblem) as excinfo:
        run.prepare(paths)
    assert excinfo.value.kind == kind


def test_setup_problem_kind_for_a_broken_settings_file(paths):
    paths.support.mkdir(parents=True, exist_ok=True)
    paths.settings_file.write_text("{not json")
    with pytest.raises(run.SetupProblem) as excinfo:
        run.prepare(paths)
    assert excinfo.value.kind == "config_invalid"


@pytest.mark.parametrize("kind", ["not_set_up", "login_expired", "offline", "playlist_unreadable"])
def test_setup_problem_kind_from_spotify(paths, monkeypatch, kind):
    def fail(s, line):
        raise spotify.SpotifyError("Spotify says no", kind)

    monkeypatch.setattr(spotify, "fetch_playlist", fail)
    with pytest.raises(run.SetupProblem) as excinfo:
        run.prepare(paths)
    assert excinfo.value.kind == kind and str(excinfo.value) == "Spotify says no"


def test_a_missing_login_stops_before_any_network_call(paths, monkeypatch):
    paths.spotify_token.unlink()

    def never(*a, **k):
        raise AssertionError("no playlist may be read without a login")

    monkeypatch.setattr(spotify, "load_session", never)
    monkeypatch.setattr(spotify, "fetch_playlist", never)
    monkeypatch.setattr(spotify, "_http", never)
    rec = []
    with pytest.raises(run.SetupProblem) as excinfo:
        run.prepare(paths, emit=rec.append)
    assert excinfo.value.kind == "not_set_up" and excinfo.value.service == "spotify"
    assert str(excinfo.value) == "Spotify is not set up yet. Run: discjockey setup"
    assert not [e for e in rec if isinstance(e, ReadingPlaylist)]


def test_a_service_problem_names_its_service(paths, monkeypatch):
    def fail(s, line):
        raise spotify.SpotifyError("Spotify says no", "login_expired")

    monkeypatch.setattr(spotify, "fetch_playlist", fail)
    with pytest.raises(run.SetupProblem) as excinfo:
        run.prepare(paths)
    assert excinfo.value.service == "spotify"


def test_qobuz_problem_kinds(paths, monkeypatch):
    prep = run.prepare(paths)
    with pytest.raises(run.SetupProblem) as excinfo:  # no .streamrip/config.toml yet
        run.open_qobuz(prep)
    assert excinfo.value.kind == "not_set_up"
    assert library.load_state(paths)["qobuz_usage"]["signals"] == []  # not a warning sign from Qobuz: nothing recorded

    from discjockey import qobuz
    cfg = qobuz.config_file(paths)
    cfg.parent.mkdir(parents=True)
    cfg.write_text("")

    def refuse(cls, p):
        raise run.QobuzError("Qobuz did not accept your login. Run: discjockey setup")

    monkeypatch.setattr(run.QobuzSource, "open", classmethod(refuse))
    with pytest.raises(run.SetupProblem) as excinfo:
        run.open_qobuz(prep)
    assert excinfo.value.kind == "qobuz_login_failed"


def test_stop_while_spotify_asks_to_wait(paths, monkeypatch):
    """The hub's Stop reaches a Spotify read that waits out a rate limit, within about a second."""
    import time

    from discjockey.events import Cancelled, CancelToken
    paths.spotify_app.write_text(json.dumps({"client_id": "cid"}))
    paths.spotify_token.write_text(json.dumps({"access_token": "A", "refresh_token": "R",
                                               "expires_at": time.time() + 3600}))
    monkeypatch.undo()  # the real load_session and fetch_playlist
    monkeypatch.setattr(spotify, "_http", lambda *a, **k: (429, {"retry-after": "100"}, b""))
    token = CancelToken()
    threading.Timer(0.2, token.cancel).start()
    started = time.monotonic()
    with pytest.raises(Cancelled):
        run.prepare(paths, dry_run=True, token=token)
    assert time.monotonic() - started < 2


def test_stop_between_playlists(paths, monkeypatch):
    from discjockey.events import Cancelled, CancelToken
    paths.playlists_file.write_text(PLAYLISTS + "Other = https://open.spotify.com/playlist/3DiscjockeyExampleList\n")
    token = CancelToken()
    read = []

    def fetch(s, line):
        read.append(line.folder)
        token.cancel()
        return FetchedPlaylist(line, [], [])

    monkeypatch.setattr(spotify, "fetch_playlist", fetch)
    with pytest.raises(Cancelled):
        run.prepare(paths, dry_run=True, token=token)
    assert read == ["Hard_Bounce"]


# --- partial plans: the hub runs only what the user saw and left ticked ---

def test_action_key():
    from discjockey.models import Action
    t = TRACKS[0]
    assert run.action_key(Action("acquire", "t1", "A", t, (0, 0))) == ("acquire", "t1", "Library/A")
    assert run.action_key(Action("adopt_bought", "t1", "B", t, (0, 0), src="Library/A/x.aiff",
                                 dest_dir="Library/B")) == ("adopt_bought", "t1", "Library/B")


def test_select_actions_runs_only_ticked_ones_and_lists_the_rest(paths):
    prep = run.prepare(paths, dry_run=True)
    keys = [run.action_key(a) for a in prep.plan.actions]
    previewed = set(keys[:2])  # the third track was added in Spotify after the preview
    run.select_actions(prep, previewed, {keys[0]})
    assert [a.track_id for a in prep.plan.actions] == ["t1"]
    notes = {r.track_id: r.note for r in prep.log.section("queued")}
    assert notes == {"t2": "left out of this run by you", "t3": "new since the preview, next run"}


def test_select_actions_decides_whether_qobuz_is_needed(paths, monkeypatch):
    from discjockey.models import Action
    prep = run.prepare(paths, dry_run=True)
    bought = Action("adopt_bought", "t9", "Hard_Bounce", TRACKS[0], (0, 0), src="Library/B/x.aiff",
                    dest_dir="Library/Hard_Bounce")
    prep.plan.actions.append(bought)
    run.select_actions(prep, {run.action_key(a) for a in prep.plan.actions}, {run.action_key(bought)})
    assert not prep.needs_qobuz
    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, p: pytest.fail("no Qobuz login needed")))
    assert run.open_qobuz(prep) is None


def test_a_bought_file_whose_target_changed_is_not_run(paths):
    from discjockey.models import Action
    prep = run.prepare(paths, dry_run=True)
    seen = ("adopt_bought", "t1", "Library/Old_Target")
    prep.plan.actions = [Action("adopt_bought", "t1", "Hard_Bounce", TRACKS[0], (0, 0), src="Library/B/x.aiff",
                                dest_dir="Library/Hard_Bounce")]
    run.select_actions(prep, {seen}, {seen})
    assert prep.plan.actions == [] and prep.log.section("queued")[0].note == "new since the preview, next run"


class KbpsFallback:
    def __init__(self, rates):
        self.rates, self.asked = rates, []

    def stream_kbps(self, source, source_id):
        self.asked.append(source_id)
        rate = self.rates[source_id]
        if isinstance(rate, Exception):
            raise rate
        return rate


def _lossy(source_id, **extra):
    return {"artist": "A", "title": source_id, "status": "not_lossless", "path": f"Library/F/{source_id}.aiff",
            "source": "youtube_music", "source_id": source_id, **extra}


def test_fill_kbps_asks_only_lossy_downloads_without_a_bitrate():
    state = {"tracks": {
        "a": _lossy("a"), "b": _lossy("b", source_kbps=140), "c": _lossy("c"),
        "d": {**_lossy("d"), "status": "lossless", "source": "qobuz"},
        "e": {**_lossy("e"), "source": "manual"},
    }}
    events = []
    fb = KbpsFallback({"a": 131, "c": RuntimeError("Video unavailable")})
    assert run.fill_kbps(state, fb, events.append) == 1
    assert sorted(fb.asked) == ["a", "c"]
    assert state["tracks"]["a"]["source_kbps"] == 131
    assert not state["tracks"]["c"].get("source_kbps")  # tried again next sync
    assert state["tracks"]["b"]["source_kbps"] == 140
    assert any(isinstance(e, Message) and e.level == "debug" and "Video unavailable" in e.text for e in events)


def test_fill_kbps_does_nothing_when_all_are_known():
    assert run.fill_kbps({"tracks": {"b": _lossy("b", source_kbps=140)}}, None) == 0


def test_needs_qobuz_is_false_when_qobuz_is_skipped(paths):
    save_settings(paths.settings_file, Settings(qobuz_skipped=True))
    prep = run.prepare(paths)
    assert prep.plan.actions and not prep.needs_qobuz
    assert run.open_qobuz(prep) is None


def test_budget_text_has_a_line_per_service(paths):
    save_settings(paths.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}))
    lines = run.budget_text(run.prepare(paths)).splitlines()
    assert [line.split(" today")[0] for line in lines] == ["Qobuz", "YouTube Premium"]
    save_settings(paths.settings_file, Settings(qobuz_skipped=True, accounts={"youtube": Account("chrome", 30)}))
    assert run.budget_text(run.prepare(paths)).startswith("YouTube Premium today:")


def test_execute_hands_the_logins_and_account_budgets_on(paths, monkeypatch):
    save_settings(paths.settings_file, Settings(accounts={"soundcloud": Account("firefox", 60),
                                                          "youtube": Account("chrome", 30)}))
    seen = {}
    monkeypatch.setattr(run, "FallbackSource", lambda **kw: seen.update(fallback=kw))

    def acquirer(*a, **kw):
        seen["accounts"] = kw["accounts"]
        return FakeAcquirer()

    monkeypatch.setattr(run, "Acquirer", acquirer)
    run.execute(run.prepare(paths), None)
    assert seen["fallback"]["logins"] == {"soundcloud": ("firefox", None), "youtube": ("chrome", None)}
    assert list(seen["accounts"]) == ["youtube", "soundcloud"]
    assert seen["accounts"]["youtube"].service == "youtube"


# --- the scan before planning (plan library stage 1, task 3.3) ---

def placed(paths, key="t1", rel="Library/Hard_Bounce/Artist - Song 1.aiff"):
    """A song of the playlist Discjockey placed as lossless (records and a real small AIFF)."""
    (paths.root / rel).parent.mkdir(parents=True, exist_ok=True)
    write_aiff(paths.root / rel, music(1))
    state = empty_state()
    state["tracks"][key] = {"artist": "Artist", "title": "Song 1", "folder": "Hard_Bounce", "path": rel,
                            "status": "lossless", "source": "qobuz", "source_id": "q1", "source_format": "flac",
                            "duration_ms": 180000, "aliases": [], "in_playlists": True, "rejected_sources": [],
                            "added": "2026-10-01T10:00:00", "last_attempt": "2026-10-01",
                            "last_upgrade_check": date.today().isoformat()}
    save_state(paths, state)
    return rel


def test_a_file_moved_by_hand_is_not_downloaded_again(paths):
    rel = placed(paths)
    mine = paths.library / "My crate" / "Artist - Song 1.aiff"
    mine.parent.mkdir()
    (paths.root / rel).rename(mine)
    events = []
    prep = run.prepare(paths, emit=events.append)
    assert "t1" not in [a.track.id for a in prep.plan.actions if a.kind == "acquire"]
    e = library.load_state(paths)["tracks"]["t1"]
    assert (e["path"], e["placed_by"]) == ("Library/My crate/Artist - Song 1.aiff", "user")
    assert "Checked your Library: 1 file you moved." in [m.text for m in events if isinstance(m, Message)]


def test_a_dry_run_scans_too(paths):
    rel = placed(paths)
    (paths.root / rel).unlink()
    prep = run.prepare(paths, dry_run=True)
    assert library.load_state(paths)["tracks"]["t1"]["file_gone"] == date.today().isoformat()
    assert prep.state["tracks"]["t1"]["path"] is None  # the plan works on the files as they are
    assert "t1" in [a.track.id for a in prep.plan.actions if a.kind == "acquire"]


def test_without_the_lock_the_plan_reads_the_last_scan_and_writes_nothing(paths):
    rel = placed(paths)
    (paths.root / rel).unlink()

    @contextmanager
    def taken():
        yield False
    prep = run.prepare(paths, dry_run=True, lock=taken)
    assert library.load_state(paths)["tracks"]["t1"]["path"] == rel  # not scanned: nothing written
    assert prep.state["tracks"]["t1"]["path"] == rel


def test_prepare_builds_only_the_snapshots_it_needs(paths, monkeypatch):
    placed(paths)
    built = []
    snapshot = db.snapshot
    monkeypatch.setattr(db, "snapshot", lambda *a, **kw: built.append(1) or snapshot(*a, **kw))
    run.prepare(paths)
    assert len(built) == 2  # one for finishing interrupted steps, one after the scan for the plan
    built.clear()
    run.prepare(paths, dry_run=True)
    assert len(built) == 1


def test_a_dry_run_on_a_library_not_yet_migrated_finishes_no_pending_step(paths):
    tmp = paths.data / ".tmp" / "t9" / "x.aiff"
    tmp.parent.mkdir(parents=True)
    write_aiff(tmp, music(1, 0))
    v1 = {"version": 1, "tracks": {}, "never": {}, "qobuz_usage": {"days": {}, "signals": []},
          "pending": [{"track_id": "t9", "renames": [[".discjockey/.tmp/t9/x.aiff", "Library/A/x.aiff"]],
                       "entry": {"artist": "A", "title": "Lost", "folder": "A", "path": "Library/A/x.aiff",
                                 "status": "lossless", "source": "qobuz", "source_id": "q1"}}]}
    library.write_json_atomic(paths.state_file, v1, indent=2)
    before = paths.state_file.read_bytes()
    prep = run.prepare(paths, dry_run=True)
    assert tmp.exists() and not (paths.library / "A" / "x.aiff").exists()  # no music file was changed
    assert paths.state_file.read_bytes() == before and not paths.db_file.exists()  # recording the read made none
    assert len(prep.state["pending"]) == 1
    run.prepare(paths)  # the next sync finishes the step and moves the records
    assert (paths.library / "A" / "x.aiff").exists() and paths.db_file.exists()


def test_the_scan_waits_while_a_step_is_pending(paths):
    rel = placed(paths)
    state = library.load_state(paths)
    state["pending"].append({"track_id": "t9", "renames": [[".discjockey/.tmp/t9/x.aiff", "Library/A/x.aiff"]],
                             "entry": None})
    save_state(paths, state)
    (paths.root / rel).unlink()
    run.prepare(paths, dry_run=True)  # a dry run doesn't finish the step: its files are between two places
    assert library.load_state(paths)["tracks"]["t1"]["path"] == rel


def test_an_ambiguous_result_carries_the_song_key_not_the_tracks_own_id(paths, monkeypatch):
    qobuz_track = SourceTrack("900000001", "Song", ("Artist",), "Al", None, 180000, None, service="qobuz")
    monkeypatch.setattr(run.planner, "plan", lambda *a, **k: Plan(
        {"tracks": {}}, [], [("t1", qobuz_track, "Hard_Bounce", ["Library/A/x.aiff"])], []))
    prep = run.prepare(paths, dry_run=True)
    assert [(r.track_id, r.title) for r in prep.log.section("ambiguous")] == [("t1", "Song")]


# --- the user's own songs (plan library stage 4, task 3.6) ---

def _used_today(n):
    state = empty_state()
    state["qobuz_usage"] = {"days": {date.today().isoformat(): n}, "signals": []}
    return state


@pytest.mark.parametrize("used, room", [(0, 25), (30, 25), (60, 10), (79, 0), (80, 0)])
def test_first_check_room_is_at_most_half_of_what_qobuz_has_left_today(used, room):
    # 60 a day and 20 carried over from a quiet yesterday: 80 today
    assert run.first_check_room(_used_today(used), Settings()) == room


def test_first_check_room_without_qobuz_is_the_cap():
    assert run.first_check_room(_used_today(80), Settings(qobuz_skipped=True)) == run.FIRST_CHECKS_PER_RUN == 25


def test_prepare_and_replan_plan_with_the_first_check_room(paths, monkeypatch):
    seen = []
    real = run.planner.plan
    monkeypatch.setattr(run.planner, "plan", lambda *a, **k: seen.append(k.get("first_checks")) or real(*a, **k))
    prep = run.prepare(paths, dry_run=True)  # the preview shows what the run does (W9)
    run.replan(prep)
    assert seen == [25, 25]


def own_song(paths):
    """A song of the user's own (`local:1`) with a file: Song 1 of the playlist, 0.5 s longer."""
    rel = "Library/Mine/Artist - Song 1.aiff"
    (paths.root / rel).parent.mkdir(parents=True, exist_ok=True)
    write_aiff(paths.root / rel, music(1))
    state = empty_state()
    state["tracks"]["local:1"] = {"artist": "Artist", "title": "Song 1", "folder": "", "path": rel,
                                  "status": "lossless", "source": "manual", "source_id": None, "source_format": "flac",
                                  "duration_ms": 180500, "aliases": [], "in_playlists": False, "rejected_sources": [],
                                  "added": "2026-10-01T10:00:00", "last_attempt": None,
                                  "last_upgrade_check": None}
    save_state(paths, state)


def test_link_only_saves_the_links_and_downloads_nothing(paths, monkeypatch):
    own_song(paths)
    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: pytest.fail("nothing is downloaded"))
    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, p: pytest.fail("no Qobuz login")))
    prep = run.prepare(paths)
    assert library.load_state(paths)["tracks"]["local:1"]["aliases"] == []  # planned, not saved yet
    meanwhile = library.load_state(paths)  # another write since (the import's): prep's snapshot is stale
    meanwhile["tracks"]["local:1"]["last_attempt"] = "2026-10-02"
    save_state(paths, meanwhile)
    with pytest.raises(library.StateError):
        save_state(paths, copy.deepcopy(prep.state))
    events = []
    fresh = run.link_only(paths, prep, events.append)
    tracks = library.load_state(paths)["tracks"]
    assert tracks["local:1"]["aliases"] == ["t1"] and tracks["local:1"]["in_playlists"] is True
    assert "t2" not in tracks and "t3" not in tracks
    assert [(a.kind, a.track_id) for a in fresh.plan.actions] == [("acquire", "t2"), ("acquire", "t3")]
    assert [e.text for e in events] == ["Artist - Song 1: the same song as a file of yours, not downloaded."]
    assert library.load_state(paths)["tracks"]["local:1"]["last_attempt"] == "2026-10-02"  # the other write stays


def test_files_waiting_to_be_imported_reach_prepared(paths, tmp_path_factory):
    run.prepare(paths)  # makes library.db
    assert run.prepare(paths).import_waiting == 0
    mine = tmp_path_factory.mktemp("mine")
    write_aiff(mine / "Example Artist - Night Drive.aiff", music(2))
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, mine, datetime.now())
    prep = run.prepare(paths)  # its scan finds the file
    assert prep.import_waiting == 1
    assert run.replan(prep).import_waiting == 1


def test_an_import_links_its_files_with_the_real_link_only_from_a_stale_read(paths, tmp_path_factory, monkeypatch):
    from discjockey import importer
    from discjockey.quality import AudioInfo
    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: pytest.fail("nothing is downloaded"))
    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, p: pytest.fail("no Qobuz login")))
    prep = run.prepare(paths)  # the window's read, before the import writes anything
    mine = tmp_path_factory.mktemp("mine")
    write_aiff(mine / "Artist - Song 1.aiff", music(1))
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, mine, datetime.now())
    events = []
    result = importer.run_import(paths, emit=events.append, token=CancelToken(),
                                 link=lambda: importer.link_playlists(paths, prep, emit=events.append),
                                 probe=lambda p: AudioInfo("pcm_s16be", 44100, 180.5),
                                 inspect=lambda p: ("pcm_s16be", None))
    assert (result.own_songs, result.link_note) == (1, None)
    tracks = library.load_state(paths)["tracks"]
    assert tracks["local:1"]["aliases"] == ["t1"] and tracks["local:1"]["in_playlists"] is True
    assert tracks["local:1"]["import_state"] == "done"  # the link kept what the import wrote
    assert "t2" not in tracks  # nothing downloaded or planned into the records
    assert "Artist - Song 1: the same song as a file of yours, not downloaded." in [
        e.text for e in events if isinstance(e, Message)]


# --- plan library stage 5, B1.4: every read is kept as the playlists' records (D1) ---

BOUNCE = "0DiscjockeyExampleList"
BOUNCY = "3DiscjockeyExampleList"
TWO_PLAYLISTS = PLAYLISTS + f"Bouncy = https://open.spotify.com/playlist/{BOUNCY}\n"


def recorded(paths):
    """{ref: [track tokens]} of library.db's read records."""
    with db.connect(paths.db_file) as conn:
        return {ref: [t.token for t in r.tracks] for ref, r in db.playlist_records(conn).items()}


def per_playlist(monkeypatch, tracks_of):
    monkeypatch.setattr(spotify, "fetch_playlist",
                        lambda s, line: FetchedPlaylist(line, list(tracks_of[line.playlist_id]), []))


def test_a_sync_keeps_what_it_read_as_the_playlists_records(paths):
    run.prepare(paths)
    with db.connect(paths.db_file) as conn:
        record = db.playlist_records(conn)[BOUNCE]
    assert record.service == "spotify" and record.read_at.startswith(date.today().isoformat())
    assert [(t.position, t.token, t.artist, t.title, t.duration_ms) for t in record.tracks] == [
        (1, "t1", "Artist", "Song 1", 180000), (2, "t2", "Artist", "Song 2", 180000),
        (3, "t3", "Artist", "Song 3", 180000)]


def test_a_dry_run_keeps_its_read_too_with_or_without_the_lock(paths, monkeypatch):
    save_state(paths, empty_state())  # a library with library.db
    run.prepare(paths, dry_run=True)
    assert recorded(paths) == {BOUNCE: ["t1", "t2", "t3"]}

    @contextmanager
    def taken():
        yield False
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: FetchedPlaylist(line, list(TRACKS[:1]), []))
    run.prepare(paths, dry_run=True, lock=taken)  # the window's read while a job holds the lock
    assert recorded(paths) == {BOUNCE: ["t1"]}


def test_a_playlist_that_cant_be_read_or_is_switched_off_keeps_its_record(paths, monkeypatch):
    paths.playlists_file.write_text(TWO_PLAYLISTS)
    per_playlist(monkeypatch, {BOUNCE: TRACKS, BOUNCY: TRACKS[2:]})
    run.prepare(paths)
    assert recorded(paths) == {BOUNCE: ["t1", "t2", "t3"], BOUNCY: ["t3"]}

    def unreadable(s, line):
        raise spotify.SpotifyError("Spotify answered HTTP 404.", "playlist_unreadable")
    monkeypatch.setattr(spotify, "fetch_playlist", unreadable)
    with pytest.raises(run.SetupProblem):
        run.prepare(paths)
    assert recorded(paths) == {BOUNCE: ["t1", "t2", "t3"], BOUNCY: ["t3"]}

    paths.playlists_file.write_text(PLAYLISTS + f"#off# Bouncy = https://open.spotify.com/playlist/{BOUNCY}\n")
    per_playlist(monkeypatch, {BOUNCE: TRACKS[:2]})
    run.prepare(paths)
    assert recorded(paths) == {BOUNCE: ["t1", "t2"], BOUNCY: ["t3"]}  # off, not read: its record stays

    paths.playlists_file.write_text(PLAYLISTS)  # its line is gone: so is its record
    run.prepare(paths)
    assert recorded(paths) == {BOUNCE: ["t1", "t2"]}


def test_a_failing_record_never_fails_the_read(paths, monkeypatch, caplog):
    run.prepare(paths)

    def locked(*a, **kw):
        raise sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(db, "record_reads", locked)
    prep = run.prepare(paths, dry_run=True)
    assert [a.kind for a in prep.plan.actions] == ["acquire"] * 3
    [warning] = [r for r in caplog.records if "couldn't keep the playlists' read records" in r.getMessage()]
    assert warning.exc_info is not None  # unexpected: with its traceback


def test_records_of_another_version_are_one_warning_line(paths, caplog):
    run.prepare(paths)
    fetched = run.prepare(paths, dry_run=True).fetched  # (prepare itself then refuses the records before reading)
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE meta SET value = ? WHERE key = 'schema_version'", (str(db.SCHEMA_VERSION + 1),))
    run.record_reads(paths, fetched, datetime.now())
    [warning] = [r for r in caplog.records if "couldn't keep the playlists' read records" in r.getMessage()]
    assert warning.exc_info is None and warning.getMessage() == (
        f"couldn't keep the playlists' read records: {db.NEWER}")


def test_a_long_job_transaction_holds_the_read_up_briefly_not_for_the_full_wait(paths, caplog):
    run.prepare(paths)
    before = recorded(paths)
    other = sqlite3.connect(str(paths.db_file), isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # a job's long transaction (an import's scan)

    @contextmanager
    def taken():
        yield False
    start = time.monotonic()
    try:
        prep = run.prepare(paths, dry_run=True, lock=taken)
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert time.monotonic() - start < run.RECORD_WAIT_MS / 1000 + 2  # far below the binding 5 s
    assert [fp.line.folder for fp in prep.fetched] == ["Hard_Bounce"]
    assert "couldn't keep the playlists' read records" in caplog.text
    assert recorded(paths) == before
