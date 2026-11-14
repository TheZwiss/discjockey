"""Music-like synthetic audio for tests: kicks, short synth notes and hi-hat noise at 128 BPM, never repeating."""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import numpy as np
import pytest

SR = 44100
needs_ffmpeg = pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")


def music(seconds: float = 60, seed: int = 0) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(seconds * SR)
    x = np.zeros(n)
    step = int(SR * 60 / 128 / 2)  # eighth notes
    t = np.arange(step) / SR
    kick = np.sin(2 * np.pi * (55 * t + 100 / 30 * (1 - np.exp(-30 * t)))) * np.exp(-12 * t) * 0.8
    for i, s in enumerate(range(0, n - step, step)):
        f = 110 * 2 ** (rng.integers(0, 36) / 12)
        note = np.sin(2 * np.pi * f * t) * np.exp(-rng.uniform(5, 25) * t) * rng.uniform(0.15, 0.4)
        hat = rng.standard_normal(step) * np.exp(-80 * t) * rng.uniform(0.03, 0.15)
        x[s:s + step] += note + hat + (kick if i % 2 == 0 else 0)
    return (0.5 * x).astype(np.float32)


def lowpass(x: np.ndarray, hz: float) -> np.ndarray:
    spec = np.fft.rfft(x)
    spec[np.fft.rfftfreq(len(x), 1 / SR) > hz] = 0
    return np.fft.irfft(spec, n=len(x)).astype(np.float32)


def write_aiff(path: Path, x: np.ndarray, channels: int = 2) -> Path:
    """16-bit/44.1 kHz AIFF like the ones Discjockey makes (mono input copied to both channels)."""
    subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(SR), "-ac", "1", "-i", "-",
         "-ac", str(channels), "-c:a", "pcm_s16be", "-f", "aiff", str(path)],
        input=np.asarray(x, dtype=np.float32).tobytes(), check=True,
    )
    return path


def pcm(path: Path) -> np.ndarray:
    """The exact 16-bit samples of a file, frames x channels."""
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le",
                        "-ac", "2", "-"], capture_output=True, check=True)
    return np.frombuffer(r.stdout, dtype="<i2").reshape(-1, 2)


def to_aac(src: Path, dst: Path, lowpass_hz: int | None = None) -> Path:
    """A lossy copy as YouTube Music would hand it out (AAC 128 kbit/s in .m4a)."""
    af = ["-af", f"lowpass=f={lowpass_hz}"] if lowpass_hz else []
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), *af, "-c:a", "aac", "-b:a", "128k",
                    str(dst)], check=True)
    return dst


def picture(width: int, height: int, fmt: str = "jpeg") -> bytes:
    """A test picture (ffmpeg's test pattern with noise, so it doesn't compress to nothing) as a baseline JPEG or a PNG."""
    codec, form = ("mjpeg", "image2") if fmt == "jpeg" else ("png", "image2")
    r = subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-f", "lavfi", "-i",
                        f"testsrc2=s={width}x{height}:d=1,noise=alls=40:allf=t", "-frames:v", "1", "-pix_fmt",
                        "yuvj420p" if fmt == "jpeg" else "rgb24", "-c:v", codec, "-q:v", "3", "-f", form, "-"],
                       capture_output=True, check=True)
    return r.stdout


# a 16 x 16 baseline JPEG (ffmpeg's mjpeg, a red square): small enough to write as a cover without ffmpeg, and within
# the CDJ limits `audio.cdj_cover` keeps byte for byte
TINY_JPEG = bytes.fromhex(
    "ffd8ffe000104a46494600010200000100010000fffe00104c61766336322e32382e31303100ffdb0043000806060706"
    "070808080808080909090a0a0a090909090a0a0a0a0a0a0c0c0c0a0a0a0a0a0a0a0c0c0c0c0d0e0d0d0d0c0d0e0e0f0f"
    "0f1212111115151519191fffc4004c000101000000000000000000000000000000060101010000000000000000000000"
    "0000000607100100000000000000000000000000000000110100000000000000000000000000000000ffc00011080010"
    "001003012200021100031100ffda000c03010002110311003f008b004d7f7fffd9"
)
