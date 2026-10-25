import shutil
import subprocess
from datetime import date

import pytest
from mutagen.aiff import AIFF

from discjockey.acquire import Acquirer, AcquireResult, Ready, make_ready
from discjockey.events import AccountUsage, CancelToken, Checked, SourceChosen, StepChanged, Tracker
from discjockey.models import Candidate, SourceTrack
from discjockey.pacing import Budget, NoPacer
from discjockey.qobuz import QobuzPreviewOnly
from discjockey.settings import Settings

T = SourceTrack("t1", "Gimme Gimme", ("Vatoz Locoz",), "Album", None, 156000, "DECE72605755")
ISRC_Q = "DECE72605755"
NAME_Q = "Vatoz Locoz Gimme Gimme"


def qc(id, isrc="DECE72605755", dur=156.0, title="Gimme Gimme"):
    return Candidate("qobuz", id, title, "Vatoz Locoz", dur, isrc=isrc)


def fc(id, source="youtube", dur=156.0):
    return Candidate(source, id, "Vatoz Locoz - Gimme Gimme", "Vatoz Locoz", dur, url=f"https://x/{id}")


class Unavailable(Exception):
    permanent = True


class FakeQobuz:
    def __init__(self, results=None, fail_search=False, fail_download=(), unavailable=(), preview=()):
        self.results = results or {}
        self.fail_search, self.fail_download = fail_search, set(fail_download)
        self.unavailable, self.preview = set(unavailable), set(preview)
        self.searches, self.downloads = [], []

    def search(self, query, limit=10):
        self.searches.append(query)
        if self.fail_search:
            raise RuntimeError("network down")
        return self.results.get(query, [])

    def download(self, cand, workdir, progress=None):
        if cand.id in self.fail_download:
            raise RuntimeError("timeout")
        if cand.id in self.unavailable:
            raise Unavailable("region locked")
        if cand.id in self.preview:
            raise QobuzPreviewOnly()
        self.downloads.append(cand.id)
        p = workdir / f"qobuz_{cand.id}.flac"
        p.write_bytes(b"x")
        return p


class FakeFallback:
    def __init__(self, cands=(), errors=(), offers=None, fail_direct=False):
        self.cands, self.errors, self.downloads = list(cands), list(errors), []
        self.offers, self.fail_direct, self.searched = offers or {}, fail_direct, []

    def search(self, track, sources=None):
        self.searched.append(sources)
        return [c for c in self.cands if sources is None or c.source in sources], list(self.errors)

    def free_downloads(self, cands):
        return [{**self.offers[c.key], "key": c.key} for c in cands if c.key in self.offers]

    def download(self, cand, workdir, progress=None):
        if cand.direct and self.fail_direct:
            raise RuntimeError("Requested format is not available")
        self.downloads.append(("direct:" if cand.direct else "") + cand.id)
        p = workdir / f"{cand.source}_{cand.id}.webm"
        p.write_bytes(b"x")
        return p


def fake_process(statuses=None):
    statuses = statuses or {}

    def process(downloaded, track, cand, workdir, tracker):
        status = statuses.get(cand.key, "lossless" if cand.source == "qobuz" else "not_lossless")
        if status is None:  # simulates a failed duration check
            return None
        return Ready(downloaded, status, cand.source, cand.id, "flac", None, "comment")
    return process


def acquirer(qobuz=None, fallback=None, statuses=None, count=0, pacer=None):
    # yesterday fully used, so today's allowance is exactly the limit of 60
    state = {"qobuz_usage": {"days": {"2026-10-19": 60, "2026-10-20": count}, "signals": []}}
    budget = Budget(state, lambda: None, Settings(60), today=lambda: date(2026, 10, 20))
    return Acquirer(qobuz, fallback or FakeFallback(), budget, pacer or NoPacer(), fake_process(statuses)), state


def used(state):
    return state["qobuz_usage"]["days"]["2026-10-20"]


def test_isrc_hit_is_downloaded_and_counted(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("1")]})
    a, state = acquirer(q)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "ready" and r.ready.source == "qobuz" and r.ready.source_id == "1"
    assert used(state) == 1
    assert q.searches == [ISRC_Q]


def test_isrc_wrong_duration_falls_through_to_name_search(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("1", dur=200.0)], NAME_Q: [qc("2", isrc=None)]})
    a, _ = acquirer(q)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.ready.source_id == "2"


