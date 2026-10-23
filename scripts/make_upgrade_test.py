"""Make a test upgrade for the live rekordbox check (plan Task 29), without touching anything that exists.

    uv run python scripts/make_upgrade_test.py "Library/Hard_Bounce/Vatoz Locoz - Gimme Gimme.aiff"

From one lossless AIFF in Library/ (only read, never changed) it makes a separate test track:
- Library/_Upgrade test/not_lossless/<stem> (upgrade test).aiff: a lossy copy (AAC 128 kbit/s, 16 kHz lowpass,
  converted back like a YouTube download) with 30 ms of extra silence at the start, so a swap must shift;
- Upgrades ready/_Upgrade test/<stem> (upgrade test).aiff: the lossless copy, parked;
- a state entry `upgrade-test-<n>` (not in any playlist) with the measured alignment.
The distinct "(upgrade test)" name keeps rekordbox's search for missing files from linking the test entry to the
original file. Remove it all afterwards by hand (plan Task 29, step 6).
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from mutagen.aiff import AIFF  # noqa: E402
from mutagen.id3 import COMM, TIT2  # noqa: E402

from discjockey import audio, library, quality, upgrades  # noqa: E402
from discjockey.align import compare_files  # noqa: E402
from discjockey.library import LockHeld, NoLibrary, Paths  # noqa: E402
from discjockey.names import fold  # noqa: E402
from discjockey.planner import ENTRY_KEYS  # noqa: E402

FOLDER = "_Upgrade test"
SUFFIX = " (upgrade test)"
EXTRA_SILENCE_MS = 30
LOSSY_COMMENT = "YouTube Music AAC · cutoff {khz:.1f} kHz (upgrade test copy)"


def _retitle(path: Path, title: str, comment: str | None = None) -> None:
    f = AIFF(str(path))
    if f.tags is None:
        f.add_tags()
    f.tags.add(TIT2(encoding=1, text=title))
    if comment:
        f.tags.delall("COMM")
        f.tags.add(COMM(encoding=1, lang="eng", desc="", text=comment))
    f.save(v2_version=3)


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


def make(paths: Paths, source: str, now: datetime) -> str:
    """Returns the new state key. Raises ValueError with a plain message when something is in the way."""
    src = Path(source) if Path(source).is_absolute() else paths.root / source
    rel = src.resolve().relative_to(paths.root.resolve()).as_posix() if src.exists() else source
    if not src.is_file() or not fold(rel).startswith("library/") or src.suffix.lower() not in (".aiff", ".aif"):
        raise ValueError(f"{source} is not an AIFF file in Library/.")
    stem = src.stem + SUFFIX
    current_rel = f"Library/{FOLDER}/not_lossless/{stem}.aiff"
    parked_rel = f"Upgrades ready/{FOLDER}/{stem}.aiff"
    for taken in (current_rel, parked_rel, f"Library/{FOLDER}/{stem}.aiff"):
        if (paths.root / taken).exists():
            raise ValueError(f"{taken} already exists. Remove the earlier test first.")

    state = library.load_state(paths.state_file)
    original = _source_entry(state, rel)
    artist, _, title = src.stem.partition(" - ")
    artist, title = original.get("artist", artist), original.get("title", title or src.stem) + SUFFIX
    work = paths.tmp / "upgrade-test"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir(parents=True)
    try:
        current = _make_lossy(src, work)
        cutoff = quality.analyze(current, lossy=True)
        _retitle(current, title, LOSSY_COMMENT.format(khz=(cutoff or 16000) / 1000))
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


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Make a test upgrade from one lossless AIFF in Library/.")
    p.add_argument("source", help="a lossless AIFF in Library/, e.g. \"Library/Hard_Bounce/Artist - Title.aiff\"")
    p.add_argument("--root", type=Path, default=None, help="the music folder (default: the one Discjockey uses)")
    args = p.parse_args(argv)
    resolved = library.resolve_paths()
    paths = Paths(args.root, support=resolved.support) if args.root else resolved.paths
    if paths is None:
        print("No music folder: choose one in Discjockey's Setup first, or pass --root.")
        return 2
    try:
        with library.run_lock(paths.lock):
            make(paths, args.source, datetime.now())
    except LockHeld:
        print("Another Discjockey run is still going. Wait until it has finished.")
        return 3
    except (ValueError, NoLibrary) as e:
        print(e)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
