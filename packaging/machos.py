"""The Mach-O files in an app bundle and their minimum macOS (spec public-release §6.3, §6.6). sign_app.py signs
these files; `minos` fails the build when one needs a newer macOS than LSMinimumSystemVersion.

usage: python packaging/machos.py minos <Discjockey.app> [--max 12.0]"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

MAX_MINOS = "12.0"  # = app_info.MIN_MACOS (a test compares them)
THIN = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xfe\xed\xfa\xce"}
FAT = {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}
BLOCK = re.compile(r"^Load command \d+$", re.M)
CMD = re.compile(r"^\s*cmd (\S+)", re.M)
FIELD = {"LC_BUILD_VERSION": re.compile(r"^\s*minos (\d+(?:\.\d+)*)\s*$", re.M),
         "LC_VERSION_MIN_MACOSX": re.compile(r"^\s*version (\d+(?:\.\d+)*)\s*$", re.M)}


def is_macho(path: Path) -> bool:
    with path.open("rb") as f:  # an unreadable file raises: it must not silently escape signing and the minos check
        head = f.read(8)
    if head[:4] in THIN:
        return True
    # universal binaries; Java class files share 0xcafebabe but carry a class version (> 40) where fat has a count
    return head[:4] in FAT and 0 < int.from_bytes(head[4:8], "big") < 20


def macho_files(app: Path) -> list[Path]:
    """Every Mach-O file in the bundle that is not a symlink (os.walk doesn't follow symlinked folders)."""
    found = []
    for folder, _, names in os.walk(app):
        for name in names:
            p = Path(folder) / name
            if not p.is_symlink() and is_macho(p):
                found.append(p)
    return sorted(found)


def minos(path: Path, run=subprocess.run) -> list[str]:
    """The minimum macOS of each architecture in `path`, from `vtool -show-build`. Only LC_BUILD_VERSION's `minos`
    and LC_VERSION_MIN_MACOSX's `version` count: the `version` under `tool LD` is the linker's."""
    out = run(["vtool", "-show-build", str(path)], capture_output=True, text=True).stdout
    found = []
    for block in BLOCK.split(out)[1:]:
        cmd = CMD.search(block)
        pattern = FIELD.get(cmd.group(1)) if cmd else None
        match = pattern.search(block) if pattern else None
        if match:
            found.append(match.group(1))
    return found


def key(version: str) -> tuple[int, ...]:
    return tuple(int(x) for x in version.split("."))


def too_new(app: Path, maximum: str = MAX_MINOS, run=subprocess.run) -> list[str]:
    problems = []
    for path in macho_files(app):
        found = minos(path, run)
        rel = path.relative_to(app).as_posix()
        if not found:
            problems.append(f"{rel}: no minimum macOS found")
        elif key(max(found, key=key)) > key(maximum):
            problems.append(f"{rel}: needs macOS {max(found, key=key)}")
    return problems


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = p.add_subparsers(dest="command", required=True)
    m = sub.add_parser("minos")
    m.add_argument("app", type=Path)
    m.add_argument("--max", default=MAX_MINOS)
    a = p.parse_args(argv)
    try:
        problems = too_new(a.app, a.max)
    except OSError as e:  # unreadable file, or vtool (Xcode command line tools) missing
        print(f"minos: {e}", file=sys.stderr)
        return 1
    for line in problems:
        print(f"minos: {line}", file=sys.stderr)
    if not problems:
        print(f"  every Mach-O file runs on macOS {a.max}")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