def test_failed_duration_check_rejects_and_tries_next(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("1")], NAME_Q: [qc("1"), qc("2", dur=157.0)]})
    a, state = acquirer(q, statuses={"qobuz:1": None})
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.ready.source_id == "2"
    assert r.rejected == ["qobuz:1"]
    assert q.downloads == ["1", "2"]  # 1 is not downloaded twice
    assert used(state) == 2


def test_rejected_candidates_are_never_downloaded(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("1")], NAME_Q: [qc("1")]})
    a, _ = acquirer(q)
    r = a.acquire(T, {"qobuz:1"}, tmp_path, lossless_only=False)
    assert q.downloads == [] and r.kind == "missing"


def test_fallback_used_when_qobuz_has_nothing(tmp_path):
    fb = FakeFallback([fc("y1", "youtube"), fc("m1", "youtube_music")])
    a, _ = acquirer(FakeQobuz(), fb)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.ready.source == "youtube_music"
    assert fb.downloads == ["m1"]


def test_fallback_at_most_three_downloads(tmp_path):
    fb = FakeFallback([fc(f"y{i}") for i in range(5)])
    a, _ = acquirer(FakeQobuz(), fb, statuses={f"youtube:y{i}": None for i in range(5)})
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert fb.downloads == ["y0", "y1", "y2"] and r.kind == "missing"


def test_nothing_anywhere_is_missing(tmp_path):
    a, _ = acquirer(FakeQobuz(), FakeFallback())
    assert a.acquire(T, set(), tmp_path, lossless_only=False).kind == "missing"


def test_search_error_is_errored_not_missing(tmp_path):
    a, _ = acquirer(FakeQobuz(fail_search=True), FakeFallback())
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "errored"
    assert any("network down" in e for e in r.errors)


def test_fallback_search_error_is_errored(tmp_path):
    a, _ = acquirer(FakeQobuz(), FakeFallback(errors=["YouTube search failed: 403"]))
    assert a.acquire(T, set(), tmp_path, lossless_only=False).kind == "errored"


def test_download_error_is_errored(tmp_path):
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}, fail_download={"1"}), FakeFallback())
    assert a.acquire(T, set(), tmp_path, lossless_only=False).kind == "errored"


def test_unavailable_qobuz_track_is_rejected_not_errored(tmp_path):
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}, unavailable={"1"}), FakeFallback())
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "missing" and r.rejected == ["qobuz:1"] and r.errors == []


def test_daily_limit_reached_queues_without_fallback(tmp_path):
    fb = FakeFallback([fc("y1")])
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}), fb, count=60)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "queued" and fb.downloads == []


def test_daily_limit_reached_mid_track(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("1")], NAME_Q: [qc("2", isrc=None)]})
    fb = FakeFallback([fc("y1")])
    a, _ = acquirer(q, fb, statuses={"qobuz:1": None}, count=59)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "queued" and r.rejected == ["qobuz:1"] and fb.downloads == []


def test_lossless_only_discards_fake_and_skips_fallback(tmp_path):
    fb = FakeFallback([fc("y1")])
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}), fb, statuses={"qobuz:1": "fake_lossless"})
    r = a.acquire(T, set(), tmp_path, lossless_only=True)
    assert r.kind == "missing" and r.rejected == ["qobuz:1"] and fb.downloads == []
    assert fb.searched == [("soundcloud",)]  # only for the artists' free downloads


GATE = {"url": "https://hypeddit.com/a/b", "host": "hypeddit.com", "direct": False, "page": "https://sc/s1",
        "title": "Gimme Gimme", "uploader": "Vatoz Locoz"}
DIRECT = {**GATE, "url": "https://sc/s1", "host": "soundcloud.com", "direct": True}


def test_free_downloads_of_matching_soundcloud_versions_are_noted(tmp_path):
    fb = FakeFallback([fc("y1", "youtube_music"), fc("s1", "soundcloud")], offers={"soundcloud:s1": GATE})
    a, _ = acquirer(None, fb)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "ready" and r.ready.source == "youtube_music"  # a gate is for the user, not downloaded
    assert r.free_downloads == [GATE]


def test_none_found_is_an_empty_list_and_a_failed_search_keeps_the_old_ones(tmp_path):
    a, _ = acquirer(None, FakeFallback([fc("y1", "youtube_music")]))
    assert a.acquire(T, set(), tmp_path, lossless_only=False).free_downloads == []
    a, _ = acquirer(None, FakeFallback([fc("y1", "youtube_music")], errors=["SoundCloud search failed: 403"]))
    assert a.acquire(T, set(), tmp_path, lossless_only=False).free_downloads is None


