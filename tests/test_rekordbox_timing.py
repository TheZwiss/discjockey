"""Where rekordbox's timeline sits for a file (discjockey/rekordbox/timing.py, probe.py, offset.py): the pure
measurement and its snapping, every branch of `timeline_offset` with a stubbed decode, and the ffmpeg side on a test
M4A and the two MP3 fixtures (tests/fixtures/clicks-*.mp3, made as rekordbox_helpers says)."""
from __future__ import annotations

import shutil
import subprocess
from contextlib import contextmanager
from pathlib import Path

import numpy as np
import pytest
import sqlcipher3

from discjockey import quality
from discjockey.quality import AudioInfo
from discjockey.rekordbox import locate, master, process, timing
from discjockey.rekordbox import offset as offset_module
from discjockey.rekordbox.offset import RATE, timeline_offset
from discjockey.rekordbox.probe import start_trim
from discjockey.rekordbox.timing import Decided, Measured, agree, decide, expected, measure
from rekordbox_helpers import clicks, make_anlz, make_master, pqtz_tag, pwv3_from, pwv3_tag, write_wav

FIXTURES = Path(__file__).parent / "fixtures"
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
SR = 44100
AUDIO = clicks(20, SR)


# --- pure: measure, expected, decide, agree ---

@pytest.mark.parametrize("sr, extra", [(44100, 0), (44100, 1105), (44100, 2257), (44100, -900),
                                       (48000, 1024), (32000, 700)])
def test_a_synthetic_shift_is_recovered_and_snapped(sr, extra):
    audio = AUDIO if sr == SR else clicks(20, sr)
    got = measure(pwv3_from(audio, sr, extra / sr), audio, sr)
    assert got.score >= timing.MIN_SCORE
    assert abs(got.offset_s * sr - extra) <= 5
    assert decide(got, [0.0, extra / sr, (extra + 1152) / sr]) == Decided(extra / sr, None)


def test_a_waveform_of_other_audio_scores_low_and_is_timing():
    other = pwv3_from(clicks(20, SR, bpm=97, seed=9), SR, 0, seed=3)
    got = measure(other, AUDIO, SR)
    assert got.score < timing.MIN_SCORE
    assert decide(got, [0.0]) == Decided(None, "timing")


def test_a_flat_waveform_or_too_little_overlap():
    assert decide(measure(np.full(3000, 7, np.uint8), AUDIO, SR), [0.0]).reason == "timing"
    assert measure(pwv3_from(AUDIO, SR, 0)[:150], AUDIO, SR) is None
    assert measure(pwv3_from(AUDIO, SR, 0), AUDIO[:SR], SR) is None
    assert measure(pwv3_from(AUDIO, SR, 0), np.zeros(0, np.float32), SR) is None


def test_decide_snaps_within_a_quarter_millisecond_only():
    assert decide(Measured(0.0251, 0.95), [0.0, 0.025]) == Decided(0.025, None)
    assert decide(Measured(0.02526, 0.95), [0.0, 0.025]) == Decided(None, "timing")
    assert decide(Measured(0.025, 0.89), [0.0, 0.025]) == Decided(None, "timing")


def test_a_measurement_between_the_two_closest_mp3_values_snaps_to_neither():
    values = expected("mp3", SR, 0)  # no tag: 0, 1105, 1152, 2257 samples
    between = (1105 + 1152) / 2 / SR  # 1128.5 samples: 0.54 ms from each, more than the 0.25 ms tolerance
    assert decide(Measured(between, 0.95), values) == Decided(None, "timing")
    assert decide(Measured(1105 / SR, 0.95), values) == Decided(1105 / SR, None)
    assert decide(Measured(1152 / SR, 0.95), values) == Decided(1152 / SR, None)


def test_tracks_must_agree():
    assert agree([0.025, 0.025]) == Decided(0.025, None)
    assert agree([0.025, 0.051]) == Decided(None, "timing")
    assert agree([]) == Decided(0.0, None)


