import base64
import json
import os

import numpy as np
import pytest

from discjockey.hub import spectrum
from discjockey.library import Paths
from audio_helpers import SR, lowpass, needs_ffmpeg, write_aiff

REL = "Library/A/not_lossless/Artist - Song.aiff"


def noise(seconds=20, cutoff=None, seed=1):
    x = np.random.default_rng(seed).standard_normal(int(seconds * SR)).astype(np.float32) * 0.3
    return lowpass(x, cutoff) if cutoff else x


def decoded(data):
    m = np.frombuffer(base64.b64decode(data["data"]), dtype=np.uint8).reshape(data["cols"], data["bands"])
    return data["floor_db"] * (1 - m / 255.0)  # back to dB relative to the loudest cell


@pytest.fixture
def paths(tmp_path):
    p = Paths(tmp_path, support=tmp_path / ".support")
    f = tmp_path / REL
    f.parent.mkdir(parents=True)
    f.write_bytes(b"audio")
    return p


def test_matrix_shows_where_the_lossy_cutoff_is(paths):
    calls = []

    def decode(path):
        calls.append(path)
        return noise(cutoff=16000), SR

    data = spectrum.spectrum(paths, REL, decode=decode)
    assert (data["cols"], data["bands"], data["max_hz"]) == (400, 128, 22050)
    assert data["duration_s"] == pytest.approx(20, abs=0.01)
    db = decoded(data)
    band_hz = data["max_hz"] / data["bands"]
    below = db[:, int(10000 / band_hz):int(15000 / band_hz)].mean()
    above = db[:, int(17500 / band_hz):].mean()
    assert below - above > 30 and db.max() == 0


def test_full_band_noise_has_no_cliff(paths):
    db = decoded(spectrum.spectrum(paths, REL, decode=lambda p: (noise(), SR)))
    band_hz = 22050 / 128
    assert abs(db[:, int(10000 / band_hz):int(15000 / band_hz)].mean() - db[:, int(17500 / band_hz):-2].mean()) < 6


def test_cached_by_path_size_and_mtime(paths):
    calls = []

    def decode(path):
        calls.append(path)
        return noise(5), SR

    first = spectrum.spectrum(paths, REL, decode=decode)
    assert spectrum.spectrum(paths, REL, decode=decode) == first and len(calls) == 1
    f = paths.root / REL
    os.utime(f, ns=(f.stat().st_atime_ns, f.stat().st_mtime_ns + 10**9))  # swapped: same name, new content
    spectrum.spectrum(paths, REL, decode=decode)
    assert len(calls) == 2
    assert len(list((paths.cache / "spectrum").iterdir())) == 1  # the old one is cleaned up


def test_very_short_or_silent_audio(paths):
    data = spectrum.spectrum(paths, REL, decode=lambda p: (np.zeros(100, dtype=np.float32), SR))
    assert len(base64.b64decode(data["data"])) == 400 * 128
    assert base64.b64decode(data["waveform"]) == bytes(400)  # silence: a flat line, no divide by zero


def waveform(data):
    return np.frombuffer(base64.b64decode(data["waveform"]), dtype=np.uint8)


def test_waveform_shows_a_loud_click_as_its_peak_not_its_mean(paths):
    x = noise(20, seed=3) * 0.1  # peaks around 0.1
    x[int(10.01 * SR)] = 0.95  # one sample of a kick's attack, inside column 200 of 400
    data = spectrum.spectrum(paths, REL, decode=lambda p: (x, SR))
    w = waveform(data)
    assert len(w) == data["cols"] == 400
    assert w[200] == 255 and w.max() == 255  # the click sets the scale; a mean would have hidden it
    assert w[199] < 255 * 0.5 and w[201] < 255 * 0.5
    assert w[199] > 0  # the quiet stretches are still drawn


def test_waveform_follows_the_loudness_of_each_stretch(paths):
    x = noise(20, seed=4)
    x[: len(x) // 2] *= 0.25  # first half quieter
    w = waveform(spectrum.spectrum(paths, REL, decode=lambda p: (x, SR)))
    assert w[:200].max() < w[200:].max() * 0.5 and w[200:].max() == 255


def test_a_cached_spectrum_without_a_waveform_is_made_again(paths):
    calls = []

    def decode(path):
        calls.append(path)
        return noise(5), SR

    first = spectrum.spectrum(paths, REL, decode=decode)
    (cached,) = (paths.cache / "spectrum").iterdir()
    old = {k: v for k, v in first.items() if k != "waveform"}  # written by an earlier version
    cached.write_text(json.dumps(old), encoding="utf-8")
    again = spectrum.spectrum(paths, REL, decode=decode)
    assert again == first and len(calls) == 2


def test_refuses_files_outside_the_library(paths):
    with pytest.raises(ValueError):
        spectrum.spectrum(paths, ".discjockey/state.json", decode=lambda p: (noise(1), SR))


@needs_ffmpeg
def test_real_aiff(paths, tmp_path):
    write_aiff(paths.root / REL, noise(10, cutoff=17000))
    db = decoded(spectrum.spectrum(paths, REL))
    band_hz = 22050 / 128
    assert db[:, int(10000 / band_hz):int(15000 / band_hz)].mean() - db[:, int(18500 / band_hz):].mean() > 30
