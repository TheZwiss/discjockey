"""Make a test upgrade for a live rekordbox check, without touching anything that exists.

    uv run python scripts/make_upgrade_test.py "Library/Hard_Bounce/Artist - Title.aiff" [--keep-lossy m4a]

From one lossless AIFF in Library/ (only read, never changed) it makes a separate test track:
- Library/_Upgrade test/not_lossless/<stem> (upgrade test).aiff: a lossy copy (AAC 128 kbit/s, 16 kHz lowpass,
  converted back like a YouTube download) with 30 ms of extra silence at the start, so a swap must shift. With
  `--keep-lossy m4a` the lossy copy stays an .m4a (<stem> (upgrade test).m4a), as an own file bought or kept as
  AAC would be: New track then renders the AIFF lined up with rekordbox's timeline of the M4A (rekordbox stage A
  live check, plan §8 step 3);
- Upgrades ready/_Upgrade test/<stem> (upgrade test).aiff: the lossless copy, parked;
- a state entry `upgrade-test-<n>` (not in any playlist) with the measured alignment.
The distinct "(upgrade test)" name keeps rekordbox's search for missing files from linking the test entry to the
original file.

Click tracks (the live tests of the rekordbox stages B to D need files that are not made from a library track):

    uv run python scripts/make_upgrade_test.py --click mp3|m4a48|flac|aiff|aac|wav96 [--bpm 120] [--same-edit] [--messy-name] --into <scratch>
    uv run python scripts/make_upgrade_test.py --attach-upgrades --into <scratch>

`--click` writes a synthetic click track (a quiet noise bed and one decaying noise burst per beat, a few ms off the beat;
40 s) into the scratch folder, as `Click Test - Click <kind> <bpm> BPM (upgrade test).<ext>` with the artist and title
tags (the title carries the marker, so every file Discjockey derives from it does too). The kinds: mp3 (LAME, 320
kbit/s, 44.1 kHz), m4a48 (AAC 256 kbit/s in .m4a, 48 kHz), flac (16-bit 44.1 kHz), aiff (16-bit 44.1 kHz) and aac
(AAC in .m4a, 44.1 kHz, 420 kbit/s with Homebrew's `fdkaac`, about 225 kbit/s without it, see below). It also writes the lossless upgrade for it,
parked as `Upgrades ready/_Upgrade test/<same name>.aiff`: the same click track as a 16-bit 44.1 kHz AIFF with 30 ms of
silence in front (a swap must shift), or with `--same-edit` the very same audio (stage C). The upgrade is not yet
attached to anything: a library track exists only once Discjockey has imported the file. So it takes two calls with the
import in between: `--click ...`, then `folder add <scratch>` and its import, then `--attach-upgrades --into <scratch>`,
which parks the upgrade on each imported click track of that folder (measuring how the two lines up now). A stage that
needs no upgrade (stage D) simply does not attach it.

Stage D's click tracks also need `wav96` (24-bit 96 kHz WAV) and `--messy-name`, which names the file
`click_final (upgrade test).<ext>` instead of the tidy name (the marker stays, so `--clean` finds it; the title tag
still carries it). The AAC at 420 kbit/s (stage D, a file above the CDJs' 320 kbit/s limit) needs the Fraunhofer FDK AAC
encoder: when `fdkaac` is on PATH (`brew install fdk-aac-encoder`), `aac` is encoded with `fdkaac -b 420000` (AAC-LC,
about 420 kbit/s on a click track) and the artist and title tags are put on afterwards. Without it `aac` falls back to
ffmpeg's `aac`, which writes only about 225 kbit/s on a click track (the AudioToolbox encoder `aac_at` stops at about 322
kbit/s for 44.1 or 48 kHz stereo), and the script says so in its output.

Cleaning up afterwards: remove the test tracks from rekordbox's collection and quit rekordbox, remove the scratch folder
from Discjockey (`folder remove <scratch> --yes`), then

    uv run python scripts/make_upgrade_test.py --clean upgrade-test-<n> [--into <scratch>] [--json]
    uv run python scripts/make_upgrade_test.py --all-marked [--into <scratch>] [--json]

`--clean ID` and `--all-marked` refuse unless rekordbox is closed (exit 2) and no other Discjockey run holds the lock
(exit 3). They remove the test entries this script made (key `upgrade-test-<n>` and a title with the marker) from
library.db and move to the macOS Trash every file whose name carries " (upgrade test)" inside Library/, Superseded/,
Upgrades ready/ and each `--into` scratch folder (`--clean ID` only those named like that entry's track; `--all-marked`
all of them), then remove the `_Upgrade test/` folders once they are empty and list what was moved. A file without the
marker beside them stays, and so does one that carries it elsewhere than Discjockey's own names do (`Song (UPGRADE
TEST).mp3`, `My Song (upgrade test) remix.mp3`): the marker, in lower case, ends the name or is followed by ` (` or ` [`.
`--clean ID` is for a track made from a library file; click tracks (their entries are Discjockey's own) are cleaned
with `--all-marked --into <scratch>`. An `--into` that is a link, `/`, the home folder or a folder above the music
folder is refused (exit 2). The Trash is not a deletion: the script never deletes an audio file, whoever empties the
Trash does. It ends with `library scan` as the next step (`--json`: one object with `moved` and `next`).
"""
from __future__ import annotations

