import json
import threading
import time

import pytest
from hub_helpers import LOSSY, PARKED, fake_spotify, make_api, make_root, refreshed, wait_job, write

from discjockey import library, run
from discjockey.sources import spotify
from discjockey.acquire import AcquireResult, Ready
from discjockey.align import Alignment
from discjockey.events import SourceChosen
from discjockey.hub import jobs
from discjockey.library import load_state, run_lock, save_state
from discjockey.models import Candidate, ScanSummary
from discjockey.settings import Account, Settings, load_settings, save_settings


@pytest.fixture
def root(tmp_path, monkeypatch):
    fake_spotify(monkeypatch)
    return make_root(tmp_path, upgrade=True)


def oplog(root):
    return [json.loads(line) for line in (root.reports / "operations.jsonl").read_text().splitlines()]


def test_hide_through_the_bridge(root):
    api, rec = make_api(root)
    api.todo()  # what the page shows
    f = wait_job(api, rec, api.hide("t2", True))
    assert f.ok and f.kind == "hide" and f.result["result"]["section"] == "hidden"
    assert load_state(root)["tracks"]["t2"]["hidden"] is True
    assert oplog(root)[-1]["operation"] == "hide" and "(hidden)" in root.not_lossless_md.read_text()
    assert [g["key"] for g in api.todo()["groups"]] == ["not_found"]
    assert api.todo("all", True)["hidden_count"] == 1


def test_precondition_refusal_when_the_console_changed_the_track(root):
    api, rec = make_api(root)
    api.track("t2")
    state = load_state(root)  # the console placed a lossless file a minute ago
    state["tracks"]["t2"].update(status="lossless", path="Library/Hard_Bounce/Armin Hermann - Get Naughty.aiff",
                                 upgrade=None)
    save_state(root, state)
    before = library.load_state(root)
    f = wait_job(api, rec, api.hide("t2", True))
    assert (f.ok, f.problem) == (False, "changed") and "changed in the meantime" in f.message
    assert library.load_state(root) == before
    assert oplog(root)[-1]["result"] == "changed"


def test_a_track_never_shown_is_refused(root):
    api, rec = make_api(root)
    f = wait_job(api, rec, api.hide("t2", True))
    assert f.problem == "changed"


def test_interrupted_steps_are_recovered_first_and_reported(root):
    api, rec = make_api(root)
    api.todo()
    src, dst = ".discjockey/.tmp/t9/x.aiff", "Library/Powertrance/Other - Nine.aiff"
    write(root, src, b"placed")
    state = load_state(root)
    state["pending"].append({"track_id": "t9", "renames": [[src, dst]],
                             "entry": {"artist": "Other", "title": "Nine", "folder": "Powertrance", "path": dst,
                                       "status": "lossless"}})
    save_state(root, state)
    f = wait_job(api, rec, api.hide("t2", True))
    assert f.ok and f.result["recovered"] == [["Finished an interrupted step for Other - Nine", True]]
    assert (root.root / dst).read_bytes() == b"placed"


def test_only_one_change_at_a_time_and_none_during_a_console_run(root):
    api, rec = make_api(root)
    api.todo()
    with run_lock(root.lock):
        answer = api.hide("t2", True)
    assert answer == {"ok": False, "kind": "console", "message": jobs.CONSOLE_TEXT}
    release = threading.Event()
    api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    assert api.hide("t2", True)["kind"] == "busy"
    release.set()
    api._jobs.wait(5)


def test_rescan_library_runs_a_scan_job_and_counts_what_it_found(root, monkeypatch):
    api, rec = make_api(root)
    seen = {}

    def fake_scan(paths, emit):
        seen["paths"] = paths
        return ScanSummary(moved=1, new=2, gone=3, replaced=4, copies=5, offline=1)
    monkeypatch.setattr(library, "scan_library", fake_scan)
    f = wait_job(api, rec, api.rescan_library())
    assert f.ok and f.kind == "scan" and seen["paths"] == root
    assert f.result == {"moved": 1, "new": 2, "gone": 3, "changed": 4, "copies": 5}