def test_the_artists_original_from_soundcloud_comes_before_youtube_music(tmp_path):
    fb = FakeFallback([fc("y1", "youtube_music"), fc("s1", "soundcloud")], offers={"soundcloud:s1": DIRECT})
    a, _ = acquirer(None, fb)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "ready" and r.ready.source == "soundcloud" and fb.downloads == ["direct:s1"]


def test_an_original_that_needs_a_login_falls_back_quietly(tmp_path):
    fb = FakeFallback([fc("y1", "youtube_music"), fc("s1", "soundcloud")], offers={"soundcloud:s1": DIRECT},
                      fail_direct=True)
    a, _ = acquirer(None, fb)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "ready" and r.ready.source == "youtube_music" and r.errors == []


def test_upgrade_check_takes_a_lossless_original_but_no_stream(tmp_path):
    fb = FakeFallback([fc("s1", "soundcloud")], offers={"soundcloud:s1": DIRECT})
    a, _ = acquirer(FakeQobuz(), fb, statuses={"soundcloud:s1": "lossless"})
    r = a.acquire(T, set(), tmp_path, lossless_only=True)
    assert r.kind == "ready" and fb.downloads == ["direct:s1"]
    fb = FakeFallback([fc("s1", "soundcloud")], offers={"soundcloud:s1": DIRECT})
    a, _ = acquirer(FakeQobuz(), fb)  # the original is an MP3: not an upgrade, but not rejected either
    r = a.acquire(T, set(), tmp_path, lossless_only=True)
    assert r.kind == "missing" and r.rejected == [] and r.free_downloads == [DIRECT]


def test_upgrade_check_search_errors_do_not_make_it_an_error(tmp_path):
    a, _ = acquirer(FakeQobuz(), FakeFallback(errors=["SoundCloud search failed: 403"]))
    r = a.acquire(T, set(), tmp_path, lossless_only=True)
    assert r.kind == "missing" and r.free_downloads is None


def test_fake_lossless_is_kept_in_normal_acquisition(tmp_path):
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}), statuses={"qobuz:1": "fake_lossless"})
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "ready" and r.ready.status == "fake_lossless"


needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def noise_flac(path, seconds):
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
                    f"anoisesrc=d={seconds}:c=white:r=44100:a=0.3", "-c:a", "flac", str(path)], check=True)


@needs_ffmpeg
def test_make_ready_converts_tags_and_judges(tmp_path):
    src = tmp_path / "qobuz_1.flac"
    noise_flac(src, 10)
    track = SourceTrack("t1", "Song", ("Artist",), "Album", None, 10000, "DE1")
    r = make_ready(src, track, Candidate("qobuz", "1", "Song", "Artist", 10.0), tmp_path)
    assert r.status == "lossless" and r.path.suffix == ".aiff" and r.path.exists()
    assert AIFF(str(r.path)).tags.getall("COMM")[0].text == ["Qobuz FLAC · verified lossless"]


@needs_ffmpeg
def test_make_ready_rejects_preview_length_file(tmp_path):
    src = tmp_path / "qobuz_1.flac"
    noise_flac(src, 30)
    track = SourceTrack("t1", "Song", ("Artist",), "Album", None, 180000, None)
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    assert make_ready(src, track, Candidate("qobuz", "1", "Song", "Artist", 180.0), tmp_path, tracker) is None
    checked = [e for e in events if isinstance(e, Checked)]
    assert len(checked) == 1 and checked[0].ok is False
    assert round(checked[0].file_duration_s) == 30 and checked[0].track_duration_s == 180.0
    assert checked[0].codec == "flac"


@needs_ffmpeg
def test_make_ready_reports_the_length_check(tmp_path):
    src = tmp_path / "qobuz_1.flac"
    noise_flac(src, 10)
    track = SourceTrack("t1", "Song", ("Artist",), "Album", None, 10000, None)
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    make_ready(src, track, Candidate("qobuz", "1", "Song", "Artist", 10.0), tmp_path, tracker)
    checked = [e for e in events if isinstance(e, Checked)]
    assert checked == [Checked("t1", checked[0].file_duration_s, 10.0, "flac", True)]
    steps = [e.step if isinstance(e, StepChanged) else type(e).__name__ for e in events
             if isinstance(e, (StepChanged, Checked))]
    assert steps[:2] == ["check", "Checked"]


