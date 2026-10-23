import numpy as np
import pytest
from audio_helpers import SR, lowpass, music, needs_ffmpeg, to_aac, write_aiff

from discjockey import align
from discjockey.align import Alignment, compare, compare_files
from discjockey.audio import convert_to_aiff

X = music(60)


def samples(ms):
    return round(ms * SR / 1000)


def test_identical_audio_matches_exactly():
    a = compare(X, X.copy())
    assert (a.result, a.offset_samples, a.text) == ("exact", 0, "matches exactly")
    assert a.swap_safe


def test_lossy_looking_copy_matches_exactly():
    a = compare(lowpass(X, 16000), X)
    assert a.result == "exact" and a.swap_safe


def test_new_version_with_audio_later_is_shifted():
    new = np.concatenate((np.zeros(samples(23), np.float32), X))
    a = compare(X, new)
    assert a.result == "shifted" and a.swap_safe
    assert a.offset_samples == samples(23) and abs(a.offset_ms - 23) < 0.1
    assert a.text == "lines up after shifting by 23 ms"


def test_new_version_with_audio_earlier_is_shifted():
    a = compare(lowpass(X, 16000), X[samples(40):])
    assert a.result == "shifted"
    assert a.offset_samples == -samples(40) and abs(a.offset_ms + 40) < 0.1
    assert a.text == "lines up after shifting by 40 ms"


def test_speed_change_is_different():
    t = np.arange(len(X)) * 1.001  # 0.1 % faster: the probes drift apart by about 30 ms
    faster = np.interp(t[t < len(X) - 1], np.arange(len(X)), X).astype(np.float32)
    a = compare(X, faster)
    assert a.result == "different" and not a.swap_safe
    assert a.text == "doesn't line up: a swap would shift your cue points"


def test_other_edit_drifts_and_is_different():
    half = len(X) // 2  # 10 ms more in the middle: both probes match well, but 10 ms apart
    edit = np.concatenate((X[:half], np.zeros(samples(10), np.float32), X[half:]))
    a = compare(X, edit)
    assert a.result == "different"
    assert abs(a.drift_ms - 10) < 0.1 and a.drift_ms > align.MAX_DRIFT_MS


def test_unrelated_audio_is_different():
    assert compare(X, music(60, seed=7)).result == "different"


def test_too_short_is_different():
    short = X[: SR * 29]
    assert compare(short, short).result == "different"


def test_looped_music_picks_the_shift_closest_to_zero():
    bar = music(1.875, seed=3)  # one bar at 128 BPM, repeated sample for sample like a DAW loop
    loop = np.tile(bar, 40)
    noisy = loop + np.random.default_rng(1).standard_normal(len(loop)).astype(np.float32) * 0.01
    new = np.concatenate((np.zeros(samples(12), np.float32), loop))
    a = compare(noisy, new)
    assert a.result == "shifted" and a.offset_samples == samples(12)


def test_alignment_round_trips_through_state():
    a = compare(X, np.concatenate((np.zeros(samples(23), np.float32), X)))
    assert Alignment.from_dict(a.to_dict()) == a
    old = {"result": "exact", "offset_ms": 0.0, "drift_ms": 0.0, "text": "matches exactly"}  # without samples
    assert Alignment.from_dict(old).offset_samples == 0


@needs_ffmpeg
def test_compare_files(tmp_path):
    cur = write_aiff(tmp_path / "cur.aiff", X)
    new = write_aiff(tmp_path / "new.aiff", np.concatenate((np.zeros(samples(23), np.float32), X)))
    a = compare_files(cur, new)
    assert a.result == "shifted" and a.offset_samples == samples(23)


@needs_ffmpeg
def test_undecodable_file_is_unknown(tmp_path):
    cur = write_aiff(tmp_path / "cur.aiff", X)
    broken = tmp_path / "new.aiff"
    broken.write_text("not audio")
    a = compare_files(cur, broken)
    assert (a.result, a.text) == ("unknown", "could not compare the two versions")
    assert not a.swap_safe


@needs_ffmpeg
def test_youtube_style_aac_copy_is_swap_safe(tmp_path, capsys):
    """Real lossy pipeline: AAC 128 kbit/s .m4a, converted the way Discjockey converts downloads."""
    original = write_aiff(tmp_path / "original.aiff", X)
    lossy = tmp_path / "lossy.aiff"
    convert_to_aiff(to_aac(original, tmp_path / "lossy.m4a"), lossy)
    a = compare_files(lossy, original)
    with capsys.disabled():
        print(f"\nAAC 128k round trip: {a.result}, offset {a.offset_samples} samples ({a.offset_ms} ms)")
    assert a.swap_safe and abs(a.offset_ms) < 30