def test_expected_values_by_format():
    def samples(codec, trim, sr=SR):
        return [round(v * sr) for v in expected(codec, sr, trim)]
    for codec in ("pcm_s16be", "pcm_s24le", "pcm_f32le", "flac", "alac"):
        assert samples(codec, 500) == [0]
    assert samples("mp3", 1105) == [0, 1105, 2257]
    assert samples("mp3", 0) == [0, 1105, 1152, 2257]  # no tag: 0, or a delay the header didn't show
    assert samples("mp3", 1000, 48000) == [0, 1000, 1105, 2152, 2257]
    for codec in ("aac", "vorbis", "opus", "wmav2"):
        assert samples(codec, 1024) == [0, 1024]
    assert expected("aac", 48000, 1024) == [0.0, 1024 / 48000]


# --- timeline_offset, every branch (decode stubbed) ---

def info(codec="mp3", sr=SR):
    return lambda path: AudioInfo(codec, sr, 20.0)


def stubs(codec="mp3", trim=1105):
    return {"probe_audio": info(codec), "decode": lambda path: (AUDIO, SR), "trim": lambda path, c: trim,
            "running": lambda: False}


def rekordbox(tmp_path, tracks):
    """A rekordbox library in `tmp_path/rb` with one row per `(path, cues, extra_samples | None, grid)`: an extra gives
    the track an analysis with a waveform shifted that much; None no analysis files at all."""
    rows = [{"ID": str(i + 1), "path": str(path), "cues": cues} for i, (path, cues, _, _) in enumerate(tracks)]
    folder = tmp_path / "rb"
    make_master(folder, rows)
    place = locate(env={"DISCJOCKEY_REKORDBOX": str(folder)})
    for i, (_, _, extra, grid) in enumerate(tracks):
        if extra is None:
            continue
        dat = place.share / f"PIONEER/USBANLZ/{i:03x}/{i + 1}/ANLZ0000.DAT"
        make_anlz(dat, [pqtz_tag(40 if grid else 0)])
        make_anlz(dat.with_suffix(".EXT"), [pwv3_tag(pwv3_from(AUDIO, SR, extra / SR))])
    return place


def test_no_rekordbox_is_zero(tmp_path):
    got = timeline_offset(tmp_path / "a.mp3", **stubs())  # conftest: an empty DISCJOCKEY_REKORDBOX
    assert (got.samples, got.why, got.rekordbox.state, got.entries) == (0, "no_rekordbox", "none", [])


def test_no_rekordbox_is_answered_before_the_file_is_probed(tmp_path):
    def broken(path):
        raise RuntimeError("ffprobe failed")
    got = timeline_offset(tmp_path / "a.mp3", **{**stubs(), "probe_audio": broken})
    assert (got.samples, got.why) == (0, "no_rekordbox")


def test_a_read_error_in_rekordbox_s_library_is_unreadable_not_a_crash(tmp_path, monkeypatch):
    f = tmp_path / "a.mp3"
    place = rekordbox(tmp_path, [(f, 2, 1105, True)])

    def damaged(self, path):
        raise sqlcipher3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(master.Master, "entries_for", damaged)
    got = timeline_offset(f, place=place, **stubs())
    assert (got.samples, got.why, got.entries) == (None, "unreadable", [])
    got = timeline_offset(f, place=place, **stubs("pcm_s16le"))
    assert (got.samples, got.why) == (0, "format")


def test_a_library_is_opened_once_for_one_answer(tmp_path, monkeypatch):
    f = tmp_path / "a.mp3"
    place = rekordbox(tmp_path, [(f, 2, 1105, True)])
    opens = []
    real = master.open_read

    def counting(place, running):
        opens.append(1)
        return real(place, running)
    monkeypatch.setattr(master, "open_read", counting)
    got = timeline_offset(f, place=place, **stubs())
    assert (got.why, got.rekordbox.state) == ("measured", "ready") and len(opens) == 1