def test_a_scan_that_changed_something_plans_the_preview_again_without_reading_spotify(root, monkeypatch):
    api, rec = make_api(root)
    refreshed(api, rec)
    before, read_at = api._store.prep, api._store.read_at
    monkeypatch.setattr(spotify, "fetch_playlist", lambda *a, **k: pytest.fail("the scan read Spotify"))
    replans, real = [], run.replan
    monkeypatch.setattr(run, "replan", lambda prep: replans.append(prep) or real(prep))
    monkeypatch.setattr(library, "scan_library", lambda paths, emit: ScanSummary())
    assert wait_job(api, rec, api.rescan_library()).ok
    assert replans == [] and api._store.prep is before  # nothing changed: the preview stays as it is
    monkeypatch.setattr(library, "scan_library", lambda paths, emit: ScanSummary(gone=1))
    assert wait_job(api, rec, api.rescan_library()).ok
    assert replans == [before] and api._store.prep is not before
    assert api._store.prep.fetched is before.fetched and api._store.read_at == read_at


def test_a_scan_without_a_preview_plans_nothing(root, monkeypatch):
    api, rec = make_api(root)
    monkeypatch.setattr(run, "replan", lambda prep: pytest.fail("nothing to plan again"))
    monkeypatch.setattr(library, "scan_library", lambda paths, emit: ScanSummary(gone=1))
    assert wait_job(api, rec, api.rescan_library()).ok and api._store.prep is None


def test_rescan_library_on_a_real_library_finishes_without_a_problem(root):
    api, rec = make_api(root)
    f = wait_job(api, rec, api.rescan_library())
    assert f.ok and set(f.result) == {"moved", "new", "gone", "changed", "copies"}
    assert all(isinstance(n, int) for n in f.result.values())


def test_rescan_library_answers_busy_and_console_at_once(root):
    api, rec = make_api(root)
    with run_lock(root.lock):
        assert api.rescan_library() == {"ok": False, "kind": "console", "message": jobs.CONSOLE_TEXT}
    release = threading.Event()
    api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    assert api.rescan_library() == {"ok": False, "kind": "busy", "message": jobs.BUSY_TEXT}
    release.set()
    api._jobs.wait(5)


def test_a_change_while_a_scan_runs_hears_that_the_library_is_being_checked(root):
    api, rec = make_api(root)
    api.todo()
    release, running = threading.Event(), threading.Event()

    def slow(ctx):
        running.set()
        release.wait(5)
    api._jobs.start("scan", slow)
    assert running.wait(5)
    assert api.hide("t2", True) == {"ok": False, "kind": "busy", "message": jobs.SCANNING_TEXT}
    release.set()
    api._jobs.wait(5)
    entered, done = threading.Event(), threading.Event()

    def preview_scan():  # the Sync preview's scan holds the lock without a job
        with api._jobs.scan_lock() as held:
            assert held
            entered.set()
            done.wait(5)
    t = threading.Thread(target=preview_scan)
    t.start()
    assert entered.wait(5)
    assert api.hide("t2", True) == {"ok": False, "kind": "busy", "message": jobs.SCANNING_TEXT}
    done.set()
    t.join(5)


def test_swap_through_the_bridge(root):
    api, rec = make_api(root, compare=lambda cur, new: Alignment("exact", 0, 0.0, 0.0, "matches exactly"))
    api.track("t2")
    f = wait_job(api, rec, api.upgrade("t2", "swap"))
    assert f.ok and f.result["result"]["section"] == "swapped"
    e = load_state(root)["tracks"]["t2"]
    assert e["status"] == "lossless" and e["path"] == "Library/Hard_Bounce/Armin Hermann - Get Naughty.aiff"
    assert (root.root / e["path"]).read_bytes() == b"parked lossless"
    assert (root.root / "Superseded/Hard_Bounce/Armin Hermann - Get Naughty (lossy).aiff").read_bytes() == \
        b"lossy audio"
    assert not (root.root / PARKED).exists()


