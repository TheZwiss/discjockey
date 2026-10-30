import shutil
import subprocess
import wave

import numpy as np
import pytest

from discjockey.quality import FAKE_BELOW_HZ, LOSSY_CLIFF_DB, analyze, cutoff_hz, is_lossless_codec, probe, quality_line, verdict

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
    assert verdict(True, 21000) == "lossless"  # a steep anti-alias filter of a 44.1 kHz master
    assert verdict(True, 20000) == "fake_lossless"  # an Opus / MP3 320 wall
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
    c = cutoff_hz(x, SR, cliff_db=LOSSY_CLIFF_DB)  # a lossy file shows where it ends
    assert c is not None and 19800 <= c <= 20600


def test_soft_edge_near_20_khz_in_a_lossless_file_is_fake():
    # 28 dB over 800 Hz is too soft for a cliff, but no natural roll-off falls that fast at 20 kHz
    c = cutoff_hz(soft_edge(noise(), 19800, 800), SR)
    assert c is not None and 19800 <= c <= 20600
    assert verdict(True, c) == "fake_lossless"


def shaped(x, points):
    """The level in dB follows a line through the (Hz, dB) points (flat beyond the last)."""
    spec = np.fft.rfft(x)
    f = np.fft.rfftfreq(len(x), 1 / SR)
    hz, db = zip(*points)
    return np.fft.irfft(spec * 10 ** (np.interp(f, hz, db) / 20), n=len(x)).astype(np.float32)


def test_steps_into_a_floor_are_a_cutoff():
    # a lossy edge in steps, each too small for a cliff, down to a flat floor with nothing above
    steps = [(0, 0), (17550, 0), (17650, -12), (18950, -12), (19050, -24), (19550, -24), (19650, -40)]
    x = shaped(noise(), steps)
    assert cutoff_hz(x, SR) is not None and 17400 <= cutoff_hz(x, SR) <= 17900


def test_slope_into_a_floor_is_a_cutoff():
    # 36 dB along a slope over 2.5 kHz, then the flat floor
    x = shaped(noise(), [(0, 0), (15800, 0), (18300, -36)])
    c = cutoff_hz(x, SR)
    assert c is not None and 16000 <= c <= 17000


def test_natural_roll_off_is_full_band():
    # keeps falling up to the top: no floor
    assert cutoff_hz(shaped(noise(), [(0, 0), (12000, 0), (21500, -40), (22050, -42)]), SR) is None


def test_slow_roll_off_into_a_floor_is_full_band():
    # a quiet top end that sinks into the noise floor, but over 6 kHz, not 3
    assert cutoff_hz(shaped(noise(), [(0, 0), (12000, 0), (18000, -30)]), SR) is None


@pytest.mark.parametrize("wall_hz", [19600, 20000, 20200, 20500])
def test_a_brick_wall_near_20_khz_is_fake(wall_hz):
    # Opus always walls at ~20 kHz, LAME 320 kbps at 20.2-20.5 kHz: full level up to the wall, nothing above
    c = cutoff_hz(shaped(noise(), [(0, 0), (wall_hz, 0), (wall_hz + 300, -40)]), SR)
    assert c is not None and abs(c - wall_hz) <= 300
    assert verdict(True, c) == "fake_lossless"


@pytest.mark.parametrize("points", [
    [(0, 0), (19900, 0), (20000, -14), (20100, -21), (20300, -27), (20500, -38), (20800, -55), (21500, -60)],
    [(0, 0), (19900, 0), (20000, -14), (20200, -23), (20400, -25)],  # into a shallow floor only 25 dB down
    [(0, 0), (19900, 0), (20000, -12), (20200, -19), (20400, -20)],  # 20 dB down: too shallow for a cliff
])
def test_decoded_opus_saved_as_wav_is_fake(points):
    # the measured shape of decoded Opus: flat to 19.9 kHz, 14 dB down at 20.0 kHz, then falling to the floor
    c = cutoff_hz(shaped(noise(), points), SR)
    assert c is not None and 19800 <= c <= 20300
    assert verdict(True, c) == "fake_lossless"


@pytest.mark.parametrize("points", [
    [(0, 0), (17000, 0), (20000, -12), (22050, -28)],  # a natural roll-off near 20 kHz
    [(0, 0), (19500, 0), (22050, -25)],  # a resampler's anti-alias filter, falling over 2.5 kHz
    [(0, 0), (20900, 0), (21200, -40)],  # a steep anti-alias filter above the lossy walls
])
def test_a_roll_off_or_anti_alias_filter_stays_lossless(points):
    c = cutoff_hz(shaped(noise(), points), SR)
    assert c is None or c >= FAKE_BELOW_HZ
    assert verdict(True, c) == "lossless"


def test_the_quality_line_of_an_own_file_puts_the_format_in_brackets():
    assert quality_line("manual", "pcm_s16le", "lossless", None, own=True) == "Your own file (PCM) · verified lossless"
    assert quality_line("manual", "pcm_s16le", "fake_lossless", 16100, own=True) == (
        "Your own file (PCM) · fake lossless, cutoff 16.1 kHz")
    assert quality_line("manual", "mp3", "not_lossless", 16000, 320, own=True) == (
        "Your own file (MP3 320 kbps) · cutoff 16.0 kHz")
    assert quality_line("qobuz", "flac", "lossless", None, own=True) == "Qobuz FLAC · verified lossless"
    assert quality_line("manual", "pcm_s16le", "lossless", None) == "bought file PCM · verified lossless"


def test_the_quality_line_of_a_file_whose_sound_is_not_checked_yet_gives_no_verdict():
    assert quality_line("manual", "pcm_s16le", "lossless", None, own=True, checked=False) == (
        "Your own file (PCM) · sound not checked yet")
    assert quality_line("manual", "mp3", "not_lossless", None, own=True, checked=False) == (
        "Your own file (MP3) · lossy, sound not checked yet")
    assert quality_line("manual", "pcm_s16le", "lossless", None, own=True) == "Your own file (PCM) · verified lossless"