class SpyPacer(NoPacer):
    def __init__(self):
        self.calls = []

    def between_qobuz_downloads(self):
        self.calls.append("between")


def test_protection_pause_only_between_two_qobuz_downloads(tmp_path):
    pacer = SpyPacer()
    q = FakeQobuz({ISRC_Q: [qc("1")]})
    a, _ = acquirer(q, pacer=pacer)
    a.acquire(T, set(), tmp_path, lossless_only=False)
    assert pacer.calls == []  # nothing to wait for before the first download of the run
    a.acquire(T, set(), tmp_path, lossless_only=False)
    assert pacer.calls == ["between"]


def test_steps_are_reported(tmp_path):
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}))
    a.acquire(T, set(), tmp_path, False, tracker)
    assert [e.step for e in events if isinstance(e, StepChanged)] == ["search", "download"]


def test_auto_stop_after_three_failed_qobuz_downloads(tmp_path):
    events = []
    fb = FakeFallback([fc("y1")])
    a, state = acquirer(FakeQobuz({ISRC_Q: [qc("1")], NAME_Q: [qc("2", isrc=None)]}, fail_download={"1", "2"}), fb)
    a.emit = events.append
    first = a.acquire(T, set(), tmp_path, lossless_only=False)  # 2 failures; Qobuz had trouble -> no YouTube copy
    assert first.kind == "errored" and fb.downloads == []
    second = a.acquire(T, set(), tmp_path, lossless_only=False)  # 3rd failure -> Qobuz paused for this run
    assert second.kind == "errored" and a.budget.stopped  # its own download failed; no name search after that
    third = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert third.kind == "queued" and "paused" in third.note
    assert [s["kind"] for s in state["qobuz_usage"]["signals"]][-1] == "auto_stop"
    warnings = [e for e in events if getattr(e, "level", "") == "warning"]
    assert len(warnings) == 1 and "paused" in warnings[0].text


def test_qobuz_trouble_does_not_fill_the_library_from_youtube(tmp_path):
    fb = FakeFallback([fc("y1")])
    a, state = acquirer(FakeQobuz(fail_search=True), fb)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "errored" and fb.downloads == []
    assert {s["kind"] for s in state["qobuz_usage"]["signals"]} == {"search_failed"}


def test_preview_length_file_leaves_a_warning_sign(tmp_path):
    a, state = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}), statuses={"qobuz:1": None})
    a.acquire(T, set(), tmp_path, lossless_only=False)
    assert [s["kind"] for s in state["qobuz_usage"]["signals"]] == ["duration_mismatch"]


class FallbackPacer(NoPacer):
    def __init__(self):
        self.calls = 0

    def between_fallback_downloads(self):
        self.calls += 1


def test_fallback_pause_only_between_downloads(tmp_path):
    pacer = FallbackPacer()
    fb = FakeFallback([fc("y1"), fc("y2")])
    a, _ = acquirer(FakeQobuz(), fb, statuses={"youtube:y1": None}, pacer=pacer)
    a.acquire(T, set(), tmp_path, lossless_only=False)
    assert fb.downloads == ["y1", "y2"] and pacer.calls == 1


def test_qobuz_preview_is_a_temporary_failure_not_a_rejection(tmp_path):
    fb = FakeFallback([fc("y1")])
    a, state = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}, preview={"1"}), fb)
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert r.kind == "errored" and r.rejected == [] and fb.downloads == []  # no YouTube copy, retried next run
    assert any("subscription" in e for e in r.errors)
    assert state["qobuz_usage"]["days"]["2026-10-20"] == 0  # not counted toward the daily limit
    assert [s["kind"] for s in state["qobuz_usage"]["signals"]] == ["preview_only"]
    assert a.budget.failures_in_a_row == 1  # counts toward the auto-stop


def test_qobuz_previews_trigger_the_auto_stop(tmp_path):
    a, state = acquirer(FakeQobuz({ISRC_Q: [qc("1")], NAME_Q: [qc("2", isrc=None)]}, preview={"1", "2"}))
    a.acquire(T, set(), tmp_path, lossless_only=False)
    a.acquire(T, set(), tmp_path, lossless_only=False)
    assert a.budget.stopped and state["qobuz_usage"]["signals"][-1]["kind"] == "auto_stop"
    assert a.acquire(T, set(), tmp_path, lossless_only=False).kind == "queued"


