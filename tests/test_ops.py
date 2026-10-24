import json
import shutil
from datetime import date, datetime
from pathlib import Path

import pytest

from discjockey import ops
from discjockey.acquire import Ready
from discjockey.events import AccountUsage, Cancelled, CancelToken, Result, SourceChosen
from hub_helpers import records
from discjockey.library import Paths, empty_state, load_state, save_state
from discjockey.models import Candidate
from discjockey.ops import OpProblem
from discjockey.pacing import Budget
from discjockey.planner import ENTRY_KEYS
from discjockey.settings import Account, Settings

NOW = datetime(2026, 10, 20, 12, 0, 0)
LOSSY = "Library/A/not_lossless/Artist - Song.aiff"


def make_entry(path=LOSSY, status="not_lossless", **kw):
    e = dict.fromkeys(ENTRY_KEYS)
    e.update(aliases=[], artist="Artist", title="Song", duration_ms=180000, folder="A", path=path, status=status,
             source="youtube_music", source_id="y1", source_format="opus", cutoff_hz=16000, rejected_sources=[],
             in_playlists=True, added="2026-10-01T10:00:00", last_attempt="2026-10-01",
             last_upgrade_check="2026-10-10")
    if status == "missing":
        e.update(path=None, source=None, source_id=None, source_format=None, cutoff_hz=None)
    e.update(kw)
    return e


def touch(paths, rel, data=b"old audio"):
    f = paths.root / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_bytes(data)
    return f


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    p.data.mkdir()
    state = empty_state()
    state["tracks"]["t1aaaaaaa"] = make_entry()
    save_state(p, state)
    touch(p, LOSSY)
    return p


def shown(paths, tid="t1aaaaaaa"):
    """What the window showed: taken from the state as it was when the page asked."""
    return ops.snapshot(load_state(paths)["tracks"].get(tid))


def oplog(paths):
    f = paths.reports / "operations.jsonl"
    return [json.loads(line) for line in f.read_text().splitlines()] if f.exists() else []


def test_snapshot():
    e = make_entry(upgrade={"file": "Upgrades ready/A/x.aiff"})
    assert ops.snapshot(e) == {"status": "not_lossless", "path": LOSSY, "upgrade_file": "Upgrades ready/A/x.aiff"}
    assert ops.snapshot(None) is None


def test_hide_and_unhide(paths):
    done = ops.run_single(paths, "hide", "t1aaaaaaa", shown(paths),
                          lambda state: ops.set_hidden(paths, state, "t1aaaaaaa", True), now=lambda: NOW)
    assert done.result.section == "hidden" and done.recovered == []
    assert load_state(paths)["tracks"]["t1aaaaaaa"]["hidden"] is True
    assert "(hidden)" in paths.not_lossless_md.read_text()
    ops.run_single(paths, "unhide", "t1aaaaaaa", shown(paths),
                   lambda state: ops.set_hidden(paths, state, "t1aaaaaaa", False), now=lambda: NOW)
    assert load_state(paths)["tracks"]["t1aaaaaaa"]["hidden"] is False
    assert "(hidden)" not in paths.not_lossless_md.read_text()
    assert [(r["operation"], r["result"]) for r in oplog(paths)] == [("hide", "done"), ("unhide", "done")]
    assert oplog(paths)[0] == {"time": "2026-10-20T12:00:00", "track_id": "t1aaaaaaa", "artist": "Artist",
                               "title": "Song", "operation": "hide", "result": "done",
                               "message": "hidden from the to-do list"}


def test_refused_when_the_track_changed_in_the_meantime(paths):
    expect = shown(paths)
    state = load_state(paths)  # meanwhile the console placed a lossless file
    state["tracks"]["t1aaaaaaa"] = make_entry(path="Library/A/Artist - Song.aiff", status="lossless")
    save_state(paths, state)
    before = load_state(paths)
    called = []
    with pytest.raises(OpProblem) as excinfo:
        ops.run_single(paths, "hide", "t1aaaaaaa", expect, lambda s: called.append(1), now=lambda: NOW)
    assert excinfo.value.kind == "changed" and "changed in the meantime" in str(excinfo.value)
    assert called == [] and load_state(paths) == before
    assert oplog(paths)[-1]["result"] == "changed"