import argparse
import functools
import json
import os
import shutil
import subprocess
import sys
import unicodedata
import zlib
from datetime import datetime
from pathlib import Path, PurePosixPath

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutagen.aiff import AIFF  # noqa: E402
from mutagen.id3 import COMM, TIT2, TPE1  # noqa: E402
from mutagen.mp4 import MP4  # noqa: E402
from mutagen.wave import WAVE  # noqa: E402

from discjockey import audio, library, quality, upgrades  # noqa: E402
from discjockey.align import compare_files  # noqa: E402
from discjockey.library import LockHeld, NoLibrary, Paths  # noqa: E402
from discjockey.names import expected_stem, fold  # noqa: E402
from discjockey.planner import ENTRY_KEYS  # noqa: E402
from discjockey.rekordbox import process as rb_process  # noqa: E402

FOLDER = "_Upgrade test"
SUFFIX = " (upgrade test)"
EXTRA_SILENCE_MS = 30
LOSSY_COMMENT = "YouTube Music AAC · cutoff {khz:.1f} kHz (upgrade test copy)"

# --click: kind -> (file extension, ffmpeg's muxer, sample rate, ffmpeg codec arguments)
CLICK_KINDS = {
    "mp3": ("mp3", "mp3", 44100, ["-c:a", "libmp3lame", "-b:a", "320k"]),
    "m4a48": ("m4a", "ipod", 48000, ["-c:a", "aac", "-b:a", "256k"]),
    "flac": ("flac", "flac", 44100, ["-c:a", "flac", "-sample_fmt", "s16"]),
    "aiff": ("aiff", "aiff", 44100, ["-c:a", "pcm_s16be"]),
    "aac": ("m4a", "ipod", 44100, ["-c:a", "aac", "-b:a", "420k"]),
    "wav96": ("wav", "wav", 96000, ["-c:a", "pcm_s24le"]),
}
MESSY_STEM = "click_final"  # --messy-name: the file's stem before the marker (stage D: a name that needs the clean name)
CLICK_SECONDS = 40  # the alignment check needs 30 s at least (align.MIN_DURATION_S)
CLICK_ARTIST = "Click Test"
UPGRADE_SHIFT_MS = 30  # the parked click upgrade without --same-edit starts this much later than the click file
UPGRADE_RATE = 44100  # parked upgrades are 16-bit 44.1 kHz AIFFs like the ones Discjockey makes