def test_swap_refused_when_the_versions_do_not_line_up(root):
    api, rec = make_api(root, compare=lambda cur, new: Alignment("different", text="doesn't line up"))
    api.track("t2")
    f = wait_job(api, rec, api.upgrade("t2", "swap"))
    assert (f.ok, f.problem) == (False, "refused") and "Not swapped" in f.message
    assert (root.root / LOSSY).read_bytes() == b"lossy audio"


def test_an_upgrade_no_longer_waiting_is_called_a_better_version(tmp_path, monkeypatch):
    # a parked file can be a 256 kbps stream, so the refusal must not call it lossless
    fake_spotify(monkeypatch)
    root = make_root(tmp_path)
    api, rec = make_api(root)
    api.track("t2")
    f = wait_job(api, rec, api.upgrade("t2", "swap"))
    assert (f.ok, f.problem) == (False, "changed")
    assert f.message == "No better version is waiting for this track any more."


def test_add_new_and_discard(root):
    api, rec = make_api(root)
    api.track("t2")
    assert wait_job(api, rec, api.upgrade("t2", "discard")).ok
    e = load_state(root)["tracks"]["t2"]
    assert e["upgrade"] is None and "qobuz:q2" in e["rejected_sources"]
    assert api.upgrade("t2", "explode")["kind"] == "refused"


def test_save_the_qobuz_limit(root):
    api, rec = make_api(root)
    assert wait_job(api, rec, api.save_limits("qobuz", 90, 20)).ok
    assert json.loads(root.settings_file.read_text()) == {"daily_qobuz_limit": 90,
                                                         "extra_today": {"date": "2026-10-20", "amount": 20},
                                                         "qobuz_skipped": False, "warnings_seen": {}, "qobuz_last_check": None,
                                                             "accounts": {}}
    assert api.limits("qobuz")["usage"]["today"]["allowance"] == 90 + 30 + 20
    assert wait_job(api, rec, api.save_limits("qobuz", 60, 0)).ok
    assert json.loads(root.settings_file.read_text())["extra_today"] is None
    assert api.save_limits("qobuz", 0, 0)["kind"] == "refused" and api.save_limits("qobuz", 60, 500)["kind"] == "refused"


# --- a bought file dropped on the window ---

def drop(api, path):
    api._on_drop({"type": "drop", "dataTransfer": {"files": [{"name": path.name, "pywebviewFullPath": str(path)}]}})


def test_drop_then_add_bought_file(root, tmp_path):
    api, rec = make_api(root, analyze=lambda p: ("pcm_s16le", None))
    api.todo()
    api.select("t2")
    src = tmp_path / "Downloads" / "Get Naughty (Extended).wav"
    src.parent.mkdir()
    src.write_bytes(b"RIFF bought")
    drop(api, src)
    assert rec.events[-1] == jobs.FileDropped("t2", src.name, True, "")
    f = wait_job(api, rec, api.add_bought_file("t2"))
    assert f.ok and f.result["result"]["section"] == "bought"
    e = load_state(root)["tracks"]["t2"]
    assert e["path"] == "Library/Hard_Bounce/Armin Hermann - Get Naughty.wav" and e["upgrade"] is None
    assert src.read_bytes() == b"RIFF bought"
    assert api.add_bought_file("t2")["kind"] == "refused"  # the drop is used up


def test_a_drop_for_another_track_or_without_a_selection(root, tmp_path):
    api, rec = make_api(root)
    src = tmp_path / "x.wav"
    src.write_bytes(b"x")
    drop(api, src)
    assert rec.events[-1].readable is False and "Select the track" in rec.events[-1].message
    api.select("t3")
    drop(api, src)
    assert api.add_bought_file("t2")["kind"] == "refused"


def test_a_file_macos_does_not_let_us_read(root, tmp_path):
    api, rec = make_api(root)
    api.select("t2")
    src = tmp_path / "locked.wav"
    src.write_bytes(b"x")
    src.chmod(0)
    try:
        drop(api, src)
    finally:
        src.chmod(0o644)
    assert rec.events[-1].readable is False and "macOS didn't let Discjockey read this file" in rec.events[-1].message


