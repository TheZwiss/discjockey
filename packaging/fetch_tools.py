"""Puts ffmpeg, ffprobe and deno as pinned in packaging/tools.json (spec public-release §6.2) into <out>/bin.

Two kinds of pin:
- a download ("url", "sha256", "member"): deno's release zip. The download's SHA-256 must match, and the program is
  unpacked from the zip.
- a source build ("url", "sha256", "programs", "configure"): ffmpeg and ffprobe, built by packaging/build_ffmpeg.sh
  from FFmpeg's own source release (checked against its SHA-256) with exactly the "configure" arguments. Building
  from source keeps the ffmpeg in the app free of third-party libraries (packaging/licenses/ffmpeg.txt).

Good downloads are kept in the cache folder under their hash, and a build under a key made of the source's hash, the
configure arguments and the build script's own hash, so the next run neither fetches nor builds them again. Every
program must be an arm64 macOS program.

--fresh-build ignores a cached build and replaces it (downloads stay cached, they are re-hashed on every use): a
cached build can't be checked against any hash, so the release job, which signs what it ships, builds its own.

usage: python packaging/fetch_tools.py --out dist/tools [--cache dist/cache] [--fresh-build]"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
import zipfile
from collections.abc import Callable
from pathlib import Path

HERE = Path(__file__).resolve().parent
PINS = HERE / "tools.json"
BUILD_SCRIPT = HERE / "build_ffmpeg.sh"
MH_MAGIC_64 = b"\xcf\xfa\xed\xfe"
CPU_ARM64 = 0x0100000C


class FetchError(Exception):
    pass


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def curl(url: str, dest: Path) -> None:
    """curl, not urllib: the build venv's Python may have no CA certificates; macOS's curl has them."""
    subprocess.run(["curl", "-fsSL", "--retry", "3", "-o", str(dest), url], check=True)


def cached_download(name: str, pin: dict, suffix: str, cache: Path, download: Callable[[str, Path], None]) -> Path:
    """The pinned file in the cache (<sha256><suffix>), downloaded when it is missing or not the pinned bytes."""
    cache.mkdir(parents=True, exist_ok=True)
    archive = cache / f"{pin['sha256']}{suffix}"
    if not (archive.is_file() and sha256(archive) == pin["sha256"]):
        part = cache / f".{name}.part"
        part.unlink(missing_ok=True)
        download(pin["url"], part)
        got = sha256(part)
        if got != pin["sha256"]:
            part.unlink(missing_ok=True)
            raise FetchError(f"{name}: {pin['url']} has SHA-256 {got}, packaging/tools.json pins {pin['sha256']}")
        part.replace(archive)
    return archive


def is_arm64_program(data: bytes) -> bool:
    return data[:4] == MH_MAGIC_64 and int.from_bytes(data[4:8], "little") == CPU_ARM64


def install(name: str, data: bytes, out_bin: Path) -> Path:
    out_bin.mkdir(parents=True, exist_ok=True)
    target, partial = out_bin / name, out_bin / f".{name}.tmp"
    partial.write_bytes(data)
    partial.chmod(0o755)
    partial.replace(target)  # chmod first, then rename: the final path never holds a truncated or unexecutable file
    return target


def fetch_one(name: str, pin: dict, out_bin: Path, cache: Path, download: Callable[[str, Path], None] = curl) -> Path:
    archive = cached_download(name, pin, ".zip", cache, download)
    with zipfile.ZipFile(archive) as z:
        try:
            data = z.read(pin["member"])
        except KeyError:
            raise FetchError(f"{name}: {pin['member']} is not in {pin['url']}") from None
    if not is_arm64_program(data):
        raise FetchError(f"{name}: {pin['member']} in {pin['url']} is not an arm64 macOS program")
    return install(name, data, out_bin)


def run_build(source: Path, configure: list[str], out: Path) -> None:
    """packaging/build_ffmpeg.sh: the programs from `source` into `out` (a few minutes)."""
    subprocess.run(["sh", str(BUILD_SCRIPT), str(source.resolve()), str(out.resolve()), *configure], check=True)


def build_key(pin: dict, script: Path = BUILD_SCRIPT) -> str:
    """What a cached build depends on: the source, the configure arguments and the build script."""
    recipe = {"source": pin["sha256"], "configure": pin["configure"], "script": sha256(script)}
    return sha256_bytes(json.dumps(recipe, sort_keys=True).encode())


def build_problem(name: str, folder: Path, programs: list[str]) -> str | None:
    """Why `folder` doesn't hold a usable build (a program missing or not arm64), or None when it does."""
    for program in programs:
        path = folder / program
        if not path.is_file():
            return f"{name}: the build made no {program}"
        with path.open("rb") as f:
            if not is_arm64_program(f.read(8)):
                return f"{name}: the built {program} is not an arm64 macOS program"
    return None


