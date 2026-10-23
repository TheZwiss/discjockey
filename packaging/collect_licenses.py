"""The licences folder Discjockey.app carries (spec public-release §6.5): the hand-kept texts in packaging/licenses
(ffmpeg's GPL notice with where its source is published and how it is built; deno's MIT licence; the GPL-3.0
text), Python's licence,
and the licence files of every Python distribution with files in the app. "In the app" comes from what PyInstaller
collected, not from the build venv: streamrip declares pytest-asyncio and pytest-mock as runtime dependencies, so the
venv holds pytest, which the app doesn't. packaging/discjockey.spec writes the source path of every file it collected
(toc_sources) to a list and runs this with the build venv's Python, where each file maps to the distribution whose
RECORD names it (bundled): code, data and binaries alike.

    dist/build/venv/bin/python packaging/collect_licenses.py --out dist/licenses --bundled dist/bundled-sources.txt

Fails when a bundled distribution has neither a licence file nor licence metadata."""
from __future__ import annotations

import argparse
import importlib.metadata as md
import json
import re
import shutil
import sys
import tomllib
from collections.abc import Callable, Iterable
from pathlib import Path

HERE = Path(__file__).resolve().parent
HAND_KEPT = HERE / "licenses"
PINS = HERE / "tools.json"
PACKAGE_JSON = HERE.parent / "hub-ui" / "package.json"
PYPROJECT = HERE.parent / "pyproject.toml"
SOURCE_URL = "https://github.com/TheZwiss/discjockey"
LICENCE_FILE = re.compile(r"(licen[cs]e|copying|notice|authors)", re.I)


def canonical(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def hand_kept_label(stem: str) -> str:
    """The INDEX line for a hand-kept text: what it covers, the version bundled, the licence. Versions come from the
    pins and from hub-ui/package.json, so they cannot drift from what is built."""
    pins = json.loads(PINS.read_text(encoding="utf-8"))
    ui = json.loads(PACKAGE_JSON.read_text(encoding="utf-8")).get("devDependencies", {})
    labels = {
        "ffmpeg": f"ffmpeg {pins['ffmpeg']['version']} and ffprobe {pins['ffmpeg']['version']}: GPL-3.0-or-later, "
                  "built from FFmpeg's source release without external libraries (source: ffmpeg.txt)",
        "deno": f"deno {pins['deno']['version']}: MIT",
        "svelte": f"svelte {ui['svelte']} (in the user interface): MIT",
        "vite": f"vite {ui['vite']} (preload helper in the user interface): MIT",
        "GPL-3.0": "GNU General Public License 3.0, full text (Discjockey's own licence, and the one of the ffmpeg build)",
    }
    return labels.get(stem, stem)


def own_version() -> str:
    """Discjockey's version, from pyproject.toml (the one other place that repeats discjockey.__version__)."""
    return tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))["project"]["version"]


def own_source_note(version: str) -> str:
    """The INDEX paragraph about Discjockey's own licence and where its source is: GPL-3.0 §6 needs the corresponding
    source offered with the binary. The tag of a release is v<version>."""
    return (f"Discjockey {version}: GPL-3.0-only (GPL-3.0.txt). Its source code is at {SOURCE_URL}; "
            f"the source of this version is the tag v{version}.")


def toc_sources(*tocs: Iterable[tuple]) -> list[Path]:
    """The source file of every entry in PyInstaller TOCs (dest_name, src_name, typecode), in order. Entries without a
    file on disk (namespace packages "-", built-in modules None) and relative names are skipped."""
    sources = []
    for toc in tocs:
        for entry in toc:
            src = entry[1]
            if src and src != "-" and Path(src).is_absolute():
                sources.append(Path(src))
    return sources


def bundled(dists: Iterable[md.Distribution], sources: Iterable[Path]) -> list[md.Distribution]:
    """The distributions owning at least one of `sources` (by their RECORD), sorted by name. A file in a .dist-info
    folder doesn't count: copied metadata alone ships none of the distribution's work."""
    owner: dict[Path, md.Distribution] = {}
    for dist in dists:
        for f in dist.files or []:
            if f.parts and not f.parts[0].endswith(".dist-info"):
                owner.setdefault(Path(dist.locate_file(f)).resolve(), dist)
    found = {}
    for src in sources:
        dist = owner.get(Path(src).resolve())
        if dist is not None and dist.metadata.get("Name"):
            found.setdefault(canonical(dist.metadata["Name"]), dist)
    return [found[name] for name in sorted(found)]


def licence_files(dist: md.Distribution) -> list[Path]:
    return [Path(dist.locate_file(f)) for f in dist.files or []
            if f.parts and f.parts[0].endswith(".dist-info") and LICENCE_FILE.search(f.name)]


