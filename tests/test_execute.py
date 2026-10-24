from dataclasses import replace
from datetime import datetime, timedelta

import pytest

from discjockey.acquire import AcquireResult, Ready
from discjockey.align import Alignment
from discjockey.execute import Executor
from discjockey.library import Paths, empty_state, load_state
from discjockey.models import Action, SpotifyTrack
from discjockey.planner import ENTRY_KEYS
from discjockey.events import ActionFinished, ActionStarted, Cancelled, CancelToken, RunStarted, StepChanged
from discjockey.report import RunLog

NOW = datetime(2026, 10, 20, 12, 0, 0)


class FakeAcquirer:
    def __init__(self, *results):
        self.results = list(results)
        self.calls = []
        self.better = []
        self.originals = []
        self.qobuz = []
        self.declined = []

    def acquire(self, track, rejected, workdir, lossless_only, tracker, better_than=None, originals=True,
                declined=frozenset(), qobuz=True):
        self.calls.append((track.id, set(rejected), lossless_only))
        self.better.append(better_than)
        self.originals.append(originals)
        self.qobuz.append(qobuz)
        self.declined.append(set(declined))
        r = self.results.pop(0)
        if isinstance(r, BaseException):
            raise r
        return r(workdir) if callable(r) else r


def ready(status="lossless", source="qobuz", sid="q1"):
    def make(workdir):
        p = workdir / f"{source}_{sid}.aiff"
        p.write_bytes(b"new audio")
        cutoff = None if status == "lossless" else 16000
        return AcquireResult("ready", Ready(p, status, source, sid, "flac", cutoff, "comment"))
    return make


def act(kind, tid="t1aaaaaaa", folder="A", title="Song", **kw):
    t = SpotifyTrack(tid, title, ("Artist",), "Album", None, 180000, None)
    return Action(kind, tid, folder, t, (0, 0), **kw)


def entry(path, status="lossless", folder="A", **kw):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=180000, folder=folder, path=path,
             status=status, source="qobuz", source_id="q0", source_format="flac", rejected_sources=[],
             in_playlists=True, added="2026-10-01T10:00:00", last_attempt="2026-10-01",
             last_upgrade_check="2026-10-01")
    e.update(kw)
    return e


SHIFTED = Alignment("shifted", 1014, 22.993, 0.0, "lines up after shifting by 23 ms")
ALIGN_CALLS = []


@pytest.fixture
def env(tmp_path):
    ALIGN_CALLS.clear()
    paths = Paths(tmp_path, support=tmp_path / ".support")
    paths.library.mkdir()
    state = empty_state()

    def make(*results, limit=None, analyze=("pcm_s16le", None), alignment=SHIFTED):
        acq = FakeAcquirer(*results)
        ex = Executor(paths, state, RunLog(NOW), acq, lambda p: analyze, now=lambda: NOW, limit=limit)
        ex.align_files = lambda cur, new: ALIGN_CALLS.append((cur, new)) or alignment
        return ex, acq
    return paths, state, make


def touch(paths, rel, data=b"old audio"):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)


def test_new_lossless_track_is_placed(env):
    paths, state, make = env
    ex, _ = make(ready())
    ex.run([act("acquire", reason="new")])
    e = state["tracks"]["t1aaaaaaa"]
    assert e["path"] == "Library/A/Artist - Song.aiff" and e["status"] == "lossless"
    assert (paths.root / e["path"]).read_bytes() == b"new audio"
    assert state["pending"] == [] and load_state(paths.state_file) == state
    assert len(ex.log.section("new_lossless")) == 1
    assert not (paths.tmp / "t1aaaaaaa").exists()


def test_not_lossless_goes_to_subfolder(env):
    paths, state, make = env
    ex, _ = make(ready("not_lossless", "youtube_music", "y1"))
    ex.run([act("acquire", reason="new")])
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/A/not_lossless/Artist - Song.aiff"


def test_two_new_tracks_with_same_name_in_one_run(env):
    paths, state, make = env
    ex, _ = make(ready(sid="q1"), ready(sid="q2"))
    ex.run([act("acquire", tid="t1aaaaaaa", reason="new"), act("acquire", tid="t2bbbbbbb", reason="new")])
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/A/Artist - Song.aiff"
    assert state["tracks"]["t2bbbbbbb"]["path"] == "Library/A/Artist - Song [t2bbbb].aiff"


