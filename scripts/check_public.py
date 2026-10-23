"""Finds personal data in a tree before it goes public (spec public-release, phase 6). Run it through
scripts/check_public.sh. Stdlib only.

Rules (all generic: personal words come from a denylist outside the tree, never from this file):
- home-path  a real person's /Users/<name> path (placeholders like /Users/you are fine)
- email      an e-mail address outside the allowed domains (text files only)
- repo-url   a repo of the private GitHub account other than the public one
- denylist   a word from the denylist file; the output names the entry's number, never the word

Paths are scanned too (a finding on a path reports line 0). A symlink is scanned as its target text and never
followed. A file that cannot be read (or a tracked file missing on disk) is an error: exit 2, not "clean".
Binary files (a NUL byte in the first 8 KB) get every rule except `email`, which random compressed bytes would
trigger; a non-ASCII denylist entry is matched there as its UTF-8 bytes.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

DEFAULT_DENYLIST = "~/.discjockey-public-denylist"
DENYLIST_ENV = "DISCJOCKEY_PUBLIC_DENYLIST"
EXCLUDED_PREFIX = "docs/archive/pre-public/"  # repo mode only; --dir proves the exclusion happened by not skipping it

HOME_PATH = re.compile(r"/Users/([A-Za-z0-9._-]+)")
HOME_ALLOWED = {"you", "dj", "someone", "x", "Shared"}

EMAIL = re.compile(r"([A-Za-z0-9._%+-]+)@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)")
EMAIL_OK_DOMAINS = ("example.com", "example.org", "example.net", "users.noreply.github.com")
EMAIL_OK_ADDRESSES = {
    "git@github.com",  # the SSH clone user, not a person
}
EMAIL_OK_TLDS = {"invalid", "test", "example"}
IMAGE_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "svg", "webp"}

REPO_URL = re.compile(r"TheZwiss/([A-Za-z0-9._-]+)", re.IGNORECASE)
PUBLIC_REPO = "discjockey"


@dataclass(frozen=True)
class Finding:
    path: str
    line: int
    rule: str
    shown: str


def load_denylist(path) -> list[str] | None:
    """The entries of the denylist file (comments and blank lines dropped), or None when the file is missing."""
    try:
        text = Path(path).expanduser().read_text(encoding="utf-8", errors="replace")
    except (FileNotFoundError, NotADirectoryError):
        return None
    entries = []
    for raw in text.splitlines():
        entry = raw.strip()
        if entry and not entry.startswith("#"):
            entries.append(entry)
    return entries


def _denylist_pattern(entry: str) -> re.Pattern:
    """Case-insensitive, with a word boundary at each end that is a word character."""
    start = r"(?<!\w)" if re.match(r"\w", entry) else ""
    end = r"(?!\w)" if re.search(r"\w$", entry) else ""
    return re.compile(start + re.escape(entry) + end, re.IGNORECASE)


def _email_allowed(local: str, domain: str) -> bool:
    if f"{local}@{domain}".lower() in EMAIL_OK_ADDRESSES:
        return True
    domain = domain.lower()
    labels = domain.split(".")
    tld = labels[-1]
    if not tld.isalpha() or len(tld) < 2:  # `pkg@1.2.3`, `name@v1.2`: a version, not an address
        return True
    if tld in IMAGE_EXTENSIONS:  # `shot@1280.png`: a file name
        return True
    if tld in EMAIL_OK_TLDS:
        return True
    return any(domain == ok or domain.endswith("." + ok) for ok in EMAIL_OK_DOMAINS)


def _scan_line(text: str, check_email: bool) -> list[tuple[str, str]]:
    """(rule, shown) for the generic rules on one line."""
    found = []
    for m in HOME_PATH.finditer(text):
        name = m.group(1).rstrip(".-")  # `/Users/you.` at the end of a sentence
        if name and name not in HOME_ALLOWED:
            found.append(("home-path", "/Users/" + name))
    if check_email:
        for m in EMAIL.finditer(text):
            if not _email_allowed(m.group(1), m.group(2)):
                found.append(("email", m.group(0)))
    for m in REPO_URL.finditer(text):
        repo = m.group(1).rstrip(".")
        repo = repo[:-4] if repo.lower().endswith(".git") else repo
        if repo.lower() != PUBLIC_REPO:
            found.append(("repo-url", m.group(0)))
    return found


def scan(files: Iterable[tuple[str, bytes]], denylist: list[str]) -> list[Finding]:
    patterns = [(i, _denylist_pattern(entry)) for i, entry in enumerate(denylist, 1)]
    # binary files are decoded latin-1, so a non-ASCII entry is matched as its UTF-8 bytes read the same way
    binary_patterns = [(i, _denylist_pattern(entry.encode("utf-8").decode("latin-1")))
                       for i, entry in enumerate(denylist, 1) if not entry.isascii()]

    def scan_text(path: str, lineno: int, text: str, binary: bool, out: list[Finding]) -> None:
        for rule, shown in _scan_line(text, not binary):
            out.append(Finding(path, lineno, rule, shown))
        hits = patterns + (binary_patterns if binary else [])
        for number in sorted({n for n, pattern in hits if pattern.search(text)}):
            out.append(Finding(path, lineno, "denylist", f"denylist entry {number}"))

    findings: list[Finding] = []
    for path, data in files:
        scan_text(path, 0, path, False, findings)
        binary = b"\0" in data[:8192]
        text = data.decode("latin-1") if binary else data.decode("utf-8", errors="replace")
        for lineno, line in enumerate(text.split("\n"), 1):
            scan_text(path, lineno, line, binary, findings)
    return findings


def _read(full: Path, rel: str, errors: list[str]) -> bytes | None:
    """The file's bytes; a symlink gives its target text and is never followed. None (and an error line) when
    it cannot be read."""
    try:
        if full.is_symlink():
            return os.fsencode(os.readlink(full))
        return full.read_bytes()
    except OSError as e:
        errors.append(f"{rel}: cannot read: {e.strerror or type(e).__name__}")
        return None


def _repo_files(root: Path, errors: list[str]) -> list[tuple[str, bytes]]:
    listing = subprocess.run(["git", "ls-files", "-z"], cwd=root, check=True, capture_output=True).stdout
    files = []
    for raw in listing.split(b"\0"):
        if not raw:
            continue
        rel = os.fsdecode(raw)
        if rel.startswith(EXCLUDED_PREFIX):
            continue
        full = root / rel
        if not os.path.lexists(full):
            errors.append(f"{rel}: tracked file is missing on disk")
        elif full.is_dir() and not full.is_symlink():  # a submodule: only its path is scanned
            files.append((rel, b""))
        else:
            data = _read(full, rel, errors)
            if data is not None:
                files.append((rel, data))
    return files


def _dir_files(directory: Path, errors: list[str]) -> list[tuple[str, bytes]]:
    files = []
    def unreadable(error: OSError) -> None:  # os.walk skips a folder it cannot list unless told
        errors.append(f"{Path(error.filename).relative_to(directory).as_posix()}: cannot read the folder")

    # followlinks is off: a linked folder is not entered
    for folder, names, filenames in os.walk(directory, onerror=unreadable):
        names.sort()
        linked_folders = [n for n in names if (Path(folder) / n).is_symlink()]
        for name in sorted(filenames + linked_folders):
            full = Path(folder) / name
            rel = full.relative_to(directory).as_posix()
            if full.is_symlink() or full.is_file():
                data = _read(full, rel, errors)
                if data is not None:
                    files.append((rel, data))
    return files


def main(argv: list[str], repo_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(prog="check_public.sh", description="Finds personal data in the tree.")
    parser.add_argument("--dir", help="scan every regular file under DIR instead of the tracked files")
    parser.add_argument("--require-denylist", action="store_true", help="exit 2 when the denylist file is missing")
    args = parser.parse_args(argv)  # a usage error exits 2

    denylist_path = os.environ.get(DENYLIST_ENV) or DEFAULT_DENYLIST
    try:
        denylist = load_denylist(denylist_path)
    except OSError:  # a folder, or a file nobody may read: not "no findings"
        print(f"denylist cannot be read: {denylist_path}", file=sys.stderr)
        return 2
    if denylist is None:
        if args.require_denylist:
            print(f"denylist not found: {denylist_path} (set {DENYLIST_ENV})", file=sys.stderr)
            return 2
        print(f"warning: denylist not found: {denylist_path} (set {DENYLIST_ENV}); personal words are not checked",
              file=sys.stderr)
    elif args.require_denylist and not denylist:  # a file of blanks and comments (or an empty secret) checks no word
        print(f"denylist has no entries: {denylist_path}", file=sys.stderr)
        return 2

    errors: list[str] = []
    if args.dir is not None:
        directory = Path(args.dir)
        if not directory.is_dir():
            print(f"not a folder: {args.dir}", file=sys.stderr)
            return 2
        files = _dir_files(directory, errors)
    else:
        root = repo_root or Path(__file__).resolve().parents[1]
        try:
            files = _repo_files(root, errors)
        except (subprocess.CalledProcessError, FileNotFoundError):
            print(f"cannot list the tracked files of {root} (is it a git repo?)", file=sys.stderr)
            return 2

    findings = scan(files, denylist or [])
    for f in findings:
        print(f"{f.path}:{f.line}: {f.rule}: {f.shown}")
    for error in errors:  # a file that could not be checked is not a clean file
        print(error, file=sys.stderr)
    if errors:
        what = "1 file or folder" if len(errors) == 1 else f"{len(errors)} files or folders"
        print(f"{what} could not be read; the check is incomplete", file=sys.stderr)
        return 2
    if findings:
        print(f"{len(findings)} findings")
        return 1
    loaded = f"loaded {len(denylist)} entries" if denylist is not None else "not found"
    print(f"public check: clean ({len(files)} files, denylist: {loaded})")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