@contextmanager
def view_of(place, running=False):
    """A batch's view of `place`: the open library, its index and its status (what Session.view() hands out)."""
    with master.open_read(place, running) as db:
        yield master.RekordboxView(db, db.index(), master.status_of(db, running))


@pytest.mark.parametrize("tracks, want", [
    ([("a.mp3", 3, 2257, True), ("a.mp3", 0, 2257, True)], (2257, "measured")),
    ([("a.mp3", 3, 1105, True), ("a.mp3", 2, 2257, True)], (None, "timing")),
    ([("a.mp3", 2, None, False)], (None, "not_analysed")),
    ([("a.mp3", 0, None, False)], (0, "no_cues")),
    ([("other.mp3", 2, None, False)], (0, "not_in_rekordbox")),
])
def test_a_view_gives_the_answer_of_the_own_open_and_opens_nothing(tmp_path, monkeypatch, tracks, want):
    f = tmp_path / "a.mp3"
    place = rekordbox(tmp_path, [(tmp_path / name, *rest) for name, *rest in tracks])
    own = timeline_offset(f, place=place, **stubs())
    assert (own.samples, own.why) == want
    forbidden = pytest.fail  # nothing may be located, asked or opened while the view answers
    with view_of(place) as view:
        monkeypatch.setattr(master, "open_read", forbidden)
        monkeypatch.setattr(process, "running", forbidden)
        monkeypatch.setattr(offset_module, "locate", forbidden)
        with_view = timeline_offset(f, view=view, **{**stubs(), "running": forbidden})
    assert with_view == own


def test_a_view_whose_read_fails_is_unreadable_like_the_own_open(tmp_path, monkeypatch):
    f = tmp_path / "a.mp3"
    place = rekordbox(tmp_path, [(f, 1, 1105, True)])

    def damaged(self, path, index=None):
        raise sqlcipher3.DatabaseError("database disk image is malformed")
    monkeypatch.setattr(master.Master, "entries_for", damaged)
    with view_of(place) as view:
        got = timeline_offset(f, view=view, **stubs())
        assert (got.samples, got.why, got.entries, got.rekordbox) == (None, "unreadable", [], view.status)
        assert timeline_offset(f, view=view, **stubs("pcm_s16le")).samples == 0


def test_a_file_no_track_holds_is_zero(tmp_path):
    place = rekordbox(tmp_path, [(tmp_path / "other.mp3", 2, None, False)])
    got = timeline_offset(tmp_path / "a.mp3", place=place, **stubs())
    assert (got.samples, got.why, got.rekordbox.state) == (0, "not_in_rekordbox", "ready")


def test_measured_tracks_snap_and_agree(tmp_path):
    f = tmp_path / "a.mp3"
    place = rekordbox(tmp_path, [(f, 3, 2257, True), (f, 0, 2257, True)])
    got = timeline_offset(f, place=place, **stubs())
    assert (got.samples, got.why) == (2257, "measured")
    first = got.entries[0]
    assert (first.cues, first.grid, first.pwv3, first.expected_ms) == (3, True, True, 2257 / SR * 1000)
    assert abs(first.offset_ms - first.expected_ms) < 0.12 and first.score >= 0.9


def test_two_tracks_that_disagree_are_timing(tmp_path):
    f = tmp_path / "a.mp3"
    got = timeline_offset(f, place=rekordbox(tmp_path, [(f, 3, 1105, True), (f, 2, 2257, True)]), **stubs())
    assert (got.samples, got.why) == (None, "timing")


def test_a_measurement_off_the_expected_values_is_timing(tmp_path):
    f = tmp_path / "a.mp3"
    got = timeline_offset(f, place=rekordbox(tmp_path, [(f, 3, 1600, True)]), **stubs())
    assert (got.samples, got.why) == (None, "timing")
    assert abs(got.entries[0].offset_ms - 1600 / SR * 1000) < 0.12 and got.entries[0].expected_ms is None