def test_untracked_file_with_other_case_is_not_overwritten(env):
    paths, state, make = env
    touch(paths, "Library/A/artist - song.aiff", b"user file")
    ex, _ = make(ready())
    ex.run([act("acquire", reason="new")])
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/A/Artist - Song [t1aaaa].aiff"
    assert (paths.root / "Library/A/artist - song.aiff").read_bytes() == b"user file"


def test_bought_file_replaces_not_lossless(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    touch(paths, "Library/A/Artist - Song.wav", b"bought")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless")
    ex, _ = make()
    ex.run([act("adopt_bought", src="Library/A/Artist - Song.wav")])
    e = state["tracks"]["t1aaaaaaa"]
    assert (e["path"], e["status"], e["source"]) == ("Library/A/Artist - Song.wav", "lossless", "manual")
    assert (paths.root / "Superseded/A/Artist - Song.aiff").exists()


def test_fake_bought_file_goes_to_not_lossless(env):
    paths, state, make = env
    touch(paths, "Library/A/Artist - Song.wav", b"bought")
    state["tracks"]["t1aaaaaaa"] = entry(None, status="missing", source=None, source_id=None)
    ex, _ = make(analyze=("pcm_s16le", 16000))
    ex.run([act("adopt_bought", src="Library/A/Artist - Song.wav")])
    e = state["tracks"]["t1aaaaaaa"]
    assert (e["path"], e["status"]) == ("Library/A/not_lossless/Artist - Song.wav", "fake_lossless")


def test_bought_file_next_to_a_file_the_user_keeps_elsewhere(env):
    paths, state, make = env
    touch(paths, "Library/Sets/2024/x.aiff")
    touch(paths, "Library/Sets/2024/Artist - Song.wav", b"bought")
    state["tracks"]["t1aaaaaaa"] = entry("Library/Sets/2024/x.aiff", status="not_lossless")
    ex, _ = make()
    ex.run([act("adopt_bought", src="Library/Sets/2024/Artist - Song.wav")])
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/Sets/2024/Artist - Song.wav"
    assert (paths.root / "Superseded/Sets/2024/x.aiff").exists()


def test_bought_file_in_the_placement_folder_joins_the_current_file(env):
    paths, state, make = env
    touch(paths, "Library/Sets/2024/x.aiff")
    touch(paths, "Library/A/Artist - Song.wav", b"bought")
    state["tracks"]["t1aaaaaaa"] = entry("Library/Sets/2024/x.aiff", status="not_lossless")
    ex, _ = make()
    ex.run([act("adopt_bought", src="Library/A/Artist - Song.wav")])
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/Sets/2024/Artist - Song.wav"
    assert (paths.root / "Library/Sets/2024/Artist - Song.wav").read_bytes() == b"bought"
    assert (paths.root / "Superseded/Sets/2024/x.aiff").exists()
    assert not (paths.root / "Library/A/Artist - Song.wav").exists()


def test_a_lossy_bought_file_stays_next_to_a_file_outside_a_playlist_folder(env):
    paths, state, make = env
    touch(paths, "Library/Sets/2024/Artist - Song.aiff")
    touch(paths, "Library/A/Artist - Song.aiff", b"bought")
    state["tracks"]["t1aaaaaaa"] = entry("Library/Sets/2024/Artist - Song.aiff", status="not_lossless")
    ex, _ = make(analyze=("pcm_s16le", 16000))
    ex.run([act("adopt_bought", src="Library/A/Artist - Song.aiff")])
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/Sets/2024/Artist - Song.aiff"  # the old one left the name
    assert (paths.root / "Library/Sets/2024/Artist - Song.aiff").read_bytes() == b"bought"
    assert (paths.root / "Superseded/Sets/2024/Artist - Song.aiff").exists()


def test_a_file_gone_is_downloaded_again_into_the_placement_folder(env):
    paths, state, make = env
    state["tracks"]["t1aaaaaaa"] = entry(None, status="missing", source=None, source_id=None, file_gone="2026-10-19")
    ex, _ = make(ready())
    ex.run([act("acquire", reason="redownload")])
    e = state["tracks"]["t1aaaaaaa"]
    assert (e["path"], e["file_gone"]) == ("Library/A/Artist - Song.aiff", None)
    assert len(ex.log.section("redownloaded")) == 1


def files_under(paths, *dirs):
    return sorted(p.relative_to(paths.root).as_posix() for d in dirs for p in (paths.root / d).rglob("*") if p.is_file())


def test_upgrade_parks_the_lossless_version(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="qobuz", source_id="q9")
    before = dict(state["tracks"]["t1aaaaaaa"])
    ex, acq = make(ready())
    ex.run([act("upgrade")])
    e = state["tracks"]["t1aaaaaaa"]
    assert (paths.root / "Upgrades ready/A/Artist - Song.aiff").read_bytes() == b"new audio"
    assert files_under(paths, "Library") == ["Library/A/not_lossless/Artist - Song.aiff"]
    assert (paths.root / "Library/A/not_lossless/Artist - Song.aiff").read_bytes() == b"old audio"
    assert not (paths.root / "Superseded").exists()
    assert {k: v for k, v in e.items() if k not in ("upgrade", "last_upgrade_check")} == {
        k: v for k, v in before.items() if k not in ("upgrade", "last_upgrade_check")}
    assert e["last_upgrade_check"] == "2026-10-20"
    assert e["upgrade"] == {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz", "source_id": "q1",
                            "source_format": "flac", "found": "2026-10-20", "alignment": SHIFTED.to_dict()}
    assert ALIGN_CALLS[0] == (paths.root / "Library/A/not_lossless/Artist - Song.aiff",
                              paths.tmp / "t1aaaaaaa" / "qobuz_q1.aiff")
    r = ex.log.section("upgrade_ready")[0]
    assert "lines up after shifting by 23 ms" in r.note and r.path == "Upgrades ready/A/Artist - Song.aiff"
    assert "qobuz:q9" in acq.calls[0][1] and acq.calls[0][2] is True
    assert load_state(paths.state_file) == state and state["pending"] == []


def test_an_upgrade_result_carries_the_found_files_status_a_lossless_soundcloud_original(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="soundcloud", source_id="sc0", source_kbps=128)
    ex, _ = make(ready(source="soundcloud", sid="sc1"))
    ex.run([act("upgrade")])
    r = ex.log.section("upgrade_ready")[0]
    assert r.source == "soundcloud" and r.found_status == "lossless"
    assert r.status == "not_lossless"  # still the current file's


def test_an_upgrade_of_a_file_kept_elsewhere_waits_in_its_mirror_folder(env):
    paths, state, make = env
    touch(paths, "Library/Sets/2024/x.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/Sets/2024/x.aiff", status="not_lossless", source_id="q9")
    ex, _ = make(ready())
    ex.run([act("upgrade")])
    assert state["tracks"]["t1aaaaaaa"]["upgrade"]["file"] == "Upgrades ready/Sets/2024/Artist - Song.aiff"
    assert (paths.root / "Upgrades ready/Sets/2024/Artist - Song.aiff").read_bytes() == b"new audio"


def test_parked_name_already_taken_gets_the_id_suffix(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    touch(paths, "Upgrades ready/A/Artist - Song.aiff", b"something the user put there")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless")
    ex, _ = make(ready())
    ex.run([act("upgrade")])
    assert state["tracks"]["t1aaaaaaa"]["upgrade"]["file"] == "Upgrades ready/A/Artist - Song [t1aaaa].aiff"
    assert (paths.root / "Upgrades ready/A/Artist - Song.aiff").read_bytes() == b"something the user put there"


def test_an_alignment_that_does_not_line_up_is_parked_too(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless")
    different = Alignment("different", text="doesn't line up: a swap would shift your cue points")
    ex, _ = make(ready(), alignment=different)
    ex.run([act("upgrade")])
    assert state["tracks"]["t1aaaaaaa"]["upgrade"]["alignment"]["result"] == "different"
    assert "doesn't line up" in ex.log.section("upgrade_ready")[0].note


PARKED = {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz", "source_id": "q5",
          "source_format": "flac", "found": "2026-10-10", "alignment": SHIFTED.to_dict()}


def test_redownload_makes_a_parked_upgrade_stale(env):
    paths, state, make = env
    touch(paths, "Upgrades ready/A/Artist - Song.aiff", b"parked")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         upgrade=dict(PARKED))  # the user deleted the current file
    ex, _ = make(ready())
    ex.run([act("acquire", reason="redownload")])
    assert state["tracks"]["t1aaaaaaa"]["upgrade"] is None
    assert not (paths.root / "Upgrades ready/A/Artist - Song.aiff").exists()


def test_bought_file_makes_a_parked_upgrade_stale(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    touch(paths, "Library/A/Artist - Song.wav", b"bought")
    touch(paths, "Upgrades ready/A/Artist - Song.aiff", b"parked")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         upgrade=dict(PARKED))
    ex, _ = make()
    ex.run([act("adopt_bought", src="Library/A/Artist - Song.wav")])
    assert state["tracks"]["t1aaaaaaa"]["upgrade"] is None
    assert not (paths.root / "Upgrades ready/A/Artist - Song.aiff").exists()


def test_upgrade_without_result_only_records_the_check(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/x.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/x.aiff", status="not_lossless")
    ex, _ = make(AcquireResult("missing", rejected=["qobuz:5"]))
    ex.run([act("upgrade")])
    e = state["tracks"]["t1aaaaaaa"]
    assert e["status"] == "not_lossless" and e["last_upgrade_check"] == "2026-10-20"
    assert "qobuz:5" in e["rejected_sources"]


def test_one_failing_action_does_not_stop_the_run(env):
    paths, state, make = env
    touch(paths, "Library/A/Artist - Song.wav", b"not audio")
    state["tracks"]["t1aaaaaaa"] = entry(None, status="missing", source=None, source_id=None)
    ex, _ = make(ready())

    def broken(path):
        raise RuntimeError("ffprobe found no audio")

    ex.analyze_file = broken
    ex.run([act("adopt_bought", src="Library/A/Artist - Song.wav"),
            act("acquire", tid="t2bbbbbbb", title="Other", reason="new")])
    assert "ffprobe found no audio" in ex.log.section("errors")[0].note
    assert state["tracks"]["t2bbbbbbb"]["status"] == "lossless"


def test_redownload_reuses_the_old_name(env):
    paths, state, make = env
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/Artist - Song.aiff")  # file was deleted
    ex, _ = make(ready())
    ex.run([act("acquire", reason="redownload")])
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/A/Artist - Song.aiff"


def test_rejected_source_kept_when_daily_limit_queues(env):
    paths, state, make = env
    state["tracks"]["t1aaaaaaa"] = entry(None, status="missing", source=None, source_id=None)
    ex, _ = make(AcquireResult("queued", rejected=["qobuz:7"]))
    ex.run([act("acquire", reason="retry")])
    assert state["tracks"]["t1aaaaaaa"]["rejected_sources"] == ["qobuz:7"]
    assert state["tracks"]["t1aaaaaaa"]["status"] == "missing"


def test_a_queued_upgrade_check_is_not_stamped_as_checked(env):
    # an account used up today: the check comes again tomorrow, not after WAIT_DAYS
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="youtube_music", source_kbps=129)
    ex, acq = make(AcquireResult("queued", note="daily YouTube Premium limit reached"))
    ex.run([act("upgrade")])
    assert acq.better == [129] and state["tracks"]["t1aaaaaaa"]["last_upgrade_check"] == "2026-10-01"
    assert ex.log.section("queued")[0].note == "daily YouTube Premium limit reached"


def test_a_queued_upgrade_check_does_not_search_the_originals_again_until_a_real_check(env):
    # the artists' originals were searched (anonymously) in the queued check: the next syncs only wait for the account
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="youtube_music", source_kbps=129)
    gate = {"url": "https://hypeddit.com/x", "host": "hypeddit.com", "direct": False}
    ex, acq = make(AcquireResult("queued", note="daily YouTube Premium limit reached", free_downloads=[gate]),
                   AcquireResult("queued", note="daily YouTube Premium limit reached"),
                   AcquireResult("missing"), AcquireResult("missing"))
    ex.run([act("upgrade")])
    e = state["tracks"]["t1aaaaaaa"]
    assert e["originals_searched"] == "2026-10-20" and e["last_upgrade_check"] == "2026-10-01"
    assert e["free_downloads"] == [gate]
    ex.run([act("upgrade")])  # queued again, without the search
    assert state["tracks"]["t1aaaaaaa"]["originals_searched"] == "2026-10-20"
    ex.run([act("upgrade")])  # the account is free again: the real check, still without the search
    assert state["tracks"]["t1aaaaaaa"]["last_upgrade_check"] == "2026-10-20"
    ex.run([act("upgrade")])  # a later check searches the originals again
    assert acq.originals == [True, False, False, True]


def test_a_queued_upgrade_check_does_not_search_qobuz_again_until_a_real_check(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="youtube_music", source_kbps=129)
    queued = AcquireResult("queued", note="daily YouTube Premium limit reached", qobuz_searched=True)
    ex, acq = make(queued, AcquireResult("queued", note="daily YouTube Premium limit reached"),
                   AcquireResult("missing"), AcquireResult("missing"))
    ex.run([act("upgrade")])  # a real check's search, noted because it waits for the account
    e = state["tracks"]["t1aaaaaaa"]
    assert e["qobuz_searched"] == "2026-10-20" and e["last_upgrade_check"] == "2026-10-01"
    ex.run([act("upgrade")])  # queued again, without Qobuz
    assert state["tracks"]["t1aaaaaaa"]["qobuz_searched"] == "2026-10-20"
    ex.run([act("upgrade")])  # the account is free again: the real check, still without Qobuz
    assert state["tracks"]["t1aaaaaaa"]["last_upgrade_check"] == "2026-10-20"
    ex.run([act("upgrade")])  # a later check searches Qobuz again
    assert acq.qobuz == [True, False, False, True]


def test_a_failed_qobuz_search_in_a_queued_check_is_searched_again(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="youtube_music", source_kbps=129)
    ex, acq = make(AcquireResult("queued", note="daily YouTube Premium limit reached"), AcquireResult("missing"))
    ex.run([act("upgrade")])
    assert state["tracks"]["t1aaaaaaa"].get("qobuz_searched") is None
    ex.run([act("upgrade")])
    assert acq.qobuz == [True, True]


@pytest.mark.parametrize("days, again", [(6, False), (7, True)])
def test_the_searches_of_a_queued_check_count_only_until_the_weekly_wait(env, days, again):
    # an account blocked for a week: Qobuz and the artists' originals are searched again once a week
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    day = (NOW - timedelta(days=days)).date().isoformat()
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="youtube_music", source_kbps=129, last_upgrade_check="2026-09-01",
                                         qobuz_searched=day, originals_searched=day)
    ex, acq = make(AcquireResult("queued", note="daily YouTube Premium limit reached"))
    ex.run([act("upgrade")])
    assert acq.qobuz == [again] and acq.originals == [again]