def test_unknown_track_is_refused(paths):
    with pytest.raises(OpProblem) as excinfo:
        ops.run_single(paths, "hide", "nope", {"status": "missing", "path": None, "upgrade_file": None},
                       lambda s: None, now=lambda: NOW)
    assert excinfo.value.kind == "changed"


def test_pending_steps_are_recovered_first(paths):
    src, dst = ".discjockey/.tmp/t2/x.aiff", "Library/B/Other - Two.aiff"
    touch(paths, src, b"placed")
    state = load_state(paths)
    state["pending"].append({"track_id": "t2", "renames": [[src, dst]],
                             "entry": make_entry(path=dst, status="lossless", title="Two", artist="Other")})
    save_state(paths, state)
    seen = {}

    def do(state):
        seen["pending"] = list(state["pending"])
        return ops.set_hidden(paths, state, "t1aaaaaaa", True)

    done = ops.run_single(paths, "hide", "t1aaaaaaa", shown(paths), do, now=lambda: NOW)
    assert seen["pending"] == [] and (paths.root / dst).read_bytes() == b"placed"
    assert done.recovered and done.recovered[0][1] is True and "Two" in done.recovered[0][0]
    assert load_state(paths)["tracks"]["t2"]["path"] == dst


def test_an_unexpected_error_is_logged_and_passed_on(paths):
    def boom(state):
        raise OSError("disk full")

    with pytest.raises(OSError):
        ops.run_single(paths, "hide", "t1aaaaaaa", shown(paths), boom, now=lambda: NOW)
    assert oplog(paths)[-1]["result"] == "failed" and "disk full" in oplog(paths)[-1]["message"]
    assert paths.not_lossless_md.exists()  # rewritten whatever happened


def test_a_refusal_from_the_operation_is_logged(paths):
    def refuse(state):
        raise OpProblem("Not possible.")

    with pytest.raises(OpProblem):
        ops.run_single(paths, "hide", "t1aaaaaaa", shown(paths), refuse, now=lambda: NOW)
    assert oplog(paths)[-1]["result"] == "refused" and oplog(paths)[-1]["message"] == "Not possible."


def test_the_result_is_a_result(paths):
    done = ops.run_single(paths, "hide", "t1aaaaaaa", shown(paths),
                          lambda state: ops.set_hidden(paths, state, "t1aaaaaaa", True), now=lambda: NOW)
    assert isinstance(done.result, Result) and done.result.track_id == "t1aaaaaaa"


# --- a bought file dropped into the window ---

def bought(tmp_path, name="My Purchase.wav", data=b"RIFF bought audio"):
    downloads = tmp_path / "Downloads"
    downloads.mkdir(exist_ok=True)
    f = downloads / name
    f.write_bytes(data)
    return f


def add(paths, src, analyze=lambda p: ("pcm_s16le", None), tid="t1aaaaaaa"):
    state = load_state(paths)
    return ops.add_bought_file(paths, state, tid, src, analyze=analyze, now=lambda: NOW), state


def test_bought_wav_is_filed_under_the_expected_name(paths, tmp_path):
    src = bought(tmp_path)
    before = (src.read_bytes(), src.stat().st_mtime_ns)
    result, state = add(paths, src)
    e = state["tracks"]["t1aaaaaaa"]
    assert result.section == "bought"
    assert e["path"] == "Library/A/Artist - Song.wav" and e["status"] == "lossless" and e["source"] == "manual"
    assert (paths.root / e["path"]).read_bytes() == b"RIFF bought audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"  # the lossy one, kept
    assert (src.read_bytes(), src.stat().st_mtime_ns) == before  # the user's own file is only read
    assert records(load_state(paths)) == records(state) and state["pending"] == []
    assert not (paths.tmp / "t1aaaaaaa").exists()


def test_bought_file_for_a_missing_track(paths, tmp_path):
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"] = make_entry(status="missing")
    save_state(paths, state)
    result, state = add(paths, bought(tmp_path, "x.aif"))
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/A/Artist - Song.aif"
    assert not (paths.root / "Superseded").exists()


def test_bought_fake_lossless_goes_to_not_lossless(paths, tmp_path):
    result, state = add(paths, bought(tmp_path), analyze=lambda p: ("pcm_s16le", 16000))
    e = state["tracks"]["t1aaaaaaa"]
    assert e["status"] == "fake_lossless" and e["path"] == "Library/A/not_lossless/Artist - Song.wav"


