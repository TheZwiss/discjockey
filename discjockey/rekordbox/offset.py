"""One answer per file: where rekordbox's timeline sits for it (`timeline_offset`; design rekordbox-repoint §3,
plan stage A §1.2, §1.7).

`TimelineOffset.samples` is `d` in 44.1 kHz samples (`round(d_s × 44100)`): a moment at `t` in ffmpeg's default
decode of the file sits at `t + d` on rekordbox's timeline. None means unknown, and `why` says how it was found or why
not:

- `no_rekordbox`: no rekordbox library on this Mac: d = 0.
- `unreadable`: rekordbox's library can't be read (or rekordbox holds it) and the file's format can have a trim:
  unknown. A PCM, FLAC or ALAC file answers `format` instead (its d can only be 0).
- `not_in_rekordbox`: no rekordbox track holds the file: d = 0.
- Otherwise each track is looked at. One without cues and without a grid doesn't care where the audio sits (not
  measured). One with a waveform (`PWV3` in its `.EXT`) is measured and snapped to the file's expected values
  (`timing.measure`, `decide`). One without: a format whose d can only be 0 → 0; else `not_analysed`. The tracks that care must land on one value.
  The answer is `measured` when a measurement decided it, `format` when the format did, `no_cues` when no track
  cares (d = 0), and `not_analysed` or `timing` (unknown) when a track couldn't be placed or they disagree;
  `not_analysed` wins over `timing` (analysing the track in rekordbox is what helps first).

`entries` holds every track's findings for the preview and stage B's batch JSON. The old file is decoded once, only
when some track has a waveform; its start trim is probed only for a format that can have one. Reads rekordbox's
library read-only and its analysis files; writes nothing. Raises `RuntimeError` (or `probe.ProbeError`) when ffmpeg
can't read the file.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

import numpy as np

from .. import quality
from . import anlz, master, probe, process, timing
from .locate import Place, locate
from .master import Entry, Status, Unreadable

RATE = 44100
Why = Literal["no_rekordbox", "not_in_rekordbox", "format", "no_cues", "measured", "not_analysed", "timing",
              "unreadable"]


@dataclass(frozen=True)
class EntryTiming:
    entry: Entry
    cues: int
    grid: bool               # the analysis holds a beat grid
    pwv3: bool               # the analysis holds a waveform to measure
    offset_ms: float | None  # measured
    expected_ms: float | None  # the expected value it snapped to
    score: float | None


@dataclass(frozen=True)
class TimelineOffset:
    samples: int | None
    why: Why
    rekordbox: Status
    entries: list[EntryTiming]


_LOCATE = object()


def analysis_files(place: Place, entry: Entry) -> tuple[Path, Path] | None:
    """The track's `.DAT` and `.EXT`: `AnalysisDataPath` (it starts with `/PIONEER/USBANLZ/…`) under `share`."""
    if not entry.analysis_path:
        return None
    dat = place.share / entry.analysis_path.lstrip("/")
    return dat, dat.with_suffix(".EXT")


def _analysis(place: Place, entry: Entry) -> tuple[bool, np.ndarray | None]:
    """Whether the track has a beat grid, and its waveform heights (None without one)."""
    files = analysis_files(place, entry)
    if files is None:
        return False, None
    dat, ext = (anlz.read(f) for f in files)
    grid = dat is not None and anlz.beat_count(dat) > 0
    heights = None if ext is None else anlz.pwv3_heights(ext)
    if heights is not None and len(heights) == 0:
        heights = None
    return grid, heights


def timeline_offset(old_file: Path, *, place=_LOCATE, running: Callable[[], bool] | None = None,
                    decode: Callable | None = None, trim: Callable | None = None,
                    probe_audio: Callable | None = None) -> TimelineOffset:
    """Where rekordbox's timeline sits for `old_file`. `place` defaults to `locate()`, `running` to
    `process.running`, `decode` to `quality.decode_mono`, `trim` to `probe.start_trim`, `probe_audio` to
    `quality.probe`, each looked up at call time."""
    place = locate() if place is _LOCATE else place
    is_running = (running or process.running)()
    rb = master.status(place, lambda: is_running)
    info = (probe_audio or quality.probe)(old_file)
    zero = timing.zero_only(info.codec)
    if rb.state == "none":
        return TimelineOffset(0, "no_rekordbox", rb, [])
    try:
        if rb.state != "ready" or rb.problem == "busy":
            raise Unreadable(rb.problem or "key")
        with master.open_read(place, is_running) as db:
            entries = db.entries_for(Path(os.path.abspath(old_file)))
            cues = db.cue_counts([e.id for e in entries])
    except Unreadable:
        return TimelineOffset(0 if zero else None, "format" if zero else "unreadable", rb, [])
    if not entries:
        return TimelineOffset(0, "not_in_rekordbox", rb, [])

    expected_s: list[float] | None = None
    audio: tuple[np.ndarray, int] | None = None
    findings: list[EntryTiming] = []
    values: list[float] = []
    reasons: set[str] = set()
    measured_any = False
    for entry in entries:
        grid, heights = _analysis(place, entry)
        n_cues = cues.get(entry.id, 0)
        if not n_cues and not grid:  # nothing on rekordbox's timeline to keep in place
            findings.append(EntryTiming(entry, n_cues, grid, heights is not None, None, None, None))
            continue
        if heights is None:
            findings.append(EntryTiming(entry, n_cues, grid, False, None, None, None))
            if zero:
                values.append(0.0)
            else:
                reasons.add("not_analysed")
            continue
        if audio is None:
            audio = (decode or quality.decode_mono)(old_file)
        if expected_s is None:
            trimmed = 0 if zero else (trim or probe.start_trim)(old_file, info.codec)
            expected_s = timing.expected(info.codec, info.sample_rate, trimmed)
        got = timing.measure(heights, *audio)
        decided = timing.decide(got, expected_s) if got is not None else timing.Decided(None, "timing")
        findings.append(EntryTiming(
            entry, n_cues, grid, True,
            None if got is None else got.offset_s * 1000,
            None if decided.offset_s is None else decided.offset_s * 1000,
            None if got is None else got.score))
        if decided.offset_s is None:
            reasons.add("timing")
        else:
            values.append(decided.offset_s)
            measured_any = True

    for reason in ("not_analysed", "timing"):
        if reason in reasons:
            return TimelineOffset(None, reason, rb, findings)
    if not values:
        return TimelineOffset(0, "no_cues", rb, findings)
    agreed = timing.agree(values)
    if agreed.offset_s is None:
        return TimelineOffset(None, "timing", rb, findings)
    return TimelineOffset(round(agreed.offset_s * RATE), "measured" if measured_any else "format", rb, findings)
