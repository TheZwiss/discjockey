"""The playlist's own upload (plan library stage 6, D7/I6): tried once after Qobuz and before the fallback search,
through the same account rules as any other match."""
import shutil

import pytest
from mutagen.aiff import AIFF
from test_acquire import NAME_Q, FakeFallback, FakeQobuz, T, acquirer, fc, noise_flac
from test_acquire_accounts import AccountFallback, RecordingPacer, setup

from discjockey.acquire import MISSES_PER_TRACK, make_ready, upload_candidate
from discjockey.events import CancelToken, SourceChosen, Tracker
from discjockey.models import Candidate, SourceTrack

SC_ID, YT_ID = "900000101", "EXAMPLEid01"
SC_KEY, YT_KEY = f"soundcloud:{SC_ID}", f"youtube_music:{YT_ID}"
GATE = {"url": "https://hypeddit.com/example", "host": "hypeddit.com", "direct": False,
        "page": "https://soundcloud.com/example-label/example", "title": "Gimme Gimme", "uploader": "example-label"}
DIRECT = {**GATE, "url": GATE["page"], "host": "soundcloud.com", "direct": True}


def sc_upload(account_only=False, dur=156000):
    return SourceTrack(SC_ID, "Gimme Gimme", ("Vatoz Locoz",), "", None, dur, None, service="soundcloud",
                       link="https://soundcloud.com/example-label/example", account_only=account_only)


def yt_upload():
    return SourceTrack(YT_ID, "Gimme Gimme", ("Vatoz Locoz",), "", None, 156000, None, service="youtube_music")


def get(a, tmp_path, upload, rejected=(), lossless_only=False, events=None, **kw):
    tracker = Tracker((events if events is not None else []).append, CancelToken(), "t1", min_interval=0)
    return a.acquire(T, set(rejected), tmp_path, lossless_only, tracker, upload=upload, **kw)


class RecordingFallback(FakeFallback):
    """FakeFallback that also notes which candidates the download-button lookup was asked about."""

    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.looked_up = []

    def free_downloads(self, cands):
        self.looked_up += [c.key for c in cands]
        return super().free_downloads(cands)


def test_the_candidate_is_the_upload_itself_and_its_address_comes_from_the_id():
    c = upload_candidate(sc_upload())
    assert c == Candidate("soundcloud", SC_ID, "Gimme Gimme", "Vatoz Locoz", 156.0,
                          url=f"https://api.soundcloud.com/tracks/{SC_ID}")
    assert upload_candidate(yt_upload()).url == f"https://music.youtube.com/watch?v={YT_ID}"


def test_qobuz_comes_first_then_the_upload_and_no_search_when_it_works(tmp_path):
    q = FakeQobuz({NAME_Q: []})
    fb = RecordingFallback([fc("y1")])
    a, _ = acquirer(q, fb)
    events = []
    r = get(a, tmp_path, sc_upload(), events=events)
    assert q.searches == ["DECE72605755", NAME_Q]
    assert (r.kind, r.ready.source, r.ready.source_id) == ("ready", "soundcloud", SC_ID)
    assert fb.downloads == [SC_ID] and fb.searched == [] and fb.looked_up == [SC_KEY]
    assert [(e.source, e.query_kind) for e in events if isinstance(e, SourceChosen)] == [("soundcloud", "upload")]


def test_a_qobuz_hit_never_reaches_the_upload(tmp_path):
    from test_acquire import qc
    q = FakeQobuz({"DECE72605755": [qc("1")]})
    fb = RecordingFallback()
    a, _ = acquirer(q, fb)
    r = get(a, tmp_path, sc_upload())
    assert r.ready.source == "qobuz" and fb.downloads == [] and fb.looked_up == []


def test_qobuz_trouble_leaves_the_upload_for_the_next_run(tmp_path):
    fb = RecordingFallback()
    a, _ = acquirer(FakeQobuz(fail_search=True), fb)
    r = get(a, tmp_path, sc_upload())
    assert r.kind == "errored" and fb.downloads == [] and fb.looked_up == []


def test_the_artist_s_free_download_comes_before_the_stream(tmp_path):
    fb = RecordingFallback(offers={SC_KEY: DIRECT})
    a, _ = acquirer(None, fb)
    events = []
    r = get(a, tmp_path, sc_upload(), events=events)
    assert fb.downloads == [f"direct:{SC_ID}"] and r.kind == "ready"
    assert r.free_downloads == [{k: v for k, v in DIRECT.items()}]
    assert [e.query_kind for e in events if isinstance(e, SourceChosen)] == ["upload"]