def test_limit_queues_the_rest(env):
    paths, state, make = env
    ex, acq = make(ready(), limit=1)
    ex.run([act("acquire", tid="t1aaaaaaa", reason="new"), act("acquire", tid="t2bbbbbbb", reason="new")])
    assert len(acq.calls) == 1 and "t2bbbbbbb" not in state["tracks"]
    assert len(ex.log.section("queued")) == 1


def test_queued_by_daily_limit_changes_nothing(env):
    paths, state, make = env
    ex, _ = make(AcquireResult("queued"))
    ex.run([act("acquire", reason="new")])
    assert state["tracks"] == {} and len(ex.log.section("queued")) == 1


def test_missing_new_track_recorded_with_buy_links(env):
    paths, state, make = env
    ex, _ = make(AcquireResult("missing"))
    ex.run([act("acquire", reason="new")])
    assert state["tracks"]["t1aaaaaaa"]["status"] == "missing"
    assert "beatport" in ex.log.section("missing")[0].note


def test_errored_new_track_not_recorded(env):
    paths, state, make = env
    ex, _ = make(AcquireResult("errored", errors=["network down"]))
    ex.run([act("acquire", reason="new")])
    assert state["tracks"] == {}
    assert "network down" in ex.log.section("errors")[0].note


def test_redownload_rejects_previous_fallback_source(env):
    paths, state, make = env
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/x.aiff", status="not_lossless",
                                         source="youtube", source_id="y1")
    ex, acq = make(AcquireResult("missing"))
    ex.run([act("acquire", reason="redownload")])
    assert "youtube:y1" in acq.calls[0][1]
    assert "youtube:y1" in state["tracks"]["t1aaaaaaa"]["rejected_sources"]