def build_one(name: str, pin: dict, out_bin: Path, cache: Path, download: Callable[[str, Path], None] = curl,
              build: Callable[[Path, list[str], Path], None] = run_build,
              log: Callable[[str], None] = lambda line: None, fresh_build: bool = False) -> list[Path]:
    """A build enters the cache only once every program is there and arm64, so a bad build is never reused.
    fresh_build: a cached build is dropped and built again (the source download stays cached, it is hash-checked)."""
    built = cache / f"build-{name}-{build_key(pin)}"
    programs = pin["programs"]
    if fresh_build:
        shutil.rmtree(built, ignore_errors=True)
    if build_problem(name, built, programs):
        source = cached_download(name, pin, ".tar.xz", cache, download)
        log(f"  {name} {pin['version']}: building from source (a few minutes)")
        staging = cache / f".build-{name}.tmp"
        shutil.rmtree(staging, ignore_errors=True)
        try:
            build(source, pin["configure"], staging)
            problem = build_problem(name, staging, programs)
            if problem:
                raise FetchError(problem)
            shutil.rmtree(built, ignore_errors=True)
            staging.replace(built)
        finally:
            shutil.rmtree(staging, ignore_errors=True)
    return [install(program, (built / program).read_bytes(), out_bin) for program in programs]


def programs_of(pins: dict) -> list[str]:
    """Every program the pins put into bin/, in order."""
    return [program for name, pin in pins.items() for program in pin.get("programs", [name])]


def fetch_all(out: Path, cache: Path, pins_path: Path = PINS, download: Callable[[str, Path], None] = curl,
              build: Callable[[Path, list[str], Path], None] = run_build,
              log: Callable[[str], None] = lambda line: None, fresh_build: bool = False) -> list[Path]:
    """All programs go into a staging folder first; <out>/bin is replaced only when every one passed, so a failure
    leaves no partial bin/ (and an earlier complete bin/ stays as it was)."""
    pins = json.loads(pins_path.read_text(encoding="utf-8"))
    staging = out.parent / f".{out.name}.staging"
    shutil.rmtree(staging, ignore_errors=True)
    try:
        for name, pin in pins.items():
            if "configure" in pin:
                build_one(name, pin, staging / "bin", cache, download, build, log, fresh_build)
            else:
                fetch_one(name, pin, staging / "bin", cache, download)
        out.mkdir(parents=True, exist_ok=True)
        shutil.rmtree(out / "bin", ignore_errors=True)
        (staging / "bin").replace(out / "bin")
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return [out / "bin" / program for program in programs_of(pins)]


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--cache", type=Path)
    p.add_argument("--fresh-build", action="store_true",
                   help="build ffmpeg again even when the cache holds a build (the release job)")
    a = p.parse_args(argv)
    try:
        for path in fetch_all(a.out, a.cache or a.out.parent / "cache",
                               log=lambda line: print(line, flush=True), fresh_build=a.fresh_build):
            print(f"  {path.name}: ok")
    except (FetchError, subprocess.CalledProcessError) as e:
        print(f"fetch_tools: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
