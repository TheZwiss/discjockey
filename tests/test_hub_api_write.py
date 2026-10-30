import json
import threading
import time
from datetime import datetime
from pathlib import Path

import pytest
from hub_helpers import (LOSSY, PARKED, fake_import, fake_spotify, import_folder, make_api, make_root, music_root,
                         refreshed, wait_job, write)

from discjockey import db, importer, library, run
from discjockey.sources import spotify
from discjockey.acquire import AcquireResult, Ready
from discjockey.align import Alignment
from discjockey.events import ImportProgress, SourceChosen
from discjockey.hub import jobs
from discjockey.library import load_state, run_lock, save_state
from discjockey.models import Candidate, ScanSummary, WatchedFolder
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
                                                         "qobuz_skipped": False, "spotify_skipped": False, "import_skipped": False,
                                                             "warnings_seen": {},
                                                         "qobuz_last_check": None,
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
    assert answer["ok"] and answer["track_duration_s"] == 268.0
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


# --- the import of the user's own music (plan library stage 4, group 5) ---

from discjockey.hub.jobs import IMPORTING_TEXT


@pytest.fixture
def lib(tmp_path, monkeypatch):
    """A hub over a small library (`make_root`) in tmp_path/music, with an import folder of 3 files beside it."""
    fake_spotify(monkeypatch)
    paths = music_root(tmp_path, upgrade=True)
    return paths, import_folder(tmp_path, 3), fake_import(monkeypatch)


def own_songs(paths):
    return {k: e for k, e in load_state(paths)["tracks"].items() if k.startswith("local:")}


def test_adding_a_folder_watches_and_imports_it_in_one_job(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    f = wait_job(api, rec, api.add_watched_folder(str(folder)))
    assert (f.ok, f.kind, f.problem) == (True, "import", None)
    assert f.message == "Imported 3 files."
    assert f.result == {"files": 3, "own_songs": 3, "sound_checked": 3, "unreadable": 0, "left": 0, "stopped": False,
                        "link_note": None}
    assert sorted(e["title"] for e in own_songs(paths).values()) == ["Song 1", "Song 2", "Song 3"]
    rows = api.watched_folders()
    assert [(r["kind"], r["name"], r["state"], r["files"], r["waiting"]) for r in rows["folders"]] == [
        ("library", "Library", "online", 2, 0), ("import", "Music", "online", 3, 0)]
    progress = [e for e in rec.events if isinstance(e, ImportProgress)]
    assert {p.phase for p in progress} >= {"scan", "tags", "sound", "link"}


def test_one_file_is_imported_in_the_singular(lib):
    paths, folder, fakes = lib
    for extra in sorted(folder.iterdir())[1:]:
        extra.unlink()
    api, rec = make_api(paths)
    assert wait_job(api, rec, api.add_watched_folder(str(folder))).message == "Imported 1 file."


def test_a_refused_folder_says_why_and_starts_nothing(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    inside = paths.library / "Hard_Bounce"
    a = api.add_watched_folder(str(inside))
    assert (a["ok"], a["kind"]) == (False, "refused")
    assert a["message"] == "This is inside your music folder, which Discjockey watches already."
    gone = api.add_watched_folder(str(folder / "nope"))
    assert gone["message"] == "That folder isn't there. If it is on a drive, connect the drive first."
    assert rec.events == [] and api.job_status()["job"] is None
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    again = api.add_watched_folder(str(folder))
    assert again["message"] == "Discjockey watches this folder already."


def test_every_other_write_answers_busy_with_the_import_words_while_it_runs(lib, tmp_path):
    paths, folder, fakes = lib
    other = import_folder(tmp_path, 1, "Example Drive/More")  # a folder the check passes: the job, not it, refuses
    gate, reading = threading.Event(), threading.Event()
    fakes.on_probe = lambda n: reading.set() or gate.wait(10)
    api, rec = make_api(paths)
    job = api.add_watched_folder(str(folder))
    try:
        assert job["ok"] and reading.wait(5)  # the job is past adding the folder, held at its first file
        for answer in (api.hide("t2", True), api.start_import(), api.add_watched_folder(str(other)),
                       api.setup_skip_import(), api.rescan_library()):
            assert (answer["ok"], answer["kind"], answer["message"]) == (False, "busy", IMPORTING_TEXT), answer
    finally:
        gate.set()
    assert wait_job(api, rec, job).ok


def test_stop_ends_the_import_between_two_files_and_continue_import_finishes_it(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    fakes.on_probe = lambda n: api.stop() if n == 2 else None
    f = wait_job(api, rec, api.add_watched_folder(str(folder)))
    assert (f.ok, f.problem, f.kind) == (False, "stopped", "import")
    assert f.result["stopped"] is True and f.result["files"] == 2 and f.result["left"] == 3  # 1 not read + 2 to judge
    assert f.message == "Import stopped with 3 files to go. It carries on where it stopped."
    assert api.watched_folders()["stopped"] is True
    fakes.on_probe = None
    done = wait_job(api, rec, api.start_import())
    assert (done.ok, done.result["stopped"]) == (True, False)
    assert api.watched_folders()["stopped"] is False
    assert len(own_songs(paths)) == 3 and done.result["left"] == 0


def test_a_stop_with_one_file_to_go_says_so_in_the_singular(lib):
    paths, folder, fakes = lib
    for extra in sorted(folder.iterdir())[1:]:
        extra.unlink()
    api, rec = make_api(paths)
    fakes.on_probe = lambda n: api.stop()
    f = wait_job(api, rec, api.add_watched_folder(str(folder)))
    assert f.result["left"] == 1 and f.message == "Import stopped with 1 file to go. It carries on where it stopped."


def import_jobs(rec):
    return [e for e in rec.events if isinstance(e, jobs.JobStarted) and e.kind == "import"]


def wait_idle(api):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline and (api._jobs.current is None or not api._jobs.current.done.is_set()):
        time.sleep(0.01)


def test_the_import_starts_by_itself_after_the_opening_scan_when_files_wait(lib):
    paths, folder, fakes = lib
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, folder, datetime(2026, 10, 20))
    api, rec = make_api(paths)
    api._first_read()  # what the app does when it opens: no page is involved
    wait_idle(api)
    started = import_jobs(rec)
    assert len(started) == 1
    done = rec.finished(started[0].job_id)
    assert done is not None and done.ok and done.result["files"] == 3
    assert len(own_songs(paths)) == 3
    assert api.refresh(auto=True)["kind"] == "refused"  # the Sync page's own try finds the read done
    assert len(import_jobs(rec)) == 1


def test_the_automatic_import_does_not_wait_for_the_playlists_to_be_read(lib, monkeypatch):
    paths, folder, fakes = lib
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, folder, datetime(2026, 10, 20))
    gate, real = threading.Event(), spotify.fetch_playlist

    def slow(session, line):
        gate.wait(10)
        return real(session, line)

    monkeypatch.setattr(spotify, "fetch_playlist", slow)
    api, rec = make_api(paths)
    try:
        api._first_read()
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline and not import_jobs(rec):
            time.sleep(0.01)
        assert len(import_jobs(rec)) == 1  # started while the read still waits on the network
    finally:
        gate.set()
    wait_idle(api)
    assert len(own_songs(paths)) == 3


def test_the_automatic_import_starts_without_spotify_set_up(lib, monkeypatch):
    paths, folder, fakes = lib
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, folder, datetime(2026, 10, 20))
    monkeypatch.setattr(spotify, "load_session", lambda p: (_ for _ in ()).throw(
        spotify.SourceError("Spotify isn't connected.", "not_set_up", "spotify")))
    monkeypatch.setattr(spotify, "login_state", lambda p: spotify.LoginState("missing", "Spotify isn't connected."))
    api, rec = make_api(paths)
    api._first_read()
    wait_idle(api)
    started = import_jobs(rec)
    assert len(started) == 1 and rec.finished(started[0].job_id).ok
    assert len(own_songs(paths)) == 3