def test_keyboard_interrupt_keeps_finished_work(env):
    paths, state, make = env
    ex, _ = make(ready(), KeyboardInterrupt())
    with pytest.raises(KeyboardInterrupt):
        ex.run([act("acquire", tid="t1aaaaaaa", reason="new"), act("acquire", tid="t2bbbbbbb", reason="new")])
    on_disk = load_state(paths.state_file)
    assert "t1aaaaaaa" in on_disk["tracks"] and on_disk["pending"] == []


def test_events_tell_front_ends_what_happens(env):
    paths, state, make = env
    events = []
    ex, _ = make(ready())
    ex.emit = events.append
    ex.run([act("acquire", reason="new")])
    kinds = [type(e).__name__ for e in events]
    assert kinds == ["RunStarted", "ActionStarted", "ActionFinished"]
    assert events[0].total == 1 and events[1].index == 1
    r = events[2].result
    assert (r.section, r.status, r.source, r.path) == ("new_lossless", "lossless", "qobuz", "Library/A/Artist - Song.aiff")


def test_acquirer_gets_a_tracker_that_reports_steps(env):
    paths, state, make = env
    events = []

    class StepAcquirer:
        def acquire(self, track, rejected, workdir, lossless_only, tracker, better_than=None):
            tracker.step("download")
            return ready()(workdir)

    ex, _ = make()
    ex.acquirer, ex.emit = StepAcquirer(), events.append
    ex.run([act("acquire", reason="new")])
    steps = [e for e in events if isinstance(e, StepChanged)]
    assert steps[0].step == "download" and steps[0].track_id == "t1aaaaaaa"