def test_a_48k_value_becomes_44k1_samples(tmp_path):
    f = tmp_path / "a.m4a"
    place = rekordbox(tmp_path, [(f, 1, None, False)])
    audio = clicks(20, 48000)
    dat = place.share / "PIONEER/USBANLZ/000/1/ANLZ0000.DAT"
    make_anlz(dat, [pqtz_tag(40)])
    make_anlz(dat.with_suffix(".EXT"), [pwv3_tag(pwv3_from(audio, 48000, 1024 / 48000))])
    got = timeline_offset(f, place=place, probe_audio=info("aac", 48000), decode=lambda path: (audio, 48000),
                          trim=lambda path, codec: 1024, running=lambda: False)
    assert (got.samples, got.why) == (941, "measured")  # 1024 samples at 48 kHz are 21.33 ms: 941 at 44.1 kHz
    assert got.entries[0].expected_ms == 1024 / 48000 * 1000 and RATE == 44100


@pytest.mark.parametrize("codec, cues, grid, want", [
    ("mp3", 0, False, (0, "no_cues")),
    ("mp3", 2, False, (None, "not_analysed")),
    ("pcm_s16be", 2, False, (0, "format")),
    ("flac", 0, True, (0, "format")),
])
def test_without_a_waveform(tmp_path, codec, cues, grid, want):
    f = tmp_path / "a.file"
    place = rekordbox(tmp_path, [(f, cues, None, False)])
    if grid:  # a grid but no waveform
        make_anlz(place.share / "PIONEER/USBANLZ/000/1/ANLZ0000.DAT", [pqtz_tag(16)])
    got = timeline_offset(f, place=place, **stubs(codec))
    assert (got.samples, got.why) == want
    assert [(e.pwv3, e.grid) for e in got.entries] == [(False, grid)]


def test_not_analysed_wins_over_timing(tmp_path):
    f = tmp_path / "a.mp3"
    got = timeline_offset(f, place=rekordbox(tmp_path, [(f, 2, 1600, True), (f, 2, None, False)]), **stubs())
    assert (got.samples, got.why) == (None, "not_analysed")


def test_a_track_without_cues_or_grid_isnt_measured(tmp_path):
    f = tmp_path / "a.mp3"

    def no_decode(path):
        raise AssertionError("decoded for a track that doesn't care")
    got = timeline_offset(f, place=rekordbox(tmp_path, [(f, 0, 1600, False)]), **{**stubs(), "decode": no_decode})
    assert (got.samples, got.why) == (0, "no_cues") and got.entries[0].pwv3 and got.entries[0].offset_ms is None


@pytest.mark.parametrize("codec, want", [("mp3", (None, "unreadable")), ("pcm_s16le", (0, "format"))])
def test_an_unreadable_library(tmp_path, codec, want):
    folder = tmp_path / "rb"
    make_master(folder, [{"path": str(tmp_path / "a.mp3")}], key="ab" * 32)
    place = locate(env={"DISCJOCKEY_REKORDBOX": str(folder)})
    got = timeline_offset(tmp_path / "a.mp3", place=place, **stubs(codec))
    assert (got.samples, got.why, got.rekordbox.state, got.entries) == (*want, "unreadable", [])


# --- the ffmpeg side ---

def elst_skip(path: Path) -> int:
    """The media time of an MP4's first edit-list entry (version 0): the samples it skips at the start."""
    data = path.read_bytes()
    at = data.index(b"elst")
    assert data[at + 4] == 0
    return int.from_bytes(data[at + 16:at + 20], "big", signed=True)


def lame_delay(path: Path) -> int:
    """An MP3's start trim per its Info/LAME tag: the encoder delay (12 bits) plus the decoder's 529."""
    head = path.read_bytes()[:4096]
    at = next(head.index(tag) for tag in (b"LAME", b"Lavc", b"Lavf") if tag in head[head.index(b"Info"):])
    at = head.index(head[at:at + 4], head.index(b"Info"))
    return (head[at + 21] << 4 | head[at + 22] >> 4) + 529