def test_bought_file_never_overwrites(paths, tmp_path):
    touch(paths, "Library/A/artist - song.wav", b"someone else's file")
    before = load_state(paths)
    with pytest.raises(OpProblem, match="already taken"):
        add(paths, bought(tmp_path))
    assert (paths.root / "Library/A/artist - song.wav").read_bytes() == b"someone else's file"
    assert (paths.root / LOSSY).read_bytes() == b"old audio" and load_state(paths) == before


def test_bought_file_never_overwrites_a_file_that_appears_meanwhile(paths, tmp_path):
    def analyze(p):  # while Discjockey checks the copy, a file with the same name lands in the folder
        touch(paths, "Library/A/Artist - Song.wav", b"appeared")
        return "pcm_s16le", None

    with pytest.raises(OpProblem, match="already taken"):
        add(paths, bought(tmp_path), analyze=analyze)
    assert (paths.root / "Library/A/Artist - Song.wav").read_bytes() == b"appeared"
    state = load_state(paths)
    assert state["pending"] == [] and state["tracks"]["t1aaaaaaa"]["path"] == LOSSY
    assert not (paths.tmp / "t1aaaaaaa").exists()


@pytest.mark.parametrize("name", ["x.m4a", "x.opus", "x"])
def test_only_wav_aiff_flac_or_mp3(paths, tmp_path, name):
    with pytest.raises(OpProblem, match="WAV, AIFF, FLAC or MP3"):
        add(paths, bought(tmp_path, name))


def test_a_file_macos_does_not_let_us_read(paths, tmp_path):
    src = bought(tmp_path)
    src.chmod(0)
    try:
        with pytest.raises(OpProblem, match="macOS didn't let Discjockey read this file"):
            add(paths, src)
    finally:
        src.chmod(0o644)


def test_a_file_without_audio_is_refused_before_anything_is_placed(paths, tmp_path):
    def analyze(p):
        raise RuntimeError("ffprobe found no audio in bought.wav")

    with pytest.raises(OpProblem, match="no audio"):
        add(paths, bought(tmp_path), analyze=analyze)
    assert not (paths.root / "Library/A/Artist - Song.wav").exists()
    assert (paths.root / LOSSY).exists()


def test_a_lossless_track_takes_no_bought_file(paths, tmp_path):
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"] = make_entry(path="Library/A/Artist - Song.aiff", status="lossless")
    save_state(paths, state)
    with pytest.raises(OpProblem, match="lossless already"):
        add(paths, bought(tmp_path))


def test_a_bought_file_makes_a_parked_upgrade_stale(paths, tmp_path):
    touch(paths, "Upgrades ready/A/Artist - Song.aiff", b"parked")
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"]["upgrade"] = {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz",
                                               "source_id": "q1", "source_format": "flac", "found": "2026-10-10",
                                               "alignment": {"result": "exact"}}
    save_state(paths, state)
    result, state = add(paths, bought(tmp_path))
    assert state["tracks"]["t1aaaaaaa"]["upgrade"] is None
    assert not (paths.root / "Upgrades ready/A/Artist - Song.aiff").exists()


needs_ffmpeg = pytest.mark.skipif(__import__("shutil").which("ffmpeg") is None, reason="ffmpeg not installed")


@needs_ffmpeg
def test_bought_flac_is_converted_to_aiff_with_its_tags(paths, tmp_path):
    import subprocess

    from mutagen.aiff import AIFF

    from discjockey import quality
    src = tmp_path / "Downloads" / "bought.flac"
    src.parent.mkdir()
    subprocess.run(["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "anoisesrc=d=5:c=white:r=44100:a=0.3",
                    "-metadata", "title=Song (Extended)", "-metadata", "artist=Artist", "-metadata", "album=EP",
                    "-c:a", "flac", str(src)], check=True)
    result, state = add(paths, src, analyze=quality.inspect)
    e = state["tracks"]["t1aaaaaaa"]
    assert e["path"] == "Library/A/Artist - Song.aiff" and e["status"] == "lossless"
    assert e["source_format"].startswith("pcm_")
    tags = AIFF(str(paths.root / e["path"])).tags
    assert str(tags["TIT2"]) == "Song (Extended)" and str(tags["TPE1"]) == "Artist" and str(tags["TALB"]) == "EP"
    assert src.exists()