def test_stop_flag_ends_the_run_between_actions(env):
    paths, state, make = env
    token = CancelToken()

    class StopAfterFirst:
        def acquire(self, track, rejected, workdir, lossless_only, tracker, better_than=None):
            token.cancel()  # e.g. the user pressed Stop while this track was downloading
            return ready()(workdir)

    ex, _ = make()
    ex.acquirer, ex.token = StopAfterFirst(), token
    with pytest.raises(Cancelled):
        ex.run([act("acquire", tid="t1aaaaaaa", reason="new"), act("acquire", tid="t2bbbbbbb", reason="new")])
    assert "t1aaaaaaa" in load_state(paths.state_file)["tracks"]
    assert "t2bbbbbbb" not in state["tracks"]


def test_stop_inside_a_download_discards_the_track_cleanly(env):
    paths, state, make = env
    token = CancelToken()

    class StoppedMidway:
        def acquire(self, track, rejected, workdir, lossless_only, tracker, better_than=None):
            (workdir / "partial.flac").write_bytes(b"half")
            token.cancel()
            tracker.progress(10, 100, "bytes")  # raises Cancelled, as the real download callbacks do
            raise AssertionError("not reached")

    ex, _ = make()
    ex.acquirer, ex.token = StoppedMidway(), token
    with pytest.raises(Cancelled):
        ex.run([act("acquire", reason="new")])
    assert state["tracks"] == {} and not (paths.tmp / "t1aaaaaaa").exists()


