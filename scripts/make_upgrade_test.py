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

    uv run python scripts/make_upgrade_test.py --click mp3|m4a48|flac|aiff|aac [--bpm 120] [--same-edit] --into <scratch>
    uv run python scripts/make_upgrade_test.py --attach-upgrades --into <scratch>

`--click` writes a synthetic click track (a quiet noise bed and one decaying noise burst per beat, a few ms off the beat;
40 s) into the scratch folder, as `Click Test - Click <kind> <bpm> BPM (upgrade test).<ext>` with the artist and title
tags (the title carries the marker, so every file Discjockey derives from it does too). The kinds: mp3 (LAME, 320
kbit/s, 44.1 kHz), m4a48 (AAC 256 kbit/s in .m4a, 48 kHz), flac (16-bit 44.1 kHz), aiff (16-bit 44.1 kHz) and aac
(AAC in .m4a, 44.1 kHz, asked for 420 kbit/s: ffmpeg's encoder writes about 225 kbit/s on a click track). It also writes the lossless upgrade for it,
parked as `Upgrades ready/_Upgrade test/<same name>.aiff`: the same click track as a 16-bit 44.1 kHz AIFF with 30 ms of
silence in front (a swap must shift), or with `--same-edit` the very same audio (stage C). The upgrade is not yet
attached to anything: a library track exists only once Discjockey has imported the file. So it takes two calls with the
import in between: `--click ...`, then `folder add <scratch>` and its import, then `--attach-upgrades --into <scratch>`,
which parks the upgrade on each imported click track of that folder (measuring how the two lines up now). A stage that
needs no upgrade (stage D) simply does not attach it.

Removing it afterwards: remove the test track from rekordbox's collection, quit Discjockey, then delete by hand the
folders `Library/_Upgrade test/`, `Superseded/_Upgrade test/` and `Upgrades ready/_Upgrade test/` (whichever
exist), and remove the entry:

    uv run python scripts/make_upgrade_test.py --remove upgrade-test-<n>

`--remove` only takes a test entry this script made (its key and its "(upgrade test)" title) and changes no file.
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import zlib
from datetime import datetime
from pathlib import Path, PurePosixPath

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutagen.aiff import AIFF  # noqa: E402
from mutagen.id3 import COMM, TIT2, TPE1  # noqa: E402
from mutagen.mp4 import MP4  # noqa: E402

from discjockey import audio, library, quality, upgrades  # noqa: E402
from discjockey.align import compare_files  # noqa: E402
from discjockey.library import LockHeld, NoLibrary, Paths  # noqa: E402
from discjockey.names import fold  # noqa: E402
from discjockey.planner import ENTRY_KEYS  # noqa: E402

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
}
CLICK_SECONDS = 40  # the alignment check needs 30 s at least (align.MIN_DURATION_S)
CLICK_ARTIST = "Click Test"
UPGRADE_SHIFT_MS = 30  # the parked click upgrade without --same-edit starts this much later than the click file
UPGRADE_RATE = 44100  # parked upgrades are 16-bit 44.1 kHz AIFFs like the ones Discjockey makes


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


def remove(paths: Paths, track_id: str) -> str:
    """Removes a test entry this script made (no file is changed). Returns its title; ValueError for anything else."""
    state = library.open_state(paths)
    e = state["tracks"].get(track_id)
    if not track_id.startswith("upgrade-test-") or not e or not e["title"].endswith(SUFFIX):
        raise ValueError(f"{track_id} is not a test track this script made, so nothing was removed.")
    del state["tracks"][track_id]
    library.save_state(paths, state)
    return e["title"]


# --- click tracks (--click, --attach-upgrades) ---

def click_names(kind: str, bpm: float) -> tuple[str, str, str]:
    """(artist, title, file name) of a click track: `Artist - Title.<ext>` with the marker in the title."""
    title = f"Click {kind} {bpm:g} BPM{SUFFIX}"
    return CLICK_ARTIST, title, f"{CLICK_ARTIST} - {title}.{CLICK_KINDS[kind][0]}"


def _tag_aiff(path: Path, artist: str, title: str) -> None:
    f = AIFF(str(path))
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


def make_click(paths: Paths, kind: str, bpm: float, into: Path, same_edit: bool = False) -> tuple[Path, Path]:
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
    artist, title, name = click_names(kind, bpm)
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
        _ffmpeg_from_floats(x, sr, made, muxer, [*codec, "-metadata", f"title={title}", "-metadata", f"artist={artist}"])
        if ext == "aiff":
            _tag_aiff(made, artist, title)
        delay = None if same_edit else f"adelay=delays={round(UPGRADE_SHIFT_MS * sr / 1000)}S:all=1"
        _ffmpeg_from_floats(x, sr, twin, "aiff", ["-c:a", "pcm_s16be"], filters=delay, out_rate=UPGRADE_RATE)
        _tag_aiff(twin, artist, title)
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Make a test upgrade from one lossless AIFF in Library/, or click tracks.")
    p.add_argument("source", nargs="?",
                   help="a lossless AIFF in Library/, e.g. \"Library/Hard_Bounce/Artist - Title.aiff\"")
    p.add_argument("--root", type=Path, default=None, help="the music folder (default: the one Discjockey uses)")
    p.add_argument("--keep-lossy", choices=["m4a"], default=None, help="keep the lossy copy as an .m4a file")
    p.add_argument("--remove", metavar="ID", default=None, help="remove the test entry ID (its files go by hand)")
    p.add_argument("--click", choices=list(CLICK_KINDS), default=None,
                   help="make a click track of this kind in --into, and its parked lossless upgrade")
    p.add_argument("--bpm", type=float, default=120, help="the click track's tempo (default 120)")
    p.add_argument("--same-edit", action="store_true",
                   help="with --click: the parked upgrade is the very same audio (default: 30 ms later)")
    p.add_argument("--attach-upgrades", action="store_true",
                   help="park the upgrade of each imported click track in --into on its library track")
    p.add_argument("--into", type=Path, default=None, help="the scratch folder (--click, --attach-upgrades)")
    args = p.parse_args(argv)
    if sum(map(bool, (args.source, args.remove, args.click, args.attach_upgrades))) != 1:
        p.error("give one of: a source file, --click KIND, --attach-upgrades, --remove ID")
    if (args.click or args.attach_upgrades) and args.into is None:
        p.error("--click and --attach-upgrades need --into <scratch folder>")
    if args.same_edit and not args.click:
        p.error("--same-edit belongs to --click")
    resolved = library.resolve_paths()
    paths = Paths(args.root, support=resolved.support) if args.root else resolved.paths
    if paths is None:
        print("No music folder: choose one in Discjockey's Setup first, or pass --root.")
        return 2
    try:
        with library.run_lock(paths.lock):
            if args.remove:
                print(f"Removed the test entry {args.remove}: {remove(paths, args.remove)}")
            elif args.click:
                make_click(paths, args.click, args.bpm, args.into, args.same_edit)
            elif args.attach_upgrades:
                attach_upgrades(paths, args.into, datetime.now())
            else:
                make(paths, args.source, datetime.now(), args.keep_lossy)
    except LockHeld:
        print("Another Discjockey run is still going. Wait until it has finished.")
        return 3
    except (ValueError, NoLibrary) as e:
        print(e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