@pytest.fixture(scope="module")
def m4a(tmp_path_factory):
    folder = tmp_path_factory.mktemp("m4a")
    wav = write_wav(folder / "clicks.wav", clicks(20, 48000), 48000)
    out = folder / "clicks.m4a"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-c:a", "aac", "-b:a", "128k", str(out)],
                   check=True)
    return out


@needs_ffmpeg
def test_start_trim_is_the_files_own_skip(m4a):
    assert start_trim(m4a, "aac", 48000) == elst_skip(m4a) > 0
    lame = FIXTURES / "clicks-lame.mp3"
    assert start_trim(lame, "mp3", SR) == lame_delay(lame) == 1105
    assert start_trim(FIXTURES / "clicks-notag.mp3", "mp3", SR) == 0
    assert start_trim(FIXTURES / "clicks-notag.mp3", "pcm_s16le") == 0  # nothing to drop: not decoded


@needs_ffmpeg
def test_timeline_offset_measures_real_decodes_exactly(tmp_path, m4a, monkeypatch):
    lame, notag = FIXTURES / "clicks-lame.mp3", FIXTURES / "clicks-notag.mp3"
    cases = [  # file, rekordbox's extra samples over ffmpeg's decode (native rate), sample rate
        (m4a, elst_skip(m4a), 48000),
        (lame, 1105, SR),            # the tag's delay
        (lame, 1105 + 1152, SR),     # one frame more, as rekordbox sometimes does
        (notag, 1105, SR),           # a delay the header doesn't show
    ]
    rows, files = [], []
    for i, (src, extra, sr) in enumerate(cases):
        f = tmp_path / "music" / f"{i}{src.suffix}"
        f.parent.mkdir(exist_ok=True)
        shutil.copyfile(src, f)
        rows.append({"ID": str(i + 1), "path": str(f), "cues": 2})
        files.append(f)
    folder = tmp_path / "rb"
    make_master(folder, rows)
    monkeypatch.setenv("DISCJOCKEY_REKORDBOX", str(folder))
    share = folder / "share"
    for i, (f, (_, extra, sr)) in enumerate(zip(files, cases)):
        audio, rate = quality.decode_mono(f)
        assert rate == sr
        dat = share / f"PIONEER/USBANLZ/{i:03x}/{i + 1}/ANLZ0000.DAT"
        make_anlz(dat, [pqtz_tag(40)])
        make_anlz(dat.with_suffix(".EXT"), [pwv3_tag(pwv3_from(audio, sr, extra / sr))])
    for f, (_, extra, sr) in zip(files, cases):
        got = timeline_offset(f)  # the defaults: locate(), process.running (conftest: closed), ffmpeg
        assert (got.why, got.samples) == ("measured", round(extra / sr * RATE)), f.name
        assert abs(got.entries[0].offset_ms - extra / sr * 1000) < 0.12


@needs_ffmpeg
def test_a_six_minute_file_is_measured_in_a_few_seconds(tmp_path):
    """Plan §1.7 aims at 3 s for a 6-minute file, decode included; the guard is looser so a slow machine passes and a
    regression still shows. The real time is printed with `pytest -s`."""
    import time
    long = clicks(360, SR)
    f = write_wav(tmp_path / "long.wav", long, SR)
    place = rekordbox_for_audio(tmp_path, f, long)
    started = time.perf_counter()
    got = timeline_offset(f, place=place, running=lambda: False)
    took = time.perf_counter() - started
    print(f"six-minute measurement: {took:.2f} s")
    assert (got.why, got.samples) == ("measured", 0)
    assert took < 6, took


def rekordbox_for_audio(tmp_path, f, audio):
    folder = tmp_path / "rb"
    make_master(folder, [{"ID": "1", "path": str(f), "cues": 2}])
    place = locate(env={"DISCJOCKEY_REKORDBOX": str(folder)})
    dat = place.share / "PIONEER/USBANLZ/000/1/ANLZ0000.DAT"
    make_anlz(dat, [pqtz_tag(40)])
    make_anlz(dat.with_suffix(".EXT"), [pwv3_tag(pwv3_from(audio, SR, 0))])
    return place
