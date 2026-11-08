"""Where rekordbox's timeline sits for a file, measured from its waveform. **Pure:** no I/O, no clock (design
rekordbox-repoint §3.2–§3.4, plan stage A §0.2, §1.7).

rekordbox keeps cues and the grid in ms on its own decode of a file. That decode can start a little later in the
audio than ffmpeg's default decode (it doesn't drop an MP3's encoder delay or an MP4's edit list), so a moment at
`t` in ffmpeg's decode sits at `t + d` on rekordbox's timeline. `d` is found by comparing rekordbox's own waveform
(`PWV3`: the peak per 1/150 s column, heights 0–31) with the same envelope of ffmpeg's decode:

- `measure(heights, audio, sr)`: the envelope is the peak absolute sample of each 1/150 s window, for any fractional
  start (one running max over a window length, sampled per shift); every shift from `SHIFT_MIN_S` to `SHIFT_MAX_S` in
  `STEP_S` steps is scored by the Pearson correlation of heights and envelope over the columns from `SKIP_COLUMNS`
  on, and the best shift is refined by a parabola through its neighbours, then by a search at sample resolution
  within one step of it (the middle of the best scores).
- `expected(codec, sr, trim_samples)`: the values `d` can take for this kind of file, from the start trim ffmpeg
  applies (`probe.start_trim`). PCM, FLAC, ALAC: 0. MP3: the union `{0, trim, trim + 1152, 1105, 1105 + 1152}` in
  the file's own samples (1105 = LAME's 576 encoder delay + the decoder's 529; rekordbox sometimes adds one more
  1152-sample frame, and a file without a tag can still have the delay). Every other lossy codec: `{0, trim}`.
  The closest two MP3 values are 1105 and 1152 (47 samples, about 1.07 ms apart, when trim is 0): still more than
  twice `TOLERANCE_S`, so no measurement is within tolerance of two values and a snap is never ambiguous.
- `decide(measured, expected)`: accepted when the score is at least `MIN_SCORE` and the measurement lies within
  `TOLERANCE_S` of an expected value; the answer is **that expected value**, exact to the sample. Else `timing`.
- `agree(values)`: several rekordbox tracks for one file must land on the same value, else `timing`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

import numpy as np

COLUMNS_PER_SECOND = 150
SHIFT_MIN_S = -0.060
SHIFT_MAX_S = 0.080
STEP_S = 0.00025
SKIP_COLUMNS = 40          # rekordbox's first columns (a fade-in of its own) don't follow the audio
MIN_COLUMNS = 150          # under a second of columns to compare: too short to measure
MIN_SCORE = 0.90
TOLERANCE_S = 0.00025
MP3_DELAY = 1105           # samples: LAME's encoder delay (576) + the decoder delay (529)
MP3_FRAME = 1152           # samples in one MPEG-1 Layer III frame
ZERO_ONLY = frozenset({"flac", "alac"})  # plus every `pcm_*` codec

Reason = Literal["timing"]


@dataclass(frozen=True)
class Measured:
    offset_s: float  # rekordbox's timeline minus ffmpeg's default decode; positive: rekordbox's is later
    score: float     # the correlation at the best shift


@dataclass(frozen=True)
class Decided:
    offset_s: float | None
    reason: Reason | None


def zero_only(codec: str) -> bool:
    """Whether a file of this codec has nothing ffmpeg trims, so `d` can only be 0."""
    return codec.startswith("pcm_") or codec in ZERO_ONLY


def expected(codec: str, sr: int, trim_samples: int) -> list[float]:
    """The values `d` can take for a file of `codec` at `sr` whose start ffmpeg trims by `trim_samples`, in seconds,
    deduplicated, ascending."""
    if zero_only(codec):
        samples = {0}
    elif codec in ("mp3", "mp3float"):
        samples = {0, trim_samples, trim_samples + MP3_FRAME, MP3_DELAY, MP3_DELAY + MP3_FRAME}
    else:
        samples = {0, trim_samples}
    return [s / sr for s in sorted(samples)]


def _running_max(x: np.ndarray, width: int) -> np.ndarray:
    """`out[i] = max(x[i:i + width])` for every `i` with a whole window, in O(n): the max of a window is the max of
    the suffix maximum of the block it starts in and the prefix maximum of the block it ends in."""
    n = len(x)
    blocks = -(-n // width)
    padded = np.zeros(blocks * width, dtype=x.dtype)
    padded[:n] = x
    grid = padded.reshape(blocks, width)
    prefix = np.maximum.accumulate(grid, axis=1).ravel()
    suffix = np.maximum.accumulate(grid[:, ::-1], axis=1)[:, ::-1].ravel()
    count = n - width + 1
    return np.maximum(suffix[:count], prefix[width - 1:width - 1 + count])


def measure(heights: np.ndarray, audio: np.ndarray, sr: int) -> Measured | None:
    """rekordbox's offset against ffmpeg's decode `audio` (mono, native rate `sr`), from its waveform `heights`.
    None when the two overlap by too few columns to measure."""
    if sr <= 0 or len(audio) == 0:
        return None
    col = sr / COLUMNS_PER_SECOND            # samples per column, fractional at some rates
    width = max(1, int(round(col)))
    if len(audio) < width:
        return None
    env = _running_max(np.abs(np.asarray(audio, dtype=np.float32)), width)
    shifts = np.arange(SHIFT_MIN_S, SHIFT_MAX_S + STEP_S / 2, STEP_S)
    # rekordbox's column k covers ffmpeg's samples from k * col - shift * sr: keep the columns every shift can read
    first = max(SKIP_COLUMNS, int(np.ceil(SHIFT_MAX_S * sr / col)) + 1)
    last = min(len(heights), int(np.floor((len(env) - 1 + SHIFT_MIN_S * sr) / col)))
    if last - first < MIN_COLUMNS:
        return None
    k = np.arange(first, last)
    h = np.asarray(heights[first:last], dtype=np.float64)
    h = h - h.mean()
    h_norm = float(np.sqrt(h @ h))
    base = k * col

    def score(shift_samples: float) -> float:
        if h_norm == 0:
            return 0.0
        e = env[(base - shift_samples).astype(np.int64)].astype(np.float64)
        e -= e.mean()
        e_norm = float(np.sqrt(e @ e))
        return float(h @ e) / (h_norm * e_norm) if e_norm > 0 else 0.0

    scores = np.array([score(shift * sr) for shift in shifts])
    best = int(np.argmax(scores))
    offset = float(shifts[best]) * sr
    if 0 < best < len(shifts) - 1:
        a, b, c = scores[best - 1], scores[best], scores[best + 1]
        bend = a - 2 * b + c
        if bend < 0:
            offset += STEP_S * sr * 0.5 * (a - c) / bend
    # The parabola is only as good as the curve is round; a step at sample resolution around it finds the middle of
    # the best scores (on click tracks: within 2 samples instead of 11)
    reach = int(np.ceil(STEP_S * sr))
    lo = max(int(np.ceil(SHIFT_MIN_S * sr)), int(round(offset)) - reach)
    hi = min(int(np.floor(SHIFT_MAX_S * sr)), int(round(offset)) + reach)
    fine = np.arange(lo, hi + 1)
    fine_scores = np.array([score(s) for s in fine])
    top = fine[fine_scores >= fine_scores.max() - 1e-12]
    if fine_scores.max() >= scores[best]:
        offset = (float(top.min()) + float(top.max())) / 2
    return Measured(offset / sr, float(max(scores[best], fine_scores.max())))


def decide(measured: Measured, expected_s: list[float]) -> Decided:
    """The expected value `measured` lands on (within `TOLERANCE_S`, with a score of at least `MIN_SCORE`), else
    `timing`."""
    if measured.score < MIN_SCORE or not expected_s:
        return Decided(None, "timing")
    nearest = min(expected_s, key=lambda v: abs(v - measured.offset_s))
    if abs(nearest - measured.offset_s) > TOLERANCE_S:
        return Decided(None, "timing")
    return Decided(nearest, None)


def agree(values: list[float]) -> Decided:
    """One value for a file from its tracks' values: all equal, else `timing`. Empty: nothing to agree on (0)."""
    if not values:
        return Decided(0.0, None)
    first = values[0]
    if any(v != first for v in values[1:]):
        return Decided(None, "timing")
    return Decided(first, None)
