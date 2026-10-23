"""The §2 order of stream versions, downloads through YouTube Premium / SoundCloud Go+, and the §4 wait rule."""
from datetime import date

from test_acquire import ISRC_Q, NAME_Q, FakeFallback, FakeQobuz, T, fc

from discjockey.acquire import GIVE_UP_AFTER, Acquirer, Ready
from discjockey.events import AccountUsage, CancelToken, Message, Tracker
from discjockey.pacing import AUTO_STOP_AFTER, Budget, NoPacer
from discjockey.settings import Account, Settings

TODAY = date(2026, 10, 20)


class AccountFallback(FakeFallback):
    """FakeFallback that answers format listings (kbps through the login) and downloads with or without it."""

    def __init__(self, cands=(), kbps=None, probe_error=None, download_error=None, **kw):
        super().__init__(cands, **kw)
        self.kbps = kbps or {}  # "source:id" -> kbps through the login (default 129: no premium format)
        self.probe_error, self.download_error, self.probes = probe_error, download_error, []

    def stream_kbps(self, source, source_id, account=False):
        self.probes.append((f"{source}:{source_id}", account))
        if self.probe_error:
            raise self.probe_error
        return self.kbps.get(f"{source}:{source_id}", 129)

    def download(self, cand, workdir, progress=None, account=False):
        if account and self.download_error:
            raise self.download_error
        if not account:
            return super().download(cand, workdir, progress)
        self.downloads.append("account:" + cand.id)
        p = workdir / f"{cand.source}_{cand.id}.m4a"
        p.write_bytes(b"x")
        return p


def process(kbps=None):
    """Ready with the kbps the file would have: 256 for an account download, 128 for an artist's original."""
    def p(downloaded, track, cand, workdir, tracker):
        rate = (kbps or {}).get(cand.key, 128 if cand.direct else 256 if downloaded.suffix == ".m4a" else 129)
        return Ready(downloaded, "not_lossless", cand.source, cand.id, "aac", 20000, "c", rate)
    return p


class RecordingPacer(NoPacer):
    def __init__(self):
        self.calls = []

    def between_fallback_downloads(self):
        self.calls.append("fallback")

    def between_account_downloads(self, service):
        self.calls.append(service)


def setup(fallback, used=None, limits=None, stopped=(), kbps=None, pacer=None, qobuz=None):
    """Accounts set up with limit (default YouTube 30, SoundCloud 60) and today's use; yesterday fully used."""
    limits = limits if limits is not None else {"youtube": 30, "soundcloud": 60}
    state = {f"{s}_usage": {"days": {"2026-10-19": limit, "2026-10-20": (used or {}).get(s, 0)}, "signals": []}
             for s, limit in limits.items()}
    settings = Settings(accounts={s: Account("chrome", limit) for s, limit in limits.items()})
    budgets = {s: Budget(state, lambda: None, settings, today=lambda: TODAY, service=s) for s in limits}
    for s in stopped:
        budgets[s].stopped = True
    events = []
    a = Acquirer(qobuz, fallback, Budget({}, lambda: None, Settings()), pacer or NoPacer(), process(kbps),
                 emit=events.append, accounts=budgets)
    return a, state, events


def run(a, tmp_path, events=None):
    tracker = Tracker((events if events is not None else []).append, CancelToken(), "t1", min_interval=0)
    return a.acquire(T, set(), tmp_path, False, tracker)


def test_without_accounts_order_and_calls_stay_as_before(tmp_path):
    fb = AccountFallback([fc("y1", "youtube"), fc("s1", "soundcloud"), fc("m1", "youtube_music")])
    a, _, _ = setup(fb, limits={})
    r = run(a, tmp_path)
    assert r.ready.source_id == "m1" and fb.downloads == ["m1"] and fb.probes == []