def licence_metadata(dist: md.Distribution) -> str | None:
    meta = dist.metadata
    if meta.get("License-Expression"):
        return meta["License-Expression"].strip()
    short = (meta.get("License") or "").strip()
    if short and len(short) < 200 and "\n" not in short:
        return short
    classifiers = [c.split(" :: ")[-1] for c in meta.get_all("Classifier") or [] if c.startswith("License ::")]
    return ", ".join(classifiers) or (short[:200] if short else None)


def python_licence() -> Path:
    v = sys.version_info
    return Path(sys.base_prefix) / "lib" / f"python{v.major}.{v.minor}" / "LICENSE.txt"


HEADER = "Discjockey bundles these components. Their licences are in this folder."


def _previous_output(out: Path) -> bool:
    """True when `out` holds an INDEX.txt that this script wrote (its first line is HEADER)."""
    try:
        return (out / "INDEX.txt").read_text(encoding="utf-8").splitlines()[:1] == [HEADER]
    except (OSError, UnicodeDecodeError):
        return False


def collect(out: Path, dists: Iterable[md.Distribution], hand_kept: Path = HAND_KEPT,
            python_licence_file: Path | None = None, version: str | None = None) -> list[str]:
    """Writes out/<hand-kept files and folders>, out/python/…, out/INDEX.txt (replacing `out` when it is a previous
    output). The INDEX names Discjockey's version and the public source (own_source_note).
    Returns the problems. Refuses (and changes nothing) when `out` exists and is neither empty nor a previous output
    (one whose INDEX.txt this script wrote): a typo like `--out .` must not delete a folder."""
    python_licence_file = python_licence_file or python_licence()
    version = version or own_version()
    if out.exists():
        if not out.is_dir() or (any(out.iterdir()) and not _previous_output(out)):
            return [f"refusing to replace {out}: it is not empty and not a previous licences folder (no INDEX.txt of ours)"]
        shutil.rmtree(out)
    (out / "python").mkdir(parents=True)
    problems, index = [], []
    for f in sorted(hand_kept.iterdir()):
        if f.is_file():
            shutil.copy2(f, out / f.name)
            index.append(f"{hand_kept_label(f.stem)} -> {f.name}")
        elif f.is_dir():
            shutil.copytree(f, out / f.name)
            index.append(f"{f.name} -> {f.name}/")
    python_version = sys.version.split()[0]
    if python_licence_file.is_file():
        (out / "python" / f"Python-{python_version}").mkdir()
        shutil.copy2(python_licence_file, out / "python" / f"Python-{python_version}" / "LICENSE.txt")
        index.append(f"Python {python_version}: PSF-2.0")
    else:
        problems.append(f"Python's licence is not at {python_licence_file}")
    seen: set[str] = set()
    named = []
    for dist in dists:
        if dist.metadata.get("Name"):
            named.append(dist)
        else:
            problems.append(f"a distribution at {getattr(dist, "_path", "unknown location")} has no Name in its metadata")
    for dist in sorted(named, key=lambda d: canonical(d.metadata["Name"])):
        name = canonical(dist.metadata["Name"])
        if name in seen:
            continue
        seen.add(name)
        files, meta = licence_files(dist), licence_metadata(dist)
        if not files and not meta:
            problems.append(f"{name} {dist.version}: no licence file and no licence metadata")
            continue
        dest = out / "python" / f"{name}-{dist.version}"
        dest.mkdir()
        for f in files:
            target, n = dest / f.name, 1
            while target.exists():  # same-named files from different folders must not overwrite each other
                n += 1
                target = dest / f"{f.stem}-{n}{f.suffix}"
            shutil.copy2(f, target)
        if not files:
            (dest / "LICENSE-METADATA.txt").write_text(f"{name} {dist.version}: {meta}\n")
        index.append(f"{name} {dist.version}: {meta or 'see its folder'}")
    (out / "INDEX.txt").write_text(HEADER + "\n\n" + own_source_note(version) + "\n\n" + "\n".join(index) + "\n")
    return problems


def main(argv: list[str] | None = None,
         distributions: Callable[[], Iterable[md.Distribution]] = md.distributions) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--bundled", type=Path, required=True,
                   help="a file with the source path of every file PyInstaller collected, one per line")
    a = p.parse_args(argv)
    try:
        sources = [Path(line) for line in a.bundled.read_text(encoding="utf-8").splitlines() if line.strip()]
    except OSError as e:
        print(f"collect_licenses: can't read {a.bundled}: {e}", file=sys.stderr)
        return 1
    problems = collect(a.out, bundled(distributions(), sources))
    for line in problems:
        print(f"collect_licenses: {line}", file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