def test_it_does_not_start_when_nothing_waits_or_for_a_read_the_user_asked_for(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    refreshed(api, rec)
    api._auto_import()  # no watched folder
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, folder, datetime(2026, 10, 20))
    wait_job(api, rec, api.refresh())  # "Read playlists" is not the window opening
    assert not [e for e in rec.events if isinstance(e, jobs.JobStarted) and e.kind == "import"]
    assert importer.files_waiting(paths) == 3  # the read's scan found them: they wait for Continue import


def test_a_stop_holds_the_automatic_start_for_the_session(lib):
    paths, folder, fakes = lib
    with db.connect(paths.db_file) as conn:
        db.add_watched_folder(conn, folder, datetime(2026, 10, 20))
    api, rec = make_api(paths)
    refreshed(api, rec)
    fakes.on_probe = lambda n: api.stop() if n == 1 else None
    api._auto_import()
    first = api._jobs.current
    assert first.done.wait(10) and rec.finished(first.id).problem == "stopped"
    fakes.on_probe = None
    api._auto_import()
    api._auto_import()
    assert len([e for e in rec.events if isinstance(e, jobs.JobStarted) and e.kind == "import"]) == 1
    assert wait_job(api, rec, api.start_import()).ok  # Continue import still works, and lets it start by itself again
    assert api._import_stopped is False