def test_premium_youtube_music_comes_first_and_counts(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud"), fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, state, _ = setup(fb)
    events = []
    r = run(a, tmp_path, events)
    assert fb.downloads == ["account:m1"] and r.ready.kbps == 256
    assert state["youtube_usage"]["days"]["2026-10-20"] == 1
    assert AccountUsage("youtube", 1, 30) in events


def test_go_plus_comes_before_free_youtube_music(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music"), fc("s1", "soundcloud")], kbps={"soundcloud:s1": 256})
    a, state, _ = setup(fb, limits={"soundcloud": 60})
    run(a, tmp_path)
    assert fb.probes == [("soundcloud:s1", True)] and fb.downloads == ["account:s1"]


def test_no_premium_stream_is_tried_as_a_free_one_after_the_others(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music"), fc("s1", "soundcloud")], kbps={"soundcloud:s1": 256})
    a, state, _ = setup(fb)
    run(a, tmp_path)
    assert fb.probes == [("youtube_music:m1", True), ("soundcloud:s1", True)]
    assert fb.downloads == ["account:s1"]
    assert state["youtube_usage"]["signals"][-1]["kind"] == "premium_missing"


def test_soundcloud_without_a_go_plus_stream_is_only_noted(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud")])
    a, state, _ = setup(fb, limits={"soundcloud": 60})
    run(a, tmp_path)
    assert fb.downloads == ["s1"]
    assert a.accounts["soundcloud"].failures_in_a_row == 0
    assert state["soundcloud_usage"]["signals"][-1]["kind"] == "premium_missing"


def test_waits_when_the_only_good_match_needs_a_used_up_account(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")])
    a, _, _ = setup(fb, used={"youtube": 30}, limits={"youtube": 30})
    r = run(a, tmp_path)
    assert (r.kind, r.note) == ("queued", "daily YouTube Premium limit reached")
    assert fb.downloads == [] and fb.probes == []


def test_a_paused_account_makes_its_tracks_wait(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")])
    a, _, _ = setup(fb, stopped=("youtube",))
    r = run(a, tmp_path)
    assert (r.kind, r.note) == ("queued", f"YouTube Premium paused after {AUTO_STOP_AFTER} failed requests in a row")


def test_another_account_of_the_same_tier_stands_in(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music"), fc("s1", "soundcloud")], kbps={"soundcloud:s1": 256})
    a, _, _ = setup(fb, used={"youtube": 30})
    r = run(a, tmp_path)
    assert r.kind == "ready" and fb.downloads == ["account:s1"]


def test_free_only_matches_never_wait(tmp_path):
    fb = AccountFallback([fc("y1", "youtube")])
    a, _, _ = setup(fb, used={"youtube": 30, "soundcloud": 60})
    assert run(a, tmp_path).kind == "ready" and fb.downloads == ["y1"]


def test_unreadable_cookies_fall_back_to_the_free_stream_and_count(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")],
                         probe_error=RuntimeError('could not find chrome cookies database in "/Users/x"'))
    a, state, _ = setup(fb, limits={"youtube": 30})
    r = run(a, tmp_path)
    assert r.kind == "ready" and fb.downloads == ["m1"]
    assert state["youtube_usage"]["signals"][-1]["kind"] == "cookies_unreadable"
    assert a.accounts["youtube"].failures_in_a_row == 1


def test_drm_protected_account_stream_is_skipped_without_a_warning_sign(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud")], probe_error=RuntimeError("[soundcloud] 1: This video is DRM protected"))
    a, state, _ = setup(fb, limits={"soundcloud": 60})
    run(a, tmp_path)
    assert state["soundcloud_usage"]["signals"] == [] and fb.downloads == ["s1"]


def test_drm_protected_account_stream_says_so_in_the_debug_log(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud")],
                         probe_error=RuntimeError("ERROR: [soundcloud] 1: This video is DRM protected"))
    a, _, events = setup(fb, limits={"soundcloud": 60})
    run(a, tmp_path)
    assert any(isinstance(e, Message) and e.level == "debug" and "DRM-protected" in e.text for e in events)


def test_three_failed_account_downloads_pause_it_and_say_so(tmp_path):
    cands = [fc(f"m{i}", "youtube_music") for i in range(1, 4)]
    fb = AccountFallback(cands, kbps={c.key: 256 for c in cands},
                         download_error=RuntimeError("HTTP Error 403: Forbidden"))
    a, state, events = setup(fb, limits={"youtube": 30})
    run(a, tmp_path)
    assert a.accounts["youtube"].stopped
    assert [s["kind"] for s in state["youtube_usage"]["signals"]] == ["refused"] * 3 + ["auto_stop"]
    assert any(isinstance(e, Message) and e.level == "warning" and "YouTube Premium" in e.text for e in events)


def test_a_low_bitrate_artist_original_waits_behind_an_account_stream(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud"), fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256},
                         offers={"soundcloud:s1": {"url": "u", "host": "soundcloud.com", "direct": True}})
    a, _, _ = setup(fb, limits={"youtube": 30})
    r = run(a, tmp_path)
    assert fb.downloads == ["direct:s1", "account:m1"] and r.ready.source_id == "m1"


def test_the_artist_original_is_kept_when_the_account_download_fails(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud"), fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256},
                         offers={"soundcloud:s1": {"url": "u", "host": "soundcloud.com", "direct": True}},
                         download_error=RuntimeError("HTTP Error 403: Forbidden"))
    a, _, _ = setup(fb, limits={"youtube": 30})
    r = run(a, tmp_path)
    assert r.ready.source_id == "s1" and r.ready.kbps == 128


def test_protection_pause_between_downloads_of_the_same_account(tmp_path):
    pacer = RecordingPacer()
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb, limits={"youtube": 30}, pacer=pacer)
    run(a, tmp_path)
    (tmp_path / "2").mkdir()
    run(a, tmp_path / "2")
    assert pacer.calls == ["youtube"]


def test_upgrade_checks_never_use_an_account(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music"), fc("s1", "soundcloud")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb)
    a.acquire(T, set(), tmp_path, True, Tracker([].append, CancelToken(), "t1"))
    assert fb.probes == [] and fb.searched == [("soundcloud",)]


# --- review fixes ---

def test_a_go_plus_version_without_its_stream_makes_the_track_wait_for_youtube(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music"), fc("s1", "soundcloud")])  # s1 has no Go+ stream
    a, _, _ = setup(fb, used={"youtube": 30})
    r = run(a, tmp_path)
    assert (r.kind, r.note) == ("queued", "daily YouTube Premium limit reached")
    assert fb.downloads == [] and fb.probes == [("soundcloud:s1", True)]


def test_a_go_plus_version_behind_several_youtube_uploads_is_still_tried(tmp_path):
    cands = [fc(f"m{i}", "youtube_music") for i in range(1, 4)] + [fc("s1", "soundcloud")]
    fb = AccountFallback(cands, kbps={"soundcloud:s1": 256})
    a, _, _ = setup(fb)
    run(a, tmp_path)
    assert fb.downloads == ["account:s1"]
    assert [p for p, _ in fb.probes] == ["youtube_music:m1", "youtube_music:m2", "soundcloud:s1"]
    assert not a.accounts["youtube"].stopped


def test_one_track_counts_one_missing_premium_toward_the_auto_stop(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music"), fc("m2", "youtube_music")])
    a, state, _ = setup(fb, limits={"youtube": 30})
    run(a, tmp_path)
    assert a.accounts["youtube"].failures_in_a_row == 1 and fb.downloads == ["m1"]


def test_logged_in_format_listings_are_paced(tmp_path):
    pacer = RecordingPacer()
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb, limits={"youtube": 30}, pacer=pacer)
    run(a, tmp_path)
    fb.kbps = {}  # the next track has no premium stream: the listing alone is a logged-in request
    (tmp_path / "2").mkdir()
    run(a, tmp_path / "2")
    assert pacer.calls == ["youtube"] and fb.downloads == ["account:m1", "m1"]


def test_soundcloud_is_no_longer_asked_after_many_tracks_without_go_plus(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud")])
    a, _, events = setup(fb, limits={"soundcloud": 60})
    for i in range(GIVE_UP_AFTER + 2):
        (tmp_path / str(i)).mkdir()
        assert run(a, tmp_path / str(i)).kind == "ready"
    assert len(fb.probes) == GIVE_UP_AFTER
    assert any(isinstance(e, Message) and "SoundCloud Go+" in e.text for e in events)


# --- upgrade checks of lossy files below ~256 kbps (spec §4, decision 5) ---

def check(a, tmp_path, better_than, **kw):
    return a.acquire(T, set(), tmp_path, True, Tracker([].append, CancelToken(), "t1"), better_than=better_than, **kw)


def test_upgrade_check_finds_a_256_stream_for_a_128_file(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, state, _ = setup(fb, limits={"youtube": 30})
    r = check(a, tmp_path, 128)
    assert r.kind == "ready" and r.ready.kbps == 256 and fb.downloads == ["account:m1"]
    assert fb.searched == [("soundcloud",), ("youtube_music",)]
    assert state["youtube_usage"]["days"]["2026-10-20"] == 1


def test_upgrade_check_looks_for_no_stream_without_an_account_or_for_a_good_file(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb, limits={})
    assert check(a, tmp_path, 128).kind == "missing" and fb.searched == [("soundcloud",)]
    fb2 = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    b, _, _ = setup(fb2, limits={"youtube": 30})
    assert check(b, tmp_path, 320).kind == "missing" and fb2.searched == [("soundcloud",)]


def test_upgrade_check_waits_for_an_account_that_is_used_up_or_paused_today(tmp_path):
    # "checked, nothing yet" would skip the track for a week: 30 upgrades a week instead of 30 a day
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb, used={"youtube": 30}, limits={"youtube": 30})
    r = check(a, tmp_path, 128)
    assert (r.kind, r.note) == ("queued", "daily YouTube Premium limit reached")
    assert fb.searched == [("soundcloud",)] and fb.probes == []  # the artists' originals are still looked at
    fb2 = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    b, _, _ = setup(fb2, limits={"youtube": 30}, stopped=("youtube",))
    r = check(b, tmp_path, 128)
    assert r.kind == "queued" and r.note.startswith("YouTube Premium paused")


def test_upgrade_check_waits_when_one_account_could_not_be_asked_today(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")])  # no premium stream through YouTube
    a, _, _ = setup(fb, used={"soundcloud": 60})
    r = check(a, tmp_path, 128)
    assert (r.kind, r.note) == ("queued", "daily SoundCloud Go+ limit reached")
    assert fb.searched == [("soundcloud",), ("youtube_music",)]


def test_upgrade_check_does_not_wait_for_an_account_given_up_on(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")])
    a, _, _ = setup(fb, limits={"youtube": 30})
    a.given_up.add("youtube")
    assert check(a, tmp_path, 128).kind == "missing"


def test_upgrade_check_with_a_stream_found_does_not_wait_for_the_other_account(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb, used={"soundcloud": 60})
    assert check(a, tmp_path, 128).kind == "ready"


def test_upgrade_check_rejects_a_stream_that_came_out_no_better(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb, limits={"youtube": 30}, kbps={"youtube_music:m1": 160})
    r = check(a, tmp_path, 128)
    assert r.kind == "missing" and r.rejected == ["youtube_music:m1"]


def test_upgrade_check_does_not_offer_a_declined_stream_again(tmp_path):
    # declined: the current upload's stream, discarded or no better; its artist's original may still be tried
    fb = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    a, _, _ = setup(fb, limits={"youtube": 30})
    r = check(a, tmp_path, 128, declined={"youtube_music:m1"})
    assert r.kind == "missing" and r.rejected == [] and fb.probes == [] and fb.downloads == []


def test_upgrade_check_lists_few_uploads_without_premium_and_takes_no_free_stream(tmp_path):
    cands = [fc(f"m{i}", "youtube_music") for i in range(1, 4)]
    fb = AccountFallback(cands)  # no premium stream for any of them
    a, _, _ = setup(fb, limits={"youtube": 30})
    assert check(a, tmp_path, 128).kind == "missing"
    assert [p for p, _ in fb.probes] == ["youtube_music:m1", "youtube_music:m2"] and fb.downloads == []
    assert a.accounts["youtube"].failures_in_a_row == 1


def test_upgrade_check_listings_are_paced(tmp_path):
    pacer = RecordingPacer()
    fb = AccountFallback([fc("m1", "youtube_music")])  # no premium stream: the listing alone is a logged-in request
    a, _, _ = setup(fb, limits={"youtube": 30}, pacer=pacer)
    check(a, tmp_path, 128)
    check(a, tmp_path, 128)
    assert pacer.calls == ["youtube"] and len(fb.probes) == 2


def test_upgrade_check_searches_soundcloud_once(tmp_path):
    # the artists' originals and the Go+ listing come from the same anonymous SoundCloud search
    fb = AccountFallback([fc("m1", "youtube_music"), fc("s1", "soundcloud")], kbps={"soundcloud:s1": 256})
    a, _, _ = setup(fb)
    r = check(a, tmp_path, 128)
    assert r.kind == "ready" and fb.downloads == ["account:s1"]
    assert fb.searched == [("soundcloud",), ("youtube_music",)]


def test_upgrade_check_pauses_between_an_artist_original_and_the_first_listing(tmp_path):
    pacer = RecordingPacer()
    fb = AccountFallback([fc("s1", "soundcloud"), fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256},
                         offers={"soundcloud:s1": {"url": "u", "host": "soundcloud.com", "direct": True}})
    a, _, _ = setup(fb, limits={"youtube": 30}, pacer=pacer)
    r = check(a, tmp_path, 128)  # the original is a 128 kbps MP3: not lossless, so the account is asked
    assert r.kind == "ready" and fb.downloads == ["direct:s1", "account:m1"]
    assert pacer.calls == ["fallback"]


def test_upgrade_check_without_the_originals_searches_only_for_the_account_streams(tmp_path):
    fb = AccountFallback([fc("m1", "youtube_music"), fc("s1", "soundcloud")], kbps={"youtube_music:m1": 256},
                         offers={"soundcloud:s1": {"url": "u", "host": "soundcloud.com", "direct": True}})
    a, _, _ = setup(fb, limits={"youtube": 30})
    r = check(a, tmp_path, 128, originals=False)
    assert r.kind == "ready" and fb.searched == [("youtube_music",)] and fb.downloads == ["account:m1"]
    assert r.free_downloads is None  # not looked this time: the ones known stay
    fb2 = AccountFallback([fc("m1", "youtube_music")], kbps={"youtube_music:m1": 256})
    b, _, _ = setup(fb2, used={"youtube": 30}, limits={"youtube": 30})
    r = check(b, tmp_path, 128, originals=False)
    assert r.kind == "queued" and fb2.searched == []


def test_a_queued_upgrade_check_notes_a_qobuz_search_that_found_nothing_better(tmp_path):
    q = FakeQobuz()
    a, _, _ = setup(AccountFallback(), used={"youtube": 30}, limits={"youtube": 30}, qobuz=q)
    r = check(a, tmp_path, 128)
    assert r.kind == "queued" and q.searches == [ISRC_Q, NAME_Q] and r.qobuz_searched


def test_upgrade_check_without_qobuz_leaves_out_its_search(tmp_path):
    q = FakeQobuz()
    a, _, _ = setup(AccountFallback(), used={"youtube": 30}, limits={"youtube": 30}, qobuz=q)
    r = check(a, tmp_path, 128, qobuz=False)
    assert r.kind == "queued" and q.searches == [] and not r.qobuz_searched


def test_a_qobuz_search_that_failed_or_did_not_run_is_not_noted(tmp_path):
    q = FakeQobuz(fail_search=True)
    a, _, _ = setup(AccountFallback(), used={"youtube": 30}, limits={"youtube": 30}, qobuz=q)
    assert not check(a, tmp_path, 128).qobuz_searched
    q2 = FakeQobuz()
    b, _, _ = setup(AccountFallback(), used={"youtube": 30}, limits={"youtube": 30}, qobuz=q2)
    b.budget.stopped = True  # paused by the auto-stop earlier in this run
    r = check(b, tmp_path, 128)
    assert r.kind == "queued" and q2.searches == [] and not r.qobuz_searched


def test_drm_protected_go_plus_streams_never_count_toward_giving_the_account_up(tmp_path):
    fb = AccountFallback([fc("s1", "soundcloud")], probe_error=RuntimeError("[soundcloud] 1: This video is DRM protected"))
    a, state, _ = setup(fb, limits={"soundcloud": 60})
    for i in range(GIVE_UP_AFTER + 1):
        (tmp_path / str(i)).mkdir()
        assert run(a, tmp_path / str(i)).kind == "ready"
    assert len(fb.probes) == GIVE_UP_AFTER + 1 and "soundcloud" not in a.given_up
    assert state["soundcloud_usage"]["signals"] == [] and a.accounts["soundcloud"].failures_in_a_row == 0
