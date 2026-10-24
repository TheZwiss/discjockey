import json
import threading
from contextlib import contextmanager
from datetime import date

import pytest
from audio_helpers import music, write_aiff

from discjockey import db, library, run, spotify
from discjockey.acquire import AcquireResult, Ready
from discjockey.events import ActionFinished, CancelToken, Message, ReadingPlaylist, RunFinished
from discjockey.library import Paths, empty_state, save_state
from discjockey.models import FetchedPlaylist, SpotifyTrack
from discjockey.settings import Account, Settings, save_settings

PLAYLISTS = "Hard_Bounce = https://open.spotify.com/playlist/0DiscjockeyExampleList\n"
TRACKS = [SpotifyTrack(f"t{i}", f"Song {i}", ("Artist",), "Al", None, 180000, None) for i in range(1, 4)]


@pytest.fixture
def paths(tmp_path, monkeypatch):
    p = Paths(tmp_path, support=tmp_path / ".support")
    p.data.mkdir()
    p.support.mkdir(parents=True, exist_ok=True)
    p.playlists_file.write_text(PLAYLISTS)
    monkeypatch.setattr(spotify, "load_session", lambda paths: spotify.Session("cid", paths.spotify_token, {}))
    monkeypatch.setattr(spotify, "fetch_playlist", lambda s, line: FetchedPlaylist(line, list(TRACKS), []))
    return p


class FakeAcquirer:
    def __init__(self, on_call=None):
        self.on_call, self.calls = on_call, 0

    def acquire(self, track, rejected, workdir, lossless_only, tracker, better_than=None):
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
    assert any(isinstance(e, Message) and "Spotify" in e.text for e in events)
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


def test_the_scan_waits_while_a_step_is_pending(paths):
    rel = placed(paths)
    state = library.load_state(paths)
    state["pending"].append({"track_id": "t9", "renames": [[".discjockey/.tmp/t9/x.aiff", "Library/A/x.aiff"]],
                             "entry": None})
    save_state(paths, state)
    (paths.root / rel).unlink()
    run.prepare(paths, dry_run=True)  # a dry run doesn't finish the step: its files are between two places
    assert library.load_state(paths)["tracks"]["t1"]["path"] == rel
