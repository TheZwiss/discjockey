"""Spectral cutoff analysis (detects lossy sources), probing, and the verdict rules."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .models import SOURCE_NAMES

FRAME = 8192
HOP = 4096
BAND_HZ = 100
WINDOW_BANDS = 4
CLIFF_DB = 18.0
LOSSY_CLIFF_DB = 12.0  # lossy sources: the cutoff is only shown, never decides the verdict, and their edge
                       # (YouTube Opus ~20 kHz) can fall over ~600 Hz instead of at once
SEARCH_LOW_HZ = 10_000
SEARCH_HIGH_HZ = 21_500
FAKE_BELOW_HZ = 19_500
CHUNK_FRAMES = 256
LOSSLESS_CODECS = {"flac", "alac", "wavpack", "ape", "tta"}


@dataclass(frozen=True)
class AudioInfo:
    codec: str
    sample_rate: int
    duration_s: float
    kbps: int | None = None  # the whole file's average bitrate (for lossy files, the codec's)


def probe(path: Path) -> AudioInfo:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a:0",
         "-show_entries", "stream=codec_name,sample_rate:format=duration,bit_rate", "-of", "json", str(path)],
        capture_output=True, text=True, start_new_session=True,
    )
    data = json.loads(r.stdout or "{}") if r.returncode == 0 else {}
    streams = data.get("streams") or []
    if not streams:
        raise RuntimeError(f"ffprobe found no audio in {Path(path).name}: {r.stderr.strip()[:300]}")
    s, fmt = streams[0], data["format"]
    rate = fmt.get("bit_rate")
    kbps = round(int(rate) / 1000) if rate and str(rate).isdigit() else None
    return AudioInfo(s["codec_name"], int(s["sample_rate"]), float(fmt["duration"]), kbps)


def decode_mono(path: Path) -> tuple[np.ndarray, int]:
    info = probe(path)
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1",
         "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True, start_new_session=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {Path(path).name}: {r.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(r.stdout, dtype=np.float32), info.sample_rate


def _bands(x: np.ndarray, sr: int) -> np.ndarray | None:
    """70th-percentile dB spectrum of the loud frames, averaged into 100 Hz bands."""
    if len(x) < FRAME:
        return None
    n = 1 + (len(x) - FRAME) // HOP
    frames = np.lib.stride_tricks.sliding_window_view(x, FRAME)[::HOP][:n]
    rms = np.sqrt(np.mean(np.square(frames, dtype=np.float64), axis=1))
    if rms.max() <= 0:
        return None
    loud = np.flatnonzero(rms >= 0.1 * rms.max())
    window = np.hanning(FRAME)
    rows = []
    for i in range(0, len(loud), CHUNK_FRAMES):  # chunked to keep memory low on long tracks
        chunk = frames[loud[i:i + CHUNK_FRAMES]] * window
        power = np.abs(np.fft.rfft(chunk, axis=1)) ** 2
        rows.append((10 * np.log10(power + 1e-20)).astype(np.float32))
    p70 = np.percentile(np.concatenate(rows), 70, axis=0)
    freqs = np.fft.rfftfreq(FRAME, 1 / sr)
    idx = (freqs // BAND_HZ).astype(int)
    n_bands = int(freqs[-1] // BAND_HZ)
    return np.array([p70[idx == b].mean() for b in range(n_bands)])


def cutoff_hz(samples: np.ndarray, sample_rate: int, cliff_db: float = CLIFF_DB) -> int | None:
    """Lowest spectral cliff (>= cliff_db within 400 Hz) between 10 and 21.5 kHz, or None for full band."""
    bands = _bands(samples, sample_rate)
    if bands is None:
        return None
    w = WINDOW_BANDS
    drops = {}
    for b in range(w, len(bands) - w + 1):
        if SEARCH_LOW_HZ <= b * BAND_HZ <= SEARCH_HIGH_HZ:
            drops[b] = float(bands[b - w:b].mean() - bands[b:b + w].mean())
    region: list[int] = []
    for b in sorted(drops):
        if drops[b] >= cliff_db:
            region.append(b)
        elif region:
            break
    if not region:
        return None
    return max(region, key=lambda b: drops[b]) * BAND_HZ


def analyze(path: Path, lossy: bool = False) -> int | None:
    return cutoff_hz(*decode_mono(path), cliff_db=LOSSY_CLIFF_DB if lossy else CLIFF_DB)


def inspect(path: Path) -> tuple[str, int | None]:
    codec = probe(path).codec
    return codec, analyze(path, lossy=not is_lossless_codec(codec))


def is_lossless_codec(codec: str) -> bool:
    return codec.startswith("pcm_") or codec in LOSSLESS_CODECS


def verdict(source_lossless: bool, cutoff: int | None) -> str:
    if not source_lossless:
        return "not_lossless"
    if cutoff is not None and cutoff < FAKE_BELOW_HZ:
        return "fake_lossless"
    return "lossless"


def quality_line(source: str, codec: str, status: str, cutoff: int | None, kbps: int | None = None) -> str:
    name = SOURCE_NAMES[source]
    fmt = "PCM" if codec.startswith("pcm_") else codec.upper()
    if kbps and status == "not_lossless":
        fmt += f" {kbps} kbps"
    khz = f"{cutoff / 1000:.1f} kHz" if cutoff else None
    if status == "lossless":
        return f"{name} {fmt} · verified lossless"
    if status == "fake_lossless":
        return f"{name} {fmt} · fake lossless, cutoff {khz}"
    return f"{name} {fmt} · cutoff {khz}" if khz else f"{name} {fmt} · lossy"