def test_failed_searches_separated_by_working_ones_do_not_pause_qobuz(tmp_path):
    class Flaky(FakeQobuz):
        def search(self, query, limit=10):  # ISRC search fails, name search works, track after track
            if query == ISRC_Q:
                self.searches.append(query)
                raise RuntimeError("network hiccup")
            return super().search(query, limit)

    a, _ = acquirer(Flaky())
    for _ in range(4):
        a.acquire(T, set(), tmp_path, lossless_only=False)
    assert not a.budget.stopped


def test_no_further_qobuz_search_once_qobuz_is_paused(tmp_path):
    q = FakeQobuz(fail_search=True)
    a, _ = acquirer(q)
    a.budget.failures_in_a_row = 2  # two earlier failures; this track's ISRC search is the third
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert a.budget.stopped and q.searches == [ISRC_Q]  # the name search is not sent any more
    assert r.kind == "errored"


def test_no_further_qobuz_download_once_qobuz_is_paused(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("1"), qc("2")]}, fail_download={"1", "2"})
    attempts = []
    q.download = lambda cand, workdir, progress=None: attempts.append(cand.id) or FakeQobuz.download(q, cand, workdir)
    a, _ = acquirer(q)
    a.budget.failures_in_a_row, a.budget.download_failed_in_row = 2, True  # two failed downloads before
    r = a.acquire(T, set(), tmp_path, lossless_only=False)
    assert attempts == ["1"] and r.kind == "errored"


def test_source_chosen_before_each_download_and_usage_after_each_counted_one(tmp_path):
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    q = FakeQobuz({ISRC_Q: [qc("1")]})
    a, _ = acquirer(q, count=41)
    a.acquire(T, set(), tmp_path, False, tracker)
    names = [type(e).__name__ if not isinstance(e, StepChanged) else e.step for e in events]
    assert names == ["search", "SourceChosen", "download", "AccountUsage"]
    assert events[1] == SourceChosen("t1", "qobuz", "isrc", "Gimme Gimme", 156.0)
    assert events[3] == AccountUsage("qobuz", 42, 60)


def test_the_exact_id_is_downloaded_first_without_any_search(tmp_path):
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    q = FakeQobuz({ISRC_Q: [qc("1")]})
    a, state = acquirer(q, count=41)
    r = a.acquire(T, set(), tmp_path, False, tracker, exact="900000001")
    assert r.kind == "ready" and r.ready.source_id == "900000001"
    assert q.searches == [] and q.downloads == ["900000001"] and used(state) == 42
    assert [e for e in events if isinstance(e, SourceChosen)] == [
        SourceChosen("t1", "qobuz", "exact", "Gimme Gimme", 156.0)]
    assert r.qobuz_searched is False


def test_a_preview_only_exact_id_is_not_downloaded_again_by_the_search(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("900000001"), qc("2")]}, preview={"900000001"})
    attempts = []
    q.download = lambda cand, workdir, progress=None: attempts.append(cand.id) or FakeQobuz.download(q, cand, workdir)
    a, state = acquirer(q)
    r = a.acquire(T, set(), tmp_path, False, exact="900000001")
    assert attempts == ["900000001", "2"] and q.searches == [ISRC_Q]
    assert r.kind == "ready" and r.ready.source_id == "2" and r.qobuz_searched is False  # the name step never ran
    assert used(state) == 1 and a.budget.failures_in_a_row == 0  # the search worked: the streak is broken


def test_a_failed_exact_id_counts_once_toward_the_auto_stop(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("900000001")]}, preview={"900000001"})
    a, state = acquirer(q)
    r = a.acquire(T, set(), tmp_path, False, exact="900000001")
    assert r.kind == "errored" and r.rejected == []
    assert a.budget.failures_in_a_row == 1 and q.downloads == []  # one failed request; the search skips that id
    assert [s["kind"] for s in state["qobuz_usage"]["signals"]] == ["preview_only"]


def test_a_permanently_unavailable_exact_id_is_rejected_and_the_search_goes_on(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("2")]}, unavailable={"900000001"})
    a, _ = acquirer(q)
    r = a.acquire(T, set(), tmp_path, False, exact="900000001")
    assert r.kind == "ready" and r.ready.source_id == "2" and r.rejected == ["qobuz:900000001"]


