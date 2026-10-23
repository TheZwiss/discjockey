"""Do two versions of a track line up? Measured before a swap, so the user's cue points keep fitting the audio.

Two 8 s excerpts of the new file (at 25 % and 75 % of its length) are searched in the current file within
±3 s by FFT cross-correlation. Offset > 0: the audio comes that much later in the new file than in the current
one, so a swap trims that many samples at the start of the new audio (offset < 0: pads silence).
"""
from __future__ import annotations

import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

import numpy as np

SR = 44100
PROBE_S = 8.0
PROBES = (0.25, 0.75)  # where the excerpts sit in the new file
MAX_SHIFT_S = 3.0
MIN_SCORE = 0.6  # normalized correlation at the peak
MAX_DRIFT_MS = 5.0  # the two probes must agree this closely (else: other edit or speed)
EXACT_MS = 1.0
MIN_DURATION_S = 30
TIE_SCORE = 0.01  # peaks this close to the best one count as equally good (loops repeat bar by bar) ...
PEAK_GAP_S = 0.005  # ... and are told apart when at least this far apart; the one closest to no shift wins

TEXTS = {
    "exact": "matches exactly",
    "different": "doesn't line up: a swap would shift your cue points",
    "unknown": "could not compare the two versions",
}


@dataclass(frozen=True)
class Alignment:
    result: str  # exact | shifted | different | unknown
    offset_samples: int = 0
    offset_ms: float = 0.0
    drift_ms: float | None = None
    text: str = ""

    @property
    def swap_safe(self) -> bool:
        return self.result in ("exact", "shifted")

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> Alignment:
        return cls(d["result"], int(d.get("offset_samples", 0)), float(d.get("offset_ms", 0.0)),
                   d.get("drift_ms"), d.get("text", TEXTS.get(d["result"], "")))


def unknown() -> Alignment:
    return Alignment("unknown", text=TEXTS["unknown"])


def _different(drift_ms: float | None = None) -> Alignment:
    return Alignment("different", drift_ms=drift_ms, text=TEXTS["different"])


def _best_lag(probe: np.ndarray, window: np.ndarray, zero_lag: int) -> tuple[int, float]:
    """Lag of `probe` inside `window` with the highest normalized correlation, and that score.
    `zero_lag` is the lag at which the two files would line up without any shift."""
    p, w = probe.astype(np.float64), window.astype(np.float64)
    n_lags = len(w) - len(p) + 1
    size = 1 << (len(w) + len(p) - 1).bit_length()
    corr = np.fft.irfft(np.fft.rfft(w, size) * np.conj(np.fft.rfft(p, size)), size)[:n_lags]
    energy = np.concatenate(([0.0], np.cumsum(w * w)))
    window_norm = np.sqrt(np.maximum(energy[len(p):len(p) + n_lags] - energy[:n_lags], 0))
    denom = np.linalg.norm(p) * window_norm
    score = np.divide(corr, denom, out=np.zeros(n_lags), where=denom > 1e-9)
    best = float(score.max())
    # every lag about as good as the best one, grouped into separate peaks; each peak's top lag is a candidate
    near = np.flatnonzero(score >= best - TIE_SCORE)
    gap = int(PEAK_GAP_S * SR)
    groups = np.split(near, np.flatnonzero(np.diff(near) > gap) + 1)
    peaks = [int(g[np.argmax(score[g])]) for g in groups]
    return min(peaks, key=lambda lag: abs(lag - zero_lag)), best  # ties: the one closest to no shift


def compare(current: np.ndarray, new: np.ndarray, sr: int = SR) -> Alignment:
    """Pure: both arrays are mono float audio at `sr`."""
    if min(len(current), len(new)) < MIN_DURATION_S * sr:
        return _different()
    probe_n, shift = int(PROBE_S * sr), int(MAX_SHIFT_S * sr)
    offsets = []
    for frac in PROBES:
        start = int(len(new) * frac) - probe_n // 2
        lo = max(0, start - shift)
        window = current[lo:start + probe_n + shift]
        if len(window) < probe_n:
            return _different()
        lag, score = _best_lag(new[start:start + probe_n], window, start - lo)
        if score < MIN_SCORE:
            return _different()
        offsets.append(start - (lo + lag))
    drift_ms = abs(offsets[0] - offsets[1]) * 1000 / sr
    if drift_ms > MAX_DRIFT_MS:
        return _different(round(drift_ms, 2))
    offset = round(sum(offsets) / len(offsets))
    ms = offset * 1000 / sr
    if abs(ms) < EXACT_MS:
        return Alignment("exact", offset, round(ms, 3), round(drift_ms, 2), TEXTS["exact"])
    return Alignment("shifted", offset, round(ms, 3), round(drift_ms, 2),
                     f"lines up after shifting by {abs(ms):.0f} ms")


def decode(path: Path) -> np.ndarray:
    """Mono 32-bit float at 44.1 kHz, whatever the file's own rate."""
    r = subprocess.run(
        ["ffmpeg", "-nostdin", "-v", "error", "-i", str(path), "-map", "0:a:0", "-ac", "1", "-ar", str(SR),
         "-f", "f32le", "-acodec", "pcm_f32le", "-"],
        capture_output=True, start_new_session=True,
    )
    if r.returncode != 0:
        raise RuntimeError(f"ffmpeg could not decode {Path(path).name}: {r.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(r.stdout, dtype=np.float32)


def compare_files(current: Path, new: Path) -> Alignment:
    try:
        a, b = decode(current), decode(new)
    except (OSError, RuntimeError):
        return unknown()
    return compare(a, b)
