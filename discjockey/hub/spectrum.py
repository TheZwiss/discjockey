"""Spectrogram data for the window's canvas (spec "hub" 7.6): ~400 time columns x 128 frequency bands, in dB
relative to the loudest cell, cached in the support folder's cache/spectrum/ by path, size and mtime."""
from __future__ import annotations

import base64
import hashlib
import json
from pathlib import PurePosixPath

import numpy as np

from .. import quality
from ..library import Paths
from ..names import fold

COLS = 400
BANDS = 128
FRAME = 4096
FLOOR_DB = -100.0  # quieter than this (relative to the loudest cell) is drawn black
SERVED = ("library", "superseded", "upgrades ready")


def matrix(samples: np.ndarray, sr: int, cols: int = COLS, bands: int = BANDS) -> np.ndarray:
    """cols x bands, dB relative to the loudest cell, clipped at FLOOR_DB. Bands split 0 Hz .. sr/2 evenly."""
    x = np.asarray(samples, dtype=np.float32)
    if len(x) < FRAME:
        x = np.pad(x, (0, FRAME - len(x)))
    starts = np.linspace(0, len(x) - FRAME, cols).astype(int)
    frames = np.stack([x[s:s + FRAME] for s in starts]) * np.hanning(FRAME).astype(np.float32)
    power = np.abs(np.fft.rfft(frames, axis=1)) ** 2  # cols x (FRAME/2 + 1)
    edges = np.linspace(0, power.shape[1], bands + 1).astype(int)
    banded = np.stack([power[:, a:max(b, a + 1)].mean(axis=1) for a, b in zip(edges[:-1], edges[1:])], axis=1)
    db = 10 * np.log10(banded + 1e-20)
    db -= db.max()
    return np.clip(db, FLOOR_DB, 0.0)


def encode(db: np.ndarray) -> str:
    """Base64 of one byte per cell, row by row (time), low to high frequency: 0 = FLOOR_DB, 255 = 0 dB."""
    return base64.b64encode(np.round((1 - db / FLOOR_DB) * 255).astype(np.uint8).tobytes()).decode("ascii")


def spectrum(paths: Paths, rel: str, decode=quality.decode_mono) -> dict:
    if ".." in PurePosixPath(rel).parts or fold(rel).split("/")[0] not in SERVED:
        raise ValueError(f"{rel} is not a music file Discjockey manages")
    f = paths.root / rel
    st = f.stat()
    folder = paths.cache / "spectrum"
    key = hashlib.sha1(fold(rel).encode()).hexdigest()
    cached = folder / f"{key}-{st.st_size}-{st.st_mtime_ns}.json"
    if cached.exists():
        try:
            return json.loads(cached.read_text(encoding="utf-8"))
        except ValueError:
            pass
    samples, sr = decode(f)
    data = {"cols": COLS, "bands": BANDS, "max_hz": sr // 2, "duration_s": round(len(samples) / sr, 3),
            "floor_db": FLOOR_DB, "data": encode(matrix(samples, sr))}
    folder.mkdir(parents=True, exist_ok=True)
    for old in folder.glob(f"{key}-*.json"):  # an older version of this file (e.g. before a swap)
        old.unlink(missing_ok=True)
    tmp = cached.with_suffix(".tmp")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    tmp.replace(cached)
    return data