def test_a_broken_drop_event_is_ignored(root):
    api, rec = make_api(root)
    api._on_drop({"type": "drop"})
    api._on_drop(None)
    assert isinstance(rec.events[-1], jobs.FileDropped) and rec.events[-1].readable is False


# --- "Wrong song?" ---

class FakeFallback:
    def __init__(self, **kw):
        self.downloads = []

    def search(self, track):
        return [Candidate("youtube_music", "abc", "Get Naughty", "Armin Hermann - Topic", 268.0,
                          url="https://music.youtube.com/watch?v=abc")], []

    def download(self, cand, workdir, progress=None, section=None):
        self.downloads.append((cand.key, section))
        p = workdir / f"{cand.source}_{cand.id}.webm"
        p.write_bytes(b"downloaded")
        return p

    def lookup(self, source, url):
        return Candidate(source, "zzzzzzzzzzz", "Get Naughty", "Armin Hermann", 268.0, url=url)


def fake_process(downloaded, track, cand, workdir, tracker):
    out = workdir / "new.aiff"
    out.write_bytes(b"replacement")
    return Ready(out, "not_lossless", cand.source, cand.id, "opus", 20100, "YouTube Music OPUS · cutoff 20.1 kHz")


def test_search_candidates_lists_the_current_version_first(root):
    api, rec = make_api(root, fallback=FakeFallback)
    answer = api.search_candidates("t2")
    assert answer["ok"] and answer["spotify_duration_s"] == 268.0
    rows = answer["candidates"]
    assert [(r["key"], r["current"]) for r in rows] == [("youtube:abcdefghijk", True), ("youtube_music:abc", False)]
    assert rows[1]["score"] == 100 and rows[1]["can_preview"] and rows[1]["length_diff_s"] == 0.0
    assert answer["notes"] == ["Qobuz is not set up, so only YouTube Music, SoundCloud and YouTube were searched."]


def test_use_a_candidate_from_the_list(root):
    api, rec = make_api(root, fallback=FakeFallback, process=fake_process)
    api.track("t2")
    row = api.search_candidates("t2")["candidates"][1]
    f = wait_job(api, rec, api.use_candidate("t2", row))
    assert f.ok and f.kind == "use_candidate" and f.result["result"]["section"] == "replaced"
    e = load_state(root)["tracks"]["t2"]
    assert (e["source"], e["source_id"]) == ("youtube_music", "abc") and "youtube:abcdefghijk" in e["rejected_sources"]
    assert (root.root / e["path"]).read_bytes() == b"replacement"
    assert SourceChosen("t2", "youtube_music", "chosen", "Get Naughty", 268.0) in rec.events


def test_use_a_pasted_link(root):
    api, rec = make_api(root, fallback=FakeFallback, process=fake_process)
    api.track("t2")
    f = wait_job(api, rec, api.use_link("t2", "https://youtu.be/zzzzzzzzzzz"))
    assert f.ok and load_state(root)["tracks"]["t2"]["source_id"] == "zzzzzzzzzzz"
    assert api.use_link("t2", "https://example.com/song")["kind"] == "refused"


def test_none_of_these(root):
    api, rec = make_api(root)
    api.track("t2")
    f = wait_job(api, rec, api.reject_current("t2"))
    assert f.ok and load_state(root)["tracks"]["t2"]["status"] == "missing"
    assert (root.root / "Superseded/Hard_Bounce/Armin Hermann - Get Naughty.aiff").exists()


def test_preview_through_the_media_server(root, monkeypatch):
    from discjockey import candidates
    from discjockey.hub.media import MediaServer
    monkeypatch.setattr(candidates.audio, "convert_to_aiff", lambda src, dst, **kw: dst.write_bytes(b"AIFF"))
    api, rec = make_api(root, fallback=FakeFallback)
    api._media = MediaServer(root)
    row = api.search_candidates("t2")["candidates"][1]
    url = api.preview("t2", row)["url"]
    assert "/cache/previews/youtube_music_abc.aiff?v=" in url
    assert api.preview("t2", {**row, "source": "qobuz"}) == {"ok": False, "kind": "refused",
                                                             "message": "Qobuz versions have no preview."}


