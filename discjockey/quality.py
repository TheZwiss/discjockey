"""Spectral cutoff analysis (detects lossy sources), probing, and the verdict rules."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .models import OWN_FILE, SOURCE_NAMES

FRAME = 8192
HOP = 4096
BAND_HZ = 100
WINDOW_BANDS = 4
CLIFF_DB = 18.0
LOSSY_CLIFF_DB = 12.0  # lossy sources: the cutoff is only shown, never decides the verdict, and their edge
                       # (YouTube Opus ~20 kHz) can fall over ~600 Hz instead of at once
SEARCH_LOW_HZ = 10_000
SEARCH_HIGH_HZ = 21_500
# A lossy encoder's top end can also fall gradually or in steps, each too small for a cliff, into a flat floor:
FLOOR_TOL_DB = 3.0     # the floor: every band from its start up to 21.5 kHz within this of the top kHz's level
FLOOR_MIN_HZ = 1_500   # and at least this wide (a mastering low-pass near 20 kHz leaves a narrower one)
FALL_SPAN_HZ = 3_000   # the music this far below the floor's start (its level over MUSIC_HZ) ...
FALL_DB = 30.0         # ... sits at least this far above the floor (a natural roll-off falls slower)
MUSIC_HZ = 500
EDGE_DB = 10.0         # the cutoff is where the fall first drops this far below that music level
# A lossless file whose sound ends below this is fake. The cutoff is only ever a wall (a cliff, or a steep fall into
# a flat floor); natural roll-offs and resamplers' anti-alias filters fall too slowly to leave one. Lossy encoders wall
# at or below 20.5 kHz (Opus always ~20 kHz, LAME 320 kbps 20.2-20.5 kHz); a steep anti-alias filter sits at 21+ kHz.
FAKE_BELOW_HZ = 20_800
WALL_LOW_HZ = 19_500   # from here up to WALL_HIGH_HZ a smaller cliff (LOSSY_CLIFF_DB) is a wall too: an encoder's wall into
                       # a quiet top end can fall only 12-18 dB, while natural roll-offs fall about 10 dB per kHz or less
WALL_HIGH_HZ = 20_400  # encoders low-pass near 20 kHz (Opus, LAME); mastering filters sit higher, so above this a cliff must be CLIFF_DB
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
    """Where the top end ends, or None for full band: the lowest spectral cliff (>= cliff_db within 400 Hz)
    between 10 and 21.5 kHz, failing that the edge of a steeper fall into a flat floor (`_floor_edge`), failing that
    a smaller wall (>= LOSSY_CLIFF_DB) between WALL_LOW_HZ and WALL_HIGH_HZ."""
    bands = _bands(samples, sample_rate)
    if bands is None:
        return None
    for edge in (_cliff(bands, cliff_db), _floor_edge(bands),
                 _cliff(bands, min(cliff_db, LOSSY_CLIFF_DB), WALL_LOW_HZ, WALL_HIGH_HZ - BAND_HZ)):
        if edge is not None:
            return edge
    return None


def _cliff(bands: np.ndarray, cliff_db: float,
           low_hz: int = SEARCH_LOW_HZ, high_hz: int = SEARCH_HIGH_HZ) -> int | None:
    w = WINDOW_BANDS
    drops = {}
    for b in range(w, len(bands) - w + 1):
        if low_hz <= b * BAND_HZ <= high_hz:
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


def _floor_edge(bands: np.ndarray) -> int | None:
    """The start of a fall of FALL_DB or more within FALL_SPAN_HZ into a flat floor that runs to 21.5 kHz.

    A lossy encoder leaves nothing above its low-pass, so the top bands sit flat at a floor; its edge can fall
    in steps or along a slope (each step too small for a cliff). Genuine roll-offs keep falling up to the top,
    reach a floor only near 20 kHz, or fall more slowly than FALL_DB per FALL_SPAN_HZ."""
    top, low = SEARCH_HIGH_HZ // BAND_HZ, SEARCH_LOW_HZ // BAND_HZ
    if len(bands) <= top:  # sampled too low to reach the floor's reference
        return None
    level = float(np.median(bands[top - 1000 // BAND_HZ:top + 1]))
    start = top
    while start > low and abs(bands[start - 1] - level) <= FLOOR_TOL_DB:
        start -= 1
    if (top - start) * BAND_HZ < FLOOR_MIN_HZ:
        return None
    fall_from = start - FALL_SPAN_HZ // BAND_HZ
    music = float(bands[fall_from - MUSIC_HZ // BAND_HZ:fall_from].mean())
    if music - level < FALL_DB:
        return None
    edge = next((b for b in range(max(fall_from, low), start) if bands[b] <= music - EDGE_DB), start)
    return edge * BAND_HZ


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


def quality_line(source: str, codec: str, status: str, cutoff: int | None, kbps: int | None = None,
                 own: bool = False, checked: bool = True) -> str:
    """The words under a track: where it came from, its format and the verdict. `own`: a file of the user's own that
    the import found, which the "manual" source would call a bought file. `checked` False: the import has read the
    file's tags but not judged its sound yet, so the codec's guess ("lossless" for a WAV) is no verdict."""
    fmt = "PCM" if codec.startswith("pcm_") else codec.upper()
    if kbps and status == "not_lossless":
        fmt += f" {kbps} kbps"
    if own and source == "manual":  # "Your own file (PCM) · …": the format in brackets reads as a sentence
        name, fmt = OWN_FILE[0].upper() + OWN_FILE[1:], f"({fmt})"
    else:
        name = SOURCE_NAMES[source]
    khz = f"{cutoff / 1000:.1f} kHz" if cutoff else None
    if not checked:
        return f"{name} {fmt} · {'sound not checked yet' if status == 'lossless' else 'lossy, sound not checked yet'}"
    if status == "lossless":
        return f"{name} {fmt} · verified lossless"
    if status == "fake_lossless":
        return f"{name} {fmt} · fake lossless, cutoff {khz}"
    return f"{name} {fmt} · cutoff {khz}" if khz else f"{name} {fmt} · lossy"