def test_queued_result_carries_the_reason(env):
    paths, state, make = env
    ex, _ = make(AcquireResult("queued", note="Qobuz paused after 3 failed downloads in a row"))
    ex.run([act("acquire", reason="new")])
    assert ex.log.section("queued")[0].note == "Qobuz paused after 3 failed downloads in a row"


def test_upgrade_check_without_result_is_reported(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/x.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/x.aiff", status="not_lossless")
    ex, _ = make(AcquireResult("missing"))
    ex.run([act("upgrade")])
    assert ex.log.section("checked")[0].status == "not_lossless"


def test_stop_while_comparing_leaves_the_check_for_next_time(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless")
    token = CancelToken()

    class StopAfterDownload:
        def acquire(self, track, rejected, workdir, lossless_only, tracker, better_than=None, originals=True,
                    declined=frozenset(), qobuz=True):
            token.cancel()  # the user pressed Stop while the lossless version was downloading
            return ready()(workdir)

    ex, _ = make()
    ex.acquirer, ex.token = StopAfterDownload(), token
    with pytest.raises(Cancelled):
        ex.run([act("upgrade")])
    e = state["tracks"]["t1aaaaaaa"]
    assert e.get("upgrade") is None and e["last_upgrade_check"] == "2026-10-01"
    assert not (paths.root / "Upgrades ready").exists() and not (paths.tmp / "t1aaaaaaa").exists()


@pytest.mark.parametrize("errors,kind", [
    (["Qobuz search by ISRC failed: Cannot connect to host www.qobuz.com:443"], "network"),
    (["Download from qobuz (1) failed: Qobuz only offers a 30-second preview of this track."], "qobuz"),
    (["Could not convert the youtube file: broken"], "other"),
])
def test_errors_carry_an_error_kind(env, errors, kind):
    paths, state, make = env
    ex, _ = make(AcquireResult("errored", errors=errors))
    ex.run([act("acquire", reason="new")])
    assert ex.log.section("errors")[0].error_kind == kind


def test_not_found_carries_an_error_kind(env):
    paths, state, make = env
    ex, _ = make(AcquireResult("missing"))
    ex.run([act("acquire", reason="new")])
    assert ex.log.section("missing")[0].error_kind == "not_found"


def test_an_unexpected_error_is_kind_other(env):
    paths, state, make = env
    ex, _ = make(RuntimeError("boom"))
    ex.run([act("acquire", reason="new")])
    r = ex.log.section("errors")[0]
    assert r.error_kind == "other" and "boom" in r.note


def test_run_started_lists_the_actions_in_order(env):
    paths, state, make = env
    events = []
    ex, _ = make(ready())
    ex.emit = events.append
    with_cover = act("acquire", tid="t2bbbbbbb", title="Other", reason="new")
    with_cover = replace(with_cover, track=replace(with_cover.track, image_url="https://i.scdn.co/image/x"))
    ex.run([act("acquire", reason="new"), with_cover])
    from discjockey.events import PlannedAction
    assert events[0].actions == (PlannedAction("acquire", "t1aaaaaaa", "Song", "Artist", None),
                                 PlannedAction("acquire", "t2bbbbbbb", "Other", "Artist", "https://i.scdn.co/image/x"))


def test_a_lossy_file_is_checked_for_a_better_stream_and_parked_with_its_bitrate(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="youtube_music", source_id="m0", source_kbps=129)

    def better(workdir):
        p = workdir / "youtube_music_m1.aiff"
        p.write_bytes(b"new audio")
        return AcquireResult("ready", Ready(p, "not_lossless", "youtube_music", "m1", "aac", 20000, "c", 256))

    ex, acq = make(better)
    ex.run([act("upgrade")])
    up = state["tracks"]["t1aaaaaaa"]["upgrade"]
    assert acq.better == [129]
    assert (up["status"], up["kbps"], up["cutoff_hz"], up["source"]) == ("not_lossless", 256, 20000, "youtube_music")


def test_a_stream_of_the_current_upload_that_came_out_no_better_is_declined_not_rejected(env):
    # rejected_sources means "wrong song": the version the user keeps must not show as marked wrong
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="not_lossless",
                                         source="youtube_music", source_id="m0", source_kbps=129)
    ex, acq = make(AcquireResult("missing", rejected=["youtube_music:m0", "youtube_music:m2"]), AcquireResult("missing"))
    ex.run([act("upgrade")])
    e = state["tracks"]["t1aaaaaaa"]
    assert e["rejected_sources"] == ["youtube_music:m2"] and e["declined_streams"] == ["youtube_music:m0"]
    assert load_state(paths.state_file)["tracks"]["t1aaaaaaa"]["declined_streams"] == ["youtube_music:m0"]
    e["last_upgrade_check"] = "2026-10-01"
    ex.run([act("upgrade")])  # the next check: the account step skips it, the rest of the check doesn't
    assert acq.declined == [set(), {"youtube_music:m0"}]
    assert "youtube_music:m0" not in acq.calls[1][1]


def test_lossless_and_qobuz_entries_ask_for_no_stream(env):
    paths, state, make = env
    touch(paths, "Library/A/not_lossless/Artist - Song.aiff")
    state["tracks"]["t1aaaaaaa"] = entry("Library/A/not_lossless/Artist - Song.aiff", status="fake_lossless",
                                         source="qobuz", source_id="q9")
    ex, acq = make(AcquireResult("missing"))
    ex.run([act("upgrade")])
    assert acq.better == [None]