def test_an_exact_file_that_fails_the_length_check_is_not_downloaded_again_by_the_search(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("900000001"), qc("2")]})
    a, _ = acquirer(q, statuses={"qobuz:900000001": None})
    r = a.acquire(T, set(), tmp_path, False, exact="900000001")
    assert q.downloads == ["900000001", "2"] and q.searches == [ISRC_Q]
    assert r.kind == "ready" and r.ready.source_id == "2" and r.rejected == ["qobuz:900000001"]


def test_an_exact_file_that_is_not_lossless_is_rejected_in_an_upgrade_check_and_the_chain_goes_on(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("900000001"), qc("2")]})
    a, _ = acquirer(q, statuses={"qobuz:900000001": "not_lossless"})
    r = a.acquire(T, set(), tmp_path, True, exact="900000001")
    assert q.downloads == ["900000001", "2"] and r.rejected == ["qobuz:900000001"]
    assert r.kind == "ready" and r.ready.source_id == "2"


def test_the_exact_id_that_would_be_the_third_failure_pauses_qobuz_before_any_search(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("2")]}, fail_download={"900000001"})
    a, _ = acquirer(q)
    a.budget.failures_in_a_row, a.budget.download_failed_in_row = 2, True
    r = a.acquire(T, set(), tmp_path, False, exact="900000001")
    assert a.budget.stopped and q.searches == [] and q.downloads == [] and r.kind == "errored"


def test_the_exact_id_waits_when_the_budget_is_used_up_or_paused(tmp_path):
    q = FakeQobuz()
    a, _ = acquirer(q, count=60)
    assert a.acquire(T, set(), tmp_path, False, exact="900000001").kind == "queued"
    a, _ = acquirer(q)
    a.budget.stopped = True
    assert a.acquire(T, set(), tmp_path, False, exact="900000001").kind == "queued"
    assert q.searches == [] and q.downloads == []


def test_an_exact_id_that_was_rejected_before_is_not_tried(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("2")]})
    a, _ = acquirer(q)
    r = a.acquire(T, {"qobuz:900000001"}, tmp_path, False, exact="900000001")
    assert q.downloads == ["2"] and q.searches == [ISRC_Q] and r.ready.source_id == "2"


def test_without_an_exact_id_or_without_qobuz_nothing_changes(tmp_path):
    q = FakeQobuz({ISRC_Q: [qc("1")]})
    a, _ = acquirer(q)
    assert a.acquire(T, set(), tmp_path, False, exact=None).ready.source_id == "1"
    q2 = FakeQobuz()
    a, _ = acquirer(q2, FakeFallback([fc("y1")]))
    assert a.acquire(T, set(), tmp_path, False, qobuz=False, exact="900000001").ready.source_id == "y1"
    assert q2.downloads == [] and q2.searches == []


def test_source_chosen_names_how_the_candidate_was_found(tmp_path):
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    q = FakeQobuz({ISRC_Q: [], NAME_Q: []})
    a, _ = acquirer(q, FakeFallback([fc("y1", source="youtube_music")]))
    a.acquire(T, set(), tmp_path, False, tracker)
    chosen = [e for e in events if isinstance(e, SourceChosen)]
    assert chosen == [SourceChosen("t1", "youtube_music", "fallback", "Vatoz Locoz - Gimme Gimme", 156.0)]
    assert not any(isinstance(e, AccountUsage) for e in events)  # YouTube downloads don't count


def test_failed_qobuz_download_reports_no_usage(tmp_path):
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")], NAME_Q: []}, fail_download={"1"}))
    a.acquire(T, set(), tmp_path, False, tracker)
    assert [e.query_kind for e in events if isinstance(e, SourceChosen)] == ["isrc"]
    assert not any(isinstance(e, AccountUsage) for e in events)


class OrderPacer(NoPacer):
    def __init__(self, events):
        self.events = events

    def between_qobuz_downloads(self):
        self.events.append("between")


def test_the_source_is_known_before_the_protection_pause(tmp_path):
    events = []
    tracker = Tracker(events.append, CancelToken(), "t1", min_interval=0)
    a, _ = acquirer(FakeQobuz({ISRC_Q: [qc("1")]}), pacer=OrderPacer(events))
    a.acquire(T, set(), tmp_path, False, tracker)
    events.clear()
    a.acquire(T, set(), tmp_path, False, tracker)
    names = [e if isinstance(e, str) else type(e).__name__ for e in events]
    assert names.index("SourceChosen") < names.index("between") < names.index("StepChanged", names.index("between"))