@needs_ffmpeg
def test_bought_mp3_stays_lossy_and_takes_the_old_files_name(paths, tmp_path):
    from mutagen.aiff import AIFF
    from mutagen.id3 import APIC, ID3, TALB

    from discjockey import quality
    src = tmp_path / "Downloads" / "Song [FREE DL].mp3"
    src.parent.mkdir()
    # a committed MP3 (1 s of white noise, LAME at 128 kbps, no ID3 tag): the app's own ffmpeg has no MP3 encoder (it
    # never makes MP3s), and CI runs the tests with that ffmpeg. Made with
    #   ffmpeg -f lavfi -i anoisesrc=d=1:c=white:r=44100:a=0.3 -ac 1 -c:a libmp3lame -b:a 128k -write_xing 1 -id3v2_version 0 noise-128k.mp3
    # (generated noise, no licence). The test gives its copy the ID3 tag an artist's download has.
    shutil.copyfile(Path(__file__).parent / "fixtures" / "noise-128k.mp3", src)
    cover = b"\xff\xd8\xff\xe0 tiny cover \xff\xd9"
    id3 = ID3()
    id3.add(TALB(encoding=3, text="Free EP"))
    id3.add(APIC(encoding=3, mime="image/jpeg", type=3, desc="", data=cover))
    id3.save(src)
    result, state = add(paths, src, analyze=quality.inspect)
    e = state["tracks"]["t1aaaaaaa"]
    assert e["path"] == LOSSY and e["status"] == "not_lossless" and e["source_format"] == "mp3"
    assert (paths.root / LOSSY).read_bytes()[:4] == b"FORM"  # AIFF now, in the old file's place
    assert [p.name for p in (paths.root / "Superseded/A").iterdir()] == ["Artist - Song.aiff"]
    tags = AIFF(str(paths.root / LOSSY)).tags
    assert str(tags["TIT2"]) == "Song" and str(tags["TALB"]) == "Free EP"  # the MP3's album
    assert [f.data for f in tags.getall("APIC")] == [cover]  # and its cover
    assert result.section == "bought" and src.exists()


def test_through_run_single(paths, tmp_path):
    src = bought(tmp_path)
    done = ops.run_single(paths, "add_bought_file", "t1aaaaaaa", shown(paths),
                          lambda state: ops.add_bought_file(paths, state, "t1aaaaaaa", src,
                                                            analyze=lambda p: ("pcm_s16le", None), now=lambda: NOW),
                          now=lambda: NOW)
    assert done.result.section == "bought" and oplog(paths)[-1]["result"] == "done"
    assert "Every track in your playlists is lossless." in paths.not_lossless_md.read_text()


# --- "Wrong song?": use another version, or none of these ---

class FakeSource:
    def __init__(self, fail=None, stop_with=None):
        self.fail, self.stop_with, self.downloads = fail, stop_with, []

    def download(self, cand, workdir, progress=None):
        if self.stop_with:
            self.stop_with.cancel()
            progress(1, 10)
        if self.fail:
            raise self.fail
        self.downloads.append(cand.key)
        p = workdir / f"{cand.source}_{cand.id}.dl"
        p.write_bytes(b"downloaded")
        return p


def fake_process(status="lossless", length_ok=True, kbps=None):
    def process(downloaded, track, cand, workdir, tracker):
        if not length_ok:
            return None
        out = workdir / f"{cand.source}_{cand.id}.aiff"
        out.write_bytes(b"new audio")
        fmt = "flac" if cand.source == "qobuz" else "opus"
        return Ready(out, status, cand.source, cand.id, fmt, None if status == "lossless" else 20000, "comment",
                     kbps)
    return process


def budget_for(state, used=0):
    state["qobuz_usage"]["days"] = {"2026-10-19": 60, "2026-10-20": used}
    return Budget(state, lambda: None, Settings(60), today=lambda: date(2026, 10, 20), now=lambda: NOW)


def use(paths, cand, source=None, process=None, used=0, events=None, token=None):
    state = load_state(paths)
    source = source or FakeSource()
    result = ops.use_candidate(paths, state, "t1aaaaaaa", cand, qobuz=source, fallback=source,
                               budget=budget_for(state, used), emit=(events if events is not None else []).append,
                               token=token, process=process or fake_process(), now=lambda: NOW)
    return result, state, source