def test_searches_and_previews_wait_while_a_sync_runs(root):
    api, rec = make_api(root, fallback=FakeFallback)
    release = threading.Event()
    api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    assert api.search_candidates("t2")["kind"] == "sync_running"
    assert api.preview("t2", {"source": "youtube", "id": "x", "url": "https://x"})["kind"] == "sync_running"
    release.set()
    api._jobs.wait(5)
    with run_lock(root.lock):  # the console's sync too
        assert api.search_candidates("t2")["kind"] == "sync_running"


def test_bad_candidates_from_the_page_are_refused(root):
    api, rec = make_api(root)
    assert api.use_candidate("t2", {"source": "spotify", "id": "x"})["kind"] == "refused"
    assert api.use_candidate("t2", {"source": "youtube", "id": "x", "url": "file:///etc/passwd"})["kind"] == "refused"


# --- the state rule (spec 6.2): only the job that holds the lock writes state.json ---

def test_reads_during_a_sync_never_write_state(root, monkeypatch):
    api, rec = make_api(root, fallback=FakeFallback)
    refreshed(api, rec)
    second = threading.Event()
    release = threading.Event()

    class SlowAcquirer:
        n = 0

        def acquire(self, track, rejected, workdir, lossless_only, tracker, exact=None):
            SlowAcquirer.n += 1
            if SlowAcquirer.n == 2:
                second.set()
                release.wait(5)
            f = workdir / "q.aiff"
            f.write_bytes(b"audio")
            return AcquireResult("ready", Ready(f, "lossless", "qobuz", "q" + track.id, "flac", None, "ok"))

    class FakeQobuz:
        check = None

        def close(self):
            pass

    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: SlowAcquirer())
    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, p: FakeQobuz()))
    writers = []
    real_save = library.save_state

    def spy(paths, state, **kw):
        writers.append(threading.current_thread().name)
        real_save(paths, state, **kw)

    monkeypatch.setattr(library, "save_state", spy)
    keys = [a["key"] for g in api.sync_preview()["groups"] for a in g["actions"]]
    answer = api.start_sync(keys)
    assert second.wait(5)
    before = library.load_state(root)
    for call in (api.dashboard, api.sidebar, api.sync_preview, api.job_status, api.todo, api.library,
                 api.limits, api.runs, api.setup_status, api.playlists):
        assert call()["ok"]
    api.track("t2")
    assert api.search_candidates("t2")["kind"] == "sync_running"
    assert api.refresh()["kind"] == "busy"  # ↻ is off while the hub's own sync runs
    assert library.load_state(root) == before
    release.set()
    f = wait_job(api, rec, answer)
    assert f.ok and f.result["exit_code"] == 0
    assert writers and all(name.startswith("hub-job-") for name in writers)
    snap = api.job_status()["job"]
    assert [r["result"]["track_id"] for r in snap["results"]] == ["t4", "t5"]


def test_stop_safely_from_the_page(root, monkeypatch):
    api, rec = make_api(root)
    refreshed(api, rec)
    started = threading.Event()

    class StopAware:
        def acquire(self, track, rejected, workdir, lossless_only, tracker, exact=None):
            started.set()
            while True:
                tracker.progress(1, 10, "bytes")
                time.sleep(0.01)

    class FakeQobuz:
        check = None

        def close(self):
            pass

    monkeypatch.setattr(run, "Acquirer", lambda *a, **k: StopAware())
    monkeypatch.setattr(run.QobuzSource, "open", classmethod(lambda cls, p: FakeQobuz()))
    answer = api.start_sync([a["key"] for g in api.sync_preview()["groups"] for a in g["actions"]])
    assert started.wait(5)
    assert api.job_status()["job"]["stopping"] is False
    assert api.stop() == {"ok": True, "stopped": True}
    f = wait_job(api, rec, answer)
    assert f.ok and f.result["exit_code"] == 130
    assert api.stop() == {"ok": True, "stopped": False}


def test_start_sync_checks_the_keys(root):
    api, rec = make_api(root)
    assert api.start_sync([["acquire", "t1"]])["kind"] == "refused"


