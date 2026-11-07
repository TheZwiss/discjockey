"""The ffmpeg side of rekordbox timing (plan rekordbox stage A §0.3, §1.2): how many samples ffmpeg's default decode
drops at a file's start (`start_trim`).

ffmpeg drops an MP3's encoder delay (from its LAME/Lavc tag), an MP4's edit-list skip, Opus' pre-skip; rekordbox
doesn't always (design §3.2). The decode with `-flags2 +skip_manual` keeps those samples: the decoder only marks
them. Checked 2026-11-07 with the bundled ffmpeg 9.0.2 and ffmpeg 8.1: for MP3 and M4A (AAC) it gives the same
untrimmed start as `-ignore_editlist 1`, which is an MP4-only option (any other input refuses to open with it), so
one flag serves every format.

`trim` is found by matching, not by lengths (their difference also counts the end padding): the lag at which the
default decode, from its first audible sample, equals the untrimmed decode sample for sample (max abs difference
under `EXACT`) over `MATCH_S`. Both decodes stop after `SPAN_S`; a file silent that long is decoded whole once more.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import numpy as np

from .timing import zero_only

UNTRIMMED = ("-flags2", "+skip_manual")
SPAN_S = 30
MATCH_S = 2
MAX_TRIM_S = 1.0     # an edit-list skip or encoder delay is far below this
EXACT = 1e-6
AUDIBLE = 1e-3


class ProbeError(RuntimeError):
    """ffmpeg couldn't decode the file, or its two decodes don't line up."""


def _decode(path: Path, untrimmed: bool, seconds: float | None) -> np.ndarray:
    cmd = ["ffmpeg", "-nostdin", "-v", "error", *(UNTRIMMED if untrimmed else ()), "-i", str(path),
           "-map", "0:a:0", "-ac", "1", *(("-t", str(seconds)) if seconds else ()),
           "-f", "f32le", "-acodec", "pcm_f32le", "-"]
    r = subprocess.run(cmd, capture_output=True, start_new_session=True)
    if r.returncode != 0:
        raise ProbeError(f"ffmpeg could not decode {Path(path).name}: {r.stderr.decode(errors='replace')[:300]}")
    return np.frombuffer(r.stdout, dtype=np.float32)


def _lag(trimmed: np.ndarray, untrimmed: np.ndarray, sr: int) -> int | None:
    """The smallest `L` with `untrimmed[j + L:] == trimmed[j:]` over `MATCH_S` from the first audible sample `j`;
    None when there is no audible sample."""
    audible = np.flatnonzero(np.abs(trimmed) > AUDIBLE)
    if len(audible) == 0:
        return None
    j = int(audible[0])
    n = min(int(MATCH_S * sr), len(trimmed) - j)
    window = trimmed[j:j + n]
    reach = untrimmed[j:j + int(MAX_TRIM_S * sr) + 1]
    for lag in np.flatnonzero(np.abs(reach - trimmed[j]) < EXACT):
        lag = int(lag)
        part = untrimmed[j + lag:j + lag + n]
        if len(part) == n and float(np.max(np.abs(part - window))) < EXACT:
            return lag
    raise ProbeError("the untrimmed decode doesn't hold the default decode")


def start_trim(path: Path, codec: str, sr: int | None = None) -> int:
    """How many of the file's own samples ffmpeg's default decode drops at its start (0 for PCM, FLAC, ALAC: they have
    nothing to drop). `sr` is the file's sample rate (only bounds the search; 48 kHz when unknown). Raises
    `ProbeError`."""
    if zero_only(codec):
        return 0
    rate = sr or 48000
    lag = _lag(_decode(path, False, SPAN_S), _decode(path, True, SPAN_S + MAX_TRIM_S), rate)
    if lag is None:  # silent for the whole span: compare the whole file
        lag = _lag(_decode(path, False, None), _decode(path, True, None), rate)
    return 0 if lag is None else lag
