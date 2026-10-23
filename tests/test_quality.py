import shutil
import subprocess
import wave

import numpy as np
import pytest

from discjockey.quality import LOSSY_CLIFF_DB, analyze, cutoff_hz, is_lossless_codec, probe, quality_line, verdict

SR = 44100
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def noise(seconds=8, seed=0):
    return (np.random.default_rng(seed).standard_normal(SR * seconds) * 0.1).astype(np.float32)


def band(x, low, high):
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    spec[(f < low) | (f > high)] = 0
    return np.fft.irfft(spec, n=len(x)).astype(np.float32)


@pytest.mark.parametrize("hz", [16000, 17900, 20000])
def test_cutoff_detected(hz):
    c = cutoff_hz(band(noise(), 0, hz), SR)
    assert c is not None and abs(c - hz) <= 200


def test_full_band_has_no_cutoff():
    assert cutoff_hz(noise(), SR) is None


def test_lowest_cliff_wins_over_largest_drop():
    # weak content between 17.9 and 19.4 kHz: the real lossy edge is 17.9 kHz,
    # the biggest drop is at 19.4 kHz (this fooled the "largest drop" rule on 2026-10-13)
    x = band(noise(), 0, 17900) + 0.05 * band(noise(seed=1), 17900, 19400)
    c = cutoff_hz(x, SR)
    assert abs(c - 17900) <= 200


def test_sparse_transients_do_not_hide_cutoff():
    x = band(noise(), 0, 17900)
    x[:: SR * 2] += 0.9
    assert abs(cutoff_hz(x, SR) - 17900) <= 200


def test_silence_and_short_input():
    assert cutoff_hz(np.zeros(SR * 2, dtype=np.float32), SR) is None
    assert cutoff_hz(np.zeros(100, dtype=np.float32), SR) is None


def test_verdict():
    assert verdict(True, None) == "lossless"
    assert verdict(True, 20000) == "lossless"
    assert verdict(True, 16000) == "fake_lossless"
    assert verdict(False, None) == "not_lossless"
    assert verdict(False, 16000) == "not_lossless"


def test_is_lossless_codec():
    assert all(is_lossless_codec(c) for c in ("flac", "alac", "pcm_s16le", "pcm_s24be"))
    assert not any(is_lossless_codec(c) for c in ("mp3", "aac", "opus", "vorbis"))


def test_quality_line():
    assert quality_line("qobuz", "flac", "lossless", None) == "Qobuz FLAC · verified lossless"
    assert quality_line("qobuz", "flac", "fake_lossless", 16100) == "Qobuz FLAC · fake lossless, cutoff 16.1 kHz"
    assert quality_line("youtube_music", "opus", "not_lossless", 20000) == "YouTube Music OPUS · cutoff 20.0 kHz"
    assert quality_line("manual", "pcm_s16le", "lossless", None) == "bought file PCM · verified lossless"
    assert quality_line("soundcloud", "aac", "not_lossless", 17900, 160) == "SoundCloud AAC 160 kbps · cutoff 17.9 kHz"
    assert quality_line("qobuz", "flac", "lossless", None, 900) == "Qobuz FLAC · verified lossless"


def write_wav(path, x):
    pcm = (np.clip(x, -1, 1) * 32767).astype("<i2")
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(pcm.tobytes())


@needs_ffmpeg
def test_probe_and_analyze_file(tmp_path):
    f = tmp_path / "x.wav"
    write_wav(f, band(noise(seconds=5), 0, 16000))
    info = probe(f)
    assert info.codec == "pcm_s16le" and info.sample_rate == SR and abs(info.duration_s - 5) < 0.1
    assert info.kbps == 706  # 16-bit mono at 44.1 kHz
    assert abs(analyze(f) - 16000) <= 200


@needs_ffmpeg
def test_probe_rejects_non_audio(tmp_path):
    f = tmp_path / "x.txt"
    f.write_text("hello")
    with pytest.raises(RuntimeError):
        probe(f)


def soft_edge(x, start, width, depth_db=28):
    """YouTube Opus style: the level falls by depth_db over `width` Hz instead of at once."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    gain_db = -np.clip((f - start) / width, 0, 1) * depth_db
    return np.fft.irfft(spec * 10 ** (gain_db / 20), n=len(x)).astype(np.float32)


def test_soft_edge_of_a_lossy_file_is_still_shown():
    x = soft_edge(noise(), 19800, 800)
    assert cutoff_hz(x, SR) is None  # too gentle to call a lossless file fake
    c = cutoff_hz(x, SR, cliff_db=LOSSY_CLIFF_DB)  # but a lossy file shows where it ends
    assert c is not None and 19800 <= c <= 20600