def test_the_import_links_the_playlists_and_asks_what_is_plausible(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    refreshed(api, rec)  # the window's read: t4 "AEIOU" by Pegassi is new
    fakes.tags["Example Artist - Song 1.aiff"] = {"artist": "Other Artist", "title": "AEIOU"}
    fakes.seconds["Example Artist - Song 1.aiff"] = 180.0  # the playlist song's length
    f = wait_job(api, rec, api.add_watched_folder(str(folder)))
    assert f.ok and f.result["link_note"] is None
    todo = api.todo()
    assert todo["chips"]["same_song"] == 1
    item = next(g for g in todo["groups"] if g["key"] == "same_song")["items"][0]
    assert item["track_id"] == "t4" and item["pair"]["own_key"] == "local:1" and item["pair"]["why"] == "artist"
    assert item["detail"] == "Same title, different artist"
    preview = api.sync_preview()
    assert preview["waiting_answers"] == 1
    assert "t4" not in [a["track_id"] for g in preview["groups"] for a in g["actions"]]  # held until the answer (D4)


def test_answering_yes_links_the_file_and_no_releases_the_download(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    refreshed(api, rec)
    fakes.tags["Example Artist - Song 1.aiff"] = {"artist": "Other Artist", "title": "AEIOU"}
    fakes.tags["Example Artist - Song 2.aiff"] = {"artist": "Other Artist", "title": "non stop"}
    fakes.seconds.update({"Example Artist - Song 1.aiff": 180.0, "Example Artist - Song 2.aiff": 180.0})
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    pairs = {i["track_id"]: i["pair"] for g in api.todo()["groups"] if g["key"] == "same_song" for i in g["items"]}
    assert set(pairs) == {"t4", "t5"}
    yes = wait_job(api, rec, api.answer_same_song("t4", pairs["t4"]["own_key"], True))
    assert (yes.ok, yes.kind, yes.result) == (True, "answer", {})
    no = wait_job(api, rec, api.answer_same_song("t5", pairs["t5"]["own_key"], False))
    assert no.ok
    planned = api._store.prep.plan.state["tracks"]  # the next plan: saved by the next sync or import
    linked = planned[pairs["t4"]["own_key"]]  # "Yes": the file's own song is the playlist song now
    assert (linked["aliases"], linked["in_playlists"]) == (["t4"], True)
    assert linked["path"].endswith("Example Artist - Song 1.aiff")
    assert planned[pairs["t5"]["own_key"]]["in_playlists"] is False  # "No": still only a file of the user's
    assert api.todo()["chips"]["same_song"] == 0 and api.sync_preview()["waiting_answers"] == 0
    wanted = [a["track_id"] for g in api.sync_preview()["groups"] for a in g["actions"]]
    assert "t5" in wanted and "t4" not in wanted  # "No, keep them apart" releases the download


def test_an_answer_the_records_cannot_take_fails_in_plain_words(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    bad = wait_job(api, rec, api.answer_same_song("local:1", "local:2", True))  # an own song is no playlist song
    assert (bad.ok, bad.problem) == (False, "changed") and "nothing to answer" in bad.message
    for args in ((1, "local:1", True), ("t4", "local:1", "yes"), ("t4", None, True)):
        a = api.answer_same_song(*args)
        assert (a["ok"], a["kind"]) == (False, "refused")
    for call in (lambda: api.keep_duplicates("not a group", []), lambda: api.keep_duplicates(5, []),
                 lambda: api.keep_duplicates("dup:1-2", "x"), lambda: api.keep_duplicates("dup:1-2", [1]),
                 lambda: api.supersede_duplicate("dup:1-2", "x", []), lambda: api.supersede_duplicate("nope", 1, []),
                 lambda: api.supersede_duplicate("dup:1-2", 1, None)):
        assert call()["kind"] == "refused"


def copies(paths, tmp_path, fakes, n=3):
    """n copies of one file in a watched folder (the same audio), imported."""
    folder = tmp_path / "outside" / "Copies"
    folder.mkdir(parents=True)
    for i in range(1, n + 1):
        (folder / f"Example Artist - Copy {i}.aiff").write_bytes(b"the very same audio" * 50)
    return folder


def test_a_group_of_copies_is_one_duplicate_item_and_keep_all_answers_the_whole_group(lib, tmp_path):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(copies(paths, tmp_path, fakes, 3))))
    group = next(g for g in api.todo()["groups"] if g["key"] == "duplicate")
    item = group["items"][0]
    assert item["detail"] == "The same audio in 3 files" and item["pair"]["why"] == "same_audio"
    assert [f["quality"] for f in item["pair"]["files"]] == ["lossless"] * 3
    gid = item["pair"]["group_id"]
    before = api.sidebar()["todo"]
    shown = [f["path"] for f in item["pair"]["files"]]
    wrong = wait_job(api, rec, api.keep_duplicates(gid, shown[:2]))  # not the files the card showed
    assert (wrong.ok, wrong.problem) == (False, "changed") and api.todo()["chips"]["duplicate"] == 1
    done = wait_job(api, rec, api.keep_duplicates(gid, shown))
    assert (done.ok, done.kind) == (True, "answer")
    assert api.todo()["chips"]["duplicate"] == 0 and api.sidebar()["todo"] == before - 1  # one answer, all three


def test_moving_a_duplicate_to_superseded_keeps_the_file_and_the_others(lib, tmp_path):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    copy_dir = copies(paths, tmp_path, fakes, 2)
    wait_job(api, rec, api.add_watched_folder(str(copy_dir)))
    pair = next(i for g in api.todo()["groups"] if g["key"] == "duplicate" for i in g["items"])["pair"]
    moving = pair["files"][1]
    shown = [f["path"] for f in pair["files"]]
    other = wait_job(api, rec, api.supersede_duplicate(pair["group_id"], moving["file_id"], [shown[0], "/x/else.aiff"]))
    assert (other.ok, other.problem) == (False, "changed") and Path(moving["path"]).is_file()
    done = wait_job(api, rec, api.supersede_duplicate(pair["group_id"], moving["file_id"], shown))
    assert (done.ok, done.kind) == (True, "supersede")
    assert done.result["recovered"] == [] and done.result["result"]["section"] == "replaced"
    moved_to = paths.root / done.result["result"]["path"]
    assert moved_to.is_file() and not Path(moving["path"]).exists()  # moved, never deleted
    assert Path(pair["files"][0]["path"]).is_file()
    assert api.todo()["chips"]["duplicate"] == 0
    stale = api.supersede_duplicate(pair["group_id"], moving["file_id"], shown)
    assert wait_job(api, rec, stale).problem == "changed"


def test_removing_a_folder_forgets_its_files_and_reports_what_downloads_again(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    fid = next(r["id"] for r in api.watched_folders()["folders"] if r["kind"] == "import")
    preview = api.removal_preview(fid)
    assert (preview["name"], preview["files"], preview["redownload"]) == ("Music", 3, 0)
    done = wait_job(api, rec, api.remove_watched_folder(fid))
    assert (done.ok, done.kind, done.result) == (True, "folders", {"files": 3, "redownload": 0})
    assert [r["kind"] for r in api.watched_folders()["folders"]] == ["library"]
    assert not own_songs(paths) and all(p.is_file() for p in folder.iterdir())  # the files stay where they are
    for bad in (fid, 0, "x", True, None):
        assert api.remove_watched_folder(bad)["kind"] == "refused"
        assert api.removal_preview(bad)["kind"] == "refused"


def test_removing_the_folder_of_a_playlist_songs_only_file_makes_it_download_again(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    refreshed(api, rec)
    # t3 "Gone Track" by Some Artist has no file: this one is certainly it (same names, same length), so the import links it
    fakes.tags["Example Artist - Song 1.aiff"] = {"artist": "Some Artist", "title": "Gone Track"}
    fakes.seconds["Example Artist - Song 1.aiff"] = 180.0
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    assert load_state(paths)["tracks"]["t3"]["path"].endswith("Example Artist - Song 1.aiff")
    assert api.todo()["chips"]["same_song"] == 0 and "local:1" not in load_state(paths)["tracks"]
    fid = next(r["id"] for r in api.watched_folders()["folders"] if r["kind"] == "import")
    assert api.removal_preview(fid) == {"ok": True, "name": "Music", "files": 3, "redownload": 1}
    done = wait_job(api, rec, api.remove_watched_folder(fid))
    assert done.result == {"files": 3, "redownload": 1}
    assert load_state(paths)["tracks"]["t3"]["path"] is None
    wanted = [(a["kind"], a["track_id"]) for g in api.sync_preview()["groups"] for a in g["actions"]]
    assert ("acquire", "t3") in wanted  # the preview was planned again at once


def test_continue_import_clears_the_stop_before_the_job_can_be_stopped_again(lib, monkeypatch):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    api._import_stopped = True
    seen = []
    real = api._jobs.start

    def start(kind, work, *a, **kw):
        seen.append(api._import_stopped)
        raise jobs.Busy("busy", "busy")

    monkeypatch.setattr(api._jobs, "start", start)
    assert api.start_import()["kind"] == "busy"
    assert seen == [False]  # cleared before the job could stop itself again
    assert api._import_stopped is True  # a refused start leaves the stop as it was
    monkeypatch.setattr(api._jobs, "start", real)



def test_an_import_folders_file_plays_through_its_file_id(lib):
    from discjockey.hub.media import MediaServer
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    assert wait_job(api, rec, api.add_watched_folder(str(folder))).ok
    api._media = MediaServer(paths)
    api._media.bind(paths, api._file_path)  # what _attach does for the app's server
    with db.connect(paths.db_file) as conn:
        ids = {rel: i for i, rel in conn.execute("SELECT id, path FROM files WHERE folder = 2")}
    one = ids["Example Artist - Song 1.aiff"]
    entry = {"path": str(folder / "Example Artist - Song 1.aiff"), "file_id": one}
    url = api._audio("local:1", entry)
    assert url is not None and f"/file/{one}?v=" in url
    assert api._audio("local:1", {**entry, "file_id": 999}) is None  # not a row of the records
    assert api._audio("local:1", {"path": entry["path"]}) is None
    outside = folder.parent / "secret.aiff"
    outside.write_bytes(b"secret")
    (folder / "escape.aiff").symlink_to(outside)
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET path = 'escape.aiff' WHERE id = ?", (ids["Example Artist - Song 2.aiff"],))
    assert api._file_path(ids["Example Artist - Song 2.aiff"]) is None  # a link leading out of the folder
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET online = 0 WHERE id = ?", (one,))
    assert api._file_path(one) is None and api._audio("local:1", entry) is None  # its drive is offline
    assert api._file_path(ids["Example Artist - Song 3.aiff"]) == (folder / "Example Artist - Song 3.aiff").resolve()



def test_a_stop_while_the_import_reads_the_playlists_to_link_ends_it_stopped(lib, monkeypatch):
    paths, folder, fakes = lib
    api, rec = make_api(paths)  # no read yet: the link phase reads the playlists itself
    real = spotify.fetch_playlist

    def stopping(session, line):
        api.stop()
        return real(session, line)

    monkeypatch.setattr(spotify, "fetch_playlist", stopping)
    f = wait_job(api, rec, api.add_watched_folder(str(folder)))
    assert (f.ok, f.problem, f.kind) == (False, "stopped", "import")
    assert f.result["stopped"] is True and f.message.startswith("Import stopped with")
    assert api._import_stopped is True  # no automatic start again this session; Continue import is offered
    assert api.watched_folders()["stopped"] is True



def test_a_stopped_or_failed_import_plans_the_preview_again(lib, monkeypatch):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    refreshed(api, rec)  # the window's read: the preview exists
    planned = []
    real = jobs.preview_after_run
    monkeypatch.setattr(jobs, "preview_after_run", lambda store, prep, at: planned.append(prep) or real(store, prep, at))
    fakes.on_probe = lambda n: api.stop() if n == 2 else None
    f = wait_job(api, rec, api.add_watched_folder(str(folder)))
    assert f.problem == "stopped" and len(planned) == 1  # the files imported before the stop show in To-do and Sync
    fakes.on_probe = None

    def broken(*a, **kw):
        raise RuntimeError("the disk went away")

    monkeypatch.setattr(importer, "run_import", broken)
    f = wait_job(api, rec, api.start_import())
    assert (f.ok, f.problem) == (False, "crashed") and len(planned) == 2


def test_a_folder_refused_inside_the_job_shows_the_w5_words():
    refused = db.FolderRefused("watched", "/Volumes/Example/Music/Inside", "/Volumes/Example/Music")
    assert jobs.problem_of(refused) == ("refused", "This is inside Music, which Discjockey watches already.")
    assert jobs.problem_of(db.FolderRefused("holds_music", "/Volumes/Example"))[1].startswith("This folder holds your")
    assert jobs.problem_of(ValueError("plain"))[1] == "plain"



def test_the_sidebar_counts_duplicate_groups_without_loading_their_files(lib, monkeypatch):
    import shutil
    paths, folder, fakes = lib
    shutil.copy(folder / "Example Artist - Song 1.aiff", folder / "Example Artist - Song 1 copy.aiff")
    api, rec = make_api(paths)
    assert wait_job(api, rec, api.add_watched_folder(str(folder))).ok
    with db.connect(paths.db_file) as conn:
        assert len(db.duplicate_groups(conn)) == 1
    real, loaded = db.group_files, []
    monkeypatch.setattr(db, "group_files", lambda conn, gid: loaded.append(gid) or real(conn, gid))
    total = api.todo()["chips"]
    assert total["duplicate"] == 1 and len(loaded) == 1  # the page lists the group, so it loads its files
    loaded.clear()
    assert api.sidebar()["todo"] == total["all"] and loaded == []


def test_a_duplicate_group_in_a_folder_that_just_went_away_leaves_the_list_and_every_count(lib):
    import shutil
    paths, folder, fakes = lib
    shutil.copy(folder / "Example Artist - Song 1.aiff", folder / "Example Artist - Song 1 copy.aiff")
    api, rec = make_api(paths)
    assert wait_job(api, rec, api.add_watched_folder(str(folder))).ok
    here = api.todo()["chips"]
    assert here["duplicate"] == 1 and api.sidebar()["todo"] == here["all"]
    gone = folder.with_name("Music (ejected)")
    folder.rename(gone)  # no scan has run: the rows still say online
    with db.connect(paths.db_file) as conn:
        assert len(db.duplicate_groups(conn)) == 1
    out = api.todo()
    assert out["chips"]["duplicate"] == 0 and not any(g["key"] == "duplicate" for g in out["groups"])
    assert api.todo("duplicate")["chips"] == out["chips"]
    assert api.sidebar()["todo"] == out["chips"]["all"] == here["all"] - 1  # the sidebar agrees with the page
    gone.rename(folder)
    assert api.todo()["chips"] == here and api.sidebar()["todo"] == here["all"]


def test_an_unplugged_import_folder_makes_its_files_offline_before_any_scan(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    key = sorted(own_songs(paths))[0]
    file_id = own_songs(paths)[key]["file_id"]
    with db.connect(paths.db_file) as conn:
        assert conn.execute("SELECT online FROM files WHERE id = ?", (file_id,)).fetchone()[0] == 1
    assert api.track(key)["track"]["file_state"] == "here"
    assert api._file_path(file_id) is not None
    gone = folder.with_name("Music (ejected)")
    folder.rename(gone)  # the drive goes: no scan has run, the row still says online
    with db.connect(paths.db_file) as conn:
        assert conn.execute("SELECT online FROM files WHERE id = ?", (file_id,)).fetchone()[0] == 1
    detail = api.track(key)["track"]
    assert (detail["file_state"], detail["audio_url"]) == ("folder_missing", None)  # not under /Volumes: not found
    rows = {r["track_id"]: r["file_state"] for r in api.library()["rows"]}
    assert rows[key] == "folder_missing" and set(rows.values()) == {"here", "folder_missing"}  # the list agrees
    assert api.watched_folders()["folders"][1]["state"] == "missing"  # the same answer as Settings
    assert api._file_path(file_id) is None  # the media vetting refuses too: the file can't be resolved
    gone.rename(folder)  # plugged back in
    assert api.track(key)["track"]["file_state"] == "here"
    assert {r["file_state"] for r in api.library()["rows"]} == {"here"}
    assert api.watched_folders()["folders"][1]["state"] == "online"
    assert api._file_path(file_id) is not None


def _drive_events(rec):
    return [e for e in rec.events if isinstance(e, jobs.DrivesChanged)]


def test_the_drives_watch_says_once_when_a_watched_folder_goes_and_once_when_it_is_back(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    api._check_drives()
    api._check_drives()
    assert _drive_events(rec) == []  # the first look is the baseline, the second saw nothing change
    gone = folder.with_name("Music (ejected)")
    folder.rename(gone)
    api._check_drives()
    api._check_drives()
    api._check_drives()
    assert _drive_events(rec) == [jobs.DrivesChanged(1)]  # once per change, however often it looks
    gone.rename(folder)
    api._check_drives()
    api._check_drives()
    assert _drive_events(rec) == [jobs.DrivesChanged(1), jobs.DrivesChanged(0)]


def test_the_drives_watch_tells_an_ejected_drive_from_a_missing_folder_and_waits_out_an_unreadable_db(lib, monkeypatch):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    stick = "/Volumes/Example Stick/Music"
    looks = iter([{}, {stick: "unmounted"}, {stick: "unmounted"}, {stick: "missing"}, None, {stick: "missing"}, {}])

    def away():
        now = next(looks)
        if now is None:
            raise db.unreadable(OSError("busy"))
        return now

    monkeypatch.setattr(api, "_away_roots", away)
    for _ in range(7):
        api._check_drives()
    # the reason changed with the same count (the stick is back, the folder on it is not): that is a change too; an
    # unreadable look says nothing and keeps the last answer, so the look after it is no change
    assert _drive_events(rec) == [jobs.DrivesChanged(1), jobs.DrivesChanged(1), jobs.DrivesChanged(0)]


def test_the_drives_watch_runs_in_the_background_and_stops_with_the_window(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    thread = api._watch_drives(interval=0.01)
    time.sleep(0.05)
    api._jobs.close()
    thread.join(1)
    assert not thread.is_alive() and _drive_events(rec) == []  # nothing came or went


def test_a_file_deleted_in_an_online_folder_says_file_missing_until_the_next_scan(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    key = sorted(own_songs(paths))[0]
    path = Path(api.track(key)["track"]["path"])
    assert path.exists()
    path.unlink()
    detail = api.track(key)["track"]
    assert (detail["file_state"], detail["audio_url"]) == ("file_missing", None)
    assert api.watched_folders()["folders"][1]["state"] == "online"  # the folder itself is there


def test_the_unplugged_drive_and_the_missing_folder_are_told_apart_by_the_mount(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    asked = []
    api._svc.mounted = lambda p: asked.append(p) or False
    assert api._away_folders([WatchedFolder(7, Path("/Volumes/Example Stick/Music"), "import")]) == {7: "unmounted"}
    assert asked == [Path("/Volumes/Example Stick")]
    api._svc.mounted = lambda p: True
    assert api._away_folders([WatchedFolder(7, Path("/Volumes/Example Stick/Music"), "import")]) == {7: "missing"}
    assert api._away_folders([WatchedFolder(8, folder, "import"), WatchedFolder(9, paths.library, "library")]) == {}


def test_a_stored_offline_file_stays_offline_even_when_its_folder_is_there(lib):
    paths, folder, fakes = lib
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    key = sorted(own_songs(paths))[0]
    with db.connect(paths.db_file) as conn:
        conn.execute("UPDATE files SET online = 0 WHERE id = ?", (own_songs(paths)[key]["file_id"],))
    assert api.track(key)["track"]["file_state"] == "offline"


# --- the sidebar, Favourites and crate switches (plan library stage 5, B2) ---

def crate_library(tmp_path, monkeypatch):
    """A hub with an import folder of crates: Hard/ (2 files), Hard/2019/ (1), House/ (1), a file in the folder itself."""
    fake_spotify(monkeypatch)
    paths = music_root(tmp_path, upgrade=True)
    folder = import_folder(tmp_path, 1)
    for sub, n in (("Hard", 2), ("Hard/2019", 1), ("House", 1)):
        (folder / sub).mkdir(parents=True, exist_ok=True)
        for i in range(n):
            (folder / sub / f"Example Artist - {sub.replace('/', ' ')} {i}.aiff").write_bytes(f"{sub}{i}".encode() * 50)
    fake_import(monkeypatch)
    api, rec = make_api(paths)
    wait_job(api, rec, api.add_watched_folder(str(folder)))
    return api, rec, paths, folder


def test_the_sidebar_and_the_settings_rows_list_the_crates_of_a_watched_folder(tmp_path, monkeypatch):
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    [w] = api.sidebar()["watched"]
    assert (w["path"], w["name"], w["files"], w["state"], w["too_many"]) == (str(folder), "Music", 5, "here", False)
    assert [(c["label"], c["files"], c["has_crates"], c["hidden"]) for c in w["crates"]] == [
        ("Hard", 3, True, False), ("Hard › 2019", 1, False, False), ("House", 1, False, False)]
    row = api.watched_folders()["folders"][1]
    assert (row["crates"], row["too_many"]) == (w["crates"], False)
    assert api.watched_folders()["folders"][0]["crates"] == []  # the Library has none


def test_a_watched_folder_and_its_crates_have_their_views_with_crate_labels_as_places(tmp_path, monkeypatch):
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    whole = api.library("folder", str(folder))
    assert (whole["folder_kind"], whole["title"], whole["summary"]["tracks"], whole["empty"]) == ("watched", "Music", 5, None)
    assert sorted({r["subfolder"] for r in whole["rows"]}) == ["", "Hard", "Hard › 2019", "House"]
    hard = api.library("folder", str(folder / "Hard"))
    assert (hard["folder_kind"], hard["title"], hard["subtitle"][-1]) == ("crate", "Hard", "Music › Hard")
    assert sorted((r["subfolder"], r["place"]) for r in hard["rows"]) == [
        ("", "Music › Hard"), ("", "Music › Hard"), ("2019", "Music › Hard › 2019")]
    row = hard["rows"][0]
    assert api.track(row["track_id"])["track"]["place"] == row["place"]


def test_set_crate_shown_hides_and_shows_and_none_goes_back_to_the_default(tmp_path, monkeypatch):
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    house = str(folder / "House")
    assert api.set_crate_shown(house, False) == {"ok": True, "path": house, "shown": False}
    hidden = lambda: {c["name"]: c["hidden"] for c in api.sidebar()["watched"][0]["crates"]}  # noqa: E731
    assert hidden() == {"Hard": False, "2019": False, "House": True}
    assert {c["name"]: c["hidden"] for c in api.watched_folders()["folders"][1]["crates"]}["House"] is True
    assert api.set_crate_shown(house, True)["shown"] is True and hidden()["House"] is False
    api.set_crate_shown(house, False)
    assert api.set_crate_shown(house, None)["shown"] is None and hidden()["House"] is False
    assert api.set_crate_shown("", True)["kind"] == "refused"
    assert api.set_crate_shown(house, "yes")["kind"] == "refused"
    assert api.set_crate_shown(3, True)["kind"] == "refused"


def test_set_favourites_keeps_the_order_and_the_sidebar_resolves_them(tmp_path, monkeypatch):
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    ref = api.sidebar()["playlists"][1]["ref"]
    keys = [f"folder:{folder}/Hard", f"playlist:{ref}", "playlist:gone", f"folder:{folder}/Hard"]
    assert api.set_favourites(keys) == {"ok": True, "favourites": [f"folder:{folder}/Hard", f"playlist:{ref}",
                                                                   "playlist:gone"]}
    assert [(f["key"], f["name"]) for f in api.sidebar()["favourites"]] == [
        (f"folder:{folder}/Hard", "Hard"), (f"playlist:{ref}", "Powertrance")]  # the gone key stays stored, unshown
    assert api.set_favourites([])["favourites"] == [] and api.sidebar()["favourites"] == []
    for bad in ("playlist:x", [3], ["x:y"], None):
        assert api.set_favourites(bad)["kind"] == "refused", bad


def test_a_favourite_or_a_crate_switch_saves_during_a_sync_and_a_console_run_without_a_job(tmp_path, monkeypatch):
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    release = threading.Event()
    job = api._jobs.start("sync", lambda ctx: release.wait(5) and None)
    assert api.set_favourites(["folder:Library/Hard_Bounce"])["ok"]
    assert api.set_crate_shown(str(folder / "House"), False)["ok"]
    release.set()
    api._jobs.wait(5)
    with run_lock(paths.lock):
        assert api.set_favourites([])["ok"] and api.set_crate_shown(str(folder / "House"), None)["ok"]
    assert api._jobs.running() is None and rec.finished().job_id == job.id  # no job of its own


def test_a_save_that_cannot_get_the_database_answers_busy_and_changes_nothing(tmp_path, monkeypatch):
    import sqlite3
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    api.set_favourites(["folder:Library/Hard_Bounce"])  # stored; no line uses the key as a folder, so none is shown
    monkeypatch.setattr("discjockey.hub.api.BRIEF_WRITE_WAIT_MS", 50)
    other = sqlite3.connect(str(paths.db_file), isolation_level=None)
    other.execute("BEGIN IMMEDIATE")  # a running job's write transaction
    try:
        answers = [api.set_favourites([]), api.set_crate_shown(str(folder / "House"), False)]
        assert api.sidebar()["ok"]  # reading still works beside the writer
    finally:
        other.execute("ROLLBACK")
        other.close()
    assert [(a["ok"], a["kind"]) for a in answers] == [(False, "busy"), (False, "busy")]
    assert all("Try again" in a["message"] for a in answers)
    with db.connect(paths.db_file) as conn:
        assert db.favourites(conn) == ["folder:Library/Hard_Bounce"] and db.crate_overrides(conn) == {}
    assert not api.sidebar()["watched"][0]["crates"][2]["hidden"]
    assert api.set_favourites([])["ok"]  # once the writer is done it works


def test_the_events_that_tell_the_page_to_read_the_sidebar_again(tmp_path, monkeypatch):
    """B2.4: no event was added. A finished read is JobFinished (kind refresh), a finished import JobFinished (kind
    import), a drive that came or went DrivesChanged; the page re-reads the sidebar on each (stores/hub.ts)."""
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    assert rec.finished().kind == "import" and rec.finished().ok
    assert api.sidebar()["watched"][0]["files"] == 5  # what the page reads on that event
    api._check_drives()
    gone = folder.with_name("Music (ejected)")
    folder.rename(gone)
    api._check_drives()
    assert [e for e in rec.events if isinstance(e, jobs.DrivesChanged)] == [jobs.DrivesChanged(1)]
    sb = api.sidebar()
    assert (sb["watched"][0]["state"], sb["watched"][0]["files"]) == ("folder_missing", 5)  # an away folder keeps its count
    refreshed(api, rec)
    assert rec.finished().kind == "refresh"


def test_a_save_that_fails_for_any_other_reason_than_a_lock_does_not_say_try_again(tmp_path, monkeypatch):
    import sqlite3
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    for error in (sqlite3.DatabaseError("file is not a database"),
                  sqlite3.OperationalError("attempt to write a readonly database")):
        monkeypatch.setattr(db, "set_favourites", lambda conn, keys, error=error: (_ for _ in ()).throw(error))
        answer = api.set_favourites([])
        assert (answer["ok"], answer["kind"]) == (False, "config_invalid"), error
        assert "Try again" not in answer["message"]
    locked = sqlite3.OperationalError("database is locked")
    monkeypatch.setattr(db, "set_crate_shown", lambda conn, path, shown: (_ for _ in ()).throw(locked))
    assert api.set_crate_shown(str(folder / "House"), True)["kind"] == "busy"


def test_a_save_without_library_db_is_refused_and_says_what_to_do(tmp_path, monkeypatch):
    api, rec, paths, folder = crate_library(tmp_path, monkeypatch)
    api._jobs.wait(5)
    for name in ("library.db", "library.db-wal", "library.db-shm"):
        (paths.data / name).unlink(missing_ok=True)
    answers = [api.set_favourites([]), api.set_crate_shown(str(folder / "House"), False)]
    assert [(a["ok"], a["kind"]) for a in answers] == [(False, "refused")] * 2
    assert all("open Discjockey again" in a["message"] and "Try again" not in a["message"] for a in answers)