QC = Candidate("qobuz", "q7", "Song", "Artist", 180.0)
YC = Candidate("youtube_music", "abc", "Song", "Artist - Topic", 180.0, url="https://music.youtube.com/watch?v=abc")


def test_use_a_qobuz_version(paths):
    events = []
    result, state, source = use(paths, QC, events=events)
    e = state["tracks"]["t1aaaaaaa"]
    assert result.section == "replaced" and source.downloads == ["qobuz:q7"]
    assert e["path"] == "Library/A/Artist - Song.aiff" and e["status"] == "lossless"
    assert (e["source"], e["source_id"], e["source_format"]) == ("qobuz", "q7", "flac")
    assert (paths.root / e["path"]).read_bytes() == b"new audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"  # never deleted
    assert "youtube_music:y1" in e["rejected_sources"]  # the wrong one is never used again
    assert e["last_attempt"] == "2026-10-20" and e["upgrade"] is None
    assert state["qobuz_usage"]["days"]["2026-10-20"] == 1  # counts toward today's limit
    assert SourceChosen("t1aaaaaaa", "qobuz", "chosen", "Song", 180.0) in events
    assert AccountUsage("qobuz", 1, 60) in events
    assert records(load_state(paths)) == records(state) and not (paths.tmp / "t1aaaaaaa").exists()


def test_use_a_lossy_version_with_the_same_name(paths):
    result, state, _ = use(paths, YC, process=fake_process("not_lossless"))
    e = state["tracks"]["t1aaaaaaa"]
    assert e["path"] == LOSSY and (paths.root / LOSSY).read_bytes() == b"new audio"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"
    assert state["qobuz_usage"]["days"]["2026-10-20"] == 0  # YouTube downloads don't count


@pytest.mark.parametrize("cand, status, kbps", [(YC, "not_lossless", 256), (QC, "lossless", None)])
def test_use_this_records_the_new_files_bitrate(paths, cand, status, kbps):
    # else the weekly upgrade check keeps asking for "better than 129 kbps" and fetches the same 256 kbps stream
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"]["source_kbps"] = 129
    save_state(paths, state)
    _, state, _ = use(paths, cand, process=fake_process(status, kbps=kbps))
    assert state["tracks"]["t1aaaaaaa"]["source_kbps"] == kbps


def test_the_current_version_cannot_be_chosen(paths):
    with pytest.raises(OpProblem, match="the version you have now"):
        use(paths, Candidate("youtube_music", "y1", "Song", "Artist", 180.0, url="https://x"))


def test_a_version_with_the_wrong_length_is_rejected_and_nothing_moves(paths):
    with pytest.raises(OpProblem, match="3 seconds") as excinfo:
        use(paths, YC, process=fake_process(length_ok=False))
    assert excinfo.value.kind == "refused"
    state = load_state(paths)
    assert "youtube_music:abc" in state["tracks"]["t1aaaaaaa"]["rejected_sources"]
    assert state["tracks"]["t1aaaaaaa"]["path"] == LOSSY and (paths.root / LOSSY).read_bytes() == b"old audio"


def test_daily_limit_reached(paths):
    with pytest.raises(OpProblem, match="limit") as excinfo:
        use(paths, QC, used=60)
    assert excinfo.value.kind == "refused"


def test_failed_qobuz_download_counts_toward_the_auto_stop(paths):
    state = load_state(paths)
    budget = budget_for(state)
    with pytest.raises(OpProblem, match="did not work") as excinfo:
        ops.use_candidate(paths, state, "t1aaaaaaa", QC, qobuz=FakeSource(RuntimeError("timeout")), fallback=None,
                          budget=budget, process=fake_process(), now=lambda: NOW)
    assert excinfo.value.kind == "failed" and budget.failures_in_a_row == 1
    assert state["qobuz_usage"]["signals"][-1]["kind"] == "download_rejected"
    assert (paths.root / LOSSY).read_bytes() == b"old audio"


def test_stop_during_the_download_changes_nothing(paths):
    token = CancelToken()
    with pytest.raises(Cancelled):
        use(paths, YC, source=FakeSource(stop_with=token), token=token)
    state = load_state(paths)
    assert state["tracks"]["t1aaaaaaa"]["path"] == LOSSY and not (paths.tmp / "t1aaaaaaa").exists()