def test_a_free_download_that_needs_a_login_falls_back_to_the_stream(tmp_path):
    fb = RecordingFallback(offers={SC_KEY: DIRECT}, fail_direct=True)
    a, _ = acquirer(None, fb)
    r = get(a, tmp_path, sc_upload())
    assert fb.downloads == [SC_ID] and r.kind == "ready" and fb.searched == []


def test_a_gate_link_is_noted_and_the_stream_taken(tmp_path):
    fb = RecordingFallback(offers={SC_KEY: GATE})
    a, _ = acquirer(None, fb)
    r = get(a, tmp_path, sc_upload())
    assert fb.downloads == [SC_ID] and r.free_downloads == [GATE]


def test_the_upload_s_gate_link_stays_beside_the_search_s_ones(tmp_path):
    other = {**GATE, "url": "https://toneden.io/example", "host": "toneden.io"}
    fb = RecordingFallback([fc("s2", "soundcloud")], offers={SC_KEY: GATE, "soundcloud:s2": other})
    a, _ = acquirer(None, fb, statuses={SC_KEY: None})  # the upload fails its length check
    r = get(a, tmp_path, sc_upload())
    assert r.free_downloads == [GATE, other] and fb.downloads == [SC_ID, "s2"]


def test_a_youtube_music_upload_is_downloaded_free_without_a_download_button_lookup(tmp_path):
    fb = RecordingFallback()
    a, _ = acquirer(None, fb)
    r = get(a, tmp_path, yt_upload())
    assert fb.downloads == [YT_ID] and fb.looked_up == [] and r.free_downloads is None


def test_a_failed_upload_falls_through_to_the_search_and_is_not_downloaded_again(tmp_path):
    fb = RecordingFallback([Candidate("soundcloud", SC_ID, "Vatoz Locoz - Gimme Gimme", "Vatoz Locoz", 156.0,
                                      url="https://soundcloud.com/example-label/example"), fc("y1")])
    pacer = RecordingPacer()
    a, _ = acquirer(None, fb, statuses={SC_KEY: None}, pacer=pacer)
    r = get(a, tmp_path, sc_upload())
    assert fb.downloads == [SC_ID, "y1"] and r.ready.source_id == "y1"
    assert r.rejected == [SC_KEY]  # _try records it as for a searched candidate
    assert fb.looked_up == [SC_KEY]  # the search's own lookup leaves the upload out
    assert pacer.calls == ["fallback"]  # the search's first download is paced after the upload's


def test_an_upload_whose_download_fails_is_not_downloaded_again_by_the_search(tmp_path):
    class Failing(RecordingFallback):
        def download(self, cand, workdir, progress=None):
            if cand.id == SC_ID:
                raise RuntimeError("HTTP Error 404")
            return super().download(cand, workdir, progress)

    fb = Failing([Candidate("soundcloud", SC_ID, "Vatoz Locoz - Gimme Gimme", "Vatoz Locoz", 156.0, url="x"),
                  fc("y1")])
    a, _ = acquirer(None, fb)
    r = get(a, tmp_path, sc_upload())
    assert fb.downloads == ["y1"] and r.ready.source_id == "y1" and r.rejected == []


def test_a_rejected_upload_is_not_tried(tmp_path):
    fb = RecordingFallback([fc("y1")], offers={SC_KEY: DIRECT})
    a, _ = acquirer(None, fb)
    r = get(a, tmp_path, sc_upload(), rejected={SC_KEY})
    assert fb.downloads == ["y1"] and fb.looked_up == [] and r.ready.source_id == "y1"


def test_a_rejected_youtube_music_upload_does_not_come_back_through_the_youtube_search(tmp_path):
    fb = RecordingFallback([fc(YT_ID), fc("y1")])  # the search finds the same video as youtube:EXAMPLEid01
    a, _ = acquirer(None, fb)
    r = get(a, tmp_path, yt_upload(), rejected={YT_KEY})
    assert fb.downloads == ["y1"] and r.ready.source_id == "y1"


def test_a_youtube_music_upload_tried_once_is_not_downloaded_again_by_the_youtube_search(tmp_path):
    fb = RecordingFallback([fc(YT_ID), fc("y1")])
    a, _ = acquirer(None, fb, statuses={YT_KEY: None})  # its length check fails
    r = get(a, tmp_path, yt_upload())
    assert fb.downloads == [YT_ID, "y1"] and r.ready.source_id == "y1"
    assert r.rejected == [YT_KEY]


def test_the_stream_cap_spans_the_upload_and_the_search(tmp_path):
    fb = RecordingFallback([fc(f"y{i}") for i in range(5)])
    a, _ = acquirer(None, fb, statuses={SC_KEY: None, **{f"youtube:y{i}": None for i in range(5)}})
    r = get(a, tmp_path, sc_upload())
    assert fb.downloads == [SC_ID, "y0", "y1"] and r.kind == "missing"  # 3 streams for the track, not 1 + 3