@functools.lru_cache(maxsize=None)
def encoder_available(name: str) -> bool:
    """Whether the ffmpeg on PATH can encode with `name` (the app's own ffmpeg has no MP3 encoder, a Homebrew one does)."""
    try:
        out = subprocess.run(["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        return False
    return any(line.split()[1:2] == [name] for line in out.splitlines())


FDKAAC_KBPS = 420


def fdkaac_path() -> str | None:
    """The `fdkaac` on PATH (Homebrew's fdk-aac-encoder), or None."""
    return shutil.which("fdkaac")


def _click_encoder(kind: str) -> str:
    return CLICK_KINDS[kind][3][1]  # the codec arguments start with "-c:a", <encoder>


def _retitle(path: Path, title: str, comment: str | None = None) -> None:
    f = AIFF(str(path))
    if f.tags is None:
        f.add_tags()
    f.tags.add(TIT2(encoding=1, text=title))
    if comment:
        f.tags.delall("COMM")
        f.tags.add(COMM(encoding=1, lang="eng", desc="", text=comment))
    f.save(v2_version=3)


def clicks(seconds: float, sr: int, bpm: float = 120, seed: int = 1) -> np.ndarray:
    """A click track: a quiet noise bed and one click per beat from 0.5 s, each a decaying noise burst of its own
    length and level, a few ms off the beat (so its onset falls at a different place in rekordbox's 1/150 s columns
    each time), so a waveform comparison has one clear, sharp best shift. Copied from `clicks` in
    tests/rekordbox_helpers.py (a script cannot import tests/): keep the two the same."""
    rng = np.random.default_rng(seed)
    n = int(seconds * sr)
    x = 0.01 * rng.standard_normal(n)
    step = 60 / bpm
    for t in np.arange(0.5, seconds - 0.1, step):
        length = int(rng.integers(sr // 400, sr // 40))
        start = int((t + rng.uniform(-0.02, 0.02)) * sr)
        burst = rng.standard_normal(length) * np.exp(-np.arange(length) / (length / 4)) * rng.uniform(0.3, 0.9)
        x[start:start + length] += burst[:max(0, n - start)]
    return np.clip(x, -1, 1).astype(np.float32)


def _retitle_m4a(path: Path, artist: str, title: str, comment: str) -> None:
    f = MP4(str(path))
    if f.tags is None:
        f.add_tags()
    f.tags["\xa9nam"], f.tags["\xa9ART"], f.tags["\xa9cmt"] = [title], [artist], [comment]
    f.save()


def _make_lossy_m4a(src: Path, work: Path) -> Path:
    """The lossy copy kept as AAC in .m4a, the extra silence encoded in front."""
    out = work / "current.m4a"
    silence = round(EXTRA_SILENCE_MS * 44.1)
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0", "-map_metadata", "-1",
                    "-af", f"lowpass=f=16000,adelay=delays={silence}S:all=1", "-c:a", "aac", "-b:a", "128k",
                    str(out)], check=True)
    return out


def _make_lossy(src: Path, work: Path) -> Path:
    m4a, converted, out = work / "lossy.m4a", work / "lossy.aiff", work / "current.aiff"
    subprocess.run(["ffmpeg", "-nostdin", "-v", "error", "-y", "-i", str(src), "-map", "0:a:0",
                    "-af", "lowpass=f=16000", "-c:a", "aac", "-b:a", "128k", str(m4a)], check=True)
    audio.convert_to_aiff(m4a, converted)
    upgrades.build_staged(converted, out, -round(EXTRA_SILENCE_MS * 44.1))  # silence in front
    audio.copy_tags(src, out)
    return out


def _source_entry(state: dict, rel: str) -> dict:
    for e in state["tracks"].values():
        if e.get("path") and fold(e["path"]) == fold(rel):
            return e
    return {}


def _free_id(state: dict) -> str:
    n = 1
    while f"upgrade-test-{n}" in state["tracks"]:
        n += 1
    return f"upgrade-test-{n}"


def make(paths: Paths, source: str, now: datetime, keep_lossy: str | None = None) -> str:
    """Returns the new state key. `keep_lossy="m4a"` keeps the lossy copy as an .m4a. Raises ValueError with a plain
    message when something is in the way."""
    src = Path(source) if Path(source).is_absolute() else paths.root / source
    rel = src.resolve().relative_to(paths.root.resolve()).as_posix() if src.exists() else source
    if not src.is_file() or not fold(rel).startswith("library/") or src.suffix.lower() not in (".aiff", ".aif"):
        raise ValueError(f"{source} is not an AIFF file in Library/.")
    stem = src.stem + SUFFIX
    current_rel = f"Library/{FOLDER}/not_lossless/{stem}.{keep_lossy or 'aiff'}"
    parked_rel = f"Upgrades ready/{FOLDER}/{stem}.aiff"
    for taken in (current_rel, parked_rel, f"Library/{FOLDER}/{stem}.aiff"):
        if (paths.root / taken).exists():
            raise ValueError(f"{taken} already exists. Remove the earlier test first.")

    state = library.open_state(paths)
    original = _source_entry(state, rel)
    artist, _, title = src.stem.partition(" - ")
    artist, title = original.get("artist", artist), original.get("title", title or src.stem) + SUFFIX
    work = paths.tmp / "upgrade-test"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        current = _make_lossy_m4a(src, work) if keep_lossy else _make_lossy(src, work)
        cutoff = quality.analyze(current, lossy=True)
        comment = LOSSY_COMMENT.format(khz=(cutoff or 16000) / 1000)
        if keep_lossy:
            _retitle_m4a(current, artist, title, comment)
        else:
            _retitle(current, title, comment)
        parked = work / "parked.aiff"
        shutil.copyfile(src, parked)
        _retitle(parked, title)
        alignment = compare_files(current, parked)
        info = quality.probe(parked)
        track_id = _free_id(state)
        entry = dict.fromkeys(ENTRY_KEYS)
        entry.update(
            aliases=[], isrc=original.get("isrc"), artist=artist, title=title,
            duration_ms=round(info.duration_s * 1000), folder=FOLDER, path=current_rel, status="not_lossless",
            source="youtube_music", source_id="upgrade-test", source_format="aac", cutoff_hz=cutoff,
            rejected_sources=[], in_playlists=False, added=now.isoformat(timespec="seconds"),
            last_attempt=now.date().isoformat(), last_upgrade_check=now.date().isoformat(),
            upgrade={"file": parked_rel, "source": original.get("source") or "qobuz",
                     "source_id": original.get("source_id") or "upgrade-test",
                     "source_format": original.get("source_format") or info.codec,
                     "found": now.date().isoformat(), "alignment": alignment.to_dict()})
        library.run_op(paths, state, track_id, [(current.relative_to(paths.root).as_posix(), current_rel),
                                                 (parked.relative_to(paths.root).as_posix(), parked_rel)], entry)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Made test track {track_id}: {artist} - {title}")
    print(f"  lossy copy:  {current_rel} (cutoff {(cutoff or 0) / 1000:.1f} kHz, "
          f"{EXTRA_SILENCE_MS} ms of extra silence at the start)")
    print(f"  parked:      {parked_rel}")
    print(f"  alignment:   {alignment.text} ({alignment.result}, {alignment.offset_samples} samples)")
    print(f"  original {rel} was only read.")
    print(f"Test track id: {track_id} (you need it to remove the test again)")
    return track_id


# --- click tracks (--click, --attach-upgrades) ---

def click_names(kind: str, bpm: float, messy: bool = False) -> tuple[str, str, str]:
    """(artist, title, file name) of a click track: `Artist - Title.<ext>` with the marker in the title, or with
    `messy` `click_final (upgrade test).<ext>` (the tags stay the same, the marker stays in the name)."""
    title = f"Click {kind} {bpm:g} BPM{SUFFIX}"
    stem = f"{MESSY_STEM}{SUFFIX}" if messy else f"{CLICK_ARTIST} - {title}"
    return CLICK_ARTIST, title, f"{stem}.{CLICK_KINDS[kind][0]}"


def _tag_id3(path: Path, artist: str, title: str) -> None:
    """Artist and title as plain ID3 in an AIFF or a WAV (what Discjockey's import reads there)."""
    f = WAVE(str(path)) if path.suffix == ".wav" else AIFF(str(path))
    if f.tags is None:
        f.add_tags()
    f.tags.add(TPE1(encoding=1, text=artist))
    f.tags.add(TIT2(encoding=1, text=title))
    f.save(v2_version=3)


def _ffmpeg_from_floats(x: np.ndarray, sr: int, out: Path, muxer: str, args: list[str], *, filters: str | None = None,
                        out_rate: int | None = None) -> None:
    """`x` (mono floats at `sr`) as a stereo file at `out`; `filters` an ffmpeg -af chain, `out_rate` a new rate."""
    cmd = ["ffmpeg", "-nostdin", "-v", "error", "-y", "-f", "f32le", "-ar", str(sr), "-ac", "1", "-i", "-"]
    if filters:
        cmd += ["-af", filters]
    if out_rate:
        cmd += ["-ar", str(out_rate)]
    try:
        subprocess.run(cmd + ["-ac", "2", *args, "-f", muxer, str(out)], input=np.asarray(x, "<f4").tobytes(),
                       check=True, capture_output=True)
    except subprocess.CalledProcessError as e:
        raise ValueError(f"ffmpeg could not write {out.name}: {e.stderr.decode(errors='replace').strip()[-300:]}") from e


def _click_audio(kind: str, bpm: float) -> tuple[np.ndarray, int]:
    """The click track's audio and its rate. The same kind and bpm give the same audio every time."""
    sr = CLICK_KINDS[kind][2]
    return clicks(CLICK_SECONDS, sr, bpm, zlib.crc32(f"{kind} {bpm:g}".encode())), sr


def make_click(paths: Paths, kind: str, bpm: float, into: Path, same_edit: bool = False,
               messy_name: bool = False) -> tuple[Path, Path]:
    """Writes the click track into `into` and its lossless upgrade into Upgrades ready/_Upgrade test/ (nothing exists
    to attach it to until the click track is imported: `attach_upgrades`). Returns both paths; ValueError with a plain
    message when something is in the way."""
    if kind not in CLICK_KINDS:
        raise ValueError(f"{kind} is not a click track kind. Choose one of: {', '.join(CLICK_KINDS)}.")
    if not 30 <= bpm <= 300:
        raise ValueError("--bpm must be between 30 and 300.")
    here = into.resolve()
    for taken in ("Library", "Superseded", "Upgrades ready", ".discjockey"):
        if here == (paths.root / taken).resolve() or (paths.root / taken).resolve() in here.parents:
            raise ValueError(f"{into} is inside {taken}/. Make the click track in a scratch folder outside the music "
                             "folder's own folders.")
    fdk = fdkaac_path() if kind == "aac" else None  # the one kind with a second encoder: ffmpeg's only reaches ~225 kbit/s
    if not fdk and not encoder_available(_click_encoder(kind)):
        works = [k for k in CLICK_KINDS if encoder_available(_click_encoder(k))]
        raise ValueError(f"This ffmpeg has no {_click_encoder(kind)} encoder, so --click {kind} cannot be made. "
                         f"Kinds that work here: {', '.join(works) or 'none'}.")
    artist, title, name = click_names(kind, bpm, messy_name)
    ext, muxer, _, codec = CLICK_KINDS[kind]
    target = into / name
    parked = paths.root / "Upgrades ready" / FOLDER / f"{target.stem}.aiff"
    for taken in (target, parked):
        if taken.exists():
            raise ValueError(f"{taken} already exists. Remove the earlier test first.")
    x, sr = _click_audio(kind, bpm)
    work = paths.tmp / "upgrade-test"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        made, twin = work / f"click.{ext}", work / "upgrade.aiff"
        if fdk:
            wav = work / "click.wav"
            _ffmpeg_from_floats(x, sr, wav, "wav", ["-c:a", "pcm_s16le"])
            try:
                subprocess.run([fdk, "-b", str(FDKAAC_KBPS * 1000), "-o", str(made), str(wav)], check=True,
                               capture_output=True, stdin=subprocess.DEVNULL)
            except (OSError, subprocess.CalledProcessError) as e:
                detail = getattr(e, "stderr", b"") or b""
                raise ValueError(f"fdkaac could not write {made.name}: {detail.decode(errors='replace').strip()[-300:] or e}") from e
            f = MP4(str(made))
            if f.tags is None:
                f.add_tags()
            f.tags["\xa9nam"], f.tags["\xa9ART"] = [title], [artist]
            f.save()
        else:
            _ffmpeg_from_floats(x, sr, made, muxer, [*codec, "-metadata", f"title={title}", "-metadata", f"artist={artist}"])
        if ext in ("aiff", "wav"):
            _tag_id3(made, artist, title)
        delay = None if same_edit else f"adelay=delays={round(UPGRADE_SHIFT_MS * sr / 1000)}S:all=1"
        _ffmpeg_from_floats(x, sr, twin, "aiff", ["-c:a", "pcm_s16be"], filters=delay, out_rate=UPGRADE_RATE)
        _tag_id3(twin, artist, title)
        into.mkdir(parents=True, exist_ok=True)
        parked.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(made), target)
        shutil.move(str(twin), parked)
    finally:
        shutil.rmtree(work, ignore_errors=True)
    print(f"Made the click track {target}")
    print(f"  {kind}, {bpm:g} BPM, {CLICK_SECONDS} s; its lossless upgrade "
          f"({'the same audio' if same_edit else f'{UPGRADE_SHIFT_MS} ms later'}) waits at "
          f"{parked.relative_to(paths.root).as_posix()}")
    if kind == "aac":
        print(f"  the AAC is {FDKAAC_KBPS} kbit/s (fdkaac)" if fdk else
              f"  the AAC is only about 225 kbit/s (ffmpeg's encoder); `brew install fdk-aac-encoder` gives {FDKAAC_KBPS}")
    print(f"Next: add {into} to Discjockey's folders and import it, then run this script with "
          f"--attach-upgrades --into {into}")
    return target, parked


def attach_upgrades(paths: Paths, into: Path, now: datetime) -> list[str]:
    """Parks the upgrade `make_click` wrote on each imported click track of `into` (a song of Discjockey's library
    whose file is in `into`, carries the marker and has none yet), with how the two line up now. Returns their ids;
    ValueError when there is nothing to attach to."""
    state = library.open_state(paths)
    here = into.resolve()
    attached, missing = [], []
    for track_id, e in sorted(state["tracks"].items()):
        path = e.get("path")
        if not path or not e.get("title", "").endswith(SUFFIX) or e.get("upgrade"):
            continue
        current = Path(path) if PurePosixPath(path).is_absolute() else paths.root / path
        if here not in current.resolve().parents:
            continue
        parked_rel = f"Upgrades ready/{FOLDER}/{current.stem}.aiff"
        if not (paths.root / parked_rel).is_file():
            missing.append(current.name)
            continue
        alignment = compare_files(current, paths.root / parked_rel)
        state["tracks"][track_id] = {**e, "upgrade": {
            "file": parked_rel, "source": "qobuz", "source_id": "upgrade-test", "source_format": "flac",
            "found": now.date().isoformat(), "alignment": alignment.to_dict()}}
        attached.append(track_id)
        print(f"Parked the lossless upgrade on {track_id}: {current.name} ({alignment.text}, "
              f"{alignment.offset_samples} samples)")
    if attached:
        library.save_state(paths, state)
    for name in missing:
        print(f"No parked upgrade was found for {name}: make it with --click first.")
    if not attached:
        raise ValueError(f"No imported click track without an upgrade was found in {into}. Add the folder to "
                         "Discjockey and import it first (folder add), and make the click track with --click.")
    return attached


# --- clean-up (--clean, --all-marked) ---

REKORDBOX_OPEN = ("rekordbox is open. Remove the test tracks from its collection and quit it, then run this "
                  "again.")
LOCK_HELD = "Another Discjockey run is still going. Wait until it has finished."
ENTRY_PREFIX = "upgrade-test-"


class RekordboxOpen(ValueError):
    """rekordbox was found open (checked again once the lock is held and right before the first file moves)."""


class CleanFailed(ValueError):
    """A file could not be moved to the Trash; `moved` is what had gone before it (nothing else was changed)."""

    def __init__(self, message: str, moved: list[Path]):
        super().__init__(message)
        self.moved = moved


def rekordbox_open() -> bool:
    return rb_process.running()


def trash_item(path: Path) -> None:
    """Moves one file to the macOS Trash (the person empties it; nothing is deleted). Through NSFileManager when
    pyobjc is there (pywebview brings it), else by asking the Finder. Raises OSError when it cannot."""
    try:
        from Foundation import NSURL, NSFileManager
    except ImportError:
        script = ["on run argv", 'tell application "Finder" to delete (POSIX file (item 1 of argv) as alias)', "end run"]
        r = subprocess.run(["/usr/bin/osascript", *(a for line in script for a in ("-e", line)), str(path.absolute())],
                           capture_output=True, text=True)
        if r.returncode != 0:
            raise OSError(r.stderr.strip() or "the Finder would not move it")
        return
    ok, _, error = NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_(
        NSURL.fileURLWithPath_(str(path)), None, None)
    if not ok:
        raise OSError(str(error.localizedDescription()) if error is not None else "the Trash would not take it")


def own_entry(state: dict, track_id: str) -> dict:
    """The state entry of a test track this script made (key `upgrade-test-<n>`, a title with the marker);
    ValueError for anything else."""
    e = state["tracks"].get(track_id)
    if not track_id.startswith(ENTRY_PREFIX) or not e or not e["title"].endswith(SUFFIX):
        raise ValueError(f"{track_id} is not a test track this script made, so nothing was changed.")
    return e


def carries_marker(name: str) -> bool:
    """True when the file name carries the marker the way Discjockey's own names put it: at the end of the stem
    (`Artist - Title (upgrade test).aiff`), or followed by ` (` or ` [` (a Superseded `(lossy)` or `(2)`, a
    collision `[tag]`). The marker is written in lower case and matched as written: a person's own
    `Song (UPGRADE TEST).mp3` or `My Song (upgrade test) remix.mp3` is not ours."""
    stem = Path(unicodedata.normalize("NFC", name)).stem
    i = stem.find(SUFFIX)
    while i >= 0:
        rest = stem[i + len(SUFFIX):]
        if rest == "" or rest.startswith((" (", " [")):
            return True
        i = stem.find(SUFFIX, i + 1)
    return False


def marked_files(roots: list[Path], stems: set[str] | None = None) -> list[Path]:
    """The files under `roots` whose names carry the marker (`carries_marker`; with `stems`: only those whose name
    starts with one of them, a song's clean name, so its Superseded and collision names count too). Symbolic links
    are not followed or taken; each file once; the paths are absolute."""
    found: dict[str, Path] = {}
    folded_stems = None if stems is None else tuple(fold(s) for s in stems)
    for root in roots:
        for here, _, names in os.walk(root.absolute(), followlinks=False):
            for name in names:
                path = Path(here) / name
                if (carries_marker(name) and (folded_stems is None or fold(name).startswith(folded_stems))
                        and not path.is_symlink()):
                    found.setdefault(str(path.resolve()), path)
    return sorted(found.values())


def entry_stems(e: dict) -> set[str]:
    """The names a test entry's files start with: its song's clean name, and the stems of its current and parked
    files (a collision-tagged or differently named source file), each cut at the end of its first marker."""
    stems = {expected_stem(e["artist"], e["title"])}
    files = [e.get("path"), (e.get("upgrade") or {}).get("file")]
    for rel in files:
        stem = Path(rel).stem if rel else ""
        i = stem.find(SUFFIX)
        if i >= 0:
            stems.add(stem[: i + len(SUFFIX)])
    return stems


def check_scratch(paths: Paths, folder: Path) -> None:
    """ValueError (nothing changed) unless `folder` is a scratch folder of its own: not a symbolic link, not `/`,
    not the home folder and not a folder that holds the home or the music folder."""
    if folder.is_symlink():
        raise ValueError(f"{folder} is not a scratch folder of its own: it is a link to another folder. Give the "
                         "folder itself.")
    here = folder.resolve()
    for name, big in (("the home folder", Path.home().resolve()), ("the music folder", paths.root.resolve())):
        if here == big or here in big.parents:
            raise ValueError(f"{folder} is not a scratch folder of its own: it is or holds {name}. Give the folder "
                             "the test files are in.")
    if here == Path(here.anchor):
        raise ValueError(f"{folder} is not a scratch folder of its own: it is the top of the disk.")


def drop_empty_folders(paths: Paths) -> list[Path]:
    """Removes the `_Upgrade test/` folders of Library/, Superseded/ and Upgrades ready/ (and the folders in them)
    that hold nothing now; a folder with anything in it stays. Returns the ones it removed."""
    gone = []
    for top in (paths.library, paths.root / "Superseded", paths.root / "Upgrades ready"):
        base = top / FOLDER
        if not base.is_dir() or base.is_symlink():
            continue
        for here, _, _ in os.walk(base, topdown=False):
            try:
                os.rmdir(here)
                gone.append(Path(here))
            except OSError:
                pass
    return gone


def clean(paths: Paths, entry: str | None, into: list[Path]) -> dict:
    """The clean-up: moves the marked files to the Trash, then removes the test entries from library.db, then the
    empty `_Upgrade test/` folders. `entry`: one test track (its entry and the files named like its song), None for
    everything marked. `into`: the scratch folders to look in besides Library/, Superseded/ and Upgrades ready/.
    Returns {"moved", "entries", "folders", "next"}; ValueError when `entry` is no test track, a folder is missing or is no
    scratch folder of its own, or rekordbox opened (nothing changed); CleanFailed when the Trash would not take a file (the entries stay, so running it again
    finishes)."""
    state = library.open_state(paths)
    if entry is not None:
        e = own_entry(state, entry)
        entries, stems = [entry], entry_stems(e)
    else:
        entries = [k for k, e in state["tracks"].items() if k.startswith(ENTRY_PREFIX) and e["title"].endswith(SUFFIX)]
        stems = None
    for folder in into:
        if not folder.is_dir():
            raise ValueError(f"{folder} is not a folder.")
        check_scratch(paths, folder)
    roots = [paths.library, paths.root / "Superseded", paths.root / "Upgrades ready", *into]
    files = marked_files([r for r in roots if r.is_dir()], stems)
    if files and rekordbox_open():  # opened since the first look: nothing has moved yet
        raise RekordboxOpen(REKORDBOX_OPEN)
    moved: list[Path] = []
    for f in files:
        try:
            trash_item(f)
        except OSError as err:
            raise CleanFailed(f"{f.name} could not be moved to the Trash ({err}). Nothing else was changed: run it "
                              "again to finish.", moved) from err
        moved.append(f)
    titles = {k: state["tracks"].pop(k)["title"] for k in entries}
    if titles:
        library.save_state(paths, state)
    return {"moved": moved, "entries": titles, "folders": drop_empty_folders(paths),
            "next": [{"run": "library scan", "why": "the files are gone from the folders: let Discjockey see it"}]}


def shown(paths: Paths, p: Path) -> str:
    try:
        return p.resolve().relative_to(paths.root.resolve()).as_posix()
    except ValueError:
        return str(p)


def print_clean(paths: Paths, done: dict, as_json: bool) -> None:
    if as_json:
        print(json.dumps({"ok": True, "moved": [str(p) for p in done["moved"]], "entries": list(done["entries"]),
                          "folders": [str(p) for p in done["folders"]], "next": done["next"]}, indent=2))
        return
    if done["moved"]:
        print(f"Moved {len(done['moved'])} file(s) to the Trash (empty it yourself when you are sure):")
        for p in done["moved"]:
            print(f"  {shown(paths, p)}")
    else:
        print("No file with the marker was found.")
    for k, title in done["entries"].items():
        print(f"Removed the test entry {k}: {title}")
    for p in done["folders"]:
        print(f"Removed the empty folder {shown(paths, p)}")
    for n in done["next"]:
        print(f"Next: {n['run']}  ({n['why']})")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Make a test upgrade from one lossless AIFF in Library/, or click tracks.")
    p.add_argument("source", nargs="?",
                   help="a lossless AIFF in Library/, e.g. \"Library/Hard_Bounce/Artist - Title.aiff\"")
    p.add_argument("--root", type=Path, default=None, help="the music folder (default: the one Discjockey uses)")
    p.add_argument("--keep-lossy", choices=["m4a"], default=None, help="keep the lossy copy as an .m4a file")
    p.add_argument("--clean", nargs="?", const="", metavar="ID", default=None,
                   help="clean up after the tests: remove the test entry ID (or, with --all-marked, all of them) "
                        "and move the files with the marker to the Trash (rekordbox closed)")
    p.add_argument("--all-marked", action="store_true", help="--clean for every test entry and every marked file")
    p.add_argument("--json", action="store_true", help="with --clean: the answer as one JSON object")
    p.add_argument("--click", choices=list(CLICK_KINDS), default=None,
                   help="make a click track of this kind in --into, and its parked lossless upgrade")
    p.add_argument("--bpm", type=float, default=120, help="the click track's tempo (default 120)")
    p.add_argument("--same-edit", action="store_true",
                   help="with --click: the parked upgrade is the very same audio (default: 30 ms later)")
    p.add_argument("--attach-upgrades", action="store_true",
                   help="park the upgrade of each imported click track in --into on its library track")
    p.add_argument("--messy-name", action="store_true",
                   help="with --click: name the file click_final (upgrade test) instead of the tidy name")
    p.add_argument("--into", type=Path, action="append", default=None,
                   help="the scratch folder (--click, --attach-upgrades); with --clean, a scratch folder to clean "
                        "too (repeat for more)")
    args = p.parse_args(argv)
    cleaning = args.clean is not None or args.all_marked
    if sum(map(bool, (args.source, cleaning, args.click, args.attach_upgrades))) != 1:
        p.error("give one of: a source file, --click KIND, --attach-upgrades, --clean ID, --all-marked")
    if cleaning and bool(args.clean) == args.all_marked:
        p.error("--clean takes a test entry ID, or give --all-marked alone")
    if (args.click or args.attach_upgrades) and (args.into is None or len(args.into) != 1):
        p.error("--click and --attach-upgrades need one --into <scratch folder>")
    if args.same_edit and not args.click:
        p.error("--same-edit belongs to --click")
    if args.messy_name and not args.click:
        p.error("--messy-name belongs to --click")
    if args.json and not cleaning:
        p.error("--json belongs to --clean")
    if args.into and not (cleaning or args.click or args.attach_upgrades):
        p.error("--into belongs to --click, --attach-upgrades and --clean")
    resolved = library.resolve_paths()
    paths = Paths(args.root, support=resolved.support) if args.root else resolved.paths
    if paths is None:
        print("No music folder: choose one in Discjockey's Setup first, or pass --root.")
        return 2
    try:
        with library.run_lock(paths.lock):
            if cleaning:
                if rekordbox_open():
                    raise RekordboxOpen(REKORDBOX_OPEN)
                print_clean(paths, clean(paths, args.clean or None, args.into or []), args.json)
            elif args.click:
                make_click(paths, args.click, args.bpm, args.into[0], args.same_edit, args.messy_name)
            elif args.attach_upgrades:
                attach_upgrades(paths, args.into[0], datetime.now())
            else:
                make(paths, args.source, datetime.now(), args.keep_lossy)
    except LockHeld:
        print(json.dumps({"ok": False, "message": LOCK_HELD}) if args.json else LOCK_HELD)
        return 3
    except CleanFailed as e:
        if args.json:
            print(json.dumps({"ok": False, "message": str(e), "moved": [str(m) for m in e.moved]}))
        else:
            print(e)
            for m in e.moved:
                print(f"  moved before it stopped: {shown(paths, m)}")
        return 2
    except (RekordboxOpen, ValueError, NoLibrary) as e:
        print(json.dumps({"ok": False, "message": str(e)}) if args.json else e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