def test_using_a_version_makes_a_parked_upgrade_stale(paths):
    touch(paths, "Upgrades ready/A/Artist - Song.aiff", b"parked")
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"]["upgrade"] = {"file": "Upgrades ready/A/Artist - Song.aiff", "source": "qobuz",
                                               "source_id": "q1", "source_format": "flac", "found": "2026-10-10",
                                               "alignment": {"result": "exact"}}
    save_state(paths, state)
    use(paths, YC, process=fake_process("not_lossless"))
    assert not (paths.root / "Upgrades ready/A/Artist - Song.aiff").exists()


def test_a_version_chosen_after_it_was_rejected_is_no_longer_rejected(paths):
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"]["rejected_sources"] = ["youtube_music:abc"]
    save_state(paths, state)
    result, state, _ = use(paths, YC, process=fake_process("not_lossless"))
    assert state["tracks"]["t1aaaaaaa"]["rejected_sources"] == ["youtube_music:y1"]


def test_none_of_these(paths):
    state = load_state(paths)
    result = ops.reject_current(paths, state, "t1aaaaaaa")
    e = state["tracks"]["t1aaaaaaa"]
    assert result.section == "rejected"
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"
    assert not (paths.root / LOSSY).exists()
    assert e["status"] == "missing" and e["path"] is None and e["source"] is None and e["last_attempt"] is None
    assert e["rejected_sources"] == ["youtube_music:y1"]
    assert records(load_state(paths)) == records(state)


def test_none_of_these_forgets_the_old_files_bitrate(paths):
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"]["source_kbps"] = 129
    ops.reject_current(paths, state, "t1aaaaaaa")
    assert state["tracks"]["t1aaaaaaa"]["source_kbps"] is None


def test_none_of_these_then_the_next_sync_searches_again_without_it(paths):
    from discjockey.models import FetchedPlaylist, PlaylistLine
    from discjockey.planner import plan
    state = load_state(paths)
    ops.reject_current(paths, state, "t1aaaaaaa")
    fetched = [FetchedPlaylist(PlaylistLine("A", "pl", 1), [ops.track_of("t1aaaaaaa", state["tracks"]["t1aaaaaaa"])],
                               [])]
    p = plan(fetched, state, [], date(2026, 10, 20))
    assert [(a.kind, a.reason) for a in p.actions] == [("acquire", "retry")]


def test_none_of_these_needs_the_file(paths):
    (paths.root / LOSSY).unlink()
    with pytest.raises(OpProblem, match="not where Discjockey expects it"):
        ops.reject_current(paths, load_state(paths), "t1aaaaaaa")


def test_a_crash_between_the_two_steps_leaves_a_track_the_next_sync_searches_again(paths, monkeypatch):
    real = ops.run_op
    calls = []

    def crash_on_second(*args, **kw):
        calls.append(args[3])
        if len(calls) == 2:
            raise KeyboardInterrupt  # the power goes off before the new file is placed
        return real(*args, **kw)

    monkeypatch.setattr(ops, "run_op", crash_on_second)
    with pytest.raises(KeyboardInterrupt):
        use(paths, YC, process=fake_process("not_lossless"))
    e = load_state(paths)["tracks"]["t1aaaaaaa"]
    assert e["status"] == "missing" and e["path"] is None and e["rejected_sources"] == ["youtube_music:y1"]
    assert (paths.root / "Superseded/A/Artist - Song.aiff").read_bytes() == b"old audio"
    assert load_state(paths)["pending"] == []


def test_a_different_recording_at_the_path_asks_for_a_rekordbox_check(paths):
    result, state, _ = use(paths, YC, process=fake_process("not_lossless"))
    assert state["tracks"]["t1aaaaaaa"]["rekordbox_check"] == {"reason": "wrong_song", "since": "2026-10-20"}


def test_a_first_file_for_a_missing_track_needs_no_rekordbox_check(paths):
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"] = make_entry(status="missing")
    save_state(paths, state)
    result, state, _ = use(paths, YC, process=fake_process("not_lossless"))
    assert state["tracks"]["t1aaaaaaa"].get("rekordbox_check") is None


def test_none_of_these_asks_for_a_rekordbox_check(paths):
    state = load_state(paths)
    ops.reject_current(paths, state, "t1aaaaaaa", now=lambda: NOW)
    e = state["tracks"]["t1aaaaaaa"]
    assert e["rekordbox_check"] == {"reason": "wrong_song", "since": "2026-10-20"}
    assert records(load_state(paths)) == records(state)