def test_rekordbox_checked_through_the_bridge(root):
    state = load_state(root)
    state["tracks"]["t1"]["rekordbox_check"] = {"reason": "wrong_song", "since": "2026-10-16"}
    save_state(root, state)
    api, rec = make_api(root)
    assert "rekordbox_check" in [g["key"] for g in api.todo()["groups"]]
    f = wait_job(api, rec, api.rekordbox_checked("t1"))
    assert f.ok and f.kind == "rekordbox_checked"
    assert load_state(root)["tracks"]["t1"]["rekordbox_check"] is None
    assert "rekordbox_check" not in [g["key"] for g in api.todo()["groups"]]


class RefusingQobuz:
    """Qobuz rejects every download (an account warning sign)."""
    tries = 0

    def download(self, cand, workdir, progress=None):
        RefusingQobuz.tries += 1
        raise RuntimeError("403 forbidden")

    def close(self):
        pass


QOBUZ_ROW = {"source": "qobuz", "id": "q9", "title": "Get Naughty", "artist": "Armin Hermann", "duration_s": 268.0}


def test_failed_qobuz_downloads_in_a_row_pause_qobuz_for_the_hub_session(root):
    RefusingQobuz.tries = 0
    api, rec = make_api(root, fallback=FakeFallback, process=fake_process, open_qobuz=lambda p: RefusingQobuz())
    api.track("t2")
    for _ in range(3):
        f = wait_job(api, rec, api.use_candidate("t2", QOBUZ_ROW))
        assert not f.ok and f.problem == "failed"
    f = wait_job(api, rec, api.use_candidate("t2", QOBUZ_ROW))
    assert not f.ok and f.problem == "refused" and "Qobuz is paused" in f.message
    assert RefusingQobuz.tries == 3  # the 4th click sent nothing to Qobuz
    assert [s["kind"] for s in load_state(root)["qobuz_usage"]["signals"]][-1] == "auto_stop"
    f = wait_job(api, rec, api.use_link("t2", "https://open.qobuz.com/track/123"))
    assert not f.ok and "Qobuz is paused" in f.message
    wait_job(api, rec, api.start_sync([]))  # a new sync starts a new streak
    assert api._qobuz_streak == {"failures_in_a_row": 0, "download_failed_in_row": False, "stopped": False}


def counting_qobuz(calls):
    def open_qobuz(paths):
        calls.append(paths)
        return RefusingQobuz()
    return open_qobuz


def test_daily_limit_and_current_version_are_checked_before_qobuz_is_asked(root):
    from datetime import date
    calls = []
    api, rec = make_api(root, fallback=FakeFallback, process=fake_process, open_qobuz=counting_qobuz(calls))
    state = load_state(root)
    state["qobuz_usage"]["days"][date.today().isoformat()] = 1000
    save_state(root, state)
    api.track("t2")
    for start in (lambda: api.use_candidate("t2", QOBUZ_ROW),
                  lambda: api.use_link("t2", "https://open.qobuz.com/track/123")):
        f = wait_job(api, rec, start())
        assert not f.ok and f.problem == "refused" and "limit" in f.message
    state["qobuz_usage"]["days"] = {}
    state["tracks"]["t2"].update(source="qobuz", source_id="q9")
    save_state(root, state)
    api.track("t2")
    f = wait_job(api, rec, api.use_candidate("t2", QOBUZ_ROW))
    assert not f.ok and "the version you have now" in f.message
    assert calls == []  # no login, no link lookup


def test_a_dropped_file_is_kept_when_its_job_is_refused(root, tmp_path):
    api, rec = make_api(root, analyze=lambda p: ("pcm_s16le", None))
    api.todo()
    api.select("t2")
    src = tmp_path / "Get Naughty.wav"
    src.write_bytes(b"RIFF bought")
    drop(api, src)
    with run_lock(root.lock):  # the console runs
        assert api.add_bought_file("t2")["kind"] == "console"
    f = wait_job(api, rec, api.add_bought_file("t2"))
    assert f.ok and f.result["result"]["section"] == "bought"


