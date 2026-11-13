"""Pure: what the club players refuse (issue 33 stage D, plan rekordbox stage D §0.4 and §1.4). `cdj_problem` says, for
an own file's stored facts (`models.FileAudio`) and extension, whether the CDJ-3000 or the CDJ-2000NXS2 would refuse it
or stutter on it, with the words To-do's row (`short`) and the panels (`words`) use.

Only what those two players can't play is flagged: FLAC, ALAC and 88.2/96 kHz files play on both and are not. Players
that stop at 48 kHz or lack FLAC/ALAC (XDJ-RX3, XDJ-XZ, XDJ-700, CDJ-2000NXS) are served by Make all lossless files
AIFF, not by this rule. A value that is missing never matches its rule, so a file whose facts are partly unknown is
never flagged for what isn't known.

The limits (checked 2026-11-13 against Pioneer DJ's CDJ-3000 specifications and the CDJ-2000NXS2 operating
instructions, "Playable music file formats"; the CDJ-3000 manual's own table was not reachable, so the NXS2's, which
the CDJ-3000 page matches in formats, hold): MP3 32-320 kbps at 32/44.1/48 kHz; AAC 16-320 kbps up to 48 kHz; WAV, AIFF,
FLAC and ALAC 16- and 24-bit at 44.1-96 kHz. Not flagged either, because ffprobe can't tell it cheaply: a
WAVE_FORMAT_EXTENSIBLE header (docs/issues.md).
"""
from __future__ import annotations

from dataclasses import dataclass

from .models import CONTAINER_NAMES, FORMAT_NAMES, FileAudio

REASONS = ("format", "bitrate", "bits", "rate_high", "rate_low")

MAX_LOSSY_KBPS = 320
MAX_LOSSY_RATE = 48_000
MAX_LOSSLESS_RATE = 96_000
MIN_LOSSLESS_RATE = 44_100
LOSSLESS_BITS = (16, 24)

_LOSSY = ("mp3", "aac")
_LOSSLESS_NAMED = ("flac", "alac")  # lossless codecs that are not `pcm_*`; any PCM is a format the players read
# (its depth is the `bits` rule's); a codec name the words know beyond models.FORMAT_NAMES
_NAMES = {**FORMAT_NAMES, "wmav1": "WMA", "wmav2": "WMA", "wmapro": "WMA", "wmalossless": "WMA", "ac3": "AC-3",
          "eac3": "E-AC-3", "dts": "DTS", "wavpack": "WavPack", "ape": "APE", "tta": "TTA", "dsd_lsbf": "DSD",
          "dsd_msbf": "DSD", "dsd_lsbf_planar": "DSD", "dsd_msbf_planar": "DSD", "amr_nb": "AMR", "amr_wb": "AMR"}


@dataclass(frozen=True)
class CdjProblem:
    """Why a CDJ refuses a file: `reason` one of REASONS, `short` To-do's one line, `words` the sentence for panels."""
    reason: str
    short: str
    words: str


def _is_pcm(codec: str) -> bool:
    return codec.startswith("pcm_")


def format_name(audio: FileAudio, ext: str) -> str:
    """How the words name the file: its container for PCM (WAV, AIFF), else its codec (MP3, AAC, FLAC, Opus ...)."""
    codec = audio.codec
    if _is_pcm(codec):
        return CONTAINER_NAMES.get(ext.lower(), "PCM")
    return _NAMES.get(codec, codec.upper())


def _khz(rate: int) -> str:
    return f"{rate / 1000:g}"


def _depth(audio: FileAudio) -> str:
    """"24-bit", "32-bit float": the depth the `bits` rule names."""
    kind = " float" if audio.codec.startswith("pcm_f") else ""  # pcm_f32le, pcm_f64be
    return f"{audio.bits}-bit{kind}"


def cdj_problem(audio: FileAudio, ext: str) -> CdjProblem | None:
    """The first rule of plan §1.4 the file breaks, else None; `audio` the file's stored facts, `ext` its extension
    (lower case, with the dot)."""
    codec = audio.codec
    pcm = _is_pcm(codec)
    lossy = codec in _LOSSY
    lossless = pcm or codec in _LOSSLESS_NAMED
    name = format_name(audio, ext)
    if not (lossy or lossless):
        return CdjProblem("format", f"{name} · CDJs don't play it", f"CDJs don't play {name} files.")
    if lossy and audio.kbps is not None and audio.kbps > MAX_LOSSY_KBPS:
        return CdjProblem(
            "bitrate", f"{name} {audio.kbps} kbps · CDJs stop at {MAX_LOSSY_KBPS}",
            f"{name} at {audio.kbps} kbps: CDJs play {name} only up to {MAX_LOSSY_KBPS} kbps, so it may not load or "
            "may stutter.")
    if lossless and audio.bits is not None and audio.bits not in LOSSLESS_BITS:
        depth = _depth(audio)
        return CdjProblem("bits", f"{name} {depth} · CDJs play 16/24-bit",
                          f"{name} {depth}: CDJs play only 16- and 24-bit files.")
    if audio.rate is not None:
        limit = MAX_LOSSY_RATE if lossy else MAX_LOSSLESS_RATE
        if audio.rate > limit:
            return CdjProblem("rate_high", f"{name} {_khz(audio.rate)} kHz · CDJs stop at {_khz(limit)} kHz",
                              f"{name} at {_khz(audio.rate)} kHz: CDJs play {name} only up to {_khz(limit)} kHz.")
        if lossless and audio.rate < MIN_LOSSLESS_RATE:
            return CdjProblem("rate_low", f"{name} {_khz(audio.rate)} kHz · CDJs need 44.1 kHz",
                              f"{name} at {_khz(audio.rate)} kHz: CDJs play {name} from 44.1 kHz.")
    return None