def test_a_track_without_an_upload_keeps_its_three_streams(tmp_path):
    fb = RecordingFallback([fc(f"y{i}") for i in range(5)])
    a, _ = acquirer(None, fb, statuses={f"youtube:y{i}": None for i in range(5)})
    r = get(a, tmp_path, None)
    assert fb.downloads == ["y0", "y1", "y2"] and r.kind == "missing"


def test_without_an_upload_nothing_changes(tmp_path):
    fb = RecordingFallback([fc("y1")])
    a, _ = acquirer(None, fb)
    r = get(a, tmp_path, None)
    assert fb.searched == [None] and fb.downloads == ["y1"] and r.ready.source_id == "y1"


# --- the account rules (spec sources-and-limits §2-§4) ---

def test_the_upload_comes_through_go_plus_with_the_pause_and_counts(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={SC_KEY: 256})
    pacer = RecordingPacer()
    a, state, _ = setup(fb, limits={"soundcloud": 60}, pacer=pacer)
    a.account_downloaded.add("soundcloud")  # an earlier track of this run used the account
    events = []
    r = get(a, tmp_path, sc_upload(), events=events)
    assert fb.probes == [(SC_KEY, True)] and fb.downloads == [f"account:{SC_ID}"] and r.ready.kbps == 256
    assert pacer.calls == ["soundcloud"] and fb.searched == []
    assert state["soundcloud_usage"]["days"]["2026-10-20"] == 1
    assert [e.query_kind for e in events if isinstance(e, SourceChosen)] == ["upload"]