def test_use_this_is_refused_when_the_file_is_not_where_state_says(root):
    api, rec = make_api(root, fallback=FakeFallback, process=fake_process)
    api.track("t2")
    (root.root / load_state(root)["tracks"]["t2"]["path"]).unlink()  # moved in Finder
    row = api.search_candidates("t2")["candidates"][1]
    f = wait_job(api, rec, api.use_candidate("t2", row))
    assert not f.ok and f.problem == "refused" and "not where Discjockey expects it. Run a sync first" in f.message
    e = load_state(root)["tracks"]["t2"]
    assert e["source"] == "youtube" and e["path"]


def test_save_limits_keeps_the_other_services(root):
    save_settings(root.settings_file, Settings(70, None, 0, {"youtube": Account("chrome", 30)}))
    api, rec = make_api(root)
    assert wait_job(api, rec, api.save_limits("youtube", 25, 5)).ok
    s = load_settings(root.settings_file)
    assert s.daily_qobuz_limit == 70 and s.accounts["youtube"].daily_limit == 25
    assert s.accounts["youtube"].extra_amount == 5 and s.accounts["youtube"].browser == "chrome"


def test_saving_the_qobuz_limit_keeps_the_accounts(root):
    save_settings(root.settings_file, Settings(70, None, 0, {"youtube": Account("chrome", 30)}))
    api, rec = make_api(root)
    assert wait_job(api, rec, api.save_limits("qobuz", 90, 0)).ok
    assert load_settings(root.settings_file).accounts == {"youtube": Account("chrome", 30)}


def test_limits_of_a_service_that_is_not_set_up(root):
    api, _ = make_api(root)
    answer = api.limits("youtube")
    assert answer["ok"] and answer["usage"] is None and [c["set_up"] for c in answer["cards"]] == [True, False, False]
    assert api.save_limits("youtube", 30, 0) == {"ok": False, "kind": "refused",
                                                 "message": "Set up YouTube Premium first."}
    assert api.limits("tidal")["ok"] is False


class AccountFailingFallback(FakeFallback):
    seen: list = []

    def stream_kbps(self, source, source_id, account=False):
        return 256  # the login gives a premium stream, so Use this downloads through the account

    def download(self, cand, workdir, progress=None, section=None, account=False):
        AccountFailingFallback.seen.append(account)
        if account:
            raise RuntimeError("HTTP Error 403: Forbidden")
        return super().download(cand, workdir, progress, section)


def test_use_this_keeps_the_account_streak_and_pauses_it(root):
    save_settings(root.settings_file, Settings(accounts={"youtube": Account("chrome", 30)}))
    AccountFailingFallback.seen = []
    api, rec = make_api(root, fallback=AccountFailingFallback, process=fake_process)
    api.track("t2")
    row = api.search_candidates("t2")["candidates"][1]
    for _ in range(3):
        assert not wait_job(api, rec, api.use_candidate("t2", row)).ok
    assert wait_job(api, rec, api.use_candidate("t2", row)).ok
    assert AccountFailingFallback.seen == [True, True, True, False]


def test_got_it_marks_the_warning_signs_seen(root):
    st = load_state(root)
    st["qobuz_usage"]["signals"] = [{"time": "2026-10-20T20:00:00", "kind": "search_failed", "message": "x"}]
    save_state(root, st)
    api, rec = make_api(root)
    assert api.sidebar()["limits_warning"] is True and api.limits("qobuz")["cards"][0]["new_warnings"] == 1
    f = wait_job(api, rec, api.mark_warnings_seen("qobuz"))
    assert f.ok and f.result == {"service": "qobuz", "seen_until": "2026-10-20T21:47:00"}
    assert load_settings(root.settings_file).warnings_seen == {"qobuz": "2026-10-20T21:47:00"}
    page = api.limits("qobuz")
    assert page["cards"][0]["new_warnings"] == 0 and page["usage"]["signals"][0]["new"] is False
    assert api.sidebar()["limits_warning"] is False
    assert api.mark_warnings_seen("youtube")["kind"] == "refused"