def test_rekordbox_checked_clears_the_reminder(paths):
    state = load_state(paths)
    state["tracks"]["t1aaaaaaa"]["rekordbox_check"] = {"reason": "added_as_new", "since": "2026-10-19"}
    save_state(paths, state)
    result = ops.rekordbox_checked(paths, state, "t1aaaaaaa")
    assert result.section == "rekordbox_checked" and state["tracks"]["t1aaaaaaa"]["rekordbox_check"] is None
    assert records(load_state(paths)) == records(state)


def test_a_fourth_replacement_still_finds_a_superseded_name(paths):
    for name in ("Artist - Song", "Artist - Song [t1aaaa]", "Artist - Song [t1aaaaaaa]"):
        touch(paths, f"Superseded/A/{name}.aiff", b"an earlier wrong song")
    result, state, _ = use(paths, YC, process=fake_process("not_lossless"))
    assert (paths.root / "Superseded/A/Artist - Song (2).aiff").read_bytes() == b"old audio"


def test_the_superseded_name_is_chosen_before_anything_is_downloaded(paths, monkeypatch):
    real = ops.NameReserver.choose

    def no_name(self, dest_dir, *args):
        if dest_dir.startswith("Superseded/"):
            raise FileExistsError("no free file name")
        return real(self, dest_dir, *args)

    monkeypatch.setattr(ops.NameReserver, "choose", no_name)
    source = FakeSource()
    with pytest.raises(FileExistsError):
        use(paths, QC, source=source)
    state = load_state(paths)
    assert source.downloads == [] and state["qobuz_usage"]["days"].get("2026-10-20", 0) == 0


def test_qobuz_versions_are_refused_while_qobuz_is_paused(paths):
    state = load_state(paths)
    budget = budget_for(state)
    budget.stopped = True
    source = FakeSource()
    with pytest.raises(OpProblem, match="Qobuz is paused"):
        ops.use_candidate(paths, state, "t1aaaaaaa", QC, qobuz=source, fallback=source, budget=budget,
                          process=fake_process(), now=lambda: NOW)
    assert source.downloads == []


def test_use_this_needs_the_file_where_state_says(paths):
    (paths.root / LOSSY).unlink()  # moved or renamed in Finder
    source = FakeSource()
    with pytest.raises(OpProblem, match="not where Discjockey expects it"):
        use(paths, YC, source=source)
    assert source.downloads == []
    assert load_state(paths)["tracks"]["t1aaaaaaa"]["path"] == LOSSY


class AccountSource(FakeSource):
    """Lists formats through the login (`kbps`, or `probe_error`) and downloads with or without it."""
    kbps, probe_error = 256, None

    def stream_kbps(self, source, source_id, account=False):
        self.probes = getattr(self, "probes", []) + [(f"{source}:{source_id}", account)]
        if self.probe_error:
            raise self.probe_error
        return self.kbps

    def download(self, cand, workdir, progress=None, account=False):
        if self.fail:
            raise self.fail
        self.downloads.append(("account:" if account else "") + cand.key)
        p = workdir / f"{cand.source}_{cand.id}.dl"
        p.write_bytes(b"downloaded")
        return p


def youtube_budget(state, used=0):
    state["youtube_usage"] = {"days": {"2026-10-19": 30, "2026-10-20": used}, "signals": []}
    return Budget(state, lambda: None, Settings(accounts={"youtube": Account("chrome", 30)}),
                  today=lambda: date(2026, 10, 20), now=lambda: NOW, service="youtube")


def use_with_account(paths, used, kbps=256, probe_error=None):
    state = load_state(paths)
    source, events = AccountSource(), []
    source.kbps, source.probe_error = kbps, probe_error
    yt = youtube_budget(state, used)
    ops.use_candidate(paths, state, "t1aaaaaaa", YC, qobuz=None, fallback=source, budget=budget_for(state),
                      accounts={"youtube": yt}, emit=events.append, process=fake_process("not_lossless"),
                      now=lambda: NOW)
    return source, state, events


def test_use_this_downloads_through_the_account_and_counts(paths):
    source, state, events = use_with_account(paths, used=0)
    assert source.probes == [("youtube_music:abc", True)]  # the formats are listed first, like in a run
    assert source.downloads == ["account:youtube_music:abc"]
    assert state["youtube_usage"]["days"]["2026-10-20"] == 1
    assert AccountUsage("youtube", 1, 30) in events