def test_the_upload_waits_for_a_used_up_account(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")])
    a, _, _ = setup(fb, used={"soundcloud": 60}, limits={"soundcloud": 60})
    r = get(a, tmp_path, sc_upload())
    assert (r.kind, r.note) == ("queued", "daily SoundCloud Go+ limit reached")
    assert fb.downloads == [] and fb.probes == [] and fb.searched == []


def test_the_upload_waits_for_a_paused_account(tmp_path):
    fb = AccountFallback()
    a, _, _ = setup(fb, stopped=("youtube",))
    r = get(a, tmp_path, yt_upload())
    assert r.kind == "queued" and fb.downloads == []


def test_without_a_go_plus_stream_the_upload_is_taken_free(tmp_path):
    fb = AccountFallback([fc("y1")])
    a, state, _ = setup(fb, limits={"soundcloud": 60})
    r = get(a, tmp_path, sc_upload())
    assert fb.probes == [(SC_KEY, True)] and fb.downloads == [SC_ID] and r.ready.source_id == SC_ID
    assert state["soundcloud_usage"]["signals"][-1]["kind"] == "premium_missing"


def test_a_go_plus_only_upload_without_the_account_is_not_downloaded_and_the_search_follows(tmp_path):
    fb = AccountFallback([Candidate("soundcloud", SC_ID, "Vatoz Locoz - Gimme Gimme", "Vatoz Locoz", 156.0, url="x"),
                          fc("y1")])
    a, _, _ = setup(fb, limits={})
    r = get(a, tmp_path, sc_upload(account_only=True))
    assert fb.downloads == ["y1"] and r.ready.source_id == "y1"
    assert r.rejected == []  # no account: nothing was listed, so the upload is not remembered as no good


def test_a_go_plus_only_upload_without_a_go_plus_stream_is_never_taken_free(tmp_path):
    fb = AccountFallback([fc("y1")])
    a, _, _ = setup(fb, limits={"soundcloud": 60})
    r = get(a, tmp_path, sc_upload(account_only=True))
    assert fb.probes == [(SC_KEY, True)] and fb.downloads == ["y1"]
    # its listing showed no Go+ stream, so the free preview is out for good, as the failed length check made it before
    assert r.ready.source_id == "y1" and r.rejected == [SC_KEY]


def test_a_go_plus_only_upload_whose_listing_failed_is_not_rejected_for_good(tmp_path):
    fb = AccountFallback([fc("y1")], probe_error=RuntimeError("HTTP Error 502: Bad Gateway"))
    a, _, _ = setup(fb, limits={"soundcloud": 60})
    r = get(a, tmp_path, sc_upload(account_only=True))
    assert fb.probes[0] == (SC_KEY, True) and fb.downloads == ["y1"] and r.ready.source_id == "y1"
    assert r.rejected == []  # the listing failed: nothing is known about the stream, so it is tried again next run


def test_a_go_plus_only_upload_comes_through_the_account(tmp_path):
    fb = AccountFallback(kbps={SC_KEY: 256})
    a, _, _ = setup(fb, limits={"soundcloud": 60})
    r = get(a, tmp_path, sc_upload(account_only=True))
    assert fb.downloads == [f"account:{SC_ID}"] and r.kind == "ready"


def test_a_failed_upload_s_listing_leaves_one_more_for_the_search(tmp_path):
    others = [Candidate("soundcloud", f"s{i}", "Vatoz Locoz - Gimme Gimme", "Vatoz Locoz", 156.0, url=f"x{i}")
              for i in range(3)]
    fb = AccountFallback(others)
    events = []
    a, state, _ = setup(fb, limits={"soundcloud": 60})
    a.process = lambda downloaded, track, cand, workdir, tracker: None  # every file fails its length check
    r = get(a, tmp_path, sc_upload(), events=events)
    assert [p for p, _ in fb.probes] == [SC_KEY, "soundcloud:s0"]  # MISSES_PER_TRACK over the upload and the search
    assert len(fb.probes) == MISSES_PER_TRACK and r.kind == "missing"
    misses = [s for s in state["soundcloud_usage"]["signals"] if s["kind"] == "premium_missing"]
    assert len(misses) == 2  # noted, like any SoundCloud listing without Go+; only YouTube's count once per track


# --- upgrade checks (lossless_only) ---

def test_an_upgrade_check_takes_the_upload_s_lossless_original_first(tmp_path):
    fb = RecordingFallback([fc("s2", "soundcloud")], offers={SC_KEY: DIRECT, "soundcloud:s2": DIRECT})
    a, _ = acquirer(None, fb, statuses={SC_KEY: "lossless"})
    events = []
    r = get(a, tmp_path, sc_upload(), lossless_only=True, events=events)
    assert fb.downloads == [f"direct:{SC_ID}"] and r.ready.status == "lossless"
    assert fb.searched == [("soundcloud",)] and fb.looked_up == [SC_KEY, "soundcloud:s2"]
    assert [e.query_kind for e in events if isinstance(e, SourceChosen)] == ["upload"]


def test_an_upgrade_check_without_the_originals_leaves_the_upload_s_original_out(tmp_path):
    fb = RecordingFallback(offers={SC_KEY: DIRECT})
    a, _ = acquirer(None, fb, statuses={SC_KEY: "lossless"})
    r = get(a, tmp_path, sc_upload(), lossless_only=True, originals=False)
    assert fb.downloads == [] and r.kind == "missing"


def test_an_upgrade_check_asks_the_upload_s_account_stream_before_searching(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={SC_KEY: 256, "youtube_music:m1": 256})
    a, _, _ = setup(fb)
    r = get(a, tmp_path, sc_upload(), lossless_only=True, better_than=128)
    assert fb.downloads == [f"account:{SC_ID}"] and r.ready.kbps == 256
    assert fb.searched == [("soundcloud",)]  # the originals' search only; no stream search after the upload worked


def test_an_upgrade_check_never_takes_the_upload_s_free_stream(tmp_path):
    fb = AccountFallback(kbps={SC_KEY: 129})
    a, _, _ = setup(fb, limits={"soundcloud": 60})
    r = get(a, tmp_path, sc_upload(), lossless_only=True, better_than=128)
    assert fb.downloads == [] and r.kind == "missing" and fb.probes == [(SC_KEY, True)]


def test_an_upgrade_check_does_not_offer_a_declined_upload_stream_again(tmp_path):
    fb = AccountFallback(kbps={SC_KEY: 256})
    a, _, _ = setup(fb, limits={"soundcloud": 60})
    r = get(a, tmp_path, sc_upload(), lossless_only=True, better_than=128, declined={SC_KEY})
    assert fb.downloads == [] and fb.probes == [] and r.kind == "missing"


# --- D10 ---

@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_a_track_without_an_album_takes_the_candidate_s_album(tmp_path):
    src = tmp_path / "qobuz_1.flac"
    noise_flac(src, 10)
    track = SourceTrack(YT_ID, "Song", ("Artist",), "", None, 10000, None, service="youtube_music")
    r = make_ready(src, track, Candidate("qobuz", "1", "Song", "Artist", 10.0, album="Example Album"), tmp_path)
    assert AIFF(str(r.path)).tags.getall("TALB")[0].text == ["Example Album"]
    src2 = tmp_path / "qobuz_2.flac"
    noise_flac(src2, 10)
    track = SourceTrack("t1", "Song", ("Artist",), "Own Album", None, 10000, None)
    r = make_ready(src2, track, Candidate("qobuz", "2", "Song", "Artist", 10.0, album="Example Album"), tmp_path)
    assert AIFF(str(r.path)).tags.getall("TALB")[0].text == ["Own Album"]