def test_use_this_without_a_premium_stream_downloads_free_and_spends_no_account_download(paths):
    source, state, events = use_with_account(paths, used=0, kbps=129)
    assert source.probes == [("youtube_music:abc", True)] and source.downloads == ["youtube_music:abc"]
    assert state["youtube_usage"]["days"]["2026-10-20"] == 0
    assert not any(isinstance(e, AccountUsage) for e in events)
    assert state["youtube_usage"]["signals"][-1]["kind"] == "premium_missing"  # as in a run (spec §4)
    assert load_state(paths)["tracks"]["t1aaaaaaa"]["source"] == "youtube_music"


def test_use_this_with_a_failed_listing_downloads_free_and_notes_the_warning_sign(paths):
    source, state, _ = use_with_account(paths, used=0, probe_error=RuntimeError("HTTP Error 429: Too Many Requests"))
    assert source.downloads == ["youtube_music:abc"]
    assert state["youtube_usage"]["signals"][-1]["kind"] == "rate_limited"
    assert state["youtube_usage"]["days"]["2026-10-20"] == 0


def test_use_this_lists_nothing_when_the_account_is_used_up(paths):
    source, _, _ = use_with_account(paths, used=30)
    assert getattr(source, "probes", []) == []


def test_use_this_keeps_only_the_first_200_characters_of_an_account_error(paths):
    state = load_state(paths)
    error = "ERROR: HTTP Error 403: Forbidden " + "x" * 400 + "\nTraceback (most recent call last): ..."
    source = AccountSource(fail=RuntimeError(error))
    yt = youtube_budget(state)
    with pytest.raises(OpProblem):
        ops.use_candidate(paths, state, "t1aaaaaaa", YC, qobuz=None, fallback=source, budget=budget_for(state),
                          accounts={"youtube": yt}, process=fake_process("not_lossless"), now=lambda: NOW)
    signal = state["youtube_usage"]["signals"][-1]
    who = f"{state['tracks']['t1aaaaaaa']['artist']} - {state['tracks']['t1aaaaaaa']['title']}"
    assert signal["kind"] == "refused" and signal["message"] == f"{who}: {error[:200]}"


def test_use_this_downloads_free_when_the_account_is_used_up(paths):
    source, state, _ = use_with_account(paths, used=30)
    assert source.downloads == ["youtube_music:abc"]
    assert state["youtube_usage"]["days"]["2026-10-20"] == 30


def test_a_bought_file_lands_next_to_a_file_kept_elsewhere(paths, tmp_path):
    state = empty_state()  # option A (spec §7): the user keeps this one outside its playlist folder
    state["tracks"]["t1aaaaaaa"] = make_entry(path="Library/Sets/2024/x.aiff")
    touch(paths, "Library/Sets/2024/x.aiff")
    result = ops.add_bought_file(paths, state, "t1aaaaaaa", bought(tmp_path), analyze=lambda p: ("pcm_s16le", None),
                                 now=lambda: NOW)
    assert result.section == "bought"
    assert state["tracks"]["t1aaaaaaa"]["path"] == "Library/Sets/2024/Artist - Song.wav"
    assert (paths.root / "Superseded/Sets/2024/x.aiff").read_bytes() == b"old audio"
    assert not (paths.root / "Library/A/Artist - Song.wav").exists()


def test_a_version_used_lands_next_to_a_file_kept_elsewhere(paths):
    state = empty_state()
    state["tracks"]["t1aaaaaaa"] = make_entry(path="Library/Sets/2024/x.aiff")
    touch(paths, "Library/Sets/2024/x.aiff")
    result = ops.use_candidate(paths, state, "t1aaaaaaa", QC, qobuz=FakeSource(), fallback=FakeSource(),
                               budget=budget_for(state), process=fake_process(), now=lambda: NOW)
    assert result.path == state["tracks"]["t1aaaaaaa"]["path"] == "Library/Sets/2024/Artist - Song.aiff"
    assert (paths.root / "Library/Sets/2024/Artist - Song.aiff").read_bytes() == b"new audio"
    assert (paths.root / "Superseded/Sets/2024/x.aiff").read_bytes() == b"old audio"
